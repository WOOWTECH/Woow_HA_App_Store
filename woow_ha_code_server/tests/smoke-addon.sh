#!/usr/bin/env bash
# Smoke test against a real Home Assistant instance's Supervisor API.
# Checks the add-on's OWN state (installed, started, not stuck on an
# update) rather than anything inside the container — tests/smoke-*.sh
# (via tests/lib/parity.sh, PARITY_TARGET=ha) cover the container internals.
#
# Requires:
#   HA_URL      e.g. https://woowtech-ha.woowtech.io
#   HA_TOKEN    a Home Assistant Long-Lived Access Token with admin rights
#   ADDON_SLUG  default woow_ha_code_server
set -uo pipefail

HA_URL="${HA_URL:?set HA_URL, e.g. https://your-ha-host}"
HA_TOKEN="${HA_TOKEN:?set HA_TOKEN to a Long-Lived Access Token}"
ADDON_SLUG="${ADDON_SLUG:-woow_ha_code_server}"

PASS_N=0; FAIL_N=0
ok()  { printf '  \033[32mPASS\033[0m  %s\n' "$*"; PASS_N=$((PASS_N+1)); }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL_N=$((FAIL_N+1)); }

echo "== Supervisor: add-on info (${ADDON_SLUG}) =="
INFO="$(curl -sS --max-time 10 -H "Authorization: Bearer ${HA_TOKEN}" \
    "${HA_URL}/api/hassio/addons/${ADDON_SLUG}/info")"

if [ -z "${INFO}" ]; then
    bad "empty response from Supervisor API — check HA_URL/HA_TOKEN and that the add-on is installed"
else
    STATE="$(echo "${INFO}" | jq -r '.data.state // empty')"
    [ "${STATE}" = "started" ] && ok "state == started" || bad "state == ${STATE:-<missing>}"

    UPDATE_AVAILABLE="$(echo "${INFO}" | jq -r '.data.update_available // empty')"
    [ "${UPDATE_AVAILABLE}" = "false" ] && ok "update_available == false" || bad "update_available == ${UPDATE_AVAILABLE:-<missing>} (stuck on an old version?)"

    INGRESS_URL="$(echo "${INFO}" | jq -r '.data.ingress_url // empty')"
    if [ -n "${INGRESS_URL}" ]; then
        ok "ingress_url present: ${INGRESS_URL}"
    else
        bad "ingress_url missing — ingress may not be enabled"
    fi
fi

echo
echo "== Supervisor: bootstrap log lines present =="
LOGS="$(curl -sS --max-time 10 -H "Authorization: Bearer ${HA_TOKEN}" \
    "${HA_URL}/api/hassio/addons/${ADDON_SLUG}/logs" 2>/dev/null || true)"
if echo "${LOGS}" | grep -q "init-woow: done"; then
    ok "init-woow completed (found 'init-woow: done' in logs)"
else
    bad "did not find 'init-woow: done' in the add-on's logs — check for an init-woow error earlier in the log"
fi

echo
printf '  %d passed, %d failed\n\n' "${PASS_N}" "${FAIL_N}"
echo "NOTE: this script cannot check the workbench HTML through ingress directly —"
echo "that requires a valid ingress session cookie, which the Supervisor REST API"
echo "does not mint. See tests/smoke-acp-webview.md for the browser-based check,"
echo "and tests/lib/parity.sh PARITY_TARGET=ha for container-internal checks."
[ "${FAIL_N}" -eq 0 ] || exit 1
