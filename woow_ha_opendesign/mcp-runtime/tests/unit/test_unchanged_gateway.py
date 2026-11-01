"""0.2.6 gateway side: the runtime pinned since 0.2.6 makes the same of the child's tools as 0.2.5's (management venv).

gateway_capture.py turns the child's tools/list (as v0.2.5's child listed it, fixtures/surface-0.2.5.json "child"; the
current child lists the same, test_unchanged_child.py) into what a client gets, and authorizes a fixed set of
tools/call requests, with this tree's gateway policy and the HA 15-tool table. fixtures/surface-0.2.5.json "gateway"
is the same capture with v0.2.5's gateway. This draft permits only six reviewed inputSchema changes and the two
corresponding pattern-mismatch messages; all other listed fields, forwarded arguments and JSON-RPC outcomes remain
equal. HA_OD_MCP_CODE / HA_OD_MCP_VENDOR: as in test_surface.py.
"""
from pathlib import Path
import copy
import json
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
FIXTURE = json.loads((HERE / 'fixtures' / 'surface-0.2.5.json').read_text())

import gateway_capture  # noqa: E402  (sets the vendored and HA paths)

from mcp_admin_core import policy  # noqa: E402

from ha_opendesign_mcp import surface  # noqa: E402

CURRENT = gateway_capture.capture(FIXTURE['child'])
CHANGED_SCHEMAS = frozenset({'get_project', 'delete_project', 'list_project_files',
                             'get_file_info', 'read_file', 'send_message'})
CHANGED_ERROR_PATTERNS = {'get_project/not-a-uuid': ('get_project', 'project_id'),
                          'read_file/characters': ('read_file', 'file_path')}


class Unchanged(unittest.TestCase):
    def test_only_reviewed_input_schemas_change(self):
        for variant, before in FIXTURE['gateway']['listed'].items():
            with self.subTest(variant=variant):
                old_tools = {tool['name']: tool for tool in before['tools']}
                new_tools = {tool['name']: tool for tool in CURRENT['listed'][variant]['tools']}
                self.assertEqual(set(new_tools), set(old_tools))
                for name, tool in new_tools.items():
                    if name in CHANGED_SCHEMAS:
                        self.assertEqual(tool['inputSchema'], policy.declared_schema(surface.TABLE[name].arguments))
                        self.assertEqual({**tool, 'inputSchema': old_tools[name]['inputSchema']}, old_tools[name])
                    else:
                        self.assertEqual(tool, old_tools[name])
        listed = CURRENT['listed']['granted']['tools']
        self.assertEqual(len(listed), 15)
        for tool in listed:  # the schema a client sees is the gateway's own argument model, not the child's
            self.assertEqual(tool['inputSchema'], policy.declared_schema(surface.TABLE[tool['name']].arguments))
        self.assertEqual(len(CURRENT['listed']['list_skills-disabled-no-grant']['tools']), 11)

    def test_requests_unchanged(self):
        self.assertEqual(sorted(CURRENT['requests']), sorted(FIXTURE['gateway']['requests']))
        for variant, cases in FIXTURE['gateway']['requests'].items():
            for case, before in cases.items():
                with self.subTest(variant=variant, case=case):
                    current = copy.deepcopy(CURRENT['requests'][variant][case])
                    if case in CHANGED_ERROR_PATTERNS:
                        name, field = CHANGED_ERROR_PATTERNS[case]
                        detail = current['error']['data']['errors']
                        self.assertEqual(len(detail), 1)
                        self.assertEqual(detail[0]['field'], field)
                        self.assertEqual(detail[0]['type'], 'string_pattern_mismatch')
                        pattern = policy.declared_schema(surface.TABLE[name].arguments)['properties'][field]['pattern']
                        self.assertEqual(detail[0]['message'], "String should match pattern '%s'" % pattern)
                        detail[0]['message'] = before['error']['data']['errors'][0]['message']
                    self.assertEqual(current, before)
        refused = CURRENT['requests']['list_skills-disabled-no-grant']
        self.assertEqual(refused['create_project']['error'],
                         {'code': -32602, 'message': 'Unknown tool', 'data': {'tool': 'create_project'}})

    def test_whole_capture_diff_is_only_reviewed_schema_and_pattern_text(self):
        current = copy.deepcopy(CURRENT)
        for variant, listed in current['listed'].items():
            old = {tool['name']: tool for tool in FIXTURE['gateway']['listed'][variant]['tools']}
            for tool in listed['tools']:
                if tool['name'] in CHANGED_SCHEMAS:
                    tool['inputSchema'] = old[tool['name']]['inputSchema']
        for variant, cases in current['requests'].items():
            for case in CHANGED_ERROR_PATTERNS:
                cases[case]['error']['data']['errors'][0]['message'] = (
                    FIXTURE['gateway']['requests'][variant][case]['error']['data']['errors'][0]['message'])
        self.assertEqual(current, FIXTURE['gateway'])


if __name__ == '__main__':
    unittest.main()
