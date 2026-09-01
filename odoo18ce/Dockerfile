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
# 2. Install PostgreSQL 16 and pin the exact Odoo build already deployed.
#    Ingress changes must not silently upgrade a nightly Odoo package and
#    trigger an unrelated database migration.
# ──────────────────────────────────────────────
ARG ODOO_DEB_VERSION="18.0.20260806"
ARG ODOO_DEB_SHA256="60def7fca9f7005be9575f70f17e7db4e4e43190b36d0f34832fb0248beb6ba5"
RUN apt-get update \
    && apt-get install -y \
        postgresql-16 \
        postgresql-client-16 \
    && curl -fsSL \
        "https://nightly.odoo.com/18.0/nightly/deb/odoo_${ODOO_DEB_VERSION}_all.deb" \
        -o /tmp/odoo.deb \
    && echo "${ODOO_DEB_SHA256}  /tmp/odoo.deb" | sha256sum -c - \
    && apt-get install -y --no-install-recommends \
        /tmp/odoo.deb \
        fonts-noto-cjk \
        wkhtmltopdf \
        jq \
        git \
        nginx \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/odoo.deb

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
    && chmod a+rx /etc/services.d/*/finish \
    && chmod a+rx /usr/local/bin/odoo-maintenance-bootstrap

EXPOSE 8069 5691 8072
