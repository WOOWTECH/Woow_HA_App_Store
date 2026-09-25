# Woow Hermes Agent add-on.
#
# Built FROM the upstream image pinned by digest, plus the `slim` steps of
# Woow_podman_hermes (container/Containerfile), plus the add-on layer: nginx
# for HA Ingress, jq for the options, and the s6 services in rootfs/.
#
# The ARG is deliberately not called BUILD_FROM: the Supervisor overrides
# BUILD_FROM with its own base image when it builds a local add-on.
ARG HERMES_BASE=docker.io/nousresearch/hermes-agent:v2026.8.31@sha256:64923faeae267792bf9bf87fe3b4c4869e35004e360c7df01730ad801b74d524
FROM ${HERMES_BASE}
USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ---- vendored from Woow_podman_hermes container/Containerfile (slim) ----
ARG DDGS_VERSION=9.16.0
ARG OFFICECLI_VERSION=v1.0.135
ARG OFFICECLI_SHA256=00028af3db48678fc9ff6c8f9e70fa4c150dcee2b43ed85254afc8f4a48e13eb
ARG SUPERPOWERS_REF=b36e0829c6d0140e93cfef2ca599b1b07d4a7797

RUN apt-get update \
 && apt-get install -y --no-install-recommends tmux nginx libnginx-mod-http-js jq \
 && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled /etc/nginx/conf.d \
 && ln -sf /opt/hermes/.venv/bin/hermes /usr/local/bin/hermes \
 && rm -f /usr/local/bin/argocd /usr/local/bin/helm /usr/bin/docker \
 && rm -rf /opt/hermes/skills/apple /opt/hermes/skills/gaming /opt/hermes/skills/email \
           /opt/hermes/skills/social-media /opt/hermes/skills/yuanbao /opt/hermes/skills/media/heartmula \
           /opt/hermes/skills/media/songsee /opt/hermes/skills/media/spotify \
           /opt/hermes/skills/media/youtube-content /opt/hermes/skills/smart-home/openhue

RUN SITE="$(/opt/hermes/.venv/bin/python3 -c 'import site; print(site.getsitepackages()[0])')" \
 && uv pip install --python /opt/hermes/.venv/bin/python3 --target="$SITE" "ddgs==${DDGS_VERSION}" \
 && /opt/hermes/.venv/bin/python3 -c 'from ddgs import DDGS'

RUN curl -fsSL --retry 5 -o /usr/local/bin/officecli \
      "https://github.com/iOfficeAI/OfficeCLI/releases/download/${OFFICECLI_VERSION}/officecli-linux-x64" \
 && echo "${OFFICECLI_SHA256}  /usr/local/bin/officecli" | sha256sum -c - \
 && chmod 0755 /usr/local/bin/officecli \
 && DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=true officecli --version

# MCP OAuth RFC 9207 `iss` patches. They exit 1 when an anchor is missing.
COPY vendor/podman/patches/ /tmp/woow-patches/
RUN python3 /tmp/woow-patches/iss-callback.py \
 && python3 /tmp/woow-patches/iss-permissive.py \
 && find /opt/hermes/hermes_cli /opt/hermes/tools -type d -name __pycache__ -prune -exec rm -rf {} + \
 && rm -rf /tmp/woow-patches

RUN git clone --filter=blob:none https://github.com/obra/superpowers.git /tmp/sp \
 && git -C /tmp/sp checkout --quiet "${SUPERPOWERS_REF}" \
 && mkdir -p /opt/woow/seed \
 && cp -a /tmp/sp/skills /opt/woow/seed/skills \
 && rm -rf /tmp/sp

RUN chown -R hermes:hermes /opt/hermes/ui-tui /opt/hermes/node_modules

# ---- add-on layer ----
COPY vendor/podman/fix-model-routes.py /opt/woow/fix-model-routes.py
COPY rootfs/ /
RUN chmod 0755 /etc/cont-init.d/00-woow-options /etc/cont-init.d/020-woow-provision \
               /etc/cont-init.d/03-woow-dotenv /usr/local/bin/woow-provision \
               /etc/s6-overlay/s6-rc.d/woow-nginx/run /etc/s6-overlay/s6-rc.d/woow-provision/run

# The non-secret settings the podman unit set, minus the ones upstream no longer
# reads (HERMES_DASHBOARD_INSECURE, HERMES_DASHBOARD_TUI) and the UID-1000 remap
# (no migrated data, so the image's own UID 10000 and HERMES_TUI_DIR are kept).
ENV HERMES_DASHBOARD=1 \
    HERMES_DASHBOARD_HOST=0.0.0.0 \
    HERMES_DASHBOARD_PORT=9119 \
    API_SERVER_ENABLED=true \
    API_SERVER_HOST=0.0.0.0 \
    API_SERVER_CORS_ORIGINS=* \
    WEBHOOK_ENABLED=true \
    WEBHOOK_PORT=8644 \
    GATEWAY_ALLOW_ALL_USERS=true \
    HERMES_WRITE_SAFE_ROOT=/opt/data:/media \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=true \
    NODE_OPTIONS=--max-old-space-size=4096 \
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_SERVICES_GRACETIME=25000 \
    S6_KILL_GRACETIME=25000

# Build-time proofs. A base bump that moves a patched or rewritten anchor fails here.
RUN set -e; \
    L=/opt/hermes/hermes_cli/dashboard_auth/login_page.py; W=/opt/hermes/hermes_cli/web_dist/assets; \
    grep -q "fetch('/auth/password-login'" "$L"; \
    grep -q "window.location.assign((data && data.next) || '/')" "$L"; \
    grep -q "url('/fonts/" "$L"; \
    grep -q 'href="/auth/login?' "$L"; \
    grep -lq 'function(e){return`/`+e}' "$W"/*.js; \
    grep -lq 'window.location.assign(`/login`)' "$W"/*.js; \
    grep -lq 'href:`/config`' "$W"/*.js; \
    grep -q 'iss: Optional\[str\] = None' /opt/hermes/hermes_cli/web_routers/mcp.py; \
    grep -q 'iss mismatch tolerated' /opt/hermes/.venv/lib/python*/site-packages/mcp/client/auth/utils.py; \
    nginx -V 2>&1 | grep -q -- '--with-http_sub_module'; \
    test -f /usr/lib/nginx/modules/ngx_http_js_module.so; \
    /opt/hermes/.venv/bin/python -c 'import aiohttp' && /opt/hermes/.venv/bin/python -c 'import ast; ast.parse(open("/opt/woow/ws_relay.py").read())'; \
    nginx -t -c /etc/nginx/nginx.conf; \
    command -v tmux jq officecli; \
    test -x /usr/local/bin/hermes; \
    test -f /opt/woow/seed/skills/brainstorming/SKILL.md

ARG BUILD_VERSION=dev
ENV WOOW_IMAGE_VERSION=${BUILD_VERSION}
ARG BUILD_ARCH
LABEL io.hass.name="Woow Hermes Agent" \
      io.hass.type="addon" \
      io.hass.arch="${BUILD_ARCH}" \
      io.hass.version="${BUILD_VERSION}" \
      io.woowtech.hermes.base="${HERMES_BASE}" \
      org.opencontainers.image.source="https://github.com/WOOWTECH/Woow_ha_hermes_add_on"

# Keep upstream's dispatcher (it execs s6-overlay's /init as PID 1). Under s6,
# `gateway run` registers the gateway as the supervised gateway-default service
# and this process becomes a heartbeat.
ENTRYPOINT ["/opt/hermes/docker/entrypoint-dispatch.sh"]
CMD ["gateway", "run"]
