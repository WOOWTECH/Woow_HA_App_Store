"""Builtin deployment hooks use the same management contract while retaining its 15-tool policy.

0.2.6 (runtime 0.4.0): on the HA schema 3 store (state.BuiltinStore): no operation denies (a policy carrying them is
refused), the configuration revision of the shared management contract, product.runtime_version kept.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CODE = os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1]))
VENDOR = os.environ.get('HA_OD_MCP_VENDOR', str(HERE.parents[1] / 'vendor'))
sys.path[:0] = [str(Path(VENDOR) / 'packages/mcp-admin-core'), CODE]

import httpx
from mcp_admin_core import VERSION
from mcp_admin_core.configuration import ConfigurationState
from mcp_admin_core.gateway import make_apps
from mcp_admin_core.products import TOOLS
from ha_opendesign_mcp import defaults, runtime, surface
from ha_opendesign_mcp.state import BuiltinStore


class Management(unittest.IsolatedAsyncioTestCase):
    async def test_builtin_fixed_backend_catalog_and_existing_grants(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BuiltinStore(Path(directory))
            try:
                runtime.pin_backend(store)
                defaults.apply(store)
                store.update(disabled=['send_message'])
                before = store.load().model_dump()
                async def reply(request):
                    if request.method == 'DELETE':
                        return httpx.Response(200)
                    message = json.loads(request.content)
                    if 'id' not in message:
                        return httpx.Response(202)
                    result = {'serverInfo': {'name': 'opendesign', 'version': '1'}, 'protocolVersion': '2025-03-26'}
                    if message['method'] == 'tools/list':
                        result = {'tools': [{'name': name, 'description': name, 'inputSchema': {'type': 'object'}}
                                           for name in surface.NAMES]}
                    return httpx.Response(200, headers={'mcp-session-id': 'owned'}, json={
                        'jsonrpc': '2.0', 'id': message['id'], 'result': result})
                async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as child:
                    admin, _ = make_apps(store, TOOLS['opendesign'], child, verify_admin=runtime.ingress_user,
                        management=runtime.management_options(), configuration=ConfigurationState(store))
                    wrapped = runtime.IngressSocketPeer(admin)
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(wrapped, client=None), base_url='http://builtin') as client:
                        identity = {'x-remote-user-id': 'a'*32}
                        b = (await client.get('/api/bootstrap', headers=identity)).json()
                        self.assertEqual(b['policy_contract'], 'woow-v3-exact-grants')
                        self.assertNotIn('denied_operations', b)  # schema 3: no operation denies
                        self.assertEqual(set(b['tools']), surface.NAMES)
                        self.assertEqual(b['tools']['read_file']['inputSchema'], surface.ReadFile.model_json_schema())
                        self.assertEqual(b['enabled_write_tools'], ['create_project', 'delete_project', 'send_message'])
                        self.assertEqual(b['disabled'], ['send_message'])
                        cap = (await client.get('/api/capabilities', headers=identity)).json()
                        self.assertEqual(cap['admin']['authority'], 'ha-ingress')
                        self.assertEqual(cap['deployment']['kind'], 'builtin')
                        self.assertEqual(cap['product']['version'], os.environ.get('WOOW_ADDON_VERSION', 'unknown'))
                        self.assertEqual(cap['product']['runtime_version'], VERSION)
                        self.assertEqual(VERSION, '0.4.0')
                        self.assertFalse(cap['backend']['can_edit'])
                        self.assertFalse(cap['capabilities']['operation_denies'])
                        self.assertEqual(cap['tools']['catalog_count'], 15)
                        self.assertEqual(cap['tools']['effective_count'], 14)
                        items = {item['name']: item for item in cap['tools']['items']}
                        self.assertFalse(items['send_message']['policy_enabled'])
                        self.assertEqual(items['read_file']['schema_source'], 'registry')
                        self.assertIn('file_path', items['read_file']['inputSchema']['properties'])
                        denied = await client.put('/api/backend', headers={**identity, 'x-csrf-token': b['csrf']},
                                                  json={'connection': {'url': 'http://127.0.0.1:9999'}})
                        self.assertEqual(denied.status_code, 403)
                        # A policy with operation denies (a schema 4 field) is refused; nothing is saved.
                        policy = {'writes_enabled': False, 'disabled': [], 'enabled_write_tools': ['create_project'],
                                  'denied_operations': {'create_project': ['x']}}
                        refused = await client.put('/api/policy', headers={**identity, 'x-csrf-token': b['csrf']},
                                                   json=policy)
                        self.assertEqual(refused.status_code, 400)
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(wrapped), base_url='http://builtin') as public:
                        self.assertEqual((await public.get('/api/capabilities', headers=identity)).status_code, 403)
                self.assertEqual(store.load().model_dump(), before)
            finally:
                store.close()

    async def test_policy_saves_stay_schema_3(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BuiltinStore(Path(directory))
            try:
                runtime.pin_backend(store)
                defaults.apply(store)
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as child:
                    admin, _ = make_apps(store, TOOLS['opendesign'], child, verify_admin=runtime.ingress_user,
                        management=runtime.management_options(), configuration=ConfigurationState(store))
                    wrapped = runtime.IngressSocketPeer(admin)
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(wrapped, client=None), base_url='http://builtin') as client:
                        identity = {'x-remote-user-id': 'b'*32}
                        bootstrap = await client.get('/api/bootstrap', headers=identity)
                        b = bootstrap.json()
                        saved = await client.put('/api/policy', json={
                            'writes_enabled': False, 'disabled': ['list_skills'], 'enabled_write_tools': ['delete_project']},
                            headers={**identity, 'x-csrf-token': b['csrf'], 'if-match': bootstrap.headers['etag']})
                        self.assertEqual(saved.status_code, 200, saved.text)
                        self.assertTrue(saved.json()['saved'])
                        stale = await client.put('/api/policy', json={
                            'writes_enabled': False, 'disabled': [], 'enabled_write_tools': []},
                            headers={**identity, 'x-csrf-token': b['csrf'], 'if-match': bootstrap.headers['etag']})
                        self.assertEqual(stale.status_code, 409)  # an edit from a page that did not see the save
                stored = json.loads((Path(directory) / 'state.json').read_text())
                self.assertEqual(stored['schema_version'], 3)
                self.assertEqual((stored['disabled'], stored['enabled_write_tools']), (['list_skills'], ['delete_project']))
                self.assertNotIn('denied_operations', stored)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
