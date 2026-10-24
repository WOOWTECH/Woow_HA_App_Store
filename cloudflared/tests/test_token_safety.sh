#!/usr/bin/env bash
# Execute the real runtime entry point with a stub cloudflared. No root or
# Cloudflare credentials are required. This is a public-process seam test.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"

cat > "$work/bin/cloudflared" <<'STUB'
#!/bin/sh
printf '%s\n' "$@" > "$ARGV_RECORD"
STUB
chmod +x "$work/bin/cloudflared"

cat > "$work/bashio.sh" <<'STUB'
bashio::log.info() { echo "[INFO] $*"; }
bashio::log.debug() { echo "[DEBUG] $*"; }
bashio::log.notice() { echo "[NOTICE] $*"; }
bashio::log.warning() { echo "[WARNING] $*"; }
bashio::log.error() { echo "[ERROR] $*"; }
bashio::log.trace() { echo "[TRACE] $*"; }
bashio::config.true() { return 1; }
bashio::config.has_value() {
    [[ "${SIMULATE_UNCONFIGURED:-0}" != 1 ]] &&
        [[ "$1" == tunnel_token || ( "$1" == run_parameters && -n "${RUN_PARAMS:-}" ) ]]
}
bashio::config() {
    if [[ "$1" == run_parameters ]]; then printf '%s' "$RUN_PARAMS";
    else printf '%s' 'TEST_SECRET_DO_NOT_LOG'; fi
}
STUB

export ARGV_RECORD="$work/argv"
export CLOUDFLARED_TOKEN_FILE="$work/token"
PATH="$work/bin:$PATH" bash -c 'source "$1"; source "$2"' _ "$work/bashio.sh" "$root/cloudflared/rootfs/run.sh" > "$work/log"

rg -q -- '--token-file=' "$work/argv"
! rg -q -- '--token=' "$work/argv"
rg -q -- '--metrics=127.0.0.1:36500' "$work/argv"
test "$(cat "$work/token")" = 'TEST_SECRET_DO_NOT_LOG'
test "$(stat -c %a "$work/token")" = 600
! rg -q 'TEST_SECRET_DO_NOT_LOG' "$work/argv" "$work/log"
export RUN_PARAMS='--protocol quic'
PATH="$work/bin:$PATH" bash -c 'source "$1"; source "$2"' _ "$work/bashio.sh" "$root/cloudflared/rootfs/run.sh" > "$work/log"
rg -q -- '--protocol' "$work/argv"
rg -q -- 'quic' "$work/argv"
export RUN_PARAMS='--token=ADVERSARIAL_SECRET'
if PATH="$work/bin:$PATH" bash -c 'source "$1"; source "$2"' _ "$work/bashio.sh" "$root/cloudflared/rootfs/run.sh" > "$work/log"; then
    echo 'FAIL: an unsafe run parameter reached cloudflared' >&2
    exit 1
fi
! rg -q 'ADVERSARIAL_SECRET' "$work/log" "$work/argv"
export RUN_PARAMS='--metrics=0.0.0.0:36500'
if PATH="$work/bin:$PATH" bash -c 'source "$1"; source "$2"' _ "$work/bashio.sh" "$root/cloudflared/rootfs/run.sh" > "$work/log"; then
    echo 'FAIL: run_parameters opened the metrics listener publicly' >&2
    exit 1
fi
cat > "$work/bin/sleep" <<'STUB'
#!/bin/sh
exit 0
STUB
chmod +x "$work/bin/sleep"
export SIMULATE_UNCONFIGURED=1 WEBGUI_UNCONFIGURED_MARKER="$work/unconfigured" RUN_PARAMS=''
touch "$WEBGUI_UNCONFIGURED_MARKER"
printf '%s' 'STALE_TEST_TOKEN' > "$work/token"
rm -f "$work/argv"
PATH="$work/bin:$PATH" bash -c 'source "$1"; source "$2"' _ "$work/bashio.sh" "$root/cloudflared/rootfs/run.sh" > "$work/log"
rg -q 'not configured' "$work/log"
test ! -e "$work/token"
test ! -e "$work/argv"
echo 'PASS: token is confined to a 0600 file; argv and raw log are clean; metrics use loopback'
