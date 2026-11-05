"""Tests of the mock Supervisor's fixtures and its record of unmocked calls (pipeline #142).

The mock runs as a real local HTTP server (`mock_supervisor.py serve` on a free
port), no Docker. Calls come from 127.0.0.2, as an add-on's would come from its
own address: the mock leaves calls from 127.0.0.1 out of its log.
"""
import contextlib, http.client, json, os, pathlib, socket, subprocess, sys, tempfile, time, unittest
import mock_supervisor as m

TOOL = pathlib.Path(__file__).resolve().parent / 'mock_supervisor.py'
TOKEN = 'test-token'
ADDON = {'name': 'Test', 'slug': 'test_addon', 'version': '1.0.0', 'options': {'level': 'info'}}

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]

class Mock:
    """`serve` in a subprocess on a temporary state directory (and fixtures, when given {relative path: data or raw text})."""
    def __init__(self, fixtures=None):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix='mock-supervisor-'))
        self.state = self.dir / 'state'; self.state.mkdir()
        (self.state / 'addon.json').write_text(json.dumps(ADDON), encoding='utf-8')
        args = []
        if fixtures is not None:
            root = self.dir / 'supervisor'; root.mkdir()
            for rel, data in fixtures.items():
                f = root / rel; f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')
            args = ['--fixtures', str(root)]
        self.port = free_port()
        self.proc = subprocess.Popen([sys.executable, str(TOOL), 'serve', '--state', str(self.state), '--port', str(self.port), *args],
            env={**os.environ, 'SUPERVISOR_TOKEN': TOKEN}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 15
        while True:
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=1):break
            except OSError:
                if self.proc.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f'the mock did not start: {self.proc.stderr.read().decode(errors="replace")}')
                time.sleep(0.1)
    def call(self, path, method='GET', source='127.0.0.2', token=TOKEN):
        """(status, decoded body; None for HEAD)."""
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5, source_address=(source, 0))
        try:
            c.request(method, path, headers={'Authorization': f'Bearer {token}'})
            r = c.getresponse(); raw = r.read(); return r.status, json.loads(raw) if method != 'HEAD' else None
        finally:
            c.close()
    def summary(self):
        return m.summary(self.state)
    def close(self):
        self.proc.terminate(); self.proc.wait(10); self.proc.stderr.close()
        for f in sorted(self.dir.rglob('*'), reverse=True):
            f.rmdir() if f.is_dir() else f.unlink()
        self.dir.rmdir()

class Tests(unittest.TestCase):
    def mock(self, fixtures=None):
        mock = Mock(fixtures); self.addCleanup(mock.close); return mock

    def test_without_fixtures_the_defaults_answer_and_nothing_is_unmocked(self):
        mock = self.mock()
        self.assertEqual(mock.call('/addons/self/info'), (200, {'result': 'ok', 'data': ADDON}))
        self.assertEqual(mock.call('/addons/test_addon/info')[1]['data'], ADDON)
        self.assertEqual(mock.call('/addons/self/options/config')[1]['data'], {'level': 'info'})
        self.assertEqual(mock.call('/info/')[1]['data'], m._info())
        self.assertEqual(mock.call('/core/info?x=1')[1]['data'], m._core_info())
        self.assertEqual(mock.call('/supervisor/ping'), (200, {'result': 'ok', 'data': {}}))
        self.assertEqual(mock.summary(), {'unmocked': [], 'broken_fixtures': []})

    def test_a_fixture_beats_the_default_answer(self):
        mock = self.mock({'info.json': {'supervisor': 'fixture'}, 'addons/self/stats.json': {'cpu_percent': 99}})
        self.assertEqual(mock.call('/info'), (200, {'result': 'ok', 'data': {'supervisor': 'fixture'}}))
        self.assertEqual(mock.call('/addons/self/stats')[1]['data'], {'cpu_percent': 99})
        # The add-on's own slug reads the self fixture too.
        self.assertEqual(mock.call('/addons/test_addon/stats/')[1]['data'], {'cpu_percent': 99})
        # Paths without a fixture keep their default.
        self.assertEqual(mock.call('/os/info')[1]['data'], m._os_info())

    def test_an_info_fixture_is_laid_over_the_runtime_info_on_every_alias(self):
        # The runtime writes version, options and ingress_port per version: the fixture must not wipe them.
        mock = self.mock({'addons/self/info.json': {'hostname': 'from-fixture', 'version': '9.9.9'}})
        expected = {**ADDON, 'hostname': 'from-fixture', 'version': '9.9.9'}
        for path in ('/addons/self/info', '/addons/self/info/', '/addons/self', '/addons/test_addon/info', '/addons/test_addon'):
            self.assertEqual(mock.call(path), (200, {'result': 'ok', 'data': expected}), path)
        # Another add-on's info is not the add-on's own.
        self.assertEqual(mock.call('/addons/other/info')[0], 404)

    def test_an_info_fixture_that_is_not_an_object_is_broken(self):
        mock = self.mock({'addons/self/info.json': ['a', 'list']})
        self.assertEqual(mock.call('/addons/self')[0], 500)
        self.assertEqual(mock.summary()['broken_fixtures'], [{'path': '/addons/self', 'count': 1, 'methods': ['GET']}])

    def test_ping_answers_itself_whatever_the_fixtures(self):
        # The runtime's readiness check (from 127.0.0.1) must not break on a repo's supervisor/ping.json.
        mock = self.mock({'supervisor/ping.json': '{broken'})
        for source in ('127.0.0.1', '127.0.0.2'):
            self.assertEqual(mock.call('/supervisor/ping', source=source), (200, {'result': 'ok', 'data': {}}))

    def test_every_method_is_answered_and_logged(self):
        mock = self.mock({'services/mqtt.json': {'host': 'x'}})
        self.assertEqual(mock.call('/services/mqtt', method='PATCH')[1]['data'], {'host': 'x'})
        self.assertEqual(mock.call('/services/mqtt', method='HEAD'), (200, None))
        self.assertEqual(mock.call('/nope', method='PATCH')[0], 404); self.assertEqual(mock.call('/nope', method='HEAD')[0], 404)
        self.assertEqual(mock.call('/nope', method='OPTIONS')[0], 404)
        self.assertEqual(mock.summary()['unmocked'], [{'path': '/nope', 'count': 3, 'methods': ['HEAD', 'OPTIONS', 'PATCH']}])

    def test_a_fixture_answers_a_path_the_mock_does_not_know(self):
        mqtt = {'host': 'core-mosquitto', 'port': 1883, 'ssl': False, 'protocol': '3.1.1', 'username': 'addons', 'password': 'pw'}
        mock = self.mock({'services/mqtt.json': mqtt})
        self.assertEqual(mock.call('/services/mqtt'), (200, {'result': 'ok', 'data': mqtt}))
        self.assertEqual(mock.call('/services/mqtt', method='POST')[1]['data'], mqtt)
        self.assertEqual(mock.summary()['unmocked'], [])

    def test_a_missing_path_is_404_and_summarized_with_its_count(self):
        mock = self.mock({'services/mqtt.json': {}})
        for path in ('/services/mysql', '/services/mysql/', '/services/mysql?x=1'):
            status, body = mock.call(path)
            self.assertEqual((status, body['result']), (404, 'error')); self.assertIn('not mocked', body['message'])
        mock.call('/hardware/info', method='POST')
        # The runtime's own checks from 127.0.0.1 are not the add-on's calls.
        mock.call('/hardware/info', source='127.0.0.1')
        self.assertEqual(mock.summary(), {'unmocked': [{'path': '/hardware/info', 'count': 1, 'methods': ['POST']},
            {'path': '/services/mysql', 'count': 3, 'methods': ['GET']}], 'broken_fixtures': []})
        # requests.log keeps its format: one "METHOD PATH STATUS" line per logged call.
        self.assertEqual((mock.state / 'requests.log').read_text(encoding='utf-8').splitlines(),
            ['GET /services/mysql 404', 'GET /services/mysql/ 404', 'GET /services/mysql?x=1 404', 'POST /hardware/info 404'])

    def test_summary_after_a_log_size_covers_the_later_calls_only(self):
        # The runtime keeps one requests.log for both versions and summarizes each from where its phase began.
        mock = self.mock()
        mock.call('/services/mysql'); start = m.log_size(mock.state)
        mock.call('/services/mysql'); mock.call('/hardware/info')
        self.assertEqual(m.summary(mock.state, start)['unmocked'], [{'path': '/hardware/info', 'count': 1, 'methods': ['GET']},
            {'path': '/services/mysql', 'count': 1, 'methods': ['GET']}])
        self.assertEqual(m.summary(mock.state)['unmocked'][1]['count'], 2)
        self.assertEqual(m.log_size(mock.state / 'nowhere'), 0)

    def test_a_broken_fixture_is_500_and_summarized(self):
        mock = self.mock({'services/mqtt.json': '{not json'})
        status, body = mock.call('/services/mqtt')
        self.assertEqual(status, 500); self.assertIn('not usable JSON', body['message'])
        self.assertEqual(mock.summary(), {'unmocked': [], 'broken_fixtures': [{'path': '/services/mqtt', 'count': 1, 'methods': ['GET']}]})

    def test_paths_cannot_reach_outside_the_fixtures(self):
        mock = self.mock({'info.json': {}})
        (mock.dir / 'secret.json').write_text('{"leak": true}', encoding='utf-8')
        for path in ('/../secret', '/%2e%2e/secret', '/.hidden'):
            self.assertEqual(mock.call(path)[0], 404, path)

    def test_without_the_token_nothing_is_answered(self):
        mock = self.mock({'services/mqtt.json': {}})
        self.assertEqual(mock.call('/services/mqtt', token='wrong')[0], 401)
        self.assertEqual(mock.summary()['unmocked'], [])

    def test_summary_without_a_log_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(m.summary(d), {'unmocked': [], 'broken_fixtures': []})

    def test_fixture_file_mapping(self):
        with contextlib.ExitStack() as stack:
            stack.callback(setattr, m, 'FIXTURES', m.FIXTURES)
            m.FIXTURES = pathlib.Path('/fx')
            f = lambda p, slug=None: m.fixture_file(m.canonical(p, slug))
            self.assertEqual(f('/services/mqtt'), pathlib.Path('/fx/services/mqtt.json'))
            self.assertEqual(f('/addons/self/info/?a=b'), pathlib.Path('/fx/addons/self/info.json'))
            self.assertEqual(f('/addons/self'), pathlib.Path('/fx/addons/self/info.json'))
            self.assertEqual(f('/addons/abc', 'abc'), pathlib.Path('/fx/addons/self/info.json'))
            self.assertEqual(f('/addons/abc/stats', 'abc'), pathlib.Path('/fx/addons/self/stats.json'))
            self.assertEqual(f('/addons/abcd/stats', 'abc'), pathlib.Path('/fx/addons/abcd/stats.json'))
            self.assertEqual(f('/addons/other/info', 'abc'), pathlib.Path('/fx/addons/other/info.json'))
            for bad in ('/', '/a/../b', '/a/%2e', '/a b', '/supervisor/ping'):
                self.assertIsNone(f(bad), bad)
            m.FIXTURES = None
            self.assertIsNone(f('/services/mqtt'))

if __name__ == '__main__':
    unittest.main()
