# Nextcloud 操作說明

## 現況與範圍

**0.1.8（experimental）**：映像 `ghcr.io/woowtech/amd64-mcp-nextcloud:0.1.8` 由候選 04ae485 建置，通過 container/mock 與
supply-chain gate（2026-10-11），以測過的 image ID 推送、匿名拉取驗證通過，可從本 repository 的 HA 商店安裝；變更見 [CHANGELOG](CHANGELOG.md)，
測試 HA 回歸進行中。0.1.7 是本產品第一個版本（先前版本號沒有 Nextcloud 映像）；2026-10-08 第一次在測試 HA 實測（[0.1.7 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.7.md)）：讀取 6/6、寫入與未知工具 5/5 拒絕、
後端斷線、重啟、child 恢復、權杖輪替、一般使用者 403 皆通過；後端是同一台 HA 的 Nextcloud 35.0.1（專屬測試使用者，只讀它自己的檔案）。
寫入工具尚未在實機授權實測。
[發佈關卡](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/release.md) 的人工 gates 和其他產品一樣維持關閉。

管理面板與其他產品相同：管理程序以 runtime `SUPERVISOR_TOKEN` 連固定 `ws://supervisor/core/websocket`，只查
`config/auth/list`，確認 Ingress 使用者是 active 的 owner 或 system-admin 才放行；token 只給管理程序，child 不繼承。
此 token 具**廣泛 Core 管理能力**（`homeassistant_api: true`），負責人已於 2026-10-08 核准本 Add-on 使用（與其他六支相同，
只用於管理面板確認 HA owner／管理員）。`panel_admin` 不是角色授權。

**支援的 Core 版本**：管理面板只在本版審查過的 HA Core 版本運作（0.1.7、0.1.8：2026.7.2–2026.9.4 與 2026.10.0，和其他六支共用同一個驗證器）。
其他版本（含之後的 patch 與 beta）整個管理面板都回 403，看起來和「不是管理員」完全一樣（add-on 紀錄也沒有訊息）；
MCP 端點（Bearer token）不受影響。新的 Core 版本要等 add-on 發新版才支援，升級 Core 前請先對照這份清單。

本產品 runtime：**FastMCP 3.4.5**，子程序是 WOOWTECH 的 MIT 套件 `nextcloud_mcp_server` v0.1.5（commit 4e09c86）
放在 `apps/nextcloud/vendor`，對上游的修改逐檔記在 `docs/provenance/runtime-sources.json`。上游 9 個工具全部支援：

| 工具 | 類型 | 預設 |
|---|---|---|
| `get_file_tree` | 讀：列出資料夾（深度 1–3，最多 500 筆） | 開 |
| `get_file_content`、`read_text_file` | 讀：UTF-8 文字檔（最大 1 MiB），後者另回 etag | 開 |
| `list_calendars`、`list_tasks` | 讀：行事曆與任務（VTODO，不能改） | 開 |
| `create_text_file` | 寫：只建新檔，從不覆寫 | 關，需授權 |
| `update_text_file` | 寫：etag 相符才整份取代 | 關，需授權 |
| `upload_file` | 寫：上傳任意檔案（base64），不帶 etag 只建新檔 | 關，需授權 |
| `delete_file_checked` | 寫：etag 相符才刪單一檔案（進垃圾桶） | 關，需授權 |

逐名 schema／預設以 [工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md) 與 [machine manifest](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.json) 為準。
寫入授權只認逐工具的 exact grant；舊的全域寫入開關不授權任何 Nextcloud 工具。停用（disabled）永遠優先。
政策一變更，子程序就以新的環境變數重啟：有授權寫入工具才 `NEXTCLOUD_MCP_READONLY=false`，有授權
`delete_file_checked` 才 `NEXTCLOUD_MCP_ALLOW_DELETE=true`，其他沒開放的工具列入 `NEXTCLOUD_MCP_DISABLED_TOOLS`，
子程序根本不註冊；gateway 另外再以本地 schema 檢查每個呼叫，tools/list 也由 gateway 依本地定義重建。

## 後端與設定主權

一個 Add-on 只有一個 Nextcloud 帳號：**url（Nextcloud 根網址）、username、app_password**。

- 請在 Nextcloud「個人設定 → 安全性 → 裝置與工作階段」為本 Add-on 建立專用 **App 密碼**，不要填登入密碼。
  建議用權限最小的專用帳號，只分享需要的資料夾給它。url、使用者名稱與 App 密碼存檔時就會檢查：
  `backend_policy` 會拒絕的網址（路徑含 `.`／`..` 片段、解碼後含 `%` 或 `\`、metadata 類主機）與空白或前後有空白的帳密都存不進去。
  主機名稱含中文等非 ASCII 字元（IDN，例如 `.台灣`）時，請改填 `xn--` 形式（punycode），例如 `https://雲端.example.tw` 要填成
  `https://xn--suzq78c.example.tw`；面板會直接顯示要填的 `xn--` 形式。
- **帳密錯誤會鎖住，而不是一直重試**：Nextcloud 回 401（帳密錯誤）之後，子程序不再用這組帳密連 Nextcloud，工具與健康檢查
  都直接回 `BACKEND_HTTP_ERROR status=401`，直到子程序重啟（在面板重新儲存後端設定，或重新啟動 Add-on）。回 429（暴力破解防護
  擋下）時同樣停止連線，但只停 5 分鐘（gateway 的傳輸層看不到 Retry-After，所以一律用預設的 5 分鐘），之後再試一次。
  這是為了避免每 15 秒一次的健康檢查不斷送出失敗的登入，觸發 Nextcloud 的暴力破解防護、把 Add-on 所在的 IP
  （在家用 NAT 或沒設 trusted_proxies 的反向代理後面，常是整個網路共用的 IP）封鎖，連同一 IP 的網頁登入與其他用戶端一起被擋。
- **輪替 App 密碼**（沒有任何失敗登入）：先在 Nextcloud 建立新的 App 密碼 → 到面板「後端」選「取代」存入新密碼
  （存檔會以新密碼重啟子程序）→ 等面板顯示後端可連線 → 再到 Nextcloud 撤銷舊密碼。
- **只撤銷、不再使用**：先在面板清除後端連線（清除後子程序停止、健康檢查不再登入），或停止 Add-on，然後再撤銷。
  （管理面板只在 Add-on 執行中才能開啟，所以要換新密碼時不要先停止 Add-on。）
- **必須立刻撤銷**（例如密碼外洩）：可以先撤銷。Add-on 通常只會失敗登入一次就鎖住；若 Nextcloud 延遲回應或撤銷時有請求
  正在進行，可能多幾次（健康探測最多兩次，每個在途的工具請求一次），之後就不再嘗試，到面板存入新密碼後自動恢復。
- 若 IP 已被封鎖：Nextcloud 管理員可執行 `occ security:bruteforce:reset <ip>` 清除該 IP 的紀錄；長期可在
  「管理設定 → 安全性」的暴力破解 IP 白名單（Brute-force settings app）加入 Add-on 所在的 IP。修好密碼後也要等舊紀錄過期或先清除，
  否則登入可能被延遲到超過健康檢查的逾時，readiness 會停在 503。
- 後端憑證／URL、token、policy 由 GUI/state 擁有；HA options 為空，不放 credentials、不覆寫 state。
- 所有後端請求都經 gateway 的 `backend_policy`：DNS 只解析一次並檢查所有位址類別、連線釘在檢查過的位址、
  不跟隨轉址、不讀 proxy 環境變數、TLS 一定驗證。所以 URL 必須是最終位址（轉址會回 `BACKEND_HTTP_ERROR status=30x`）；
  私有 CA 的 Nextcloud 目前不支援（`CA_BUNDLE` 未提供，需另行審查），`http://` 只建議在可信任的內網使用。
- 錯誤代碼：凡是後端回應或連線造成的錯誤，訊息都以公開代碼開頭，後面接說明，例如
  `BACKEND_HTTP_ERROR status=404: "x" does not exist.`、`BACKEND_HTTP_ERROR status=412: "x" changed since it was read (current etag …)`、
  `BACKEND_INVALID_RESPONSE`（無效、無法解碼或過大的回應）、`BACKEND_TIMEOUT`、`BACKEND_UNAVAILABLE`、`BACKEND_DESTINATION_DENIED`、
  `BACKEND_BUSY`；鎖存的 401／429 與轉址也是 `BACKEND_HTTP_ERROR status=N`。`delete_file_checked` 在送出前發現 etag 不符時是
  `ETAG_MISMATCH:`（只讀取了檔案資訊，沒有送出刪除請求）。工具自己的拒絕（需要檔案卻是資料夾、文字工具遇到二進位檔、未知的行事曆 id、行事曆沒有
  VTODO）與輸入檢查錯誤不帶代碼。訊息中的 etag 只顯示合法的 etag 字元（最長 256），否則顯示 unknown；Nextcloud 回應的內容一律不轉給 client。

## 已知限制

- gateway 每個 MCP 請求最多 256 KiB：`create_text_file`／`update_text_file` 的內容與 `upload_file` 的 base64 都要小於此值。
- 檔名或路徑含 `%` 的檔案會被 `backend_policy` 拒絕（`BACKEND_DESTINATION_DENIED`）；直接讀寫這種檔案或資料夾都會失敗。
  `get_file_tree` 往下列子資料夾（depth 2–3）時，遇到名稱含 `%` 的子資料夾會略過它、不中斷整個列表，並把 `truncated` 設為 true。
- `list_tasks` 不指定行事曆時，遇到 gateway 拒絕（例如 id 含 `%`）或無權讀取（403／404）的行事曆會略過，結果多一個
  `skipped_calendars` 計數。直接指定時：被 gateway 拒絕的行事曆（例如 id 含 `%`）回 `BACKEND_DESTINATION_DENIED`，
  無權讀取或已不存在的回 `BACKEND_HTTP_ERROR status=403` 或 `status=404`。
- 單一任務物件巢狀超過 32 層（或超過 1 MiB）會略過，計入 `skipped_large_objects`。
- 不能建立資料夾、不能修改任務、不展開重複任務；`list_tasks` 描述截 500 字。
- Nextcloud 的 etag 大約以秒為單位：同一個檔案在一秒內連續寫兩次，etag 可能不變。這時 `update_text_file`／`upload_file`
  的結果會多一個 `note` 欄位提醒，下一次有條件寫入前請等一秒。

## 網路、健康與更新

- `8099`：Ingress-only，無主機 mapping；不是 MCP endpoint。
- `8081/mcp`：Bearer Streamable HTTP；`8081/tcp: null` 預設不公開 LAN mapping。
- `3000`：child loopback-only，永不暴露；子程序的 Host/Origin 檢查只接受 localhost／127.0.0.1。
- Session：先 initialize，之後每個請求都帶 `Mcp-Session-Id`。initialize 以外沒帶 `Mcp-Session-Id` 的請求一律回 400，不會開 session（0.1.8 起；這個檢查排在 Bearer 401、方法 405、Origin 403 與 policy 403 之後）。client 用完要送 `DELETE /mcp`（帶 `Mcp-Session-Id`）；沒送的 session 閒置 30 分鐘後由子程序結束（0.1.8 起；以前要等子程序重啟），之後用它的請求回 404（有 id 的請求與 GET 是 JSON-RPC 錯誤，通知與 DELETE 沒有內容），client 要重新 initialize。MCP child 重啟（含 Add-on 重啟）後舊 session 也會失效。詳見 [client 文件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。

後端健康檢查用子程序私有的 `woow_backend_probe`（不在工具清單，gateway 不列出也不授權）：每 15 秒用一個新的連線
讀一次 OCS `cloud/user`，只回 ok 與使用者 id，不佔用工具的連線，也不讀任何檔案；公開工具全部停用時照樣運作。
後端斷線時 readiness 回 503，但不重啟 Add-on（故意不設 watchdog）。資料夾權限、備份還原與更新流程同其他產品，
見 [操作指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md) 與 [更新備份回復](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md)。

## 發佈與尚未通過關卡

本產品尚需 source/license/secret、image、HA 實測（真實 Nextcloud 版本與受限帳號）、管理員及 non-admin、Ingress UX、
LAN client、backup/restore 與效能證據。其他產品通過不能替本產品背書。
