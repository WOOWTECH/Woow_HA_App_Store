"""Run in the HA image as root; reproduce Supervisor's restored ownership."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('repair', '/opt/woow/restore_ownership.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert os.geteuid() == 0


def as_user(argv):
    def drop():
        os.setgroups([])
        os.setgid(10000)
        os.setuid(10000)
    return subprocess.run(argv, preexec_fn=drop, capture_output=True)


with tempfile.TemporaryDirectory(prefix='ha1014-restore-regression-') as temp:
    top = Path(temp)
    top.chmod(0o755)
    home = top / 'application'
    home.mkdir(mode=0o700)
    os.chown(home, 10000, 10000)
    for name in ['platforms', 'platforms/pairing', 'plugins', 'backups']:
        (home / name).mkdir(mode=0o700)
    state = home / 'plugins/state.json'
    state.write_text('{"synthetic":true}')
    state.chmod(0o600)
    outside = top / 'outside'
    outside.mkdir(mode=0o700)
    secret = outside / 'do-not-touch'
    secret.write_text('synthetic outside data')
    secret.chmod(0o600)
    (home / 'external-link').symlink_to(outside, target_is_directory=True)
    assert as_user(['/bin/mkdir', '-p', str(home / 'platforms/pairing')]).returncode != 0
    assert as_user(['/bin/cat', str(state)]).returncode != 0
    before = (secret.stat().st_uid, secret.stat().st_gid, secret.stat().st_mode, secret.read_bytes())
    count = module.repair(str(home), 10000, 10000)
    assert count >= 5
    assert as_user(['/bin/mkdir', '-p', str(home / 'platforms/pairing')]).returncode == 0
    assert as_user(['/bin/cat', str(state)]).returncode == 0
    assert state.stat().st_mode & 0o777 == 0o600
    assert before == (secret.stat().st_uid, secret.stat().st_gid, secret.stat().st_mode, secret.read_bytes())
    assert module.repair(str(home), 10000, 10000) == 0
    (home / 'hardlink').hardlink_to(secret)
    try:
        module.repair(str(home), 10000, 10000)
    except RuntimeError as exc:
        assert 'hardlinked' in str(exc)
    else:
        raise AssertionError('hardlink must fail closed')
    assert secret.stat().st_uid == 0
    (home / 'hardlink').unlink()
    print(json.dumps({'result':'PASS','checks':['restored_root0700_reproduces_failure','platforms_parent_and_plugins_repaired','ordinary_modes_preserved','symlink_target_unchanged','hardlink_refused','warm_boot_idempotent']}))
