"""Negative controls for the image gate; no Docker or real secrets needed."""
from pathlib import Path
import ast
import importlib.util
import contextlib
import io
import json
import os
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import image_boot_probe as probe


class BootGate(unittest.TestCase):
    def test_main_path_comes_only_from_candidate(self):
        spec = importlib.util.spec_from_file_location('image_smoke', Path(__file__).with_name('test-exec-boundary-image.py'))
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        original = '/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/bin:/bin'
        with patch.dict(os.environ, {'PATH': '/not-the-candidate'}), \
             patch.object(smoke, 'docker', return_value=SimpleNamespace(stdout=json.dumps({'path': original}).encode())) as docker:
            path = smoke.main_context('same-candidate-container')
            self.assertEqual(path, '/command:' + original)
            args = docker.call_args.args
            self.assertEqual(args[:3], ('exec', 'same-candidate-container', smoke.PYTHON))
            self.assertIn("os.environ['PATH']", args[-1])
            self.assertIn("os.access('/command/s6-setuidgid', os.X_OK)", args[-1])
            self.assertIn("os.access('/command/with-contenv', os.X_OK)", args[-1])
        cases = smoke.exec_cases(path)
        self.assertEqual(len(cases), 6)
        for flags, *_ in cases[:3]:
            self.assertFalse(any(x.startswith('PATH=') for x in flags))
        for flags, *_ in cases[3:]:
            self.assertEqual([x for x in flags if x.startswith('PATH=')], ['PATH=' + path])
        seed = ast.parse(smoke.seed_environment(path))
        self.assertEqual(ast.literal_eval(seed.body[-1].value.args[0]), path)
        for bad in ({}, {'path': ''}, {'path': '/usr/bin'}, {'path': '/opt/hermes/bin::/bin'}, {'path': 'relative:/opt/hermes/bin'}):
            with patch.object(smoke, 'docker', return_value=SimpleNamespace(stdout=json.dumps(bad).encode())):
                with self.assertRaises((ValueError, KeyError)): smoke.main_context('same-candidate-container')

    def test_context_diagnostics_only_print_boolean_schema(self):
        spec = importlib.util.spec_from_file_location('image_smoke', Path(__file__).with_name('test-exec-boundary-image.py'))
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        value = {name + '_' + check: False for name in ('s6-setuidgid', 'with-contenv')
                 for check in ('exists', 'executable', 'safe_file')}
        value.update(pid1_s6=False, tokens_cleaned=True, with_contenv_clears_env=True,
                     path='/synthetic-private-path')
        output = io.StringIO()
        with patch.object(smoke, 'docker', return_value=SimpleNamespace(stdout=json.dumps(value).encode())), contextlib.redirect_stdout(output):
            smoke.context_metadata('fixture')
        receipt = json.loads(output.getvalue().removeprefix('CONTEXT_CHECKS '))
        self.assertNotIn('path', receipt)
        self.assertTrue(all(type(v) is bool for v in receipt.values()))
        self.assertNotIn('/synthetic-private-path', output.getvalue())
        for bad in (dict(value, unexpected='synthetic'), dict(value, pid1_s6='synthetic')):
            output = io.StringIO()
            with patch.object(smoke, 'docker', return_value=SimpleNamespace(stdout=json.dumps(bad).encode())), contextlib.redirect_stdout(output):
                with self.assertRaises(ValueError): smoke.context_metadata('fixture')
            self.assertEqual(output.getvalue(), '')

    def test_empty_secret_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'secret'
            self.assertFalse(probe.secret_nonempty(p))
            p.touch()
            self.assertFalse(probe.secret_nonempty(p))
            p.write_text('synthetic')
            self.assertTrue(probe.secret_nonempty(p))

    def test_json_health_not_spa(self):
        self.assertTrue(probe.valid_health({'status': 'ok', 'platform': 'hermes-agent'}))
        for value in ('<html>ok</html>', {}, {'status': 'ok'}, {'status': 'error', 'platform': 'hermes-agent'}):
            self.assertFalse(probe.valid_health(value))

    def test_actual_worker_identity_uid_and_marker(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for pid in ('20', '10'): (root / pid).mkdir()
            (root / '10/cmdline').write_bytes(b's6-supervise\0gateway-default\0')
            (root / '20/cmdline').write_bytes(b'python\0/opt/hermes/.venv/bin/hermes\0gateway\0run\0--replace\0')
            (root / '20/status').write_text('Uid:\t10000\t10000\t10000\t10000\nPPid:\t10\n')
            env = {'tokens_absent': True, 'supervised_child': True}
            def check(pid=20, main=30):
                return probe.worker_checks('gateway-default', pid, main, root, lambda _: env)
            self.assertTrue(all(check().values()))
            self.assertFalse(any(check(pid=0).values()))
            self.assertFalse(any(check(main=20).values()))
            env['supervised_child'] = False
            self.assertFalse(check()['identity'])
            env['supervised_child'] = True
            env['tokens_absent'] = False
            self.assertFalse(check()['tokens_absent'])
            (root / '20/status').write_text('Uid:\t0\t0\t0\t0\nPPid:\t10\n')
            self.assertFalse(check()['uid10000'])
            # Heartbeat has the same gateway/run words, but is not this service.
            (root / '10/cmdline').write_bytes(b's6-supervise\0main-hermes\0')
            self.assertFalse(check()['identity'])

    def test_bundled_launcher_worker_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for pid in ('20', '10'): (root / pid).mkdir()
            (root / '20/status').write_text('Uid:\t10000\t10000\t10000\t10000\nPPid:\t10\n')
            env = {'tokens_absent': True, 'supervised_child': True}
            def check(role, args, parent=None):
                (root / '10/cmdline').write_bytes(('s6-supervise\0' + (parent or role) + '\0').encode())
                (root / '20/cmdline').write_bytes(('\0'.join(args) + '\0').encode())
                return probe.worker_checks(role, 20, 30, root, lambda _: env)
            launch = ['/opt/hermes/.venv/bin/python', '-P', '-c', probe.BUNDLED_HERMES_BOOTSTRAP]
            for role, command in [('gateway-default', ['gateway', 'run', '--replace']),
                                  ('dashboard', ['dashboard', '--host', '0.0.0.0'])]:
                self.assertTrue(all(check(role, launch + command).values()))
                self.assertFalse(check(role, launch + command, parent='main-hermes')['identity'])
                self.assertFalse(check(role, ['/tmp/python', *launch[1:], *command])['identity'])
                self.assertFalse(check(role, [*launch[:3], 'print("hermes")', *command])['identity'])
                self.assertFalse(check(role, [*launch[:3], launch[3] + '; print(1)', *command])['identity'])
                self.assertFalse(check(role, launch + ['chat'])['identity'])

    def test_paseo_bootstrap_matches_vendored_wrapper_and_rejects_extra_code(self):
        wrapper = (Path(__file__).resolve().parents[1] / 'vendor/paseo/hermes').read_text()
        self.assertIn(probe.PASEO_HERMES_BOOTSTRAP, wrapper)
        launch = ['/opt/hermes/.venv/bin/python', '-P', '-c', probe.PASEO_HERMES_BOOTSTRAP]
        self.assertEqual(probe.hermes_arguments(launch + ['dashboard']), ['dashboard'])
        self.assertEqual(probe.hermes_arguments(launch + ['acp']), ['acp'])
        self.assertIsNone(probe.hermes_arguments([*launch[:3], launch[3] + '\nprint(1)', 'dashboard']))
        self.assertIsNone(probe.hermes_arguments(['/tmp/python', *launch[1:], 'dashboard']))

    def test_heartbeat_dashboard_relay_without_gateway_fails(self):
        # Every other gate is live/healthy; only the true gateway PID is absent.
        original_worker_checks = probe.worker_checks
        def workers(role, pid, main):
            if role == 'gateway-default': return original_worker_checks(role, pid, main)
            return {'identity': True, 'uid10000': True, 'tokens_absent': True}
        with patch.object(probe, 'service_pid', side_effect=lambda role: 0 if role == 'gateway-default' else 30), \
             patch.object(probe, 'worker_checks', side_effect=workers), \
             patch.object(probe, 'gateway_health', return_value=True), \
             patch.object(probe, 'secret_nonempty', return_value=True), \
             patch.object(probe.Path, 'read_bytes', return_value=b's6-svscan'), \
             patch.object(probe.Path, 'exists', return_value=False), \
             patch.object(probe.socket, 'create_connection'):
            checks = probe.collect()
            self.assertTrue(checks['dashboard_listening'] and checks['relay_listening'])
            self.assertFalse(checks['gateway-default_identity'])
            self.assertFalse(all(checks.values()))


if __name__ == '__main__': unittest.main(verbosity=2)
