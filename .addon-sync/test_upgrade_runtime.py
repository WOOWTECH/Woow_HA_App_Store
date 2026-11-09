"""The upgrade test's runtime entry (pipeline #137, data hooks #138) against tiny fake add-ons on real Docker, no mocks.

Each fake add-on asks the mock Supervisor for its own info with its token (a wrong answer exits), reads
/data/options.json and counts its starts in /data. Needs a Docker daemon (GitHub runners have one)."""
import contextlib, io, json, pathlib, re, shutil, subprocess, tempfile, traceback, unittest, uuid
from unittest import mock
import yaml
import upgrade_runtime as rt
from upgrade_check import ASSIGNED_INGRESS_PORT

FAKE = r'''
import json, os, re, sys, time, urllib.error, urllib.request, http.server
# Like dnsmasq-dhcp (#175): exits 0 at once without the capability its config.yaml's privileged asks for (NET_ADMIN, bit 12).
caps = int(re.search(r'CapEff:\s*(\w+)', open('/proc/self/status').read()).group(1), 16)
print('NET_ADMIN', 'present' if caps & 1 << 12 else 'absent', flush=True)
if os.environ['MODE'] == 'needs-net-admin' and not caps & 1 << 12:sys.exit(0)
req =urllib.request.Request('http://supervisor/addons/self/info', headers={'Authorization': 'Bearer ' + os.environ['SUPERVISOR_TOKEN']})
info = json.load(urllib.request.urlopen(req, timeout=10))['data']
assert info['slug'] == 'fake', info
# Like headscale, the add-on's private data may be mounted at the path of a `data` map entry.
D = '/var/lib/fake' if os.path.exists('/var/lib/fake/options.json') else '/data'
if os.path.isdir('/config'):open('/config/fake.conf', 'w').write('conf')
options = json.load(open(D + '/options.json'))
assert options['greeting'] == 'hi', options
# Other Supervisor API calls the options ask for (#142): what each answered goes to the log.
for path in options.get('calls', []):
    try:
        r = urllib.request.urlopen(urllib.request.Request('http://supervisor' + path, headers=req.headers), timeout=10)
        print('answer', path, r.status, json.dumps(json.load(r)['data'], sort_keys=True), flush=True)
    except urllib.error.HTTPError as e:
        print('answer', path, e.code, flush=True)
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
        if os.environ['MODE'] == 'ha-core' and self.path == '/':
            # #174: like music_assistant's ingress index, the user Supervisor's ingress names must be an HA admin, asked
            # through the mock's HA Core websocket (as hamh connects: <base>/api/websocket), and HA Core's REST API
            # must answer RUNNING; else 500, so the ingress probe fails.
            sys.path.insert(0, '/'); import mock_supervisor as m
            try:
                sock, reader = m.ws_connect('http://supervisor/core', os.environ['SUPERVISOR_TOKEN'])
                users = m.ws_call(sock, reader, {'type': 'config/auth/list'}); sock.close()
                admin = any(u['id'] == self.headers.get('X-Remote-User-ID') and 'system-admin' in u['group_ids'] for u in users)
                config = json.load(urllib.request.urlopen(urllib.request.Request('http://supervisor/core/api/config', headers=req.headers), timeout=10))
                ok = admin and config['state'] == 'RUNNING'
            except Exception as e:
                print('HA Core check failed:', repr(e), flush=True); ok = False
            self.send_response(200 if ok else 500); self.end_headers(); self.wfile.write(b'admin' if ok else b'no'); return
        item = D + '/items/' + self.path[7:] if self.path.startswith('/items/') else ''
        if item and os.path.exists(item):
            self.send_response(200); self.end_headers(); self.wfile.write(open(item, 'rb').read()); return
        # /feature is what the smoke hook (#139) checks; a version in MODE regress has lost it.
        works = self.path == '/health' or (self.path == '/feature' and os.environ['MODE'] != 'regress')
        self.send_response(200 if works else 404); self.end_headers(); self.wfile.write(str(starts).encode())
    def do_PUT(self):
        open(D + '/items/' + self.path[7:], 'wb').write(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(204); self.end_headers()
# Like hamh and woow-tailscale (ingress_port: 0), serve on the ingress port Supervisor reports, if any; like pi_agent's
# nginx (host_network, #158), only on the address Supervisor reports: binding fails unless it is in this namespace.
server = http.server.HTTPServer((info['ip_address'], info.get('ingress_port') or 8080), H)
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
# The smoke hook (#139) runs the same checks on both versions, after seed on the comparison target (it finds the
# item seed stored); the new version reports one more check, which also finds what smoke left in its own
# HOOK_STATE_DIR on the comparison target. It exits 1 when a check fails.
SMOKE = r'''#!/usr/bin/env python3
import json, os, sys, urllib.error, urllib.request
def status(path):
    try:return urllib.request.urlopen(os.environ['ADDON_URL'] + path, timeout=10).status
    except urllib.error.HTTPError as e:return e.code
checks = [('seeded item readable', status('/items/greeting') == 200), ('feature works', status('/feature') == 200)]
state = os.environ['HOOK_STATE_DIR']
if os.environ['PHASE'] == 'new':checks.append(('new check', status('/health') == 200 and os.path.exists(state + '/smoke-old') and state == '/smoke-state'))
open(state + '/smoke-' + os.environ['PHASE'], 'w').write('ran')
json.dump({'checks': [{'name': n, 'result': 'pass' if ok else 'fail', 'detail': os.environ['PHASE']} for n, ok in checks]}, open(os.environ['REPORT_DIR'] + '/smoke.json', 'w'))
sys.exit(0 if all(ok for _, ok in checks) else 1)
'''

# #157: seed keeps the options the comparison target booted with and prints its password; verify finds the
# repository's value and the same generated password on the new version (and prints it: the report must mask it).
SEED_OPTIONS = r'''#!/usr/bin/env python3
import json, os, shutil
shutil.copy(os.environ['DATA_DIR_DATA'] + '/options.json', os.environ['HOOK_STATE_DIR'] + '/old-options.json')
print('pw=' + json.load(open(os.environ['DATA_DIR_DATA'] + '/options.json'))['pw'])
# Then enough output that the password sits where the report cuts the output to its last 4000 characters.
print('.' * 3988)
'''
VERIFY_OPTIONS = r'''#!/usr/bin/env python3
import json, os, re, sys
old = json.load(open(os.environ['HOOK_STATE_DIR'] + '/old-options.json'))
new = json.load(open(os.environ['DATA_DIR_DATA'] + '/options.json'))
print('pw=' + new['pw'])
checks = [('repo value', old['token'] == new['token'] == 'repo-token-value', ''),
    ('repo value beats the default', new['greeting'] == 'hi' and new['level'] == 3, str(new['level'])),
    ('generated password', bool(re.fullmatch('[A-Za-z0-9]{32}', new['pw'])), str(len(new['pw']))),
    ('same password on both versions', old['pw'] == new['pw'], ''),
    ('optional password not generated', 'spare' not in new, ''),
    ('key only the new schema has', ('extra' in old, new.get('extra')) == (False, 'new only'), '')]
json.dump({'checks': [{'name': n, 'result': 'pass' if ok else 'fail', 'detail': d} for n, ok, d in checks]}, open(os.environ['REPORT_DIR'] + '/verify.json', 'w'))
sys.exit(0 if all(ok for _, ok, _ in checks) else 1)
'''

# #158: a host-network add-on is reached at the bridge gateway, from the Supervisor's address.
VERIFY_HOST = r'''#!/usr/bin/env python3
import json, os, sys, urllib.request
env = dict(os.environ)
body = urllib.request.urlopen(env['ADDON_URL'] + '/health', timeout=10).read().decode()
checks = [('address', (env['ADDON_HOST'], env['ADDON_URL']) == ('172.30.32.1', 'http://172.30.32.1:8080'), env['ADDON_URL']),
    ('answers on the gateway', body == '2', body)]
json.dump({'checks': [{'name': n, 'result': 'pass' if ok else 'fail', 'detail': d} for n, ok, d in checks]}, open(env['REPORT_DIR'] + '/verify.json', 'w'))
sys.exit(0 if all(ok for _, ok, _ in checks) else 1)
'''

def docker_ok():
    try:return subprocess.run(['docker', 'info'], capture_output=True).returncode == 0
    except OSError:return False

def leftovers():
    """Containers and networks an upgrade test left behind (close() removes them, also when open() fails)."""
    names = subprocess.run(['docker', 'ps', '-a', '--filter', 'name=upgrade-test-', '--format', '{{.Names}}'], capture_output=True, text=True).stdout.split()
    return names + subprocess.run(['docker', 'network', 'ls', '--filter', 'name=upgrade-test-', '--format', '{{.Name}}'], capture_output=True, text=True).stdout.split()

class RegressionReport(unittest.TestCase):
    """compare_smoke() and the report's category 3 section (#139), on a result as upgrade_test() returns it; no Docker."""
    def result(self, old, new, passed=True, reason=''):
        def run(phase, code, checks):
            return {'hook': 'smoke', 'phase': phase, 'passed': code == 0, 'exit_code': code, 'detail': f'exited with code {code}',
                'checks': [{'name': n, 'result': r, 'detail': f'{phase} {n}'} for n, r in checks.items()], 'output': '', 'report_error': '', 'reported': True}
        return {'name': 'fake', 'passed': passed, 'reason': reason, 'hooks': ['smoke'], 'data_checked': False, 'phases': [
            {'phase': p, 'version': v, 'image': 'i', 'method': 'stays-up', 'started': True, 'detail': 'd', 'answer': '', 'logs': '', 'hooks': [run(p, *r)]}
            for p, v, r in (('old', '1.0.0', old), ('new', '1.1.0', new))]}
    def test_regression_fails_a_passing_upgrade_test_and_every_check_is_in_the_report(self):
        result = rt.compare_smoke(self.result((0, {'api': 'pass', 'old bug': 'fail'}), (1, {'api': 'fail', 'old bug': 'fail', 'new | check': 'pass'})))
        self.assertFalse(result['passed']); self.assertEqual(result['reason'], result['regression']['reason'])
        text = rt.report(result)
        self.assertIn('**Failed**: regression (category 3): (the hook) passes on the comparison target but is fail on the new version; api passes', text)
        self.assertIn('| check | the comparison target 1.0.0 | the new version 1.1.0 | comparison |', text)
        for row in ('| (the hook) | pass | **fail** | **regression** |', '| api | pass | **fail** | **regression** |',
                '| old bug | **fail** | **fail** | not compared: not passing on the comparison target (未比對, report only) |',
                '| new \\| check | absent | pass | only in the new version, passes |'):
            self.assertIn(row, text)
    def test_a_failed_upgrade_test_keeps_its_reason(self):
        result = rt.compare_smoke(self.result((0, {'api': 'pass'}), (0, {'api': 'fail'}), passed=False, reason='verify failed'))
        self.assertEqual((result['passed'], result['reason']), (False, 'verify failed')); self.assertFalse(result['regression']['passed'])
        result = rt.compare_smoke(self.result((0, {'api': 'pass'}), (0, {'api': 'pass', 'new': 'skip'})))
        self.assertFalse(result['passed']); self.assertIn('| new | absent | skip | only in the new version: **must pass** | new new |', rt.report(result))
    def test_smoke_runs_are_in_the_regression_table_only(self):
        result = self.result((0, {'api': 'pass'}), (0, {'api': 'pass'}))
        result['hooks'] = ['seed', 'smoke']
        result['phases'][0]['hooks'].insert(0, {'hook': 'seed', 'phase': 'old', 'passed': True, 'exit_code': 0, 'detail': 'exited 0',
            'checks': [{'name': 'item stored', 'result': 'pass', 'detail': 'ok'}], 'output': '', 'report_error': '', 'reported': True})
        text = rt.report(rt.compare_smoke(result))
        self.assertIn('| api | pass | pass | no regression | new api |', text)
        self.assertIn('| the comparison target 1.0.0 | seed | item stored | pass | ok |', text); self.assertNotIn('| smoke |', text)

class HookDispatch(unittest.TestCase):
    """upgrade_test()'s phase loop with every hook present, its containers stubbed (no Docker): which hook runs where,
    in which order (#139; a KeyError here once broke every upgrade test with smoke, n8n #28)."""
    def run_upgrade_test(self, hooks, failing=()):
        """hooks: the upgrade-check/ files; failing: the (hook, phase) runs that fail. The result and the runs in order."""
        work = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, work, True)
        (work / 'addon/upgrade-check').mkdir(parents=True)
        for h in hooks:(work / 'addon/upgrade-check' / h).write_text('#!/bin/sh\n', encoding='utf-8')
        calls = []
        class Env:
            prefix = 'upgrade-test-stub'
            def __init__(self, *a):pass
            def open(self):pass
            def start(self, phase, *a):return f'stub-{phase}'
            def run_hook(self, hook, phase, *a):
                calls.append((hook, phase)); ok = (hook, phase) not in failing
                return {'hook': hook, 'phase': phase, 'passed': ok, 'exit_code': 0 if ok else 1, 'detail': 'exited 0' if ok else 'exited with code 1',
                    'checks': [{'name': 'api', 'result': 'pass' if ok else 'fail', 'detail': ''}], 'output': '', 'report_error': '', 'reported': True}
            def stop(self, *a):pass
            def supervisor_calls(self):return {'unmocked': [], 'broken_fixtures': []}
            def close(self):pass
        config = lambda v:{'name': 'Fake', 'slug': 'fake', 'version': v, 'arch': ['amd64']}
        with mock.patch.object(rt, 'UpgradeTestEnv', Env), mock.patch.object(rt, 'wait_started', return_value=(True, 'started', '')), \
                mock.patch.object(rt, '_logs', return_value=''):
            result = rt.compare_smoke(rt.upgrade_test('fake', str(work / 'addon'), 'old:1', config('1.0.0'), 'new:1', config('1.1.0'), str(work / 'w')))
        return result, calls
    def test_every_hook_runs_in_its_phase_with_smoke_after_the_data_hook(self):
        result, calls = self.run_upgrade_test(('seed', 'verify', 'smoke'))
        self.assertEqual(calls, [('seed', 'old'), ('smoke', 'old'), ('verify', 'new'), ('smoke', 'new')])
        self.assertTrue(result['passed'], result['reason']); self.assertEqual(result['hooks'], ['seed', 'verify', 'smoke'])
        self.assertTrue(result['regression']['compared'])
        result, calls = self.run_upgrade_test(('smoke',))
        self.assertEqual(calls, [('smoke', 'old'), ('smoke', 'new')]); self.assertTrue(result['passed'], result['reason'])
    def test_a_failing_data_hook_stops_smoke_on_that_version(self):
        result, calls = self.run_upgrade_test(('seed', 'verify', 'smoke'), failing={('seed', 'old')})
        self.assertEqual(calls, [('seed', 'old')]); self.assertIn('seed failed on the comparison target', result['reason'])
        result, calls = self.run_upgrade_test(('seed', 'verify', 'smoke'), failing={('verify', 'new')})
        self.assertEqual(calls, [('seed', 'old'), ('smoke', 'old'), ('verify', 'new')])
        self.assertEqual(result['phases'][1]['smoke_not_run'], result['reason']); self.assertFalse(result['regression']['compared'])
    def test_a_smoke_regression_fails_the_test(self):
        result, calls = self.run_upgrade_test(('seed', 'verify', 'smoke'), failing={('smoke', 'new')})
        self.assertEqual(len(calls), 4); self.assertFalse(result['passed'])
        self.assertTrue(result['reason'].startswith('regression (category 3): '), result['reason'])

class HookChecks(unittest.TestCase):
    """What a hook's report may say and what smoke's environment is (#139); no Docker."""
    def test_the_hooks_own_row_name_is_reserved(self):
        path = pathlib.Path(tempfile.mkdtemp()) / 'smoke.json'; self.addCleanup(shutil.rmtree, path.parent)
        path.write_text(json.dumps({'checks': [{'name': 'api', 'result': 'pass'}, {'name': '(the hook)', 'result': 'pass'}]}), encoding='utf-8')
        checks, problem = rt._read_checks(path)
        self.assertEqual(checks, []); self.assertIn("names a check '(the hook)', which is reserved", problem)
    def test_an_unusable_report_gives_no_checks(self):
        # The checks before the problem are not kept: on the comparison target they would be compared one by one.
        path = pathlib.Path(tempfile.mkdtemp()) / 'smoke.json'; self.addCleanup(shutil.rmtree, path.parent)
        api = {'name': 'api', 'result': 'pass'}
        for bad, why in (({'name': 'api', 'result': 'ok'}, 'has a check that is not'), (api, "names two checks 'api'")):
            with self.subTest(why=why):
                path.write_text(json.dumps({'checks': [api, bad]}), encoding='utf-8')
                checks, problem = rt._read_checks(path)
                self.assertEqual(checks, []); self.assertIn(why, problem)
    def test_smoke_has_its_own_state_directory(self):
        env = rt.UpgradeTestEnv(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, env.work)
        config = {'slug': 'fake', 'version': '1.0.0'}
        self.assertEqual([env.hook_env('old', 'i', config, h)['HOOK_STATE_DIR'] for h in ('seed', 'verify', 'smoke')],
            ['/hook-state', '/hook-state', '/smoke-state'])

class IngressInfo(unittest.TestCase):
    """#161: /addons/self/info's ingress_entry and ingress_url as Supervisor gives them (App.ingress_entry/ingress_url)."""
    def addon_info(self, **config):
        return rt.addon_info({'slug': 'fake', 'version': '1.0.0', **config}, {}, 'tok')
    def test_ingress_without_an_entry(self):
        info = self.addon_info(ingress=True)
        self.assertEqual((info['ingress_entry'], info['ingress_url']), ('/api/hassio_ingress/tok', '/api/hassio_ingress/tok/'))
    def test_the_entry_is_only_appended_to_the_url(self):
        info = self.addon_info(ingress=True, ingress_entry='signin')
        self.assertEqual((info['ingress_entry'], info['ingress_url']), ('/api/hassio_ingress/tok', '/api/hassio_ingress/tok/signin'))
    def test_the_entry_is_appended_as_is(self):
        self.assertEqual(self.addon_info(ingress=True, ingress_entry='/')['ingress_url'], '/api/hassio_ingress/tok//')
    def test_no_ingress_gives_none_even_with_an_entry(self):
        info = self.addon_info(ingress_entry='signin')
        self.assertEqual((info['ingress_entry'], info['ingress_url']), (None, None))
    def test_old_and_new_version_share_the_token(self):
        env = rt.UpgradeTestEnv(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, env.work)
        config, seen = {'slug': 'fake', 'version': '1.0.0', 'ingress': True}, []
        with mock.patch.object(rt, 'docker', return_value=''):
            for phase in ('old', 'new'):
                env.start(phase, 'image', config, {})
                seen.append(json.loads((env.state / 'addon.json').read_text(encoding='utf-8'))['ingress_entry'])
        self.assertEqual(seen[0], seen[1]); self.assertRegex(seen[0], r'^/api/hassio_ingress/[A-Za-z0-9_-]{20,}$')
    def test_each_upgrade_test_has_its_own_token(self):
        envs = [rt.UpgradeTestEnv(tempfile.mkdtemp()) for _ in range(2)]
        for env in envs:self.addCleanup(shutil.rmtree, env.work)
        self.assertNotEqual(envs[0].ingress_token, envs[1].ingress_token)

class HostNetwork(unittest.TestCase):
    """#158: host_network: true runs the version in the host's namespace at the bridge gateway, as Supervisor does; any
    other value changes nothing. No Docker: the docker command is recorded."""
    VALUES = ({'host_network': True}, {}, {'host_network': False})
    def config(self, **extra):
        return {'slug': 'fake', 'version': '1.0.0', 'webui': 'http://[HOST]:[PORT:8080]/', **extra}
    def start(self, config):
        env = rt.UpgradeTestEnv(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, env.work)
        with mock.patch.object(rt, 'docker', return_value='') as docker:container = env.start('old', 'image:1', config, {})
        info = json.loads((env.state / 'addon.json').read_text(encoding='utf-8'))
        return env, container, list(docker.call_args.args), info
    def test_host_network_runs_in_the_hosts_namespace(self):
        env, container, args, info = self.start(self.config(host_network=True))
        self.assertEqual(args[:6], ['run', '-d', '--name', container, '--network', 'host'])
        self.assertNotIn('--ip', args); self.assertNotIn(env.net, args)
        # It still finds the mock Supervisor by name and gets its token.
        for arg in ('supervisor:172.30.32.2', 'hassio:172.30.32.2', f'SUPERVISOR_TOKEN={env.token}', f'HASSIO_TOKEN={env.token}'):
            self.assertIn(arg, args)
        self.assertEqual(info['ip_address'], '172.30.32.1')
    def test_without_host_network_the_arguments_are_unchanged(self):
        for value in self.VALUES[1:]:
            with self.subTest(value):
                env, container, args, info = self.start(self.config(**value))
                self.assertEqual(args, ['run', '-d', '--name', container, '--network', env.net, '--ip', '172.30.33.10', '--init',
                    '--add-host', 'supervisor:172.30.32.2', '--add-host', 'hassio:172.30.32.2', '-e', f'SUPERVISOR_TOKEN={env.token}',
                    '-e', f'HASSIO_TOKEN={env.token}', '-e', 'TZ=UTC', '--mount', f'type=bind,source={env.data.as_posix()}/data,target=/data', 'image:1'])
                self.assertEqual(info['ip_address'], '172.30.33.10')
    def test_the_hooks_address_is_the_gateway(self):
        env = rt.UpgradeTestEnv(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, env.work)
        for value, host in zip(self.VALUES, ('172.30.32.1', '172.30.33.10', '172.30.33.10')):
            with self.subTest(value):
                hook = env.hook_env('new', 'i', self.config(**value))
                self.assertEqual((hook['ADDON_HOST'], hook['ADDON_URL']), (host, f'http://{host}:8080'))
                self.assertEqual(rt.addon_url({'slug': 'fake', **value}), f'http://{host}')
                self.assertEqual(rt.addon_url({'ingress': True, 'ingress_port': 8099, **value}), f'http://{host}:8099')
    def test_the_probe_asks_each_version_at_its_own_address(self):
        # The comparison target and the new version may differ: each version's config.yaml decides for it.
        work = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, work, True)
        (work / 'addon/upgrade-check').mkdir(parents=True)
        (work / 'addon/upgrade-check/settings.yaml').write_text('stable_seconds: 1\n', encoding='utf-8')
        urls = []
        class Env:
            prefix = 'upgrade-test-stub'
            def __init__(self, *a):pass
            def open(self):pass
            def start(self, phase, *a):return f'stub-{phase}'
            def probe(self, url, below, timeout=5):urls.append(url); return True
            def fetch(self, url):return ''
            def stop(self, *a):pass
            def supervisor_calls(self):return {'unmocked': [], 'broken_fixtures': []}
            def close(self):pass
        config = lambda v, **extra:{'slug': 'fake', 'version': v, 'watchdog': 'http://[HOST]:[PORT:8080]/health', **extra}
        with mock.patch.object(rt, 'UpgradeTestEnv', Env), mock.patch.object(rt, '_down', return_value=''), mock.patch.object(rt, '_logs', return_value=''):
            result = rt.upgrade_test('fake', str(work / 'addon'), 'old:1', config('1.0.0', host_network=True), 'new:1', config('1.1.0'), str(work / 'w'))
        self.assertTrue(result['passed'], result['reason'])
        self.assertEqual(urls, ['http://172.30.32.1:8080/health', 'http://172.30.33.10:8080/health'])

class Privileged(unittest.TestCase):
    """#175: each version runs with one --cap-add per entry of its own config.yaml privileged, as Supervisor does; a value
    Supervisor would refuse fails the add-on's test before any container starts. No Docker: the docker command is recorded."""
    def config(self, **extra):
        return {'slug': 'fake', 'version': '1.0.0', **extra}
    def args(self, config):
        env = rt.UpgradeTestEnv(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, env.work)
        with mock.patch.object(rt, 'docker', return_value='') as docker:container = env.start('old', 'image:1', config, {})
        return env, container, list(docker.call_args.args)
    def caps(self, args):
        return [args[i + 1] for i, a in enumerate(args) if a == '--cap-add']
    def test_one_capability_gets_one_cap_add(self):
        env, container, args = self.args(self.config(privileged=['NET_ADMIN']))
        self.assertEqual(self.caps(args), ['NET_ADMIN'])
        self.assertEqual(args[:10], ['run', '-d', '--name', container, '--network', env.net, '--ip', '172.30.33.10', '--init', '--cap-add'])
    def test_each_entry_gets_its_own_flag(self):
        env, container, args = self.args(self.config(privileged=['NET_ADMIN', 'NET_RAW', 'SYS_ADMIN']))
        self.assertEqual(self.caps(args), ['NET_ADMIN', 'NET_RAW', 'SYS_ADMIN']); self.assertEqual(args.count('--cap-add'), 3)
    def test_without_privileged_no_capability_and_the_arguments_are_unchanged(self):
        for value in ({}, {'privileged': []}):
            with self.subTest(value):
                env, container, args = self.args(self.config(**value))
                self.assertEqual(args, ['run', '-d', '--name', container, '--network', env.net, '--ip', '172.30.33.10', '--init',
                    '--add-host', 'supervisor:172.30.32.2', '--add-host', 'hassio:172.30.32.2', '-e', f'SUPERVISOR_TOKEN={env.token}',
                    '-e', f'HASSIO_TOKEN={env.token}', '-e', 'TZ=UTC', '--mount', f'type=bind,source={env.data.as_posix()}/data,target=/data', 'image:1'])
    def test_host_network_and_privileged_apply_independently(self):
        env, container, args = self.args(self.config(host_network=True, privileged=['NET_ADMIN']))
        self.assertEqual(args[:6], ['run', '-d', '--name', container, '--network', 'host']); self.assertEqual(self.caps(args), ['NET_ADMIN'])
    def test_every_capability_supervisor_accepts_is_applied(self):
        env, container, args = self.args(self.config(privileged=list(rt.CAPABILITIES)))
        self.assertEqual(self.caps(args), list(rt.CAPABILITIES))
    def run_stubbed(self, old, new, profile=False):
        """upgrade_test() with the docker side stubbed: (result, [(phase, its --cap-add values)] of the versions started).
        `profile`: the add-on's directory has an apparmor.txt (#181)."""
        work = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, work, True)
        (work / 'addon/upgrade-check').mkdir(parents=True)
        if profile:(work / 'addon/apparmor.txt').write_text('profile fake {}\n', encoding='utf-8')
        (work / 'addon/upgrade-check/settings.yaml').write_text('stable_seconds: 1\n', encoding='utf-8')
        started, opened = [], []
        def docker(*args, check=True):
            if args[0] == 'run' and args[3].endswith(('-old', '-new')):started.append((args[3][-3:], self.caps(list(args))))
            if args[0] == 'network' and args[1] == 'create':opened.append(args)
            return ''
        with mock.patch.object(rt, 'docker', docker), mock.patch.object(rt.UpgradeTestEnv, 'probe', return_value=True), \
                mock.patch.object(rt, '_down', return_value=''), mock.patch.object(rt, '_logs', return_value=''), \
                mock.patch.object(rt.UpgradeTestEnv, 'supervisor_calls', return_value={'unmocked': [], 'broken_fixtures': []}):
            result = rt.upgrade_test('fake', str(work / 'addon'), 'old:1', {'slug': 'fake', 'version': '1.0.0', **old}, 'new:1',
                {'slug': 'fake', 'version': '1.1.0', **new}, str(work / 'w'))
        return result, started, opened
    def test_old_and_new_versions_each_use_their_own_list(self):
        result, started, _ = self.run_stubbed({'privileged': ['NET_ADMIN']}, {'privileged': ['SYS_ADMIN', 'NET_RAW']})
        self.assertTrue(result['passed'], result['reason'])
        self.assertEqual(started, [('old', ['NET_ADMIN']), ('new', ['SYS_ADMIN', 'NET_RAW'])])
        result, started, _ = self.run_stubbed({}, {'privileged': ['NET_ADMIN']})
        self.assertEqual(started, [('old', []), ('new', ['NET_ADMIN'])])
    def test_a_value_supervisor_would_refuse_fails_as_the_prs_fault_before_any_container_starts(self):
        cases = ((('old', 'the comparison target (1.0.0)'), ['NET_ADMIN', 'NET_ADMN'], "'NET_ADMN'"),
            (('new', 'the new version (1.1.0)'), ['net_admin'], "'net_admin'"),
            (('new', 'the new version (1.1.0)'), 'NET_ADMIN', 'not a list of capability names'),
            (('old', 'the comparison target (1.0.0)'), [['NET_ADMIN']], 'not a list of capability names'),
            (('new', 'the new version (1.1.0)'), None, 'not a list of capability names'))
        for (side, label), value, why in cases:
            with self.subTest(side=side, value=value):
                sides = {'old': {}, 'new': {}}; sides[side] = {'privileged': value}
                result, started, opened = self.run_stubbed(sides['old'], sides['new'])
                self.assertFalse(result['passed']); self.assertEqual((started, opened, result['phases']), ([], [], []))
                self.assertIn(f'the config.yaml of fake, {label}, has privileged: {json.dumps(value)}', result['reason'])
                self.assertIn(why, result['reason']); self.assertIn('Supervisor would refuse to install it', result['reason'])
    def test_unapplied_settings_are_listed_per_version_and_change_nothing(self):
        # #181: declared settings the runtime does not apply are recorded per version; the test runs and passes as without them.
        old = {'usb': True, 'full_access': False, 'devices': ['/dev/ttyUSB0']}
        new = {'usb': True, 'video': True, 'host_dbus': True, 'apparmor': True, 'privileged': ['NET_ADMIN']}
        result, started, _ = self.run_stubbed(old, new, profile=True)
        self.assertTrue(result['passed'], result['reason'])
        self.assertEqual(started, [('old', []), ('new', ['NET_ADMIN'])])
        self.assertEqual(result['unapplied_settings'], {'old': ['devices: ["/dev/ttyUSB0"]', 'usb: true'],
            'new': ['usb: true', 'video: true', 'host_dbus: true', 'apparmor: custom profile apparmor.txt']})
        result, _, _ = self.run_stubbed({}, {})
        self.assertTrue(result['passed']); self.assertEqual(result['unapplied_settings'], {'old': [], 'new': []})
    def test_the_prs_fault_exits_1_with_the_reason_not_as_a_tool_error(self):
        work = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, work, True)
        (work / 'addon').mkdir()
        for side, value in (('old', {}), ('new', {'privileged': ['NET_ADMN']})):
            (work / f'{side}.yaml').write_text(yaml.safe_dump({'slug': 'fake', 'version': '1.0.0', **value}), encoding='utf-8')
        args = ['--name', 'fake', '--addon-dir', str(work / 'addon'), '--report-dir', str(work / 'reports'), '--old-image', 'old:1',
            '--old-config', str(work / 'old.yaml'), '--new-image', 'new:1', '--new-config', str(work / 'new.yaml')]
        with mock.patch.object(rt, 'docker', side_effect=AssertionError('no docker command may run')), \
                contextlib.redirect_stdout(io.StringIO()) as out:code = rt.main(args)
        result = json.loads((work / 'reports/fake.json').read_text(encoding='utf-8'))
        self.assertEqual(code, 1, out.getvalue()); self.assertNotIn('could not run', result['reason'])
        self.assertIn("::error title=Upgrade test::fake: the config.yaml of fake, the new version (1.0.0), has privileged: [\"NET_ADMN\"]", out.getvalue())

class UnappliedSettings(unittest.TestCase):
    """#181: unapplied_settings() lists the Supervisor settings a config.yaml declares that the runtime does not apply."""
    def test_declared_settings_are_listed_in_order_with_their_values(self):
        config = {'host_uts': True, 'devices': ['/dev/net/tun'], 'usb': True, 'uart': True, 'udev': True, 'video': True, 'gpio': True,
            'tmpfs': True, 'audio': True, 'full_access': True, 'kernel_modules': True, 'realtime': True, 'docker_api': True,
            'host_dbus': True, 'host_pid': True, 'host_ipc': True}
        self.assertEqual(rt.unapplied_settings(config), ['devices: ["/dev/net/tun"]'] + [f'{k}: true' for k in rt.UNAPPLIED_SETTINGS[1:]])
    def test_defaults_and_false_values_are_left_out(self):
        config = {'devices': [], 'usb': False, 'uart': False, 'full_access': False, 'tmpfs': None, 'audio': '', 'apparmor': True,
            'privileged': ['NET_ADMIN'], 'host_network': True, 'map': ['config:rw'], 'slug': 'x'}
        self.assertEqual(rt.unapplied_settings(config), [])
        self.assertEqual(rt.unapplied_settings({}), [])
    def test_a_custom_apparmor_profile_is_listed_unless_apparmor_is_false(self):
        work = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, work, True)
        profile = work / 'apparmor.txt'
        self.assertEqual(rt.unapplied_settings({}, profile), [])
        profile.write_text('profile x {}\n', encoding='utf-8')
        self.assertEqual(rt.unapplied_settings({}, profile), ['apparmor: custom profile apparmor.txt'])
        self.assertEqual(rt.unapplied_settings({'apparmor': True}, profile), ['apparmor: custom profile apparmor.txt'])
        self.assertEqual(rt.unapplied_settings({'apparmor': False}, profile), [])
        # Without the version's directory (the comparison target), apparmor.txt cannot be seen.
        self.assertEqual(rt.unapplied_settings({}), [])
    def test_a_long_device_list_is_shortened(self):
        devices = [f'/dev/d{i}' for i in range(97)]
        self.assertEqual(rt.unapplied_settings({'devices': devices}),
            ['devices: 97 entries ("/dev/d0", "/dev/d1", "/dev/d2", "/dev/d3", "/dev/d4", … and 92 more)'])
    def test_other_values_are_shown_as_given(self):
        self.assertEqual(rt.unapplied_settings({'tmpfs': 'size=64m', 'video': 'yes'}), ['video: "yes"', 'tmpfs: "size=64m"'])

class HaCoreLifecycle(unittest.TestCase):
    """#174 without Docker: the docker and docker exec commands are recorded, core-setup is stood in for."""
    OWNER = {'url': rt.CORE_URL, 'client_id': rt.CORE_URL + '/', 'refresh_token': 'r', 'user_id': 'uid-1', 'user_name': 'upgrade-test',
        'display_name': 'Upgrade Test'}
    def env(self, ha_core):
        env = rt.UpgradeTestEnv(tempfile.mkdtemp(), None, ha_core); self.addCleanup(shutil.rmtree, env.work); return env
    def start_core(self, env, returncode=0, output='', down=''):
        """env.start_core() with core-setup exiting `returncode` (writing the owner on 0); (its result, the commands run)."""
        commands = []
        class Setup:
            def __init__(self, args, **kw):
                commands.append(args); self.returncode = returncode
                if returncode == 0:(env.state / 'core.json').write_text(json.dumps(HaCoreLifecycle.OWNER), encoding='utf-8')
            def poll(self):return self.returncode
            def communicate(self):return output, None
            def kill(self):self.returncode = -9
        run = lambda args, **kw:commands.append(args) or subprocess.CompletedProcess(args, 0, b'', b'')
        with mock.patch.object(rt, 'docker', side_effect=lambda *a, **k:commands.append(['docker', *a]) or ''), \
                mock.patch.object(rt.subprocess, 'Popen', Setup), mock.patch.object(rt.subprocess, 'run', run), \
                mock.patch.object(rt, '_down', return_value=down), mock.patch.object(rt, '_logs', return_value='core log'):
            return env.start_core(), commands
    def probe_args(self, env, url):
        with mock.patch.object(rt.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:env.probe(url, 500)
        return run.call_args.args[0]
    def test_ha_core_runs_on_the_mock_network_with_its_own_config_and_is_onboarded_by_the_mock(self):
        env = self.env(True)
        (ok, detail, seconds, logs), commands = self.start_core(env)
        self.assertEqual((ok, logs), (True, '')); self.assertIn('onboarded (owner upgrade-test) and RUNNING', detail); self.assertIsInstance(seconds, int)
        run = next(c for c in commands if c[:2] == ['docker', 'run'])
        self.assertEqual(run, ['docker', 'run', '-d', '--name', env.core, '--network', env.net, '--ip', '172.30.32.20', '-e', 'TZ=UTC',
            '--mount', f'type=bind,source={env.work / "ha-core"},target=/config', rt.CORE_IMAGE])
        # The image is the version the mock's /core/info reports; its config is no data directory of the add-on.
        self.assertEqual(rt.CORE_IMAGE, f'ghcr.io/home-assistant/qemux86-64-homeassistant:{rt.mock_supervisor.VERSIONS["homeassistant"]}')
        self.assertFalse((env.work / 'ha-core').is_relative_to(env.data))
        setup = next(c for c in commands if 'core-setup' in c)
        self.assertEqual(setup, ['docker', 'exec', env.supervisor, 'python', '/tooling/mock_supervisor.py', 'core-setup', '--core', 'http://172.30.32.20:8123',
            '--state', '/state', '--timeout', '180'])
    def test_the_probe_sends_the_owner_only_for_a_flagged_component(self):
        flagged, plain = self.env(True), self.env(False)
        self.start_core(flagged)
        args = self.probe_args(flagged, 'http://172.30.32.1:8094/')
        self.assertEqual(args[args.index('--header'):], ['--header', 'X-Remote-User-ID: uid-1', '--header', 'X-Remote-User-Name: upgrade-test',
            '--header', 'X-Remote-User-Display-Name: Upgrade Test'])
        self.assertNotIn('--header', self.probe_args(flagged, 'tcp://172.30.32.1:1883'))
        self.assertNotIn('--header', self.probe_args(plain, 'http://172.30.32.1:8094/'))
        self.assertEqual(plain.probe_headers, {})
    def test_the_180_s_wait_running_out_is_ha_core_not_starting(self):
        env = self.env(True)
        (ok, detail, seconds, logs), _ = self.start_core(env, 1, 'HA Core did not reach RUNNING within 180 s (it is STARTING)')
        self.assertEqual((ok, detail, seconds, logs), (False, 'HA Core did not reach RUNNING within 180 s (it is STARTING)', None, 'core log'))
        self.assertEqual(env.probe_headers, {})
        (ok, detail, _, _), _ = self.start_core(self.env(True), 1, '')
        self.assertEqual((ok, detail), (False, 'core-setup exited with code 1'))
        # HA Core's container exiting ends the wait at once, with why.
        (ok, detail, _, _), _ = self.start_core(self.env(True), None, down='the container exited with code 2')
        self.assertEqual((ok, detail), (False, 'the container exited with code 2'))
    def stub(self, core_result):
        """An UpgradeTestEnv stand-in whose start_core() returns `core_result`; calls: what upgrade_test asked of it."""
        calls = []
        class Env:
            prefix = 'upgrade-test-stub'
            core = 'upgrade-test-stub-core'
            def __init__(self, *a):calls.append(('init', a[2] if len(a) > 2 else False))
            def open(self):pass
            def start_core(self):calls.append('start_core'); return core_result
            def start(self, phase, *a):calls.append(phase); return f'stub-{phase}'
            def probe(self, url, below, timeout=5):return True
            def fetch(self, url):return ''
            def stop(self, *a):pass
            def supervisor_calls(self):return {'unmocked': [], 'broken_fixtures': []}
            def close(self):pass
        return Env, calls
    def upgrade_test(self, ha_core, core_result=(True, 'RUNNING', 40, '')):
        work = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, work, True)
        (work / 'addon/upgrade-check').mkdir(parents=True)
        (work / 'addon/upgrade-check/settings.yaml').write_text('stable_seconds: 1\n', encoding='utf-8')
        Env, calls = self.stub(core_result)
        config = lambda v:{'slug': 'fake', 'version': v, 'ingress': True, 'ingress_port': 8099}
        with mock.patch.object(rt, 'UpgradeTestEnv', Env), mock.patch.object(rt, '_down', return_value=''), mock.patch.object(rt, '_logs', return_value='core end log'):
            return rt.upgrade_test('fake', str(work / 'addon'), 'old:1', config('1.0.0'), 'new:1', config('1.1.0'), str(work / 'w'), ha_core), calls
    def test_ha_core_starts_once_before_the_comparison_target(self):
        result, calls = self.upgrade_test(True)
        self.assertTrue(result['passed'], result['reason']); self.assertEqual(calls, [('init', True), 'start_core', 'old', 'new'])
        self.assertEqual(result['ha_core'], {'image': rt.CORE_IMAGE, 'started': True, 'seconds': 40, 'detail': 'RUNNING', 'logs': 'core end log'})
        self.assertIn('Test HA Core (測試用 HA Core)', rt.report(result))
    def test_ha_core_that_does_not_start_fails_before_any_version_with_its_own_reason(self):
        result, calls = self.upgrade_test(True, (False, 'HA Core did not reach RUNNING within 180 s (it is STARTING)', None, 'boot log'))
        self.assertFalse(result['passed']); self.assertEqual(calls, [('init', True), 'start_core']); self.assertEqual(result['phases'], [])
        self.assertEqual(result['reason'], 'the test HA Core did not start (測試用 HA Core 沒有啟動): HA Core did not reach RUNNING within 180 s (it is STARTING)')
        text = rt.report(rt.compare_smoke(result))
        self.assertIn('**Failed**: the test HA Core did not start', text); self.assertIn('**did not start**', text)
        self.assertIn('Last log lines of the test HA Core', text); self.assertIn('boot log', text)
    def test_unflagged_components_never_start_ha_core(self):
        result, calls = self.upgrade_test(False)
        self.assertTrue(result['passed']); self.assertEqual(calls, [('init', False), 'old', 'new']); self.assertNotIn('ha_core', result)
        self.assertNotIn('HA Core', rt.report(result))

@unittest.skipUnless(docker_ok(), 'needs a Docker daemon (present on GitHub runners)')
class Runtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = {}
        build = pathlib.Path(tempfile.mkdtemp())
        try:
            (build / 'run.py').write_text(FAKE, encoding='utf-8')
            # The ha-core fake add-on (#174) talks websocket with mock_supervisor's frame code; fake_ha_core.py is the
            # standard-library HA Core the runtime starts in place of the real image (never pulled in tests).
            for name in ('mock_supervisor.py', 'fake_ha_core.py'):shutil.copy(rt.TOOLING / name, build / name)
            for mode in ('good', 'crash', 'answer-then-crash', 'forget', 'regress', 'needs-net-admin', 'ha-core'):
                (build / 'Dockerfile').write_text(f'FROM {rt.MOCK_IMAGE}\nENV MODE={mode}\nCOPY run.py mock_supervisor.py /\nCMD ["python", "-u", "/run.py"]\n')
                tag = f'local/upgrade-test-fake-{mode}:{uuid.uuid4().hex[:8]}'
                subprocess.run(['docker', 'build', '-q', '-t', tag, str(build)], check=True, capture_output=True)
                cls.images[mode] = tag
            for mode, args in (('core-running', ''), ('core-never', ', "--never-running"')):
                (build / 'Dockerfile').write_text(f'FROM {rt.MOCK_IMAGE}\nCOPY fake_ha_core.py mock_supervisor.py /\n'
                    f'CMD ["python", "-u", "/fake_ha_core.py"{args}]\n')
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
    def run_test(self, old, new, sides=None, ha_core=False, **cfg):
        # sides: config.yaml keys of one version only ({'old': {...}, 'new': {...}}). ha_core: --ha-core (#174).
        side = lambda s: self.config(s, **{**cfg, **(sides or {}).get(s, {})})
        args = ['--name', 'fake', '--addon-dir', str(self.dir / 'addon'), '--report-dir', str(self.reports), '--summary', str(self.dir / 'summary.md'),
            '--old-image', self.images[old], '--old-config', side('old'), '--new-image', self.images[new], '--new-config', side('new'),
            *(['--ha-core'] if ha_core else [])]
        with contextlib.redirect_stdout(io.StringIO()) as out:code = rt.main(args)
        return code, json.loads((self.reports / 'fake.json').read_text(encoding='utf-8')), out.getvalue()
    def test_flagged_add_on_that_needs_ha_core_starts_with_the_test_ha_core(self):
        # #174: the fake add-on's ingress answers 200 only when the probe's X-Remote-User-ID is an admin in HA Core (asked
        # over the mock's websocket) and HA Core's REST API is RUNNING, as music_assistant's ingress index needs.
        self.settings(stable_seconds=3); seen = []; close = rt.UpgradeTestEnv.close
        def keep(env):
            seen.append((env.state / 'requests.log').read_text(encoding='utf-8')); close(env)
        with mock.patch.object(rt, 'CORE_IMAGE', self.images['core-running']), mock.patch.object(rt.UpgradeTestEnv, 'close', keep):
            code, result, out = self.run_test('ha-core', 'ha-core', ha_core=True, ingress=True, ingress_port=8099)
        self.assertEqual(code, 0, out + json.dumps(result, indent=1)); self.assertTrue(result['passed'])
        self.assertEqual([(p['started'], p['method']) for p in result['phases']], [(True, 'ingress'), (True, 'ingress')])
        core = result['ha_core']
        self.assertEqual((core['image'], core['started']), (self.images['core-running'], True)); self.assertIsInstance(core['logs'], str)
        self.assertIsInstance(core['seconds'], int); self.assertIn('onboarded (owner upgrade-test) and RUNNING', core['detail'])
        self.assertEqual([p['answer'] for p in result['phases']], ['admin', 'admin'])
        log = seen[0].splitlines()
        # Every probe and the fetch of its answer asked HA Core through the mock: at least twice per version.
        self.assertGreaterEqual(log.count('GET /core/api/websocket 101 ha_core'), 4); self.assertGreaterEqual(log.count('GET /core/api/config 200 ha_core'), 4)
        self.assertEqual([l for l in log if 'ha_core' in l and ' 200 ' not in l and ' 101 ' not in l], [])
        # HA Core's answers are not unmocked Supervisor calls.
        self.assertEqual([p['supervisor'] for p in result['phases']], [{'unmocked': [], 'broken_fixtures': []}] * 2)
        self.assertIn('Test HA Core (測試用 HA Core)', (self.dir / 'summary.md').read_text(encoding='utf-8')); self.assertEqual(leftovers(), [])
    def test_the_same_add_on_without_the_flag_gets_no_ha_core(self):
        # Unflagged: no HA Core, /core/api... is 404 and the probe sends no X-Remote-User-*: the comparison target fails.
        self.settings(startup_timeout=8, stable_seconds=3)
        code, result, out = self.run_test('ha-core', 'ha-core', ingress=True, ingress_port=8099)
        self.assertEqual(code, 1); self.assertNotIn('ha_core', result)
        self.assertIn('the comparison target (1.0.0) did not start: the ingress http://172.30.33.10:8099/ did not answer below HTTP 500', result['reason'])
        self.assertIn('HA Core check failed', result['phases'][0]['logs'])
    def test_ha_core_that_never_runs_fails_the_test_with_its_own_reason(self):
        with mock.patch.object(rt, 'CORE_IMAGE', self.images['core-never']), mock.patch.object(rt, 'CORE_WAIT', 6):
            code, result, out = self.run_test('ha-core', 'ha-core', ha_core=True, ingress=True, ingress_port=8099)
        self.assertEqual(code, 1); self.assertEqual(result['phases'], [])
        self.assertEqual(result['reason'], f'{rt.CORE_FAILED}: HA Core did not reach RUNNING within 6 s (it is STARTING)')
        self.assertEqual((result['ha_core']['started'], result['ha_core']['seconds']), (False, None))
        self.assertIn(f'::error title=Upgrade test::fake: {rt.CORE_FAILED}', out)
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        self.assertIn('**did not start**', summary); self.assertIn('Last log lines of the test HA Core', summary); self.assertEqual(leftovers(), [])
    def test_ha_core_that_exits_fails_at_once(self):
        # An entrypoint that exits: the runtime sees the container down instead of waiting out CORE_WAIT.
        with mock.patch.object(rt, 'CORE_IMAGE', self.images['crash']):
            code, result, out = self.run_test('ha-core', 'ha-core', ha_core=True, ingress=True, ingress_port=8099)
        self.assertEqual(code, 1); self.assertEqual(result['phases'], [])
        self.assertRegex(result['reason'], re.escape(rt.CORE_FAILED) + r': the container exited with code \d+')
        self.assertEqual(leftovers(), [])
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
        # Nothing unmocked, no map entry ignored: the report has no such section (#142).
        self.assertEqual([p['supervisor'] for p in result['phases']], [{'unmocked': [], 'broken_fixtures': []}] * 2)
        self.assertEqual(result['map_warnings'], {'old': [], 'new': []})
        self.assertNotIn('Unmocked Supervisor calls', summary); self.assertNotIn('Map entries Supervisor ignores', summary)
    def test_unmocked_supervisor_calls_are_reported_and_fixtures_answer(self):
        # #142: a fixture in upgrade-check/supervisor/ answers its path; a path with neither a fixture nor a default
        # answers 404 and is listed per version with its count; a broken fixture answers 500. None of it fails the test.
        self.settings(stable_seconds=3)
        fixtures = self.dir / 'addon/upgrade-check/supervisor'; (fixtures / 'services').mkdir(parents=True)
        (fixtures / 'services/mqtt.json').write_text('{"host": "core-mosquitto", "port": 1883}', encoding='utf-8')
        (fixtures / 'broken.json').write_text('{', encoding='utf-8')
        # The info fixture is laid over the runtime's (the fake add-on exits unless its slug is still there), and a
        # broken ping fixture does not break the runtime's readiness check.
        (fixtures / 'addons/self').mkdir(parents=True); (fixtures / 'addons/self/info.json').write_text('{"hostname": "from-fixture"}', encoding='utf-8')
        (fixtures / 'supervisor').mkdir(); (fixtures / 'supervisor/ping.json').write_text('{', encoding='utf-8')
        calls = ['/services/mqtt', '/services/mysql', '/services/mysql/', '/broken', '/info']
        code, result, out = self.run_test('good', 'good', options={'greeting': 'hi', 'calls': calls}, map=['config:rw', 'addon_config'])
        self.assertEqual(code, 0, out + json.dumps(result, indent=1)); self.assertTrue(result['passed'])
        for p in result['phases']:
            self.assertIn('answer /services/mqtt 200 {"host": "core-mosquitto", "port": 1883}', p['logs'])
            self.assertIn('answer /services/mysql 404', p['logs']); self.assertIn('answer /broken 500', p['logs'])
            self.assertIn('answer /info 200', p['logs'])
            # Each version's own calls only, though the mock keeps one log for both.
            self.assertEqual(p['supervisor'], {'unmocked': [{'path': '/services/mysql', 'count': 2, 'methods': ['GET']}],
                'broken_fixtures': [{'path': '/broken', 'count': 1, 'methods': ['GET']}]})
        ignored = ["map entry 'addon_config' is ignored because 'config' is present (as Supervisor does)"]
        self.assertEqual(result['map_warnings'], {'old': ignored, 'new': ignored})
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        self.assertIn('Unmocked Supervisor calls (未模擬的 Supervisor 呼叫)', summary)
        for row in ('| the comparison target 1.0.0 | `/services/mysql` | 2 | GET |', '| the new version 1.1.0 | `/services/mysql` | 2 | GET |',
                '| the new version 1.1.0 | `/broken` | 1 | GET |'):
            self.assertIn(row, summary)
        self.assertIn('Supervisor fixtures that cannot be used', summary)
        self.assertIn("- map entry 'addon_config' is ignored because 'config' is present", summary)
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
    def test_comparison_target_that_docker_cannot_run_fails_with_the_reason(self):
        # #140: its image cannot be pulled, so docker run fails: the comparison target did not start, not a tool error.
        self.images = {**self.images, 'missing': f'local/upgrade-test-fake-missing:{uuid.uuid4().hex[:8]}'}
        code, result, out = self.run_test('missing', 'good')
        self.assertEqual(code, 1); self.assertEqual([(p['phase'], p['started']) for p in result['phases']], [('old', False)])
        self.assertIn('the comparison target (1.0.0) did not start: docker run failed', result['reason'])
        self.assertIn('::error title=Upgrade test::fake: the comparison target (1.0.0) did not start', out); self.assertEqual(leftovers(), [])
    def test_comparison_target_whose_entrypoint_is_missing_did_not_start_with_its_logs(self):
        # #140: docker run creates the container but cannot start it (exit 127): the image's fault, with what it logged.
        build = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, build, True)
        (build / 'Dockerfile').write_text(f'FROM {rt.MOCK_IMAGE}\nCMD ["/no-such-entrypoint"]\n')
        tag = f'local/upgrade-test-fake-noentry:{uuid.uuid4().hex[:8]}'
        subprocess.run(['docker', 'build', '-q', '-t', tag, str(build)], check=True, capture_output=True)
        self.addCleanup(subprocess.run, ['docker', 'image', 'rm', '-f', tag], capture_output=True)
        self.images = {**self.images, 'noentry': tag}
        # init: false, as Supervisor does then: with docker's init, init itself starts and exits 127 (an ordinary exit).
        code, result, out = self.run_test('noentry', 'good', init=False)
        self.assertEqual(code, 1, out); self.assertEqual([(p['phase'], p['started']) for p in result['phases']], [('old', False)])
        self.assertIn('the comparison target (1.0.0) did not start: docker run failed (127)', result['reason'])
        self.assertIn('no-such-entrypoint', result['reason']); self.assertIsInstance(result['phases'][0]['logs'], str)
        self.assertEqual(leftovers(), [])
    def test_docker_run_failure_that_is_not_the_images_is_a_tool_error(self):
        # #140: an address outside the hassio subnet stands for any runner fault (name or address in use, a bind
        # mount, the daemon): the test could not run (exit 2), it is not the comparison target's failure.
        with mock.patch.object(rt, 'ADDON_IP', '10.255.0.10'):code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 2, out); self.assertIn('the upgrade test could not run: docker run failed', result['reason'])
        self.assertNotIn('did not start', result['reason']); self.assertEqual(leftovers(), [])
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
    def network_modes(self):
        """Record each version's docker network mode as it stops (UpgradeTestEnv.stop): the list it fills."""
        modes, stop = [], rt.UpgradeTestEnv.stop
        def record(env, container, config):
            modes.append(subprocess.run(['docker', 'inspect', '-f', '{{.HostConfig.NetworkMode}}', container], capture_output=True, text=True).stdout.strip())
            stop(env, container, config)
        patch = mock.patch.object(rt.UpgradeTestEnv, 'stop', record); patch.start(); self.addCleanup(patch.stop)
        return modes
    def test_host_network_add_on_listens_on_the_gateway_and_finds_the_supervisor(self):
        # #158, pi_agent: the fake binds the address /addons/self/info reports (172.30.32.1), which exists only in the
        # host's namespace; it still reaches the mock Supervisor by name, and the probe and hooks reach it there.
        self.settings(stable_seconds=3); self.hook('verify', VERIFY_HOST); modes = self.network_modes()
        code, result, out = self.run_test('good', 'good', host_network=True, **self.DATA_CONFIG)
        self.assertEqual(code, 0, out + json.dumps(result, indent=1)); self.assertTrue(result['passed'])
        self.assertEqual(modes, ['host', 'host'])
        self.assertIn('the watchdog http://172.30.32.1:8080/health answered with success', result['phases'][0]['detail'])
        self.assertEqual([c['result'] for c in result['phases'][1]['hooks'][0]['checks']], ['pass', 'pass'])
        self.assertEqual(leftovers(), [])
    def test_each_version_runs_on_the_network_its_config_says(self):
        # The comparison target has host_network, the new version not: each is probed at its own address.
        self.settings(stable_seconds=3); modes = self.network_modes()
        code, result, out = self.run_test('good', 'good', watchdog='http://[HOST]:[PORT:8080]/health', sides={'old': {'host_network': True}})
        self.assertEqual(code, 0, out + json.dumps(result, indent=1))
        self.assertEqual((modes[0], modes[1].startswith('upgrade-test-')), ('host', True))
        self.assertEqual([p['detail'].split(' answered')[0] for p in result['phases']],
            ['the watchdog http://172.30.32.1:8080/health', 'the watchdog http://172.30.33.10:8080/health'])
    def test_an_add_on_that_needs_its_privileged_capability_gets_it(self):
        # #175, dnsmasq-dhcp: the fake exits 0 at once without NET_ADMIN; privileged: [NET_ADMIN] gives it, on the bridge
        # and with host_network alike.
        self.settings(stable_seconds=3)
        code, result, out = self.run_test('needs-net-admin', 'needs-net-admin', privileged=['NET_ADMIN'], sides={'old': {'host_network': True}})
        self.assertEqual(code, 0, out + json.dumps(result, indent=1)); self.assertEqual([p['started'] for p in result['phases']], [True, True])
        for p in result['phases']:self.assertIn('NET_ADMIN present', p['logs'])
        self.assertEqual(leftovers(), [])
    def test_without_privileged_the_capability_is_absent_and_such_an_add_on_does_not_start(self):
        self.settings(stable_seconds=3)
        code, result, out = self.run_test('needs-net-admin', 'needs-net-admin')
        self.assertEqual(code, 1); self.assertEqual([(p['phase'], p['started']) for p in result['phases']], [('old', False)])
        self.assertIn('the comparison target (1.0.0) did not start: the container exited with code 0', result['reason'])
        self.assertIn('NET_ADMIN absent', result['phases'][0]['logs'])
    def test_each_version_gets_the_capabilities_of_its_own_config(self):
        self.settings(stable_seconds=3)
        code, result, out = self.run_test('good', 'good', sides={'old': {'privileged': ['NET_ADMIN']}})
        self.assertEqual(code, 0, out + json.dumps(result, indent=1))
        self.assertEqual([('NET_ADMIN present' in p['logs'], 'NET_ADMIN absent' in p['logs']) for p in result['phases']], [(True, False), (False, True)])
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
        # No smoke: category 3 compares only that both versions start (#139).
        self.assertEqual([(r['name'], r['verdict']) for r in result['regression']['rows']], [('starts', 'pass')])
        self.assertIn('upgrade-check/ has no smoke, so only startup is compared (沒有 smoke，只比對能啟動)', summary)
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
    # The regression comparison (#139): smoke on both versions, compared check by check.
    def test_smoke_check_that_passes_on_the_target_and_fails_on_the_new_version_fails(self):
        self.settings(stable_seconds=3); self.hook('seed', SEED_ITEM); self.hook('smoke', SMOKE)
        code, result, out = self.run_test('good', 'regress', **self.DATA_CONFIG)
        self.assertEqual(code, 1, out + json.dumps(result, indent=1)); self.assertFalse(result['passed'])
        # Category 2 passed: both started and seed passed; smoke failing on the new version is category 3 only.
        self.assertEqual([p['started'] for p in result['phases']], [True, True]); self.assertEqual(result['hooks'], ['seed', 'smoke'])
        self.assertEqual([[h['hook'] for h in p['hooks']] for p in result['phases']], [['seed', 'smoke'], ['smoke']])
        self.assertTrue(result['reason'].startswith('regression (category 3): '), result['reason'])
        self.assertIn('feature works passes on the comparison target but is fail on the new version', result['reason'])
        self.assertIn('::error title=Upgrade test::fake: regression (category 3)', out)
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        for row in ('| feature works | pass | **fail** | **regression** |', '| seeded item readable | pass | pass | no regression |',
                '| new check | absent | pass | only in the new version, passes |', '| (the hook) | pass | **fail** | **regression** |'):
            self.assertIn(row, summary)
    def test_smoke_check_that_already_fails_on_the_target_is_only_reported(self):
        self.settings(stable_seconds=3); self.hook('seed', SEED_ITEM); self.hook('smoke', SMOKE)
        code, result, out = self.run_test('regress', 'regress', **self.DATA_CONFIG)
        self.assertEqual(code, 0, out + json.dumps(result, indent=1)); self.assertTrue(result['passed'])
        self.assertEqual({r['name']: r['verdict'] for r in result['regression']['rows']},
            {'(the hook)': 'not compared', 'seeded item readable': 'pass', 'feature works': 'not compared', 'new check': 'pass'})
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        # The comparison target's smoke exited 1 (feature works fails) but wrote its report: a check only the new
        # version has still must pass.
        self.assertIn('| new check | absent | pass | only in the new version, passes |', summary)
        self.assertIn('no smoke check that passes on the comparison target fails on the new version', summary)
        self.assertIn('| feature works | **fail** | **fail** | not compared: not passing on the comparison target (未比對, report only) |', summary)
    def test_smoke_does_not_run_on_the_new_version_after_category_2_failed(self):
        self.settings(stable_seconds=3); self.hook('smoke', SMOKE); self.hook('verify', '#!/bin/sh\nexit 3\n')
        code, result, out = self.run_test('good', 'good', **self.DATA_CONFIG)
        self.assertEqual(code, 1); self.assertIn('verify failed on the new version (1.1.0): exited with code 3', result['reason'])
        self.assertEqual([[h['hook'] for h in p['hooks']] for p in result['phases']], [['smoke'], ['verify']])
        self.assertEqual(result['phases'][1]['smoke_not_run'], result['reason'])
        self.assertEqual((result['regression']['compared'], result['regression']['rows']), (False, []))
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        self.assertIn('**Regression comparison** (category 3): not compared, smoke did not run on the new version: verify failed', summary)
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
    # #157: upgrade-check/options.yaml over the defaults, random required passwords, the same on both versions.
    OPTIONS_SCHEMA = {'greeting': 'str', 'pw': 'password', 'token': 'password', 'level': 'int', 'spare': 'password?'}
    def options_yaml(self, text):
        (self.dir / 'addon/upgrade-check').mkdir(exist_ok=True)
        (self.dir / 'addon/upgrade-check/options.yaml').write_text(text, encoding='utf-8')
    def test_repo_options_and_a_generated_password_reach_both_versions(self):
        self.settings(stable_seconds=3); self.hook('seed', SEED_OPTIONS); self.hook('verify', VERIFY_OPTIONS)
        self.options_yaml('token: repo-token-value\nlevel: 3\nextra: new only\n')
        code, result, out = self.run_test('good', 'good', options={'greeting': 'hi', 'pw': '', 'token': None, 'level': 1, 'spare': None},
            schema=self.OPTIONS_SCHEMA, sides={'new': {'schema': {**self.OPTIONS_SCHEMA, 'extra': 'str?'}}})
        self.assertEqual(code, 0, out + json.dumps(result, indent=1)); self.assertTrue(result['passed'])
        self.assertEqual([c['result'] for c in result['phases'][1]['hooks'][0]['checks']], ['pass'] * 6)
        self.assertEqual(result['options'], {'from_repo': ['extra', 'level', 'token'], 'generated': ['pw'], 'warnings': []})
        # Both hooks printed the password: the result and the report show the mask instead.
        for p in result['phases']:self.assertIn(f'{rt.MASK}', p['hooks'][0]['output'])
        # Masked before the cut: no piece of the password is left at the start of seed's output.
        self.assertIsNone(re.search('[A-Za-z0-9]{8}', result['phases'][0]['hooks'][0]['output'].replace(rt.MASK, '')))
        summary = (self.dir / 'summary.md').read_text(encoding='utf-8')
        self.assertIn('Test options (測試用的 options): upgrade-check/options.yaml sets `extra`, `level`, `token`; random passwords for `pw`', summary)
        self.assertNotIn('repo-token-value', json.dumps(result) + summary + out)
    def test_options_yaml_with_a_key_no_schema_has_fails_before_any_container(self):
        self.options_yaml('greting: typo\n')
        code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 2); self.assertEqual(result['phases'], [])
        self.assertIn("could not run: upgrade-check/options.yaml sets 'greting', which no version's config.yaml schema has", result['reason'])
        self.assertEqual(leftovers(), [])

class TestOptions(unittest.TestCase):
    """#157: what /data/options.json holds for each version, without Docker."""
    def build(self, config, given=None):
        (options,), generated = rt.build_test_options([config], given)
        return options, generated
    def test_without_options_yaml_or_passwords_the_defaults_stay(self):
        config = {'options': {'a': 1, 'b': None, 'c': ''}, 'schema': {'a': 'int', 'b': 'str?', 'c': 'str'}}
        self.assertEqual(self.build(config), ({'a': 1, 'c': ''}, {}))
    def test_repo_values_win_as_supervisor_merges_them(self):
        config = {'options': {'a': 1, 'nested': {'x': 1, 'y': 2}, 'items': [1, 2], 'gone': 'default'},
            'schema': {'a': 'int', 'nested': {'x': 'int', 'y': 'int'}, 'items': ['int'], 'gone': 'str?', 'new': 'str?'}}
        options, _ = self.build(config, {'a': 5, 'nested': {'y': 9}, 'items': [3], 'gone': None, 'new': 'n'})
        self.assertEqual(options, {'a': 5, 'nested': {'x': 1, 'y': 9}, 'items': [3], 'new': 'n'})
    def test_a_key_one_schema_lacks_is_left_out_for_that_version(self):
        old = {'options': {}, 'schema': {'a': 'str', 'n': {'x': 'str'}}}
        new = {'options': {}, 'schema': {'a': 'str', 'b': 'str?', 'n': {'x': 'str', 'y': 'str?'}}}
        given = {'a': 'x', 'b': 'x', 'n': {'x': '1', 'y': '2'}}
        rt.check_test_options(given, (old, new))
        (o, n), _ = rt.build_test_options([old, new], given)
        self.assertEqual(o, {'a': 'x', 'n': {'x': '1'}}); self.assertEqual(n, given)
        with self.assertRaisesRegex(ValueError, r"sets 'c', which no version's config.yaml schema has \(Supervisor drops"):
            rt.check_test_options({'a': 'x', 'c': 'x'}, (old, new))
        # Nested too, as Supervisor drops unknown keys of a nested mapping.
        with self.assertRaisesRegex(ValueError, r"sets 'n.z', which no version's config.yaml schema has"):
            rt.check_test_options({'n': {'x': '1', 'z': '3'}}, (old, new))
        # Without a schema mapping nothing is checked or left out.
        rt.check_test_options({'c': 'x'}, (old, {'options': {}, 'schema': False}))
        self.assertEqual(self.build({'options': {}}, {'c': 'x'})[0], {'c': 'x'})
    def test_a_password_value_that_is_not_a_string_is_refused(self):
        config = {'schema': {'pw': 'password?', 'n': {'pw': 'password'}, 'port': 'int'}}
        rt.check_test_options({'pw': None, 'port': 5, 'n': {'pw': 'ok'}}, [config])
        for given, name in (({'pw': 1234}, "'pw'"), ({'n': {'pw': True}}, "'n.pw'")):
            with self.subTest(given), self.assertRaisesRegex(ValueError, f'{name} is a password option, so its value must be a string, not a'):
                rt.check_test_options(given, [config])
        # A version without a schema accepts any key, but the other version's password type is still checked.
        for configs in (({'schema': False}, config), (config, {})):
            with self.subTest(configs):
                rt.check_test_options({'anything': 1, 'n': {'pw': 'ok', 'extra': 2}}, configs)
                with self.assertRaisesRegex(ValueError, "'n.pw' is a password option, so its value must be a string, not a int"):
                    rt.check_test_options({'n': {'pw': 1234}}, configs)
    def test_required_passwords_left_empty_get_one_random_value_for_both_versions(self):
        # omnigent: admin_password ''; odoo and nextcloud: null; nextcloud's db_password is password? (optional).
        old = {'options': {'admin_password': '', 'admin_passwd': None, 'db_password': None, 'user': ''},
            'schema': {'admin_password': 'password', 'admin_passwd': 'password', 'db_password': 'password?', 'user': 'str', 'smtp': 'password?'}}
        new = {**old, 'schema': {**old['schema'], 'short': 'password(4,12)', 'long': 'password(40,)'}}
        (first, second), generated = rt.build_test_options([old, new], None)
        self.assertEqual(sorted(generated), ['admin_passwd', 'admin_password', 'long', 'short'])
        for options in (first, second):
            self.assertRegex(options['admin_password'], r'^[A-Za-z0-9]{32}$'); self.assertRegex(options['admin_passwd'], r'^[A-Za-z0-9]{32}$')
            # Other required options that are empty stay so; optional passwords are not generated.
            self.assertEqual(options['user'], ''); self.assertNotIn('db_password', options); self.assertNotIn('smtp', options)
        self.assertEqual([first[k] for k in ('admin_password', 'admin_passwd')], [second[k] for k in ('admin_password', 'admin_passwd')])
        self.assertNotEqual(first['admin_password'], first['admin_passwd'])
        self.assertEqual((len(second['short']), len(second['long'])), (12, 40))
    def test_a_shared_password_fits_both_versions_length_ranges(self):
        old, new = {'options': {}, 'schema': {'pw': 'password(,20)'}}, {'options': {}, 'schema': {'pw': 'password(10,40)'}}
        (o, n), generated = rt.build_test_options([old, new], None)
        self.assertEqual((len(o['pw']), o['pw']), (20, n['pw']))
        self.assertEqual(rt.password_length('pw', ['password(40,)', 'password']), 40)
        with self.assertRaisesRegex(ValueError, r"'pw' needs a generated value, but its length ranges \(password\(,8\), password\(10,\)\) do not overlap"):
            rt.build_test_options([{'schema': {'pw': 'password(,8)'}}, {'schema': {'pw': 'password(10,)'}}], None)
        # A version that gets the password from the repository does not constrain the generated one.
        (o, n), generated = rt.build_test_options([{'schema': {'pw': 'password(,8)'}}, {'schema': {'pw': 'password(10,)'}}], {'pw': 'given-by-repo'})
        self.assertEqual((o['pw'], n['pw'], generated), ('given-by-repo', 'given-by-repo', {}))
    def test_a_password_one_version_requires_reaches_every_version_that_keeps_the_option(self):
        # A real upgrade keeps the user's value, so the version that has the option as password?, as another type,
        # or with no schema gets the same value too (replacing its own default); one whose schema lacks it does not.
        old = {'options': {'pw': '', 'n': {'pw': None}}, 'schema': {'pw': 'password', 'n': {'pw': 'password'}}}
        for schema in ({'pw': 'password(,20)?', 'n': {'pw': 'password?'}}, {'pw': 'str', 'n': {'pw': 'str?'}}, False):
            with self.subTest(schema):
                new = {'options': {'pw': 'new-default'}, 'schema': schema}
                (o, n), generated = rt.build_test_options([old, new], None)
                self.assertEqual(sorted(generated), ['n.pw', 'pw'])
                self.assertEqual((n['pw'], n['n']['pw']), (o['pw'], o['n']['pw'])); self.assertEqual(n['pw'], generated['pw'])
                # The optional password's range binds the shared value too.
                self.assertEqual(len(o['pw']), 20 if schema and schema['pw'].startswith('password(') else 32)
        (o, n), generated = rt.build_test_options([old, {'options': {}, 'schema': {'other': 'str?', 'n': 'str?'}}], None)
        self.assertEqual(n, {}); self.assertEqual(o['pw'], generated['pw'])
        # The new version requires it and the comparison target has it as password?: the target gets it too.
        (o, n), generated = rt.build_test_options([{'options': {}, 'schema': {'pw': 'password?'}}, {'options': {}, 'schema': {'pw': 'password'}}], None)
        self.assertEqual(o, n); self.assertEqual(o, {'pw': generated['pw']})
    def test_a_repo_password_is_kept_and_nested_passwords_are_generated(self):
        config = {'options': {'pw': '', 'db': {'pw': None, 'host': 'h'}, 'users': [{'name': 'a'}]},
            'schema': {'pw': 'password', 'db': {'pw': 'password', 'host': 'str'}, 'users': [{'name': 'str', 'pw': 'password'}],
                'auth': {'secret': 'password', 'realm': 'str?'}}}
        options, generated = self.build(config, {'pw': 'from-repo'})
        self.assertEqual(options['pw'], 'from-repo'); self.assertEqual(sorted(generated), ['auth.secret', 'db.pw'])
        self.assertEqual(options['db']['pw'], generated['db.pw']); self.assertEqual(options['users'], [{'name': 'a'}])
        # A required nested mapping the options lack is created for its password.
        self.assertEqual(options['auth'], {'secret': generated['auth.secret']})
    def test_options_yaml_is_read_and_must_be_a_mapping(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d, True)
        self.assertIsNone(rt.read_test_options(d))
        for text, expected in (('', {}), ('a: 1\nb: [x]\n', {'a': 1, 'b': ['x']})):
            (d / 'options.yaml').write_text(text, encoding='utf-8'); self.assertEqual(rt.read_test_options(d), expected)
        for text, message in (('- secret-one\n', 'must be a mapping of option: value .as in config.yaml options., not a list'),
                ('pw: [secret-two\n', 'is not valid YAML at line 2, column 1'),
                ('1: secret-three\n', 'must be a mapping of option: value; a key is a int, not a name'), ('secret-four\n', 'must be a mapping')):
            (d / 'options.yaml').write_text(text, encoding='utf-8')
            with self.subTest(text):
                with self.assertRaisesRegex(ValueError, 'upgrade-check/options.yaml ' + message) as caught:rt.read_test_options(d)
                # The file may hold passwords: the error never quotes it.
                self.assertNotIn('secret', str(caught.exception))
    def test_an_options_yaml_linked_out_of_upgrade_check_is_refused(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d, True)
        (d / 'hooks').mkdir(); (d / 'elsewhere.yaml').write_text('a: 1\n', encoding='utf-8'); (d / 'hooks/inside.yaml').write_text('b: 2\n', encoding='utf-8')
        try:(d / 'hooks/options.yaml').symlink_to(d / 'elsewhere.yaml')
        except OSError:self.skipTest('this account cannot create symlinks (Windows without developer mode)')
        with self.assertRaisesRegex(ValueError, 'upgrade-check/options.yaml is a symlink to .*, outside upgrade-check/'):rt.read_test_options(d / 'hooks')
        (d / 'hooks/options.yaml').unlink(); (d / 'hooks/options.yaml').symlink_to(d / 'hooks/inside.yaml')
        self.assertEqual(rt.read_test_options(d / 'hooks'), {'b': 2})
    def test_a_malformed_options_yaml_is_a_tool_error_before_docker(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d, True)
        (d / 'addon/upgrade-check').mkdir(parents=True); (d / 'addon/upgrade-check/options.yaml').write_text('- a\n', encoding='utf-8')
        cfg = d / 'config.yaml'; cfg.write_text('slug: fake\nversion: 1.0.0\n', encoding='utf-8')
        args = ['--name', 'fake', '--addon-dir', str(d / 'addon'), '--report-dir', str(d / 'reports'),
            '--old-image', 'x', '--old-config', str(cfg), '--new-image', 'y', '--new-config', str(cfg)]
        with mock.patch.object(rt, 'docker', side_effect=AssertionError('docker was called')), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(rt.main(args), 2)
        result = json.loads((d / 'reports/fake.json').read_text(encoding='utf-8'))
        self.assertIn('the upgrade test could not run: upgrade-check/options.yaml must be a mapping of option: value', result['reason'])
        self.assertIn('::error title=Upgrade test::fake: the upgrade test could not run: upgrade-check/options.yaml', out.getvalue())
    def test_an_error_holding_a_password_is_masked_and_keeps_its_kind(self):
        d = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d, True)
        (d / 'upgrade-check').mkdir(); (d / 'upgrade-check/options.yaml').write_text('pw: repo-secret-1\n', encoding='utf-8')
        config = {'version': '1', 'schema': {'pw': 'password'}}
        def run(error):
            class Env:
                def __init__(self, *a):pass
                def open(self):raise error
                def close(self):pass
            with mock.patch.object(rt, 'UpgradeTestEnv', Env):rt.upgrade_test('fake', d, 'x', config, 'y', config, d / 'work')
        # A tool error stays one (main(): could not run, exit 2), masked.
        with self.assertRaises(RuntimeError) as caught:run(OSError('docker run failed: pw=repo-secret-1'))
        self.assertEqual(str(caught.exception), 'docker run failed: pw=[password]')
        # A bug is not turned into a tool error: it still crashes, masked, naming its type, with its traceback.
        # (Not assertRaises: it drops the traceback.)
        try:run(KeyError('repo-secret-1')); self.fail('no exception')
        except rt.MaskedError as e:bug = e
        self.assertNotIsInstance(bug, rt.TOOL_ERRORS); self.assertEqual(str(bug), "KeyError: '[password]'"); self.assertIsNone(bug.__cause__)
        self.assertIn('open', [f.name for f in traceback.extract_tb(bug.__traceback__)])
        # Without a password in it, an error is raised as it is.
        with self.assertRaises(KeyError):run(KeyError('other'))
    def test_generated_and_repo_passwords_are_masked_but_not_defaults_or_names(self):
        config = {'schema': {'pw': 'password', 'opt': 'password?', 'list': ['password'], 'name': 'str'}}
        given = {'opt': 'q"uoted-secret', 'list': ['listed-secret'], 'name': 'visible-name'}
        words = rt.mask_words({'pw': 'generated-secret-1'}, given, [config])
        self.assertEqual(set(words), {'generated-secret-1', 'listed-secret', 'q"uoted-secret', r'q\"uoted-secret'})
        self.assertEqual(rt.mask_words({}, None, [config]), []); self.assertEqual(rt.mask('x', []), 'x')
        # A secret under an option typed str, but named like one, is masked too; other str values and non-strings are not.
        named = {'schema': {'api_token': 'str', 'db': {'db_password': 'str?', 'host': 'str'}, 'use_auth_token': 'bool', 'name': 'str'}}
        given = {'api_token': 'token-under-str', 'db': {'db_password': 'nested-db-secret', 'host': 'db.local'}, 'use_auth_token': True, 'name': 'shown'}
        self.assertEqual(set(rt.mask_words({}, given, [named])), {'token-under-str', 'nested-db-secret'})
        # A version without a schema has no types: names alone decide, so its options.yaml secrets are masked as well.
        self.assertEqual(set(rt.mask_words({}, {'admin_password': 'no-schema-secret', 'level': 'info'}, [{'schema': False}])),
            {'no-schema-secret'})
        masked = rt.mask({'a': ['x generated-secret-1 y', {'b': 'listed-secret abc visible-name'}], 'log': '{"pw": "q\\"uoted-secret"}', 'n': 3}, words)
        self.assertEqual(masked, {'a': [f'x {rt.MASK} y', {'b': f'{rt.MASK} abc visible-name'}], 'log': f'{{"pw": "{rt.MASK}"}}', 'n': 3})
        # The add-on's name and each version's image and version stay as they are.
        result = {'name': 'my-secret-addon', 'reason': 'secret', 'phases': [{'image': 'img:secret', 'version': 'secret', 'detail': 'secret'}]}
        self.assertEqual(rt.mask_result(result, ['secret']), {'name': 'my-secret-addon', 'reason': rt.MASK,
            'phases': [{'image': 'img:secret', 'version': 'secret', 'detail': rt.MASK}]})
    def test_weak_or_colliding_repo_passwords_are_warned_about_without_their_value(self):
        config = {'name': 'Fake Addon', 'slug': 'fake', 'version': '1.0.0', 'schema': {'a': 'password', 'b': 'password?', 'c': 'password', 'd': 'str'}}
        warnings = rt.option_warnings({'a': 'short', 'b': 'Addon-and-more'[:5], 'c': 'long-and-test-only', 'd': 'x'}, [config], ['local/fake:1'])
        self.assertEqual(warnings, ['the password `a` is shorter than 8 characters; it is masked wherever it appears, so pick a longer, test-only value',
            'the password `b` is shorter than 8 characters; it is masked wherever it appears, so pick a longer, test-only value'])
        self.assertEqual(rt.option_warnings({'c': 'local/fake:1'}, [config], ['local/fake:1']),
            ["the password `c` appears in the add-on's name, slug, image or version; it is masked wherever it appears, so pick a longer, test-only value"])
        self.assertEqual(rt.option_warnings({'c': 'long-and-test-only'}, [config], ['img']), [])
        named = {'name': 'Fake Addon', 'slug': 'fake', 'version': '1.0.0', 'schema': {'api_key': 'str'}}
        self.assertEqual(rt.option_warnings({'api_key': 'short'}, [named], ['img']),
            ['the password `api_key` is shorter than 8 characters; it is masked wherever it appears, so pick a longer, test-only value'])

class ImageFault(unittest.TestCase):
    """#140: which failed `docker run` is the image's fault (the version did not start) and which the test's (a tool error)."""
    def test_classification(self):
        cases = [(125, "Unable to find image 'local/x:1' locally\ndocker: Error response from daemon: pull access denied for local/x", True),
            (125, 'docker: Error response from daemon: manifest unknown: manifest unknown', True),
            (125, 'docker: Error response from daemon: failed to resolve reference "ghcr.io/o/x:1": not found', True),
            (127, 'docker: Error response from daemon: failed to create task for container: ... exec: "/nope": stat /nope: no such file or directory', True),
            (126, 'exec: "/run": permission denied', True),
            (125, 'docker: Error response from daemon: Conflict. The container name "/upgrade-test-1-old" is already in use', False),
            (125, 'docker: Error response from daemon: Address already in use', False),
            (125, 'docker: Error response from daemon: invalid mount config for type "bind": bind source path does not exist: /w/x', False),
            (125, 'docker: Error response from daemon: Invalid address 10.255.0.10: It does not belong to any of this network\'s subnets', False),
            (1, 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?', False)]
        for code, output, fault in cases:
            with self.subTest(output):self.assertEqual(rt.image_fault(rt.DockerError('docker run failed', code, output)), fault)

class Fixtures(unittest.TestCase):
    """upgrade-check/supervisor/ checks and map warnings that need no Docker (#142)."""
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.dir, True)
        self.hooks = self.dir / 'addon/upgrade-check'; self.hooks.mkdir(parents=True)
    def link(self, path, target, **kw):
        try:path.symlink_to(target, **kw)
        except OSError:self.skipTest('this account cannot create symlinks (Windows without developer mode)')
    def test_fixtures_inside_upgrade_check_are_fine(self):
        self.assertEqual(rt.fixtures_problem(self.hooks), '')
        (self.hooks / 'supervisor/services').mkdir(parents=True); (self.hooks / 'shared.json').write_text('{}', encoding='utf-8')
        self.link(self.hooks / 'supervisor/services/mqtt.json', self.hooks / 'shared.json')
        self.assertEqual(rt.fixtures_problem(self.hooks), '')
    def test_a_fixtures_directory_linked_out_of_upgrade_check_is_a_tool_error_before_any_container(self):
        outside = self.dir / 'elsewhere'; outside.mkdir()
        self.link(self.hooks / 'supervisor', outside, target_is_directory=True)
        self.assertIn('upgrade-check/supervisor is a symlink to', rt.fixtures_problem(self.hooks))
        # main() reports it as a tool error and never reaches Docker.
        cfg = self.dir / 'config.yaml'; cfg.write_text('slug: fake\nversion: 1.0.0\n', encoding='utf-8')
        args = ['--name', 'fake', '--addon-dir', str(self.dir / 'addon'), '--report-dir', str(self.dir / 'reports'),
            '--old-image', 'x', '--old-config', str(cfg), '--new-image', 'y', '--new-config', str(cfg)]
        with mock.patch.object(rt, 'docker', side_effect=AssertionError('docker was called')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(rt.main(args), 2)
        result = json.loads((self.dir / 'reports/fake.json').read_text(encoding='utf-8'))
        self.assertIn('could not run: upgrade-check/supervisor is a symlink to', result['reason']); self.assertIn('outside upgrade-check/', result['reason'])
    def test_a_fixture_file_linked_out_of_upgrade_check_is_named(self):
        (self.hooks / 'supervisor').mkdir(); outside = self.dir / 'mqtt.json'; outside.write_text('{}', encoding='utf-8')
        self.link(self.hooks / 'supervisor/mqtt.json', outside)
        self.assertIn('upgrade-check/supervisor/mqtt.json is a symlink to', rt.fixtures_problem(self.hooks))
    def test_map_warnings_never_raise(self):
        self.assertEqual(rt._map_warnings({'map': ['config:rw', 'addon_config']}),
            ["map entry 'addon_config' is ignored because 'config' is present (as Supervisor does)"])
        with mock.patch.object(rt, 'map_warnings', side_effect=ValueError('bad map')):
            self.assertEqual(rt._map_warnings({}), ['map could not be read: bad map'])

class Report(unittest.TestCase):
    """report()'s informational sections (#142), without Docker."""
    def result(self, **extra):
        phases = [{'phase': ph, 'version': v, 'image': 'img', 'method': 'stays-up', 'started': True, 'detail': 'ok', 'answer': '', 'logs': '',
            'hooks': [], 'supervisor': {'unmocked': [], 'broken_fixtures': []}} for ph, v in (('old', '1.0.0'), ('new', '1.1.0'))]
        return {'name': 'fake', 'passed': True, 'reason': '', 'hooks': [], 'data_checked': False, 'phases': phases, **extra}
    def test_map_warnings_that_differ_name_the_version(self):
        text = rt.report(self.result(map_warnings={'old': ['old one'], 'new': ['new one']}))
        self.assertIn('- the new version: new one', text); self.assertIn('- the comparison target: old one', text)
        text = rt.report(self.result(map_warnings={'old': [], 'new': ['new one']}))
        self.assertIn('- the new version: new one', text); self.assertNotIn('comparison target:', text)
    def test_a_result_without_the_new_keys_still_reports(self):
        # A tool error's result, or one from before #142, has no supervisor or map_warnings.
        r = self.result(); [p.pop('supervisor') for p in r['phases']]
        self.assertNotIn('Unmocked', rt.report(r)); self.assertNotIn('Map entries', rt.report(r)); self.assertNotIn('Test options', rt.report(r))
        self.assertNotIn('Supervisor settings not applied', rt.report(r))
    def test_unapplied_settings_are_listed_per_version(self):
        # #181: each version lists its own; the same list on both is written once; none: no section.
        title = '**Supervisor settings not applied (未套用的 Supervisor 設定)**'
        text = rt.report(self.result(unapplied_settings={'old': ['usb: true'], 'new': ['usb: true', 'video: true']}))
        self.assertIn(title, text); self.assertIn('do not add skip_upgrade_test', text); self.assertIn('不加 skip_upgrade_test', text)
        self.assertIn('- the new version: `usb: true`\n- the new version: `video: true`\n- the comparison target: `usb: true`', text)
        text = rt.report(self.result(unapplied_settings={'old': [], 'new': ['apparmor: custom profile apparmor.txt']}))
        self.assertIn('- the new version: `apparmor: custom profile apparmor.txt`', text); self.assertNotIn('comparison target:', text)
        text = rt.report(self.result(unapplied_settings={'old': ['host_dbus: true'], 'new': ['host_dbus: true']}))
        self.assertIn('- both versions: `host_dbus: true`', text); self.assertEqual(text.count('host_dbus'), 1)
        self.assertNotIn('the new version:', text)
        for empty in ({'old': [], 'new': []}, None):
            with self.subTest(empty):self.assertNotIn('Supervisor settings not applied', rt.report(self.result(unapplied_settings=empty)))
        # A backquote from config.yaml cannot end the code span; a | cannot break the line.
        text = rt.report(self.result(unapplied_settings={'old': [], 'new': ['tmpfs: "a`b|c"']}))
        self.assertIn('- the new version: `tmpfs: "a\'b\\|c"`', text)
    def test_unapplied_settings_never_change_the_result_or_exit_code(self):
        # #181: main() exits as the result says, and the step summary has the section.
        work = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, work, True)
        for side in ('old', 'new'):(work / f'{side}.yaml').write_text('slug: fake\nversion: 1.0.0\nusb: true\n', encoding='utf-8')
        args = ['--name', 'fake', '--addon-dir', str(work), '--report-dir', str(work / 'reports'), '--summary', str(work / 'summary.md'),
            '--old-image', 'old:1', '--old-config', str(work / 'old.yaml'), '--new-image', 'new:1', '--new-config', str(work / 'new.yaml')]
        for passed, code in ((True, 0), (False, 1)):
            with self.subTest(passed=passed):
                r = self.result(passed=passed, reason='' if passed else 'it did not start', unapplied_settings={'old': ['usb: true'], 'new': ['usb: true']})
                with mock.patch.object(rt, 'upgrade_test', return_value=r), mock.patch.object(rt, 'compare_smoke', side_effect=lambda x: x), \
                        contextlib.redirect_stdout(io.StringIO()):self.assertEqual(rt.main(args), code)
                self.assertEqual(json.loads((work / 'reports/fake.json').read_text(encoding='utf-8'))['passed'], passed)
        self.assertEqual((work / 'summary.md').read_text(encoding='utf-8').count('Supervisor settings not applied'), 2)
    def test_test_options_are_named_without_values(self):
        text = rt.report(self.result(options={'from_repo': ['a|b'], 'generated': ['db.pw']}))
        self.assertIn(r'Test options (測試用的 options): upgrade-check/options.yaml sets `a\|b`; random passwords for `db.pw` (the same on both versions).', text)
        self.assertIn('random passwords for `x`', rt.report(self.result(options={'from_repo': [], 'generated': ['x']})))
        text = rt.report(self.result(options={'from_repo': ['a'], 'generated': [], 'warnings': ['the password `a` is short']}))
        self.assertIn('- **Warning**: the password `a` is short.', text)
    def test_the_unmocked_table_lists_the_most_called_paths_per_version(self):
        r = self.result()
        r['phases'][0]['supervisor']['unmocked'] = [{'path': f'/p{i:02}', 'count': i, 'methods': ['GET']} for i in range(1, 36)]
        r['phases'][1]['supervisor']['unmocked'] = [{'path': '/only', 'count': 1, 'methods': ['GET']}]
        text = rt.report(r)
        self.assertIn('| the comparison target 1.0.0 | `/p35` | 35 | GET |', text); self.assertIn('| the comparison target 1.0.0 | `/p06` | 6 | GET |', text)
        self.assertNotIn('`/p05`', text); self.assertIn('| the comparison target 1.0.0 | … and 5 more paths | | |', text)
        self.assertIn('| the new version 1.1.0 | `/only` | 1 | GET |', text); self.assertEqual(text.count('more paths'), 1)
        # The most called first.
        self.assertLess(text.index('`/p35`'), text.index('`/p34`'))
    def test_unmocked_calls_of_one_version_only(self):
        r = self.result(); r['phases'][1]['supervisor']['unmocked'] = [{'path': '/a|b', 'count': 3, 'methods': ['GET', 'POST']}]
        text = rt.report(r)
        self.assertIn(r'| the new version 1.1.0 | `/a\|b` | 3 | GET, POST |', text); self.assertEqual(text.count('`/a'), 1)

if __name__ == '__main__':
    unittest.main()
