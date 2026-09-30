# The base image is pinned here, not in a build.yaml: Supervisor has
# deprecated that file and passes a modernized build only BUILD_ARCH
# (issues #110, #124). The tag is one dated Debian base tag for every
# architecture. BUILD_ARCH has no default on purpose: Supervisor, CI and
# the publish action all pass it, and a bare `docker build` that forgot
# it fails on the image reference instead of quietly building amd64 on an
# arm64 host. The weekly odoo-bump rewrites the BASE_IMAGE_TAG line the
# way it rewrites ODOO_DEB_VERSION below; keep both lines in this shape.
ARG BUILD_ARCH
ARG BASE_IMAGE_TAG="bookworm-2026.08.0"
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:${BASE_IMAGE_TAG}

# Every RUN below pipes curl into another tool; without pipefail a failed
# download would be masked by the consumer exiting 0.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ──────────────────────────────────────────────
# 1. Add PostgreSQL 16 APT repository
# ──────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gnupg2 curl ca-certificates \
    && echo "deb http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg \
    && rm -rf /var/lib/apt/lists/*

# ──────────────────────────────────────────────
# 2. Layer (a): the stable packages.
#
#    PostgreSQL 16, the fonts and tools the add-on needs, and the packages
#    the pinned Odoo `.deb` depends on. That dependency list lives in
#    `odoo-deb-depends.txt` beside this file, and the guard test
#    (tests/test_dockerfile_layers.py) keeps it equal to the list below.
#    Installing Odoo's dependencies here and the `.deb` alone in (b) is what
#    stops an Odoo bump from re-sending this layer to every host: it is the
#    big one, about 480 MiB of packages, and Docker cannot resume a partial
#    layer (issue #153, ADR 0013).
#
#    Nothing that changes often belongs here, and nothing small: a small apt
#    addition goes in layer (c) below. LAYER_A_REFRESH is the one deliberate
#    way to rebuild this layer -- after a security notice for PostgreSQL or
#    for anything else named below, change the date in a pull request and
#    say in the CHANGELOG that the next update is a full download. It
#    reaches only what this RUN installs: a fix for the base image, or for
#    curl, gnupg2 and the libraries they bring in above (libssl3 among
#    them), arrives with a base-image bump instead. BuildKit puts every declared ARG
#    into the environment of the RUN steps below it, so the declaration
#    alone would do it; the echo spends one line to make that true of any
#    builder, and puts the date in the build log.
# ──────────────────────────────────────────────
ARG LAYER_A_REFRESH="2026-09-29"
RUN echo "layer (a) refreshed ${LAYER_A_REFRESH}" \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        adduser \
        fonts-dejavu-core \
        fonts-font-awesome \
        fonts-inconsolata \
        fonts-noto-cjk \
        fonts-roboto-unhinted \
        git \
        gsfonts \
        jq \
        libjs-underscore \
        lsb-base \
        nginx \
        postgresql-16 \
        postgresql-client-16 \
        python3 \
        python3-asn1crypto \
        python3-babel \
        python3-cbor2 \
        python3-chardet \
        python3-cryptography \
        python3-dateutil \
        python3-decorator \
        python3-docutils \
        python3-freezegun \
        python3-geoip2 \
        python3-gevent \
        python3-greenlet \
        python3-idna \
        python3-jinja2 \
        python3-libsass \
        python3-lxml \
        python3-markupsafe \
        python3-num2words \
        python3-ofxparse \
        python3-openpyxl \
        python3-openssl \
        python3-passlib \
        python3-pil \
        python3-polib \
        python3-psutil \
        python3-psycopg2 \
        python3-pypdf2 \
        python3-qrcode \
        python3-renderpm \
        python3-reportlab \
        python3-requests \
        python3-rjsmin \
        python3-serial \
        python3-stdnum \
        python3-tz \
        python3-urllib3 \
        python3-usb \
        python3-vobject \
        python3-werkzeug \
        python3-xlrd \
        python3-xlsxwriter \
        python3-xlwt \
        python3-zeep \
        wkhtmltopdf \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ──────────────────────────────────────────────
# 3. Layer (b): the Odoo package, alone.
#
#    Pinned to the exact build already deployed: Ingress changes must not
#    silently upgrade a nightly Odoo package and trigger an unrelated
#    database migration.
#
#    Both ARGs are declared here, below (a). BuildKit hands every in-scope
#    ARG to the RUN steps under it, so a bumped version would miss (a)'s
#    cache as well if these lines sat any higher. The weekly odoo-bump
#    rewrites both of them; keep them in this shape.
#
#    apt resolves the package's dependencies here as before. One that
#    `odoo-deb-depends.txt` missed is installed into this layer, where it
#    makes (b) bigger and never breaks the build.
# ──────────────────────────────────────────────
ARG ODOO_DEB_VERSION="18.0.20260914"
ARG ODOO_DEB_SHA256="378a53702f9971722260d1182bfb7dd650e9c3b859f92b1c0d520a222e1bc3dd"
RUN apt-get update \
    && curl -fsSL \
        "https://nightly.odoo.com/18.0/nightly/deb/odoo_${ODOO_DEB_VERSION}_all.deb" \
        -o /tmp/odoo.deb \
    && echo "${ODOO_DEB_SHA256}  /tmp/odoo.deb" | sha256sum -c - \
    && apt-get install -y --no-install-recommends \
        /tmp/odoo.deb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/odoo.deb

# ──────────────────────────────────────────────
# 4. Layer (c): small apt additions.
#
#    Everything added after this layout was settled goes here, so that one
#    small package does not re-send (a) or (b) to every host (ADR 0013).
#    It is the last apt layer, not the last layer: the add-ons clone, the
#    rootfs overlay and the chmod step sit below it and are rebuilt with
#    it, about 33 MiB, almost all of it the clone. They belong below
#    because the rootfs changes on nearly every Release, and such a Release
#    must not re-run apt. The clone is down here with them by the layout
#    #154 settled, not because its ref moves.
#
#    python3-yaml is here for the Rewrite scan: the exception list shipped
#    in the image is YAML and still applies to Generated rewrites (ADR
#    0005), and the container had no YAML reader at all (ADR 0008). The
#    Debian package, not pip: nothing else in this image installs Python
#    from outside the distribution.
#
#    python3-pycryptodome is for WOOWTECH's ECPay e-invoice module
#    (ecpay_odoo18), which declares pycryptodomex and imports Cryptodome.
#    Debian ships exactly that: the package registers as pycryptodomex and
#    provides the Cryptodome namespace, so Odoo's dependency check passes
#    (issue #141).
# ──────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3-yaml \
        python3-pycryptodome \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ──────────────────────────────────────────────
# 5. Clone WOOWTECH odoo-addons (main, shallow)
# ──────────────────────────────────────────────
ARG WOOW_ADDONS_REF="51856b0abbce68848b2b024a00191cac5eeead3f"
RUN mkdir -p /opt/woow-addons \
    && git -C /opt/woow-addons init \
    && git -C /opt/woow-addons remote add origin \
        https://github.com/WOOWTECH/odoo-addons.git \
    && git -C /opt/woow-addons fetch --depth 1 origin "${WOOW_ADDONS_REF}" \
    && git -C /opt/woow-addons checkout --detach FETCH_HEAD \
    && rm -rf /opt/woow-addons/.git

# ──────────────────────────────────────────────
# 6. Copy rootfs overlay
# ──────────────────────────────────────────────
COPY rootfs/ /

# ──────────────────────────────────────────────
# 7. Set script permissions
# ──────────────────────────────────────────────
RUN chmod a+rx /etc/cont-init.d/*.sh \
    && chmod a+rx /etc/services.d/*/run \
    && chmod a+rx /etc/services.d/*/finish \
    && chmod a+rx /usr/local/bin/odoo-maintenance-bootstrap \
    && chmod a+rx /usr/local/bin/odoo-canonical-url \
    && chmod a+r /usr/local/lib/odoo-maintenance.py /usr/local/lib/odoo-maintenance-account.py \
    && chmod a+r /usr/local/lib/literal_rewrite_gate.py /usr/local/lib/literal_rewrite_exceptions.yaml \
    && chmod a+r /usr/local/lib/rewrite_scan.py /usr/local/lib/rewrite_apply.py \
    && chmod a+r /usr/local/lib/canonical_catchup.py \
    && chmod a+rx /usr/local/bin/odoo-canonical-catchup \
    && chmod a+r /usr/local/lib/self_check.py \
    && chmod a+r /usr/local/lib/supervisor-read.sh \
    && chmod a+rx /usr/local/bin/odoo-rewrite-scan \
    && chmod a+rx /usr/local/bin/odoo-rewrite-apply \
    && chmod a+rx /usr/local/bin/odoo-jsonrpc-filter \
    && chmod -R a+rX /opt/woow-server-addons

EXPOSE 8069 5691 8072

# Supervisor reads container health instead of polling from outside
# (the manifest `watchdog` key is obsolete). Loopback on 8069 is the LAN
# tier, so this exercises nginx and Odoo together. The start period covers
# first-boot database creation and a module update after an upgrade.
HEALTHCHECK --interval=60s --timeout=10s --start-period=600s --retries=3 \
    CMD ["curl", "-fsS", "--max-time", "8", "-o", "/dev/null", "http://127.0.0.1:8069/web/login"]

# ──────────────────────────────────────────────
# 8. Image labels. The publish workflow fills these in; a local or CI
#    build leaves all but io.hass.arch empty, which is harmless. BUILD_ARCH
#    is the one every build passes, because the FROM above needs it.
# ──────────────────────────────────────────────
ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION
LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="WoowTech" \
    org.opencontainers.image.licenses="LGPL-3.0-only" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/odoo18ce/DOCS.md" \
    org.opencontainers.image.created="${BUILD_DATE}" \
    org.opencontainers.image.revision="${BUILD_REF}" \
    org.opencontainers.image.version="${BUILD_VERSION}"
