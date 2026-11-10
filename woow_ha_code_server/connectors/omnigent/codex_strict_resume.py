"""Opt-in original Codex cold adoption. Never synthesize/fork/start a thread.

Only the private owner request dispatcher invokes this helper. Native bootstrap
uses current SDK authority; a missing original or failed resume is a hard error.
"""
import asyncio
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import urlparse

from omnigent.runner.native.woow_claude_strict_resume import (
    fail, native_id, read_native, reserve_native, _process_record,
)


def is_codex(record):
    args = record['args']
    return bool(args) and (Path(os.fsdecode(args[0])).name in ('codex', 'codex.exe') or
        Path(record['exe']).name in ('codex', 'codex.exe') or
        any(b'@openai/codex/' in arg for arg in args[:3]))


def process_home(record):
    values = (record['path'] / 'environ').read_bytes().split(b'\0')
    homes = [os.fsdecode(x.split(b'=', 1)[1]) for x in values if x.startswith(b'CODEX_HOME=')]
    return Path(homes[0]).resolve() if len(homes) == 1 else None


def assert_no_writer(plan, *, proc_root=Path('/proc')):
    for path in proc_root.iterdir():
        if not path.name.isdigit() or int(path.name) == os.getpid():
            continue
        try:
            if path.stat().st_uid != os.geteuid():
                continue
            args = [x for x in (path / 'cmdline').read_bytes().split(b'\0') if x]
            if not args:
                continue
            candidate = {'args': args, 'exe': str((path / 'exe').resolve()), 'path': path}
            if not is_codex(candidate):
                continue
            if plan.native_id.encode() in args or process_home(candidate) == plan.home.resolve():
                fail('STRICT_NATIVE_ALREADY_RUNNING')
        except FileNotFoundError:
            continue
        except PermissionError:
            fail('STRICT_PROCESS_CHECK_UNAVAILABLE')


def validate_rollout(raw, nid, workspace):
    if not raw.endswith(b'\n'):
        fail('STRICT_NATIVE_FILE_INVALID')
    try:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if not rows or any(not isinstance(row, dict) for row in rows):
            fail('STRICT_NATIVE_FILE_INVALID')
        headers = [r.get('payload') for r in rows if r.get('type') == 'session_meta']
        if len(headers) != 1 or not isinstance(headers[0], dict):
            fail('STRICT_NATIVE_FILE_INVALID')
        header = headers[0]
        if rows[0].get('type') != 'session_meta' or header.get('id') != nid:
            fail('STRICT_NATIVE_ID_CHANGED')
        if header.get('cwd') != str(workspace):
            fail('STRICT_WORKSPACE_MISMATCH')
        if not any(r.get('type') in ('response_item', 'event_msg', 'turn_context') for r in rows[1:]):
            fail('STRICT_NATIVE_FILE_INVALID')
    except (ValueError, TypeError, UnicodeError):
        fail('STRICT_NATIVE_FILE_INVALID')


def fingerprint_authority(root):
    """Compare existing authority bytes privately; no credential copy/output."""
    out = {}
    for name in ('config.toml', 'auth.json', 'hooks.json'):
        path = root / name
        if not path.exists():
            out[name] = None
            continue
        raw = path.read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            fail('STRICT_AUTHORITY_UNSAFE')
        out[name] = hashlib.sha256(raw).hexdigest()
    return out


@dataclass
class StrictCodexPlan:
    session_id: str
    native_id: str
    workspace: Path
    root: Path
    bridge: Path
    home: Path
    path: Path
    size: int
    sha256: str
    inode: tuple
    epoch: int
    busy: object
    current_epoch: object
    authority_root: Path
    authority_fingerprint: dict
    launch_ticks: int | None = None
    launch_started_at: float | None = None
    app_server: object | None = None

    def check_prefix(self, *, allow_append=False):
        raw, meta = read_native(self.path, self.size if allow_append else None)
        if ((meta.st_dev, meta.st_ino) != self.inode or meta.st_nlink != 1 or
            len(raw) != self.size or hashlib.sha256(raw).hexdigest() != self.sha256 or
            (not allow_append and meta.st_size != self.size)):
            fail('STRICT_NATIVE_FILE_CHANGED')

    def check_authority(self):
        if fingerprint_authority(self.authority_root) != self.authority_fingerprint:
            fail('STRICT_AUTHORITY_CHANGED')

    def check_cold(self):
        if self.busy() or self.current_epoch() != self.epoch:
            fail('SESSION_BUSY')
        self.check_prefix()
        self.check_authority()
        assert_no_writer(self)

    def before_prepare(self, config):
        if (config.external_session_id != self.native_id or
            Path(config.workspace).resolve() != self.workspace.resolve() or
            config.fork_source_id or config.fork_source_external_id):
            fail('STRICT_NATIVE_ID_CHANGED')
        from omnigent.runner.native import orchestration
        old = orchestration._AUTO_CODEX_APP_SERVERS.get(self.session_id)
        task = orchestration._AUTO_FORWARDER_TASKS.get(self.session_id)
        if old is not None or (task is not None and not task.done()):
            fail('STRICT_NATIVE_ALREADY_RUNNING')
        self.check_cold()

    def resume_existing(self, config, home):
        if config.external_session_id != self.native_id or Path(home).resolve() != self.home.resolve():
            fail('STRICT_NATIVE_ID_CHANGED')
        self.check_cold()
        return self.path

    def before_server(self, server, config, reset_pick):
        self.check_cold()
        if (config.external_session_id != self.native_id or reset_pick is not None or
            Path(server.codex_home).resolve() != self.home.resolve() or
            Path(server.cwd).resolve() != self.workspace.resolve() or
            server.trust_project or server.trust_all_hooks):
            fail('STRICT_LAUNCH_CONFIG_CHANGED')
        self.app_server = server
        self.launch_ticks = int(float(Path('/proc/uptime').read_text().split()[0]) * os.sysconf('SC_CLK_TCK'))
        self.launch_started_at = time.time()


def prepare_plan(ctx, request, info, *, bridge_root=None, authority_root=None):
    sid = ctx.session_id
    if (request.get('engine') != 'codex' or request.get('sessionId') != sid or
        info.get('id') != sid or info.get('permission_level') != 4 or
        info.get('harness') != 'codex-native' or info.get('archived')):
        fail('STRICT_SESSION_INVALID')
    if info.get('status') != 'idle' or any(info.get(k) for k in (
        'pending_inputs', 'pending_elicitations', 'active_response_id', 'terminal_pending', 'background_task_count')):
        fail('SESSION_BUSY')
    nid = native_id(info.get('external_session_id'))
    if request.get('nativeSessionId') != nid:
        fail('STRICT_NATIVE_ID_CHANGED')
    selected_bridge = (info.get('labels') or {}).get('omnigent.codex_native.bridge_id') or sid
    # Pinned ORIGINAL auto-create uses SID, not fork/transfer bridge labels.
    # Reject a different bridge instead of silently attaching the default.
    if selected_bridge != sid:
        fail('STRICT_BRIDGE_ID_CHANGED')
    workspace = Path(info.get('workspace') or '')
    if not workspace.is_absolute() or request.get('workspace') != str(workspace):
        fail('STRICT_WORKSPACE_MISMATCH')
    workspace.resolve(strict=True)
    from omnigent.harnesses.codex_native import bridge as bridge_api
    bridge = bridge_api.bridge_dir_for_bridge_id(sid) if bridge_root is None else bridge_root / hashlib.sha256(sid.encode()).hexdigest()[:32]
    home = bridge / 'codex-home'
    if home.resolve(strict=True) != home:
        # HOME mount aliases may be legitimate; require the canonical spelling
        # in this explicit operation instead of following arbitrary links.
        fail('STRICT_NATIVE_FILE_UNSAFE')
    candidates = list((home / 'sessions').glob('**/rollout-*-' + nid + '.jsonl'))
    if len(candidates) != 1:
        fail('STRICT_NATIVE_FILE_UNAVAILABLE')
    path = candidates[0]
    if path.parent.resolve(strict=True) != path.parent:
        fail('STRICT_NATIVE_FILE_UNSAFE')
    raw, meta = read_native(path)
    if meta.st_nlink != 1 or meta.st_mode & 0o022:
        fail('STRICT_NATIVE_FILE_UNSAFE')
    validate_rollout(raw, nid, workspace)
    digest = hashlib.sha256(raw).hexdigest()
    if request.get('originalBytes') != len(raw) or request.get('originalSHA256') != digest:
        fail('STRICT_NATIVE_FILE_CHANGED')
    if authority_root is None:
        from omnigent.inner.codex_executor import _codex_home_config_source_from_env
        authority_root = _codex_home_config_source_from_env().resolve(strict=True)
    plan = StrictCodexPlan(sid, nid, workspace, bridge.parent, bridge, home, path,
        len(raw), digest, (meta.st_dev, meta.st_ino), ctx.resource_registry.session_activity_epoch(sid),
        lambda: ctx.resource_registry.session_turn_is_active(sid),
        lambda: ctx.resource_registry.session_activity_epoch(sid), authority_root, fingerprint_authority(authority_root))
    plan.check_cold()
    return plan


def descendants(pid, *, proc_root=Path('/proc')):
    todo, seen, rows = [pid], set(), []
    while todo and len(seen) < 128:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        record = _process_record(current, proc_root=proc_root)
        rows.append(record)
        # Do not inspect independent MCP children below the actual native.
        if Path(record['exe']).name in ('codex', 'codex.exe'):
            continue
        try:
            todo.extend(map(int, (record['path'] / 'task' / str(current) / 'children').read_text().split()))
        except (OSError, ValueError):
            fail('STRICT_NATIVE_PROCESS_UNAVAILABLE')
    if todo:
        fail('STRICT_NATIVE_PROCESS_UNAVAILABLE')
    return rows


def verify_processes(plan, server, pane_pid, *, proc_root=Path('/proc')):
    proc = getattr(server, 'proc', None)
    if proc is None or proc.returncode is not None or plan.launch_ticks is None:
        fail('STRICT_NATIVE_PROCESS_UNAVAILABLE')
    endpoint = urlparse(server.listen_url or '')
    if endpoint.scheme != 'ws' or endpoint.hostname != '127.0.0.1' or not endpoint.port:
        fail('STRICT_NATIVE_BINDING_CHANGED')
    # Bind the observed RPC socket to the NEW registered process tree. A stale
    # bridge URL or a foreign process cannot satisfy attachment confirmation.
    inodes = set()
    for line in (proc_root / 'net/tcp').read_text().splitlines()[1:]:
        fields = line.split()
        if fields[1] == f'0100007F:{endpoint.port:04X}' and fields[3] == '0A':
            inodes.add('socket:[' + fields[9] + ']')
    servers = []
    for record in descendants(proc.pid, proc_root=proc_root):
        if not is_codex(record) or b'app-server' not in record['args']:
            continue
        try:
            sockets = set()
            for fd in (record['path'] / 'fd').iterdir():
                try:
                    sockets.add(os.readlink(fd))
                except FileNotFoundError:
                    # Unrelated descriptors may close while listing /proc.
                    # Still require the actual listening socket below.
                    continue
        except OSError:
            continue
        if sockets & inodes:
            servers.append(record)
    if len(servers) != 1:
        fail('STRICT_NATIVE_PROCESS_UNAVAILABLE')
    native = servers[0]
    if native['startTicks'] < plan.launch_ticks or process_home(native) != plan.home.resolve():
        fail('STRICT_NATIVE_GENERATION_CHANGED')
    if (native['path'] / 'cwd').resolve() != plan.workspace.resolve():
        fail('STRICT_WORKSPACE_MISMATCH')
    # A real fresh TUI must be attached to this exact native thread/endpoint.
    matches = []
    for record in descendants(pane_pid, proc_root=proc_root):
        args = [os.fsdecode(x) for x in record['args']]
        if is_codex(record) and 'resume' in args and plan.native_id in args and server.listen_url in args:
            matches.append(record)
    if not matches or any(r['startTicks'] < plan.launch_ticks for r in matches):
        fail('STRICT_NATIVE_GENERATION_CHANGED')
    return {'nativePid': native['pid'], 'nativeStartTicks': native['startTicks'],
            'registeredProcessPid': proc.pid, 'panePid': pane_pid}


async def confirm_attachment(plan, registry):
    from omnigent.runner.native import orchestration
    from omnigent.harnesses.codex_native.bridge import read_bridge_state
    from omnigent.harnesses.codex_native.app_server import client_for_transport
    from omnigent.entities.session_resources import terminal_resource_id
    server = orchestration._AUTO_CODEX_APP_SERVERS.get(plan.session_id)
    state = read_bridge_state(plan.bridge)
    if (server is None or server is not plan.app_server or state is None or
        state.session_id != plan.session_id or state.thread_id != plan.native_id or
        Path(state.codex_home).resolve() != plan.home.resolve() or
        state.socket_path != server.listen_url or state.active_turn_id):
        fail('STRICT_ATTACH_UNCONFIRMED')
    view = await registry.get_terminal_resource(plan.session_id, terminal_resource_id('codex', 'main'))
    terminal = registry.terminal_registry.get(plan.session_id, 'codex', 'main')
    if view is None or terminal is None:
        fail('STRICT_ATTACH_UNCONFIRMED')
    pane = await asyncio.to_thread(terminal.pane_pid_sync)
    identity = await asyncio.to_thread(verify_processes, plan, server, pane)
    client = client_for_transport(server.listen_url, client_name='woow-strict-original-codex')
    client_closed = False
    try:
        await client.connect()
        loaded = (await client.request('thread/loaded/list', {})).get('result', {}).get('data', [])
        thread = (await client.request('thread/read', {'threadId': plan.native_id, 'includeTurns': False})).get('result', {}).get('thread', {})
        if (plan.native_id not in loaded or thread.get('id') != plan.native_id or
            thread.get('status', {}).get('type') != 'idle' or thread.get('cwd') != str(plan.workspace)):
            fail('STRICT_NATIVE_ID_CHANGED')
        if thread.get('path') and Path(thread['path']).resolve() != plan.path.resolve():
            fail('STRICT_NATIVE_FILE_CHANGED')
        plan.check_prefix(allow_append=True)
        plan.check_authority()
        again = await asyncio.to_thread(terminal.pane_pid_sync)
        if again != pane or await asyncio.to_thread(verify_processes, plan, server, again) != identity:
            fail('STRICT_NATIVE_GENERATION_CHANGED')
        await client.close()
        client_closed = True
        # Deletion/rebinding can detach a terminal before async close kills
        # its pane. Re-read authority after ALL awaited RPC/process checks;
        # cached objects being alive does not mean this session owns them.
        current_view = await registry.get_terminal_resource(plan.session_id, terminal_resource_id('codex', 'main'))
        current_terminal = registry.terminal_registry.get(plan.session_id, 'codex', 'main')
        current_state = read_bridge_state(plan.bridge)
        if (current_view is None or current_terminal is not terminal or
            orchestration._AUTO_CODEX_APP_SERVERS.get(plan.session_id) is not server or
            current_state is None or current_state.session_id != plan.session_id or
            current_state.thread_id != plan.native_id or current_state.active_turn_id or
            Path(current_state.codex_home).resolve() != plan.home.resolve() or
            current_state.socket_path != server.listen_url):
            fail('STRICT_ATTACH_UNCONFIRMED')
        if plan.busy() or plan.current_epoch() != plan.epoch:
            fail('SESSION_BUSY')
        return {'state':'attached','sessionId':plan.session_id,'nativeSessionId':plan.native_id,
            'historyPrefixPreserved':True,'originalBytes':plan.size,'originalSHA256':plan.sha256,
            'currentNativeVerified':True,'sameProcess':False,'toolsVerified':False,
            'launchStartedAt':plan.launch_started_at,'threadReadVerified':True,
            'authorityFilesUnchanged':True, **identity}
    finally:
        if not client_closed:
            await client.close()


async def cold_resume(ctx, request, *, launch_kwargs):
    from omnigent.runner.native.orchestration import _launch_native_terminal
    response = await ctx.server_client.get('/v1/sessions/'+ctx.session_id,
        params={'include_items':'false','include_usage':'false','include_live_status':'false'})
    if response.status_code != 200:
        fail('STRICT_SESSION_UNAVAILABLE')
    plan = prepare_plan(ctx, request, response.json())
    with reserve_native(plan):
        result = await _launch_native_terminal('codex-native', replace(ctx, woow_strict_resume=plan),
            **{**launch_kwargs,'pre_launch':None,'reraise':True})
        if result is not True:
            fail('STRICT_ATTACH_FAILED')
        return result, await confirm_attachment(plan, ctx.resource_registry)
