"""Prepare an explicit operator-coordinated cold resume, never ordinary ensure.

Caller fetches EDIT-authorized detail and fences the original conversation in
the shared runner cold-init dispatch before invoking this callback.
No caller-provided native paths, command, model, auth or terminal args accepted.
"""
import asyncio
from contextlib import ExitStack, contextmanager
from dataclasses import replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import struct
import tempfile
import time
import uuid


class PiResumeError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code):
    if not value:
        raise PiResumeError(code)


def owner_path(path, directory=False):
    path = Path(path)
    require(path.is_absolute(), 'PI_RESUME_UNSAFE_PATH')
    for part in [*reversed(path.parents), path]:
        require(not part.is_symlink(), 'PI_RESUME_UNSAFE_PATH')
    st = path.lstat()
    require((stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode))
            and st.st_uid == os.getuid() and not st.st_mode & 0o022, 'PI_RESUME_UNSAFE_PATH')
    return path


def resident_directory(path):
    """Accept the existing PVC root, not a caller-selected history location.

    PaaS mounts /data/pi-agent root:coder 2775. Its private child files still
    require owner_path; accepting the resident directory changes no ownership.
    """
    path = Path(path)
    require(path.is_absolute(), 'PI_RESUME_UNSAFE_PATH')
    for part in [*reversed(path.parents), path]:
        require(not part.is_symlink(), 'PI_RESUME_UNSAFE_PATH')
    st = path.lstat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid in (0, os.getuid()) and not st.st_mode & 0o002
            and (not st.st_mode & 0o020 or st.st_gid in (os.getegid(), *os.getgroups())), 'PI_RESUME_UNSAFE_PATH')
    return path


def _bridge(session_id):
    from omnigent.harnesses.pi_native.bridge import bridge_dir_for_session_id
    return bridge_dir_for_session_id(session_id)


def _write(path, data):
    fd, name = tempfile.mkstemp(prefix='.pi-strict-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def reserve_attachment(bridge):
    """Reserve preparation, owner assignment, child spawn and confirmation."""
    owner_path(bridge, True)
    fd = os.open(bridge / 'woow-pi-attach.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o077, 'PI_RESUME_UNSAFE_PATH')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PiResumeError('SESSION_BUSY') from None
        yield
    finally:
        os.close(fd)


def _socket_peer_pid(bridge):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(1)
        client.connect(str(bridge / 'woow-mcp.sock'))
        pid, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        require(uid == os.getuid(), 'PI_RESUME_IDENTITY_CHANGED')
        return pid


def _check_no_native(bridge):
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            command = (proc / 'cmdline').read_bytes().split(b'\0')
            is_pi = command[0] == b'pi' or any(b'pi-coding-agent' in x or b'pi_strict_launcher.mjs' in x for x in command)
            if not is_pi:
                continue
            env = dict(x.split(b'=', 1) for x in (proc / 'environ').read_bytes().split(b'\0') if b'=' in x)
            require(env.get(b'OMNIGENT_PI_NATIVE_CONFIG') != str(bridge / 'config.json').encode(), 'SESSION_BUSY')
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue


def _validate_session(session_id, info):
    require(isinstance(session_id, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', session_id), 'PI_RESUME_INVALID_SESSION')
    require(info.get('id') == session_id and info.get('status') == 'idle' and not info.get('archived'), 'SESSION_BUSY')
    require(info.get('harness') == 'pi-native', 'PI_RESUME_INVALID_SESSION')
    require(not any(info.get(k) for k in ('active_response_id', 'pending_inputs', 'pending_elicitations', 'terminal_pending')), 'SESSION_BUSY')
    require(not info.get('terminal_launch_args'), 'PI_RESUME_CUSTOM_ARGS_UNSUPPORTED')
    native = info.get('external_session_id', '')
    require(re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', native), 'PI_RESUME_IDENTITY_CHANGED')
    return native


def inspect_pi_recovery(session_id, info, expected):
    """Read an explicit original snapshot; accept no caller-selected file paths.

    The backup naming scheme is the task's already-created private persistent
    history store. Destination filename follows Pi 0.99.1 SessionManager's
    header timestamp convention. Neither this check nor recovery synthesizes
    any JSONL record or copies provider credentials.
    """
    native = _validate_session(session_id, info)
    require(expected.get('restoreSnapshot') is True and expected.get('sessionId') == session_id
            and expected.get('nativeSessionId') == native and expected.get('workspace') == info.get('workspace'),
            'PI_RESUME_IDENTITY_CHANGED')
    digest = expected.get('originalSHA256', '')
    size = expected.get('originalBytes')
    require(re.fullmatch(r'[0-9a-f]{64}', digest) and type(size) is int and 0 < size <= 128 * 1024 * 1024,
            'PI_RESUME_INVALID_HISTORY')
    persistent = resident_directory(Path(os.environ['PI_AGENT_DATA_DIR']))
    backup = owner_path(persistent / 'connectors/native-history-backup-20261110' / session_id / (native + '-' + digest + '.jsonl'))
    require(not backup.stat().st_mode & 0o077, 'PI_RESUME_UNSAFE_PATH')
    data = backup.read_bytes()
    require(len(data) == size and hashlib.sha256(data).hexdigest() == digest, 'PI_RESUME_HISTORY_CHANGED')
    require(data.endswith(b'\n'), 'PI_RESUME_INVALID_HISTORY')
    try:
        rows = [json.loads(line) for line in data.splitlines()]
        header = rows[0]
        stamp = header.get('timestamp', '')
        require(header.get('type') == 'session' and header.get('version') == 3 and header.get('id') == native
                and header.get('cwd') == info['workspace'] and all(r.get('id') and r.get('type') != 'session' for r in rows[1:])
                and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', stamp), 'PI_RESUME_INVALID_HISTORY')
    except (ValueError, KeyError, TypeError, IndexError):
        raise PiResumeError('PI_RESUME_INVALID_HISTORY') from None
    owner_path(Path(info['workspace']), True)
    # A missing bridge must not switch from lost per-session provider settings
    # to a global default. The coordinated receipt binds the prior agent dir.
    agent = resident_directory(Path(os.environ['PI_CODING_AGENT_DIR']))
    require(expected.get('expectedAgentDir') == str(agent), 'PI_RESUME_ENV_UNAVAILABLE')
    bridge = Path(_bridge(session_id))
    require(not agent.is_relative_to(bridge), 'PI_RESUME_ENV_UNAVAILABLE')
    # Normal Pi launch prefers a per-bridge agent directory. A surviving one
    # must not override the prior persistent directory bound by this recovery.
    local_agent = bridge / 'pi-agent'
    require(not local_agent.exists() and not local_agent.is_symlink(), 'PI_RESUME_ENV_UNAVAILABLE')
    _check_no_native(bridge)
    return {'bridge': bridge, 'history': bridge / 'sessions' / (stamp.replace(':', '-').replace('.', '-') + '_' + native + '.jsonl'),
            'backup': backup, 'data': data}


async def _recovery_controls(ctx):
    """Use the pinned SDK's current runner authorization, never backup headers."""
    from omnigent.cli_auth import databricks_request_headers
    from omnigent.conversation_browser import conversation_url
    from omnigent.runner._entry import _make_auth_token_factory, _runner_tunnel_binding_token_from_env
    from omnigent.runner.identity import RUNNER_TUNNEL_TOKEN_HEADER
    from omnigent.runner.tool_dispatch import build_native_relay_tool_schemas
    server_url = str(ctx.server_client.base_url).rstrip('/')
    require(server_url.startswith(('http://', 'https://')), 'PI_RESUME_ENV_UNAVAILABLE')
    factory = _make_auth_token_factory()
    token = await asyncio.to_thread(factory) if factory is not None else None
    headers = databricks_request_headers(server_url, bearer_token=token)
    binding = _runner_tunnel_binding_token_from_env()
    require(binding, 'PI_RESUME_ENV_UNAVAILABLE')
    headers[RUNNER_TUNNEL_TOKEN_HEADER] = binding
    tools = build_native_relay_tool_schemas(getattr(ctx.agent_spec, 'spec', ctx.agent_spec))
    return dict(session_id=ctx.session_id, server_url=server_url,
                conversation_url=conversation_url(server_url, ctx.session_id), auth_headers=headers, tools=tools)


def _restore_pi_history(plan):
    """Called under SDK preparation AND attachment locks; never overwrite."""
    bridge, history, data = plan['bridge'], plan['history'], plan['data']
    _check_no_native(bridge)
    require(not (bridge / 'woow-pi-cold-active').exists(), 'SESSION_BUSY')
    for name in ('inbox', 'sessions'):
        (bridge / name).mkdir(mode=0o700, exist_ok=True)
        owner_path(bridge / name, True)
    require(not list((bridge / 'inbox').iterdir()), 'SESSION_BUSY')
    existing = list((bridge / 'sessions').glob('*.jsonl'))
    require(not existing or existing == [history], 'PI_RESUME_HISTORY_CHANGED')
    if history.exists() or history.is_symlink():
        require(owner_path(history).read_bytes() == data, 'PI_RESUME_HISTORY_CHANGED')
    else:
        # Atomic publish without replacing a concurrently-created destination.
        fd, temporary = tempfile.mkstemp(prefix='.pi-restore-', dir=history.parent)
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(data); file.flush(); os.fsync(file.fileno())
            os.link(temporary, history, follow_symlinks=False)
        finally:
            Path(temporary).unlink(missing_ok=True)
    require(owner_path(history).read_bytes() == data, 'PI_RESUME_HISTORY_CHANGED')
    directory = os.open(history.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def prepare_pi_cold_resume(session_id, authorized_info, *, expected=None):
    """Return {body, receipt}; local files derive only from SDK/session identity.

    This is a bounded operator staging tool, not an automatic UI refresh action.
    The body is an INTERNAL spec carrier for launch_pi_strict, never a central
    terminal POST: central can wake a runner through normal initialization first.
    """
    try:
        info = authorized_info
        native = _validate_session(session_id, info)
        bridge = owner_path(_bridge(session_id), True)
        require(not bridge.stat().st_mode & 0o077, 'PI_RESUME_UNSAFE_PATH')
        with open(bridge / 'woow-pi-cold.lock', 'a+b', opener=lambda p, flags: os.open(p, flags | os.O_NOFOLLOW, 0o600)) as lock:
            owner_path(Path(lock.name))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PiResumeError('SESSION_BUSY') from None
            _check_no_native(bridge)
            require(not (bridge / 'woow-pi-cold-active').exists(), 'SESSION_BUSY')
            require(not list(owner_path(bridge / 'inbox', True).iterdir()), 'SESSION_BUSY')
            config_file = owner_path(bridge / 'config.json')
            config_bytes = config_file.read_bytes()
            require(json.loads(config_bytes)['sessionId'] == session_id, 'PI_RESUME_IDENTITY_CHANGED')
            sessions = owner_path(bridge / 'sessions', True)
            candidates = list(sessions.glob('*_' + native + '.jsonl'))
            require(len(candidates) == 1, 'PI_RESUME_PERSISTENCE_MISSING')
            history = owner_path(candidates[0])
            data = history.read_bytes()
            if expected is not None:
                require(expected.get('sessionId') == session_id and expected.get('nativeSessionId') == native
                        and expected.get('originalBytes') == len(data)
                        and expected.get('originalSHA256') == hashlib.sha256(data).hexdigest(), 'PI_RESUME_HISTORY_CHANGED')
            require(data and data.endswith(b'\n'), 'PI_RESUME_INVALID_HISTORY')
            rows = [json.loads(line) for line in data.splitlines()]
            header = rows[0]
            require(header.get('type') == 'session' and header.get('version') == 3 and header.get('id') == native
                    and all(r.get('id') and r.get('type') != 'session' for r in rows[1:]), 'PI_RESUME_INVALID_HISTORY')
            cwd = owner_path(Path(header['cwd']), True)
            require(info.get('workspace') == str(cwd), 'PI_RESUME_IDENTITY_CHANGED')
            if expected is not None:
                require(expected.get('workspace') == str(cwd), 'PI_RESUME_IDENTITY_CHANGED')
            executable = Path(shutil.which('pi') or '').resolve()
            package = executable.parent.parent.parent
            require(json.loads((package / 'package.json').read_text())['version'] == '0.99.1', 'PI_RESUME_VERSION_UNSUPPORTED')
            node = str(Path(shutil.which('node')).resolve())
            extension = owner_path(bridge / 'omnigent_pi_native_extension.js')
            require('woow_pi_mcp_refresh.cjs' in extension.read_text(), 'PI_RESUME_EXTENSION_NOT_READY')
            owner_path(bridge / 'woow_pi_mcp_refresh.cjs')
            env = {'OMNIGENT_PI_NATIVE_CONFIG': str(config_file), 'OMNIGENT_PI_NATIVE_BRIDGE_DIR': str(bridge)}
            # Preserve resident native agent directory; never synthesize credentials.
            agent = bridge / 'pi-agent'
            if agent.is_dir():
                env['PI_CODING_AGENT_DIR'] = str(owner_path(agent, True))
            elif os.environ.get('PI_CODING_AGENT_DIR'):
                env['PI_CODING_AGENT_DIR'] = str(resident_directory(Path(os.environ['PI_CODING_AGENT_DIR'])))
            if expected is not None and expected.get('restoreSnapshot') is True:
                require(env.get('PI_CODING_AGENT_DIR') == expected.get('expectedAgentDir'), 'PI_RESUME_ENV_UNAVAILABLE')
            # Snapshot outside the upstream orphan-cleanup root. Never rewrite
            # native history or any provider/auth/trust configuration.
            persistent = resident_directory(Path(os.environ['PI_AGENT_DATA_DIR']))
            snapshots = persistent / 'connectors' / 'pi-resume-snapshots' / bridge.name
            snapshots.mkdir(parents=True, mode=0o700, exist_ok=True)
            owner_path(snapshots, True)
            digest = hashlib.sha256(data).hexdigest()
            snapshot = snapshots / (digest + '.jsonl')
            if snapshot.exists():
                require(owner_path(snapshot).read_bytes() == data, 'PI_RESUME_HISTORY_CHANGED')
            else:
                _write(snapshot, data)
            ticket = {'version': 1, 'requestId': uuid.uuid4().hex, 'sessionId': session_id, 'nativeSessionId': native,
                      'bridgeDir': str(bridge), 'nativeFile': str(history), 'nativeBytes': len(data),
                      'nativeSHA256': digest, 'entryCount': len(rows), 'cwd': str(cwd),
                      'configSHA256': hashlib.sha256(config_bytes).hexdigest(), 'packageDir': str(package),
                      'expiresAt': int(time.time() * 1000) + 120000}
            launcher = bridge / 'pi_strict_launcher.mjs'
            _write(launcher, Path(__file__).with_name('pi_strict_launcher.mjs').read_bytes())
            ticket_file = bridge / ('woow-pi-cold-ticket-' + ticket['requestId'] + '.json')
            _write(ticket_file, json.dumps(ticket).encode())
            require(history.read_bytes() == data and config_file.read_bytes() == config_bytes, 'PI_RESUME_HISTORY_CHANGED')
            return {'ticket': ticket, 'body': {'terminal': 'pi', 'session_key': 'main', 'spec': {
                'command': node, 'args': [str(launcher), str(ticket_file)], 'cwd': str(cwd),
                'env': env, 'scrollback': 100000, 'tmux_allow_passthrough': True}},
                'receipt': {k: ticket[k] for k in ('sessionId', 'nativeSessionId', 'nativeBytes', 'nativeSHA256', 'entryCount')}}
    except PiResumeError:
        raise
    except Exception:
        raise PiResumeError('PI_RESUME_FAILED') from None


async def launch_pi_strict(ctx, *, authorized_info, busy, epoch, expected=None):
    """Bohr's explicit bound init dispatch calls this under its ensure lock.

    `busy()` covers runner turns/pending input/approval and `epoch()` increments
    on ordinary input admission. The shared dispatch must fence the cold session
    initialization before calling this; there is deliberately no central POST.
    Return only after the native extension confirms the original ID and bytes.
    Never catch this error and run the ordinary Pi initializer as fallback.
    """
    if expected and expected.get('restoreSnapshot') is True:
        from omnigent.harnesses.pi_native.bridge import write_extension_files
        from omnigent.native.native_bridge_common import bridge_dir_preparation_lock
        require(not busy(), 'SESSION_BUSY')
        generation = epoch()
        plan = inspect_pi_recovery(ctx.session_id, authorized_info, expected)
        controls = await _recovery_controls(ctx)
        require(not busy() and epoch() == generation, 'SESSION_BUSY')
        bridge = plan['bridge']
        # Keep attachment reservation across restoration, spawn, and native
        # confirmation. The stable SDK lock also excludes its orphan reaper.
        with ExitStack() as reservation:
            with bridge_dir_preparation_lock(bridge):
                plan = inspect_pi_recovery(ctx.session_id, authorized_info, expected)
                bridge.mkdir(mode=0o700, parents=True, exist_ok=True)
                owner_path(bridge, True)
                require(not bridge.stat().st_mode & 0o077, 'PI_RESUME_UNSAFE_PATH')
                reservation.enter_context(reserve_attachment(bridge))
                config = bridge / 'config.json'
                if config.exists() or config.is_symlink():
                    require(json.loads(owner_path(config).read_text()).get('sessionId') == ctx.session_id, 'PI_RESUME_IDENTITY_CHANGED')
                _restore_pi_history(plan)
                write_extension_files(bridge, **controls)
                _write(bridge / 'owner.pid', str(os.getpid()).encode())
            return await _launch_pi_strict_reserved(ctx, authorized_info=authorized_info,
                busy=busy, epoch=epoch, expected=expected)
    with reserve_attachment(Path(_bridge(ctx.session_id))):
        return await _launch_pi_strict_reserved(ctx, authorized_info=authorized_info,
            busy=busy, epoch=epoch, expected=expected)


async def _launch_pi_strict_reserved(ctx, *, authorized_info, busy, epoch, expected):
    from omnigent.harnesses.pi_native.bridge import pi_native_env_unset
    from omnigent.inner.datamodel import OSEnvSpec, TerminalEnvSpec
    from omnigent.native.native_bridge_common import bridge_dir_preparation_lock
    from omnigent.runner.resource_registry import PI_NATIVE_TERMINAL_ROLE
    try:
        from .woow_pi_native_resume import _exchange
    except ImportError:
        from native_resume import _exchange

    require(not busy(), 'SESSION_BUSY')
    generation = epoch()
    bridge = Path(_bridge(ctx.session_id))
    with bridge_dir_preparation_lock(bridge):
        prepared = prepare_pi_cold_resume(ctx.session_id, authorized_info, expected=expected)
        # The cold runner now owns this bridge. A dead prior owner marker would
        # let periodic maintenance delete the live resumed process's history.
        _write(bridge / 'owner.pid', str(os.getpid()).encode())
    spec = prepared['body']['spec']
    ticket = prepared['ticket']  # Immutable caller binding, never reread shared ticket state.
    agent = getattr(ctx.agent_spec, 'spec', ctx.agent_spec)
    agent_os = getattr(agent, 'os_env', None)
    require(agent_os is not None, 'PI_RESUME_ENV_UNAVAILABLE')
    require(not busy() and epoch() == generation, 'SESSION_BUSY')
    view = await ctx.resource_registry.launch_required_terminal(
        session_id=ctx.session_id, terminal_name='pi', session_key='main',
        resource_role=PI_NATIVE_TERMINAL_ROLE, parent_os_env=agent_os,
        spec=TerminalEnvSpec(os_env=OSEnvSpec(type='caller_process', cwd=spec['cwd'], sandbox=agent_os.sandbox),
            command=spec['command'], args=spec['args'], env=spec['env'],
            env_unset=pi_native_env_unset(os.environ), scrollback=100000,
            tmux_allow_passthrough=True, tmux_start_on_attach=False, keep_alive_after_exit=True))
    receipt = prepared['receipt']
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            native = receipt['nativeSessionId']
            probe = await _exchange(bridge, {'version': 1, 'action': 'probe', 'sessionId': ctx.session_id,
                'nativeSessionId': native, 'deadlineMs': int(time.time() * 1000) + 2000})
            if probe.get('state') == 'ready' and probe.get('nativeSessionId') == native:
                data = owner_path(Path(ticket['nativeFile'])).read_bytes()
                require(hashlib.sha256(data[:receipt['nativeBytes']]).hexdigest() == receipt['nativeSHA256'], 'PI_RESUME_HISTORY_CHANGED')
                opened = json.loads(owner_path(bridge / 'woow-pi-cold-opened.json').read_text())
                require(opened['nativeSessionId'] == native and opened['sessionId'] == ctx.session_id
                        and opened['originalSHA256'] == receipt['nativeSHA256']
                        and opened['requestId'] == ticket['requestId'], 'PI_RESUME_IDENTITY_CHANGED')
                terminal = ctx.resource_registry.terminal_registry.get(ctx.session_id, 'pi', 'main')
                require(terminal is not None, 'PI_RESUME_ATTACH_UNCONFIRMED')
                pane_pid = await asyncio.to_thread(terminal.pane_pid_sync)
                require(type(opened.get('pid')) is int and opened['pid'] == pane_pid
                        and opened['pid'] == _socket_peer_pid(bridge), 'PI_RESUME_IDENTITY_CHANGED')
                return view, opened
        except PiResumeError:
            raise
        except Exception:
            pass
        await asyncio.sleep(0.1)
    raise PiResumeError('PI_RESUME_ATTACH_UNCONFIRMED')


async def cold_resume(ctx, request, *, launch_kwargs):
    """Exact adapter for Bohr's woow_native_strict_bootstrap.strict_cold_launch.

    The shared loader has already validated and locked the private expiring
    owner-request envelope. This adapter binds its history bytes to fresh server
    detail and takes the same Pi ensure lock as ordinary init/ensure.
    """
    from omnigent.entities.session_resources import session_resource_view_to_dict

    require(request.get('engine') == 'pi' and request.get('sessionId') == ctx.session_id, 'PI_RESUME_INVALID_SESSION')
    locks = launch_kwargs['ensure_locks']
    async with locks.setdefault(ctx.session_id, asyncio.Lock()):
        registry = ctx.resource_registry
        require(registry.terminal_registry is not None, 'PI_RESUME_ENV_UNAVAILABLE')
        require(registry.terminal_registry.get(ctx.session_id, 'pi', 'main') is None, 'SESSION_BUSY')
        response = await ctx.server_client.get('/v1/sessions/' + ctx.session_id, params={'include_usage': 'false'})
        require(response.status_code == 200, 'PI_RESUME_SESSION_UNAVAILABLE')
        info = response.json()
        resolver = launch_kwargs.get('resolve_agent_spec')
        if resolver is not None:
            ctx = replace(ctx, agent_spec=await resolver())
        builder = launch_kwargs.get('build_context')
        if builder is not None:
            ctx = await builder(ctx)
        view, opened = await launch_pi_strict(ctx, authorized_info=info, expected=request,
            busy=lambda: registry.session_turn_is_active(ctx.session_id),
            epoch=lambda: registry.session_activity_epoch(ctx.session_id))
        ctx.publish_event(ctx.session_id, {'type': 'session.resource.created', 'resource': session_resource_view_to_dict(view)})
        return True, {'state': 'attached', 'sessionId': ctx.session_id, 'nativeSessionId': request['nativeSessionId'],
            'historyPrefixPreserved': True, 'originalBytes': request['originalBytes'],
            'originalSHA256': request['originalSHA256'], 'pid': opened['pid'], 'sameProcess': False, 'toolsVerified': False,
            'restoredFromSnapshot': request.get('restoreSnapshot') is True}
