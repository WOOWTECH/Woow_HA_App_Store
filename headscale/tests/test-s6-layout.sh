#!/usr/bin/env bash
# Every legacy longrun in services.d must stay up once started. s6-overlay's
# legacy-services waits (s6-svwait -u, no time limit) until all of them are
# up; one that takes itself down on purpose (s6-svc -O / -d, then exit 0)
# keeps s6 startup from ever finishing, and the add-on is then SIGKILLed on
# every stop (exit 137). Pipeline unattended-pipeline/213.
#
# Usage: bash headscale/tests/test-s6-layout.sh
set -euo pipefail

addon_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
services="${addon_dir}/rootfs/etc/services.d"
failed=0

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    failed=1
}

for dir in "${services}"/*/; do
    name=$(basename "${dir}")
    run="${dir}run"
    [[ -f "${run}" ]] || { fail "${name}: no run script"; continue; }
    [[ "$(<"${dir}type")" == 'longrun' ]] || fail "${name}: type is not longrun"
    # Ignore comments when looking for commands.
    code=$(sed -e 's/^[[:space:]]*#.*$//' "${run}")
    if grep -Eq 's6-svc[[:space:]]+-[a-zA-Z]*[Od]' <<< "${code}"; then
        fail "${name}: run takes its own service down (s6-svc -O/-d)"
    fi
    if grep -Eq '(^|[[:space:];])(exit[[:space:]]+0|exit[[:space:]]*$|bashio::exit\.ok)' <<< "${code}"; then
        fail "${name}: run exits successfully instead of staying up"
    fi
    last=$(grep -Ev '^[[:space:]]*$' <<< "${code}" | tail -n1)
    [[ "${last}" =~ ^[[:space:]]*exec[[:space:]] ]] \
        || fail "${name}: last command is not exec (got: ${last})"
done

(( failed == 0 )) || exit 1
printf 'PASS: s6 legacy services stay up\n'
