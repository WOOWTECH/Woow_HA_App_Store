#!/usr/bin/env bash
# Smoke test: the developer toolchain a coding agent actually reaches for.
#
# Every check here exists because the 2026-09 field test found it broken on a
# deployment that passed all the pre-existing smoke tests. pi could write a
# pytest suite it could not run, could not `npm install -g`, and could not
# `git commit`. None of that is exotic — it is the second thing anyone asks an
# agent to do — and none of it was asserted anywhere.
#
# Corresponds to PARITY_CONTRACT.md §H (P46, P49, P50, P51).
set -uo pipefail

. "$(dirname "$0")/lib/parity.sh"

PASS_N=0; FAIL_N=0

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$*"; PASS_N=$((PASS_N+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL_N=$((FAIL_N+1)); }
skip() { printf '  \033[90mSKIP\033[0m  %s\n' "$*"; }

echo "== P51: pi on PATH in BOTH shell kinds (PARITY_TARGET=${PARITY_TARGET}) =="
# /etc/profile overwrites PATH wholesale for login shells, discarding the image
# ENV. code-server's integrated terminal IS a login shell, so a pi that only
# resolves in a non-login shell is a pi the user cannot run.
NONLOGIN="$(CX sh -c 'command -v pi' 2>/dev/null | tr -d '\r')"
LOGIN="$(CX sh -lc 'command -v pi' 2>/dev/null | tr -d '\r')"
if [ -n "${NONLOGIN}" ] && [ "${NONLOGIN}" = "${LOGIN}" ]; then
    ok "pi resolves to ${LOGIN} in both login and non-login shells"
else
    bad "pi PATH differs by shell kind — non-login='${NONLOGIN}' login='${LOGIN}'"
fi

echo
echo "== P49: python3 toolchain (pip + venv) =="
# The image used to install python3-minimal, citing a Debian Trixie metadep
# deadlock. Result: pi wrote a pytest suite and then had no pip, no ensurepip
# and no venv to run it with — and the documented escape hatch
# (`sudo apt install python3-pip`) is dead, because the quadlet sets
# NoNewPrivileges=true and k3s sets allowPrivilegeEscalation:false.
if OUT="$(CX sh -lc 'python3 -m pip --version' 2>&1 | tr -d '\r')"; then
    ok "python3 -m pip works: ${OUT}"
else
    bad "python3 -m pip broken: ${OUT}"
fi
if OUT="$(CX sh -lc 'V=$(mktemp -d)/v && python3 -m venv "$V" && "$V"/bin/python -c "print(1)" && rm -rf "$V"' 2>&1 | tr -d '\r')"; then
    ok "python3 -m venv creates a usable venv"
else
    bad "python3 -m venv broken: ${OUT}"
fi

echo
echo "== P50: npm install -g as the run user =="
# npm's default prefix is root-owned /usr. As uid 1000 under no-new-privileges
# `npm install -g` died with EACCES — the single most idiomatic way to install
# a CLI tool. Fixed with a run-user-writable NPM_CONFIG_PREFIX; the second half
# of this check is the part that matters, because an earlier attempt at the fix
# installed successfully into a prefix that /etc/profile then dropped off PATH.
if OUT="$(CX sh -lc 'npm install -g --silent --no-fund --no-audit cowsay@1.6.0' 2>&1 | tr -d '\r')"; then
    WHERE="$(CX sh -lc 'command -v cowsay' 2>/dev/null | tr -d '\r')"
    if [ -n "${WHERE}" ]; then
        ok "npm install -g succeeded and cowsay is on PATH in a login shell (${WHERE})"
    else
        bad "npm install -g succeeded but the binary is NOT on PATH in a login shell — the prefix's bin dir is missing from /etc/profile.d"
    fi
    CX sh -lc 'npm uninstall -g --silent cowsay >/dev/null 2>&1' >/dev/null 2>&1 || true
else
    bad "npm install -g failed: $(printf '%s' "${OUT}" | tail -3)"
fi

echo
echo "== P46: git commit works out of the box =="
# git's identity auto-detect needs a hostname containing a dot. podman
# (2505cfd5a5d8) and k3s (code-server-7b6f95f546-85r6s) hostnames have none, so
# git rejects the derived `user@host.(none)` and `git commit` exits 128. HA
# resolves to *.local.hass.io and was never affected — the deployment provides
# the identity, so this is a deployment check, not an image check.
IDENT="$(CX sh -lc 'git config --get user.email' 2>/dev/null | tr -d '\r')"
if [ -z "${IDENT}" ]; then
    skip "no git identity configured on this deployment — mount one at /etc/gitconfig, or run scripts/install.sh with GIT_USER_NAME/GIT_USER_EMAIL"
else
    if OUT="$(CX sh -lc 'D=$(mktemp -d) && cd "$D" && git init -q . && git commit -q --allow-empty -m smoke && git log -1 --format=%ae && rm -rf "$D"' 2>&1 | tr -d '\r')"; then
        ok "git commit succeeds, authored as ${OUT}"
    else
        bad "git commit failed: $(printf '%s' "${OUT}" | tail -3)"
    fi
    # The ACP panel's pi runs with HOME re-pointed at the state volume by
    # pi-code. Without pi-code's GIT_CONFIG_GLOBAL carry-over, it resolves a
    # different ~/.gitconfig from the terminal, and the same repo ends up with
    # commits from two different authors. Reproduce the panel's environment by
    # sourcing the wrapper's env setup — everything up to the final exec.
    PANEL_IDENT="$(CX sh -lc '
        eval "$(sed "/^exec /d" /usr/local/bin/pi-code)"
        git config --get user.email
    ' 2>/dev/null | tr -d '\r')"
    if [ "${PANEL_IDENT}" = "${IDENT}" ]; then
        ok "panel-pi git identity matches the terminal's (${IDENT})"
    else
        bad "panel-pi would commit as '${PANEL_IDENT}' but the terminal commits as '${IDENT}' — pi-code's GIT_CONFIG_GLOBAL carry-over is missing, or the host identity is still mounted over ~/.gitconfig instead of /etc/gitconfig"
    fi
fi

echo
printf '  %d passed, %d failed\n\n' "${PASS_N}" "${FAIL_N}"
[ "${FAIL_N}" -eq 0 ] || exit 1
