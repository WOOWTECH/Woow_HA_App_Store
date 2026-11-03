"""The upgrade test's runtime entry (pipeline #137) against tiny fake add-ons on real Docker, no mocks.

Each fake add-on asks the mock Supervisor for its own info with its token (a wrong answer exits), reads
/data/options.json and counts its starts in /data. Needs a Docker daemon (GitHub runners have one)."""
import contextlib, io, json, pathlib, shutil, subprocess, tempfile, unittest, uuid
import yaml
import upgrade_runtime as rt

FAKE = r'''
import json, os, sys, time, urllib.request, http.server
req = urllib.request.Request('http://supervisor/addons/self/info', headers={'Authorization': 'Bearer ' + os.environ['SUPERVISOR_TOKEN']})
info = json.load(urllib.request.urlopen(req, timeout=10))['data']
assert info['slug'] == 'fake', info
options = json.load(open('/data/options.json'))
assert options['greeting'] == 'hi', options
starts = int(open('/data/starts').read()) + 1 if os.path.exists('/data/starts') else 1
open('/data/starts', 'w').write(str(starts))
print('started', starts, flush=True)
if os.environ['MODE'] == 'crash':
    time.sleep(2); sys.exit(3)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == '/health' else 404); self.end_headers(); self.wfile.write(str(starts).encode())
server = http.server.HTTPServer(('0.0.0.0', 8080), H)
if os.environ['MODE'] == 'answer-then-crash':
    # Answers its watchdog at once, then dies: a version that only looks started.
    import threading; threading.Thread(target=server.serve_forever, daemon=True).start(); time.sleep(4); os._exit(4)
server.serve_forever()
'''

def docker_ok():
    try:return subprocess.run(['docker', 'info'], capture_output=True).returncode == 0
    except OSError:return False

@unittest.skipUnless(docker_ok(), 'needs a Docker daemon (present on GitHub runners)')
class Runtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = {}
        build = pathlib.Path(tempfile.mkdtemp())
        try:
            (build / 'run.py').write_text(FAKE, encoding='utf-8')
            for mode in ('good', 'crash', 'answer-then-crash'):
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
    def test_settings_that_are_not_a_mapping_fail_with_the_reason(self):
        (self.dir / 'addon/upgrade-check').mkdir()
        (self.dir / 'addon/upgrade-check/settings.yaml').write_text('- 5\n', encoding='utf-8')
        code, result, out = self.run_test('good', 'good')
        self.assertEqual(code, 2); self.assertIn('could not run: settings must be a mapping', result['reason'])

if __name__ == '__main__':
    unittest.main()
