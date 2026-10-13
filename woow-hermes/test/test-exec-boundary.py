"""Real /bin/sh regression tests; only external commands/files are sandbox doubles.

--unpatched runs the same security assertions against the captured upstream source
and MUST fail. No real environment, credentials, s6 service or agent is used.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ADDON = Path(__file__).resolve().parent.parent
FIXTURES = ADDON / "test/fixtures/exec-boundary"
UNPATCHED = "--unpatched" in sys.argv
if UNPATCHED:
    sys.argv.remove("--unpatched")
HASHES = {
    "hermes-exec-shim.sh": "57637e73c8db76aa84a38e4a2edb1b155bfd86a2e89a8d4c38c4546ee1175985",
    "main-wrapper.sh": "d01d7ece5198f79496cf8ce64552665699995f0bf2cabbac78205b6b1779fb9b",
}
TOKENS = ("SUPERVISOR_TOKEN", "HASSIO_TOKEN")


def load_patch():
    spec = importlib.util.spec_from_file_location("boundary_patch", ADDON / "patches/ha-exec-boundary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# All executables are outside the shell-under-test. The s6 double models only
# argv/exec and environment handoff, NOT actual kernel UID/capability changes.
HELPER = r'''
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
with open(os.environ["EVENTS"], "a") as f:
    f.write(json.dumps({"name": name, "argv": sys.argv[1:], "env": dict(os.environ)}) + "\n")
if name == "with-contenv":
    for key in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN"):
        os.environ[key] = "sentinel-rehydrated-not-a-secret"
    os.environ["HERMES_HOME"] = os.environ["TEST_DATA"]
    os.execvp(sys.argv[1], sys.argv[1:])
if name == "s6-setuidgid":
    assert sys.argv[1] == "hermes"
    os.environ["TEST_UID"] = "10000"
    os.execvp(sys.argv[2], sys.argv[2:])
sys.exit(int(os.environ["TEST_EXIT"]))
'''


class ShellBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.data = self.root / "data"
        self.data.mkdir()
        self.venv = self.root / "hermes/.venv/bin"
        self.venv.mkdir(parents=True)
        (self.venv / "activate").write_text(":\n")
        for name in ("with-contenv", "s6-setuidgid", "hermes", "agent-probe"):
            target = self.bin / name
            target.write_text(f"#!{sys.executable}\n" + HELPER)
            target.chmod(0o755)
        shutil.copy2(self.bin / "hermes", self.venv / "hermes")
        (self.bin / "id").write_text('#!/bin/sh\nif [ "$2" = hermes ]; then echo 10000; else echo "$TEST_UID"; fi\n')
        (self.bin / "id").chmod(0o755)
        self.scripts = {}
        for name, digest in HASHES.items():
            source = (FIXTURES / name).read_text()
            self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), digest)
            if not UNPATCHED:
                source = load_patch().patched_source(name, source)
            # Relocate filesystem dependencies only; keep the entire real shell
            # control flow, conditions, quoting, exec and exit statements intact.
            source = source.replace("/opt/hermes", str(self.root / "hermes"))
            source = source.replace("/opt/data", str(self.data))
            source = source.replace("/command/", str(self.bin) + "/")
            target = self.root / name
            target.write_text(source)
            self.scripts[name] = target
            subprocess.run(["/bin/sh", "-n", str(target)], check=True)

    def run_shell(self, name, uid="0", args=(), optout="", reenter=False,
                  ready=False, tokens=True, code=37, missing=None):
        events_path = self.root / "events.jsonl"
        events_path.unlink(missing_ok=True)
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin", "HOME": "/root",
            "TEST_UID": uid, "TEST_DATA": str(self.data), "TEST_EXIT": str(code),
            "EVENTS": str(events_path), "OPENAI_API_KEY": "provider-sentinel",
            "CUSTOM_SETTING": "keep spaces; $literal", "HERMES_DOCKER_EXEC_AS_ROOT": optout,
        }
        if not reenter:
            env["HERMES_HOME"] = str(self.data)
        if ready:
            env["HERMES_MAIN_WRAPPER_ENV_READY"] = "1"
        if tokens:
            env.update({key: "sentinel-input-not-a-secret" for key in TOKENS})
        if missing:
            missing.unlink()
        result = subprocess.run(["/bin/sh", str(self.scripts[name]), *args], env=env,
                                cwd=self.root, capture_output=True, text=True, timeout=5)
        events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
        return result, events

    def assert_handoff(self, result, events, args, names, code=37, main=False):
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual([e["name"] for e in events], names)
        self.assertEqual(events[-1]["argv"], list(args))
        for event in events:
            for key in TOKENS:
                self.assertNotIn(key, event["env"], event["name"])
            self.assertEqual(event["env"]["OPENAI_API_KEY"], "provider-sentinel")
            self.assertEqual(event["env"]["CUSTOM_SETTING"], "keep spaces; $literal")
        if main:
            self.assertNotIn("HERMES_MAIN_WRAPPER_ENV_READY", events[-1]["env"])
        self.assertEqual(result.stdout, "")

    def test_shim_root_and_nonroot(self):
        args = ("chat", "", "two words", "*;$HOME", "--query=x")
        for uid in ("0", "10000", "12345"):
            with self.subTest(uid=uid):
                result, events = self.run_shell("hermes-exec-shim.sh", uid=uid, args=args)
                self.assert_handoff(result, events, args, ["s6-setuidgid", "hermes"] if uid == "0" else ["hermes"])
                self.assertEqual(events[-1]["env"]["HOME"], str(self.data) if uid == "0" else "/root")

    def test_shim_root_optout(self):
        for value in ("1", "true", "TRUE", "True", "yes", "YES", "Yes", "false", "0"):
            with self.subTest(value=value):
                result, events = self.run_shell("hermes-exec-shim.sh", optout=value)
                drop = value in ("false", "0")
                self.assert_handoff(result, events, (), ["s6-setuidgid", "hermes"] if drop else ["hermes"])
                self.assertEqual(events[-1]["env"]["HOME"], str(self.data) if drop else "/root")

    def test_shim_failures_preserved(self):
        result, events = self.run_shell("hermes-exec-shim.sh", missing=self.bin / "s6-setuidgid")
        self.assertEqual(result.returncode, 126)
        self.assertEqual(events, [])
        result, events = self.run_shell("hermes-exec-shim.sh", missing=self.venv / "hermes")
        self.assertEqual(result.returncode, 127)
        self.assertEqual(events, [])

    def test_main_routes_root_nonroot_and_reentry(self):
        for uid in ("0", "10000"):
            for reenter in (False, True):
                for args in ((), ("agent-probe", "", "two words", "*;$HOME"), ("chat", "--query", "a b")):
                    with self.subTest(uid=uid, reenter=reenter, args=args):
                        result, events = self.run_shell("main-wrapper.sh", uid=uid, args=args, reenter=reenter)
                        executable = bool(args and args[0] == "agent-probe")
                        names = (["with-contenv"] if reenter else []) + (["s6-setuidgid"] if uid == "0" else [])
                        self.assert_handoff(result, events, args[1:] if executable else args,
                                            names + ["agent-probe" if executable else "hermes"], main=True)
                        self.assertEqual(events[-1]["env"]["HOME"], str(self.data))

    def test_image_seed_with_environment_clearing_reentry(self):
        # Exercise the image runner's actual seed callsite against a helper ABI
        # that clears inherited variables (including the wrapper-ready marker).
        spec = importlib.util.spec_from_file_location('image_smoke', ADDON / 'test/test-exec-boundary-image.py')
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        envdir = self.root / 'container_environment'
        seed = smoke.seed_environment(f'{self.bin}:/usr/bin:/bin')
        exec(seed.replace("'/run/s6/container_environment'", repr(str(envdir))), {})
        for key, value in {
            'EVENTS': str(self.root / 'events.jsonl'), 'TEST_UID': '0',
            'TEST_DATA': str(self.data), 'TEST_EXIT': '42',
            'OPENAI_API_KEY': 'provider-sentinel',
            'CUSTOM_SETTING': 'keep spaces; $literal',
        }.items():
            (envdir / key).write_text(value)
        helper = self.bin / 'with-contenv'
        helper.write_text(f'#!{sys.executable}\n' +
                          'import os, sys\nfrom pathlib import Path\n' +
                          f'env = {{p.name: p.read_text() for p in Path({str(envdir)!r}).iterdir()}}\n' +
                          'os.environ.clear()\nos.environ.update(env)\n' +
                          'os.execvp(sys.argv[1], sys.argv[1:])\n')
        args = ('agent-probe', '', 'two words', '*;$HOME')
        result, events = self.run_shell('main-wrapper.sh', args=args, reenter=True, code=42)
        self.assert_handoff(result, events, args[1:], ['s6-setuidgid', 'agent-probe'], code=42, main=True)
        self.assertEqual(events[-1]['env']['BOUNDARY_KEEP'], 'synthetic-preserved')
        self.assertEqual(events[-1]['env']['HERMES_HOME'], '/opt/data')

    def test_main_reentry_guard(self):
        result, events = self.run_shell("main-wrapper.sh", reenter=True, ready=True)
        self.assert_handoff(result, events, (), ["s6-setuidgid", "hermes"], main=True)

    def test_main_without_with_contenv(self):
        result, events = self.run_shell("main-wrapper.sh", reenter=True, missing=self.bin / "with-contenv")
        self.assert_handoff(result, events, (), ["s6-setuidgid", "hermes"], main=True)

    def test_main_rejects_arbitrary_uid(self):
        result, events = self.run_shell("main-wrapper.sh", uid="12345")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(events, [])
        self.assertIn("not supported", result.stderr)

    def test_absent_tokens_and_exit_codes(self):
        for name in HASHES:
            for code in (0, 1, 42, 126, 127):
                with self.subTest(name=name, code=code):
                    result, events = self.run_shell(name, tokens=False, code=code)
                    self.assert_handoff(result, events, (), ["s6-setuidgid", "hermes"], code=code)


@unittest.skipIf(UNPATCHED, "red phase exercises original shell only")
class PatchContract(unittest.TestCase):
    def test_hashes_and_patch_validation(self):
        patch = load_patch()
        for name in HASHES:
            source = (FIXTURES / name).read_text()
            updated = patch.patched_source(name, source)
            patch.check_source(name, updated)
            self.assertEqual(patch.patched_source(name, updated), updated)
            subprocess.run(["/bin/sh", "-n"], input=updated, text=True, check=True)
            for bad in (source + "# drift\n", source.replace("set -e", "set -e\nset -e"),
                        source.replace("set -e", "set -u"), updated.replace("unset SUPERVISOR_TOKEN HASSIO_TOKEN", ":", 1)):
                with self.subTest(name=name, bad=bad[-40:]):
                    with self.assertRaises(ValueError):
                        patch.patched_source(name, bad)
            with self.assertRaises(ValueError):
                patch.check_source(name, source)

    def test_cli_preflight_and_reentry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in HASHES:
                shutil.copy2(FIXTURES / name, root / name)
            cmd = [sys.executable, str(ADDON / "patches/ha-exec-boundary.py"), "--directory", directory]
            second = root / "main-wrapper.sh"
            second.write_text(second.read_text() + "# drift\n")
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual((root / "hermes-exec-shim.sh").read_bytes(), (FIXTURES / "hermes-exec-shim.sh").read_bytes())
            shutil.copy2(FIXTURES / second.name, second)
            second.chmod(0o755)
            for args in ([], [], ["--check"]):
                subprocess.run(cmd + args, check=True, capture_output=True)
                self.assertEqual(second.stat().st_mode & 0o777, 0o755)

    def test_installed_copy_preflight_and_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "hermes-exec-shim.sh"
            wrapper = root / "main-wrapper.sh"
            installed = root / "installed-hermes"
            for name in HASHES:
                shutil.copy2(FIXTURES / name, root / name)
            shutil.copy2(source, installed)
            installed.chmod(0o751)
            before = installed.stat()
            cmd = [sys.executable, str(ADDON / "patches/ha-exec-boundary.py"),
                   "--directory", directory, "--installed-shim", str(installed)]
            original = installed.read_bytes()
            # Last-target drift must not partly patch either preceding source.
            installed.write_bytes(original + b"# drift\n")
            saved = {p: p.read_bytes() for p in (source, wrapper, installed)}
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual({p: p.read_bytes() for p in saved}, saved)
            installed.unlink()
            installed.symlink_to(source)
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(source.read_bytes(), original)
            installed.unlink()
            installed.write_bytes(original)
            installed.chmod(0o751)
            before = installed.stat()
            # Already-patched source with the as-yet-unpatched installed copy.
            subprocess.run(cmd[:-2], check=True, capture_output=True)
            subprocess.run(cmd, check=True, capture_output=True)
            patched = installed.read_bytes()
            self.assertEqual(patched, source.read_bytes())
            for args in ([], ["--check"]):
                subprocess.run(cmd + args, check=True, capture_output=True)
                after = installed.stat()
                self.assertEqual((after.st_ino, after.st_mode, after.st_uid, after.st_gid),
                                 (before.st_ino, before.st_mode, before.st_uid, before.st_gid))
                self.assertEqual(installed.read_bytes(), patched)
            # Original source + original copy in one pass, and source symlinks fail.
            for name in HASHES:
                (root / name).write_bytes((FIXTURES / name).read_bytes())
            installed.write_bytes(original)
            subprocess.run(cmd, check=True, capture_output=True)
            self.assertEqual(installed.read_bytes(), patched)
            source.unlink()
            source.symlink_to(installed)
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(installed.read_bytes(), patched)

    def test_build_and_bootstrap_contract(self):
        dockerfile = (ADDON / "Dockerfile").read_text()
        self.assertIn("python3 /tmp/woow-own-patches/ha-exec-boundary.py", dockerfile)
        self.assertIn("ha-exec-boundary.py --check", dockerfile)
        init = (ADDON / "rootfs/etc/cont-init.d/00-woow-options").read_text()
        self.assertLess(init.index("http://supervisor/network/info"), init.index('rm -f "$ENVDIR/SUPERVISOR_TOKEN"'))
        self.assertLess(init.index("http://supervisor/addons/self/options"), init.index('rm -f "$ENVDIR/SUPERVISOR_TOKEN"'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
