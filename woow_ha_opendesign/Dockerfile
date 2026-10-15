# Base = the shared WoowTech OpenDesign "core" image: the PaaS open-design image
# built from the WoowTech fork (OpenDesign 0.24.1 + WoowTech daemon/web changes,
# white-label / zh-TW / export patches, Claude Code, Codex, Pi, OpenCode, the
# omnigent CLI with its SDK patch, bundled woowtech-brand skill and woow-omnigent
# plugin, no brainstorming skill). This file adds only the Home Assistant shell:
# nginx Ingress adaptation, the ttyd CLI Terminal, the root PID-1 launcher, the
# /data layout, the headless export renderer, the omnigent-host kit and the
# built-in Woow OpenDesign MCP server (mcp-runtime/).
#
# The core is published as the public ghcr.io/woowtech/open-design-core,
# copied from the PaaS registry by digest (paas-odoo-ci #325, approval #328:
# OpenDesign 0.24.1 from fork woow-od-v0.24.1-w2.1 = ba3a448). Bump = change the
# tag and digest together here, in .github/workflows/build.yml and build.yaml.
ARG BUILD_FROM=ghcr.io/woowtech/open-design-core:20261014.1921@sha256:bfec7cc6c96b559506f33dce9296d9c2e02e9acbb0fe543ad434ea66370baf35

# --- Built-in Woow OpenDesign MCP server: admin UI assets (mcp-runtime/, see mcp-runtime/README.md) ---
# Built with the core image's own Node/npm from the vendored, lock-pinned UI sources; only dist/ is kept.
# --include=dev because the core sets NODE_ENV=production.
FROM ${BUILD_FROM} AS woow-mcp-ui
USER root
WORKDIR /ui
COPY mcp-runtime/vendor/packages/mcp-admin-ui/ ./
RUN /usr/local/bin/npm ci --include=dev --ignore-scripts --no-audit --no-fund \
    && /usr/local/bin/npm run build \
    && test -f dist/index.html

FROM ${BUILD_FROM}

# Versions the core image must provide; the contract RUN below fails the build
# on any mismatch instead of shipping a different core silently.
# OpenDesign 0.24.1 ships its daemon as package version 0.23.1.
ARG CORE_OPENDESIGN_VERSION=0.24.1
ARG CORE_DAEMON_PACKAGE_VERSION=0.23.1
ARG CORE_CLAUDE_CODE_VERSION=2.1.296
ARG CORE_CODEX_VERSION=0.162.1
ARG CORE_PI_VERSION=1.1.0
ARG CORE_OPENCODE_VERSION=1.18.33
ARG CORE_OMNIGENT_VERSION=0.16.0

USER root

# The core defaults target the PaaS chart (HOME=/home/opendesign, daemon on
# 7457, omnigent state on the od-home PVC). Home Assistant persists only /data,
# so everything stateful moves below /data/opendesign and the daemon listens on
# loopback 7456 behind nginx :8099 (the HA ingress_port).
ENV NODE_ENV=production \
    OD_BIND_HOST=127.0.0.1 \
    OD_PORT=7456 \
    OD_DATA_DIR=/data/opendesign \
    HOME=/data/opendesign/home \
    OMNIGENT_CONFIG_HOME=/data/opendesign/home/.omnigent \
    OMNIGENT_DATA_DIR=/data/opendesign/home/.omnigent \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser

# Only the HA-specific packages; chromium, CJK/emoji fonts, fontconfig, bash,
# python3, ripgrep, gcompat, libgcc/libstdc++, tmux and tini come from the core.
RUN apk add --no-cache \
      nginx \
      su-exec \
      ttyd=1.7.7-r0 \
    && rm -rf /etc/nginx/http.d/* /var/cache/apk/*

# playwright-core for the injected headless export renderer, locked separately
# in /opt/ha-opendesign/package-lock.json. The agent CLIs are NOT installed
# here: the core image provides them (asserted below as UID 1001).
COPY runtime/package.json runtime/package-lock.json /opt/ha-opendesign/
RUN /usr/local/bin/npm ci --omit=dev --prefix /opt/ha-opendesign \
    && /usr/local/bin/npm cache clean --force

# Core contract, as the runtime user: a core that lacks a CLI, has another
# version, or still ships brainstorming fails here, not on a user's HA host.
RUN set -eu; \
    test "$(id -u open-design)" = 1001; \
    test "$(id -g open-design)" = 1001; \
    test -f /app/apps/daemon/dist/server.js; \
    test -d /app/apps/web/out; \
    grep -Fq "\"version\": \"${CORE_DAEMON_PACKAGE_VERSION}\"" /app/apps/daemon/package.json; \
    test -f /app/skills/woowtech-brand/SKILL.md; \
    test -f /app/plugins/_official/woow/woow-omnigent/open-design.json; \
    test ! -e /app/skills/brainstorming; \
    test -x /usr/local/bin/omnigent; \
    su-exec open-design:open-design sh -ceu "\
      v=\$(claude --version | awk '{print \$1}'); test \"\$v\" = '${CORE_CLAUDE_CODE_VERSION}'; \
      v=\$(codex --version | awk '{print \$2}'); test \"\$v\" = '${CORE_CODEX_VERSION}'; \
      v=\$(pi --version | tr -d '[:space:]'); test \"\$v\" = '${CORE_PI_VERSION}'; \
      v=\$(opencode --version | tr -d '[:space:]'); test \"\$v\" = '${CORE_OPENCODE_VERSION}'; \
      OMNIGENT_CONFIG_HOME=/tmp/og-contract OMNIGENT_DATA_DIR=/tmp/og-contract omnigent --version 2>&1 | grep -Fq '${CORE_OMNIGENT_VERSION}'; \
      rm -rf /tmp/og-contract"; \
    for b in bash node npm chromium-browser python3 rg tmux flock setsid nginx ttyd su-exec; do \
      command -v "$b" >/dev/null || { echo "missing: $b"; exit 1; }; \
    done; \
    test -x /sbin/tini; \
    test -x /usr/local/bin/node; \
    test -x /usr/local/bin/npm; \
    fc-list | grep -qi 'Noto Sans CJK'; \
    echo "core contract OK: OpenDesign ${CORE_OPENDESIGN_VERSION}, claude ${CORE_CLAUDE_CODE_VERSION}, codex ${CORE_CODEX_VERSION}, pi ${CORE_PI_VERSION}, opencode ${CORE_OPENCODE_VERSION}, omnigent ${CORE_OMNIGENT_VERSION}"

# HA wording for the core's white-label "{agent} is not signed in" hint: the
# add-on's CLI Terminal instead of the PaaS /console/ path. The patch fails the
# build when the core text it replaces is missing or ambiguous.
COPY ha-patches/sign-in-hint.py /tmp/ha-patches/sign-in-hint.py
RUN python3 /tmp/ha-patches/sign-in-hint.py /app/apps/web/out \
    && rm -rf /tmp/ha-patches

COPY rootfs/ /
# omnigent-host kit: byte-identical copies of woow-paas-charts
# shared/omnigent-host (KIT.sha256). The chart mounts these from a ConfigMap;
# HA has no chart, so the image lays out the same /etc/omnigent-host tree.
RUN set -eu; \
    cd /etc/omnigent-host; \
    sha256sum -c KIT.sha256; \
    mkdir -p bin; \
    install -m 0555 omnigent-shim bin/omnigent; \
    install -m 0555 omnigent-shim bin/omni; \
    install -m 0555 omnigent-host-status bin/omnigent-host-status; \
    install -m 0555 omnigent-host-status /usr/local/bin/omnigent-host-status; \
    chmod 0555 supervisor.sh omnigent-host-launch omnigent-host-status omnigent-shim; \
    chmod 0444 og_helper.py omnigent-host-profile.sh KIT.sha256; \
    chown -R root:root /etc/omnigent-host; \
    mkdir -p /data/opendesign/home; \
    chown -R open-design:open-design /data; \
    # Tools that resolve the passwd home instead of $HOME (OpenCode keeps its
    # cache/data/state there) must land in the persistent HA home too, not in
    # the core's /home/opendesign (a PaaS PVC mount point, ephemeral here).
    awk -F: 'BEGIN{OFS=":"} $1=="open-design"{$6="/data/opendesign/home"} {print}' /etc/passwd > /tmp/passwd; \
    cat /tmp/passwd > /etc/passwd; rm -f /tmp/passwd; \
    test "$(getent passwd open-design | cut -d: -f6)" = /data/opendesign/home; \
    chmod 0755 \
      /usr/local/bin/ha-opendesign \
      /usr/local/bin/ha-opendesign-agents \
      /opt/ha-opendesign/shared-agents.mjs \
      /opt/ha-opendesign/headless-entry.mjs \
      /opt/ha-opendesign/headless-renderer.mjs; \
    chown -R open-design:open-design /opt/ha-opendesign

# --- Built-in Woow OpenDesign MCP server (mcp-runtime/, see mcp-runtime/README.md) ---
# Pinned Woow MCP gateway + OpenDesign tools (mcp-runtime/VENDOR.json), hash-pinned wheels, users mcp (10001)
# and ha-ingress (1002, nginx). Code is root-owned and read-only; state lives in /data/mcp (uid 10001, 0700).
COPY --from=woow-mcp-ui /ui/dist /opt/woow/packages/mcp-admin-ui/dist
COPY mcp-runtime/ /tmp/mcp-runtime/
RUN sh /tmp/mcp-runtime/install.sh && rm -rf /tmp/mcp-runtime

# amd64 only: the core image is built for linux/amd64.
ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=0.2.0
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
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${BUILD_REF}" \
      org.opencontainers.image.version="${BUILD_VERSION}"

# HA mounts /data at runtime as root. PID 1 starts as root only long enough to
# create/chown owned directories; the launcher drops every application process
# to the open-design UID/GID 1001 with su-exec. The core's PaaS ENTRYPOINT
# (tini -- omnigent-host-entry) and CMD (daemon on 7457) are replaced.
USER root
WORKDIR /
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/ha-opendesign"]
CMD []
