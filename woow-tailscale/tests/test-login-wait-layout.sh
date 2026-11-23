#!/usr/bin/env bash
# Waiting for the first Tailscale login must not block the s6 start-up.
#
# s6-overlay brings the `user` bundle up in one `s6-rc -u change top` call and,
# on stop, runs `s6-rc -bda change`, which waits for that call to finish. If a
# service in the boot set waits for login (a oneshot, or a longrun with
# readiness notification), the start-up never completes before login, the stop
# waits for it, and Supervisor SIGKILLs the container (exit code 137).
#
# This test runs the real stage2 hook on a copy of the service tree for several
# app configurations, then checks the resulting service graph:
# - post-tailscaled (which waits for login) is a longrun without
#   notification-fd, so s6-rc counts it as up as soon as it is spawned;
# - nothing else in the boot set depends on post-tailscaled;
# - every service that needs a logged-in node is outside the boot set, in the
#   `logged-in` bundle that post-tailscaled starts after login, and still
#   depends on post-tailscaled so it is stopped before it.
set -euo pipefail

addon_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source_tree="${addon_dir}/rootfs/etc/s6-overlay/s6-rc.d"
hook="${addon_dir}/rootfs/etc/s6-overlay/scripts/stage2_hook.sh"
tmpdir=$(mktemp -d)
trap 'rm -rf -- "${tmpdir}"' EXIT

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

# Services that need a logged-in node (a Tailscale IP, the tailnet name, or
# the control plane's capabilities).
login_services=(forwarding magicdns-ingress-proxy mss-clamping share-homeassistant taildrive taildrop)

# Run the stage2 hook against a copy of the tree. Arguments are key=value
# app options; anything not given takes the config.yaml default.
prepare_tree() {
    local case_dir="$1"
    shift
    mkdir -p "${case_dir}"
    cp -a "${source_tree}" "${case_dir}/s6-rc.d"
    {
        printf 'declare -A TEST_OPTIONS=(\n'
        printf '  [userspace_networking]=true [accept_dns]=true [accept_routes]=true\n'
        printf '  [taildrop]=true [share_homeassistant]=disabled [advertise_routes]=local_subnets\n'
        local kv
        for kv in "$@"; do
            printf '  [%s]=%s\n' "${kv%%=*}" "${kv#*=}"
        done
        printf ')\n'
        cat <<'EOF'
bashio::addon.options() { printf '{}\n'; }
bashio::addon.option() { :; }
bashio::jq() { printf '\n'; }
bashio::var.true() { [[ "${1:-}" == true ]]; }
bashio::var.has_value() { [[ -n "${1:-}" ]]; }
bashio::log.info() { :; }
bashio::log.warning() { :; }
bashio::config() { printf '%s\n' "${TEST_OPTIONS[$1]}"; }
bashio::config.true() { [[ "${TEST_OPTIONS[$1]}" == true ]]; }
bashio::config.false() { [[ "${TEST_OPTIONS[$1]}" == false ]]; }
bashio::config.equals() { [[ "${TEST_OPTIONS[$1]}" == "$2" ]]; }
EOF
        tail -n +2 -- "${hook}" \
            | sed -e "s#/etc/s6-overlay/s6-rc.d#${case_dir}/s6-rc.d#g"
    } > "${case_dir}/hook"
    bash "${case_dir}/hook" > /dev/null 2>&1 || fail "stage2 hook failed for: $*"
}

# Print the atomic services a name expands to (a bundle expands to its contents).
expand() {
    local tree="$1" name="$2" item
    if [[ -d "${tree}/${name}/contents.d" ]]; then
        for item in "${tree}/${name}/contents.d"/*; do
            [[ -e "${item}" ]] || continue
            expand "${tree}" "$(basename -- "${item}")"
        done
    else
        printf '%s\n' "${name}"
    fi
}

# Print the direct dependencies of an atomic service. Services that are not in
# the tree (s6-overlay's own `base`) have none here.
direct_deps() {
    local tree="$1" name="$2" item
    [[ -d "${tree}/${name}/dependencies.d" ]] || return 0
    for item in "${tree}/${name}/dependencies.d"/*; do
        [[ -e "${item}" ]] || continue
        expand "${tree}" "$(basename -- "${item}")"
    done
}

# Print the transitive dependencies of an atomic service (not the service
# itself); fail on a dependency cycle.
declare -A visiting
all_deps() {
    local tree="$1" name="$2" dep
    [[ -z "${visiting[${name}]:-}" ]] || fail "dependency cycle through ${name}"
    visiting[${name}]=1
    while IFS= read -r dep; do
        printf '%s\n' "${dep}"
        all_deps "${tree}" "${dep}"
    done < <(direct_deps "${tree}" "${name}")
    unset 'visiting[${name}]'
}

# Print a bundle's services plus everything they depend on.
closure() {
    local tree="$1" bundle="$2" service
    while IFS= read -r service; do
        printf '%s\n' "${service}"
        all_deps "${tree}" "${service}"
    done < <(expand "${tree}" "${bundle}") | sort -u
}

contains() {
    grep -Fxq -- "$2" <<< "$1"
}

check_case() {
    local name="$1"
    shift
    local case_dir="${tmpdir}/${name}"
    prepare_tree "${case_dir}" "$@"
    local tree="${case_dir}/s6-rc.d"
    local boot logged_in service deps
    declare -A opts=([userspace_networking]=true [taildrop]=true [share_homeassistant]=disabled)
    local kv
    for kv in "$@"; do opts[${kv%%=*}]="${kv#*=}"; done

    [[ -d "${tree}/logged-in/contents.d" ]] || fail "${name}: no logged-in bundle"
    [[ "$(<"${tree}/logged-in/type")" == bundle ]] || fail "${name}: logged-in is not a bundle"

    boot=$(closure "${tree}" user)
    logged_in=$(closure "${tree}" logged-in)

    contains "${boot}" post-tailscaled || fail "${name}: post-tailscaled is not started at boot"
    [[ "$(<"${tree}/post-tailscaled/type")" == longrun ]] \
        || fail "${name}: post-tailscaled must be a longrun, a oneshot blocks the start-up until login"
    [[ ! -e "${tree}/post-tailscaled/notification-fd" ]] \
        || fail "${name}: post-tailscaled must not use notification-fd, s6-rc would wait for login at boot"

    while IFS= read -r service; do
        [[ "${service}" == post-tailscaled ]] && continue
        deps=$(all_deps "${tree}" "${service}")
        ! contains "${deps}" post-tailscaled \
            || fail "${name}: boot service ${service} depends on post-tailscaled and would wait for login"
    done <<< "${boot}"

    for service in "${login_services[@]}"; do
        ! contains "${boot}" "${service}" || fail "${name}: ${service} needs login but starts at boot"
    done

    local -a expected=(taildrive)
    if [[ "${opts[userspace_networking]}" != true ]]; then
        expected+=(forwarding magicdns-ingress-proxy mss-clamping)
    fi
    [[ "${opts[taildrop]}" == false ]] || expected+=(taildrop)
    [[ "${opts[share_homeassistant]}" == disabled ]] || expected+=(share-homeassistant)
    for service in "${expected[@]}"; do
        contains "${logged_in}" "${service}" || fail "${name}: ${service} is not started after login"
        deps=$(all_deps "${tree}" "${service}")
        contains "${deps}" post-tailscaled \
            || fail "${name}: ${service} does not depend on post-tailscaled"
    done
    for service in "${login_services[@]}"; do
        if contains "${logged_in}" "${service}" && ! printf '%s\n' "${expected[@]}" | grep -Fxq -- "${service}"; then
            fail "${name}: ${service} is disabled by the configuration but still started"
        fi
    done
}

check_case defaults
check_case kernel_dns userspace_networking=false accept_dns=true
check_case kernel_no_dns userspace_networking=false accept_dns=false
check_case kernel_no_routes userspace_networking=false accept_routes=false advertise_routes=
check_case userspace_no_dns accept_dns=false
check_case share_no_taildrop share_homeassistant=serve taildrop=false

printf 'PASS: waiting for login does not block the s6 start-up\n'
