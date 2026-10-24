# Base = the shared WoowTech OpenDesign "core" image: the PaaS open-design image
# built from the WoowTech fork (OpenDesign 0.24.1 + WoowTech daemon/web changes,
# white-label / zh-TW / export patches, Claude Code, Codex, Pi, OpenCode, the
# bundled woowtech-brand skill, no brainstorming skill). This file adds only the
# Home Assistant shell: nginx Ingress adaptation, the ttyd CLI Terminal, the
# root PID-1 launcher, the /data layout, the headless export renderer and the
# built-in Woow OpenDesign MCP server (mcp-runtime/).
#
# 0.2.1 removed Omnigent from the add-on (until Omnigent is stable). The pinned
# core (20261018.1219, fork w2.2) is built with OMNIGENT=off: no omnigent CLI,
# no omnigent-host-entry, no bundled woow-omnigent plugin or skill. The removal
# step below stays as a guard so an older core can never bring them back.
#
# The core is published as the public ghcr.io/woowtech/open-design-core,
# copied from the PaaS registry by digest (paas-odoo-ci #359, approval #372:
# OpenDesign 0.24.1 from fork woow-od-v0.24.1-w2.2 = 1c7e697). Bump with
# .github/scripts/pin-core.sh <tag> <digest> (rewrites every pin).
ARG BUILD_FROM=ghcr.io/woowtech/open-design-core:20261018.1219@sha256:f349632632e0c3fa9e546da8e83f89aa60d283d473fdf47fffa5728e01cde023

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

USER root

# The core defaults target the PaaS chart (HOME=/home/opendesign, daemon on
# 7457). Home Assistant persists only /data,
# so everything stateful moves below /data/opendesign and the daemon listens on
# loopback 7456 behind nginx :8099 (the HA ingress_port).
ENV NODE_ENV=production \
    OD_BIND_HOST=127.0.0.1 \
    OD_PORT=7456 \
    OD_DATA_DIR=/data/opendesign \
    HOME=/data/opendesign/home \
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
    test ! -e /app/skills/brainstorming; \
    su-exec open-design:open-design sh -ceu "\
      v=\$(claude --version | awk '{print \$1}'); test \"\$v\" = '${CORE_CLAUDE_CODE_VERSION}'; \
      v=\$(codex --version | awk '{print \$2}'); test \"\$v\" = '${CORE_CODEX_VERSION}'; \
      v=\$(pi --version | tr -d '[:space:]'); test \"\$v\" = '${CORE_PI_VERSION}'; \
      v=\$(opencode --version | tr -d '[:space:]'); test \"\$v\" = '${CORE_OPENCODE_VERSION}'"; \
    for b in bash node npm chromium-browser python3 rg tmux flock setsid nginx ttyd su-exec; do \
      command -v "$b" >/dev/null || { echo "missing: $b"; exit 1; }; \
    done; \
    test -x /sbin/tini; \
    test -x /usr/local/bin/node; \
    test -x /usr/local/bin/npm; \
    fc-list | grep -qi 'Noto Sans CJK'; \
    echo "core contract OK: OpenDesign ${CORE_OPENDESIGN_VERSION}, claude ${CORE_CLAUDE_CODE_VERSION}, codex ${CORE_CODEX_VERSION}, pi ${CORE_PI_VERSION}, opencode ${CORE_OPENCODE_VERSION}"

# Omnigent is not part of the add-on (0.2.1): remove the core's woow-omnigent
# plugin and skill (no-ops on a core without them) and fail if either remains.
RUN set -eu; \
    rm -rf /app/plugins/_official/woow/woow-omnigent /app/skills/woow-omnigent; \
    if [ -d /app/plugins/_official/woow ] && [ -z "$(ls -A /app/plugins/_official/woow)" ]; then \
      rmdir /app/plugins/_official/woow; \
    fi; \
    test ! -e /app/plugins/_official/woow/woow-omnigent; \
    test ! -e /app/skills/woow-omnigent; \
    ! grep -rlsF 'woow-omnigent' /app/plugins /app/skills

# HA wording for the core's white-label "{agent} is not signed in" hint: the
# add-on's CLI Terminal instead of the PaaS /console/ path. The patch fails the
# build when the core text it replaces is missing or ambiguous.
COPY ha-patches/sign-in-hint.py /tmp/ha-patches/sign-in-hint.py
RUN python3 /tmp/ha-patches/sign-in-hint.py /app/apps/web/out \
    && rm -rf /tmp/ha-patches

COPY rootfs/ /
RUN set -eu; \
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
ARG BUILD_VERSION=0.2.3
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
