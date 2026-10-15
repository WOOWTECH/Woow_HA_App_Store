# Upstream n8n release wrapped by this add-on. The editor and the task runners
# must come from the same release, so both images are derived from this one
# value. The add-on's own version (config.yaml) may advance ahead of it.
ARG N8N_UPSTREAM_VERSION=2.43.6

ARG BUILD_FROM=docker.io/n8nio/n8n:${N8N_UPSTREAM_VERSION}

ARG BUILD_VERSION=2.43.6

FROM docker.io/n8nio/runners:${N8N_UPSTREAM_VERSION} AS runner

# The Python task runner's virtualenv and its compiled dependencies are built
# for the runners image's own CPython (3.13 for n8n 2.43), not for the
# distribution python3 of the n8n base (3.14). Stage that interpreter, found
# through the venv's own symlink, so it is copied without naming a version.
FROM runner AS runner-python
# hadolint ignore=DL3002
USER root
RUN set -eu; \
    py="$(readlink -f /opt/runners/task-runner-python/.venv/bin/python)"; \
    name="$(basename "${py}")"; \
    mkdir -p /woow-python/usr/local/bin /woow-python/usr/local/lib; \
    cp -a "${py}" /woow-python/usr/local/bin/; \
    cp -a "/usr/local/lib/${name}" /woow-python/usr/local/lib/; \
    cp -a /usr/local/lib/lib"${name}".so* /woow-python/usr/local/lib/

FROM ${BUILD_FROM}

# n8n environment variables
#
# The task broker authentication token is deliberately absent: every
# installation generates its own secret on first boot (init-keygen) and keeps
# it in /data. The broker only listens on loopback because the runner launcher
# lives in this same container.
ENV \
    NODE_ENV=production \
    N8N_EDITION="community" \
    N8N_USER_FOLDER="/config" \
    DB_SQLITE_POOL_SIZE=2 \
    #Migrate `~/.n8n/binaryData` to `~/.n8n/storage`. Will become the default in v3
    N8N_MIGRATE_FS_STORAGE_PATH=true \
    N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true \
    N8N_BLOCK_ENV_ACCESS_IN_NODE=false \
    N8N_DIAGNOSTICS_ENABLED=false \
    N8N_VERSION_NOTIFICATIONS_ENABLED=false \
    N8N_PORT=5678 \
    N8N_PROTOCOL="http" \
    N8N_RUNNERS_MODE="external" \
    N8N_RUNNERS_BROKER_LISTEN_ADDRESS="127.0.0.1" \
    N8N_NATIVE_PYTHON_RUNNER=true \
    N8N_RUNNERS_TASK_BROKER_URI="http://127.0.0.1:5679"

# hadolint ignore=DL3002
USER root

# Fallback only — the branch is normally read from the base image below.
ARG ALPINE_VERSION=v3.24

# hadolint global ignore=DL4001
# Restore a usable `apk` binary. The n8n image ships a complete, valid apk
# database but no apk executable, so this fetches the static one and lets it
# install apk-tools properly.
#
# Everything below is load-bearing; each line is here because its absence
# broke a real install. Do not "simplify" them away:
#
#   1. NO --initdb. The database is intact (apk.static can enumerate every
#      installed package). Re-initialising it makes apk believe nothing is
#      installed, and it then reconciles the filesystem against world — which
#      on an empty world purges the entire base image, busybox included.
#   2. Test each apk-tools-static generation against the base database before
#      using it. apk 3.0.8 from v3.23 cannot read the database in the arm64
#      n8n 2.12.3 image, while v3.22's apk 2.14 can. The current branch is
#      still tried first so compatible bases use their native generation.
#   3. apk-tools-static FILENAME resolved from the directory index. Alpine's
#      CDN keeps only the current build per branch, so a pinned filename
#      starts 404-ing as soon as upstream cuts a new revision.
#   4. Exact-checksum pins stripped from world. The image ships entries like
#      `libcurl><Q10MJ...`, freezing packages at the builds available the day
#      it was made. Each one becomes unsatisfiable when Alpine publishes a
#      new revision and blocks unrelated installs. Names are kept, so world
#      still describes the image's real contents and nothing is purged.
#   5. libapk2 deleted rather than unpinned: the apk 3.x series replaced it
#      with `libapk` and no libapk2 package exists on this branch any more.
#   6. Branch read from /etc/os-release when /etc/alpine-release is absent.
#      The n8n 2.43 base is a Docker Hardened Images Alpine build that ships
#      only os-release; guessing the branch would fetch a mismatched
#      apk-tools.
RUN \
    set -eux; \
    cd /tmp; \
    ARCH="$(uname -m)"; \
    if [ -r /etc/alpine-release ]; then \
        ALPINE_BRANCH="v$(cut -d. -f1,2 /etc/alpine-release)"; \
    elif grep -q '^ID=alpine$' /etc/os-release 2>/dev/null \
        && OS_VERSION_ID="$(sed -n 's/^VERSION_ID=//p' /etc/os-release | tr -d '"')" \
        && [ -n "${OS_VERSION_ID}" ]; then \
        ALPINE_BRANCH="v$(echo "${OS_VERSION_ID}" | cut -d. -f1,2)"; \
    else \
        ALPINE_BRANCH="${ALPINE_VERSION}"; \
    fi; \
    echo "Base image Alpine branch: ${ALPINE_BRANCH}"; \
    APK_REPO=""; \
    APK_STATIC=""; \
    for STATIC_BRANCH in "${ALPINE_BRANCH}" v3.22; do \
        STATIC_BASE="http://dl-cdn.alpinelinux.org/alpine/${STATIC_BRANCH}/main/${ARCH}"; \
        APK_FILE="$(wget -qO- "${STATIC_BASE}/" \
            | grep -o 'apk-tools-static-[0-9][^"]*\.apk' \
            | sort -V \
            | tail -n1)"; \
        test -n "${APK_FILE}"; \
        CANDIDATE_DIR="/tmp/apk-static-${STATIC_BRANCH}"; \
        mkdir -p "${CANDIDATE_DIR}"; \
        echo "Trying ${APK_FILE} from ${STATIC_BASE}"; \
        wget -nv -O "${CANDIDATE_DIR}/apk-tools-static.apk" "${STATIC_BASE}/${APK_FILE}"; \
        tar -xzf "${CANDIDATE_DIR}/apk-tools-static.apk" -C "${CANDIDATE_DIR}"; \
        if "${CANDIDATE_DIR}/sbin/apk.static" --no-network info >/dev/null 2>&1; then \
            APK_STATIC="${CANDIDATE_DIR}/sbin/apk.static"; \
            APK_REPO="http://dl-cdn.alpinelinux.org/alpine/${STATIC_BRANCH}/main"; \
            break; \
        fi; \
        rm -rf "${CANDIDATE_DIR}"; \
    done; \
    test -n "${APK_STATIC}" && test -n "${APK_REPO}" || { echo "No apk-tools-static candidate can read the base apk database" >&2; exit 1; }; \
    if [ -f /etc/apk/world ]; then \
        sed -i 's/><.*$//' /etc/apk/world; \
        sed -i '/^libapk2$/d' /etc/apk/world; \
    fi; \
    "${APK_STATIC}" -X "${APK_REPO}" add apk-tools; \
    apk --version; \
    rm -rf /tmp/*

RUN \
    set -eux; \
    apk add --no-cache \
        shadow \
        bash \
        curl \
        jq \
        tzdata \
        libcrypto3 \
        libssl3 \
        musl-utils \
        musl \
        python3 \
        py3-pip \
        python3-dev \
        redis \
        nginx; \
    python3 -m venv /usr/local/lib/node_modules/@n8n/task-runner-python/.venv; \
    /usr/local/lib/node_modules/@n8n/task-runner-python/.venv/bin/pip install --upgrade pip; \
    rm -rf /tmp/*

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG BUILD_ARCH=amd64
# renovate: datasource=github-releases packageName=hassio-addons/bashio
ARG BASHIO_VERSION="v0.17.5"
# renovate: datasource=github-releases packageName=just-containers/s6-overlay versioning=regex:^(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)\.(?<other>\d+)$
ARG S6_OVERLAY_VERSION="3.2.1.0"
# renovate: datasource=github-releases packageName=home-assistant/tempio
ARG TEMPIO_VERSION="2024.11.2"
RUN \
    apk add --no-cache --virtual .build-dependencies \
        tar \
        xz \
    \
    && S6_ARCH="${BUILD_ARCH}" \
    && if [ "${BUILD_ARCH}" = "i386" ]; then S6_ARCH="i686"; \
    elif [ "${BUILD_ARCH}" = "amd64" ]; then S6_ARCH="x86_64"; \
    elif [ "${BUILD_ARCH}" = "armv7" ]; then S6_ARCH="arm"; fi \
    \
    && curl -fL -sS --retry 5 --retry-delay 3 --retry-connrefused --connect-timeout 15 --max-time 120 "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" \
        | tar -C / -Jxpf - \
    \
    && curl -fL -sS --retry 5 --retry-delay 3 --retry-connrefused --connect-timeout 15 --max-time 120 "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz" \
        | tar -C / -Jxpf - \
    \
    && curl -fL -sS --retry 5 --retry-delay 3 --retry-connrefused --connect-timeout 15 --max-time 120 "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-symlinks-noarch.tar.xz" \
        | tar -C / -Jxpf - \
    \
    && curl -fL -sS --retry 5 --retry-delay 3 --retry-connrefused --connect-timeout 15 --max-time 120 "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-symlinks-arch.tar.xz" \
        | tar -C / -Jxpf - \
    \
    && curl -fJL -sS --retry 5 --retry-delay 3 --retry-connrefused --connect-timeout 15 --max-time 300 -o /tmp/bashio.tar.gz \
        "https://github.com/hassio-addons/bashio/archive/${BASHIO_VERSION}.tar.gz" \
    && mkdir /tmp/bashio \
    && tar zxvf \
        /tmp/bashio.tar.gz \
        --strip 1 -C /tmp/bashio \
    \
    && mv /tmp/bashio/lib /usr/lib/bashio \
    && ln -s /usr/lib/bashio/bashio /usr/bin/bashio \
    \
    && curl -fL -sS --retry 5 --retry-delay 3 --retry-connrefused --connect-timeout 15 --max-time 120 -o /usr/bin/tempio \
        "https://github.com/home-assistant/tempio/releases/download/${TEMPIO_VERSION}/tempio_${BUILD_ARCH}" \
    && chmod a+x /usr/bin/tempio \
    \
    && apk del --no-cache --purge .build-dependencies \
    && rm -rf /tmp/*

# The launcher is taken from the runners image of the same n8n release, so its
# version (and its n8n-task-runners.json contract) always matches the runners.
COPY --from=runner --chown=root:root /usr/local/bin/task-runner-launcher /usr/local/bin/task-runner-launcher
COPY --from=runner --chown=root:root /opt/runners/task-runner-javascript /opt/runners/task-runner-javascript
COPY --from=runner --chown=root:root /opt/runners/task-runner-python /opt/runners/task-runner-python

# Upstream's Python interpreter for the Python runner (see the runner-python
# stage). The venv already points at /usr/local/bin/python3.X; the base
# image's python3 (used by Execute Command and shells) stays untouched.
COPY --from=runner-python /woow-python/ /
RUN cd /opt/runners/task-runner-python \
    && .venv/bin/python -I -c "import ssl, sqlite3, ctypes, lzma, bz2, zlib, decimal, hashlib, json, asyncio, uuid, websockets, sentry_sdk, urllib3, certifi; import src.main" \
    && .venv/bin/python -I -c "import sys; print('Python task runner interpreter', sys.version.split()[0])"

COPY .common/redis/ /

COPY rootfs/ /

ENTRYPOINT ["/init"]
CMD []

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
