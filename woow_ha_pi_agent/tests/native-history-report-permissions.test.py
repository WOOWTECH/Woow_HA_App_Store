"""Root hook writer / uid1000 Store reader on owned synthetic files only.

Run with sudo in the CI source job, or as root in the bounded fixture image.
Requiring root makes the UID boundary mandatory rather than a skipped claim.
No SDK imports, provider calls, image startup, or real addon data are used.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


HOOKS = Path(__file__).resolve().parents[1] / "upgrade-check"
READER = r'''
import errno,json,os,stat,sys
from pathlib import Path
assert os.geteuid() == os.getegid() == 1000 and os.getgroups() == []
report = Path(sys.argv[1])
record = json.loads(report.read_bytes())
assert set(record) == {"checks", "scope", "files", "homes", "seedManifestSha256"}
assert set(record["scope"]) == {"syntheticFilesOnly", "maintenanceExecuted", "fileSurvivalOnly", "productionAdmission"}
assert record["scope"] == dict(syntheticFilesOnly=True, maintenanceExecuted=False, fileSurvivalOnly=True, productionAdmission=False)
assert len(record["checks"]) == 1
check = record["checks"][0]
assert set(check) == {"name", "result", "detail"}
assert check["name"] == "bounded-synthetic-native-file-survival"
assert check["result"] == sys.argv[2]
assert check["detail"].startswith("native-fixture-v1:")
assert record["files"] == (9 if sys.argv[2] == "pass" else 0)
assert record["homes"] == (3 if sys.argv[2] == "pass" else 0)
for filename in sys.argv[3:]:
    try:
        Path(filename).read_bytes()
    except PermissionError as error:
        assert error.errno == errno.EACCES
    else:
        raise AssertionError("private seed state readable by Store reader")
info = report.stat()
assert info.st_uid == info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o644
print(json.dumps(dict(readerUid=os.geteuid(), readerGid=os.getegid(), writerUid=info.st_uid,
    reportMode=oct(stat.S_IMODE(info.st_mode)), result=check["result"], privateStateDenied=len(sys.argv[3:]))))
'''


class PublicReportPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.geteuid(), 0, "mandatory root writer / uid1000 reader fixture")
        self.temp = tempfile.TemporaryDirectory(prefix="ha-public-report-boundary-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.base.chmod(0o755)
        self.data = self.base / "data"
        self.state = self.base / "state"
        self.data.mkdir(mode=0o700)
        self.state.mkdir(mode=0o700)
        self.serial = 0

    def call(self, hook, success, **extra):
        self.serial += 1
        report = self.base / ("report-" + str(self.serial))
        report.mkdir(mode=0o755)
        report.chmod(0o755)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
               "DATA_DIR_DATA": str(self.data), "HOOK_STATE_DIR": str(self.state),
               "REPORT_DIR": str(report), "PHASE": "old" if hook == "seed" else "new",
               "ADDON_VERSION": "0.15.22" if hook == "seed" else "0.15.23",
               "ADDON_IMAGE": "owned-fixture:old" if hook == "seed" else "owned-fixture:new"}
        env.update(extra)
        result = subprocess.run([sys.executable, "-B", str(HOOKS / hook)], env=env,
                                text=True, capture_output=True, timeout=10, umask=0o077)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        private = [self.state / name for name in ("native-history-seed.json", "native-history-seed.sha256")]
        private = [path for path in private if path.exists()]
        for path in private:
            info = path.stat()
            self.assertEqual((stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid), (0o600, 0, 0))
        reader = subprocess.run([sys.executable, "-I", "-B", "-c", READER, str(report / (hook + ".json")),
                                 "pass" if success else "fail", *map(str, private)],
                                user=1000, group=1000, extra_groups=[], cwd="/tmp",
                                text=True, capture_output=True, timeout=10,
                                env={"PATH": os.environ.get("PATH", "")})
        self.assertEqual(reader.returncode, 0, "uid1000 report read failed: " + reader.stderr)
        readback = json.loads(reader.stdout)
        self.assertEqual(readback["readerUid"], 1000)
        self.assertEqual(readback["writerUid"], 0)
        self.assertEqual(readback["privateStateDenied"], len(private))
        return readback

    def test_seed_success_report_is_public_and_seed_state_stays_private(self):
        self.assertEqual(self.call("seed", True)["privateStateDenied"], 2)

    def test_seed_failure_report_is_public(self):
        self.call("seed", False, PHASE="new")
        self.assertEqual(list(self.state.iterdir()), [])

    def test_verify_success_report_is_public_and_seed_state_stays_private(self):
        self.call("seed", True)
        self.assertEqual(self.call("verify", True)["privateStateDenied"], 2)

    def test_verify_failure_report_is_public_and_seed_state_stays_private(self):
        self.call("seed", True)
        manifest = json.loads((self.state / "native-history-seed.json").read_bytes())
        native = self.data / "pi-agent/home/.omnigent/codex-native"
        missing = native / next(path for path in manifest["files"] if path.endswith("rollout-old.jsonl"))
        missing.unlink()
        self.assertEqual(self.call("verify", False)["privateStateDenied"], 2)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("root writer required; run this owned fixture with sudo")
    unittest.main(verbosity=2)
