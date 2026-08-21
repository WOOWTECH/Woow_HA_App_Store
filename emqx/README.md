# Woow EMQX - Home Assistant Add-on

[EMQX](https://www.emqx.io/) 是一個開源的高效能即時訊息處理引擎，為大規模 IoT 設備提供事件串流能力。
作為最具擴展性的 MQTT Broker，EMQX 可連接任何設備、任何規模——包括你的智慧家庭。

此 Add-on 由 **WOOWTECH** 維護，基於 [hassio-addons/addon-emqx](https://github.com/hassio-addons/addon-emqx) 進行 Fork。
EMQX 是 Home Assistant 中 Mosquitto MQTT Broker 的進階替代方案，提供圖形化管理介面。

## Installation

To install, click the button below:

[![Open your Home Assistant instance and show the dashboard of an add-on.](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=woow-emqx&repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_emqx)

Or add the repository manually:

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_emqx)

Then navigate to **Settings → Add-ons → Add-on Store**, find "Woow EMQX" and click **INSTALL**.

## 架構組成

| 元件 | 版本 | 說明 |
|------|------|------|
| EMQX | 5.8.9 | MQTT Broker |
| Erlang/OTP | 內建 | EMQX 執行環境 |
| SQLite | 內建 | 內部設定存儲 |

## 系統需求

- Home Assistant OS (HAOS) 或 Home Assistant Supervised
- 支援架構：`amd64`、`aarch64`
- 建議至少 512MB RAM
- 需要主機網路模式 (host_network)

## 快速安裝

1. 在 Home Assistant 中新增此 Add-on 儲存庫
2. 安裝 **Woow EMQX**
3. 啟動 Add-on
4. 點擊 **開啟 Web UI** 進入 EMQX Dashboard
5. 使用預設帳號登入：
   - **使用者名稱**: `admin`
   - **密碼**: `public`
6. **務必先設定 MQTT 驗證機制**

## 連接埠說明

此 Add-on 使用主機網路模式，直接使用 Home Assistant 主機的連接埠：

| 連接埠 | 協定 | 說明 |
|--------|------|------|
| 1883 | MQTT | 標準 MQTT 連線 |
| 8083 | MQTT/WS | MQTT over WebSocket |
| 8084 | MQTT/WSS | MQTT over 安全 WebSocket |
| 8883 | MQTTS | MQTT over SSL/TLS |
| 18083 | HTTP | EMQX Dashboard（管理介面） |

## 首次設定

### 1. 設定驗證機制（必要）

首次登入 EMQX Dashboard 後，**必須**先設定 MQTT 驗證：

1. 前往 **Access Control** → **Authentication**
2. 點擊 **Create**
3. 選擇驗證方式（建議 **Password-Based** → **Built-in Database**）
4. 完成建立
5. 新增 MQTT 使用者帳號和密碼

### 2. 設定 Home Assistant MQTT 整合

1. 前往 Home Assistant **設定** → **裝置與服務** → **新增整合**
2. 搜尋 **MQTT**
3. 填寫連線資訊：
   - **Broker**: `homeassistant` 或 `localhost`
   - **連接埠**: `1883`
   - **使用者名稱**: （在 EMQX 中建立的帳號）
   - **密碼**: （在 EMQX 中設定的密碼）

### 3. 設定 Zigbee2MQTT（選擇性）

如果使用 Zigbee2MQTT：
- **Broker**: `homeassistant` 或 `a0d7b954-emqx`
- **連接埠**: `1883`
- 使用在 EMQX 中建立的帳號和密碼

### 4. 外部設備連線

外部 IoT 設備連線到 EMQX：
- **Broker**: Home Assistant 主機的 IP 位址
- **連接埠**: `1883`（MQTT）或 `8883`（MQTT over SSL/TLS）

## 設定說明

大部分設定可直接在 EMQX Dashboard（Web UI）中完成，無需修改 Add-on 設定。

### 環境變數（進階）

對於 Dashboard 中無法設定的進階選項，可透過環境變數設定：

```yaml
env_vars:
  - name: EMQX_NODE__NAME
    value: "something@else.local"
  - name: EMQX_LISTENERS__TCP__DEFAULT__MAX_CONNECTIONS
    value: "1000000"
```

規則：
- 僅接受以 `EMQX_` 開頭的變數名稱
- 變數名稱使用雙底線 `__` 代表設定層級
- 修改後需重啟 Add-on

完整環境變數參考：https://www.emqx.io/docs/en/v5.0/admin/cfg.html

### ngrok TCP 通道（選用）

可透過 ngrok 將 raw MQTT（連接埠 1883）開啟為公開的 TCP 通道，
並把解析後的公開網址印到 Add-on Log：

```yaml
ngrok_enabled: true
ngrok_authtoken: "<你的 ngrok authtoken>"
ngrok_tcp_addr: ""
```

- `ngrok_enabled`：設為 `true` 以啟用 ngrok TCP 1883 通道（預設 `false`）
- `ngrok_authtoken`：ngrok 帳號的 authtoken（啟用 ngrok 時必填）
- `ngrok_tcp_addr`：可選，指定 ngrok 保留的 TCP 位址以取得「固定」的公開端點；留空則由 ngrok 自動指派臨時位址

注意：
- 8083（MQTT over WebSocket）不在 ngrok 範圍內，請改用 Cloudflare Tunnel
- TCP 位址穩定性：ngrok 自動指派的 TCP 位址在每次重啟後都可能改變；
  若需要重啟後仍維持固定的端口，請在 ngrok 帳號中設定保留的 TCP address 並填入 `ngrok_tcp_addr`

## EMQX Dashboard 功能

### 監控面板
- 即時連線數、訊息吞吐量
- 節點狀態監控
- 系統資源使用狀況

### 用戶端管理
- 查看所有連線的 MQTT 用戶端
- 踢出特定用戶端
- 查看訂閱主題和訊息統計

### 存取控制
- **Authentication（驗證）**: 設定帳號密碼、JWT、X.509 憑證等驗證方式
- **Authorization（授權）**: 設定主題存取權限（ACL）

### 規則引擎
- 建立資料橋接（Data Bridge）
- 設定訊息轉發規則
- 支援 Webhook、Kafka、PostgreSQL 等目標

### 診斷工具
- WebSocket 用戶端（內建 MQTT 測試工具）
- 慢訂閱診斷
- 主題監控

## 資料存儲

| 路徑 | 說明 |
|------|------|
| `/data/emqx/data` | EMQX 資料（持久化） |
| `/data/emqx/etc` | EMQX 設定檔（持久化） |
| `/data/emqx/plugins` | EMQX 外掛（持久化） |
| `/config/log` | 記錄檔 |

## 備份與還原

- 備份包含 `/data/emqx/` 下的所有資料
- 包括驗證設定、ACL 規則、資料橋接設定等
- 記錄檔不包含在備份中

## 與 Mosquitto 的比較

| 功能 | Mosquitto | EMQX |
|------|-----------|------|
| 圖形化管理介面 | 無 | ✅ EMQX Dashboard |
| 用戶端管理 | 無 | ✅ 即時監控 |
| 規則引擎 | 無 | ✅ 資料橋接 |
| WebSocket 支援 | 需額外設定 | ✅ 內建 |
| ACL 管理 | 檔案設定 | ✅ Web UI 管理 |
| 叢集支援 | 無 | ✅ 支援 |
| 資源使用 | 極低 | 中等 |
| 最大連線數 | 數千 | 數百萬 |

## 已知問題與限制

### 連接埠衝突
- **無法與 Mosquitto Add-on 同時運行**（兩者都使用連接埠 1883）
- EMQX 預設使用連接埠 1883、8083、8084、8883
- [WebRTC (AlexxIT)](https://github.com/AlexxIT/WebRTC) 整合可能在連接埠 8083 產生衝突

解決方式：
1. 暫時停止衝突的 Add-on 或整合
2. 啟動 EMQX 後在 Dashboard 中修改 Listener 連接埠
3. 重新啟動衝突的服務

### 資源需求
EMQX 比 Mosquitto 需要更多系統資源（RAM、CPU）。如果你的 Home Assistant 主機資源有限，Mosquitto 可能是更好的選擇。

## 疑難排解

### EMQX 無法啟動
- 檢查記錄檔中的錯誤訊息
- 確認連接埠 1883、18083 沒有被佔用
- 確認主機有足夠的記憶體

### MQTT 用戶端無法連線
- 確認已在 EMQX Dashboard 中設定驗證機制
- 確認使用者帳號和密碼正確
- 確認連線的 Broker 位址正確

### Dashboard 無法存取
- Dashboard 透過 Home Assistant Ingress 存取（側邊欄）
- 也可直接存取 `http://<ha-ip>:18083`

## 技術細節

### S6-Overlay 服務啟動順序

```
init-emqx (oneshot) → emqx (longrun) → ngrok (longrun) → ngrok-announce (oneshot)
```

### 服務說明

| 服務 | 類型 | 說明 |
|------|------|------|
| init-emqx | oneshot | 建立資料目錄 |
| emqx | longrun | EMQX MQTT Broker |
| ngrok | longrun | ngrok TCP 1883 通道（由 config 控制） |
| ngrok-announce | oneshot | 印出解析後的 ngrok 公開網址 |

### 檔案結構

```
woow-emqx/
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
├── test/
│   ├── options.json         # 測試用設定
│   ├── docker-compose.amd64.yml
│   └── docker-compose.aarch64.yml
└── rootfs/
    └── etc/s6-overlay/s6-rc.d/
        ├── init-emqx/       # EMQX 初始化
        ├── emqx/            # EMQX 服務 (longrun)
        ├── ngrok/           # ngrok TCP 通道 (longrun)
        ├── ngrok-announce/  # 印出 ngrok 公開網址 (oneshot)
        └── user/contents.d/ # 服務註冊
```

## 與原版差異

| 功能 | 原版 (hassio-addons) | WOOWTECH 版本 |
|------|---------------------|---------------|
| 品牌 | Community Add-ons | WOOWTECH |
| 中文支援 | 無 | 繁體中文翻譯及文件 |
| 功能 | 完全相同 | 完全相同 |
| EMQX 版本 | v5.8.9 | v5.8.9 |

## 授權條款

MIT License

## 致謝

- [hassio-addons/addon-emqx](https://github.com/hassio-addons/addon-emqx) — 原始 EMQX HA Add-on (Franck Nijhof)
- [emqx/emqx](https://github.com/emqx/emqx) — EMQX 開源 MQTT Broker
- [WOOWTECH](https://github.com/WOOWTECH) — 本 Fork 維護者
