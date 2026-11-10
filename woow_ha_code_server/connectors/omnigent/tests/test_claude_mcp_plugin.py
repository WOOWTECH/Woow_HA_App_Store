import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys
import threading
import ast
import importlib.metadata
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("claude_mcp_plugin", Path(__file__).parents[1] / "claude_mcp_plugin.py")
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
NATIVE_ID = "12345678-1234-1234-1234-123456789abc"


class NativeContract(unittest.TestCase):
    def test_pinned_settings_argument_binds_process_without_bridge_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge = Path(folder)
            settings = bridge / 'claude-settings.json'
            hooks = {event: [{'hooks': [{'command': 'hook --bridge-dir ' + str(bridge)}]}]
                     for event in ('SessionStart', 'Stop')}
            settings.write_text(json.dumps({'hooks': hooks}))
            settings.chmod(0o600)
            plugin._assert_process_bridge(bridge, ['claude', '--settings', str(settings)], {})
            for args in ([], ['--settings', str(settings) + '.other']):
                with self.assertRaises((plugin.ClaudeRefreshError, FileNotFoundError)):
                    plugin._assert_process_bridge(bridge, args, {})
            settings.write_text(json.dumps({'hooks': {}}))
            with self.assertRaisesRegex(plugin.ClaudeRefreshError, 'SESSION_NOT_LOCAL'):
                plugin._assert_process_bridge(bridge, ['--settings', str(settings)], {})

    def test_every_native_dependency_is_in_explicit_contract(self):
        tree = ast.parse(Path(plugin.__file__).read_text())
        used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name) and n.value.id == 'native'}
        self.assertEqual(used, plugin.NATIVE_APIS)
        self.assertNotIn('claude_global_config_path', used)

    def test_path_uses_native_environment_including_legacy_and_relative_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = {'HOME': str(root / 'home'), 'CLAUDE_CONFIG_DIR': 'private'}
            self.assertEqual(plugin.claude_config_path(root, env), root / 'private/.claude.json')
            (root / 'private').mkdir()
            (root / 'private/.config.json').write_text('{}')
            self.assertEqual(plugin.claude_config_path(root, env), root / 'private/.config.json')
            (root / 'private/.config.json').unlink()
            env['CLAUDE_CODE_CUSTOM_OAUTH_URL'] = 'present-not-read'
            self.assertEqual(plugin.claude_config_path(root, env), root / 'private/.claude-custom-oauth.json')
            self.assertEqual(plugin.claude_config_path(root, {'HOME': str(root / 'home')}), root / 'home/.claude.json')

    def test_actual_installed_pinned_bridge_contract(self):
        try:
            version = importlib.metadata.version('omnigent')
        except importlib.metadata.PackageNotFoundError:
            self.skipTest('run this contract case with installed Omnigent 0.16.0')
        self.assertEqual(version, '0.16.0')
        from omnigent.harnesses.claude_native import bridge
        plugin.assert_native_contract(bridge)
        # Signature-bind the calls made by the adapter, not a fake API object.
        import inspect
        args = {'bridge_dir_for_bridge_id': (('id',), {}),
                'read_claude_session_id': ((Path('/unused'),), {}),
                'read_transcript_path': ((Path('/unused'),), {}),
                '_bridge_injection_lock': ((Path('/unused'),), {}),
                '_bridge_injection_file_lock': ((Path('/unused'),), {}),
                '_serialize_bridge_injection': ((lambda: None,), {}),
                '_wait_for_tmux_info': ((Path('/unused'),), {'timeout_s': 1}),
                'has_pending_user_prompt': ((Path('/unused'),), {}),
                '_capture_pane': (('socket', 'target'), {}),
                '_occupying_surface': (('text',), {}), '_is_box_rule': (('line',), {}),
                '_run_tmux': (('socket', 'send-keys', '-t', 'target', 'Enter'), {})}
        self.assertEqual(set(args), plugin.NATIVE_APIS - {'BRIDGE_ID_LABEL_KEY', '_CLAUDE_PROMPT_GLYPH'})
        for name, (positional, keyword) in args.items():
            inspect.signature(getattr(bridge, name)).bind(*positional, **keyword)


class DirectProjection(unittest.TestCase):
    def plan(self, existing, projected=None, ledger=None, **kwargs):
        return plugin.merge_direct_config(existing, workspace='/work',
            projected=projected or {}, managed_names=['a', 'b'], ledger=ledger or {}, **kwargs)

    def test_removal_keeps_name_as_disabled_local_tombstone_and_cannot_reimport(self):
        original = {'mcpServers': {'a': {'command': 'old'}, 'private': {'command': 'mine'}},
                    'oauthAccount': {'opaque': 'private'}, 'model': 'opus', 'projects': {
                        '/work': {'allowedTools': ['Read'], 'disabledMcpServers': ['private']},
                        '/elsewhere': {'mcpServers': {'a': {'command': 'elsewhere'}}}}}
        result, ledger = self.plan(original, {'b': {'command': 'new'}})
        self.assertEqual(result['mcpServers'], {'b': {'command': 'new'}, 'private': {'command': 'mine'}})
        self.assertEqual(result['projects']['/work']['mcpServers']['a'], plugin.tombstone('a'))
        self.assertEqual(result['projects']['/work']['disabledMcpServers'], ['private', 'a'])
        self.assertEqual(ledger['disabledOwned'], ['a'])
        for key in ('oauthAccount', 'model'):
            self.assertEqual(result[key], original[key])
        self.assertEqual(result['projects']['/elsewhere'], original['projects']['/elsewhere'])
        self.assertEqual(original['mcpServers']['a']['command'], 'old')

    def test_readding_removes_only_our_disabled_preference(self):
        original = {'projects': {'/work': {'disabledMcpServers': ['a', 'private']}}}
        retired, ledger = self.plan(original)
        self.assertEqual(ledger['disabledOwned'], ['b'])
        active = {'a': {'command': 'v2'}, 'b': {'command': 'v2'}}
        restored, ledger = self.plan(retired, active, ledger)
        self.assertEqual(restored['projects']['/work']['disabledMcpServers'], ['a', 'private'])
        self.assertEqual(restored['projects']['/work']['mcpServers'], {})
        self.assertEqual(ledger['retired'], [])
        self.assertEqual(ledger['disabledOwned'], [])

    def test_repeated_plan_is_idempotent(self):
        first, ledger = self.plan({})
        second, next_ledger = self.plan(first, ledger=ledger)
        self.assertEqual((first, ledger), (second, next_ledger))

    def test_owned_tombstone_manual_edit_is_refused(self):
        first, ledger = self.plan({})
        first['projects']['/work']['mcpServers']['a'] = {'command': 'user-edited'}
        with self.assertRaisesRegex(plugin.ClaudeRefreshError, 'OWNERSHIP_CHANGED'):
            self.plan(first, ledger=ledger)

    def test_unowned_local_and_project_overrides_are_not_deleted(self):
        for source, kwargs in [({'projects': {'/work': {'mcpServers': {'a': {'command': 'mine'}}}}}, {}),
                               ({}, {'project_servers': {'a': {'command': 'mine'}}})]:
            with self.assertRaisesRegex(plugin.ClaudeRefreshError, 'DIRECT_SCOPE_CONFLICT'):
                self.plan(source, **kwargs)

    def test_exact_active_project_definition_is_preserved(self):
        active = {'a': {'command': 'same'}}
        result, _ = self.plan({'projects': {'/work': {'mcpServers': active}}}, active,
                              project_servers=active)
        self.assertEqual(result['projects']['/work']['mcpServers']['a'], active['a'])

    def test_relay_and_invalid_names_fail_without_secret_text(self):
        for names in (['omnigent'], ['private secret'], [3]):
            with self.assertRaises(plugin.ClaudeRefreshError) as caught:
                plugin.merge_direct_config({}, workspace='/work', projected={}, managed_names=names, ledger={})
            self.assertNotIn('private secret', str(caught.exception))


class OwnershipAndReceipts(unittest.TestCase):
    def test_real_config_files_preserve_auth_and_keep_tombstones_out_of_import_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data, config_dir, workspace = root / 'data', root / 'claude', root / 'workspace'
            (data / 'shared').mkdir(parents=True)
            config_dir.mkdir()
            workspace.mkdir()
            config = config_dir / '.claude.json'
            managed = data / 'shared/managed.json'
            managed.write_text(json.dumps({'managedServers': ['a', 'b']}))
            config.write_text(json.dumps({'mcpServers': {'b': {'command': 'new'}}, 'oauthAccount': {'opaque': 'retained'}}))
            for path in (config, managed): path.chmod(0o600)
            context = {'workspace': str(workspace), 'config': config}
            with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(config_dir)}):
                counts = plugin._prepare_direct(context, data)
                self.assertEqual(counts, {'retiredCount': 1, 'configuredCount': 1})
                saved = json.loads(config.read_text())
                self.assertEqual(saved['oauthAccount'], {'opaque': 'retained'})
                self.assertEqual(set(saved['mcpServers']), {'b'})
                self.assertEqual(saved['projects'][str(workspace)]['mcpServers']['a'], plugin.tombstone('a'))
                self.assertEqual(plugin._prepare_direct(context, data), counts)
            self.assertFalse((data / 'shared/.sync-lock').exists())
            self.assertFalse(Path(str(config) + '.lock').exists())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_native_directory_lock_never_steals_existing_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / 'config.lock'
            lock.mkdir()
            with self.assertRaisesRegex(plugin.ClaudeRefreshError, 'CONFIG_BUSY'):
                with plugin._directory_lock(lock):
                    self.fail('entered existing lock')
            self.assertTrue(lock.is_dir())
            lock.rmdir()
            with plugin._directory_lock(lock):
                self.assertTrue(lock.is_dir())
            self.assertFalse(lock.exists())

    def test_prefix_rewrite_or_pid_replacement_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            transcript = Path(folder) / 'native.jsonl'
            transcript.write_bytes(b'original\n')
            transcript.chmod(0o600)
            context = {'identity': {'pid': 123, 'startTicks': '1'}, 'transcript': transcript,
                       'size': 9, 'sha256': hashlib.sha256(b'original\n').hexdigest(), 'inode': transcript.stat().st_ino}
            native = SimpleNamespace(read_claude_session_id=lambda _: NATIVE_ID)
            with patch.object(plugin, '_process_identity', return_value=context['identity']):
                plugin._assert_same(native, Path(folder), NATIVE_ID, context)
                transcript.write_bytes(b'rewritten\n')
                with self.assertRaisesRegex(plugin.ClaudeRefreshError, 'HISTORY_CHANGED'):
                    plugin._assert_same(native, Path(folder), NATIVE_ID, context)
            with patch.object(plugin, '_process_identity', return_value={'pid': 123, 'startTicks': '2'}):
                with self.assertRaisesRegex(plugin.ClaudeRefreshError, 'NATIVE_ID_CHANGED'):
                    plugin._assert_same(native, Path(folder), NATIVE_ID, context)

    def test_partial_native_last_line_waits_for_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'transcript'
            p.write_bytes(b'prefix\n{"type":"system"}\n{"part')
            self.assertEqual(plugin._new_records({'transcript': p}, 7), [{'type': 'system'}])

    def test_public_async_boundary_hides_private_exception_text(self):
        import asyncio
        with patch.object(plugin, '_refresh_claude', side_effect=RuntimeError('Authorization: private')):
            with self.assertRaisesRegex(plugin.ClaudeRefreshError, '^MCP_REFRESH_FAILED$'):
                asyncio.run(plugin.refresh_claude('conversation1', {}, sync=lambda: None))


class PersistentSubmission(unittest.TestCase):
    def test_native_config_poll_allows_unrelated_writes_but_rejects_mcp_race(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.claude.json'
            path.write_text(json.dumps({'mcpServers': {'owned': {'command': 'v1'}}}))
            context = {'config': path, 'workspace': '/workspace'}
            def write_unrelated(seconds):
                self.assertEqual(seconds, 2.0)
                value = json.loads(path.read_text()); value['preference'] = 'preserved'
                path.write_text(json.dumps(value))
            with patch.object(plugin.time, 'sleep', side_effect=write_unrelated):
                plugin._await_native_config_poll(context)
            def race(seconds):
                path.write_text(json.dumps({'mcpServers': {'owned': {'command': 'v2'}}}))
            with patch.object(plugin.time, 'sleep', side_effect=race):
                with self.assertRaisesRegex(plugin.ClaudeRefreshError, 'MCP_CONFIG_CHANGED'):
                    plugin._await_native_config_poll(context)

    def test_repeat_request_reads_receipt_without_sync_or_second_enter(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            bridge = Path(folder)
            for name in ('state.json', 'tmux.json'):
                (bridge / name).write_text('{}')
                (bridge / name).chmod(0o600)
            transcript = bridge / 'transcript.jsonl'
            transcript.write_bytes(b'original\n')
            transcript.chmod(0o600)
            context = {'identity': {'pid': 123, 'startTicks': '1'}, 'transcript': transcript,
                       'size': 9, 'sha256': hashlib.sha256(b'original\n').hexdigest(), 'inode': transcript.stat().st_ino}
            native = SimpleNamespace(BRIDGE_ID_LABEL_KEY='native-bridge', bridge_dir_for_bridge_id=lambda _: bridge,
                read_claude_session_id=lambda _: NATIVE_ID, _serialize_bridge_injection=lambda fn: fn,
                _bridge_injection_lock=lambda _: threading.Lock(),
                _bridge_injection_file_lock=lambda _: SimpleNamespace(acquire=lambda **kw: None, release=lambda: None),
                has_pending_user_prompt=lambda _: False, _wait_for_tmux_info=lambda *a, **kw: {'socket_path': 's', 'tmux_target': 't'},
                _capture_pane=lambda *a: '', _occupying_surface=lambda _: None)
            module = SimpleNamespace(bridge=native)
            sync = Mock(return_value='a' * 64)
            with patch.dict(sys.modules, {'omnigent.harnesses.claude_native': module}), \
                 patch.object(plugin, 'assert_native_contract'), \
                 patch.object(plugin, '_native_process', side_effect=lambda *a: dict(context)), \
                 patch.object(plugin, '_process_identity', return_value=context['identity']), \
                 patch.object(plugin, '_composer_text', return_value=''), \
                 patch.object(plugin, '_prepare_direct', return_value={'retiredCount': 1, 'configuredCount': 2}) as prepare, \
                 patch.object(plugin, '_await_native_config_poll') as settle, \
                 patch.object(plugin, 'submit_native_reload', return_value={'state': 'submitted'}) as submit, \
                 patch.object(plugin, '_poll_receipt', side_effect=[{'state': 'receipt-pending'}, {'state': 'reloaded'}]):
                info = {'external_session_id': NATIVE_ID}
                first = plugin._refresh_claude('conversation1', info, sync=sync)
                self.assertEqual(first['refresh']['state'], 'queued')
                self.assertFalse(first['refresh']['toolsVerified'])
                self.assertTrue((bridge / 'woow-claude-mcp-pending.json').exists())
                second = plugin._refresh_claude('conversation1', info, sync=sync)
                self.assertEqual(second['refresh']['state'], 'reloaded')
                self.assertFalse(second['refresh']['inventoryVerified'])
                self.assertFalse(second['refresh']['toolsVerified'])
                self.assertFalse((bridge / 'woow-claude-mcp-pending.json').exists())
                self.assertEqual(sync.call_count, 1)
                self.assertEqual(prepare.call_count, 1)
                self.assertEqual(settle.call_count, 1)
                self.assertEqual(submit.call_count, 1)

    def test_existing_input_lock_is_refused_without_waiting_or_sending(self):
        lock = threading.Lock()
        lock.acquire()
        native = SimpleNamespace(_bridge_injection_lock=lambda _: lock)
        with self.assertRaisesRegex(plugin.ClaudeRefreshError, 'SUBMISSION_BUSY'):
            with plugin._injection_lock(native, Path('/unused')):
                self.fail('entered occupied injection lock')
        self.assertTrue(lock.locked())
        lock.release()


class NativeSubmission(unittest.TestCase):
    def test_dim_native_placeholder_is_empty_but_typed_or_ambiguous_input_is_not(self):
        native = SimpleNamespace(_capture_pane=lambda *a: '─────────\n❯ suggestion\n─────────\n',
            _occupying_surface=lambda _: None, _is_box_rule=lambda line: line == '─────────',
            _CLAUDE_PROMPT_GLYPH='❯')
        for raw, expected in [
            ('❯ \x1b[2msuggestion\x1b[0m', ''),
            ('❯ suggestion', 'suggestion'),
            ('❯ sug\x1b[2mgestion\x1b[0m', 'suggestion'),
            ('❯ \x1b[2mdifferent\x1b[0m', None),
        ]:
            with patch.object(plugin.subprocess, 'run', return_value=SimpleNamespace(returncode=0,
                    stdout='─────────\n' + raw + '\n─────────\n')):
                self.assertEqual(plugin._input_text(native, 'socket', 'target'), expected)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = Path(self.temp.name)
        self.commands = []
        self.draft = ""
        self.approval = False
        self.ident = NATIVE_ID
        self.accept = True
        self.eligibility = {"state": "eligible", "nativeSessionId": NATIVE_ID}
        def run(socket, *args):
            self.commands.append(args)
            if args[0] == "paste-buffer": self.draft = plugin.RELOAD_COMMAND
            if args[0] == "send-keys" and self.accept: self.draft = ""
        self.native = SimpleNamespace(
            read_claude_session_id=lambda _: self.ident,
            _serialize_bridge_injection=lambda fn: fn,
            _wait_for_tmux_info=lambda *a, **kw: {"socket_path": "socket", "tmux_target": "target"},
            has_pending_user_prompt=lambda _: self.approval,
            _capture_pane=lambda *a: "─────────\n❯ " + self.draft + "\n─────────\n",
            _occupying_surface=lambda pane: None,
            _is_box_rule=lambda line: line == "─────────",
            _CLAUDE_PROMPT_GLYPH="❯", _run_tmux=run)

    def submit(self):
        with patch.object(plugin.time, "sleep", lambda _: None):
            return plugin.submit_native_reload(self.bridge, native_session_id=NATIVE_ID,
                eligibility=self.eligibility, claude_version="2.1.285", native=self.native, timeout=0.01)

    def test_only_one_enter_and_never_escape_clear_restart_or_model_text(self):
        result = self.submit()
        self.assertEqual(result["state"], "submitted")
        self.assertFalse(result["reloadVerified"])
        keys = [args for args in self.commands if args[0] == "send-keys"]
        self.assertEqual(keys, [("send-keys", "-t", "target", "Enter")])
        self.assertEqual(list(self.bridge.iterdir()), [])

    def test_busy_native_composer_can_accept_queue_without_interrupt(self):
        # Busy handling is native. This adapter only submits; it never claims
        # a native queue receipt based on an empty composer observation.
        self.native._capture_pane = lambda *a: "Working…\n─────────\n❯ " + self.draft + "\n─────────\nesc to interrupt"
        self.assertEqual(self.submit()["state"], "submitted")
        self.assertFalse(any("Escape" in args for args in self.commands))

    def test_occupied_multiline_composer_is_not_erased(self):
        self.draft = "\nprivate existing input"
        with self.assertRaisesRegex(plugin.PluginError, "COMPOSER_OCCUPIED"):
            self.submit()
        self.assertEqual(self.commands, [])

    def test_pending_approval_or_identity_change_never_types(self):
        for approval, ident in [(True, NATIVE_ID), (False, "different")]:
            self.approval, self.ident = approval, ident
            with self.assertRaises(plugin.PluginError): self.submit()
            self.assertEqual(self.commands, [])

    def test_unconfirmed_enter_is_not_retried(self):
        self.accept = False
        result = self.submit()
        self.assertEqual(result["state"], "submission-unknown")
        self.assertFalse(result["retrySafe"])
        self.assertEqual(len([x for x in self.commands if x[0] == "send-keys"]), 1)

    def test_native_error_text_is_never_exposed(self):
        def fail(*a): raise RuntimeError("Authorization: Bearer private-fixture")
        self.native._run_tmux = fail
        with self.assertRaisesRegex(plugin.PluginError, "^MCP_CLAUDE_NATIVE_SUBMIT_FAILED$"):
            self.submit()


class Receipts(unittest.TestCase):
    def record(self, text, **kwargs):
        return {"sessionId": NATIVE_ID, "type": "system", "subtype": "local_command", "content": text, **kwargs}

    def test_assistant_claim_and_other_session_do_not_prove_reload(self):
        for overrides in ({"type": "assistant"}, {"sessionId": "different"}):
            records = [self.record("<command-name>/reload-plugins</command-name><command-args>--force</command-args>"),
                self.record("<local-command-stdout>Reloaded: 1 plugin MCP server</local-command-stdout>", **overrides)]
            self.assertEqual(plugin.native_reload_receipt(records, native_session_id=NATIVE_ID)["state"], "receipt-pending")

    def test_native_summary_still_requires_independent_tool_call(self):
        records = [self.record("<command-name>/reload-plugins</command-name><command-args>--force</command-args>"),
            self.record("<local-command-stdout>Reloaded: 1 plugin · 2 plugin MCP servers</local-command-stdout>")]
        result = plugin.native_reload_receipt(records, native_session_id=NATIVE_ID)
        self.assertEqual(result["state"], "reloaded")
        self.assertTrue(result["reloadVerified"])
        self.assertFalse(result["toolsVerified"])
        records[-1]["content"] += " 1 error during load"
        self.assertEqual(plugin.native_reload_receipt(records, native_session_id=NATIVE_ID)["state"], "reload-failed")

    def test_installed_2_1_285_user_command_and_system_result_schema(self):
        command = {"sessionId": NATIVE_ID, "type": "user", "message": {"role": "user", "content":
            "<command-name>/reload-plugins</command-name><command-args>--force</command-args>"}}
        output = self.record("<local-command-stdout>Reloaded: 0 plugins · 0 plugin MCP servers</local-command-stdout>")
        result = plugin.native_reload_receipt([command, output], native_session_id=NATIVE_ID)
        self.assertTrue(result["reloadVerified"])
        self.assertFalse(result["toolsVerified"])
        fake = {"sessionId": NATIVE_ID, "type": "user", "message": {"content": output["content"]}}
        self.assertEqual(plugin.native_reload_receipt([command, fake], native_session_id=NATIVE_ID)["state"], "receipt-pending")

    def test_other_native_command_breaks_reload_pairing(self):
        records = [self.record("<command-name>/reload-plugins</command-name><command-args>--force</command-args>"),
                   self.record("<command-name>/mcp</command-name><command-args>reconnect all</command-args>"),
                   self.record("<local-command-stdout>Reloaded: 1 plugin MCP server</local-command-stdout>")]
        self.assertEqual(plugin.native_reload_receipt(records, native_session_id=NATIVE_ID)["state"], "receipt-pending")


if __name__ == "__main__":
    unittest.main()
