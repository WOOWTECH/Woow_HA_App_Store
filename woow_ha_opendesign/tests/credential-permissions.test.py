"""The startup boundary repairs only known private provider files after restore."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('credential_permissions', ROOT / 'rootfs/usr/local/libexec/ha-opendesign-credentials.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

FILES = ('.codex/auth.json', '.codex/config.toml', '.claude/.credentials.json',
         '.claude/settings.json', '.pi/agent/auth.json', '.pi/agent/models.json',
         '.pi/agent/settings.json')
DIRS = ('.codex', '.claude', '.pi', '.pi/agent')


class CredentialPermissions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir(mode=0o750)

    def write(self, name, mode=0o644):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"fixture":"not-a-secret"}\n')
        path.chmod(mode)
        return path

    def test_restored_modes_are_private_without_changing_content_owners_or_unrelated_paths(self):
        private = [self.write(name) for name in FILES]
        unrelated = [self.write('.codex/unknown.json'), self.write('.claude/skills/tool.sh', 0o755),
                     self.write('projects/demo/.pi/agent/auth.json'), self.write('notes.txt')]
        for name in DIRS:
            (self.home / name).chmod(0o755)
        paths = private + unrelated + [self.home, self.home / 'projects']
        before = {p: (p.stat(), p.read_bytes() if p.is_file() else None) for p in paths}
        module.harden_credentials(self.home)
        for p in private:
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600, str(p))
        for name in DIRS:
            self.assertEqual(stat.S_IMODE((self.home / name).stat().st_mode), 0o700)
        for p, (old, content) in before.items():
            now = p.stat()
            self.assertEqual((now.st_uid, now.st_gid, now.st_ino, now.st_mtime_ns),
                             (old.st_uid, old.st_gid, old.st_ino, old.st_mtime_ns))
            if content is not None:
                self.assertEqual(p.read_bytes(), content)
            if p not in private:
                self.assertEqual(now.st_mode, old.st_mode)
        module.harden_credentials(self.home)  # idempotent

    def test_missing_providers_and_files_remain_absent(self):
        module.harden_credentials(self.home)
        self.assertEqual(list(self.home.iterdir()), [])
        (self.home / '.codex').mkdir()
        module.harden_credentials(self.home)
        self.assertEqual(list((self.home / '.codex').iterdir()), [])

    def test_credential_symlinks_are_refused_without_touching_the_target(self):
        outside = self.base / 'outside.json'
        outside.write_bytes(b'unchanged'); outside.chmod(0o644)
        (self.home / '.codex').mkdir()
        (self.home / '.codex/auth.json').symlink_to(outside)
        with self.assertRaises(OSError):
            module.harden_credentials(self.home)
        self.assertEqual(outside.read_bytes(), b'unchanged')
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o644)

    def test_provider_directory_symlinks_are_refused_at_every_depth(self):
        for name in ['.codex', '.claude', '.pi', '.pi/agent']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / 'home'; home.mkdir()
                outside = Path(tmp) / 'outside'; outside.mkdir(); outside.chmod(0o755)
                credential = outside / 'auth.json'; credential.write_bytes(b'unchanged')
                credential.chmod(0o644)
                link = home / name; link.parent.mkdir(exist_ok=True)
                link.symlink_to(outside, target_is_directory=True)
                with self.assertRaises(OSError):
                    module.harden_credentials(home)
                self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE(credential.stat().st_mode), 0o644)

    def test_home_and_ancestor_symlinks_are_refused(self):
        p = self.write('.codex/auth.json')
        link = self.base / 'alias'; link.symlink_to(self.home)
        with self.assertRaises(OSError):
            module.harden_credentials(link)
        ancestor = self.base / 'ancestor'; ancestor.symlink_to(self.base)
        with self.assertRaises(OSError):
            module.harden_credentials(ancestor / 'home')
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o644)

    def test_hardlinks_are_refused_without_changing_either_name(self):
        p = self.write('.codex/auth.json')
        outside = self.base / 'outside.json'; os.link(p, outside)
        with self.assertRaises(ValueError):
            module.harden_credentials(self.home)
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o644)
        self.assertEqual(outside.stat().st_nlink, 2)
        self.assertEqual(outside.read_bytes(), b'{"fixture":"not-a-secret"}\n')

    def test_fifo_and_directory_at_credential_path_are_refused(self):
        for kind in ['fifo', 'directory']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp); (home / '.codex').mkdir()
                p = home / '.codex/auth.json'
                if kind == 'fifo':
                    os.mkfifo(p, 0o644)
                else:
                    p.mkdir(mode=0o755)
                before = p.stat().st_mode
                with self.assertRaises(ValueError):
                    module.harden_credentials(home)
                self.assertEqual(p.stat().st_mode, before)

    def test_failure_message_contains_no_exception_or_secret(self):
        import contextlib
        import io
        stderr = io.StringIO()
        with patch.object(module, 'harden_credentials', side_effect=PermissionError('fake-secret')):
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(module.main(), 78)
        self.assertEqual(stderr.getvalue(), '[ha-opendesign] refused unsafe provider credential path or permissions\n')


if __name__ == '__main__':
    unittest.main()
