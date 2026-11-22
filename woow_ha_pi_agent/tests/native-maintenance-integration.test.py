"""Offline HA source contract; no SDK import, image build or tenant access."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/omnigent-native-maintenance-patch"
MANIFEST_SHA256 = "1b5341f48184336fb5697f258340ec541f80abf3440765234a0d2aecc9d766f4"


class HAMaintenanceIntegrationTests(unittest.TestCase):
    def test_reviewed_bundle_bytes_are_unchanged(self):
        manifest = (PATCH / "SOURCE-BUNDLE-MANIFEST.json").read_bytes()
        self.assertEqual(hashlib.sha256(manifest).hexdigest(), MANIFEST_SHA256)
        files = json.loads(manifest)["files"]
        actual = {str(p.relative_to(PATCH)) for p in PATCH.rglob("*") if p.is_file()}
        self.assertEqual(actual, set(files) | {"SOURCE-BUNDLE-MANIFEST.json"})
        for name, expected in files.items():
            with self.subTest(name=name):
                data = (PATCH / name).read_bytes()
                self.assertEqual(len(data), expected["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected["sha256"])

    def test_sdk_pin_matches_captured_source_version(self):
        pin = json.loads((ROOT / "cli-runtime/versions.json").read_text())["omnigent"]["version"]
        lock = json.loads((PATCH / "source-lock.json").read_text())
        self.assertEqual(pin, lock["capturedCoreVersion"])
        self.assertRegex((ROOT / "cli-runtime/omnigent/requirements.in").read_text(),
                         rf"(?m)^omnigent=={re.escape(pin)}$")
        requirements = (ROOT / "cli-runtime/omnigent/requirements.lock").read_text()
        self.assertRegex(requirements, rf"(?m)^omnigent=={re.escape(pin)} \\\n+    --hash=sha256:[0-9a-f]{{64}} \\\n+    --hash=sha256:[0-9a-f]{{64}}$")

    def builder(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        return dockerfile.split("AS omnigent-builder\n", 1)[1].split("\nFROM ", 1)[0]

    def test_strict_patch_is_after_existing_patches_before_runtime_copy(self):
        stage = self.builder()
        marker = "COPY patches/omnigent-native-maintenance-patch/ /opt/patches/omnigent-native-maintenance-patch/"
        self.assertEqual(stage.count(marker), 1)
        self.assertLess(stage.index("omnigent-model-options-patch.py --site-packages"), stage.index(marker))
        step = stage.split(marker, 1)[1].split("\nCOPY ", 1)[0]
        self.assertIn('sysconfig.get_paths()["purelib"]', step)
        self.assertIn('importlib.metadata.version("omnigent")', step)
        self.assertIn('lock["capturedCoreVersion"]', step)
        self.assertIn('/tmp/pins/omnigent/version', step)
        self.assertEqual(step.count('"$PATCH/apply_maintenance_patch.py" --site-packages "$SP" --strict'), 2)
        self.assertIn('--strict --check-only', step)
        self.assertNotRegex(step, r"\|\||;\s*true\b|set \+e")
        self.assertIn('COPY --from=omnigent-builder /opt/omnigent/venv /opt/omnigent/venv',
                      (ROOT / "Dockerfile").read_text())

    def test_installed_source_tests_are_nonroot_and_network_disabled(self):
        stage = self.builder()
        self.assertIn('python3-venv util-linux', stage)
        marker = 'COPY patches/omnigent-native-maintenance-patch/ /opt/patches/omnigent-native-maintenance-patch/'
        step = stage.split(marker, 1)[1].split("\nCOPY ", 1)[0]
        self.assertIn('RUN --network=none set -eu;', step)
        self.assertIn("-p 'test_build_patch.py'", step)
        self.assertIn('PI_NATIVE_MAINTENANCE_TEST_SOURCE="$SP/omnigent/native/native_bridge_common.py"', step)
        self.assertIn('setpriv --reuid=1000 --regid=1000 --clear-groups --', step)
        self.assertIn("-p 'test_maintenance_preservation.py'", step)
        self.assertIn('chmod a+r,go-w', step)

    def test_new_builder_run_has_valid_bash_syntax(self):
        stage = self.builder()
        marker = 'COPY patches/omnigent-native-maintenance-patch/ /opt/patches/omnigent-native-maintenance-patch/'
        step = stage.split(marker, 1)[1].split("\nCOPY ", 1)[0].strip()
        script = step.removeprefix('RUN --network=none ').replace('\\\n', '\n')
        result = subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
