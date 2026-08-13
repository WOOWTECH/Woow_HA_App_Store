ARG BUILD_FROM
FROM ${BUILD_FROM}

# Seed curated custom components + defaults into /config on boot (ADR 0005).
COPY rootfs /
RUN chmod +x /opt/woow_seed/woow_seed.sh

WORKDIR /config
CMD [ "/opt/woow_seed/woow_seed.sh" ]
