# WoowTech MIT-licensed fork of hassio-addons/app-tailscale at upstream commit 24464c97a779bdd64c9975f514bff6e1d9058cca.
# Woow retains the upstream add-on baseline and is prepared for managed control-server migration.

ARG BUILD_FROM=ghcr.io/hassio-addons/base/amd64:21.0.2
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Setup base
ARG BUILD_ARCH=amd64
ARG TAILSCALE_VERSION="v1.102.3"
# Alpine packages are not pinned: Alpine keeps only the newest revision of each
# package, so an exact `-rN` pin stops resolving as soon as the package is
# rebuilt (0.1.6 had to move nginx from 1.30.6-r0 to 1.30.7-r0 for this).
#
# The `sed` on /etc/apk/world is load-bearing. Base images record the exact
# package builds present when they were made (e.g. libssl3 at 3.5.4-r0) as
# hard constraints in world. Alpine publishes new revisions continuously, so
# those pins go stale and then EVERY apk operation in the image fails to
# resolve, including installs unrelated to the pinned package. Stripping the
# constraints leaves the package NAMES, so world still describes what the
# image actually contains and nothing gets purged.
RUN \
    sed -i 's/[<>=~].*$//' /etc/apk/world \
    && apk upgrade --no-cache libssl3 libcrypto3 \
    && apk add --no-cache \
        bind-tools \
        dnsmasq \
        ethtool \
        ipcalc \
        iproute2 \
        iptables \
        nginx \
        coreutils \
        networkmanager \
    \
    && ln -sf /sbin/xtables-nft-multi /sbin/ip6tables \
    && ln -sf /sbin/xtables-nft-multi /sbin/iptables \
    \
    && rm -f -r \
        /usr/lib/NetworkManager/dispatcher.d \
    \
    && if [ "${BUILD_ARCH}" = "aarch64" ]; then ARCH="arm64"; fi \
    && if [ "${BUILD_ARCH}" = "amd64" ]; then ARCH="amd64"; fi \
    \
    && curl -L -s \
        "https://pkgs.tailscale.com/stable/tailscale_${TAILSCALE_VERSION#v}_${ARCH}.tgz" \
        | tar zxvf - -C /opt/ --strip-components 1 \
    \
    && rm -f -r \
        /opt/systemd

# Copy root filesystem
COPY rootfs /

RUN chmod +x /etc/s6-overlay/s6-rc.d/*/run \
    /etc/s6-overlay/s6-rc.d/*/up \
    /usr/local/lib/woow-tailscale/reconcile-login-server

HEALTHCHECK \
    CMD healthcheck

# S6 Overlay stage 2 hook
ENV S6_STAGE2_HOOK=/etc/s6-overlay/scripts/stage2_hook.sh

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
    org.opencontainers.image.source="https://github.com/WOOWTECH/Woow_HA_App_Store" \
    org.opencontainers.image.documentation="https://github.com/WOOWTECH/Woow_HA_App_Store/blob/main/woow-tailscale/DOCS.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}
