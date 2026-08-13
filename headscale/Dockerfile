ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:9.3.0
ARG HEADPLANE_VERSION="0.7.0"

###############################################################################
# Stage 1 — Official Headplane image, used only as a COPY source.
# Its final stage is distroless (nodejs24-debian13, same glibc family as our
# Debian base), so we lift out the self-contained app build (/app) and the
# bundled Node.js runtime (/nodejs) instead of running it directly.
###############################################################################
# hadolint ignore=DL3006
FROM ghcr.io/tale/headplane:${HEADPLANE_VERSION} AS headplane

###############################################################################
# Stage 2 — Add-on image
###############################################################################
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

# Setup base system
ARG BUILD_ARCH="amd64"
ARG HEADSCALE_VERSION="v0.29.3"
ARG YQ_VERSION="v4.53.3"
ARG NGROK_BASE_URL="https://bin.equinox.io/c/bNyj1mQVY4c"

# Runtime dependencies + Headscale (official .deb) + yq + ngrok v3 static binary.
# bin.equinox.io is ngrok's official release channel (Equinox is wholly owned by
# ngrok; see https://ngrok.com/docs/gateway/device-gateway/linux).
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        jq \
        nginx \
    && case "${BUILD_ARCH}" in \
        aarch64) ARCH="arm64" ;; \
        amd64)   ARCH="amd64" ;; \
        *) echo "Unsupported BUILD_ARCH: ${BUILD_ARCH}" >&2; exit 1 ;; \
       esac \
    && curl -fsSL -o /tmp/headscale.deb \
        "https://github.com/juanfont/headscale/releases/download/${HEADSCALE_VERSION}/headscale_${HEADSCALE_VERSION#v}_linux_${ARCH}.deb" \
    && dpkg -i --force-confdef --force-confold /tmp/headscale.deb \
    && curl -fsSL -o /usr/bin/yq \
        "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_${ARCH}" \
    && chmod +x /usr/bin/yq \
    && curl -fsSL -o /tmp/ngrok.tgz \
        "${NGROK_BASE_URL}/ngrok-v3-stable-linux-${ARCH}.tgz" \
    && tar -xzf /tmp/ngrok.tgz -C /usr/local/bin ngrok \
    && chmod +x /usr/local/bin/ngrok \
    && apt-get clean \
    && rm -fr \
        /root/.cache \
        /tmp/* \
        /var/lib/apt/lists/*

# Headplane dashboard: bundled Node.js runtime + self-contained app build
COPY --from=headplane /nodejs /opt/nodejs
COPY --from=headplane /app /opt/headplane

# Patch Headplane build for HA Ingress —「方案 A」, verified on 0.7.0 artifacts:
# keep the /admin basename INTACT as the unique rewrite anchor for the nginx
# sub_filter shim, and only switch React Router route discovery from "lazy" to
# "initial". This removes the /__manifest?paths=... endpoint whose query-string
# paths can never be rewritten by sub_filter (client-side navigation would break
# under the dynamic ingress prefix); the SSR HTML then references the full
# static manifest instead. Verified: /__manifest returns 404 afterwards and all
# pages navigate correctly.
#
# WARNING (version-sensitive — re-verify on EVERY Headplane bump):
#  - Do NOT apply broad rules like s|"/admin"|"/"|g: it corrupts the
#    composeListener basename (GET / then redirects to "//").
#  - Never run sed over non-JS/CSS files: hp_ssh.wasm contains an
#    "/adminupdate" byte sequence and fonts/ico are binary.
# The grep guard below fails the build loudly if the pattern ever disappears
# from a future Headplane build, instead of silently shipping a broken shim.
# Sourcemaps are deleted purely to slim the image (harmless, verified).
RUN sed -i 's|"mode": "lazy"|"mode": "initial"|' /opt/headplane/build/server/index.js \
    && if ! grep -q '"mode": "initial"' /opt/headplane/build/server/index.js; then \
         echo "ERROR: Headplane route-discovery patch did not apply -" \
              "build output changed; re-run the ingress recon before bumping Headplane." >&2; \
         exit 1; \
       fi \
    && find /opt/headplane/build -type f -name '*.map' -delete

# Copy root filesystem
COPY rootfs /

# Files uploaded via the GitHub API lose their executable bit — restore it for
# the s6 legacy cont-init and service scripts.
RUN chmod +x /etc/cont-init.d/*.sh /etc/services.d/*/run

# Health check (Headscale control plane)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://127.0.0.1:8080/health || exit 1

# Build arguments
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
    maintainer="WoowTech" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.authors="WoowTech" \
    org.opencontainers.image.vendor="WoowTech" \
    org.opencontainers.image.url="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}
