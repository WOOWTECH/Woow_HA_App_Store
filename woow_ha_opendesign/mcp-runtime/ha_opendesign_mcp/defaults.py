"""0.2.1: the three OpenDesign writers are on by default (owner decision 2026-10-15), applied ONCE per state.

The vendored policy enables a writer only with an exact grant in state.enabled_write_tools (policy.enabled), and a new
state starts with none. On its first start with 0.2.1 the runtime therefore grants create_project, delete_project and
send_message, except a tool the administrator has disabled (state.disabled always wins and is left as it is), then
writes MARKER next to state.json. While the marker exists this never runs again, so an administrator who later revokes
a grant keeps that choice across restarts and updates. A fresh install and a 0.2.0 state (no marker) are treated
alike. Restoring a backup made before 0.2.1 restores a state without the marker: it is applied again, once.

The caller holds the store's exclusive writer lock (vendored config.Store) and runs this before any listener starts,
so no administrator change can interleave. Stdlib only.
"""
import json
import os
import secrets
import stat

MARKER = 'ha-tool-defaults.json'
WRITERS = ('create_project', 'delete_project', 'send_message')
RECORD = 'woow-ha-opendesign 0.2.1: OpenDesign writers on by default'


def applied(directory):
    """True when the marker exists. A marker that is not a regular file (e.g. a symlink) is refused."""
    try:
        info = os.lstat(os.path.join(directory, MARKER))
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError('tool defaults marker is not a regular file')
    return True


def apply(store, directory=None):
    """Grant the writers once (see the module docstring). Returns what was done, or None when already applied."""
    directory = str(store.directory if directory is None else directory)
    if applied(directory):
        return None
    state = store.load()
    grants = list(state.enabled_write_tools)
    granted = [name for name in WRITERS if name not in grants and name not in state.disabled]
    if granted:
        store.update(enabled_write_tools=grants + granted)
    record = {'schema': 1, 'record': RECORD, 'granted': granted,
              'left_disabled': [name for name in WRITERS if name in state.disabled]}
    _write(directory, record)
    return record


def _write(directory, record):
    """Durable, no-follow, same-directory replace (as config.Store._write)."""
    temporary = os.path.join(directory, '.tool-defaults-' + secrets.token_hex(16))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, os.path.join(directory, MARKER))
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
