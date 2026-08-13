ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:9.1.0
FROM ${BUILD_FROM}

ENV \
    LANG=C.UTF-8 \
    NODE_ENV=production \
    npm_config_cache=/tmp/npm-cache \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    PI_TELEMETRY=0 \
    PI_SKIP_VERSION_CHECK=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Node.js 22 (pi-web requires >=22.19.0). glibc-based Debian base is required
# because Bun / pi native modules will not run on Alpine musl.
#
# Video pipeline dependencies (v0.11.0):
#   - python3 + venv/pip: TTS scripts, Playwright bindings, srt/verify helpers.
#   - ffmpeg (+ libass, libx264, aac bundled by Debian): segment build, xfade
#     concat, subtitle burn, verify (ffprobe).
#   - fonts-noto-cjk + fonts-noto-color-emoji: subtitle burn under CJK/emoji
#     scripts (~7MB but nothing else covers 中/日/韓 in libass).
#   - Chromium runtime .so set (libnss3, libatk-bridge, libcups, libxcomposite,
#     libxdamage, libxrandr, libgbm, libpango, libcairo, libasound, libatspi):
#     required by the Playwright-downloaded browser at capture time. The
#     browser binary itself lands in /data/pi-agent/playwright-cache at first
#     boot (see video-tools-init) so image size stays flat across upgrades.
#   - rclone: Google Drive upload step. .deb from downloads.rclone.org because
#     Debian bookworm's rclone is a year behind current.
# Base image bump: ~300MB gzipped. Trade-off vs runtime download: apt cache
# is faster than pip on every fresh install, and puts ffmpeg/rclone under
# apt security updates.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl git gnupg jq nginx openssh-client \
       python3 python3-venv python3-pip \
       ffmpeg \
       fonts-noto-cjk fonts-noto-color-emoji fontconfig \
       libnss3 libatk-bridge2.0-0 libcups2 libxcomposite1 libxdamage1 \
       libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && ARCH="$(dpkg --print-architecture)" \
    && curl -fsSL "https://downloads.rclone.org/rclone-current-linux-${ARCH}.deb" -o /tmp/rclone.deb \
    && dpkg -i /tmp/rclone.deb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /etc/nginx/sites-enabled/default /etc/nginx/conf.d/*

# pi-web ships pre-built .next/ in the npm tarball; @earendil-works/pi-coding-agent
# is a transitive dep, so no separate agent daemon is needed.
#
# Pinned: upstream ships absolute-path assets and 40+ /api/* routes that the
# ingress shim rewrites in nginx.conf. A floating `@latest` means an upstream
# refactor of _next chunk names, RSC prefetch shape, or a new /api/* route can
# silently regress the shim without any local code change. Bump manually after
# validating a new upstream release doesn't break Ingress.
ARG PI_WEB_VERSION=0.8.4
RUN npm install -g --omit=dev "@agegr/pi-web@${PI_WEB_VERSION}" \
    && rm -rf /tmp/npm-cache

COPY rootfs/ /

# rootfs COPY doesn't reliably preserve +x on files created outside a POSIX
# filesystem. Explicitly re-mark every executable we ship so s6-overlay's
# service supervisor can run them.
RUN chmod +x \
      /etc/s6-overlay/s6-rc.d/pi-web/run \
      /etc/s6-overlay/s6-rc.d/nginx/run \
      /etc/s6-overlay/scripts/video-tools-init

ARG BUILD_ARCH=amd64
ARG BUILD_VERSION \
    BUILD_DATE \
    BUILD_DESCRIPTION \
    BUILD_NAME \
    BUILD_REF \
    BUILD_REPOSITORY

LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
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
