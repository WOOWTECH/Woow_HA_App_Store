"""Product-scoped read_file output pin; all HTTP peers and credentials are synthetic."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
CODE = Path(os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1])))
VENDOR = Path(os.environ.get('HA_OD_MCP_VENDOR', str(CODE / 'vendor')))
sys.path[:0] = [str(VENDOR / 'packages/mcp-admin-core'), str(CODE)]

import httpx  # noqa: E402
from mcp_admin_core import gateway, policy  # noqa: E402
from mcp_admin_core.products import TOOLS  # noqa: E402
from ha_opendesign_mcp import defaults, output_contract as contract, runtime  # noqa: E402
from ha_opendesign_mcp.state import BuiltinStore  # noqa: E402

PIN = contract.READ_FILE_OUTPUT
RAW = {'name': 'read_file', 'description': 'Read a text file',
       'inputSchema': {'type': 'object'}, 'outputSchema': PIN}
OTHER = {'name': 'health', 'inputSchema': {'type': 'object'}, 'outputSchema': PIN}
INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': '2025-11-25', 'capabilities': {},
    'clientInfo': {'name': 'output-contract-test', 'version': '0'}}}


def listed(schema=PIN, *, disabled=()):
    child = copy.deepcopy(RAW)
    if schema is None:
        child.pop('outputSchema')
    else:
        child['outputSchema'] = schema
    with tempfile.TemporaryDirectory() as directory:
        store = BuiltinStore(Path(directory))
        try:
            defaults.apply(store)
            if disabled:
                store.update(disabled=list(disabled))
            message = {'jsonrpc': '2.0', 'id': 2, 'result': {'tools': [child, copy.deepcopy(OTHER)]}}
            return gateway.filter_list(message, TOOLS['opendesign'], store.load())['result']['tools']
        finally:
            store.close()


class ReviewedPin(unittest.TestCase):
    def test_exact_only_and_generic_vendor_stays_closed(self):
        contract.guard_vendor()
        contract.install()  # repeated install is safe
        self.assertIs(gateway.filter_list, contract.filter_list)
        tools = listed()
        self.assertEqual([t['name'] for t in tools], ['read_file', 'health'])
        self.assertEqual(tools[0]['outputSchema'], PIN)
        self.assertIsNot(tools[0]['outputSchema'], PIN)
        self.assertNotIn('outputSchema', tools[1])
        for changed in (None, {}, {'type': 'object'},
                        {**PIN, 'title': 'different'},
                        {**PIN, 'extra': True},
                        {**PIN, '$ref': 'https://example.invalid/schema'},
                        {**PIN, 'properties': {'result': {'type': 'string', 'pattern': '(a+)+$'}}}):
            with self.subTest(changed=changed):
                self.assertNotIn('outputSchema', listed(changed)[0])
        self.assertEqual([t['name'] for t in listed(disabled=['read_file'])], ['health'])
        with tempfile.TemporaryDirectory() as directory:
            store = BuiltinStore(Path(directory))
            try:
                raw = {'result': {'tools': [copy.deepcopy(RAW)]}}
                self.assertNotIn('outputSchema', policy.filter_list(raw, TOOLS['opendesign'], store.load())
                                 ['result']['tools'][0])
            finally:
                store.close()

    def test_source_hash_signature_and_binding_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'vendor/packages/mcp-admin-core/mcp_admin_core'
            installed = root / 'packages/mcp-admin-core/mcp_admin_core'
            with self.assertRaisesRegex(RuntimeError, 'one known vendor layout'):
                contract._vendor_dir(root)
            source.mkdir(parents=True)
            self.assertEqual(contract._vendor_dir(root), source)
            source.rmdir()
            installed.mkdir(parents=True)
            self.assertEqual(contract._vendor_dir(root), installed)
            source.mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, 'one known vendor layout'):
                contract._vendor_dir(root)
        with mock.patch.dict(contract.VENDOR_SHA256, {'policy.py': '0' * 64}):
            with self.assertRaisesRegex(RuntimeError, 'reviewed vendor'):
                contract.guard_vendor()
        with mock.patch.object(gateway, 'filter_list', lambda *args: None):
            with self.assertRaisesRegex(RuntimeError, 'hook already changed'):
                contract.install()
        self.assertIs(gateway.filter_list, contract.filter_list)

    def test_installed_layout_import_checks_reviewed_vendor_and_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(VENDOR / 'packages/mcp-admin-core', root / 'packages/mcp-admin-core',
                            ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(CODE / 'ha_opendesign_mcp', root / 'ha_opendesign_mcp',
                            ignore=shutil.ignore_patterns('__pycache__'))
            env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(root),
                   'PYTHONDONTWRITEBYTECODE': '1',
                   'PYTHONPATH': str(root / 'packages/mcp-admin-core') + ':' + str(root)}
            command = ('from ha_opendesign_mcp import output_contract, runtime; '
                       'from mcp_admin_core import gateway; '
                       'output_contract.guard_vendor(); '
                       'assert gateway.filter_list is output_contract.filter_list; '
                       'assert gateway.tool_catalog is output_contract.tool_catalog')
            result = subprocess.run([sys.executable, '-B', '-c', command], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr[-1000:])

    def test_duplicate_child_name_cannot_make_catalog_or_listing_false_green(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BuiltinStore(Path(directory))
            try:
                defaults.apply(store)
                state = store.load()
                for second in (copy.deepcopy(RAW), {**RAW, 'outputSchema': {'type': 'object'}}):
                    for pair in ([copy.deepcopy(RAW), second], [second, copy.deepcopy(RAW)]):
                        with self.subTest(pair=pair):
                            reply = gateway.filter_list({'result': {'tools': pair}}, TOOLS['opendesign'], state)
                            self.assertTrue(all('outputSchema' not in tool for tool in reply['result']['tools']))
                            catalog = gateway.tool_catalog(TOOLS['opendesign'], [copy.deepcopy(RAW)], pair, state)
                            item = next(x for x in catalog['items'] if x['name'] == 'read_file')
                            self.assertNotIn('outputSchema', item)
            finally:
                store.close()

    def test_observed_management_catalog_keeps_policy_and_never_uses_fallback_guess(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BuiltinStore(Path(directory))
            try:
                defaults.apply(store)
                registry = TOOLS['opendesign']
                state = store.load()
                pinned = [copy.deepcopy(RAW)]
                observed = [copy.deepcopy(RAW)]
                base = contract.ORIGINAL_CATALOG(registry, pinned, observed, state)
                result = gateway.tool_catalog(registry, pinned, observed, state)
                item = next(x for x in result['items'] if x['name'] == 'read_file')
                before = next(x for x in base['items'] if x['name'] == 'read_file')
                self.assertEqual({k: v for k, v in item.items() if k not in
                                  ('outputSchema', 'output_schema_source')}, before)
                self.assertTrue(item['policy_enabled'] and item['effective'])
                self.assertEqual(item['outputSchema'], PIN)
                self.assertEqual(item['output_schema_source'], 'reviewed_child')
                for raw in (None, [], [{**RAW, 'outputSchema': {**PIN, 'extra': 1}}],
                            [{k: v for k, v in RAW.items() if k != 'outputSchema'}]):
                    with self.subTest(raw=raw):
                        missing = gateway.tool_catalog(registry, pinned, raw, state)
                        self.assertNotIn('outputSchema', next(x for x in missing['items']
                                                             if x['name'] == 'read_file'))
                store.update(disabled=['read_file'])
                disabled = gateway.tool_catalog(registry, pinned, observed, store.load())
                item = next(x for x in disabled['items'] if x['name'] == 'read_file')
                self.assertFalse(item['policy_enabled'])
                self.assertFalse(item['effective'])
                self.assertEqual(item['reason'], 'policy_disabled')
                self.assertNotIn('outputSchema', item)
            finally:
                store.close()


class GatewayPaths(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = BuiltinStore(Path(self.temp.name))
        runtime.pin_backend(self.store)
        defaults.apply(self.store)
        self.token = self.store.load().token

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    async def exercise(self, mode):
        requests = []

        def child(request):
            if mode == 'local':
                raise AssertionError('local listed_reply reached child')
            payload = json.loads(request.content) if request.method == 'POST' and request.content else {}
            requests.append(payload.get('method'))
            method = payload.get('method')
            if request.method == 'DELETE':
                return httpx.Response(200)
            if method == 'notifications/initialized':
                return httpx.Response(202)
            result = ({'protocolVersion': '2025-11-25', 'serverInfo': {'name': 'od', 'version': '1'},
                       'capabilities': {'tools': {}}} if method == 'initialize' else
                      {'tools': [copy.deepcopy(RAW), copy.deepcopy(OTHER)]})
            reply = {'jsonrpc': '2.0', 'id': payload['id'], 'result': result}
            if mode == 'sse' and method == 'tools/list':
                return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                      content=('event: message\ndata: ' + json.dumps(reply) + '\n\n').encode())
            return httpx.Response(200, headers={'mcp-session-id': 'synthetic-session'}, json=reply)

        async with httpx.AsyncClient(transport=httpx.MockTransport(child)) as upstream:
            options = {'listing': [copy.deepcopy(RAW), copy.deepcopy(OTHER)],
                       'availability': lambda: {'child': 'backoff', 'ready': False,
                                                'backend': 'unknown', 'reason': None}} if mode == 'local' else {}
            _, app = gateway.make_apps(self.store, TOOLS['opendesign'], upstream,
                                       verify_admin=runtime.ingress_user, **options)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                         base_url='http://addon') as client:
                headers = {'Authorization': 'Bearer ' + self.token,
                           'Accept': 'application/json, text/event-stream'}
                initialized = await client.post('/mcp', headers=headers, json=INIT)
                self.assertEqual(initialized.status_code, 200, initialized.text[:200])
                headers['Mcp-Session-Id'] = initialized.headers['mcp-session-id']
                headers['MCP-Protocol-Version'] = '2025-11-25'
                notified = await client.post('/mcp', headers=headers,
                                             json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
                self.assertEqual(notified.status_code, 202)
                for disabled in (False, True):
                    if disabled:
                        self.store.update(disabled=['read_file'])
                    answer = await client.post('/mcp', headers=headers,
                                               json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
                    self.assertEqual(answer.status_code, 200, answer.text[:200])
                    if mode == 'sse':
                        self.assertTrue(answer.headers['content-type'].startswith('text/event-stream'))
                        payload = json.loads(next(line[5:].strip() for line in answer.text.splitlines()
                                                  if line.startswith('data:')))
                    else:
                        self.assertTrue(answer.headers['content-type'].startswith('application/json'))
                        payload = answer.json()
                    tools = payload['result']['tools']
                    self.assertEqual([t['name'] for t in tools], ['health'] if disabled else
                                     ['read_file', 'health'])
                    if not disabled:
                        self.assertEqual(tools[0]['outputSchema'], PIN)
                        self.assertNotIn('outputSchema', tools[1])
                await client.delete('/mcp', headers=headers)
        if mode == 'local':
            self.assertEqual(requests, [])
        else:
            self.assertEqual(requests.count('tools/list'), 2)

    async def test_proxied_json(self):
        await self.exercise('json')

    async def test_proxied_sse(self):
        await self.exercise('sse')

    async def test_vendor_local_listed_reply(self):
        await self.exercise('local')


if __name__ == '__main__':
    unittest.main()
