"""Run HA volume ownership repair after UID remap, before unprivileged setup."""
import argparse
from pathlib import Path

ANCHOR = '\nneeds_chown=false\n'
BLOCK = '''
# woow: Supervisor restore resets ownership of the dedicated addon_config mount.
# The generic upstream allowlist intentionally excludes host-owned content, but
# this HA mount contains only application state. Repair it after UID remapping.
if [ "$HERMES_HOME" = /opt/data ]; then
    /opt/hermes/.venv/bin/python /opt/woow/restore_ownership.py
fi
'''


def patch(source):
    if BLOCK in source:
        return source
    if source.count(ANCHOR) != 1:
        raise ValueError('stage2 ownership anchor must occur exactly once')
    return source.replace(ANCHOR, BLOCK + ANCHOR, 1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=Path, default=Path('/opt/hermes/docker/stage2-hook.sh'))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    source = args.target.read_text()
    result = patch(source)
    if args.check:
        if result != source:
            raise SystemExit('HA ownership repair not installed')
    else:
        args.target.write_text(result)
