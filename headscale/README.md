# Woow Headscale VPN

自架 [Tailscale](https://tailscale.com/) control plane 的 Home Assistant add-on：**Headscale v0.29.3** + **Headplane v0.7.0** 管理介面，單容器、s6-overlay 監督（`amd64` / `aarch64`）。

所有裝置用**未修改的官方 Tailscale client** 加入你自己的 `100.64.0.0/10` tailnet；資料面走 WireGuard P2P + 公共 DERP fallback，不經 HA 主機、HA 端不需開任何 UDP port。

## 特色

- **GUI 走 HA Ingress**：sidebar 點「Headscale VPN」即自動登入 Headplane（免貼 API key）；GUI 不開任何 host port，管理面被 HA 帳號體系保護。
- **只需曝露一個 port**：control plane 映射到 host `28080`，區網直接用；對外曝露走反代（如 [Woow_ha_nginxpm](https://github.com/WOOWTECH/Woow_ha_nginxpm) + router 443）或**內建 ngrok tunnel**（填 authtoken 即用，public URL 自動注入 `server_url`）。
- **備份即還原**：noise key、SQLite、API key 全收在 add-on data 目錄，HA backup 還原後整組 VPN 復活。
- MagicDNS + 自訂 DNS 紀錄熱更新（`dns_records.json`）、自動建立 `default` 使用者、自動產生 Headplane API key。

## 快速開始

1. 加入倉庫 `https://github.com/WOOWTECH/Woow_ha_vpn_headscale_package` → 安裝本 add-on（本地 build 約 3–5 分鐘）。
2. Configuration 設定 `server_url`（區網測試：`http://<HA_IP>:28080`）→ 啟動。
3. 裝置端：`tailscale up --login-server=http://<HA_IP>:28080`，依 Log / 註冊頁指示完成核准。

完整說明（架構、port 分層、曝露教學、裝置註冊、備份還原、troubleshooting）見 add-on 的 **Documentation** 分頁（[DOCS.md](./DOCS.md)）。

## 注意

- Control plane 不能走 HA Ingress / Cloudflare Tunnel（TS2021 協議的 `Upgrade` header 會被剥除），詳 DOCS.md §8。
- 出處：服務組裝參考 [AlessioBazzanella/homeassistant-headscale-addon](https://github.com/AlessioBazzanella/homeassistant-headscale-addon)（MIT）；ingress shim 參考 [yuriy1337/headscale-ha](https://github.com/yuriy1337/headscale-ha)；設定基準來自 [WOOWTECH/Woow_vpn_headscale_package](https://github.com/WOOWTECH/Woow_vpn_headscale_package) podman 分支。
