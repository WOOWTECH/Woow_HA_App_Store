# Woow EMQX - Home Assistant Add-on

[EMQX](https://www.emqx.io/) 是一個開源的高效能 MQTT 訊息代理伺服器，
支援大規模 IoT 設備的事件串流處理。可作為 Mosquitto MQTT Add-on 的進階替代方案。

此 Add-on 為 WOOWTECH 基於 [hassio-addons/addon-emqx](https://github.com/hassio-addons/addon-emqx) 的 Fork 版本。

## 安裝說明

1. 安裝 **Woow EMQX** Add-on
2. 啟動 Add-on
3. 檢查記錄檔確認啟動成功
4. 開啟 Web UI
5. 使用預設帳號登入：使用者名稱 `admin`，密碼 `public`
6. **務必先設定 MQTT 驗證**：前往「Access Control」→「Authentication」

## 首次登入

- **使用者名稱**: `admin`
- **密碼**: `public`
- **請務必在設定 MQTT 用戶端之前，先設定驗證機制**

## 連線設定

### Home Assistant / Zigbee2MQTT 連線
- **Broker 主機**: `homeassistant` 或 `a0d7b954-emqx` 或 `localhost`
- **連接埠**: `1883`（MQTT）或 `8883`（MQTT over SSL/TLS）

### 外部設備連線
- **Broker 主機**: Home Assistant 的 IP 位址或主機名稱
- **連接埠**: `1883`（MQTT）

## 設定說明

大部分設定可透過 Web UI（EMQX Dashboard）完成。
進階設定可透過環境變數進行：

```yaml
env_vars:
  - name: EMQX_NODE__NAME
    value: "something@else.local"
```

僅接受以 `EMQX_` 開頭的環境變數。
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
- 8083（MQTT over WebSocket）不在 ngrok 範圍內，請改用 Cloudflare Tunnel
- TCP 位址穩定性：ngrok 自動指派的 TCP 位址在每次重啟後都可能改變；
  若需要重啟後仍維持固定的端口，請在 ngrok 帳號中設定保留的 TCP address 並填入 `ngrok_tcp_addr`

## 已知問題

- 此 Add-on 無法與 Mosquitto Add-on 同時運行
- EMQX 預設使用連接埠 1883、8083、8084、8883，可能與其他 Add-on 衝突
- WebRTC 整合（AlexxIT）可能會在連接埠 8083 產生衝突
