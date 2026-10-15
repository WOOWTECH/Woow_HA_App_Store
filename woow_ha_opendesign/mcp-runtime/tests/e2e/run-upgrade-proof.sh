#!/usr/bin/env bash
# 0.2.0 -> 0.2.1 upgrade proof of the built-in MCP server's one-time default grants (test-only, builder VM).
#
#   OLD_IMG=<0.2.0 image> IMG=<0.2.1 image> [PROOF_PREFIX=...] mcp-runtime/tests/e2e/run-upgrade-proof.sh <evidence-dir>
#
# 1. 0.2.0 on a fresh /data volume; the administrator disables delete_project (and grants nothing).
# 2. The same volume under 0.2.1: create_project and send_message are granted once, delete_project stays disabled,
#    the marker /data/mcp/ha-tool-defaults.json records it: 14 tools.
# 3. The administrator removes every grant and the add-on restarts: the marker keeps the grants from coming back.
# Same network shape as run-proof.sh (Supervisor Ingress peer 172.30.32.2, add-on 172.30.33.10, client .20).
set -Eeuo pipefail

OLD_IMG=${OLD_IMG:?0.2.0 add-on image}
IMG=${IMG:?0.2.1 add-on image}
EV=${1:?evidence dir}
P=${PROOF_PREFIX:-mcp-upgrade}
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
red() { local s t; s=$(cat); for t in "$SUP_TOKEN" "$TOKEN"; do [[ -n $t ]] && s=${s//"$t"/[REDACTED]}; done; printf '%s\n' "$s"; }
log() { printf '\n### %s\n' "$*"; }
probe() { docker exec -e MCP_TOKEN="$1" $P-client $PY /e2e/mcp_probe.py "http://$ADDON:8081" "${@:2}"; }
admin() { docker exec -e FAKE_ADMIN_ID="$FAKE_ADMIN_ID" -e FAKE_USER_ID="$FAKE_USER_ID" $P-supervisor $PY /e2e/admin_probe.py $ADDON "$@"; }
wait_ready() {
  local start=$SECONDS
  until probe '' ready 2>/dev/null | grep -q '"status": 200'; do
    (( SECONDS - start < 300 )) || { echo "not ready after 300s"; return 1; }
    sleep 3
  done
  echo "ready after ~$((SECONDS - start))s"
}
run_addon() {
  docker rm -f $P-addon >/dev/null 2>&1 || true
  docker run -d --name $P-addon --network $NET --ip $ADDON --hostname local-woow-ha-opendesign \
    -e SUPERVISOR_TOKEN="$SUP_TOKEN" -v $P-data:/data "$1" >/dev/null
}
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
docker run -d --name $P-client --network $NET --ip 172.30.33.20 -v "$E2E:/e2e:ro" --entrypoint sleep "$IMG" infinity >/dev/null

u01() {
  log "0.2.0 ($OLD_IMG) on a fresh volume"
  run_addon "$OLD_IMG"
  wait_ready
  log "0.2.0 administrator: delete_project disabled, no grants"
  admin disable-delete
  admin policy
  docker exec $P-addon sh -c 'ls /data/mcp; test ! -e /data/mcp/ha-tool-defaults.json && echo "no marker (0.2.0)"'
}
u02() {
  log "the same volume under 0.2.1 ($IMG)"
  run_addon "$IMG"
  wait_ready
  docker logs $P-addon 2>&1 | grep 'tool defaults applied'
  admin policy
  probe "$TOKEN" tools runs
  docker exec $P-addon cat /data/mcp/ha-tool-defaults.json
  docker exec $P-addon stat -c '%a %u:%g %n' /data/mcp/ha-tool-defaults.json /data/mcp/state.json
}
u03() {
  log "administrator removes every grant (and the disable), then the add-on restarts"
  admin ungrant
  docker restart $P-addon >/dev/null
  wait_ready
  admin policy
  probe "$TOKEN" tools
  # The container's log spans both starts: one line means the defaults were applied only at the first 0.2.1 start.
  echo "defaults log lines in this container's whole log: $(docker logs $P-addon 2>&1 | grep -c 'tool defaults applied' || true)"
  log "and once more"
  docker restart $P-addon >/dev/null
  wait_ready
  admin policy
}

docker volume inspect $P-data >/dev/null
step u01-old-0.2.0.txt u01
TOKEN=$(admin reveal)
[[ ${#TOKEN} == 43 ]] || { echo "unexpected token shape"; exit 1; }
step u01b-old-0.2.0-tools.txt probe "$TOKEN" tools runs
step u02-upgrade-0.2.1.txt u02
step u03-revoked-stays-revoked.txt u03
if grep -rlF -e "$TOKEN" -e "$SUP_TOKEN" "$EV"; then echo "LEAK: token found in evidence"; exit 1; fi
echo "leak check: neither throwaway credential appears in the evidence files" | tee "$EV/u10-leak-check.txt"
