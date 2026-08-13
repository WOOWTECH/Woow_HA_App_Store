# Woow Headscale VPN — 使用說明

把 HA 主機變成自架 Tailscale 網路（tailnet）的 control plane：

- **Headscale v0.29.3** — 開源版 Tailscale 控制伺服器（官方 .deb）
- **Headplane v0.7.0** — Web 管理介面，經 **HA Ingress** 使用（sidebar 點開自動登入，免貼 API key）
- **選配 ngrok tunnel** — 填 authtoken 就能把 control plane 打洞到公網，免碰 router

所有裝置（手機、筆電、其他 HAOS 機器）用**未修改的官方 Tailscale client** 加入，取得 `100.64.0.0/10` 的 tailnet IP，彼此以 WireGuard 直連。

---

## 1. 架構總覽

```
                        Internet
                           |
          +----------------+------------------+
          |（路徑 A）router 443                |（路徑 B）ngrok tunnel
          |  → Woow_ha_nginxpm 反代            |  http: https://xxx.ngrok-free.dev
          |  → HA:28080                       |  tcp:  tcp://N.tcp.ngrok.io:P
          +----------------+------------------+
                           |
  [Woow Headscale VPN add-on 容器]（s6-overlay 單容器多服務）
    headscale    0.0.0.0:8080  ──映射→ host 28080（control plane）
    headplane    127.0.0.1:3001（無 host port）
    nginx shim   :3000  ←── HA Ingress（sidebar「Headscale VPN」，自動登入）
    ngrok        選配，只出站連線，public URL 自動注入 server_url
                           |
   手機/筆電：官方 Tailscale app ── tailscale up --login-server=<URL>
   其他 HAOS：官方 Tailscale add-on（login_server 指過來）
                           |
   資料面：WireGuard P2P（裝置間 UDP 41641）＋公共 DERP relay fallback
           —— 完全不經過本 add-on 與 HA 主機，HA 端不需開任何 UDP port
```

---

## 2. Port 分層與安全模型

| 容器 port | Host port（預設） | 用途 |
|-----------|------------------|------|
| 8080/tcp  | **28080** | **Headscale control plane** — `tailscale up --login-server` 的目標，**唯一需要曝露的 port** |
| 9090/tcp  | —（停用） | Prometheus metrics；需要時在 add-on **Network** 區自行指定 host port |
| 50443/tcp | —（停用） | gRPC remote CLI；Headscale 要求有效 TLS 才可用，預設關閉 |
| 3000/tcp  | **無（ingress-only）** | Headplane GUI 的 nginx shim；只有 HA Ingress 進得來 |

三層流量各走各的路：

1. **控制面（control plane, 28080）**：裝置註冊、金鑰交換、節點名單。走 Tailscale 專用的 TS2021 協議（非標準 HTTP Upgrade），所以**不能走 HA Ingress、不能放 Cloudflare Tunnel 後面**（詳 §8C）。這是唯一需要對外曝露的 port。
2. **資料面（data plane）**：裝置之間的實際流量走 WireGuard P2P（UDP 41641），NAT 打洞失敗時 fallback 到 **公共 DERP relay**（Tailscale 官方 `controlplane.tailscale.com/derpmap/default`）。**資料面不經過本 add-on、不經過 HA 主機**——HA 端不需要開任何 UDP port。
3. **管理面（Headplane GUI）**：**ingress-only**。GUI 沒有任何 host port，`http://<HA_IP>:3000` 從外部連不上；唯一入口是 HA sidebar，等於被 HA 的帳號/2FA 體系保護。自動登入用的 API key 檔（`/_ha_key`）也只能經 ingress 到達（nginx 已以 `allow 172.30.32.2; deny all;` 鎖定來源）。要在外網用 GUI，走你既有的 HA 遠端存取管道（Nabu Casa、自家反代 HA）即可，GUI 是純 HTTP、沒有協議限制。

---

## 3. 安裝與首次啟動

1. 加入倉庫 `https://github.com/WOOWTECH/Woow_ha_vpn_headscale_package` → 安裝 **Woow Headscale VPN**（本地 build，首次約 3–5 分鐘）。
2. **Configuration** 分頁確認 `server_url`（見 §4；區網測試用預設值即可）→ **START**。
3. 驗證：
   - `curl http://<HA_IP>:28080/health` 應回 200。
   - add-on **Log** 分頁會以大字輸出最終 login-server URL（複製給 `tailscale up` 用）。
   - HA sidebar 出現「Headscale VPN」，點開直接進 Headplane（自動登入，免貼 API key）。
4. 首次啟動會自動：建立 `default` 使用者（`create_default_user: true` 時）、產生 Headplane API key（效期 3650 天）與 cookie secret、初始化 `dns_records.json`。

---

## 4. 設定選項（逐項）

改任何選項後需**重啟 add-on** 生效。

| 選項 | 型別 / 預設 | 說明 |
|------|------------|------|
| `server_url` | url / `http://homeassistant.local:28080` | 裝置連 control plane 用的 URL，會寫進每台裝置的設定，**必須是裝置實際連得到的位址**。區網測試建議改成 `http://<HA_IP>:28080`（IP 比 mDNS 名穩定）；正式曝露後改成 `https://vpn.example.com`（§8A）。`ngrok_enabled: true` 時此值會被 ngrok public URL **自動覆寫**。⚠️ hostname 不得與 `magic_dns_base_domain` 相同，否則啟動檢查會擋下（§10）。⚠️ 裝置註冊後才改 `server_url`＝所有裝置要重新登入，請先定案再大量註冊。 |
| `log_level` | list / `info` | Headscale log 等級：`trace` `debug` `info` `warn` `error`。 |
| `ipv4_prefix` | str / `100.64.0.0/10` | tailnet IPv4 範圍（CGNAT 段，Tailscale 官方同款）。⚠️ 已有節點後更改會使既有節點 IP 失效，非必要勿動。 |
| `ipv6_prefix` | str / `fd7a:115c:a1e0::/48` | tailnet IPv6 範圍（ULA）。 |
| `magic_dns_base_domain` | str / `ts.local` | MagicDNS 網域尾碼：節點可用 `<hostname>.<user>.ts.local` 互相解析。**不得與 `server_url` 的 hostname 相同**（Headscale 硬性限制）。 |
| `create_default_user` | bool / `true` | 首次啟動自動建立名為 `default` 的 Headscale user（idempotent，已存在不會重建）。 |
| `ngrok_enabled` | bool / `false` | 啟用內建 ngrok tunnel（§8B）。 |
| `ngrok_authtoken` | password / 空 | ngrok 帳號的 authtoken（[dashboard.ngrok.com](https://dashboard.ngrok.com) 取得）。`ngrok_enabled: true` 時必填。 |
| `ngrok_mode` | list / `http` | `http`＝HTTPS tunnel（有效 TLS，建議）；`tcp`＝raw TCP passthrough（無有效 TLS，login-server 用 `http://`，僅測試用；且 ngrok 規定 TCP endpoint 需綁付款卡）。 |
| `ngrok_domain` | str / 空 | `http` 模式的固定網域（帶入 ngrok `--url`）。留空＝每次重啟拿隨機 URL（見 §8B 警告）。免費帳號可填 ngrok 配發的專屬 dev domain（`xxxx.ngrok-free.dev`，帳號綁定、永久）；reserved/自有網域需付費方案。 |

---

## 5. GUI（Headplane）

- 入口：HA sidebar →「Headscale VPN」。nginx shim 會自動帶 API key 登入，直接進站。
- 可管理：**Machines**（節點清單、註冊、改名、expire）、**Users**、**DNS**（MagicDNS / extra records）、**ACL**（policy file 模式）、**Settings**。
- Headplane 對 Headscale 的設定熱更新走同容器 process 整合（`integration.proc`，SIGHUP reload），在 GUI 改 DNS/設定即時生效，不需重啟 add-on。
- 自動登入用的 API key 存於 `/var/lib/headscale/.headplane_api_key`（效期 3650 天，遺失會自動重生）。

> ⚠️ Ingress 介面的路徑重寫規則（sed / sub_filter）與 **Headplane 0.7.0** 的 build 產物綁定，請勿自行改裝其他 Headplane 版本，升級一律等本 add-on 發版。

---

## 6. 裝置註冊流程

先決條件：裝置連得到 `server_url`（區網內＝`http://<HA_IP>:28080`；外網＝§8 的曝露路徑）。

### 6.1 手機（官方 Tailscale app）

1. 安裝官方 Tailscale app（App Store / Google Play）。
2. 指定自訂 control server：
   - **Android**：開 app → 右上 ⋮ 選單 → 「Use an alternate server」→ 輸入 `server_url`。
   - **iOS**：先開過一次 app，再到 iOS **設定 → Tailscale → Alternate Coordination Server URL** 填入 `server_url`，回 app 登入。
3. app 會顯示（或開瀏覽器到）`.../register/hskey-authreq-XXXX` 的註冊網址——**該頁面會直接顯示要執行的註冊指令**，照抄到 Headscale CLI 執行（§6.5），或改用 Headplane **Machines** 頁以 registration key 完成註冊（Headplane 0.7.0 支援 headscale 0.29 的 registration flow）。
4. 註冊完成後手機取得 `100.64.x.x` IP，`http://100.64.x.x:8123` 即可從任何 tailnet 裝置連回 HA。

### 6.2 筆電 / 桌機（tailscale CLI）

```bash
tailscale up --login-server=http://<HA_IP>:28080
# 依畫面指示打開註冊網址 → 照頁面指令在伺服器端核准（§6.5）
```

### 6.3 Pre-auth key（免互動註冊，適合批量/無頭裝置）

在 Headplane **Users** 頁產生 pre-auth key，或用 CLI（`--user` 在 headscale 0.29 需要**數字 user ID**，先 `headscale users list` 查）：

```bash
headscale users list                                # 查 ID，例如 default = 1
headscale preauthkeys create --user 1 --expiration 24h
```

裝置端：

```bash
tailscale up --login-server=<server_url> --authkey=<key>
```

### 6.4 其他 HAOS 機器（官方 Tailscale add-on）

用官方社群 add-on [hassio-addons/addon-tailscale](https://github.com/hassio-addons/addon-tailscale)，Configuration 建議：

```yaml
login_server: "http://<HA_IP>:28080"   # 或你的正式 https URL
accept_dns: true
accept_routes: true
advertise_exit_node: false      # Tailscale 雲端語意的功能，保持關閉
advertise_connector: false      # Headscale 不支援 App Connector
share_homeassistant: disabled   # Headscale 不支援 Serve/Funnel
always_use_derp: false
userspace_networking: true
log_level: info
```

官方 add-on **沒有 `auth_key` 選項**，只能走瀏覽器/URL 流程：

1. 啟動 add-on → 開 **Log** 分頁，找 `To authenticate, visit: https://.../register/hskey-authreq-XXXX`。
2. 打開該網址，照頁面顯示的指令在 Headscale 端核准（§6.5），數秒內連上。
3. 驗證：`headscale nodes list` 應看到該機器。

> 🔴 **已知坑（crash-loop）**：官方 Tailscale add-on 只要**曾經**登入過 Tailscale 官方雲端或其他 server，就會 crash-loop 並噴：
>
> ```
> can't change --login-server without --force-reauth
> FATAL: Unable to start up Tailscale
> ```
>
> add-on 沒有暴露 `--force-reauth`。**解法：解除安裝 → 重新安裝**（清掉 add-on 的 `/data` 舊狀態），重填 `login_server` 再啟動。此坑已在實機驗證（清除重裝後立即註冊成功）。

Headscale 環境下**不支援**的官方 add-on 功能：App Connector、Tailscale Serve/Funnel、雲端 admin console 的 key 效期管理。

### 6.5 在 HA 主機上執行 headscale CLI

用 **Terminal & SSH** add-on（需關 protection mode 才有 docker 權限）進到 add-on 容器：

```bash
docker exec -it $(docker ps -q -f name=woow-headscale) headscale nodes list
docker exec -it $(docker ps -q -f name=woow-headscale) headscale users list
```

註冊核准（實際參數以註冊頁顯示的指令為準）：

```bash
docker exec -it $(docker ps -q -f name=woow-headscale) \
  headscale auth register --user default --auth-id hskey-authreq-XXXXXXXX
```

（舊版 alias：`headscale nodes register --user default --key …`；`--user` 報錯時改用數字 ID。）

---

## 7. MagicDNS 與自訂 DNS records

- MagicDNS 預設開啟：節點以 `<hostname>.<user>.<magic_dns_base_domain>` 互解（例 `nas.default.ts.local`）。
- 額外 DNS 紀錄放在 **`/etc/headscale/dns_records.json`**（首次啟動自動建立為 `[]`）。此路徑在 `addon_config` 映射內，可從 HA 主機的 `/addon_configs/<repo>_woow-headscale/dns_records.json` 用 File editor / Studio Code Server / Samba 編輯。格式：

```json
[
  { "name": "grafana.ts.local", "type": "A", "value": "100.64.0.3" }
]
```

- Headscale 原生監看此檔（`extra_records_path`），**存檔即熱生效**，不用重啟；Headplane 的 DNS 頁也是改這個檔。

---

## 8. 對外曝露 control plane

區網用不到本節。要讓 4G/外網裝置入網，二選一：

### 8A. 路徑 A（正式）：Woow_ha_nginxpm 反代 + router 443

```
Internet ──443──> Router ──443──> HA 主機（Nginx Proxy Manager）──> HA:28080
```

1. 安裝 [Woow_ha_nginxpm](https://github.com/WOOWTECH/Woow_ha_nginxpm)（Nginx Proxy Manager add-on）。
2. **DNS**：`vpn.example.com` A 記錄 → 你的公網 IP。用 Cloudflare 管 DNS 的話**必須 DNS-only（灰雲）**——橘雲＝經 CF proxy，跟 Cloudflare Tunnel 一樣會剥 Upgrade header（§8C）。
3. **Router**：TCP 443 port-forward → HA 主機（NPM 的 443）。
4. **NPM 新增 Proxy Host**：
   - Domain: `vpn.example.com`；Scheme: `http`；Forward IP: `<HA_IP>`；Forward Port: `28080`
   - ✅ **Websockets Support**（帶入 Upgrade/Connection header passthrough）
   - SSL 分頁：Request a new SSL Certificate（Let's Encrypt）＋ Force SSL
   - **Advanced 分頁**貼自訂設定（TS2021 必需的 Upgrade passthrough 補強）：

     ```nginx
     proxy_http_version 1.1;
     proxy_set_header Upgrade $http_upgrade;
     proxy_set_header Connection $http_connection;
     proxy_buffering off;
     proxy_request_buffering off;
     ```

5. `server_url` 改成 `https://vpn.example.com` → 重啟 add-on → `curl https://vpn.example.com/health` 應回 200。

不用 NPM、自架 nginx 的話，Headscale 官方參考設定（重點：`proxy_http_version 1.1` + Upgrade passthrough + `proxy_buffering off`）：

```nginx
map $http_upgrade $connection_upgrade {
    default      keep-alive;
    'websocket'  upgrade;
    ''           close;
}
server {
    listen 443 ssl;
    server_name vpn.example.com;
    location / {
        proxy_pass http://<HA_IP>:28080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $server_name;
        proxy_buffering off;
    }
}
```

Traefik / Caddy 也可行（原生 upgrade passthrough；Traefik 若 HTTP/2 協商導致失敗，用 `TLSOption` 把 ALPN 釘在 `http/1.1`）。

### 8B. 路徑 B（快速 / 測試）：內建 ngrok

免碰 router、免公網 IP，適合快速開通與外網測試：

1. 註冊 [ngrok](https://dashboard.ngrok.com) 帳號，複製 authtoken。
2. 設定：`ngrok_enabled: true`、`ngrok_authtoken: <token>`、`ngrok_mode: http` → 重啟。
3. add-on 內部流程：ngrok service 先建 tunnel → headscale 啟動前輪詢本機 ngrok API（`127.0.0.1:4040/api/tunnels`，最多 120 秒）取得 public URL → 自動覆寫 `server_url` → 啟動。**Log 分頁會大字輸出最終 login-server URL**，複製給裝置用即可。
4. 手機走 4G 以該 `https://xxxx.ngrok-free.dev` URL 註冊（§6.1）。

> 🔴🔴 **警告（free tier，務必先讀）**：`ngrok_domain` 留空時，**每次 add-on 重啟 public URL 都會變**——所有已註冊裝置的 login-server 立即失聯，**必須逐台重新註冊**。正式環境請擇一：
> - 免費帳號到 ngrok dashboard 領取帳號綁定的**永久 dev domain**（`xxxx.ngrok-free.dev`）填入 `ngrok_domain` → URL 固定；
> - 付費方案 reserved/自有網域填入 `ngrok_domain`；
> - 或改走路徑 A。

free tier 其他限制：流量 1 GB/月、HTTP 20,000 requests/月、最多 3 個 online endpoints；瀏覽器開 tunnel URL 會先看到 ngrok 插頁警告（**不影響 Tailscale client**，控制協議照常通過）。

`ngrok_mode: tcp`：raw TCP passthrough，配隨機 `N.tcp.ngrok.io:port`、無有效 TLS → login-server 用 `http://host:port`（add-on 會自動把 `tcp://` 轉成 `http://`）。協議層一定通（實測 ✅），但**僅供測試**（noise 內層仍加密，惟正式環境應走 HTTPS）；且 ngrok 規定 **TCP endpoint 需帳號綁定有效付款卡**，否則報 `ERR_NGROK_8013`。

### 8C. 為什麼 Cloudflare Tunnel 不可用

Tailscale control 協議（TS2021）**不是普通 HTTP**：

1. Client 送 `POST /ts2021` 帶非標準 header `Upgrade: tailscale-control-protocol`（且是 POST，不是 WebSocket 標準的 GET）；
2. 收到 `101 Switching Protocols` 後在原連線上跑 **Noise IK** 加密握手；
3. 再於加密通道內多工 HTTP/2。

Cloudflare Tunnel（含橘雲 proxy）會剥掉 POST 上的 `Upgrade` header，第 1 步就斷——client 在 `/machine/register` 收到 500，Headscale log 出現：

```
WRN no upgrade header in TS2021 request. If headscale is behind a reverse
proxy, make sure it is configured to pass WebSockets through.
```

佐證：[cloudflared#883](https://github.com/cloudflare/cloudflared/issues/883)、[cloudflared#990](https://github.com/cloudflare/cloudflared/issues/990)、[Headscale 官方 reverse-proxy 文件](https://headscale.net/stable/ref/integration/reverse-proxy/)，以及本專案 2026-07 實測（詳 [Woow_vpn_headscale_package/docs/EXTERNAL-ACCESS.md](https://github.com/WOOWTECH/Woow_vpn_headscale_package/blob/main/docs/EXTERNAL-ACCESS.md)）。同理 **control plane 也不能走 HA Ingress**。可行方案即 §8A/§8B。

---

## 9. 備份與還原

所有 VPN state 集中在 add-on 的 data 目錄 `/var/lib/headscale`，HA backup（完整或勾選本 add-on 的部分備份）即涵蓋：

| 檔案 | 內容 |
|------|------|
| `noise_private.key` | **伺服器身分金鑰**——遺失＝所有裝置必須重新註冊 |
| `db.sqlite` | 節點、使用者、pre-auth key（WAL 模式） |
| `.headplane_api_key` | Headplane 自動登入用 API key |
| `.headplane_cookie_secret` | Headplane session secret |
| `headplane/` | Headplane 資料目錄 |

設定面（`/etc/headscale`：render 出的 config 與 `dns_records.json`）在 `addon_config` 映射，也在 backup 範圍。

**還原**：Settings → System → Backups → 還原含本 add-on 的備份 → 啟動 add-on → 節點全數回來；只要 `server_url` 不變，所有 client 完全無感。換新硬體同樣適用（還原後把曝露路徑指到新機器即可）。

---

## 10. Troubleshooting

**add-on 起不來，log 顯示 server_url 與 magic_dns_base_domain 相同的錯誤**
cont-init 啟動檢查：`server_url` 的 hostname 不得等於（或為子網域）`magic_dns_base_domain`（Headscale 會拒絕啟動）。改其中一個（例如 base domain 用 `ts.local`、server_url 用 IP 或 `vpn.example.com`）。

**裝置註冊時 500（/machine/register），headscale log 出現 `WRN no upgrade header in TS2021 request`**
中間有東西剥掉 Upgrade header：確認沒放在 Cloudflare Tunnel/橘雲後面（§8C）、反代有 `proxy_http_version 1.1` + Upgrade passthrough + `proxy_buffering off`（§8A）、NPM 的 Websockets Support 有勾。

**ngrok 啟用後 headscale 一直不啟動 / log 顯示等不到 tunnel（約 120 秒後退出）**
headscale 輪詢 `127.0.0.1:4040/api/tunnels` 逾時。檢查：`ngrok_authtoken` 是否正確、ngrok service log 有無錯誤（authtoken 無效、free tier endpoint 數量達上限、`tcp` 模式未綁付款卡的 `ERR_NGROK_8013`）。

**官方 Tailscale add-on crash-loop：`can't change --login-server without --force-reauth`**
該 add-on 曾登入過其他 server。解除安裝 → 重新安裝（清 `/data`）→ 重填 `login_server` → 啟動（§6.4）。

**手機/筆電連不上 `server_url`**
先在裝置瀏覽器開 `<server_url>/health` 應見 200。區網用 `homeassistant.local` 失敗就改 `http://<HA_IP>:28080`（部分平台 mDNS 不可靠）；外網確認 §8 路徑暢通。

**HA sidebar 點開 GUI 空白或 404**
重啟 add-on 再試；確認沒有自行改裝其他 Headplane 版本（ingress 重寫規則版本敏感，§5）。仍異常請附 add-on log 回報 issue。

**`http://<HA_IP>:3000` 連不上**
這是設計行為：GUI ingress-only、無 host port（§2）。請從 HA sidebar 進。

**裝置都註冊了但互 ping 不通**
資料面問題（與 add-on 無關）：兩端 `tailscale status` 看連線型態；NAT 打洞失敗會自動走公共 DERP relay（較慢但可通）；確認裝置端防火牆未擋 Tailscale 介面。

**Host port 28080 被占用**
在 add-on **Network** 區改成其他 host port，並同步更新 `server_url` 與反代目標。

**重啟 add-on 資料會不會不見？**
不會。state 都在 `/var/lib/headscale`（data 映射），重啟/更新皆保留；只有解除安裝或還原舊備份會動到。

---

## 11. 出處與致謝

- 服務組裝（cont-init / tempio / s6 版型）：[AlessioBazzanella/homeassistant-headscale-addon](https://github.com/AlessioBazzanella/homeassistant-headscale-addon)（MIT）
- HA Ingress nginx shim 與自動登入機制：[yuriy1337/headscale-ha](https://github.com/yuriy1337/headscale-ha)
- 曝露相容性實測與 HAOS 接入指南：[WOOWTECH/Woow_vpn_headscale_package](https://github.com/WOOWTECH/Woow_vpn_headscale_package)（`docs/EXTERNAL-ACCESS.md`、`docs/HAOS-ADDON-SETUP.md`；設定基準取自 podman 分支）
- 上游專案：[juanfont/headscale](https://github.com/juanfont/headscale)（BSD-3-Clause）、[tale/headplane](https://github.com/tale/headplane)（BSD-3-Clause）
