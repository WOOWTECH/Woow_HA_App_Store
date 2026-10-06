# No HA Core rebuild, pip install, rebranding or seeded /config files.
ARG BUILD_FROM=ghcr.io/home-assistant/home-assistant:2026.9.1@sha256:612d76760b544cb40b7ba01387fdac964c59a6a550a50a4d30b4773c822d2918
FROM ${BUILD_FROM}
ARG BUILD_VERSION=2026.9.1-1
LABEL io.hass.type="addon" \
      io.hass.version="${BUILD_VERSION}" \
      org.opencontainers.image.source="https://github.com/WOOWTECH/Woow_haos_ha_core"
# The executable bit is tracked in git (100755); no BuildKit-only flags needed.
COPY rootfs/usr/local/bin/ha-core-entrypoint /usr/local/bin/ha-core-entrypoint
# The verified upstream image has ENTRYPOINT ["/init"] and no CMD.
ENTRYPOINT ["/usr/local/bin/ha-core-entrypoint", "/init"]
