#!/bin/sh
# Build-time install of the built-in OpenDesign MCP server (run as root from the add-on Dockerfile).
#
#   COPY --from=woow-mcp-ui /ui/dist /opt/woow/packages/mcp-admin-ui/dist
#   COPY mcp-runtime/ /tmp/mcp-runtime/
#   RUN sh /tmp/mcp-runtime/install.sh && rm -rf /tmp/mcp-runtime
#
# Layout matches the vendored source (/opt/woow, see VENDOR.json) so the vendored path logic works unchanged.
# Both virtual environments use the base image's /usr/bin/python3 and install ONLY hash-pinned wheels whose
# versions equal the source repository's uv.lock files (requirements/*.txt).
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
# (pinned httpx/httpcore sources) and launch.py's FastMCP server; BoundedTools checks the pinned MCP SDK sources.
PYTHONPATH="$root/packages/mcp-admin-core:$root" "$root/.venv/bin/python" -c '
import mcp_admin_core.run_product, ha_opendesign_mcp.runtime
from mcp_admin_core.products import TOOLS
assert len(TOOLS["opendesign"]) == 11, sorted(TOOLS["opendesign"])
'
OD_API_BASE=http://127.0.0.1:7456 PYTHONPATH="$root/apps/opendesign/vendor:$root/apps/runtime:$root/apps/opendesign" \
  "$root/apps/opendesign/.venv/bin/python" -c '
import launch
from bounded_tools import BoundedTools
workers = BoundedTools(launch.mcp, capacity=1)
workers.close()
assert len(launch.mcp._tool_manager.list_tools()) == 15
'
echo "built-in MCP installed: $(sed -n 's/.*"source_commit": "\([0-9a-f]*\)".*/\1/p' "$src/VENDOR.json")"
