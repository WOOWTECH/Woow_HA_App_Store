"""0.2.1 child side: the bounded OpenDesign handlers (od_tools.py) on the vendored server, against a fake OpenDesign
daemon on loopback (no network; the vendored backend_policy transport is used unchanged).

0.2.6: the server is MCP Python SDK 2's MCPServer, built by child.setup() (the child's real entry: od_tools, BoundedTools,
then the vendored keep_error_text, so a failed call reads 'Error executing tool <name>: <code>' as with SDK 1.x), and
list_runs is the fifth replaced handler (the 0.2.1-0.2.5 projection, od_rules.run_rows).

HA_OD_MCP_CODE / HA_OD_MCP_VENDOR: as in test_surface.py.
"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
CODE = os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1]))
VENDOR = Path(os.environ.get('HA_OD_MCP_VENDOR', str(HERE.parents[1] / 'vendor')))
FIXTURES = HERE / 'fixtures'
PROJECT = '62720fb2-1795-474e-ab8c-f03657706bed'
MISSING = '00000000-0000-4000-8000-000000000000'
BIG = 'x' * (1024 * 1024 + 1)


class Daemon(BaseHTTPRequestHandler):
    """Answers like OpenDesign 0.24.1 (2026-10-15 measurement), from FILES / CHAT below."""
    FILES = {'index.html': b'<h1>hi</h1>\n', 'sub/a.txt': b'nested\n', 'bin.dat': b'\x89PNG\x00\x01',
             'bad.txt': b'\xff\xfe', 'big.txt': BIG.encode(), 'grown.txt': BIG.encode(), '.env': b'FAKE=1\n'}
    LISTED_SIZES = {'grown.txt': 10}  # the list shows an older, smaller size
    chat = 'chat-claude-auth.sse'
    chat_status = 200
    stall = 0.0  # seconds of keepalives before the chat body
    requests = []

    def log_message(self, *args):
        pass

    def reply(self, status, body, media='application/json'):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', media)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        Daemon.requests.append(('GET', self.path))
        if self.path == '/api/connectors':
            return self.reply(200, {'connectors': [{'id': 'github', 'name': 'GitHub', 'status': 'available',
                                                    'auth': {'configured': False, 'token': 'tok-secret'},
                                                    'url': 'https://example.invalid/x',
                                                    'tools': [{'name': 'github.github_get_issue'}]}]})
        if self.path == '/api/runs':
            return self.reply(200, {'runs': [{'id': 'e9138737-f40d-4766-9153-ddb8407177f9', 'projectId': PROJECT,
                                              'status': 'failed', 'error': 'auth failed at /data/opendesign/home',
                                              'eventsLogPath': '/data/opendesign/runs/x/events.jsonl'}],
                                    'awaitingInputProjectIds': []})
        prefix = '/api/projects/%s' % PROJECT
        if self.path == prefix:
            return self.reply(200, {'project': {'id': PROJECT}, 'resolvedDir': '/data/opendesign/projects/x'})
        if self.path == prefix + '/files':
            return self.reply(200, {'files': [
                {'name': name, 'path': name, 'type': 'file', 'size': self.LISTED_SIZES.get(name, len(data)),
                 'localPath': '/data/opendesign/projects/x/' + name}
                for name, data in self.FILES.items() if not name.startswith('.')]})
        if self.path.startswith(prefix + '/files/'):
            name = self.path[len(prefix + '/files/'):]
            if name in self.FILES:
                return self.reply(200, self.FILES[name], 'application/octet-stream')
            return self.reply(404, {'error': {'code': 'FILE_NOT_FOUND', 'message': 'ENOENT /data/opendesign/x'}})
        return self.reply(404, {'error': {'code': 'PROJECT_NOT_FOUND', 'message': 'project not found'}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        Daemon.requests.append(('POST', self.path, body))
        if self.path == '/api/projects':
            return self.reply(200, {'project': {'id': body['id'], 'name': body['name']}})
        if self.path != '/api/chat':
            return self.reply(404, {})
        if self.chat_status != 200:
            return self.reply(self.chat_status, {'error': {'code': 'VALIDATION_FAILED', 'message': 'needs config'}})
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        until = time.monotonic() + self.stall
        try:
            while time.monotonic() < until:
                self.wfile.write(b': keepalive\n\n')
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write((FIXTURES / self.chat).read_bytes())
        except (BrokenPipeError, ConnectionResetError):
            pass  # the handler stopped reading (deadline)


SERVER = ThreadingHTTPServer(('127.0.0.1', 0), Daemon)
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
os.environ['OD_API_BASE'] = 'http://127.0.0.1:%d' % SERVER.server_address[1]
sys.path[:0] = [str(VENDOR / 'apps' / 'opendesign' / 'vendor'), str(VENDOR / 'apps' / 'runtime'),
                str(VENDOR / 'apps' / 'opendesign')]
sys.path.append(CODE)

import launch  # noqa: E402  vendored
import opendesign_mcp_server.od_mcp_server as od  # noqa: E402  vendored

from ha_opendesign_mcp import child, od_rules, od_tools  # noqa: E402

logging.getLogger('httpx').setLevel(logging.WARNING)
APP, CLIENT, WORKERS = child.setup()


def call(name, arguments):
    """Through the MCPServer (BoundedTools, then keep_error_text around the handler): (is_error, text)."""
    async def run():
        return await launch.mcp.call_tool(name, arguments)
    try:
        result = asyncio.run(run())
    except Exception as error:  # the SDK's ToolError: "Error executing tool <name>: <public code>"
        return True, str(error)
    content = result[0] if isinstance(result, tuple) else getattr(result, 'content', result)
    return bool(getattr(result, 'is_error', False)), ''.join(getattr(item, 'text', '') for item in content)


class Surface(unittest.TestCase):
    def test_fifteen_tools_five_replaced(self):
        from mcp.server.mcpserver import MCPServer
        self.assertIsInstance(launch.mcp, MCPServer)
        tools = {tool.name: tool for tool in launch.mcp._tool_manager.list_tools()}
        self.assertEqual(len(tools), 15)
        self.assertEqual(od_tools.REPLACED, ('list_connectors', 'read_file', 'create_project', 'send_message',
                                             'list_runs'))
        for name, tool in tools.items():
            self.assertTrue(tool.is_async, name)  # BoundedTools: every tool runs on the owned workers
            self.assertTrue(getattr(tool.fn, '_woow_keeps_error_text', False), name)  # keep_error_text, last
            module = 'ha_opendesign_mcp.od_tools' if name in od_tools.REPLACED else 'opendesign_mcp_server.od_mcp_server'
            self.assertEqual(tool.fn.__wrapped__.__module__, module, name)
        self.assertEqual(sorted(tools['send_message'].parameters['properties']), ['agent_id', 'project_id', 'prompt'])
        self.assertEqual(sorted(tools['read_file'].parameters['properties']), ['file_path', 'project_id'])
        self.assertEqual(tools['create_project'].parameters['required'], ['prompt'])
        self.assertEqual(tools['list_runs'].description, 'List all active and completed AI agent runs.')
        with self.assertRaises(RuntimeError):
            od_tools.install(launch.mcp, od)  # the handlers are async (wrapped) now: never replaced twice


class Tools(unittest.TestCase):
    def setUp(self):
        Daemon.requests = []
        Daemon.chat, Daemon.chat_status, Daemon.stall = 'chat-claude-auth.sse', 200, 0.0

    def test_list_connectors(self):
        error, text = call('list_connectors', {})
        self.assertFalse(error)
        self.assertEqual(json.loads(text)['connectors'], [{
            'id': 'github', 'name': 'GitHub', 'provider': None, 'category': None, 'status': 'available',
            'configured': False, 'toolCount': 1, 'tools': ['github.github_get_issue']}])
        self.assertNotIn('tok-secret', text)
        self.assertNotIn('example.invalid', text)

    def test_list_runs_projection(self):
        # 0.2.1-0.2.5: the vendored output_policy projection; 0.2.6: the same projection in od_rules.run_rows (the
        # runtime pinned since 0.2.6 returns the runs unprojected: error texts and log paths).
        error, text = call('list_runs', {})
        self.assertFalse(error, text)
        self.assertEqual(json.loads(text), {'runs': [{'id': 'e9138737-f40d-4766-9153-ddb8407177f9',
                                                      'projectId': PROJECT, 'status': 'failed'}], 'truncated': False})

    def test_read_file(self):
        self.assertEqual(call('read_file', {'project_id': PROJECT, 'file_path': 'index.html'}), (False, '<h1>hi</h1>\n'))
        self.assertEqual(call('read_file', {'project_id': PROJECT, 'file_path': 'sub/a.txt'}), (False, 'nested\n'))

    def test_read_file_refusals(self):
        cases = {'.env': 'FILE_PATH_REFUSED', 'keys/server.pem': 'FILE_PATH_REFUSED', '../x': 'FILE_PATH_REFUSED',
                 'missing.txt': 'FILE_NOT_FOUND', 'bin.dat': 'FILE_NOT_TEXT', 'bad.txt': 'FILE_NOT_TEXT',
                 'big.txt': 'FILE_TOO_LARGE', 'grown.txt': 'FILE_TOO_LARGE'}
        for path, code in cases.items():
            with self.subTest(path=path):
                error, text = call('read_file', {'project_id': PROJECT, 'file_path': path})
                self.assertTrue(error)
                self.assertTrue(text.endswith(': ' + code), text)
        # Refused names never reach OpenDesign; a file the list does not show is never fetched.
        fetched = [r[1] for r in Daemon.requests if '/files/' in r[1]]
        self.assertEqual(sorted(fetched), sorted('/api/projects/%s/files/%s' % (PROJECT, name)
                                                 for name in ('bin.dat', 'bad.txt', 'grown.txt')))
        error, text = call('read_file', {'project_id': MISSING, 'file_path': 'index.html'})
        self.assertTrue(text.endswith('BACKEND_HTTP_ERROR status=404'), text)

    def test_create_project_auth_failure(self):
        error, text = call('create_project', {'prompt': 'A landing page\nfor a coffee shop'})
        self.assertFalse(error, text)
        result = json.loads(text)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errorCode'], 'AGENT_AUTH_REQUIRED')
        self.assertEqual(result['runId'], 'e9138737-f40d-4766-9153-ddb8407177f9')
        self.assertTrue(result['registered'])
        self.assertNotIn('/data/', text)
        chat = [r for r in Daemon.requests if r[1] == '/api/chat'][0][2]
        self.assertEqual(chat['agentId'], 'claude')
        self.assertTrue(od_rules.UUID.fullmatch(chat['projectId']))
        register = [r for r in Daemon.requests if r[1] == '/api/projects'][0][2]
        self.assertEqual(register, {'id': chat['projectId'], 'name': 'A landing page'})  # vendored _register_project

    def test_create_project_unknown_agent_not_registered(self):
        Daemon.chat = 'chat-unknown-agent.sse'
        error, text = call('create_project', {'prompt': 'x', 'agent_id': 'no-such-agent'})
        result = json.loads(text)
        self.assertEqual((result['status'], result['errorCode'], result['runId']), ('failed', 'AGENT_UNAVAILABLE', None))
        self.assertNotIn('registered', result)
        self.assertFalse([r for r in Daemon.requests if r[1] == '/api/projects'])

    def test_chat_refused_by_daemon(self):
        Daemon.chat_status = 400  # e.g. byok-opencode without its browser-local configuration
        error, text = call('create_project', {'prompt': 'x', 'agent_id': 'byok-opencode'})
        self.assertTrue(error)
        self.assertTrue(text.endswith(': BACKEND_HTTP_ERROR status=400'), text)
        self.assertNotIn('needs config', text)

    def test_send_message(self):
        Daemon.chat = 'chat-success.sse'
        error, text = call('send_message', {'project_id': PROJECT, 'prompt': 'hi', 'agent_id': 'opencode'})
        self.assertEqual(json.loads(text), {'projectId': PROJECT, 'runId': '29a8b67a-faaf-44ae-b66f-8bf2479b5442',
                                            'status': 'succeeded',
                                            'agentResponse': 'Hi! What would you like to design today?\n\n'})
        self.assertFalse([r for r in Daemon.requests if r[1] == '/api/projects'])  # never registers again

    def test_send_message_unknown_project(self):
        error, text = call('send_message', {'project_id': MISSING, 'prompt': 'hi'})
        self.assertTrue(text.endswith(': PROJECT_NOT_FOUND'), text)
        self.assertFalse([r for r in Daemon.requests if r[1] == '/api/chat'])

    def test_bad_arguments_refused_in_child_too(self):
        for name, arguments in (('send_message', {'project_id': 'x', 'prompt': 'hi'}),
                                ('create_project', {'prompt': 'hi', 'agent_id': 'A B'}),
                                ('create_project', {'prompt': 'x' * 20001})):
            with self.subTest(name=name):
                self.assertTrue(call(name, arguments)[1].endswith(': INVALID_ARGUMENTS'))
        self.assertFalse(Daemon.requests)

    def test_deadline(self):
        Daemon.stall = 2.0
        Daemon.chat = 'chat-success.sse'
        with mock.patch.object(od_rules, 'CHAT_SECONDS', 0.5):
            started = time.monotonic()
            error, text = call('send_message', {'project_id': PROJECT, 'prompt': 'hi'})
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.5)
        result = json.loads(text)
        self.assertEqual(result['status'], 'unknown')  # no start event was seen before the deadline
        self.assertEqual(result['note'], od_rules.WAITING_NOTE)

    def test_busy(self):
        for _ in range(od_tools.CHAT_SLOTS):
            od_tools._chats.acquire()
        try:
            self.assertTrue(call('create_project', {'prompt': 'x'})[1].endswith(': BACKEND_BUSY'))
        finally:
            for _ in range(od_tools.CHAT_SLOTS):
                od_tools._chats.release()


if __name__ == '__main__':
    try:
        unittest.main(verbosity=1)
    finally:
        WORKERS.close()
        CLIENT.close()
        SERVER.shutdown()
