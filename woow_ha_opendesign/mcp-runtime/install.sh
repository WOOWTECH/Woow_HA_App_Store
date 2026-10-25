#!/bin/sh
# Build-time install of the built-in OpenDesign MCP server (run as root from the add-on Dockerfile).
#
#   COPY --from=woow-mcp-ui /ui/dist /opt/woow/packages/mcp-admin-ui/dist
#   COPY mcp-runtime/ /tmp/mcp-runtime/
#   RUN sh /tmp/mcp-runtime/install.sh && rm -rf /tmp/mcp-runtime
#
# Layout matches the vendored source (/opt/woow, see VENDOR.json) so the vendored path logic works unchanged.
# Both virtual environments use the base image's /usr/bin/python3 and install ONLY the hash-pinned wheels of
# requirements/*.txt (versions: requirements/lock.sh).
set -eu
export HOME=/root PIP_NO_CACHE_DIR=1

src=$(cd "$(dirname "$0")" && pwd)
py=/usr/bin/python3
root=/opt/woow

test -x "$py"
test -f "$root/packages/mcp-admin-ui/dist/index.html"  # built by the woow-mcp-ui stage

# Principals: mcp (gateway + child, owns /data/mcp) and ha-ingress (nginx; the only other opener of admin.sock).
# OpenDesign, its agents and the ttyd shell stay uid open-design (1001) and get neither.
getent group mcp >/dev/null || addgroup -S -g 10001 mcp
getent passwd mcp >/dev/null || adduser -S -D -H -u 10001 -G mcp -h /data/mcp -s /sbin/nologin mcp
getent group ha-ingress >/dev/null || addgroup -S -g 1002 ha-ingress
getent passwd ha-ingress >/dev/null || adduser -S -D -H -u 1002 -G ha-ingress -h /var/empty -s /sbin/nologin ha-ingress
test "$(id -u mcp):$(id -g mcp)" = "10001:10001"
test "$(id -u ha-ingress):$(id -g ha-ingress)" = "1002:1002"
if id -nG open-design | tr ' ' '\n' | grep -qx -e mcp -e ha-ingress; then
  echo "open-design must not belong to mcp or ha-ingress" >&2
  exit 1
fi

mkdir -p "$root/bin"
cp -R "$src/vendor/." "$root/"
rm -rf "$root/packages/mcp-admin-ui/src" "$root/packages/mcp-admin-ui/scripts" \
  "$root/packages/mcp-admin-ui/package.json" "$root/packages/mcp-admin-ui/package-lock.json"
cp -R "$src/ha_opendesign_mcp" "$root/ha_opendesign_mcp"
cp "$src/bin/ha-opendesign-mcp" "$root/bin/ha-opendesign-mcp"
cp "$src/VENDOR.json" "$root/VENDOR.json"

"$py" -m venv "$root/.venv"
"$root/.venv/bin/pip" install --no-cache-dir --disable-pip-version-check --no-deps --only-binary=:all: \
  --require-hashes -r "$src/requirements/management.txt"
"$py" -m venv "$root/apps/opendesign/.venv"
"$root/apps/opendesign/.venv/bin/pip" install --no-cache-dir --disable-pip-version-check --no-deps \
  --only-binary=:all: --require-hashes -r "$src/requirements/child.txt"
"$root/.venv/bin/pip" uninstall -y -q pip
"$root/apps/opendesign/.venv/bin/pip" uninstall -y -q pip

# Root-owned, read-only code; byte-code compiled now (runtime sets PYTHONDONTWRITEBYTECODE).
"$root/.venv/bin/python" -m compileall -q "$root/packages" "$root/apps" "$root/packaging" "$root/ha_opendesign_mcp" >/dev/null
chown -R root:root "$root"
chmod -R u=rwX,go=rX "$root"
chmod 0755 "$root/bin/ha-opendesign-mcp"

# Import-time checks of the vendored code: management imports; child imports run backend_policy.check_sources()
# (pinned httpx/httpcore sources) and launch.py's MCPServer (MCP Python SDK 2 since 0.2.6); BoundedTools and
# keep_error_text check the pinned MCP SDK sources.
# 0.2.1: importing the runtime applies the HA overlay (surface.install): the gateway table is the 15 PaaS tools with the
# bounded argument models (0.2.6: not the pinned runtime's full surface), checked by the schema 3 state; the child's
# replaced handlers (od_tools.install) come from the overlay. child.setup() is the child's real entry.
PYTHONPATH="$root/packages/mcp-admin-core:$root" "$root/.venv/bin/python" -c '
import mcp_admin_core.run_product, ha_opendesign_mcp.runtime
from mcp_admin_core.products import TOOLS
from ha_opendesign_mcp import surface
from ha_opendesign_mcp.state import BuiltinState
assert len(TOOLS["opendesign"]) == 15, sorted(TOOLS["opendesign"])
assert all(TOOLS["opendesign"][name] is tool for name, tool in surface.TABLE.items())
assert not any(tool.child_schema for tool in TOOLS["opendesign"].values())
assert BuiltinState.model_fields["schema_version"].default == 3
'
OD_API_BASE=http://127.0.0.1:7456 PYTHONPATH="$root/apps/opendesign/vendor:$root/apps/runtime:$root/apps/opendesign" \
  "$root/apps/opendesign/.venv/bin/python" -c '
import sys
sys.path.append("/opt/woow")
import launch
from ha_opendesign_mcp import child
app, client, workers = child.setup()
workers.close()
client.close()
tools = launch.mcp._tool_manager.list_tools()
assert len(tools) == 15
assert all(tool.is_async and getattr(tool.fn, "_woow_keeps_error_text", False) for tool in tools)
'
# The overlay's unit tests with the image's own interpreters and pinned packages (loopback fake daemon, no network).
HA_OD_MCP_CODE="$root" HA_OD_MCP_VENDOR="$root" sh "$src/tests/unit/run.sh" "$root/.venv/bin/python" \
  "$root/apps/opendesign/.venv/bin/python"
echo "built-in MCP installed: $(sed -n 's/.*"source_commit": "\([0-9a-f]*\)".*/\1/p' "$src/VENDOR.json")"
