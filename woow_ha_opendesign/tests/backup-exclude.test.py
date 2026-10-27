"""Exercise the native Supervisor path matcher against a real backup tree.

Supervisor App._is_excluded_by_filter matches the full host path with
Path.match. A matched directory is pruned by securetar's recursive walk.
This is a filesystem contract fixture, not native HA restore acceptance.
"""
from pathlib import Path
import io
import inspect
import os
import tarfile
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path("opendesign/paseo/packages/runtime")


class BackupExclusion(unittest.TestCase):
    def test_native_filter_prunes_runtime_and_preserves_user_data(self):
        # Current and legacy Supervisor roots; match against native host paths,
        # while keeping all fixture I/O inside the temporary directory.
        for origin in ("/data/apps/data/fixture_woow_ha_opendesign",
                       "/data/addons/data/fixture_woow_ha_opendesign"):
            with self.subTest(origin=origin):
                self.check_roundtrip(Path(origin))

    def check_roundtrip(self, origin):
        config = yaml.safe_load((ROOT / "config.yaml").read_text())
        exclusions = config.get("backup_exclude", [])
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "addons/data/fixture_woow_ha_opendesign"
            preserved = [
                "options.json", "mcp/state.json", "opendesign/opendesign.db",
                "opendesign/projects/project/session.json",
                "opendesign/shared/workspaces/project/source.txt",
                "opendesign/home/.claude/.credentials.json",
                "opendesign/home/.codex/auth.json",
                "opendesign/home/.pi/agent/auth.json",
                "opendesign/home/.local/share/opendesign-paseo/current.json",
                "opendesign/paseo/bridge.json", "opendesign/paseo/state.json",
                "opendesign/paseo/daemon/config.json",
                "opendesign/paseo/daemon/sessions/conversation.json",
                "opendesign/paseo/packages/npm-cache/_cacache/content-v2/package",
                "opendesign/paseo/packages/providers/pi/node_modules/pi.js",
                "opendesign/paseo/packages/runtime-user-project/keep.txt",
                "opendesign/projects/demo/opendesign/paseo/packages/runtime/keep.txt",
                "opendesign/home/opendesign/paseo/packages/runtime/keep.txt",
                "opendesign/shared/workspaces/opendesign/paseo/packages/runtime/keep.txt",
            ]
            for name in preserved:
                file = data / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(("fixture:" + name).encode())
            executable = data / RUNTIME / "releases/pinned/node_modules/@esbuild/linux-x64/bin/esbuild"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"reconstructible package binary")
            os.link(executable, executable.parent / "hardlink")
            self.assertEqual(executable.stat().st_nlink, 2)
            archive = io.BytesIO()

            def native_filter(member):
                full_path = origin / Path(member.name).relative_to("data")
                return None if any(full_path.match(pattern) for pattern in exclusions) else member

            with tarfile.open(fileobj=archive, mode="w") as target:
                target.add(data, arcname="data", filter=native_filter)
            archive.seek(0)
            with tarfile.open(fileobj=archive, mode="r") as source:
                self.assertFalse(any(Path(member.name) == Path("data") / RUNTIME for member in source),
                                 "runtime package tree must be excluded")
            archive.seek(0)
            restored = Path(tmp) / "restore"
            with tarfile.open(fileobj=archive, mode="r|") as source:
                # Python 3.10 test hosts lack filters. Only this test's own
                # fixed, relative paths enter this disposable archive.
                options = {"filter": "data"} if "filter" in inspect.signature(source.extractall).parameters else {}
                source.extractall(restored, **options)
            self.assertFalse((restored / "data" / RUNTIME).exists(), "runtime package tree must be excluded")
            for name in preserved:
                self.assertTrue((restored / "data" / name).exists(), "user data excluded: " + name)
                self.assertEqual((restored / "data" / name).read_bytes(), (data / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
