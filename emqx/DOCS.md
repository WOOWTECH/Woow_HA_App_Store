# Woow EMQX - Home Assistant Add-on

[EMQX](https://www.emqx.io/) 是一個開源的高效能 MQTT 訊息代理伺服器，
支援大規模 IoT 設備的事件串流處理。可作為 Mosquitto MQTT Add-on 的進階替代方案。

此 Add-on 為 WOOWTECH 基於 [hassio-addons/addon-emqx](https://github.com/hassio-addons/addon-emqx) 的 Fork 版本。

## 版本說明

- **Add-on 版本**：5.9.1（Home Assistant 顯示的版本）
- **EMQX Broker 版本**：5.8.9

EMQX 5.8.9 是最後一個 Apache-2.0 開源版本；EMQX 5.9 以後（含 6.x）改為
Business Source License 企業版，不允許內嵌出貨，因此本 Add-on 固定使用 5.8.x。
Add-on 版號 5.9.x 只代表 Add-on 本身的改版，不是 EMQX 5.9。

## 安裝說明

1. 安裝 **Woow EMQX** Add-on
2. 啟動 Add-on
3. 檢查記錄檔確認啟動成功
4. 開啟 Web UI
5. 使用預設帳號登入：使用者名稱 `admin`，密碼 `public`，**登入後立刻修改密碼**
6. **務必先設定 MQTT 驗證**：前往「Access Control」→「Authentication」

## 安全性提醒（請務必閱讀）

- **預設允許匿名 MQTT**：尚未建立任何驗證機制前，任何連得到連接埠 1883／8083／8084／8883
  的用戶端都能**不需帳密**連線、發佈與訂閱所有主題。本 Add-on 使用主機網路，
  這些連接埠直接開在 Home Assistant 主機上，同一個區網的任何裝置都連得到。
- **Dashboard 預設帳密 `admin` / `public`**：這是公開的預設值，第一次登入後請立刻修改
  （右上角使用者選單 →「修改密碼」，或「System」→「Users」）。Dashboard（18083）
  也直接開在主機上，區網內可直接存取 `http://<HA 主機 IP>:18083`。
- **開啟 ngrok 等於把 1883 公開到網際網路**：`ngrok_enabled: true` 時，任何知道 ngrok
  位址的人都能從網際網路連到你的 Broker；若尚未設定驗證，等於**任何人都能匿名連入**、
  讀取與控制你的智慧家庭訊息。**開啟 ngrok 前務必先完成下方的驗證設定。**

### 在 Dashboard 開啟 MQTT 驗證

1. 開啟 Web UI，前往 **Access Control** → **Authentication**
2. 點擊 **Create**，選擇 **Password-Based** → **Built-in Database**，完成建立
3. 在剛建立的驗證器中點 **Users**，新增 MQTT 使用者帳號與密碼
4. 確認驗證器狀態為啟用；之後沒有正確帳密的用戶端會被拒絕連線
5. 更新 Home Assistant MQTT 整合、Zigbee2MQTT 與其他設備的帳號密碼
6. （選用）在 **Access Control** → **Authorization** 設定主題存取權限（ACL）

## 首次登入

- **使用者名稱**: `admin`
- **密碼**: `public`（登入後請立刻修改）
- **請務必在設定 MQTT 用戶端之前，先設定驗證機制**

## 連線設定

本 Add-on 使用主機網路（host network），EMQX 直接在 Home Assistant 主機上監聽
1883 等連接埠，**沒有** `a0d7b954-emqx` 或 `core-mosquitto` 這類 Add-on 主機名稱
（`a0d7b954-emqx` 是社群版 Add-on 的名稱，不適用於本 Add-on）。

### Home Assistant MQTT 整合
- **Broker 主機**: `localhost`（或 `127.0.0.1`、`homeassistant`）
- **連接埠**: `1883`（MQTT）或 `8883`（MQTT over SSL/TLS）

### 其他 Add-on（例如 Zigbee2MQTT）
- **Broker 主機**: `homeassistant`（或 `172.30.32.1`）——**不要**填 `localhost`，
  一般 Add-on 有自己的網路，`localhost` 指的是它自己
- **連接埠**: `1883`

### 外部設備連線
- **Broker 主機**: Home Assistant 主機的 IP 位址
- **連接埠**: `1883`（MQTT）或 `8883`（MQTT over SSL/TLS）

## 設定說明

大部分設定可透過 Web UI（EMQX Dashboard）完成。
進階設定可透過環境變數進行：

```yaml
env_vars:
  - name: EMQX_LISTENERS__TCP__DEFAULT__MAX_CONNECTIONS
    value: "100000"
```

僅接受以 `EMQX_` 開頭的環境變數。記錄檔只會印出變數名稱，不會印出值。

注意：
- **不要隨意設定 `EMQX_NODE__NAME`**。EMQX 的資料庫以節點名稱命名，改名後會開到空的資料庫
  （帳號、驗證、ACL、規則都會「消失」，舊資料仍留在磁碟上）。節點名稱已固定記錄在
  `/data/emqx/node.name`，不會因 Home Assistant 主機改名而改變。
- 若把 Dashboard 改成只監聽 127.0.0.1（`EMQX_DASHBOARD__LISTENERS__HTTP__BIND`），
  Supervisor 的 watchdog 將無法檢查 `/api/v5/status`，Add-on 會被判定異常而重啟。
完整環境變數參考：https://www.emqx.io/docs/en/v5.0/admin/cfg.html

## ngrok TCP 通道（選用）

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
- **安全性**：開啟後 1883 會公開在網際網路上；**務必先在 Dashboard 設定 MQTT 驗證**，
  否則任何人都能匿名連入（見上方「安全性提醒」）
- 8083（MQTT over WebSocket）不在 ngrok 範圍內，請改用 Cloudflare Tunnel
- TCP 位址穩定性：ngrok 自動指派的 TCP 位址在每次重啟後都可能改變；
  若需要重啟後仍維持固定的端口，請在 ngrok 帳號中設定保留的 TCP address 並填入 `ngrok_tcp_addr`

## 已知問題

- 此 Add-on 無法與 Mosquitto Add-on 同時運行
- EMQX 預設使用連接埠 1883、8083、8084、8883，可能與其他 Add-on 衝突
- WebRTC 整合（AlexxIT）可能會在連接埠 8083 產生衝突

## 節點名稱與 Erlang cookie

- `/data/emqx/node.name`：EMQX 節點名稱。既有安裝升級時沿用資料庫原本的名稱
  （例如 `emqx@homeassistant.local`），新安裝為 `emqx@127.0.0.1`。
- `/data/emqx/node.cookie`：每台安裝第一次啟動時隨機產生的 Erlang cookie（權限 600）。
  請勿外流；它保護 EMQX 的 Erlang 分散式連線埠。
- 兩者都在 `/data`，會隨 Add-on 備份一起備份與還原。
