# WoowTech HA App Store

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_HA_App_Store)

一鍵加入 37 個 WOOWTECH 自製／鏡像維護 Home Assistant App 的統一 store repo。

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
4. 按 **Add** → 關閉 → 頁面下拉即可看到 37 個 App

### 方法三：CLI (HAOS SSH)
```bash
ha store add https://github.com/WOOWTECH/Woow_HA_App_Store
```

## 內含 Apps（37 個）

> 版本為 2026-10-06 的 catalog；即時版本以各目錄的 `config.yaml` 與 `.addon-sync/catalog.json` 為準。
> 「本機建置」= 沒有預建映像，安裝時由 Supervisor 在裝置上 build，耗時且吃記憶體，小機器請留意。

### 🏢 WOOWTECH 自主開發
| Slug | 名稱 | Ver | 安裝 | 用途 |
|---|---|---|---|---|
| `cloudflared` | Woow Cloudflared | 1.0.4 | 預建映像 | Cloudflare Tunnel 遠端存取（含 web GUI） |
| `odoo18ce` | Woow Odoo 18 | 0.4.11 | 預建映像 | Odoo 18 社群版 + PostgreSQL 16 一站式 |
| `woow-emqx` | Woow EMQX | 5.9.0 | 本機建置 | EMQX 5.x MQTT broker（企業級，內建 ngrok） |
| `woow-headscale` | Woow Headscale VPN | 0.1.0 | 本機建置 | 自架 Headscale + Headplane GUI |
| `woow-tailscale` | Woow Tailscale | 0.1.2 | 本機建置 | Tailscale / Headscale VPN 用戶端 |
| `woow-immich` | Woow Immich | 2.5.7 | 本機建置 | 自架相簿（Google Photos 替代） |
| `woow_lan_gateway` | Woow LAN Gateway | 0.1.4 | 本機建置（amd64） | 工廠註冊 LAN 的 fail-closed 公網 IPv4 閘道 |
| `woow-n8n` | Woow n8n | 2.12.17 | 預建映像 | AI/自動化 workflow |
| `woow-hermes` | Woow Hermes Agent | 0.1.6 | 預建映像（amd64） | Hermes Agent（NousResearch）：HA 側邊欄 dashboard + 聊天終端機，OpenAI 相容 API 與 Webhook 可經 Cloudflare Tunnel 對外 |
| `woow-nextcloud-office` | Woow Nextcloud Office | 0.2.3 | 預建映像（amd64） | Nextcloud + 內建 PostgreSQL／Redis／Collabora Online |
| `woow-nginxproxymanager` | Woow Nginx Proxy Manager | 2.12.4-v2 | 本機建置 | Nginx Proxy Manager 的 WOOWTECH 版（與社群版 slug 不同） |
| `woow_ha_code_server` | Woow Code Server | 0.1.6 | 預建映像 | code-server + pi coding agent + Claude Code + ACP 側邊欄（取代原 `vscode` 鏡像） |
| `woow_ha_pi_agent` | Woow HA Pi Agent | 0.14.3 | 預建映像 | pi-web + coding agent SDK + 影音管線 |
| `woow_ha_opendesign` | Woow HA OpenDesign | 0.1.8 | 預建映像 | Ingress-only BYOK 設計工作台 + PDF／圖片／PPTX 匯出 |
| `woow-omnigent` | Woow Omnigent | 0.1.15 | 預建映像 | Omnigent 編排伺服器 + 內建 Postgres（外部 runner 註冊制） |

### 🧩 HA Core 實例
| Slug | 名稱 | Ver | 安裝 | 用途 |
|---|---|---|---|---|
| `woow_ha_core_1..5` | Woowtech HA Core 1-5 | 2.3.0 | 本機建置 | 巢狀 HA Core 實例（每個獨立 onboarding，預設 port 8124-8128） |
| `apporo_ha_core_1..5` | Apporo HA Core 1-5 | 2.3.0 | 本機建置 | Apporo 品牌的巢狀 HA Core 實例。**與同編號的 `woow_ha_core_N` 預設使用相同 host port**，不要同時啟用，或先改其中一個的 port |
| `woow_ha_core` | Home Assistant Core (official image) | 2026.9.1-1 | 本機建置 | 獨立的官方 HA Core 2026.9.1，無品牌改動或預設設定；manifest 標為 **experimental** |

### 🪞 WOOWTECH 鏡像維護（防上游失聯）
| Slug | 名稱 | Ver | 安裝 | 上游 |
|---|---|---|---|---|
| `dnsmasq-dhcp` | Dnsmasq-DHCP | 5.1.0 | 預建映像 | [f18m/ha-addon-dnsmasq-dhcp](https://github.com/f18m/ha-addon-dnsmasq-dhcp) |
| `hamh` | Home-Assistant-Matter-Hub | 2.0.58 | 預建映像 | [riddix/home-assistant-matter-hub](https://github.com/riddix/home-assistant-matter-hub) |
| `frigate` | Frigate | 0.18.0 | 預建映像 | [blakeblackshear/frigate-hass-addons](https://github.com/blakeblackshear/frigate-hass-addons) |
| `jellyfin` | Jellyfin | 0.2.1 | 預建映像 | [hassio-addons/app-jellyfin](https://github.com/hassio-addons/app-jellyfin) |
| `music_assistant` | Music Assistant | 2.10.5 | 預建映像 | [music-assistant.io](https://music-assistant.io) |
| `local_audio` | Local Audio | 0.1.13 | 預建映像 | [music-assistant/local-audio-addon](https://github.com/music-assistant/local-audio-addon)；manifest 標為 **experimental** |
| `netease_cloud_music_api` | NetEase Cloud Music API | 0.1.1 | 本機建置 | [NeteaseCloudMusicApiEnhanced/api-enhanced](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced)（Music Assistant 用） |
| `ytm_po_token_generator` | YT Music PO Token Generator | 2.0.1 | 預建映像 | [Brainicism/bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) |
| `knxd` | KNXD daemon | 0.6.1 | 預建映像 | [da-anda/hass-io-addons](https://github.com/da-anda/hass-io-addons/tree/main/knxd) |
| `ha_mcp` | Home Assistant MCP Server | 7.14.1 | 預建映像（上游 homeassistant-ai 映像） | [homeassistant-ai/ha-mcp](https://github.com/homeassistant-ai/ha-mcp) |
| `ha_mcp_webhook_proxy` | Webhook Proxy for HA MCP | 2.0.4 | 本機建置 | [homeassistant-ai/ha-mcp](https://github.com/homeassistant-ai/ha-mcp) |

## 相依 store（HA 內建，非本 repo）

以下 addon 走 HA 原生 store，本 repo 不打包：
- **Advanced SSH & Web Terminal**, **Mosquitto**, **Node-RED**, **Glances** → 從「Community Add-ons」store 安裝
- **Nginx Proxy Manager**、**Tailscale** 的社群版同樣走 Community store；本 store 另提供 WOOW 版 `woow-nginxproxymanager`、`woow-tailscale`。slug 不同，是不同的 addon，不會自動取代已安裝的社群版
- **File editor**, **Samba share**, **Matter Server**, **ESPHome** → Official/Community store

> Jellyfin 原本要從 Community Apps store 安裝，現已改為本 repo 的 WOOWTECH 鏡像
> （`jellyfin`），不再依賴上游 store。
>
> **Studio Code Server（`vscode`）已於 2026-09-11 下架**，由 WOOWTECH 自有的
> `woow_ha_code_server` 取代。兩者是**不同的 addon**（slug、選項 schema、映像都不同），
> 不是版本升級 —— 已安裝舊 `vscode` 的人不會被自動換掉，但本 store 不再提供它。

## 版本策略與同步

- 每個 App 目錄都從**對應的 WOOWTECH 個別 repo 單向同步**，不在本 repo 直接修改。唯一例外是側欄標題政策 `.github/scripts/sidebar_titles.py`。來源、路徑與政策的對照表在 [`.addon-sync/registry.json`](.addon-sync/registry.json)。
- 流程：
  1. 個別 repo 的 `woow-addon-sync.yml` 確認必要 CI 與各架構映像都通過，再把固定 commit、雜湊與映像 digest 寫進該 repo 的 `woow-addon-sync` 分支。
  2. 本 repo 的 `sync-upstreams.yml` 依 registry 重新驗證：正式 Release、CI、預設分支、各架構映像、防降版、防亂序。
  3. 全部通過後才更新 App 目錄與 [`.addon-sync/catalog.json`](.addon-sync/catalog.json)。
  
  細節見 [`.addon-sync/README.md`](.addon-sync/README.md)。
- **只同步正式 Release**：`odoo18ce`、`woow-hermes`、`woow-nextcloud-office`。其餘跟隨來源 repo 的預設分支。
- 觸發方式（盡力而為，不是即時）：
  - 排程每 5 分鐘一次，錯開整點。此帳號的 GitHub 排程實測常延遲 2–7 小時。
  - 來源 repo 的 `repository_dispatch`，目前 Odoo 發 Release 時會送。
  - 手動執行 workflow。
- 驗證失敗或來源版本較舊時保留現有版本，並在 workflow 頁面以 warning 標示；不會清空目錄。
- 開發／beta／nightly 通道（例如 `music_assistant_beta`、`hamh-alpha`、`ha_mcp_dev`）不會進入本 store。
- `woow-tailscale`：自 2026-10-06（0.1.2）起以個別 repo [`Woow_ha_vpn_tailscale_package`](https://github.com/WOOWTECH/Woow_ha_vpn_tailscale_package) 為權威，已併入原 store 0.1.1 的修正。
- `knxd`：來源是 WOOWTECH 鏡像 repo [`Woow_ha_knxd_add_on`](https://github.com/WOOWTECH/Woow_ha_knxd_add_on)，釘在上游 0.6.1；要升版需先更新鏡像 repo。
- 想單獨安裝：加入對應的**個別 repo URL**（例如 `WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on`）
- 想用單一入口：加入**本 store URL**

## 本機下載（Local Download）

`.addon-sync/download_addon.py` 只需 Python 3 標準函式庫，可把 catalog 中的 App 下載成 HAOS `/addons/` 的 local addon 目錄：

```sh
python3 download_addon.py --list
python3 download_addon.py woow_ha_pi_agent --destination ./local-addons --arch amd64
```

- 驗證 catalog ID、來源封存檔與 manifest 雜湊。
- 拒絕覆寫既有目錄；新下載的目錄一律 manual boot。
- 不會安裝、啟動、升級或解除安裝任何 App。
- 有預建映像的項目會包成固定 digest 的 local Dockerfile，這**不是重新編譯原始碼**；「本機建置」項目則在安裝時 build。

## 授權

各 addon 保留其原始授權：
- WOOWTECH 自主 addon：見各子目錄 LICENSE
- 鏡像 addon（`dnsmasq-dhcp`, `frigate`, `hamh`, `jellyfin`, `knxd`, `music_assistant`, `local_audio`, `netease_cloud_music_api`, `ytm_po_token_generator`, `ha_mcp`, `ha_mcp_webhook_proxy`）：
  各自沿用 upstream 授權。Dnsmasq-DHCP、Frigate（blakeblackshear）與 Jellyfin
  （hassio-addons）皆為 MIT

## 維護

- 維護者：WOOWTECH `<woowtech@designsmart.com.tw>`
- Baseline 目標：HAOS 18.x、HA Core 2026.7.x、amd64 / aarch64
- 各 add-on 的實機驗證狀態以其個別 repository 與 release 紀錄為準
