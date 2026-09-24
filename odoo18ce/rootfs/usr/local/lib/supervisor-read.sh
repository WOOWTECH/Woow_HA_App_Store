#!/usr/bin/env bash
# ==============================================================================
# A Supervisor read that waits for its value (issues #119, #108).
#
# At boot a bashio read can come back empty for a moment: the Supervisor has
# not answered yet, or the DHCP lease behind `network.ipv4_address` has not
# arrived. bashio then writes that empty answer to its file cache under
# /tmp/.bashio, and every later read in this container returns it. One bad
# moment becomes the whole start.
#
# `woow::supervisor.read` runs the read again until it returns something or
# a budget runs out, flushing the cache keys behind it after every answer
# that is not a value — so the Supervisor is really asked again, and so an
# exhausted budget leaves nothing empty in the cache for the next reader.
# "Not a value" is the empty string, jq's `null`, and `0.0.0.0`: the
# Supervisor's own placeholder for a container whose network it has not
# loaded yet (supervisor/docker/app.py, NO_ADDDRESS). The value goes to
# stdout; an exhausted budget is exit 1 with nothing printed, and the
# caller decides what an empty value means and says how long was waited.
# When the budget runs out and the last attempt wrote an error, that error
# is logged, so "the Supervisor said nothing" and "the Supervisor could not
# be asked" (no token, no socket, an API error) read differently.
#
# `woow::supervisor.read_until_ok` is the variant for a read whose empty
# answer is a real answer — a port that is not published — and that only
# needs another try when the Supervisor request itself failed.
#
# What neither bounds is one read that hangs: bashio's curl has no
# --max-time, so a Supervisor that accepts the connection and never
# answers holds the read, as it held the single read before this helper.
#
# Usage:
#   woow::supervisor.read          BUDGET POLL "KEY..." COMMAND [ARG...]
#   woow::supervisor.read_until_ok BUDGET POLL "KEY..." COMMAND [ARG...]
#     BUDGET   seconds to keep trying (decided on #108: 30)
#     POLL     seconds between attempts (decided on #108: 2)
#     KEY...   bashio cache keys to flush between attempts, space-separated:
#              the filtered key and the info key it is derived from
#     COMMAND  the bashio read, with its arguments
#
# Sourced, not executed: `. /usr/local/lib/supervisor-read.sh`.
# ==============================================================================

# The budget decided on #108, owned here so every caller reads one number.
WOOW_SUPERVISOR_BUDGET="${WOOW_SUPERVISOR_BUDGET:-30}"
WOOW_SUPERVISOR_POLL="${WOOW_SUPERVISOR_POLL:-2}"

woow::supervisor.is_value() {
    case "$1" in
        ''|null|0.0.0.0) return 1 ;;
        *) return 0 ;;
    esac
}

# The clock the budget is measured on. bash's SECONDS counts whole seconds;
# a test replaces this function with a counter its `sleep` stub advances.
woow::supervisor.now() {
    printf '%s' "${SECONDS}"
}

# Flush the given cache keys. In a subshell: bashio's flush ends the shell
# on a filesystem error, and that must not end the script it was called from.
woow::supervisor.flush() {
    local key
    for key in $1; do
        ( bashio::cache.flush "${key}" ) || true
    done
}

# One retry loop for both reads. $1 is the acceptance test: `value` accepts
# on a value, `ok` accepts on the command's exit status.
woow::supervisor._retry() {
    local accept=$1 budget=$2 poll=$3 keys=$4
    shift 4
    local started value='' status error
    started="$(woow::supervisor.now)"
    error="$(mktemp)"
    while :; do
        status=0
        value="$("$@" 2>"${error}")" || status=$?
        case "${accept}" in
            value)
                # An answer that is not a value is retried, and bashio's
                # cache of it flushed so the Supervisor is really asked.
                if woow::supervisor.is_value "${value}"; then
                    status=0
                else
                    status=1
                    woow::supervisor.flush "${keys}"
                fi
                ;;
            # ok: the command's own status decides, and bashio caches only
            # a request that succeeded, so there is nothing to flush.
        esac
        if [ "${status}" -eq 0 ]; then
            rm -f "${error}"
            printf '%s' "${value}"
            return 0
        fi
        # Whole seconds, so "past the budget" rather than "at it": the wait
        # is then never shorter than asked, at most a poll longer. A budget
        # of nothing is one attempt and no poll.
        if [ "${budget}" -le 0 ] \
            || [ $(( $(woow::supervisor.now) - started )) -gt "${budget}" ]; then
            break
        fi
        sleep "${poll}"
    done
    if [ -s "${error}" ]; then
        bashio::log.warning "Supervisor read $1 failed on its last attempt: $(tail -n 1 "${error}")"
    fi
    rm -f "${error}"
    return 1
}

woow::supervisor.read() {
    woow::supervisor._retry value "$@"
}

woow::supervisor.read_until_ok() {
    woow::supervisor._retry ok "$@"
}

# ------------------------------------------------------------------------------
# Hand a value from cont-init to the services (issue #108, ADR 0006).
#
# s6-overlay reads /run/s6/container_environment/NAME into the environment
# of every `with-contenv` script that starts later, so a value settled once
# in cont-init is the value the maintenance bootstrap sees, and neither side
# derives it twice. An empty file means "unset" to s6-envdir, which is why
# the settle step below publishes a marker beside the values. The file is
# made world-readable whatever the caller's umask (cont-init runs under
# 077), so a with-contenv reader that is not root — none today — is not
# stopped by s6-envdir on a file it cannot read. The Static tier points
# WOOW_CONTAINER_ENV_DIR elsewhere.
#
#   woow::supervisor.publish NAME VALUE
# ------------------------------------------------------------------------------
woow::supervisor.publish() {
    local dir="${WOOW_CONTAINER_ENV_DIR:-/run/s6/container_environment}"
    mkdir -p "${dir}" \
        && printf '%s' "$2" > "${dir}/$1" \
        && chmod 0644 "${dir}/$1"
}

# ------------------------------------------------------------------------------
# The Canonical URL's two Supervisor inputs, settled once per start.
#
# Without public_url the Canonical URL is the host's LAN IPv4 address with
# the published Odoo port. Both come from the Supervisor, and both share
# one budget (WOOW_SUPERVISOR_BUDGET, decided on #108): the address is
# waited for first, and the port gets whatever is left, read again only
# while the request itself fails, because "no port published" is an empty
# answer that is final. A Supervisor that cannot be asked at all therefore
# costs one budget, not two. Whatever was settled — possibly nothing — is
# set in WOOW_LAN_IPV4 and WOOW_LAN_PORT for the caller and published under
# the same names with WOOW_CANONICAL_SETTLED=1, so the bootstrap reuses this
# start's answer and never asks on its own. An address that never comes is
# one warning here; the caller's own "no Canonical URL" line follows.
# Returns 1 when there is no address, 0 otherwise.
# ------------------------------------------------------------------------------
woow::supervisor.settle_canonical_inputs() {
    local budget="${WOOW_SUPERVISOR_BUDGET}" poll="${WOOW_SUPERVISOR_POLL}"
    local started status=0 remaining
    started="$(woow::supervisor.now)"
    WOOW_LAN_IPV4="$(woow::supervisor.read "${budget}" "${poll}" \
        "network.interface.default.info.ipv4.address network.interface.default.info" \
        bashio::network.ipv4_address)" || status=1
    if [ -z "${WOOW_LAN_IPV4}" ]; then
        bashio::log.warning "The Supervisor reported no host LAN address after waiting at least ${budget} seconds; this start has no Canonical URL from it"
    fi
    remaining=$(( budget - ( $(woow::supervisor.now) - started ) ))
    if [ "${remaining}" -lt 0 ]; then
        remaining=0
    fi
    WOOW_LAN_PORT="$(woow::supervisor.read_until_ok "${remaining}" "${poll}" \
        "addons.self.network.8069-tcp addons.self.info" \
        bashio::addon.port 8069)" || true
    if ! woow::supervisor.publish WOOW_LAN_IPV4 "${WOOW_LAN_IPV4}" \
        || ! woow::supervisor.publish WOOW_LAN_PORT "${WOOW_LAN_PORT}" \
        || ! woow::supervisor.publish WOOW_CANONICAL_SETTLED 1; then
        # The bootstrap will see no marker and use no LAN address; this side
        # drops what it settled on too, so both sides stay equal (ADR 0006).
        bashio::log.warning "The settled Canonical URL inputs could not be published to the container environment; this start uses no LAN address on either side"
        WOOW_LAN_IPV4=''
        WOOW_LAN_PORT=''
        status=1
    fi
    return "${status}"
}
