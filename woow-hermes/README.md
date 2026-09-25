# Woow Hermes Agent — Home Assistant Add-on

**WOOWTECH 維護的 [Hermes Agent](https://github.com/NousResearch/hermes-agent) Home Assistant 附加元件**

儀表板與聊天終端機放進 HA 側邊欄，功能與區網 port 完全一致；OpenAI 相容 API 與 Webhook 開在區網 port，可由同一台 HA 上的 Cloudflared add-on 建立 HTTPS 對外網址。

## 安裝

在 **設定 → 附加元件 → 附加元件商店 → 右上角 ⋮ → 儲存庫** 加入：

```
https://github.com/WOOWTECH/Woow_HA_App_Store
```

再到商店找 **Woow Hermes Agent**，按 **安裝**。

---

## 目錄

- [簡介](#簡介)
- [系統需求](#系統需求)
- [安裝與首次設定](#安裝與首次設定)
- [入口與 port](#入口與-port)
- [設定選項](#設定選項)
- [Cloudflare Tunnel 對外](#cloudflare-tunnel-對外)
- [側邊欄與區網 port](#側邊欄與區網-port)
- [網頁與瀏覽器工具](#網頁與瀏覽器工具)
- [安全](#安全)
- [資料、備份與記憶體](#資料備份與記憶體)
- [與上游及 podman 版的差異](#與上游及-podman-版的差異)
- [內建元件](#內建元件)
- [架構](#架構)
- [常見問題](#常見問題)
- [致謝與授權](#致謝與授權)

---

## 簡介

[Hermes Agent](https://github.com/NousResearch/hermes-agent) 是 Nous Research 的自架 AI agent。它能用終端機、檔案、網頁搜尋與擷取、瀏覽器、程式執行、長期記憶、子 agent 等工具實際做事，並提供：

- **網頁儀表板**：Sessions、聊天、Files、Analytics、Models、Logs、排程（Cron）、Skills、Plugins、MCP、Channels、Webhooks、Profiles、Config、Keys、System、Kanban。
- **瀏覽器裡的聊天終端機**：透過 WebSocket 連到 agent 的 TUI。
- **排程**：一次性或週期性的 agent 任務。
- **MCP**：接 stdio 與 HTTP 的 MCP 伺服器，支援 OAuth。
- **Skills**：內建與自訂 skill，並可從 skill hub 安裝。
- **OpenAI 相容 API**：`/v1/chat/completions`、`/v1/responses`，支援串流。
- **Webhook**：外部服務（GitHub、GitLab 等）以 HMAC 簽章觸發 agent。

本 add-on 以 [Woow_podman_hermes](https://github.com/WOOWTECH/Woow_podman_hermes) 的 `slim` 映像為基礎，包成 Home Assistant add-on，並補上 HA Ingress 所需的轉接層。

---

## 系統需求

| 項目 | 需求 |
|---|---|
| 安裝方式 | Home Assistant OS 或 Supervised |
| CPU 架構 | **amd64（x86-64）**，不支援 ARM（樹莓派等） |
| 記憶體 | 至少 4 GB，建議 8 GB 以上。add-on 平常約 0.4–1.3 GB，使用瀏覽器工具時約 2 GB |
| 磁碟 | 可用空間至少 5 GB（映像解壓後約 3.3 GB，另加資料） |
| 模型 | 任一 Hermes 支援的供應商：ChatGPT 帳號登入（`openai-codex`）、OpenRouter、MiniMax、OpenAI API 等 |

HA 無法限制單一 add-on 的記憶體。啟動時可用記憶體不足 4 GB，add-on 會在 log 中提醒。

---

## 安裝與首次設定

1. 依上方步驟加入商店並安裝（下載約 1 GB，視網路與主機效能約 5–15 分鐘）。
2. 在 add-on 的 **資訊** 頁打開：
   - **開機時啟動**
   - **Watchdog**（HA 不會自動幫你打開）
   - **在側邊欄顯示**
3. 按 **啟動**。第一次啟動會自動產生 **儀表板密碼**、**Gateway API 金鑰**、**Webhook 密鑰**，並寫回 **設定** 頁，點眼睛圖示即可查看。
4. 從側邊欄的 **Hermes** 開啟，帳號 `admin`（或你設定的 **儀表板帳號**），密碼為上一步的儀表板密碼。
5. 在儀表板設定模型：
   - **ChatGPT 帳號**：依 Hermes 的提示登入 `openai-codex`，再到 **Models** 頁或聊天右側的模型選單選擇 ChatGPT 帳號支援的模型（例如 `gpt-5.5`）。預設模型不是 ChatGPT 帳號可用的模型，不改會出現 400 錯誤。
   - **API 金鑰**：在儀表板的 **Keys** 頁填入，或填在 add-on 設定頁（見下節）。

---

## 入口與 port

| 入口 | 網址 | 驗證 | 經 HA Ingress |
|---|---|---|---|
| 儀表板 + 聊天終端機 | HA 側邊欄 **Hermes** | HA 登入，再登入 Hermes | 是 |
| 儀表板 + 聊天終端機 | `http://<HA IP>:9119` | Hermes 登入 | 否（區網直連） |
| OpenAI 相容 API | `http://<HA IP>:8642/v1` | `Authorization: Bearer <Gateway API 金鑰>` | 否 |
| Webhook 接收器 | `http://<HA IP>:8644/webhooks/<route>` | HMAC（Webhook 密鑰） | 否 |

- HA Ingress 走 add-on 內部的 `9120`，只允許 Supervisor 連線，不對外開放。
- 在 **網路** 分頁可以改 host port 或停用某個 port。停用 `9119` 後仍可從側邊欄使用；改了 port 要一併改 Cloudflare 規則。

---

## 設定選項

| 選項 | 說明 |
|---|---|
| 儀表板帳號（`dashboard_username`） | 登入帳號，預設 `admin`，區網 port 與側邊欄共用 |
| 儀表板密碼（`dashboard_password`） | 留空則首次啟動時自動產生並回存。建議保留自動產生的長隨機密碼 |
| Gateway API 金鑰（`api_server_key`） | `8642` API 的 Bearer 金鑰，留空則自動產生 |
| Webhook 密鑰（`webhook_secret`） | `8644` webhook 的 HMAC 密鑰，留空則自動產生 |
| 儀表板公開網址（`public_url`） | MCP OAuth 登入完成後導回的網址。留空則為 `http://<HA IP>:9119`，只在區網有效。**不要填 HA 側邊欄網址** |
| MiniMax / OpenRouter API 金鑰、GitHub token | 只有在這裡修改時才寫入 Hermes，在儀表板 **Keys** 頁改的值不會在重啟時被覆蓋 |
| 額外環境變數（`env_vars`） | 進階設定，傳給所有 Hermes 程序。`HERMES_HOME`、`PATH`、`SUPERVISOR_TOKEN` 等保留名稱會被略過 |

修改密碼、金鑰後需重新啟動 add-on。

---

## Cloudflare Tunnel 對外

儀表板本身**不建議公開**。對外建議只開 API 與 Webhook。

### 用 Cloudflared add-on（同一台 HA）

在 Cloudflare Zero Trust 的 tunnel **Public Hostnames**（遠端管理模式），或 Cloudflared add-on 的 `additional_hosts`（本地設定模式）新增：

```yaml
additional_hosts:
  - hostname: hermes-api.example.com
    service: http://homeassistant:8642
  - hostname: hermes-hook.example.com
    service: http://homeassistant:8644
```

### MCP OAuth 從外網登入

MCP 伺服器的 OAuth 登入完成後，瀏覽器會被導回 **儀表板公開網址**。要在外網完成 OAuth：

1. 在 API 的公開網址上，只開放回呼路徑：`^/api/mcp/oauth/callback/` → `http://homeassistant:9119`。
2. 把 **儀表板公開網址** 設為 `https://<API 公開網址>`，重啟 add-on。

### Cloudflare 的限制

- 單一請求 body 上限 100 MB，大檔請在區網上傳。
- 約 100–125 秒沒有回應就會回 524，長時間的 chat completion 請用 `stream: true`。
- 經 Cloudflare 開啟 HA 時，頁面會多出 Cloudflare 自己的 `/cdn-cgi/challenge-platform` 請求，屬正常現象。

---

## 側邊欄與區網 port

兩個入口是同一個 Hermes 程序，帳號、sessions、對話、skills、排程、MCP 與設定完全共用。側邊欄經過 add-on 內的轉接層：

- 在 HA ingress 的網址前綴下改寫網址。
- 把 Hermes 的 session cookie 改名。
- 還原被 HA 吞掉的 WebSocket 關閉碼。
- 重新整理時停在原頁。

兩條路徑已經在真實 HAOS 上實測，功能一致。刻意設計或平台造成的差異：

| 項目 | 說明 |
|---|---|
| 登入各自獨立 | 側邊欄與 `:9119` 各自登入、各自登出，互不影響（瀏覽器 cookie 不分 port，add-on 刻意分開） |
| 瀏覽器端偏好 | 主題、語言存在瀏覽器，側邊欄與 `:9119` 是不同網址，各自保存 |
| 剪貼簿 | `:9119` 是 HTTP，瀏覽器不開放剪貼簿 API（Ctrl+V 貼上無效，右鍵貼上可用）；經 HTTPS 的側邊欄可用 |
| 下載的 Content-Type | 經 HA ingress 時少了 `charset`，檔案內容完全相同 |
| Webhooks 頁顯示的網址 | 顯示 `http://localhost:8644/...`（上游行為）。外部請用 `http://<HA IP>:8644/webhooks/<route>` 或 Cloudflare 網址 |

---

## 網頁與瀏覽器工具

- **網頁搜尋**：DuckDuckGo（`ddgs`），不需金鑰。
- **網頁擷取**：Parallel，不需金鑰。
- **瀏覽器工具**：用映像內附的 Chromium（agent-browser 已預先安裝）。

這些預設值只在設定為空時寫入。在儀表板 **Config** 改用其他供應商後，重啟也不會被改回來。

---

## 安全

- **指令審核**：維持 Hermes 預設。
  - 聊天中：低風險指令直接執行；高風險指令（刪檔、安裝套件、`sudo`、下載後直接執行等）由 smart 審核判斷，必要時在聊天中跳出允許／拒絕。
  - 沒有人能審核的執行（排程、OpenAI API、Webhook）：危險指令一律**拒絕**。上游 Hermes 會在這三種情境自動核准，add-on 已修補（`patches/approval-unattended.py`），CI 每次發佈都會在映像內驗證。
  - 可在儀表板 **Config** 的 `approvals.cron_mode`、`approvals.unattended_mode` 調整。
- **Supervisor token**：add-on 啟動後就從 agent 的環境中移除，agent 無法操作 HA Supervisor。
- **Webhook**：需正確的 HMAC 簽章（V2 含時間戳記，防重送）；上游預設 webhook 執行時不給 terminal 工具。
- **API**：需 Bearer 金鑰。CORS 允許所有來源（`API_SERVER_CORS_ORIGINS=*`），公開 API 時請妥善保管金鑰。
- **密碼**：請保留自動產生的長隨機密碼。Hermes 的登入次數限制以用戶端可偽造的標頭判斷來源，區網上可被繞過。
- **登出**：只清除瀏覽器的 cookie，舊 token 在伺服器端仍有效，直到過期（上游行為）。
- **備份**：add-on 的 HA 備份包含所有金鑰、模型登入與對話紀錄，請當作機密保管。

---

## 資料、備份與記憶體

| 路徑 | 內容 | 在 HA 備份中 |
|---|---|---|
| `/addon_configs/<slug>/`（容器內 `/opt/data`） | Hermes 的全部資料：config、sessions、skills、記憶、排程、kanban、MCP 設定、上傳的檔案 | 是，但排除 `logs`、`lazy-packages`、`.cache`、`.npm` |
| add-on 私有 `/data` | 選項與自動產生的密鑰 | 是 |
| `/media` | HA 的 media 資料夾，agent 可讀寫 | 依 HA 備份設定 |

- 備份採 **cold** 模式：備份進行時 Hermes 會暫停，確保 SQLite 資料一致。
- 解除安裝時，HA 會詢問是否刪除 `/addon_configs/<slug>/`，請先備份。

---

## 與上游及 podman 版的差異

| 項目 | 上游 Hermes / podman 版 | 本 add-on |
|---|---|---|
| 入口 | 區網 port | 另加 HA 側邊欄（Ingress 轉接層） |
| 無人審核時的危險指令 | 排程、API、Webhook 會被 smart 審核自動核准 | 一律拒絕 |
| 網頁擷取 | 裝了 ddgs 後擷取會失敗 | 擷取改用 Parallel |
| 瀏覽器工具 | 預設要連一個執行中的 Chrome，容器內無法使用 | 改用內附 Chromium，agent-browser 預先安裝 |
| Swagger（`/docs`） | 在子路徑下網址錯誤 | 在側邊欄顯示正確的前綴 |
| Webhooks 頁 | 只設環境變數時顯示未啟用 | 自動寫入 `platforms.webhook` |
| 密鑰 | podman secrets | 首次啟動自動產生並寫回 add-on 設定 |
| Session 簽章密鑰 | 每次重啟重新產生，所有人被登出 | 固定保存，重啟後仍維持登入 |
| Postgres / Redis | podman 版附帶（實際未使用） | 移除 |
| 審核政策 | podman 版宣稱套用「免審核」政策，實際未生效 | 維持上游預設，移除無效的程式碼 |

---

## 內建元件

| 元件 | 版本 |
|---|---|
| Hermes Agent（`nousresearch/hermes-agent`，以 digest 固定） | v2026.8.31（dashboard 0.21.0） |
| ddgs（DuckDuckGo 搜尋） | 9.16.0 |
| agent-browser | 0.26.0 |
| OfficeCLI | v1.0.135 |
| superpowers skills（`obra/superpowers`） | `b36e0829` |
| nginx + njs、tmux、jq | Debian 13 套件 |
| MCP OAuth `iss` 修補 | 取自 Woow_podman_hermes |

---

## 架構

```
瀏覽器 ─ HA 側邊欄 ─ HA Core / Supervisor ingress ─┐
                                                   ▼
              ┌──────────── add-on 容器（s6-overlay）────────────┐
              │  nginx :9120  Ingress 轉接層                      │
              │   ├─ 網址前綴改寫、cookie 改名、shim 注入           │
              │   └─ WebSocket → ws_relay :9121（還原關閉碼）      │
              │                    ▼                              │
區網 :9119 ──▶ │  Hermes dashboard :9119（儀表板、聊天 PTY）         │
區網 :8642 ──▶ │  Hermes gateway  :8642（OpenAI API）              │
區網 :8644 ──▶ │                  :8644（Webhook）                 │
              │  woow-provision（首次設定、預設值）                  │
              └──────────────────────────────────────────────────┘
Cloudflared add-on ─▶ http://homeassistant:8642 / :8644
```

---

## 常見問題

**聊天出現 `HTTP 400 … model is not supported when using Codex with a ChatGPT account`**
預設模型不是 ChatGPT 帳號可用的模型。到 **Models** 頁或聊天右側的模型選單，改成 ChatGPT 帳號支援的模型（例如 `gpt-5.5`）。

**側邊欄要我再登入一次**
側邊欄與 `:9119` 的登入刻意分開，各自登入一次即可。

**快速打字或貼上長文字時少了字**
上游 Hermes 終端機的輸入問題，直連也一樣。一般打字速度不受影響。

**重新連線後輸入框多出一個 `l`**
上游問題。送出前刪掉即可。

**新增 MCP 伺服器後，聊天找不到它的工具**
在聊天中輸入 `/reload-mcp`，或開新的對話（上游問題）。

**Webhooks 頁顯示 `localhost:8644`**
上游只顯示本機網址。外部請用 `http://<HA IP>:8644/webhooks/<route>` 或 Cloudflare 網址。

**安裝或更新很久**
映像約 1 GB，解壓後約 3.3 GB，在 2 核的主機上解壓約需 10 分鐘。

**log 顯示可用記憶體不足**
Hermes 加上瀏覽器工具需要較多記憶體，建議主機至少 8 GB RAM。

---

## 致謝與授權

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) 由 [Nous Research](https://nousresearch.com) 開發，以 MIT 授權釋出。本 add-on 的圖示與 logo 為 Hermes 官方 App 圖示。
- 內附的第三方工具依其各自的授權。
- Home Assistant 打包由 [WOOWTECH](https://github.com/WOOWTECH) 維護：[Woow_ha_hermes_add_on](https://github.com/WOOWTECH/Woow_ha_hermes_add_on)。
