#!/usr/bin/env python3
"""The mock Home Assistant Supervisor of the upgrade test (pipeline #137).

upgrade_runtime.py runs this in a container at the Supervisor's address
(172.30.32.2) on the add-on's hassio network. Standard library only.

  serve --state DIR [--fixtures DIR] [--port 80]
                       answer the Supervisor API. --state DIR/addon.json is the
                       add-on's own info (written by the runtime for each version,
                       read on every request); requests are logged to
                       DIR/requests.log as "METHOD PATH STATUS", except those from
                       127.0.0.1 (the runtime's readiness check). Every call needs
                       the add-on's token. --fixtures is the source repo's
                       upgrade-check/supervisor/ (see Fixtures).
  probe --url URL      one check from the Supervisor's address: exit 0 when an
                       http(s) URL answers below --below (upgrade_check.startup_probe
                       sets it) or a tcp://host:port accepts a connection. Each
                       --header 'Name: value' is sent with an http(s) check (#174).
  core-setup --core URL [--state DIR] [--timeout 180]
                       onboard a fresh HA Core (#174, below) and wait until it is
                       RUNNING: exit 1 with the reason on stderr when that does not
                       happen within --timeout seconds.

The minimal API: /addons/self/info, /addons/self/options/config,
/addons/self/stats, /info, /os/info, /core/info, /network/info, /dns/info
and /supervisor/ping. Every method (GET, POST, HEAD, PATCH...) is answered the
same way. A path loses its query and trailing slash; /addons/<the add-on's
slug>/... is /addons/self/..., and /addons/self is /addons/self/info
(canonical()). Any other path answers 404 and summary() lists it as an
unmocked Supervisor call (未模擬的 Supervisor 呼叫).

Fixtures (#142): one JSON file per canonical path, the `data` of the answer
(the mock adds the {"result": "ok"} envelope): /services/mqtt ->
services/mqtt.json, /addons/self/info (and its aliases) -> addons/self/info.json.
A fixture beats the default answer, except:
  - addons/self/info.json must be an object and is laid over the info the
    runtime writes for each version (version, options, ingress_port...): its
    keys replace those keys only;
  - /supervisor/ping always answers itself: the runtime's readiness check
    must not depend on the repo.
A fixture that is not valid JSON (or an info overlay that is not an object)
answers 500 and summary() lists it as broken. Only path segments of letters,
digits, '.', '_' and '-' are looked up, never one starting with '.'.

HA Core (#174): for a component the Store registry flags
upgrade_comparison.ha_core, the runtime starts a real HA Core (CORE_IMAGE at
VERSIONS['homeassistant'], the version /core/info reports) on the mock network
and writes DIR/core.json with its URL; `core-setup` (run in this container, the
only one that talks to HA Core) onboards it headlessly with the REST flow of
version_control's tools/rebuild_real.py (POST /api/onboarding/users ->
auth_code -> /auth/token authorization_code -> core_config, analytics,
integration), adds the owner's refresh token, user id and names to core.json,
then waits until HA Core's /api/config state is RUNNING. With core.json the
mock forwards what the real Supervisor's api/proxy.py does: /core/api/<path>,
/core/api/ and /core/api/stream (GET, POST, HEAD), and the websockets
/core/api/websocket and /core/websocket, and the same under /homeassistant/.
  - REST: the add-on's token (Authorization, its last word, or X-Ha-Access;
    else 401) is dropped and HA Core is called with the owner's access token,
    got from the refresh token (grant_type=refresh_token) as Supervisor does and
    renewed before it expires. The query, Content-Type and body go to HA Core;
    its status, Content-Type and body (streamed) come back.
  - Websocket (no header token, as in Supervisor): the mock sends auth_required,
    checks the add-on's auth message (access_token or api_password) against its
    token and answers auth_ok or auth_invalid, both with VERSIONS['homeassistant'];
    then it logs in to HA Core's websocket with the owner's token and pipes
    frames both ways unchanged, supervisor/ and hassio/ messages too. No
    extension is negotiated, so frames need no rewriting beyond masking.
  - Until core.json has the refresh token and HA Core is RUNNING, or when HA
    Core does not answer, these paths answer 502. Without core.json (no flag)
    they are ordinary unmocked paths (404 with the token, 401 without), and
    GET /core without a token answers 401 either way (music_assistant tells add-on
    mode by it).
  - Forwarded calls are logged as "METHOD PATH STATUS ha_core": summary() does
    not count HA Core's answers as unmocked Supervisor calls.
"""
from __future__ import annotations
import argparse, base64, collections, hashlib, http.client, http.server, json, os, pathlib, re, secrets, socket, ssl, struct, sys
import threading, time, urllib.error, urllib.parse, urllib.request

TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
STATE = pathlib.Path('/state')
FIXTURES = None  # the repo's fixtures directory (serve --fixtures), or None
SEGMENT = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9._-]*')
VERSIONS = {'supervisor': '2026.10.0', 'homeassistant': '2026.10.1', 'os': '16.2', 'dns': '2026.10.0'}
# The mock host's LAN and the add-ons' docker network: /network/info and /dns/info report the same addresses.
HOST_NAMESERVER = '192.168.1.1'
DOCKER_DNS = '172.30.32.3'
# #174: the test HA Core's image (its tag is VERSIONS['homeassistant'], bumped by hand), the runtime's hand-over file in
# the state directory, the paths forwarded to it, the request log's mark on a forwarded call, and the onboarded owner.
CORE_IMAGE = 'ghcr.io/home-assistant/qemux86-64-homeassistant'
CORE_FILE = 'core.json'
CORE_PATH = re.compile(r'/(?:core|homeassistant)/(?:(?P<ws>api/websocket|websocket)|(?P<api>api/.*))')
FORWARDED = 'ha_core'
OWNER = 'upgrade-test'
WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
WS_TEXT, WS_CLOSE = 0x1, 0x8

def _addon():
    return json.loads((STATE / 'addon.json').read_text(encoding='utf-8'))

def _info():
    return {'supervisor': VERSIONS['supervisor'], 'homeassistant': VERSIONS['homeassistant'], 'hassos': VERSIONS['os'],
        'docker': '27.5.1', 'hostname': 'homeassistant', 'operating_system': f'Home Assistant OS {VERSIONS["os"]}',
        'features': ['reboot', 'shutdown', 'services', 'network', 'hostname', 'timedate', 'os_agent', 'haos', 'resolved',
            'journal', 'disk', 'mount'], 'machine': 'qemux86-64', 'arch': 'amd64', 'supported_arch': ['amd64', 'i386'],
        'supported': True, 'channel': 'stable', 'logging': 'info', 'state': 'running', 'timezone': 'UTC'}

def _os_info():
    return {'version': VERSIONS['os'], 'version_latest': VERSIONS['os'], 'update_available': False, 'board': 'ova',
        'boot': 'A', 'data_disk': '/dev/sda8', 'boot_slots': {}}

def _core_info():
    return {'version': VERSIONS['homeassistant'], 'version_latest': VERSIONS['homeassistant'], 'update_available': False,
        'machine': 'qemux86-64', 'arch': 'amd64', 'ip_address': '172.30.32.1', 'image': CORE_IMAGE,
        'boot': True, 'port': 8123, 'ssl': False, 'watchdog': True, 'audio_input': None, 'audio_output': None, 'backups_exclude_database': False}

def _network_info():
    return {'interfaces': [{'interface': 'eth0', 'type': 'ethernet', 'enabled': True, 'connected': True, 'primary': True,
            'mac': '02:42:ac:11:00:02', 'ipv4': {'method': 'auto', 'address': ['192.168.1.10/24'], 'nameservers': [HOST_NAMESERVER],
                'gateway': '192.168.1.1', 'ready': True},
            'ipv6': {'method': 'disabled', 'address': [], 'nameservers': [], 'gateway': None, 'ready': False}, 'wifi': None, 'vlan': None}],
        'docker': {'interface': 'hassio', 'address': '172.30.32.0/23', 'gateway': '172.30.32.1', 'dns': DOCKER_DNS},
        'host_internet': True, 'supervisor_internet': True}

def _dns_info():
    # Supervisor's api/dns.py: `host` is the DNS plugin's address on the docker network, `locals` the host's nameservers.
    return {'version': VERSIONS['dns'], 'version_latest': VERSIONS['dns'], 'update_available': False, 'host': DOCKER_DNS,
        'servers': [], 'locals': [f'dns://{HOST_NAMESERVER}'], 'mdns': True, 'llmnr': True, 'fallback': True}

def normalize(path):
    """The path an API call is routed, looked up and summarized by: no query, no trailing slash."""
    return path.split('?', 1)[0].rstrip('/') or '/'

def canonical(path, slug=None):
    """The path the default answers and the fixtures know a call by: normalize(), then /addons/<slug>/... as
    /addons/self/... and /addons/self as /addons/self/info."""
    path = normalize(path)
    if slug and (path == f'/addons/{slug}' or path.startswith(f'/addons/{slug}/')):
        path = '/addons/self' + path[len(f'/addons/{slug}'):]
    return '/addons/self/info' if path == '/addons/self' else path

def fixture_file(path):
    """The fixture file for a canonical path (it may not exist), or None when the path cannot name one."""
    parts = path.strip('/').split('/')
    if FIXTURES is None or path == '/supervisor/ping' or not all(SEGMENT.fullmatch(p) for p in parts):
        return None
    return pathlib.Path(FIXTURES, *parts[:-1], parts[-1] + '.json')

def route(path):
    """(status, data) for one API call; data None means 404 (500: a broken fixture)."""
    addon = _addon()
    path = canonical(path, addon.get('slug'))
    fixture = fixture_file(path)
    if fixture is not None and fixture.is_file():
        try:
            data = json.loads(fixture.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return 500, None
        if path != '/addons/self/info':
            return 200, data
        # The add-on's own info is the runtime's for each version: the fixture changes the keys it names only.
        return (200, {**addon, **data}) if isinstance(data, dict) else (500, None)
    if path == '/addons/self/info':
        return 200, addon
    if path == '/addons/self/options/config':
        return 200, addon.get('options', {})
    if path == '/addons/self/stats':
        return 200, {'cpu_percent': 1.0, 'memory_usage': 1 << 26, 'memory_limit': 1 << 32, 'memory_percent': 1.5,
            'network_rx': 0, 'network_tx': 0, 'blk_read': 0, 'blk_write': 0}
    if path == '/supervisor/ping':
        return 200, {}
    data = {'/info': _info, '/os/info': _os_info, '/core/info': _core_info, '/network/info': _network_info,
        '/dns/info': _dns_info}.get(path)
    return (200, data()) if data else (404, None)

# #174: HA Core behind the mock (module docstring).
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # straight to HA Core, whatever the environment says

def _http(url, method='GET', body=None, headers=None, timeout=30):
    """(status, body bytes) of one call; OSError when it cannot be made."""
    try:
        with _OPENER.open(urllib.request.Request(url, data=body, method=method, headers=headers or {}), timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def _post_json(url, data, access=None):
    headers = {'Content-Type': 'application/json', **({'Authorization': f'Bearer {access}'} if access else {})}
    return _http(url, 'POST', json.dumps(data).encode(), headers)

def _post_form(url, form):
    return _http(url, 'POST', urllib.parse.urlencode(form).encode(), {'Content-Type': 'application/x-www-form-urlencoded'})

def _core():
    """The runtime's core.json, or None: this component has no HA Core."""
    path = STATE / CORE_FILE
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None

class CoreDown(Exception):
    """HA Core cannot be used (502): not onboarded or not RUNNING yet, or not answering."""

_CORE_LOCK = threading.Lock()
_CORE_CACHE = {}  # the owner's access token (refresh, access, expires) and the HA Core seen RUNNING (running: its url)

def core_access(core):
    """The owner's access token, from core.json's refresh token (grant_type=refresh_token) as Supervisor gets its own,
    kept until a minute before it expires. CoreDown before core-setup wrote the refresh token, or when HA Core refuses."""
    if not core.get('refresh_token'):
        raise CoreDown('the test HA Core is not onboarded yet')
    with _CORE_LOCK:
        c = _CORE_CACHE
        if c.get('refresh') == core['refresh_token'] and time.monotonic() < c.get('expires', 0):
            return c['access']
        try:
            status, raw = _post_form(core['url'] + '/auth/token', {'grant_type': 'refresh_token', 'refresh_token': core['refresh_token'],
                'client_id': core['client_id']})
            tokens = json.loads(raw) if status == 200 else None
            access = tokens['access_token'] if isinstance(tokens, dict) else None
        except (OSError, ValueError, KeyError) as e:
            raise CoreDown(f'the test HA Core did not answer the token refresh: {e}') from None
        if not access:
            raise CoreDown(f'the test HA Core refused the owner refresh token (HTTP {status})')
        c.update(refresh=core['refresh_token'], access=access, expires=time.monotonic() + float(tokens.get('expires_in', 1800)) - 60)
        return access

def core_state(url, access):
    """HA Core's state as /api/config gives it ('RUNNING' when it runs), or why it cannot be read."""
    try:
        status, raw = _http(url + '/api/config', headers={'Authorization': f'Bearer {access}'}, timeout=10)
    except OSError as e:
        return f'not answering ({e})'
    if status != 200:
        return f'answering /api/config with HTTP {status}'
    try:
        data = json.loads(raw)
    except ValueError:
        return 'answering /api/config with something that is not JSON'
    return str(data.get('state') or 'without a state') if isinstance(data, dict) else 'answering /api/config with something that is not an object'

def core_ready(core):
    """The owner's access token once HA Core is RUNNING (remembered: it is not restarted during a test); CoreDown before."""
    access = core_access(core)
    if _CORE_CACHE.get('running') != core['url']:
        state = core_state(core['url'], access)
        if state != 'RUNNING':
            raise CoreDown(f'the test HA Core is {state}, not RUNNING yet')
        _CORE_CACHE['running'] = core['url']
    return access

# A hand-written websocket (RFC 6455), standard library only: frames are read from a buffered reader and written with
# a send callable (socket.sendall, or the handler's unbuffered wfile.write).
def ws_accept(key):
    """Sec-WebSocket-Accept for a Sec-WebSocket-Key."""
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()

def _exact(reader, n):
    data = reader.read(n)
    if len(data) < n:
        raise EOFError('the websocket closed')
    return data

def _mask(data, key):
    n = len(data)
    return (int.from_bytes(data, 'big') ^ int.from_bytes((key * (n // 4 + 1))[:n], 'big')).to_bytes(n, 'big') if n else data

def read_frame(reader):
    """(first byte: FIN, RSV bits and opcode as sent; the payload, unmasked) of the next frame. EOFError at the end."""
    b0, b1 = _exact(reader, 2)
    n = b1 & 0x7f
    if n == 126:
        n = struct.unpack('!H', _exact(reader, 2))[0]
    elif n == 127:
        n = struct.unpack('!Q', _exact(reader, 8))[0]
    key = _exact(reader, 4) if b1 & 0x80 else None
    data = _exact(reader, n)
    return b0, _mask(data, key) if key else data

def write_frame(send, b0, data, masked):
    """Send one frame: masked as a client's must be (toward HA Core), unmasked as a server's (toward the add-on)."""
    n, bit = len(data), 0x80 if masked else 0
    if n < 126:
        head = bytes([b0, bit | n])
    elif n < 1 << 16:
        head = bytes([b0, bit | 126]) + struct.pack('!H', n)
    else:
        head = bytes([b0, bit | 127]) + struct.pack('!Q', n)
    if masked:
        key = os.urandom(4); head += key; data = _mask(data, key)
    send(head + data)

def send_json(send, message, masked):
    write_frame(send, 0x80 | WS_TEXT, json.dumps(message).encode(), masked)

def read_json(reader):
    """The next text message (its fragments joined) as JSON; pings or pongs before it are skipped. EOFError on close."""
    parts = []
    while True:
        b0, data = read_frame(reader)
        if b0 & 0x0f == WS_CLOSE:
            raise EOFError('the websocket closed')
        if b0 & 0x08:
            continue
        parts.append(data)
        if b0 & 0x80:
            return json.loads(b''.join(parts))

def ws_connect(url, access, timeout=30):
    """A websocket to HA Core at `url` (http://host:port, or a base such as http://supervisor/core as an add-on uses),
    <url>/api/websocket, logged in with `access`: (socket, buffered reader). OSError, EOFError or ValueError when it
    cannot be opened or the login is refused."""
    parts = urllib.parse.urlsplit(url)
    sock = socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f'GET {parts.path.rstrip("/")}/api/websocket HTTP/1.1\r\nHost: {parts.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        reader = sock.makefile('rb')
        status, headers = reader.readline().decode('latin-1').split(), {}
        while True:
            line = reader.readline().decode('latin-1').strip()
            if not line:
                break
            name, _, value = line.partition(':'); headers[name.strip().lower()] = value.strip()
        if status[1:2] != ['101'] or headers.get('sec-websocket-accept') != ws_accept(key):
            raise ValueError(f'HA Core did not open its websocket: {" ".join(status)}')
        hello = read_json(reader)
        if hello.get('type') != 'auth_required':
            raise ValueError(f'HA Core opened its websocket with {hello.get("type")!r}, not auth_required')
        send_json(sock.sendall, {'type': 'auth', 'access_token': access}, True)
        answer = read_json(reader)
        if answer.get('type') != 'auth_ok':
            raise ValueError(f'HA Core answered the owner login with {answer.get("type")!r}')
        sock.settimeout(None)
        return sock, reader
    except BaseException:
        sock.close(); raise

def ws_call(sock, reader, message, ident=1):
    """The result of one websocket command (`message` without its id): ValueError when it fails."""
    send_json(sock.sendall, {**message, 'id': ident}, True)
    while True:
        answer = read_json(reader)
        if answer.get('id') == ident and answer.get('type') == 'result':
            if not answer.get('success'):
                raise ValueError(f'{message.get("type")} failed: {answer.get("error")}')
            return answer.get('result')

def pipe(reader, send, masked, done):
    """Copy frames from `reader` to `send` unchanged (masked toward HA Core). At a close frame it stops and gives the
    other side 5 s to answer it before done() ends both; at the end of a connection, done() at once."""
    try:
        while True:
            b0, data = read_frame(reader)
            write_frame(send, b0, data, masked)
            if b0 & 0x0f == WS_CLOSE:
                timer = threading.Timer(5, done); timer.daemon = True; timer.start()
                return
    except (OSError, EOFError, ValueError):
        done()

class Handler(http.server.BaseHTTPRequestHandler):
    def _log(self, status, mark=''):
        # The runtime's own readiness check comes from inside this container: the log keeps the add-on's calls only.
        if self.client_address[0] != '127.0.0.1':
            with open(STATE / 'requests.log', 'a', encoding='utf-8') as log:
                log.write(f'{self.command} {self.path} {status}{" " + mark if mark else ""}\n')
    def _reply(self, status, body, mark=''):
        self._log(status, mark)
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)
    def _answer(self):
        path, _, query = self.path.partition('?')
        forwarded = CORE_PATH.fullmatch(path)
        core = _core() if forwarded else None
        if core is not None:
            return self._websocket(core) if forwarded['ws'] else self._forward(core, forwarded['api'], query)
        auth = self.headers.get('Authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else self.headers.get('X-Supervisor-Token', '')
        if not TOKEN or token != TOKEN:
            return self._reply(401, {'result': 'error', 'message': 'Unauthorized'})
        status, data = route(self.path)
        self._reply(status, {'result': 'ok', 'data': data} if status == 200 else
            {'result': 'error', 'message': f'{self.path} is not mocked' if status == 404 else f'the fixture for {self.path} is not usable JSON'})
    def _forward(self, core, path, query):
        """#174: one REST call to HA Core with the owner's token, as Supervisor's proxy makes it (module docstring)."""
        if self.command not in ('GET', 'POST', 'HEAD'):
            return self._reply(405, {'result': 'error', 'message': f'{self.command} is not forwarded to HA Core'}, FORWARDED)
        auth = self.headers.get('Authorization')
        token = auth.split(' ')[-1] if auth is not None else self.headers.get('X-Ha-Access', '')
        if not TOKEN or token != TOKEN:
            return self._reply(401, {'result': 'error', 'message': 'Unauthorized'}, FORWARDED)
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else None
        try:
            access = core_ready(core)
        except CoreDown as e:
            return self._reply(502, {'result': 'error', 'message': str(e)}, FORWARDED)
        target = urllib.parse.urlsplit(core['url'])
        conn = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=300)
        headers = {'Authorization': f'Bearer {access}'}
        if self.headers.get('Content-Type'):
            headers['Content-Type'] = self.headers['Content-Type']
        try:
            conn.request(self.command, '/' + path + (f'?{query}' if query else ''), body=body, headers=headers)
            answer = conn.getresponse()
        except OSError as e:
            conn.close()
            return self._reply(502, {'result': 'error', 'message': f'the test HA Core did not answer: {e}'}, FORWARDED)
        try:
            self._log(answer.status, FORWARDED)
            self.send_response(answer.status)
            if answer.getheader('Content-Type'):
                self.send_header('Content-Type', answer.getheader('Content-Type'))
            if answer.getheader('Content-Length') is not None:
                self.send_header('Content-Length', answer.getheader('Content-Length'))
            self.end_headers()
            # Streamed as it comes (/api/stream never ends by itself); this server closes the connection after it.
            while self.command != 'HEAD':
                chunk = answer.read1(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except OSError:
            pass
        finally:
            self.close_connection = True; conn.close()
    def _websocket(self, core):
        """#174: the add-on's websocket, logged in here and piped to HA Core's (module docstring)."""
        key = self.headers.get('Sec-WebSocket-Key')
        if self.command != 'GET' or 'websocket' not in self.headers.get('Upgrade', '').lower() or not key:
            return self._reply(400, {'result': 'error', 'message': 'not a websocket request'}, FORWARDED)
        try:
            access = core_ready(core)
        except CoreDown as e:
            return self._reply(502, {'result': 'error', 'message': str(e)}, FORWARDED)
        self._log(101, FORWARDED)
        self.protocol_version = 'HTTP/1.1'  # a 101 answer in HTTP/1.0 is refused by websocket clients
        self.send_response(101)
        self.send_header('Upgrade', 'websocket'); self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', ws_accept(key))
        self.end_headers()
        self.close_connection = True
        send, version = self.wfile.write, VERSIONS['homeassistant']
        try:
            send_json(send, {'type': 'auth_required', 'ha_version': version}, False)
            hello = read_json(self.rfile)
            token = hello.get('access_token') or hello.get('api_password') if isinstance(hello, dict) else None
            if not isinstance(hello, dict) or hello.get('type') != 'auth' or not TOKEN or token != TOKEN:
                send_json(send, {'type': 'auth_invalid', 'message': 'Invalid access'}, False)
                return
            send_json(send, {'type': 'auth_ok', 'ha_version': version}, False)
            upstream, reader = ws_connect(core['url'], access)
        except (OSError, EOFError, ValueError):
            try:
                write_frame(send, 0x80 | WS_CLOSE, struct.pack('!H', 1011), False)
            except OSError:
                pass
            return
        def done():
            for s in (upstream, self.connection):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        back = threading.Thread(target=pipe, args=(reader, send, False, done), daemon=True)
        back.start()
        pipe(self.rfile, upstream.sendall, True, done)
        back.join(10)
        upstream.close()
    def __getattr__(self, name):
        # Every method (do_HEAD, do_PATCH...) is answered and logged alike, never with http.server's unlogged 501.
        if name.startswith('do_'):
            return self._answer
        raise AttributeError(name)
    def log_message(self, *args):
        pass

def log_size(state):
    """The size of `state`/requests.log now (0 without one): summary(state, start=...) then covers later calls only."""
    log = pathlib.Path(state) / 'requests.log'
    return log.stat().st_size if log.is_file() else 0

def summary(state, start=0):
    """What the mock could not answer, from `state`/requests.log after byte `start` (log_size; no log: nothing):
    {'unmocked': [{'path', 'count', 'methods'}], 'broken_fixtures': [same]}; paths normalized, sorted by path.
    The log already leaves out the runtime's own checks from 127.0.0.1; calls forwarded to HA Core (marked) are not
    the mock's to answer, so they are left out too (#174)."""
    log = pathlib.Path(state) / 'requests.log'
    seen = {404: collections.defaultdict(list), 500: collections.defaultdict(list)}
    if log.is_file():
        with open(log, 'rb') as f:
            f.seek(start); text = f.read().decode('utf-8', errors='replace')
        for line in text.splitlines():
            parts = line.split(' ')
            if len(parts) < 3 or not parts[-1].isdigit() or int(parts[-1]) not in seen:
                continue
            seen[int(parts[-1])][normalize(' '.join(parts[1:-1]))].append(parts[0])
    rows = lambda calls: [{'path': p, 'count': len(m), 'methods': sorted(set(m))} for p, m in sorted(calls.items())]
    return {'unmocked': rows(seen[404]), 'broken_fixtures': rows(seen[500])}

def probe(url, below, timeout, headers=None):
    """True when `url` answers as the startup check needs (see the module docstring); `headers` go with an http(s) check."""
    if url.startswith('tcp://'):
        host, _, port = url[6:].rstrip('/').rpartition(':')
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except OSError:
            return False
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout,
                context=ssl._create_unverified_context()) as r:
            return r.status < below
    except urllib.error.HTTPError as e:
        return e.code < below
    except (OSError, ValueError):
        return False

def core_setup(url, state, timeout):
    """#174: onboard the fresh HA Core at `url` (the REST flow of version_control's tools/rebuild_real.py), write
    `state`/core.json {url, client_id, refresh_token, user_id, user_name, display_name} and wait until HA Core is
    RUNNING. '' when it is within `timeout` seconds of the call, else why not."""
    deadline = time.monotonic() + timeout
    last = 'no answer'
    # 1. HA Core's HTTP is up once /api/onboarding answers (onboarding works before HA Core is RUNNING).
    while True:
        try:
            status, raw = _http(url + '/api/onboarding', timeout=10)
            if status == 200:
                steps = json.loads(raw); break
            last = f'HTTP {status}'
        except (OSError, ValueError) as e:
            last = str(e) or type(e).__name__
        if time.monotonic() >= deadline:
            return f'HA Core did not answer /api/onboarding within {timeout:g} s ({last})'
        time.sleep(1)
    if any(isinstance(s, dict) and s.get('step') == 'user' and s.get('done') for s in steps):
        return 'onboarding failed: HA Core already has its owner (its config directory is not fresh)'
    # 2. The owner and its tokens, then the other steps, as rebuild_real.py's ONBOARDING_SCRIPT does them.
    client_id = url + '/'
    try:
        status, raw = _post_json(url + '/api/onboarding/users', {'client_id': client_id, 'name': OWNER, 'username': OWNER,
            'password': secrets.token_urlsafe(24), 'language': 'en'})
        if status != 200:
            return f'onboarding failed: /api/onboarding/users answered HTTP {status}: {raw[:200].decode(errors="replace")}'
        status, raw = _post_form(url + '/auth/token', {'grant_type': 'authorization_code', 'code': json.loads(raw)['auth_code'],
            'client_id': client_id})
        if status != 200:
            return f'onboarding failed: /auth/token answered HTTP {status}: {raw[:200].decode(errors="replace")}'
        tokens = json.loads(raw)
        for step, body in (('core_config', {}), ('analytics', {}), ('integration', {'client_id': client_id, 'redirect_uri': client_id + '?auth_callback=1'})):
            status, raw = _post_json(f'{url}/api/onboarding/{step}', body, tokens['access_token'])
            if status != 200:
                return f'onboarding failed: /api/onboarding/{step} answered HTTP {status}: {raw[:200].decode(errors="replace")}'
        sock, reader = ws_connect(url, tokens['access_token'])
        try:
            user = ws_call(sock, reader, {'type': 'auth/current_user'})
        finally:
            sock.close()
        core = {'url': url, 'client_id': client_id, 'refresh_token': tokens['refresh_token'], 'user_id': user['id'], 'user_name': OWNER,
            'display_name': user.get('name') or OWNER}
    except (OSError, EOFError, ValueError, KeyError, TypeError) as e:
        return f'onboarding failed: {type(e).__name__}: {e}'
    tmp = pathlib.Path(state) / (CORE_FILE + '.tmp')
    tmp.write_text(json.dumps(core), encoding='utf-8'); tmp.replace(pathlib.Path(state) / CORE_FILE)
    # 3. RUNNING, as the forwarded paths need it.
    while True:
        last = core_state(url, tokens['access_token'])
        if last == 'RUNNING':
            return ''
        if time.monotonic() >= deadline:
            return f'HA Core did not reach RUNNING within {timeout:g} s (it is {last})'
        time.sleep(1)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('serve'); s.add_argument('--state', default='/state')
    s.add_argument('--fixtures', help="the repo's Supervisor fixtures directory"); s.add_argument('--port', type=int, default=80)
    c = sub.add_parser('probe'); c.add_argument('--url', required=True)
    c.add_argument('--below', type=int, default=300); c.add_argument('--timeout', type=float, default=5)
    c.add_argument('--header', action='append', default=[], help="'Name: value', sent with an http(s) check")
    k = sub.add_parser('core-setup'); k.add_argument('--core', required=True, help='the test HA Core, http://host:port')
    k.add_argument('--state', default='/state'); k.add_argument('--timeout', type=float, default=180)
    a = p.parse_args(argv)
    if a.command == 'probe':
        headers = dict(h.split(':', 1) for h in a.header)
        return 0 if probe(a.url, a.below, a.timeout, {k.strip(): v.strip() for k, v in headers.items()}) else 1
    if a.command == 'core-setup':
        why = core_setup(a.core.rstrip('/'), a.state, a.timeout)
        if why:
            print(why, file=sys.stderr)
        return 1 if why else 0
    global STATE, FIXTURES
    STATE = pathlib.Path(a.state)
    FIXTURES = pathlib.Path(a.fixtures) if a.fixtures else None
    http.server.ThreadingHTTPServer(('0.0.0.0', a.port), Handler).serve_forever()

if __name__ == '__main__':
    sys.exit(main())
