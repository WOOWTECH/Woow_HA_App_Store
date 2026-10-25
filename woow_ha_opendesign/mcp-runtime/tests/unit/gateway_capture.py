"""0.2.6: what the built-in server's gateway makes of a child's tools/list and of tools/call requests, recorded for
test_unchanged_gateway.py (management Python, requirements/management.txt).

  gateway_capture.py <child capture JSON (surface_capture.py)>

With the HA overlay's 15-tool table and an OpenDesign state (connection set, the three writers granted, or the
variants below), prints one JSON document:

  "listed":   the tools/list a client gets: the vendored policy.filter_list() of the child's list (name, the gateway's
              own inputSchema, description...), for every tool enabled and for list_skills disabled with no writer
              granted
  "requests": for each tools/call case, the arguments the gateway forwards (normalized by the tool's argument model)
              or the JSON-RPC error a client gets instead (ToolCallRefused.error(): unknown or disabled tool, invalid
              arguments with the sanitized reasons, a writer without its grant)

HA_OD_MCP_CODE / HA_OD_MCP_VENDOR select the tree, so the same script recorded the "gateway" part of
fixtures/surface-0.2.5.json from v0.2.5 (its schema 3 state came from the vendored products.ProductState; since 0.2.6
from ha_opendesign_mcp.state.BuiltinState: the same model).
"""
import copy
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CODE = os.environ.get('HA_OD_MCP_CODE', str(HERE.parents[1]))
VENDOR = os.environ.get('HA_OD_MCP_VENDOR', str(HERE.parents[1] / 'vendor'))
sys.path[:0] = [str(Path(VENDOR) / 'packages' / 'mcp-admin-core'), CODE]

from mcp_admin_core import policy  # noqa: E402
from mcp_admin_core.products import TOOLS  # noqa: E402

from ha_opendesign_mcp import surface  # noqa: E402

surface.install()
TABLE = TOOLS['opendesign']
PROJECT = '76c45d7a-3147-45cf-a3f4-295ee256e48e'
WRITERS = ['create_project', 'delete_project', 'send_message']
CASES = {
    'health': ('health', {}),
    'health/extra': ('health', {'verbose': True}),
    'get_project': ('get_project', {'project_id': PROJECT}),
    'get_project/not-a-uuid': ('get_project', {'project_id': 'abc'}),
    'get_project/missing': ('get_project', {}),
    'get_file_info': ('get_file_info', {'project_id': PROJECT, 'file_path': 'src/index.html'}),
    'get_file_info/traversal': ('get_file_info', {'project_id': PROJECT, 'file_path': '../x'}),
    'read_file': ('read_file', {'project_id': PROJECT, 'file_path': 'src/index.html'}),
    'read_file/secret': ('read_file', {'project_id': PROJECT, 'file_path': '.env'}),
    'read_file/key': ('read_file', {'project_id': PROJECT, 'file_path': 'keys/server.pem'}),
    'read_file/characters': ('read_file', {'project_id': PROJECT, 'file_path': 'a%2e'}),
    'list_connectors/extra': ('list_connectors', {'filter': 'x'}),
    'create_project': ('create_project', {'prompt': 'A landing page'}),
    'create_project/agent': ('create_project', {'prompt': 'x', 'agent_id': 'byok-opencode'}),
    'create_project/empty': ('create_project', {'prompt': ''}),
    'create_project/too-long': ('create_project', {'prompt': 'x' * 20001}),
    'create_project/bad-agent': ('create_project', {'prompt': 'x', 'agent_id': '../bin/sh'}),
    'create_project/not-text': ('create_project', {'prompt': 1}),
    'send_message': ('send_message', {'project_id': PROJECT, 'prompt': 'Make it blue'}),
    'send_message/no-project': ('send_message', {'prompt': 'x'}),
    'delete_project': ('delete_project', {'project_id': PROJECT}),
    'list_runs': ('list_runs', {}),
    'unknown_tool': ('no_such_tool', {}),
}
VARIANTS = {'granted': {}, 'list_skills-disabled-no-grant': {'disabled': ['list_skills'], 'enabled_write_tools': []}}


def state(**changes):
    try:
        from ha_opendesign_mcp.state import BuiltinState as Model  # 0.2.6
    except ImportError:
        from mcp_admin_core.products import ProductState as Model  # 0.2.0-0.2.5: the vendored schema 3 model
    value = {'schema_version': 3, 'token': 'A' * 43, 'child_token': 'B' * 43, 'backend_url': None,
             'backend_key': None, 'endpoint': None, 'writes_enabled': False, 'disabled': [],
             'enabled_write_tools': WRITERS, 'product': 'opendesign', 'connection': {'url': 'http://127.0.0.1:7456'}}
    return Model.model_validate({**value, **changes})


def request(name, arguments, current):
    message = {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}
    try:
        policy.authorize(message, TABLE, current)
    except policy.ToolCallRefused as refused:
        return {'error': refused.error()}
    return {'forwarded': message['params']['arguments']}


def capture(child):
    out = {'listed': {}, 'requests': {}}
    for variant, changes in VARIANTS.items():
        current = state(**changes)
        reply = policy.filter_list({'jsonrpc': '2.0', 'id': 2, 'result': copy.deepcopy(child['tools'])}, TABLE, current)
        out['listed'][variant] = reply['result']
        out['requests'][variant] = {case: request(name, copy.deepcopy(arguments), current)
                                    for case, (name, arguments) in CASES.items()}
    return out


def main():
    child = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(capture(child), indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
