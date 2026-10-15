#!/bin/sh
# omnigent-host supervisor — WOOW PaaS shared kit (POSIX sh: dash, bash, busybox ash).
#
# Canonical copy: woow-paas-charts/shared/omnigent-host/supervisor.sh. Charts carry a
# byte-identical vendored copy (scripts/sync-omnigent-host-kit.sh); never edit one.
#
# Keeps `omnigent host` connected so an Omnigent server can run sessions in this
# environment, unattended and across pod restarts, WITHOUT ever logging in for
# the tenant or holding credentials of its own. It runs INSIDE the service's
# main container, started in the background by omnigent-host-launch (the
# container's entrypoint wrapper), like a daemon on an ordinary machine: the
# host dials out to the Omnigent server over the network; no extra container.
#
#   * disabled (OG_HOST_ENABLED=0), no omnigent CLI, missing python/PyYAML,
#     old tmux, no flock, unwritable state dir -> writes the status and EXITS 0
#     quietly (the product is never affected);
#
#   * waits quietly until the tenant ran `omnigent login <url>` in the
#     environment's terminal (a file test every OG_IDLE_SECONDS; python only
#     runs when the token/config files change, or every OG_REPROBE_SECONDS);
#   * identity lives in config.yaml on the volume (og_helper.py seed): an
#     existing host_id is kept and only host.name is set to OG_HOST_NAME;
#     without a host block omnigent generates the id on first start;
#   * watchdog every OG_WATCH_SECONDS (and whenever the token/config files
#     change): only two consecutive DEFINITIVE rejections (401 with a fresh or
#     refreshed token, refused refresh grant) stop the host -> "login-expired";
#     5xx / connection errors never do (the host rides the outage); a re-login
#     to another URL or account restarts the host against it;
#   * exit 78 with HTTP 409 (host id owned by another account) -> exponential
#     backoff and status "needs-reset-id" (action: omnigent host reset-id --yes);
#   * the Omnigent URL for login hints is read at RUNTIME from
#     OG_SERVER_URL_FILE (a ConfigMap file outside the pod template), so the
#     platform can set it without restarting the pod;
#   * the host tree gets oom_score_adj OG_OOM_SCORE_ADJ (1000) and a userspace
#     memory guard kills the largest Omnigent session before the container's
#     cgroup OOM (memory.oom.group=1 kills EVERY process, product included);
#     other exits -> exponential backoff 5 s .. OG_BACKOFF_MAX;
#   * stopping = SIGTERM, then SIGKILL (process group) after OG_STOP_GRACE_SECONDS;
#   * the status detail follows the host log ("Connected as" after an outage);
#   * size-capped logs: host.log / supervisor.log rotate at OG_LOG_MAX_BYTES,
#     omnigent's own logs/ files are capped and pruned by age while running;
#   * one supervisor (and so one host) per volume: flock on OG_STATE_DIR/supervisor.lock;
#   * status JSON (no secrets) at OG_STATUS_FILE for omnigent-host-status;
#   * telemetry off for every omnigent process (env + config.yaml);
#   * never prints tokens: no `set -x`, no env dumps; og_helper.py prints none.
#
# Every setting is an environment variable; see README.md for the full contract.
set -u

: "${HOME:=/tmp}"
HOME0=$HOME
# OG_HOME: HOME for the host and its sessions when it must differ from the
# product's HOME (default: the container's HOME).
[ -n "${OG_HOME:-}" ] && HOME=$OG_HOME
export HOME

# ── configuration ────────────────────────────────────────────────────────────
OG_CONFIG_HOME=${OG_CONFIG_HOME:-${OMNIGENT_CONFIG_HOME:-$HOME/.omnigent}}
OG_DATA_DIR=${OG_DATA_DIR:-${OMNIGENT_DATA_DIR:-$OG_CONFIG_HOME}}
OG_STATE_DIR=${OG_STATE_DIR:-$OG_DATA_DIR/omnigent-host}
OG_STATUS_FILE=${OG_STATUS_FILE:-$OG_STATE_DIR/status.json}
OG_SERVER_URL=${OG_SERVER_URL:-}
OG_SERVER_URL_FILE=${OG_SERVER_URL_FILE:-}
OG_HOST_ENABLED=${OG_HOST_ENABLED:-1}
OG_HOST_NAME=${OG_HOST_NAME:-}
OG_WORKSPACE=${OG_WORKSPACE:-}
OG_WATCH_SECONDS=${OG_WATCH_SECONDS:-120}
OG_PROVIDERS=${OG_PROVIDERS:-}
OG_PASSTHROUGH=${OG_PASSTHROUGH:-}
OG_UNSET_ENV=${OG_UNSET_ENV:-}
OG_LOG_MAX_BYTES=${OG_LOG_MAX_BYTES:-5242880}
OG_LOG_RETENTION_DAYS=${OG_LOG_RETENTION_DAYS:-14}
OG_LOGS_MAX_BYTES=${OG_LOGS_MAX_BYTES:-268435456}
OG_TMUX_MIN=${OG_TMUX_MIN-3.3}
OG_STOP_GRACE_SECONDS=${OG_STOP_GRACE_SECONDS:-15}
OG_CONFIRM_SECONDS=${OG_CONFIRM_SECONDS:-20}
OG_IDLE_SECONDS=${OG_IDLE_SECONDS:-15}
OG_REPROBE_SECONDS=${OG_REPROBE_SECONDS:-300}
OG_TICK_SECONDS=${OG_TICK_SECONDS:-5}
OG_BACKOFF_MAX=${OG_BACKOFF_MAX:-300}
OG_BACKOFF_78_MIN=${OG_BACKOFF_78_MIN:-60}
OG_BACKOFF_78_MAX=${OG_BACKOFF_78_MAX:-1800}
OG_HEALTHY_SECONDS=${OG_HEALTHY_SECONDS:-600}
OG_PRUNE_SECONDS=${OG_PRUNE_SECONDS:-60}
OG_LOCK_RETRY_SECONDS=${OG_LOCK_RETRY_SECONDS:-60}
OG_OOM_SCORE_ADJ=${OG_OOM_SCORE_ADJ-1000}
OG_MEM_GUARD_PERCENT=${OG_MEM_GUARD_PERCENT:-90}
OG_MEM_GUARD_SECONDS=${OG_MEM_GUARD_SECONDS:-2}
OG_CGROUP_DIR=${OG_CGROUP_DIR:-/sys/fs/cgroup}
OG_UNREACHABLE_PROBE_SECONDS=${OG_UNREACHABLE_PROBE_SECONDS:-15}
OG_WORKSPACE_SEED_DIR=${OG_WORKSPACE_SEED_DIR:-}
OG_WORKSPACE_SEED_UPDATE=${OG_WORKSPACE_SEED_UPDATE:-}
OG_BIN=${OG_BIN:-omnigent}
OG_PYTHON=${OG_PYTHON:-}
OG_HELPER=${OG_HELPER:-$(dirname "$0")/og_helper.py}

TOKENS=$OG_DATA_DIR/auth_tokens.json
CONFIG=$OG_CONFIG_HOME/config.yaml
SUPLOG=$OG_STATE_DIR/supervisor.log
HOSTLOG=$OG_STATE_DIR/host.log
LOCK=$OG_STATE_DIR/supervisor.lock

# Integer knobs: non-numbers fall back to the default, then floors apply (a
# zero/negative interval must never turn a loop into a busy loop).
int_or() { case $1 in ''|*[!0-9]*) printf '%s' "$2" ;; *) printf '%s' "$1" ;; esac; }
at_least() { if [ "$1" -lt "$2" ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
OG_WATCH_SECONDS=$(at_least "$(int_or "$OG_WATCH_SECONDS" 120)" 2)
OG_LOG_MAX_BYTES=$(at_least "$(int_or "$OG_LOG_MAX_BYTES" 5242880)" 65536)
OG_LOGS_MAX_BYTES=$(at_least "$(int_or "$OG_LOGS_MAX_BYTES" 268435456)" 1048576)
OG_LOG_RETENTION_DAYS=$(at_least "$(int_or "$OG_LOG_RETENTION_DAYS" 14)" 1)
OG_STOP_GRACE_SECONDS=$(at_least "$(int_or "$OG_STOP_GRACE_SECONDS" 15)" 1)
OG_CONFIRM_SECONDS=$(at_least "$(int_or "$OG_CONFIRM_SECONDS" 20)" 1)
OG_IDLE_SECONDS=$(at_least "$(int_or "$OG_IDLE_SECONDS" 15)" 1)
OG_REPROBE_SECONDS=$(at_least "$(int_or "$OG_REPROBE_SECONDS" 300)" 2)
OG_TICK_SECONDS=$(at_least "$(int_or "$OG_TICK_SECONDS" 5)" 1)
OG_BACKOFF_MAX=$(at_least "$(int_or "$OG_BACKOFF_MAX" 300)" 5)
OG_BACKOFF_78_MIN=$(at_least "$(int_or "$OG_BACKOFF_78_MIN" 60)" 1)
OG_BACKOFF_78_MAX=$(at_least "$(int_or "$OG_BACKOFF_78_MAX" 1800)" "$OG_BACKOFF_78_MIN")
OG_HEALTHY_SECONDS=$(at_least "$(int_or "$OG_HEALTHY_SECONDS" 600)" 1)
OG_PRUNE_SECONDS=$(at_least "$(int_or "$OG_PRUNE_SECONDS" 60)" 1)
OG_LOCK_RETRY_SECONDS=$(at_least "$(int_or "$OG_LOCK_RETRY_SECONDS" 60)" 1)
OG_MEM_GUARD_PERCENT=$(int_or "$OG_MEM_GUARD_PERCENT" 90)
OG_MEM_GUARD_SECONDS=$(at_least "$(int_or "$OG_MEM_GUARD_SECONDS" 2)" 1)
OG_UNREACHABLE_PROBE_SECONDS=$(at_least "$(int_or "$OG_UNREACHABLE_PROBE_SECONDS" 15)" 2)

# ── environment for every omnigent process (host, runners, helper) ───────────
export OMNIGENT_CONFIG_HOME="$OG_CONFIG_HOME" OMNIGENT_DATA_DIR="$OG_DATA_DIR"
export OG_STATE_DIR OG_HOST_NAME OG_PROVIDERS
export OG_WORKSPACE OG_WORKSPACE_SEED_DIR OG_WORKSPACE_SEED_UPDATE
export OMNIGENT_HOST_NO_OPEN=1
export OMNIGENT_ANALYTICS=0 DO_NOT_TRACK=1 DISABLE_TELEMETRY=1 OMNIGENT_DISABLE_TELEMETRY=1

# ── logging / status ─────────────────────────────────────────────────────────
now() { date +%s; }
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() {
  _l="$(ts) omnigent-host: $*"
  printf '%s\n' "$_l"
  printf '%s\n' "$_l" 2>/dev/null >>"$SUPLOG" || true
}
jesc() { printf '%s' "$1" | tr -d '\000-\037' | sed 's/\\/\\\\/g; s/"/\\"/g'; }

ST_STATE=""
ST_DETAIL=""
ST_ACTION=""
ST_SINCE=""
ST_RETRY_AT=""
ST_SERVER=""
ST_LOGIN_URL=""
ST_GUARD=""
RESTARTS=0
LAST_RC=""

# The Omnigent URL for hints (and the helper's fallback server): OG_SERVER_URL
# if set, else the first line of OG_SERVER_URL_FILE, re-read on every use (a
# mounted ConfigMap file follows `helm upgrade` without a pod restart). Only
# http(s) URLs without whitespace, quotes or backslashes are used.
SURL=""
read_server_url() {
  SURL=$OG_SERVER_URL
  if [ -z "$SURL" ] && [ -n "$OG_SERVER_URL_FILE" ] && [ -r "$OG_SERVER_URL_FILE" ]; then
    IFS= read -r SURL <"$OG_SERVER_URL_FILE" || :
  fi
  case $SURL in
    http://?* | https://?*) ;;
    *) SURL="" ;;
  esac
  case $SURL in
    *[[:space:][:cntrl:]\"\'\\\`]*) SURL="" ;;
  esac
  SURL=${SURL%/}
}
login_command() {
  read_server_url
  _u=${SURL:-$ST_LOGIN_URL}
  printf 'omnigent login %s' "${_u:-<Omnigent URL>}"
}
write_status() {
  _dir=$(dirname "$OG_STATUS_FILE")
  mkdir -p "$_dir" 2>/dev/null || return 0
  _tmp="$OG_STATUS_FILE.tmp.$$"
  {
    printf '{\n'
    printf '  "schema": 1,\n'
    printf '  "state": "%s",\n' "$(jesc "$ST_STATE")"
    printf '  "detail": "%s",\n' "$(jesc "$ST_DETAIL")"
    printf '  "action": "%s",\n' "$(jesc "$ST_ACTION")"
    printf '  "login_command": "%s",\n' "$(jesc "$(login_command)")"
    printf '  "server": "%s",\n' "$(jesc "$ST_SERVER")"
    printf '  "host_name": "%s",\n' "$(jesc "$OG_HOST_NAME")"
    printf '  "workspace": "%s",\n' "$(jesc "$OG_WORKSPACE")"
    printf '  "since": "%s",\n' "$(jesc "$ST_SINCE")"
    printf '  "updated": "%s",\n' "$(ts)"
    printf '  "retry_at": "%s",\n' "$(jesc "$ST_RETRY_AT")"
    printf '  "restarts": "%s",\n' "$RESTARTS"
    printf '  "last_exit_code": "%s",\n' "$(jesc "$LAST_RC")"
    printf '  "host_log": "%s",\n' "$(jesc "$HOSTLOG")"
    printf '  "memory_guard": "%s",\n' "$(jesc "$ST_GUARD")"
    printf '  "supervisor_pid": "%s"\n' "$$"
    printf '}\n'
  } >"$_tmp" 2>/dev/null && chmod 644 "$_tmp" 2>/dev/null && mv -f "$_tmp" "$OG_STATUS_FILE" 2>/dev/null
  rm -f "$_tmp" 2>/dev/null
  return 0
}
# set_status <state> <detail> [action] — writes only when something changed.
set_status() {
  _a=${3:-}
  if [ "$1" = "$ST_STATE" ] && [ "$2" = "$ST_DETAIL" ] && [ "$_a" = "$ST_ACTION" ]; then return 0; fi
  [ "$1" = "$ST_STATE" ] || ST_SINCE=$(ts)
  ST_STATE=$1 ST_DETAIL=$2 ST_ACTION=$_a
  write_status
}

# ── small utilities ──────────────────────────────────────────────────────────
child=""
STOPPING=0
HOST_RC=0
# Interruptible sleep: traps run as soon as a signal arrives. The sleep must not
# inherit fd 9 (the lock), or an orphaned sleep would keep holding it.
NAP_PID=""
nap() {
  sleep "$1" 9>&- &
  NAP_PID=$!
  wait "$NAP_PID" 2>/dev/null || true
  NAP_PID=""
}
# A condition this container cannot fix (disabled, image too old, ...): record
# it for omnigent-host-status and exit quietly; the product keeps running.
give_up() {
  log "$1; exiting (the product is not affected)"
  [ -n "${2:-}" ] && set_status "$2" "${3:-$1}" "${4:-}"
  exit 0
}
fsize() { wc -c 2>/dev/null <"$1" | tr -d ' ' || echo 0; }
fingerprint() {
  for _f in "$TOKENS" "$CONFIG"; do
    if [ -e "$_f" ]; then printf '%s:%s ' "$(stat -c %Y "$_f" 2>/dev/null)" "$(fsize "$_f")"; else printf 'none '; fi
  done
}
# Rotate a log this supervisor writes (copytruncate: writers use O_APPEND).
rotate_log() {
  [ -f "$1" ] || return 0
  [ "$(fsize "$1")" -gt "$OG_LOG_MAX_BYTES" ] || return 0
  cp -f "$1" "$1.1" 2>/dev/null && : >"$1"
}
# Cap omnigent's own log files (host/runner/...) and prune them by age and total size.
prune_omnigent_logs() {
  _ld=$OG_DATA_DIR/logs
  [ -d "$_ld" ] || return 0
  find "$_ld" -type f -mtime +"$OG_LOG_RETENTION_DAYS" -exec rm -f {} + 2>/dev/null
  _capk=$((OG_LOG_MAX_BYTES / 1024))
  find "$_ld" -type f -size +"${_capk}k" 2>/dev/null | while IFS= read -r _f; do
    tail -c $((OG_LOG_MAX_BYTES / 2)) "$_f" >"$_f.trim" 2>/dev/null && cat "$_f.trim" >"$_f"
    rm -f "$_f.trim"
  done
  _maxk=$((OG_LOGS_MAX_BYTES / 1024))
  _n=0
  while [ "$_n" -lt 200 ]; do
    _tot=$(du -sk "$_ld" 2>/dev/null | awk '{print $1}')
    [ "${_tot:-0}" -gt "$_maxk" ] || break
    # shellcheck disable=SC2012 # oldest file first; log names have no newlines
    _old=$(ls -1tr "$_ld"/runner/* "$_ld"/host/* 2>/dev/null | head -n 1)
    [ -n "$_old" ] || break
    rm -f "$_old"
    _n=$((_n + 1))
  done
}
rotate_all() {
  rotate_log "$SUPLOG"
  rotate_log "$HOSTLOG"
}

# ── signals ──────────────────────────────────────────────────────────────────
stop_host() {
  [ -n "$child" ] || return 0
  kill -TERM "$child" 2>/dev/null
  _i=0
  while kill -0 "$child" 2>/dev/null && [ "$_i" -lt "$OG_STOP_GRACE_SECONDS" ]; do
    sleep 1
    _i=$((_i + 1))
  done
  if kill -0 "$child" 2>/dev/null; then
    log "host (pid $child) ignored SIGTERM for ${OG_STOP_GRACE_SECONDS}s; sending SIGKILL"
    # whole process group (setsid); dash wants "--", busybox rejects it
    kill -s KILL -- "-$child" 2>/dev/null || kill -s KILL "-$child" 2>/dev/null
    kill -s KILL "$child" 2>/dev/null
  fi
  wait "$child" 2>/dev/null
  HOST_RC=$?
  child=""
}
on_term() {
  trap '' TERM INT HUP
  STOPPING=1
  [ -n "$NAP_PID" ] && kill "$NAP_PID" 2>/dev/null
  log "received stop signal; shutting down"
  stop_host
  ST_RETRY_AT=""
  set_status stopped "supervisor stopped (container terminating)"
  exit 0
}
trap on_term TERM INT HUP

# ── startup checks ───────────────────────────────────────────────────────────
case $OG_HOST_ENABLED in
  0 | false | no | off) log "omnigentHost disabled (OG_HOST_ENABLED=$OG_HOST_ENABLED); exiting"; exit 0 ;;
esac
if ! mkdir -p "$OG_STATE_DIR" 2>/dev/null || ! (: >>"$LOCK") 2>/dev/null; then
  give_up "cannot write $OG_STATE_DIR (volume missing or read-only)" error "state directory $OG_STATE_DIR is not writable"
fi
chmod 700 "$OG_STATE_DIR" 2>/dev/null || true
if ! command -v flock >/dev/null 2>&1; then
  give_up "flock is not available in this image (needed for the one-host lock)" image-too-old "flock missing in this image" "redeploy the service with a current image"
fi
exec 9>>"$LOCK"
if ! flock -n 9; then
  log "another supervisor holds $LOCK; waiting for it to exit"
  until flock -n 9; do nap "$OG_LOCK_RETRY_SECONDS"; done
fi

# From here on this process owns OG_STATE_DIR.
# The real omnigent CLI: OG_BIN as given when it is a path (charts set the
# image's pinned CLI), else the first "omnigent" on PATH that is not the kit's
# PATH shim (bin/omnigent refuses a second `omnigent host` while this
# supervisor holds the lock) and not under HOME/OG_HOME (a tenant-installed
# copy, e.g. in a persistent ~/.local/bin, never replaces the image's CLI).
under_home() {
  for _h in "$HOME0" "$HOME" "${OG_HOME:-}"; do
    _h=${_h%/}
    [ -n "$_h" ] || continue
    case $1 in "$_h"/*) return 0 ;; esac
  done
  return 1
}
og_real_bin() {
  case $1 in */*) [ -x "$1" ] && printf '%s' "$1"; return ;; esac
  _oifs=$IFS
  IFS=:
  set -f
  for _d in $PATH; do
    _c=${_d:-.}/$1
    under_home "$_c" && continue
    if [ -f "$_c" ] && [ -x "$_c" ] && ! head -c 512 "$_c" 2>/dev/null | grep -q OMNIGENT_HOST_KIT_SHIM; then
      IFS=$_oifs; set +f; printf '%s' "$_c"; return 0
    fi
  done
  IFS=$_oifs
  set +f
  return 1
}
og_bin_path=$(og_real_bin "$OG_BIN" || true)
if [ -z "$og_bin_path" ]; then
  give_up "omnigent CLI not found in this image" image-too-old "the omnigent CLI is not installed in this image" "redeploy the service with a current image"
fi
find_python() {
  if [ -n "$OG_PYTHON" ]; then printf '%s' "$OG_PYTHON"; return 0; fi
  _r=$(readlink -f "$og_bin_path" 2>/dev/null || printf '%s' "$og_bin_path")
  _p=$(sed -n '1s/^#![[:space:]]*//p' "$_r" 2>/dev/null | awk '{print $1}')
  case $_p in
    */env) _p=$(sed -n '1s/^#![[:space:]]*//p' "$_r" | awk '{print $2}'); _p=$(command -v "$_p" 2>/dev/null) ;;
  esac
  if [ -n "$_p" ] && [ -x "$_p" ]; then printf '%s' "$_p"; return 0; fi
  if [ -x "$(dirname "$_r")/python" ]; then printf '%s' "$(dirname "$_r")/python"; return 0; fi
  return 1
}
OG_PY=$(find_python) || OG_PY=""
if [ -z "$OG_PY" ] || ! "$OG_PY" -c 'import yaml' >/dev/null 2>&1 || [ ! -r "$OG_HELPER" ]; then
  give_up "cannot find omnigent's python (with PyYAML) or $OG_HELPER" image-too-old "omnigent's python or the kit helper is missing" "redeploy the service with a current image"
fi
tmux_ok() {
  [ -n "$OG_TMUX_MIN" ] || return 0
  _v=$(tmux -V 2>/dev/null) || return 1
  _v=${_v#tmux }
  _v=${_v#next-}
  _maj=$(printf '%s' "${_v%%.*}" | sed 's/[^0-9].*//')
  _min=$(printf '%s' "${_v#*.}" | sed 's/[^0-9].*//')
  _nmaj=$(int_or "${OG_TMUX_MIN%%.*}" 3)
  _nmin=$(int_or "${OG_TMUX_MIN#*.}" 3)
  [ -n "$_maj" ] || return 1
  [ -n "$_min" ] || _min=0
  [ "$_maj" -gt "$_nmaj" ] && return 0
  [ "$_maj" -eq "$_nmaj" ] && [ "$_min" -ge "$_nmin" ]
}
if ! tmux_ok; then
  give_up "tmux >= $OG_TMUX_MIN is required for the native Claude/pi harnesses and is missing" image-too-old "tmux >= $OG_TMUX_MIN is missing in this image" "redeploy the service with a current image"
fi

# Identity comes from config.yaml only; the env override would bypass it.
for _v in OMNIGENT_HOST_ID OMNIGENT_HOST_NAME; do
  if eval "[ -n \"\${$_v+x}\" ]"; then
    log "ignoring $_v from the environment (identity is kept in config.yaml)"
    unset "$_v"
  fi
done
# Variables the host (and so every session) must not inherit, e.g. platform API keys.
set -f
for _v in $(printf '%s' "$OG_UNSET_ENV" | tr ',' ' '); do
  case $_v in ''|*[!A-Za-z0-9_]*|[0-9]*) log "OG_UNSET_ENV: ignoring invalid name"; continue ;; esac
  unset "$_v"
done
# Extra env names sessions inherit (OMNIGENT_RUNNER_ENV_PASSTHROUGH).
_pt=""
for _v in $(printf '%s' "OMNIGENT_ANALYTICS,DO_NOT_TRACK,DISABLE_TELEMETRY,OG_HOST_TREE,$OG_PASSTHROUGH,${OMNIGENT_RUNNER_ENV_PASSTHROUGH:-}" | tr ',' ' '); do
  case $_v in ''|*[!A-Za-z0-9_]*|[0-9]*) log "OG_PASSTHROUGH: ignoring invalid name"; continue ;; esac
  case ",$_pt," in *",$_v,"*) ;; *) _pt=${_pt:+$_pt,}$_v ;; esac
done
set +f
export OMNIGENT_RUNNER_ENV_PASSTHROUGH="$_pt"

# Convenience links for the web UI's folder picker (it opens at the host's ~)
# and for omnigent's claude-sdk readiness check (it looks at ~/.claude).
if [ -n "$OG_WORKSPACE" ] && [ -d "$OG_WORKSPACE" ]; then
  case $OG_WORKSPACE in
    "$HOME" | "$HOME"/*) ;;
    *) [ -e "$HOME/workspace" ] || ln -s "$OG_WORKSPACE" "$HOME/workspace" 2>/dev/null || true ;;
  esac
fi
if [ -n "${CLAUDE_CONFIG_DIR:-}" ] && [ ! -e "$HOME/.claude" ]; then
  ln -s "$CLAUDE_CONFIG_DIR" "$HOME/.claude" 2>/dev/null || true
fi
SETSID=""
command -v setsid >/dev/null 2>&1 && SETSID=setsid
SUP_PID=$$

# ── login probe ──────────────────────────────────────────────────────────────
P_REASON=""
P_SERVER=""
P_LOGIN_URL=""
P_ACCOUNT=""
probe() {
  read_server_url
  _out=$(OG_SERVER_URL=$SURL "$OG_PY" "$OG_HELPER" state 2>/dev/null)
  _rc=$?
  P_REASON=$(printf '%s\n' "$_out" | sed -n 's/^reason=//p' | head -n 1)
  P_SERVER=$(printf '%s\n' "$_out" | sed -n 's/^server=//p' | head -n 1)
  P_LOGIN_URL=$(printf '%s\n' "$_out" | sed -n 's/^login_url=//p' | head -n 1)
  P_ACCOUNT=$(printf '%s\n' "$_out" | sed -n 's/^account=//p' | head -n 1)
  [ -n "$P_LOGIN_URL" ] && ST_LOGIN_URL=$P_LOGIN_URL
  case $_rc in
    0 | 3 | 4 | 5) return "$_rc" ;;
  esac
  P_REASON="probe-error-rc$_rc"
  return 5
}
# A rejection only counts when the server says so twice in a row.
probe_confirmed() {
  probe
  _prc=$?
  [ "$_prc" -eq 4 ] || return "$_prc"
  nap "$OG_CONFIRM_SECONDS"
  probe
}

SERVER=""
ACCOUNT=""
wait_for_login() {
  _last_fp="unset"
  _last_probe=0
  _rc=3
  while :; do
    if [ ! -s "$TOKENS" ]; then
      _rc=3
      P_REASON=no-token-file
      _last_fp="unset"
    else
      _fp=$(fingerprint)
      if [ "$_fp" != "$_last_fp" ] || [ $(($(now) - _last_probe)) -ge "$OG_REPROBE_SECONDS" ]; then
        probe_confirmed
        _rc=$?
        _last_fp=$(fingerprint)
        _last_probe=$(now)
      fi
    fi
    case $_rc in
      0 | 5)
        SERVER=$P_SERVER
        ACCOUNT=$P_ACCOUNT
        ST_SERVER=$SERVER
        [ "$_rc" -eq 5 ] && log "login found; server not reachable right now ($P_REASON) - starting the host anyway, it retries by itself"
        return 0
        ;;
      3)
        if [ "$ST_STATE" != waiting-login ]; then
          log "not logged in; waiting for the tenant to run: $(login_command)"
        fi
        ST_RETRY_AT=""
        set_status waiting-login "not logged in to Omnigent" "$(login_command)"
        ;;
      4)
        if [ "$ST_STATE" != login-expired ]; then
          log "Omnigent login expired or was revoked ($P_REASON); waiting for: $(login_command)"
        fi
        ST_RETRY_AT=""
        set_status login-expired "the Omnigent login expired or was revoked ($P_REASON)" "$(login_command)"
        ;;
    esac
    nap "$OG_IDLE_SECONDS"
  done
}

# ── workspace seed (optional; og_helper.py workspace, manifest-tracked) ─────
# Files from OG_WORKSPACE_SEED_DIR land in OG_WORKSPACE only where missing; the
# manifest (OG_STATE_DIR/workspace-seed.json) makes a tenant's deletion or edit
# permanent. Only paths in OG_WORKSPACE_SEED_UPDATE are updated, and only while
# unedited; other newer versions are offered under .omnigent-seed-updates/.
seed_workspace() {
  [ -n "$OG_WORKSPACE_SEED_DIR" ] && [ -d "$OG_WORKSPACE_SEED_DIR" ] && [ -n "$OG_WORKSPACE" ] || return 0
  "$OG_PY" "$OG_HELPER" workspace 2>&1 | while IFS= read -r _line; do log "seed: $_line"; done
}

# ── host lifecycle ───────────────────────────────────────────────────────────
STARTED=0
START_MARK=""
start_host() {
  seed_workspace
  "$OG_PY" "$OG_HELPER" seed 2>&1 | while IFS= read -r _line; do log "config: $_line"; done
  # A pod fsGroup makes kubelet chmod the volume (0600 -> 0660) on every mount.
  [ -f "$TOKENS" ] && chmod go-rwx "$TOKENS" 2>/dev/null
  rotate_all
  RESTARTS=$((RESTARTS + 1))
  START_MARK="=== omnigent-host supervisor: host start #$RESTARTS $(ts) ==="
  printf '%s\n' "$START_MARK" >>"$HOSTLOG" 2>/dev/null
  _wd=$HOME
  [ -n "$OG_WORKSPACE" ] && [ -d "$OG_WORKSPACE" ] && _wd=$OG_WORKSPACE
  # Own process group (setsid) so a SIGKILL escalation reaches the whole tree.
  # oom_score_adj (inherited by every session, also through tmux) so the kernel
  # prefers Omnigent sessions over the product; OG_HOST_TREE=<supervisor pid>
  # (inherited, and passed through to runners) marks the tree for the memory guard.
  # fd 9 (the lock) is not inherited: it belongs to this supervisor.
  (
    cd "$_wd" 2>/dev/null || cd "$HOME" 2>/dev/null || true
    _cur=$(cat /proc/self/oom_score_adj 2>/dev/null || echo 1000)
    case $OG_OOM_SCORE_ADJ in
      '' | *[!0-9]*) ;;   # only raising is supported (lowering needs privileges)
      *) [ "$_cur" -lt "$OG_OOM_SCORE_ADJ" ] && { printf '%s\n' "$OG_OOM_SCORE_ADJ" >/proc/self/oom_score_adj; } 2>/dev/null ;;
    esac
    OG_HOST_TREE=$SUP_PID
    export OG_HOST_TREE
    # shellcheck disable=SC2086 # $SETSID is empty or one word
    exec $SETSID "$og_bin_path" host --server "$SERVER" --non-interactive --no-open
  ) </dev/null >>"$HOSTLOG" 2>&1 9>&- &
  child=$!
  STARTED=$(now)
  ST_RETRY_AT=""
  log "host started (pid $child, server $SERVER, name ${OG_HOST_NAME:-<config.yaml>})"
  set_status starting "host process started, waiting for it to connect"
}
host_connected() {
  tail -n 400 "$HOSTLOG" 2>/dev/null | awk -v m="$START_MARK" '$0 == m {c = 0; s = 1} s && /Connected as/ {c = 1} END {exit !c}'
}
# True when the host printed "Connected as" after byte offset $1 of host.log
# (the whole file when it was rotated meanwhile): it reconnected by itself.
host_reconnected_since() {
  _sz=$(fsize "$HOSTLOG")
  [ "${_sz:-0}" -gt "$1" ] || { [ "${_sz:-0}" -lt "$1" ] && grep -q 'Connected as' "$HOSTLOG" 2>/dev/null; return; }
  tail -c +$(($1 + 1)) "$HOSTLOG" 2>/dev/null | grep -q 'Connected as'
}

# ── memory guard ─────────────────────────────────────────────────────────────
# The host shares the product's container cgroup. Kubernetes (cgroup v2) sets
# memory.oom.group=1, so a cgroup OOM kills EVERY process of the container,
# product included, whatever their oom_score_adj. Before that happens, kill the
# largest Omnigent session process (env OG_HOST_TREE=<this supervisor's pid>; never the host itself,
# never anything else) once the working set (usage - inactive_file, as kubelet
# counts it) reaches OG_MEM_GUARD_PERCENT of the container limit.
PAGE_KB=4
_pg=$(getconf PAGESIZE 2>/dev/null) && case $_pg in '' | *[!0-9]*) ;; *) PAGE_KB=$((_pg / 1024)) ;; esac
MG_USAGE="" MG_LIMIT="" MG_STAT="" MG_INACTIVE=""
if [ -r "$OG_CGROUP_DIR/memory.max" ] && [ -r "$OG_CGROUP_DIR/memory.current" ]; then
  MG_LIMIT=$OG_CGROUP_DIR/memory.max MG_USAGE=$OG_CGROUP_DIR/memory.current MG_STAT=$OG_CGROUP_DIR/memory.stat MG_INACTIVE=inactive_file
elif [ -r "$OG_CGROUP_DIR/memory/memory.limit_in_bytes" ]; then
  MG_LIMIT=$OG_CGROUP_DIR/memory/memory.limit_in_bytes MG_USAGE=$OG_CGROUP_DIR/memory/memory.usage_in_bytes MG_STAT=$OG_CGROUP_DIR/memory/memory.stat MG_INACTIVE=total_inactive_file
fi
MG_LAST=0
# mem_pct -> sets MG_PCT (working set as % of the limit), returns 1 without a limit
mem_pct() {
  [ -n "$MG_LIMIT" ] || return 1
  _lim="" _use="" _inact=0
  IFS= read -r _lim <"$MG_LIMIT" 2>/dev/null || :
  IFS= read -r _use <"$MG_USAGE" 2>/dev/null || :
  case $_lim$_use in '' | *[!0-9]*) return 1 ;; esac
  # "no limit" (v1 reports ~2^63): nothing to guard
  [ "${#_lim}" -lt 19 ] || return 1
  [ "$_lim" -gt 0 ] || return 1
  if [ -r "$MG_STAT" ]; then
    while read -r _k _v; do
      if [ "$_k" = "$MG_INACTIVE" ]; then _inact=$_v; break; fi
    done <"$MG_STAT"
  fi
  case $_inact in '' | *[!0-9]*) _inact=0 ;; esac
  _ws=$((_use - _inact))
  [ "$_ws" -gt 0 ] || _ws=0
  MG_PCT=$((_ws * 100 / _lim))
}
# MG_VICTIM = pid of the largest-RSS process carrying OG_HOST_TREE=$$, excluding
# the host ($child) and this supervisor ("" when there is none); MG_RSS_KB its RSS.
mem_victim() {
  _best="" _best_rss=0
  for _p in /proc/[0-9]*; do
    _pid=${_p#/proc/}
    [ "$_pid" = "$$" ] && continue
    [ "$_pid" = "$child" ] && continue
    [ -r "$_p/environ" ] || continue
    tr '\000' '\n' <"$_p/environ" 2>/dev/null | grep -qx "OG_HOST_TREE=$SUP_PID" || continue
    _rss=0
    read -r _sz _rss _rest <"$_p/statm" 2>/dev/null || continue
    case $_rss in '' | *[!0-9]*) continue ;; esac
    if [ "$_rss" -gt "$_best_rss" ]; then _best=$_pid _best_rss=$_rss; fi
  done
  MG_RSS_KB=$((_best_rss * PAGE_KB))
  MG_VICTIM=$_best
}
mem_guard() {
  [ "$OG_MEM_GUARD_PERCENT" -gt 0 ] || return 0
  mem_pct || return 0
  [ "$MG_PCT" -ge "$OG_MEM_GUARD_PERCENT" ] || return 0
  # one kill per OG_MEM_GUARD_SECONDS*3: give the kernel time to free memory
  _t=$(now)
  [ $((_t - MG_LAST)) -ge $((OG_MEM_GUARD_SECONDS * 3)) ] || return 0
  mem_victim
  _v=$MG_VICTIM
  [ -n "$_v" ] || return 0
  _comm=$(cat "/proc/$_v/comm" 2>/dev/null || echo '?')
  kill -KILL "$_v" 2>/dev/null || return 0
  MG_LAST=$_t
  log "memory guard: container at ${MG_PCT}% of its memory limit; killed Omnigent session process $_v ($_comm, $((MG_RSS_KB / 1024)) MiB) to protect the product"
  ST_GUARD="$(ts) killed session process $_comm ($((MG_RSS_KB / 1024)) MiB) at ${MG_PCT}% of the container memory limit"
  write_status
  return 0
}
# nap_guarded <seconds>: like nap, running the memory guard every OG_MEM_GUARD_SECONDS.
nap_guarded() {
  if [ -z "$MG_LIMIT" ] || [ "$OG_MEM_GUARD_PERCENT" -le 0 ]; then nap "$1"; return; fi
  _left=$1
  while [ "$_left" -gt 0 ]; do
    _s=$OG_MEM_GUARD_SECONDS
    [ "$_s" -gt "$_left" ] && _s=$_left
    nap "$_s"
    [ "$STOPPING" -eq 1 ] && return
    mem_guard
    _left=$((_left - _s))
  done
}

STOP_REASON=""
UNREACH_AT=""
watch_host() {
  STOP_REASON=""
  UNREACH_AT=""
  _next=$(($(now) + OG_WATCH_SECONDS))
  _fp=$(fingerprint)
  _last_cap=0
  while kill -0 "$child" 2>/dev/null; do
    nap_guarded "$OG_TICK_SECONDS"
    kill -0 "$child" 2>/dev/null || break
    _t=$(now)
    rotate_all
    if [ $((_t - _last_cap)) -ge "$OG_PRUNE_SECONDS" ]; then
      prune_omnigent_logs
      _last_cap=$_t
    fi
    [ "$ST_STATE" = starting ] && host_connected && set_status running "connected"
    # After an outage the host reconnects by itself: follow its log at once
    # instead of showing "unreachable" until the next probe.
    if [ -n "$UNREACH_AT" ] && host_reconnected_since "$UNREACH_AT"; then
      UNREACH_AT=""
      log "host reconnected to the server"
      [ "$ST_STATE" = running ] && set_status running "connected"
    fi
    _nfp=$(fingerprint)
    if [ "$_t" -ge "$_next" ] || [ "$_nfp" != "$_fp" ]; then
      probe_confirmed
      _rc=$?
      _fp=$(fingerprint)
      _next=$(($(now) + OG_WATCH_SECONDS))
      case $_rc in
        3 | 4)
          STOP_REASON=login
          log "watchdog: login no longer usable ($P_REASON, confirmed); stopping the host"
          stop_host
          return 0
          ;;
        0)
          if [ "$P_SERVER" != "$SERVER" ] || [ "$P_ACCOUNT" != "$ACCOUNT" ]; then
            STOP_REASON=relogin
            log "watchdog: the tenant logged in again (server or account changed); restarting the host"
            stop_host
            return 0
          fi
          UNREACH_AT=""
          if [ "$ST_STATE" = running ]; then set_status running "connected"; fi
          ;;
        5)
          if [ "$ST_STATE" = running ]; then
            set_status running "server unreachable right now ($P_REASON); the host keeps retrying"
            # watch the log for the host's own reconnect, and re-probe sooner
            [ -n "$UNREACH_AT" ] || UNREACH_AT=$(fsize "$HOSTLOG")
            [ "$OG_UNREACHABLE_PROBE_SECONDS" -lt "$OG_WATCH_SECONDS" ] && _next=$(($(now) + OG_UNREACHABLE_PROBE_SECONDS))
          fi
          ;;
      esac
    fi
  done
  wait "$child" 2>/dev/null
  HOST_RC=$?
  child=""
}

# Sleep up to $1 seconds; return early when the token/config files changed since
# the host exited (new login, `omnigent host reset-id`).
EXIT_FP=""
backoff_wait() {
  ST_RETRY_AT=$(date -u -d "@$(($(now) + $1))" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || printf '+%ss' "$1")
  write_status
  _end=$(($(now) + $1))
  while [ "$(now)" -lt "$_end" ]; do
    if [ "$(fingerprint)" != "$EXIT_FP" ]; then
      log "token/config files changed; retrying now"
      break
    fi
    nap "$OG_TICK_SECONDS"
  done
  ST_RETRY_AT=""
}

# ── main loop ────────────────────────────────────────────────────────────────
log "supervisor up (host name ${OG_HOST_NAME:-<config.yaml>}, data $OG_DATA_DIR, watch ${OG_WATCH_SECONDS}s)"
prune_omnigent_logs
backoff=5
backoff78=$OG_BACKOFF_78_MIN
while :; do
  wait_for_login
  start_host
  watch_host
  EXIT_FP=$(fingerprint)
  [ "$STOPPING" -eq 1 ] && exit 0
  _ran=$(($(now) - STARTED))
  LAST_RC=$HOST_RC
  case $STOP_REASON in
    login | relogin) continue ;;
  esac
  log "host exited rc=$HOST_RC after ${_ran}s (log: $HOSTLOG)"
  if [ "$_ran" -ge "$OG_HEALTHY_SECONDS" ]; then
    backoff=5
    backoff78=$OG_BACKOFF_78_MIN
  fi
  _tail=$(tail -n 60 "$HOSTLOG" 2>/dev/null)
  if [ "$HOST_RC" -eq 78 ]; then
    if printf '%s\n' "$_tail" | grep -q -e 'HTTP 409' -e 'already registered to a different account'; then
      log "this host id belongs to another Omnigent account; the tenant must run: omnigent host reset-id --yes (retry in ${backoff78}s)"
      set_status needs-reset-id "this machine's host id is registered to a different Omnigent account" "omnigent host reset-id --yes"
    else
      probe_confirmed
      case $? in
        3 | 4) continue ;;   # wait_for_login reports it
      esac
      set_status host-error "the host stopped with a permanent error (exit 78); see $HOSTLOG" ""
    fi
    backoff_wait "$backoff78"
    backoff78=$((backoff78 * 2))
    [ "$backoff78" -gt "$OG_BACKOFF_78_MAX" ] && backoff78=$OG_BACKOFF_78_MAX
  else
    if printf '%s\n' "$_tail" | grep -q 'already running'; then
      set_status duplicate-host "another omnigent host runs on this data directory (started by hand, bypassing the kit's omnigent wrapper?)" "OG_SHIM_BYPASS=1 omnigent host stop --all   (the background service then reconnects by itself)"
    else
      set_status backoff "the host exited (rc=$HOST_RC); restarting in ${backoff}s" ""
    fi
    backoff_wait "$backoff"
    backoff=$((backoff * 2))
    [ "$backoff" -gt "$OG_BACKOFF_MAX" ] && backoff=$OG_BACKOFF_MAX
  fi
done
