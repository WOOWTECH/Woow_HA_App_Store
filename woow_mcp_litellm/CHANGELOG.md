# LiteLLM Changelog

## 0.1.7 — 2026-10-08 公開（experimental）

- 2026-10-09 補充（映像與功能不變，不需要更新）：顯示名稱改為「Woow LiteLLM MCP Server」，圖示改用 LiteLLM 的圖示（[來源](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/provenance/icons.md)）；同時上架 [WOOW HA App Store](https://github.com/WOOWTECH/Woow_HA_App_Store) 與 ha-rebrand 的 Local Download。兩個商店的同名 add-on 在 HA 裡是不同的 add-on，同一台 HA 只裝其中一個來源的。
- 本產品功能沒有變動。0.1.7 新增第七支產品 WOOW Nextcloud MCP；所有 add-on 共用同一個版號，所以隨同重建映像 `ghcr.io/woowtech/amd64-mcp-litellm:0.1.7`（候選 7cc8bcb，build／container／supply-chain gate 全過；本版的審查針對新增的 Nextcloud：R1 REQUEST CHANGES，修正後 R2、R3 APPROVE WITH NOTES，最後由交付線做差異檢查）；0.1.0–0.1.6 tag 不覆寫。
- 已知問題：0.1.6 列出的已知問題（延到 0.1.7 的那幾項）本版都沒有處理（本版刻意不改既有六支產品的行為），延到 0.1.8。

## 0.1.6 — 2026-10-08 公開（experimental）

- 管理面板（HA 角色驗證）：原本只認 Home Assistant Core 2026.7.2，Core 一升級，管理面板與管理 API 就全部回 403。改為經原始碼審查的版本清單 2026.7.2–2026.9.4 與 2026.10.0（驗證器用到的 Core 使用者清單 API、欄位、回應格式與管理員群組在這些版本間沒有變動；2026.10.0 改用 probatio，相關的 13 個檔案有改動，逐行審查後確認不影響；auth 訊息由 Supervisor 產生，審查紀錄見 docs/ha-role-core-contract.md）；清單外的版本照樣拒絕，auth_required 與 auth_ok 回報的版本也必須相同。MCP 端點不受影響（它用 Bearer token）。
- gateway（0.1.5 發佈候選審查 F3 與 0.1.6 審查）：tools/list 的結果由 gateway 重新組成，只留工具清單與字串型的 nextCursor，同名工具只留第一個。
  每個工具的名稱與 inputSchema 用 gateway 自己的定義；title、description、annotations.title 是子程序文字，只在是字串時保留；
  四個提示（readOnlyHint、destructiveHint、idempotentHint、openWorldHint）只保留保守的值，或本地定義沒有寫入路徑的工具才保留放寬的值
  （Claude Code 會把 readOnlyHint 當作唯讀）。outputSchema、execution、icons、_meta 與其他欄位不再轉送：TS client 會把 outputSchema 裡的
  子程序文字放進錯誤訊息、Python client 會去抓子程序指定的 $ref 網址，execution.taskSupport 為 required 時會拒絕呼叫該工具。
  影響：client 不再依子程序的 outputSchema 檢查 structuredContent（n8n validate_* 截斷結果時原本會失敗，現在正常）；
  n8n 給 Claude Code 的 `anthropic/maxResultSizeChars` 也不再轉送，Claude Code 會套用它預設的 MCP 輸出上限。
- gateway（0.1.5 R2 審查觀察）：gateway 拒絕 initialize 時（Bearer 在等待中被撤銷 401；回覆格式錯誤、過大、protocolVersion 不是日期、
  子程序回 401/403 或轉址 502；BACKEND_UNAVAILABLE 或狀態讀取失敗 503；子程序自己的 4xx/5xx 照轉但不帶 session id），子程序可能已經
  建立 session 並回了 Mcp-Session-Id。這個 id 不會交給 client，而本 add-on 的子程序（釘選的 FastMCP 3.4.5）沒有設定閒置回收，
  這個 session 原本會一直留到子程序重啟（本機以釘選版本的 SDK 實測：改版前被扣住的 session 直接 ping 仍回 200，改版後回 404）。
  現在 gateway 會自己送一次 `DELETE /mcp` 結束該 session：只限 gateway 會轉送的 session id（可見 ASCII、1–256 字元），
  且不是 client 自己帶來的 id；先關閉子程序的回覆，在同一個請求名額內送出，最多等 2 秒，子程序的回應一律不讀、不轉送，
  錯誤一律忽略，session id 也不寫進任何紀錄。client 收到的回覆完全不變，最多晚 2 秒（本機以釘選版本的 SDK 實測，延遲沒有
  可量測的差別）；initialize 成功（含 JSON-RPC 錯誤回覆）時 session 照常交給 client，其他方法不受影響。
- gateway（0.1.6 AI 測試第 0 階段的發現，負責人決定 D21）：經 OpenRouter 實測，Claude 與 GPT 只要看到任一工具的
  inputSchema 頂層有 oneOf、anyOf 或 allOf（GPT 另含 enum、const、not），就拒收整個請求（HTTP 400），所以原樣轉送
  工具清單的 client 先前在 n8n、Odoo、Hermes 三支 add-on 上一個工具都叫不到。共用的 gateway 現在只宣告頂層為
  `type: object` 的 schema（分支規則改寫進 description）。本 add-on 的工具 schema 頂層本來就沒有這些關鍵字，
  tools/list 內容不變；驗證完全不變，gateway 仍用原本嚴格的 pydantic 模型檢查每個呼叫。
- 映像 `ghcr.io/woowtech/amd64-mcp-litellm:0.1.6`（候選 302c96d，build／container／supply-chain gate 全過；發佈候選完整獨立審查與複審 APPROVE WITH NOTES）；0.1.0–0.1.5 tag 不覆寫。
- 已知問題（延到 0.1.7）：
  - 被 policy 拒絕的 tools/call 仍回 HTTP 403（0.1.5 發佈候選審查 F7；上面 R2 的修正只涵蓋被拒的 initialize）。Python MCP SDK
    1.x client 收到這個 403 會整段斷線、不送 DELETE，每次在子程序留下一個 session，一直留到子程序重啟（見下一項）。
  - 子程序沒有閒置回收：一般 session 也只在 client 送 `DELETE /mcp` 或子程序重啟（含 Add-on 重啟）時結束，client 當掉、斷線或
    結束時沒送 DELETE，session 就一直留著、佔用記憶體。沒帶 `Mcp-Session-Id` 的 initialize 以外請求（例如 ping、tools/list、
    GET、DELETE）也會讓子程序開一個新 session 並留下來。client 用完請送 `DELETE /mcp`（帶 `Mcp-Session-Id`）。

## 0.1.5 — 2026-10-06 公開（experimental）

- gateway（0.1.4 複審與 0.1.5 審查的縱深防禦建議）：client 收到的每個回覆都由 gateway 重新組成，只含 jsonrpc、id 與 result 或 error 其中一個，error 只保留 code（一律整數）、message、data；子程序加在回覆最外層的其他欄位不再轉送（TS client 會把未知的最外層欄位名稱放進錯誤訊息），error 裡多出的欄位也一併去掉，ping 成功一律回 `{}`，其他 result 照子程序內容轉送（工具清單與 capabilities 照舊過濾）。POST 的 SSE 串流只轉送這個請求自己的回覆，送出後立即結束；GET 串流不轉送任何回覆（各子程序都沒有可續傳的事件紀錄）。錯誤碼超出 32 位元範圍或 message 不是字串時，改成 gateway 自己的錯誤。initialize 回覆的 protocolVersion 必須是日期格式（YYYY-MM-DD），否則回 502。
- 來源紀錄（ledger）：補列 backend_policy.py 在六個 Python venv（五支商店服務加上封存的 Odoo Manage 原始碼）守住的 httpx／httpcore 原始碼、odoo_b2_scope.py 在 Odoo venv 漏列的 4 個原始碼，以及 bounded_tools.py 在 OpenDesign venv 守住的 MCP SDK 原始碼。測試以 Python 語法樹找出各服務載入哪些共用模組（各種 import 寫法、常數參數的動態載入與間接載入，掃描服務內所有 Python 檔），逐一確認對應 venv 都有列；判定不了的載入方式（exec／eval、非常數參數、改名或以字串取得的載入函式）會讓測試失敗。
- 基底映像：`python:3.13.16-slim-bookworm` 改釘 Docker Hub 2026-10-06 重建版（amd64 `f0408636…`），已內含 libpcre2-8-0 10.42-1+deb12u2 與 perl-base 5.36.0-7+deb12u4 安全更新；原本從 Debian snapshot 升級 libpcre2 的步驟已移除。
- 映像 `ghcr.io/woowtech/amd64-mcp-litellm:0.1.5`（候選 0c66bd0，build／container／supply-chain gate 全過；發佈候選完整獨立審查 APPROVE WITH NOTES）；0.1.0–0.1.4 tag 不覆寫。

## 0.1.4 — 2026-10-06 公開（experimental）

- gateway（0.1.2 審查留下的建議，經 0.1.4 發佈候選審查補強）：子程序對請求的 4xx／5xx 回應保留狀態碼（404 讓 client 重開 session、Retry-After 照轉），內容改由 gateway 產生（JSON-RPC 錯誤 -32000 與 HTTP 狀態說明），不再轉送子程序的文字；失敗的 initialize 不帶 session id；子程序回 401／403（拒絕的是 gateway 自己的權杖）以及任何請求、DELETE、通知收到 1xx／3xx 都回 502。子程序的通知只轉 `notifications/tools/list_changed`，而且是 gateway 固定的內容；progress、log 等其他通知不轉送。回覆必須正好帶 result 或 error 其中一個；錯誤碼不是 JSON 整數（例如字串 "-32042"）或為 URL elicitation（-32042）時，改成 gateway 自己的錯誤、不帶子程序資料（JSON、SSE、initialize 都適用）。
- 共用核心：原生探測名稱改由健康檢查實際使用的探測取得（0.1.3 發佈候選審查 #6，行為不變）。
- 映像 `ghcr.io/woowtech/amd64-mcp-litellm:0.1.4`（候選 73a40eb，build／container／supply-chain gate 全過；發佈候選完整獨立審查 APPROVE WITH NOTES）；0.1.0–0.1.3 tag 不覆寫。

## 0.1.3 — 2026-10-06 公開（experimental）

- gateway：`/mcp` 的所有 HTTP 方法都先驗 Bearer 再回 405（`Allow: GET, POST, DELETE`）；TRACE、PROPFIND 等以前由框架在驗證前就回 405，Allow 清單還列了 gateway 實際拒絕的方法（0.1.2 審查的 NIT）。
- 健康檢查：子程序回的 `protocolVersion` 須符合與 session id 相同的規則（可列印 ASCII、不含空白、1–256 字元）才沿用為標頭；否則該輪判定失敗，並照常帶 session id 關閉 session（以前遇到無法當標頭的值會在清理前出錯，留下子程序 session）。
- 映像 `ghcr.io/woowtech/amd64-mcp-litellm:0.1.3`（候選 a0db7d7，build／container／supply-chain gate 全過；獨立審查：Odoo 健康探測 APPROVE WITH NOTES、意見已修，發佈候選完整審查 APPROVE WITH NOTES）；0.1.0、0.1.1、0.1.2 tag 不覆寫。

## 0.1.2 — 2026-10-06 公開（experimental）

- 初始化時子程序沒有回覆（例如後端連不上、子程序無法建立連線階段），gateway 改回 HTTP 503＋JSON-RPC 錯誤 `BACKEND_UNAVAILABLE`（附 Retry-After），不再給出 200 空回應與失效的 session id；串流回應只保留回覆那個事件的 id／event／retry 行，其餘事件（heartbeat、通知）不轉送；過大或格式錯誤的回覆回 502。
- 成功回應只接受 gateway 能解析、過濾的格式（0.1.2 獨立資安審查與複審的建議，舊版即有的缺口）：GET 必須是 SSE；請求的回覆必須是 SSE 或 HTTP 200 的 JSON，其他 2xx、其他、重複或缺少的媒體型別回 502，且不轉送該回應的任何內容（即使宣稱長度為 0）；通知與 DELETE 的回應只帶狀態與轉送標頭；轉送的標頭值須合規（不合規就丟掉，避免子程序的怪字元讓 gateway 出錯並佔住連線名額）；HEAD／PUT／PATCH／OPTIONS 驗證後回 405、不轉給子程序；轉給子程序的 Accept 固定；子程序回 100–599 以外的狀態碼時回 502；initialize 回覆的 session id 無法轉送時回 502；會溢位成無限大的數字（如 `1e400`）視同 NaN 拒絕；媒體型別不分大小寫、不帶參數比對，送給 client 的固定是 `text/event-stream` 或 `application/json`。JSON 回覆一律解析、須回應同一個請求（id 與型別相同），過濾後重新序列化；批次回 502。SSE 事件依看得懂的行重組（data、合規的 id／event／retry 與純 ASCII 註解），BOM、未知欄位等不轉送，單獨的 CR 視為格式錯誤；空 data 的 priming 事件照常通過；子程序發起的反向請求（elicitation、sampling、roots 等）不轉送。請求內容任何位置含孤立 surrogate 回 400。轉給子程序的 initialize 一律帶 `capabilities: {}`（gateway 不轉 sampling／elicitation 等反向請求）。
- 健康檢查：子程序的異常回應（不合規的 session id、怪異內容）只會讓就緒狀態為 false，不再讓整個 add-on 停止（獨立審查發現的舊問題）。
- bootstrap 在 HA 還原修復後，等 `/data/mcp` 通過最後檢查才印 `re-owned` 訊息；修復時暫時調高的 soft `RLIMIT_NOFILE` 修完即還原，不再沿用到管理程序。
- 映像 `ghcr.io/woowtech/amd64-mcp-litellm:0.1.2`（候選 114f23a，build／container／supply-chain gate 全過；獨立 SPEC 與安全審 APPROVE WITH NOTES、意見已修，修正複審 APPROVE WITH NOTES）；0.1.0、0.1.1 tag 不覆寫。

## 0.1.1 — 2026-10-05 公開（experimental）

- HA 管理權限 `homeassistant_api: true`（負責人 2026-10-05 核准，與 n8n 相同的固定 WebSocket 角色驗證），讓 HA owner／system-admin 能在 Ingress 面板設定後端；provider 90153cb 已 SPEC＋安全審。
- bootstrap 把 runtime `SUPERVISOR_TOKEN` 交給本產品管理程序（僅此一個變數，child 不繼承），供 HA 管理角色驗證使用。
- 修正 HA 還原本 Add-on 後資料變成 root 擁有、無法啟動的問題：bootstrap 只在資料剛好屬 root 時，第一遍核准並握住每個 inode、第二遍只改這些重驗過的 inode（R1 修正 d687cad、19892a3，獨立 SPEC＋安全審）。
- 新增五個有界 metadata 讀取工具（Pi 候選 cf7fea1）；回歸修正 57609d1 後全套通過。
- 映像 `ghcr.io/woowtech/amd64-mcp-litellm:0.1.1`（候選 d2e1e3b，build／container／supply-chain gate 全過）；0.1.0 tag 不覆寫。

## 0.1.0 — 2026-10-05 公開（experimental）

- 新增獨立 amd64 root-context 封裝、Supervisor 2026.09.3 安全子集 manifest。
- runtime：FastMCP 3.4.5 / pinned public vendor；40 個來源工具中支援 7，33 個明列 withheld，
  [工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md) 尚未完成功能平齊。
- 8099 Ingress-only／8081 可選 LAN／3000 loopback；保護模式、init true；不設
  backend-dependent watchdog、不開 HA/Supervisor/Docker API 權限。
- 共用 UI 已本地整合，exact grants/typed forms 已接 Core；本產品正式角色路徑仍封鎖；未建置 image、未做 HA E2E。
- 資料 v3：完整 v1/v2 migration、新增空 exact grants；UI 保存完整 grants+global false，disabled 優先，其他產品不可匯入 n8n state。
- 手動更新前做受控 cold backup（只中斷本 Add-on，含秘密）；rollback 必須使用相容
  image+完整資料，不可盲目 downgrade。請見 [完整步驟](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md)。
- 授權／公開去密／映像／實際 backend／Ingress/client／備份還原驗收仍待批准。
