"""Disposable image fixture: restore-like root/0644 input, real startup and UIDs."""
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys

HOME = Path('/data/opendesign/home')
FILES = {
    '.codex/auth.json': b'{"auth_mode":"apikey","OPENAI_API_KEY":"ha-permission-fixture-not-a-secret"}\n',
    '.codex/config.toml': b'# permission fixture\n',
    '.claude/.credentials.json': b'{}\n',
    '.claude/settings.json': b'{"env":{}}\n',
    '.pi/agent/auth.json': b'{}\n',
    '.pi/agent/models.json': b'{"providers":{}}\n',
    '.pi/agent/settings.json': b'{}\n',
}
DIRS = ['.codex', '.claude', '.pi', '.pi/agent']
if sys.argv[1] == 'seed':
    for name, content in FILES.items():
        p = HOME / name
        assert not p.is_symlink()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content); p.chmod(0o644); os.chown(p, 0, 0)
    for name in DIRS:
        (HOME / name).chmod(0o755)
    print('seeded disposable root/0644 credential fixture')
elif sys.argv[1] == 'verify':
    for name, content in FILES.items():
        p = HOME / name
        assert p.read_bytes() == content, 'credential bytes changed'
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, 'credential mode not private'
        assert (p.stat().st_uid, p.stat().st_gid) == (1001, 1001)
    for name in DIRS:
        assert stat.S_IMODE((HOME / name).stat().st_mode) == 0o700
    for helper in ['ha-opendesign-credentials.py', 'ha-opendesign-return.py']:
        p = Path('/usr/local/libexec') / helper
        assert p.stat().st_uid == 0 and p.stat().st_mode & 0o022 == 0
    # Open actual files under each service identity; no bytes reach stdout/logs.
    probe = '''import pathlib,sys
for name in sys.argv[2:]:
 try:
  with (pathlib.Path('/data/opendesign/home')/name).open('rb') as stream: stream.read(1)
 except PermissionError:
  assert sys.argv[1]=='denied'
 else:
  assert sys.argv[1]=='allowed'
'''
    identities = [('open-design:open-design', 'allowed'), ('ha-ingress:ha-ingress', 'denied'),
                  ('mcp:mcp', 'denied'), ('1002:1001', 'denied')]
    assert pwd.getpwnam('ha-ingress').pw_uid == 1002 and pwd.getpwnam('mcp').pw_uid == 10001
    for identity, expected in identities:
        result = subprocess.run(['su-exec', identity, 'python3', '-c', probe, expected, *FILES], capture_output=True)
        assert result.returncode == 0, 'credential access policy failed for ' + identity
    # Real locked CLIs as the agent user, without a model/network request. Codex
    # must load the restored API-key config; never print its status/key fragment.
    for command in [['codex', 'login', 'status'], ['claude', '--version'], ['pi', '--version']]:
        result = subprocess.run(['su-exec', 'open-design:open-design', *command], capture_output=True, timeout=30)
        assert result.returncode == 0, 'native CLI credential/home probe failed: ' + command[0]
    print('credential startup PASS: bytes retained, 0600/0700, UID1001 usable; nginx/MCP denied')
else:
    raise SystemExit('expected seed or verify')
