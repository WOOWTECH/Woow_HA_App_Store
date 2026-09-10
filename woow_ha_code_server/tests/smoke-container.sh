#!/usr/bin/env bash
# Smoke test: container/pod is up, /healthz is 200, PASSWORD gate is
# enforced (podman/k3s — HA delegates auth to its ingress session cookie,
# see PARITY_CONTRACT.md, so the password-gate checks below are skipped
# there, not failed).
# Zero cost, no LLM calls. Fail loud if any of the above regresses.
set -uo pipefail

. "$(dirname "$0")/lib/parity.sh"

PASS="${CODE_SERVER_PASSWORD:-woowtech}"
PASS_N=0; FAIL_N=0

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$*"; PASS_N=$((PASS_N+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL_N=$((FAIL_N+1)); }
skip() { printf '  \033[90mSKIP\033[0m  %s\n' "$*"; }

echo "== Container/pod liveness (PARITY_TARGET=${PARITY_TARGET}) =="
STATUS="$(LIVENESS)"
case "${PARITY_TARGET}" in
podman) [ "${STATUS}" = "healthy" ] && ok "container health = healthy" || bad "container health = ${STATUS:-unknown}" ;;
ha)     [ "${STATUS}" = "running" ] && ok "add-on container status = running" || bad "add-on container status = ${STATUS:-unknown}" ;;
k3s)    [ "${STATUS:-0}" -ge 1 ] 2>/dev/null && ok "deployment readyReplicas = ${STATUS}" || bad "deployment readyReplicas = ${STATUS:-0}" ;;
esac

if [ -n "${BASE}" ]; then
    echo
    echo "== HTTP surface (${BASE}) =="
    CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "${BASE}/healthz" 2>&1)"
    [ "${CODE}" = "200" ] && ok "/healthz -> 200" || bad "/healthz -> ${CODE}"
else
    skip "HTTP surface — no direct BASE for PARITY_TARGET=${PARITY_TARGET} (reached via ingress/tunnel; check manually)"
fi

if [ "${PARITY_TARGET}" = "ha" ]; then
    echo
    skip "password-gate checks — HA delegates auth to the ingress session cookie, code-server itself runs --auth none"
else
    echo
    echo "== Password gate =="
    # Root without login redirects to /login (302) or shows the login page (200).
    CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "${BASE}/")"
    case "${CODE}" in
        200|302) ok "/ -> ${CODE} (login page)" ;;
        *)       bad "/ -> ${CODE}" ;;
    esac

    # code-server re-renders the login page (HTTP 200) with an error banner
    # rather than returning 401. So we assert on the body containing an
    # error string, which is the actually-testable behavior — a "silently
    # accept anything" regression would render the workspace HTML instead.
    BODY="$(curl -sS --max-time 5 -X POST \
        --data-urlencode "password=deliberately-wrong-$$" \
        "${BASE}/login")"
    if echo "${BODY}" | grep -qiE 'incorrect password|missing password|invalid password'; then
        ok "wrong password rejected (login page re-rendered with error)"
    else
        bad "wrong password NOT rejected — body did not carry an error banner"
        echo "${BODY}" | head -c 300 | sed 's/^/       /'
    fi

    # Right password redirects (302) to the workbench.
    CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 -X POST \
        --data-urlencode "password=${PASS}" \
        "${BASE}/login")"
    case "${CODE}" in
        302|200) ok "correct password -> ${CODE}" ;;
        *)       bad "correct password -> ${CODE}" ;;
    esac
fi

echo
printf '  %d passed, %d failed\n\n' "${PASS_N}" "${FAIL_N}"
[ "${FAIL_N}" -eq 0 ] || exit 1
