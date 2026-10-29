#!/usr/bin/env sh
# Apporo HA Core — seed curated custom components into /config, then start HA.
# Runs as the container entrypoint, before Home Assistant.
# Policy: seed-if-missing, per component folder. Never overwrites an existing folder or user edits;
# the three exceptions, unused old component groups, a hacs without hacs_frontend/ and
# an unused woow_zha_quirks before 1.4, are handled by seed_groups.py.
# See docs/adr/0002-seed-curated-custom-components-on-boot.md, 0003-replace-unused-old-component-groups.md,
# 0004-replace-hacs-without-frontend.md and 0005-replace-unused-old-zha-quirks.md
set -eu

# The APPORO_SEED_* overrides exist for tests/test_seed.py; the image never sets them.
SEED_DIR="${APPORO_SEED_DIR:-/opt/apporo_seed}"
CONFIG_DIR="${APPORO_SEED_CONFIG_DIR:-/config}"
PYTHON="${APPORO_SEED_PYTHON:-/usr/local/bin/python}"

mkdir -p "${CONFIG_DIR}/custom_components"

# One exception to seed-if-missing: an old split component group that is present
# but not in use is removed, so its consolidated successor gets seeded below.
# seed_groups.py prints the successors to skip (groups in use, or whose check failed);
# it handles each group on its own and does not fail because of one. If the script
# cannot run, or is killed, the successor of every group that still has an old folder
# in custom_components or a folder left in .apporo_seed_removed is not seeded; the
# script restores or replaces that group on the next boot. HA must still start.
# A folder named after the successor (only ha_permission_manager) counts as old unless
# its manifest.json version is 2 or higher, as is_successor() decides; a manifest that
# cannot be read counts as old, so the group is kept and logged.
# The fallback does not repeat the hacs or woow_zha_quirks checks: an existing hacs or
# woow_zha_quirks is then left as it is.
# COMPONENT_GROUPS repeats seed_groups.py GROUPS (name, successor, old_domains) because
# this fallback runs exactly when that script cannot; tests/test_seed.py checks they match.
COMPONENT_GROUPS="
permission ha_permission_manager ha_permission_manager ha_area_control ha_label_control
records woow_ha_records ha_finance ha_asset_record ha_health_record ha_note_record
protocol woow_multi_protocol woow_dmx woow_knx woow_modbus
"
if ! skip="$("${PYTHON}" "$(dirname "$0")/seed_groups.py" "${CONFIG_DIR}" "${SEED_DIR}")"; then
  skip=""
  while read -r group successor old_domains; do
    [ -n "${group}" ] || continue
    held=""
    if [ -e "${CONFIG_DIR}/.apporo_seed_removed/${group}" ]; then held=1; fi
    for name in ${old_domains}; do
      [ -e "${CONFIG_DIR}/custom_components/${name}" ] || continue
      if [ "${name}" = "${successor}" ]; then
        major="$(sed -n 's/^.*"version"[[:space:]]*:[[:space:]]*"\{0,1\}\([0-9][0-9]*\).*$/\1/p' \
          "${CONFIG_DIR}/custom_components/${name}/manifest.json" 2>/dev/null)" || major=""
        major="${major%%[!0-9]*}"
        if [ -n "${major}" ] && [ "${major}" -ge 2 ]; then continue; fi
      fi
      held=1
    done
    if [ -n "${held}" ]; then
      echo "[apporo_seed] kept the old ${group} components: component group check failed; ${successor} not seeded."
      skip="${skip} ${successor}"
    fi
  done <<EOF
${COMPONENT_GROUPS}
EOF
fi
# Unquoted on purpose: word splitting turns the lines into one space-separated list.
skip=" $(echo ${skip} | tr -d '\r') "

# Seed each managed custom component only when its folder is absent.
if [ -d "${SEED_DIR}/custom_components" ]; then
  for src in "${SEED_DIR}/custom_components/"*/; do
    [ -d "${src}" ] || continue
    name="$(basename "${src}")"
    case "${skip}" in *" ${name} "*) continue ;; esac
    dest="${CONFIG_DIR}/custom_components/${name}"
    if [ ! -e "${dest}" ]; then
      cp -a "${src}" "${dest}"
      echo "[apporo_seed] seeded custom_component: ${name}"
    fi
  done
fi

cd "${CONFIG_DIR}"
exec "${PYTHON}" -m homeassistant --config "${CONFIG_DIR}"
