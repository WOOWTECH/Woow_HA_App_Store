#!/usr/bin/env bash
# =============================================================================
# Regression tests for the two WOOWTECH resilience patches in the forked
# add-on core:
#
#   1. s6-rc.d/prepare/up   — a failing prepare must NOT halt the container
#                             (it records /tmp/webgui-prepare-failed instead)
#   2. rootfs/run.sh        — marker branches: idle when unconfigured, idle +
#                             retry every 5 min when the setup failed, and
#                             proceed normally when neither marker is present
#
# These paths never execute in remote-managed (tunnel_token) mode, so they
# cannot be exercised on a production token-mode instance. This harness runs
# the REAL scripts against a stubbed bashio / cloudflared / sleep so the
# control flow is covered without a live tunnel.
#
# Usage:  bash cloudflared/tests/test_resilience_patches.sh
# =============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_SH="${REPO_ROOT}/cloudflared/rootfs/run.sh"
UP_FILE="${REPO_ROOT}/cloudflared/rootfs/etc/s6-overlay/s6-rc.d/prepare/up"

UNCONFIGURED_MARKER=/tmp/webgui-unconfigured
FAILED_MARKER=/tmp/webgui-prepare-failed
PREPARE_PATH=/etc/s6-overlay/s6-rc.d/prepare/run.sh

WORK="$(mktemp -d)"
SENTINEL="${WORK}/cloudflared-was-exec'd"
ATTEMPTS="${WORK}/prepare-attempts"

PASS=0
FAIL=0

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS + 1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL + 1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

cleanup() {
    rm -f "$UNCONFIGURED_MARKER" "$FAILED_MARKER"
    rm -rf "$WORK"
    rm -f "$PREPARE_PATH"
}
trap cleanup EXIT

# ── stub environment ──────────────────────────────────────────────────

# bashio: log helpers echo, config reports remote-managed (token) mode.
cat > "${WORK}/stub_bashio.sh" <<'STUB'
bashio::log.info()    { echo "[INFO] $*"; }
bashio::log.notice()  { echo "[NOTICE] $*"; }
bashio::log.warning() { echo "[WARNING] $*"; }
bashio::log.error()   { echo "[ERROR] $*"; }
bashio::log.debug()   { echo "[DEBUG] $*"; }
bashio::log.trace()   { :; }
bashio::config.true()      { return 1; }
bashio::config.has_value() { [ "$1" = "tunnel_token" ]; }
bashio::config()           { echo "STUB_TOKEN"; }
STUB

# cloudflared: record that the tunnel was actually reached, then exit.
mkdir -p "${WORK}/bin"
cat > "${WORK}/bin/cloudflared" <<STUB
#!/bin/sh
echo "\$@" > "${SENTINEL}"
exit 0
STUB
# sleep: collapse the 5-minute retry interval so the loop is testable.
cat > "${WORK}/bin/sleep" <<'STUB'
#!/bin/sh
case "$1" in
  infinity) exec /bin/sleep infinity ;;
  *)        exec /bin/sleep 0.05 ;;
esac
STUB
chmod +x "${WORK}/bin/cloudflared" "${WORK}/bin/sleep"

# Install a prepare script at the absolute path run.sh's retry loop calls.
# $1 = number of leading attempts that should fail (999 = always fail).
install_prepare() {
    mkdir -p "$(dirname "$PREPARE_PATH")"
    cat > "$PREPARE_PATH" <<STUB
#!/bin/sh
n=\$(cat "${ATTEMPTS}" 2>/dev/null || echo 0)
n=\$((n + 1))
echo "\$n" > "${ATTEMPTS}"
if [ "\$n" -le "$1" ]; then
    echo "[stub prepare] attempt \$n: failing"
    exit 1
fi
echo "[stub prepare] attempt \$n: succeeding"
exit 0
STUB
    chmod +x "$PREPARE_PATH"
    rm -f "$ATTEMPTS"
}

# Run run.sh with the stub environment; $1 = timeout seconds.
run_runsh() {
    PATH="${WORK}/bin:${PATH}" timeout "${1}" bash -c \
        "source '${WORK}/stub_bashio.sh'; source '${RUN_SH}'" 2>&1
}

reset_state() {
    rm -f "$UNCONFIGURED_MARKER" "$FAILED_MARKER" "$SENTINEL" "$ATTEMPTS"
}

# ── 1. the s6 'up' wrapper ─────────────────────────────────────────────

head_ "s6 prepare/up wrapper (a failing setup must not halt the container)"

# Extract the shell command the execline 'up' line runs, so the test exercises
# the committed wrapper rather than a copy of it.
UP_CMD="$(grep -v '^#' "$UP_FILE" | grep -m1 'prepare/run.sh' | sed 's|^/bin/sh -ec "||; s|"$||')"
if [ -z "$UP_CMD" ]; then
    bad "could not extract the wrapper command from ${UP_FILE}"
else
    ok "wrapper command extracted from the committed up file"
fi

reset_state
install_prepare 0                       # succeeds immediately
/bin/sh -ec "$UP_CMD" >/dev/null 2>&1
rc=$?
[ "$rc" -eq 0 ] && ok "successful prepare → wrapper exits 0" \
                || bad "successful prepare → wrapper exited ${rc}"
[ ! -f "$FAILED_MARKER" ] && ok "successful prepare → no failure marker" \
                          || bad "successful prepare → marker was created"

reset_state
install_prepare 999                     # always fails
/bin/sh -ec "$UP_CMD" >/dev/null 2>&1
rc=$?
[ "$rc" -eq 0 ] && ok "failing prepare → wrapper still exits 0 (container survives)" \
                || bad "failing prepare → wrapper exited ${rc}, s6 would halt the container"
[ -f "$FAILED_MARKER" ] && ok "failing prepare → failure marker recorded" \
                        || bad "failing prepare → marker missing"

# A stale marker from a previous boot must not leak into a healthy start.
install_prepare 0
touch "$FAILED_MARKER"
/bin/sh -ec "$UP_CMD" >/dev/null 2>&1
[ ! -f "$FAILED_MARKER" ] && ok "stale marker cleared when prepare succeeds again" \
                          || bad "stale marker survived a successful prepare"

# ── 2. run.sh marker branches ─────────────────────────────────────────

head_ "run.sh: unconfigured add-on keeps the Web GUI alive"

reset_state
touch "$UNCONFIGURED_MARKER"
out="$(run_runsh 2)"
case "$out" in
    *"not configured yet"*) ok "logs the not-configured notice" ;;
    *)                      bad "missing not-configured notice; got: ${out}" ;;
esac
[ ! -f "$SENTINEL" ] && ok "cloudflared is NOT started while unconfigured" \
                     || bad "cloudflared was started despite the unconfigured marker"

head_ "run.sh: failed setup idles, retries, and self-heals"

reset_state
install_prepare 999                     # never recovers
touch "$FAILED_MARKER"
out="$(run_runsh 2)"
case "$out" in
    *"Tunnel setup failed"*) ok "logs the setup-failure error" ;;
    *)                       bad "missing setup-failure error; got: ${out}" ;;
esac
case "$out" in
    *"retries the setup every 5 minutes"*) ok "tells the user it will self-heal" ;;
    *) bad "missing self-heal notice" ;;
esac
case "$out" in
    *"Retrying tunnel setup"*) ok "retry loop actually re-runs prepare" ;;
    *) bad "retry loop never fired" ;;
esac
[ ! -f "$SENTINEL" ] && ok "cloudflared stays down while setup keeps failing" \
                     || bad "cloudflared started even though setup never succeeded"

reset_state
install_prepare 2                       # fails twice, then succeeds
touch "$FAILED_MARKER"
out="$(run_runsh 5)"
case "$out" in
    *"succeeded on retry"*) ok "recovery is announced when a retry succeeds" ;;
    *) bad "missing recovery notice; got: ${out}" ;;
esac
[ ! -f "$FAILED_MARKER" ] && ok "marker cleared after a successful retry" \
                          || bad "marker survived a successful retry"
[ -f "$SENTINEL" ] && ok "tunnel starts once setup recovers" \
                   || bad "tunnel never started after recovery"

head_ "run.sh: healthy start is unchanged from upstream"

reset_state
out="$(run_runsh 5)"
[ -f "$SENTINEL" ] && ok "no markers → cloudflared is exec'd" \
                   || bad "no markers → cloudflared was never started; got: ${out}"
if [ -f "$SENTINEL" ]; then
    args="$(cat "$SENTINEL")"
    case "$args" in
        *"--no-autoupdate"*) ok "keeps upstream flag --no-autoupdate" ;;
        *) bad "missing --no-autoupdate (upstream parity broken)" ;;
    esac
    case "$args" in
        *"--metrics=0.0.0.0:36500"*) ok "keeps upstream metrics endpoint" ;;
        *) bad "missing --metrics (dashboard status would break)" ;;
    esac
    case "$args" in
        *"run --token=STUB_TOKEN"*) ok "token mode passes the token through" ;;
        *) bad "token not passed through; got: ${args}" ;;
    esac
fi

# ── summary ────────────────────────────────────────────────────────

printf '\n%s\n' "──────────────────────────────────────────────"
printf 'passed: %d   failed: %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
