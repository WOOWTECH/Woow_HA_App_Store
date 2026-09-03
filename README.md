# WoowTech HA App Store

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_HA_App_Store)

一鍵加入 19 個 WOOWTECH 精選 / 自製 Home Assistant App 的統一 store repo。

## 使用方式

### 方法一：一鍵加入（推薦）
點選上方藍色按鈕（需在 HA UI 內），跳出「加入 add-on repository」對話框後按 **Add**。

### 方法二：手動加入
1. HA UI → **Settings** → **Add-ons** → **Add-on Store**
2. 右上角 ⋮ → **Repositories**
3. 貼上：
   ```
   https://github.com/WOOWTECH/Woow_HA_App_Store
   ```
4. 按 **Add** → 關閉 → 頁面下拉即可看到 19 個 App

### 方法三：CLI (HAOS SSH)
```bash
ha store add https://github.com/WOOWTECH/Woow_HA_App_Store
```

## 內含 Apps（19 個）

### 🏢 WOOWTECH 自主開發
| Slug | 名稱 | Ver | 用途 |
|---|---|---|---|
| `cloudflared` | Cloudflared Web GUI | 1.0.3 | Cloudflare Tunnel 遠端存取（含 web GUI） |
| `odoo18ce` | Odoo 18 CE | 0.3.31 | Odoo 18 社群版 + PostgreSQL 16 一站式 |
| `woow-emqx` | Woow EMQX | 5.9.0 | EMQX 5.x MQTT broker（企業級，內建 ngrok） |
| `woow-headscale` | Woow Headscale VPN | 0.1.0 | 自架 Headscale + Headplane GUI |
| `woow-immich` | Woow Immich | 2.5.7 | 自架相簿（Google Photos 替代） |
| `woow_lan_gateway` | Woow LAN Gateway | 0.1.4 | 工廠註冊 LAN 的 fail-closed 公網 IPv4 閘道 |
| `woow-n8n` | Woow n8n | 2.12.16 | AI/自動化 workflow |
| `woow-nextcloud` | Woow Nextcloud | 33.0.3 | 自架雲端硬碟 |
| `woow-tailscale` | Woow Tailscale | 0.1.0 | Tailscale / Headscale VPN 用戶端 |
| `woow_ha_pi_agent` | Woow HA Pi Agent | 0.13.2 | pi-web + coding agent SDK + 影音管線 |
| `woow_ha_core_1..5` | Woowtech HA Core 1-5 | 2.3.0 | 巢狀 HA Core 實例（每個獨立 onboarding，port 8124-8128） |

### 🪞 WOOWTECH 鏡像維護（防上游失聯）
| Slug | 名稱 | Ver | 上游 |
|---|---|---|---|
| `dnsmasq-dhcp` | Dnsmasq-DHCP | 5.1.0 | [f18m/ha-addon-dnsmasq-dhcp](https://github.com/f18m/ha-addon-dnsmasq-dhcp) |
| `hamh` | Home-Assistant-Matter-Hub | 2.0.54 | [riddix/home-assistant-matter-hub](https://github.com/riddix/home-assistant-matter-hub) |
| `music_assistant` | Music Assistant | 2.9.13 | [music-assistant.io](https://music-assistant.io) |
| `knxd` | KNXD daemon | 0.6.1 | [da-anda/hass-io-addons](https://github.com/da-anda/hass-io-addons/tree/main/knxd) |

## 相依 store（HA 內建，非本 repo）

以下 addon 走 HA 原生 store，本 repo 不打包：
- **Advanced SSH & Web Terminal**, **Mosquitto**, **Node-RED**, **Nginx Proxy Manager**, **Tailscale**, **Glances** → 從「Community Add-ons」store 安裝
- **File editor**, **Samba share**, **Matter Server**, **ESPHome** → Official/Community store

## 版本策略

- **每日自動同步**：`sync-upstreams.yml` 從映射的 WOOWTECH 個別 repo 更新套件目錄，有差異就自動 commit/push
- Dnsmasq-DHCP 先同步到 `WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on`，再由此流程匯入集中 store
- 想單獨安裝：加入對應的**個別 repo URL**（例如 `WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on`）
- 想用單一入口：加入**本 store URL**

## 授權

各 addon 保留其原始授權：
- WOOWTECH 自主 addon：見各子目錄 LICENSE
- 鏡像 addon（`dnsmasq-dhcp`, `hamh`, `music_assistant`, `knxd`）：各自沿用 upstream 授權；Dnsmasq-DHCP 為 MIT

## 維護

- 維護者：WOOWTECH `<woowtech@designsmart.com.tw>`
- Baseline 目標：HAOS 18.x、HA Core 2026.7.x、amd64 / aarch64
- 各 add-on 的實機驗證狀態以其個別 repository 與 release 紀錄為準
