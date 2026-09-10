#!/usr/bin/env bash
# Smoke test: pi CLI is on PATH at the pinned version, pi-acp is present,
# the pi-code wrapper is installed, and this deployment's OWN internal
# /data/pi-agent store exists and is correctly seeded. No sibling-package
# assertions any more — pi state is private per PARITY_CONTRACT.md.
set -uo pipefail

. "$(dirname "$0")/lib/parity.sh"

EXPECTED_PI_VERSION="${EXPECTED_PI_VERSION:-0.83.0}"
PASS_N=0; FAIL_N=0

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$*"; PASS_N=$((PASS_N+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL_N=$((FAIL_N+1)); }
skip() { printf '  \033[90mSKIP\033[0m  %s\n' "$*"; }

echo "== pi CLI (PARITY_TARGET=${PARITY_TARGET}) =="
if V="$(CX pi --version 2>&1)"; then
    [ "${V}" = "${EXPECTED_PI_VERSION}" ] \
        && ok "pi --version = ${V}" \
        || bad "pi --version = ${V} (expected ${EXPECTED_PI_VERSION})"
else
    bad "pi not on PATH inside container"
fi

if CX which pi-acp >/dev/null 2>&1; then
    ok "pi-acp on PATH"
else
    bad "pi-acp not on PATH"
fi

if CX test -x /usr/local/bin/pi-code; then
    ok "pi-code wrapper installed + executable"
else
    bad "pi-code wrapper missing"
fi

if CX test -x /usr/local/bin/pi-seed; then
    ok "pi-seed installed + executable"
else
    bad "pi-seed missing"
fi

echo
echo "== Internal pi state store (/data/pi-agent) =="
if CX test -d /data/pi-agent; then
    ok "/data/pi-agent exists"
    if CX test -f /data/pi-agent/.woow-pi-store; then
        ok "  .woow-pi-store marker present — store was seeded from the skeleton, not a bare empty dir"
    else
        bad "  .woow-pi-store marker MISSING — /data/pi-agent may be an unseeded volume or the container's writable layer"
    fi
    if CX test -f /data/pi-agent/auth.json; then
        PERM="$(CX_ROOT stat -c '%a' /data/pi-agent/auth.json 2>/dev/null || echo '?')"
        [ "${PERM}" = "600" ] && ok "  auth.json present, mode 600" || bad "  auth.json present but mode ${PERM} (expected 600)"
    else
        skip "  auth.json absent — run 'pi login' inside this deployment (see README First run)"
    fi
else
    bad "/data/pi-agent NOT present — pi state will be lost on container restart"
fi

echo
echo "== Shared-file integrity (rootfs/opt/SHA256SUMS) =="
if CX_ROOT test -f /opt/SHA256SUMS; then
    if CX_ROOT sh -c 'sha256sum -c /opt/SHA256SUMS' >/tmp/parity-sha256-$$ 2>&1; then
        ok "pi-code / pi.sh / pi-seed match the pinned SHA256SUMS"
    else
        bad "SHA256SUMS mismatch — a shared file drifted from the pinned hash"
    fi
else
    skip "/opt/SHA256SUMS not present on this target (only shipped by the image build)"
fi

echo
echo "== pi-code HOME re-scoping =="
# Static check: pi-code must export HOME=\${PI_AGENT_DATA_DIR}/home. This
# does not require auth or a running pi subprocess.
if OUT="$(CX_ROOT grep -E '^export HOME' /usr/local/bin/pi-code 2>&1)"; then
    if echo "${OUT}" | grep -q 'PI_AGENT_DATA_DIR}/home'; then
        ok "pi-code exports HOME=\${PI_AGENT_DATA_DIR}/home"
    else
        bad "pi-code HOME export missing or wrong: ${OUT}"
    fi
else
    bad "could not inspect pi-code wrapper: ${OUT}"
fi

echo
echo "== F1: Unicode-space path handling (patches/fix-unicode-space-paths.mjs) =="
# Not a static check. Upstream folds U+3000 (and friends) to an ASCII space on
# every read/write/edit, which makes `Q1<U+3000>報告.txt` silently resolve to
# `Q1<SPACE>報告.txt` — a confidential/public pair differing only by space type
# cross-reads, with isError=false. The image patches that out at build time.
#
# The original incident was NOT a broken patch: the patch script was never
# invoked. So this runs the verifier shipped inside the image, which asserts
# the marker is present in every path-utils.js copy AND that the behaviour is
# actually right against a real filesystem.
if CX test -f /opt/patches/f1-verify.mjs; then
    if OUT="$(CX node /opt/patches/f1-verify.mjs 2>&1)"; then
        ok "Unicode-space paths resolve exactly (patch applied and behaving)"
    else
        bad "Unicode-space path handling is WRONG — reads/writes may hit the wrong file:"
        printf '%s\n' "${OUT}" | sed 's/^/        /'
    fi
else
    bad "/opt/patches/f1-verify.mjs missing — the image predates the F1 patch, or patches/ was not COPYed"
fi

echo
printf '  %d passed, %d failed\n\n' "${PASS_N}" "${FAIL_N}"
[ "${FAIL_N}" -eq 0 ] || exit 1
