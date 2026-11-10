"""Real supervisor process test, supplied a read-only canonical kit source.

WOOW_TEST_KIT_SOURCE=/path/to/shared/omnigent-host python -m unittest ...
Uses only the kit's fake CLI/server with synthetic test credentials.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kit_entry", ROOT / "kit-entry.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
KIT = os.environ.get("WOOW_TEST_KIT_SOURCE")


class KitEnvironment(unittest.TestCase):
    def test_deployment_kit_forwards_pinned_claude_guard(self):
        with patch.dict(os.environ, {"OG_HOST_ENABLED": "0", "OG_PASSTHROUGH": "EXISTING_FLAG", "DISABLE_AUTOUPDATER": "0"}, clear=True), \
                patch.object(sys, "argv", ["kit-entry.py", "--", "product-entry"]), \
                patch.object(os, "execvpe") as execute:
            entry.main()
        env = execute.call_args.args[2]
        self.assertEqual(env["DISABLE_AUTOUPDATER"], "1")
        self.assertIn("DISABLE_AUTOUPDATER", env["OG_PASSTHROUGH"].split(","))
        self.assertIn("EXISTING_FLAG", env["OG_PASSTHROUGH"].split(","))


@unittest.skipUnless(KIT, "set WOOW_TEST_KIT_SOURCE to the canonical kit")
class KitLifecycle(unittest.TestCase):
    def test_overlay_accepts_readonly_configmap_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            projected = Path(temporary)
            revision = projected / "..revision"
            revision.mkdir()
            source = revision / "supervisor.sh"
            original = (Path(KIT) / "supervisor.sh").read_bytes()
            source.write_bytes(original)
            source.chmod(0o555)
            (revision / "helper.sh").write_text("#!/bin/sh\n")
            (revision / "helper.sh").chmod(0o555)
            (projected / "..data").symlink_to(revision, target_is_directory=True)
            (projected / "supervisor.sh").symlink_to("..data/supervisor.sh")
            (projected / "helper.sh").symlink_to("..data/helper.sh")
            stage = entry.prepare(projected)
            self.addCleanup(lambda: shutil.rmtree(stage, ignore_errors=True))
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(source.stat().st_mode & 0o777, 0o555)
            self.assertEqual(stage.stat().st_mode & 0o777, 0o700)
            self.assertTrue((stage / "supervisor.sh").stat().st_mode & 0o200)
            self.assertFalse((stage / "supervisor.sh").is_symlink())
            self.assertIn("WOOW_CONNECTOR_PAUSE_V1", (stage / "supervisor.sh").read_text())
            self.assertEqual((stage / "helper.sh").resolve(), revision / "helper.sh")
            entry.patcher.patch(stage / "supervisor.sh")  # Integrity receipt remains valid.

    def test_overlay_pauses_without_restarting_and_survives_supervisor_restart(self):
        import yaml
        original = Path(KIT)
        source_hash = hashlib.sha256((original / "supervisor.sh").read_bytes()).hexdigest()
        stage = entry.prepare(original)
        self.addCleanup(lambda: shutil.rmtree(stage, ignore_errors=True))
        self.assertEqual(hashlib.sha256((original / "supervisor.sh").read_bytes()).hexdigest(), source_hash)
        self.assertIn("WOOW_CONNECTOR_PAUSE_V1", (stage / "supervisor.sh").read_text())
        subprocess.run(["sh", "-n", str(stage / "supervisor.sh")], check=True)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name in ("home", "data", "workspace", "fake", "server"):
            (root / name).mkdir()
        server_dir = root / "server"
        (server_dir / "control.json").write_text('{"me":200,"token":200}')
        (server_dir / "requests.log").touch()
        server = subprocess.Popen([sys.executable, str(original / "tests/fake_server.py"),
                                   str(server_dir / "control.json"), str(server_dir / "port"), str(server_dir / "requests.log")],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: self.stop(server))
        self.wait_for(lambda: (server_dir / "port").exists())
        url = "http://127.0.0.1:" + (server_dir / "port").read_text().strip()
        tokens = {url: {"token": "SYNTHETIC_TEST_TOKEN", "user_id": "tester", "expires_at": time.time() + 3600}}
        (root / "data/auth_tokens.json").write_text(json.dumps(tokens))
        (root / "data/config.yaml").write_text(yaml.safe_dump({"server": url}))
        (root / "fake/ctl.json").write_text('{"mode":"run"}')
        env = {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin", "HOME": str(root / "home"),
               "LANG": "C.UTF-8", "OG_KIT_DIR": str(stage), "OG_HOST_ENABLED": "1",
               "OG_CONFIG_HOME": str(root / "data"), "OG_DATA_DIR": str(root / "data"),
               "OG_WORKSPACE": str(root / "workspace"), "OG_HOST_NAME": "connector-fixture", "OG_SERVER_URL": url,
               "OG_PYTHON": sys.executable, "OG_BIN": str(original / "tests/fake_omnigent"),
               "FAKE_OG_DIR": str(root / "fake"), "OG_IDLE_SECONDS": "1", "OG_TICK_SECONDS": "1",
               "OG_CONFIRM_SECONDS": "1", "OG_REPROBE_SECONDS": "2", "OG_WATCH_SECONDS": "2",
               "OG_STOP_GRACE_SECONDS": "1", "OG_TMUX_MIN": "", "OG_MEM_GUARD_PERCENT": "0"}
        log = open(root / "output.log", "wb")
        self.addCleanup(log.close)
        status_file = root / "data/omnigent-host/status.json"
        pause_file = status_file.parent / "connector-paused"
        starts_file = root / "fake/starts.log"
        def state():
            try:
                return json.loads(status_file.read_text()).get("state")
            except (OSError, ValueError):
                return None
        def starts():
            return len(starts_file.read_text().splitlines()) if starts_file.exists() else 0
        def launch():
            process = subprocess.Popen(["sh", str(stage / "supervisor.sh")], env=env, stdout=log, stderr=log)
            self.addCleanup(lambda: self.stop(process))
            return process
        first = launch()
        self.wait_for(lambda: state() == "running")
        self.assertEqual(starts(), 1)
        pause_file.write_text('{"paused":true}')
        self.wait_for(lambda: state() == "paused")
        time.sleep(2.1)
        self.assertEqual(starts(), 1, "watchdog must not restart a paused host")
        self.stop(first)
        second = launch()
        self.wait_for(lambda: state() == "paused")
        time.sleep(2.1)
        self.assertEqual(starts(), 1, "pause must persist across supervisor restart")
        pause_file.unlink()
        self.wait_for(lambda: starts() == 2 and state() == "running")
        self.stop(second)
        log.flush()
        self.assertNotIn("SYNTHETIC_TEST_TOKEN", (root / "output.log").read_text())

    @staticmethod
    def wait_for(callback, timeout=15):
        deadline = time.monotonic() + timeout
        while not callback():
            if time.monotonic() >= deadline:
                raise AssertionError("supervisor state transition timed out")
            time.sleep(.1)

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
