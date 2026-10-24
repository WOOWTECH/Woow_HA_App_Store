"""Builtin deployment hooks use the same management contract while retaining its 15-tool policy."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
CODE = os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1]))
VENDOR = os.environ.get('HA_OD_MCP_VENDOR', str(HERE.parents[1] / 'vendor'))
sys.path[:0] = [str(Path(VENDOR) / 'packages/mcp-admin-core'), CODE]

import httpx
from mcp_admin_core.capabilities import ManagementOptions
from mcp_admin_core.gateway import make_apps
from mcp_admin_core.products import ProductStore, TOOLS
from ha_opendesign_mcp import defaults, runtime, surface


class Management(unittest.IsolatedAsyncioTestCase):
    async def test_builtin_fixed_backend_catalog_and_existing_grants(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProductStore(Path(directory), 'opendesign')
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
                        management=runtime.management_options())
                    wrapped = runtime.IngressSocketPeer(admin)
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(wrapped, client=None), base_url='http://builtin') as client:
                        identity = {'x-remote-user-id': 'a'*32}
                        b = (await client.get('/api/bootstrap', headers=identity)).json()
                        cap = (await client.get('/api/capabilities', headers=identity)).json()
                        self.assertEqual(cap['admin']['authority'], 'ha-ingress')
                        self.assertEqual(cap['deployment']['kind'], 'builtin')
                        self.assertEqual(cap['product']['version'], os.environ.get('WOOW_ADDON_VERSION', 'unknown'))
                        self.assertEqual(cap['product']['runtime_version'], '0.1.14')
                        self.assertFalse(cap['backend']['can_edit'])
                        self.assertEqual(cap['tools']['catalog_count'], 15)
                        self.assertEqual(cap['tools']['effective_count'], 14)
                        items = {item['name']: item for item in cap['tools']['items']}
                        self.assertFalse(items['send_message']['policy_enabled'])
                        self.assertEqual(items['read_file']['schema_source'], 'registry')
                        self.assertIn('file_path', items['read_file']['inputSchema']['properties'])
                        denied = await client.put('/api/backend', headers={**identity, 'x-csrf-token': b['csrf']},
                                                  json={'connection': {'url': 'http://127.0.0.1:9999'}})
                        self.assertEqual(denied.status_code, 403)
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(wrapped), base_url='http://builtin') as public:
                        self.assertEqual((await public.get('/api/capabilities', headers=identity)).status_code, 403)
                self.assertEqual(store.load().model_dump(), before)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
