#!/bin/sh
# Unit tests of the HA overlay (ha_opendesign_mcp: 0.2.1 tool surface, default grants, bounded handlers; 0.2.4
# management identity, the add-on version the root bootstrap passes on, child sessions; 0.2.6 the schema 3 state kept
# from 0.2.5, the tools, schemas and failure texts unchanged against v0.2.5 (fixtures/surface-0.2.5.json), and the
# gateway in front of the real MCP SDK 2 child: server/discover, the legacy handshake, the request body ceiling).
#
#   tests/unit/run.sh <management python> <child python>
#
# Each Python must have the pinned packages of requirements/management.txt or child.txt (install.sh runs this with
# the image's two virtual environments during the image build). HA_OD_MCP_CODE / HA_OD_MCP_VENDOR select the code
# (default: this repository's mcp-runtime and mcp-runtime/vendor; /opt/woow in the image). No network is used: the
# child tests talk to a fake OpenDesign daemon on 127.0.0.1.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
mgmt=${1:?management python}
child=${2:?child python}
export PYTHONDONTWRITEBYTECODE=1
"$mgmt" -B -W ignore "$here/test_od_rules.py"
"$mgmt" -B -W ignore "$here/test_surface.py"
"$mgmt" -B -W ignore "$here/test_state.py"
"$mgmt" -B -W ignore "$here/test_management.py"
"$mgmt" -B -W ignore "$here/test_bootstrap.py"
"$mgmt" -B -W ignore "$here/test_unchanged_gateway.py"
"$child" -B -W ignore "$here/test_od_tools.py"
"$child" -B -W ignore "$here/test_child_session.py"
"$child" -B -W ignore "$here/test_unchanged_child.py"
HA_OD_MCP_CHILD_PYTHON="$child" "$mgmt" -B -W ignore "$here/test_gateway_child.py"
echo "HA overlay unit tests passed"
