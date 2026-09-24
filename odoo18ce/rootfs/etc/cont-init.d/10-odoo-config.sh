#!/usr/bin/with-contenv bashio
# ==============================================================================
# 10-odoo-config.sh
# Read HA options → generate /data/odoo.conf
# ==============================================================================
set -e
umask 077

declare CONF="/data/odoo.conf"
declare DATA_DIR="/data/odoo"
declare LOG_DIR="/data/odoo/logs"
declare FILESTORE_DIR="/data/odoo/filestore"

# ---------- 1. Create directories ----------
mkdir -p "${FILESTORE_DIR}" "${LOG_DIR}" /data/addons /share/odoo_addons
chown -R odoo:odoo "${DATA_DIR}" /data/addons /share/odoo_addons

# ---------- 2. Read options ----------
ADMIN_PASSWD=$(bashio::config 'admin_passwd')
DB_PASSWORD=$(bashio::config 'db_password')

# System
TZ=$(bashio::config 'TZ')
TZ="${TZ:-Asia/Taipei}"

# Performance
WORKERS=$(bashio::config 'workers')
WORKERS="${WORKERS:-0}"

MAX_CRON=$(bashio::config 'max_cron_threads')
MAX_CRON="${MAX_CRON:-1}"

MEM_HARD=$(bashio::config 'limit_memory_hard')
MEM_HARD="${MEM_HARD:-2684354560}"

MEM_SOFT=$(bashio::config 'limit_memory_soft')
MEM_SOFT="${MEM_SOFT:-2147483648}"

TIME_CPU=$(bashio::config 'limit_time_cpu')
TIME_CPU="${TIME_CPU:-60}"

TIME_REAL=$(bashio::config 'limit_time_real')
TIME_REAL="${TIME_REAL:-120}"

# Network: Odoo is bound to localhost and only the bundled nginx gateways
# can reach it, so proxy_mode is always True in the rendered config below.

# Database
LIST_DB=$(bashio::config 'list_db')
LIST_DB="${LIST_DB:-true}"

# Modules
WITHOUT_DEMO=$(bashio::config 'without_demo')
WITHOUT_DEMO="${WITHOUT_DEMO:-true}"

EXTRA_ADDONS=$(bashio::config 'odoo_extra_addons')
EXTRA_ADDONS="${EXTRA_ADDONS:-}"

# Developer
DEV_MODE=$(bashio::config 'dev_mode')
DEV_MODE="${DEV_MODE:-false}"

LOG_LEVEL=$(bashio::config 'log_level')
LOG_LEVEL="${LOG_LEVEL:-info}"

# Map boolean to Odoo config values
if bashio::var.true "${LIST_DB}"; then LIST_DB_VAL="True"; else LIST_DB_VAL="False"; fi
if bashio::var.true "${WITHOUT_DEMO}"; then WITHOUT_DEMO_VAL="all"; else WITHOUT_DEMO_VAL="False"; fi

# ---------- 3. Build addons_path ----------
# /opt/woow-server-addons carries the add-on's own server-wide module and
# has to be on the path for the server_wide_modules line below to import.
BASE_ADDONS="/usr/lib/python3/dist-packages/odoo/addons,/data/addons,/share/odoo_addons,/opt/woow-addons/addons,/opt/woow-server-addons"
if [ -n "${EXTRA_ADDONS}" ]; then
    ADDONS_PATH="${EXTRA_ADDONS},${BASE_ADDONS}"
else
    ADDONS_PATH="${BASE_ADDONS}"
fi

# Ensure all addons directories exist
IFS=',' read -ra ADDON_DIRS <<< "${ADDONS_PATH}"
for dir in "${ADDON_DIRS[@]}"; do
    dir=$(echo "${dir}" | xargs)  # trim whitespace
    if [ -n "${dir}" ] && [ ! -d "${dir}" ]; then
        mkdir -p "${dir}"
        chown odoo:odoo "${dir}"
    fi
done

# ---------- 4. Generate odoo.conf ----------
bashio::log.info "Generating ${CONF}..."

cat > "${CONF}" <<EOF
[options]
; --- Core ---
admin_passwd = ${ADMIN_PASSWD}
db_host = 127.0.0.1
db_port = 5432
db_user = odoo
db_password = ${DB_PASSWORD}
data_dir = ${DATA_DIR}

; --- Addons ---
addons_path = ${ADDONS_PATH}

; Odoo guesses web.base.url from the request an administrator logged in
; from whenever web.base.url.freeze is unset, which is the state of every
; database created between two starts. woow_base_url_guard removes that
; guess in every process, so the maintenance bootstrap stays the only
; writer of the Canonical URL. base and web are Odoo's own defaults and
; have to be repeated because naming this option replaces them.
server_wide_modules = base,web,woow_base_url_guard

; --- Logging ---
logfile = ${LOG_DIR}/odoo-server.log
log_level = ${LOG_LEVEL}

; --- Network ---
proxy_mode = True
http_interface = 127.0.0.1
http_port = 8070
workers = ${WORKERS}
list_db = ${LIST_DB_VAL}
without_demo = ${WITHOUT_DEMO_VAL}

; --- Resource Limits ---
max_cron_threads = ${MAX_CRON}
limit_memory_hard = ${MEM_HARD}
limit_memory_soft = ${MEM_SOFT}
limit_time_cpu = ${TIME_CPU}
limit_time_real = ${TIME_REAL}
EOF

# WebSocket upstream. Odoo binds every listener to http_interface, which is
# loopback, so the gevent worker can never answer the published 8072 host
# port itself. Keep it on an internal port and let nginx own 8072, so the
# same origin gate applies there as on 8069.
if [ "${WORKERS}" -gt 0 ]; then
    echo "gevent_port = 8073" >> "${CONF}"
    WS_PORT=8073
else
    WS_PORT=8070
fi

# Render the dual nginx gateway.
#
# The 8069 origin listener serves two callers and gives them different
# privileges. A LAN caller -- matched on source address, which Docker
# preserves on the published host port -- gets the full application including
# the database manager. The Cloudflare tunnel always arrives from inside the
# add-on network, so it never matches the LAN list and stays on the
# restricted tier behind its expected Host header.
PUBLIC_PROTO='https'
PUBLIC_HOST_MAP=''
DENY_STATUS='503'
PUBLIC_URL=''
if bashio::config.has_value 'public_url'; then
    PUBLIC_URL="$(bashio::config 'public_url')"
    PUBLIC_PROTO="${PUBLIC_URL%%://*}"
    if [ "${PUBLIC_PROTO}" != "https" ]; then
        bashio::log.error "public_url must use https"
        exit 1
    fi
    PUBLIC_HOST="${PUBLIC_URL#*://}"
    PUBLIC_HOST="${PUBLIC_HOST%%/*}"
    # An off-LAN caller is only recognised when it presents this exact Host.
    PUBLIC_HOST_MAP="\"${PUBLIC_HOST}\" 1; \"${PUBLIC_HOST}:443\" 1;"
    DENY_STATUS='444'
fi

# LAN allow-list for the 8069 origin. Every entry is validated as an IPv4
# CIDR before it reaches the nginx geo block, so a malformed option fails the
# start-up instead of injecting a directive. nginx statements are terminated
# by ';' rather than by newlines, so one rendered line is valid config.
LAN_NETWORKS="$(bashio::config 'lan_networks' 2>/dev/null || true)"
# IPv4 private ranges only. IPv6 clients therefore fall through to the
# deny tier unless an operator adds their own prefix, which keeps the
# default fail-closed on a dual-stack LAN.
if [ -z "${LAN_NETWORKS}" ]; then
    LAN_NETWORKS='192.168.0.0/16 10.0.0.0/8 172.16.0.0/12'
fi
LAN_GEO=''
for LAN_CIDR in ${LAN_NETWORKS}; do
    if ! echo "${LAN_CIDR}" | grep -Eq '^([0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}|[0-9A-Fa-f:]+/[0-9]{1,3})$'; then
        bashio::log.error "lan_networks entry is not an IPv4/IPv6 CIDR: ${LAN_CIDR}"
        exit 1
    fi
    LAN_GEO="${LAN_GEO}${LAN_CIDR} 1; "
done
bashio::log.info "8069 origin: LAN tier = ${LAN_NETWORKS}"

# Canonical URL for the Runtime shim (issue #70).
#
# Odoo 18 builds some outbound links in the browser, from the address in the
# address bar: the Discuss invitation link is `window.location.origin` joined
# to `/chat/<id>/<uuid>`, and `@web/core/utils/urls` falls back to the browser
# protocol and host because Odoo 18 session info carries no origin. Through
# Ingress that address is the Home Assistant host, so the link is useless to
# the person it is sent to, and the lock the maintenance bootstrap puts on
# web.base.url cannot reach it: the value never passes through the server.
# The Runtime shim publishes the Canonical URL to the page instead, so a
# Literal rewrite can use it as the base of one exact expression at a time.
#
# The rule that chooses the value exists once, in canonical_url() in the
# maintenance library. The bootstrap calls it later, in services.d, for
# web.base.url; this step calls the same function through
# /usr/local/bin/odoo-canonical-url with the same three inputs. Neither side
# derives the value on its own.
#
# Without public_url the value is the host's LAN address with the published
# Odoo port, both read from the Supervisor (needs hassio_api). When the
# Supervisor reports no address there is no Canonical URL, the shim publishes
# an empty string, and every rewrite keeps the browser origin it uses today.
#
# Both are read through the shared helper (issue #108): the Supervisor can
# answer empty for a moment at boot, bashio caches that answer, and one read
# used to make it the whole start. The helper waits, and publishes what it
# settled on for the maintenance bootstrap, so both sides see one address
# and one port per start (ADR 0006) and the bootstrap never asks on its own.
# shellcheck disable=SC1091
if ! . "${WOOW_LIB_DIR:-/usr/local/lib}/supervisor-read.sh"; then
    bashio::log.error "supervisor-read.sh could not be loaded"
    exit 1
fi
CANONICAL_LAN_IPV4=''
CANONICAL_PORT=''
if [ -z "${PUBLIC_URL}" ]; then
    woow::supervisor.settle_canonical_inputs || true
    CANONICAL_LAN_IPV4="${WOOW_LAN_IPV4}"
    CANONICAL_PORT="${WOOW_LAN_PORT}"
fi
# A missing or broken helper costs the shim its value; it never costs the
# operator the add-on, so `set -e` is kept away from this one command.
CANONICAL_URL=''
if ! CANONICAL_URL="$(
    ODOO_MAINT_PUBLIC_URL="${PUBLIC_URL}" \
    ODOO_MAINT_LAN_IPV4="${CANONICAL_LAN_IPV4}" \
    ODOO_MAINT_PORT="${CANONICAL_PORT}" \
    /usr/local/bin/odoo-canonical-url
)"; then
    bashio::log.warning "odoo-canonical-url failed; the Runtime shim publishes no Canonical URL"
    CANONICAL_URL=''
fi
# The value is rendered into a JavaScript string literal that sits inside an
# nginx quoted parameter. Only a bare http(s) origin may reach either, so a
# value of any other shape is dropped rather than escaped; the shim then
# publishes an empty string and nothing changes.
if [ -n "${CANONICAL_URL}" ] \
    && ! echo "${CANONICAL_URL}" | grep -Eq '^https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?$'; then
    bashio::log.warning "Canonical URL is not a bare origin; the Runtime shim will not publish it"
    CANONICAL_URL=''
fi
if [ -n "${CANONICAL_URL}" ]; then
    bashio::log.info "Runtime shim Canonical URL = ${CANONICAL_URL}"
else
    bashio::log.warning "No Canonical URL; links the browser builds keep the browser origin"
fi

ADDON_VERSION="$(bashio::addon.version 2>/dev/null || echo unknown)"
sed -e "s/%%WS_PORT%%/${WS_PORT}/g" \
    -e "s#%%CANONICAL_URL%%#${CANONICAL_URL}#g" \
    -e "s#%%PUBLIC_PROTO%%#${PUBLIC_PROTO}#g" \
    -e "s#%%PUBLIC_HOST_MAP%%#${PUBLIC_HOST_MAP}#g" \
    -e "s#%%DENY_STATUS%%#${DENY_STATUS}#g" \
    -e "s#%%LAN_NETWORKS%%#${LAN_GEO}#g" \
    -e "s#%%INGRESS_CACHE_VERSION%%#${ADDON_VERSION}#g" \
    /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

# Generated rewrites (ADR 0005). The Ingress asset location includes this
# file unconditionally, so nginx refuses to start while it is missing. Create
# it empty on a fresh install; an existing one is the last good generation
# the running add-on wrote, so it is never overwritten here.
declare GENERATED_REWRITES="/data/nginx-generated-rewrites.conf"
if [ ! -e "${GENERATED_REWRITES}" ]; then
    bashio::log.info "Creating empty ${GENERATED_REWRITES}"
    : > "${GENERATED_REWRITES}"
    # umask 077 above would otherwise leave it readable to root only.
    chmod 0644 "${GENERATED_REWRITES}"
fi

# default_db → db_name
if bashio::config.has_value 'default_db'; then
    DEFAULT_DB=$(bashio::config 'default_db')
    echo "db_name = ${DEFAULT_DB}" >> "${CONF}"
fi

# dev_mode
if bashio::var.true "${DEV_MODE}"; then
    echo "dev_mode = all" >> "${CONF}"
fi

# ---------- 5. SMTP (only if smtp_server is set) ----------
if bashio::config.has_value 'smtp_server'; then
    SMTP_SERVER=$(bashio::config 'smtp_server')

    SMTP_PORT=$(bashio::config 'smtp_port')
    SMTP_PORT="${SMTP_PORT:-465}"

    SMTP_SSL=$(bashio::config 'smtp_ssl')
    SMTP_SSL="${SMTP_SSL:-true}"

    if bashio::var.true "${SMTP_SSL}"; then SMTP_SSL_VAL="True"; else SMTP_SSL_VAL="False"; fi

    cat >> "${CONF}" <<EOF

; --- SMTP ---
smtp_server = ${SMTP_SERVER}
smtp_port = ${SMTP_PORT}
smtp_ssl = ${SMTP_SSL_VAL}
EOF

    if bashio::config.has_value 'email_from'; then
        echo "email_from = $(bashio::config 'email_from')" >> "${CONF}"
    fi
    if bashio::config.has_value 'smtp_user'; then
        echo "smtp_user = $(bashio::config 'smtp_user')" >> "${CONF}"
    fi
    if bashio::config.has_value 'smtp_password'; then
        echo "smtp_password = $(bashio::config 'smtp_password')" >> "${CONF}"
    fi
fi

# ---------- 6. Permissions ----------
chown odoo:odoo "${CONF}"
chmod 0600 "${CONF}"

bashio::log.info "Odoo config written to ${CONF}"
