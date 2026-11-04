"""The upgrade test's runtime entry (pipeline #137, data hooks #138) against tiny fake add-ons on real Docker, no mocks.

Each fake add-on asks the mock Supervisor for its own info with its token (a wrong answer exits), reads
/data/options.json and counts its starts in /data. Needs a Docker daemon (GitHub runners have one)."""
import contextlib, io, json, pathlib, shutil, subprocess, tempfile, unittest, uuid
from unittest import mock
import yaml
import upgrade_runtime as rt
from upgrade_check import ASSIGNED_INGRESS_PORT

FAKE = r'''
import json, os, sys, time, urllib.request, http.server
req = urllib.request.Request('http://supervisor/addons/self/info', headers={'Authorization': 'Bearer ' + os.environ['SUPERVISOR_TOKEN']})
info = json.load(urllib.request.urlopen(req, timeout=10))['data']
assert info['slug'] == 'fake', info
# Like headscale, the add-on's private data may be mounted at the path of a `data` map entry.
D = '/var/lib/fake' if os.path.exists('/var/lib/fake/options.json') else '/data'
if os.path.isdir('/config'):open('/config/fake.conf', 'w').write('conf')
options = json.load(open(D + '/options.json'))
assert options['greeting'] == 'hi', options
starts = int(open(D + '/starts').read()) + 1 if os.path.exists(D + '/starts') else 1
open(D + '/starts', 'w').write(str(starts))
print('started', starts, flush=True)
if os.environ['MODE'] == 'crash':
    time.sleep(2); sys.exit(3)
if os.environ['MODE'] == 'forget':
    # Starts, but loses what the comparison target stored: an upgrade that drops the data.
    import shutil; shutil.rmtree(D + '/items', ignore_errors=True)
os.makedirs(D + '/items', exist_ok=True)
class H(http.server.BaseHTTPRequestHandler):
    # The add-on's own API for the data hooks: PUT /items/<key> stores the body in /data, GET /items/<key> reads it.
    def do_GET(self):
        item = D + '/items/' + self.path[7:] if self.path.startswith('/items/') else ''
        if item and os.path.exists(item):
            self.send_response(200); self.end_headers(); self.wfile.write(open(item, 'rb').read()); return
        self.send_response(200 if self.path == '/health' else 404); self.end_headers(); self.wfile.write(str(starts).encode())
    def do_PUT(self):
        open(D + '/items/' + self.path[7:], 'wb').write(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(204); self.end_headers()
# Like hamh and woow-tailscale (ingress_port: 0), serve on the ingress port Supervisor reports, if any.
server = http.server.HTTPServer(('0.0.0.0', info.get('ingress_port') or 8080), H)
if os.environ['MODE'] == 'answer-then-crash':
    # Answers its watchdog at once, then dies: a version that only looks started.
    import threading; threading.Thread(target=server.serve_forever, daemon=True).start(); time.sleep(4); os._exit(4)
server.serve_forever()
'''

# The data hooks (#138) of the fake add-on, run by the framework in the mock Supervisor's container. seed stores an
# item through the add-on's API and a file in the share directory, and records the environment it was given.
SEED = r'''#!/usr/bin/env python3
import json, os, urllib.request
env = dict(os.environ)
urllib.request.urlopen(urllib.request.Request(env['ADDON_URL'] + '/items/greeting', data=b'hello', method='PUT'), timeout=10)
open(env['DATA_DIR_SHARE'] + '/seeded.txt', 'w').write('seeded')
json.dump(env, open(env['HOOK_STATE_DIR'] + '/seed-env.json', 'w'))
json.dump({'checks': [{'name': 'item stored', 'result': 'pass', 'detail': 'greeting=hello'}]}, open(env['REPORT_DIR'] + '/seed.json', 'w'))
print('seeded')
'''
# For the map types test: seed stores an item through the API (in the add-on's data, wherever it is mounted);
# verify finds it, and the add-on's own files, in the directories DATA_DIR_DATA and DATA_DIR_ADDON_CONFIG name.
SEED_ITEM = r'''#!/usr/bin/env python3
import os, urllib.request
urllib.request.urlopen(urllib.request.Request(os.environ['ADDON_URL'] + '/items/greeting', data=b'hello', method='PUT'), timeout=10)
'''
VERIFY_DIRS = r'''#!/usr/bin/env python3
import json, os, sys
env = dict(os.environ); data, conf = env.get('DATA_DIR_DATA', ''), env.get('DATA_DIR_ADDON_CONFIG', '')
def read(path):return open(path).read() if os.path.exists(path) else None
checks = [('addon_config dir', conf == '/upgrade-data/all_app_configs/fake', conf),
    ('addon_config holds the add-on /config', read(conf + '/fake.conf') == 'conf', conf),
    ('data dir holds the item written at /var/lib/fake', read(data + '/items/greeting') == 'hello', data),
    ('no other data dirs', sorted(k for k in env if k.startswith('DATA_DIR_')) == ['DATA_DIR_ADDON_CONFIG', 'DATA_DIR_DATA'],
        ' '.join(sorted(k for k in env if k.startswith('DATA_DIR_'))))]
json.dump({'checks': [{'name': n, 'result': 'pass' if ok else 'fail', 'detail': str(d)} for n, ok, d in checks]}, open(env['REPORT_DIR'] + '/verify.json', 'w'))
sys.exit(0 if all(ok for _, ok, _ in checks) else 1)
'''
# verify reads them back, checks what the framework hands it, and fails when a check fails.
VERIFY = r'''#!/usr/bin/env python3
import json, os, sys, urllib.error, urllib.request
env = dict(os.environ)
def get(url, headers={}):
    try:return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10).read().decode()
    except urllib.error.HTTPError as e:return f'HTTP {e.code}'
item = get(env['ADDON_URL'] + '/items/greeting')
info = json.loads(get(env['SUPERVISOR_URL'] + '/addons/self/info', {'Authorization': 'Bearer ' + env['SUPERVISOR_TOKEN']}))['data']
seed = json.load(open(env['HOOK_STATE_DIR'] + '/seed-env.json'))
checks = [('item kept', item == 'hello', item),
    ('share file kept', open(env['DATA_DIR_SHARE'] + '/seeded.txt').read() == 'seeded', env['DATA_DIR_SHARE']),
    ('data dir is the add-on /data', os.path.exists(env['DATA_DIR_DATA'] + '/options.json'), env['DATA_DIR_DATA']),
    ('supervisor answers', info['version'] == env['ADDON_VERSION'] == '1.1.0', info['version']),
    ('phases', (seed['PHASE'], env['PHASE']) == ('old', 'new'), env['PHASE']),
    ('images', seed['ADDON_IMAGE'].startswith('local/upgrade-test-fake-good:') and env['ADDON_IMAGE'].startswith('local/upgrade-test-fake-'), env['ADDON_IMAGE']),
    ('report dirs', (seed['REPORT_DIR'], env['REPORT_DIR']) == ('/hook-reports/old', '/hook-reports/new'), env['REPORT_DIR']),
    ('address', env['ADDON_URL'] == 'http://' + env['ADDON_HOST'] + ':8080', env['ADDON_URL'])]
json.dump({'checks': [{'name': n, 'result': 'pass' if ok else 'fail', 'detail': d} for n, ok, d in checks]
    + [{'name': 'not applicable', 'result': 'skip', 'detail': ''}]}, open(env['REPORT_DIR'] + '/verify.json', 'w'))
sys.exit(0 if all(ok for _, ok, _ in checks) else 1)
'''

def docker_ok():
    try:return subprocess.run(['docker', 'info'], capture_output=True).returncode == 0
    except OSError:return False

def leftovers():
    """Containers and networks an upgrade test left behind (close() removes them, also when open() fails)."""
    names = subprocess.run(['docker', 'ps', '-a', '--filter', 'name=upgrade-test-', '--format', '{{.Names}}'], capture_output=True, text=True).stdout.split()
    return names + subprocess.run(['docker', 'network', 'ls', '--filter', 'name=upgrade-test-', '--format', '{{.Name}}'], capture_output=True, text=True).stdout.split()

@unittest.skipUnless(docker_ok(), 'needs a Docker daemon (present on GitHub runners)')
class Runtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = {}
        build = pathlib.Path(tempfile.mkdtemp())
        try:
            (build / 'run.py').write_text(FAKE, encoding='utf-8')
            for mode in ('good', 'crash', 'answer-then-crash', 'forget'):
                (build / 'Dockerfile').write_text(f'FROM {rt.MOCK_IMAGE}\nENV MODE={mode}\nCOPY run.py /run.py\nCMD ["python", "-u", "/run.py"]\n')
                tag = f'local/upgrade-test-fake-{mode}:{uuid.uuid4().hex[:8]}'
                subprocess.run(['docker', 'build', '-q', '-t', tag, str(build)], check=True, capture_output=True)
                cls.images[mode] = tag
        finally:
            shutil.rmtree(build)
    @classmethod
    def tearDownClass(cls):
        subprocess.run(['docker', 'image', 'rm', '-f', *cls.images.values()], capture_output=True)
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / 'addon').mkdir(); self.reports = self.dir / 'reports'
    def config(self, side, **cfg):
        cfg = {'name': 'Fake', 'slug': 'fake', 'version': {'old': '1.0.0', 'new': '1.1.0'}[side], 'arch': ['amd64'],
            'options': {'greeting': 'hi'}, 'schema': {'greeting': 'str'}, **cfg}
        path = self.dir / f'{side}.yaml'; path.write_text(yaml.safe_dump(cfg), encoding='utf-8'); return str(path)
    def settings(self, **values):
        (self.dir / 'addon/upgrade-check').mkdir(exist_ok=True)
        (self.dir / 'addon/upgrade-check/settings.yaml').write_text(yaml.safe_dump(values), encoding='utf-8')
    def hook(self, name, text):
        (self.dir / 'addon/upgrade-check').mkdir(exist_ok=True)
        path = self.dir / f'addon/upgrade-check/{name}'; path.write_text(text, encoding='utf-8', newline='\n'); path.chmod(0o755)
    def run_test(self, old, new, **cfg):
        args = ['--name', 'fake', '--addon-dir', str(self.dir / 'addon'), '--report-dir', str(self.reports), '--summary', str(self.dir / 'summary.md'),
            '--old-image', self.images[old], '--old-config', self.config('old', **cfg), '--new-image', self.images[new], '--new-config', self.config('new', **cfg)]
        with contextlib.redirect_stdout(io.StringIO()) as out:code = rt.main(args)
        return code, json.loads((self.reports / 'fake.json').read_text(encoding='utf-8')), out.getvalue()
    def test_new_version_that_starts_on_the_old_data_passes(self):
        self.settings(stable_seconds=8)
        code, result, out = self.run_test('good', 'good', watchdog='http://[HOST]:[PORT:8080]/health')
        self.assertIn('answered with success, then the container ran 8 s without exiting or restarting', result['phases'][1]['detail'])
        self.assertEqual(code, 0, out); self.assertTrue(result['passed'])
        self.assertEqual([(p['phase'], p['started'], p['method']) for p in result['phases']], [('old', True, 'watchdog'), ('new', True, 'watchdog')])
        # The new version started on the comparison target's /data: its start count went on from the old one's.
        self.assertIn('2', result['phases'][1]['answer'])
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        self.assertIn('Startup only: data was not checked', summary); self.assertIn('只檢查啟動，沒有檢查資料', summary)
        # No hook: as before #138, startup only.
        self.assertEqual((result['hooks'], result['data_checked'], [p['hooks'] for p in result['phases']]), ([], False, [[], []]))
    def test_ingress_port_0_is_probed_at_the_port_supervisor_would_assign(self):
        # The add-on reads its port from /addons/self/info: it must get a real one, the same for both versions.
        self.settings(stable_seconds=3)
        code, result, out = self.run_test('good', 'good', ingress=True, ingress_port=0, webui='http://[HOST]:[PORT:9999]/')
        self.assertEqual(code, 0, out)
        self.assertEqual([(p['started'], p['method']) for p in result['phases']], [(True, 'ingress'), (True, 'ingress')])
        self.assertIn(f'the ingress http://172.30.33.10:{ASSIGNED_INGRESS_PORT}/ answered', result['phases'][1]['detail'])
    def test_new_version_that_crashes_after_starting_fails_with_the_reason(self):
        self.settings(stable_seconds=8)
        code, result, out = self.run_test('good', 'crash')
        self.assertEqual(code, 1); self.assertFalse(result['passed'])
        self.assertEqual([(p['phase'], p['started'], p['method']) for p in result['phases']], [('old', True, 'stays-up'), ('new', False, 'stays-up')])
        self.assertIn('the new version (1.1.0) did not start: the container exited with code 3', result['reason'])
        self.assertIn('::error title=Upgrade test::fake: the new version (1.1.0) did not start', out)
        self.assertIn('started 2', result['phases'][1]['logs'])
    def test_new_version_that_answers_its_watchdog_then_crashes_fails(self):
        # The probe passing is not enough: the container must then stay up for stable_seconds (owner, 2026-11-03).
        self.settings(stable_seconds=10)
        code, result, out = self.run_test('good', 'answer-then-crash', watchdog='http://[HOST]:[PORT:8080]/health')
        self.assertEqual(code, 1); self.assertEqual([p['started'] for p in result['phases']], [True, False])
        self.assertIn('answered with success, then the container exited with code 4 within 10 s', result['reason'])
    def test_comparison_target_that_does_not_start_fails_before_the_new_version(self):
        self.settings(stable_seconds=8)
        code, result, out = self.run_test('crash', 'good')
        self.assertEqual(code, 1); self.assertEqual([p['phase'] for p in result['phases']], ['old'])
        self.assertIn('the comparison target (1.0.0) did not start', result['reason'])
    def test_no_answer_within_the_time_limit_fails(self):
        self.settings(startup_timeout=6, stable_seconds=3)
        code, result, out = self.run_test('good', 'good', watchdog='http://[HOST]:[PORT:9999]/health')
        self.assertEqual(code, 1); self.assertIn('the watchdog http://172.30.33.10:9999/health did not answer with success within 6 s', result['reason'])
    def test_add_on_that_asks_supervisor_at_once_starts_when_the_mock_is_slow_to_listen(self):
        # Real Supervisor is up before any add-on starts: the add-on must not race the mock (CI run 41613705993).
        slow = ['sh', '-c', 'sleep 4; exec python -u /tooling/mock_supervisor.py serve']
        with mock.patch.object(rt, 'MOCK_COMMAND', slow):
            code, result, out = self.run_test('good', 'good', ingress=True, ingress_port=0)
        self.assertEqual(code, 0, out); self.assertEqual([p['started'] for p in result['phases']], [True, True])
    def test_mock_supervisor_that_never_answers_is_a_tool_error_with_its_log(self):
        broken = ['sh', '-c', 'echo mock is broken; sleep 600']
        with mock.patch.object(rt, 'MOCK_COMMAND', broken), mock.patch.object(rt, 'MOCK_WAIT', 4):
            code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 2); self.assertEqual(result['phases'], [])
        self.assertIn('the upgrade test could not run: the mock Supervisor did not answer within 4 s', result['reason'])
        self.assertIn('mock is broken', result['reason']); self.assertEqual(leftovers(), [])
    def test_mock_supervisor_that_exits_is_a_tool_error_at_once(self):
        crashed = ['sh', '-c', 'echo mock crashed; exit 5']
        with mock.patch.object(rt, 'MOCK_COMMAND', crashed):
            code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 2)
        self.assertIn('the mock Supervisor did not answer (the container exited with code 5)', result['reason'])
        self.assertIn('mock crashed', result['reason']); self.assertEqual(leftovers(), [])
    def test_request_log_keeps_the_add_ons_calls_not_the_readiness_check(self):
        # What #142 reports as unmocked Supervisor calls must come from the add-on only.
        self.settings(stable_seconds=3); seen = []; close = rt.UpgradeTestEnv.close
        def keep_log(env):
            seen.append((env.state / 'requests.log').read_text(encoding='utf-8')); close(env)
        with mock.patch.object(rt.UpgradeTestEnv, 'close', keep_log):
            code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 0, out); self.assertEqual(seen[0].splitlines(), ['GET /addons/self/info 200'] * 2)
    def test_settings_that_are_not_a_mapping_fail_with_the_reason(self):
        (self.dir / 'addon/upgrade-check').mkdir()
        (self.dir / 'addon/upgrade-check/settings.yaml').write_text('- 5\n', encoding='utf-8')
        code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 2); self.assertIn('could not run: settings must be a mapping', result['reason'])
    # The data check (#138): seed on the comparison target, verify on the new version, on the same directories.
    DATA_CONFIG = {'watchdog': 'http://[HOST]:[PORT:8080]/health', 'webui': 'http://[HOST]:[PORT:8080]/',
        'map': [{'type': 'share', 'read_only': False, 'path': '/srv/share'}]}
    def test_data_seeded_on_the_target_and_still_there_on_the_new_version_passes(self):
        self.settings(stable_seconds=3); self.hook('seed', SEED); self.hook('verify', VERIFY)
        code, result, out = self.run_test('good', 'good', **self.DATA_CONFIG)
        self.assertEqual(code, 0, out + json.dumps(result, indent=1)); self.assertTrue(result['passed'])
        self.assertEqual((result['hooks'], result['data_checked']), (['seed', 'verify'], True))
        seed, verify = (p['hooks'][0] for p in result['phases'])
        self.assertEqual((seed['hook'], seed['phase'], seed['passed'], seed['exit_code']), ('seed', 'old', True, 0))
        self.assertEqual(seed['checks'], [{'name': 'item stored', 'result': 'pass', 'detail': 'greeting=hello'}]); self.assertIn('seeded', seed['output'])
        self.assertEqual((verify['hook'], verify['phase'], verify['passed']), ('verify', 'new', True))
        self.assertEqual([c['result'] for c in verify['checks']], ['pass'] * 8 + ['skip'])
        # Every check is in the step summary, and it says data was checked.
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        self.assertIn('Data checked', summary); self.assertNotIn('Startup only', summary)
        for row in ('| seed | item stored | pass | greeting=hello |', '| verify | item kept | pass | hello |', '| verify | not applicable | skip |'):
            self.assertIn(row, summary)
    def test_hooks_get_each_data_directory_by_its_map_type(self):
        # #156: addon_config comes from all_app_configs/<slug>, and a `data` entry moves /data (headscale-style);
        # DATA_DIR_<TYPE> is named by the type config.yaml writes and is the directory the add-on wrote to.
        self.settings(stable_seconds=3)
        self.hook('seed', SEED_ITEM); self.hook('verify', VERIFY_DIRS)
        code, result, out = self.run_test('good', 'good', **{**self.DATA_CONFIG,
            'map': [{'type': 'data', 'path': '/var/lib/fake'}, {'type': 'addon_config', 'read_only': False}]})
        self.assertEqual(code, 0, out + json.dumps(result, indent=1))
        self.assertEqual([c['result'] for c in result['phases'][1]['hooks'][0]['checks']], ['pass'] * 4)
    def test_new_version_that_loses_the_data_fails_in_verify(self):
        self.settings(stable_seconds=3); self.hook('seed', SEED); self.hook('verify', VERIFY)
        code, result, out = self.run_test('good', 'forget', **self.DATA_CONFIG)
        self.assertEqual(code, 1); self.assertFalse(result['passed']); self.assertTrue(result['data_checked'])
        self.assertIn('verify failed on the new version (1.1.0): exited with code 1; failing checks: item kept', result['reason'])
        self.assertIn('::error title=Upgrade test::fake: verify failed on the new version', out)
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        self.assertIn('| verify | item kept | **fail** | HTTP 404 |', summary); self.assertIn('Output of verify on the new version', summary)
    def test_verify_that_exits_non_zero_fails(self):
        self.settings(stable_seconds=3); self.hook('verify', '#!/bin/sh\necho "the data is gone"\nexit 3\n')
        code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 1); self.assertEqual(result['hooks'], ['verify'])
        self.assertIn('verify failed on the new version (1.1.0): exited with code 3', result['reason'])
        self.assertIn('the data is gone', result['phases'][1]['hooks'][0]['output'])
        # verify ran without a seed: the report must not say seed wrote anything.
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        self.assertIn('Data checked by verify on the new version; there is no seed', summary); self.assertNotIn('seed wrote', summary)
    def test_hook_whose_interpreter_is_missing_or_that_links_outside_fails_with_a_hint(self):
        self.settings(stable_seconds=3); self.hook('verify', '#!/bin/bash\necho hi\n')
        code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 1); self.assertIn('could not run (exit 127): the interpreter on the #! line of upgrade-check/verify was not found', result['reason'])
        outside = self.dir / 'outside-verify'; outside.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8', newline='\n')
        (self.dir / 'addon/upgrade-check/verify').unlink()
        try:(self.dir / 'addon/upgrade-check/verify').symlink_to(outside)
        except OSError:self.skipTest('this account cannot create symlinks (Windows without developer mode)')
        code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 1); self.assertIn('upgrade-check/verify is a symlink to', result['reason'])
        self.assertIn('outside upgrade-check/', result['reason']); self.assertIsNone(result['phases'][1]['hooks'][0]['exit_code'])
    def test_verify_that_exits_0_with_a_failing_check_fails(self):
        self.settings(stable_seconds=3)
        self.hook('verify', '#!/bin/sh\necho \'{"checks":[{"name":"row kept","result":"fail","detail":"0 rows"}]}\' > "$REPORT_DIR/verify.json"\n')
        code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 1); self.assertIn('verify failed on the new version (1.1.0): exited 0; failing checks: row kept', result['reason'])
    def test_seed_that_fails_fails_on_the_comparison_target(self):
        self.settings(stable_seconds=3); self.hook('seed', '#!/bin/sh\nexit 2\n'); self.hook('verify', VERIFY)
        code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 1); self.assertEqual([p['phase'] for p in result['phases']], ['old'])
        self.assertIn('seed failed on the comparison target (1.0.0): exited with code 2', result['reason']); self.assertFalse(result['data_checked'])
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        self.assertIn('Data was not checked: the test failed before verify ran', summary); self.assertNotIn('已檢查資料', summary)
    def test_hook_past_its_time_limit_or_with_a_broken_report_fails(self):
        self.settings(stable_seconds=3, hook_timeout=3); self.hook('seed', '#!/bin/sh\necho "{" > "$REPORT_DIR/seed.json"\n')
        self.hook('verify', '#!/bin/sh\nsleep 30\n')
        code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 1); self.assertIn('seed failed on the comparison target (1.0.0): exited 0; its report seed.json is not JSON', result['reason'])
        (self.dir / 'addon/upgrade-check/seed').unlink()
        code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 1); self.assertIn('verify failed on the new version (1.1.0): did not finish within 3 s (hook_timeout)', result['reason'])
        self.assertEqual(leftovers(), [])

if __name__ == '__main__':
    unittest.main()
