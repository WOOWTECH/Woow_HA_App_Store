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
  summary --state DIR  print, as JSON, the Supervisor calls the mock could not
                       answer (summary() below; pipeline #142).
  probe --url URL      one check from the Supervisor's address: exit 0 when an
                       http(s) URL answers below --below (upgrade_check.startup_probe
                       sets it) or a tcp://host:port accepts a connection.

The minimal API: /addons/self/info (also /addons/<slug>/info and /addons/self),
/addons/self/options/config, /addons/self/stats, /info, /os/info, /core/info,
/network/info and /supervisor/ping. Any other path answers 404 and is listed by
summary as an unmocked Supervisor call (未模擬的 Supervisor 呼叫).

Fixtures (#142): one JSON file per API path, the `data` of the answer
(the mock adds the {"result": "ok"} envelope), for every method. The path
loses its query and trailing slash and maps to <fixtures><path>.json:
/services/mqtt -> services/mqtt.json, /addons/self/info -> addons/self/info.json.
/addons/<the add-on's slug>/... reads addons/self/... too. A fixture beats the
default answer, so a repo can also change /info or /addons/self/info. A
fixture that is not valid JSON answers 500 and summary lists it as broken.
Only path segments of letters, digits, '.', '_' and '-' are looked up ('..'
never is).
"""
from __future__ import annotations
import argparse, collections, http.server, json, os, pathlib, re, socket, ssl, sys, urllib.error, urllib.request

TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
STATE = pathlib.Path('/state')
FIXTURES = None  # the repo's fixtures directory (serve --fixtures), or None
SEGMENT = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9._-]*')
VERSIONS = {'supervisor': '2026.10.0', 'homeassistant': '2026.10.1', 'os': '16.2'}

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
        'machine': 'qemux86-64', 'arch': 'amd64', 'ip_address': '172.30.32.1', 'image': 'ghcr.io/home-assistant/qemux86-64-homeassistant',
        'boot': True, 'port': 8123, 'ssl': False, 'watchdog': True, 'audio_input': None, 'audio_output': None, 'backups_exclude_database': False}

def _network_info():
    return {'interfaces': [{'interface': 'eth0', 'type': 'ethernet', 'enabled': True, 'connected': True, 'primary': True,
            'mac': '02:42:ac:11:00:02', 'ipv4': {'method': 'auto', 'address': ['192.168.1.10/24'], 'nameservers': ['192.168.1.1'],
                'gateway': '192.168.1.1', 'ready': True},
            'ipv6': {'method': 'disabled', 'address': [], 'nameservers': [], 'gateway': None, 'ready': False}, 'wifi': None, 'vlan': None}],
        'docker': {'interface': 'hassio', 'address': '172.30.32.0/23', 'gateway': '172.30.32.1', 'dns': '172.30.32.3'},
        'host_internet': True, 'supervisor_internet': True}

def normalize(path):
    """The path an API call is routed, looked up and summarized by: no query, no trailing slash."""
    return path.split('?', 1)[0].rstrip('/') or '/'

def fixture_file(path, slug=None):
    """The fixture file for a normalized path (it may not exist), or None when the path cannot name one."""
    parts = path.strip('/').split('/')
    if FIXTURES is None or not all(SEGMENT.fullmatch(p) for p in parts):
        return None
    if slug and len(parts) > 1 and parts[0] == 'addons' and parts[1] == slug:
        parts[1] = 'self'
    return pathlib.Path(FIXTURES, *parts[:-1], parts[-1] + '.json')

def route(path):
    """(status, data) for one API call; data None means 404 (500: a broken fixture)."""
    path = normalize(path)
    addon = _addon()
    fixture = fixture_file(path, addon.get('slug'))
    if fixture is not None and fixture.is_file():
        try:
            return 200, json.loads(fixture.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return 500, None
    if path in ('/addons/self', '/addons/self/info', f'/addons/{addon.get("slug")}/info'):
        return 200, addon
    if path == '/addons/self/options/config':
        return 200, addon.get('options', {})
    if path == '/addons/self/stats':
        return 200, {'cpu_percent': 1.0, 'memory_usage': 1 << 26, 'memory_limit': 1 << 32, 'memory_percent': 1.5,
            'network_rx': 0, 'network_tx': 0, 'blk_read': 0, 'blk_write': 0}
    if path == '/supervisor/ping':
        return 200, {}
    data = {'/info': _info, '/os/info': _os_info, '/core/info': _core_info, '/network/info': _network_info}.get(path)
    return (200, data()) if data else (404, None)

class Handler(http.server.BaseHTTPRequestHandler):
    def _answer(self):
        auth = self.headers.get('Authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else self.headers.get('X-Supervisor-Token', '')
        if not TOKEN or token != TOKEN:
            status, body = 401, {'result': 'error', 'message': 'Unauthorized'}
        else:
            status, data = route(self.path)
            body = ({'result': 'ok', 'data': data} if status == 200 else
                {'result': 'error', 'message': f'{self.path} is not mocked' if status == 404 else f'the fixture for {self.path} is not valid JSON'})
        # The runtime's own readiness check comes from inside this container: the log keeps the add-on's calls only.
        if self.client_address[0] != '127.0.0.1':
            with open(STATE / 'requests.log', 'a', encoding='utf-8') as log:
                log.write(f'{self.command} {self.path} {status}\n')
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    do_GET = do_POST = do_PUT = do_DELETE = _answer
    def log_message(self, *args):
        pass

def summary(state):
    """What the mock could not answer, from `state`/requests.log (no log: nothing):
    {'unmocked': [{'path', 'count', 'methods'}], 'broken_fixtures': [same]}; paths normalized, sorted by path.
    The log already leaves out the runtime's own checks from 127.0.0.1."""
    log = pathlib.Path(state) / 'requests.log'
    seen = {404: collections.defaultdict(list), 500: collections.defaultdict(list)}
    if log.is_file():
        for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
            parts = line.split(' ')
            if len(parts) < 3 or not parts[-1].isdigit() or int(parts[-1]) not in seen:
                continue
            seen[int(parts[-1])][normalize(' '.join(parts[1:-1]))].append(parts[0])
    rows = lambda calls: [{'path': p, 'count': len(m), 'methods': sorted(set(m))} for p, m in sorted(calls.items())]
    return {'unmocked': rows(seen[404]), 'broken_fixtures': rows(seen[500])}

def probe(url, below, timeout):
    """True when `url` answers as the startup check needs (see the module docstring)."""
    if url.startswith('tcp://'):
        host, _, port = url[6:].rstrip('/').rpartition(':')
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except OSError:
            return False
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=ssl._create_unverified_context()) as r:
            return r.status < below
    except urllib.error.HTTPError as e:
        return e.code < below
    except (OSError, ValueError):
        return False

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('serve'); s.add_argument('--state', default='/state')
    s.add_argument('--fixtures', help="the repo's Supervisor fixtures directory"); s.add_argument('--port', type=int, default=80)
    m = sub.add_parser('summary'); m.add_argument('--state', default='/state')
    c = sub.add_parser('probe'); c.add_argument('--url', required=True)
    c.add_argument('--below', type=int, default=300); c.add_argument('--timeout', type=float, default=5)
    a = p.parse_args(argv)
    if a.command == 'probe':
        return 0 if probe(a.url, a.below, a.timeout) else 1
    if a.command == 'summary':
        print(json.dumps(summary(a.state), indent=1)); return 0
    global STATE, FIXTURES
    STATE = pathlib.Path(a.state)
    FIXTURES = pathlib.Path(a.fixtures) if a.fixtures else None
    http.server.ThreadingHTTPServer(('0.0.0.0', a.port), Handler).serve_forever()

if __name__ == '__main__':
    sys.exit(main())
