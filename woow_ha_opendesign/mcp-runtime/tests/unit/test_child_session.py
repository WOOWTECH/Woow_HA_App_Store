"""0.2.4 child side: MCP sessions of the built-in child, built by child.setup() (the child's real entry, without
uvicorn) and driven through the SDK's own Streamable HTTP app (httpx ASGI transport, no network). 0.2.6: on MCP Python
SDK 2.3.0 (MCPServer), checked the way WOOWTECH/Woow_ha_mcp_addons 0.4.0 checks its children (tests/test_session_idle.py
there).

What the runtime documents (vendored apps/runtime/session_idle.py, gateway.end_session): a session that sees no
request for the limit (30 minutes; WOOW_MCP_SESSION_IDLE_SECONDS in tests) is ended and its id answers 404, so the
client initializes again; a session in use stays; DELETE ends it. The SDK (1.30.0 and 2.3.0) passes its own 30-minute
default explicitly, which session_idle replaces with the add-on limit. The SDK also caps the sessions at 10 000 (503
beyond) and limits request bodies (4 MiB by default): session_idle sets BODY_BYTES, the largest body the vendored
gateway forwards (gateway.MAX_REQUEST, 16 MiB since 0.2.6), so a body just under it reaches the child and one over it
gets 413.

HA_OD_MCP_CODE / HA_OD_MCP_VENDOR: as in test_surface.py.
"""
import ast
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
CODE = os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1]))
VENDOR = Path(os.environ.get('HA_OD_MCP_VENDOR', str(HERE.parents[1] / 'vendor')))
PATHS = [str(VENDOR / 'apps' / 'opendesign' / 'vendor'), str(VENDOR / 'apps' / 'runtime'),
         str(VENDOR / 'apps' / 'opendesign')]
LIMIT = 2.0  # seconds, this process only
os.environ['WOOW_MCP_SESSION_IDLE_SECONDS'] = str(LIMIT)
os.environ['OD_API_BASE'] = 'http://127.0.0.1:9'  # never contacted: initialize and tools/list stay in the child
sys.path[:0] = PATHS
sys.path.append(CODE)

import httpx  # noqa: E402
import launch  # noqa: E402  vendored
from mcp.server.streamable_http_manager import DEFAULT_MAX_SESSIONS  # noqa: E402
import session_idle  # noqa: E402  vendored apps/runtime

from ha_opendesign_mcp import child  # noqa: E402

APP, CLIENT, WORKERS = child.setup()
for name in ('httpx', 'mcp'):
    logging.getLogger(name).setLevel(logging.WARNING)
logging.getLogger('asyncio').setLevel(logging.ERROR)  # the test loop's debug mode calls the 16 MiB body's encoding slow
MANAGER = launch.mcp.session_manager
INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'session-test', 'version': '0'}}}
HEADERS = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}


def constant(node):
    """An integer written as a constant or a product of constants (0.2.6: gateway.MAX_REQUEST = 16 * 1024 * 1024)."""
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return constant(node.left) * constant(node.right)
    raise AssertionError('not an integer constant: ' + ast.dump(node))


def gateway_max_request():
    """MAX_REQUEST of the vendored gateway, read from its source (the child environment cannot import the gateway)."""
    tree = ast.parse((VENDOR / 'packages/mcp-admin-core/mcp_admin_core/gateway.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and [getattr(t, 'id', None) for t in node.targets] == ['MAX_REQUEST']:
            return constant(node.value)
    raise AssertionError('gateway.MAX_REQUEST not found')


def reply(response):
    """The JSON-RPC message of a 200 answer, plain JSON or one SSE event."""
    if response.headers.get('content-type', '').startswith('text/event-stream'):
        data = [line[5:].strip() for line in response.text.splitlines() if line.startswith('data:')]
        return json.loads(data[-1])
    return response.json()


class Settings(unittest.TestCase):
    def test_the_manager_gets_the_add_on_limits(self):
        from mcp.server.mcpserver import MCPServer
        self.assertIsInstance(launch.mcp, MCPServer)  # 0.2.6: MCP Python SDK 2
        self.assertEqual(MANAGER.session_idle_timeout, LIMIT)  # the env limit replaced MCPServer's explicit default
        self.assertFalse(MANAGER.stateless)
        self.assertEqual(MANAGER.max_sessions, DEFAULT_MAX_SESSIONS)
        self.assertEqual(DEFAULT_MAX_SESSIONS, 10000)
        self.assertEqual(MANAGER.max_request_body_size, session_idle.BODY_BYTES)
        self.assertEqual(session_idle.BODY_BYTES, gateway_max_request())
        self.assertEqual(session_idle.BODY_BYTES, 16 * 1024 * 1024)

    def test_a_production_child_ends_idle_sessions_after_30_minutes(self):
        # A fresh child process without the test variable, as the add-on starts it (setup(), no uvicorn).
        code = ('import sys; sys.path[:0] = %r; sys.path.append(%r)\n'
                'from ha_opendesign_mcp import child\n'
                'import launch\n'
                'app, client, workers = child.setup()\n'
                'm = launch.mcp.session_manager\n'
                'print(m.session_idle_timeout, m.max_sessions, m.max_request_body_size)\n'
                'workers.close(); client.close()\n') % (PATHS, CODE)
        env = {k: v for k, v in os.environ.items() if k != 'WOOW_MCP_SESSION_IDLE_SECONDS'}
        done = subprocess.run([sys.executable, '-B', '-W', 'ignore', '-c', code], env=env, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertEqual(done.stdout.split(), ['1800.0', '10000', str(session_idle.BODY_BYTES)])

    def test_an_invalid_limit_refuses_to_start(self):
        for value in ('0', 'abc', '100000'):
            os.environ['WOOW_MCP_SESSION_IDLE_SECONDS'] = value
            try:
                with self.assertRaises(ValueError):
                    session_idle.seconds()
            finally:
                os.environ['WOOW_MCP_SESSION_IDLE_SECONDS'] = str(LIMIT)


class Sessions(unittest.IsolatedAsyncioTestCase):
    async def test_idle_session_ends_used_session_stays_delete_ends(self):
        async with MANAGER.run():
            transport = httpx.ASGITransport(APP)
            async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:3000') as client:
                async def initialize():
                    response = await client.post('/mcp', headers=HEADERS, json=INIT)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertIn('result', reply(response))
                    session = response.headers['mcp-session-id']
                    headers = {**HEADERS, 'mcp-session-id': session, 'mcp-protocol-version': '2025-03-26'}
                    done = await client.post('/mcp', headers=headers,
                                             json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
                    self.assertEqual(done.status_code, 202)
                    return session, headers

                async def tools(headers, ident):
                    return await client.post('/mcp', headers=headers,
                                             json={'jsonrpc': '2.0', 'id': ident, 'method': 'tools/list'})

                first, headers = await initialize()
                # In use: a request every quarter of the limit keeps the session past the limit.
                for ident in range(2, 9):
                    await asyncio.sleep(LIMIT / 4)
                    response = await tools(headers, ident)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(len(reply(response)['result']['tools']), 15)
                # Idle for twice the limit: the session is gone and its id answers 404.
                await asyncio.sleep(LIMIT * 2)
                self.assertEqual((await tools(headers, 9)).status_code, 404)
                # The client initializes again and gets a new session.
                second, headers = await initialize()
                self.assertNotEqual(second, first)
                self.assertEqual((await tools(headers, 10)).status_code, 200)
                # The request body ceiling (0.2.6, as the HA MCP add-ons 0.4.0 check it): a ping whose _meta pads it
                # to just under BODY_BYTES reaches the child (the SDK's own 4 MiB limit would answer 413); one byte
                # over the limit does not.
                padding = 'A' * (session_idle.BODY_BYTES - 4096)
                big = {'jsonrpc': '2.0', 'id': 12, 'method': 'ping', 'params': {'_meta': {'padding': padding}}}
                self.assertLess(len(json.dumps(big)), session_idle.BODY_BYTES)
                response = await client.post('/mcp', headers=headers, json=big)
                self.assertEqual(response.status_code, 200, response.text[:200])
                self.assertEqual(reply(response)['result'], {})
                over = json.dumps({'jsonrpc': '2.0', 'id': 13, 'method': 'ping',
                                   'params': {'_meta': {'padding': 'A' * session_idle.BODY_BYTES}}})
                response = await client.post('/mcp', headers=headers, content=over)
                self.assertEqual(response.status_code, 413)
                # DELETE ends a session at once.
                self.assertEqual((await client.delete('/mcp', headers=headers)).status_code, 200)
                self.assertEqual((await tools(headers, 11)).status_code, 404)
                self.assertEqual(MANAGER._server_instances, {})


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        WORKERS.close()
        CLIENT.close()
