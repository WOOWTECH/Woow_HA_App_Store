"""0.2.6 gateway side: the runtime pinned since 0.2.6 makes the same of the child's tools as 0.2.5's (management venv).

gateway_capture.py turns the child's tools/list (as v0.2.5's child listed it, fixtures/surface-0.2.5.json "child"; the
current child lists the same, test_unchanged_child.py) into what a client gets, and authorizes a fixed set of
tools/call requests, with this tree's gateway policy and the HA 15-tool table. fixtures/surface-0.2.5.json "gateway"
is the same capture with v0.2.5's gateway. Equal means: the same tools listed (names, the gateway's own inputSchema,
descriptions), the same arguments forwarded to the child, and the same JSON-RPC errors for refused calls (unknown or
disabled tools, invalid arguments with their reasons, writers without a grant). HA_OD_MCP_CODE / HA_OD_MCP_VENDOR: as
in test_surface.py.
"""
from pathlib import Path
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


class Unchanged(unittest.TestCase):
    def test_listed_tools_unchanged(self):
        for variant, before in FIXTURE['gateway']['listed'].items():
            with self.subTest(variant=variant):
                self.assertEqual(CURRENT['listed'][variant], before)
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
                    self.assertEqual(CURRENT['requests'][variant][case], before)
        refused = CURRENT['requests']['list_skills-disabled-no-grant']
        self.assertEqual(refused['create_project']['error'],
                         {'code': -32602, 'message': 'Unknown tool', 'data': {'tool': 'create_project'}})

    def test_the_whole_capture(self):
        self.assertEqual(CURRENT, FIXTURE['gateway'])


if __name__ == '__main__':
    unittest.main()
