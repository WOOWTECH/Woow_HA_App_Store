# Woow Omnigent HAOS add-on image.
#
# What's inside:
#   - omnigent==0.21.0            (upstream orchestration server)
#   - Postgres 16                 (bundled — no MariaDB add-on dependency)
#   - nginx                       (HA Ingress path rewriter for the React SPA)
#   - s6-overlay v3.2.1.0         (supervises the three long-lived processes)
#   - bashio v0.17.5              (options.json → env in init scripts)
#
# What's NOT inside (by design — Option 3 in the design doc):
#   - No pi CLI      — external runners bring their own pi + auth
#   - No claude/codex CLI
#   - No omnigent runner    — external hosts register via
#                             `omnigent host --server http://this-addon:8000`
#
# Sizing target: <400 MB compressed.

# Base image is per-arch and pinned in the CI matrix via --build-arg.
# The `base/{arch}` naming matches upstream hassio-addons/addon-base packages
# (e.g. ghcr.io/hassio-addons/base/amd64:20.2.0). The default here is just a
# fallback for local `docker build` on amd64 — CI always overrides it.
ARG BUILD_FROM=ghcr.io/hassio-addons/base/amd64:20.2.0
FROM ${BUILD_FROM}

ARG BUILD_ARCH=amd64
ARG BUILD_VERSION
ARG BUILD_DATE

ARG OMNIGENT_VERSION=0.21.0
# Alpine 3.24 同時提供 postgresql16 與 postgresql17。固定用 16，和其他
# Omnigent 部署的 Postgres major version 一致（日後搬資料庫時，備份與
# WAL 可以互通）。
ARG POSTGRES_VERSION=16

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Taipei \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    HOME=/data/omnigent-home \
    ARTIFACT_DIR=/data/artifacts \
    OMNIGENT_ADMIN_CREDENTIALS_PATH=/data/admin-credentials \
    PGDATA=/data/postgres

# --- System packages ---------------------------------------------------------
# python3 + pip for omnigent, postgresql for the bundled DB, nginx for the
# HA Ingress reverse proxy, curl + jq for the setup-admin curl loop, tini
# via s6-overlay for zombie reaping. The base image already ships bashio.
RUN apk add --no-cache \
        bash \
        ca-certificates \
        curl \
        jq \
        nginx \
        postgresql${POSTGRES_VERSION} \
        postgresql${POSTGRES_VERSION}-client \
        postgresql${POSTGRES_VERSION}-contrib \
        python3 \
        py3-pip \
        py3-psycopg \
        tzdata

# --- omnigent (upstream Python package) --------------------------------------
# The pypi package pulls a lot of psycopg / grpc / uvicorn wheels — no
# compilers needed; all published as cp3xx manylinux wheels.
# rm -rf ~/.omnigent because `omnigent --version` at build time
# initialises $HOME/.omnigent/logs as root uid 0, which will collide with
# the addon's runtime uid mapping. Clean slate on first run.
# google-re2 is a transitive dep of cel-python (via omnigent) and ships
# no musllinux wheel — it must build from source, which needs g++ + make.
# We install a throwaway .build-deps group so the runtime image stays lean.
# Do NOT trail with `|| true` — a silent pip failure is what shipped 0.1.5
# without the omnigent binary and burnt half an afternoon of debugging.
# google-re2 wheel build needs g++ (build-base) + abseil headers.
# The other -dev packages were belt-and-braces but they trigger apk
# version-pinning conflicts on base 20.2.0 (openssl-dev wants
# libcrypto3-3.5.8 but world pins 3.5.6). Everything else in
# omnigent's dep tree ships musllinux wheels.
# Base 20.2.0 pins musl=1.2.5-r23 in /etc/apk/world while Alpine now ships
# musl-dev 1.2.5-r24 only, so build-base cannot be selected. Re-adding musl
# without the pin upgrades it to the repository's release first.
RUN apk add --no-cache --upgrade musl \
 && apk add --no-cache --virtual .build-deps \
        build-base \
        abseil-cpp-dev \
        re2-dev \
 && pip3 install --no-cache-dir "omnigent==${OMNIGENT_VERSION}" \
 && omnigent --version \
 && which omnigent \
 && apk del .build-deps
RUN rm -rf /root/.omnigent /data/omnigent-home/.omnigent 2>/dev/null || true

# --- HA Ingress native base-path support ------------------------------------
# Omnigent 0.21.0 reads window.__OMNIGENT_BASE_PATH__ for API, WebSocket,
# navigation and auth redirects. The nginx HTML injection supplies it from
# Supervisor's validated X-Ingress-Path. Fail the build if upstream removes
# this contract, so a new version cannot silently break the HA panel.
RUN grep -R -q '__OMNIGENT_BASE_PATH__' \
        /usr/lib/python3.12/site-packages/omnigent/server/static/web-ui/assets/

# --- Rootfs overlay: s6 services + nginx config + init scripts ---------------
COPY rootfs/ /

# Marks all our copied `run` / `up` / `type` files executable & consistent.
RUN chmod +x \
        /etc/s6-overlay/s6-rc.d/init-addon-config/run \
        /etc/s6-overlay/s6-rc.d/init-postgres/run \
        /etc/s6-overlay/s6-rc.d/svc-postgres/run \
        /etc/s6-overlay/s6-rc.d/init-omnigent-config/run \
        /etc/s6-overlay/s6-rc.d/svc-omnigent-server/run \
        /etc/s6-overlay/s6-rc.d/init-admin-claim/run \
        /etc/s6-overlay/s6-rc.d/nginx/run \
 && chmod 0755 /etc/s6-overlay/s6-rc.d/*/type \
        /etc/s6-overlay/s6-rc.d/*/up 2>/dev/null || true

# HA add-on base image already sets `ENTRYPOINT ["/init"]` from s6-overlay.

# --- Labels ------------------------------------------------------------------
LABEL \
    io.hass.name="Woow Omnigent" \
    io.hass.description="Omnigent 0.21.0 orchestration server for HAOS" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    maintainer="WOOWTECH <woowtech@designsmart.com.tw>" \
    org.opencontainers.image.title="Woow HA Omnigent" \
    org.opencontainers.image.description="Omnigent 0.21.0 orchestration server bundled as a HAOS add-on" \
    org.opencontainers.image.source="https://github.com/WOOWTECH/Woow_ha_omnigent_addon" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.version="${BUILD_VERSION}" \
    org.opencontainers.image.created="${BUILD_DATE}"
