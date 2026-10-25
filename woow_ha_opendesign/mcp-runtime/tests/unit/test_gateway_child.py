"""0.2.6: the vendored gateway in front of the real child on MCP Python SDK 2.3.0 (management venv; the child runs in
its own venv on a Unix socket, as in the add-on: HA_OD_MCP_CHILD_PYTHON, which tests/unit/run.sh sets).

Checked as WOOWTECH/Woow_ha_mcp_addons 0.4.0 checks its SDK 2 children (tests/test_protocol_clients.py there):

- server/discover (MCP 2026-07-28, which the Python SDK 2 client and Claude.ai send first) gets a clean JSON-RPC
  -32601 from the gateway itself, with or without the 2026-07-28 headers, before any session or child; the client then
  falls back to initialize;
- an SDK 2 child refuses an initialize that carries a 2026-07-28 MCP-Protocol-Version header (HTTP 400), so the
  gateway no longer forwards that header with an initialize: the handshake works through the gateway at every reviewed
  revision, also for a client that keeps its server/discover header; a 2026-07-28 request inside a session fails, as
  such a header did with SDK 1.x;
- through the gateway: the 15 tools as 0.2.5 listed them (fixtures/surface-0.2.5.json), a successful call, and a
  failure with its 0.2.5 text ('Error executing tool <name>: <code>');
- the request body ceiling: the gateway reads a body up to 16 MiB (gateway.MAX_REQUEST, 256 KiB until 0.2.5) and
  answers a larger one 413.

HA_OD_MCP_CODE / HA_OD_MCP_VENDOR: as in test_surface.py.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
CODE = Path(os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1])))
VENDOR = Path(os.environ.get('HA_OD_MCP_VENDOR', str(HERE.parents[1] / 'vendor')))
sys.path[:0] = [str(VENDOR / 'packages/mcp-admin-core'), str(CODE)]
CHILD_PYTHON = os.environ.get('HA_OD_MCP_CHILD_PYTHON')

import httpx  # noqa: E402
from mcp_admin_core import VERSION, gateway  # noqa: E402
from mcp_admin_core.configuration import ConfigurationState  # noqa: E402
from mcp_admin_core.products import TOOLS  # noqa: E402

from ha_opendesign_mcp import defaults, runtime  # noqa: E402
from ha_opendesign_mcp.state import BuiltinStore  # noqa: E402

LISTED = json.loads((HERE / 'fixtures' / 'surface-0.2.5.json').read_text())['gateway']['listed']['granted']
logging.getLogger('asyncio').setLevel(logging.ERROR)  # the test loop's debug mode calls the 16 MiB body's parsing slow
MISSING = '00000000-0000-4000-8000-000000000000'
MODERN = '2026-07-28'
ACCEPT = {'Accept': 'application/json, text/event-stream'}
DISCOVER = {'jsonrpc': '2.0', 'id': 0, 'method': 'server/discover', 'params': {'_meta': {
    'io.modelcontextprotocol/clientCapabilities': {}, 'io.modelcontextprotocol/protocolVersion': MODERN,
    'io.modelcontextprotocol/clientInfo': {'name': 'probe', 'version': '0'}}}}


def initialize(version):
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': version, 'capabilities': {}, 'clientInfo': {'name': 'gateway-child-test', 'version': '0'}}}


class Daemon(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/api/health':
            status, body = 200, {'ok': True, 'version': '0.24.1'}
        else:
            status, body = 404, {'error': {'code': 'PROJECT_NOT_FOUND', 'message': 'ENOENT /data/opendesign/x'}}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def message(response, ident):
    """The JSON-RPC message answering `ident` (plain JSON or SSE)."""
    if response.headers.get('content-type', '').startswith('text/event-stream'):
        for line in response.text.splitlines():
            if line.startswith('data:'):
                value = json.loads(line[5:].strip())
                if value.get('id') == ident:
                    return value
        raise AssertionError('no reply in ' + response.text[:500])
    return response.json()


@unittest.skipUnless(CHILD_PYTHON, 'HA_OD_MCP_CHILD_PYTHON (the child venv python) not set')
class GatewayAndChild(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='odmcp-')
        root = Path(cls.tmp.name)
        cls.socket = root / 'child.sock'
        cls.daemon = ThreadingHTTPServer(('127.0.0.1', 0), Daemon)
        threading.Thread(target=cls.daemon.serve_forever, daemon=True).start()
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(root), 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1',
               'PYTHONPATH': ':'.join(str(VENDOR / p) for p in ('apps/opendesign/vendor', 'apps/runtime',
                                                                'apps/opendesign')),
               'OD_API_BASE': 'http://127.0.0.1:%d' % cls.daemon.server_address[1],
               'HA_OD_MCP_CHILD_SOCKET': str(cls.socket)}
        cls.log = open(root / 'child.log', 'w+b')
        cls.child = subprocess.Popen([CHILD_PYTHON, '-B', '-W', 'ignore', str(CODE / 'ha_opendesign_mcp' / 'child.py')],
                                     env=env, cwd=root, stdin=subprocess.DEVNULL, stdout=cls.log, stderr=cls.log,
                                     start_new_session=True)
        deadline = time.monotonic() + 90
        with httpx.Client(transport=httpx.HTTPTransport(uds=str(cls.socket)), trust_env=False, timeout=5) as client:
            while True:
                try:
                    answer = client.post('http://127.0.0.1:3000/mcp', headers=ACCEPT, json=initialize('2025-11-25'))
                    if answer.status_code == 200:
                        client.delete('http://127.0.0.1:3000/mcp', headers={
                            **ACCEPT, 'mcp-session-id': answer.headers['mcp-session-id']})
                        break
                except httpx.TransportError:
                    pass
                if cls.child.poll() is not None or time.monotonic() > deadline:
                    cls.tearDownClass()
                    raise AssertionError('child did not start: ' + cls.child_log())
                time.sleep(0.2)

    @classmethod
    def child_log(cls):
        cls.log.seek(0)
        return cls.log.read().decode(errors='replace')[-4000:]

    @classmethod
    def tearDownClass(cls):
        if cls.child.poll() is None:
            cls.child.terminate()
            try:
                cls.child.wait(10)
            except subprocess.TimeoutExpired:
                cls.child.kill()
                cls.child.wait(10)
        cls.log.close()
        cls.daemon.shutdown()
        cls.daemon.server_close()
        cls.tmp.cleanup()

    async def asyncSetUp(self):
        self.state_dir = tempfile.TemporaryDirectory()
        self.store = BuiltinStore(Path(self.state_dir.name) / 'mcp')
        runtime.pin_backend(self.store)
        defaults.apply(self.store)
        self.token = self.store.load().token
        self.to_child = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(self.socket)), trust_env=False,
                                          follow_redirects=False, timeout=httpx.Timeout(10, connect=3))
        _, app = gateway.make_apps(self.store, TOOLS['opendesign'], self.to_child, verify_admin=runtime.ingress_user,
                                   management=runtime.management_options(),
                                   configuration=ConfigurationState(self.store), server_name='woow-mcp-opendesign')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app, client=('192.0.2.10', 50000)),
                                        base_url='http://addon:8081', timeout=60)
        self.auth = {'Authorization': 'Bearer ' + self.token, **ACCEPT}

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.to_child.aclose()
        self.store.close()
        self.state_dir.cleanup()

    async def rpc(self, headers, body):
        answer = await self.client.post('/mcp', headers=headers, json=body)
        self.assertEqual(answer.status_code, 200, answer.text[:500])
        if 'id' not in body:
            return None
        if answer.headers.get('mcp-session-id'):
            headers['Mcp-Session-Id'] = answer.headers['mcp-session-id']
        return message(answer, body['id'])

    async def handshake(self, version, headers):
        result = (await self.rpc(headers, initialize(version)))['result']
        self.assertIn('Mcp-Session-Id', headers)
        headers['MCP-Protocol-Version'] = result['protocolVersion']
        answer = await self.client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        self.assertEqual(answer.status_code, 202)
        return result

    async def test_server_discover_gets_a_clean_error(self):
        for headers in ({**self.auth, 'MCP-Protocol-Version': MODERN, 'Mcp-Method': 'server/discover'}, self.auth):
            with self.subTest(headers=sorted(headers)):
                answer = await self.client.post('/mcp', headers=headers, json=DISCOVER)
                self.assertEqual(answer.status_code, 200)
                self.assertNotIn('mcp-session-id', answer.headers)
                self.assertEqual(answer.json(), {'jsonrpc': '2.0', 'id': 0,
                                                 'error': {'code': -32601, 'message': 'Method not found'}})
        unauthorized = await self.client.post('/mcp', headers=ACCEPT, json=DISCOVER)
        self.assertEqual(unauthorized.status_code, 401)

    async def test_the_child_itself_refuses_a_2026_header_on_initialize(self):
        # The premise of the gateway's change: mcp 1.x ignored the header on an initialize, SDK 2 routes it to its
        # 2026-07-28 handling, which refuses an initialize.
        answer = await self.to_child.post('http://127.0.0.1:3000/mcp', json=initialize('2025-11-25'),
                                          headers={**ACCEPT, 'MCP-Protocol-Version': MODERN})
        self.assertEqual(answer.status_code, 400)
        self.assertNotIn('mcp-session-id', answer.headers)

    async def test_legacy_initialize_list_and_call_through_the_gateway(self):
        for version in sorted(gateway.PROTOCOL_VERSIONS):
            for modern_header in (False, True):
                with self.subTest(version=version, modern_header=modern_header):
                    headers = {**self.auth, **({'MCP-Protocol-Version': MODERN} if modern_header else {})}
                    result = await self.handshake(version, headers)
                    self.assertEqual(result['protocolVersion'], version)
                    self.assertEqual(result['serverInfo'], {'name': 'woow-mcp-opendesign', 'version': VERSION})
                    listed = (await self.rpc(headers, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}))['result']
                    self.assertEqual(listed, LISTED)  # the 15 tools exactly as 0.2.5 listed them
                    called = (await self.rpc(headers, {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
                        'name': 'health', 'arguments': {}}}))['result']
                    self.assertIsNot(called.get('isError'), True, called)
                    self.assertEqual(json.loads(called['content'][0]['text']), {'ok': True, 'version': '0.24.1'})
                    failed = (await self.rpc(headers, {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {
                        'name': 'get_project', 'arguments': {'project_id': MISSING}}}))['result']
                    self.assertTrue(failed['isError'])
                    self.assertEqual([item['text'] for item in failed['content']],
                                     ['Error executing tool get_project: BACKEND_HTTP_ERROR status=404'])
                    ended = await self.client.delete('/mcp', headers=headers)
                    self.assertIn(ended.status_code, (200, 204))

    async def test_a_2026_request_in_a_session_fails_as_before(self):
        headers = dict(self.auth)
        await self.handshake('2025-11-25', headers)
        answer = await self.client.post('/mcp', headers={**headers, 'MCP-Protocol-Version': MODERN},
                                        json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        self.assertEqual(answer.status_code, 400)
        self.assertNotIn('tools', answer.text)
        listed = (await self.rpc(headers, {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'}))['result']
        self.assertEqual(len(listed['tools']), 15)
        await self.client.delete('/mcp', headers=headers)

    async def test_the_request_body_ceiling(self):
        self.assertEqual(gateway.MAX_REQUEST, 16 * 1024 * 1024)
        headers = dict(self.auth)
        await self.handshake('2025-11-25', headers)
        # Just under the ceiling: read, then refused by the tool's own argument model (a prompt is at most 20,000
        # characters), never by size.
        body = {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {
            'name': 'create_project', 'arguments': {'prompt': 'x' * (gateway.MAX_REQUEST - 4096)}}}
        refused = await self.rpc(headers, body)
        self.assertEqual(refused['error']['code'], -32602)
        self.assertEqual(refused['error']['data']['errors'][0]['field'], 'prompt')
        over = json.dumps({**body, 'params': {'name': 'create_project',
                                              'arguments': {'prompt': 'x' * gateway.MAX_REQUEST}}})
        answer = await self.client.post('/mcp', headers={**headers, 'Content-Type': 'application/json'}, content=over)
        self.assertEqual(answer.status_code, 413)
        await self.client.delete('/mcp', headers=headers)


if __name__ == '__main__':
    unittest.main()
