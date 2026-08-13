# Changelog

本檔案記錄 **Woow Headscale VPN** add-on 的版本變更。

## 0.1.0 (2026-08-07)

初版釋出（Supervisor 本地 build，`amd64` / `aarch64`）。

### Added

- **Headscale v0.29.3**（官方 .deb 安裝）— 自架 Tailscale control plane：公共 DERP（`controlplane.tailscale.com/derpmap/default`）、SQLite（WAL）、ACL policy file 模式、MagicDNS（`magic_dns_base_domain` 可設定）、`logtail` 停用。
- **Headplane v0.7.0**（自 `ghcr.io/tale/headplane:0.7.0` 移植）管理介面：**HA Ingress 唯一入口**（sidebar「Headscale VPN」，nginx shim + 自動登入，免貼 API key）；GUI 不開任何 host port（ingress-only 安全模型）。同容器 `proc` 整合（SIGHUP 熱 reload 設定）。
- **選配 ngrok tunnel service**：`ngrok_authtoken` 填入即用；`http`（HTTPS tunnel，`ngrok_domain` 可固定網域）與 `tcp`（raw passthrough，測試用）兩模式；public URL 自動注入 `server_url`，最終 login-server URL 於 log 大字輸出。
- Port 佈局：`8080/tcp → 28080`（control plane，唯一需曝露）；`9090/tcp`（metrics）與 `50443/tcp`（gRPC remote CLI）預設停用；`3000` 為 ingress-only、不進 ports。
- 儲存映射：`addon_config → /etc/headscale`（設定 + `dns_records.json` 熱更新 DNS 紀錄）、`data → /var/lib/headscale`（noise key、SQLite、API key、cookie secret 全收於此 → **HA backup 還原＝整組 VPN 復活**）。
- 啟動自動化（s6-overlay）：tempio render 設定檔、`server_url` hostname ≠ `magic_dns_base_domain` 啟動檢查（含子網域）、`create_default_user` 自動建 `default` 使用者（idempotent）、自動產 Headplane API key（效期 3650 天）與 cookie secret。
- 選項集合：`server_url`、`log_level`、`ipv4_prefix`、`ipv6_prefix`、`magic_dns_base_domain`、`create_default_user`、`ngrok_enabled`、`ngrok_authtoken`、`ngrok_mode`、`ngrok_domain`。
- 安全：nginx ingress shim 以 `allow 172.30.32.2; deny all;` 鎖定來源，`/_ha_key` 只能經 HA Ingress proxy 到達；apparmor profile 涵蓋 headscale/headplane/nginx/ngrok/nodejs。
- 文件：DOCS.md（zh-TW）含架構圖、port 分層、兩條曝露路徑教學（Woow_ha_nginxpm 反代 / 內建 ngrok）、裝置註冊流程、Cloudflare Tunnel 不可用說明、備份還原、troubleshooting。

### Known limitations

- Control plane（28080）不能走 HA Ingress 或 Cloudflare Tunnel（TS2021 `Upgrade` header 會被剥除）；曝露請走反代（Upgrade passthrough）或 ngrok。
- 無 OIDC 選項（規劃於後續版本接 OpenClaw）。
- ⚠️ **維護注意**：ingress shim 的 sed / sub_filter 重寫規則與 Headplane 0.7.0 build 產物**版本綁定**——任何 Headplane 版本 bump 必須連同 ingress 介面整組回歸驗收（逐頁 Machines / Users / DNS / ACL / Settings，確認 client-side 換頁不逃出 ingress 路徑、assets 無 404、無 double-prefix）。

### Credits

- 服務組裝版型：[AlessioBazzanella/homeassistant-headscale-addon](https://github.com/AlessioBazzanella/homeassistant-headscale-addon)（MIT）
- Ingress shim 與自動登入：[yuriy1337/headscale-ha](https://github.com/yuriy1337/headscale-ha)
- 設定基準與曝露實測：[WOOWTECH/Woow_vpn_headscale_package](https://github.com/WOOWTECH/Woow_vpn_headscale_package)（podman 分支 / docs）
