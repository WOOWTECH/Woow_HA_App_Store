#!/usr/bin/env python3
"""Only reviewed provider files may seed the disposable connected smoke HOME."""
from pathlib import Path
import stat
import sys

ALLOWED = {
    '.claude.json', '.claude/.credentials.json', '.claude/settings.json',
    '.codex/auth.json', '.codex/config.toml',
    '.pi/agent/auth.json', '.pi/agent/models.json', '.pi/agent/settings.json',
    '.config/opencode/opencode.json', '.config/opencode/opencode.jsonc',
    '.local/share/opencode/auth.json',
}


def validate(root):
    root = Path(root)
    assert root.is_dir() and not root.is_symlink(), 'provider fixture must be a real directory'
    assert stat.S_IMODE(root.stat().st_mode) & 0o077 == 0, 'provider fixture directory must be private'
    found = set()
    directories = {str(parent) for name in ALLOWED for parent in Path(name).parents if str(parent) != '.'}
    for item in root.rglob('*'):
        metadata = item.lstat()
        relative = item.relative_to(root).as_posix()
        assert not stat.S_ISLNK(metadata.st_mode), 'provider fixture must not contain symlinks'
        if stat.S_ISDIR(metadata.st_mode):
            assert relative in directories, 'unexpected provider fixture directory'
            continue
        assert stat.S_ISREG(metadata.st_mode) and relative in ALLOWED, 'unexpected provider fixture file'
        assert metadata.st_mode & 0o077 == 0, 'provider fixture files must be private'
        assert 0 < metadata.st_size <= 1024 * 1024, 'provider fixture file size outside bounds'
        found.add(relative)
    assert '.claude/.credentials.json' in found and '.codex/auth.json' in found, 'Claude and Codex login files required'
    assert '.pi/agent/models.json' in found, 'Pi model configuration required'
    assert found & {'.config/opencode/opencode.json', '.config/opencode/opencode.jsonc'}, 'OpenCode model configuration required'


if __name__ == '__main__':
    try:
        validate(sys.argv[1])
    except (AssertionError, OSError, IndexError) as error:
        # No file contents, filenames supplied by the caller, or credential values.
        if isinstance(error, AssertionError):
            raise SystemExit(str(error)) from None
        raise SystemExit('provider fixture cannot be validated') from None
