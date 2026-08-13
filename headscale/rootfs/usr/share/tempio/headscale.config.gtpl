---
# Woow Headscale VPN add-on — Headscale 設定（由 tempio 從 add-on options 產生）
# 每次 add-on 啟動都會重新 render：手動修改會被覆蓋。
# 基準：WOOWTECH/Woow_vpn_headscale_package（branch podman）config/headscale/config.yaml
# 參考：AlessioBazzanella/homeassistant-headscale-addon、yuriy1337/headscale-ha
# 注意：server_url 的網域不可與 dns.base_domain 相同（cont-init 會驗證）。

# ngrok_enabled 時，services.d/headscale/run 會在啟動前以 tunnel public URL 覆寫此欄位
server_url: "{{ .server_url }}"

listen_addr: 0.0.0.0:8080
metrics_listen_addr: 0.0.0.0:9090
grpc_listen_addr: 0.0.0.0:50443
grpc_allow_insecure: false

noise:
  private_key_path: /var/lib/headscale/noise_private.key

prefixes:
  v4: "{{ .ipv4_prefix }}"
  v6: "{{ .ipv6_prefix }}"
  allocation: sequential

derp:
  # 不自架 DERP relay，使用 Tailscale 公共 DERP map 作為 NAT 穿透 fallback
  server:
    enabled: false
  urls:
    - https://controlplane.tailscale.com/derpmap/default
  paths: []
  auto_update_enabled: true
  update_frequency: 24h

disable_check_updates: true

database:
  type: sqlite
  sqlite:
    path: /var/lib/headscale/db.sqlite
    write_ahead_log: true

dns:
  magic_dns: true
  base_domain: "{{ .magic_dns_base_domain }}"
  nameservers:
    global:
      - 1.1.1.1
      - 8.8.8.8
    split: {}
  search_domains: []
  # Headplane 直接編輯此檔，Headscale 熱載入，毋須重啟
  extra_records_path: /etc/headscale/dns_records.json

policy:
  mode: file
  # 留空 = 不套用 ACL policy（預設全部放行）。要用 ACL 時把 HuJSON 檔
  # 放進 add-on 設定資料夾（容器內 /etc/headscale），在此填路徑後重啟。
  path: ""

# Headscale CLI 與 server 溝通用的 unix socket（/var/run 為 tmpfs，
# cont-init 每次啟動會重建目錄）
unix_socket: /var/run/headscale/headscale.sock
unix_socket_permission: "0770"

log:
  level: {{ .log_level }}
  format: text

logtail:
  enabled: false
