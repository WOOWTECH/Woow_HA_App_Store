"""Root metadata lookup through real HTTP, with disposable fake credentials."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'rootfs/usr/local/libexec/ha-opendesign-return.py'
spec = importlib.util.spec_from_file_location('ha_return', SOURCE)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
TOKEN = 'fake-supervisor-secret-do-not-print'
OPTION = 'fake-private-option-do-not-print'


@contextlib.contextmanager
def server(body=b'', status=200, location=None, delay=0, drip=0):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get('Authorization')))
            time.sleep(delay)
            self.send_response(status)
            if location:
                self.send_header('Location', location)
            self.end_headers()
            try:
                if drip:
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(drip)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{http.server_port}/addons/self/info', requests
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def metadata(slug):
    return json.dumps({'result': 'ok', 'data': {'slug': slug, 'options': {'secret': OPTION}}}).encode()


class ReturnMetadataTests(unittest.TestCase):
    def lookup(self, body, **kwargs):
        with server(body, **kwargs) as (url, _requests):
            return helper.return_target(TOKEN, endpoint=url)

    def test_installed_slug_and_store_prefix_are_used_without_private_fields(self):
        for slug in ['1b7b4ce7_woow_ha_opendesign', 'a1234def_woow_ha_opendesign', 'local_woow_ha_opendesign']:
            with self.subTest(slug=slug), server(metadata(slug)) as (url, requests):
                target = helper.return_target(TOKEN, endpoint=url)
                self.assertEqual(target, ('/app/' + slug, '← 返回 OpenDesign'))
                self.assertEqual(requests, [('/addons/self/info', 'Bearer ' + TOKEN)])
                rendered = helper.nginx_config(target)
                self.assertNotIn(TOKEN, rendered)
                self.assertNotIn(OPTION, rendered)
                self.assertNotIn('options', rendered)

    def test_malformed_and_injectable_slug_fall_back_to_native_root(self):
        for slug in [None, {}, [], '', '/plugins', '//evil.test', '../bad', 'a/b', 'a?b', 'a#b',
                     'a"; include /etc/passwd; #', 'a\nb', 'a$b', 'a\\b', 'a%2fb', 'é', 'a' * 129]:
            with self.subTest(slug=slug):
                self.assertEqual(self.lookup(metadata(slug)), ('/', '← 返回 Home Assistant'))

    def test_errors_and_oversized_response_fall_back_without_leaking(self):
        bodies = [b'not json ' + TOKEN.encode(), b'null', b'[]', b'{"result":"error"}',
                  b'{"result":"ok","data":null}', b'x' * (helper.MAX_RESPONSE_BYTES + 1)]
        for body in bodies:
            with self.subTest(size=len(body)):
                self.assertEqual(self.lookup(body), ('/', '← 返回 Home Assistant'))
        self.assertEqual(self.lookup(metadata('valid_slug'), status=500), ('/', '← 返回 Home Assistant'))

    def test_proxy_environment_cannot_receive_authorization(self):
        with server(metadata('real_slug')) as (url, requests), server() as (proxy, leaked):
            env = {key: proxy for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']}
            env.update(NO_PROXY='', no_proxy='')
            with patch.dict(os.environ, env):
                self.assertEqual(helper.return_target(TOKEN, endpoint=url)[0], '/app/real_slug')
            self.assertEqual(len(requests), 1)
            self.assertEqual(leaked, [])

    def test_redirect_is_not_followed_or_given_authorization(self):
        with server(metadata('wrong_slug')) as (destination, leaked):
            with server(status=302, location=destination.replace('127.0.0.1', 'localhost')) as (url, requests):
                self.assertEqual(helper.return_target(TOKEN, endpoint=url), ('/', '← 返回 Home Assistant'))
                self.assertEqual(len(requests), 1)
                self.assertEqual(leaked, [])

    def test_whole_lookup_deadline_bounds_slow_response(self):
        with server(metadata('late_slug'), delay=1) as (url, _requests):
            start = time.monotonic()
            self.assertEqual(helper.return_target(TOKEN, endpoint=url, deadline=0.15), ('/', '← 返回 Home Assistant'))
            self.assertLess(time.monotonic() - start, 0.6)

    def test_whole_deadline_also_bounds_a_response_that_keeps_delivering_bytes(self):
        with server(metadata('slow_slug'), drip=0.03) as (url, _requests):
            start = time.monotonic()
            self.assertEqual(helper.return_target(TOKEN, endpoint=url, deadline=0.15), ('/', '← 返回 Home Assistant'))
            self.assertLess(time.monotonic() - start, 0.6)

    def test_missing_token_never_contacts_supervisor(self):
        with server(metadata('wrong_slug')) as (url, requests):
            self.assertEqual(helper.return_target('', endpoint=url), ('/', '← 返回 Home Assistant'))
            self.assertEqual(requests, [])

    def test_entrypoint_failure_emits_only_safe_fallback_config(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {'SUPERVISOR_TOKEN': TOKEN}), patch.object(helper, 'return_target', side_effect=RuntimeError(TOKEN + OPTION)):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                helper.main()
        self.assertEqual(out.getvalue(), 'set $ha_return_path "/";\nset $ha_return_label "← 返回 Home Assistant";\n')
        self.assertEqual(err.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
