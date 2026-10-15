# Woow n8n - Home Assistant Add-on

**WOOWTECH 維護的 n8n Home Assistant 附加元件（HTTP 區網版本）**

基於 [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons/tree/main/n8n) 的分支版本，移除了 SSL/HTTPS 強制需求，適合區域網路內使用 HTTP 存取，對外連線透過 Cloudflare Tunnel 建立 HTTPS 安全通道。

## Installation

To install, click the button below:

[![Open your Home Assistant instance and show the dashboard of an add-on.](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=woow-n8n&repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_n8n)

Or add the repository manually:

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_n8n)

Then navigate to **Settings → Add-ons → Add-on Store**, find "Woow n8n" and click **INSTALL**.

---

## 目錄

- [簡介](#簡介)
- [與上游版本的差異](#與上游版本的差異)
- [系統需求](#系統需求)
- [安裝方式](#安裝方式)
- [設定說明](#設定說明)
- [Cloudflare Tunnel 設定](#cloudflare-tunnel-設定)
- [從 2.12.x 升級到 2.43.x](#從-212x-升級到-243x)
- [安全性說明](#安全性說明)
- [預建映像與發布順序](#預建映像與發布順序)
- [內建元件](#內建元件)
- [目錄結構](#目錄結構)
- [常見問題](#常見問題)
- [致謝](#致謝)
- [授權條款](#授權條款)

---

## 簡介

[n8n](https://n8n.io) 是一個工作流程自動化平台，讓技術團隊能夠結合程式碼的靈活性與無程式碼的開發速度。提供超過 400 個整合套件、原生 AI 功能，以及公平程式碼（fair-code）授權模式，讓您在完全掌控資料與部署的同時建構強大的自動化流程。

### 主要特色

- **400+ 整合套件**：涵蓋各種常用服務與 API
- **原生 AI 功能**：基於 LangChain 的 AI 工作流程
- **JavaScript / Python 支援**：可在工作流程中執行自訂程式碼
- **視覺化編輯器**：拖放式介面建構自動化流程
- **自架部署**：完全掌控您的資料

---

## 與上游版本的差異

本版本從 [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons) 分支而來，主要修改如下：

| 項目 | 上游版本 | WOOWTECH 版本 |
|------|----------|----------------|
| 預設協定 | HTTPS（需 SSL 憑證） | HTTP（區網直接存取） |
| SSL 設定 | 需要 `ssl`、`certfile`、`keyfile` | 已移除，不需設定 |
| 自簽憑證 | 找不到憑證時自動產生 | 不需要 |
| Web UI 網址 | `https://[HOST]:5678` | `http://[HOST]:5678` |
| 對外安全連線 | 自行設定 SSL | 建議使用 Cloudflare Tunnel |
| 翻譯 | 僅英文 | 新增繁體中文（zh-Hant） |
| 時區預設 | UTC | 建議設為 Asia/Taipei |

### 為什麼移除 SSL？

在區域網路（LAN）環境中，HTTP 已足夠安全且設定更簡單。對外連線建議透過 Cloudflare Tunnel 建立 HTTPS 加密通道，好處包括：

1. **免費 SSL 憑證**：Cloudflare 自動管理
2. **無需開放路由器連接埠**：Tunnel 從內部向外連線
3. **DDoS 防護**：Cloudflare 內建防護
4. **簡化管理**：不需自行維護 SSL 憑證

---

## 系統需求

- Home Assistant OS 或 Home Assistant Supervised
- 支援架構：`amd64`、`aarch64`（ARM64）
- 建議至少 2GB RAM

---

## 安裝方式

### 第一步：新增儲存庫

1. 開啟 Home Assistant
2. 前往 **設定** > **附加元件** > **附加元件商店**
3. 點選右上角 **三個點** > **儲存庫**
4. 輸入此儲存庫網址：
   ```
   https://github.com/WOOWTECH/Woow_ha_n8n
   ```
5. 點選 **新增** > **關閉**

### 第二步：安裝附加元件

1. 在附加元件商店中搜尋 **Woow n8n**
2. 點選 **安裝**
3. 等待安裝完成

### 第三步：首次設定

1. 前往附加元件的 **設定** 頁面
2. 設定時區（建議）：
   ```yaml
   TZ: Asia/Taipei
   GENERIC_TIMEZONE: Asia/Taipei
   ```
3. 調整日誌等級（選擇性）：
   ```yaml
   N8N_LOG_LEVEL: info
   ```
4. 點選 **啟動**
5. 點選 **開啟網頁介面** 並完成首次設定精靈

---

## 設定說明

### 可用設定選項

| 選項 | 類型 | 預設值 | 說明 |
|------|------|--------|------|
| `N8N_LOG_LEVEL` | 選項 | `info` | 日誌等級：`error`、`warn`、`info`、`debug` |
| `TZ` | 字串 | （空） | 時區，例如 `Asia/Taipei` |
| `GENERIC_TIMEZONE` | 字串 | （空） | 排程節點使用的時區 |
| `N8N_HOST` | 字串 | （自動偵測） | 主機名稱或 IP |
| `N8N_PATH` | 字串 | `/` | n8n 部署路徑 |
| `N8N_EDITOR_BASE_URL` | URL | （空） | 透過反向代理開啟編輯器時的完整公開 HTTPS URL |
| `N8N_WEBHOOK_URL` | URL | （自動產生） | 公開 Webhook URL（內建 n8n 2.43 使用此設定）；未設定時為 `http://<HA IP>:5678` |
| `WEBHOOK_URL` | URL | （空） | 舊版名稱（已棄用）；若有設定會複製到 `N8N_WEBHOOK_URL`，但 n8n 會出現棄用警告，建議改用新名稱 |
| `N8N_PROXY_HOPS` | 整數 | `1` | n8n 前方可信任的反向代理層數；預設 `1` 同時適用 Cloudflare Tunnel 與 HA Ingress（Ingress nginx 只把用戶端位址交給 n8n） |
| `N8N_SECURE_COOKIE` | 布林 | `false` | HTTP 版本會在啟動時強制有效值為 `false`，避免 n8n 在 `http://` 下阻擋登入 |
| `clean_redis` | 布林 | `false` | 啟動時刪除 Redis 資料檔（`/config/redis/dump.rdb`） |
| `env_vars` | 列表 | `[]` | 自訂環境變數（key-value 對） |

### 自訂環境變數範例

透過 `env_vars` 可傳入任何 n8n 支援的環境變數：

```yaml
env_vars:
  - key: N8N_SMTP_HOST
    value: smtp.gmail.com
  - key: N8N_SMTP_PORT
    value: "465"
  - key: N8N_SMTP_USER
    value: your-email@gmail.com
```

---

## Cloudflare Tunnel 設定

若需從外部網路安全存取 n8n，建議使用 Cloudflare Tunnel。

### 前置需求

- Cloudflare 帳號
- 已在 Cloudflare 上管理的網域
- 已安裝 Cloudflare Tunnel（可透過 HA 的 Cloudflared 附加元件）

### 設定步驟

1. 在 Cloudflare Zero Trust 儀表板中建立 Tunnel
2. 設定 Tunnel 的 Public Hostname：
   - **Subdomain**：例如 `n8n`
   - **Domain**：您的網域
   - **Service Type**：`HTTP`
   - **URL**：`<HA 內部 IP>:5678`
3. 在 n8n 附加元件設定中加入：
   ```yaml
   N8N_HOST: n8n.your-domain.com
   N8N_EDITOR_BASE_URL: https://n8n.your-domain.com
   N8N_WEBHOOK_URL: https://n8n.your-domain.com
   N8N_PROXY_HOPS: 1
   N8N_SECURE_COOKIE: false
   ```
4. 重新啟動附加元件。

設定完成後，完整 n8n UI、REST API、Webhook 與 `/rest/push` WebSocket 都會使用 `https://n8n.your-domain.com`。Cloudflare Tunnel 原生支援 WebSocket，不需額外開放路由器連接埠。

同時，Add-on 的 **Open Web UI** 與 HA 側邊欄會走獨立的 Ingress port 5690。Ingress nginx 依每台 HA 的 `X-Ingress-Path` 動態改寫資產與 n8n `BASE_PATH`。n8n 編輯器的 Vite preload helper 以根路徑組出相依檔案網址，無法辨識已加上 Ingress token 前綴的初始連結，會重複載入樣式表而讓畫面高度塌陷；Ingress nginx 只在 Ingress 回應中把該 helper 的網址產生函式改為使用 `window.BASE_PATH`。自 2.43.6 起，改寫比對的是函式本體 ``function(e){return`/`+e}``，不再依賴每版都會變的壓縮後名稱；`test/test-ingress-bundle-seam.py` 會在每次建置時確認這段程式在實際出貨的 n8n bundle 中只出現一次、且位於 preload helper 內。

由於 Ingress nginx 會改寫 HTML、JavaScript 與 CSS 內容，Ingress port 5690 對這三類回應設定 `Cache-Control: no-store`，避免瀏覽器或 Cloudflare 保存舊版轉換內容；圖片、字型、圖示與其他未改寫的二進位資產保留上游快取政策。公開 Cloudflare n8n 入口仍維持網域根路徑 `/`，直接 port 5678 行為不變。

> **安全提醒：** 此模式會公開完整 n8n 入口，必須完成 n8n 擁有者帳號設定並使用強密碼。若在同一 hostname 啟用 Cloudflare Access，請為 production webhook 路徑設計適當的 Bypass policy，否則第三方服務會收到 Access 登入頁而不是 Webhook 回應。

---

## 從 2.12.x 升級到 2.43.x

Add-on 2.43.6 將內建 n8n 從 2.12.3 升到 2.43.6，更新前請先看完：

- **資料庫遷移是單向、不可逆的。** n8n 2.43.6 第一次啟動時會把資料庫（工作流程、憑證、執行紀錄）遷移到新結構；n8n 2.12.3 無法再使用遷移後的資料庫，沒有降級路徑。
- **更新前必須先做 add-on 備份。** 在 Home Assistant 建立包含本 add-on 的備份（**設定 → 系統 → 備份**，或在更新對話框勾選更新前備份）。備份同時包含 `/config` 的 n8n 資料與 add-on 私有的 `/data`。
- **回滾只能還原備份。** 在已遷移的資料上改裝舊版 add-on 不是回滾；請還原更新前的備份，它會連同未遷移的資料庫一起回到 2.12.x 版 add-on。
- **讓第一次啟動跑完。** 資料庫大時第一次啟動可能要好幾分鐘；日誌出現 `Migrations in progress, please do NOT stop the process.` 時請勿停止或重新啟動 add-on。在 n8n 第一次就緒前，Supervisor watchdog 會得到「啟動中」的回應，不會在遷移途中重啟 add-on（若一小時仍未就緒，才交還給 watchdog 處理）。
- **升級後要重建 n8n API key。** 舊 API key 只帶有建立當時存在的 scope，較新的 scope（例如 n8n 2.30 起的發布工作流程）不在其中，部分 public API 呼叫會回 403。請在 n8n **Settings → n8n API** 建立新 key 並選擇需要的 scope（All／Read only／Custom），更新使用它的工具（例如 **Woow n8n MCP** add-on）後再刪除舊 key。
- **資料夾需要新 key 並註冊實例。** n8n 2.43 的資料夾 API（Woow n8n MCP 的 `n8n_manage_folders` 工具會用到）只接受帶 `folder:*` scope 的 API key，而且實例要先註冊免費 Community 功能（**Settings → Usage and plan**）；2.12 建立的舊 key 即使註冊後也會被拒。
- **Instance-level MCP（選用）。** n8n 2.43 可以直接提供 MCP 伺服器：**Settings → Instance-level MCP → Enable MCP access**，選擇要開放的工作流程，在 **Connection details** 取得 access token。**Woow n8n MCP** add-on 0.2.1 起有對應的選填欄位。

---

## 安全性說明

- **Supervisor token：** add-on 自己的啟動腳本（唯一使用 Supervisor API 的地方）仍使用 `hassio_api`；它執行完後 token 會從容器環境移除，n8n、task runner、nginx 與 Redis 啟動時都沒有 `SUPERVISOR_TOKEN`／`HASSIO_TOKEN`。工作流程無論透過 `$env`、讀檔或讀其他行程都拿不到。
- **`$env` 仍然開放：** 為了不破壞既有使用 `$env` 的工作流程，保留 `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`。能編輯工作流程的人可以讀到你在 `env_vars` 設定的所有變數，包含密碼與 API token。
- **Code 節點沒有限制：** JavaScript／Python Code 節點可匯入任何模組，並以 root 身分在 add-on 容器內執行（維持不變，避免破壞既有工作流程）。因此能編輯工作流程的人可以讀寫 add-on 能存取的所有檔案（`/config`、`/data`、`/share`、`/media`），包含 `/config/.n8n` 內的 n8n 資料庫與加密金鑰，等同能取得所有已儲存的憑證。請只把可編輯工作流程的帳號給你願意交付這些憑證的人，並設定強密碼（尤其是透過 Cloudflare 對外公開編輯器時）。
- **Task broker：** n8n 與 task runner 之間的 broker 只聽 `127.0.0.1`，並使用每台安裝首次啟動時產生的隨機 token（`/data/n8n-runners-auth-token`，僅 root 可讀、會隨備份保存），不再是共用的固定值。
- **日誌：** 名稱含 `PASS`、`PWD`、`SECRET`、`KEY`、`TOKEN`、`AUTH`、`CREDENTIAL`、`PRIVATE`、`DSN`（不分大小寫）的設定值在日誌中一律遮罩，網址中的帳密（`https://user:password@host`）也會移除；設定值不再寫入 `/.env`、`/etc/environment` 或 `~/.bashrc`。

---

## 預建映像與發布順序

Home Assistant Supervisor 安裝時會直接拉取預建且有版本標籤的映像，不會在主機端建構此 Add-on。Add-on 版本為 `X.Y.Z` 時，依主機架構拉取 `ghcr.io/woowtech/woow-ha-n8n-amd64:X.Y.Z` 或 `ghcr.io/woowtech/woow-ha-n8n-aarch64:X.Y.Z`；對應 GHCR 標籤是安裝的必要相依項目。儲存庫管理者必須將這兩個 GHCR package 保持為公開，因為 Supervisor 不會提供 registry 登入憑證。

每個 PR 都會由 **CI** workflow 執行全部測試、建置 amd64 映像並對容器做 smoke test（健康檢查、watchdog、headless 瀏覽器走 Ingress、JavaScript／Python Code 節點、秘密處理）。維護者發布順序：先更新 `n8n/config.yaml` 與 `n8n/CHANGELOG.md` 並合併版本變更至 `main`，等待 **Publish n8n add-on images** 重跑同樣的檢查、發布兩種架構的標籤並建立 Release，最後才公告更新。

已發布的映像標籤不可變更：已安裝的系統與備份都以標籤引用映像。publish workflow 遇到「由其他 commit 建出的既有標籤」會直接失敗、拒絕覆寫。要修正問題請在 `n8n/config.yaml` 升一個版本，切勿重建或重推既有版本；對同一個發布 commit 重跑 workflow 是安全的，只會補發尚未發布的架構。兩種 GHCR 映像尚未可用前，請勿公告或建議使用者安裝該版本。

---

## 內建元件

### n8n（工作流程引擎）

- 連接埠：`5678`（HTTP）
- 資料儲存：SQLite
- Task Runner：支援 JavaScript 與 Python（Python Code 節點使用 n8n runners 映像內建的 CPython 3.13；容器 shell 的 `python3` 是 Alpine 的 3.14）
- n8n 不依賴 Redis：Redis 無法啟動時只影響使用 Redis 的工作流程

### Redis（供工作流程使用）

- 連接埠：`6379`，只聽容器內的 `127.0.0.1`／`::1`（無密碼、protected mode 開啟），HA 與其他 add-on 連不到
- 用途：給工作流程（例如 Redis 節點）以 `localhost:6379` 使用；n8n 本身不使用
- 設定檔位置：`/config/redis/redis.conf`

---

## 目錄結構

```
n8n/
├── .common/
│   └── redis/                    # Redis 設定與服務
├── rootfs/
│   ├── etc/
│   │   ├── n8n-task-runners.json # Task Runner 設定
│   │   └── s6-overlay/s6-rc.d/   # 服務管理
│   │       ├── init-addon-config/ # 環境變數載入
│   │       ├── init-keygen/       # 網路設定與 task broker token 初始化
│   │       ├── svc-n8n/           # n8n 主服務
│   │       ├── svc-runner/        # Task Runner 服務
│   │       └── user/contents.d/   # 服務註冊
│   └── usr/local/bin/
│       ├── woow-n8n-startup-guard # 首次就緒前讓 watchdog 回報「啟動中」
│       ├── check-ssl.sh          # SSL 憑證檢查（保留相容性）
│       └── selfsigned-ssl-gen.sh # 自簽憑證產生（保留相容性）
├── test/                          # 測試（run-tests.sh、容器 smoke、升級 smoke）
├── translations/
│   ├── en.yaml                   # 英文翻譯
│   └── zh-Hant.yaml              # 繁體中文翻譯
├── addon_info.yaml               # 版本追蹤設定
├── CHANGELOG.md                  # 變更日誌
├── config.yaml                   # 附加元件主設定與 GHCR 映像範本
├── Dockerfile                    # 容器映像建構檔
├── DOCS.md                       # 英文說明文件
└── README.md                     # 本檔案
```

---

## 常見問題

### Q：區網存取顯示連線不安全？

A：這是正常的，因為本版本使用 HTTP 而非 HTTPS。區網內 HTTP 已足夠安全。若需要 HTTPS，請設定 Cloudflare Tunnel。

### Q：如何更新 n8n 版本？

A：WOOWTECH 會定期追蹤上游版本並發布更新。您可在 Home Assistant 的附加元件頁面中更新。

### Q：工作流程資料儲存在哪裡？

A：所有資料儲存在 `/config` 目錄中（對應 Home Assistant 的 addon_config），包含：
- SQLite 資料庫（工作流程、憑證等）
- Task Runner 工作目錄
- Redis 資料

### Q：如何備份？

A：此附加元件支援 Home Assistant 的冷備份（cold backup），會在備份前自動停止服務。日誌檔案（logs）會被排除以節省空間。

### Q：Redis 出現問題怎麼辦？

A：在附加元件設定中啟用 `clean_redis: true`，然後重新啟動。這會以全新的 Redis 資料庫啟動。問題解決後請關閉此選項。

### Q：可以使用外部資料庫（PostgreSQL）嗎？

A：可以，透過 `env_vars` 設定相關的資料庫環境變數即可。請參考 [n8n 官方文件](https://docs.n8n.io/hosting/configuration/environment-variables/database/)。

---

## 致謝

- **上游專案**：[fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons) - 原始 n8n HA Add-on
- **n8n**：[n8n-io/n8n](https://github.com/n8n-io/n8n) - 工作流程自動化平台
- **Home Assistant**：[home-assistant](https://www.home-assistant.io/) - 智慧家庭平台

---

## 授權條款

本專案基於 MIT 授權條款發布。

原始程式碼來自 [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons)，同樣使用 MIT 授權。

n8n 本身使用 [Sustainable Use License](https://github.com/n8n-io/n8n/blob/master/LICENSE.md)。
