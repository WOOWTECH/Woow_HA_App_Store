"""0.2.1 gateway side: the 15-tool OpenDesign table, its argument models and the default grants, with the vendored
policy and gateway and (0.2.6) the HA schema 3 store, state.BuiltinStore (management virtual environment).

HA_OD_MCP_CODE: the directory holding ha_opendesign_mcp; HA_OD_MCP_VENDOR: the directory holding packages/ and apps/
(defaults: this repository's mcp-runtime and mcp-runtime/vendor; /opt/woow for both in the image).
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
sys.path[:0] = [str(Path(VENDOR) / 'packages' / 'mcp-admin-core'), CODE]

from mcp_admin_core import policy, products  # noqa: E402
from mcp_admin_core.config import ConfigError  # noqa: E402
from mcp_admin_core.products import TOOLS  # noqa: E402

from ha_opendesign_mcp import defaults, surface  # noqa: E402
from ha_opendesign_mcp.state import BuiltinStore  # noqa: E402  0.2.6: the schema 3 store

surface.install()
TABLE = TOOLS['opendesign']
PROJECT = '76c45d7a-3147-45cf-a3f4-295ee256e48e'
MARKER = 'probe-input-marker-qqqqqqqqqqqq'
READS = {'health', 'version', 'list_agents', 'list_connectors', 'list_projects', 'get_project', 'list_project_files',
         'read_file', 'get_file_info', 'list_runs', 'list_plugins', 'list_skills'}
WRITERS = {'create_project', 'delete_project', 'send_message'}


def call(name, arguments):
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}


class Table(unittest.TestCase):
    def test_fifteen_tools(self):
        self.assertEqual(set(TABLE), READS | WRITERS)
        self.assertEqual(len(TABLE), 15)
        self.assertEqual({name for name, tool in TABLE.items() if tool.write}, WRITERS)
        self.assertIs(surface.install(), TABLE)  # idempotent
        self.assertEqual(list(TABLE), list(surface.TABLE))
        self.assertTrue(all(TABLE[name] is tool for name, tool in surface.TABLE.items()))

    def test_bounded_models_not_the_vendored_full_surface(self):
        # 0.2.6: the pinned runtime's own TOOLS['opendesign'] is the standalone add-on's full surface (any JSON object,
        # the child's schema). This table keeps the bounded models: the 11 of products.BOUNDED_TOOLS plus ADDED.
        self.assertFalse(any(tool.child_schema for tool in TABLE.values()))
        self.assertTrue(all(TABLE[name] is tool for name, tool in products.BOUNDED_TOOLS['opendesign'].items()))
        self.assertEqual(list(products.BOUNDED_TOOLS['opendesign']), list(surface.BOUNDED))
        full = products.full_tools('opendesign')
        self.assertEqual(set(full), set(TABLE))  # same names, other models
        self.assertTrue(all(tool.child_schema for tool in full.values()))

    def test_conflicting_pin_refused(self):
        bounded = products.BOUNDED_TOOLS['opendesign']
        bounded['read_file'] = policy.Tool(surface.ReadFile)  # a pin that defines one of the four itself
        try:
            with self.assertRaises(RuntimeError):
                surface.table()
        finally:
            del bounded['read_file']
        saved = bounded.pop('list_runs')  # a pin without one of the 11
        try:
            with self.assertRaises(RuntimeError):
                surface.table()
        finally:
            bounded['list_runs'] = saved
        self.assertEqual(list(surface.table()), list(surface.TABLE))

    def test_declared_schemas_are_plain_objects(self):
        for name, tool in TABLE.items():
            schema = policy.declared_schema(tool.arguments)
            self.assertEqual(schema['type'], 'object', name)
            self.assertFalse(policy.TOP_LEVEL_REFUSED & schema.keys(), name)
        self.assertEqual(sorted(policy.declared_schema(surface.SendMessage)['properties']),
                         ['agent_id', 'project_id', 'prompt'])
        self.assertEqual(policy.declared_schema(surface.CreateProject)['required'], ['prompt'])


class Arguments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = BuiltinStore(Path(self.tmp.name))
        self.store.update(connection={'url': 'http://127.0.0.1:7456'})
        defaults.apply(self.store)
        self.state = self.store.load()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def allowed(self, name, arguments):
        message = call(name, arguments)
        policy.authorize(message, TABLE, self.state)
        return message['params']['arguments']

    def refused(self, name, arguments):
        with self.assertRaises(policy.ToolCallRefused) as caught:
            policy.authorize(call(name, arguments), TABLE, self.state)
        error = caught.exception.error()
        self.assertNotIn(MARKER, json.dumps(error))
        return caught.exception

    def test_read_file(self):
        self.assertEqual(self.allowed('read_file', {'project_id': PROJECT, 'file_path': 'src/index.html'}),
                         {'project_id': PROJECT, 'file_path': 'src/index.html'})
        refusal = self.refused('read_file', {'project_id': PROJECT, 'file_path': '.env'})
        self.assertEqual(refusal.kind, 'invalid_params')
        self.assertEqual(refusal.errors[0]['field'], 'file_path')
        self.assertIn('secret-like file name refused', refusal.errors[0]['message'])
        for path in ('keys/id_rsa', 'server.pem', 'credentials.json', '../x', 'a/../b', '/etc/passwd', 'a%2e'):
            with self.subTest(path=path):
                self.assertEqual(self.refused('read_file', {'project_id': PROJECT, 'file_path': path}).kind,
                                 'invalid_params')
        self.refused('read_file', {'project_id': PROJECT, 'file_path': 'a.html', 'extra': MARKER})
        self.refused('read_file', {'project_id': MARKER, 'file_path': 'a.html'})

    def test_list_connectors(self):
        self.assertEqual(self.allowed('list_connectors', {}), {})
        self.refused('list_connectors', {'filter': MARKER})

    def test_create_project(self):
        self.assertEqual(self.allowed('create_project', {'prompt': 'A landing page'}),
                         {'prompt': 'A landing page', 'agent_id': 'claude'})
        self.assertEqual(self.allowed('create_project', {'prompt': 'x', 'agent_id': 'byok-opencode'})['agent_id'],
                         'byok-opencode')
        for arguments in ({}, {'prompt': ''}, {'prompt': 'x' * 20001}, {'prompt': 'x', 'agent_id': 'Claude'},
                          {'prompt': 'x', 'agent_id': '../bin/sh'}, {'prompt': 'x', 'agent_id': MARKER + ' x'},
                          {'prompt': 'x', 'project_id': PROJECT}, {'prompt': 1}):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.refused('create_project', arguments).kind, 'invalid_params')

    def test_send_message(self):
        self.assertEqual(self.allowed('send_message', {'project_id': PROJECT, 'prompt': 'Make it blue'}),
                         {'project_id': PROJECT, 'prompt': 'Make it blue', 'agent_id': 'claude'})
        self.refused('send_message', {'prompt': 'x'})
        self.refused('send_message', {'project_id': 'nope', 'prompt': 'x'})


class Defaults(unittest.TestCase):
    """Fresh install, a 0.2.0 state, an administrator's disable, and the one-time marker, on the schema 3 store."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def enabled(self, store):
        state = store.load()
        return {name for name in TABLE if policy.enabled(name, TABLE, state)}

    def listed(self, store):
        child = {'jsonrpc': '2.0', 'id': 2, 'result': {'tools': [{'name': name, 'inputSchema': {}} for name in TABLE]}}
        return {tool['name'] for tool in policy.filter_list(child, TABLE, store.load())['result']['tools']}

    def test_fresh_install_all_fifteen(self):
        store = BuiltinStore(self.dir)
        try:
            self.assertEqual(self.enabled(store), READS)  # what 0.2.0's rules give a new state: 12 reads
            defaults.apply(store)
            self.assertEqual(self.enabled(store), READS | WRITERS)
            self.assertEqual(len(self.listed(store)), 15)
        finally:
            store.close()

    def write_020_state(self, **fields):
        """A 0.2.0 state: schema 3, the same fields; only 0.2.0's grants (none, or delete_project) possible."""
        store = BuiltinStore(self.dir)
        try:
            store.update(connection={'url': 'http://127.0.0.1:7456'}, **fields)
        finally:
            store.close()

    def test_existing_020_state(self):
        self.write_020_state(enabled_write_tools=['delete_project'], disabled=['list_skills'])
        store = BuiltinStore(self.dir)
        try:
            record = defaults.apply(store)
            self.assertEqual(record['granted'], ['create_project', 'send_message'])
            state = store.load()
            self.assertEqual(state.enabled_write_tools, ['delete_project', 'create_project', 'send_message'])
            self.assertEqual(state.disabled, ['list_skills'])
            self.assertEqual(state.connection.url, 'http://127.0.0.1:7456')
            self.assertEqual(self.enabled(store), (READS | WRITERS) - {'list_skills'})
        finally:
            store.close()

    def test_admin_disabled_writer_respected(self):
        self.write_020_state(disabled=['delete_project'])
        store = BuiltinStore(self.dir)
        try:
            defaults.apply(store)
            self.assertEqual(self.enabled(store), READS | {'create_project', 'send_message'})
            self.assertEqual(len(self.listed(store)), 14)
        finally:
            store.close()

    def test_admin_revocation_survives_restart(self):
        store = BuiltinStore(self.dir)
        try:
            defaults.apply(store)
            store.update(enabled_write_tools=[], writes_enabled=False)  # PUT /api/policy: every grant removed
        finally:
            store.close()
        store = BuiltinStore(self.dir)  # next start
        try:
            self.assertIsNone(defaults.apply(store))
            self.assertEqual(self.enabled(store), READS)
        finally:
            store.close()

    def test_grants_are_this_tables_writers(self):
        """The state accepts grants for the three writers of this table only (0.2.6: checked against surface.TABLE)."""
        store = BuiltinStore(self.dir)
        try:
            for grants in (['list_projects'], ['create_project', 'create_project'], ['n8n_delete_workflow']):
                with self.subTest(grants=grants), self.assertRaises(ConfigError):
                    store.update(enabled_write_tools=grants)
            self.assertEqual(store.load().enabled_write_tools, [])
        finally:
            store.close()


if __name__ == '__main__':
    unittest.main(verbosity=1)
