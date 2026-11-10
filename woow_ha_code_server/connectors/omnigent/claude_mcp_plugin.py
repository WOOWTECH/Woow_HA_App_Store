"""Same-process Claude 2.1.285 direct MCP refresh (legacy filename).

Uses the supported non-immediate /reload-plugins --force command. Missing direct
servers otherwise survive this command, so retired managed names receive a
workspace-local disabled inert definition with a different native config hash.
The native event loop queues reload behind active turns. No plugin registration,
credential changes, process restart, transcript synthesis, or model fallback.

refresh_claude requires an ALREADY ATTACHED original Omnigent native bridge.
Cold strict resume is a separate, explicit runner operation.
"""
import asyncio
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import uuid
import unicodedata

RELOAD_COMMAND = "/reload-plugins --force"
_UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}")
_NAME = re.compile(r"[A-Za-z0-9_-]+")
_HASH = re.compile(r"[a-f0-9]{64}")
NATIVE_APIS = frozenset({
    'BRIDGE_ID_LABEL_KEY', 'bridge_dir_for_bridge_id', 'read_claude_session_id',
    'read_transcript_path', '_bridge_injection_lock', '_bridge_injection_file_lock',
    '_serialize_bridge_injection', '_wait_for_tmux_info', 'has_pending_user_prompt',
    '_capture_pane', '_occupying_surface', '_is_box_rule', '_CLAUDE_PROMPT_GLYPH', '_run_tmux',
})

class ClaudeRefreshError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

PluginError = ClaudeRefreshError  # Compatibility for the isolated submission primitive.

def _check(ok, code):
    if not ok:
        raise ClaudeRefreshError(code)

def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def assert_native_contract(native):
    """Pinned 0.16 API surface, verified against its actual installed package."""
    _check(all(hasattr(native, name) for name in NATIVE_APIS), 'MCP_RUNTIME_UNSUPPORTED')
    constants = {'BRIDGE_ID_LABEL_KEY', '_CLAUDE_PROMPT_GLYPH'}
    _check(all(isinstance(getattr(native, name), str) for name in constants)
           and all(callable(getattr(native, name)) for name in NATIVE_APIS - constants), 'MCP_RUNTIME_UNSUPPORTED')


def claude_config_path(workspace, environment):
    """Claude 2.1.285 path rules; does not depend on a newer runner API.

    Resolve using the attached process's environment/cwd, never this connector's
    login home. Existing legacy .config.json takes precedence. Do not expand ~,
    interpret shell text, transfer credentials, or create a fallback config.
    """
    home = environment.get('HOME')
    _check(isinstance(home, str) and os.path.isabs(home), 'MCP_CONFIG_HOME_MISSING')
    directory = environment.get('CLAUDE_CONFIG_DIR')
    def resolved(base, name):
        value = os.path.normpath(os.path.join(base, name))
        return Path(value) if os.path.isabs(value) else Path(workspace) / value
    legacy_base = os.path.join(home, '.claude') if directory is None else directory
    legacy = resolved(unicodedata.normalize('NFC', legacy_base), '.config.json')
    if legacy.exists():
        return legacy
    suffix = '-custom-oauth' if environment.get('CLAUDE_CODE_CUSTOM_OAUTH_URL') else ''
    return resolved(directory or home, '.claude' + suffix + '.json')

def _owned(path, *, directory=False, private=False):
    s = Path(path).lstat()
    _check(s.st_uid == os.getuid() and not s.st_mode & (0o077 if private else 0o022)
           and (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)), "MCP_UNSAFE_CONFIG")
    return s

def _atomic(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".woow-mcp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write((_json(value) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

def tombstone(name):
    return {"type": "stdio", "command": "/bin/false", "args": ["woow-mcp-retired-v1", name]}

def merge_direct_config(existing, *, workspace, projected, managed_names, ledger, project_servers=None):
    """Pure plan. Preserve unrelated settings and explicit user disabled choices.

    The ledger belongs to this config/workspace, not one conversation. Local
    tombstones do not pollute the canonical user-scope import performed by sync.
    An unowned local/project override is refused rather than silently replaced.
    """
    names = set(managed_names)
    _check(all(isinstance(n, str) and _NAME.fullmatch(n) for n in names), "MCP_CONFIG_INVALID")
    _check("omnigent" not in names and set(projected) <= names, "MCP_RELAY_CONFLICT")
    _check(isinstance(existing, dict) and isinstance(ledger, dict), "MCP_CONFIG_INVALID")
    result = copy.deepcopy(existing)
    projects = result.setdefault("projects", {})
    project = projects.setdefault(workspace, {})
    local = project.setdefault("mcpServers", {})
    disabled = project.get("disabledMcpServers", [])
    _check(isinstance(local, dict) and isinstance(disabled, list) and all(isinstance(x, str) for x in disabled), "MCP_CONFIG_INVALID")
    retired_before = set(ledger.get("retired", []))
    ours_disabled = set(ledger.get("disabledOwned", []))
    _check(ours_disabled <= retired_before <= names, "MCP_OWNERSHIP_CHANGED")
    for name in retired_before:
        _check(local.get(name) == tombstone(name), "MCP_OWNERSHIP_CHANGED")
    for name in names:
        for scope in (local, project_servers or {}):
            if name in scope and not (scope is local and name in retired_before):
                _check(name in projected and scope[name] == projected[name], "MCP_DIRECT_SCOPE_CONFLICT")
    retired = names - set(projected)
    # Remove only preferences introduced by this helper, never the user's.
    disabled = [n for n in disabled if n not in (ours_disabled - retired)]
    owned_next = ours_disabled & retired
    for name in sorted(retired):
        local[name] = tombstone(name)
        if name not in disabled:
            disabled.append(name)
            owned_next.add(name)
    for name in retired_before - retired:
        local.pop(name)
    project["disabledMcpServers"] = disabled
    servers = result.setdefault("mcpServers", {})
    _check(isinstance(servers, dict), "MCP_CONFIG_INVALID")
    for name in names:
        servers.pop(name, None)
        if name in projected:
            servers[name] = copy.deepcopy(projected[name])
    return result, {"version": 1, "workspace": workspace, "retired": sorted(retired),
                    "disabledOwned": sorted(owned_next)}

@contextmanager
def _directory_lock(path):
    # Claude 2.1.285 uses proper-lockfile's mkdir(<config>.lock) protocol.
    # Never steal/delete an existing lock. Our bounded write is below its stale
    # threshold; model/provider work and synchronize() run outside this lock.
    path = Path(path)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        raise ClaudeRefreshError("MCP_CONFIG_BUSY") from None
    identity = path.stat()
    try:
        yield
    finally:
        now = path.lstat()
        if (now.st_dev, now.st_ino) == (identity.st_dev, identity.st_ino):
            path.rmdir()


@contextmanager
def _injection_lock(native, bridge):
    """Use upstream locks without waiting past the connector request lifetime."""
    thread_lock = native._bridge_injection_lock(bridge)
    _check(thread_lock.acquire(blocking=False), 'MCP_SUBMISSION_BUSY')
    file_lock = native._bridge_injection_file_lock(bridge)
    acquired = False
    try:
        try:
            file_lock.acquire(timeout=0)
            acquired = True
        except Exception:
            raise ClaudeRefreshError('MCP_SUBMISSION_BUSY') from None
        yield
    finally:
        if acquired:
            file_lock.release()
        thread_lock.release()

def _composer_text(native, pane):
    """Require a complete framed composer, including every continuation row."""
    if not pane.strip() or native._occupying_surface(pane) is not None:
        return None
    lines = pane.splitlines()
    rules = [i for i, line in enumerate(lines) if native._is_box_rule(line)]
    if len(rules) < 2:
        return None
    inside = lines[rules[-2] + 1:rules[-1]]
    if not inside or not inside[0].strip().startswith(native._CLAUDE_PROMPT_GLYPH):
        return None
    inside[0] = inside[0].strip()[len(native._CLAUDE_PROMPT_GLYPH):]
    return "\n".join(inside).strip()


def _input_text(native, socket, target):
    pane = native._capture_pane(socket, target)
    value = _composer_text(native, pane)
    if not value:
        return value
    # Pinned TUI displays its generated suggestion as a dim placeholder in an
    # empty draft. Plain capture loses that distinction. Recognize only one
    # wholly dim row, with no ordinary typed text, and matching plain capture.
    # Never erase text or accept a multiline/ambiguous rendering as empty.
    try:
        result = subprocess.run(['tmux', '-S', socket, 'capture-pane', '-e', '-p', '-t', target],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return value
    if result.returncode:
        return value
    ansi = result.stdout
    plain = re.sub(r'\x1b\[[0-9;]*m', '', ansi)
    if _composer_text(native, plain) != value:
        return None
    rules = [i for i, line in enumerate(plain.splitlines()) if native._is_box_rule(line)]
    inside = ansi.splitlines()[rules[-2] + 1:rules[-1]]
    if len(inside) == 1 and native._CLAUDE_PROMPT_GLYPH in inside[0]:
        tail = inside[0].split(native._CLAUDE_PROMPT_GLYPH, 1)[1]
        match = re.fullmatch(r'\s*\x1b\[2m([^\x1b]*)\x1b\[(?:0|22)m\s*', tail)
        if match and match[1].strip() == value:
            return ''
    return value


def submit_native_reload(bridge_dir, *, native_session_id, eligibility,
                         claude_version, native=None, timeout=5.0,
                         _locked=False, _identity_check=lambda: None):
    """Submit exactly one supported command without Escape, clear, or fallback.

    Command-only integration primitive used by refresh_claude. Claude
    2.1.285 declares reload-plugins as non-immediate local: its submit controller
    enqueues it when the turn guard is active. The native event loop therefore
    owns busy handling; this function never interrupts a turn to obtain idleness.

    The runner's existing cross-process injection lock serializes other runner
    inputs. A person typing directly into tmux is outside that lock: occupied,
    changed or unrecognizable input is refused, never erased. An adapter must
    provide exclusive terminal input while this brief submission is in progress.
    Pending approval/dialogs are refused. A missing commit/submit observation is
    UNKNOWN; never resend automatically and never turn it into a model prompt.
    """
    _check(eligibility.get("state") == "eligible" and
           eligibility.get("nativeSessionId") == native_session_id, "MCP_CLAUDE_NOT_ELIGIBLE")
    _check(claude_version == "2.1.285", "MCP_CLAUDE_CLI_UNVERIFIED")
    if native is None:
        from omnigent.harnesses.claude_native import bridge as native
    bridge_dir = Path(bridge_dir)

    def perform(owned_bridge):
        _identity_check()
        _check(native.read_claude_session_id(owned_bridge) == native_session_id,
               "MCP_CLAUDE_NATIVE_ID_CHANGED")
        info = native._wait_for_tmux_info(owned_bridge, timeout_s=1)
        socket, target = info["socket_path"], info["tmux_target"]
        _check(not native.has_pending_user_prompt(owned_bridge), "MCP_CLAUDE_APPROVAL_PENDING")
        _check(_input_text(native, socket, target) == "", "MCP_CLAUDE_COMPOSER_OCCUPIED")
        # No secret command arguments; only this constant command is ever typed.
        buffer_name = "woow-mcp-" + uuid.uuid4().hex
        fd, temporary = tempfile.mkstemp(prefix=".woow-reload-", dir=owned_bridge)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(RELOAD_COMMAND.encode())
            native._run_tmux(socket, "load-buffer", "-b", buffer_name, temporary)
            _check(not native.has_pending_user_prompt(owned_bridge), "MCP_CLAUDE_APPROVAL_PENDING")
            _check(_input_text(native, socket, target) == "",
                   "MCP_CLAUDE_COMPOSER_OCCUPIED")
            native._run_tmux(socket, "paste-buffer", "-p", "-d", "-b", buffer_name, "-t", target)
        finally:
            Path(temporary).unlink(missing_ok=True)
            try:
                native._run_tmux(socket, "delete-buffer", "-b", buffer_name)
            except Exception:
                pass  # Already deleted by paste-buffer -d, or load failed.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _check(not native.has_pending_user_prompt(owned_bridge), "MCP_CLAUDE_APPROVAL_PENDING")
            current = _input_text(native, socket, target)
            if current == RELOAD_COMMAND:
                break
            _check(current in ("", None), "MCP_CLAUDE_COMPOSER_CHANGED")
            time.sleep(0.05)
        else:
            raise PluginError("MCP_CLAUDE_DRAFT_UNCONFIRMED")
        # One Enter only. A timeout after this point is never safe to retry.
        time.sleep(0.1)
        _check(not native.has_pending_user_prompt(owned_bridge), "MCP_CLAUDE_APPROVAL_PENDING")
        _check(native.read_claude_session_id(owned_bridge) == native_session_id,
               "MCP_CLAUDE_NATIVE_ID_CHANGED")
        _check(_input_text(native, socket, target) == RELOAD_COMMAND,
               "MCP_CLAUDE_COMPOSER_CHANGED")
        _identity_check()
        native._run_tmux(socket, "send-keys", "-t", target, "Enter")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _check(native.read_claude_session_id(owned_bridge) == native_session_id,
                   "MCP_CLAUDE_NATIVE_ID_CHANGED")
            if _input_text(native, socket, target) == "":
                return {"state": "submitted", "nativeSessionId": native_session_id,
                        "reloadVerified": False, "toolsVerified": False}
            time.sleep(0.05)
        return {"state": "submission-unknown", "nativeSessionId": native_session_id,
                "retrySafe": False, "reloadVerified": False, "toolsVerified": False}

    try:
        return perform(bridge_dir) if _locked else native._serialize_bridge_injection(perform)(bridge_dir)
    except PluginError:
        raise
    except Exception:
        # Upstream tmux errors may contain captured private text. Never propagate.
        raise PluginError("MCP_CLAUDE_NATIVE_SUBMIT_FAILED") from None


def native_reload_receipt(records, *, native_session_id):
    """Read newly appended native records only; never accept assistant prose.

    The caller baselines its transcript cursor before submission and confirms
    unchanged native identity/PID separately. A summary is not an MCP call proof.
    """
    command_seen = False
    for record in records:
        if record.get("sessionId") != native_session_id:
            continue
        # Installed 2.1.285 persists the submitted slash command as a user
        # message, then its trusted native result as system/local_command.
        # A user marker alone is never a receipt; assistant prose cannot supply
        # the result. Records must be read from the native JSONL after the
        # adapter's saved cursor, not from client-submitted API items.
        message = record.get("message", {})
        is_command_input = record.get("type") == "user" and isinstance(message, dict)
        is_native_output = record.get("type") == "system" and record.get("subtype") == "local_command"
        if not (is_command_input or is_native_output):
            continue
        content = message.get("content", "") if is_command_input else record.get("content", "")
        if not isinstance(content, str):
            continue
        if "<command-name>" in content:
            command_seen = ("<command-name>/reload-plugins</command-name>" in content and
                            "<command-args>--force</command-args>" in content)
        elif is_native_output and command_seen and content.startswith("<local-command-stdout>Reloaded:"):
            if "errors during load" in content or "error during load" in content:
                return {"state": "reload-failed", "toolsVerified": False}
            if "plugin MCP server" not in content or "next session" in content:
                return {"state": "reload-incomplete", "toolsVerified": False}
            return {"state": "reloaded", "nativeSessionId": native_session_id,
                    "reloadVerified": True, "toolsVerified": False}
    return {"state": "receipt-pending", "reloadVerified": False, "toolsVerified": False}


def _process_identity(pid):
    proc = Path('/proc', str(pid))
    _check(proc.stat().st_uid == os.getuid(), 'MCP_NATIVE_ID_CHANGED')
    # Parenthesized comm may contain spaces; starttime is field22.
    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': pid, 'startTicks': fields[19]}


def _assert_process_bridge(bridge, args, environment):
    """Pinned launchers bind through env or the exact private hooks settings file."""
    declared = environment.get('HARNESS_CLAUDE_NATIVE_BRIDGE_DIR')
    if declared:
        _check(Path(declared).samefile(bridge), 'MCP_SESSION_NOT_LOCAL')
        return
    # Pinned 0.16 strict launcher passes --settings, rather than exporting the
    # bridge directory into Claude's exec environment. Require its exact file,
    # ownership and actual native hook binding; never infer from cwd alone.
    _check(args.count('--settings') == 1, 'MCP_SESSION_NOT_LOCAL')
    offset = args.index('--settings')
    _check(offset + 1 < len(args), 'MCP_SESSION_NOT_LOCAL')
    settings = Path(args[offset + 1])
    _owned(settings, private=True)
    _check(settings.samefile(bridge / 'claude-settings.json'), 'MCP_SESSION_NOT_LOCAL')
    hooks = json.loads(settings.read_text()).get('hooks', {})
    _check(all(str(bridge) in json.dumps(hooks.get(event, [])) for event in ('SessionStart', 'Stop')),
           'MCP_SESSION_NOT_LOCAL')


def _native_process(native, bridge, native_id):
    info = native._wait_for_tmux_info(bridge, timeout_s=1)
    result = subprocess.run(['tmux', '-S', info['socket_path'], 'display-message', '-p',
                             '-t', info['tmux_target'], '#{pane_pid}'], capture_output=True, timeout=3)
    _check(result.returncode == 0 and result.stdout.strip().isdigit(), 'MCP_NATIVE_UNAVAILABLE')
    todo, seen, candidates = [int(result.stdout)], set(), []
    while todo and len(seen) < 128:
        pid = todo.pop()
        if pid in seen:
            continue
        seen.add(pid)
        proc = Path('/proc', str(pid))
        try:
            ident = _process_identity(pid)
            exe = (proc / 'exe').resolve(strict=True)
            if exe.name in ('claude', 'claude.exe'):
                candidates.append((ident, exe))
            todo.extend(map(int, (proc / 'task' / str(pid) / 'children').read_text().split()))
        except FileNotFoundError:
            continue
    _check(len(candidates) == 1, 'MCP_NATIVE_UNAVAILABLE')
    ident, exe = candidates[0]
    proc = Path('/proc', str(ident['pid']))
    # Read environment privately for path resolution only. Never return it.
    env = dict(part.decode().split('=', 1) for part in (proc / 'environ').read_bytes().split(b'\0') if b'=' in part)
    args = [part.decode() for part in (proc / 'cmdline').read_bytes().split(b'\0') if part]
    _assert_process_bridge(bridge, args, env)
    for flag in ('--resume', '--session-id'):
        if flag in args:
            offset = args.index(flag)
            _check(offset + 1 < len(args) and args[offset + 1] == native_id, 'MCP_NATIVE_ID_CHANGED')
    version = subprocess.run([str(exe), '--version'], capture_output=True, timeout=5)
    _check(version.returncode == 0 and re.match(rb'2\.1\.285(?:\s|$)', version.stdout), 'MCP_CLI_UNVERIFIED')
    workspace = str((proc / 'cwd').resolve(strict=True))
    transcript = native.read_transcript_path(bridge)
    _check(transcript is not None and transcript.name == native_id + '.jsonl', 'MCP_PERSISTENCE_MISSING')
    _owned(transcript)
    raw = transcript.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line]
    _check(rows and all(row.get('sessionId', native_id) == native_id for row in rows)
           and any(row.get('cwd') == workspace for row in rows), 'MCP_PERSISTENCE_MISMATCH')
    config = claude_config_path(workspace, env)
    _owned(config)
    return {'identity': ident, 'workspace': workspace, 'config': config, 'transcript': transcript,
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'inode': transcript.stat().st_ino}


def _assert_same(native, bridge, native_id, context):
    _check(native.read_claude_session_id(bridge) == native_id
           and _process_identity(context['identity']['pid']) == context['identity'], 'MCP_NATIVE_ID_CHANGED')
    transcript = context['transcript']
    _owned(transcript)
    _check(transcript.stat().st_ino == context['inode'], 'MCP_HISTORY_CHANGED')
    with transcript.open('rb') as stream:
        prefix = stream.read(context['size'])
    _check(len(prefix) == context['size'] and hashlib.sha256(prefix).hexdigest() == context['sha256'],
           'MCP_HISTORY_CHANGED')


def _new_records(context, cursor):
    with context['transcript'].open('rb') as stream:
        stream.seek(cursor)
        data = stream.read()
    # A native writer may be midway through its final line.
    return [json.loads(line) for line in data[:data.rfind(b'\n') + 1].splitlines() if line]


def _poll_receipt(native, bridge, native_id, context, pending, seconds=4):
    deadline = time.monotonic() + seconds
    while True:
        _assert_same(native, bridge, native_id, context)
        receipt = native_reload_receipt(_new_records(context, pending['cursor']), native_session_id=native_id)
        if receipt['state'] != 'receipt-pending' or time.monotonic() >= deadline:
            return receipt
        time.sleep(.2)


def _prepare_direct(context, data):
    config = context['config']
    managed_path = data / 'shared/managed.json'
    canonical = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(data / 'claude'))) / '.claude.json'
    for path in (managed_path, canonical):
        _owned(path)
    # Serialize with canonical sync and with the pinned native config writer.
    with _directory_lock(data / 'shared/.sync-lock'), _directory_lock(str(config) + '.lock'):
        managed = json.loads(managed_path.read_text())
        names = managed.get('managedServers', managed.get('servers', []))
        _check(isinstance(names, list), 'MCP_CONFIG_INVALID')
        source = json.loads(canonical.read_text()).get('mcpServers', {})
        projected = {name: source[name] for name in names if name in source}
        before = config.read_bytes()
        existing = json.loads(before)
        directory = config.parent / '.woow-mcp-refresh'
        directory.mkdir(mode=0o700, exist_ok=True)
        _owned(directory, directory=True, private=True)
        ledger_path = directory / (hashlib.sha256(context['workspace'].encode()).hexdigest() + '.json')
        ledger = {}
        if ledger_path.exists():
            _owned(ledger_path, private=True)
            ledger = json.loads(ledger_path.read_text())
            _check(ledger.get('workspace') == context['workspace'], 'MCP_OWNERSHIP_CHANGED')
        project_file = Path(context['workspace']) / '.mcp.json'
        project_servers = {}
        if project_file.exists():
            _owned(project_file)
            project_servers = json.loads(project_file.read_text()).get('mcpServers', {})
        rendered, next_ledger = merge_direct_config(existing, workspace=context['workspace'],
            projected=projected, managed_names=names, ledger=ledger, project_servers=project_servers)
        _check(config.read_bytes() == before, 'MCP_CONFIG_CHANGED')
        # Private exact rollback material; never restore it wholesale over later writes.
        backup = directory / ('before-' + uuid.uuid4().hex + '.json')
        _atomic(backup, existing)
        # A crash between config and ledger publication is refused on the next
        # attempt as an unowned local override. It never grants permissions.
        _atomic(config, rendered)
        _atomic(ledger_path, next_ledger)
        return {'retiredCount': len(next_ledger['retired']), 'configuredCount': len(projected)}


def _await_native_config_poll(context):
    """Let pinned Claude's 1000ms external-config poll run before reload.

    The reload command reads the native cached global config. An immediate
    submission can acknowledge a reload of the previous config. Two poll
    intervals avoid that publication race; this is not an inventory receipt.
    Refuse concurrent MCP edits, and retain the normal identity check afterward.
    """
    def fingerprint():
        value = json.loads(context['config'].read_text())
        project = value.get('projects', {}).get(context['workspace'], {})
        return json.dumps([value.get('mcpServers', {}), project.get('mcpServers', {}),
            project.get('disabledMcpServers', []), project.get('enabledMcpjsonServers', []),
            project.get('disabledMcpjsonServers', [])], sort_keys=True)
    expected = fingerprint()
    time.sleep(2.0)
    _check(fingerprint() == expected, 'MCP_CONFIG_CHANGED')


def _refresh_claude(session_id, info, *, sync):
    from omnigent.harnesses.claude_native import bridge as native
    assert_native_contract(native)
    native_id = info.get('external_session_id')
    _check(isinstance(native_id, str) and _UUID.fullmatch(native_id), 'MCP_PERSISTENCE_MISSING')
    bridge_id = (info.get('labels') or {}).get(native.BRIDGE_ID_LABEL_KEY) or session_id
    bridge = Path(native.bridge_dir_for_bridge_id(bridge_id))
    _owned(bridge, directory=True, private=True)
    _check(native.read_claude_session_id(bridge) == native_id, 'MCP_NATIVE_ID_CHANGED')
    for name in ('state.json', 'tmux.json'):
        _owned(bridge / name)
    pending_path = bridge / 'woow-claude-mcp-pending.json'

    def perform(owned_bridge):
        context = _native_process(native, bridge, native_id)
        pending = None
        if pending_path.exists():
            _owned(pending_path, private=True)
            pending = json.loads(pending_path.read_text())
            _check(pending['nativeSessionId'] == native_id and pending['identity'] == context['identity'],
                   'MCP_PENDING_NATIVE_CHANGED')
            # Reconstruct the earlier cursor baseline, not the new call's tail.
            context.update(size=pending['cursor'], sha256=pending['prefixSha256'], inode=pending['inode'])
            _assert_same(native, bridge, native_id, context)
        else:
            _check(not native.has_pending_user_prompt(bridge), 'MCP_APPROVAL_PENDING')
            terminal = native._wait_for_tmux_info(bridge, timeout_s=1)
            _check(_input_text(native, terminal['socket_path'], terminal['tmux_target']) == '',
                   'MCP_COMPOSER_OCCUPIED')
            try:
                digest = sync()
            except Exception:
                raise ClaudeRefreshError('MCP_SYNC_FAILED') from None
            _check(isinstance(digest, str) and _HASH.fullmatch(digest), 'MCP_SYNC_FAILED')
            _assert_same(native, bridge, native_id, context)
            counts = _prepare_direct(context, Path(os.environ.get('PI_AGENT_DATA_DIR', '/data/pi-agent')))
            _await_native_config_poll(context)
            _assert_same(native, bridge, native_id, context)
            # Only commands after config publication can satisfy this request.
            # Snapshot complete lines; an active native writer may be mid-line.
            current = context['transcript'].read_bytes()
            complete = current[:current.rfind(b'\n') + 1]
            _check(len(complete) >= context['size'], 'MCP_HISTORY_CHANGED')
            context.update(size=len(complete), sha256=hashlib.sha256(complete).hexdigest())
            pending = {'version': 1, 'nativeSessionId': native_id, 'identity': context['identity'],
                       'cursor': context['size'], 'prefixSha256': context['sha256'], 'inode': context['inode'],
                       'configurationHash': digest, 'state': 'submission-unknown', **counts}
            _atomic(pending_path, pending)  # Persist before possible Enter; no blind resubmission.
            submitted = submit_native_reload(bridge, native_session_id=native_id,
                eligibility={'state': 'eligible', 'nativeSessionId': native_id}, claude_version='2.1.285',
                native=native, _locked=True, _identity_check=lambda: _assert_same(native, bridge, native_id, context))
            pending['state'] = submitted['state']
            _atomic(pending_path, pending)
        receipt = _poll_receipt(native, bridge, native_id, context, pending)
        _check(receipt['state'] not in ('reload-failed', 'reload-incomplete'), 'MCP_RELOAD_FAILED')
        applied = receipt['state'] == 'reloaded'
        if applied:
            _atomic(bridge / 'woow-claude-mcp-last.json', {**pending, 'state': 'reloaded'})
            pending_path.unlink()
        return {'sessionId': session_id, 'engine': 'claude', 'refresh': {
            'state': 'reloaded' if applied else 'queued' if pending['state'] == 'submitted' else 'submission-unknown',
            'method': 'native-config-reload', 'historyPreserved': True, 'nativeSessionId': native_id,
            'configurationHash': pending['configurationHash'], 'reloadVerified': applied,
            'inventoryVerified': False, 'toolsVerified': False, 'retrySafe': False,
            'retiredCount': pending['retiredCount'], 'configuredCount': pending['configuredCount']}}
    with _injection_lock(native, bridge):
        return perform(bridge)


async def refresh_claude(session_id, info, *, sync):
    """Called only after the connector's existing edit/local/unarchived checks.

    Native queue handles a turn racing the UI idle check. A pending request is
    inspected on repeat calls, never injected again. No ensure/retry/resume here.
    All failures are fixed codes; private native/config text must never escape.
    """
    try:
        _check(isinstance(session_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{8,128}', session_id)
               and isinstance(info, dict), 'MCP_INVALID_REQUEST')
        return await asyncio.to_thread(_refresh_claude, session_id, info, sync=sync)
    except ClaudeRefreshError:
        raise
    except Exception:
        raise ClaudeRefreshError('MCP_REFRESH_FAILED') from None
