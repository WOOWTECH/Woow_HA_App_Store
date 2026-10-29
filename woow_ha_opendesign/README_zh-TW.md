# Woow HA OpenDesign 附加元件

以 WoowTech 共用 OpenDesign core 映像（與 WOOW PaaS 相同的建置）提供 OpenDesign **0.24.1**，封裝成獨立的 Home Assistant 附加元件，支援 `amd64`。

- 透過 Home Assistant Ingress／側邊欄存取。唯一宣告的區域網路連接埠是內建 MCP server 的 `8081/tcp`，預設不映射。
- OpenDesign 只監聽 `127.0.0.1`，由非特權 nginx 提供 Supervisor Ingress 入口。
- OpenDesign 原生 API BYOK 的供應商、模型與 API 金鑰設定只保留在各管理員瀏覽器的 localStorage；金鑰不會寫入 `/data`、附加元件選項、日誌或 Home Assistant 備份。
- OpenDesign 專案與應用程式狀態保存於 `/data/opendesign`，由冷備份涵蓋。
- 系統 Chromium、Playwright 與 Noto CJK／emoji 字型提供無頭匯出。
- 支援獨立 HTML、ZIP、截圖式 PDF、PNG/JPEG，以及每張投影片為圖片的 PPTX。**不支援可編輯 PPTX**，要求此模式時會明確失敗。
- core 映像提供 Claude Code `2.1.296`、Codex CLI `0.162.1`、Pi Coding Agent `1.1.0` 與 OpenCode `1.18.33`（OpenDesign 原生 `byok-opencode` API runtime）；附加元件建置時以 UID 1001 逐一核對版本，不需要 Paseo 插件，也不會在首次使用時下載 CLI。
- 來自 core 的 WoowTech 改動：白牌介面、繁體中文語系修正、匯出修正、內建 `woowtech-brand` skill，並移除 `brainstorming` skill。
- **Omnigent 插件（0.2.10 起）：**原生插件 GUI 與 daemon 管理的 host，首次需輸入網址／帳密，新狀態私有持久化於 `/data`，不採用歷史退役登入。設定頁可經 Ingress 重新整理，Pi 自訂模型會列出，**Configure** 會在 daemon 建立的引導對話中開啟設定。已在 Home Assistant OS 驗收升級、Ingress 重新整理、全新與還原後連線、原生備份還原（見[設定、升級與驗證](DOCS.md#omnigent-plugin)）。
- 透過 OpenDesign 原生 **Plugins** 頁面安裝的插件與 Skills，會由同一個 daemon 提供給 Claude Code、Codex、Pi、OpenCode 的專案執行流程。
- OpenDesign「外掛」頁內建受 HA Ingress 保護的 **CLI 終端機**（`<Ingress>/console/`），可在 GUI 中完成 Claude Code、Codex、Pi 的互動登入。OpenCode 更多 API provider 可在 **Settings → API providers** 設定。
- **內建 OpenDesign MCP server**（取代另一支「Woow OpenDesign MCP Server」附加元件）：MCP 用戶端連 `8081/tcp`＋Bearer token，Claude.ai 連接器用 `/private_<token>/mcp`。工具與 WOOW PaaS 的 OpenDesign MCP 相同共 15 支，預設全開，包含寫入工具 `create_project`、`send_message`（會執行 OpenDesign agent）與 `delete_project`。管理頁（token、工具權限）是 OpenDesign「外掛」頁內建的 **MCP Server**，只能經 HA Ingress 進入。詳見 [DOCS.md](DOCS.md#built-in-mcp-server)。

[English](README.md) · [附加元件說明](DOCS.md)

## 安裝

1. 在 Home Assistant 開啟 **設定 → 附加元件 → 附加元件商店 → 儲存庫**。
2. 加入 `https://github.com/WOOWTECH/Woow_ha_opendesign_add_on`。
3. 安裝 **Woow HA OpenDesign**，在「資訊」頁籤打開 **Watchdog**（Home Assistant 新裝的附加元件預設是關的；沒開時內部程序一結束，附加元件就會停著不會自己回來），再啟動並選 **開啟網頁介面**；0.2.10 起會直接進入 **Plugins**。
4. 在 **設定** 設定 API BYOK 的供應商、模型與金鑰；設定只會保留在該瀏覽器。
5. 開啟 **Local AI → Rescan** 重新掃描已預裝的 CLI。接著進入 **Plugins** 安裝工作流程，再於專案中選取；OpenDesign 會將所選 Skill stage 到專案並交給當次選用的代理。
6. 在 OpenDesign 開啟 **Plugins → Expert suites → Personal**，按內建 **CLI 終端機** 的「開啟」（開新分頁），在終端執行 `claude` 後輸入 `/login`、`codex login --device-auth`，或執行 `pi` 後在 TUI 輸入 `/login`。登入狀態保存在 `/data/opendesign/home`。OpenCode API 供應商可在 **Settings → API providers** 設定。
7. 在同一個 **Plugins → Expert suites → Personal** 頁面開啟 **Paseo**，進行連線設定、供應商登入、模型選擇與服務啟停；詳見 [Paseo 設定與資料保存](DOCS.md#paseo-setup-and-persistence)。
8. 要連接 Omnigent（0.2.10 起），進入 **Plugins → Omnigent → Open → Configure** 輸入伺服器網址、帳號與密碼；要使用的已安裝引擎仍須各自完成供應商登入。詳見 [Omnigent 設定](DOCS.md#omnigent-plugin)。

本附加元件沒有設定選項，也沒有主機目錄掛載。

OpenDesign 原生插件、Skills 的共用方式及 CLI 登入步驟請見[代理與插件設定說明](docs/shared-agent-capabilities.md)。

## 架構

```text
瀏覽器 → HA 驗證 Ingress → nginx :8099 → OpenDesign 127.0.0.1:7456
                                  ↘ loopback ttyd :7681 (CLI 登入 TTY)
                                  ↘ /data/opendesign
                                  ↘ 系統 Chromium renderer
```

nginx 先驗證 `X-Ingress-Path`，改寫初始回應中的根路徑 URL，並在應用程式碼之前注入 shim，以處理 fetch、XHR、EventSource、WebSocket、history、worker、動態資源 URL 與 web 模式的匯出缺口。HA Ingress 的 PDF 操作會改走可下載的截圖 PDF 二進位端點，PNG/JPEG 儲存則直接呼叫 daemon 的無頭 image 端點。SSE／WebSocket 不緩衝，且對上游停用壓縮以便安全改寫。

root PID 1 啟動器先準備 Home Assistant 以 root 掛載的 `/data`，安全移除已撤回的 `/data/opendesign/credentials` 舊路徑且不追蹤 symbolic link，再透過 `su-exec` 讓 nginx、OpenDesign 與 loopback ttyd 以 UID/GID 1001 執行；任一程序退出時會停止其他程序並結束，由 Supervisor 一起重新啟動（須打開 **Watchdog**；實測約 11 秒恢復，沒開時附加元件會停在 `error`）。關閉時先送 TERM、最多等待五秒，再送 KILL 並回收程序。nginx PID 與暫存目錄位於 `/tmp`。

## 驗證

```sh
./tests/run.sh
```

本機測試不需要 Docker；會檢查 YAML、禁止的主機／本機執行環境耦合、JavaScript 與 shell 語法、renderer／網路安全純函式、匯出 bridge、Ingress fixture，以及 CI 的最小權限與不可變發布政策。CI 會先實際建置 amd64 映像，透過模擬 Supervisor 路徑剝除的代理在 Chromium 中執行注入腳本與 fetch／XHR／SSE／WebSocket、PDF／圖片操作，並驗證健康檢查、持久性、renderer 與 HTTP 匯出。PR／main 建置只有 `contents: read` 權限且不登入 GHCR；發布的方式是把提升 `config.yaml` 版本的 PR 合併到 `main`；推 Git 標籤不會發布任何東西，因為那會跳過 PR 的必要檢查。某個版本還沒有 Release 時，`main` 上第一次執行會先預檢確認映像版本標籤不存在，再發布 amd64 映像，最後由 App Store 的共用 workflow 在該 commit 建立 `v<版本>` 標籤與 Release；之後的 `main` 執行不會再動已發布的版本。已發布版本不可覆寫；發布失敗時必須再開一個提升 `config.yaml` 版本的 PR。

## 安全性

API BYOK 的供應商、模型與金鑰只存在管理員瀏覽器的 localStorage，不在 `/data`、附加元件選項、日誌或 Home Assistant 備份中；不同瀏覽器不共用這些設定。供應商呼叫會離開附加元件到所選供應商。

模型產生的 HTML 在套用請求政策的 renderer Chromium 中執行。允許 `data:`、`blob:`、`about:`、精確的 OpenDesign loopback origin，以及通過 DNS／IP 驗證並固定連線位址的公共 HTTP(S)。所有 WebSocket 與 Supervisor、link-local、RFC1918、CGNAT、其他 loopback 連接埠及 IPv6 私有／link-local 位址都會被拒絕。render 工作採單工執行，並受絕對期限、64 張投影片、總像素／輸出位元組、涵蓋 DNS 驗證到固定連線抓取完成的共用遠端資源 semaphore，以及遠端總位元組上限約束。CJK／emoji 使用映像內建字型，不依賴遠端字型 CDN。

## 授權

目標執行映像衍生自 WoowTech fork 建置的 OpenDesign 0.24.1 core。本附加元件把 Dockerfile 與 CI 以 digest 釘至 `ghcr.io/woowtech/open-design-core:20261029.0033@sha256:c8cd57f07adaef23b8dddbb22a8b75f97bdf8ca42c8bfbec1b284dc60ee5a4cf`（與 0.2.10 以 `20261027.1127` 釘的是同一個 digest）。Home Assistant 本機附加元件建置器不接受 `build.yaml` 的 digest 語法，因此本機開發路徑使用對應 tag；必須先確認公開 tag 解析到相同 digest 才能建置發行。OpenDesign 採 Apache-2.0 授權，core 映像附有其授權與 WoowTech 改動聲明；本儲存庫的附加元件封裝及整合程式採 MIT 授權，詳見 [LICENSE](LICENSE)，因此映像標示為 `Apache-2.0 AND MIT`。
