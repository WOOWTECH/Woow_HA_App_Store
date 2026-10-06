ARG BUILD_FROM
FROM ${BUILD_FROM}

# Seed curated custom components into /config on boot (ADR 0002).
COPY rootfs /
RUN chmod +x /opt/apporo_seed/apporo_seed.sh

WORKDIR /config
CMD [ "/opt/apporo_seed/apporo_seed.sh" ]
