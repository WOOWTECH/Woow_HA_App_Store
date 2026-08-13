# Woow Nextcloud - Home Assistant Add-on

[Nextcloud](https://nextcloud.com/) 是全球最受歡迎的開源內容協作平台，為數千萬使用者提供檔案同步、分享、協作等功能。

此 Add-on 由 **WOOWTECH** 維護，基於 [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons) 進行修改：
- 將 MariaDB 替換為 **PostgreSQL 16**（效能更佳、相容性更好）
- 移除 SSL/HTTPS（僅使用 HTTP，適用於區域網路 LAN 環境）
- 外部存取建議使用 **Cloudflare Tunnel** 提供 HTTPS

![Nextcloud](https://raw.githubusercontent.com/nextcloud/screenshots/master/nextcloud-hub-files-25-preview.png)

## 架構組成

此 Add-on 為一體式 (All-in-One) 部署，包含：

| 元件 | 版本 | 說明 |
|------|------|------|
| Nextcloud | 33.0.0 | 主程式（基於 LSIO 映像檔） |
| PostgreSQL | 16 | 關聯式資料庫（取代 MariaDB） |
| Redis | 內建 | 快取 / 檔案鎖定（Unix Socket） |
| Nginx | 內建 | 網頁伺服器（來自 LSIO 基礎映像檔） |

## 系統需求

- Home Assistant OS (HAOS) 或 Home Assistant Supervised
- 支援架構：`amd64`、`aarch64`
- 建議至少 2GB RAM
- 磁碟空間視使用者資料量而定

## Installation

To install, click the button below:

[![Open your Home Assistant instance and show the dashboard of an add-on.](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=woow-nextcloud&repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_nextcloud)

Or add the repository manually:

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_nextcloud)

Then navigate to **Settings → Add-ons → Add-on Store**, find "Woow Nextcloud" and click **INSTALL**.

## 快速安裝

1. 在 Home Assistant 中新增此 Add-on 儲存庫
2. 安裝 **Woow Nextcloud**
3. 設定管理員帳號和密碼
4. 啟動 Add-on
5. 點擊 **開啟 Web UI** 進入 Nextcloud

## 設定說明

### 基本設定

| 設定項 | 預設值 | 說明 |
|--------|--------|------|
| `ADMIN_USER` | `admin` | 管理員帳號（首次安裝時使用） |
| `ADMIN_PASS` | — | 管理員密碼（必填） |
| `db_password` | `nextcloud` | PostgreSQL 資料庫密碼 |
| `NEXTCLOUD_DATADIR` | `/share/nextcloud` | 使用者資料存儲路徑 |
| `DEFAULT_PHONE_REGION` | — | 兩碼國家代碼（例如 `TW`） |
| `TZ` | — | 時區（例如 `Asia/Taipei`） |
| `PUID` | `1000` | 執行程序的使用者 ID |
| `PGID` | `1000` | 執行程序的群組 ID |

### 資料庫

此 Add-on 內建 PostgreSQL 16，自動初始化，無需手動設定。

- 資料庫使用者：`nextcloud`
- 資料庫名稱：`nextcloud`
- 資料庫密碼：可透過 `db_password` 設定修改（預設：`nextcloud`）
- 資料存儲路徑：`/config/postgres`
- 僅監聽 localhost，不對外暴露

### 反向代理設定（Cloudflare Tunnel）

此 Add-on 僅提供 HTTP（連接埠 80），外部 HTTPS 存取建議使用 Cloudflare Tunnel：

1. 在 Cloudflare 建立 Tunnel，指向 `http://<ha-ip>:80`
2. 在 Add-on 設定中進行以下配置：

| 設定項 | 範例值 | 說明 |
|--------|--------|------|
| `OVERWRITEPROTOCOL` | `https` | 告訴 Nextcloud 使用 HTTPS |
| `OVERWRITEHOST` | `cloud.example.com` | 外部存取的域名 |
| `OVERWRITECLIURL` | `https://cloud.example.com` | 完整存取 URL |
| `trusted_proxies` | `172.30.33.0/24` | Cloudflare Tunnel 代理 IP |
| `trusted_domains` | `cloud.example.com` | 允許存取的域名 |

### SMTP 郵件設定

設定 SMTP 以啟用 Nextcloud 的郵件通知功能：

| 設定項 | 說明 |
|--------|------|
| `SMTP_HOST` | SMTP 伺服器主機名稱 |
| `SMTP_PORT` | SMTP 連接埠 |
| `SMTP_SECURE` | 加密方式（`STARTTLS` 或 `SSL`） |
| `SMTP_AUTH` | 是否啟用驗證（`true`/`false`） |
| `SMTP_AUTHTYPE` | 驗證類型（`LOGIN` 或 `PLAIN`） |
| `SMTP_USER` | 驗證使用者名稱 |
| `SMTP_PASS` | 驗證密碼 |
| `MAIL_FROM_ADDRESS` | 寄件人（`@` 前的部分） |
| `MAIL_DOMAIN` | 郵件網域（`@` 後的部分） |

### 外部儲存掛載

可透過 `storage_mounts` 設定掛載外部儲存：

```yaml
storage_mounts:
  - path: /mnt/nas
    type: nfs
    mount: "192.168.1.100:/volume1/nextcloud"
    options: "vers=4,soft"
  - path: /mnt/smb
    type: smb
    mount: "//192.168.1.200/share"
    username: "user"
    password: "pass"
```

支援的類型：`local`、`smb`、`cifs`、`nfs`

### 自訂環境變數

可透過 `env_vars` 傳遞額外設定：

```yaml
env_vars:
  - key: "PHP_MEMORY_LIMIT"
    value: "1024M"
  - key: "PHP_UPLOAD_LIMIT"
    value: "16G"
```

## 連接埠說明

| 連接埠 | 服務 | 說明 |
|--------|------|------|
| 80/tcp | HTTP | Nextcloud 網頁介面 |
| 5432/tcp | PostgreSQL | 資料庫（預設不對外暴露） |
| 6379/tcp | Redis | 快取（預設不對外暴露） |

## 備份與還原

- Add-on 使用 **cold backup**（備份前會停止服務）
- 備份範圍包含 `/config`（資料庫資料）和 `/share/nextcloud`（使用者資料）
- 記錄檔 (`**/log`) 不包含在備份中
- 建議定期使用 Home Assistant 的備份功能進行完整備份

## 資料目錄遷移

如需變更 Nextcloud 資料目錄：

1. 停止 Add-on
2. 將資料從舊路徑複製到新路徑
3. 在 Add-on 設定中更新 `NEXTCLOUD_DATADIR`
4. 重新啟動 Add-on

Add-on 會自動偵測路徑變更並執行遷移。

## NAS 儲存

若要將使用者資料儲存在 NAS 上：

1. **首次啟動前**：在 Home Assistant 中新增 `Share` 類型的網路儲存，命名為 `nextcloud`
2. 確保 `NEXTCLOUD_DATADIR` 指向正確的 NAS 路徑（例如 `/share/nextcloud`）
3. 若已安裝，需手動遷移 `/share/nextcloud` 的內容至 NAS

## Office 文件編輯

1. 安裝並啟動 [Collabora CODE](https://github.com/fabio-garavini/hassio-addons) Add-on
2. 在 Nextcloud 中安裝 **Nextcloud Office** 應用程式
3. 前往 `管理設定` > `Office`
4. 選擇 `使用自有伺服器`
5. 輸入 Collabora URL：`http://<your-ha-ip>:9980`
6. 儲存設定

## 疑難排解

### Nextcloud 無法啟動
- 檢查 Add-on 記錄檔中的錯誤訊息
- 確認 PostgreSQL 是否正常啟動（記錄檔中應有 "PostgreSQL is ready"）
- 確認 `db_password` 是否與上次啟動時一致（變更密碼不會自動更新已初始化的資料庫）

### 資料庫連線失敗
- PostgreSQL 資料庫會在 Add-on 啟動時自動初始化
- 若需重置資料庫，刪除 `/config/postgres` 資料夾後重新啟動

### 存取被拒絕
- 確認已將存取域名加入 `trusted_domains`
- 若使用反向代理，確認 `trusted_proxies` 設定正確
- 確認 `OVERWRITEPROTOCOL` 設定與實際存取方式一致

## 與原版差異

| 功能 | 原版 (fabio-garavini) | WOOWTECH 版本 |
|------|----------------------|---------------|
| 資料庫 | MariaDB | PostgreSQL 16 |
| HTTPS | 內建 SSL | HTTP only（搭配 Cloudflare Tunnel） |
| 憑證管理 | 內建 init-keygen | 無（不需要） |
| 資料庫密碼 | 寫死 | 可透過 `db_password` 設定 |
| 中文支援 | 無 | 繁體中文翻譯 |

## 技術細節

### S6-Overlay 服務啟動順序

```
init-os-end
  └── init-adduser
  └── init-addon-config
  └── init-postgres-config
        └── init-postgres-initdb
              └── svc-postgres (longrun)
                    └── init-nextcloud-config
                          └── svc-nginx (longrun)
                          └── svc-redis (longrun)
                          └── svc-php-fpm (longrun)
```

### 檔案結構

```
nextcloud/
├── config.yaml          # Add-on 設定定義
├── build.yaml           # 建置設定
├── addon_info.yaml      # Add-on 資訊
├── Dockerfile           # 容器建置檔
├── DOCS.md              # 使用說明文件
├── CHANGELOG.md         # 變更記錄
├── README.md            # 此文件
├── translations/
│   ├── en.yaml          # 英文翻譯
│   └── zh-Hant.yaml     # 繁體中文翻譯
├── test/
│   ├── options.json     # 測試用設定
│   ├── docker-compose.amd64.yml
│   └── docker-compose.aarch64.yml
├── .common/
│   ├── addon-config/    # HA Add-on 設定處理
│   └── mount-external-storage/  # 外部儲存掛載
└── rootfs/
    ├── etc/
    │   ├── s6-overlay/s6-rc.d/
    │   │   ├── init-adduser/         # 使用者初始化
    │   │   ├── init-addon-config/    # Add-on 設定處理
    │   │   ├── init-postgres-config/ # PostgreSQL 目錄初始化
    │   │   ├── init-postgres-initdb/ # PostgreSQL 資料庫初始化
    │   │   ├── svc-postgres/         # PostgreSQL 服務 (longrun)
    │   │   ├── init-nextcloud-config/ # Nextcloud 初始化/升級
    │   │   ├── svc-redis/            # Redis 服務 (longrun)
    │   │   └── ...
    │   └── nginx/templates/          # Nginx 設定範本
    ├── defaults/
    │   └── redis.conf                # Redis 預設設定
    └── usr/bin/
        └── occ                       # Nextcloud OCC 指令包裝
```

## 授權條款

MIT License

## 致謝

- [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons) — 原始 Nextcloud HA Add-on
- [LinuxServer.io](https://linuxserver.io/) — Nextcloud 基礎映像檔
- [Nextcloud](https://nextcloud.com/) — 開源雲端檔案平台
- [WOOWTECH](https://github.com/WOOWTECH) — 本 Fork 維護者
