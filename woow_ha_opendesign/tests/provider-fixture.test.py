import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('provider_fixture', Path(__file__).with_name('validate-omnigent-provider-fixture.py'))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProviderFixtureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ('.claude/.credentials.json', '.codex/auth.json', '.pi/agent/models.json', '.config/opencode/opencode.json'):
            self.write(name)

    def write(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
        path.chmod(0o600)
        return path

    def test_reviewed_provider_files_are_accepted(self):
        MODULE.validate(self.root)

    def test_legacy_omnigent_state_is_rejected(self):
        self.write('.omnigent/auth_tokens.json')
        with self.assertRaisesRegex(AssertionError, 'unexpected'):
            MODULE.validate(self.root)

    def test_symlink_cannot_import_outside_files(self):
        path = self.root / '.codex/auth.json'
        path.unlink()
        path.symlink_to('/etc/passwd')
        with self.assertRaisesRegex(AssertionError, 'symlinks'):
            MODULE.validate(self.root)

    def test_public_credential_is_rejected(self):
        (self.root / '.codex/auth.json').chmod(0o644)
        with self.assertRaisesRegex(AssertionError, 'private'):
            MODULE.validate(self.root)

    def test_missing_local_login_fails_before_container_creation(self):
        (self.root / '.codex/auth.json').unlink()
        with self.assertRaisesRegex(AssertionError, 'login files required'):
            MODULE.validate(self.root)


if __name__ == '__main__':
    unittest.main()
