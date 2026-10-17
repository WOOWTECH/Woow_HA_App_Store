#!/usr/bin/env bash
# Every longrun "finish" script that takes down the S6 supervision tree must
# leave the container exit code at 0 when the service was stopped by SIGTERM.
#
# Stopping the app (Supervisor `docker stop`) makes s6 send SIGTERM to every
# longrun; s6 then calls finish with exit code 256 and signal 15. Writing
# 128+15=143 into the container exit code makes the container exit 143, which
# Supervisor records as a failed container: the app shows "error" instead of
# "stopped" after a normal stop (INFRA-HS-015-1). Other signals and real
# failures must still be reported.
set -euo pipefail

addon_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
services_dir="${addon_dir}/rootfs/etc/s6-overlay/s6-rc.d"
tmpdir=$(mktemp -d)
trap 'rm -rf -- "${tmpdir}"' EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

exitcode_file='/run/s6-linux-init-container-results/exitcode'
halt_bin='/run/s6/basedir/bin/halt'

# Run one finish script with the container paths redirected into a sandbox and
# the bashio/helper commands stubbed. Prints "<container exit code> <halted>".
run_finish() {
    local finish="$1"
    local container_code="$2"
    local service_code="$3"
    local signal="$4"
    local case_dir
    case_dir=$(mktemp -d -p "${tmpdir}")

    printf '%s\n' "${container_code}" > "${case_dir}/exitcode"
    printf '#!/usr/bin/env bash\ntouch %q\n' "${case_dir}/halted" > "${case_dir}/halt"
    chmod +x "${case_dir}/halt"

    {
        printf '%s\n' \
            'bashio::log.info() { :; }' \
            'bashio::log.warning() { :; }' \
            'magicdns-ingress-proxy-forwarding() { :; }' \
            'unprotect-subnet-routes() { :; }'
        # Drop the with-contenv shebang; redirect the container paths.
        tail -n +2 -- "${finish}" \
            | sed -e "s#${exitcode_file}#${case_dir}/exitcode#g" \
                  -e "s#${halt_bin}#${case_dir}/halt#g"
    } > "${case_dir}/finish"

    bash "${case_dir}/finish" "${service_code}" "${signal}" >/dev/null 2>&1 || true

    local halted=no
    [[ -e "${case_dir}/halted" ]] && halted=yes
    printf '%s %s\n' "$(tr -d '[:space:]' < "${case_dir}/exitcode")" "${halted}"
}

expect() {
    local finish="$1" want="$2" got
    shift 2
    got=$(run_finish "${finish}" "$@")
    [[ "${got}" == "${want}" ]] \
        || fail "${finish#"${services_dir}/"} with container=$1 service=$2 signal=$3: expected '${want}', got '${got}'"
}

checked=0
while IFS= read -r -d '' finish; do
    # Only the finish scripts that propagate a service failure to the container.
    grep -Fq "${exitcode_file}" "${finish}" || continue
    checked=$((checked + 1))

    # Normal stop: SIGTERM from s6 during container shutdown.
    expect "${finish}" '0 yes' 0 256 15
    # An earlier, real failure is never overwritten.
    expect "${finish}" '3 yes' 3 256 15
    # Killed by any other signal is still a failure (128 + signal).
    expect "${finish}" '137 no' 0 256 9
    expect "${finish}" '139 no' 0 256 11
    # A service that exits non-zero takes the container down with its code.
    expect "${finish}" '2 yes' 0 2 0
    # A clean exit changes nothing.
    expect "${finish}" '0 no' 0 0 0
done < <(find "${services_dir}" -mindepth 2 -maxdepth 2 -name finish -print0 | sort -z)

(( checked >= 8 )) || fail "expected at least 8 failure-propagating finish scripts, found ${checked}"

printf 'PASS: finish exit codes (%d scripts)\n' "${checked}"
