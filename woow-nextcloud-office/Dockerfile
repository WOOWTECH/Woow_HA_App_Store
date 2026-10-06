# syntax=docker/dockerfile:1.7
# Unreleased PHP8.4 prototype; build/runtime and collation gates: RUNTIME-PLAN.md.
FROM debian:trixie-slim

ARG BUILD_ARCH=amd64
ARG S6_OVERLAY_VERSION=3.2.1.0
ARG BASHIO_VERSION=v0.17.5
ARG TEMPIO_VERSION=2024.11.2
ARG TARGETARCH
# Official Collabora release keyring, fingerprint 7EB1530818B7683284483B7BD8915E456E7C440E.
ARG COLLABORA_KEYRING_SHA256=b77f959916c0ec2072b72860d80f9c066910d9bddd2f69534b488f4b4d5ca4dd

ENV DEBIAN_FRONTEND=noninteractive \
    NEXTCLOUD_ROOT=/var/www/nextcloud \
    NEXTCLOUD_DATADIR=/share/nextcloud \
    PGDATA=/data/postgres \
    REDIS_DIR=/data/redis

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg xz-utils tar bzip2 unzip jq gosu procps iproute2 netcat-openbsd \
 && install -d -m 0755 /etc/apt/keyrings \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/keyrings/postgresql.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && curl --fail --show-error --location --proto '=https' --tlsv1.2 https://collaboraoffice.com/downloads/gpg/collaboraonline-release-keyring.gpg -o /etc/apt/keyrings/collabora.gpg \
 && printf '%s  %s\n' "${COLLABORA_KEYRING_SHA256}" /etc/apt/keyrings/collabora.gpg | sha256sum -c - \
 && chmod 0644 /etc/apt/keyrings/collabora.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/collabora.gpg] https://www.collaboraoffice.com/repos/CollaboraOnline/CODE-deb ./" > /etc/apt/sources.list.d/collabora-code.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      nginx redis-server postgresql-16 postgresql-client-16 \
      php8.4-fpm php8.4-cli php8.4-common php8.4-pgsql php8.4-curl php8.4-gd php8.4-intl php8.4-mbstring php8.4-xml php8.4-zip php8.4-bcmath php8.4-gmp php8.4-imagick php8.4-redis php8.4-apcu php8.4-bz2 \
      imagemagick ffmpeg smbclient libsmbclient0 davfs2 coolwsd coolwsd-deprecated \
 && { echo 'apc.enable_cli=1'; echo 'memory_limit=1024M'; echo 'upload_max_filesize=16G'; echo 'post_max_size=16G'; } > /etc/php/8.4/cli/conf.d/99-woow-nextcloud-office.ini \
 && { echo 'memory_limit=1024M'; echo 'upload_max_filesize=16G'; echo 'post_max_size=16G'; echo 'opcache.enable=1'; } > /etc/php/8.4/fpm/conf.d/99-woow-nextcloud-office.ini \
 && rm -rf /var/lib/apt/lists/*

RUN case "${TARGETARCH:-${BUILD_ARCH}}" in \
      amd64|x86_64) S6_ARCH=x86_64; TEMPIO_ARCH=amd64 ;; \
      arm64|aarch64) S6_ARCH=aarch64; TEMPIO_ARCH=aarch64 ;; \
      *) echo "Unsupported arch ${TARGETARCH:-${BUILD_ARCH}}"; exit 1 ;; \
    esac \
 && curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" -o /tmp/s6-noarch.tar.xz \
 && curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz" -o /tmp/s6-arch.tar.xz \
 && tar -C / -Jxpf /tmp/s6-noarch.tar.xz \
 && tar -C / -Jxpf /tmp/s6-arch.tar.xz \
 && curl -fsSL "https://github.com/hassio-addons/bashio/archive/${BASHIO_VERSION}.tar.gz" -o /tmp/bashio.tar.gz \
 && mkdir -p /tmp/bashio /usr/lib/bashio \
 && tar -xzf /tmp/bashio.tar.gz --strip 1 -C /tmp/bashio \
 && cp -a /tmp/bashio/lib/* /usr/lib/bashio/ \
 && ln -sf /usr/lib/bashio/bashio /usr/bin/bashio \
 && curl -fsSL "https://github.com/home-assistant/tempio/releases/download/${TEMPIO_VERSION}/tempio_${TEMPIO_ARCH}" -o /usr/bin/tempio \
 && chmod +x /usr/bin/tempio \
 && rm -rf /tmp/*

COPY build/verify-nextcloud.sh build/nextcloud-release-key.asc /tmp/nextcloud-verify/
# Declared here, after the OS/package layers, so changing the Nextcloud version only
# rebuilds the Nextcloud layers (an ARG change invalidates every later RUN's cache).
ARG NEXTCLOUD_VERSION=35.0.1
# Official SHA256 of nextcloud-${NEXTCLOUD_VERSION}.tar.bz2; must change together with the version.
ARG NEXTCLOUD_SHA256=7ed305e880192d804ba83179a19dd22257679608d63161a611ce3f8a918d2aa6
# Nextcloud release signing key (primary fingerprint) shipped as build/nextcloud-release-key.asc.
ARG NEXTCLOUD_KEY_FPR=28806A878AE423A28372792ED75899B9A724937A
RUN mkdir -p /var/www \
 && curl -fsSL "https://download.nextcloud.com/server/releases/nextcloud-${NEXTCLOUD_VERSION}.tar.bz2" -o /tmp/nextcloud.tar.bz2 \
 && curl -fsSL "https://download.nextcloud.com/server/releases/nextcloud-${NEXTCLOUD_VERSION}.tar.bz2.asc" -o /tmp/nextcloud.tar.bz2.asc \
 && bash /tmp/nextcloud-verify/verify-nextcloud.sh /tmp/nextcloud.tar.bz2 /tmp/nextcloud.tar.bz2.asc /tmp/nextcloud-verify/nextcloud-release-key.asc "${NEXTCLOUD_SHA256}" "${NEXTCLOUD_KEY_FPR}" \
 && tar -xjf /tmp/nextcloud.tar.bz2 -C /var/www \
 && rm -rf /tmp/nextcloud.tar.bz2 /tmp/nextcloud.tar.bz2.asc /tmp/nextcloud-verify \
 && chown -R www-data:www-data /var/www/nextcloud \
 && mkdir -p /run/php /run/postgresql /run/redis /data/postgres /data/redis /data/nextcloud/config /data/nextcloud/custom_apps /share/nextcloud \
 && chown -R postgres:postgres /run/postgresql /data/postgres \
 && chown -R redis:redis /run/redis /data/redis \
 && chown -R www-data:www-data /data/nextcloud /share/nextcloud /var/www/nextcloud

COPY rootfs/ /
RUN chmod +x /usr/local/bin/* \
 && find /etc/s6-overlay/s6-rc.d -name run -type f -exec chmod +x {} \; \
 && find /etc/s6-overlay/s6-rc.d -name up -type f -exec chmod +x {} \;

EXPOSE 8000 8090
ENTRYPOINT ["/init"]
