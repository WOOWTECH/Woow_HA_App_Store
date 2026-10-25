"""0.2.1: the bounds of the four OpenDesign tools the add-on adds to its built-in MCP server (stdlib only).

Shared by the gateway's argument models (surface.py, management process) and the child's tool handlers (od_tools.py),
so both sides refuse the same things. Nothing here does I/O: tests/run.sh runs tests/unit/test_od_rules.py with the
system Python.

  read_file        file_path rules (FileInfo's, plus SECRET_* below), text only, at most READ_FILE_MAX_BYTES
  list_connectors  project_connectors(): a positive projection of GET /api/connectors
  create_project,  ChatStream: the OpenDesign 0.24.1 /api/chat event stream (measured 2026-10-15) parsed with
  send_message     bounded time, bytes and agent text into a projected result (chat_result())
  list_runs        run_rows(): 0.2.6, the 0.2.1-0.2.5 projection of GET /api/runs (see below)
"""
import fnmatch
import json
import re
import time

# --- arguments -------------------------------------------------------------------------------------------------------

UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
# The gateway's FileInfo pattern (vendored products.FileInfo): letters, digits, '_', '.', ' ', '/', '-'.
FILE_PATH = re.compile(r'[A-Za-z0-9_. /-]{1,256}')
# OpenDesign agent ids (GET /api/agents on 0.24.1: claude, codex, opencode, byok-opencode, pi, gemini...).
AGENT_ID_PATTERN = r'^[a-z][a-z0-9-]{0,63}$'
AGENT_ID = re.compile(AGENT_ID_PATTERN[1:-1])
DEFAULT_AGENT = 'claude'  # the PaaS server's default
PROMPT_MAX = 20000  # characters; the gateway accepts request bodies up to 16 MiB (256 KiB until 0.2.5)

# Secret-like names read_file refuses, on top of OpenDesign's own rules (it already refuses '..' and symlinks that
# leave the project). Compared case-insensitively with EVERY path segment, so a folder named like this is refused too.
# Any segment starting with '.' is refused: .env, .env.local, .git/, .ssh/, .aws/, .npmrc, .netrc, .git-credentials...
SECRET_PATTERNS = (
    '*.pem', '*.key', '*.p12', '*.pfx', '*.jks', '*.keystore', '*.kdbx', '*.gpg', '*.asc', '*.ovpn',
    'id_*',  # id_rsa, id_ed25519, id_ecdsa (and their .pub)
    '*.env', 'env.*',
    '*credential*', '*secret*', '*password*', '*passwd*', '*private*key*', '*apikey*', '*api_key*', '*api-key*',
    'htpasswd', 'shadow', 'authorized_keys', 'known_hosts',
)


def secret_like(path):
    """True when any segment of `path` is hidden ('.' first) or matches SECRET_PATTERNS (case-insensitive)."""
    for segment in path.split('/'):
        name = segment.casefold()
        if name.startswith('.') or any(fnmatch.fnmatchcase(name, pattern) for pattern in SECRET_PATTERNS):
            return True
    return False


def file_path_problem(path):
    """None when read_file may ask OpenDesign for `path`, else a plain reason (no quotes: the gateway shows it)."""
    if not isinstance(path, str) or not FILE_PATH.fullmatch(path):
        return 'path characters not allowed'
    if any(part in ('', '.', '..') for part in path.split('/')):
        return 'relative non-traversing path required'
    if secret_like(path):
        return 'secret-like file name refused'
    return None


# --- read_file ---------------------------------------------------------------------------------------------------------

READ_FILE_MAX_BYTES = 1024 * 1024
# C0 controls other than tab, LF, CR, form feed and ESC (ANSI colours in logs): their presence means binary data.
BINARY_CONTROLS = re.compile('[\x00-\x08\x0b\x0e-\x1a\x1c-\x1f\x7f]')


def listed_file(listing, path):
    """The size of `path` when the project's file list (GET /api/projects/<id>/files) shows it as a regular file.

    OpenDesign leaves hidden files and symlinks out of that list, so it is also the allowlist: read_file reads only what
    the project's own file list shows. None when it is not listed (or not a file)."""
    files = listing.get('files') if isinstance(listing, dict) else None
    if not isinstance(files, list):
        raise ValueError('unexpected file list')
    for entry in files:
        if isinstance(entry, dict) and entry.get('path') == path and entry.get('type') == 'file':
            size = entry.get('size')
            return size if type(size) is int and size >= 0 else -1
    return None


def decode_text(data):
    """The file's text, or None for anything but UTF-8 text (invalid UTF-8, NUL or other binary control bytes)."""
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return None
    if text.startswith('\ufeff'):
        text = text[1:]
    return None if BINARY_CONTROLS.search(text) else text


# --- list_connectors ---------------------------------------------------------------------------------------------------

CONNECTOR_LIMIT = 300
CONNECTOR_TOOL_LIMIT = 50
IDENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}')
CONTROL = re.compile('[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]')


def _ident(value):
    return value if isinstance(value, str) and IDENT.fullmatch(value) else None


def _label(value, limit=128):
    """Display text: a string without control or bidi characters, shortened to `limit`; anything else None."""
    if not isinstance(value, str):
        return None
    value = CONTROL.sub('', value).strip()
    return value[:limit] or None


def project_connectors(body):
    """Only these fields of each connector: id, name, provider, category, status, configured, toolCount and the tool
    NAMES. Never descriptions, schemas, auth details, accounts, URLs or local paths."""
    items = body.get('connectors') if isinstance(body, dict) else None
    if not isinstance(items, list):
        raise ValueError('unexpected connector list')
    connectors = []
    for item in items[:CONNECTOR_LIMIT]:
        if not isinstance(item, dict) or _ident(item.get('id')) is None:
            continue
        tools = item.get('tools')
        names = ([t.get('name') for t in tools if isinstance(t, dict)] if isinstance(tools, list)
                 else item.get('allowedToolNames') if isinstance(item.get('allowedToolNames'), list) else [])
        names = [name for name in names if _ident(name) is not None]
        auth = item.get('auth')
        configured = auth.get('configured') if isinstance(auth, dict) else None
        count = item.get('toolCount')
        entry = {'id': item['id'], 'name': _label(item.get('name')), 'provider': _ident(item.get('provider')),
                 'category': _label(item.get('category'), 64), 'status': _ident(item.get('status')),
                 'configured': configured if type(configured) is bool else None,
                 'toolCount': count if type(count) is int and count >= 0 else len(names),
                 'tools': names[:CONNECTOR_TOOL_LIMIT]}
        if len(names) > CONNECTOR_TOOL_LIMIT:
            entry['toolsTruncated'] = True
        connectors.append(entry)
    return {'total': len(items), 'connectors': connectors, 'truncated': len(items) > CONNECTOR_LIMIT}


# --- list_runs ---------------------------------------------------------------------------------------------------------

# 0.2.1-0.2.5 answered list_runs with the vendored apps/runtime/output_policy.rows(body, 'runs', RUN_FIELDS); the
# runtime pinned since 0.2.6 returns GET /api/runs unprojected (each run's error text, log paths...) and no longer has
# output_policy.py, so the same projection is kept here, line for line.
RUN_FIELDS = ('id', 'projectId', 'status')
RUN_LIMIT = 100
RUN_TEXT_LIMIT = 256


def run_rows(body):
    """{'runs': [only RUN_FIELDS of the first RUN_LIMIT runs], 'truncated': bool}: a field that is a string (shortened
    to RUN_TEXT_LIMIT), a number, a boolean or null is kept, anything else left out."""
    values = body.get('runs') if isinstance(body, dict) else body
    if not isinstance(values, list):
        raise ValueError('unexpected metadata envelope')
    return {'runs': [_run(row) for row in values[:RUN_LIMIT]], 'truncated': len(values) > RUN_LIMIT}


def _run(body):
    if not isinstance(body, dict):
        raise ValueError('unexpected metadata record')
    result = {}
    for key in RUN_FIELDS:
        value = body.get(key)
        if value is None or type(value) in (bool, int, float):
            result[key] = value
        elif type(value) is str:
            result[key] = value[:RUN_TEXT_LIMIT]
    return result


# --- create_project / send_message: the /api/chat event stream --------------------------------------------------------

# Until 0.2.5 the gateway ended every MCP response stream after 120 s (vendored gateway.STREAM_SECONDS); since 0.2.6
# (runtime 0.4.0) a tools/call reply may take up to gateway.CALL_SECONDS (330 s). OpenDesign writes a keepalive comment
# every 25 s and the child reads with a 30 s timeout, so a run is followed for at most about CHAT_SECONDS + 30 s, then
# the project is registered (the vendored client's timeouts: 5 s connect, 60 s read since 0.2.6): inside that limit.
CHAT_SECONDS = 75.0
CHAT_READ_SECONDS = 30.0
CHAT_MAX_BYTES = 8 * 1024 * 1024  # the whole event stream (agent stderr can be chatty)
CHAT_MAX_LINE = 256 * 1024
AGENT_TEXT_MAX = 8000  # characters of agent text returned
CODE = re.compile(r'[A-Za-z][A-Za-z0-9_.:-]{0,63}')
CATEGORY = re.compile(r'[a-z][a-z0-9_-]{0,31}')
END_STATUS = {'succeeded': 'succeeded', 'failed': 'failed', 'cancelled': 'cancelled', 'canceled': 'cancelled'}
HINTS = {
    'auth': ("The agent is not signed in. Sign in from the add-on's CLI Terminal (or OpenDesign settings), or use "
             "another agent_id from list_agents."),
    'AGENT_UNAVAILABLE': 'Unknown or unavailable agent_id: call list_agents and use an id whose available is true.',
}
GENERIC_HINT = 'The agent run failed. Open the project in OpenDesign to see the details.'
WAITING_NOTE = ('Stopped waiting for the agent; the run may still be going in OpenDesign. Check list_runs or '
                'list_project_files later.')


class ChatStream:
    """Incremental parser of an OpenDesign 0.24.1 /api/chat SSE response. feed() returns False once the caller must
    stop reading: the run ended (event `end`), the deadline passed, or a byte bound was reached.

    Events used (2026-10-15 measurement): start {runId, projectId, cwd...}; agent {type: text_delta, delta};
    error {message, error: {code, message, details} | "<string>"}; run_retry_finished {error_code, failure_category};
    end {status, code, failureCategory, failureAction}. Everything else (diagnostic, stderr, agent status/usage...) and
    every other field (cwd, messages, details, URLs) is ignored, never returned."""

    def __init__(self, deadline=None, max_bytes=CHAT_MAX_BYTES, text_max=AGENT_TEXT_MAX, clock=time.monotonic):
        self.clock = clock
        self.deadline = clock() + CHAT_SECONDS if deadline is None else deadline
        self.max_bytes, self.text_max = max_bytes, text_max
        self.received = 0
        self.pending = b''
        self.event, self.data = None, []
        self.run_id = self.project_id = None
        self.text, self.text_length = [], 0
        self.error_code = self.category = None
        self.end = None  # the end event's payload
        self.stopped = None  # 'deadline' | 'size' | 'stream'

    def feed(self, chunk):
        if self.end is not None or self.stopped:
            return False
        self.received += len(chunk)
        if self.received > self.max_bytes:
            self.stopped = 'size'
            return False
        self.pending += chunk
        while self.end is None:
            index = self.pending.find(b'\n')
            if index < 0:
                break
            line, self.pending = self.pending[:index], self.pending[index + 1:]
            self._line(line[:-1] if line.endswith(b'\r') else line)
        if self.end is None and len(self.pending) > CHAT_MAX_LINE:
            self.stopped = 'size'
            return False
        if self.end is None and self.clock() >= self.deadline:
            self.stopped = 'deadline'
            return False
        return self.end is None

    def interrupted(self):
        """The stream broke or closed early (the caller saw a transport error or end of body)."""
        if self.end is None and not self.stopped:
            self.stopped = 'stream'

    def _line(self, line):
        if not line:
            if self.data:
                self._dispatch(self.event or 'message', b'\n'.join(self.data))
            self.event, self.data = None, []
        elif line.startswith(b'data:'):
            value = line[5:]
            self.data.append(value[1:] if value.startswith(b' ') else value)
        elif line.startswith(b'event:'):
            self.event = line[6:].strip().decode('ascii', 'replace')
        # id:, retry:, comments (': keepalive') and anything else: ignored

    def _dispatch(self, event, raw):
        try:
            payload = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return
        if not isinstance(payload, dict):
            return
        if event == 'start':
            if isinstance(payload.get('runId'), str) and UUID.fullmatch(payload['runId']):
                self.run_id = payload['runId']
            if isinstance(payload.get('projectId'), str) and UUID.fullmatch(payload['projectId']):
                self.project_id = payload['projectId']
        elif event == 'agent':
            if payload.get('type') == 'text_delta' and isinstance(payload.get('delta'), str):
                delta = payload['delta']
                self.text_length += len(delta)
                room = self.text_max - sum(map(len, self.text))
                if room > 0:
                    self.text.append(delta[:room])
        elif event == 'error':
            error = payload.get('error')
            code = error.get('code') if isinstance(error, dict) else error
            self._error(code if isinstance(code, str) and CODE.fullmatch(code) else 'AGENT_ERROR')
        elif event == 'run_retry_finished':
            if isinstance(payload.get('error_code'), str) and CODE.fullmatch(payload['error_code']):
                self._error(payload['error_code'])
            self._category(payload.get('failure_category'))
        elif event == 'end':
            self.end = payload
            self._category(payload.get('failureCategory'))

    def _error(self, code):
        if self.error_code is None or self.error_code == 'AGENT_ERROR':
            self.error_code = code

    def _category(self, value):
        if self.category is None and isinstance(value, str) and CATEGORY.fullmatch(value):
            self.category = value

    def status(self):
        if self.end is not None:
            status = END_STATUS.get(self.end.get('status'))
            if status is None:
                status = 'succeeded' if self.end.get('code') == 0 and self.error_code is None else 'failed'
            return status
        if self.stopped in ('deadline', 'size'):
            return 'running' if self.run_id else 'unknown'
        return 'failed' if self.error_code else 'unknown'


def chat_result(stream, project_id):
    """The projected tool result: ids, status, bounded agent text, a public error code and fixed hint text."""
    status = stream.status()
    result = {'projectId': stream.project_id or project_id, 'runId': stream.run_id, 'status': status}
    if stream.text:
        result['agentResponse'] = ''.join(stream.text)
        if stream.text_length > stream.text_max:
            result['agentResponseTruncated'] = True
    if status == 'failed':
        result['errorCode'] = stream.error_code or 'AGENT_RUN_FAILED'
        if stream.category:
            result['failureCategory'] = stream.category
        result['hint'] = HINTS.get(stream.category) or HINTS.get(result['errorCode']) or GENERIC_HINT
    elif status in ('running', 'unknown'):
        result['note'] = WAITING_NOTE
    return result
