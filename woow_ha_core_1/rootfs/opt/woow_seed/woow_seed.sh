#!/usr/bin/env sh
# Woowtech HA Core — seed curated custom components + defaults into /config, then start HA.
# Runs as the container entrypoint, before Home Assistant.
# Policy: seed-if-missing, per component folder. Never overwrites an existing folder or user edits.
# See docs/adr/0005-seed-custom-components-on-boot.md
set -eu

SEED_DIR="/opt/woow_seed"
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
      echo "[woow_seed] seeded custom_component: ${name}"
    fi
  done
fi

# Seed default configuration files only on a fresh instance (no configuration.yaml yet).
if [ ! -e "${CONFIG_DIR}/configuration.yaml" ] && [ -d "${SEED_DIR}/config_defaults" ]; then
  for f in "${SEED_DIR}/config_defaults/"*; do
    [ -e "${f}" ] || continue
    bn="$(basename "${f}")"
    if [ ! -e "${CONFIG_DIR}/${bn}" ]; then
      cp -a "${f}" "${CONFIG_DIR}/${bn}"
      echo "[woow_seed] seeded default: ${bn}"
    fi
  done
fi

cd "${CONFIG_DIR}"
exec /usr/local/bin/python -m homeassistant --config "${CONFIG_DIR}"
