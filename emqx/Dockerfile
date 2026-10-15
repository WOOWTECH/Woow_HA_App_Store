ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:9.5.0
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Setup base system
ARG BUILD_ARCH=amd64
# EMQX stays on the 5.8 line: v5.8.9 is the last Apache-2.0 open-source
# release. 5.9+ and 6.x are the Business Source License enterprise edition,
# which may not be shipped embedded in this add-on. CI rejects anything else.
ARG EMQX_VERSION="v5.8.9"
# SHA-256 of emqx-<version>-debian13-<arch>.tar.gz, copied from the
# .sha256 files published with the upstream GitHub release.
ARG EMQX_SHA256_AMD64="c3b5a8f7c83601867d0fc1ef19a851f6f16f56a9436de74cb05f81f188a44a90"
ARG EMQX_SHA256_ARM64="524b5dd8ccad1f7dc5e5c15171328618e1ea7703fed56e17006a27258a13ecd4"
# ngrok agent, pinned from ngrok's apt repository (the SHA-256 values come
# from its dists/*/main/binary-<arch>/Packages index).
ARG NGROK_VERSION="3.39.11"
ARG NGROK_SHA256_AMD64="e51aa234283bcf20a777e21a624b2a3501b058b3d5a1faec59106311dbe30395"
ARG NGROK_SHA256_ARM64="b307de23bddc13a5729b2c8d2283fe98166e2d211d59ceeb62204ff216798bcc"
ARG NGROK_BASE_URL="https://ngrok-agent.s3.amazonaws.com/pool/main/n/ngrok"
# This image is built on the customer's Home Assistant host, often over a
# flaky link (MTU trouble): downloads retry, abort when they stall so the
# retry kicks in, and are verified before they are unpacked.
# hadolint ignore=DL3008
RUN \
    fetch() { \
        curl -fsSL \
            --retry 5 --retry-delay 3 --retry-all-errors \
            --connect-timeout 30 --speed-limit 1024 --speed-time 60 \
            -o "$1" "$2"; \
    } \
    && case "${BUILD_ARCH}" in \
        amd64) \
            ARCH="amd64"; \
            EMQX_SHA256="${EMQX_SHA256_AMD64}"; \
            NGROK_SHA256="${NGROK_SHA256_AMD64}" ;; \
        aarch64) \
            ARCH="arm64"; \
            EMQX_SHA256="${EMQX_SHA256_ARM64}"; \
            NGROK_SHA256="${NGROK_SHA256_ARM64}" ;; \
        *) echo "Unsupported architecture: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac \
    \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        procps \
        jq \
    \
    && mkdir /opt/emqx \
    && fetch /tmp/emqx.tar.gz \
        "https://github.com/emqx/emqx/releases/download/${EMQX_VERSION}/emqx-${EMQX_VERSION#v}-debian13-${ARCH}.tar.gz" \
    && echo "${EMQX_SHA256}  /tmp/emqx.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/emqx.tar.gz -C /opt/emqx \
    \
    && fetch /tmp/ngrok.deb \
        "${NGROK_BASE_URL}/ngrok_${NGROK_VERSION}-0_${ARCH}.deb" \
    && echo "${NGROK_SHA256}  /tmp/ngrok.deb" | sha256sum -c - \
    && dpkg-deb --fsys-tarfile /tmp/ngrok.deb \
        | tar -xf - -C / ./usr/local/bin/ngrok \
    && chmod +x /usr/local/bin/ngrok \
    \
    && rm -fr \
        /opt/emqx/log \
        /var/{cache,log}/* \
        /var/lib/apt/lists/* \
        /tmp/emqx.tar.gz \
        /tmp/ngrok.deb

# Copy root filesystem
COPY rootfs /

WORKDIR /opt/emqx

#healthcheck
HEALTHCHECK CMD curl --fail http://127.0.0.1:18083 || exit 1

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
