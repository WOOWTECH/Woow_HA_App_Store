"""Stdlib-only tests of the 0.2.1 HA overlay rules (od_rules.py) and the one-time default grants (defaults.py).

Run by tests/run.sh with the system Python, and by tests/unit/run.sh in the pinned virtual environments.
HA_OD_MCP_CODE: the directory that holds ha_opendesign_mcp (default: this repository's mcp-runtime).
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1])))

from ha_opendesign_mcp import defaults, od_rules  # noqa: E402

FIXTURES = HERE / 'fixtures'
PROJECT = '76c45d7a-3147-45cf-a3f4-295ee256e48e'
OTHER = '11111111-2222-4333-8444-555555555555'


def parse(name, chunk=None, **kwargs):
    stream = od_rules.ChatStream(**kwargs)
    data = (FIXTURES / name).read_bytes()
    size = chunk or len(data)
    for start in range(0, len(data), size):
        if not stream.feed(data[start:start + size]):
            break
    else:
        stream.interrupted()
    return stream


class SecretNames(unittest.TestCase):
    REFUSED = ('.env', '.env.local', '.ENV', 'config/.env.production', '.git/config', '.ssh/id_rsa', 'id_rsa',
               'id_ed25519.pub', 'keys/server.pem', 'tls.KEY', 'cert.p12', 'store.pfx', 'app.jks', 'a.keystore',
               'vault.kdbx', 'credentials.json', 'aws_credentials', 'gcp-credential.txt', 'client_secret.json',
               'secrets.yaml', 'my.secret.txt', 'passwords.txt', 'htpasswd', 'etc/passwd', 'prod.env', 'env.js',
               'private_key.txt', 'privatekey', 'apikey.txt', 'openai_api_key', 'api-key.md', '.npmrc', '.netrc',
               '.git-credentials', 'authorized_keys', 'known_hosts', 'secret/index.html', 'backup.gpg', 'a.asc',
               'vpn.ovpn', 'shadow')
    ALLOWED = ('index.html', 'src/app.js', 'assets/logo.svg', 'design-tokens.json', 'README.md', 'styles/main.css',
               'keyboard.html', 'monkey.png', 'environment.md', 'identity.html', 'public/key-visual.png',
               'docs/sign-in-page.md')

    def test_refused(self):
        for path in self.REFUSED:
            with self.subTest(path=path):
                self.assertTrue(od_rules.secret_like(path))

    def test_allowed(self):
        for path in self.ALLOWED:
            with self.subTest(path=path):
                self.assertFalse(od_rules.secret_like(path))
                self.assertIsNone(od_rules.file_path_problem(path))

    def test_path_rules(self):
        self.assertEqual(od_rules.file_path_problem('../x'), 'relative non-traversing path required')
        self.assertEqual(od_rules.file_path_problem('/abs.html'), 'relative non-traversing path required')
        self.assertEqual(od_rules.file_path_problem('a//b'), 'relative non-traversing path required')
        self.assertEqual(od_rules.file_path_problem('a/./b'), 'relative non-traversing path required')
        self.assertEqual(od_rules.file_path_problem('a%2e%2e'), 'path characters not allowed')
        self.assertEqual(od_rules.file_path_problem('a\\b'), 'path characters not allowed')
        self.assertEqual(od_rules.file_path_problem('x' * 257), 'path characters not allowed')
        self.assertEqual(od_rules.file_path_problem('.env'), 'secret-like file name refused')
        self.assertEqual(od_rules.file_path_problem(None), 'path characters not allowed')


class ReadFileRules(unittest.TestCase):
    LISTING = {'files': [
        {'name': 'index.html', 'path': 'index.html', 'localPath': '/data/opendesign/projects/x/index.html',
         'type': 'file', 'size': 12, 'kind': 'html'},
        {'name': 'sub', 'path': 'sub', 'type': 'directory'},
        {'name': 'odd', 'path': 'odd.txt', 'type': 'file', 'size': 'big'}]}

    def test_listed_file(self):
        self.assertEqual(od_rules.listed_file(self.LISTING, 'index.html'), 12)
        self.assertIsNone(od_rules.listed_file(self.LISTING, 'sub'))
        self.assertIsNone(od_rules.listed_file(self.LISTING, '.env'))
        self.assertEqual(od_rules.listed_file(self.LISTING, 'odd.txt'), -1)
        with self.assertRaises(ValueError):
            od_rules.listed_file({'files': 'x'}, 'index.html')

    def test_decode_text(self):
        self.assertEqual(od_rules.decode_text('<h1>héllo</h1>\n\t'.encode()), '<h1>héllo</h1>\n\t')
        self.assertEqual(od_rules.decode_text('\ufeffabc'.encode()), 'abc')
        self.assertEqual(od_rules.decode_text(b'\x1b[31mred\x1b[0m'), '\x1b[31mred\x1b[0m')
        self.assertIsNone(od_rules.decode_text(b'\xff\xfe'))
        self.assertIsNone(od_rules.decode_text(b'PNG\x00\x01'))
        self.assertIsNone(od_rules.decode_text(b'abc\x07'))


class Connectors(unittest.TestCase):
    def test_positive_projection(self):
        body = {'connectors': [
            {'id': 'github', 'name': 'GitHub', 'provider': 'composio', 'category': 'Developer', 'status': 'connected',
             'description': 'Search repos', 'toolCount': 2, 'auth': {'provider': 'composio', 'configured': True,
                                                                      'accessToken': 'tok-should-not-leak',
                                                                      'accountLabel': 'someone@example.com'},
             'url': 'https://example.invalid/callback', 'localPath': '/data/opendesign/connectors/github',
             'tools': [{'name': 'github.github_search_repositories', 'inputSchemaJson': {'type': 'object'}},
                       {'name': 'bad name with spaces'}],
             'allowedToolNames': ['github.github_search_repositories']},
            {'id': 'notion', 'name': 'Notion\u202e\x07', 'status': 'available', 'allowedToolNames': ['notion.notion_search']},
            {'id': '../../etc', 'name': 'bad id'},
            'not a dict']}
        result = od_rules.project_connectors(body)
        text = json.dumps(result)
        for leaked in ('tok-should-not-leak', 'someone@example.com', 'example.invalid', '/data/', 'Search repos',
                       'inputSchemaJson', 'bad name', '../../etc'):
            self.assertNotIn(leaked, text)
        self.assertEqual(result['total'], 4)
        self.assertFalse(result['truncated'])
        github, notion = result['connectors']
        self.assertEqual(github, {'id': 'github', 'name': 'GitHub', 'provider': 'composio', 'category': 'Developer',
                                  'status': 'connected', 'configured': True, 'toolCount': 2,
                                  'tools': ['github.github_search_repositories']})
        self.assertEqual(notion['name'], 'Notion')
        self.assertEqual(notion['tools'], ['notion.notion_search'])
        self.assertIsNone(notion['configured'])
        self.assertEqual(set(github), {'id', 'name', 'provider', 'category', 'status', 'configured', 'toolCount',
                                       'tools'})

    def test_bounds(self):
        body = {'connectors': [{'id': 'c%d' % i, 'name': 'x' * 500, 'tools': [{'name': 't%d' % j} for j in range(80)]}
                               for i in range(od_rules.CONNECTOR_LIMIT + 5)]}
        result = od_rules.project_connectors(body)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['connectors']), od_rules.CONNECTOR_LIMIT)
        self.assertEqual(len(result['connectors'][0]['tools']), od_rules.CONNECTOR_TOOL_LIMIT)
        self.assertTrue(result['connectors'][0]['toolsTruncated'])
        self.assertEqual(len(result['connectors'][0]['name']), 128)
        with self.assertRaises(ValueError):
            od_rules.project_connectors({'error': 'x'})


class Runs(unittest.TestCase):
    """0.2.6: list_runs' projection, kept from the vendored output_policy.rows of 0.2.1-0.2.5."""

    def test_projection(self):
        body = {'runs': [{'id': 'r1', 'projectId': PROJECT, 'status': 'failed', 'error': 'auth failed at /data/x',
                          'eventsLogPath': '/data/opendesign/runs/r1/events.jsonl', 'agentId': 'claude'},
                         {'id': 'r2', 'projectId': None, 'status': 7, 'extra': {'nested': True}},
                         {'id': ['not', 'kept'], 'status': 'x' * 300}],
                'awaitingInputProjectIds': [PROJECT]}
        self.assertEqual(od_rules.run_rows(body), {'runs': [
            {'id': 'r1', 'projectId': PROJECT, 'status': 'failed'},
            {'id': 'r2', 'projectId': None, 'status': 7},
            {'projectId': None, 'status': 'x' * 256}], 'truncated': False})
        self.assertNotIn('/data', json.dumps(od_rules.run_rows(body)))

    def test_bounds(self):
        many = od_rules.run_rows({'runs': [{'id': str(n)} for n in range(101)]})
        self.assertEqual(len(many['runs']), 100)
        self.assertTrue(many['truncated'])
        self.assertEqual(od_rules.run_rows([{'id': 'a'}]), {'runs': [{'id': 'a', 'projectId': None, 'status': None}],
                                                           'truncated': False})
        for body in ({}, {'runs': {}}, 'x', None, {'runs': ['x']}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                od_rules.run_rows(body)


class ChatStreamParser(unittest.TestCase):
    def assert_clean(self, result):
        text = json.dumps(result)
        for leaked in ('/data/', 'cwd', 'Claude Code could not', 'Unauthorized', 'openai.com', 'req_0000',
                       'toolTokenExpiresAt', 'details'):
            self.assertNotIn(leaked, text)

    def test_claude_auth_failure_dict_error(self):
        for chunk in (None, 1, 7, 64):
            with self.subTest(chunk=chunk):
                result = od_rules.chat_result(parse('chat-claude-auth.sse', chunk), PROJECT)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['runId'], 'e9138737-f40d-4766-9153-ddb8407177f9')
                self.assertEqual(result['projectId'], PROJECT)
                self.assertEqual(result['errorCode'], 'AGENT_AUTH_REQUIRED')
                self.assertEqual(result['failureCategory'], 'auth')
                self.assertIn('CLI Terminal', result['hint'])
                self.assertEqual(result['agentResponse'], 'Not logged in · Please run /login')
                self.assert_clean(result)

    def test_string_error_and_crlf(self):
        data = (FIXTURES / 'chat-string-error.sse').read_bytes().replace(b'\n', b'\r\n')
        stream = od_rules.ChatStream()
        stream.feed(data)
        result = od_rules.chat_result(stream, OTHER)
        # The string `error` is not a code: the run_retry_finished code is used, the status comes from `end`.
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errorCode'], 'AGENT_AUTH_REQUIRED')
        self.assertEqual(result['projectId'], '5a1f1c2e-8f0b-4d7e-9a43-2c1e7b9d0f12')
        self.assert_clean(result)

    def test_string_error_only(self):
        stream = od_rules.ChatStream()
        stream.feed(b'event: error\ndata: {"error":"spawn failed at /usr/bin/x","message":"boom"}\n\n')
        stream.interrupted()
        result = od_rules.chat_result(stream, OTHER)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errorCode'], 'AGENT_ERROR')
        self.assertEqual(result['hint'], od_rules.GENERIC_HINT)
        self.assertNotIn('/usr/bin', json.dumps(result))
        stream = od_rules.ChatStream()
        stream.feed(b'event: error\ndata: {"error":"RATE_LIMITED","message":"slow down"}\n\n')
        self.assertEqual(od_rules.chat_result(stream, OTHER)['errorCode'], 'RATE_LIMITED')

    def test_unknown_agent_no_start(self):
        result = od_rules.chat_result(parse('chat-unknown-agent.sse'), OTHER)
        self.assertEqual(result, {'projectId': OTHER, 'runId': None, 'status': 'failed',
                                  'errorCode': 'AGENT_UNAVAILABLE', 'hint': od_rules.HINTS['AGENT_UNAVAILABLE']})

    def test_success(self):
        result = od_rules.chat_result(parse('chat-success.sse', 5), OTHER)
        self.assertEqual(result, {'projectId': '62720fb2-1795-474e-ab8c-f03657706bed',
                                  'runId': '29a8b67a-faaf-44ae-b66f-8bf2479b5442', 'status': 'succeeded',
                                  'agentResponse': 'Hi! What would you like to design today?\n\n'})

    def test_stops_after_end(self):
        stream = parse('chat-success.sse')
        self.assertFalse(stream.feed(b'event: agent\ndata: {"type":"text_delta","delta":"late"}\n\n'))
        self.assertNotIn('late', od_rules.chat_result(stream, OTHER)['agentResponse'])

    def test_agent_text_bounded(self):
        stream = od_rules.ChatStream(text_max=10)
        stream.feed(b'event: start\ndata: {"runId":"%s"}\n\n' % OTHER.encode())
        for _ in range(5):
            stream.feed(b'event: agent\ndata: {"type":"text_delta","delta":"abcdef"}\n\n')
        stream.feed(b'event: end\ndata: {"status":"succeeded","code":0}\n\n')
        result = od_rules.chat_result(stream, PROJECT)
        self.assertEqual(result['agentResponse'], 'abcdefabcd')
        self.assertTrue(result['agentResponseTruncated'])

    def test_deadline(self):
        now = [0.0]
        stream = od_rules.ChatStream(deadline=10.0, clock=lambda: now[0])
        self.assertTrue(stream.feed(b'event: start\ndata: {"runId":"%s","projectId":"%s"}\n\n'
                                    % (OTHER.encode(), PROJECT.encode())))
        now[0] = 10.0
        self.assertFalse(stream.feed(b': keepalive\n\n'))
        result = od_rules.chat_result(stream, PROJECT)
        self.assertEqual(result['status'], 'running')
        self.assertEqual(result['note'], od_rules.WAITING_NOTE)
        self.assertFalse(stream.feed(b'event: end\ndata: {"status":"succeeded"}\n\n'))

    def test_size_bounds(self):
        stream = od_rules.ChatStream(max_bytes=100)
        self.assertFalse(stream.feed(b'x' * 101))
        self.assertEqual(od_rules.chat_result(stream, PROJECT)['status'], 'unknown')
        stream = od_rules.ChatStream()
        stream.feed(b'event: start\ndata: {"runId":"%s"}\n\n' % OTHER.encode())
        self.assertFalse(stream.feed(b'data: ' + b'y' * (od_rules.CHAT_MAX_LINE + 1)))
        self.assertEqual(od_rules.chat_result(stream, PROJECT)['status'], 'running')

    def test_stream_closed_early(self):
        stream = od_rules.ChatStream()
        stream.feed(b'event: start\ndata: {"runId":"%s"}\n\nevent: agent\ndata: {"type":"text_delta","delta":"hi"}\n\n'
                    % OTHER.encode())
        stream.interrupted()
        result = od_rules.chat_result(stream, PROJECT)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['agentResponse'], 'hi')

    def test_end_without_status(self):
        stream = od_rules.ChatStream()
        stream.feed(b'event: end\ndata: {"code":0}\n\n')
        self.assertEqual(stream.status(), 'succeeded')
        stream = od_rules.ChatStream()
        stream.feed(b'event: end\ndata: {"code":1,"status":"weird"}\n\n')
        self.assertEqual(od_rules.chat_result(stream, PROJECT)['errorCode'], 'AGENT_RUN_FAILED')
        stream = od_rules.ChatStream()
        stream.feed(b'event: end\ndata: {"status":"canceled"}\n\n')
        self.assertEqual(stream.status(), 'cancelled')

    def test_malformed_events_ignored(self):
        stream = od_rules.ChatStream()
        stream.feed(b'event: start\ndata: not json\n\nevent: start\ndata: [1]\n\n'
                    b'event: start\ndata: {"runId":"../../x","projectId":"/data/x"}\n\n'
                    b'data: {"runId":"%s"}\n\n' % OTHER.encode())  # no event name: "message", not start
        stream.interrupted()
        self.assertEqual(od_rules.chat_result(stream, PROJECT),
                         {'projectId': PROJECT, 'runId': None, 'status': 'unknown', 'note': od_rules.WAITING_NOTE})


class FakeStore:
    """The parts of the vendored ProductStore that defaults.apply uses."""

    def __init__(self, directory, grants=(), disabled=()):
        self.directory = Path(directory)
        self.state = types.SimpleNamespace(enabled_write_tools=list(grants), disabled=list(disabled))
        self.updates = []

    def load(self):
        return types.SimpleNamespace(**vars(self.state))

    def update(self, **changes):
        self.updates.append(changes)
        for key, value in changes.items():
            setattr(self.state, key, value)


class DefaultGrants(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def marker(self):
        return json.loads((self.dir / defaults.MARKER).read_text())

    def test_fresh(self):
        store = FakeStore(self.dir)
        record = defaults.apply(store)
        self.assertEqual(store.state.enabled_write_tools, ['create_project', 'delete_project', 'send_message'])
        self.assertEqual(record['granted'], ['create_project', 'delete_project', 'send_message'])
        self.assertEqual(self.marker(), record)
        self.assertEqual(oct((self.dir / defaults.MARKER).stat().st_mode & 0o777), '0o600')
        self.assertEqual([p.name for p in self.dir.iterdir()], [defaults.MARKER])  # no temporary file left

    def test_existing_020_state_keeps_grants_and_disabled(self):
        store = FakeStore(self.dir, grants=['delete_project'], disabled=['send_message', 'list_runs'])
        record = defaults.apply(store)
        self.assertEqual(store.state.enabled_write_tools, ['delete_project', 'create_project'])
        self.assertEqual(store.state.disabled, ['send_message', 'list_runs'])
        self.assertEqual(record['granted'], ['create_project'])
        self.assertEqual(record['left_disabled'], ['send_message'])

    def test_admin_disabled_delete_project(self):
        store = FakeStore(self.dir, disabled=['delete_project'])
        defaults.apply(store)
        self.assertEqual(store.state.enabled_write_tools, ['create_project', 'send_message'])

    def test_applied_once(self):
        store = FakeStore(self.dir)
        defaults.apply(store)
        store.state.enabled_write_tools = []  # the administrator revokes every grant afterwards
        self.assertIsNone(defaults.apply(store))
        self.assertIsNone(defaults.apply(store))
        self.assertEqual(store.state.enabled_write_tools, [])
        self.assertEqual(len(store.updates), 1)

    def test_nothing_to_grant_still_marks(self):
        store = FakeStore(self.dir, grants=['send_message', 'create_project', 'delete_project'])
        record = defaults.apply(store)
        self.assertEqual(record['granted'], [])
        self.assertEqual(store.updates, [])
        self.assertTrue(defaults.applied(str(self.dir)))

    def test_symlink_marker_refused(self):
        (self.dir / 'elsewhere').write_text('{}')
        os.symlink(self.dir / 'elsewhere', self.dir / defaults.MARKER)
        with self.assertRaises(RuntimeError):
            defaults.apply(FakeStore(self.dir))


if __name__ == '__main__':
    unittest.main(verbosity=1)
