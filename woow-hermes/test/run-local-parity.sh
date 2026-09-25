#!/usr/bin/env bash
# Local ingress-parity check: run the built add-on image behind an HA ingress
# emulator and walk every dashboard page directly and through ingress.
#   hermes/test/run-local-parity.sh <image> <outdir>
set -euo pipefail
IMAGE=${1:?image}
OUT=${2:?outdir}
HERE=$(cd "$(dirname "$0")" && pwd)
NET=woow-hermes-test
TOKEN=testtoken0123456789abcdefghijklmnopqrstuvwxy
mkdir -p "$OUT/data"

cleanup() {
    podman logs woow-hermes-test-addon >"$OUT/addon.log" 2>&1 || true
    podman logs woow-hermes-test-ingress >"$OUT/ingress.log" 2>&1 || true
    podman rm -f woow-hermes-test-addon woow-hermes-test-ingress >/dev/null 2>&1 || true
    podman volume rm -f woow-hermes-test-home >/dev/null 2>&1 || true
    podman network rm -f "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

PW=$(head -c 18 /dev/urandom | base64 | tr -d '/+=')
printf '%s' "$PW" >"$OUT/.pw"
jq -n --arg pw "$PW" '{dashboard_username: "admin", dashboard_password: $pw, env_vars: []}' >"$OUT/data/options.json"

podman network create --subnet 172.30.32.0/23 "$NET" >/dev/null
podman run -d --name woow-hermes-test-addon --network "$NET" --ip 172.30.33.10 --memory=3g \
    -v "$OUT/data:/data:Z" -v woow-hermes-test-home:/opt/data -p 127.0.0.1:19119:9119 "$IMAGE" >/dev/null
# HA ingress stand-in at the Supervisor's address, run with the image's own
# aiohttp. Like HA, it hands the browser a 1000 for every WebSocket close.
podman run -d --name woow-hermes-test-ingress --network "$NET" --ip 172.30.32.2 \
    -v "$HERE/ha_ingress_emulator.py:/emulator.py:ro,Z" -p 127.0.0.1:18080:8080 \
    --entrypoint /opt/hermes/.venv/bin/python "$IMAGE" /emulator.py 8080 http://172.30.33.10:9120 >/dev/null

for _ in $(seq 1 90); do
    curl -fsS -o /dev/null http://127.0.0.1:19119/login && break
    sleep 2
done
curl -fsS -o /dev/null http://127.0.0.1:19119/login

# Boot provisioning: the Webhooks page reads platforms.webhook from config.yaml.
# Poll the value itself: the log's "done" line comes before this step runs.
for _ in $(seq 1 60); do
    webhook=$(podman exec -u hermes woow-hermes-test-addon /opt/hermes/.venv/bin/hermes config get platforms.webhook.enabled 2>&1 || true)
    [[ $webhook == true ]] && break
    sleep 5
done
echo "platforms.webhook.enabled: ${webhook}"
[[ $webhook == true ]]
# Swagger's spec names the ingress prefix as its server through the sidebar
# only (P4k); the LAN port's spec is untouched.
TOKEN_PATH="/api/hassio_ingress/$TOKEN"
spec_login() {  # base cookie-jar
    curl -fsS -c "$2" -o /dev/null -X POST "$1auth/password-login" -H 'Content-Type: application/json' \
        -d "$(jq -nc --arg pw "$PW" '{provider: "basic", username: "admin", password: $pw, next: "/"}')"
}
spec_login http://127.0.0.1:19119/ "$OUT/jar-direct"
spec_login "http://127.0.0.1:18080$TOKEN_PATH/" "$OUT/jar-ingress"
servers_direct=$(curl -fsS -b "$OUT/jar-direct" http://127.0.0.1:19119/openapi.json | jq -c '.servers')
servers_ingress=$(curl -fsS -b "$OUT/jar-ingress" "http://127.0.0.1:18080$TOKEN_PATH/openapi.json" | jq -c '.servers')
echo "openapi servers: direct ${servers_direct}, ingress ${servers_ingress}"
[[ $servers_direct == null && $servers_ingress == "[{\"url\":\"$TOKEN_PATH\"}]" ]]

# The approval gate refuses dangerous commands in unattended runs.
podman run --rm -v "$HERE:/t:ro,Z" --entrypoint /opt/hermes/.venv/bin/python "$IMAGE" /t/test-approval-gate.py

# Web and browser backends the add-on defaults to.
for pair in web.search_backend=ddgs web.extract_backend=parallel browser.backend=off; do
    value=$(podman exec -u hermes woow-hermes-test-addon /opt/hermes/.venv/bin/hermes config get "${pair%%=*}" 2>&1 || true)
    echo "${pair%%=*}: ${value}"
    [[ $value == "${pair#*=}" ]]
done

# Upstream's approval defaults stay in place.
hermes_get() { podman exec -u hermes woow-hermes-test-addon /opt/hermes/.venv/bin/hermes config get "$1" 2>&1 || true; }
approvals=$(hermes_get approvals.mode)
cron=$(hermes_get approvals.cron_mode)
echo "approvals.mode: ${approvals}, approvals.cron_mode: ${cron}"
[[ $approvals == smart && $cron == deny ]]

if [[ -z ${SKIP_WALK:-} ]]; then
    node "$HERE/walk.js" direct http://127.0.0.1:19119/ "$OUT/direct" "$OUT/.pw"
    node "$HERE/walk.js" ingress "http://127.0.0.1:18080/api/hassio_ingress/$TOKEN/" "$OUT/ingress" "$OUT/.pw"
fi
for base in http://127.0.0.1:19119/ "http://127.0.0.1:18080/api/hassio_ingress/$TOKEN/"; do
    KILL_TUI="podman exec woow-hermes-test-addon pkill -f ui-tui/dist" \
        node "$HERE/test-chat-close-codes.js" "$base" "$OUT/.pw" "$OUT" | tee -a "$OUT/chat-close-codes.txt"
done
node "$HERE/test-reload-route.js" direct http://127.0.0.1:19119/ "$OUT/.pw" | tee -a "$OUT/reload-route.txt"
node "$HERE/test-reload-route.js" panel http://127.0.0.1:18080/__ha_panel.html \
    "http://127.0.0.1:18080/api/hassio_ingress/$TOKEN/" "$OUT/.pw" | tee -a "$OUT/reload-route.txt"
node "$HERE/test-cookie-isolation.js" http://127.0.0.1:19119/ "http://127.0.0.1:18080/api/hassio_ingress/$TOKEN/" "$OUT/.pw" \
    | tee "$OUT/cookie-isolation.txt"
if [[ -z ${SKIP_WALK:-} ]]; then
    echo "--- direct";  cat "$OUT/direct/summary.json"
    echo "--- ingress"; cat "$OUT/ingress/summary.json"
fi
