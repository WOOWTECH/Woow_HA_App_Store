"""0.2.6 child side: the move to MCP Python SDK 2.3.0 changes nothing a client gets from the child (child venv).

surface_capture.py drives the child that child.setup() builds (tools/list and every tools/call case, failures
included) against a fake OpenDesign daemon; fixtures/surface-0.2.5.json holds the same capture of v0.2.5 on mcp 1.30.0.
Equal means: the same 15 tools in the same order with the same names, descriptions, input and output schemas, the same
results, and every failure answered with the same 'Error executing tool <name>: <code>' text (SDK 2 alone would show
'Error executing tool <name>'; the vendored keep_error_text restores the text). What the gateway makes of it:
test_unchanged_gateway.py. HA_OD_MCP_CODE / HA_OD_MCP_VENDOR: as in test_surface.py.
"""
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
BASELINE = json.loads((HERE / 'fixtures' / 'surface-0.2.5.json').read_text())['child']


class Unchanged(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HA_OD_MCP_CODE', 'HA_OD_MCP_VENDOR')}
        done = subprocess.run([sys.executable, '-B', '-W', 'ignore', str(HERE / 'surface_capture.py')],
                              env={**env, 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True, timeout=300)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.current = json.loads(done.stdout)

    def test_the_sdks_compared(self):
        self.assertEqual(BASELINE['sdk'], '1.30.0')
        self.assertEqual(self.current['sdk'], '2.3.0')
        self.assertEqual(importlib.metadata.version('mcp'), '2.3.0')

    def test_tools_list_unchanged(self):
        self.assertEqual([tool['name'] for tool in self.current['tools']['tools']],
                         [tool['name'] for tool in BASELINE['tools']['tools']])
        self.assertEqual(len(self.current['tools']['tools']), 15)
        for before, after in zip(BASELINE['tools']['tools'], self.current['tools']['tools']):
            with self.subTest(tool=before['name']):
                self.assertEqual(after, before)
        self.assertEqual(self.current['tools'], BASELINE['tools'])

    def test_every_call_unchanged(self):
        self.assertEqual(sorted(self.current['calls']), sorted(BASELINE['calls']))
        for case, before in sorted(BASELINE['calls'].items()):
            with self.subTest(case=case):
                self.assertEqual(self.current['calls'][case], before)

    def test_failures_keep_their_text(self):
        failures = {case: result['content'][0]['text'] for case, result in self.current['calls'].items()
                    if result.get('isError')}
        self.assertGreater(len(failures), 50)
        for case, text in failures.items():
            name = case.split('/')[-1] if case.startswith('daemon-') else case.split('/')[0]
            with self.subTest(case=case):
                self.assertRegex(text, r'^Error executing tool %s: [A-Z][A-Z_]+( status=\d{3})?$' % name)
        self.assertEqual(failures['daemon-down/health'], 'Error executing tool health: BACKEND_UNAVAILABLE')
        self.assertEqual(failures['get_project/unknown-project'],
                         'Error executing tool get_project: BACKEND_HTTP_ERROR status=404')
        self.assertEqual(failures['read_file/secret'], 'Error executing tool read_file: FILE_PATH_REFUSED')
        self.assertEqual(failures['create_project/busy'], 'Error executing tool create_project: BACKEND_BUSY')
        self.assertNotIn('/data/', json.dumps(failures))  # no daemon path or error text in a failure
        self.assertNotIn('/data/', json.dumps(self.current['calls']['list_runs']))  # nor in the runs


if __name__ == '__main__':
    unittest.main()
