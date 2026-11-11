#!/usr/bin/env bash
set -euo pipefail

addon_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
run_script="${addon_dir}/rootfs/etc/s6-overlay/s6-rc.d/post-tailscaled/run"
tmpdir=$(mktemp -d)
trap 'rm -rf -- "${tmpdir}"' EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

cat > "${tmpdir}/bashio-stub" <<'EOF'
bashio::info.hostname() { printf 'ha-test\n'; }
bashio::config() {
  case "$1" in
    login_server) printf '%s\n' "${TEST_LOGIN_SERVER:-https://hs.example}" ;;
    auth_key)
      if [[ "${TEST_AUTH_MISSING:-0}" == 1 ]]; then
        printf 'null\n'
      else
        printf '%s\n' "${TEST_AUTH_KEY:-}"
      fi
      ;;
    'tags | join(",")') printf '%s\n' "${TEST_TAGS:-}" ;;
    *) printf '\n' ;;
  esac
}
bashio::config.true() { [[ "$1" == 'userspace_networking' ]]; }
bashio::config.false() { [[ "$1" != 'userspace_networking' ]]; }
bashio::config.has_value() { return 1; }
bashio::fs.socket_exists() { return 0; }
bashio::fs.file_exists() { return 0; }
bashio::var.has_value() { [[ -n "${1:-}" && "$1" != null ]]; }
bashio::log.info() { printf 'INFO %s\n' "$*" >> "$TEST_LOG"; }
bashio::log.warning() { printf 'WARN %s\n' "$*" >> "$TEST_LOG"; }
bashio::log.notice() { printf 'NOTICE %s\n' "$*" >> "$TEST_LOG"; }
bashio::addon.option() {
  [[ "$1" == auth_key && "$2" == '' ]] || return 90
  printf 'cleared\n' >> "$TEST_CLEAR_LOG"
  [[ "${TEST_CLEAR_FAIL:-0}" != 1 ]]
}
bashio::exit.nok() { printf 'ERROR %s\n' "$*" >> "$TEST_LOG"; exit 1; }
subnet-routes() { :; }
curl() { printf '{"Warning":null}\n'; }
EOF

cat > "${tmpdir}/tailscale-stub" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  status)
    if [[ " $* " == *' --self=true '* ]]; then
      printf '{"Self":{"KeyExpiry":null}}\n'
    else
      printf '{"BackendState":"%s"}\n' "$(<"$TEST_STATE")"
    fi
    ;;
  up)
    printf '%s\n' "$*" >> "$TEST_ARGV"
    if [[ "${TEST_LOGIN_SERVER:-https://hs.example}" != 'https://controlplane.tailscale.com' ]]; then
      [[ " $* " != *' --advertise-tags='* ]] || exit 74
    fi
    for arg in "$@"; do
      if [[ "$arg" == --auth-key=file:* ]]; then
        key_file="${arg#--auth-key=file:}"
        printf '%s\n' "$key_file" >> "$TEST_KEY_FILES"
        [[ "$(stat -c '%a' "$key_file")" == 600 ]] || exit 71
        [[ "$(<"$key_file")" == "$TEST_AUTH_KEY" ]] || exit 72
      fi
    done
    if [[ "${TEST_UP_FAIL:-0}" == 1 ]]; then exit 1; fi
    if [[ "${TEST_UP_STAYS:-0}" != 1 ]]; then
      printf 'Running\n' > "$TEST_STATE"
    fi
    ;;
  serve) exit 0 ;;
  *) exit 73 ;;
esac
EOF
chmod +x "${tmpdir}/tailscale-stub"

run_case() {
  local name="$1" initial="$2" key="$3" up_fail="$4" expected_exit="$5" clear_fail="${6:-0}" up_stays="${7:-0}" missing="${8:-0}" server="${9:-https://hs.example}" tags="${10:-}"
  local case_dir="${tmpdir}/${name}" status=0
  mkdir -p "$case_dir"
  printf '%s\n' "$initial" > "$case_dir/state"
  printf 'original-private-identity' > "$case_dir/identity"
  : > "$case_dir/argv"
  : > "$case_dir/log"
  : > "$case_dir/clear"
  : > "$case_dir/key-files"
  TEST_STATE="$case_dir/state" TEST_AUTH_KEY="$key" TEST_UP_FAIL="$up_fail" TEST_UP_STAYS="$up_stays" TEST_AUTH_MISSING="$missing" TEST_LOGIN_SERVER="$server" TEST_TAGS="$tags" \
    TEST_CLEAR_FAIL="$clear_fail" TEST_LOG="$case_dir/log" TEST_ARGV="$case_dir/argv" \
    TEST_CLEAR_LOG="$case_dir/clear" TEST_KEY_FILES="$case_dir/key-files" \
    BASH_ENV="${tmpdir}/bashio-stub" TAILSCALE_BIN="${tmpdir}/tailscale-stub" \
    AUTH_KEY_RUNTIME_DIR="$case_dir" TAILSCALE_PAIRING_TIMEOUT=1 \
    bash "$run_script" > "$case_dir/stdout" 2> "$case_dir/stderr" || status=$?
  [[ "$status" == "$expected_exit" ]] || fail "$name exited $status, expected $expected_exit"
  [[ "$(<"$case_dir/identity")" == 'original-private-identity' ]] || fail "$name changed identity"
  if [[ -n "$key" ]]; then
    ! grep -RFq -- "$key" "$case_dir" || fail "$name exposed key"
  fi
  while IFS= read -r path; do
    [[ ! -e "$path" ]] || fail "$name left temporary key file"
  done < "$case_dir/key-files"
}

run_case fresh NeedsLogin 'tskey-auth-fresh-secret' 0 0
grep -q -- '--auth-key=file:' "$tmpdir/fresh/argv" || fail 'fresh pairing did not use key file'
grep -q '^cleared$' "$tmpdir/fresh/clear" || fail 'successful pairing did not clear HA option'

run_case healthy Running 'tskey-auth-unused-secret' 0 0
! grep -q -- '--auth-key' "$tmpdir/healthy/argv" || fail 'healthy node was reauthenticated'
grep -q '^cleared$' "$tmpdir/healthy/clear" || fail 'healthy node did not clear unused key'

run_case rejected NeedsLogin 'tskey-auth-rejected-secret' 1 1
[[ ! -s "$tmpdir/rejected/clear" ]] || fail 'failed pairing cleared HA option'
grep -q -- '--auth-key=file:' "$tmpdir/rejected/argv" || fail 'failed pairing did not try key'

run_case interactive NeedsLogin '' 0 0
! grep -q -- '--auth-key' "$tmpdir/interactive/argv" || fail 'interactive path used a key'
[[ ! -s "$tmpdir/interactive/clear" ]] || fail 'interactive path changed HA option'

run_case missing NeedsLogin '' 0 0 0 0 1
! grep -q -- '--auth-key' "$tmpdir/missing/argv" || fail 'missing option was treated as a key'
[[ ! -s "$tmpdir/missing/clear" ]] || fail 'missing option was cleared again'

run_case clear_failure NeedsLogin 'tskey-auth-clear-secret' 0 1 1
grep -q '^cleared$' "$tmpdir/clear_failure/clear" || fail 'clear failure path was not tried'

run_case stalled NeedsLogin 'tskey-auth-stalled-secret' 0 1 0 1
[[ ! -s "$tmpdir/stalled/clear" ]] || fail 'stalled pairing cleared HA option'
grep -q 'Pairing did not complete' "$tmpdir/stalled/log" || fail 'stalled pairing gave no useful error'

run_case headscale_tags NeedsLogin 'tskey-auth-tags-secret' 0 0 0 0 0 https://hs.example tag:lab
! grep -q -- '--advertise-tags=' "$tmpdir/headscale_tags/argv" || fail 'Headscale received requested tags'
grep -q 'ignoring the add-on tags option' "$tmpdir/headscale_tags/log" || fail 'Headscale tag guidance missing'

run_case official NeedsLogin 'tskey-auth-official-secret' 0 0 0 0 0 https://controlplane.tailscale.com tag:lab
grep -q -- '--advertise-tags=tag:lab' "$tmpdir/official/argv" || fail 'official tags option was lost'

printf 'PASS: Headscale pairing lifecycle\n'
