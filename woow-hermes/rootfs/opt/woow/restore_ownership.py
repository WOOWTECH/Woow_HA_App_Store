"""Repair HA's dedicated addon_config volume after Supervisor restore.

Supervisor extracts application configuration as root. Unlike a general host
home directory, /opt/data in this add-on is an exclusive application volume.
Preserve ordinary permission bits; chown intentionally clears privileged bits.
Never follow symlinks, modify hardlinked files, or enter nested mounts.
"""
import argparse
import os
import pwd
import stat


def mount_id(fd):
    with open(f'/proc/self/fdinfo/{fd}') as stream:
        for line in stream:
            if line.startswith('mnt_id:'):
                return int(line.split(':', 1)[1])
    raise RuntimeError('mount identity unavailable')


def repair(root, uid, gid):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, flags)
    changed = 0
    try:
        device = os.fstat(root_fd).st_dev
        root_mount = mount_id(root_fd)
        for _, directories, files, parent in os.fwalk(
            '.', topdown=True, follow_symlinks=False, dir_fd=root_fd
        ):
            current = os.fstat(parent)
            if current.st_dev != device or mount_id(parent) != root_mount:
                directories[:] = []
                continue
            if (current.st_uid, current.st_gid) != (uid, gid):
                os.fchown(parent, uid, gid)
                changed += 1
            for name in list(directories):
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or info.st_dev != device:
                    directories.remove(name)
            for name in files:
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_dev != device:
                    continue
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    current = os.fstat(fd)
                    if not stat.S_ISREG(current.st_mode) or current.st_dev != device:
                        raise RuntimeError('application volume entry changed during repair')
                    if mount_id(fd) != root_mount:
                        continue
                    if (current.st_uid, current.st_gid) != (uid, gid):
                        if current.st_nlink != 1:
                            raise RuntimeError('refusing to change hardlinked application state')
                        os.fchown(fd, uid, gid)
                        changed += 1
                finally:
                    os.close(fd)
    finally:
        os.close(root_fd)
    return changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='/opt/data')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('HA restore ownership repair requires root')
    user = pwd.getpwnam('hermes')
    count = repair(args.root, user.pw_uid, user.pw_gid)
    print(f'[woow-restore] repaired {count} application volume entries')
