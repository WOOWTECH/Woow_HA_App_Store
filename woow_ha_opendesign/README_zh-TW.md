# Woow HA OpenDesign 附加元件

將 OpenDesign **0.21.1** 封裝成獨立的 Home Assistant 附加元件，支援 `amd64` 與 `aarch64`。

- 僅透過 Home Assistant Ingress／側邊欄存取，不發布區域網路連接埠。
- OpenDesign 只監聽 `127.0.0.1`，由非特權 nginx 提供 Supervisor Ingress 入口。
- **HA Persistent BYOK Profiles** 使用內建 Pi Local CLI。金鑰保存於 `/data/opendesign/credentials/byok-profiles.json`，HA 管理員可管理，且會納入冷備份。
- OpenDesign 狀態保存於 `/data/opendesign`，由冷備份涵蓋。
- 系統 Chromium、Playwright 與 Noto CJK／emoji 字型提供無頭匯出。
- 支援獨立 HTML、ZIP、截圖式 PDF、PNG/JPEG，以及每張投影片為圖片的 PPTX。**不支援可編輯 PPTX**，要求此模式時會明確失敗。
- 映像以精確鎖定版本內建 Pi `0.84.4`；profile 支援 Anthropic、OpenAI、Google 與 OpenAI-compatible endpoint，active profile/model 適用於新 run。

[English](README.md) · [附加元件說明](DOCS.md)

## 安裝

1. 在 Home Assistant 開啟 **設定 → 附加元件 → 附加元件商店 → 儲存庫**。
2. 加入 `https://github.com/WOOWTECH/Woow_ha_opendesign_add_on`。
3. 安裝並啟動 **Woow HA OpenDesign**，再從側邊欄開啟。
4. 在 **設定** 建立 **HA Persistent BYOK Profile**、設為 active，並以 Pi Local CLI 執行新 run。

本附加元件沒有設定選項，也沒有主機目錄掛載。

## 架構

```text
瀏覽器 → HA 驗證 Ingress → nginx :8099 → OpenDesign 127.0.0.1:7456
                                               ↘ /data/opendesign
                                               ↘ 系統 Chromium renderer
```

nginx 先驗證 `X-Ingress-Path`，改寫初始回應中的根路徑 URL，並在應用程式碼之前注入 shim，以處理 fetch、XHR、EventSource、WebSocket、history、worker、動態資源 URL 與 web 模式的匯出缺口。HA Ingress 的 PDF 操作會改走可下載的截圖 PDF 二進位端點，PNG/JPEG 儲存則直接呼叫 daemon 的無頭 image 端點。SSE／WebSocket 不緩衝，且對上游停用壓縮以便安全改寫。

root PID 1 啟動器先準備 Home Assistant 以 root 掛載的 `/data`，再透過 `su-exec` 讓 nginx 與 OpenDesign 以 UID/GID 1001 執行；任一程序退出時會停止另一個並讓 Supervisor 重新啟動。關閉時先送 TERM、最多等待五秒，再送 KILL 並回收程序。nginx PID 與暫存目錄位於 `/tmp`。

## 驗證

```sh
./tests/run.sh
```

本機測試不需要 Docker；會檢查 YAML、禁止的主機／本機執行環境耦合、JavaScript 與 shell 語法、renderer／網路安全純函式、匯出 bridge、Ingress fixture，以及 CI 的最小權限與不可變發布政策。CI 會先實際建置 amd64 映像，透過模擬 Supervisor 路徑剝除的代理在 Chromium 中執行注入腳本與 fetch／XHR／SSE／WebSocket、PDF／圖片操作，並驗證健康檢查、持久性、renderer 與 HTTP 匯出。PR／main 建置只有 `contents: read` 權限且不登入 GHCR；amd64／aarch64 映像只在 Git 標籤與 `config.yaml` 版本完全相符、且預檢確認兩個版本標籤都不存在時發布。已發布版本不可覆寫；若只成功發布其中一個架構，必須提升 `config.yaml` 版本並建立新的相符標籤。

## 安全性

模型產生的 HTML 在套用請求政策的 renderer Chromium 中執行。允許 `data:`、`blob:`、`about:`、精確的 OpenDesign loopback origin，以及通過 DNS／IP 驗證並固定連線位址的公共 HTTP(S)。所有 WebSocket 與 Supervisor、link-local、RFC1918、CGNAT、其他 loopback 連接埠及 IPv6 私有／link-local 位址都會被拒絕。render 工作採單工執行，並受絕對期限、64 張投影片、總像素／輸出位元組、涵蓋 DNS 驗證到固定連線抓取完成的共用遠端資源 semaphore，以及遠端總位元組上限約束。CJK／emoji 使用映像內建字型，不依賴遠端字型 CDN。

## 授權

執行映像衍生自 `ghcr.io/nexu-io/od:0.21.1`。Dockerfile 與 release／CI 建置固定其多架構 digest；Home Assistant 本機附加元件建置器不接受 `build.yaml` 的 digest 語法，因此僅該開發路徑固定使用 `0.21.1` tag。OpenDesign 本身適用其上游授權與聲明。本儲存庫的附加元件封裝及整合程式採 MIT 授權，詳見 [LICENSE](LICENSE)。
