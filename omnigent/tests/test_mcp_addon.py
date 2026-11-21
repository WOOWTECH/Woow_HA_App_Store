"""Offline build and startup contracts. All hashes/tokens below are test fixtures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ADDON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON / "build"))
import mcp_artifact as artifact
sys.path.insert(0, str(ADDON / "upgrade-check"))
import omnigent_upgrade as hooks


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.wheel = self.root / "omnigent-0.21.0-py3-none-any.whl"
        self.ui = {"index.html": b"<head></head>", "assets/app.js":
                   b"__OMNIGENT_BASE_PATH__ /admin/mcp-server/profiles"}
        self.entries = {n: b"# fixture\n" for n in artifact.REQUIRED}
        self.entries.update({artifact.UI + n: v for n, v in self.ui.items()})
        self.entries[artifact.REQUIRED[0]] = b"omnigent_session_history OMNIGENT_MCP_PUBLIC_BASE_URL connection_url"
        self.entries["omnigent-0.21.0.dist-info/METADATA"] = b"Name: omnigent\nVersion: 0.21.0\n"
        self.write_wheel()
        self.receipt = {"schemaVersion": 1, "coreVersion": "0.21.0", "buildId": "mcp.1",
                        "sourceCommit": "a" * 40, "wheelSha256": self.sha(),
                        "uiSha256": artifact.ui_hash(self.ui),
                        "wheelImage": "ghcr.io/woowtech/omnigent-server-kubernetes@sha256:" + "b" * 64,
                        "wheelPath": "/opt/woow-artifact/omnigent-0.21.0-py3-none-any.whl"}

    def write_wheel(self):
        with zipfile.ZipFile(self.wheel, "w") as z:
            for name, content in self.entries.items():
                z.writestr(name, content)

    def sha(self):
        return hashlib.sha256(self.wheel.read_bytes()).hexdigest()

    def test_verified_wheel_and_receipt(self):
        receipt = self.root / "receipt.json"
        receipt.write_text(json.dumps(self.receipt))
        artifact.verify_wheel(self.wheel, artifact.read_receipt(receipt))

    def test_missing_receipt_pins_fail_closed(self):
        for field in ("sourceCommit", "wheelSha256", "uiSha256", "wheelImage"):
            with self.subTest(field=field):
                path = self.root / "receipt.json"
                path.write_text(json.dumps({**self.receipt, field: None}))
                with self.assertRaises(ValueError):
                    artifact.read_receipt(path)

    def test_mutated_wheel_rejected(self):
        self.wheel.write_bytes(self.wheel.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "wheel SHA"):
            artifact.verify_wheel(self.wheel, self.receipt)

    def test_ui_mismatch_rejected_even_with_matching_wheel_hash(self):
        self.entries[artifact.UI + "assets/app.js"] += b" changed"
        self.write_wheel()
        self.receipt["wheelSha256"] = self.sha()
        with self.assertRaisesRegex(ValueError, "UI SHA"):
            artifact.verify_wheel(self.wheel, self.receipt)

    def test_missing_mcp_migration_rejected(self):
        del self.entries[artifact.REQUIRED[3]]
        self.write_wheel()
        self.receipt["wheelSha256"] = self.sha()
        with self.assertRaisesRegex(ValueError, "missing MCP"):
            artifact.verify_wheel(self.wheel, self.receipt)

    def test_public_immutable_image_required(self):
        for image in ("ghcr.io/woowtech/omnigent-server-kubernetes:latest",
                      "ghcr.io/woowtech/omnigent-server:tag@sha256:" + "b" * 64,
                      "example.test/private@sha256:" + "b" * 64):
            with self.subTest(image=image):
                path = self.root / "receipt.json"
                path.write_text(json.dumps({**self.receipt, "wheelImage": image}))
                with self.assertRaises(ValueError):
                    artifact.read_receipt(path)

    def test_snapshot_artifact_rejected(self):
        (self.root / "WOOW_BUILD_RECEIPT.json").write_text(json.dumps({**self.receipt, "publishable": False}))
        with self.assertRaisesRegex(ValueError, "unpublished snapshot"):
            artifact.verify_artifact(self.root, self.receipt)

    def test_import_combined_candidate_pin(self):
        candidate = {**self.receipt, "publishable": True, "variant": "server-kubernetes",
                     "architecture": ["linux/amd64", "linux/arm64"], "runId": "123", "runAttempt": "1",
                     "platforms": [{"architecture": arch, "image": self.receipt["wheelImage"]}
                                   for arch in ("linux/amd64", "linux/arm64")]}
        source, target = self.root / "candidate.json", self.root / "pin.json"
        dockerfile = self.root / "Dockerfile"
        dockerfile.write_text("ARG OMNIGENT_WHEEL_IMAGE\nFROM ${OMNIGENT_WHEEL_IMAGE} AS wheel\nARG OMNIGENT_SOURCE_COMMIT\n")
        source.write_text(json.dumps(candidate))
        command = [sys.executable, str(ADDON / "build/mcp_artifact.py"), "pin", "--receipt", str(source), "--output", str(target), "--dockerfile", str(dockerfile)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(artifact.read_receipt(target)["wheelSha256"], self.receipt["wheelSha256"])
        self.assertEqual(json.loads(target.read_text())["runId"], "123")
        self.assertIn("ARG OMNIGENT_WHEEL_IMAGE=" + self.receipt["wheelImage"], dockerfile.read_text())
        self.assertIn("ARG OMNIGENT_SOURCE_COMMIT=" + self.receipt["sourceCommit"], dockerfile.read_text())
        candidate["architecture"] = ["linux/amd64"]
        source.write_text(json.dumps(candidate))
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_wrong_source_artifact_rejected(self):
        (self.root / "WOOW_BUILD_RECEIPT.json").write_text(json.dumps({**self.receipt, "publishable": True, "sourceCommit": "c" * 40}))
        with self.assertRaisesRegex(ValueError, "sourceCommit"):
            artifact.verify_artifact(self.root, self.receipt)


class HookTests(unittest.TestCase):
    def test_old_mcp_schema_can_be_seeded_but_new_requires_history(self):
        responses = [(200, {"result": {"protocolVersion": "2025-03-26"}}),
                     (200, {"result": {"tools": [{"name": name} for name in
                              ("omnigent_session_get", "omnigent_automation_list")]}})]
        with patch.object(hooks, "rpc", side_effect=responses):
            hooks.check_profile({}, active=True, require_history=False)
        with patch.object(hooks, "rpc", side_effect=responses):
            with self.assertRaisesRegex(AssertionError, "MCP tools missing"):
                hooks.check_profile({}, active=True)

    def test_revoked_token_must_be_denied(self):
        with patch.object(hooks, "rpc", return_value=(200, {"result": {}})):
            with self.assertRaisesRegex(AssertionError, "revoked token accepted"):
                hooks.check_profile({}, active=False)
        with patch.object(hooks, "rpc", return_value=(401, {})):
            hooks.check_profile({}, active=False)


class ConfigTests(unittest.TestCase):
    def render(self, options):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (ADDON / "rootfs/etc/s6-overlay/s6-rc.d/init-addon-config/run").read_text()
            for name, value in (("OPTIONS_FILE", root / "options.json"), ("CONFIG_ENV", root / "config.env"),
                                ("PG_VERSION_FILE", root / "PG_VERSION"), ("S6_ENV_DIR", root / "s6")):
                import re
                script = re.sub(rf"^{name}=.*$", f"{name}={value}", script, flags=re.M)
            script = script.split("# --- TZ / localtime")[0]
            script = script.replace("mkdir -p /data/omnigent-home /data/artifacts", ":")
            (root / "options.json").write_text(json.dumps({"admin_username": "fixture", "admin_password": "synthetic-password-12345", **options}))
            result = subprocess.run(["sh"], input=script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            exports = subprocess.run(["sh", "-c", '. "$1"; python3 -c \'import os,json; print(json.dumps({k:os.environ.get(k) for k in ["OMNIGENT_MCP_PUBLIC_BASE_URL","OMNIGENT_ACCOUNTS_BASE_URL"]}))\'', "sh", str(root / "config.env")], capture_output=True, text=True, check=True)
            return json.loads(exports.stdout), (root / "s6/OMNIGENT_MCP_PUBLIC_BASE_URL").read_text(), result.stderr

    def test_explicit_base_is_unchanged(self):
        url = "https://mcp.example.test/external"
        env, s6, logs = self.render({"base_url": "https://ui.example.test", "mcp_public_base_url": url})
        self.assertEqual(env["OMNIGENT_MCP_PUBLIC_BASE_URL"], url)
        self.assertEqual(env["OMNIGENT_ACCOUNTS_BASE_URL"], "https://ui.example.test")
        self.assertEqual(s6, url)
        self.assertNotIn(url, logs)

    def test_unset_option_exports_empty_for_core_fallback(self):
        env, s6, _ = self.render({})
        self.assertEqual(env["OMNIGENT_MCP_PUBLIC_BASE_URL"], "")
        self.assertEqual(s6, "")

    def test_env_vars_override_and_shell_quoting(self):
        value = "https://mcp.example.test/$(false)'quoted"
        env, s6, _ = self.render({"mcp_public_base_url": "https://old.example.test", "env_vars": [
            {"key": "OMNIGENT_MCP_PUBLIC_BASE_URL", "value": value}]})
        self.assertEqual(env["OMNIGENT_MCP_PUBLIC_BASE_URL"], value)
        self.assertEqual(s6, value)

    def test_versioned_assets_match_addon_version(self):
        import re
        version = re.search(r"^version: (.*)$", (ADDON / "config.yaml").read_text(), re.M)[1]
        aliases = set(re.findall(r"assets-v([0-9-]+)", (ADDON / "rootfs/etc/nginx/nginx.conf").read_text()))
        self.assertEqual(aliases, {version.replace(".", "-")})


if __name__ == "__main__":
    unittest.main()
