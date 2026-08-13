# Woow Nextcloud - Home Assistant Add-on

[Nextcloud](https://nextcloud.com/) 是全球最受歡迎的開源內容協作平台。

此 Add-on 為 WOOWTECH 基於 [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons) 的 Fork 版本，
將 MariaDB 替換為 PostgreSQL 16，並移除 SSL 以適用於區域網路 (LAN) 環境。

## 安裝說明

1. 安裝 **Woow Nextcloud** Add-on
2. 設定管理員 `帳號` 和 `密碼`
3. （選填）設定 `db_password` 修改 PostgreSQL 資料庫密碼
4. （選填）設定 `覆寫 URL` 為你存取 Nextcloud 的 URL，例如：`https://cloud.example.com`
5. 啟動 Nextcloud
6. 開啟 Web UI

## 資料庫

此 Add-on 內建 PostgreSQL 16 資料庫，無需額外安裝或設定。

- 預設資料庫使用者：`nextcloud`
- 預設資料庫密碼：`nextcloud`（可透過 `db_password` 設定修改）
- 預設資料庫名稱：`nextcloud`
- 資料庫資料存儲於：`/config/postgres`

## 設定說明

### 基本設定

- `ADMIN_USER`：管理員帳號（首次安裝時使用）
- `ADMIN_PASS`：管理員密碼
- `db_password`：PostgreSQL 資料庫密碼（預設：`nextcloud`）
- `NEXTCLOUD_DATADIR`：Nextcloud 資料目錄（預設：`/share/nextcloud`）
- `DEFAULT_PHONE_REGION`：兩碼國家代碼，例如：`TW`（台灣）

### 反向代理設定（Cloudflare Tunnel）

若透過 Cloudflare Tunnel 或其他反向代理存取：

1. `OVERWRITEPROTOCOL`：設為 `https`
2. `OVERWRITEHOST`：設為你的域名，例如 `cloud.example.com`
3. `OVERWRITECLIURL`：設為完整 URL，例如 `https://cloud.example.com`
4. `trusted_proxies`：加入反向代理的 IP 位址
5. `trusted_domains`：加入你的域名

### SMTP 郵件設定

設定 SMTP 可啟用 Nextcloud 的郵件通知功能：

- `SMTP_HOST`：SMTP 伺服器
- `SMTP_PORT`：SMTP 連接埠
- `SMTP_SECURE`：加密方式（`STARTTLS` 或 `SSL`）
- `SMTP_AUTH`：是否啟用驗證
- `SMTP_USER` / `SMTP_PASS`：驗證憑證
- `MAIL_FROM_ADDRESS`：寄件人（`@` 前的部分）
- `MAIL_DOMAIN`：郵件網域（`@` 後的部分）

## Office 文件編輯

1. 安裝 `Collabora CODE` Add-on 並啟動
2. 開啟 Nextcloud，安裝 `Nextcloud Office` 應用程式
3. 前往 `管理設定` > `Office`，選擇 `使用自有伺服器`
4. 輸入 Collabora URL：`http://<your-ha-ip>:9980`
5. 儲存設定即可使用

## 外部儲存

掛載在 `/media` 或 `/share` 下的資料夾或網路儲存，皆可在 Add-on 內透過 **External Storage** 應用程式存取。

## NAS 儲存

若要將資料儲存在 NAS 上，請在 **首次啟動 Nextcloud 之前** 設定好 `Share` 類型的網路儲存（名稱為 `nextcloud`），
否則需要手動將 `/share/nextcloud` 資料夾的內容遷移至 NAS。

也可透過 `storage_mounts` 設定項目掛載 SMB/CIFS 或 NFS 儲存。

## 權限設定

可透過 `PUID` 和 `PGID` 設定來變更資料夾擁有者的使用者和群組 ID。
例如掛載 NFS 共享時，可依需求調整這些值以匹配 NFS 伺服器上的權限設定。

## 自訂環境變數

透過 `env_vars` 可傳遞額外的環境變數至容器：

```yaml
env_vars:
  - key: "PHP_MEMORY_LIMIT"
    value: "1024M"
  - key: "PHP_UPLOAD_LIMIT"
    value: "16G"
```
