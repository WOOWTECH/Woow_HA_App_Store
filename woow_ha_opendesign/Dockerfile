ARG BUILD_FROM=ghcr.io/nexu-io/od:0.21.1@sha256:441daca881e699657bacf28e0c27b16cd6be551dfff4bd63368dd74bec581f39
FROM ${BUILD_FROM}

USER root

ENV NODE_ENV=production \
    OD_BIND_HOST=127.0.0.1 \
    OD_PORT=7456 \
    OD_DATA_DIR=/data/opendesign \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser \
    HOME=/data/opendesign/home

# The browser comes from Alpine rather than being downloaded on first boot.
# playwright-core is locked independently in /opt/ha-opendesign/package-lock.json.
RUN apk add --no-cache \
      bash \
      chromium \
      font-noto-cjk \
      font-noto-emoji \
      fontconfig \
      nginx \
      su-exec \
    && rm -rf /etc/nginx/http.d/* /var/cache/apk/*

COPY runtime/package.json runtime/package-lock.json /opt/ha-opendesign/
COPY runtime/pi/package.json runtime/pi/package-lock.json /opt/ha-opendesign/pi/
# Home Assistant Supervisor's BuildKit builder may supply a reduced PATH even
# though the pinned upstream image installs Node/npm under /usr/local/bin.
# Use the absolute npm path so local Supervisor builds match ordinary Docker.
RUN /usr/local/bin/npm ci --omit=dev --prefix /opt/ha-opendesign \
    && /usr/local/bin/npm ci --omit=dev --prefix /opt/ha-opendesign/pi \
    && test "$(/opt/ha-opendesign/pi/node_modules/.bin/pi --version)" = "0.84.4" \
    && /usr/local/bin/npm cache clean --force \
    && test "$(id -u open-design)" = "1001" \
    && test -x /usr/local/bin/node \
    && test -x /usr/local/bin/npm \
    && command -v bash \
    && command -v chromium-browser \
    && command -v nginx \
    && command -v su-exec

COPY rootfs/ /
RUN mkdir -p /data/opendesign \
    && chown -R open-design:open-design /data \
    && chmod 0755 \
      /usr/local/bin/ha-opendesign \
      /usr/local/bin/pi \
      /opt/ha-opendesign/ha-pi-wrapper.mjs \
      /opt/ha-opendesign/ha-byok-store.mjs \
      /opt/ha-opendesign/headless-entry.mjs \
      /opt/ha-opendesign/headless-renderer.mjs \
    && chown -R open-design:open-design /opt/ha-opendesign

ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=0.1.0
ARG BUILD_DATE
ARG BUILD_DESCRIPTION="OpenDesign for Home Assistant"
ARG BUILD_NAME="Woow HA OpenDesign"
ARG BUILD_REF
ARG BUILD_REPOSITORY=WOOWTECH/Woow_ha_opendesign_add_on

LABEL io.hass.name="${BUILD_NAME}" \
      io.hass.description="${BUILD_DESCRIPTION}" \
      io.hass.arch="${BUILD_ARCH}" \
      io.hass.type="addon" \
      io.hass.version="${BUILD_VERSION}" \
      org.opencontainers.image.title="${BUILD_NAME}" \
      org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
      org.opencontainers.image.vendor="WOOWTECH" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${BUILD_REF}" \
      org.opencontainers.image.version="${BUILD_VERSION}"

# HA mounts /data at runtime as root. PID 1 starts as root only long enough to
# create/chown owned directories; the launcher drops both application processes
# to the upstream open-design UID/GID 1001 with su-exec.
USER root
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/ha-opendesign"]
