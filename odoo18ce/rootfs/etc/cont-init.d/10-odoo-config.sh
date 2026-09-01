#!/usr/bin/with-contenv bashio
# ==============================================================================
# 10-odoo-config.sh
# Read HA options → generate /data/odoo.conf
# ==============================================================================
set -e

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
# can reach it, so forwarded headers are always safe to trust.
PROXY_MODE="true"

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
if bashio::var.true "${PROXY_MODE}"; then PROXY_MODE_VAL="True"; else PROXY_MODE_VAL="False"; fi
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

# Longpolling port (used when workers > 0)
if [ "${WORKERS}" -gt 0 ]; then
    echo "gevent_port = 8072" >> "${CONF}"
    WS_PORT=8072
else
    WS_PORT=8070
fi

# Render the dual nginx gateway. Public Cloudflare traffic uses :8069 while
# HA Supervisor Ingress uses :5691; both reach the same Odoo backend.
sed "s/%%WS_PORT%%/${WS_PORT}/g" \
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
