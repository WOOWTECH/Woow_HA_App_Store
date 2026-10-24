#!/command/with-contenv bashio
# shellcheck shell=bash
# ==============================================================================
# Home Assistant App (Add-on): Cloudflared
# Runs the Cloudflare Tunnel for Home Assistant
# ==============================================================================
declare config_file="/tmp/config.json"
declare certificate="/data/cert.pem"
declare -a options

# The unconfigured idle path exits before the normal mode branch below. A
# disconnect can therefore leave a still-valid token file behind unless it
# is removed before that early exit.
if ! bashio::config.has_value 'tunnel_token'; then
    rm -f "${CLOUDFLARED_TOKEN_FILE:-/data/tunnel-token}"
fi

# WOOWTECH Web GUI patch: when the add-on is completely unconfigured the
# prepare script skips the tunnel setup (instead of exiting fatally like
# upstream) so the Web GUI stays reachable for first-time setup. Idle here
# until the user saves a configuration and the add-on restarts.
if [ -f "${WEBGUI_UNCONFIGURED_MARKER:-/tmp/webgui-unconfigured}" ]; then
    bashio::log.notice "Add-on is not configured yet — tunnel not started."
    bashio::log.notice "Open the Web GUI (ingress panel) to configure it."
    exec sleep infinity
fi

# WOOWTECH Web GUI patch: the prepare step failed (see the error above in
# this log). Upstream would halt the whole container here; keep the Web GUI
# alive instead so the configuration can be fixed in the browser, and retry
# the setup periodically so transient failures (e.g. network not up yet
# after a host reboot) self-heal without manual intervention.
if [ -f /tmp/webgui-prepare-failed ]; then
    bashio::log.error "Tunnel setup failed — see the messages above."
    bashio::log.notice "Fix the configuration in the Web GUI (or the add-on configuration page) and restart the add-on."
    bashio::log.notice "The add-on retries the setup every 5 minutes automatically, so transient errors self-heal."
    while [ -f /tmp/webgui-prepare-failed ]; do
        sleep 300
        bashio::log.info "Retrying tunnel setup..."
        if /etc/s6-overlay/s6-rc.d/prepare/run.sh; then
            rm -f /tmp/webgui-prepare-failed
        else
            bashio::log.warning "Tunnel setup retry failed; next retry in 5 minutes."
        fi
    done
    bashio::log.info "Tunnel setup succeeded on retry — starting the tunnel."
fi

# Set common cloudflared tunnel options
options+=(--no-autoupdate)
options+=(--metrics="127.0.0.1:36500")

# Check for post_quantum option
if bashio::config.true 'post_quantum'; then
    bashio::log.trace "bashio::config.true 'post_quantum'"
    options+=(--post-quantum)
fi

# Check for additional run parameters
if bashio::config.has_value 'run_parameters'; then
    bashio::log.trace "bashio::config.has_value 'run_parameters'"
    for run_parameter in $(bashio::config 'run_parameters'); do
        case "${run_parameter}" in
            --token|--token=*|--token-file|--token-file=*|--metrics|--metrics=*)
                bashio::log.error "Tunnel credentials and metrics listener cannot be overridden through run_parameters."
                exit 1
                ;;
        esac
        options+=("${run_parameter}")
    done
fi

# Check if we run local or remote managed tunnel and set related options
if bashio::config.has_value 'tunnel_token'; then
    bashio::log.trace "bashio::config.has_value 'tunnel_token'"
    # A command-line --token is visible in process listings, and the full
    # options array may be logged. Persist only the file path in argv.
    token_file="${CLOUDFLARED_TOKEN_FILE:-/data/tunnel-token}"
    umask 077
    temporary_token_file="$(mktemp "${token_file}.XXXXXX")"
    printf '%s' "$(bashio::config 'tunnel_token')" > "${temporary_token_file}"
    chmod 600 "${temporary_token_file}"
    mv -f "${temporary_token_file}" "${token_file}"
    options+=(run --token-file="${token_file}")
else
    rm -f "${CLOUDFLARED_TOKEN_FILE:-/data/tunnel-token}"
    bashio::log.debug "using ${config_file} config file"
    options+=(--origincert="${certificate}")
    options+=(--config="${config_file}")
    options+=(run "$(bashio::config 'tunnel_name')")
fi

bashio::log.info "Connecting Cloudflare Tunnel..."
bashio::log.debug "Starting cloudflared tunnel (arguments omitted from logs)"
exec cloudflared tunnel "${options[@]}"
