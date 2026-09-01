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
| `N8N_WEBHOOK_URL` | URL | （空） | n8n 2.35+ 使用的公開 Webhook URL；會與舊版設定自動同步 |
| `WEBHOOK_URL` | URL | （自動產生） | n8n 2.35 以前使用的 Webhook URL；會與新版設定自動同步 |
| `N8N_PROXY_HOPS` | 整數 | （空） | n8n 前方可信任的反向代理層數；標準 Cloudflare Tunnel 設為 `1` |
| `N8N_SECURE_COOKIE` | 布林 | `false` | 區域網路 HTTP 預設停用；僅透過 HTTPS 存取時應設為 `true` |
| `clean_redis` | 布林 | `false` | 啟動時清除 Redis 快取 |
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
   WEBHOOK_URL: https://n8n.your-domain.com
   N8N_PROXY_HOPS: 1
   N8N_SECURE_COOKIE: true
   ```
4. 重新啟動附加元件。

設定完成後，完整 n8n UI、REST API、Webhook 與 `/rest/push` WebSocket 都會使用 `https://n8n.your-domain.com`。Cloudflare Tunnel 原生支援 WebSocket，不需額外開放路由器連接埠。

> **安全提醒：** 此模式會公開完整 n8n 入口，必須完成 n8n 擁有者帳號設定並使用強密碼。若在同一 hostname 啟用 Cloudflare Access，請為 production webhook 路徑設計適當的 Bypass policy，否則第三方服務會收到 Access 登入頁而不是 Webhook 回應。

---

## 內建元件

### n8n（工作流程引擎）

- 連接埠：`5678`（HTTP）
- 資料儲存：SQLite
- Task Runner：支援 JavaScript 與 Python

### Redis（快取與通知）

- 連接埠：`6379`（僅內部存取）
- 用途：即時通知與快取
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
│   │       ├── init-keygen/       # 網路設定初始化
│   │       ├── svc-n8n/           # n8n 主服務
│   │       ├── svc-runner/        # Task Runner 服務
│   │       └── user/contents.d/   # 服務註冊
│   └── usr/local/bin/
│       ├── check-ssl.sh          # SSL 憑證檢查（保留相容性）
│       └── selfsigned-ssl-gen.sh # 自簽憑證產生（保留相容性）
├── test/                          # 測試用 Docker Compose
├── translations/
│   ├── en.yaml                   # 英文翻譯
│   └── zh-Hant.yaml              # 繁體中文翻譯
├── addon_info.yaml               # 版本追蹤設定
├── build.yaml                    # 建構設定
├── CHANGELOG.md                  # 變更日誌
├── config.yaml                   # 附加元件主設定
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
