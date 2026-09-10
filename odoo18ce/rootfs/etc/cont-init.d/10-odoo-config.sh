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
BASE_ADDONS="/usr/lib/python3/dist-packages/odoo/addons,/data/addons,/share/odoo_addons,/opt/woow-addons/addons"
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

ADDON_VERSION="$(bashio::addon.version 2>/dev/null || echo unknown)"
sed -e "s/%%WS_PORT%%/${WS_PORT}/g" \
    -e "s#%%PUBLIC_PROTO%%#${PUBLIC_PROTO}#g" \
    -e "s#%%PUBLIC_HOST_MAP%%#${PUBLIC_HOST_MAP}#g" \
    -e "s#%%DENY_STATUS%%#${DENY_STATUS}#g" \
    -e "s#%%LAN_NETWORKS%%#${LAN_GEO}#g" \
    -e "s#%%INGRESS_CACHE_VERSION%%#${ADDON_VERSION}#g" \
    /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

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
