# Woow Nginx Proxy Manager - Home Assistant Add-on

[Nginx Proxy Manager](https://nginxproxymanager.com/) (NPM) 是一個簡單而強大的反向代理管理工具，
讓你無需深入了解 Nginx 或 Let's Encrypt，即可輕鬆管理反向代理主機並取得免費 SSL 憑證。

此 Add-on 由 **WOOWTECH** 維護，基於 [hassio-addons/addon-nginx-proxy-manager](https://github.com/hassio-addons/addon-nginx-proxy-manager) 進行 Fork。

![Nginx Proxy Manager](https://nginxproxymanager.com/screenshots/proxy-hosts.png)

## Installation

To install, click the button below:

[![Open your Home Assistant instance and show the dashboard of an add-on.](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=woow-nginxproxymanager&repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_nginxpm)

Or add the repository manually:

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_nginxpm)

Then navigate to **Settings → Add-ons → Add-on Store**, find "Woow Nginx Proxy Manager" and click **INSTALL**.

## 架構組成

此 Add-on 為一體式 (All-in-One) 部署，包含：

| 元件 | 版本 | 說明 |
|------|------|------|
| Nginx Proxy Manager | 2.12.4 | 反向代理管理介面 |
| Nginx | 1.28.0 | 反向代理伺服器 |
| Node.js | 22.16.0 | NPM 後端執行環境 |
| Certbot | 4.0.0 | Let's Encrypt SSL 憑證管理 |
| SQLite | 內建 | 設定資料庫 |

## 系統需求

- Home Assistant OS (HAOS) 或 Home Assistant Supervised
- 支援架構：`amd64`、`aarch64`
- 建議至少 512MB RAM
- 需要連接埠 80、81、443

## 快速安裝

1. 在 Home Assistant 中新增此 Add-on 儲存庫
2. 安裝 **Woow Nginx Proxy Manager**
3. 啟動 Add-on
4. 點擊 **開啟 Web UI** 進入管理介面（連接埠 81）
5. 使用預設帳號登入：
   - **帳號**: `admin@example.com`
   - **密碼**: `changeme`
6. **首次登入後立即修改密碼**

## 連接埠說明

| 連接埠 | 服務 | 說明 |
|--------|------|------|
| 80/tcp | HTTP | HTTP 入口（反向代理流量） |
| 81/tcp | Admin | NPM 管理介面 |
| 443/tcp | HTTPS | HTTPS/SSL 入口（反向代理流量） |

## 功能說明

### 1. 反向代理主機 (Proxy Hosts)

將外部域名轉發到內部服務。在 NPM 管理介面中：

1. 點擊 **Proxy Hosts** > **Add Proxy Host**
2. 填寫域名（例如 `nextcloud.example.com`）
3. 填寫內部服務的 IP 和連接埠（例如 `192.168.1.100:80`）
4. 選擇性啟用 SSL（Let's Encrypt 自動憑證）

常見設定範例：

| 域名 | 目標 | 說明 |
|------|------|------|
| `cloud.example.com` | `192.168.1.100:80` | Nextcloud |
| `grafana.example.com` | `192.168.1.100:3000` | Grafana |
| `ha.example.com` | `192.168.1.100:8123` | Home Assistant |
| `n8n.example.com` | `192.168.1.100:5678` | n8n 自動化 |

### 2. SSL 憑證管理

#### Let's Encrypt 免費憑證
- 支援 HTTP-01 Challenge（需要連接埠 80 對外開放）
- 支援 DNS-01 Challenge（無需對外開放連接埠）
  - Cloudflare
  - Route 53
  - DigitalOcean
  - 等其他 DNS 提供商
- 自動續期

#### 自訂 SSL 憑證
- 上傳自己的 SSL 憑證
- 適用於內部 CA 或付費憑證

### 3. 存取控制清單 (Access Lists)

保護你的反向代理主機：
- **基本驗證**：設定使用者名稱和密碼
- **IP 白名單**：僅允許特定 IP 存取
- **IP 黑名單**：封鎖特定 IP

### 4. 重導向主機 (Redirection Hosts)

將一個域名重導向到另一個 URL：
- 支援 301（永久重導向）
- 支援 302（暫時重導向）
- 可啟用 SSL

### 5. TCP/UDP 串流轉發 (Streams)

轉發非 HTTP 的 TCP/UDP 流量：
- 資料庫連線（PostgreSQL、MySQL 等）
- SSH 連線
- 其他 TCP/UDP 服務

### 6. 自訂 Nginx 設定

進階使用者可在每個主機中加入自訂的 Nginx 指令，例如：
- 自訂 `proxy_set_header`
- 調整緩衝區大小
- 設定速率限制
- WebSocket 支援

## 設定說明

此 Add-on **不需要額外設定**。所有管理操作都在 Web UI（連接埠 81）中完成。

## 資料存儲

所有設定資料存儲在 Home Assistant 的 Add-on 設定目錄：

```
/config/addon_nginx-proxy-manager/
├── database.sqlite                 # 設定資料庫
├── keys.json                       # API 加密金鑰
├── nginx/
│   ├── proxy_host/                 # 反向代理設定（自動生成）
│   ├── redirection_host/           # 重導向設定（自動生成）
│   ├── dead_host/                  # 已停用的主機設定
│   ├── stream/                     # TCP/UDP 串流設定
│   ├── default_host/               # 預設主機設定
│   ├── custom/                     # 自訂 Nginx 設定
│   ├── dummycert.pem               # 啟動用虛擬 SSL 憑證
│   └── dummykey.pem                # 啟動用虛擬 SSL 金鑰
├── letsencrypt/                    # Let's Encrypt SSL 憑證
├── custom_ssl/                     # 自訂 SSL 憑證
├── access/                         # 存取控制清單
└── logs/                           # 記錄檔
```

## 備份與還原

- Add-on 支援 Home Assistant 的備份功能
- 記錄檔 (`*/logs`) 不包含在備份中
- 備份包含所有設定、SSL 憑證和資料庫

## 搭配 Cloudflare Tunnel 使用

NPM 可與 Cloudflare Tunnel 搭配使用：

### 方案一：NPM 處理 SSL（傳統方式）
1. 路由器轉發連接埠 80 和 443 到 Home Assistant
2. NPM 管理 Let's Encrypt 憑證
3. NPM 反向代理到內部服務

### 方案二：Cloudflare Tunnel + NPM（推薦）
1. Cloudflare Tunnel 處理外部 HTTPS
2. NPM 作為內部反向代理
3. 不需要在路由器上轉發連接埠
4. 額外的 Cloudflare 安全防護（DDoS、WAF 等）

設定步驟：
1. 安裝 Cloudflare Tunnel Add-on
2. 建立 Tunnel，設定 `Service` 為 `http://<ha-ip>:80`
3. 在 NPM 中建立對應的 Proxy Host
4. Cloudflare 處理外部域名到 Tunnel 的連線
5. NPM 處理內部的反向代理路由

## 路由器設定（不使用 Cloudflare Tunnel 時）

如果不使用 Cloudflare Tunnel，需要在路由器上設定連接埠轉發：

| 外部連接埠 | 內部連接埠 | 目標 IP | 協定 |
|------------|------------|---------|------|
| 80 | 80 | Home Assistant IP | TCP |
| 443 | 443 | Home Assistant IP | TCP |

## 疑難排解

### NPM 無法啟動
- 檢查 Add-on 記錄檔中的錯誤訊息
- 確認連接埠 80、81、443 沒有被其他服務佔用
- 嘗試重新啟動 Add-on

### SSL 憑證申請失敗
- 確認域名已正確解析到你的公開 IP
- 確認連接埠 80 已開放（HTTP-01 Challenge）
- 或使用 DNS-01 Challenge（不需要開放連接埠）
- 檢查 Let's Encrypt 的速率限制

### 無法存取代理的服務
- 確認目標服務正在運行
- 確認目標 IP 和連接埠正確
- 檢查 Home Assistant 的防火牆設定
- 確認域名已正確解析

### 管理介面無法存取
- 確認 Add-on 已啟動
- 嘗試存取 `http://<ha-ip>:81`
- 檢查連接埠 81 是否被防火牆阻擋

## 技術細節

### S6-Overlay 服務啟動順序

```
init-npm (oneshot) → npm (longrun, port 81)
init-nginx (oneshot) → nginx (longrun, port 80/443)
                  ↑
                  └── depends on npm
```

### 服務說明

| 服務 | 類型 | 說明 |
|------|------|------|
| init-npm | oneshot | 建立目錄結構、生成虛擬 SSL 憑證 |
| npm | longrun | Node.js NPM 後端（管理介面） |
| init-nginx | oneshot | 注入 HA DNS 解析器 |
| nginx | longrun | Nginx 反向代理伺服器 |

### 檔案結構

```
woow-nginxproxymanager/
├── config.yaml              # Add-on 設定定義
├── build.yaml               # 建置設定
├── addon_info.yaml          # Add-on 資訊
├── Dockerfile               # 容器建置檔
├── DOCS.md                  # 使用說明文件
├── CHANGELOG.md             # 變更記錄
├── README.md                # 此文件
├── translations/
│   ├── en.yaml              # 英文翻譯
│   └── zh-Hant.yaml         # 繁體中文翻譯
├── patches/                 # NPM 相容性修補
│   ├── 0001-patch-data-to-config-and-logs-to-stdout.patch
│   ├── 0002-Patch-redirect-logs-to-docker-output.patch
│   ├── 0003-Patch-npm-certbot-venv-plugin-handling.patch
│   ├── 0004-replace-node-sass-with-sass.patch
│   ├── 0005-update-sass-loader-config.patch
│   └── 0006-fix-cloudflare-dependency-conflict.patch
├── test/
│   ├── options.json         # 測試用設定
│   ├── docker-compose.amd64.yml
│   └── docker-compose.aarch64.yml
└── rootfs/
    ├── etc/
    │   ├── letsencrypt.ini  # Certbot 設定
    │   ├── nginx/conf.d/include/
    │   │   └── resolvers.conf   # DNS 解析器設定
    │   └── s6-overlay/s6-rc.d/
    │       ├── init-nginx/      # Nginx 初始化
    │       ├── init-npm/        # NPM 初始化
    │       ├── nginx/           # Nginx 服務 (longrun)
    │       └── npm/             # NPM 服務 (longrun)
    └── var/www/html/
        └── index.html           # 預設 HTML 頁面
```

### 修補說明

此 Add-on 對上游 Nginx Proxy Manager 套用了以下修補：

1. **Patch 1**: 將資料路徑從 `/data` 改為 `/config`（HA 標準）
2. **Patch 2**: 將記錄輸出重導向到 Docker stdout
3. **Patch 3**: 修正 Certbot 虛擬環境處理
4. **Patch 4**: 將 `node-sass` 替換為 `sass`
5. **Patch 5**: 更新 sass-loader 設定
6. **Patch 6**: 修正 Cloudflare 相依性衝突

## 與原版差異

| 功能 | 原版 (hassio-addons) | WOOWTECH 版本 |
|------|---------------------|---------------|
| 架構支援 | amd64 / aarch64 / armv7 | amd64 / aarch64 |
| 品牌 | Community Add-ons | WOOWTECH |
| 中文支援 | 無 | 繁體中文翻譯及文件 |
| Code Notary | 啟用 | 移除 |
| 功能 | 完全相同 | 完全相同 |

## 授權條款

MIT License

## 致謝

- [hassio-addons/addon-nginx-proxy-manager](https://github.com/hassio-addons/addon-nginx-proxy-manager) — 原始 NPM HA Add-on (Franck Nijhof)
- [NginxProxyManager/nginx-proxy-manager](https://github.com/NginxProxyManager/nginx-proxy-manager) — Nginx Proxy Manager 專案
- [WOOWTECH](https://github.com/WOOWTECH) — 本 Fork 維護者
