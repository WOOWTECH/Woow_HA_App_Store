#!/usr/bin/env bash
# Stopping the app must stop tailscaled itself with SIGTERM.
#
# s6 sends SIGTERM to the service's run process. If the run script keeps
# running as bash with tailscaled in a pipeline, only bash gets the signal:
# tailscaled is left running until the container's final kill, and a service
# restart would start a second tailscaled next to it. tailscaled must be the
# run process in every mode (debug or not, with or without the dnsmasq
# resolv.conf), and outside debug mode its log is still cut after 200 lines.
set -euo pipefail

addon_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
run_script="${addon_dir}/rootfs/etc/s6-overlay/s6-rc.d/tailscaled/run"
tmpdir=$(mktemp -d)
cleanup() {
    pkill -TERM -f "${tmpdir}/" 2>/dev/null || true
    rm -rf -- "${tmpdir}"
}
trap cleanup EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

wait_for() {
    local i
    for i in $(seq 1 100); do
        if eval "$1"; then return 0; fi
        sleep 0.05
    done
    return 1
}

mkdir -p "${tmpdir}/bin"
# unshare -m and mount need root; the stubs keep the exec chain the same.
printf '#!/usr/bin/env bash\nshift\nexec "$@"\n' > "${tmpdir}/bin/unshare"
printf '#!/usr/bin/env bash\nexit 0\n' > "${tmpdir}/bin/mount"
cat > "${tmpdir}/tailscaled" <<'STUB'
#!/usr/bin/env bash
trap 'printf "TERM\n" > "$TEST_DIR/signal"; exit 0' TERM
printf '%s\n' "$$" > "$TEST_DIR/pid"
for i in $(seq 1 250); do printf 'tailscaled line %s\n' "$i"; done
while :; do sleep 0.1; done
STUB
chmod +x "${tmpdir}/bin/unshare" "${tmpdir}/bin/mount" "${tmpdir}/tailscaled"

cat > "${tmpdir}/bashio-stub" <<'STUB'
bashio::log.info() { :; }
bashio::log.notice() { :; }
bashio::debug() { [[ "$TEST_DEBUG" == 1 ]]; }
bashio::addon.port() { printf '41641\n'; }
bashio::var.has_value() { [[ -n "${1:-}" && "$1" != null ]]; }
bashio::config.true() { return 1; }
bashio::fs.file_exists() { [[ -e "$1" ]]; }
STUB

run_case() {
    local name="$1" debug="$2" dnsmasq="$3"
    local case_dir="${tmpdir}/${name}"
    mkdir -p "${case_dir}"
    [[ "${dnsmasq}" == 0 ]] || printf 'nameserver 127.100.100.100\n' > "${case_dir}/resolv.dnsmasq.conf"
    sed -e "s#/opt/tailscaled#${tmpdir}/tailscaled#g" \
        -e "s#/etc/resolv\.#${case_dir}/resolv.#g" \
        -- "${run_script}" > "${case_dir}/run"

    TEST_DIR="${case_dir}" TEST_DEBUG="${debug}" BASH_ENV="${tmpdir}/bashio-stub" \
        PATH="${tmpdir}/bin:${PATH}" \
        bash "${case_dir}/run" > "${case_dir}/out" 2>&1 &
    local pid=$!

    wait_for "[[ -s '${case_dir}/pid' ]]" || fail "${name}: tailscaled did not start"
    [[ "$(<"${case_dir}/pid")" == "${pid}" ]] \
        || fail "${name}: tailscaled is not the run process (run ${pid}, tailscaled $(<"${case_dir}/pid"))"

    kill -TERM "${pid}"
    wait "${pid}" || true
    [[ "$(cat -- "${case_dir}/signal" 2>/dev/null)" == TERM ]] || fail "${name}: tailscaled did not get SIGTERM"

    if [[ "${debug}" == 0 ]]; then
        wait_for "grep -q 'further tailscaled logs suppressed' '${case_dir}/out'" \
            || fail "${name}: log is not cut after 200 lines"
        grep -qx 'tailscaled line 200' "${case_dir}/out" || fail "${name}: line 200 is missing"
        ! grep -qx 'tailscaled line 201' "${case_dir}/out" || fail "${name}: line 201 was not suppressed"
    fi
}

run_case plain 0 0
run_case plain_debug 1 0
run_case dnsmasq 0 1
run_case dnsmasq_debug 1 1

printf 'PASS: tailscaled gets SIGTERM in every mode\n'
