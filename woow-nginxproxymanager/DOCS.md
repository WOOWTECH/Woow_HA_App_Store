# Woow Nginx Proxy Manager - Home Assistant Add-on

[Nginx Proxy Manager](https://nginxproxymanager.com/) 是一個簡單而強大的反向代理管理工具，
提供圖形化介面來管理 Nginx 反向代理主機、免費 SSL 憑證、存取控制等功能。

此 Add-on 為 WOOWTECH 基於 [hassio-addons/addon-nginx-proxy-manager](https://github.com/hassio-addons/addon-nginx-proxy-manager) 的 Fork 版本。

## 安裝說明

1. 安裝 **Woow Nginx Proxy Manager** Add-on
2. 啟動 Add-on
3. 檢查記錄檔確認啟動成功
4. 點擊「開啟 Web UI」進入管理介面
5. 使用預設帳號登入：`admin@example.com` / `changeme`
6. **立即修改預設密碼**
7. 在路由器上將連接埠 `443`（和選擇性的 `80`）轉發到 Home Assistant 主機

## 首次登入

- **帳號**: `admin@example.com`
- **密碼**: `changeme`
- 首次登入後系統會強制要求修改密碼

## 功能說明

### 反向代理主機 (Proxy Hosts)
將外部域名轉發到內部服務，例如：
- `nextcloud.example.com` → `http://192.168.1.100:80`
- `grafana.example.com` → `http://192.168.1.100:3000`

### SSL 憑證管理
- 自動申請 Let's Encrypt 免費 SSL 憑證
- 支援 DNS Challenge（Cloudflare、Route53 等）
- 支援自訂 SSL 憑證上傳
- 自動續期

### 存取控制清單 (Access Lists)
- 基本驗證（帳號/密碼）
- IP 白名單/黑名單

### TCP/UDP 串流轉發 (Stream)
- 轉發非 HTTP 的 TCP/UDP 流量
- 適用於資料庫、SSH 等服務

### 重導向主機 (Redirection Hosts)
- 將一個域名重導向到另一個 URL
- 支援 301/302 重導向

### 自訂 Nginx 設定
進階使用者可在每個主機中加入自訂的 Nginx 指令。

## 設定說明

此 Add-on 不需要額外設定。所有管理操作都在 Web UI（連接埠 81）中進行。

## 資料存儲

所有設定資料存儲在 `/config` 目錄：
- `database.sqlite` — 設定資料庫
- `nginx/` — 生成的 Nginx 設定檔
- `letsencrypt/` — SSL 憑證
- `custom_ssl/` — 自訂 SSL 憑證
- `access/` — 存取控制清單
- `logs/` — 存取與錯誤記錄檔

## 搭配 Cloudflare Tunnel

如果使用 Cloudflare Tunnel 存取 Home Assistant：
1. Cloudflare Tunnel 處理外部 HTTPS
2. NPM 可用於管理內部服務的反向代理
3. 設定 trusted_proxies 為 Cloudflare 的 IP 範圍
