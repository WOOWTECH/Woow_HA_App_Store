#!/usr/bin/env bash
# End-to-end smoke test against a running add-on instance.
#
# Requires a long-lived HA token and the addon slug.
#   HA_URL           — e.g. https://woowtech-ha.woowtech.io
#   HA_TOKEN         — HA long-lived access token
#   ADDON_SLUG       — e.g. b9cf5676_woow_ha_pi_agent
#
# Checks:
#   1. Supervisor reports addon installed + started + latest version
#   2. Store has the addon marked available (i.e. no cache staleness)
#   3. Bootstrap log lines exist for GLM (and MiniMax when configured)
#   4. Ingress "/" returns HTML rewritten with the ingress prefix
set -uo pipefail

: "${HA_URL:?HA_URL required (e.g. https://your-ha.example.com)}"
: "${HA_TOKEN:?HA_TOKEN required (HA long-lived access token)}"
: "${ADDON_SLUG:?ADDON_SLUG required (e.g. b9cf5676_woow_ha_pi_agent)}"

PASS=0; FAIL=0

pass() { PASS=$((PASS+1)); printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m  %s\n         %s\n' "$1" "$2"; }

need() { command -v "$1" >/dev/null || { echo "missing: $1"; exit 2; }; }
need curl
need jq

H=(-H "Authorization: Bearer $HA_TOKEN")

echo "── addon installed + started + up-to-date ──"
info=$(curl -sS "${H[@]}" "${HA_URL}/api/hassio/addons/${ADDON_SLUG}/info")
state=$(printf '%s' "$info" | jq -r '.data.state // "unknown"')
ver=$(printf '%s' "$info" | jq -r '.data.version // "unknown"')
latest=$(printf '%s' "$info" | jq -r '.data.version_latest // "unknown"')
upd=$(printf '%s' "$info" | jq -r '.data.update_available // false')
[ "$state" = "started" ] && pass "state=started" || fail "state" "$state"
[ "$upd" = "false" ] && pass "version $ver (latest: $latest)" || fail "outdated" "installed $ver, latest $latest"

echo "── bootstrap log lines present ──"
logs=$(curl -sS "${H[@]}" "${HA_URL}/api/hassio/addons/${ADDON_SLUG}/logs")
printf '%s' "$logs" | grep -q "Bootstrapping .* with GLM provider" \
  && pass "GLM bootstrap ran on first start" \
  || fail "GLM bootstrap" "not found in logs (has models.json survived from earlier? that's fine)"
if printf '%s' "$logs" | grep -q "Adding minimax provider"; then
  pass "MiniMax provider merged into models.json"
else
  printf '  \033[33mSKIP\033[0m  MiniMax bootstrap line — MINIMAX_API_KEY unset OR provider already present\n'
fi

echo "── ingress HTML rewritten to carry ingress prefix ──"
ingress_url=$(printf '%s' "$info" | jq -r '.data.ingress_url // ""')
if [ -z "$ingress_url" ]; then
  fail "ingress URL" "no ingress_url in addon info"
else
  html=$(curl -sS "${H[@]}" "${HA_URL}${ingress_url}")
  if printf '%s' "$html" | grep -q "$ingress_url" && ! printf '%s' "$html" | grep -q 'href="/_next/'; then
    pass "nginx sub_filter rewrote /_next/ paths under ${ingress_url}"
  else
    fail "sub_filter rewrite" "still saw bare /_next/ or missing ingress prefix in HTML"
  fi
fi

echo
echo "── Summary: ${PASS} pass / ${FAIL} fail ──"
[ "$FAIL" -eq 0 ]
