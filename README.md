# WoowTech HA App Store

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_HA_App_Store)

一鍵加入 24 個 WOOWTECH 精選 / 自製 Home Assistant App 的統一 store repo。

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
4. 按 **Add** → 關閉 → 頁面下拉即可看到 24 個 App

### 方法三：CLI (HAOS SSH)
```bash
ha store add https://github.com/WOOWTECH/Woow_HA_App_Store
```

## 內含 Apps（24 個）

### 🏢 WOOWTECH 自主開發
| Slug | 名稱 | Ver | 用途 |
|---|---|---|---|
| `cloudflared` | Woow Cloudflared | 1.0.4 | Cloudflare Tunnel 遠端存取（含 web GUI） |
| `odoo18ce` | Woow Odoo 18 | 0.3.39 | Odoo 18 社群版 + PostgreSQL 16 一站式 |
| `woow-emqx` | Woow EMQX | 5.9.0 | EMQX 5.x MQTT broker（企業級，內建 ngrok） |
| `woow-headscale` | Woow Headscale VPN | 0.1.0 | 自架 Headscale + Headplane GUI |
| `woow-immich` | Woow Immich | 2.5.7 | 自架相簿（Google Photos 替代） |
| `woow_lan_gateway` | Woow LAN Gateway | 0.1.4 | 工廠註冊 LAN 的 fail-closed 公網 IPv4 閘道 |
| `woow-n8n` | Woow n8n | 2.12.16 | AI/自動化 workflow |
| `woow-nextcloud` | Woow Nextcloud | 33.0.3 | 自架雲端硬碟 |
| `woow-tailscale` | Woow Tailscale | 0.1.1 | Tailscale / Headscale VPN 用戶端 |
| `woow_ha_code_server` | Woow Code Server | 0.1.5 | code-server + pi coding agent + ACP 側邊欄（取代原 `vscode` 鏡像） |
| `woow_ha_pi_agent` | Woow HA Pi Agent | 0.14.3 | pi-web + coding agent SDK + 影音管線 |
| `woow_ha_opendesign` | Woow HA OpenDesign | 0.1.7 | Ingress-only BYOK 設計工作台 + PDF／圖片／PPTX 匯出 |
| `woow-omnigent` | Woow Omnigent | 0.1.15 | Omnigent 編排伺服器 + 內建 Postgres（外部 runner 註冊制） |
| `woow_ha_core_1..5` | Woowtech HA Core 1-5 | 2.3.0 | 巢狀 HA Core 實例（每個獨立 onboarding，port 8124-8128） |

### 🪞 WOOWTECH 鏡像維護（防上游失聯）
| Slug | 名稱 | Ver | 上游 |
|---|---|---|---|
| `dnsmasq-dhcp` | Dnsmasq-DHCP | 5.1.0 | [f18m/ha-addon-dnsmasq-dhcp](https://github.com/f18m/ha-addon-dnsmasq-dhcp) |
| `hamh` | Home-Assistant-Matter-Hub | 2.0.56 | [riddix/home-assistant-matter-hub](https://github.com/riddix/home-assistant-matter-hub) |
| `frigate` | Frigate | 0.17.2 | [blakeblackshear/frigate-hass-addons](https://github.com/blakeblackshear/frigate-hass-addons) |
| `jellyfin` | Jellyfin | 0.1.0 | [hassio-addons/repository](https://github.com/hassio-addons/repository) |
| `music_assistant` | Music Assistant | 2.10.2 | [music-assistant.io](https://music-assistant.io) |
| `knxd` | KNXD daemon | 0.6.1 | [da-anda/hass-io-addons](https://github.com/da-anda/hass-io-addons/tree/main/knxd) |

## 相依 store（HA 內建，非本 repo）

以下 addon 走 HA 原生 store，本 repo 不打包：
- **Advanced SSH & Web Terminal**, **Mosquitto**, **Node-RED**, **Nginx Proxy Manager**, **Tailscale**, **Glances** → 從「Community Add-ons」store 安裝
- **File editor**, **Samba share**, **Matter Server**, **ESPHome** → Official/Community store

> Jellyfin 原本要從 Community Apps store 安裝，現已改為本 repo 的 WOOWTECH 鏡像
> （`jellyfin`），不再依賴上游 store。
>
> **Studio Code Server（`vscode`）已於 2026-09-11 下架**，由 WOOWTECH 自有的
> `woow_ha_code_server` 取代。兩者是**不同的 addon**（slug、選項 schema、映像都不同），
> 不是版本升級 —— 已安裝舊 `vscode` 的人不會被自動換掉，但本 store 不再提供它。

## 版本策略

- **每日自動同步**：`sync-upstreams.yml` 從映射的 WOOWTECH 個別 repo 更新套件目錄，有差異就自動 commit/push
- Dnsmasq-DHCP 先同步到 `WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on`，再由此流程匯入集中 store
- Frigate / Jellyfin 同理：各自的鏡像 repo 每日從上游同步並把容器映像
  重新託管到 `ghcr.io/woowtech/ha-mirror-*`，本 store 再從鏡像 repo 匯入
- `woow_ha_code_server` 於 2026-09-11 納入自動同步，來源
  [`Woow_ha_code_server_add_on`](https://github.com/WOOWTECH/Woow_ha_code_server_add_on)
  （整個 repo 根目錄）。該 repo 發布時會 `repository_dispatch` 通知本 store 立即同步，
  沒通知也會在每晚的排程掃到
- `hamh`、`music_assistant` 已於 2026-09-09 納入自動同步（此前它們的鏡像 repo 每晚
  都在跟上游，但 store 內的複本各落後兩個版本）
- 仍未納管的兩個，各有理由：
  - `knxd`：沒有對應的 WOOWTECH 鏡像 repo，對 da-anda 上游手動釘版本
  - `woow-tailscale`：**store 才是權威**（0.1.1，來源 repo 仍為 0.1.0）。把它加進
    MAPPINGS 會讓使用者被降級——同步流程已有防降級護欄會擋下，但請不要加
- 想單獨安裝：加入對應的**個別 repo URL**（例如 `WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on`）
- 想用單一入口：加入**本 store URL**

## 授權

各 addon 保留其原始授權：
- WOOWTECH 自主 addon：見各子目錄 LICENSE
- 鏡像 addon（`dnsmasq-dhcp`, `frigate`, `hamh`, `jellyfin`, `knxd`, `music_assistant`）：
  各自沿用 upstream 授權。Dnsmasq-DHCP、Frigate（blakeblackshear）與 Jellyfin
  （hassio-addons）皆為 MIT

## 維護

- 維護者：WOOWTECH `<woowtech@designsmart.com.tw>`
- Baseline 目標：HAOS 18.x、HA Core 2026.7.x、amd64 / aarch64
- 各 add-on 的實機驗證狀態以其個別 repository 與 release 紀錄為準
