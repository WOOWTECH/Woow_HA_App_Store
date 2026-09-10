#!/usr/bin/env bash
# Smoke test: the ACP Client extension is installed and settings.json
# carries all seven required keys from PARITY_CONTRACT.md §2.5 — the
# acp.agents wiring plus the four workspace-trust keys the extension
# needs to activate its view container at all.
set -uo pipefail

. "$(dirname "$0")/lib/parity.sh"

EXPECTED_EXT="formulahendry.acp-client"
PASS_N=0; FAIL_N=0

ok()  { printf '  \033[32mPASS\033[0m  %s\n' "$*"; PASS_N=$((PASS_N+1)); }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL_N=$((FAIL_N+1)); }

echo "== ACP Client extension (PARITY_TARGET=${PARITY_TARGET}) =="
if EXT_INSTALLED; then
    ok "extension installed: ${EXPECTED_EXT}"
else
    bad "extension NOT installed (checked via EXT_INSTALLED for PARITY_TARGET=${PARITY_TARGET})"
fi

echo
echo "== settings.json required keys (${SETTINGS}) =="
if CX test -f "${SETTINGS}"; then
    ok "settings.json exists"
    JSON="$(CX cat "${SETTINGS}" 2>/dev/null)"
    check_jq() {
        local desc="$1" filter="$2"
        if echo "${JSON}" | jq -e "${filter}" >/dev/null 2>&1; then
            ok "${desc}"
        else
            bad "${desc}"
        fi
    }
    check_jq 'acp.agents.pi.command == "pi-code"'            '.["acp.agents"].pi.command == "pi-code"'
    check_jq 'security.workspace.trust.enabled == false'      '.["security.workspace.trust.enabled"] == false'
    check_jq 'security.workspace.trust.startupPrompt == "never"' '.["security.workspace.trust.startupPrompt"] == "never"'
    check_jq 'security.workspace.trust.banner == "never"'      '.["security.workspace.trust.banner"] == "never"'
    check_jq 'security.workspace.trust.emptyWindow == false'   '.["security.workspace.trust.emptyWindow"] == false'
    # NOT `== false`. In code-server 4.135.0 this setting is
    #     {type:"string", enum:["on","off"], default:"on"}
    # — it stopped being a boolean. The workbench decides with
    # `getAutoUpdateValue() !== "off"`, so a boolean `false` fails schema
    # validation, falls back to the default, and leaves auto-update ON. We
    # shipped `false` in all three seeds and asserted it here, so the check
    # was green on exactly the configuration it was meant to prevent: the
    # pinned ACP Client extension free to update itself out from under us.
    check_jq 'extensions.autoUpdate == "off"'                  '.["extensions.autoUpdate"] == "off"'
else
    bad "settings.json missing at ${SETTINGS}"
fi

echo
printf '  %d passed, %d failed\n\n' "${PASS_N}" "${FAIL_N}"
[ "${FAIL_N}" -eq 0 ] || exit 1
