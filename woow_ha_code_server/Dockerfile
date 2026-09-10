ARG BUILD_FROM=ghcr.io/hassio-addons/vscode/amd64:7.0.0
FROM ${BUILD_FROM}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PI_AGENT_DATA_DIR=/data/pi-agent \
    PI_CODING_AGENT_DIR=/data/pi-agent \
    PI_TELEMETRY=0 \
    PI_SKIP_VERSION_CHECK=1

# --- nginx (F2 fallback only) + xz-utils (Node tarball below) --------------
# nginx: the upstream vscode image ships no nginx at all — code-server is
# reached purely through HA Supervisor ingress, and that stays true by
# default here too. nginx is only ever invoked by the nginx-direct longrun,
# which itself idles (`sleep infinity`) unless direct_password is set. See
# DOCS.md and docs/ARCHITECTURE.md for why this must never grow a
# `sub_filter` / ServiceWorker-stubbing rule the way a sibling add-on's
# nginx.conf does — that pattern would guarantee a blank ACP chat webview.
# xz-utils: this base's `tar` shells out to a standalone `xz` binary for
# .tar.xz, which is absent by default — needed to unpack the Node tarball.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx xz-utils \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default /etc/nginx/conf.d/*

# --- Node 22, from the official nodejs.org tarball -------------------------
# The upstream vscode image ships NO system Node (code-server's own Node is
# private and must not be reused) and exact-pins its Debian 13 (trixie) apt
# versions. A tarball avoids adding an apt source to that pinned world and
# avoids the untested NodeSource-on-trixie path (Woow_ha_pi_agent_add_on's
# NodeSource recipe is only proven on this base's OWN debian-base:9.1.0,
# which may pin a different Debian release). Arch is mapped from BUILD_ARCH,
# set by the CI matrix (amd64/aarch64, matching HA's own {arch} convention).
ARG BUILD_ARCH=amd64
ARG NODE_VERSION=22.23.2
RUN set -euo pipefail; \
    case "${BUILD_ARCH}" in \
      amd64)   NARCH=x64 ;; \
      aarch64) NARCH=arm64 ;; \
      *) echo "unsupported arch ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NARCH}.tar.xz" \
      | tar -xJ -C /opt \
    && mv "/opt/node-v${NODE_VERSION}-linux-${NARCH}" /opt/node22 \
    && ln -sf /opt/node22/bin/node /usr/local/bin/node \
    && ln -sf /opt/node22/bin/npm  /usr/local/bin/npm \
    && node --version | grep -q '^v22\.'

# --- pi + pi-acp, pinned, with a build-time assertion -----------------------
# Version pins match PARITY_CONTRACT.md §2.1 — the podman package and this
# add-on must agree so pi's session/skill/model schema never drifts between
# them (there is no shared state any more, but the SCHEMA must still match
# in case of a future migration tool).
ARG PI_CODING_AGENT_VERSION=0.83.0
ARG PI_ACP_VERSION=0.0.33
RUN set -euo pipefail; \
    /opt/node22/bin/npm install -g --omit=dev --no-fund --no-audit --prefix /opt/node22 \
      "@earendil-works/pi-coding-agent@${PI_CODING_AGENT_VERSION}" \
      "pi-acp@${PI_ACP_VERSION}"; \
    ln -sf /opt/node22/bin/pi     /usr/local/bin/pi; \
    ln -sf /opt/node22/bin/pi-acp /usr/local/bin/pi-acp
RUN test "$(pi --version)" = "${PI_CODING_AGENT_VERSION}"
RUN command -v pi-acp >/dev/null

# --- Stop silent Unicode-space path corruption -------------------------------
# pi folds U+00A0, U+2000-200A, U+202F, U+205F and U+3000 to an ASCII space on
# every read/write/edit, and builds its read fallback chain from the
# ALREADY-FOLDED path, so the exact path the caller asked for is never tried.
# Reproduced end to end on pi 0.83.0:
#
#   - read of `Q1<U+3000>報告.txt` returned the contents of the sibling
#     `Q1<SPACE>報告.txt`, with isError:false — a confidential/public pair
#     differing only by space type cross-reads.
#   - write to `V1<U+3000>DOC.txt` reported success and OVERWROTE the
#     ASCII-space sibling instead.
#
# U+3000 IDEOGRAPHIC SPACE is ordinary in Traditional Chinese and Japanese
# filenames, so for a zh-TW deployment this is data loss, not an edge case.
# The patch turns folding into a READ-ONLY FALLBACK (a path pasted with a
# non-breaking space still resolves) while writes are never rewritten.
#
# patches/ is byte-identical with Woow_podman_code_server_package. The only
# difference here is the search root: this add-on installs pi with
# `--prefix /opt/node22`, the podman image uses npm's default /usr prefix.
#
# f1-verify.mjs ships alongside it, and tests/smoke-pi-integration.sh runs it
# against the LIVE add-on. That check is the important half: the original
# incident was not a broken patch script, it was a patch script that was never
# invoked, and no build-time assertion can catch that.
COPY patches/ /opt/patches/
RUN set -euo pipefail; \
    COUNT=$(find /opt/node22/lib/node_modules/@earendil-works \
      -path '*/dist/*/tools/path-utils.js' | wc -l); \
    echo "[patch] found ${COUNT} path-utils.js copies"; \
    if [ "${COUNT}" -lt 2 ]; then \
      echo "[patch] FAIL: expected at least 2 copies, found ${COUNT}" >&2; \
      exit 1; \
    fi; \
    find /opt/node22/lib/node_modules/@earendil-works \
      -path '*/dist/*/tools/path-utils.js' -print0 \
    | xargs -0 node /opt/patches/fix-unicode-space-paths.mjs; \
    node /opt/patches/f1-verify.mjs

# --- npm global prefix, for RUNTIME installs only ---------------------------
# Same path as the podman package and the k3s chart, deliberately: with three
# deployments the recipe "install a CLI tool and use it" has to be one recipe.
#
# Declared AFTER the pi install above, which pins its own `--prefix
# /opt/node22` and symlinks pi/pi-acp into /usr/local/bin, so this cannot move
# them. What it fixes is the user-facing half: npm's prefix here was
# /opt/node22, whose bin dir is NOT on the login PATH (only the two symlinks
# are), so `npm install -g <pkg>` reported success and the binary was then
# "command not found" in the very terminal it was installed from. Verified on
# the live add-on before this change.
#
# rootfs/etc/profile.d/npm-global.sh puts this prefix's bin dir back on PATH
# for login shells, and also picks up the opt-in persistent prefix on the pi
# state volume (/data/pi-agent/npm-global) for globals that should survive a
# restart. Both entries are guarded on existence, so the same file is correct
# on all three deployments.
ENV NPM_CONFIG_PREFIX=/opt/npm-global
RUN mkdir -p /opt/npm-global/bin /opt/npm-global/lib

# --- ACP Client extension, into the BUILTIN dir -----------------------------
# Upstream's init-code-server purges /data/vscode/extensions/<id>* for every
# line in /root/vscode.extensions on each boot (confirmed by reading its run
# script), so installing into /data would self-delete on the next restart.
# The builtin dir is the only stable slot, and appending our own line to
# vscode.extensions makes a stale user-installed copy in /data get purged
# instead of silently shadowing this one.
ARG ACP_CLIENT_VERSION=0.2.0
RUN set -euo pipefail; \
    EXT_DIR="/usr/local/lib/code-server/lib/vscode/extensions/formulahendry.acp-client-${ACP_CLIENT_VERSION}"; \
    mkdir -p "${EXT_DIR}" /tmp/acp-vsix; \
    curl -fJL -o /tmp/acp.vsix \
      "https://open-vsx.org/api/formulahendry/acp-client/${ACP_CLIENT_VERSION}/file/formulahendry.acp-client-${ACP_CLIENT_VERSION}.vsix"; \
    unzip -q /tmp/acp.vsix -d /tmp/acp-vsix; \
    cp -a /tmp/acp-vsix/extension/. "${EXT_DIR}/"; \
    rm -rf /tmp/acp.vsix /tmp/acp-vsix; \
    test -f "${EXT_DIR}/package.json"; \
    echo "formulahendry.acp-client#${ACP_CLIENT_VERSION}" >> /root/vscode.extensions

# --- pi state skeleton -------------------------------------------------------
# NOT baked into /data here (unlike the podman image) — HA's /data is a
# per-addon Supervisor mount that does not exist at build time. init-woow's
# runtime call to pi-seed (which copies from /opt/pi-agent-skel) is what
# actually populates it, on every boot, idempotently.
RUN mkdir -p /opt/pi-agent-skel/home/.pi/agent \
             /opt/pi-agent-skel/sessions \
             /opt/pi-agent-skel/skills \
             /opt/pi-agent-skel/npm-global/bin \
 && touch /opt/pi-agent-skel/.woow-pi-store

COPY rootfs/ /
RUN chmod +x /usr/local/bin/pi-code /usr/local/bin/pi-seed \
             /etc/s6-overlay/scripts/init-woow \
             /etc/s6-overlay/s6-rc.d/nginx-direct/run \
 && sha256sum -c /opt/SHA256SUMS

ARG BUILD_ARCH=amd64
ARG BUILD_VERSION \
    BUILD_DATE \
    BUILD_DESCRIPTION \
    BUILD_NAME \
    BUILD_REF \
    BUILD_REPOSITORY
LABEL io.hass.name="${BUILD_NAME}" \
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
      org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
      org.opencontainers.image.created=${BUILD_DATE} \
      org.opencontainers.image.revision=${BUILD_REF} \
      org.opencontainers.image.version=${BUILD_VERSION}
