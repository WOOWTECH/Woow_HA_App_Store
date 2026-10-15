# shellcheck shell=bash
# ==============================================================================
# Woow EMQX: node identity (node name and Erlang cookie)
#
# Sourced by the emqx service. Every function reads its state from
# WOOW_EMQX_STATE_DIR (default /data/emqx) so the logic can be exercised
# outside the add-on container.
# ==============================================================================

WOOW_EMQX_STATE_DIR="${WOOW_EMQX_STATE_DIR:-/data/emqx}"
WOOW_EMQX_DEFAULT_NODE_NAME="${WOOW_EMQX_DEFAULT_NODE_NAME:-emqx@127.0.0.1}"

# Logs go to stderr: the resolvers below are used inside $(...).
woow_emqx::warn() {
    bashio::log.warning "$@" >&2
}

woow_emqx::info() {
    bashio::log.info "$@" >&2
}

# ------------------------------------------------------------------------------
# Prints the EMQX node name to use.
#
# EMQX keeps its Mnesia database in <data_dir>/mnesia/<node name>. Add-on
# 5.9.0 and older derived the node name from the Home Assistant hostname
# (emqx@<hostname>.local), so renaming the host left EMQX on an empty
# database. The name is now resolved once and remembered in node.name:
#
#   1. node.name exists          -> keep it
#   2. exactly one database dir  -> keep the name that database carries
#   3. several database dirs     -> the hostname-derived name, exactly what
#                                   5.9.0 would have used (with a warning)
#   4. no database yet (new)     -> emqx@127.0.0.1, independent of hostname
# ------------------------------------------------------------------------------
woow_emqx::resolve_node_name() {
    local name_file="${WOOW_EMQX_STATE_DIR}/node.name"
    local mnesia_dir="${WOOW_EMQX_STATE_DIR}/data/mnesia"
    local -a node_dirs=()
    local hostname=''
    local legacy_name=''

    if [[ -s "${name_file}" ]]; then
        cat "${name_file}"
        return 0
    fi

    if [[ -d "${mnesia_dir}" ]]; then
        mapfile -t node_dirs < <(
            find "${mnesia_dir}" -mindepth 1 -maxdepth 1 -type d \
                -name '*@*' -printf '%f\n' | LC_ALL=C sort
        )
    fi

    if [[ "${#node_dirs[@]}" -eq 1 ]]; then
        printf '%s' "${node_dirs[0]}"
        return 0
    fi

    if [[ "${#node_dirs[@]}" -gt 1 ]]; then
        hostname=$(bashio::info.hostname 2>/dev/null) || hostname=''
        if [[ -n "${hostname}" && "${hostname}" != 'null' ]]; then
            legacy_name="emqx@${hostname}.local"
        fi

        woow_emqx::warn "Found ${#node_dirs[@]} EMQX databases in ${mnesia_dir}: ${node_dirs[*]}"
        woow_emqx::warn "This happens when the Home Assistant hostname changed before."
        woow_emqx::warn "Set EMQX_NODE__NAME in env_vars to the one you want to keep."

        if [[ -n "${legacy_name}" ]]; then
            printf '%s' "${legacy_name}"
            return 0
        fi
    fi

    printf '%s' "${WOOW_EMQX_DEFAULT_NODE_NAME}"
}

# ------------------------------------------------------------------------------
# Prints the Erlang cookie, creating node.cookie (mode 600) on first use.
#
# The cookie guards Erlang distribution, which this host-network add-on
# exposes on the LAN. 5.9.0 and older used the hostname, a value every
# installation can guess. Each installation now draws its own random cookie.
# The cookie is never written into the database, so changing it keeps data.
# ------------------------------------------------------------------------------
woow_emqx::ensure_node_cookie() {
    local cookie_file="${WOOW_EMQX_STATE_DIR}/node.cookie"
    local cookie

    if [[ ! -s "${cookie_file}" ]]; then
        cookie=$(od -vAn -tx1 -N32 /dev/urandom | tr -d ' \n')
        if [[ "${#cookie}" -ne 64 ]]; then
            woow_emqx::warn "Could not generate a random Erlang cookie"
            return 1
        fi
        (
            umask 077
            printf '%s' "${cookie}" > "${cookie_file}.tmp"
        ) && mv -f "${cookie_file}.tmp" "${cookie_file}" || return 1
        woow_emqx::info "Generated a new Erlang cookie in ${cookie_file}"
    fi

    chmod 600 "${cookie_file}" || return 1
    cat "${cookie_file}"
}

# ------------------------------------------------------------------------------
# Remembers the node name EMQX was started with.
# ------------------------------------------------------------------------------
woow_emqx::pin_node_name() {
    local name="${1}"
    local name_file="${WOOW_EMQX_STATE_DIR}/node.name"

    printf '%s' "${name}" > "${name_file}.tmp" \
        && mv -f "${name_file}.tmp" "${name_file}"
}

# ------------------------------------------------------------------------------
# Maps the host part of a long node name onto 127.0.0.1.
#
# Erlang distribution resolves that host, and `emqx ctl` cannot reach the node
# when it does not resolve (e.g. a name kept from before a hostname change).
# With host networking 127.0.0.1 is the Home Assistant host itself.
# ------------------------------------------------------------------------------
woow_emqx::map_node_host() {
    local name="${1}"
    local hosts_file="${2:-${WOOW_EMQX_HOSTS_FILE:-/etc/hosts}}"
    local host

    [[ "${name}" == *@* ]] || return 0
    host="${name#*@}"

    # An IPv4 literal needs no mapping
    [[ "${host}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] && return 0
    # Only plain hostnames go into the hosts file
    [[ "${host}" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || return 0

    if awk -v h="${host}" '
        $1 !~ /^#/ { for (i = 2; i <= NF; i++) if ($i == h) found = 1 }
        END { exit found ? 0 : 1 }' "${hosts_file}" 2>/dev/null; then
        return 0
    fi

    printf '127.0.0.1\t%s\n' "${host}" >> "${hosts_file}"
}
