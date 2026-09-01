#!/usr/bin/env bash
set -euo pipefail

ADDON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${ADDON_DIR}/config.yaml"
INIT="${ADDON_DIR}/rootfs/etc/s6-overlay/s6-rc.d/init-keygen/run"
PYTHON="${PYTHON:-python3}"

"${PYTHON}" - "${CONFIG}" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as handle:
    config = yaml.safe_load(handle)

assert config["ingress"] is True
assert config["ingress_port"] == 5690
assert config["ingress_entry"] == "signin"
assert config["ingress_stream"] is True
assert config["panel_title"] == "Woow n8n"
assert config["ports"]["5678/tcp"] == 5678

nginx = (config_path := __import__('pathlib').Path(sys.argv[1]).parent / 'rootfs/etc/nginx/nginx.conf').read_text()
assert 'history.pushState=H(history.pushState)' in nginx
assert 'window.WebSocket=function' in nginx
assert 'sub_filter \'</head>\'' in nginx

schema = config["schema"]
assert "N8N_EDITOR_BASE_URL" in schema, "missing N8N_EDITOR_BASE_URL schema"
assert "N8N_WEBHOOK_URL" in schema, "missing N8N_WEBHOOK_URL schema"
assert "N8N_PROXY_HOPS" in schema, "missing N8N_PROXY_HOPS schema"
assert schema["N8N_PROXY_HOPS"] == "int(0,)?"
PY

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

cat >"${tmp}/mock-bashio" <<'SH'
bashio::network.ipv4_address() {
    printf '%s\n' '192.0.2.10/24'
}

bashio::addon.port() {
    printf '%s\n' '5678'
}
SH

run_init() {
    local case_name="$1"
    shift
    local env_dir="${tmp}/${case_name}"
    mkdir -p "${env_dir}"
    env -i \
        PATH="${PATH}" \
        BASH_ENV="${tmp}/mock-bashio" \
        S6_ENV_DIR="${env_dir}" \
        "$@" \
        bash "${INIT}"
    printf '%s' "${env_dir}"
}

legacy_dir="$(run_init legacy WEBHOOK_URL=https://legacy.example.test/)"
[[ "$(<"${legacy_dir}/N8N_WEBHOOK_URL")" == "https://legacy.example.test/" ]]

modern_dir="$(run_init modern N8N_WEBHOOK_URL=https://modern.example.test/)"
[[ "$(<"${modern_dir}/WEBHOOK_URL")" == "https://modern.example.test/" ]]

fallback_dir="$(run_init fallback)"
[[ "$(<"${fallback_dir}/WEBHOOK_URL")" == "http://192.0.2.10:5678" ]]
[[ "$(<"${fallback_dir}/N8N_WEBHOOK_URL")" == "http://192.0.2.10:5678" ]]
[[ "$(<"${fallback_dir}/N8N_HOST")" == "192.0.2.10" ]]
[[ "$(<"${fallback_dir}/N8N_PROTOCOL")" == "http" ]]

both_dir="${tmp}/both"
mkdir -p "${both_dir}"
printf '%s' 'https://legacy.example.test/' >"${both_dir}/WEBHOOK_URL"
printf '%s' 'https://modern.example.test/' >"${both_dir}/N8N_WEBHOOK_URL"
env -i \
    PATH="${PATH}" \
    BASH_ENV="${tmp}/mock-bashio" \
    S6_ENV_DIR="${both_dir}" \
    WEBHOOK_URL='https://legacy.example.test/' \
    N8N_WEBHOOK_URL='https://modern.example.test/' \
    bash "${INIT}"
[[ "$(<"${both_dir}/WEBHOOK_URL")" == "https://legacy.example.test/" ]]
[[ "$(<"${both_dir}/N8N_WEBHOOK_URL")" == "https://modern.example.test/" ]]

printf '%s\n' 'cloudflare configuration tests passed'
