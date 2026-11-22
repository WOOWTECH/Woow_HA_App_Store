"""Owned subprocess fixtures model hook phases, without images or SDK imports."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "upgrade-check"


class SyntheticUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ha-native-upgrade-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data = self.base / "data"
        self.state = self.base / "state"
        self.data.mkdir()
        self.state.mkdir()
        self.serial = 0

    def call(self, hook, *, success=True, report_expected=True, **extra):
        self.serial += 1
        report = self.base / f"report-{self.serial}"
        report.mkdir()
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
               "DATA_DIR_DATA": str(self.data), "HOOK_STATE_DIR": str(self.state),
               "REPORT_DIR": str(report), "PHASE": "old" if hook == "seed" else "new",
               "ADDON_VERSION": "0.15.22" if hook == "seed" else "0.15.23",
               "ADDON_IMAGE": "owned-fixture:old" if hook == "seed" else "owned-fixture:new"}
        env.update(extra)
        result = subprocess.run([sys.executable, "-B", str(HOOKS / hook)], env=env,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        record = report / f"{hook}.json"
        if report_expected and "REPORT_DIR" not in extra:
            self.assertTrue(record.is_file(), result.stdout + result.stderr)
            self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o644)
            parsed = json.loads(record.read_text())
            self.assertEqual(all(c["result"] == "pass" for c in parsed["checks"]), success)
            self.assertIs(parsed["scope"]["maintenanceExecuted"], False)
            self.assertIs(parsed["scope"]["syntheticFilesOnly"], True)
        return result

    def seed(self):
        self.call("seed")
        self.manifest = json.loads((self.state / "native-history-seed.json").read_text())
        self.native = self.data / "pi-agent/home/.omnigent/codex-native"
        return self.manifest

    def file(self, suffix):
        return self.native / next(name for name in self.manifest["files"] if name.endswith(suffix))

    def snapshot(self):
        result = {}
        for p in self.data.rglob("*"):
            s = p.lstat()
            result[str(p.relative_to(self.data))] = (s.st_mode, s.st_uid, s.st_gid,
                s.st_size, s.st_mtime_ns, s.st_ino,
                os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
        return result

    def rewrite_manifest(self, change):
        path = self.state / "native-history-seed.json"
        value = json.loads(path.read_text())
        change(value)
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        path.write_bytes(raw)
        (self.state / "native-history-seed.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")

    def test_old_to_new_shared_data_survival(self):
        self.seed()
        self.assertEqual(len(self.manifest["files"]), 9)
        before = self.snapshot()
        self.call("verify")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(list(self.native.iterdir())), 3)

    def test_missing_history_fails_and_is_not_reseeded(self):
        self.seed()
        missing = self.file("rollout-old.jsonl")
        missing.unlink()
        self.call("verify", success=False)
        self.assertFalse(missing.exists())

    def test_changed_bytes_fail(self):
        self.seed()
        self.file("rollout-old.jsonl").write_bytes(b"changed synthetic payload")
        self.call("verify", success=False)

    def test_mode_drift_fails(self):
        self.seed()
        self.file("config.toml").chmod(0o600)
        self.call("verify", success=False)

    def test_zero_byte_file_drift_fails(self):
        self.seed()
        self.file("rollout-empty.jsonl").write_bytes(b"x")
        self.call("verify", success=False)

    def test_missing_home_fails(self):
        self.seed()
        shutil.rmtree(self.file("dead_letter.jsonl.1").parent)
        self.call("verify", success=False)

    def test_leaf_link_fails_without_reading_or_changing_target(self):
        self.seed()
        outside = self.base / "outside"
        outside.write_bytes(b"unread synthetic outside file")
        before = outside.stat()
        target = self.file("config.toml")
        target.unlink()
        target.symlink_to(outside)
        self.call("verify", success=False)
        self.assertEqual(outside.stat().st_atime_ns, before.st_atime_ns)
        self.assertEqual(outside.read_bytes(), b"unread synthetic outside file")

    def test_directory_link_fails(self):
        self.seed()
        sessions = self.file("rollout-old.jsonl").parents[2]
        outside = self.base / "outside-dir"
        sessions.rename(outside)
        sessions.symlink_to(outside, target_is_directory=True)
        self.call("verify", success=False)

    def test_hardlink_fails(self):
        self.seed()
        os.link(self.file("config.toml"), self.base / "hardlink")
        self.call("verify", success=False)

    def test_native_ancestor_link_refuses_seed(self):
        home = self.data / "pi-agent/home"
        home.mkdir(parents=True)
        outside = self.base / "outside-dir"
        outside.mkdir()
        (home / ".omnigent").symlink_to(outside, target_is_directory=True)
        self.call("seed", success=False)
        self.assertEqual(list(outside.iterdir()), [])

    def test_noncanonical_data_scope_refuses_seed(self):
        self.call("seed", success=False, report_expected=False, DATA_DIR_DATA=str(self.data) + "/../data")
        self.assertEqual(list(self.data.iterdir()), [])

    def test_report_scope_overlap_cannot_write_fixture_data(self):
        self.call("seed", success=False, REPORT_DIR=str(self.data))
        self.assertEqual(list(self.data.iterdir()), [])

    def test_copied_data_directory_is_not_the_original_shared_mount(self):
        self.seed()
        other = self.base / "other-data"
        shutil.copytree(self.data, other)
        self.call("verify", success=False, DATA_DIR_DATA=str(other))

    def test_missing_state_fails_without_data_writes(self):
        self.call("verify", success=False)
        self.assertEqual(list(self.data.iterdir()), [])

    def test_repeated_seed_refuses_and_preserves_files(self):
        self.seed()
        before = self.snapshot()
        self.call("seed", success=False)
        self.assertEqual(self.snapshot(), before)

    def test_seal_drift_and_narrowed_resealed_scope_fail(self):
        self.seed()
        seal = self.state / "native-history-seed.sha256"
        original = seal.read_bytes()
        seal.write_text("0" * 64 + "\n")
        self.call("verify", success=False)
        seal.write_bytes(original)
        self.rewrite_manifest(lambda value: value["files"].pop(next(iter(value["files"]))))
        self.call("verify", success=False)

    def test_manifest_link_and_type_confusion_fail(self):
        self.seed()
        self.rewrite_manifest(lambda value: value.update(agedNs=True))
        self.call("verify", success=False)
        path = self.state / "native-history-seed.json"
        moved = self.base / "moved-manifest"
        path.rename(moved)
        path.symlink_to(moved)
        self.call("verify", success=False)

    def test_phase_and_image_labels_cannot_claim_same_version_upgrade(self):
        self.seed()
        self.call("verify", success=False, PHASE="old")
        self.call("verify", success=False, ADDON_VERSION="0.15.22")
        self.call("verify", success=False, ADDON_IMAGE="owned-fixture:old")

    def test_extra_and_oversized_fixture_files_fail(self):
        self.seed()
        target = self.file("config.toml")
        extra = target.parent / "unexpected"
        extra.write_bytes(b"unexpected synthetic file")
        self.call("verify", success=False)
        extra.unlink()
        target.write_bytes(b"x" * 4097)
        self.call("verify", success=False)

    def test_ci_wiring_executable_hooks_and_pure_imports(self):
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        for name in ["native-maintenance-integration.test.py", "native-history-upgrade.test.py"]:
            self.assertIn("python3 -B tests/" + name, workflow)
        for hook in ["seed", "verify"]:
            source = (HOOKS / hook).read_bytes()
            self.assertTrue(source.startswith(b"#!/usr/bin/env python3\n"))
            self.assertNotIn(b"\r", source)
            self.assertTrue((HOOKS / hook).stat().st_mode & stat.S_IXUSR)
        tree = ast.parse((HOOKS / "native_history_upgrade.py").read_text())
        imports = {n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else n.module.split(".")[0]
                   for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))}
        self.assertLessEqual(imports, {"contextlib", "hashlib", "json", "os", "pathlib", "re", "secrets", "stat", "sys", "time"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
