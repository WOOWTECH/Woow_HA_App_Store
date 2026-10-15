"""Built-in Woow OpenDesign MCP server for the Woow HA OpenDesign add-on.

Everything here is local glue around the pinned copy of WOOWTECH/Woow_ha_mcp_addons in ../vendor (see
../VENDOR.json). The vendored gateway, policy, state store, child supervision, health monitor, HA admin
verifier, admin UI and OpenDesign tool handlers are used unchanged.
"""
from pathlib import Path

PRODUCT = 'opendesign'
# The OpenDesign daemon of this same container (launcher: OD_BIND_HOST=127.0.0.1, OD_PORT=7456). Fixed: the
# built-in server has no connection settings.
BACKEND_URL = 'http://127.0.0.1:7456'
DATA_DIR = Path('/data/mcp')
RUN_DIR = Path('/run/ha-opendesign-mcp')
# Administration: only nginx (uid/gid ha-ingress) can open this socket (RUN_DIR is 0750 mcp:ha-ingress).
ADMIN_SOCKET = RUN_DIR / 'admin.sock'
# Gateway -> child: only uid mcp can open this socket (RUN_DIR/child is 0700 mcp:mcp). Replaces the
# standalone add-on's 127.0.0.1:3000, a port OpenDesign's own agents may use for dev servers.
CHILD_SOCKET = RUN_DIR / 'child' / 'child.sock'
MCP_HOST = '0.0.0.0'
MCP_PORT = 8081
# The Supervisor Ingress peer the vendored admin app requires (gateway.admin_identity). nginx forwards
# /mcp-admin/ only from this peer (allow/deny) and only over ADMIN_SOCKET.
INGRESS_PEER = ('172.30.32.2', 0)
PROXY_GROUP = 'ha-ingress'
