#!/usr/bin/env python3
"""Offline endpoint, diagnostics and hard-deadline checks; no credentials needed."""
import contextlib
from email.message import Message
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import signal
import time
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location(
    'registry_preflight', Path(__file__).resolve().parents[1] / '.github/scripts/registry-preflight.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CHALLENGE = 'Bearer realm="https://jcr-prod.woowtech.io/v2/token",service="jcr-prod.woowtech.io"'


class Response(io.BytesIO):
    def __init__(self, status=401, headers=None, body=b'{}'):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def geturl(self):
        return module.ENDPOINT


class RegistryPreflightTests(unittest.TestCase):
    def probe(self, status=401, headers=None, body=b'{}'):
        return module.probe(lambda request, timeout: Response(status, headers, body))

    def test_anonymous_request_has_descriptive_user_agent_and_bounded_timeout(self):
        def opener(request, timeout):
            self.assertEqual(request.full_url, 'https://jcr-prod.woowtech.io/v2/')
            self.assertEqual(request.get_method(), 'GET')
            self.assertIsNone(request.data)
            headers = dict(request.header_items())
            self.assertEqual(set(headers), {'User-agent', 'Accept'})
            self.assertIn('WoowTech-HA-OpenDesign-RegistryPreflight/', headers['User-agent'])
            self.assertNotIn('Docker-Client/', headers['User-agent'])
            self.assertEqual(timeout, 20)
            return Response(headers={'WWW-Authenticate': CHALLENGE})
        self.assertIsNone(module.probe(opener)['error_code'])

    def test_default_transport_disables_environment_proxies_and_redirects(self):
        with patch.object(module.urllib.request, 'build_opener') as factory:
            factory.return_value.open.return_value = Response(headers={'WWW-Authenticate': CHALLENGE})
            module.probe()
        handlers = factory.call_args.args
        self.assertTrue(any(isinstance(h, module.urllib.request.ProxyHandler) and h.proxies == {} for h in handlers))
        redirect = next(h for h in handlers if isinstance(h, module.NoRedirect))
        self.assertIsNone(redirect.redirect_request(None, None, 302, '', {}, 'https://example.invalid/'))

    def test_401_accepts_expected_challenge_and_case_insensitive_headers(self):
        result = self.probe(headers={'www-authenticate': CHALLENGE, 'Content-Type': 'application/json;charset=UTF-8'})
        self.assertEqual(result['status'], 401)
        self.assertEqual(result['content_type'], 'application/json')
        self.assertIsNone(result['error_code'])

    def test_401_refuses_missing_wrong_or_ambiguous_challenge(self):
        values = ['', 'Basic realm="registry"', CHALLENGE.replace('https:', 'http:'),
                  CHALLENGE.replace('jcr-prod.woowtech.io/v2/token', 'jcr-prod.woowtech.io.attacker.invalid/v2/token'),
                  CHALLENGE.replace('/v2/token', '/v2/token?redirect=https://example.invalid/'),
                  CHALLENGE.replace('https://', 'https://user@'),
                  CHALLENGE.replace('/v2/token', ':444/v2/token'),
                  CHALLENGE + ',realm="https://jcr-prod.woowtech.io/v2/token"',
                  CHALLENGE + ', Basic realm="other"',
                  CHALLENGE.replace('service="jcr-prod.woowtech.io"', 'service="example.invalid"')]
        for challenge in values:
            with self.subTest(challenge=challenge):
                self.assertEqual(self.probe(headers={'WWW-Authenticate': challenge})['error_code'], 'invalid_bearer_challenge')

    def test_200_requires_registry_v2_header(self):
        self.assertIsNone(self.probe(200, {'Docker-Distribution-Api-Version': 'registry/2.0'})['error_code'])
        for headers in ({}, {'Docker-Distribution-Api-Version': 'registry/1.0'}):
            self.assertEqual(self.probe(200, headers)['error_code'], 'registry_header_missing_or_invalid')

    def test_duplicate_registry_headers_cannot_hide_a_wrong_realm_or_version(self):
        for status, name, wrong, valid in (
                (401, 'WWW-Authenticate', CHALLENGE.replace('https:', 'http:'), CHALLENGE),
                (200, 'Docker-Distribution-Api-Version', 'registry/1.0', 'registry/2.0')):
            headers = Message()
            headers[name] = wrong
            headers[name] = valid
            self.assertEqual(self.probe(status, headers)['error_code'], 'ambiguous_registry_headers')

    def test_transport_endpoint_change_is_refused(self):
        response = Response(headers={'WWW-Authenticate': CHALLENGE})
        response.geturl = lambda: 'https://example.invalid/v2/'
        result = module.probe(lambda request, timeout: response)
        self.assertEqual(result['error_code'], 'unexpected_endpoint')

    def test_redirect_and_other_statuses_fail_closed(self):
        for status in (301, 302, 303, 307, 308):
            self.assertEqual(self.probe(status, {'Location': 'https://example.invalid/'})['error_code'], 'redirect_refused')
        for status in (201, 204, 404, 429, 500, 503):
            self.assertEqual(self.probe(status)['error_code'], 'unexpected_http_status')

    def test_403_returns_known_code_hash_and_restricted_headers_only(self):
        body = b'<html>error code: 1010 PRIVATE_BODY_SENTINEL</html>'
        headers = {'Server': 'cloudflare', 'Content-Type': 'text/html; charset=UTF-8',
                   'CF-Ray': '9abc1234def56789-TPE', 'Set-Cookie': 'DO_NOT_PRINT',
                   'WWW-Authenticate': 'DO_NOT_PRINT', 'Location': 'https://example.invalid/DO_NOT_PRINT'}
        result = self.probe(403, headers, body)
        self.assertEqual(set(result), {'status', 'content_type', 'server', 'cf_ray', 'error_code', 'body_sha256'})
        self.assertEqual(result['error_code'], 'cloudflare_1010')
        self.assertEqual(result['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(result['cf_ray'], '9abc1234def56789-TPE')
        self.assertNotIn('DO_NOT_PRINT', json.dumps(result))
        self.assertNotIn('PRIVATE_BODY_SENTINEL', json.dumps(result))
        self.assertEqual(self.probe(403, body=b'error code: 9876')['error_code'], 'http_403')

    def test_unexpected_header_text_is_not_reflected(self):
        result = self.probe(403, {'Server': '<html>body</html>', 'CF-Ray': 'bad\n::error::injected',
                                  'Content-Type': 'not a media type'})
        self.assertIsNone(result['server'])
        self.assertIsNone(result['cf_ray'])
        self.assertIsNone(result['content_type'])

    def test_http_error_response_is_diagnosed_without_exception_text(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(module.ENDPOINT, 403, 'DO_NOT_PRINT',
                                         {'Content-Type': 'text/html'}, io.BytesIO(b'error code: 1020'))
        self.assertEqual(module.probe(opener)['error_code'], 'cloudflare_1020')

    def test_oversized_body_is_refused_without_claiming_complete_hash(self):
        result = self.probe(403, body=b'x' * (module.MAX_BODY_BYTES + 1))
        self.assertEqual(result['error_code'], 'response_too_large')
        self.assertIsNone(result['body_sha256'])

    def test_main_emits_one_safe_json_and_exit_status(self):
        for status, code, exit_code in ((401, None, 0), (403, 'http_403', 1)):
            with patch.object(module, 'probe', return_value={**module.empty_result(), 'status': status, 'error_code': code}):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(module.main(), exit_code)
                self.assertEqual(json.loads(output.getvalue())['error_code'], code)
                self.assertEqual(len(output.getvalue().splitlines()), 1)

    def test_network_exceptions_do_not_print_arbitrary_error_text(self):
        for error, expected in ((urllib.error.URLError('DO_NOT_PRINT'), 'network_error'),
                                (TimeoutError('DO_NOT_PRINT'), 'network_timeout')):
            output = io.StringIO()
            with patch.object(module, 'probe', side_effect=error), contextlib.redirect_stdout(output):
                self.assertEqual(module.main(), 1)
            self.assertEqual(json.loads(output.getvalue())['error_code'], expected)
            self.assertNotIn('DO_NOT_PRINT', output.getvalue())

    @unittest.skipUnless(hasattr(signal, 'setitimer'), 'Linux runner deadline requires setitimer')
    def test_hard_deadline_bounds_even_blocked_dns_or_body_read(self):
        output = io.StringIO()
        old_handler = signal.getsignal(signal.SIGALRM)
        started = time.monotonic()
        with patch.object(module, 'DEADLINE_SECONDS', 0.05), \
                patch.object(module, 'probe', side_effect=lambda: time.sleep(5)), contextlib.redirect_stdout(output):
            self.assertEqual(module.main(), 1)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(json.loads(output.getvalue())['error_code'], 'network_timeout')
        self.assertEqual(signal.getsignal(signal.SIGALRM), old_handler)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))


if __name__ == '__main__':
    unittest.main()
