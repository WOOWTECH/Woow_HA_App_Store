import asyncio
import fcntl
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import stat
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'pi_strict_resume.py'
spec = importlib.util.spec_from_file_location('pi_strict_resume_test', SOURCE)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class StrictPiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bridge = self.root / 'bridge'
        self.bridge.mkdir(mode=0o700)
        for name in ('inbox', 'sessions'):
            (self.bridge / name).mkdir(mode=0o700)
        self.sid = 'original'
        self.native = '01234567-89ab-4cde-8f01-23456789abcd'
        self.info = dict(id=self.sid, external_session_id=self.native, status='idle', harness='pi-native', workspace=str(self.root))
        self.data = ('\n'.join(json.dumps(x) for x in [
            dict(type='session', version=3, id=self.native, cwd=str(self.root)),
            dict(type='message', id='one', parentId=None, message={'role': 'user', 'content': 'native-only-history'}),
        ]) + '\n').encode()
        self.history = self.bridge / 'sessions' / ('original_' + self.native + '.jsonl')
        self.history.write_bytes(self.data); self.history.chmod(0o600)
        for name, data in [('config.json', json.dumps({'sessionId': self.sid})),
                           ('omnigent_pi_native_extension.js', 'woow_pi_mcp_refresh.cjs'), ('woow_pi_mcp_refresh.cjs', 'fixture')]:
            (self.bridge / name).write_text(data); (self.bridge / name).chmod(0o600)
        package = self.root / 'package'
        (package / 'dist/bundle').mkdir(parents=True)
        (package / 'package.json').write_text('{"version":"0.99.1"}')
        self.pi = package / 'dist/bundle/cli.js'; self.pi.touch()
        self.patches = [patch.object(helper, '_bridge', return_value=self.bridge),
                        patch.object(helper, '_check_no_native'), patch.object(Path, 'home', return_value=self.root),
                        patch.object(helper.shutil, 'which', side_effect=lambda name: str(self.pi if name == 'pi' else self.root / 'node')),
                        patch.dict(os.environ, {'PI_CODING_AGENT_DIR': str(self.root), 'PI_AGENT_DATA_DIR': str(self.root)})]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)

    def prepare(self, info=None):
        return helper.prepare_pi_cold_resume(self.sid, info or self.info)

    def test_derived_path_original_snapshot_no_history_or_config_write(self):
        config = (self.bridge / 'config.json').read_bytes()
        info = {**self.info, 'nativeFile': '/attacker/chosen', 'command': 'bad', 'args': ['--no-session']}
        result = self.prepare(info)
        ticket = result['ticket']
        self.assertEqual(ticket['nativeFile'], str(self.history))
        self.assertEqual(result['receipt']['nativeSHA256'], hashlib.sha256(self.data).hexdigest())
        self.assertEqual(self.history.read_bytes(), self.data)
        self.assertEqual((self.bridge / 'config.json').read_bytes(), config)
        self.assertNotIn('ensure_native_terminal', result['body'])
        snapshots = list((self.root / 'connectors/pi-resume-snapshots').rglob('*.jsonl'))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].read_bytes(), self.data)
        self.assertEqual(snapshots[0].stat().st_mode & 0o777, 0o600)

    def test_busy_active_pending_wrong_harness_workspace_and_custom_args_refuse(self):
        for values in [dict(status='running'), dict(active_response_id='active'), dict(pending_inputs=[{}]),
                       dict(pending_elicitations=[{}]), dict(terminal_pending=True), dict(harness='claude-native'),
                       dict(workspace='/different'), dict(terminal_launch_args=['--session','different'])]:
            with self.subTest(values=list(values)), self.assertRaises(helper.PiResumeError):
                self.prepare({**self.info, **values})
        self.assertEqual(list(self.bridge.glob('woow-pi-cold-ticket-*.json')), [])

    def test_inbox_and_native_process_and_concurrent_preparation_refuse(self):
        (self.bridge / 'inbox/one.json').write_text('{}')
        with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'): self.prepare()
        (self.bridge / 'inbox/one.json').unlink()
        with patch.object(helper, '_check_no_native', side_effect=helper.PiResumeError('SESSION_BUSY')):
            with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'): self.prepare()
        lock = self.bridge / 'woow-pi-cold.lock'; lock.touch(mode=0o600)
        with open(lock, 'rb') as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'): self.prepare()
        self.assertEqual(self.history.read_bytes(), self.data)

    def test_explicit_request_binds_exact_prior_history(self):
        expected = {'sessionId': self.sid, 'nativeSessionId': self.native, 'workspace': str(self.root),
                    'originalBytes': len(self.data), 'originalSHA256': hashlib.sha256(self.data).hexdigest()}
        helper.prepare_pi_cold_resume(self.sid, self.info, expected=expected)
        for change in [dict(nativeSessionId='wrong'), dict(originalBytes=1), dict(originalSHA256='0'*64), dict(workspace='/wrong')]:
            with self.assertRaises(helper.PiResumeError):
                helper.prepare_pi_cold_resume(self.sid, self.info, expected={**expected, **change})
        self.assertEqual(self.history.read_bytes(), self.data)

    def test_two_initializer_processes_refuse_loser_before_ticket_or_owner_change(self):
        context = multiprocessing.get_context('fork')
        receiver, sender = context.Pipe(duplex=False)

        def second_initializer():
            try:
                with helper.reserve_attachment(self.bridge):
                    self.prepare()
                    helper._write(self.bridge / 'owner.pid', b'loser')
                sender.send('UNEXPECTED_SUCCESS')
            except helper.PiResumeError as error:
                sender.send(error.code)
            finally:
                sender.close()

        async def first_initializer():
            with helper.reserve_attachment(self.bridge):
                prepared = self.prepare()
                helper._write(self.bridge / 'owner.pid', str(os.getpid()).encode())
                ticket_path = Path(prepared['body']['spec']['args'][1])
                ticket = ticket_path.read_bytes()
                # First initializer has prepared but is awaiting child startup.
                child = context.Process(target=second_initializer)
                child.start()
                await asyncio.to_thread(child.join, 5)
                if child.is_alive(): child.kill(); child.join(); self.fail('initializer did not finish')
                self.assertTrue(receiver.poll(1))
                self.assertEqual(receiver.recv(), 'SESSION_BUSY')
                self.assertEqual(ticket_path.read_bytes(), ticket)
                self.assertEqual((self.bridge / 'owner.pid').read_text(), str(os.getpid()))
                self.assertEqual(len(list(self.bridge.glob('woow-pi-cold-ticket-*.json'))), 1)
                # Reservation still held through the confirmation phase.
                with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'):
                    with helper.reserve_attachment(self.bridge): pass
            return prepared

        first = asyncio.run(first_initializer())
        second = self.prepare()
        self.assertNotEqual(first['ticket']['requestId'], second['ticket']['requestId'])
        self.assertNotEqual(first['body']['spec']['args'][1], second['body']['spec']['args'][1])
        self.assertEqual(json.loads(Path(first['body']['spec']['args'][1]).read_text()), first['ticket'])
        receiver.close(); sender.close()

    def test_missing_empty_invalid_wrong_id_old_version_and_symlink_refuse(self):
        for data in [b'', b'not-json\n', self.data.replace(b'"version": 3', b'"version": 2'), self.data.replace(self.native.encode(), b'wrong')]:
            self.history.write_bytes(data)
            with self.assertRaises(helper.PiResumeError): self.prepare()
            self.assertEqual(self.history.read_bytes(), data)
        self.history.unlink()
        with self.assertRaises(helper.PiResumeError): self.prepare()
        other = self.root / 'other'; other.write_bytes(self.data); self.history.symlink_to(other)
        with self.assertRaisesRegex(helper.PiResumeError, 'UNSAFE_PATH'): self.prepare()
        self.assertEqual(other.read_bytes(), self.data)

    def recovery_fixture(self):
        rows = [json.loads(line) for line in self.data.splitlines()]
        rows[0]['timestamp'] = '2026-11-10T08:20:42.116Z'
        data = ('\n'.join(json.dumps(row) for row in rows) + '\n').encode()
        digest = hashlib.sha256(data).hexdigest()
        backup = self.root / 'connectors/native-history-backup-20261110' / self.sid / (self.native + '-' + digest + '.jsonl')
        backup.parent.mkdir(parents=True, mode=0o700)
        backup.write_bytes(data); backup.chmod(0o600)
        request = dict(restoreSnapshot=True, sessionId=self.sid, nativeSessionId=self.native,
                       workspace=str(self.root), originalBytes=len(data), originalSHA256=digest,
                       expectedAgentDir=str(self.root))
        shutil.rmtree(self.bridge)
        return backup, data, request

    def test_recovery_derives_exact_paths_and_refuses_bad_snapshot_and_identity(self):
        backup, data, request = self.recovery_fixture()
        plan = helper.inspect_pi_recovery(self.sid, self.info, {**request, 'nativeFile': '/ignored', 'backupFile': '/ignored'})
        self.assertEqual(plan['backup'], backup)
        self.assertEqual(plan['history'].name, '2026-11-10T08-20-42-116Z_' + self.native + '.jsonl')
        self.assertEqual(plan['data'], data)
        self.assertFalse(self.bridge.exists())
        for change in [dict(restoreSnapshot=False), dict(nativeSessionId='wrong'), dict(workspace='/wrong'),
                       dict(expectedAgentDir='/wrong'), dict(originalBytes=1), dict(originalSHA256='wrong')]:
            with self.subTest(change=list(change)), self.assertRaises(helper.PiResumeError):
                helper.inspect_pi_recovery(self.sid, self.info, {**request, **change})
        backup.write_bytes(data + b'{}\n')
        with self.assertRaisesRegex(helper.PiResumeError, 'HISTORY_CHANGED'):
            helper.inspect_pi_recovery(self.sid, self.info, request)
        backup.unlink(); target = self.root / 'private-history'; target.write_bytes(data); backup.symlink_to(target)
        with self.assertRaisesRegex(helper.PiResumeError, 'UNSAFE_PATH'):
            helper.inspect_pi_recovery(self.sid, self.info, request)
        self.assertFalse(self.bridge.exists())

    def test_recovery_never_overwrites_or_drops_inbox(self):
        _, data, request = self.recovery_fixture()
        plan = helper.inspect_pi_recovery(self.sid, self.info, request)
        self.bridge.mkdir(mode=0o700)
        helper._restore_pi_history(plan)
        helper._restore_pi_history(plan)  # Byte-identical retry is idempotent.
        self.assertEqual(plan['history'].read_bytes(), data)
        plan['history'].write_bytes(data + b'{}\n')
        with self.assertRaisesRegex(helper.PiResumeError, 'HISTORY_CHANGED'):
            helper._restore_pi_history(plan)
        self.assertEqual(plan['history'].read_bytes(), data + b'{}\n')
        plan['history'].write_bytes(data)
        (self.bridge / 'inbox/pending.json').write_bytes(b'{"content":"must-survive"}')
        with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'):
            helper._restore_pi_history(plan)
        self.assertEqual((self.bridge / 'inbox/pending.json').read_bytes(), b'{"content":"must-survive"}')

    def test_actual_sdk_recovery_lock_current_controls_live_owner_and_failed_preparation(self):
        vendor = os.environ.get('OMNIGENT_TEST_SITE_PACKAGES')
        if not vendor: self.skipTest('OMNIGENT_TEST_SITE_PACKAGES required')
        sys.path.insert(0, vendor); self.addCleanup(lambda: sys.path.remove(vendor))
        from omnigent.harnesses.pi_native import bridge as sdk_bridge
        from omnigent.native import native_bridge_common as common
        backup, data, request = self.recovery_fixture()
        ctx = SimpleNamespace(session_id=self.sid)
        controls = dict(session_id=self.sid, server_url='https://example.invalid', conversation_url='https://example.invalid/session',
                        auth_headers={'X-Omnigent-Runner-Tunnel-Token': 'current-fixture-binding'}, tools=[])
        kwargs = dict(authorized_info=self.info, expected=request, busy=lambda: False, epoch=lambda: 0)
        with patch.object(helper, '_recovery_controls', AsyncMock(side_effect=helper.PiResumeError('PI_RESUME_ENV_UNAVAILABLE'))):
            with self.assertRaisesRegex(helper.PiResumeError, 'ENV_UNAVAILABLE'):
                asyncio.run(helper.launch_pi_strict(ctx, **kwargs))
        self.assertFalse(self.bridge.exists())
        writer = sdk_bridge.write_extension_files
        generations = iter([0, 1])
        with patch.object(helper, '_recovery_controls', AsyncMock(return_value=controls)):
            with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'):
                asyncio.run(helper.launch_pi_strict(ctx, **{**kwargs, 'epoch': lambda: next(generations)}))
        self.assertFalse(self.bridge.exists())
        def checked_writer(bridge, **values):
            with common._try_bridge_dir_cleanup_lock(bridge) as acquired:
                self.assertFalse(acquired)
            self.assertEqual(helper.inspect_pi_recovery(self.sid, self.info, request)['data'], data)
            return writer(bridge, **values)  # Actual pinned SDK writer, no mock configuration format.
        async def confirmed(*args, **kw):
            with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'):
                with helper.reserve_attachment(self.bridge): pass
            self.assertEqual((self.bridge / 'owner.pid').read_text(), str(os.getpid()))
            self.assertEqual(common.prune_orphaned_dirs(self.bridge.parent), 0)
            plan = helper.inspect_pi_recovery(self.sid, self.info, request)
            self.assertEqual(plan['history'].read_bytes(), data)
            config = json.loads((self.bridge / 'config.json').read_text())
            self.assertEqual(config['authHeaders'], controls['auth_headers'])
            self.assertEqual(config['sessionId'], self.sid)
            return 'original-view', {'nativeSessionId': self.native}
        with patch.object(helper, '_recovery_controls', AsyncMock(return_value=controls)), \
             patch.object(sdk_bridge, 'write_extension_files', checked_writer), \
             patch.object(helper, '_launch_pi_strict_reserved', confirmed):
            result, receipt = asyncio.run(helper.launch_pi_strict(ctx, **kwargs))
        self.assertEqual(result, 'original-view')
        self.assertEqual(receipt['nativeSessionId'], self.native)
        self.assertEqual(backup.read_bytes(), data)

    def test_recovery_controls_use_current_sdk_auth_and_binding_without_provider_setup(self):
        vendor = os.environ.get('OMNIGENT_TEST_SITE_PACKAGES')
        if not vendor: self.skipTest('OMNIGENT_TEST_SITE_PACKAGES required')
        sys.path.insert(0, vendor); self.addCleanup(lambda: sys.path.remove(vendor))
        from omnigent.runner import _entry, tool_dispatch
        from omnigent import cli_auth
        from omnigent.runner.identity import RUNNER_TUNNEL_TOKEN_HEADER
        ctx = SimpleNamespace(session_id=self.sid, server_client=SimpleNamespace(base_url='https://example.invalid/'),
                              agent_spec=object())
        with patch.object(_entry, '_make_auth_token_factory', return_value=lambda: 'current-fixture-bearer'), \
             patch.object(_entry, '_runner_tunnel_binding_token_from_env', return_value='current-fixture-binding'), \
             patch.object(cli_auth, 'databricks_request_headers', return_value={'Authorization': 'fixture'}) as headers, \
             patch.object(tool_dispatch, 'build_native_relay_tool_schemas', return_value=[{'name': 'current_tool'}]) as schemas:
            result = asyncio.run(helper._recovery_controls(ctx))
        headers.assert_called_once_with('https://example.invalid', bearer_token='current-fixture-bearer')
        schemas.assert_called_once_with(ctx.agent_spec)
        self.assertEqual(result['auth_headers'][RUNNER_TUNNEL_TOKEN_HEADER], 'current-fixture-binding')
        self.assertEqual(result['session_id'], self.sid)
        self.assertEqual(result['tools'], [{'name': 'current_tool'}])

    def test_resident_pvc_directory_does_not_relax_private_file_ownership(self):
        mounted = SimpleNamespace(st_mode=stat.S_IFDIR | 0o2775, st_uid=0, st_gid=os.getegid())
        with patch.object(Path, 'lstat', return_value=mounted), patch.object(Path, 'is_symlink', return_value=False):
            self.assertEqual(helper.resident_directory(self.root), self.root)
            for changes in [dict(st_mode=stat.S_IFDIR | 0o2777), dict(st_gid=999999), dict(st_uid=999999)]:
                with patch.object(Path, 'lstat', return_value=SimpleNamespace(**{**vars(mounted), **changes})):
                    with self.assertRaisesRegex(helper.PiResumeError, 'UNSAFE_PATH'):
                        helper.resident_directory(self.root)
            with self.assertRaisesRegex(helper.PiResumeError, 'UNSAFE_PATH'):
                helper.owner_path(self.root, True)
        self.history.chmod(0o666)
        with self.assertRaisesRegex(helper.PiResumeError, 'UNSAFE_PATH'):
            helper.owner_path(self.history)

    def test_recovery_refuses_surviving_bridge_local_agent_before_restore_and_at_launch_preparation(self):
        request = dict(restoreSnapshot=True, sessionId=self.sid, nativeSessionId=self.native,
                       workspace=str(self.root), originalBytes=len(self.data),
                       originalSHA256=hashlib.sha256(self.data).hexdigest(), expectedAgentDir=str(self.root))
        (self.bridge / 'pi-agent').mkdir(mode=0o700)
        with self.assertRaisesRegex(helper.PiResumeError, 'ENV_UNAVAILABLE'):
            helper.prepare_pi_cold_resume(self.sid, self.info, expected=request)
        self.assertEqual(list(self.bridge.glob('woow-pi-cold-ticket-*.json')), [])
        _, data, request = self.recovery_fixture()
        self.bridge.mkdir(mode=0o700)
        (self.bridge / 'pi-agent').mkdir(mode=0o700)
        with self.assertRaisesRegex(helper.PiResumeError, 'ENV_UNAVAILABLE'):
            helper.inspect_pi_recovery(self.sid, self.info, request)
        self.assertFalse((self.bridge / 'sessions').exists())
        self.assertFalse((self.bridge / 'config.json').exists())

    def test_actual_pinned_runner_spec_callback_checks_admission_and_native_receipt(self):
        vendor = os.environ.get('OMNIGENT_TEST_SITE_PACKAGES')
        if not vendor:
            self.skipTest('OMNIGENT_TEST_SITE_PACKAGES required for pinned runner callback')
        sys.path.insert(0, vendor)
        sys.path.insert(0, str(SOURCE.parent))
        self.addCleanup(lambda: sys.path.remove(str(SOURCE.parent)))
        self.addCleanup(lambda: sys.path.remove(vendor))
        from omnigent.inner.datamodel import OSEnvSpec
        from omnigent.entities.session_resources import SessionResourceView
        from omnigent.runner.native.orchestration import NativeLaunchContext
        import native_resume
        launches = []
        live = [False]
        wrong_ticket = [False]
        pane = SimpleNamespace(pane_pid_sync=lambda: os.getpid())
        view = SessionResourceView(id='terminal_pi_main', type='terminal', session_id=self.sid, name='pi')

        async def launch(**kwargs):
            with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'):
                with helper.reserve_attachment(self.bridge): pass
            launches.append(kwargs)
            live[0] = True
            ticket = json.loads(Path(kwargs['spec'].args[1]).read_text())
            (self.bridge / 'woow-pi-cold-opened.json').write_text(json.dumps({
                'requestId': 'another-initializer' if wrong_ticket[0] else ticket['requestId'], 'nativeSessionId': self.native, 'sessionId': self.sid,
                'originalSHA256': ticket['nativeSHA256'], 'pid': os.getpid()}))
            (self.bridge / 'woow-pi-cold-opened.json').chmod(0o600)
            return view

        async def exchange(*args):
            with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'):
                with helper.reserve_attachment(self.bridge): pass
            return {'state': 'ready', 'nativeSessionId': self.native}

        ctx = SimpleNamespace(session_id=self.sid,
            agent_spec=SimpleNamespace(os_env=OSEnvSpec(type='caller_process', cwd=str(self.root))),
            resource_registry=SimpleNamespace(launch_required_terminal=launch, terminal_registry=SimpleNamespace(get=lambda *args: pane if live[0] else None)))
        with patch.object(native_resume, '_exchange', exchange), patch.object(helper, '_socket_peer_pid', return_value=os.getpid()):
            generations = iter([0, 1])
            with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'):
                asyncio.run(helper.launch_pi_strict(ctx, authorized_info=self.info, busy=lambda: False, epoch=lambda: next(generations)))
            self.assertEqual(launches, [])
            result, opened = asyncio.run(helper.launch_pi_strict(ctx, authorized_info=self.info, busy=lambda: False, epoch=lambda: 0))
        self.assertEqual(result, view)
        self.assertEqual(len(launches), 1)
        self.assertEqual(launches[0]['terminal_name'], 'pi')
        self.assertEqual(launches[0]['session_key'], 'main')
        self.assertEqual(launches[0]['parent_os_env'], ctx.agent_spec.os_env)
        self.assertEqual(launches[0]['spec'].os_env.sandbox, ctx.agent_spec.os_env.sandbox)
        self.assertEqual(self.history.read_bytes(), self.data)
        self.assertEqual((self.bridge / 'owner.pid').read_text(), str(os.getpid()))
        wrong_ticket[0] = True
        with patch.object(native_resume, '_exchange', exchange), patch.object(helper, '_socket_peer_pid', return_value=os.getpid()):
            with self.assertRaisesRegex(helper.PiResumeError, 'PI_RESUME_IDENTITY_CHANGED'):
                asyncio.run(helper.launch_pi_strict(ctx, authorized_info=self.info, busy=lambda: False, epoch=lambda: 0))
        wrong_ticket[0] = False
        with patch.object(native_resume, '_exchange', exchange), patch.object(helper, '_socket_peer_pid', return_value=os.getpid() + 1):
            with self.assertRaisesRegex(helper.PiResumeError, 'PI_RESUME_IDENTITY_CHANGED'):
                asyncio.run(helper.launch_pi_strict(ctx, authorized_info=self.info, busy=lambda: False, epoch=lambda: 0))
        # Exercise Bohr's exact adapter signature with actual pinned context,
        # resource serialization and terminal spec classes. No ordinary launch.
        async def get(*args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: self.info)
        async def resolve():
            return ctx.agent_spec
        events = []
        live[0] = False
        ctx.resource_registry.session_turn_is_active = lambda sid: False
        ctx.resource_registry.session_activity_epoch = lambda sid: 0
        native_ctx = NativeLaunchContext(session_id=self.sid, resource_registry=ctx.resource_registry,
            publish_event=lambda *args: events.append(args), server_client=SimpleNamespace(get=get))
        request = {'engine': 'pi', 'sessionId': self.sid, 'nativeSessionId': self.native,
            'workspace': str(self.root), 'originalBytes': len(self.data), 'originalSHA256': hashlib.sha256(self.data).hexdigest()}
        with patch.object(native_resume, '_exchange', exchange), patch.object(helper, '_socket_peer_pid', return_value=os.getpid()):
            result, receipt = asyncio.run(helper.cold_resume(native_ctx, request,
                launch_kwargs={'ensure_locks': {}, 'resolve_agent_spec': resolve}))
        self.assertTrue(result)
        self.assertEqual(receipt['nativeSessionId'], self.native)
        self.assertTrue(receipt['historyPrefixPreserved'])
        self.assertFalse(receipt['sameProcess'])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]['resource']['id'], 'terminal_pi_main')
        ctx.resource_registry.terminal_registry.get = lambda *args: object()
        with self.assertRaisesRegex(helper.PiResumeError, 'SESSION_BUSY'):
            asyncio.run(helper.cold_resume(native_ctx, request, launch_kwargs={'ensure_locks': {}}))
        self.assertEqual(len(launches), 4)


if __name__ == '__main__':
    unittest.main()
