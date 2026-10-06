#!/usr/bin/env sh
# Apporo HA Core — seed curated custom components into /config, then start HA.
# Runs as the container entrypoint, before Home Assistant.
# Policy: seed-if-missing, per component folder. Never overwrites an existing folder or user edits.
# See docs/adr/0002-seed-curated-custom-components-on-boot.md
set -eu

SEED_DIR="/opt/apporo_seed"
CONFIG_DIR="/config"

mkdir -p "${CONFIG_DIR}/custom_components"

# Seed each managed custom component only when its folder is absent.
if [ -d "${SEED_DIR}/custom_components" ]; then
  for src in "${SEED_DIR}/custom_components/"*/; do
    [ -d "${src}" ] || continue
    name="$(basename "${src}")"
    dest="${CONFIG_DIR}/custom_components/${name}"
    if [ ! -e "${dest}" ]; then
      cp -a "${src}" "${dest}"
      echo "[apporo_seed] seeded custom_component: ${name}"
    fi
  done
fi

cd "${CONFIG_DIR}"
exec /usr/local/bin/python -m homeassistant --config "${CONFIG_DIR}"
