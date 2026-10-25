"""0.2.6: the update from 0.2.5 keeps the built-in server's state as it is (management venv; the non-container part
of the upgrade proof).

fixtures/state-0.2.5.json is a state that v0.2.5 wrote and an administrator then changed on its MCP Server page
(list_skills turned off, delete_project revoked, the client endpoint saved), with the one-time default grants marker
of 0.2.1. 0.2.6's store (state.BuiltinStore) loads it unchanged, writes nothing at start (runtime.pin_backend and
defaults.apply find nothing to do) and keeps schema 3 when the policy is saved again. The vendored products.ProductStore
of the runtime pinned since 0.2.6 would migrate the same state to schema 4 with every write granted and every tool
enabled again, which is why the built-in server does not use it. HA_OD_MCP_CODE / HA_OD_MCP_VENDOR: as in
test_surface.py.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CODE = os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1]))
VENDOR = os.environ.get('HA_OD_MCP_VENDOR', str(HERE.parents[1] / 'vendor'))
sys.path[:0] = [str(Path(VENDOR) / 'packages/mcp-admin-core'), CODE]

from mcp_admin_core import policy, products  # noqa: E402
from mcp_admin_core.config import ConfigError  # noqa: E402

from ha_opendesign_mcp import defaults, runtime, surface  # noqa: E402
from ha_opendesign_mcp.state import BuiltinState, BuiltinStore  # noqa: E402

FIXTURE = json.loads((HERE / 'fixtures' / 'state-0.2.5.json').read_text())
STATE = FIXTURE['state.json']
TABLE = surface.install()


class Upgrade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / 'mcp'

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, state=STATE, marker=True):
        self.dir.mkdir(mode=0o700)
        (self.dir / 'state.json').write_text(json.dumps(state))
        (self.dir / 'state.json').chmod(0o600)
        if marker:
            (self.dir / 'ha-tool-defaults.json').write_text(json.dumps(FIXTURE['ha-tool-defaults.json']))
        (self.dir / '.writer.lock').touch(mode=0o600)  # an existing installation: never a first boot

    def stored(self):
        return json.loads((self.dir / 'state.json').read_text())

    def test_a_025_state_loads_and_starts_unchanged(self):
        self.write()
        raw = (self.dir / 'state.json').read_bytes()
        store = BuiltinStore(self.dir)
        try:
            self.assertEqual(store.load().model_dump(mode='json'), STATE)
            runtime.pin_backend(store)  # the fixed backend is already the stored one
            self.assertIsNone(defaults.apply(store))  # the 0.2.1 marker: nothing is granted again
            self.assertEqual((self.dir / 'state.json').read_bytes(), raw)  # nothing written at start
            state = store.load()
            enabled = {name for name in TABLE if policy.enabled(name, TABLE, state)}
            self.assertEqual(enabled, surface.NAMES - {'list_skills', 'delete_project'})
            # A later policy save on the MCP Server page keeps schema 3 and every other key.
            store.update(disabled=[], enabled_write_tools=['create_project', 'send_message', 'delete_project'])
            self.assertEqual(self.stored(), {**STATE, 'disabled': [],
                                             'enabled_write_tools': ['create_project', 'send_message', 'delete_project']})
        finally:
            store.close()
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['.writer.lock', 'ha-tool-defaults.json', 'state.json'])

    def test_a_fresh_install_is_0_2_5s(self):
        store = BuiltinStore(self.dir)
        try:
            state = store.load()
            self.assertEqual((state.schema_version, state.product, state.connection, state.enabled_write_tools,
                              state.writes_enabled, state.disabled), (3, 'opendesign', None, [], False, []))
            self.assertEqual(set(self.stored()), set(STATE))
            runtime.pin_backend(store)
            self.assertEqual(defaults.apply(store)['granted'], ['create_project', 'delete_project', 'send_message'])
            self.assertEqual(self.stored()['schema_version'], 3)
        finally:
            store.close()

    def test_other_states_are_refused_never_rewritten(self):
        schema_4 = {**STATE, 'schema_version': 4, 'denied_operations': {}, 'mcp_access_token': None}
        cases = {'schema 4 (the standalone add-ons)': schema_4,
                 'schema 2': {k: v for k, v in {**STATE, 'schema_version': 2}.items() if k != 'enabled_write_tools'},
                 'another product': {**STATE, 'product': 'hermes'},
                 'operation denies': {**STATE, 'denied_operations': {}},
                 'a missing key': {k: v for k, v in STATE.items() if k != 'endpoint'},
                 'an unknown grant': {**STATE, 'enabled_write_tools': ['list_projects']},
                 'an untyped backend': {**STATE, 'backend_url': 'http://127.0.0.1:7456'}}
        for name, state in cases.items():
            with self.subTest(name):
                self.write(state)
                raw = (self.dir / 'state.json').read_bytes()
                with self.assertRaises(ConfigError):
                    BuiltinStore(self.dir)
                self.assertEqual((self.dir / 'state.json').read_bytes(), raw)
                shutil.rmtree(self.dir)

    def test_the_vendored_store_would_migrate_it(self):
        # Why state.py exists: the pinned runtime's own store turns the administrator's choices back on.
        self.write()
        store = products.ProductStore(self.dir, 'opendesign')
        try:
            state = store.load()
        finally:
            store.close()
        self.assertEqual(state.schema_version, 4)
        self.assertEqual(state.disabled, [])
        self.assertTrue(state.writes_enabled)
        self.assertEqual(sorted(state.enabled_write_tools), ['create_project', 'delete_project', 'send_message'])
        with self.assertRaises(ConfigError):
            BuiltinStore(self.dir)  # and 0.2.6 (like 0.2.5) cannot read what it wrote

    def test_the_model_is_0_2_5s(self):
        self.assertEqual(set(BuiltinState.model_fields), set(STATE))
        self.assertIs(runtime.BuiltinStore, BuiltinStore)
        self.assertNotIn('ProductStore', vars(runtime))


if __name__ == '__main__':
    unittest.main()
