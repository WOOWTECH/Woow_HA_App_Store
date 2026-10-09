# Nextcloud Changelog

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
