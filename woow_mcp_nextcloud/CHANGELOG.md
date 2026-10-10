# Nextcloud Changelog

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
