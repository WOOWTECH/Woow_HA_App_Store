#!/usr/bin/env python3
"""A small fake HA Core for the tests of the mock Supervisor's HA Core forwarding (pipeline #174). Standard library
only; the real HA Core image is used only in the acceptance run, never in tests.

  python fake_ha_core.py [--port 8123] [--running-after SECONDS | --never-running]

It answers what the mock and core-setup use: the onboarding REST flow (/api/onboarding, /api/onboarding/users ->
auth_code, /auth/token with authorization_code and refresh_token, core_config, analytics, integration), GET
/api/config with its state (STARTING until RUNNING), every other /api/<path> by echoing the call as JSON, /api/stream
as two server-sent events, and the websocket /api/websocket: auth_required, auth with an access token it issued,
then get_config, auth/current_user, config/auth/list (the owner in system-admin) and any other command echoed back.
Every /api call and websocket login needs one of its access tokens (401 or auth_invalid otherwise).

For the tests: GET /fake/seen lists the tokens HA Core was called with ([[what, token]]), POST /fake/running makes it
RUNNING at once. Its websocket frames use mock_supervisor's frame code, so this file sits next to it.
"""
import argparse, http.server, json, os, sys, threading, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mock_supervisor as m

OWNER_ID = 'owner-0123456789abcdef'
STATE = {'running_at': 0.0, 'owner': None, 'access': set(), 'refresh': 'refresh-token-1', 'client_id': None, 'seen': [], 'issued': 0}
LOCK = threading.Lock()

def _issue():
    with LOCK:
        STATE['issued'] += 1; token = f'access-token-{STATE["issued"]}'; STATE['access'].add(token)
    return {'access_token': token, 'refresh_token': STATE['refresh'], 'expires_in': 1800, 'token_type': 'Bearer'}

def _state():
    return 'RUNNING' if time.monotonic() >= STATE['running_at'] else 'STARTING'

def _user():
    return {'id': OWNER_ID, 'name': STATE['owner']['name'], 'is_owner': True, 'is_admin': True,
        'credentials': [{'auth_provider_type': 'homeassistant', 'auth_provider_id': None}], 'mfa_modules': []}

def _command(msg):
    """(success, result) of one websocket command."""
    kind = msg.get('type')
    if kind == 'get_config':return True, {'state': _state(), 'version': m.VERSIONS['homeassistant']}
    if kind == 'auth/current_user':return True, _user()
    if kind == 'config/auth/list':
        return True, [{'id': OWNER_ID, 'username': STATE['owner']['username'], 'name': STATE['owner']['name'], 'is_owner': True,
            'is_active': True, 'local_only': False, 'system_generated': False, 'group_ids': ['system-admin'], 'credentials': []}]
    if kind == 'big':return True, 'x' * 100000
    return True, {'echo': msg}

class Handler(http.server.BaseHTTPRequestHandler):
    def _json(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        if self.command != 'HEAD':self.wfile.write(raw)
    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(n) if n else b''
    def _authorized(self):
        token = self.headers.get('Authorization', '')[7:]
        with LOCK:STATE['seen'].append(['rest', token])
        return token in STATE['access']
    def _answer(self):
        path, _, query = self.path.partition('?')
        if path == '/fake/seen':return self._json(200, STATE['seen'])
        if path == '/fake/running':STATE['running_at'] = 0.0; return self._json(200, {})
        if path == '/api/onboarding':
            done = STATE['owner'] is not None
            return self._json(200, [{'step': s, 'done': done} for s in ('user', 'core_config', 'analytics', 'integration')])
        if path == '/api/onboarding/users':
            if STATE['owner'] is not None:return self._json(403, {'message': 'User step already done'})
            body = json.loads(self._body()); STATE['owner'] = body; STATE['client_id'] = body['client_id']
            return self._json(200, {'auth_code': 'auth-code-1'})
        if path == '/auth/token':
            form = dict(urllib.parse.parse_qsl(self._body().decode()))
            if form.get('client_id') != STATE['client_id']:return self._json(400, {'error': 'invalid_client'})
            if form.get('grant_type') == 'authorization_code' and form.get('code') == 'auth-code-1':return self._json(200, _issue())
            if form.get('grant_type') == 'refresh_token' and form.get('refresh_token') == STATE['refresh']:
                tokens = _issue(); del tokens['refresh_token']; return self._json(200, tokens)
            return self._json(400, {'error': 'invalid_grant'})
        if path == '/api/websocket' and 'websocket' in self.headers.get('Upgrade', '').lower():return self._websocket()
        if not path.startswith('/api/'):return self._json(404, {'message': 'Not found'})
        body = self._body()
        if not self._authorized():return self._json(401, {'message': 'Unauthorized'})
        if path.startswith('/api/onboarding/'):return self._json(200, {'auth_code': 'auth-code-2'} if path.endswith('/integration') else {})
        if path == '/api/config':return self._json(200, {'state': _state(), 'version': m.VERSIONS['homeassistant']})
        if path == '/api/':return self._json(200, {'message': 'API running.'})
        if path == '/api/stream':
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            for event in (b'data: one\n\n', b'data: two\n\n'):self.wfile.write(event); time.sleep(0.2)
            return
        return self._json(200, {'method': self.command, 'path': path, 'query': query, 'body': body.decode(errors='replace'),
            'content_type': self.headers.get('Content-Type'), 'authorization': self.headers.get('Authorization')})
    def _websocket(self):
        self.protocol_version = 'HTTP/1.1'
        self.send_response(101); self.send_header('Upgrade', 'websocket'); self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', m.ws_accept(self.headers['Sec-WebSocket-Key'])); self.end_headers()
        self.close_connection = True; send = self.wfile.write
        try:
            m.send_json(send, {'type': 'auth_required', 'ha_version': m.VERSIONS['homeassistant']}, False)
            hello = m.read_json(self.rfile)
            with LOCK:STATE['seen'].append(['websocket', hello.get('access_token')])
            if hello.get('access_token') not in STATE['access']:
                m.send_json(send, {'type': 'auth_invalid', 'message': 'Invalid access token or password'}, False); return
            m.send_json(send, {'type': 'auth_ok', 'ha_version': m.VERSIONS['homeassistant']}, False)
            while True:
                b0, data = m.read_frame(self.rfile)
                op = b0 & 0x0f
                if op == m.WS_CLOSE:m.write_frame(send, 0x80 | m.WS_CLOSE, data, False); return
                if op == 0x9:m.write_frame(send, 0x8A, data, False); continue  # ping -> pong with its payload
                if op != m.WS_TEXT:continue
                msg = json.loads(data)
                ok, result = _command(msg)
                m.send_json(send, {'id': msg.get('id'), 'type': 'result', 'success': ok, 'result': result}, False)
        except (OSError, EOFError, ValueError):
            return
    def __getattr__(self, name):
        if name.startswith('do_'):return self._answer
        raise AttributeError(name)
    def log_message(self, *args):pass

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--port', type=int, default=8123); p.add_argument('--running-after', type=float, default=0)
    p.add_argument('--never-running', action='store_true')
    a = p.parse_args(argv)
    STATE['running_at'] = float('inf') if a.never_running else time.monotonic() + a.running_after
    http.server.ThreadingHTTPServer(('0.0.0.0', a.port), Handler).serve_forever()

if __name__ == '__main__':
    sys.exit(main())
