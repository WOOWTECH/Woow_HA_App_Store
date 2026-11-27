ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:9.1.0

# =============================================================================
# Stage 0 — split the pinned versions into one small file per pin.
# =============================================================================
#
# cli-runtime/versions.json is the single source of the bundled Omnigent plugin
# and Agent Connect (vendored archive and sha256), Omnigent CLI, Claude Code and
# Codex versions. CI and the tests read the same file. Each stage below copies
# only the pins it uses:
# BuildKit keys COPY --from on file content, so a bump re-runs only the stage
# that consumes the changed pin. The other components keep their cached layers,
# and HA hosts do not download those layers again.
FROM ${BUILD_FROM} AS pins
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY cli-runtime/versions.json /tmp/versions.json
RUN set -euo pipefail; \
    semver='^[0-9]+[.][0-9]+[.][0-9]+$'; \
    plugin_semver='^[0-9]+[.][0-9]+[.][0-9]+(-rc[.][0-9]+)?$'; \
    pin() { mkdir -p "$(dirname "/pins/$1")"; jq -er --arg re "$3" "$2 | strings | select(test(\$re))" /tmp/versions.json > "/pins/$1"; }; \
    pin claude/version .claude.version "${semver}"; \
    pin codex/version .codex.version "${semver}"; \
    pin omnigent/version .omnigent.version "${semver}"; \
    pin omnigent-plugin/version .omnigentPlugin.version "${plugin_semver}"; \
    pin omnigent-plugin/archive .omnigentPlugin.archive '^candidate-packages/woowtech-pi-omnigent-plugin-[0-9]+[.][0-9]+[.][0-9]+(-rc[.][0-9]+)?[.]tgz$'; \
    pin omnigent-plugin/sha256 .omnigentPlugin.sha256 '^[0-9a-f]{64}$'; \
    pin agent-connect/version .agentConnect.version "${plugin_semver}"; \
    pin agent-connect/sha256 .agentConnect.sha256 '^[0-9a-f]{64}$'; \
    pin agent-connect/runtime-revision .agentConnect.runtimeRevision '^[0-9]+[.][0-9]+[.][0-9]+-r[0-9]+-[0-9a-f]{12}$'

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
       ca-certificates curl gnupg build-essential python3 git \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Pi Web source, lock, security audit and compiled output are pinned in
# patches/pi-web-source/build-pins.json. Build from the exact upstream tag rather
# than reusing its precompiled npm artifact, so the effective Next runtime and
# the compiled tree are the same reviewed 16.4.6 build.
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
ARG PI_WEB_SOURCE_COMMIT=894e1a28dbeeb7b457c7712e495d975fe9927b89
COPY patches/pi-web-source/ /opt/pi-web-source/
COPY patches/ /opt/patches/
RUN set -euo pipefail; \
    ROOT=/opt/piweb-source/package; \
    RUNTIME_ROOT=/opt/piweb/lib/node_modules/@agegr/pi-web; \
    mkdir -p "$(dirname "$ROOT")" "$(dirname "$RUNTIME_ROOT")" /opt/piweb/bin; \
    git init "$ROOT"; \
    git -C "$ROOT" remote add origin https://github.com/agegr/pi-web.git; \
    PINNED_SOURCE_COMMIT="$(node -p 'require("/opt/patches/pi-web-source/build-pins.json").sourceCommit')"; \
    PINNED_SOURCE_REF="$(node -p 'require("/opt/patches/pi-web-source/build-pins.json").sourceRef')"; \
    test "$PI_WEB_SOURCE_COMMIT" = "$PINNED_SOURCE_COMMIT"; \
    test "$(node -p 'require("/opt/patches/pi-web-source/build-pins.json").version')" = "$PI_WEB_VERSION"; \
    git -C "$ROOT" fetch --depth=1 origin "refs/tags/$PINNED_SOURCE_REF:refs/tags/$PINNED_SOURCE_REF"; \
    test "$(git -C "$ROOT" rev-parse "refs/tags/$PINNED_SOURCE_REF^{commit}")" = "$PINNED_SOURCE_COMMIT"; \
    git -C "$ROOT" checkout --detach "$PINNED_SOURCE_COMMIT"; \
    test "$(git -C "$ROOT" rev-parse HEAD)" = "$PINNED_SOURCE_COMMIT"; \
    echo "$(node -p 'require("/opt/patches/pi-web-source/build-pins.json").patchSha256')  /opt/pi-web-source/pi-web-0.12.0-next-16.4.6.patch" | sha256sum -c -; \
    git -C "$ROOT" apply /opt/pi-web-source/pi-web-0.12.0-next-16.4.6.patch; \
    echo "$(node -p 'require("/opt/patches/pi-web-source/build-pins.json").patchedPackageJsonSha256')  $ROOT/package.json" | sha256sum -c -; \
    echo "$(node -p 'require("/opt/patches/pi-web-source/build-pins.json").patchedPackageLockSha256')  $ROOT/package-lock.json" | sha256sum -c -; \
    node -e 'const p=require(process.argv[1]); if(p.version!==process.argv[2]||p.dependencies.next!=="16.4.6"||p.devDependencies["eslint-config-next"]!=="16.4.6")process.exit(1)' "$ROOT/package.json" "$PI_WEB_VERSION"; \
    cd "$ROOT"; npm ci --include=dev --no-fund; npm audit --audit-level=high --no-fund; \
    mapfile -d '' FILES < <(find "$ROOT" -path '*@earendil-works/*/dist/*/tools/path-utils.js' -print0); \
    test "${#FILES[@]}" -ge 1; node /opt/patches/fix-unicode-space-paths.mjs "${FILES[@]}"; \
    NEXT_TELEMETRY_DISABLED=1 npm run build; \
    node -e 'const p=require(process.argv[1]); if(p.version!=="16.4.6")process.exit(1)' "$ROOT/node_modules/next/package.json"; \
    npm prune --omit=dev --ignore-scripts --no-fund; \
    rm -rf "$ROOT/.git" "$ROOT/.next/cache" "$ROOT/node_modules/.cache"; \
    test ! -e "$ROOT/.git" && test ! -e "$ROOT/.next/cache" && test ! -e "$ROOT/node_modules/.cache"; \
    ln -s "$ROOT" "$RUNTIME_ROOT"; \
    ln -s ../lib/node_modules/@agegr/pi-web/bin/pi-web.js /opt/piweb/bin/pi-web; \
    rm -rf /tmp/npm-cache

# Reproducible, architecture-aware system CLIs. User-scoped binaries in the
# persistent HOME still take precedence. Separate package locks, builder runs,
# and final COPY instructions keep each registry layer under the host transfer
# ceiling; the previous combined layer was 377 MiB and repeatedly ended in EOF.
#
# npm also installs the musl Claude executable on Debian: the lock's platform
# entries carry no libc field, so `npm ci` cannot skip it. The postinstall
# hard-links the glibc binary to bin/claude.exe, and the unused ~250 MB musl
# copy doubled this layer. Remove it, as build-paseo.mjs drops the Paseo SDK's
# musl binary; the final stage fails the build if any musl copy survives.
COPY --from=pins /pins/claude/ /tmp/pins/claude/
COPY cli-runtime/claude/ /opt/pi-clis/claude/
RUN npm ci --omit=dev --prefix=/opt/pi-clis/claude \
    && CLAUDE_VERSION="$(< /tmp/pins/claude/version)" \
    && CLAUDE_NATIVE=/opt/pi-clis/claude/node_modules/@anthropic-ai/claude-code \
    && cmp -s "${CLAUDE_NATIVE}/bin/claude.exe" "${CLAUDE_NATIVE}-linux-$(node -p process.arch)/claude" \
    && rm -rf "${CLAUDE_NATIVE}"-linux-*-musl \
    && /opt/pi-clis/claude/node_modules/.bin/claude --version | grep -qwF -e "${CLAUDE_VERSION:?}" \
    && chmod -R a+rX,go-w /opt/pi-clis/claude \
    && rm -rf /tmp/npm-cache

COPY --from=pins /pins/codex/ /tmp/pins/codex/
COPY cli-runtime/codex/ /opt/pi-clis/codex/
RUN npm ci --omit=dev --prefix=/opt/pi-clis/codex \
    && CODEX_VERSION="$(< /tmp/pins/codex/version)" \
    && /opt/pi-clis/codex/node_modules/.bin/codex --version | grep -qwF -e "${CODEX_VERSION:?}" \
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
# The runtime path is a symlink to the fixed source-build root (/opt/piweb-source/package).
# `find -H` follows that command-line symlink only; plain `find` would scan nothing.
RUN set -euo pipefail; \
    mapfile -d '' FILES < <(find -H /opt/piweb/lib/node_modules/@agegr/pi-web \
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

# Keep the official compiled 0.12.0 UI and private Ingress bridge. Add Omnigent
# to React's desktop/mobile settings navigation immediately after MCP. The
# patch checks client + SSR artifact hashes and syntax before writing either.
# Diagnostic first (never gates): prints this build's compiled-settings pins so CI and each architecture can be compared.
RUN PIN_BLOCK_SIZE=2048 node /opt/patches/print-compiled-settings-pins.mjs /opt/piweb/lib/node_modules/@agegr/pi-web || true; \
    node /opt/patches/patch-omnigent-settings.mjs /opt/piweb/lib/node_modules/@agegr/pi-web


# Omnigent is built once per architecture, never downloaded on first activation.
# Keep Python and the SDK in separate OCI layers for HA's transfer budget.
FROM ${BUILD_FROM} AS omnigent-builder
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV UV_PYTHON_INSTALL_DIR=/opt/omnigent/python UV_NO_CACHE=1
COPY --from=pins /pins/omnigent/ /tmp/pins/omnigent/
COPY cli-runtime/omnigent/requirements.lock /tmp/omnigent-requirements.lock
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3-venv util-linux \
    && python3 -m venv /tmp/uv \
    && /tmp/uv/bin/pip install --no-cache-dir 'uv==0.12.10' \
    && /tmp/uv/bin/uv python install 3.12.12 \
    && /tmp/uv/bin/uv venv --python 3.12.12 /opt/omnigent/venv \
    && /tmp/uv/bin/uv pip sync --python /opt/omnigent/venv/bin/python --require-hashes /tmp/omnigent-requirements.lock \
    && /opt/omnigent/venv/bin/python -c 'import importlib.metadata, sys; assert importlib.metadata.version("omnigent") == sys.argv[1]' "$(< /tmp/pins/omnigent/version)"
# HA already ships a pinned official Claude CLI. The SDK falls back to PATH;
# remove its duplicate binary before any runtime COPY creates an OCI layer.
RUN /opt/omnigent/venv/bin/python -c 'from pathlib import Path; import claude_agent_sdk; p=Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"; print("Removed duplicate Claude bytes:", p.stat().st_size if p.exists() else 0); p.unlink(missing_ok=True)'
# Claude Code writes its <system-reminder> context (CLAUDE.md, the memory index,
# task notifications) into the person's own transcript record, and Omnigent
# mirrors every block: the web chat shows a ~19 KB reminder bubble, the session
# title is generated from it, and api-request-blob copies show every message
# twice. This is the PaaS image's patch (paas-odoo-ci
# pi-agent/omnigent-reminder-patch, byte-identical copy). It is version-gated
# and exact-anchor, so moving the Omnigent pin or an anchor drift fails the
# build; its unit tests then run against the patched package.
COPY patches/omnigent-reminder-patch/ /opt/patches/omnigent-reminder-patch/
COPY patches/tests/omnigent-reminder-patch.test.py /opt/patches/tests/omnigent-reminder-patch.test.py
RUN SITE_PACKAGES="$(/opt/omnigent/venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && /opt/omnigent/venv/bin/python /opt/patches/omnigent-reminder-patch/omnigent-reminder-patch.py --site-packages "${SITE_PACKAGES}" --strict \
    && /opt/omnigent/venv/bin/python /opt/patches/tests/omnigent-reminder-patch.test.py \
    && grep -q 'omnigent-reminder-patch v2' "${SITE_PACKAGES}/omnigent/harnesses/claude_native/bridge.py"
# Omnigent's "Configure Pi" model picker asks the host which models a Pi
# session may start with. For a Pi on its own login, the pinned Omnigent
# answers from auth.json INTERSECT models-store.json. Pi writes that store for
# providers whose catalog it refreshes over the network, so a compatible
# endpoint declared in models.json -- which is what this image's own Models
# page writes -- is in neither file: the dialog then offers only "Default" and
# Pi cannot be used through Omnigent at all. The patch routes that empty case
# to `pi --list-models`, which already knows. Same script as
# Woow_k3s_pi_agent_package charts/pi-agent/files (byte-identical copy), where
# it runs from the chart's postStart instead. The gate reads the same pin the
# venv was built from, and --strict turns a version bump or an anchor drift
# into a red build rather than an image that silently ships an empty picker.
COPY patches/omnigent-model-options-patch/ /opt/patches/omnigent-model-options-patch/
COPY patches/tests/omnigent-model-options-patch.test.py /opt/patches/tests/omnigent-model-options-patch.test.py
RUN SITE_PACKAGES="$(/opt/omnigent/venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && /opt/omnigent/venv/bin/python /opt/patches/omnigent-model-options-patch/omnigent-model-options-patch.py --site-packages "${SITE_PACKAGES}" --strict --expected-version "$(< /tmp/pins/omnigent/version)" \
    && /opt/omnigent/venv/bin/python /opt/patches/tests/omnigent-model-options-patch.test.py \
    && grep -q '_ambient_pi_model_options' "${SITE_PACKAGES}/omnigent/harnesses/pi_native/credentials.py"
# Preserve native history/config and undelivered posts during automatic
# maintenance. Reuse PR741's reviewed payload unchanged; unknown SDK source
# bytes fail the build. Explicit session deletion keeps its existing behavior.
COPY patches/omnigent-native-maintenance-patch/ /opt/patches/omnigent-native-maintenance-patch/
RUN --network=none set -eu; \
    SP="$(/opt/omnigent/venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"; \
    PATCH=/opt/patches/omnigent-native-maintenance-patch; \
    /opt/omnigent/venv/bin/python -c 'import importlib.metadata, json, sys; lock=json.load(open(sys.argv[1])); sys.exit(0 if importlib.metadata.version("omnigent") == lock["capturedCoreVersion"] == sys.argv[2] else "maintenance SDK version differs from reviewed source lock")' "$PATCH/source-lock.json" "$(< /tmp/pins/omnigent/version)"; \
    /opt/omnigent/venv/bin/python -B "$PATCH/apply_maintenance_patch.py" --site-packages "$SP" --strict; \
    /opt/omnigent/venv/bin/python -B -m unittest discover -s "$PATCH/tests" -p 'test_build_patch.py'; \
    /opt/omnigent/venv/bin/python -B "$PATCH/apply_maintenance_patch.py" --site-packages "$SP" --strict --check-only; \
    PI_NATIVE_MAINTENANCE_TEST_SOURCE="$SP/omnigent/native/native_bridge_common.py" \
      setpriv --reuid=1000 --regid=1000 --clear-groups -- \
      /opt/omnigent/venv/bin/python -B -m unittest discover -s "$PATCH/tests" -p 'test_maintenance_preservation.py'; \
    chmod a+r,go-w "$SP/omnigent/native/native_bridge_common.py" \
      "$SP/omnigent/native/__pycache__"/native_bridge_common.*.pyc
COPY --from=pins /pins/omnigent-plugin/ /tmp/pins/omnigent-plugin/
COPY candidate-packages/ /tmp/candidate-packages/
RUN cp "/tmp/$(< /tmp/pins/omnigent-plugin/archive)" /tmp/plugin.tgz \
    && echo "$(< /tmp/pins/omnigent-plugin/sha256)  /tmp/plugin.tgz" | sha256sum --check --strict \
    && mkdir -p /opt/woow/pi-omnigent-plugin \
    && tar -xzf /tmp/plugin.tgz --strip-components=1 -C /opt/woow/pi-omnigent-plugin \
    && jq -e --arg version "$(< /tmp/pins/omnigent-plugin/version)" \
         '.name == "@woowtech/pi-omnigent-plugin" and .version == $version' /opt/woow/pi-omnigent-plugin/package.json \
    && chmod -R a+rX,go-w /opt/woow/pi-omnigent-plugin

# The HA bridge consumes the plugin API; never apply its Pi Web 0.10 overlay.
# Build the Paseo daemon runtime once for each native image architecture. The
# plugin no longer carries a web client: every connection target opens its
# official site. The same RUN then splits the runtime into two trees of hard
# links (patches/split-paseo-runtime.mjs) for the two layers below.
FROM piweb-builder AS paseo-builder
COPY --from=pins /pins/agent-connect/ /tmp/pins/agent-connect/
# Unpublished reviewable candidate: use the exact checked archive in this branch.
# candidate-packages/ holds exactly one woowtech-pi-paseo-*.tgz (tests/versions.test.mjs
# checks that). What this COPY does with a second match is not relied on: the sha256
# check below, against the pin in cli-runtime/versions.json, decides which bytes are built.
COPY candidate-packages/woowtech-pi-paseo-*.tgz /tmp/paseo.tgz
RUN echo "$(< /tmp/pins/agent-connect/sha256)  /tmp/paseo.tgz" | sha256sum --check --strict \
    && mkdir -p /opt/woow/pi-paseo-plugin \
    && tar -xzf /tmp/paseo.tgz --strip-components=1 -C /opt/woow/pi-paseo-plugin \
    && PI_PASEO_EXPECTED_VERSION="$(< /tmp/pins/agent-connect/version)" \
       PI_PASEO_EXPECTED_RUNTIME_REVISION="$(< /tmp/pins/agent-connect/runtime-revision)" \
       node /opt/patches/build-paseo.mjs \
    && node /opt/patches/split-paseo-runtime.mjs /opt/woow/pi-paseo-plugin /opt/woow/paseo-runtime /opt/woow/paseo-runtime-layers \
    && rm -rf /tmp/paseo.tgz /tmp/npm-cache

# Shared runtime is the same verified candidate used by native and k3s.
# Disable npm lifecycle scripts: seed under the persistent provider HOME at boot.
FROM piweb-builder AS shared-runtime-builder
ARG PI_SHARED_RUNTIME_VERSION=0.1.6
ARG PI_SHARED_RUNTIME_SHA256=0914069fb0cf83f258cf81034bb16573f6e4242e8779cea47b4a5e841f98a937
COPY candidate-packages/woowtech-pi-agent-shared-runtime-0.1.6.tgz /tmp/shared-runtime.tgz
RUN echo "${PI_SHARED_RUNTIME_SHA256}  /tmp/shared-runtime.tgz" | sha256sum --check --strict \
    && mkdir -p /opt/woow/pi-agent-shared-runtime \
    && tar -xzf /tmp/shared-runtime.tgz --strip-components=1 -C /opt/woow/pi-agent-shared-runtime \
    && node -e 'const p=require(process.argv[1]); if(p.name!=="@woowtech/pi-agent-shared-runtime"||p.version!==process.argv[2]) throw Error("unexpected shared runtime")' /opt/woow/pi-agent-shared-runtime/package.json "${PI_SHARED_RUNTIME_VERSION}" \
    && npm ci --prefix /opt/woow/pi-agent-shared-runtime --omit=dev --legacy-peer-deps --ignore-scripts --no-audit --no-fund \
    && test -f /opt/woow/pi-agent-shared-runtime/src/distribution.mjs \
    && chmod -R a+rX,go-w /opt/woow/pi-agent-shared-runtime \
    && rm -rf /tmp/shared-runtime.tgz /tmp/npm-cache

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
# before 0.15.0), but a runtime apt install would disappear on every Supervisor
# restart anyway, so it has to be image-baked before it can matter.
#
# Runtime and video dependencies are installed in small independent layers.
# A single 384 MiB apt layer changed between releases as Debian package
# metadata advanced, causing the Elmohome host's GHCR pull to stall. Separate
# layers keep each new transfer bounded while retaining apt-managed packages.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl git gnupg jq nginx openssh-client tmux procps util-linux \
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
COPY --from=piweb-builder /opt/piweb-source           /opt/piweb-source
COPY --from=piweb-builder /opt/piweb/bin              /usr/local/bin
COPY --from=piweb-builder /opt/pi-clis/claude /opt/pi-clis/claude
COPY --from=piweb-builder /opt/pi-clis/codex /opt/pi-clis/codex
COPY --from=omnigent-builder /opt/omnigent/python /opt/omnigent/python
COPY --from=omnigent-builder /opt/omnigent/venv /opt/omnigent/venv
COPY --from=omnigent-builder /opt/woow/pi-omnigent-plugin /opt/woow/pi-omnigent-plugin
COPY --from=paseo-builder /opt/woow/pi-paseo-plugin /opt/woow/pi-paseo-plugin
# The Paseo runtime, /opt/woow/paseo-runtime, in two layers: the Claude Agent SDK's
# platform binary (node_modules/@anthropic-ai, most of its weight) apart from the
# rest, so neither comes near the 256 MiB layer limit that
# tests/assert-image-layer-sizes.mjs enforces on main. COPY cannot exclude a
# subdirectory, so the builder stage made two trees that keep the full path;
# together they are the runtime, file for file.
COPY --from=paseo-builder /opt/woow/paseo-runtime-layers/a/ /
COPY --from=paseo-builder /opt/woow/paseo-runtime-layers/b/ /
COPY --from=shared-runtime-builder /opt/woow/pi-agent-shared-runtime /opt/woow/pi-agent-shared-runtime
RUN ln -s /usr/local/lib/node_modules/@agegr/pi-web/node_modules /opt/woow/pi-paseo-plugin/node_modules \
    && ln -s /opt/woow/pi-paseo-plugin/bin/cli.mjs /usr/local/bin/pi-paseo \
    && chmod +x /opt/woow/pi-paseo-plugin/bin/cli.mjs

# /usr/local/bin/pi-omnigent comes from rootfs: a wrapper that refuses the
# plugin's Pi Web 0.10 setup commands (install-ui, activate, install-host,
# launch-web) and passes the others to bin/cli.mjs.
RUN ln -s /usr/local/lib/node_modules/@agegr/pi-web/node_modules /opt/woow/pi-omnigent-plugin/node_modules \
    && ln -s /opt/omnigent/venv/bin/omnigent /usr/local/bin/omnigent \
    && chmod +x /opt/woow/pi-omnigent-plugin/bin/cli.mjs \
    && /opt/omnigent/venv/bin/omnigent --version


# Cross-stage assertion. Both stages derive from the same ${BUILD_FROM} and
# install the same Node major, so this should never fire — which is exactly
# why it is cheap to keep: if someone ever changes one base and not the other,
# the build fails here instead of shipping a terminal that never prompts.
RUN node -e 'const p=require("/usr/local/lib/node_modules/@agegr/pi-web/node_modules/node-pty"); if (typeof p.spawn !== "function") { throw new Error("node-pty has no spawn()"); } console.log("[build] node-pty loads under the runtime node");'


# The pins this image was built from: the image smoke compares the installed
# plugin and CLIs with them, and an installed add-on can be inspected with jq.
COPY cli-runtime/versions.json /usr/local/share/woow-ha-pi-agent/versions.json

# /usr/local/bin/claude and /usr/local/bin/codex are wrappers from rootfs that
# refresh the shared Pi Web MCP/skills state and then exec these pinned
# binaries. Check the binaries directly: running a wrapper here would write
# shared state into the image.
#
# The shipped Claude tree must hold exactly one native binary: no musl copy,
# and at most 16 MiB beside bin/claude.exe (du counts its hard link once).
RUN PINS=/usr/local/share/woow-ha-pi-agent/versions.json \
    && CLAUDE_VERSION="$(jq -er .claude.version "${PINS}")" \
    && CODEX_VERSION="$(jq -er .codex.version "${PINS}")" \
    && /opt/pi-clis/claude/node_modules/.bin/claude --version | grep -qwF -e "${CLAUDE_VERSION:?}" \
    && /opt/pi-clis/codex/node_modules/.bin/codex --version | grep -qwF -e "${CODEX_VERSION:?}" \
    && ! compgen -G '/opt/pi-clis/claude/node_modules/@anthropic-ai/*musl*' \
    && CLAUDE_TREE_BYTES="$(du -sb /opt/pi-clis/claude | cut -f1)" \
    && CLAUDE_BINARY_BYTES="$(stat -c %s /opt/pi-clis/claude/node_modules/@anthropic-ai/claude-code/bin/claude.exe)" \
    && test $((CLAUDE_TREE_BYTES - CLAUDE_BINARY_BYTES)) -le $((16 * 1024 * 1024))

COPY rootfs/ /
COPY tests/omnigent-image-smoke.mjs /tmp/omnigent-image-smoke.mjs
COPY tests/sessions-http-json-acceptance.mjs /tmp/sessions-http-json-acceptance.mjs
COPY tests/paseo-image-smoke.mjs /tmp/paseo-image-smoke.mjs
COPY tests/paseo-native-runtime.mjs /tmp/paseo-native-runtime.mjs
COPY tests/shared-distribution.test.mjs /tmp/shared-distribution.test.mjs
COPY tests/shared-sync-only.test.mjs /tmp/shared-sync-only.test.mjs

# rootfs COPY doesn't reliably preserve +x on files created outside a POSIX
# filesystem. Explicitly re-mark every executable we ship so s6-overlay's
# service supervisor can run them.
RUN chmod +x \
      /etc/s6-overlay/s6-rc.d/pi-web/run \
      /etc/s6-overlay/s6-rc.d/nginx/run \
      /etc/s6-overlay/scripts/video-tools-init \
      /usr/local/bin/pi \
      /usr/local/bin/claude \
      /usr/local/bin/codex \
      /usr/local/bin/pi-omnigent \
      /usr/local/bin/pi-agent-share-state.mjs \
    && sh -n /usr/local/bin/claude \
    && sh -n /usr/local/bin/codex \
    && sh -n /usr/local/bin/pi-omnigent \
    # Codex 0.162 runs `ps` to manage its background app-server; without
    # procps a plain `codex` exits before the sign-in screen.
    && command -v ps \
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

# CI has no HA bridge address; check a copy with a loopback listener.
# The installed shared suite includes cold/warm metadata-cache MCP startup.
RUN --network=none sed 's/listen 172.30.32.1:30142/listen 127.0.0.1:30142/' /etc/nginx/nginx.conf > /tmp/nginx-ci.conf \
    && nginx -t -c /tmp/nginx-ci.conf \
    && rm /tmp/nginx-ci.conf \
    && timeout 300s node /tmp/omnigent-image-smoke.mjs \
    && timeout 120s node /tmp/paseo-image-smoke.mjs \
    && SHARED_RUNTIME_TEST_BUNDLE=/opt/woow/pi-agent-shared-runtime SHARED_DISTRIBUTION_HELPER=/usr/local/bin/pi-agent-share-state.mjs \
       timeout 120s node --test /tmp/shared-distribution.test.mjs /tmp/shared-sync-only.test.mjs \
    && timeout 180s node --test \
       /opt/woow/pi-agent-shared-runtime/tests/resource-authority.test.mjs \
       /opt/woow/pi-agent-shared-runtime/tests/resource-boundary.test.mjs \
       /opt/woow/pi-agent-shared-runtime/tests/extension-scan.test.mjs \
       /opt/woow/pi-agent-shared-runtime/tests/bridge.test.mjs \
       /opt/woow/pi-agent-shared-runtime/tests/mcp-adapter.test.mjs \
    && rm /tmp/omnigent-image-smoke.mjs /tmp/sessions-http-json-acceptance.mjs /tmp/paseo-image-smoke.mjs /tmp/paseo-native-runtime.mjs /tmp/shared-distribution.test.mjs /tmp/shared-sync-only.test.mjs

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
