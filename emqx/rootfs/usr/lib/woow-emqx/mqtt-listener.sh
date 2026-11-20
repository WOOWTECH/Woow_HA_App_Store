# shellcheck shell=bash
# ==============================================================================
# Woow EMQX: where the MQTT TCP listener listens
#
# Sourced by the ngrok service. The listener is EMQX's default TCP listener;
# env_vars may move it with EMQX_LISTENERS__TCP__DEFAULT__BIND (for example so
# that it runs next to the Mosquitto add-on, which keeps 1883).
# ==============================================================================

readonly WOOW_EMQX_DEFAULT_MQTT_PORT=1883

# The value of EMQX_LISTENERS__TCP__DEFAULT__BIND in env_vars, or nothing.
# The service script exports env_vars in order, so the last entry wins.
woow_emqx::tcp_bind_from_options() {
    local bind='' var name
    for var in $(bashio::config 'env_vars|keys'); do
        name=$(bashio::config "env_vars[${var}].name")
        if [[ "${name}" == 'EMQX_LISTENERS__TCP__DEFAULT__BIND' ]]; then
            bind=$(bashio::config "env_vars[${var}].value")
        fi
    done
    echo "${bind}"
}

# Turn an EMQX `bind` value into the address ngrok should forward to.
# Accepts what EMQX accepts: "1885", ":1885", "0.0.0.0:1885",
# "192.168.1.5:1885", "[::]:1885", "::1:1885" (optionally HOCON-quoted).
# An empty value is EMQX's default, 1883. A wildcard host (0.0.0.0, ::, none)
# prints only the port, which ngrok forwards to localhost; any other host is
# printed as host:port. Returns 1 when the value has no valid port.
woow_emqx::ngrok_target() {
    local bind="${1//[[:space:]]/}" host port
    bind="${bind#\"}"
    bind="${bind%\"}"
    if [[ -z "${bind}" ]]; then
        echo "${WOOW_EMQX_DEFAULT_MQTT_PORT}"
        return 0
    fi
    if [[ "${bind}" == *:* ]]; then
        host="${bind%:*}"
        port="${bind##*:}"
    else
        host=''
        port="${bind}"
    fi
    if ! [[ "${port}" =~ ^[0-9]+$ ]] || (( 10#${port} < 1 || 10#${port} > 65535 )); then
        return 1
    fi
    port=$((10#${port}))
    host="${host#[}"
    host="${host%]}"
    case "${host}" in
        '' | 0.0.0.0 | :: )
            echo "${port}" ;;
        *:*)
            echo "[${host}]:${port}" ;;
        *)
            echo "${host}:${port}" ;;
    esac
}
