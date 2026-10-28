"""Restore private CLI file modes before any application process starts."""
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import stat
import sys

HOME = Path('/data/opendesign/home')
PRIVATE = {
    '.codex': ('auth.json', 'config.toml'),
    '.claude': ('.credentials.json', 'settings.json'),
    '.pi': (),
    '.pi/agent': ('auth.json', 'models.json', 'settings.json'),
    # Only OpenCode's private leaves: .config, .local and .local/share are
    # shared with other providers; traverse them without changing their modes.
    '.config/opencode': ('opencode.json', 'opencode.jsonc'),
    '.local/share/opencode': ('auth.json',),
}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@contextmanager
def directory(path, parent=None):
    # Walk every component using directory descriptors; O_NOFOLLOW on just the
    # final absolute pathname would still follow a replaced ancestor symlink.
    with ExitStack() as stack:
        if parent is None:
            path = Path(path)
            if not path.is_absolute():
                raise ValueError('absolute home required')
            parent = os.open('/', DIR_FLAGS)
            stack.callback(os.close, parent)
            parts = path.parts[1:]
        else:
            parts = path.split('/')
        for part in parts:
            if part in ('', '.', '..'):
                raise ValueError('unsafe path component')
            parent = os.open(part, DIR_FLAGS, dir_fd=parent)
            stack.callback(os.close, parent)
        yield parent


def harden_credentials(home=HOME):
    # No file content is read or rewritten. No files are created and no unknown
    # paths, projects, executables or general HOME permissions are changed.
    with directory(home) as home_fd:
        for path, names in PRIVATE.items():
            try:
                with directory(path, home_fd) as parent:
                    os.fchmod(parent, 0o700)
                    for name in names:
                        try:
                            # NONBLOCK prevents a substituted FIFO from hanging
                            # startup. Validate the opened inode before chmod.
                            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                                         dir_fd=parent)
                        except FileNotFoundError:
                            continue
                        try:
                            info = os.fstat(fd)
                            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                                raise ValueError('credential must be a single-link regular file')
                            os.fchmod(fd, 0o600)
                        finally:
                            os.close(fd)
            except FileNotFoundError:
                continue  # A provider that has never been configured is valid.


def main():
    try:
        harden_credentials()
    except (OSError, ValueError):
        # Avoid printing user content, link targets or operating-system errors.
        print('[ha-opendesign] refused unsafe provider credential path or permissions', file=sys.stderr)
        return 78
    return 0


if __name__ == '__main__':
    sys.exit(main())
