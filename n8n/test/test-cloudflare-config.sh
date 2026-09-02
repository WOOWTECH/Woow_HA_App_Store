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

assert config["version"] == "2.12.15"
assert config["ingress"] is True
assert config["ingress_port"] == 5690
assert config["ingress_entry"] == "signin"
assert config["ingress_stream"] is True
assert config["panel_title"] == "Woow n8n"
assert config["ports"]["5678/tcp"] == 5678

addon_dir = __import__('pathlib').Path(sys.argv[1]).parent
nginx = (addon_dir / 'rootfs/etc/nginx/nginx.conf').read_text()
frame_height_path = addon_dir / 'rootfs/etc/nginx/ingress-frame-height.js'
assert 'history.pushState=H(history.pushState)' in nginx
assert 'window.WebSocket=function' in nginx
assert 'HTMLLinkElement&&HTMLLinkElement.prototype' in nginx
assert "sub_filter 'url(/assets/'" in nginx
assert 'sub_filter \'</head>\'' in nginx
assert 'return 302 $safe_ingress_path/signin;' in nginx
assert "sub_filter 'hee=function(e){return`/`+e}' 'hee=function(e){return(window.BASE_PATH||`/`)+e}';" in nginx
assert 'map $upstream_http_content_type $ingress_cache_control {' in nginx
assert 'default $upstream_http_cache_control;' in nginx
assert '"~*^text/html[[:space:]]*(?:;|$)" no-store;' in nginx
assert '"~*^(?:application|text)/(?:x-)?javascript[[:space:]]*(?:;|$)" no-store;' in nginx
assert '"~*^text/css[[:space:]]*(?:;|$)" no-store;' in nginx
assert nginx.count('proxy_hide_header Cache-Control;') == 1
assert nginx.count('add_header Cache-Control $ingress_cache_control always;') == 1
assert nginx.count('proxy_set_header If-None-Match "";') == 1
assert nginx.count('proxy_set_header If-Modified-Since "";') == 1
assert 'location = /_woow/ingress-frame-height.js {' not in nginx
assert 'alias /etc/nginx/ingress-frame-height.js;' not in nginx
assert '<script src="$safe_ingress_path/_woow/ingress-frame-height.js"></script>' not in nginx
assert not frame_height_path.exists()

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
