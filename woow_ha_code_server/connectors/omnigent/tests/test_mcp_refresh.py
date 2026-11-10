import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

import tomlkit

spec = importlib.util.spec_from_file_location("mcp_refresh", Path(__file__).parents[1] / "mcp_refresh.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ManagedMerge(unittest.TestCase):
    def test_add_update_remove_preserve_relay_model_permissions_and_unmanaged_server(self):
        original = '''# model chosen in this conversation
model = "private-model"
approval_policy = "on-request"
[mcp_servers.omnigent]
command = "private-relay"
[mcp_servers.private_only]
command = "private-server"
[mcp_servers.old]
command = "old-command"
'''
        added = module.merge_managed_servers(original, '[mcp_servers.new]\ncommand="new-command"\n', ["old", "new"])
        doc = tomlkit.parse(added)
        self.assertNotIn("old", doc["mcp_servers"])
        self.assertEqual(doc["mcp_servers"]["new"]["command"], "new-command")
        removed = tomlkit.parse(module.merge_managed_servers(added, '', ["old", "new"]))
        self.assertEqual(set(removed["mcp_servers"]), {"omnigent", "private_only"})
        self.assertEqual(removed["model"], "private-model")
        self.assertEqual(removed["approval_policy"], "on-request")
        self.assertIn("# model chosen", added)

    def test_relay_conflict_and_invalid_source_fail_before_write(self):
        with self.assertRaises(module.RefreshError):
            module.merge_managed_servers('', '', ['omnigent'])
        with self.assertRaises(Exception):
            module.merge_managed_servers('model="keep"', 'invalid [', ['new'])


class NativeLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bridge = self.root / 'bridge'
        self.home = self.bridge / 'codex-home'
        self.home.mkdir(parents=True)
        self.config = self.home / 'config.toml'
        self.original = 'model="private"\n[mcp_servers.old]\ncommand="old"\n'
        self.config.write_text(self.original)
        (self.root / 'shared').mkdir()
        (self.root / 'shared/managed.json').write_text(json.dumps({'servers':['new'], 'managedServers':['old','new']}))
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'config.toml').write_text('[mcp_servers.new]\ncommand="new"\n')
        self.state = SimpleNamespace(session_id='existing',active_turn_id=None,codex_home=str(self.home),socket_path='socket',thread_id='native-original')
        self.calls = []
        self.closed = False
        self.busy = False
        self.fail_reload = False
        owner = self
        class Client:
            async def connect(self): pass
            async def close(self): owner.closed = True
            async def request(self, method, params):
                owner.calls.append((method,params))
                if method == 'thread/read':
                    return {'result':{'thread':{'id':'native-original','status':{'type':'active' if owner.busy else 'idle'}}}}
                if method != 'config/mcpServer/reload':
                    raise AssertionError('unexpected native mutation')
                if owner.fail_reload: raise RuntimeError('synthetic failure')
                return {'result':{}}
        bridge_module = ModuleType('bridge')
        bridge_module.CODEX_NATIVE_BRIDGE_ID_LABEL_KEY = 'native-bridge'
        bridge_module.bridge_dir_for_bridge_id = lambda _: self.bridge
        bridge_module.read_bridge_state = lambda _: self.state
        app_module = ModuleType('app_server')
        app_module.client_for_transport = lambda *a,**kw: Client()
        self.mock_modules = patch.dict(sys.modules, {
            'omnigent.harnesses.codex_native.bridge':bridge_module,
            'omnigent.harnesses.codex_native.app_server':app_module,
        })
        self.mock_env = patch.dict(os.environ, {'PI_AGENT_DATA_DIR':str(self.root),'CODEX_HOME':str(self.source)})
        self.mock_modules.start(); self.mock_env.start()
        self.addCleanup(self.mock_modules.stop); self.addCleanup(self.mock_env.stop)

    async def test_native_reload_uses_original_thread_without_starting_or_stopping_turn(self):
        result = await module.refresh_codex('existing',{},sync=lambda:'a'*64)
        self.assertEqual(result['refresh']['state'],'queued')
        self.assertFalse(result['refresh']['toolsVerified'])
        self.assertEqual(result['refresh']['nativeSessionId'],'native-original')
        self.assertEqual([x[0] for x in self.calls],['thread/read','config/mcpServer/reload'])
        self.assertEqual(set(tomlkit.parse(self.config.read_text())['mcp_servers']),{'new'})
        self.assertEqual(tomlkit.parse(self.config.read_text())['model'],'private')
        self.assertEqual(self.config.stat().st_mode & 0o777,0o600)
        self.assertTrue(self.closed)

    async def test_active_thread_never_writes_config_or_syncs(self):
        self.busy=True
        with self.assertRaisesRegex(module.RefreshError,'SESSION_BUSY'):
            await module.refresh_codex('existing',{},sync=lambda:self.fail('sync'))
        self.assertEqual(self.config.read_text(),self.original)
        self.assertEqual(len(self.calls),1)
        self.assertTrue(self.closed)

    async def test_rejected_reload_restores_prior_private_config(self):
        self.fail_reload=True
        with self.assertRaisesRegex(module.RefreshError,'MCP_RELOAD_FAILED'):
            await module.refresh_codex('existing',{},sync=lambda:'a'*64)
        self.assertEqual(self.config.read_text(),self.original)
        self.assertTrue(self.closed)

    async def test_equivalent_home_alias_is_accepted_but_another_directory_is_not(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.home, target_is_directory=True)
        self.state.codex_home = str(alias)
        result = await module.refresh_codex('existing',{},sync=lambda:'a'*64)
        self.assertEqual(result['refresh']['nativeSessionId'],'native-original')
        self.calls.clear()
        self.state.codex_home = str(self.source)
        with self.assertRaisesRegex(module.RefreshError,'MCP_UNSAFE_CONFIG'):
            await module.refresh_codex('existing',{},sync=lambda:self.fail('sync'))
        self.assertEqual(self.calls,[])

    async def test_foreign_bridge_and_symlink_fail_without_reload(self):
        self.state.session_id='different'
        with self.assertRaisesRegex(module.RefreshError,'MCP_SESSION_NOT_LOCAL'):
            await module.refresh_codex('existing',{},sync=lambda:'a'*64)
        self.assertEqual(self.calls,[])
        self.state.session_id='existing'
        self.config.unlink();self.config.symlink_to(self.source/'config.toml')
        with self.assertRaisesRegex(module.RefreshError,'MCP_UNSAFE_CONFIG'):
            await module.refresh_codex('existing',{},sync=lambda:'a'*64)
        self.assertEqual(len(self.calls),1)


if __name__ == '__main__':
    unittest.main()
