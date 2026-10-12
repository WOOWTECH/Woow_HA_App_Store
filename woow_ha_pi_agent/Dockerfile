ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:9.1.0

# =============================================================================
# Stage 1 — build pi-web (and compile node-pty) in a throwaway toolchain image.
# =============================================================================
#
# WHY THIS STAGE EXISTS AS OF pi-web 0.9.0
#
# 0.9.0 added a browser terminal, and with it a hard dependency on node-pty,
# which is a native addon. node-pty 1.2.0-beta.15 ships Linux x64 and arm64
# binaries under `prebuilds/`. Its install script selects the matching binary,
# with `node-gyp rebuild` as a fallback:
#
#     install: "node scripts/prebuild.js || node-gyp rebuild"
#
# Measured against the 0.8.4 image, which has neither make nor g++:
#
#     gyp ERR! build error
#     gyp ERR! stack Error: not found: make
#     gyp ERR! not ok
#
# So a compiler is now required to BUILD this add-on. It is not required to
# run it, and the agent's bash tool executes model-authored commands inside
# this container — shipping ~250MB of gcc/binutils in it is not a trade worth
# making. The toolchain stays here; only the finished tree is copied forward.
#
# The builder deliberately uses ${BUILD_FROM}, the same base as the runtime
# stage, rather than a plain debian image. The add-on is built for amd64 and
# aarch64, and a native module compiled against a different glibc or a
# different Node ABI than the one that will load it produces a terminal that
# attaches and never prompts. Same base, same arch, same Node: no seam.
FROM ${BUILD_FROM} AS piweb-builder

ENV \
    LANG=C.UTF-8 \
    NODE_ENV=production \
    npm_config_cache=/tmp/npm-cache \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl gnupg build-essential python3 \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Pinned: upstream ships absolute-path assets and 100+ /api/* routes that the
# ingress shim rewrites in nginx.conf. A floating `@latest` means an upstream
# refactor of _next chunk names, RSC prefetch shape, or a new /api/* route can
# silently regress the shim without any local code change. Bump manually after
# validating a new upstream release doesn't break Ingress.
#
# 0.9.0 notes, read out of the built middleware.js rather than release notes:
#   - the trust guard's matcher widened from "/api/:path*" to
#     ["/", "/api/:path*"], so the HTML entry point is host-checked too and
#     answers a PLAIN-TEXT 403 "Untrusted request" when it fails. No effect
#     here — nginx.conf already rewrites Host to "localhost" for the whole
#     `location /` — but it is the first thing to suspect if a future
#     nginx.conf change breaks Ingress entirely rather than partially.
#   - /api/agent/running/events and /api/auth/all-providers were REMOVED
#     upstream. Nothing in this add-on references either by name; the shim
#     matches on the /api/ prefix, not a route list.
ARG PI_WEB_VERSION=0.12.0
RUN npm install -g --omit=dev --prefix=/opt/piweb "@agegr/pi-web@${PI_WEB_VERSION}" \
    && rm -rf /tmp/npm-cache

# Reproducible, architecture-aware system CLIs. User-scoped binaries in the
# persistent HOME still take precedence. Separate package locks, builder runs,
# and final COPY instructions keep each registry layer under the host transfer
# ceiling; the previous combined layer was 377 MiB and repeatedly ended in EOF.
COPY cli-runtime/claude/ /opt/pi-clis/claude/
RUN npm ci --omit=dev --prefix=/opt/pi-clis/claude \
    && /opt/pi-clis/claude/node_modules/.bin/claude --version | grep -q '^2.1.296' \
    && chmod -R a+rX,go-w /opt/pi-clis/claude \
    && rm -rf /tmp/npm-cache

COPY cli-runtime/codex/ /opt/pi-clis/codex/
RUN npm ci --omit=dev --prefix=/opt/pi-clis/codex \
    && /opt/pi-clis/codex/node_modules/.bin/codex --version | grep -q '0.162.1' \
    && chmod -R a+rX,go-w /opt/pi-clis/codex \
    && rm -rf /tmp/npm-cache

# Validate the installed native module by loading it and checking its API.
# Current node-pty packages store platform binaries under `prebuilds/`, not
# `build/Release/pty.node`; checking that old node-gyp output path rejects a
# valid prebuilt install.
RUN set -euo pipefail; \
    PTY="/opt/piweb/lib/node_modules/@agegr/pi-web/node_modules/node-pty"; \
    node -e 'const p=require(process.argv[1]); if (typeof p.spawn !== "function") { throw new Error("node-pty loaded but has no spawn()"); } console.log("[build] node-pty OK");' "${PTY}"

# Stop silent CJK path corruption.
#
# Upstream folds U+00A0, U+2000-200A, U+202F, U+205F and U+3000 to an ASCII
# space on EVERY read, write and edit, and builds the read fallback chain from
# the already-folded path. Two consequences, both silent, both reproduced on a
# live deployment:
#
#   - a write to `台灣　報告.txt` (U+3000 IDEOGRAPHIC SPACE) lands at
#     `台灣 報告.txt` while the success message is built from the ORIGINAL
#     path — "Successfully wrote 10 bytes" to a file that does not exist;
#   - two files differing only by space type CROSS-READ: you ask for one and
#     get the other's contents, with isError=false.
#
# U+3000 is ordinary in Traditional Chinese and Japanese filenames, so for a
# zh-TW add-on this is data loss with a success message, not an edge case.
#
# The Podman and k3s siblings have carried this fix; this add-on had not, which
# left the origin repo as the only one of the three still corrupting CJK paths.
# Still unfixed upstream at pi-coding-agent 0.85.1 — the only change to those
# files since 0.83.0 was renaming a `signal` parameter to `context`.
#
# The patch turns folding into a READ-ONLY FALLBACK (a path pasted with a
# non-breaking space still resolves) while writes are never rewritten. It
# asserts every hunk, so an upstream bump fails the build rather than shipping
# an image that quietly lost the fix.
COPY patches/ /opt/patches/
RUN set -euo pipefail; \
    mapfile -d '' FILES < <(find /opt/piweb/lib/node_modules/@agegr/pi-web \
      -path '*@earendil-works/*/dist/*/tools/path-utils.js' -print0); \
    echo "[patch] found ${#FILES[@]} path-utils.js copies"; \
    if [ "${#FILES[@]}" -lt 1 ]; then \
      echo "[patch] FAIL: expected at least 1 copy, found ${#FILES[@]}" >&2; \
      exit 1; \
    fi; \
    node /opt/patches/fix-unicode-space-paths.mjs "${FILES[@]}" \
    && node --test /opt/patches/tests/chatgpt-device-id.test.mjs \
    && PI_WEB_ROOT=/opt/piweb/lib/node_modules/@agegr/pi-web node /opt/patches/tests/device-id-live.mjs \
    && node /opt/patches/patch-chatgpt-device-id.mjs \
       "/opt/piweb/lib/node_modules/@agegr/pi-web/.next/server/app/api/auth/login/[provider]/route.js" \
    && node --check "/opt/piweb/lib/node_modules/@agegr/pi-web/.next/server/app/api/auth/login/[provider]/route.js" \
    && grep -q '__piChatGPTDeviceId' \
       "/opt/piweb/lib/node_modules/@agegr/pi-web/.next/server/app/api/auth/login/[provider]/route.js"


# =============================================================================
# Stage 2 — the add-on image. No compiler.
# =============================================================================
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
# tmux — kept in parity with the k3s and Podman sibling packages, which had
# to add this after Omnigent's native-terminal launcher (used to drive the Pi
# harness there) turned out to shell out to `tmux` unconditionally and fail
# without it. Not yet exercised on this add-on (no Omnigent integration
# here today), but a runtime apt install would disappear on every Supervisor
# restart anyway, so it has to be image-baked before it can matter.
#
# Runtime and video dependencies are installed in small independent layers.
# A single 384 MiB apt layer changed between releases as Debian package
# metadata advanced, causing the Elmohome host's GHCR pull to stall. Separate
# layers keep each new transfer bounded while retaining apt-managed packages.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl git gnupg jq nginx openssh-client tmux \
       python3 python3-venv python3-pip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk fonts-noto-color-emoji fontconfig \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libnss3 libatk-bridge2.0-0 libcups2 libxcomposite1 libxdamage1 \
       libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /etc/apt/keyrings \
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
# Copied from the builder stage rather than installed here, so the compiler
# node-pty needs never lands in the shipped image. `npm install -g --prefix`
# put the tree under /opt/piweb/{lib,bin}, so it maps onto /usr/local unchanged
# and the `pi-web` bin stays a working relative symlink into lib/node_modules.
COPY --from=piweb-builder /opt/piweb/lib/node_modules /usr/local/lib/node_modules
COPY --from=piweb-builder /opt/piweb/bin              /usr/local/bin
COPY --from=piweb-builder /opt/pi-clis/claude /opt/pi-clis/claude
COPY --from=piweb-builder /opt/pi-clis/codex /opt/pi-clis/codex

# Cross-stage assertion. Both stages derive from the same ${BUILD_FROM} and
# install the same Node major, so this should never fire — which is exactly
# why it is cheap to keep: if someone ever changes one base and not the other,
# the build fails here instead of shipping a terminal that never prompts.
RUN node -e 'const p=require("/usr/local/lib/node_modules/@agegr/pi-web/node_modules/node-pty"); if (typeof p.spawn !== "function") { throw new Error("node-pty has no spawn()"); } console.log("[build] node-pty loads under the runtime node");'


RUN ln -s /opt/pi-clis/claude/node_modules/.bin/claude /usr/local/bin/claude \
    && ln -s /opt/pi-clis/codex/node_modules/.bin/codex /usr/local/bin/codex \
    && claude --version | grep -q '^2.1.296' \
    && codex --version | grep -q '0.162.1'

COPY rootfs/ /

# rootfs COPY doesn't reliably preserve +x on files created outside a POSIX
# filesystem. Explicitly re-mark every executable we ship so s6-overlay's
# service supervisor can run them.
RUN chmod +x \
      /etc/s6-overlay/s6-rc.d/pi-web/run \
      /etc/s6-overlay/s6-rc.d/nginx/run \
      /etc/s6-overlay/scripts/video-tools-init \
      /usr/local/bin/pi \
    # Fail the build rather than ship an image where `pi` resolves to nothing.
    # Upstream installs the coding agent only as a TRANSITIVE dependency of
    # pi-web, so npm never links its `pi` bin — without this launcher the CLI
    # ships inside the image with no entry on PATH.
    #
    # This never mattered before v0.14.0 because the add-on had no terminal.
    # pi-web 0.9.0 added one, and a browser terminal where `pi install`,
    # `pi config` and the TUI are all command-not-found is a terminal that
    # cannot do the thing people open it for. Both sibling packages have
    # carried this wrapper since their first release; this add-on had not.
    && test -x "$(command -v pi)" \
    && pi --version \
    && tmux -V

# SHELL is what pi-web 0.9.0's browser terminal spawns:
#     process.env.SHELL || "/bin/sh"   with argv ["-l"]
# Debian's /bin/sh is dash, so leaving SHELL unset hands every terminal session
# a shell with no history, no completion and no arrays — while still appearing
# to work. Set on the image rather than in the s6 run script so it is true for
# the pi-web process, which is what reads it.
ENV SHELL=/bin/bash

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
