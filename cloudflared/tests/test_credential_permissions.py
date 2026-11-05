"""Synthetic-only credential permission RED/GREEN and fail-closed coverage."""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import runpy
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'rootfs'
GUARD = ROOT / 'usr/local/bin/cloudflared-credential-guard'
LOADER = importlib.machinery.SourceFileLoader('credential_guard', str(GUARD))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)


class CredentialPermissions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def credential(self, name='cert.pem', mode=0o644):
        f = self.root / name
        f.write_bytes(os.urandom(64))
        f.chmod(mode)
        return f

    def test_restored_files_red_then_green_without_content_change(self):
        files = [self.credential(n) for n in MODULE.NAMES]
        hashes = [hashlib.sha256(f.read_bytes()).digest() for f in files]
        self.assertTrue(all(stat.S_IMODE(f.stat().st_mode) == 0o644 for f in files))
        MODULE.protect(self.root)
        self.assertTrue(all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in files))
        self.assertEqual(hashes, [hashlib.sha256(f.read_bytes()).digest() for f in files])

    def test_other_data_is_untouched(self):
        f = self.credential('unrelated.bin')
        before = f.stat()
        MODULE.protect(self.root)
        after = f.stat()
        self.assertEqual((before.st_mode, before.st_uid, before.st_gid, before.st_mtime_ns),
                         (after.st_mode, after.st_uid, after.st_gid, after.st_mtime_ns))

    def test_missing_credentials_not_created(self):
        MODULE.protect(self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_private_file_idempotent(self):
        f = self.credential(mode=0o600)
        MODULE.protect(self.root)
        MODULE.protect(self.root)
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)

    def test_symlink_rejected_without_modifying_target(self):
        f = self.credential('target')
        (self.root / 'cert.pem').symlink_to(f)
        with self.assertRaises(OSError):
            MODULE.protect(self.root)
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o644)

    def test_hardlink_rejected_without_modifying_alias(self):
        f = self.credential('target')
        os.link(f, self.root / 'cert.pem')
        with self.assertRaises(ValueError):
            MODULE.protect(self.root)
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o644)

    def test_directory_rejected(self):
        (self.root / 'cert.pem').mkdir()
        with self.assertRaises(ValueError):
            MODULE.protect(self.root)

    def test_fifo_rejected_without_blocking(self):
        os.mkfifo(self.root / 'cert.pem')
        with self.assertRaises(ValueError):
            MODULE.protect(self.root)

    def test_symlink_data_directory_rejected(self):
        link = self.root / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            MODULE.protect(link)

    def test_failed_chmod_propagates(self):
        self.credential()
        with patch.object(MODULE.os, 'fchmod', side_effect=PermissionError()):
            with self.assertRaises(PermissionError):
                MODULE.protect(self.root)

    def test_cli_failure_has_only_static_message(self):
        output = io.StringIO()
        with patch('os.open', side_effect=PermissionError('SYNTHETIC_PRIVATE_MARKER')):
            with contextlib.redirect_stderr(output):
                with self.assertRaises(SystemExit) as result:
                    runpy.run_path(str(GUARD), run_name='__main__')
        self.assertEqual(result.exception.code, 1)
        self.assertEqual(output.getvalue(), 'Credential permission check failed\n')

    def test_all_startup_consumers_fail_closed_before_work(self):
        paths = ['run.sh', 'etc/s6-overlay/s6-rc.d/prepare/run.sh',
                 'etc/s6-overlay/s6-rc.d/webgui/run']
        for path in paths:
            result = subprocess.run(['bash', '-c',
                'cloudflared-credential-guard() { return 1; }; source "$1"; echo unsafe',
                'test', str(ROOT / path)], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout + result.stderr, b'')


if __name__ == '__main__':
    unittest.main()
