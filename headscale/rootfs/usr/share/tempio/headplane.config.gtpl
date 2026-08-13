---
# Woow Headscale VPN add-on — Headplane v0.7.x 設定（由 tempio 產生）
# 每次 add-on 啟動都會重新 render：手動修改會被覆蓋。
# 注意：不可出現 integration.kubernetes / integration.docker 區段——
# v0.7.0 在 enabled=false 時仍會驗證 kubernetes.pod_name 導致啟動失敗
# （見 WOOWTECH/Woow_vpn_headscale_package podman 分支 config 檔頭註解）。
# 參考：AlessioBazzanella/homeassistant-headscale-addon、yuriy1337/headscale-ha

server:
  host: "127.0.0.1"
  port: 3001
  # base_url 固定指向本機（採 yuriy1337/headscale-ha 的做法）：
  # HA Ingress 的路徑前綴改寫完全交給 nginx shim 的 sub_filter 處理，
  # Headplane 本身不感知 ingress entry。
  base_url: "http://localhost:3001"
  # cookie_secret 由 cont-init.d/headscale.sh 注入
  # （持久化於 /var/lib/headscale/.headplane_cookie_secret）
  cookie_secret: ""
  # ingress 內部為純 HTTP（TLS 由 HA 前端負責）
  cookie_secure: false
  data_path: /var/lib/headscale/headplane

headscale:
  url: "http://127.0.0.1:8080"
  config_path: /etc/headscale/config.yaml
  dns_records_path: /etc/headscale/dns_records.json
  # 寬鬆驗證：ngrok 模式下 services.d/headscale/run 會在執行期改寫
  # config 的 server_url，不因 schema 驗證阻擋啟動
  config_strict: false
  # api_key 由 services.d/headplane/run 於 Headscale 就緒後注入
  api_key: ""

# Headscale 與 Headplane 同容器：proc integration 透過 /proc 找 PID，
# 設定變更後以 SIGHUP reload
integration:
  proc:
    enabled: true
