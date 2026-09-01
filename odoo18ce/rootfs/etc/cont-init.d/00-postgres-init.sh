#!/usr/bin/with-contenv bashio
# ==============================================================================
# 00-postgres-init.sh
# Initialize PostgreSQL 16 cluster, configure auth, sync password
# ==============================================================================
set -e

declare PG_DATA="/data/postgres"
declare PG_BIN="/usr/lib/postgresql/16/bin"
declare DB_PASSWORD

DB_PASSWORD=$(bashio::config 'db_password')

# Read timezone
TZ=$(bashio::config 'TZ')
TZ="${TZ:-Asia/Taipei}"

# ---------- 1. initdb if cluster does not exist ----------
if [ ! -f "${PG_DATA}/PG_VERSION" ]; then
    bashio::log.info "PostgreSQL cluster not found, initializing..."
    mkdir -p "${PG_DATA}"
    chown postgres:postgres "${PG_DATA}"
    chmod 0700 "${PG_DATA}"

    s6-setuidgid postgres \
        "${PG_BIN}/initdb" \
            --pgdata="${PG_DATA}" \
            --auth-local=peer \
            --encoding=UTF8 \
            --locale=C

    bashio::log.info "PostgreSQL cluster initialized at ${PG_DATA}"
fi

# ---------- 2. Write pg_hba.conf ----------
bashio::log.info "Writing pg_hba.conf..."
cat > "${PG_DATA}/pg_hba.conf" <<'EOF'
# TYPE  DATABASE  USER  ADDRESS        METHOD
local   all       all                  peer
host    all       all   127.0.0.1/32   scram-sha-256
EOF
chown postgres:postgres "${PG_DATA}/pg_hba.conf"

# ---------- 3. Write postgresql.conf override ----------
bashio::log.info "Writing postgresql.conf overrides..."
mkdir -p "${PG_DATA}/conf.d"
chown postgres:postgres "${PG_DATA}/conf.d"

cat > "${PG_DATA}/conf.d/ha-override.conf" <<EOF
listen_addresses = '127.0.0.1'
port = 5432
timezone = '${TZ}'
log_timezone = '${TZ}'
EOF
chown postgres:postgres "${PG_DATA}/conf.d/ha-override.conf"

if ! grep -q "include_dir = 'conf.d'" "${PG_DATA}/postgresql.conf"; then
    echo "include_dir = 'conf.d'" >> "${PG_DATA}/postgresql.conf"
fi

# ---------- 4. Start PG temporarily, create/update odoo role ----------
bashio::log.info "Starting PostgreSQL temporarily to sync role..."
s6-setuidgid postgres \
    "${PG_BIN}/pg_ctl" start \
        -D "${PG_DATA}" \
        -w -t 30 \
        -o "-c listen_addresses='' -c logging_collector=off"

# Escape single quotes in password for SQL safety
SAFE_PW="${DB_PASSWORD//\'/\'\'}"

# Use local socket connection (matched by 'local trust' in pg_hba.conf)
s6-setuidgid postgres psql -v ON_ERROR_STOP=1 <<EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'odoo') THEN
        CREATE ROLE odoo WITH LOGIN CREATEDB PASSWORD '${SAFE_PW}';
    ELSE
        ALTER ROLE odoo WITH PASSWORD '${SAFE_PW}';
    END IF;
END
\$\$;
EOSQL

bashio::log.info "PostgreSQL role 'odoo' synchronized"

# Stop temporary PG — the real one starts via services.d
s6-setuidgid postgres \
    "${PG_BIN}/pg_ctl" stop \
        -D "${PG_DATA}" \
        -m fast -w -t 30

bashio::log.info "PostgreSQL init complete"
