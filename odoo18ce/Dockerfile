ARG BUILD_FROM
FROM ${BUILD_FROM}

# ──────────────────────────────────────────────
# 1. Add PostgreSQL 16 APT repository
# ──────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gnupg2 curl ca-certificates lsb-release \
    && echo "deb http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg

# ──────────────────────────────────────────────
# 2. Add Odoo 18 nightly APT repository
# ──────────────────────────────────────────────
RUN echo "deb http://nightly.odoo.com/18.0/nightly/deb/ ./" \
        > /etc/apt/sources.list.d/odoo.list \
    && curl -fsSL https://nightly.odoo.com/odoo.key \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/odoo.gpg

# ──────────────────────────────────────────────
# 3. Install PostgreSQL 16, then Odoo 18
#    --no-install-recommends on odoo prevents
#    pulling a different PG version
# ──────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y \
        postgresql-16 \
        postgresql-client-16 \
    && apt-get install -y --no-install-recommends \
        odoo \
        fonts-noto-cjk \
        wkhtmltopdf \
        jq \
        git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ──────────────────────────────────────────────
# 4. Clone WOOWTECH odoo-addons (main, shallow)
# ──────────────────────────────────────────────
RUN git clone --depth 1 --branch main \
        https://github.com/WOOWTECH/odoo-addons.git \
        /opt/woow-addons

# ──────────────────────────────────────────────
# 5. Copy rootfs overlay
# ──────────────────────────────────────────────
COPY rootfs/ /

# ──────────────────────────────────────────────
# 6. Set script permissions
# ──────────────────────────────────────────────
RUN chmod a+rx /etc/cont-init.d/*.sh \
    && chmod a+rx /etc/services.d/*/run \
    && chmod a+rx /etc/services.d/*/finish

EXPOSE 8069 8072
