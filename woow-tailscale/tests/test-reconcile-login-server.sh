#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
helper="${repo_root}/woow-tailscale/rootfs/usr/local/lib/woow-tailscale/reconcile-login-server"
tmpdir=$(mktemp -d)
trap 'rm -rf -- "${tmpdir}"' EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

assert_file_mode() {
    local expected="$1"
    local path="$2"
    [[ "$(stat -c '%a' -- "${path}")" == "${expected}" ]] \
        || fail "expected ${path} mode ${expected}"
}

assert_no_backups() {
    local data_dir="$1"
    [[ ! -e "${data_dir}/state-backups" ]] \
        || [[ -z "$(find "${data_dir}/state-backups" -mindepth 1 -maxdepth 1 -name '*.tar.gz' -print -quit)" ]] \
        || fail "expected no backups"
}

backup_count() {
    find "$1/state-backups" -mindepth 1 -maxdepth 1 -name '*.tar.gz' -print | wc -l
}

make_state() {
    local data_dir="$1"
    printf 'state-private-key' > "${data_dir}/tailscaled.state"
    mkdir -p "${data_dir}/state"
    printf 'nested-private-key' > "${data_dir}/state/profile.conf"
    printf 'serve-private-key' > "${data_dir}/final_serve_reset_is_done"
}

# Fresh install writes only a normalized private marker.
data_dir="${tmpdir}/fresh"
mkdir -p "${data_dir}"
DATA_DIR="${data_dir}" "${helper}" 'https://hs.example/'
[[ "$(<"${data_dir}/.woow-login-server")" == 'https://hs.example' ]] \
    || fail 'fresh install marker was not normalized'
assert_file_mode 600 "${data_dir}/.woow-login-server"
assert_no_backups "${data_dir}"

# An unchanged marker must preserve all state and create no archive.
data_dir="${tmpdir}/unchanged"
mkdir -p "${data_dir}"
printf 'https://hs.example\n' > "${data_dir}/.woow-login-server"
make_state "${data_dir}"
DATA_DIR="${data_dir}" "${helper}" 'https://hs.example///'
[[ "$(<"${data_dir}/tailscaled.state")" == 'state-private-key' ]] \
    || fail 'unchanged state file was altered'
[[ "$(<"${data_dir}/state/profile.conf")" == 'nested-private-key' ]] \
    || fail 'unchanged state directory was altered'
[[ "$(<"${data_dir}/final_serve_reset_is_done")" == 'serve-private-key' ]] \
    || fail 'unchanged serve marker was altered'
assert_no_backups "${data_dir}"
[[ ! -e "${data_dir}/state-backups" ]] || fail 'unchanged server created backup directory'

# A changed marker archives all known state before removing it.
data_dir="${tmpdir}/changed"
mkdir -p "${data_dir}"
printf 'https://old.example\n' > "${data_dir}/.woow-login-server"
make_state "${data_dir}"
DATA_DIR="${data_dir}" "${helper}" 'https://new.example/'
[[ "$(<"${data_dir}/.woow-login-server")" == 'https://new.example' ]] \
    || fail 'changed marker was not replaced'
[[ ! -e "${data_dir}/tailscaled.state" ]] || fail 'changed state file was not removed'
[[ ! -e "${data_dir}/state" ]] || fail 'changed state directory was not removed'
[[ ! -e "${data_dir}/final_serve_reset_is_done" ]] || fail 'changed serve marker was not removed'
[[ "$(backup_count "${data_dir}")" == 1 ]] || fail 'expected exactly one backup'
backup=$(find "${data_dir}/state-backups" -maxdepth 1 -name '*.tar.gz' -print -quit)
tar -tzf "${backup}" | grep -Fxq 'tailscaled.state'
tar -tzf "${backup}" | grep -Fxq 'state/profile.conf'
tar -tzf "${backup}" | grep -Fxq 'final_serve_reset_is_done'
assert_file_mode 700 "${data_dir}/state-backups"
assert_file_mode 600 "${backup}"

# A changed marker with no state members updates the marker without an empty archive.
data_dir="${tmpdir}/changed-no-state"
mkdir -p "${data_dir}"
printf 'https://old.example\n' > "${data_dir}/.woow-login-server"
DATA_DIR="${data_dir}" "${helper}" 'https://new.example/'
[[ "$(<"${data_dir}/.woow-login-server")" == 'https://new.example' ]] \
    || fail 'changed marker without state was not replaced'
[[ ! -e "${data_dir}/state-backups" ]] || fail 'changed marker without state created a backup directory'

# Existing archives are never overwritten when timestamps collide.
data_dir="${tmpdir}/archive-collision"
mkdir -p "${data_dir}/state-backups"
printf 'https://old.example\n' > "${data_dir}/.woow-login-server"
printf 'preserved archive member' > "${data_dir}/preserved"
timestamp='20260821T010101Z'
existing_archive="${data_dir}/state-backups/${timestamp}-control-server-state.tar.gz"
tar -C "${data_dir}" -czf "${existing_archive}" preserved
rm -f -- "${data_dir}/preserved"
existing_checksum=$(cksum < "${existing_archive}")
collision_bin="${tmpdir}/collision-bin"
mkdir -p "${collision_bin}"
cat > "${collision_bin}/date" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' '20260821T010101Z'
EOF
chmod +x "${collision_bin}/date"
make_state "${data_dir}"
PATH="${collision_bin}:${PATH}" DATA_DIR="${data_dir}" "${helper}" 'https://new.example'
[[ "$(cksum < "${existing_archive}")" == "${existing_checksum}" ]] \
    || fail 'timestamp collision overwrote the existing archive'
[[ "$(backup_count "${data_dir}")" == 2 ]] || fail 'timestamp collision did not create another archive'
new_archive=$(find "${data_dir}/state-backups" -maxdepth 1 -name '*.tar.gz' ! -name "${existing_archive##*/}" -print -quit)
[[ -n "${new_archive}" ]] || fail 'timestamp collision did not produce a distinct archive name'
tar -tzf "${new_archive}" | grep -Fxq 'tailscaled.state'

# A failed archive creation leaves no temporary archive and preserves state and marker.
data_dir="${tmpdir}/archive-failure"
mkdir -p "${data_dir}"
printf 'https://old.example\n' > "${data_dir}/.woow-login-server"
make_state "${data_dir}"
failing_tar_bin="${tmpdir}/failing-tar-bin"
mkdir -p "${failing_tar_bin}"
cat > "${failing_tar_bin}/tar" <<'EOF'
#!/usr/bin/env bash
archive=''
previous=''
for argument in "$@"; do
    if [[ "${previous}" == '-czf' ]]; then
        archive="${argument}"
        break
    fi
    previous="${argument}"
done
[[ -n "${archive}" ]] || exit 99
printf 'corrupt archive' > "${archive}"
exit 1
EOF
chmod +x "${failing_tar_bin}/tar"
set +e
PATH="${failing_tar_bin}:${PATH}" DATA_DIR="${data_dir}" "${helper}" 'https://new.example' >/dev/null 2>&1
status=$?
set -e
[[ ${status} != 0 ]] || fail 'archive creation failure unexpectedly succeeded'
[[ "$(<"${data_dir}/.woow-login-server")" == 'https://old.example' ]] \
    || fail 'archive creation failure changed marker'
[[ "$(<"${data_dir}/tailscaled.state")" == 'state-private-key' ]] \
    || fail 'archive creation failure removed state'
[[ -z "$(find "${data_dir}/state-backups" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
    || fail 'archive creation failure left a temporary archive'

# state-backups must be a real directory, never a symlink to another location.
data_dir="${tmpdir}/backup-symlink"
target_dir="${tmpdir}/backup-target"
mkdir -p "${data_dir}" "${target_dir}"
chmod 0755 "${target_dir}"
printf 'target remains untouched' > "${target_dir}/sentinel"
ln -s "${target_dir}" "${data_dir}/state-backups"
printf 'https://old.example\n' > "${data_dir}/.woow-login-server"
make_state "${data_dir}"
set +e
DATA_DIR="${data_dir}" "${helper}" 'https://new.example' >/dev/null 2>&1
status=$?
set -e
[[ ${status} != 0 ]] || fail 'symlinked backup directory unexpectedly succeeded'
[[ "$(<"${target_dir}/sentinel")" == 'target remains untouched' ]] \
    || fail 'symlinked backup directory altered its target'
assert_file_mode 755 "${target_dir}"
[[ "$(<"${data_dir}/tailscaled.state")" == 'state-private-key' ]] \
    || fail 'symlinked backup directory removed state'
[[ "$(<"${data_dir}/.woow-login-server")" == 'https://old.example' ]] \
    || fail 'symlinked backup directory changed marker'

# State without an origin marker is never changed automatically.
data_dir="${tmpdir}/safety-guard"
mkdir -p "${data_dir}"
make_state "${data_dir}"
set +e
DATA_DIR="${data_dir}" "${helper}" 'https://hs.example' >/dev/null 2>&1
status=$?
set -e
[[ ${status} == 20 ]] || fail "safety guard exited ${status}, expected 20"
[[ "$(<"${data_dir}/tailscaled.state")" == 'state-private-key' ]] \
    || fail 'safety guard altered state file'
[[ "$(<"${data_dir}/state/profile.conf")" == 'nested-private-key' ]] \
    || fail 'safety guard altered state directory'
[[ "$(<"${data_dir}/final_serve_reset_is_done")" == 'serve-private-key' ]] \
    || fail 'safety guard altered serve marker'
[[ ! -e "${data_dir}/.woow-login-server" ]] || fail 'safety guard created marker'
[[ ! -e "${data_dir}/state-backups" ]] || fail 'safety guard created backup'

# More than three migrations retain only the latest three fixed-name archives.
data_dir="${tmpdir}/retention"
mkdir -p "${data_dir}"
printf 'https://server-0.example\n' > "${data_dir}/.woow-login-server"
fake_bin="${tmpdir}/fake-bin"
mkdir -p "${fake_bin}"
cat > "${fake_bin}/date" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "${FAKE_DATE}"
EOF
chmod +x "${fake_bin}/date"
for number in 1 2 3 4; do
    make_state "${data_dir}"
    timestamp=$(printf '20260821T00000%dZ' "${number}")
    PATH="${fake_bin}:${PATH}" FAKE_DATE="${timestamp}" DATA_DIR="${data_dir}" \
        "${helper}" "https://server-${number}.example"
done
[[ "$(backup_count "${data_dir}")" == 3 ]] || fail 'retention did not retain exactly three backups'
for timestamp in 20260821T000002Z 20260821T000003Z 20260821T000004Z; do
    [[ -f "${data_dir}/state-backups/${timestamp}-control-server-state.tar.gz" ]] \
        || fail "retention removed ${timestamp}"
done
[[ ! -e "${data_dir}/state-backups/20260821T000001Z-control-server-state.tar.gz" ]] \
    || fail 'retention kept the oldest backup'

printf 'PASS: reconcile-login-server\n'
