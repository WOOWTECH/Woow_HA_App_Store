ARG BUILD_FROM=docker.io/n8nio/n8n:2.12.3

ARG BUILD_VERSION=2.12.3

FROM docker.io/n8nio/runners:${BUILD_VERSION%-v*} AS runner

FROM ${BUILD_FROM}

# n8n environment variables
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
    N8N_RUNNERS_AUTH_TOKEN="n8n-runner" \
    N8N_RUNNERS_BROKER_LISTEN_ADDRESS="0.0.0.0" \
    N8N_NATIVE_PYTHON_RUNNER=true \
    N8N_RUNNERS_TASK_BROKER_URI="http://localhost:5679"

# hadolint ignore=DL3002
USER root

# Fallback only — the branch is normally read from /etc/alpine-release below.
ARG ALPINE_VERSION=v3.23

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
#   2. apk-tools-static FILENAME resolved from the directory index. Alpine's
#      CDN keeps only the current build per branch, so a pinned filename
#      starts 404-ing as soon as upstream cuts a new revision.
#   3. Exact-checksum pins stripped from world. The image ships entries like
#      `libcurl><Q10MJ...`, freezing packages at the builds available the day
#      it was made. Each one becomes unsatisfiable when Alpine publishes a
#      new revision and blocks unrelated installs. Names are kept, so world
#      still describes the image's real contents and nothing is purged.
#   4. libapk2 deleted rather than unpinned: the apk 3.x series replaced it
#      with `libapk` and no libapk2 package exists on this branch any more.
RUN \
    set -eux; \
    cd /tmp; \
    ARCH="$(uname -m)"; \
    if [ -r /etc/alpine-release ]; then \
        ALPINE_BRANCH="v$(cut -d. -f1,2 /etc/alpine-release)"; \
    else \
        ALPINE_BRANCH="${ALPINE_VERSION}"; \
    fi; \
    echo "Base image Alpine branch: ${ALPINE_BRANCH}"; \
    REPO="http://dl-cdn.alpinelinux.org/alpine/${ALPINE_BRANCH}/main"; \
    BASE="${REPO}/${ARCH}"; \
    APK_FILE="$(wget -qO- "${BASE}/" \
        | grep -o 'apk-tools-static-[0-9][^"]*\.apk' \
        | sort -V \
        | tail -n1)"; \
    test -n "${APK_FILE}"; \
    echo "Using ${APK_FILE} from ${BASE}"; \
    wget -nv "${BASE}/${APK_FILE}"; \
    tar -xzf apk-tools-static-*.apk; \
    if [ -f /etc/apk/world ]; then \
        sed -i 's/><.*$//' /etc/apk/world; \
        sed -i '/^libapk2$/d' /etc/apk/world; \
    fi; \
    ./sbin/apk.static -X "${REPO}" add apk-tools; \
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
        redis; \
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
    && curl -L -s "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" \
        | tar -C / -Jxpf - \
    \
    && curl -L -s "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz" \
        | tar -C / -Jxpf - \
    \
    && curl -L -s "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-symlinks-noarch.tar.xz" \
        | tar -C / -Jxpf - \
    \
    && curl -L -s "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-symlinks-arch.tar.xz" \
        | tar -C / -Jxpf - \
    \
    && curl -J -L -o /tmp/bashio.tar.gz \
        "https://github.com/hassio-addons/bashio/archive/${BASHIO_VERSION}.tar.gz" \
    && mkdir /tmp/bashio \
    && tar zxvf \
        /tmp/bashio.tar.gz \
        --strip 1 -C /tmp/bashio \
    \
    && mv /tmp/bashio/lib /usr/lib/bashio \
    && ln -s /usr/lib/bashio/bashio /usr/bin/bashio \
    \
    && curl -L -s -o /usr/bin/tempio \
        "https://github.com/home-assistant/tempio/releases/download/${TEMPIO_VERSION}/tempio_${BUILD_ARCH}" \
    && chmod a+x /usr/bin/tempio \
    \
    && apk del --no-cache --purge .build-dependencies \
    && rm -rf /tmp/*

# renovate: datasource=github-releases packageName=n8n-io/task-runner-launcher
ARG LAUNCHER_VERSION=1.4.4

RUN set -e; \
    case "$BUILD_ARCH" in \
        "amd64") ARCH_NAME="amd64" ;; \
        "aarch64") ARCH_NAME="arm64" ;; \
        *) echo "Unsupported platform: $BUILD_ARCH" && exit 1 ;; \
    esac; \
    mkdir /launcher-temp && cd /launcher-temp; \
    wget -q "https://github.com/n8n-io/task-runner-launcher/releases/download/${LAUNCHER_VERSION}/task-runner-launcher-${LAUNCHER_VERSION}-linux-${ARCH_NAME}.tar.gz"; \
    wget -q "https://github.com/n8n-io/task-runner-launcher/releases/download/${LAUNCHER_VERSION}/task-runner-launcher-${LAUNCHER_VERSION}-linux-${ARCH_NAME}.tar.gz.sha256"; \
    echo "$(cat task-runner-launcher-${LAUNCHER_VERSION}-linux-${ARCH_NAME}.tar.gz.sha256) task-runner-launcher-${LAUNCHER_VERSION}-linux-${ARCH_NAME}.tar.gz" > checksum.sha256; \
    sha256sum -c checksum.sha256; \
    mkdir -p /launcher-bin; \
    tar xzf task-runner-launcher-${LAUNCHER_VERSION}-linux-${ARCH_NAME}.tar.gz -C /usr/local/bin; \
    cd / && rm -rf /launcher-temp

COPY --from=runner --chown=root:root /opt/runners/task-runner-javascript /opt/runners/task-runner-javascript
COPY --from=runner --chown=root:root /opt/runners/task-runner-python /opt/runners/task-runner-python

# Fix Python runner: the runners image ships a venv built against its own
# Python minor, which may not match the n8n base image's Python. Symlink the
# system python into the venv and mirror the shipped site-packages into the
# directory the running interpreter will actually look in. Discover the source
# rather than hardcoding a minor, and no-op when it already matches (copying a
# directory into itself would fail the build).
RUN ln -sf /usr/bin/python3 /opt/runners/task-runner-python/.venv/bin/python && \
    ln -sf /usr/bin/python3 /opt/runners/task-runner-python/.venv/bin/python3 && \
    PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')") && \
    VENV_LIB=/opt/runners/task-runner-python/.venv/lib && \
    mkdir -p "${VENV_LIB}/python${PYVER}/site-packages" && \
    SRC=$(find "${VENV_LIB}" -maxdepth 1 -type d -name 'python3.*' \
            ! -name "python${PYVER}" | head -n1) && \
    if [ -n "${SRC}" ] && [ -d "${SRC}/site-packages" ]; then \
        cp -a "${SRC}/site-packages/." "${VENV_LIB}/python${PYVER}/site-packages/"; \
    fi

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
