#!/usr/bin/env bash
# Container-level proof of the built-in OpenDesign MCP server on the builder VM (test-only, never production).
#
#   IMG=<built add-on image> [PROOF_PREFIX=<container name prefix>] mcp-runtime/tests/e2e/run-proof.sh <evidence-dir>
#
# Topology on a throwaway Docker network shaped like HA's hassio network (172.30.32.0/23):
#   172.30.32.2  stand-in for the Supervisor Ingress peer (alias "supervisor"). It serves NOTHING: administration
#                must work with no Supervisor/Core API (owner decision 2026-10-14, Ingress login only)
#   172.30.33.10 the add-on image (real launcher: OpenDesign, nginx, ttyd, built-in MCP), /data on a fresh volume
#   172.30.33.20 a LAN-style MCP client
# Throwaway credentials are generated here and live only in this shell; every evidence file is checked for them.
set -Eeuo pipefail

IMG=${IMG:?built add-on image}
EV=${1:?evidence dir}
P=${PROOF_PREFIX:-mcp-proof}
NET=$P-hassio
E2E=$(cd "$(dirname "$0")" && pwd)
ADDON=172.30.33.10
PY=/opt/woow/.venv/bin/python
mkdir -p "$EV"
rand() { head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
SUP_TOKEN=$(rand 32)
FAKE_ADMIN_ID=$(rand 16)
FAKE_USER_ID=$(rand 16)
TOKEN=''
OLD=''
SEEN=("$SUP_TOKEN")  # every credential this run has held, for redaction and the final leak check
red() { local s t; s=$(cat); for t in "${SEEN[@]}" "$TOKEN"; do [[ -n $t ]] && s=${s//"$t"/[REDACTED]}; done; printf '%s\n' "$s"; }
log() { printf '\n### %s\n' "$*"; }
probe() { docker exec -e MCP_TOKEN="$1" $P-client $PY /e2e/mcp_probe.py "http://$ADDON:8081" "${@:2}"; }
admin() { docker exec -e FAKE_ADMIN_ID="$FAKE_ADMIN_ID" -e FAKE_USER_ID="$FAKE_USER_ID" $P-supervisor $PY /e2e/admin_probe.py $ADDON "$@"; }
wait_ready() {
  local start=$SECONDS
  until probe '' ready 2>/dev/null | grep -q '"status": 200'; do
    (( SECONDS - start < ${1:-240} )) || { echo "not ready after ${1:-240}s"; return 1; }
    sleep 3
  done
  echo "ready after ~$((SECONDS - start))s"
}
# Each step runs in THIS shell (token rotation must persist), its output is redacted into the evidence file.
step() {
  local file=$1; shift
  "$@" > "$EV/.raw" 2>&1 || echo "STEP EXIT $?" >> "$EV/.raw"
  red < "$EV/.raw" > "$EV/$file"
  rm -f "$EV/.raw"
}
cleanup() {
  docker rm -f $P-addon $P-supervisor $P-client >/dev/null 2>&1 || true
  docker network rm $NET >/dev/null 2>&1 || true
  docker volume rm $P-data >/dev/null 2>&1 || true
}
[[ ${KEEP:-0} == 1 ]] || trap cleanup EXIT
cleanup

docker network create --subnet 172.30.32.0/23 $NET >/dev/null
docker volume create $P-data >/dev/null
docker run -d --name $P-supervisor --network $NET --ip 172.30.32.2 --network-alias supervisor \
  -v "$E2E:/e2e:ro" --entrypoint sleep "$IMG" infinity >/dev/null
docker run -d --name $P-addon --network $NET --ip $ADDON --hostname local-woow-ha-opendesign \
  -e SUPERVISOR_TOKEN="$SUP_TOKEN" -v $P-data:/data --restart on-failure:10 "$IMG" >/dev/null
docker run -d --name $P-client --network $NET --ip 172.30.33.20 -v "$E2E:/e2e:ro" --entrypoint sleep "$IMG" infinity >/dev/null

s01() {
  log "image"
  docker image inspect "$IMG" --format 'id={{.Id}} created={{.Created}}'
  docker exec $P-client sh -c "sed -n 's/.*\"source_commit\": \"\\([0-9a-f]*\\)\".*/vendored Woow_ha_mcp_addons commit \\1/p' /opt/woow/VENDOR.json; /usr/bin/python3 --version; grep '\"version\"' /app/apps/daemon/package.json"
  log "startup"
  wait_ready 300
  docker logs $P-addon 2>&1 | tail -n 15
}
s02() {
  log "LAN MCP on 8081: auth refusals"
  probe "$TOKEN" auth
  log "LAN MCP on 8081: Bearer flow (initialize -> tools/list -> tools/call)"
  probe "$TOKEN" bearer
  log "Claude.ai-style URL secret /private_<token>/mcp (Origin allowed), wrong secret"
  probe "$TOKEN" secret
  log "readiness"
  probe '' ready
}
s03() {
  log "Ingress /mcp-admin/ from the Supervisor peer (no Supervisor/Core API exists on this network)"
  admin checks
  log "/mcp-admin/ from a non-Supervisor peer (LAN client) -> nginx"
  docker exec $P-client $PY -c "import httpx; r = httpx.get('http://$ADDON:8099/mcp-admin/api/bootstrap', headers={'X-Remote-User-Id': '$FAKE_ADMIN_ID'}); print('status', r.status_code)"
}
s04() {
  log "0.2.1 defaults on a fresh install: all 15 tools; the three writers granted once at first start"
  admin policy
  probe "$TOKEN" tools
  docker exec $P-addon cat /data/mcp/ha-tool-defaults.json
  docker logs $P-addon 2>&1 | grep -c 'tool defaults applied' | sed 's/^/defaults log lines: /'
  log "administrator removes every grant: reads only"
  admin ungrant
  probe "$TOKEN" tools
  log "write grant: delete_project only (exact grant)"
  admin grant-delete
  probe "$TOKEN" tools
  log "the three writers granted again"
  admin grant-writers
  probe "$TOKEN" tools
}
s15() {
  log "0.2.1 tools on a real project (no agent is signed in on this system: runs fail at once, nothing is charged)"
  local out pid
  out=$(probe "$TOKEN" create)
  echo "$out"
  pid=$(sed -n 's/^project=\([0-9a-f-]*\)$/\1/p' <<<"$out")
  [[ -n $pid ]] || { echo "no project id"; return 1; }
  log "files written into the project as uid open-design (what an agent would do)"
  docker exec -u open-design $P-addon sh -c "cd /data/opendesign/projects/$pid && printf '<h1>e2e</h1>\\n' > index.html \
    && mkdir -p sub keys && printf 'nested\\n' > sub/a.txt && printf 'FAKE_E2E_VALUE=1\\n' > .env \
    && printf 'not a key' > keys/server.pem && head -c 300 /dev/urandom > bin.dat \
    && head -c 1100000 /dev/zero | tr '\\000' a > big.txt && find . -type f | sort"
  probe "$TOKEN" "files=$pid"
  probe "$TOKEN" "chat=$pid" connectors runs
  probe "$TOKEN" "delete=$pid"
}
s05() {
  log "token rotate: old token refused, new token accepted"
  OLD=$TOKEN
  TOKEN=$(admin rotate)
  SEEN+=("$TOKEN")
  echo "old token: $(probe "$OLD" status)"
  echo "new token: $(probe "$TOKEN" status)"
  log "token revoke: every token refused (Bearer and URL secret)"
  admin revoke
  echo "after revoke: $(probe "$TOKEN" status)"
  docker exec $P-client $PY -c "import httpx; print('secret path after revoke', httpx.post('http://$ADDON:8081/private_$TOKEN/mcp', json={}).status_code)"
  log "rotate again restores access"
  OLD=$TOKEN
  TOKEN=$(admin rotate)
  SEEN+=("$TOKEN")
  echo "rotated: $(probe "$TOKEN" status)"
}
s06() { docker exec -i $P-addon sh /dev/stdin < "$E2E/container_probe.sh"; }
s07() {
  log "OpenDesign daemon paused (SIGSTOP): MCP stays up, the tool reports a backend error"
  local od
  od=$(daemon_pid)
  echo "daemon: $(docker exec $P-addon cat /proc/$od/cmdline | tr '\0' ' ')"
  docker exec $P-addon kill -STOP "$od"
  probe "$TOKEN" health
  sleep 20
  probe '' ready
  docker exec $P-addon kill -CONT "$od"
  log "daemon resumed (SIGCONT)"
  wait_ready 60
  probe "$TOKEN" health
}
# The OpenDesign node process itself (su-exec execs it directly).
daemon_pid() {
  local pid
  pid=$(docker exec $P-addon pgrep -f '^/usr/local/bin/node /opt/ha-opendesign/headless-entry.mjs' | head -1)
  [[ -n $pid ]] || { echo "OpenDesign daemon process not found" >&2; return 1; }
  echo "$pid"
}
restarted_within() {  # wait until the container's StartedAt changes; print the seconds it took
  local before=$1 limit=$2 start=$SECONDS
  until [[ $(docker inspect -f '{{.State.StartedAt}}' $P-addon) != "$before" ]]; do
    (( SECONDS - start < limit )) || { echo "no restart within ${limit}s"; return 1; }
    sleep 1
  done
  echo "container restarted after ~$((SECONDS - start))s (restart count $(docker inspect -f '{{.RestartCount}}' $P-addon))"
}
s08() {
  log "OpenDesign daemon crashes (SIGKILL): launcher stops all four processes, container restarts, same token works"
  local od before
  before=$(docker inspect -f '{{.State.StartedAt}}' $P-addon)
  od=$(daemon_pid)
  docker exec $P-addon kill -KILL "$od"
  restarted_within "$before" 180
  wait_ready 300
  probe "$TOKEN" bearer
  docker logs $P-addon 2>&1 | grep -E '^\[ha-opendesign\]|ha-opendesign-mcp|required process' | tail -n 4
  log "OpenDesign daemon stopped gracefully (SIGTERM): observed shutdown/restart time (OpenDesign-side behaviour)"
  before=$(docker inspect -f '{{.State.StartedAt}}' $P-addon)
  od=$(daemon_pid)
  docker exec $P-addon kill -TERM "$od"
  probe "$TOKEN" status
  restarted_within "$before" 240
  wait_ready 300
  probe "$TOKEN" status
  docker logs $P-addon 2>&1 | grep -E 'SIGTERM received|Aborted|required process' | tail -n 3
}
s09() {
  log "Claude Code $(docker exec $P-client claude --version 2>/dev/null) as an MCP client (Bearer header, URL secret, no auth)"
  docker exec -e HOME=/tmp/cc $P-client sh -c "mkdir -p /tmp/cc && cd /tmp/cc && claude mcp add -s user --transport http od-bearer http://$ADDON:8081/mcp --header 'Authorization: Bearer $TOKEN' >/dev/null && claude mcp add -s user --transport http od-secret http://$ADDON:8081/private_$TOKEN/mcp >/dev/null && claude mcp add -s user --transport http od-no-auth http://$ADDON:8081/mcp >/dev/null && timeout 120 claude mcp list"
}

s11() {
  log "OpenDesign page through a Supervisor-style ingress proxy: MCP Server entry -> /mcp-admin/ (Chromium)"
  docker cp "$E2E/mcp_link_browser.mjs" $P-supervisor:/opt/ha-opendesign/mcp_link_browser.mjs
  docker exec -e ADDON=$ADDON -e FAKE_ADMIN_ID="$FAKE_ADMIN_ID" $P-supervisor node /opt/ha-opendesign/mcp_link_browser.mjs
}

s12() {
  log "built-in MCP management process killed (SIGKILL): the whole add-on restarts (owner decision), same token works"
  local mgmt before
  before=$(docker inspect -f '{{.State.StartedAt}}' $P-addon)
  mgmt=$(docker exec $P-addon pgrep -f 'ha_opendesign_mcp/management.py' | head -1)
  docker exec $P-addon kill -KILL "$mgmt"
  restarted_within "$before" 180
  wait_ready 300
  probe "$TOKEN" status
  docker logs $P-addon 2>&1 | grep -E 'required process mcp' | tail -n 1
}

s13() {
  log "Claude.ai connector sequence over the URL secret (server/discover, initialize 2025-11-25, _meta everywhere, unknown request/notification)"
  probe "$TOKEN" claudeai
  log "refused tools/call (gateway 0.1.14): HTTP 200 JSON-RPC errors with a reason, no input echo; without a session 403"
  probe "$TOKEN" refusals
}
s14() {
  log "client handshake while the add-on restarts after an OpenDesign crash (SIGKILL of the daemon): per-second attempts"
  local od
  od=$(daemon_pid)
  docker exec $P-addon kill -KILL "$od"
  docker exec -e MCP_TOKEN="$TOKEN" -e STARTING_SECONDS=150 $P-client $PY /e2e/mcp_probe.py "http://$ADDON:8081" starting
}

step 01-startup.txt s01
TOKEN=$(admin reveal)
[[ ${#TOKEN} == 43 ]] || { echo "unexpected token shape"; exit 1; }
SEEN+=("$TOKEN")
step 02-mcp.txt s02
step 03-admin.txt s03
step 04-policy.txt s04
step 15-tools-0.2.1.txt s15
step 05-token-lifecycle.txt s05
step 06-container.txt s06
step 07-daemon-pause.txt s07
step 08-daemon-restart.txt s08
step 09-claude-code.txt s09
step 11-mcp-link-browser.txt s11
step 12-mcp-process-restart.txt s12
step 13-claudeai-and-refusals.txt s13
step 14-restart-window.txt s14

patterns=(); for t in "${SEEN[@]}"; do patterns+=(-e "$t"); done
if grep -rlF "${patterns[@]}" "$EV"; then echo "LEAK: token found in evidence" | tee "$EV/10-leak-check.txt"; exit 1; fi
echo "leak check: none of the ${#SEEN[@]} throwaway credentials (Supervisor token, every MCP token of this run) appears in the evidence files" | tee "$EV/10-leak-check.txt"
