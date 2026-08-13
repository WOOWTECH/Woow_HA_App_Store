#!/command/with-contenv bashio
# shellcheck shell=bash
# ==============================================================================
# Woow Headscale VPN（WoowTech Home Assistant add-on）
# cont-init：由 add-on options 產生 Headscale / Headplane / nginx ingress shim 設定
#
# 流程：
#   1. bashio::addon.config → /tmp/options.json（給 tempio 用）
#   2. tempio render Headscale 與 Headplane 兩份 config
#   3. 驗證 server_url 的 hostname ≠ magic_dns_base_domain（相同 Headscale 拒啟動）
#   4. 產生（僅首次）並注入 Headplane cookie secret（32 字元，持久化於 data）
#   5. 初始化 /etc/headscale/dns_records.json（Headplane 熱更新 DNS 記錄用）
#   6. mkdir /var/run/headscale（/run 是 tmpfs，每次啟動必須重建）
#   7. 以 bashio::addon.ingress_entry 取代 %%INGRESS_ENTRY%% render nginx.conf
#
# 出處：AlessioBazzanella/homeassistant-headscale-addon（tempio cont-init 流程）
#       yuriy1337/headscale-ha（ingress shim 與 cookie secret 持久化模型）
# ==============================================================================
readonly DATA='/var/lib/headscale'
readonly OPTIONS='/tmp/options.json'
readonly HEADSCALE_CONFIG='/etc/headscale/config.yaml'
readonly HEADPLANE_CONFIG='/etc/headplane/config.yaml'
readonly COOKIE_SECRET_FILE="${DATA}/.headplane_cookie_secret"
readonly DNS_RECORDS='/etc/headscale/dns_records.json'
readonly NGINX_TEMPLATE='/etc/nginx/ingress.conf.tpl'
readonly NGINX_CONFIG='/etc/nginx/nginx.conf'

# ------------------------------------------------------------------------------
# 1. 取得 add-on options
#    bashio::addon.config 透過 Supervisor API 取得經 schema 驗證（含預設值）的
#    options JSON，落檔給 tempio 產 config 用；個別欄位下方仍以 bashio::config
#    讀取（bashio 內部讀 /data/options.json）。
# ------------------------------------------------------------------------------
bashio::addon.config > "${OPTIONS}"

# ------------------------------------------------------------------------------
# 2. tempio render 兩份 config
# ------------------------------------------------------------------------------
bashio::log.info "Rendering Headscale configuration: ${HEADSCALE_CONFIG}"
tempio \
    -conf "${OPTIONS}" \
    -template /usr/share/tempio/headscale.config.gtpl \
    -out "${HEADSCALE_CONFIG}"

mkdir -p /etc/headplane "${DATA}/headplane"
bashio::log.info "Rendering Headplane configuration: ${HEADPLANE_CONFIG}"
tempio \
    -conf "${OPTIONS}" \
    -template /usr/share/tempio/headplane.config.gtpl \
    -out "${HEADPLANE_CONFIG}"

# ------------------------------------------------------------------------------
# 3. 驗證：server_url 的 hostname 不可等於 MagicDNS base_domain
#    （相同時 Headscale 會拒絕啟動；ngrok 動態 URL 另由
#      services.d/headscale/run 在覆寫 server_url 前再驗一次）
# ------------------------------------------------------------------------------
server_url=$(bashio::config 'server_url')
base_domain=$(bashio::config 'magic_dns_base_domain')
server_host="${server_url#*://}"   # 去掉 scheme
server_host="${server_host%%/*}"   # 去掉 path
server_host="${server_host%%:*}"   # 去掉 port
# bashio::exit.nok 只 log 第一個參數，故訊息合併成單一字串。
# v0.29.3 isSafeServerURL：hostname == base_domain（errServerURLSame）
# 或 hostname 是 base_domain 的子網域（errServerURLSuffix）皆直接 fatal，
# 兩種都在此 fail-fast + 給中文修復指引，而非讓 headscale crash-loop。
if [[ "${server_host}" == "${base_domain}" ]]; then
    bashio::exit.nok \
        "設定錯誤：server_url 的網域（${server_host}）不可與 magic_dns_base_domain（${base_domain}）相同，否則 Headscale 會拒絕啟動。請把 magic_dns_base_domain 改成別的網域（例如 ts.local）後重啟 add-on。"
fi
if [[ "${server_host}" == *".${base_domain}" ]]; then
    bashio::exit.nok \
        "設定錯誤：server_url 的網域（${server_host}）不可是 magic_dns_base_domain（${base_domain}）的子網域，否則 Headscale 會拒絕啟動。請改用互不重疊的網域後重啟 add-on。"
fi

# ------------------------------------------------------------------------------
# 4. Headplane cookie secret（32 字元；只在不存在時產生，session 跨重啟存活）
# ------------------------------------------------------------------------------
if ! bashio::fs.file_exists "${COOKIE_SECRET_FILE}"; then
    bashio::log.info 'Generating Headplane cookie secret (32 chars, persisted)'
    head -c 100 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' \
        | head -c 32 > "${COOKIE_SECRET_FILE}"
fi
cookie_secret=$(< "${COOKIE_SECRET_FILE}")
yq -i ".server.cookie_secret = \"${cookie_secret}\"" "${HEADPLANE_CONFIG}"

# ------------------------------------------------------------------------------
# 5. 額外 DNS 記錄檔（dns.extra_records_path）：Headplane 直接編輯此檔，
#    Headscale 熱載入，毋須重啟
# ------------------------------------------------------------------------------
if ! bashio::fs.file_exists "${DNS_RECORDS}"; then
    echo '[]' > "${DNS_RECORDS}"
fi

# ------------------------------------------------------------------------------
# 6. Headscale CLI 走 unix socket；/var/run 是 tmpfs，每次啟動重建目錄
# ------------------------------------------------------------------------------
mkdir -p /var/run/headscale

# ------------------------------------------------------------------------------
# 7. Render nginx ingress shim：以 Supervisor 提供的 ingress entry
#    取代模板中的 %%INGRESS_ENTRY%%（例如 /api/hassio_ingress/<token>）
# ------------------------------------------------------------------------------
ingress_entry=$(bashio::addon.ingress_entry)
bashio::log.info "Rendering nginx ingress shim (ingress entry: ${ingress_entry})"
sed "s|%%INGRESS_ENTRY%%|${ingress_entry}|g" "${NGINX_TEMPLATE}" > "${NGINX_CONFIG}"

bashio::log.info 'Configuration generation complete'
