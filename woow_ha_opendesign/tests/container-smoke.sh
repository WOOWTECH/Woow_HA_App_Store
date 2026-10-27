#!/usr/bin/env bash
set -Eeuo pipefail

image=${1:-woow-ha-opendesign:test}
container="woow-od-smoke-${RANDOM}"
volume="woow-od-data-${RANDOM}"
port=${SMOKE_PORT:-18099}
# Deliberately fake. The native BYOK smoke verifies this value never leaves the
# transient browser-style request as a log line or persisted /data artifact.
readonly BYOK_FAKE_KEY='od-byok-test-key-not-a-secret'
tmp=$(mktemp -d)

cleanup() {
  local status=$?
  if (( status != 0 )); then
    echo '--- smoke container logs ---' >&2
    docker logs "$container" >&2 || true
  fi
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

docker volume create "$volume" >/dev/null

# Deliberately fake, like Supervisor's: it must stay with the root launcher and
# never reach a child process environment.
readonly SUPERVISOR_FAKE_TOKEN='supervisor-test-token-not-a-secret'

start_container() {
  docker run -d --platform linux/amd64 --name "$container" \
    -p "127.0.0.1:${port}:8099" \
    -e SUPERVISOR_TOKEN="$SUPERVISOR_FAKE_TOKEN" \
    -v "$volume:/data" \
    "$image" >/dev/null
}

wait_for_health() {
  local attempt
  for ((attempt = 1; attempt <= 90; attempt += 1)); do
    if curl -fsS "http://127.0.0.1:${port}/api/health" >"$tmp/health.json"; then
      return 0
    fi
    if ! docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true; then
      docker logs "$container" >&2 || true
      return 1
    fi
    sleep 1
  done
  docker logs "$container" >&2 || true
  echo 'health endpoint did not become ready' >&2
  return 1
}

start_container
wait_for_health
python3 - "$tmp/health.json" <<'PY'
import json
import sys
assert json.load(open(sys.argv[1], encoding='utf-8')).get('ok') is True
PY

# HA Supervisor removes the public ingress prefix before proxying and supplies
# it in X-Ingress-Path. Nginx therefore receives '/' and must inject/rewrite the
# prefix into the returned application shell.
ingress_prefix=/api/hassio_ingress/abcdefghijklmnop
docker cp tests/export-http-contract-e2e.mjs "$container:/tmp/export-http-contract-e2e.mjs"
docker cp tests/export-archive-inspection.mjs "$container:/tmp/export-archive-inspection.mjs"
docker cp tests/fixtures/export-deck.html "$container:/tmp/export-deck.html"
docker exec \
  -e OD_EXPORT_BASE_URL=http://127.0.0.1:8099 \
  -e OD_EXPORT_INGRESS_PATH="$ingress_prefix" \
  -e OD_EXPORT_FIXTURE_PATH=/tmp/export-deck.html \
  "$container" node /tmp/export-http-contract-e2e.mjs
curl --fail-with-body -sSL -o "$tmp/ingress.html" \
  -H "X-Ingress-Path: $ingress_prefix" \
  "http://127.0.0.1:${port}/"
grep -Fq "window.__OD_INGRESS_PATH__=\"$ingress_prefix\"" "$tmp/ingress.html"
grep -Eq "(href|src)=\\\"$ingress_prefix/_next/" "$tmp/ingress.html"
curl --fail-with-body -sS -o "$tmp/terminal.html" \
  -H "X-Ingress-Path: $ingress_prefix" \
  "http://127.0.0.1:${port}/console/"
grep -Eiq '<!doctype html|<html' "$tmp/terminal.html"

# This models a browser request to <public-prefix>/api/health after Supervisor
# path stripping: nginx sees /api/health plus the validated prefix header.
curl --fail-with-body -sS -o "$tmp/ingress-health.json" \
  -H "X-Ingress-Path: $ingress_prefix" \
  "http://127.0.0.1:${port}/api/health"
python3 - "$tmp/ingress-health.json" <<'PY'
import json
import sys
assert json.load(open(sys.argv[1], encoding='utf-8')).get('ok') is True
PY

# The CLI Terminal is ttyd on loopback only; its sole public route is nginx's
# ingress-prefixed /console/ proxy (HA authenticates that route), the same path
# as the WOOW PaaS build. The image publishes no other port, and a request
# without a valid X-Ingress-Path never receives the prefixed terminal assets.
# Redirects must stay relative, ingress-prefixed paths: an absolute Location
# would name nginx's internal host:port instead of the HA origin.
curl -sS -o /dev/null -D "$tmp/terminal-redirect.txt" \
  -H "X-Ingress-Path: $ingress_prefix" \
  "http://127.0.0.1:${port}/console"
grep -Eq '^HTTP/1\.1 302' "$tmp/terminal-redirect.txt"
grep -Fqx "Location: $ingress_prefix/console/"$'\r' "$tmp/terminal-redirect.txt"
# A header that is not Supervisor-shaped is never reflected into the route.
curl -sS -o /dev/null -D "$tmp/terminal-redirect-invalid.txt" \
  -H 'X-Ingress-Path: /not-an-ingress-path' \
  "http://127.0.0.1:${port}/console"
grep -Fqx "Location: /console/"$'\r' "$tmp/terminal-redirect-invalid.txt"
# The pre-0.2.5 /terminal/ links (and anything below them) land on /console/.
for old_path in /terminal /terminal/ /terminal/ws; do
  curl -sS -o /dev/null -D "$tmp/terminal-legacy.txt" \
    -H "X-Ingress-Path: $ingress_prefix" \
    "http://127.0.0.1:${port}${old_path}"
  grep -Eq '^HTTP/1\.1 302' "$tmp/terminal-legacy.txt"
  grep -Fqx "Location: $ingress_prefix/console/"$'\r' "$tmp/terminal-legacy.txt"
done
test "$(docker port "$container" | wc -l)" = 1
docker port "$container" | grep -Eq '^8099/tcp -> 127\.0\.0\.1:'
# The built-in MCP server listens on 8081 for LAN clients (never host-mapped
# unless the user maps it). Its Ingress administration only admits the
# Supervisor peer: this host request (Docker gateway source) is refused.
docker exec "$container" sh -ceu '
  for _ in $(seq 1 60); do
    netstat -ltn | grep -q "0.0.0.0:8081 " && break
    sleep 1
  done
  # Paseo may still be installing. Check public binds now; the lifecycle
  # fixture below checks the exact full set after both start and manual stop.
  public=$(netstat -ltn | awk "/LISTEN/ { print \$4 }" | grep -v "^127\.0\.0\.1:" | sort)
  test "$public" = "$(printf "%s\n" 0.0.0.0:8081 0.0.0.0:8099 | sort)"
'
test "$(curl -sS -o /dev/null -w '%{http_code}' -H "X-Ingress-Path: $ingress_prefix" \
  -H 'X-Remote-User-Id: 0123456789abcdef0123456789abcdef' "http://127.0.0.1:${port}/mcp-admin/")" = 403
docker exec "$container" python3 -c '
import json, urllib.error, urllib.request
body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()
request = urllib.request.Request("http://127.0.0.1:8081/mcp", data=body, method="POST",
    headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
try:
    urllib.request.urlopen(request, timeout=10)
except urllib.error.HTTPError as error:
    assert error.code == 401 and error.headers.get("WWW-Authenticate", "").startswith("Bearer"), error.code
else:
    raise SystemExit("built-in MCP accepted a request without a token")
'
# 0.2.4: the MCP Server page reports the add-on version (the image's
# WOOW_ADDON_VERSION, which the root bootstrap passes to the management process)
# and the MCP runtime version (0.4.0 since 0.2.6). Read over the administration
# socket, as nginx reaches it for the Supervisor Ingress peer.
expected_version=$(docker exec "$container" printenv WOOW_ADDON_VERSION)
test -n "$expected_version"
docker exec "$container" /opt/woow/.venv/bin/python -c '
import sys
import time
import httpx
transport = httpx.HTTPTransport(uds="/run/ha-opendesign-mcp/admin.sock")
with httpx.Client(transport=transport, base_url="http://localhost", timeout=30, trust_env=False) as client:
    for attempt in range(30):
        try:
            response = client.get("/api/capabilities", headers={
                "X-Remote-User-Id": "0123456789abcdef0123456789abcdef",
                "X-Ingress-Path": "/api/hassio_ingress/smoke/mcp-admin"})
            break
        except httpx.TransportError:
            if attempt == 29:
                raise
            time.sleep(1)
response.raise_for_status()
body = response.json()
product = body["product"]
assert product == {"id": "opendesign", "version": sys.argv[1], "runtime_version": "0.4.0"}, product
assert body["deployment"] == {"kind": "builtin"} and body["admin"] == {"authority": "ha-ingress"}, body
assert body["backend"]["mode"] == "fixed" and body["backend"]["can_edit"] is False, body["backend"]
assert body["tools"]["catalog_count"] == 15, body["tools"]["catalog_count"]
' "$expected_version"

# 0.2.6: the MCP Python SDK 2.3 child behind the gateway, in this image, with the
# real OpenDesign daemon: server/discover (sent first by Claude.ai and the SDK 2
# client) gets the gateway's own JSON-RPC -32601; the 2025 handshake works, also
# with a 2026-07-28 MCP-Protocol-Version header (no longer forwarded with an
# initialize: an SDK 2 child refuses it); the 15 tools are listed exactly as
# 0.2.5 listed them; a call works and a failure keeps its 0.2.5 text. The add-on
# token is read inside the container and never printed.
docker exec -i "$container" /opt/woow/.venv/bin/python -c '
import json
import sys
import time
import httpx
listed = json.load(sys.stdin)["gateway"]["listed"]["granted"]
with open("/data/mcp/state.json") as stream:
    token = json.load(stream)["token"]
accept = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer " + token}
modern = "2026-07-28"
def reply(response, ident):
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in response.text.splitlines():
            if line.startswith("data:") and json.loads(line[5:]).get("id") == ident:
                return json.loads(line[5:])
        raise SystemExit("no reply %d" % ident)
    return response.json()
with httpx.Client(base_url="http://127.0.0.1:8081", timeout=60, trust_env=False) as client:
    discover = {"jsonrpc": "2.0", "id": 0, "method": "server/discover", "params": {"_meta": {
        "io.modelcontextprotocol/protocolVersion": modern}}}
    answer = client.post("/mcp", json=discover, headers={**accept, "MCP-Protocol-Version": modern})
    assert answer.status_code == 200 and "mcp-session-id" not in answer.headers, answer.status_code
    assert answer.json() == {"jsonrpc": "2.0", "id": 0, "error": {"code": -32601, "message": "Method not found"}}, answer.text
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25",
            "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}}}
    for attempt in range(90):  # the child may still be starting
        answer = client.post("/mcp", json=init, headers={**accept, "MCP-Protocol-Version": modern})
        if answer.status_code == 200:
            break
        time.sleep(1)
    assert answer.status_code == 200, answer.status_code
    result = reply(answer, 1)["result"]
    assert result["protocolVersion"] == "2025-11-25", result
    assert result["serverInfo"] == {"name": "woow-mcp-opendesign", "version": "0.4.0"}, result["serverInfo"]
    headers = {**accept, "Mcp-Session-Id": answer.headers["mcp-session-id"], "MCP-Protocol-Version": "2025-11-25"}
    assert client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                       headers=headers).status_code == 202
    tools = reply(client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers), 2)
    assert tools["result"] == listed, [tool["name"] for tool in tools["result"]["tools"]]
    def call(ident, name, arguments):
        return reply(client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": ident, "method": "tools/call",
                                 "params": {"name": name, "arguments": arguments}}), ident)["result"]
    health = call(3, "health", {})
    assert not health.get("isError") and json.loads(health["content"][0]["text"])["ok"] is True, health
    missing = call(4, "get_project", {"project_id": "00000000-0000-4000-8000-000000000000"})
    assert missing.get("isError") is True, missing
    assert [item["text"] for item in missing["content"]] == [
        "Error executing tool get_project: BACKEND_HTTP_ERROR status=404"], missing
    assert client.delete("/mcp", headers=headers).status_code in (200, 204)
print("built-in MCP on SDK 2: server/discover -32601, 2025 handshake, 15 tools as 0.2.5, call and failure text")
' < mcp-runtime/tests/unit/fixtures/surface-0.2.5.json

docker exec "$container" sh -ceu '
  # PID 1 is root only to prepare the Supervisor root-owned /data mount.
  test "$(id -u)" = 0
  test "$(stat -c %u:%g /data/opendesign)" = 1001:1001
  check_uid() {
    for pid in $(pidof "$1"); do
      # Short-lived CLI probes (e.g. `pi --version`) may exit between pidof
      # and the read; only a process that still exists must have the UID.
      status=$(cat "/proc/$pid/status" 2>/dev/null) || continue
      set -- $(printf "%s\n" "$status" | grep "^Uid:")
      test "$2 $3 $4" = "$uid $uid $uid"
    done
  }
  uid=1001
  for process in node ttyd; do
    test -n "$(pidof "$process")"
    check_uid "$process"
  done
  # nginx has its own UID so only it (and the MCP server) can open the MCP
  # administration socket; the MCP server runs as UID 10001.
  test -n "$(pidof nginx)"
  uid=1002
  check_uid nginx
  test -n "$(pgrep -u 10001 -f ha_opendesign_mcp/management.py)"
  test -n "$(pgrep -u 10001 -f ha_opendesign_mcp/child.py)"
  test "$(stat -c %a:%u /data/mcp)" = 700:10001
  ! su-exec open-design:open-design cat /data/mcp/state.json >/dev/null 2>&1
  # Only the root launcher keeps the Supervisor token. A child environment is
  # read as that child UID; the MCP management process is not dumpable at all.
  for proc in /proc/[0-9]*; do
    pid=${proc#/proc/}
    owner=$(awk "/^Uid:/ { print \$2 }" "$proc/status" 2>/dev/null) || continue
    test -n "$owner" && test "$owner" != 0 || continue
    env=$(su-exec "$owner" cat "/proc/$pid/environ" 2>/dev/null | tr "\000" "\n") || continue
    if printf "%s\n" "$env" | grep -q "^SUPERVISOR_TOKEN="; then
      echo "Supervisor token reached child process $pid (uid $owner)" >&2
      exit 1
    fi
  done
  # 0.2.1: no Omnigent host or kit (the core still ships the CLI until a core
  # without it is pinned).
  test ! -e /etc/omnigent-host
  test ! -e /etc/profile.d/omnigent-host.sh
  test ! -e /usr/local/bin/omnigent-host-status
  test -d /data/opendesign
  test -r /app/apps/daemon/dist/cli.js
  test -d /app/apps/web/out
  test -x /usr/bin/chromium-browser
  command -v bash >/dev/null
  command -v su-exec >/dev/null
  test -r /opt/ha-opendesign/headless-entry.mjs
  test -r /opt/ha-opendesign/headless-renderer.mjs
  test -r /opt/ha-opendesign/ha-export-bridge.js
  for executable in opencode-cli aider gemini cursor-agent qwen copilot amp; do
    if command -v "$executable" >/dev/null 2>&1 \
      || test -e "/app/node_modules/.bin/$executable" \
      || test -e "/usr/local/lib/node_modules/.bin/$executable"; then
      echo "forbidden local AI CLI present: $executable" >&2
      exit 1
    fi
  done
'
# OpenDesign's native API mode discovers `opencode` through PATH. Verify the
# real locked Alpine binaries as their runtime UID. OpenDesign can discover
# these executables through PATH without a plugin installer or first-run download.
docker exec -u 1001:1001 "$container" sh -ceu '
  test "$(id -u)" = 1001
  test "$(opencode --version)" = 1.18.33
  test "$(command -v opencode)" = /usr/local/bin/opencode
  claude --version | grep -Fq 2.1.296
  codex --version | grep -Fq 0.162.1
  pi --version | grep -Fq 1.1.0
  test ! -e /opt/ha-opendesign/opencode
  test "$(getent passwd open-design | cut -d: -f6)" = /data/opendesign/home
  command -v claude >/dev/null
  command -v codex >/dev/null
  command -v pi >/dev/null
  ! command -v opencode-cli >/dev/null 2>&1
  test ! -e /opt/ha-opendesign/ha-pi-wrapper.mjs
  test -w /data/opendesign
  printf persisted > /data/opendesign/container-smoke-sentinel
'

# Verify OpenDesign's native plugin and skill catalog APIs are available.
# The daemon resolves selected content and stages it for whichever adapter runs.
docker exec -u 1001:1001 "$container" python3 -c '
import json, urllib.request
catalog = {}
for path, key in (("/api/plugins", "plugins"), ("/api/skills", "skills")):
    with urllib.request.urlopen("http://127.0.0.1:7456" + path, timeout=10) as response:
        data = json.load(response)
    assert isinstance(data.get(key), list) and data[key], path + " native catalog is empty"
    catalog[key] = {entry.get("id") for entry in data[key]}
# The core bundles the WoowTech skill and drops brainstorming. Omnigent is
# removed from the add-on (0.2.1): neither its plugin nor its skill is offered.
assert "woow-paseo" in catalog["plugins"], "native Paseo launcher missing"
assert "woowtech-brand" in catalog["skills"], "core skills missing"
assert "brainstorming" not in catalog["skills"], "brainstorming must not be offered"
assert "woow-omnigent" not in catalog["skills"], "woow-omnigent skill must not be offered"
assert "woow-omnigent" not in catalog["plugins"], "woow-omnigent plugin must not be offered"
# The core daemon keeps its Omnigent route; without the plugin it reports not-installed.
with urllib.request.urlopen("http://127.0.0.1:7456/api/integrations/omnigent/status", timeout=30) as response:
    integration = json.load(response)
assert integration.get("installed") is False and integration.get("phase") == "not-installed", integration
'
# No Omnigent process runs ("[o]" keeps this command line from matching itself).
docker exec "$container" sh -c '! pgrep -af "[o]mnigent"'

# WoowTech white-label and zh-TW patches from the core must still reach the
# browser through ingress: the white-label head script, the zh-TW dictionary
# chunk, the WoowTech support channel, and its same-origin redirect.
grep -Fq 'id="woow-white-label"' "$tmp/ingress.html"
grep -Fq 'open-design:experience-survey:v1:retired' "$tmp/ingress.html"
docker exec "$container" sh -ceu '
  cd /app/apps/web/out
  grep -rl "請審查並潤色現有動效" _next/static/chunks | head -n1
  grep -rl "_woow/support" _next/static/chunks | head -n1
  grep -rlF "「CLI 終端機」登入 {agent}（Claude 請執行 claude 後輸入 /login）" _next/static/chunks | head -n1
  # HA wording (ha-patches/sign-in-hint.py): no PaaS-only sign-in hint is left.
  ! { grep -rlF -e "網址後加上" -e "WoowTech 平台的服務設定" _next/static/chunks | grep -v "[.]map\$"; }
' >"$tmp/patched-chunks.txt"
test "$(wc -l <"$tmp/patched-chunks.txt")" = 3
zh_chunk=$(sed -n 1p "$tmp/patched-chunks.txt")
support_chunk=$(sed -n 2p "$tmp/patched-chunks.txt")
sign_in_chunk=$(sed -n 3p "$tmp/patched-chunks.txt")
curl -fsS -H "X-Ingress-Path: $ingress_prefix" -o "$tmp/sign-in-chunk.js" "http://127.0.0.1:${port}/$sign_in_chunk"
grep -Fq 'Sign in to {agent} in the built-in CLI Terminal plugin' "$tmp/sign-in-chunk.js"
grep -Fq '請到「外掛」頁開啟內建的「CLI 終端機」' "$tmp/sign-in-chunk.js"
curl -fsS -H "X-Ingress-Path: $ingress_prefix" -o "$tmp/zh-chunk.js" "http://127.0.0.1:${port}/$zh_chunk"
grep -Fq '請審查並潤色現有動效' "$tmp/zh-chunk.js"
curl -fsS -H "X-Ingress-Path: $ingress_prefix" -o "$tmp/support-chunk.js" "http://127.0.0.1:${port}/$support_chunk"
grep -Fq 'support@woowtech.io' "$tmp/support-chunk.js"
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' -H "X-Ingress-Path: $ingress_prefix" \
  "http://127.0.0.1:${port}/_woow/support" >"$tmp/support-redirect.txt"
grep -Fqx '302 https://aiot.woowtech.io/woow' "$tmp/support-redirect.txt"
docker exec -u 1001:1001 "$container" sh -ceu '
  test -d /data/opendesign
  test ! -L /data/opendesign/home/.claude/skills
'

# Exercise the upstream native browser API request contract end-to-end: the
# daemon selects byok-opencode, invokes the bundled CLI, and streams from a
# loopback OpenAI-compatible mock. The test script itself never writes its key.
docker cp tests/container-opencode-byok-e2e.mjs "$container:/tmp/container-opencode-byok-e2e.mjs"
docker exec "$container" node /tmp/container-opencode-byok-e2e.mjs
# Read the logs to a file first: piping docker logs into a quiet grep lets grep exit on
# the first match while docker logs is still writing; pipefail turns that SIGPIPE into 141.
docker logs "$container" >"$tmp/container.log" 2>&1
if grep -Fq -- "$BYOK_FAKE_KEY" "$tmp/container.log"; then
  echo 'fake BYOK key leaked to container logs' >&2
  exit 1
fi
# Scan every regular persisted artifact, including the daemon DB/run output,
# without echoing a matching path or value into the test log.
if docker exec "$container" sh -ceu '
  if grep -R -I -F -q -- "$1" /data; then
    exit 1
  fi
' sh "$BYOK_FAKE_KEY"; then
  :
else
  echo 'fake BYOK key leaked to /data persisted artifacts' >&2
  exit 1
fi

# The withdrawn persistent-profile directory is removed at boot. A legacy
# symlink must be unlinked, never followed, and the rest of /data stays intact.
docker exec "$container" sh -ceu '
  mkdir /data/opendesign/legacy-credentials-target
  printf retained > /data/opendesign/legacy-credentials-target/sentinel
  ln -s /data/opendesign/legacy-credentials-target /data/opendesign/credentials
'

# 0.2.0 Omnigent state (with a fake login) is moved, never deleted, at the next
# start (0.2.1 removed Omnigent).
docker exec -u 1001:1001 "$container" sh -ceu '
  mkdir -m 0700 /data/opendesign/home/.omnigent
  printf "{\"fake\": \"omnigent-login-not-a-secret\"}" > /data/opendesign/home/.omnigent/auth_tokens.json
'

# Exercise the actual shared manager, native onboarding/MCP CAS and private
# socket before restart; no provider login or billable model call is made.
docker cp tests/listener-contract.mjs "$container:/tmp/listener-contract.mjs"
docker cp tests/container-paseo-e2e.mjs "$container:/tmp/container-paseo-e2e.mjs"
docker exec -u 1001:1001 "$container" node /tmp/container-paseo-e2e.mjs prepare

# Stop/recreate the container while retaining only its named /data volume.
# Every process must stop on TERM inside the launcher's grace period, without
# the KILL fallback.
docker stop -t 30 "$container" >/dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' "$container")" = 0
docker logs "$container" >"$tmp/container.log" 2>&1
if grep -Fq 'grace; sending KILL' "$tmp/container.log"; then
  echo 'a process ignored TERM and needed the launcher KILL fallback' >&2
  exit 1
fi
grep -Fq '[ha-opendesign] SIGTERM received; stopping OpenDesign' "$tmp/container.log"
docker rm "$container" >/dev/null
# A Home Assistant backup restore returns /data without the original owners
# (measured on HAOS 18.1: OpenDesign's database came back as root and the
# daemon failed with SQLITE_READONLY). Reproduce that on the retained volume;
# the launcher must hand everything back to open-design before OpenDesign starts.
docker run --rm --platform linux/amd64 -v "$volume:/data" \
  -v "$PWD/tests/credential-permissions-container.py:/tmp/credential-permissions.py:ro" \
  --entrypoint sh "$image" -ceu '
  # Disposable fixture: model the sole native backup_exclude subtree. Actual
  # Supervisor backup/uninstall/fresh restore is a separate native HA gate.
  test -d /data/opendesign/paseo/packages/runtime/releases
  rm -rf /data/opendesign/paseo/packages/runtime
  find /data/opendesign -mindepth 1 -exec chown -h 0:0 {} +
  test "$(find /data/opendesign -mindepth 1 -user 0 | wc -l)" -gt 0
  python3 /tmp/credential-permissions.py seed
'
start_container
wait_for_health
python3 - "$tmp/health.json" <<'PY'
import json
import sys
assert json.load(open(sys.argv[1], encoding='utf-8')).get('ok') is True
PY
docker cp tests/listener-contract.mjs "$container:/tmp/listener-contract.mjs"
docker cp tests/container-paseo-e2e.mjs "$container:/tmp/container-paseo-e2e.mjs"
docker exec -u 1001:1001 "$container" node /tmp/container-paseo-e2e.mjs restored
docker cp tests/credential-permissions-container.py "$container:/tmp/credential-permissions.py"
docker exec "$container" python3 /tmp/credential-permissions.py verify
docker logs "$container" >"$tmp/container.log" 2>&1
grep -Eq '\[ha-opendesign\] returned [0-9]+ path\(s\) under /data/opendesign to open-design' "$tmp/container.log"
docker exec "$container" sh -ceu '
  test "$(find /data/opendesign -xdev \( ! -user open-design -o ! -group open-design \) | wc -l)" -eq 0
'
docker exec "$container" sh -ceu '
  grep -qx persisted /data/opendesign/container-smoke-sentinel
  for skills_path in \
    /data/opendesign/home/.claude/skills \
    /data/opendesign/home/.agents/skills \
    /data/opendesign/home/.pi/agent/skills \
    /data/opendesign/home/.config/opencode/skills; do
    test ! -L "$skills_path"
  done
  test ! -e /data/opendesign/credentials
  test ! -L /data/opendesign/credentials
  grep -qx retained /data/opendesign/legacy-credentials-target/sentinel
  test ! -e /data/opendesign/home/.omnigent
  set -- /data/opendesign/.backup/omnigent-*
  test "$#" = 1 && test -d "$1" && test ! -L "$1"
  test "$(stat -c %a "$1")" = 700
  test "$(stat -c %a /data/opendesign/.backup)" = 700
  grep -Fq omnigent-login-not-a-secret "$1/auth_tokens.json"
'
docker logs "$container" >"$tmp/container.log" 2>&1
test "$(grep -c "Omnigent was removed in 0.2.1: moved its state" "$tmp/container.log")" = 1

# The previous restored check resumed Paseo through the GUI action. Repeat
# with enabled intent, missing runtime files and root-owned restored data;
# startup must rebuild without an enable request or new onboarding identity.
docker stop -t 30 "$container" >/dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' "$container")" = 0
docker rm "$container" >/dev/null
docker run --rm --platform linux/amd64 -v "$volume:/data" --entrypoint sh "$image" -ceu '
  test -d /data/opendesign/paseo/packages/runtime/releases
  rm -rf /data/opendesign/paseo/packages/runtime
  find /data/opendesign -mindepth 1 -exec chown -h 0:0 {} +
'
start_container
wait_for_health
docker cp tests/listener-contract.mjs "$container:/tmp/listener-contract.mjs"
docker cp tests/container-paseo-e2e.mjs "$container:/tmp/container-paseo-e2e.mjs"
docker exec -u 1001:1001 "$container" node /tmp/container-paseo-e2e.mjs restored-enabled

# Direct renderer acceptance uses the Chromium and playwright-core installed in
# the image. It requires no provider key or generation call.
docker cp tests/container-renderer-e2e.mjs "$container:/tmp/container-renderer-e2e.mjs"
docker exec "$container" node /tmp/container-renderer-e2e.mjs

# Create only daemon metadata over HTTP, then seed deterministic fixture HTML in
# that project's persistent directory. No BYOK call is involved.
# As above, this is the stripped nginx-side shape of the browser's prefixed API
# request. The response proves a non-health API survives ingress forwarding.
curl --fail-with-body -sS -o "$tmp/project.json" \
  -H "X-Ingress-Path: $ingress_prefix" \
  -H 'content-type: application/json' \
  --data '{"id":"ha-smoke","name":"HA smoke","skipDiscoveryBrief":true}' \
  "http://127.0.0.1:${port}/api/projects"
python3 - "$tmp/project.json" <<'PY'
import json
import sys
body = json.load(open(sys.argv[1], encoding='utf-8'))
assert 'ha-smoke' in json.dumps(body), body
PY
python3 - "$tmp/deck-file.json" tests/fixtures/export-deck.html <<'PY'
import json
import sys
from pathlib import Path

with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump({'name': 'deck.html', 'content': Path(sys.argv[2]).read_text(encoding='utf-8')}, handle)
PY
curl --fail-with-body -sS -o "$tmp/deck-file-response.json" \
  -H "X-Ingress-Path: $ingress_prefix" \
  -H 'content-type: application/json' \
  --data-binary "@$tmp/deck-file.json" \
  "http://127.0.0.1:${port}/api/projects/ha-smoke/files"
grep -Fq 'deck.html' "$tmp/deck-file-response.json"

# Run the actual injected scripts in Chromium through a Supervisor-style proxy
# that receives the public prefix, strips it, and supplies X-Ingress-Path to
# nginx. The probes exercise real browser transports and real export endpoints.
docker cp tests/container-ingress-browser-e2e.mjs "$container:/opt/ha-opendesign/container-ingress-browser-e2e.mjs"
docker exec "$container" node /opt/ha-opendesign/container-ingress-browser-e2e.mjs

# Start the real renderer acceptance in a fresh process namespace. Alpine
# crashpad state can remain unusable after closing the bridge-test Chromium on
# constrained GitHub runners even when no process is left to wait for.
docker stop -t 30 "$container" >/dev/null
docker rm "$container" >/dev/null
start_container
wait_for_health

post_export() {
  local endpoint=$1 body=$2 output=$3
  curl --fail-with-body -sS -o "$output" \
    -H 'content-type: application/json' --data "$body" \
    "http://127.0.0.1:${port}/api/projects/ha-smoke/export/${endpoint}"
  test -s "$output"
}

post_export image '{"fileName":"deck.html","deck":true,"imageFormat":"png"}' "$tmp/deck.png"
post_export image '{"fileName":"deck.html","deck":true,"imageFormat":"jpeg"}' "$tmp/deck.jpg"
post_export pdf-image '{"fileName":"deck.html","deck":true,"title":"Smoke"}' "$tmp/deck.pdf"
post_export pptx '{"fileName":"deck.html","deck":true,"title":"Smoke"}' "$tmp/deck.pptx"

docker cp "$tmp/deck.pdf" "$container:/tmp/smoke-deck.pdf" >/dev/null
test "$(docker exec "$container" pdfinfo /tmp/smoke-deck.pdf | awk '/^Pages:/ { print $2 }')" = 2

python3 - "$tmp/deck.png" "$tmp/deck.jpg" "$tmp/deck.pdf" "$tmp/deck.pptx" <<'PY'
from pathlib import Path
import io
import re
import struct
import sys
import zipfile
import zlib

png, jpg, pdf, pptx = map(Path, sys.argv[1:])


def png_pixels(data):
    assert data.startswith(b'\x89PNG\r\n\x1a\n')
    offset = 8
    compressed = bytearray()
    width = height = color_type = None
    while offset < len(data):
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if kind == b'IHDR':
            width, height, depth, color_type = struct.unpack('>IIBB', payload[:10])
            assert depth == 8 and color_type in (2, 6)
        elif kind == b'IDAT':
            compressed.extend(payload)
        elif kind == b'IEND':
            break
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    raw = zlib.decompress(compressed)
    rows = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        encoded = raw[cursor:cursor + stride]
        cursor += stride
        row = bytearray(stride)
        for index, byte in enumerate(encoded):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                estimate = left + above - upper_left
                distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            else:
                raise AssertionError(f'unsupported PNG filter {filter_type}')
            row[index] = (byte + predictor) & 0xff
        rows.append(row)
        previous = row
    return width, height, channels, rows


def jpeg_dimensions(data):
    assert data.startswith(b'\xff\xd8\xff')
    offset = 2
    while offset + 8 < len(data):
        if data[offset] != 0xff:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker in (0xd8, 0xd9):
            offset += 2
            continue
        length = struct.unpack('>H', data[offset + 2:offset + 4])[0]
        if 0xc0 <= marker <= 0xc3:
            return struct.unpack('>HH', data[offset + 5:offset + 9])
        offset += 2 + length
    raise AssertionError('JPEG dimensions not found')


png_data = png.read_bytes()
width, height, channels, rows = png_pixels(png_data)
# Upstream may preserve the requested viewport around the two stacked slides,
# so assert the authored content extent and both slide colors rather than a
# tightly-cropped canvas size.
assert width >= 640 and height >= 720, (width, height)
sample_x = 320 * channels
top = tuple(rows[180][sample_x:sample_x + 3])
bottom = tuple(rows[540][sample_x:sample_x + 3])
assert all(abs(actual - expected) <= 3 for actual, expected in zip(top, (22, 93, 186))), top
assert all(abs(actual - expected) <= 3 for actual, expected in zip(bottom, (170, 51, 51))), bottom

jpg_data = jpg.read_bytes()
jpeg_height, jpeg_width = jpeg_dimensions(jpg_data)
assert jpeg_width >= 640 and jpeg_height >= 720, (jpeg_width, jpeg_height)

pdf_data = pdf.read_bytes()
assert pdf_data.startswith(b'%PDF-') and len(pdf_data) > 100

pptx_data = pptx.read_bytes()
assert pptx_data.startswith(b'PK') and len(pptx_data) > 100
with zipfile.ZipFile(io.BytesIO(pptx_data)) as archive:
    slides = [name for name in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)]
assert len(slides) == 2, slides
print('HTTP exports: two-color full-deck PNG/JPEG, 2-page PDF, and 2-slide PPTX')
PY

editable_status=$(curl -sS -o "$tmp/editable.json" -w '%{http_code}' \
  -H 'content-type: application/json' \
  --data '{"fileName":"deck.html","deck":true,"editable":true}' \
  "http://127.0.0.1:${port}/api/projects/ha-smoke/export/pptx")
test "$editable_status" = 502
grep -qi 'Editable PPTX is unsupported' "$tmp/editable.json"

# The seeded project and DB record remain after the earlier restart; this export
# set proves renderer/assembly operation without needing an AI provider key.
echo 'container smoke: real-browser HA prefix/probes/actions, health/API, persistence, renderer, and HTTP assembly passed'
