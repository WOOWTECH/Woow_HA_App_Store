#!/bin/bash
# s6 startup and stop of a BUILT image, with Collabora enabled (pipeline unattended-pipeline/224).
# Usage: test-s6-stop.sh <image>
#
# Supervisor stops an add-on with SIGTERM and SIGKILLs it after 10 s (exit 137). s6-overlay's
# stop (rc.shutdown: s6-rc -b ... change) waits for a start transition that is still running,
# so any slow step that holds s6 startup (stage2) open also holds the stop. The richdocuments
# configuration waits for coolwsd and runs a dozen occ calls; on slow hardware that took
# minutes, and every stop during it ended in 137.
#
# The test slows down only the occ calls made by the richdocuments configuration (each waits
# OCC_DELAY seconds) to stand in for slow hardware, and checks:
#   1. s6 startup finishes soon after nginx is up, while richdocuments is still being configured;
#   2. a stop at that point finishes within the Supervisor limit, exit code 0, postgres shut down;
#   3. on the next start (no delay) richdocuments ends up enabled with the WOPI settings, and
#      a stop after that is also clean.
set -euo pipefail
IMAGE=$1
OCC_DELAY=${OCC_DELAY:-8}
NAME=nc-s6-stop-$$
work=$(mktemp -d)
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true; docker run --rm -v "$work:/w" --entrypoint rm "$IMAGE" -rf /w/data /w/share >/dev/null 2>&1 || true; rm -rf "$work"' EXIT
mkdir -p "$work/data" "$work/share"
cat > "$work/data/options.json" <<JSON
{"TZ":"UTC","NEXTCLOUD_PUBLIC_URL":"https://nextcloud.ci.invalid","HA_PUBLIC_URL":"https://ha.ci.invalid","ADMIN_USER":"ci-admin","ADMIN_PASS":"$(openssl rand -hex 16)","NEXTCLOUD_DATADIR":"/share/nextcloud","DEFAULT_PHONE_REGION":"TW","COLLABORA_ADMIN_USER":"ci-code","COLLABORA_ADMIN_PASS":"$(openssl rand -hex 16)","ENABLE_COLLABORA":true,"ENABLE_COLLABORA_ADMIN":false,"trusted_domains":[],"trusted_proxies":[]}
JSON
echo "$OCC_DELAY" > "$work/data/test-occ-delay"
# Same as the image's occ, plus a delay for calls whose parent is the richdocuments configuration.
cat > "$work/occ" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ -s /data/test-occ-delay ]] && grep -q richdocuments "/proc/$PPID/cmdline" 2>/dev/null; then
  sleep "$(cat /data/test-occ-delay)"
fi
cd /var/www/nextcloud
exec gosu www-data php occ "$@"
SH
chmod 0755 "$work/occ"

fail() { echo "FAIL: $*" >&2; docker logs "$NAME" 2>&1 | grep -E '^s6-rc|richdocuments|^Config value|LOG:' | tail -40 >&2; exit 1; }
# s6 and add-on lines only (coolwsd's trace output is very long).
logs_since() { docker logs --since "$1" "$NAME" 2>&1 | grep -vE '^(wsd|kit|frk)-|^\|' || true; }
wait_for() { # <since> <regex> <seconds>
  local i
  for ((i = 0; i < $3; i += 2)); do
    logs_since "$1" | grep -qE "$2" && return 0
    docker inspect -f '{{.State.Running}}' "$NAME" | grep -q true || return 1
    sleep 2
  done
  return 1
}
stop_clean() { # <since> <what>
  local t0 t1 code
  t0=$(date +%s)
  docker stop -t 10 "$NAME" >/dev/null
  t1=$(date +%s)
  code=$(docker inspect -f '{{.State.ExitCode}}' "$NAME")
  echo "stop ($2): $((t1 - t0)) s, exit code $code"
  [[ "$code" != 137 ]] || { echo "FAIL: stop ($2) was SIGKILLed (exit 137): s6 did not finish stopping within 10 s" >&2; return 1; }
  [[ "$code" == 0 ]] || { echo "FAIL: stop ($2) exit code $code, expected 0" >&2; return 1; }
  logs_since "$1" | grep -q 'database system is shut down' || { echo "FAIL: stop ($2): postgres did not shut down cleanly" >&2; return 1; }
}

echo "== boot 1 (first install, richdocuments occ calls delayed ${OCC_DELAY}s each)"
since1=$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker run -d --name "$NAME" --cap-add SYS_ADMIN --tmpfs /tmp -v "$work/data:/data" -v "$work/share:/share" \
  -v "$work/occ:/usr/local/bin/occ:ro" "$IMAGE" >/dev/null
wait_for "$since1" 'service svc-nginx successfully started' 900 || fail "nginx did not start"
# On failure, still stop now: the stop result is the second half of the check.
stage2=ok
wait_for "$since1" 'legacy-services successfully started' 30 || stage2=
sleep 3
stopped=ok
stop_clean "$since1" "during richdocuments configuration" || stopped=
[[ -n "$stage2" ]] || fail "s6 startup did not finish within 30 s of nginx starting (a slow step holds stage2 open)"
echo "s6 startup finished"
[[ -n "$stopped" ]] || fail "stop during richdocuments configuration was not clean"

echo "== boot 2 (no delay): richdocuments configured, then stop"
rm -f "$work/data/test-occ-delay" 2>/dev/null || docker run --rm -v "$work/data:/data" --entrypoint rm "$IMAGE" -f /data/test-occ-delay
since2=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sleep 1
docker start "$NAME" >/dev/null
wait_for "$since2" 'legacy-services successfully started' 600 || fail "boot 2: s6 startup did not finish"
ok=
for _ in $(seq 1 90); do
  if docker exec "$NAME" occ app:list --output=json 2>/dev/null | jq -e '.enabled.richdocuments' >/dev/null \
     && [[ "$(docker exec "$NAME" occ config:app:get richdocuments wopi_url 2>/dev/null)" == "http://127.0.0.1:9980" ]] \
     && [[ "$(docker exec "$NAME" occ config:app:get richdocuments public_wopi_url 2>/dev/null)" == "https://nextcloud.ci.invalid" ]] \
     && [[ "$(docker exec "$NAME" occ config:app:get richdocuments wopi_callback_url 2>/dev/null)" == "https://nextcloud.ci.invalid" ]]; then
    ok=1; break
  fi
  sleep 2
done
[[ -n "$ok" ]] || fail "boot 2: richdocuments not enabled or WOPI settings wrong"
echo "richdocuments enabled, WOPI settings OK"
stop_clean "$since2" "after richdocuments configuration" || fail "stop after richdocuments configuration was not clean"
echo "s6 stop OK: $IMAGE"
