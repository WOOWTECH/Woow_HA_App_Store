"""Disposable image fixture: synthetic archive restore, real startup and UIDs."""
import io
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import tarfile

HOME = Path('/data/opendesign/home')
FILES = {
    '.codex/auth.json': b'{"auth_mode":"apikey","OPENAI_API_KEY":"ha-permission-fixture-not-a-secret"}\n',
    '.codex/config.toml': b'# permission fixture\n',
    '.claude/.credentials.json': b'{}\n',
    '.claude/settings.json': b'{"env":{}}\n',
    '.pi/agent/auth.json': b'{}\n',
    '.pi/agent/models.json': b'{"providers":{}}\n',
    '.pi/agent/settings.json': b'{}\n',
    '.config/opencode/opencode.json': b'{"provider":{}}\n',
    '.config/opencode/opencode.jsonc': b'// retain comments after restore\n{"provider":{},}\n',
    '.local/share/opencode/auth.json': b'{}\n',
}
DIRS = ['.codex', '.claude', '.pi', '.pi/agent', '.config/opencode', '.local/share/opencode']
SHARED_FILES = {
    '.config/ha-permission-fixture/settings.json': b'{"fixture":"shared-not-a-secret"}\n',
    '.local/share/ha-permission-fixture/state.json': b'{"fixture":"shared-not-a-secret"}\n',
}
SHARED_DIRS = ['.config', '.local', '.local/share', '.config/ha-permission-fixture',
               '.local/share/ha-permission-fixture']
if sys.argv[1] == 'seed':
    assert os.geteuid() == 0, 'restore fixture requires root in the disposable container'
    # Only fixed synthetic members; never extract an external backup here.
    # All ancestors remain traversable, so later UID denials must come from
    # private provider paths rather than an inaccessible HOME/shared parent.
    archive = io.BytesIO()
    for name in [*DIRS, *SHARED_DIRS, *FILES, *SHARED_FILES]:
        p = HOME / name
        while p != HOME.parent:
            assert not p.is_symlink()
            p = p.parent
    HOME.chmod(0o755)
    with tarfile.open(fileobj=archive, mode='w') as tar:
        for name in sorted([*DIRS, *SHARED_DIRS], key=lambda name: (name.count('/'), name)):
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE; info.mode = 0o755; info.uid = info.gid = 0
            tar.addfile(info)
        for name, content in {**FILES, **SHARED_FILES}.items():
            info = tarfile.TarInfo(name)
            info.size = len(content); info.mode = 0o644; info.uid = info.gid = 0
            tar.addfile(info, io.BytesIO(content))
    archive.seek(0)
    with tarfile.open(fileobj=archive, mode='r') as tar:
        # This archive contains only the fixed synthetic members above. Retain
        # the root ownership fixture even on Python 3.14's safer default filter.
        tar.extractall(HOME, filter='fully_trusted')
    for name in FILES:
        info = (HOME / name).stat()
        assert stat.S_IMODE(info.st_mode) == 0o644 and (info.st_uid, info.st_gid) == (0, 0)
    print('restored disposable synthetic archive with root/0644 credentials')
elif sys.argv[1] == 'verify':
    changed = []
    for name, content in FILES.items():
        p = HOME / name
        if name == '.config/opencode/opencode.json':
            # shared-agents.mjs adds the managed MCP entries on every start;
            # the user's provider settings must survive that merge.
            actual = json.loads(p.read_bytes())
            expected = json.loads(content)
            assert actual.get('provider') == expected['provider'], 'OpenCode provider settings changed'
            assert isinstance(actual.get('mcp'), dict), 'shared OpenCode MCP entries missing'
        elif name == '.codex/config.toml':
            # The explicit shared-agents sync appends exactly one managed block.
            # The original user config before that block must remain intact.
            actual = p.read_bytes()
            start = b'# BEGIN ha-opendesign shared MCP'
            end = b'# END ha-opendesign shared MCP'
            assert actual.count(start) == actual.count(end) == 1, 'Codex managed MCP block count changed'
            assert actual.index(start) < actual.index(end), 'Codex managed MCP block order changed'
            assert actual[:actual.index(start)].strip() == content.strip(), 'Codex user settings changed'
            assert not actual[actual.index(end) + len(end):].strip(), 'unexpected Codex config suffix'
        elif p.read_bytes() != content:
            changed.append(name)
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, 'credential mode not private'
        assert (p.stat().st_uid, p.stat().st_gid) == (1001, 1001)
    assert not changed, 'synthetic credential bytes changed: ' + ', '.join(changed)
    for name in DIRS:
        assert stat.S_IMODE((HOME / name).stat().st_mode) == 0o700
    for name in SHARED_DIRS:
        assert stat.S_IMODE((HOME / name).stat().st_mode) == 0o755, 'shared directory mode changed'
    for name, content in SHARED_FILES.items():
        p = HOME / name
        assert p.read_bytes() == content and stat.S_IMODE(p.stat().st_mode) == 0o644
    for helper in ['ha-opendesign-credentials.py', 'ha-opendesign-return.py']:
        p = Path('/usr/local/libexec') / helper
        assert p.stat().st_uid == 0 and p.stat().st_mode & 0o022 == 0
    # Open actual files under each service identity; no bytes reach stdout/logs.
    probe = '''import pathlib,sys
private_end=4+int(sys.argv[3])
for name in sys.argv[4:private_end]:
 try:
  with (pathlib.Path('/data/opendesign/home')/name).open('rb') as stream: stream.read(1)
 except PermissionError:
  assert sys.argv[1]=='denied'
 else:
  assert sys.argv[1]=='allowed'
for name in sys.argv[private_end:]:
 try:
  with (pathlib.Path('/data/opendesign/home')/name).open('rb') as stream: stream.read(1)
 except PermissionError:
  assert sys.argv[2]=='denied'
 else:
  assert sys.argv[2]=='allowed'
'''
    # The launcher intentionally sets HOME to 0750. An alternate UID in its
    # group can read shared fixtures but must still be denied private leaves.
    identities = [('open-design:open-design', 'allowed', 'allowed'),
                  ('ha-ingress:ha-ingress', 'denied', 'denied'),
                  ('mcp:mcp', 'denied', 'denied'), ('1002:1001', 'denied', 'allowed')]
    assert pwd.getpwnam('ha-ingress').pw_uid == 1002 and pwd.getpwnam('mcp').pw_uid == 10001
    for identity, expected, shared_expected in identities:
        result = subprocess.run(['su-exec', identity, 'python3', '-c', probe, expected,
                                 shared_expected, str(len(FILES)), *FILES, *SHARED_FILES], capture_output=True, timeout=30)
        assert result.returncode == 0, 'credential access policy failed for ' + identity
    # Real locked CLIs as the agent user, without a model/network request. Codex
    # must load the restored API-key config; never print its status/key fragment.
    for command in [['codex', 'login', 'status'], ['claude', '--version'], ['pi', '--version'], ['opencode', '--version']]:
        result = subprocess.run(['su-exec', 'open-design:open-design', *command], capture_output=True, timeout=30)
        assert result.returncode == 0, 'native CLI credential/home probe failed: ' + command[0]
    print('credential startup PASS: auth bytes retained, OpenCode and Codex user settings with MCP merged, four providers 0600/0700, UID1001 usable; nginx/MCP denied; shared paths readable')
else:
    raise SystemExit('expected seed or verify')
