# Nextcloud Changelog

## 0.2.1 — 準備中（未發佈）

- **0.2.0 未上架**：0.2.0 映像已推上 GHCR（標籤不可覆寫）並在測試 VM 實測，但不發佈到 Store；**0.1.14 直接升 0.2.1**，下方 0.2.0 段落的內容（完整版、寫入與工具預設全開、原始錯誤訊息）一併由 0.2.1 發佈。升級遷移與 0.2.0 相同：state schema 3→4 只遷移一次，寫入授權全開、0.1.x 的停用清單清空，token、連線與對外端點保留；0.2.0 寫的 schema 4 state 照樣載入（n8n 另補一個空的 MCP access token 欄位）。
- Nextcloud 錯誤附上 Nextcloud 自己的錯誤訊息（使用者要求原始錯誤）：每個非 2xx 狀態（含 403 與 5xx）在對照文字後加上「Nextcloud: <訊息>」，訊息取自 Sabre `s:message`、OCS `meta/message`（XML 或 JSON）或純文字回應（最多 1000 字）；401、429 仍是固定文字並暫停連線。**更正 0.2.0 段落**：0.2.0 只對部分 4xx 附上 Sabre 訊息，403 與 5xx 仍只有固定文字，「非 2xx 回應附上 Nextcloud 自己的錯誤訊息」的描述不準確。
- 新版候選需獨立建置、掃描與 PaaS HAOS VM 驗收；既有 0.1.x、0.2.0 標籤不覆寫。

## 0.2.0 — 未上架（映像只推 GHCR；內容隨 0.2.1 發佈）

- **完整版**（使用者 2026-10-15 決定）：與原始 MCP server 及 PaaS woow-mcp-server 功能一致，所有工具（含高風險）全部開放、全部預設開啟，管理介面可逐一停用工具或取消寫入。本產品開放上游 9 個工具全部（0.1.x 為 9 個有界子集）：tools/list 用子程序自己的 inputSchema（經 provider-safe 正規化），tools/call 參數原樣轉給子程序驗證，輸出不再截斷或投影。gateway 仍檢查工具名在分類名單內（上游新增但未分類的工具一律拒絕）、未停用、寫入工具或混合工具的寫入 operation 有 grant，被拒時回 JSON-RPC 錯誤（見下方 0.1.14 段落）。
- **寫入預設開啟**：新安裝的 state 每個寫入 grant 都開、`writes_enabled=true`；**既有安裝升級時一次遷移成全開**（state schema 3→4；token、連線與對外端點保留，**0.1.x 的停用清單清空**，升級後所有工具全開）。之後管理員取消的寫入或停用的工具，重啟與後續升級都維持。0.1.x 不接受 schema 4，回退請還原升級前的備份。
- **風險：網址（權杖）＝完整後端權限**。拿到權杖或 Claude.ai 密鑰網址的 client（包括 AI 助理誤判時）不需再授權即可以後端帳號的權限寫入；後端帳號權限要設對，只保留需要的工具與寫入，外洩時立刻重新產生權杖。說明見 [共用指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#寫入預設開啟)。
- Nextcloud `NEXTCLOUD_MCP_READONLY=false`、`NEXTCLOUD_MCP_ALLOW_DELETE=true`；請求上限由 256 KiB 提高到 16 MiB，上傳 10 MiB（base64）與 1 MiB 文字檔可完整送達。
- 保留的安全層：Bearer／密鑰網址驗證（錯誤即 404）與 log 遮罩、session 與併發 slot、子程序出站 DNS pin／TLS／redirect 拒絕、回覆中憑證換成 `[REDACTED]`、原始碼 digest 守門、管理面板 HA 管理員驗證。請求上限提高到 16 MiB。
- 管理面板工具頁加上預設全開的風險提示。
- Nextcloud 錯誤回到上游行為：非 2xx 回應附上 Nextcloud 自己的錯誤訊息（Sabre message），「路徑不在家目錄」的錯誤會顯示家目錄路徑（含帳號 user id）；傳輸失敗的說明仍是上游固定文字。
- **後端錯誤回傳原始訊息**（使用者 2026-10-15 決定，與 PaaS 一致）：拿掉 0.1.x 對後端錯誤的固定代碼遮蔽（例如 `BACKEND_RPC_FAULT`、`BACKEND_UNAVAILABLE`），client 看到後端的實際錯誤文字（例如 Odoo 的 AccessError 訊息、LiteLLM／EMQX 的錯誤 body；傳輸失敗為「代碼: 原因」）。gateway 在每個轉送的回覆中把 add-on 自己持有的憑證（Add-on 權杖、child token、後端 API key／密碼與其 Basic 認證形式）換成 `[REDACTED]`；log 的密鑰網址遮罩不變。**原始錯誤可能含後端內部資訊**（模型、欄位、路徑、版本），請留意誰能拿到網址。
- 新版候選需獨立建置、掃描與 PaaS HAOS VM 驗收（含升級遷移、真實 Claude.ai 連線與完整工具實測）；既有 0.1.x 標籤不覆寫。

## 0.1.14 — 準備中（未發佈）

- 0.1.12、0.1.13 映像已推上 GHCR 但從未發佈到 Store，且不再使用（標籤不可覆寫）；以下原為 0.1.12、0.1.13 準備的內容一併改由 0.1.14 發佈。
- 工具呼叫被拒時改為正常回話說明原因（2026-10-14 經 Claude.ai 實測：參數不符的 tools/call 都只得到 HTTP 403，用戶端只看到傳輸錯誤、無法自行修正）：帶 `Mcp-Session-Id`、格式正確的 tools/call 遇到下列四種拒絕，gateway 回 HTTP 200 的 JSON-RPC 錯誤（`application/json`、`Cache-Control: no-store`）：工具不存在或未啟用 `-32602 Unknown tool`（不區分是哪一種）；參數驗證失敗 `-32602 Invalid params`，`data.errors` 列出欄位路徑、pydantic 錯誤類型與說明（最多 20 筆、每筆 300 字），**不回顯任何參數值**（自訂的鍵名顯示為 `*`，可能夾帶輸入值的錯誤類型改用固定說明）；寫入操作未開放 `-32602 Operation not permitted`（附管理員可在面板開啟的說明）；後端未設定 `-32603 Backend not configured`。權限本身不變：同樣的呼叫照樣被拒、不轉給子程序、不佔連線名額；權杖錯誤仍 401／404，沒帶 session 或格式錯誤的請求仍 403。`/mcp` 與 `/private_<token>/mcp` 相同。修正後尚未以真實 Claude.ai 重測。
- 修正真實 Claude.ai 自訂連接器連不上（2026-10-14 經 Cloudflare 到測試 VM 的實機紀錄）：Claude.ai 先送 `server/discover`、再退回 `initialize`，params 帶 MCP 保留欄位 `_meta`（traceparent 等），gateway 兩者都回 HTTP 403。現在每個允許的方法都接受選填 `params._meta`（必須是物件、序列化後至多 8 KiB，否則仍 403），並在轉給子程序前移除；不認識的 request（例如 `server/discover`、`resources/list`、`prompts/list`）由 gateway 自己回 HTTP 200 的 JSON-RPC `-32601 Method not found`，不認識的 notification 回 202，兩者都不轉給子程序、不需 session、不佔連線名額；權杖檢查仍最先（錯誤權杖仍 401／404）。只接受 `application/json` 的 client 收到 JSON 格式的 initialize 回覆。工具權限、參數驗證、寫入閘與 `/mcp`、`/private_<token>/mcp` 其他規則不變。修正後尚未以真實 Claude.ai 重測。
- 修正 HA 側邊欄打開管理面板顯示「網頁可能暫時離線」：manifest 移除 `ingress_entry: /`。Supervisor 2026.09 以 `/api/hassio_ingress/<token>/` 直接接上 ingress_entry，舊值讓入口變成 `…/<token>//`（404，0.1.11 起七支皆受影響）；不設此鍵即為根目錄。只改 manifest，映像不變。
- 開機預設由 `boot: manual` 改為 `boot: auto`（使用者 2026-10-14 決定）：HAOS／Supervisor 重開機後自動啟動，不必再手動啟動；packaging/validate.py 的 manifest 規則同步改為 auto。
- 新增 Claude.ai 網頁版自訂連接器用的密鑰網址 `/private_<token>/mcp`（七支共用 gateway）：Claude.ai 自訂連接器無法帶 Authorization header，改把同一把 Add-on 權杖放在路徑（重新產生／撤銷同時生效）；權杖錯誤、空白或已撤銷一律回與不存在路徑相同的 404，忽略請求自帶的 Authorization，允許 Origin（不轉給子程序）；`/mcp` 的 Bearer 行為不變（含 Origin 403）。所有 log 把 `/private_…/` 遮成 `/private_[REDACTED]/`。管理面板「連線與權杖」新增「顯示 Claude.ai 連線網址」（需先設定對外端點，經確認後短暫顯示並可複製）。**網址等同密碼，外洩請重新產生權杖。**說明見 [client 設定](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)；尚未以真實 Claude.ai 實測。
- 除上述各項外本產品功能未變更；七支共用版本規則一致升版。
- 新版候選需獨立建置、掃描與 PaaS HAOS VM 驗收（含重開機後自動回來）；既有 0.1.11、0.1.12、0.1.13 標籤不覆寫。

## 0.1.11 — 準備中（未發佈）

- 本產品功能未變更；依既有七支共用版本規則隨同 LiteLLM MCP metadata 修補升版。
- hosted CI 的完整 Python 測試階段使用 UID 0，以執行原有 UID10001 nondumpable proof；不略過測試，不改 builder admission。
- 新版候選需獨立建置、掃描與 PaaS HAOS VM 驗收；既有 0.1.10 標籤不覆寫。

## 0.1.10 — 準備中（未發佈）

- 本產品功能未變更；依既有七支共用版本規則隨同 LiteLLM MCP metadata 修補升版。
- 建置、掃描與實機結果待候選證據；不覆寫 0.1.9 標籤。

## 0.1.9 — 2026-10-11 公開（experimental）

- 管理面板（HA 角色驗證）：支援的 Core 版本加上 2026.10.1（2026-10-10 發佈）。驗證器用到的 21 個 Core 檔案與 2026.10.0 完全相同（[審查紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/ha-role-core-contract.md)）。0.1.8 及更早的版本在 Core 2026.10.1 上整個管理面板回 403（MCP 端點不受影響），升 Core 前先更新本 add-on。
- 映像 `ghcr.io/woowtech/amd64-mcp-nextcloud:0.1.9`（候選 57c96f2，build／container／supply-chain gate 全過；審查沒有 High／Medium）；0.1.0–0.1.8 tag 不覆寫。

## 0.1.8 — 2026-10-11 公開（experimental）

- gateway（0.1.6 發佈候選審查 GATEWAY-2）：除了 initialize，沒帶 `Mcp-Session-Id` 的請求（ping、tools/list、tools/call、通知、GET、DELETE）改由 gateway 直接回 HTTP 400，不再轉給子程序。原本五支 Python 子程序（Odoo、Hermes、OpenDesign、EMQX、LiteLLM；Nextcloud 也一樣）會先為這種請求開一個新 session 再拒絕，而且不會回收：每分鐘一次就一天留下約 1,440 個，直到子程序重啟；n8n 子程序對這種請求、GET、DELETE 本來就回 400、不開 session，但沒有 session 的通知它回 202，現在一樣改回 400。回覆的形狀和以前 gateway 轉出子程序拒絕時相同（有 id 的請求與 GET 是 JSON-RPC 錯誤 -32000「Bad Request」，通知與 DELETE 是沒有內容的 400），只是不再帶子程序新開的 session id。照規範先 initialize 的 client 不受影響；Bearer 與 policy 檢查仍在前面（沒帶或帶錯 token 401、被拒的工具 403）。
- gateway（0.1.6 審查 R1 F6）：initialize 的回覆改由 gateway 自己組成，只保留子程序的 protocolVersion，而且必須是審查過的 MCP 版本（2024-11-05、2025-03-26、2025-06-18、2025-11-25；以前任何日期格式都接受，其他值一律回 502）；capabilities 一律是 `{"tools": {}}`，serverInfo 改成這支 add-on 的名稱與版本（`woow-mcp-nextcloud`、add-on 版號），不再是子程序自己的名稱與版本；子程序的 instructions 不再轉送（Claude Code 會把 instructions 放進模型的 system prompt；EMQX、LiteLLM 子程序的說明寫的是上游全部的工具，包括本 add-on 隱藏或拒絕的工具）。Nextcloud 改送 add-on 審查過的固定說明，內容與 Nextcloud MCP 本身的說明相同（單一帳號、路徑寫法、先讀再寫與 etag 規則）；之後更新 vendored 程式若改了說明，測試會失敗，要先審查再更新 gateway 的副本。
- 子程序（0.1.6 發佈候選審查 GATEWAY-3）：client 用完不送 DELETE 留下的 session，原本要等子程序重啟才結束（本機量測每個約 90–100 KiB，每分鐘留一個就一天多 70–140 MiB）。現在 30 分鐘沒有任何請求的 session 會被結束，client 下一個請求收到 404，依 MCP 規範重新 initialize 即可；使用中的 session 不受影響（gateway 對每個請求最多等 35 秒、每個 stream 最多 120 秒）。
- 映像 `ghcr.io/woowtech/amd64-mcp-nextcloud:0.1.8`（候選 04ae485，build／container／supply-chain gate 全過；0.1.8 的審查、複審與 RR-03 審查都沒有 High／Medium）；0.1.0–0.1.7 tag 不覆寫。

## 0.1.7 — 2026-10-08 公開（experimental）

- 2026-10-09 補充（映像與功能不變，不需要更新）：顯示名稱改為「Woow Nextcloud MCP Server」，圖示改用 Nextcloud 的圖示（[來源](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/provenance/icons.md)）；同時上架 [WOOW HA App Store](https://github.com/WOOWTECH/Woow_HA_App_Store) 與 ha-rebrand 的 Local Download。兩個商店的同名 add-on 在 HA 裡是不同的 add-on，同一台 HA 只裝其中一個來源的。
- 新產品：WOOW Nextcloud MCP。子程序是 WOOWTECH 自己的 MIT 套件 `nextcloud_mcp_server`
  （[Woow_nextcloud_mcp_server](https://github.com/WOOWTECH/Woow_nextcloud_mcp_server) tag v0.1.5，commit 4e09c86），
  原始碼放在 `apps/nextcloud/vendor`；對上游的每一處修改與原因記在 `docs/provenance/runtime-sources.json`。
- 一個 Add-on 連一個 Nextcloud 帳號：根網址、使用者名稱、App 密碼（管理面板設定，不放在 HA options）。
- 工具 9 個全部支援，由 gateway 用本地嚴格 schema 檢查每個呼叫、自己重建 tools/list：
  讀取 `get_file_tree`、`get_file_content`、`read_text_file`、`list_calendars`、`list_tasks` 預設開啟；
  寫入 `create_text_file`、`update_text_file`、`upload_file`、`delete_file_checked` 預設關閉，必須逐項授權。
  子程序只在授權了寫入工具時才以 `READONLY=false` 啟動，只在授權了 `delete_file_checked` 時才設 `ALLOW_DELETE=true`，
  其餘未授權或停用的工具也不在子程序註冊（`DISABLED_TOOLS`）。寫入全部以 etag 防止覆蓋別人改過的版本；
  刪除只刪單一檔案並進 Nextcloud 垃圾桶。
- 後端連線一律經 gateway 的 `backend_policy`（DNS 釘選、位址類別檢查、不跟隨轉址、不走 proxy、TLS 一定驗證）；
  凡是後端回應或連線造成的錯誤都以公開代碼開頭（`BACKEND_HTTP_ERROR status=N`，含 412 衝突與 404；`BACKEND_INVALID_RESPONSE`、
  `BACKEND_UNAVAILABLE`、`BACKEND_TIMEOUT`、`BACKEND_DESTINATION_DENIED` 等），刪除前的本地 etag 不符是 `ETAG_MISMATCH`，
  不轉送 Nextcloud 的錯誤內容。自訂 CA（`CA_BUNDLE`）與關閉 TLS 驗證都不提供。
- 健康檢查用子程序私有的 `woow_backend_probe`（不在工具清單，gateway 不列出也不授權）：每次用新的連線
  讀一次 OCS `cloud/user`，只回 ok 與使用者 id，不佔用工具的連線；公開工具全部停用時照樣運作。
- 限制：gateway 每個請求最多 256 KiB，所以一次能寫入的文字與上傳的檔案（base64 後）都小於 256 KiB；
  檔名含 `%` 的檔案或資料夾會被 `backend_policy` 拒絕（`BACKEND_DESTINATION_DENIED`）；`get_file_tree` 遞迴時略過
  這種子資料夾並設 `truncated: true`，其他資料夾照常列出。
- 帳密錯誤（401）後子程序不再用這組帳密連 Nextcloud、一律回同一錯誤碼，直到子程序重啟（重新儲存後端設定或重啟 Add-on）；
  被 Nextcloud 暴力破解防護擋下（429）時停 5 分鐘再試，避免健康檢查反覆登入失敗而讓 Nextcloud 封鎖 Add-on 所在的 IP。輪替 App 密碼時先建立新密碼、
  在面板存入並確認可連線，再撤銷舊密碼；只撤銷時先清除後端連線或停止 Add-on；緊急撤銷通常只失敗一次（Nextcloud 延遲回應或有請求在途時可能多幾次，見 DOCS）。
  已被封鎖時用 `occ security:bruteforce:reset <ip>` 或暴力破解 IP 白名單解除。
- `list_tasks` 略過 gateway 拒絕或無權讀取的行事曆並回報 `skipped_calendars`；巢狀超過 32 層的任務物件會略過並計入
  `skipped_large_objects`。
- 管理面板存檔時就拒絕 `backend_policy` 不接受的網址、含非 ASCII 字元的主機名稱（請改填 `xn--` 形式，面板會顯示），以及空白或前後有空白的使用者名稱／App 密碼。
- 映像 `ghcr.io/woowtech/amd64-mcp-nextcloud:0.1.7`（候選 7cc8bcb，第一次送 gate 就通過 build／container／supply-chain gate；審查 R1 REQUEST CHANGES，修正後 R2、R3 APPROVE WITH NOTES，最後由交付線做差異檢查）。這是本產品第一個版本：先前版本號沒有 Nextcloud 映像，也不會補建。
- 已知問題（共用 gateway 的既有問題，與其他產品相同，延到 0.1.8）：被 policy 拒絕的 tools/call 回 HTTP 403，Python MCP SDK 1.x
  client 收到會整段斷線、不送 DELETE。子程序與 EMQX 一樣是 FastMCP 3.4.5、啟動時沒有設定閒置回收，沒送 DELETE 的 session
  預期會留到子程序重啟（未另外實測）；client 用完請送 `DELETE /mcp`（帶 `Mcp-Session-Id`），見 docs/operations/clients.md。
