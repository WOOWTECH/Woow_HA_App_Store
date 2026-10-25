"""0.2.6: what an MCP client gets from the built-in OpenDesign server's child, recorded for test_surface_unchanged.py.

Run with the child's Python (requirements/child.txt). Builds the child as the add-on does (ha_opendesign_mcp
child.setup(): the vendored server, the HA handlers, BoundedTools and, since 0.2.6, keep_error_text) against a fake
OpenDesign 0.24.1 daemon on loopback, and drives its Streamable HTTP app in process (httpx ASGI transport, no network):
initialize, tools/list and a fixed set of tools/call cases, among them every failure text the tools answer (the daemon
unreachable, its HTTP errors, an answer that is not JSON, the HA refusals, BACKEND_BUSY). Prints one JSON document:

  {"sdk": <mcp version>, "tools": <the child's tools/list result>, "calls": {<case>: <tools/call result>}}

with the project ids create_project generates replaced by "<generated>". HA_OD_MCP_CODE / HA_OD_MCP_VENDOR select the
tree (as in the other unit tests): fixtures/surface-0.2.5.json is this script's output for v0.2.5 (mcp 1.30.0):

  HA_OD_MCP_CODE=<v0.2.5>/mcp-runtime HA_OD_MCP_VENDOR=<v0.2.5>/mcp-runtime/vendor \\
    <a venv with v0.2.5's requirements/child.txt>/bin/python mcp-runtime/tests/unit/surface_capture.py
"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import re
import sys
import threading

HERE = Path(__file__).resolve().parent
CODE = os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1]))
VENDOR = Path(os.environ.get('HA_OD_MCP_VENDOR', str(HERE.parents[1] / 'vendor')))
FIXTURES = HERE / 'fixtures'
PROJECT = '62720fb2-1795-474e-ab8c-f03657706bed'
MISSING = '00000000-0000-4000-8000-000000000000'
RUN = 'e9138737-f40d-4766-9153-ddb8407177f9'
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
FILES = {'index.html': b'<h1>hi</h1>\n', 'bin.dat': b'\x89PNG\x00\x01', 'big.txt': b'x' * (1024 * 1024 + 1)}


class Daemon(BaseHTTPRequestHandler):
    """OpenDesign 0.24.1's answers (shapes of the 2026-10-15 measurement); mode '500' or 'not-json' answers every API
    request with an internal error or a body that is not JSON."""
    mode = 'ok'
    chat = 'chat-success.sse'
    chat_status = 200

    def log_message(self, *args):
        pass

    def reply(self, status, body, media='application/json'):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', media)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def broken(self):
        if self.mode == '500':
            self.reply(500, {'error': {'code': 'INTERNAL', 'message': 'boom at /data/opendesign/db.sqlite'}})
            return True
        if self.mode == 'not-json':
            self.reply(200, b'<html>not json</html>', 'text/html')
            return True
        return False

    def do_GET(self):
        if self.broken():
            return
        project = '/api/projects/' + PROJECT
        answers = {
            '/api/health': {'ok': True, 'version': '0.24.1'},
            '/api/version': {'version': '0.24.1', 'channel': 'stable', 'platform': 'linux', 'arch': 'x64'},
            '/api/agents': {'agents': [{'id': 'claude', 'name': 'Claude Code', 'available': True, 'version': '2.1.296',
                                        'path': '/usr/local/bin/claude'},
                                       {'id': 'gemini', 'name': 'Gemini CLI', 'available': False}]},
            '/api/connectors': {'connectors': [{'id': 'github', 'name': 'GitHub', 'status': 'available',
                                                'auth': {'configured': False, 'token': 'tok-secret'},
                                                'url': 'https://example.invalid/x',
                                                'tools': [{'name': 'github.github_get_issue'}]}]},
            '/api/projects': {'projects': [{'id': PROJECT, 'name': 'Demo', 'createdAt': 1760000000000}]},
            project: {'project': {'id': PROJECT, 'name': 'Demo'}, 'resolvedDir': '/data/opendesign/projects/x'},
            project + '/files': {'files': [{'name': name, 'path': name, 'type': 'file', 'size': len(data),
                                            'mime': 'text/html' if name.endswith('.html') else 'application/octet-stream'}
                                           for name, data in FILES.items()]},
            '/api/runs': {'runs': [{'id': RUN, 'projectId': PROJECT, 'status': 'failed',
                                    'error': 'auth failed at /data/opendesign/home',
                                    'eventsLogPath': '/data/opendesign/runs/x/events.jsonl'}],
                          'awaitingInputProjectIds': []},
            '/api/plugins': {'plugins': [{'id': 'woow-mcp-server', 'title': 'MCP Server', 'sourceKind': 'bundled',
                                          'trust': 'official', 'manifest': {'large': True}}]},
            '/api/skills': {'skills': [{'id': 'woowtech-brand', 'name': 'WoowTech brand', 'description': 'Brand rules',
                                        'mode': 'design', 'surface': 'web', 'triggers': list('abcdefg')}]},
        }
        if self.path in answers:
            return self.reply(200, answers[self.path])
        if self.path.startswith(project + '/files/'):
            name = self.path[len(project + '/files/'):]
            if name in FILES:
                return self.reply(200, FILES[name], 'application/octet-stream')
        return self.reply(404, {'error': {'code': 'NOT_FOUND', 'message': 'ENOENT /data/opendesign/x'}})

    def do_DELETE(self):
        if self.broken():
            return
        if self.path == '/api/projects/' + PROJECT:
            return self.reply(200, {'ok': True})
        return self.reply(404, {'error': {'code': 'PROJECT_NOT_FOUND', 'message': 'project not found'}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.broken():
            return
        if self.path == '/api/projects':
            return self.reply(200, {'project': {'id': body['id'], 'name': body['name']}})
        if self.path != '/api/chat':
            return self.reply(404, {})
        if self.chat_status != 200:
            return self.reply(self.chat_status, {'error': {'code': 'VALIDATION_FAILED', 'message': 'needs config'}})
        data = (FIXTURES / self.chat).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


SERVER = ThreadingHTTPServer(('127.0.0.1', 0), Daemon)
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
os.environ['OD_API_BASE'] = 'http://127.0.0.1:%d' % SERVER.server_address[1]
os.environ['WOOW_MCP_SESSION_IDLE_SECONDS'] = '600'
sys.path[:0] = [str(VENDOR / 'apps' / 'opendesign' / 'vendor'), str(VENDOR / 'apps' / 'runtime'),
                str(VENDOR / 'apps' / 'opendesign')]
sys.path.append(CODE)

import httpx  # noqa: E402
import launch  # noqa: E402  vendored

from ha_opendesign_mcp import child, od_tools  # noqa: E402

for name in ('httpx', 'mcp', 'mcp.server', 'mcp.server.lowlevel.server'):
    logging.getLogger(name).setLevel(logging.CRITICAL)
HEADERS = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}
INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'surface-capture', 'version': '0'}}}
READS = ('health', 'version', 'list_agents', 'list_connectors', 'list_projects', 'list_runs', 'list_plugins',
         'list_skills')
WITH_PROJECT = ('get_project', 'list_project_files', 'delete_project')
CASES = [
    *((name, name, {}) for name in READS),
    ('get_project', 'get_project', {'project_id': PROJECT}),
    ('get_project/unknown-project', 'get_project', {'project_id': MISSING}),
    ('list_project_files', 'list_project_files', {'project_id': PROJECT}),
    ('list_project_files/unknown-project', 'list_project_files', {'project_id': MISSING}),
    ('get_file_info', 'get_file_info', {'project_id': PROJECT, 'file_path': 'index.html'}),
    ('get_file_info/missing', 'get_file_info', {'project_id': PROJECT, 'file_path': 'nope.txt'}),
    ('read_file', 'read_file', {'project_id': PROJECT, 'file_path': 'index.html'}),
    ('read_file/secret', 'read_file', {'project_id': PROJECT, 'file_path': '.env'}),
    ('read_file/missing', 'read_file', {'project_id': PROJECT, 'file_path': 'nope.txt'}),
    ('read_file/binary', 'read_file', {'project_id': PROJECT, 'file_path': 'bin.dat'}),
    ('read_file/too-large', 'read_file', {'project_id': PROJECT, 'file_path': 'big.txt'}),
    ('read_file/unknown-project', 'read_file', {'project_id': MISSING, 'file_path': 'index.html'}),
    ('create_project', 'create_project', {'prompt': 'A landing page\nfor a coffee shop'}),
    ('create_project/agent-auth', 'create_project', {'prompt': 'x'}, {'chat': 'chat-claude-auth.sse'}),
    ('create_project/unknown-agent', 'create_project', {'prompt': 'x', 'agent_id': 'no-such-agent'},
     {'chat': 'chat-unknown-agent.sse'}),
    ('create_project/refused', 'create_project', {'prompt': 'x', 'agent_id': 'byok-opencode'}, {'chat_status': 400}),
    ('create_project/invalid', 'create_project', {'prompt': 'x', 'agent_id': 'A B'}),
    ('create_project/busy', 'create_project', {'prompt': 'x'}, {'busy': True}),
    ('send_message', 'send_message', {'project_id': PROJECT, 'prompt': 'hi', 'agent_id': 'opencode'}),
    ('send_message/unknown-project', 'send_message', {'project_id': MISSING, 'prompt': 'hi'}),
    ('send_message/invalid', 'send_message', {'project_id': 'x', 'prompt': 'hi'}),
    ('delete_project', 'delete_project', {'project_id': PROJECT}),
    ('delete_project/unknown-project', 'delete_project', {'project_id': MISSING}),
]
FAILURES = {'500': (*READS, *WITH_PROJECT, 'get_file_info', 'read_file', 'create_project', 'send_message'),
            'not-json': (*READS, *WITH_PROJECT, 'get_file_info', 'read_file', 'send_message')}
FAILURE_ARGUMENTS = {'get_project': {'project_id': PROJECT}, 'list_project_files': {'project_id': PROJECT},
                     'delete_project': {'project_id': PROJECT},
                     'get_file_info': {'project_id': PROJECT, 'file_path': 'index.html'},
                     'read_file': {'project_id': PROJECT, 'file_path': 'index.html'},
                     'create_project': {'prompt': 'x'}, 'send_message': {'project_id': PROJECT, 'prompt': 'hi'}}


def normalized(value):
    """Generated project ids (create_project) become <generated>; fixed ids stay."""
    text = json.dumps(value, sort_keys=True)
    for found in sorted(set(UUID.findall(text)) - {PROJECT, MISSING, RUN, '29a8b67a-faaf-44ae-b66f-8bf2479b5442'}):
        text = text.replace(found, '<generated>')
    return json.loads(text)


def message(response, ident):
    """The JSON-RPC message answering `ident` (plain JSON or SSE)."""
    if response.headers.get('content-type', '').startswith('text/event-stream'):
        for line in response.text.splitlines():
            if line.startswith('data:'):
                value = json.loads(line[5:].strip())
                if value.get('id') == ident:
                    return value
        raise AssertionError('no reply')
    return response.json()


async def capture():
    app, client, workers = child.setup()
    out = {'sdk': importlib.metadata.version('mcp'), 'calls': {}}
    try:
        async with launch.mcp.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1:3000',
                                         timeout=60) as http:
                answer = await http.post('/mcp', headers=HEADERS, json=INIT)
                assert answer.status_code == 200, answer.text
                session = answer.headers['mcp-session-id']
                headers = {**HEADERS, 'mcp-session-id': session, 'mcp-protocol-version': '2025-03-26'}
                assert (await http.post('/mcp', headers=headers, json={
                    'jsonrpc': '2.0', 'method': 'notifications/initialized'})).status_code == 202
                ident = 1

                async def rpc(method, params=None):
                    nonlocal ident
                    ident += 1
                    body = {'jsonrpc': '2.0', 'id': ident, 'method': method, **({'params': params} if params else {})}
                    answer = await http.post('/mcp', headers=headers, json=body)
                    assert answer.status_code == 200, answer.text
                    reply = message(answer, ident)
                    return reply.get('result', {'jsonrpc-error': reply.get('error')})

                async def call(case, name, arguments, setting=None):
                    setting = dict(setting or {})
                    busy = setting.pop('busy', False)
                    saved = {key: getattr(Daemon, key) for key in setting}
                    for key, value in setting.items():
                        setattr(Daemon, key, value)
                    if busy:
                        for _ in range(od_tools.CHAT_SLOTS):
                            od_tools._chats.acquire()
                    try:
                        out['calls'][case] = normalized(await rpc('tools/call', {'name': name, 'arguments': arguments}))
                    finally:
                        if busy:
                            for _ in range(od_tools.CHAT_SLOTS):
                                od_tools._chats.release()
                        for key, value in saved.items():
                            setattr(Daemon, key, value)

                out['tools'] = await rpc('tools/list')
                for case in CASES:
                    await call(*case)
                for mode, names in FAILURES.items():
                    Daemon.mode = mode
                    try:
                        for name in names:
                            await call('daemon-%s/%s' % (mode, name), name, FAILURE_ARGUMENTS.get(name, {}))
                    finally:
                        Daemon.mode = 'ok'
                SERVER.shutdown()
                SERVER.server_close()
                for name in (*READS, *WITH_PROJECT, 'get_file_info', 'read_file', 'create_project', 'send_message'):
                    await call('daemon-down/' + name, name, FAILURE_ARGUMENTS.get(name, {}))
                await http.delete('/mcp', headers=headers)
    finally:
        workers.close()
        client.close()
    return out


def main():
    print(json.dumps(asyncio.run(capture()), indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
