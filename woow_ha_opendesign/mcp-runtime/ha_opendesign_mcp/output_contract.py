"""One reviewed OpenDesign output contract at the built-in gateway boundary.

The vendored filter intentionally drops arbitrary child outputSchema values.  This
overlay restores only the SDK 2.3.0 read_file str contract after that filter has
made its normal tool/policy decision.  A changed vendor implementation must be
reviewed before this hook can start; no vendored file is modified.
"""
import copy
import hashlib
import inspect
import json
from pathlib import Path

from mcp_admin_core import capabilities, gateway, policy

from . import PRODUCT, surface

READ_FILE_OUTPUT = {
    'properties': {'result': {'title': 'Result', 'type': 'string'}},
    'required': ['result'], 'title': 'read_fileOutput', 'type': 'object',
}
# sha256 of JSON with sorted keys, no whitespace and UTF-8 (the PaaS 29fa and
# HA SDK 2.3.0 child declarations are byte-for-byte equal in this form).
SCHEMA_SHA256 = 'fb89773eb83f4240f76fad55431c06554b36e4a6b3a6ed3ea7790ccc29fde513'
if hashlib.sha256(json.dumps(READ_FILE_OUTPUT, sort_keys=True,
    separators=(',', ':'), ensure_ascii=False).encode()).hexdigest() != SCHEMA_SHA256:
    raise RuntimeError('OpenDesign output contract pin changed')

def _vendor_dir(root):
    # Repository tests import from mcp-runtime/vendor; install.sh copies that
    # vendor tree to /opt/woow/packages and removes the staging directory.
    candidates = [root / suffix for suffix in (
        'vendor/packages/mcp-admin-core/mcp_admin_core',
        'packages/mcp-admin-core/mcp_admin_core')]
    present = [path for path in candidates if path.is_dir()]
    if len(present) != 1:
        raise RuntimeError('OpenDesign output contract requires one known vendor layout')
    return present[0]


VENDOR = _vendor_dir(Path(__file__).resolve().parents[1])
VENDOR_SHA256 = {
    'policy.py': '229bf7cee338c2cd79f1209c510dd84a506e2541ebe03360323411530bbce7cc',
    'gateway.py': '06b5b2a09251f54efbf49d96fa644347da965e7a008663814071b370074e2036',
    'capabilities.py': '92bc05bb7a9546a2dc21da44e3189ecefa0a931b967c486bd41614a88ee8af63',
}
ORIGINAL_FILTER = gateway.filter_list
ORIGINAL_CATALOG = gateway.tool_catalog


def guard_vendor():
    """Fail startup if the copied vendor source or the imported call seam drifts."""
    for name, module in (('policy.py', policy), ('gateway.py', gateway),
                         ('capabilities.py', capabilities)):
        path = VENDOR / name
        if (Path(module.__file__).resolve() != path.resolve()
                or hashlib.sha256(path.read_bytes()).hexdigest() != VENDOR_SHA256[name]):
            raise RuntimeError('OpenDesign output contract requires reviewed vendor ' + name)
    for call, names in ((ORIGINAL_FILTER, ('message', 'tools', 'state')),
                        (ORIGINAL_CATALOG, ('registry', 'pinned', 'observed', 'state'))):
        parameters = tuple(inspect.signature(call).parameters.values())
        if (tuple(p.name for p in parameters) != names
                or any(p.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD for p in parameters)):
            raise RuntimeError('OpenDesign output contract requires reviewed vendor signature')
    if ORIGINAL_FILTER is not policy.filter_list or ORIGINAL_CATALOG is not capabilities.tool_catalog:
        raise RuntimeError('OpenDesign output contract requires reviewed vendor binding')


def _reviewed(candidate):
    # Strict equality rejects absent, changed, extra, $ref, pattern and other
    # child-controlled schema members.  Return our own copy, never child data.
    return copy.deepcopy(READ_FILE_OUTPUT) if type(candidate) is dict and candidate == READ_FILE_OUTPUT else None


def _unique_read_file(tools):
    if type(tools) is not list:
        return None
    matches = [tool for tool in tools if type(tool) is dict and tool.get('name') == 'read_file']
    return matches[0].get('outputSchema') if len(matches) == 1 else None


def _local(state, tools):
    return (getattr(state, 'product', None) == PRODUCT
            and tools.get('read_file') is surface.TABLE['read_file'])


def filter_list(message, tools, state):
    """Only add the pin to a read_file the original policy kept in tools/list."""
    candidate = None
    if _local(state, tools) and type(message) is dict and type(message.get('result')) is dict:
        candidate = _reviewed(_unique_read_file(message['result'].get('tools')))
    filtered = ORIGINAL_FILTER(message, tools, state)
    if candidate is not None and type(filtered.get('result')) is dict:
        matches = [tool for tool in filtered['result'].get('tools', ())
                   if type(tool) is dict and tool.get('name') == 'read_file']
        if len(matches) == 1:
            if 'outputSchema' in matches[0]:
                raise RuntimeError('unexpected vendored output schema')
            matches[0]['outputSchema'] = candidate
    return filtered


def tool_catalog(registry, pinned, observed, state):
    """Show the same reviewed contract only for an observed, effective tool."""
    catalog = ORIGINAL_CATALOG(registry, pinned, observed, state)
    if not _local(state, registry):
        return catalog
    candidate = _reviewed(_unique_read_file(observed))
    if candidate is None:
        return catalog
    matches = [item for item in catalog['items'] if item['name'] == 'read_file']
    if len(matches) == 1 and matches[0]['effective'] is True and matches[0]['policy_enabled'] is True:
        matches[0]['outputSchema'] = candidate
        matches[0]['output_schema_source'] = 'reviewed_child'
    return catalog


def install():
    guard_vendor()
    if gateway.filter_list is filter_list and gateway.tool_catalog is tool_catalog:
        return
    if gateway.filter_list is not ORIGINAL_FILTER or gateway.tool_catalog is not ORIGINAL_CATALOG:
        raise RuntimeError('OpenDesign output contract hook already changed')
    gateway.filter_list = filter_list
    gateway.tool_catalog = tool_catalog
