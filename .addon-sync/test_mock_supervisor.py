"""Tests of the mock Supervisor's fixtures and its record of unmocked calls (pipeline #142).

The mock runs as a real local HTTP server (`mock_supervisor.py serve` on a free
port), no Docker. Calls come from 127.0.0.2, as an add-on's would come from its
own address: the mock leaves calls from 127.0.0.1 out of its log.
"""
import base64, contextlib, hashlib, http.client, http.server, json, os, pathlib, socket, subprocess, sys, tempfile, threading, time, unittest
import urllib.request
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
    def raw(self, path, method='GET', headers=None, body=None, source='127.0.0.2'):
        """(status, response headers, body bytes) of one call with exactly these request headers."""
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10, source_address=(source, 0))
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse(); return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
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

    def test_dns_info_answers_with_the_docker_network_dns_address(self):
        # #163: bashio::dns.host (nginxpm's init-nginx) reads /dns/info; a 404 stopped the add-on.
        mock = self.mock()
        status, body = mock.call('/dns/info')
        self.assertEqual((status, body['result']), (200, 'ok'))
        dns = body['data']
        network = mock.call('/network/info')[1]['data']
        self.assertEqual(dns['host'], network['docker']['dns'])
        self.assertEqual(dns['host'], '172.30.32.3')
        for key in ('version', 'version_latest', 'update_available', 'servers', 'locals', 'mdns', 'llmnr', 'fallback'):
            self.assertIn(key, dns)
        self.assertEqual(dns['locals'], [f'dns://{s}' for s in network['interfaces'][0]['ipv4']['nameservers']])
        self.assertEqual(mock.call('/dns/info/?x=1')[1]['data'], dns)
        self.assertEqual(mock.summary(), {'unmocked': [], 'broken_fixtures': []})

    def test_a_dns_info_fixture_beats_the_default(self):
        mock = self.mock({'dns/info.json': {'host': '172.30.32.99', 'servers': ['dns://1.1.1.1']}})
        self.assertEqual(mock.call('/dns/info'), (200, {'result': 'ok', 'data': {'host': '172.30.32.99', 'servers': ['dns://1.1.1.1']}}))
        self.assertEqual(mock.summary(), {'unmocked': [], 'broken_fixtures': []})

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

def wait_port(port, proc, what):
    deadline = time.monotonic() + 15
    while True:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):return
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:raise RuntimeError(f'{what} did not start')
            time.sleep(0.1)

def ws_open(port, path, source='127.0.0.2', headers=''):
    """A client websocket to the mock: (socket, reader, status line, response headers), the handshake checked here
    independently of the mock's own code."""
    s = socket.create_connection(('127.0.0.1', port), timeout=10, source_address=(source, 0))
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f'GET {path} HTTP/1.1\r\nHost: supervisor\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
        f'Sec-WebSocket-Version: 13\r\n{headers}\r\n').encode())
    reader = s.makefile('rb'); status = reader.readline().decode().strip(); answer = {}
    while True:
        line = reader.readline().decode().strip()
        if not line:break
        k, _, v = line.partition(':'); answer[k.strip().lower()] = v.strip()
    if status.split()[1] == '101':
        expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        assert answer['sec-websocket-accept'] == expected, answer
    return s, reader, status, answer

class HaCore(unittest.TestCase):
    """#174: a component the registry flags ha_core gets a real HA Core behind the mock (here the standard-library
    fake_ha_core.py, never the real image): core-setup onboards it, and the mock forwards /core/api... (REST and
    websocket) with the owner's token instead of the add-on's. Without core.json (no flag) nothing changes."""
    def fake_core(self, *args):
        """A fake HA Core on a free port: its URL."""
        port = free_port()
        proc = subprocess.Popen([sys.executable, str(TOOL.parent / 'fake_ha_core.py'), '--port', str(port), *args],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (proc.terminate(), proc.wait(10)))
        wait_port(port, proc, 'the fake HA Core'); return f'http://127.0.0.1:{port}'
    def flagged(self, *core_args, onboard=True):
        """(mock, HA Core url): the mock with core.json as the runtime writes it, onboarded by core-setup unless not."""
        url = self.fake_core(*core_args); mock = Mock(); self.addCleanup(mock.close)
        (mock.state / 'core.json').write_text(json.dumps({'url': url}), encoding='utf-8')
        if onboard:self.assertEqual(m.core_setup(url, mock.state, 20), '')
        return mock, url
    def seen(self, url):
        return json.loads(urllib.request.urlopen(url + '/fake/seen', timeout=5).read())

    def test_core_setup_onboards_the_owner_and_hands_it_to_the_mock(self):
        mock, url = self.flagged()
        core = json.loads((mock.state / 'core.json').read_text(encoding='utf-8'))
        self.assertEqual({k: v for k, v in core.items() if k != 'refresh_token'}, {'url': url, 'client_id': url + '/',
            'user_id': 'owner-0123456789abcdef', 'user_name': 'upgrade-test', 'display_name': 'upgrade-test'})
        self.assertEqual(core['refresh_token'], 'refresh-token-1')
        self.assertTrue(all(s['done'] for s in json.loads(urllib.request.urlopen(url + '/api/onboarding', timeout=5).read())))
        # A second core-setup finds HA Core already onboarded: its config directory was not fresh.
        self.assertIn('already has its owner', m.core_setup(url, mock.state, 5))

    def test_rest_calls_reach_ha_core_with_the_owner_token_never_the_add_ons(self):
        mock, url = self.flagged()
        status, headers, raw = mock.raw('/core/api/states?a=1', headers={'Authorization': f'Bearer {TOKEN}'})
        echo = json.loads(raw)
        self.assertEqual((status, echo['method'], echo['path'], echo['query']), (200, 'GET', '/api/states', 'a=1'))
        self.assertRegex(echo['authorization'], r'^Bearer access-token-\d+$')
        # X-Ha-Access works too; the body and its Content-Type reach HA Core under /homeassistant/ as well.
        status, headers, raw = mock.raw('/homeassistant/api/services/light/turn_on', 'POST', {'X-Ha-Access': TOKEN,
            'Content-Type': 'application/json'}, b'{"entity_id": "light.x"}')
        echo = json.loads(raw)
        self.assertEqual((status, echo['method'], echo['path'], echo['body'], echo['content_type']),
            (200, 'POST', '/api/services/light/turn_on', '{"entity_id": "light.x"}', 'application/json'))
        self.assertEqual(headers['content-type'], 'application/json')
        self.assertEqual(json.loads(mock.raw('/core/api/', headers={'Authorization': f'Bearer {TOKEN}'})[2]), {'message': 'API running.'})
        # /api/stream comes back as HA Core streams it.
        status, headers, raw = mock.raw('/core/api/stream', headers={'Authorization': f'Bearer {TOKEN}'})
        self.assertEqual((status, headers['content-type'], raw), (200, 'text/event-stream', b'data: one\n\ndata: two\n\n'))
        # HA Core never saw the add-on's token; every call it got carried one of its own access tokens.
        tokens = [t for _, t in self.seen(url)]
        self.assertNotIn(TOKEN, tokens); self.assertTrue(tokens) ; self.assertTrue(all(t.startswith('access-token-') for t in tokens), tokens)
        # Forwarded calls are logged, marked, and not counted as unmocked Supervisor calls.
        log = (mock.state / 'requests.log').read_text(encoding='utf-8').splitlines()
        self.assertEqual(log[0], 'GET /core/api/states?a=1 200 ha_core'); self.assertEqual(len(log), 4)
        self.assertEqual(mock.summary(), {'unmocked': [], 'broken_fixtures': []})

    def test_forwarded_rest_calls_need_the_add_ons_token(self):
        mock, url = self.flagged()
        for headers in ({}, {'Authorization': 'Bearer wrong'}, {'X-Ha-Access': 'wrong'}):
            with self.subTest(headers):self.assertEqual(mock.raw('/core/api/states', headers=headers)[0], 401)
        self.assertEqual(mock.raw('/core/api/states', 'PUT', {'Authorization': f'Bearer {TOKEN}'})[0], 405)
        self.assertEqual([t for t in self.seen(url) if t[0] == 'rest' and t[1] == TOKEN], [])

    def test_bare_core_without_a_token_answers_401_flagged_or_not(self):
        # music_assistant tells add-on mode by GET http://supervisor/core answering 401.
        flagged, _ = self.flagged(); plain = Mock(); self.addCleanup(plain.close)
        for mock in (flagged, plain):
            self.assertEqual(mock.raw('/core')[0], 401)
            self.assertEqual(mock.raw('/core', headers={'Authorization': f'Bearer {TOKEN}'})[0], 404)

    def test_unflagged_components_answer_404_on_the_core_api(self):
        mock = Mock(); self.addCleanup(mock.close)
        for path in ('/core/api/config', '/core/api/', '/homeassistant/api/states', '/core/api/stream'):
            with self.subTest(path):self.assertEqual(mock.call(path)[0], 404)
        s, reader, status, _ = ws_open(mock.port, '/core/websocket', headers=f'Authorization: Bearer {TOKEN}\r\n'); s.close()
        self.assertIn(' 404 ', status + ' ')
        self.assertEqual([r['path'] for r in mock.summary()['unmocked']], ['/core/api', '/core/api/config', '/core/api/stream', '/core/websocket',
            '/homeassistant/api/states'])

    def test_502_until_ha_core_is_onboarded_and_running(self):
        mock, url = self.flagged('--never-running', onboard=False)
        auth = {'Authorization': f'Bearer {TOKEN}'}
        self.assertEqual(mock.raw('/core/api/states', headers=auth)[0], 502)
        s, reader, status, _ = ws_open(mock.port, '/core/api/websocket'); s.close(); self.assertIn(' 502 ', status + ' ')
        # Onboarded, but HA Core stays STARTING: core-setup gives up after its time limit, with the reason.
        self.assertEqual(m.core_setup(url, mock.state, 2), 'HA Core did not reach RUNNING within 2 s (it is STARTING)')
        status, _, raw = mock.raw('/core/api/states', headers=auth)
        self.assertEqual(status, 502); self.assertIn('STARTING, not RUNNING yet', json.loads(raw)['message'])
        urllib.request.urlopen(urllib.request.Request(url + '/fake/running', method='POST'), timeout=5)
        self.assertEqual(mock.raw('/core/api/states', headers=auth)[0], 200)
        self.assertIn('GET /core/api/states 502 ha_core', (mock.state / 'requests.log').read_text(encoding='utf-8').splitlines())

    def test_core_setup_gives_up_when_ha_core_never_answers(self):
        with tempfile.TemporaryDirectory() as d:
            why = m.core_setup(f'http://127.0.0.1:{free_port()}', d, 2)
            self.assertTrue(why.startswith('HA Core did not answer /api/onboarding within 2 s'), why)
            self.assertFalse((pathlib.Path(d) / 'core.json').exists())
            # The command line: exit 1 with the reason.
            r = subprocess.run([sys.executable, str(TOOL), 'core-setup', '--core', f'http://127.0.0.1:{free_port()}', '--state', d, '--timeout', '1'],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 1); self.assertIn('did not answer /api/onboarding within 1', r.stderr)

    def test_websocket_logs_in_here_then_pipes_frames_to_ha_core(self):
        mock, url = self.flagged()
        for path in ('/core/websocket', '/core/api/websocket', '/homeassistant/websocket', '/homeassistant/api/websocket'):
            with self.subTest(path):
                # No token in the handshake (browser-style clients such as hamh's send none): the auth message decides.
                s, reader, status, headers = ws_open(mock.port, path)
                self.assertTrue(status.startswith('HTTP/1.1 101'), status)
                self.assertEqual((headers['upgrade'].lower(), headers['connection'].lower()), ('websocket', 'upgrade'))
                self.assertNotIn('sec-websocket-extensions', headers)
                send = s.sendall
                self.assertEqual(m.read_json(reader), {'type': 'auth_required', 'ha_version': m.VERSIONS['homeassistant']})
                m.send_json(send, {'type': 'auth', 'access_token': TOKEN}, True)
                self.assertEqual(m.read_json(reader), {'type': 'auth_ok', 'ha_version': m.VERSIONS['homeassistant']})
                m.send_json(send, {'id': 1, 'type': 'get_config'}, True)
                self.assertEqual(m.read_json(reader)['result']['state'], 'RUNNING')
                m.send_json(send, {'id': 2, 'type': 'config/auth/list'}, True)
                (owner,) = m.read_json(reader)['result']
                self.assertEqual((owner['id'], owner['group_ids']), ('owner-0123456789abcdef', ['system-admin']))
                # supervisor/ and hassio/ messages are not filtered.
                m.send_json(send, {'id': 3, 'type': 'supervisor/api', 'endpoint': '/addons'}, True)
                self.assertEqual(m.read_json(reader)['result'], {'echo': {'id': 3, 'type': 'supervisor/api', 'endpoint': '/addons'}})
                # Large frames both ways (64-bit lengths), and a ping's pong comes back from HA Core with its payload.
                m.send_json(send, {'id': 4, 'type': 'echo', 'pad': 'y' * 70000}, True)
                self.assertEqual(len(m.read_json(reader)['result']['echo']['pad']), 70000)
                m.send_json(send, {'id': 5, 'type': 'big'}, True); self.assertEqual(m.read_json(reader)['result'], 'x' * 100000)
                m.write_frame(send, 0x89, b'hi', True); self.assertEqual(m.read_frame(reader), (0x8A, b'hi'))
                m.write_frame(send, 0x88, b'\x03\xe8', True); self.assertEqual(m.read_frame(reader)[0], 0x88)
                s.close()
        # HA Core's websocket logins used the owner's access token, never the add-on's.
        logins = [t for kind, t in self.seen(url) if kind == 'websocket']
        self.assertEqual(len(logins), 5); self.assertNotIn(TOKEN, logins)
        self.assertEqual((mock.state / 'requests.log').read_text(encoding='utf-8').splitlines()[0], 'GET /core/websocket 101 ha_core')

    def test_websocket_with_a_wrong_token_gets_auth_invalid(self):
        mock, url = self.flagged()
        for hello in ({'type': 'auth', 'access_token': 'wrong'}, {'type': 'auth'}, {'type': 'other', 'access_token': TOKEN}):
            with self.subTest(hello):
                s, reader, status, _ = ws_open(mock.port, '/core/websocket')
                m.read_json(reader); m.send_json(s.sendall, hello, True)
                self.assertEqual(m.read_json(reader)['type'], 'auth_invalid'); s.close()
        # api_password is accepted as Supervisor does.
        s, reader, status, _ = ws_open(mock.port, '/core/websocket')
        m.read_json(reader); m.send_json(s.sendall, {'type': 'auth', 'api_password': TOKEN}, True)
        self.assertEqual(m.read_json(reader)['type'], 'auth_ok')
        m.send_json(s.sendall, {'id': 1, 'type': 'get_config'}, True); self.assertTrue(m.read_json(reader)['success']); s.close()
        # HA Core saw core-setup's login and this one's only: a refused add-on never reaches it.
        self.assertEqual(len([t for kind, t in self.seen(url) if kind == 'websocket']), 2)

class Probe(unittest.TestCase):
    def test_headers_go_with_an_http_check(self):
        # #174: the runtime sends the owner's X-Remote-User-* for flagged components (test_upgrade_runtime checks which).
        got = []
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                got.append({k.lower(): v for k, v in self.headers.items() if k.lower().startswith('x-remote-user')}); self.send_response(200); self.end_headers()
            def log_message(self, *a):pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H); self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start(); self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_address[1]}/'
        self.assertTrue(m.probe(url, 300, 5, {'X-Remote-User-ID': 'u1'}))
        self.assertEqual(m.main(['probe', '--url', url, '--header', 'X-Remote-User-Name: upgrade-test', '--header', 'X-Remote-User-Display-Name: a: b']), 0)
        self.assertEqual(m.main(['probe', '--url', url]), 0)
        self.assertEqual(got, [{'x-remote-user-id': 'u1'}, {'x-remote-user-name': 'upgrade-test', 'x-remote-user-display-name': 'a: b'}, {}])

if __name__ == '__main__':
    unittest.main()
