"""MCP client probe for the built-in OpenDesign MCP server (test-only; prints results, never the token).

usage: MCP_TOKEN=... python mcp_probe.py <base-url> <check> [...]
checks:
  auth      no/wrong Bearer -> 401; Bearer + Origin -> 403
  bearer    initialize -> initialized -> tools/list -> tools/call health, version, list_projects, list_agents (Bearer)
  secret    the same over /private_<token>/mcp with an Origin header (Claude.ai style); wrong secret -> 404
  tools     only print the tools/list names (Bearer)
  health    initialize + tools/call health only (Bearer); exit 0 even if the tool reports an error
  status    HTTP status of a Bearer initialize only (token lifecycle checks)
  ready     GET /health/ready
  claudeai  the real Claude.ai connector sequence over /private_<token>/mcp (UA Claude-User, clientInfo
            Anthropic/ClaudeAI): server/discover (MCP-Protocol-Version 2026-07-28, params only _meta), initialize
            2025-11-25 with _meta.traceparent and capabilities.extensions, _meta on every allowed method, unknown
            request -> 200 JSON-RPC -32601, unknown notification -> 202
  refusals  0.1.14 refused tools/call -> HTTP 200 JSON-RPC errors with a reason and no input echo (unknown tool,
            write not granted, invalid arguments); a tools/call without a session stays 403 (Bearer)
  starting  initialize -> tools/list -> tools/call health in a loop while the daemon (re)starts (Bearer); prints
            each attempt's HTTP status / JSON-RPC outcome
  0.2.1 (the 15 PaaS tools, writers on by default; no agent is signed in on the test system, so no run costs anything):
  create        create_project with agent "claude" (not signed in: a failed run) -> projected result; list_projects
                shows the project. Prints project=<uuid> on its own line for the caller
  files=<uuid>  list_project_files, get_file_info, read_file: text ok, nested ok, .env refused by the gateway,
                binary / too large / unknown refused by the child with a public code
  chat=<uuid>   send_message as "claude" (failed: AGENT_AUTH_REQUIRED), as an unknown agent (AGENT_UNAVAILABLE), to an
                unknown project (PROJECT_NOT_FOUND); create_project as byok-opencode (refused by OpenDesign: no run)
  connectors    list_connectors: count, fields, no URL / path / token text
  runs          list_runs (vendored projection; failed in 0.2.0)
  delete=<uuid> delete_project (on by default), then list_projects without it
Outputs one JSON line per check. The token comes only from MCP_TOKEN and is redacted from all output.
"""
import json
import os
import sys

import httpx

TOKEN = os.environ.get('MCP_TOKEN', '')
ACCEPT = 'application/json, text/event-stream'
PROTOCOL = '2025-06-18'


def redact(text):
    return text.replace(TOKEN, '[REDACTED]') if TOKEN else text


def out(**fields):
    print(redact(json.dumps(fields, ensure_ascii=False, sort_keys=True)), flush=True)


def rpc_result(response):
    """Parse a JSON or SSE reply into the JSON-RPC message."""
    media = response.headers.get('content-type', '').split(';')[0]
    if media == 'text/event-stream':
        for event in response.text.split('\n\n'):
            data = '\n'.join(line[5:].lstrip() for line in event.splitlines() if line.startswith('data:'))
            if data.strip():
                return json.loads(data)
        raise ValueError('no SSE data')
    return response.json()


class Session:
    def __init__(self, client, url, headers):
        self.client, self.url, self.headers, self.next_id = client, url, dict(headers), 1

    def post(self, message, extra=None):
        headers = {'Accept': ACCEPT, 'Content-Type': 'application/json', **self.headers, **(extra or {})}
        return self.client.post(self.url, headers=headers, content=json.dumps(message))

    def request(self, method, params=None):
        message = {'jsonrpc': '2.0', 'id': self.next_id, 'method': method}
        if params is not None:
            message['params'] = params
        self.next_id += 1
        response = self.post(message)
        response.raise_for_status()
        return rpc_result(response)

    def initialize(self):
        response = self.post({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
            'protocolVersion': PROTOCOL, 'capabilities': {}, 'clientInfo': {'name': 'team-ha-mcp-probe', 'version': '0'}}})
        response.raise_for_status()
        result = rpc_result(response)['result']
        self.headers['mcp-session-id'] = response.headers['mcp-session-id']
        self.headers['mcp-protocol-version'] = result['protocolVersion']
        note = self.post({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return result, note.status_code

    def call(self, name, arguments=None):
        reply = self.request('tools/call', {'name': name, 'arguments': arguments or {}})
        result = reply.get('result') or {}
        text = ''.join(item.get('text', '') for item in result.get('content', []) if item.get('type') == 'text')
        return {'isError': bool(result.get('isError')), 'error': reply.get('error'), 'text': text[:400]}

    def close(self):
        self.client.delete(self.url, headers=self.headers)


def flow(client, url, headers, label):
    session = Session(client, url, headers)
    result, initialized = session.initialize()
    out(check=label, step='initialize', serverInfo=result.get('serverInfo'), protocolVersion=result.get('protocolVersion'),
        capabilities=result.get('capabilities'), initialized_status=initialized)
    tools = session.request('tools/list')['result']['tools']
    out(check=label, step='tools/list', count=len(tools), names=sorted(t['name'] for t in tools),
        read_only_hints=sorted(t['name'] for t in tools if (t.get('annotations') or {}).get('readOnlyHint') is True))
    for name in ('health', 'version', 'list_projects', 'list_agents'):
        out(check=label, step='tools/call ' + name, **session.call(name))
    session.close()


CLAUDE_UA = 'Claude-User'
META = {'traceparent': '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01'}  # W3C example value, not a secret
MARKER = 'probe-input-marker-' + 'q' * 12  # an argument value: must never be echoed back in a refusal


def rpc_or_status(response):
    try:
        return response.status_code, rpc_result(response)
    except Exception:  # noqa: BLE001 - only the status matters then
        return response.status_code, None


def claudeai(client, base):
    url = base + '/private_' + TOKEN + '/mcp'
    session = Session(client, url, {'Origin': 'https://claude.ai', 'User-Agent': CLAUDE_UA})
    status, reply = rpc_or_status(session.post({'jsonrpc': '2.0', 'id': 1, 'method': 'server/discover',
                                                'params': {'_meta': META}}, {'MCP-Protocol-Version': '2026-07-28'}))
    out(check='claudeai', step='server/discover (params only _meta)', status=status, error=(reply or {}).get('error'))
    response = session.post({'jsonrpc': '2.0', 'id': 2, 'method': 'initialize', 'params': {
        '_meta': META, 'protocolVersion': '2025-11-25',
        'capabilities': {'extensions': {'io.modelcontextprotocol/ui': {'mimeTypes': ['text/html;profile=mcp-app']}}},
        'clientInfo': {'name': 'Anthropic/ClaudeAI', 'version': '1.0.0'}}})
    status, reply = rpc_or_status(response)
    result = (reply or {}).get('result') or {}
    out(check='claudeai', step='initialize 2025-11-25 (_meta.traceparent, capabilities.extensions)', status=status,
        protocolVersion=result.get('protocolVersion'), serverInfo=result.get('serverInfo'), error=(reply or {}).get('error'))
    session.headers['mcp-session-id'] = response.headers['mcp-session-id']
    session.headers['mcp-protocol-version'] = result['protocolVersion']
    r = session.post({'jsonrpc': '2.0', 'method': 'notifications/initialized', 'params': {'_meta': META}})
    out(check='claudeai', step='notifications/initialized with _meta', status=r.status_code)
    r = session.post({'jsonrpc': '2.0', 'method': 'notifications/claudeai/unknown', 'params': {'_meta': META}})
    out(check='claudeai', step='unknown notification', status=r.status_code)
    status, reply = rpc_or_status(session.post({'jsonrpc': '2.0', 'id': 3, 'method': 'claudeai/unknown', 'params': {'_meta': META}}))
    out(check='claudeai', step='unknown request', status=status, error=(reply or {}).get('error'))
    status, reply = rpc_or_status(session.post({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/list', 'params': {'_meta': META}}))
    tools = ((reply or {}).get('result') or {}).get('tools', [])
    out(check='claudeai', step='tools/list with _meta', status=status, count=len(tools))
    status, reply = rpc_or_status(session.post({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {
        '_meta': {**META, 'progressToken': 7}, 'name': 'health', 'arguments': {}}}))
    result = (reply or {}).get('result') or {}
    out(check='claudeai', step='tools/call health with _meta', status=status, isError=bool(result.get('isError')),
        error=(reply or {}).get('error'), ok='"ok": true' in ''.join(i.get('text', '') for i in result.get('content', [])))
    status, reply = rpc_or_status(session.post({'jsonrpc': '2.0', 'id': 6, 'method': 'ping', 'params': {'_meta': META}}))
    out(check='claudeai', step='ping with _meta', status=status, result=(reply or {}).get('result'), error=(reply or {}).get('error'))
    session.close()


def refusals(client, base):
    bearer = {'Authorization': 'Bearer ' + TOKEN}
    session = Session(client, base + '/mcp', bearer)
    session.initialize()
    cases = [
        ('unknown tool', {'name': 'no_such_tool', 'arguments': {'value': MARKER}}),
        ('invalid arguments (delete_project project_id not a UUID)', {'name': 'delete_project', 'arguments': {'project_id': MARKER}}),
        ('invalid arguments (read_file .env, unknown member)', {'name': 'read_file', 'arguments': {
            'project_id': '00000000-0000-4000-8000-000000000000', 'file_path': '.env', 'path': MARKER}}),
        ('invalid arguments (get_project without project_id, extra field)', {'name': 'get_project', 'arguments': {'unexpected': MARKER}}),
        ('invalid argument type (get_project project_id=123)', {'name': 'get_project', 'arguments': {'project_id': 123}}),
    ]
    for ident, (case, params) in enumerate(cases, start=10):
        response = session.post({'jsonrpc': '2.0', 'id': ident, 'method': 'tools/call', 'params': params})
        status, reply = rpc_or_status(response)
        error = (reply or {}).get('error') or {}
        out(check='refusals', case=case, status=status, code=error.get('code'), message=error.get('message'),
            data=error.get('data'), argument_value_echoed=MARKER in response.text)
    no_session = Session(client, base + '/mcp', bearer).post({'jsonrpc': '2.0', 'id': 30, 'method': 'tools/call',
                                                              'params': {'name': 'no_such_tool', 'arguments': {}}})
    out(check='refusals', case='refused tools/call without a session', status=no_session.status_code)
    session.close()


LEAK_MARKERS = ('/data/', 'http://', 'https://', 'cwd', 'localPath', 'token', 'Bearer')


def leaks(text):
    return sorted(marker for marker in LEAK_MARKERS if marker in text)


def bearer_session(client, base):
    session = Session(client, base + '/mcp', {'Authorization': 'Bearer ' + TOKEN})
    session.initialize()
    return session


def projects(session):
    reply, value = call_json(session, 'list_projects', {})
    return [p.get('id') for p in value.get('projects', [])] if isinstance(value, dict) else value


def call_json(session, name, arguments):
    """Like Session.call, with the whole text (call() shortens it) parsed as JSON when it is JSON."""
    message = session.request('tools/call', {'name': name, 'arguments': arguments})
    result = message.get('result') or {}
    text = ''.join(item.get('text', '') for item in result.get('content', []) if item.get('type') == 'text')
    reply = {'isError': bool(result.get('isError')), 'error': message.get('error'), 'text': text}
    try:
        value = json.loads(reply['text'])
    except ValueError:
        value = reply['text']
    return reply, value


def od_create(client, base):
    session = bearer_session(client, base)
    tools = session.request('tools/list')['result']['tools']
    out(check='create', step='tools/list', count=len(tools), names=sorted(t['name'] for t in tools),
        input_schemas={t['name']: sorted(t['inputSchema'].get('properties', {})) for t in tools
                       if t['name'] in ('read_file', 'create_project', 'send_message')})
    reply, value = call_json(session, 'create_project', {'prompt': 'e2e probe: a one-line hello page',
                                                          'agent_id': 'claude'})
    out(check='create', step='create_project agent=claude (not signed in)', isError=reply['isError'], result=value,
        leaks=leaks(reply['text']))
    project = value.get('projectId') if isinstance(value, dict) else None
    out(check='create', step='list_projects contains the new project', present=project in projects(session))
    session.close()
    if project:
        print('project=' + project, flush=True)


def od_files(client, base, project):
    session = bearer_session(client, base)
    reply, value = call_json(session, 'list_project_files', {'project_id': project})
    names = sorted(f.get('path') for f in value.get('files', [])) if isinstance(value, dict) else value
    out(check='files', step='list_project_files', files=names)
    reply, value = call_json(session, 'get_file_info', {'project_id': project, 'file_path': 'index.html'})
    out(check='files', step='get_file_info index.html', isError=reply['isError'],
        size=value.get('size') if isinstance(value, dict) else value)
    cases = (('index.html', 'text file'), ('sub/a.txt', 'nested text file'), ('.env', 'secret-like name'),
             ('keys/server.pem', 'secret-like name'), ('bin.dat', 'binary'), ('big.txt', 'over 1 MiB'),
             ('missing.txt', 'not in the project'), ('../../mcp/state.json', 'traversal'))
    for ident, (path, label) in enumerate(cases, start=40):
        response = session.post({'jsonrpc': '2.0', 'id': ident, 'method': 'tools/call',
                                 'params': {'name': 'read_file', 'arguments': {'project_id': project, 'file_path': path}}})
        status, reply = rpc_or_status(response)
        result = (reply or {}).get('result') or {}
        error = (reply or {}).get('error')
        text = ''.join(i.get('text', '') for i in result.get('content', []))
        out(check='files', case='read_file ' + path + ' (' + label + ')', status=status,
            isError=bool(result.get('isError')), text=text[:120],
            gateway_error=None if not error else {'code': error.get('code'), 'message': error.get('message'),
                                                  'errors': (error.get('data') or {}).get('errors')})
    session.close()


def od_chat(client, base, project):
    session = bearer_session(client, base)
    for label, name, arguments in (
            ('send_message agent=claude (not signed in)', 'send_message',
             {'project_id': project, 'prompt': 'e2e probe: make the heading blue', 'agent_id': 'claude'}),
            ('send_message agent=no-such-agent', 'send_message',
             {'project_id': project, 'prompt': 'e2e probe', 'agent_id': 'no-such-agent'}),
            ('send_message unknown project', 'send_message',
             {'project_id': '00000000-0000-4000-8000-000000000000', 'prompt': 'e2e probe'}),
            ('create_project agent=byok-opencode (no browser-local configuration)', 'create_project',
             {'prompt': 'e2e probe', 'agent_id': 'byok-opencode'})):
        reply, value = call_json(session, name, arguments)
        out(check='chat', case=label, isError=reply['isError'], result=value, leaks=leaks(reply['text']))
    session.close()


def od_connectors(client, base):
    session = bearer_session(client, base)
    reply, value = call_json(session, 'list_connectors', {})
    connectors = value.get('connectors', []) if isinstance(value, dict) else []
    keys = sorted({k for c in connectors for k in c})
    out(check='connectors', isError=reply['isError'], total=value.get('total') if isinstance(value, dict) else value,
        returned=len(connectors), fields=keys, first=connectors[:2], leaks=leaks(reply['text']),
        bytes=len(reply['text']))
    session.close()


def od_runs(client, base):
    session = bearer_session(client, base)
    reply, value = call_json(session, 'list_runs', {})
    runs = value.get('runs', []) if isinstance(value, dict) else value
    out(check='runs', isError=reply['isError'], count=len(runs) if isinstance(runs, list) else runs,
        fields=sorted({k for r in runs for k in r}) if isinstance(runs, list) else None, leaks=leaks(reply['text']))
    session.close()


def od_delete(client, base, project):
    session = bearer_session(client, base)
    reply, value = call_json(session, 'delete_project', {'project_id': project})
    out(check='delete', step='delete_project', isError=reply['isError'], result=value)
    out(check='delete', step='list_projects after delete', present=project in projects(session))
    session.close()


def starting(client, base, seconds):
    """Poll a full client handshake while the add-on (re)starts; one JSON line per attempt."""
    import time
    bearer = {'Authorization': 'Bearer ' + TOKEN}
    deadline = time.monotonic() + seconds
    started = time.monotonic()
    while time.monotonic() < deadline:
        at = round(time.monotonic() - started, 1)
        session = Session(client, base + '/mcp', bearer)
        try:
            response = session.post({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
                'protocolVersion': PROTOCOL, 'capabilities': {}, 'clientInfo': {'name': 'probe', 'version': '0'}}})
        except httpx.HTTPError as exc:
            out(check='starting', t=at, initialize='transport ' + type(exc).__name__)
            time.sleep(1)
            continue
        line = {'t': at, 'initialize': response.status_code}
        if response.status_code == 200 and 'mcp-session-id' in response.headers:
            session.headers['mcp-session-id'] = response.headers['mcp-session-id']
            session.headers['mcp-protocol-version'] = rpc_result(response)['result']['protocolVersion']
            session.post({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            status, reply = rpc_or_status(session.post({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}))
            line['tools/list'] = status
            status, reply = rpc_or_status(session.post({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                                        'params': {'name': 'health', 'arguments': {}}}))
            result = (reply or {}).get('result') or {}
            text = ''.join(i.get('text', '') for i in result.get('content', []))
            line['health'] = status if reply is None else ('error ' + text[:60] if result.get('isError') else 'ok')
            session.close()
        out(check='starting', **line)
        if line.get('health') == 'ok':
            return
        time.sleep(1)


def main():
    base, checks = sys.argv[1].rstrip('/'), sys.argv[2:]
    with httpx.Client(timeout=httpx.Timeout(130, connect=5), trust_env=False) as client:
        bearer = {'Authorization': 'Bearer ' + TOKEN}
        init = {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
            'protocolVersion': PROTOCOL, 'capabilities': {}, 'clientInfo': {'name': 'probe', 'version': '0'}}}
        for check in checks:
            if check == 'auth':
                s = Session(client, base + '/mcp', {})
                r = s.post(init)
                out(check='auth', case='no Authorization', status=r.status_code, www_authenticate=r.headers.get('www-authenticate'))
                r = s.post(init, {'Authorization': 'Bearer wrong-' + 'x' * 38})
                out(check='auth', case='wrong Bearer', status=r.status_code)
                r = s.post(init, {**bearer, 'Origin': 'https://example.invalid'})
                out(check='auth', case='Bearer + Origin', status=r.status_code)
            elif check == 'bearer':
                flow(client, base + '/mcp', bearer, 'bearer')
            elif check == 'secret':
                flow(client, base + '/private_' + TOKEN + '/mcp', {'Origin': 'https://claude.ai'}, 'secret')
                r = Session(client, base + '/private_' + 'y' * 43 + '/mcp', {'Origin': 'https://claude.ai'}).post(init)
                out(check='secret', case='wrong secret', status=r.status_code)
            elif check == 'tools':
                session = Session(client, base + '/mcp', bearer)
                session.initialize()
                tools = session.request('tools/list')['result']['tools']
                out(check='tools', count=len(tools), names=sorted(t['name'] for t in tools))
                session.close()
            elif check == 'health':
                session = Session(client, base + '/mcp', bearer)
                session.initialize()
                out(check='health', **session.call('health'))
                session.close()
            elif check == 'status':
                r = Session(client, base + '/mcp', bearer).post(init)
                out(check='status', case='Bearer initialize', status=r.status_code)
            elif check == 'claudeai':
                claudeai(client, base)
            elif check == 'refusals':
                refusals(client, base)
            elif check == 'starting':
                starting(client, base, int(os.environ.get('STARTING_SECONDS', '120')))
            elif check == 'create':
                od_create(client, base)
            elif check.startswith('files='):
                od_files(client, base, check[6:])
            elif check.startswith('chat='):
                od_chat(client, base, check[5:])
            elif check == 'connectors':
                od_connectors(client, base)
            elif check == 'runs':
                od_runs(client, base)
            elif check.startswith('delete='):
                od_delete(client, base, check[7:])
            elif check == 'ready':
                r = client.get(base + '/health/ready')
                out(check='ready', status=r.status_code, body=r.text[:200])
            else:
                raise SystemExit('unknown check ' + check)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # report, without the token, and fail
        out(error=type(exc).__name__, detail=str(exc)[:300])
        raise SystemExit(1)
