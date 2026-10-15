"""Stock-image bootstrap: own only a new dedicated directory, then drop privilege.

No command override, runtime install or bootstrap HA API call. No recursive chown, except the bounded,
verified repair of state that Home Assistant restored root-owned (observed in the 2026-10-05 HA pilot).
Each product's management process receives the runtime Supervisor token for the approved HA admin
verifier (n8n 2026-10-04; the other six 2026-10-05, 0.1.1; Nextcloud 2026-10-08, 0.1.7); children are started
with allowlisted env.
Existing state must belong to uid/gid 10001. The restore repair: pass 1 approves a bounded tree of plain
directories and single-link regular files on one filesystem and keeps a descriptor on every approved
inode; pass 2 requires the same names to still name those pinned inodes and changes only the pinned
inodes after re-checking type, owner and link count. Changes made before an entry's re-check stop
bootstrap; anything changed after it cannot redirect the repair, which only ever touches pinned,
approved inodes.
"""
import ctypes
import os
from pathlib import Path
import resource
import stat
import sys

PRODUCTS = ('odoo', 'odoo-manage', 'n8n', 'hermes', 'opendesign', 'emqx', 'litellm', 'nextcloud')
UID = GID = 10001
ROOT = Path('/opt/woow')
RESTORE_OWNER = (0, 0)  # Supervisor extracts a restored app backup as root
MAX_RESTORED_ENTRIES = 512  # every approved entry holds a descriptor until the repair ends
MAX_RESTORED_DEPTH = 8
CHANGED = 'restored state changed during bootstrap'


def _owner(info):
    return (info.st_uid, info.st_gid)


def _identity(info):
    # Exact while the approved inode is pinned by an open descriptor: it cannot be freed, so its inode
    # number cannot be reused by a replacement file.
    return (info.st_dev, info.st_ino)


def _plain(info, directory):
    return stat.S_ISDIR(info.st_mode) if directory else (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)


def _names(dir_fd, limit, error):
    """Directory entry names, streamed, refusing as soon as there are more than `limit` (no full listing)."""
    names = []
    with os.scandir(dir_fd) as entries:
        for entry in entries:
            if len(names) >= limit:
                raise RuntimeError(error)
            names.append(entry.name)
    return names


def _descriptor_budget():
    """Raise the soft descriptor limit for the repair; return the limits to restore afterwards, or None."""
    need = MAX_RESTORED_ENTRIES + 64
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == resource.RLIM_INFINITY or soft >= need:
        return None
    if hard != resource.RLIM_INFINITY and hard < need:
        raise RuntimeError('descriptor limit too low for restored state')
    resource.setrlimit(resource.RLIMIT_NOFILE, (need, hard))
    return soft, hard


def _approve_restored(dir_fd, dev, depth, budget, pinned):
    """Pass 1, no changes: return {name: (descriptor, identity, children or None)}.

    Only plain directories and single-link regular files, owned by the restore owner or the runtime user,
    on the same filesystem as /data/mcp, within the entry and depth limits. Each entry is opened without
    following links (regular files with O_PATH: nothing is read or triggered), must be the inode that was
    just checked, and stays open in `pinned` until the repair ends.
    """
    if depth > MAX_RESTORED_DEPTH:
        raise RuntimeError('restored state too deep')
    approved = {}
    names = _names(dir_fd, budget[0], 'restored state too large')
    budget[0] -= len(names)  # reserve the whole level first: the total can never exceed the limit
    for name in names:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if _owner(info) not in (RESTORE_OWNER, (UID, GID)):
            raise RuntimeError('foreign restored owner')
        if info.st_dev != dev:
            raise RuntimeError('restored state crosses a filesystem boundary')
        directory = stat.S_ISDIR(info.st_mode)
        if not _plain(info, directory):
            raise RuntimeError('unsupported restored entry')
        fd = os.open(name, os.O_NOFOLLOW | (os.O_RDONLY | os.O_DIRECTORY if directory else os.O_PATH), dir_fd=dir_fd)
        pinned.append(fd)
        opened = os.fstat(fd)
        if _identity(opened) != _identity(info) or _owner(opened) != _owner(info) or not _plain(opened, directory):
            raise RuntimeError(CHANGED)
        children = _approve_restored(fd, dev, depth + 1, budget, pinned) if directory else None
        approved[name] = (fd, _identity(info), children)
    return approved


def _reown_restored(dir_fd, approved):
    """Pass 2: change only the pinned, approved inodes, each re-checked first.

    The directory must hold exactly the approved names, each still naming its pinned inode (no additions,
    removals, renames or replacements); the pinned inode must still be the approved type, owned by the
    restore owner or the runtime user, with one link. Then that inode's mode and owner are set through its
    own descriptor (regular files via the /proc/self/fd magic link of the O_PATH descriptor). Mode first,
    owner last, so an interrupted repair leaves root-owned entries that the next boot repairs again.
    Approved entries repaired before a change is found keep the change: they were approved.
    """
    if sorted(_names(dir_fd, len(approved), CHANGED)) != sorted(approved):
        raise RuntimeError(CHANGED)
    for name, (fd, identity, children) in approved.items():
        current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        held = os.fstat(fd)
        directory = children is not None
        if (_identity(current) != identity or _identity(held) != identity or not _plain(held, directory)
                or _owner(held) not in (RESTORE_OWNER, (UID, GID))):
            raise RuntimeError(CHANGED)
        if directory:
            _reown_restored(fd, children)
            os.fchmod(fd, 0o700)
            os.fchown(fd, UID, GID)
        else:
            # O_PATH descriptors cannot fchown/fchmod; the magic link names exactly this pinned inode.
            target = '/proc/self/fd/%d' % fd
            os.chmod(target, 0o600)
            os.chown(target, UID, GID)


def _repair_restored(child, top):
    """Return the number of re-owned entries; the caller reports it once the final ownership check passed."""
    original = _descriptor_budget()
    pinned = []
    try:
        _reown_restored(child, _approve_restored(child, top.st_dev, 0, [MAX_RESTORED_ENTRIES], pinned))
    finally:
        for fd in pinned:
            os.close(fd)
        if original is not None:
            # Lowering the soft limit back is always permitted; the management process keeps the image default.
            resource.setrlimit(resource.RLIMIT_NOFILE, original)
    os.fchmod(child, 0o700)
    os.fchown(child, UID, GID)
    return len(pinned)


def prepare_data(parent=Path('/data')):
    # Directory fds prevent a substituted symlink from redirecting bootstrap.
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.mkdir('mcp', mode=0o700, dir_fd=fd)
            created = True
        except FileExistsError:
            created = False
        child = os.open('mcp', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            if created and os.geteuid() == 0:
                os.fchown(child, UID, GID)
            info = os.fstat(child)
            repaired = None
            if (not created and os.geteuid() == 0 and (info.st_uid, info.st_gid) == RESTORE_OWNER
                    and RESTORE_OWNER != (UID, GID)):
                repaired = _repair_restored(child, info)
                info = os.fstat(child)
            if (info.st_uid, info.st_gid) != (UID, GID) or stat.S_IMODE(info.st_mode) != 0o700:
                raise RuntimeError('incompatible data ownership')
            if repaired is not None:
                print('bootstrap: re-owned %d restored entries in /data/mcp' % repaired, file=sys.stderr, flush=True)
        finally:
            os.close(child)
    finally:
        os.close(fd)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in PRODUCTS:
        raise RuntimeError('fixed product required')
    product = sys.argv[1]
    os.umask(0o077)
    prepare_data()
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(GID)
        os.setuid(UID)
    if (os.getuid(), os.geteuid(), os.getgid()) != (UID, UID, GID):
        raise RuntimeError('runtime privilege drop failed')
    # Linux no_new_privs: later exec cannot gain setuid/file-capability authority.
    if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
        raise RuntimeError('no_new_privs unavailable')
    python = str(ROOT / '.venv/bin/python')
    # The final interpreter exec MUST enter the trusted post-exec guard.
    args = [str(ROOT / 'packaging/management_launcher.py'), product]
    # Fixed environment; no proxy/Python/provider URL or command injection.
    # The approved management verifier needs the runtime token; it is the only inherited variable.
    # Child env stripping AND post-exec procfs/memory denial are both required.
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/data/mcp',
           'PYTHONPATH': str(ROOT / 'packages/mcp-admin-core') + ':' + str(ROOT / 'apps/n8n'),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1'}
    token = os.environ.get('SUPERVISOR_TOKEN')
    if token:
        env['SUPERVISOR_TOKEN'] = token
    os.chdir(ROOT)
    os.execve(python, [python, *args], env)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError):
        raise SystemExit('bootstrap unavailable; check protected data ownership and release documentation') from None
