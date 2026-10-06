ARG BUILD_FROM=ghcr.io/hassio-addons/base:18.2.0
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

# Required for webpack config of NPM with Node.js 22
ENV NODE_OPTIONS="--openssl-legacy-provider"

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Copy patches
COPY patches/*.patch /usr/src/

ARG NGINX_PROXY_MANAGER_VERSION="v2.12.4"

# ── Stage 1: system packages ────────────────────────────────────────────
# Kept separate from the rest: this is the layer most likely to break when
# Alpine moves, and merging it into the build made failures undiagnosable.
#
# The `sed` on /etc/apk/world is load-bearing. Base images record the exact
# package builds present when they were made — e.g. `libssl3=3.5.4-r0` — as
# hard constraints in world. Alpine publishes new revisions continuously, so
# those pins go stale and then EVERY apk operation in the image fails to
# resolve, including installs unrelated to the pinned package. Stripping the
# constraints leaves the package NAMES, so world still describes what the
# image actually contains and nothing gets purged.
# hadolint ignore=DL3018
RUN \
    set -x \
    && sed -i 's/[<>=~].*$//' /etc/apk/world \
    && apk upgrade --no-cache libssl3 libcrypto3 \
    && apk add --no-cache --virtual .build-dependencies \
        build-base \
        git \
        libffi-dev \
        openssl-dev \
        patch \
        python3-dev \
    \
    && apk add --no-cache \
        apache2-utils \
        certbot \
        libcap \
        logrotate \
        nginx-mod-stream \
        nginx \
        nodejs \
        npm \
        openssl \
        py3-pip \
        python3 \
        yarn

# ── Stage 2: modclean (global yarn package) ─────────────────────────────
RUN \
    set -x \
    && yarn global add modclean

# ── Stage 3: fetch and patch upstream sources ──────────────────────────
# curl gets -f so an HTML 404 page is a hard failure here rather than a
# confusing tar error two commands later.
#
# The patch loop reports the failing FILE and patch's exit code before
# bailing. Without that, a failure reaches the log as a bare `exit 1` after
# the relevant "Applying ..." line has already scrolled out of the build
# output Supervisor keeps. --batch --forward stops patch prompting for input
# in a non-interactive build and makes an already-applied hunk a no-op.
RUN \
    set -x \
    && curl -fJ -L -o /tmp/nginxproxymanager.tar.gz \
        "https://github.com/NginxProxyManager/nginx-proxy-manager/archive/${NGINX_PROXY_MANAGER_VERSION}.tar.gz" \
    && mkdir /app \
    && tar zxf \
        /tmp/nginxproxymanager.tar.gz \
        --strip 1 -C /app \
    && for i in /usr/src/*.patch; do \
        echo "=== APPLYING $(basename "${i}")"; \
        if patch -d /app -p 1 --batch --forward < "${i}"; then \
            echo "=== OK $(basename "${i}")"; \
        else \
            rc=$?; \
            echo "=== FAILED $(basename "${i}") (patch exit ${rc})"; \
            find /app -name '*.rej' -print -exec cat {} \; ; \
            exit 1; \
        fi; \
    done \
    && rm -f /tmp/nginxproxymanager.tar.gz

# ── Stage 4: build, assemble, clean ────────────────────────────────────
# The logrotate config upstream NPM ships is written for the standalone NPM
# image and is wrong twice over inside an add-on. It rotates /data/logs, but
# patch 0001 moves all state to /config; and it declares `su npm npm`, while
# this image has no npm user — the same reason nginx.conf gets switched to
# `user root` a few lines down. logrotate treats an unknown user as fatal for
# the whole block, so NPM's rotation timer logged a CommandError plus a stack
# trace on every fire and rotated nothing. (Upstream hassio-addons has the
# identical defect.)
#
# The `logrotate --debug` call is the guard, not decoration: it exits 1 on the
# unpatched file and 0 on the patched one. If upstream ever reformats the file
# out from under these seds, the build fails here instead of silently shipping
# a broken timer again.
# hadolint ignore=DL3003,DL3042
RUN \
    set -x \
    && cd /app/frontend \
    && yarn install --ignore-engines --network-timeout 100000 \
    && yarn build --ignore-engines \
    && rm -rf node_modules \
    \
    && mkdir -p /opt/nginx-proxy-manager/frontend \
    && cp -r /app/frontend/dist/. /opt/nginx-proxy-manager/frontend/ \
    \
    && cd /app/backend \
    && yarn install \
    && rm -rf node_modules \
    && cp -r /app/backend/. /opt/nginx-proxy-manager/ \
    \
    && cp -R /app/global/. /opt/nginx-proxy-manager/global/ \
    \
    && cd /opt/nginx-proxy-manager \
    && yarn install \
    && rm -rf /etc/services.d/frontend \
    && rm -rf /opt/nginx-proxy-manager/config \
    \
    && rm -f -r /etc/nginx \
    && cp -r /app/docker/rootfs/etc/nginx /etc/nginx \
    && rm -f /etc/nginx/conf.d/dev.conf \
    \
    && cp /app/docker/rootfs/etc/letsencrypt.ini /etc \
    && cp /app/docker/rootfs/etc/logrotate.d/nginx-proxy-manager /etc/logrotate.d \
    && sed -i \
        -e 's#/data/logs/#/config/logs/#g' \
        -e '/^[[:space:]]*su npm npm[[:space:]]*$/d' \
        /etc/logrotate.d/nginx-proxy-manager \
    && logrotate --debug /etc/logrotate.d/nginx-proxy-manager \
    \
    && sed -i "s#user npm;#user root;#" /etc/nginx/nginx.conf \
    && sed -i "s#root /app/frontend;#root /opt/nginx-proxy-manager/frontend;#" \
        /etc/nginx/conf.d/production.conf \
    && sed -i "s#table.string('id').notNull().primary();#table.string('id', 32).notNull().primary();#" \
        /opt/nginx-proxy-manager/migrations/20190227065017_settings.js \
    \
    && mkdir -p \
        /run/nginx \
    \
    && modclean \
        --path /opt/nginx-proxy-manager \
        --no-progress \
        --keep-empty \
        --run \
    \
    && yarn global remove modclean \
    && yarn cache clean \
    \
    && apk del --purge .build-dependencies \
    \
    && rm -f -r \
        /app \
        /etc/init.d/nginx \
        /etc/logrotate.d/nginx \
        /opt/nginx-proxy-manager/node_modules/bcrypt/build \
        /root/.cache \
        /root/.node-gyp \
        /tmp/.[!.]* \
        /tmp/* \
        /usr/lib/node_modules \
        /usr/local/share/.cache \
        /var/lib/nginx \
        /var/log/nginx \
        /var/tmp/nginx \
        /var/www

# Copy root filesystem
COPY rootfs /

# Build arguments
ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

# Labels
LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="WOOWTECH <woowtech@designsmart.com.tw>" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="WOOWTECH" \
    org.opencontainers.image.authors="WOOWTECH <woowtech@designsmart.com.tw>" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.url="https://github.com/WOOWTECH" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}
