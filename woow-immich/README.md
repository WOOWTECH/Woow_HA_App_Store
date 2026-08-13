# Woow Immich - Home Assistant Add-on

**WOOWTECH 維護的 Immich Home Assistant 附加元件（HTTP 區網版本）**

基於 [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons/tree/main/immich) 的分支版本，移除了 SSL/HTTPS 強制需求，適合區域網路內使用 HTTP 存取，對外連線透過 Cloudflare Tunnel 建立 HTTPS 安全通道。

![main screenshot](https://github.com/immich-app/immich/raw/main/design/immich-screenshots.png)


## Installation

To install, click the button below:

[![Open your Home Assistant instance and show the dashboard of an add-on.](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=woow-immich&repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_immich)

Or add the repository manually:

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_immich)

Then navigate to **Settings → Add-ons → Add-on Store**, find "Woow Immich" and click **INSTALL**.

---

## 目錄

- [簡介](#簡介)
- [與上游版本的差異](#與上游版本的差異)
- [系統需求](#系統需求)
- [安裝方式](#安裝方式)
- [設定說明](#設定說明)
- [Cloudflare Tunnel 設定](#cloudflare-tunnel-設定)
- [內建元件](#內建元件)
- [儲存管理](#儲存管理)
- [外部儲存掛載](#外部儲存掛載)
- [NAS 儲存設定](#nas-儲存設定)
- [媒體庫遷移](#媒體庫遷移)
- [資料庫備份還原](#資料庫備份還原)
- [常見問題](#常見問題)
- [致謝](#致謝)
- [授權條款](#授權條款)

---

## 簡介

[Immich](https://immich.app) 是一個高效能的自架照片與影片管理解決方案，旨在取代商業雲端服務。本附加元件提供完整的一體化媒體管理生態系統，具備 AI 驅動功能。

### 主要特色

- **自動備份**：從手機/網頁客戶端同步
- **AI 智慧搜尋**：物件/場景辨識、人臉辨識
- **時間軸檢視**：按時間排列的媒體組織
- **共享相簿**：協作式照片管理
- **RAW 支援**：專業攝影工作流程
- **機器學習**：基於 TensorFlow 的辨識引擎

---

## 與上游版本的差異

本版本從 [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons) 分支而來，主要修改如下：

| 項目 | 上游版本 | WOOWTECH 版本 |
|------|----------|----------------|
| 預設協定 | HTTPS（需 SSL 憑證） | HTTP（區網直接存取） |
| SSL 設定 | 需要 `ssl`、`certfile`、`keyfile` | 已移除，不需設定 |
| 自簽憑證 | 找不到憑證時自動產生 | 不需要 |
| Web UI 網址 | `https://[HOST]:8080` | `http://[HOST]:8080` |
| 對外安全連線 | 自行設定 SSL | 建議使用 Cloudflare Tunnel |
| 翻譯 | 僅英文 | 新增繁體中文（zh-Hant） |
| SSL volume 掛載 | 需要掛載 `/ssl` | 不需要 |
| Nginx 反向代理 | 支援 SSL/HTTP 切換 | 固定 HTTP |

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
- 建議至少 4GB RAM（機器學習功能需要較多記憶體）
- 建議使用 SSD 以獲得更好的效能

---

## 安裝方式

### 第一步：新增儲存庫

1. 開啟 Home Assistant
2. 前往 **設定** > **附加元件** > **附加元件商店**
3. 點選右上角 **三個點** > **儲存庫**
4. 輸入此儲存庫網址：
   ```
   https://github.com/WOOWTECH/Woow_ha_immich
   ```
5. 點選 **新增** > **關閉**

### 第二步：安裝附加元件

1. 在附加元件商店中搜尋 **Woow Immich**
2. 點選 **安裝**
3. 等待安裝完成（映像檔較大，需要一些時間）

### 第三步：首次設定

1. 前往附加元件的 **設定** 頁面
2. 設定時區：
   ```yaml
   TZ: Asia/Taipei
   ```
3. 選擇儲存類型（SSD 或 HDD）
4. 點選 **啟動**
5. 點選 **開啟網頁介面** 並完成首次設定精靈

---

## 設定說明

### 可用設定選項

| 選項 | 類型 | 預設值 | 說明 |
|------|------|--------|------|
| `PUID` | 整數 | `0` | 執行 Immich 的使用者 ID |
| `PGID` | 整數 | `0` | 執行 Immich 的群組 ID |
| `TZ` | 字串 | `Etc/UTC` | 時區，建議 `Asia/Taipei` |
| `IMMICH_LOG_LEVEL` | 選項 | `log` | 日誌等級：`verbose`/`debug`/`log`/`warn`/`error` |
| `DB_STORAGE_TYPE` | 選項 | `HDD` | 儲存類型：`SSD` 或 `HDD` |
| `MACHINE_LEARNING_MODEL_TTL` | 整數 | `300` | ML 模型閒置保留時間（秒），`0` = 永不卸載 |
| `MACHINE_LEARNING_WORKERS` | 整數 | (空) | ML 工作程序數量 |
| `MACHINE_LEARNING_WORKER_TIMEOUT` | 整數 | `300` | ML 工作程序逾時（秒） |
| `IMMICH_TRUSTED_PROXIES` | 字串 | `172.30.32.0/23` | 受信任代理 IP |
| `IMMICH_MEDIA_LOCATION` | 路徑 | `/media/immich` | 媒體儲存位置 |
| `storage_mounts` | 列表 | `[]` | 外部儲存掛載 |
| `clean_redis` | 布林 | (空) | 啟動時清除 Redis |
| `APPLY_PERMISSIONS` | 布林 | `false` | 啟動時套用檔案權限 |
| `backup_location` | 字串 | (空) | PostgreSQL 備份位置 |
| `restore_backup` | 布林 | `false` | 是否還原備份 |
| `delete_db` | 布林 | (空) | 刪除資料庫（僅還原時使用） |
| `env_vars` | 列表 | `[]` | 自訂環境變數 |

### 網路連接埠

| 連接埠 | 服務 |
|--------|------|
| `8080/tcp` | Immich 網頁介面（HTTP） |
| `5432/tcp` | PostgreSQL 資料庫 |
| `6379/tcp` | Redis 資料庫 |

---

## Cloudflare Tunnel 設定

若需從外部網路安全存取 Immich，建議使用 Cloudflare Tunnel。

### 設定步驟

1. 在 Cloudflare Zero Trust 儀表板中建立 Tunnel
2. 設定 Tunnel 的 Public Hostname：
   - **Subdomain**：例如 `immich`
   - **Domain**：您的網域
   - **Service Type**：`HTTP`
   - **URL**：`<HA 內部 IP>:8080`
3. 在 Immich 管理介面中設定外部 URL
4. 重新啟動附加元件

設定完成後，您可透過 `https://immich.your-domain.com` 從外部安全存取 Immich。

**手機 App 設定**：在 Immich 手機 App 中，伺服器位址請填入 Cloudflare Tunnel 的 HTTPS 網址。

---

## 內建元件

### Immich 核心 + 機器學習

- 連接埠：`2283`（內部），透過 Nginx 反向代理至 `8080`
- 支援物件辨識、場景辨識、人臉辨識
- 資料快取：`/data/cache`

### PostgreSQL + VectorChord

- 版本：PostgreSQL 16
- 向量搜尋擴充：VectorChord + pgvecto.rs
- 資料目錄：`/config/postgres`
- 通訊方式：Unix Socket（效能更好）

### Redis

- 連接埠：`6379`
- 通訊方式：Unix Socket (`/var/run/redis/redis.sock`)
- 設定檔：`/config/redis/redis.conf`

### Nginx

- 連接埠：`8080`（HTTP）
- 角色：反向代理，將外部請求轉發至 Immich 核心

---

## 儲存管理

### Immich 媒體庫

- 預設儲存在 `/media/immich`（由 `IMMICH_MEDIA_LOCATION` 設定）
- 若要包含在附加元件備份中，可改為 `/config/library`（注意：這會大幅增加備份大小）
- **請勿**手動移動或修改此資料夾中的檔案，應透過 Immich 介面管理

### 外部媒體庫

- 可將照片/影片儲存在掛載於以下路徑的外部資料夾：
  - `/media`
  - `/share`
  - `/mnt`（透過 storage_mounts）

---

## 外部儲存掛載

### 掛載硬碟

1. 將硬碟連接到 Home Assistant 伺服器
2. 啟動 Immich 並查看日誌中的磁碟資訊
3. 在 `storage_mounts` 中新增：
   ```yaml
   - type: local
     mount: sda          # 磁碟裝置名稱
     path: storage       # 掛載到 /mnt/storage
     auto_format: true   # 格式化為 ext4
     erase: true
   ```
4. 啟動後依照日誌提示更新設定（改用 UUID）
5. 更新後務必關閉 `auto_format` 和 `erase`

---

## NAS 儲存設定

### 方式一：透過 Home Assistant 儲存掛載

1. 停止 Immich
2. 前往 **Supervisor** > **系統** > **儲存**
3. 新增網路儲存（SMB 或 NFS）
4. 更新 `IMMICH_MEDIA_LOCATION` 為 `/<usage>/<name>`
5. 啟動 Immich

### 方式二：透過附加元件設定

SMB 範例：
```yaml
storage_mounts:
  - type: smb
    mount: //192.168.1.242/photos
    path: immich-nas
    username: user
    password: password
```

NFS 範例：
```yaml
storage_mounts:
  - type: nfs
    mount: 192.168.1.242:/storage/photos
    path: immich-nfs
```

---

## 媒體庫遷移

若要將媒體庫搬移到新位置：

1. 確保新資料夾為空或不存在
2. 修改 `IMMICH_MEDIA_LOCATION` 為新路徑
3. 啟動 Immich，系統會自動執行遷移

支援的路徑：`/media/`、`/share/`、`/config/library`、`/mnt/`（外部掛載）

---

## 資料庫備份還原

### 手動還原 PostgreSQL 備份

1. 確保已透過 [Immich 傾印](https://docs.immich.app/administration/backup-and-restore/#trigger-dump) 建立備份
2. 將備份檔案放置於 Home Assistant 可存取的路徑
3. 在設定中：
   - 設定 `backup_location` 為備份檔路徑（如 `/media/immich/backups/backup.sql.gz`）
   - 啟用 `restore_backup`
   - 啟用 `delete_db` 和 `clean_redis`
4. 啟動 Immich 並查看日誌
5. 還原完成後，**務必停用** `restore_backup`、`delete_db` 和 `clean_redis`

---

## 常見問題

### Q：區網存取顯示連線不安全？

A：本版本使用 HTTP，瀏覽器可能會顯示「不安全」提示，但在區網內這是正常的。若需 HTTPS，請設定 Cloudflare Tunnel。

### Q：機器學習處理速度很慢？

A：考慮預載機器學習模型以加速處理。注意這會使用更多記憶體。也可增加 `MACHINE_LEARNING_WORKERS` 數量。

### Q：上傳失敗？

A：檢查儲存空間是否足夠，以及檔案權限是否與 `PUID`/`PGID` 設定一致。

### Q：手機 App 無法連線？

A：
- 區網：使用 `http://<HA IP>:8080`
- 外網：使用 Cloudflare Tunnel 的 HTTPS 網址

### Q：如何備份？

A：此附加元件支援 Home Assistant 的冷備份（cold backup），備份前會自動停止服務。快取和日誌會被排除。

### Q：Redis 出現問題怎麼辦？

A：在設定中啟用 `clean_redis`，重新啟動後再關閉此選項。

---

## 致謝

- **上游專案**：[fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons) - 原始 Immich HA Add-on
- **Immich**：[immich-app/immich](https://github.com/immich-app/immich) - 照片與影片管理平台
- **ImageGenius**：[imagegenius/docker-immich](https://github.com/imagegenius/docker-immich) - Docker 基礎映像
- **Home Assistant**：[home-assistant](https://www.home-assistant.io/) - 智慧家庭平台

---

## 授權條款

本專案基於 MIT 授權條款發布。

原始程式碼來自 [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons)，同樣使用 MIT 授權。

Immich 本身使用 [AGPL-3.0 License](https://github.com/immich-app/immich/blob/main/LICENSE)。
