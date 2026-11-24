# Nextcloud 操作說明

## 現況與範圍

**0.2.1（experimental，2026-10-15 上架商店）**：映像 `ghcr.io/woowtech/amd64-mcp-nextcloud:0.2.1`（GitHub tag／release `v0.2.1`，以映像建置 commit `88a707f` 為準）。0.2.1 起是完整版：上游 9 個工具全部開放，全部工具與寫入預設開啟（管理面板可逐一停用或取消寫入），後端錯誤回原始訊息（add-on 持有的憑證換成 `[REDACTED]`），見下方說明與 [CHANGELOG](CHANGELOG.md)。上架歷程：0.1.10（2026-10-13）、0.1.11、0.1.14（2026-10-14）與 0.2.1 已上架商店；0.1.12、0.1.13、0.2.0 映像只推 GHCR、未上架。下一段是 0.1.9 時的建置與回歸紀錄（測試 HA 的回歸紀錄目前到 0.1.9）。

**0.1.9 時的紀錄（experimental）**：映像 `ghcr.io/woowtech/amd64-mcp-nextcloud:0.1.9` 由候選 57c96f2 建置，通過 container/mock 與
supply-chain gate（2026-10-11），以測過的 image ID 推送、匿名拉取驗證通過，可從本 repository 的 HA 商店安裝；只加上 Core 2026.10.1 支援，見 [CHANGELOG](CHANGELOG.md)，
2026-10-11 已在測試 HA 回歸（[0.1.9 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.9.md)）；0.1.8 已在測試 HA 回歸（[0.1.8 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.8.md)）。0.1.7 是本產品第一個版本（先前版本號沒有 Nextcloud 映像）；2026-10-08 第一次在測試 HA 實測（[0.1.7 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.7.md)）：讀取 6/6、寫入與未知工具 5/5 拒絕、
後端斷線、重啟、child 恢復、權杖輪替、一般使用者 403 皆通過；後端是同一台 HA 的 Nextcloud 35.0.1（專屬測試使用者，只讀它自己的檔案）。
寫入工具尚未在實機授權實測。
[發佈關卡](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/release.md) 的人工 gates 和其他產品一樣維持關閉。

管理面板與其他產品相同：管理程序以 runtime `SUPERVISOR_TOKEN` 連固定 `ws://supervisor/core/websocket`，只查
`config/auth/list`，確認 Ingress 使用者是 active 的 owner 或 system-admin 才放行；token 只給管理程序，child 不繼承。
此 token 具**廣泛 Core 管理能力**（`homeassistant_api: true`），負責人已於 2026-10-08 核准本 Add-on 使用（與其他六支相同，
只用於管理面板確認 HA owner／管理員）。`panel_admin` 不是角色授權。

**支援的 Core 版本**：管理面板只在本版審查過的 HA Core 版本運作（0.1.7、0.1.8：2026.7.2–2026.9.4 與 2026.10.0；0.1.9 起再加 2026.10.1；0.4.2 起再加 2026.10.2–2026.10.4；0.4.14 起再加 2026.11.0–2026.11.2；和其他六支共用同一個驗證器）。
其他版本（含之後的 patch 與 beta）整個管理面板都回 403；0.4.1 以前看起來和「不是管理員」完全一樣（add-on 紀錄也沒有訊息），0.4.2 起管理面板改顯示「這個 HA Core 版本尚未審核：<版本>」，add-on 紀錄也記一行同樣的說明（不含權杖）；
MCP 端點（Bearer token）不經這項檢查，不受影響。新的 Core 版本要等 add-on 發新版才支援，升級 Core 前請先對照這份清單。0.4.3 起，舊版升級後自動全開的設定在未審核的 Core 上也無法用管理面板還原或調整：請先把 add-on 更新到審過這個 Core 的版本，再到管理面板「還原升級前的限制」；需要立刻限制 MCP 時先停止 add-on（進階的離線還原步驟見 [legacy migration](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/legacy-migration.md#when-the-panel-refuses-an-unreviewed-core)）。

本產品 runtime：**FastMCP 4.1.3 / MCP SDK 2.3.0**（0.4.0 起；0.3.4 是 FastMCP 3.4.11 / SDK 1.30.0，之前 FastMCP 3.4.5），子程序是 WOOWTECH 的 MIT 套件 `nextcloud_mcp_server` v0.1.6（commit 8aa6be3，0.4.8 起；0.1.7–0.4.7 是 v0.1.5，commit 4e09c86）
放在 `apps/nextcloud/vendor`，對上游的修改逐檔記在 `docs/provenance/runtime-sources.json`。上游 9 個工具全部支援：

| 工具 | 類型 | 預設 |
|---|---|---|
| `get_file_tree` | 讀：列出資料夾（深度 1–3，最多 500 筆） | 開 |
| `get_file_content`、`read_text_file` | 讀：UTF-8 文字檔（最大 1 MiB），後者另回 etag | 開 |
| `list_calendars`、`list_tasks` | 讀：行事曆與任務（VTODO，不能改） | 開 |
| `create_text_file` | 寫：只建新檔，從不覆寫 | 開，可逐一關閉 |
| `update_text_file` | 寫：etag 相符才整份取代 | 開，可逐一關閉 |
| `upload_file` | 寫：上傳任意檔案（base64），不帶 etag 只建新檔 | 開，可逐一關閉 |
| `delete_file_checked` | 寫：etag 相符才刪單一檔案（進垃圾桶） | 開，可逐一關閉 |

逐名 schema／預設以 [工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md) 與 [machine manifest](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.json) 為準。
「預設」指新安裝，以及從 0.1.x 升級時一次（state schema 4 遷移：四個寫入 grant 全開、0.1.x 的停用清單清空，token 與連線保留）；之後管理員取消的寫入或停用的工具，重啟與升級都維持。從 0.1.x 升級在 0.3.0–0.4.1 要先經管理面板的升級確認頁；**下一版起（未發版，負責人 2026-10-27 決定）**第一次啟動自動一次性全開、MCP 立刻可用，事後通知只在管理面板（與 add-on log 的一行），升級後請打開管理面板查看，可在那裡「還原升級前的限制」（只關回舊設定停用的工具與沒授權的寫入）或「保持全開，不再提示」（[legacy migration](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/legacy-migration.md)）。**風險：網址＝這個帳號的完整檔案權限**，client 不需先授權就能建立、覆寫、上傳與刪除檔案；App 密碼用權限最小的帳號，只保留需要的寫入（見 [寫入預設開啟](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#寫入預設開啟)）。0.2.1 起 tools/list 用子程序自己的 inputSchema，tools/call 參數原樣轉給子程序驗證；請求上限 16 MiB（上傳 10 MiB）。錯誤訊息在對照文字後附上 Nextcloud 自己的訊息（0.2.1 起，含 403 與 5xx；401、429 仍為固定文字）。
寫入授權只認逐工具的 exact grant；舊的全域寫入開關不授權任何 Nextcloud 工具。停用（disabled）永遠優先。
政策一變更，子程序就以新的環境變數重啟：有授權寫入工具才 `NEXTCLOUD_MCP_READONLY=false`，有授權
`delete_file_checked` 才 `NEXTCLOUD_MCP_ALLOW_DELETE=true`，其他沒開放的工具列入 `NEXTCLOUD_MCP_DISABLED_TOOLS`，
子程序根本不註冊；gateway 另外檢查每個呼叫的工具名、停用與寫入授權。

**MCP 提供的內容**：這個 add-on 透過 MCP 只提供工具（tools）：`initialize` 宣告的能力只有 `tools`，`prompts/list`、`resources/list` 等請求回 -32601（Method not found）。`initialize` 另外送出一段固定的 server instructions（只能用管理員設定的那一個帳號、路徑規則），與 WOOW PaaS 的 Nextcloud MCP 相同。負責人 2026-11-07 決定維持只提供工具。

## 後端與設定主權

每個帳號一個 Nextcloud 帳號：**url（Nextcloud 根網址）、username、app_password**（0.5.0 起一個 Add-on 可以有預設帳號＋最多 3 個額外帳號，見下方「多帳號」）。

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

## 多帳號（0.5.0 起）

0.5.0 起這個 add-on 開通多帳號（多帳號第一批 train A，與 LiteLLM、Nextcloud、EMQX 同版；Odoo 先於它們以自己的 0.5.0 開通）：除了預設帳號（就是 0.4.x 的設定與權杖，升級後不變），HA 管理員可以在管理面板再新增最多 3 個帳號。
升級後只用預設帳號的安裝，權杖、兩條網址、`state.json`、工具政策與子程式都不變；仍看得到的改變列在 [CHANGELOG](CHANGELOG.md) 0.5.0 段。完整規則見
[多帳號契約](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/multi-profile/contract.md)（開通後預設帳號會變的事：第 1.4 節）與[操作指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#多帳號產品開通後)。

- **每個帳號一組**：Nextcloud 連線（url、username、App 密碼）、一把 MCP 權杖與它的兩條網址、一份工具政策、一個子程式。新帳號複製預設帳號當下的工具政策（之後各自獨立），後端連線是空的，要另外設定。「MCP 用戶端端點」全 add-on 一個，
  在預設帳號設定。帳號上限（3）與記憶體數值（每個子程式 160 MiB）是暫定，目標硬體量測（HM-19c）後定案；可用記憶體或開檔數不夠時上限更低，新增帳號回 409。
- **常見用法**（和 WOOW PaaS 相同）：同一台 Nextcloud，預設帳號接一個 Nextcloud 使用者，額外帳號各接另一個使用者（各自的 App 密碼）；每個 AI 代理只拿自己那個帳號的網址。看得到什麼由那個使用者在 Nextcloud 的權限與分享決定：帳號之間的資料邊界是各帳號的 Nextcloud 使用者，不是這個 add-on。
- **面板的帳號頁**：面板頂端的帳號選單（只有預設帳號時也有）切換、新增、改名、刪除帳號；刪除要兩段確認，先撤銷權杖、抹掉後端憑證再刪，
  不能復原；預設帳號不能改名或刪除。切到某個帳號後，「總覽」「後端連線」「工具權限」「連線與權杖」「診斷與維護」都是那個帳號的。選擇只放在
  頁面記憶體，重新整理回到預設帳號。開面板時瀏覽器 console 有一筆 400（`profile_id_required`）是預期的。
- **每個帳號的網址**：Bearer 一律是 `<端點>/mcp`、帶那個帳號的權杖；密鑰網址每個帳號各一條 `…/private_<那個帳號的權杖>/mcp`。只看權杖決定是
  哪個帳號（8081 不看 `X-MCP-Profile`、cookie 或查詢參數）；錯的、撤銷的、已刪帳號的權杖照舊：Bearer 401、密鑰網址 404。到那個帳號的
  「連線與權杖」顯示、複製、重新產生或撤銷它的權杖，不影響別的帳號；面板產生的範例名稱，額外帳號是 `woow-nextcloud-<帳號 id 前 8 碼>`。
  見 [client 文件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md#多帳號產品開通後)。
- **一個代理只接一個帳號**：每個帳號的 `serverInfo.name` 與工具名稱都相同（和 PaaS 一致）。同一個代理同時接兩個帳號時，模型分不出哪個工具是
  哪個帳號的，可能把寫入送到錯的帳號。要用兩個帳號就開兩個代理或兩個對話；Claude.ai 每個帳號各新增一個自訂連接器、各貼自己的密鑰網址。
- **換後端身分會換權杖**（和 PaaS 一致）：改 url 或 username（含清空連線）時，同一次存檔換新的 MCP 權杖，兩條舊網址立即失效：到「連線與權杖」複製新的，更新所有用戶端。只改 App 密碼、第一次設定、權杖已撤銷時不換；貼上的頁面路徑（`index.php`、`remote.php`、`ocs`、`apps`、`login`、`settings`）會先被切掉再比，網址只差 scheme、host 的大小寫、預設 port 或結尾斜線時也不換。網址改到另一台伺服器（scheme、host 或 port 變了）時要一起重填 App 密碼，否則不存（422）。存檔回 503 時重新啟動 add-on，重啟後到「連線與權杖」確認網址（權杖可能已換）。後端網址不能填 loopback（127.0.0.0/8、::1、`localhost`；0.5.0 之前存的照樣讀得出來，但連不上）。
- **輪替與清除**：「輪替 App 密碼」照舊（只換 App 密碼不換權杖）。「只撤銷、不再使用」先在面板清除後端連線仍可做，但 0.5.0 起清除也會換新權杖：舊網址就此失效，之後重新設定要到「連線與權杖」複製新網址。
- **存工具政策**（單帳號也一樣，0.5.0 起）：政策收緊或沒變不重啟子程式（閘道立刻擋掉新停用的工具，子程式自己的限制下次啟動才跟上）；放寬時只有子程式在執行或啟動中才重啟，停著、退避、失敗或被擋的子程式不會被存檔叫起來，下次啟動用新政策。還原舊政策同一規則。
- **存連線時的正規化**（單帳號也一樣，0.5.0 起）：貼上的頁面路徑被切掉、scheme 與 host 轉小寫、去預設 port 與結尾斜線，帳密去前後空白；只差寫法時沿用已存的寫法。路徑從第一個叫 `index.php`、`remote.php`、`ocs`、`apps`、`login`、`settings` 的段落切起，所以裝在含這種段落的子路徑下（例如 `/apps/cloud`）的 Nextcloud 會被存成那段之前的路徑。
- **暴力破解防護**：Nextcloud 的失敗登入節流推定以來源位址計，add-on 的每個帳號共用同一個位址，一個帳號連續打錯 App 密碼可能讓別的帳號一起被延遲或擋下；實測留給真後端驗收（UC-12）。
- **密鑰網址的來源檢查**：全 add-on 一份清單、所有帳號共用，預設只有 `https://claude.ai`、模式 report-only：清單外的來源照常服務，只在
  add-on log 記一行 `decision=would_deny`（帶帳號 id 前 8 碼）。在「連線與權杖」的「瀏覽器來源檢查」卡片可切 enforce（清單外 403）；
  切之前先看 log 把需要的來源加進清單。政策檔壞掉時每個帳號的密鑰網址都回 503，到面板存一份新的就好。
- **還原與核對**：還原的備份裡有額外帳號時，add-on 在服務前撤銷每個帳號（連預設帳號）的權杖：到預設帳號頁的核對卡逐帳號核對（名稱、後端身分、
  政策摘要都是備份當時的值），按「已核對」後才能重新產生權杖；讀不到設定的帳號會移到隔離區，只能刪除。備份裡沒有額外帳號時，權杖回到備份
  當時的值、不撤銷，面板顯示還原提示：備份後權杖可能外洩就重新產生。還原也把來源檢查設定帶回備份當時的值，沒有提示，還原後到「連線與權杖」
  看一次。虛擬機或磁碟快照的還原、0.5.0 之前做的備份偵測不到：升到最新版後按「診斷與維護」的「全部撤銷」，再逐帳號重新產生。守門每一行 log 的
  意思見 [更新、備份與回復](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md#多帳號版本的還原回退與全部撤銷hm-13bhm-13c)。
- **事故處理**（懷疑某個子程式或帳號被攻破）：① 在「診斷與維護」按「全部撤銷」（面板打不開就停止 add-on）；② 在 Nextcloud 撤銷每個帳號用的 App 密碼（全部帳號都要換），再到面板逐帳號存新憑證；③ 檢查每個帳號的政策與後端網址有沒有被改；④ 檢查帳號清單有沒有多出來的帳號、孤兒或
  隔離目錄；⑤ 必要時還原事故前的備份；⑥ 留 add-on log 與診斷頁（帳號只記 id 前 8 碼；不要貼權杖或密碼）。詳見
  [操作指南的事故處理](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#事故處理懷疑某個子程式或帳號被攻破)。
- **已知限制**：所有帳號的子程式都以同一個系統帳號執行，一個子程式被攻破（例如上游 MCP server 的漏洞）等於整個 add-on 與每個帳號都被完全
  控制，所以不宣稱多租戶，也不宣稱子程式之間隔離。帳號之間的隔離在請求層（各自的名額、位元組額度、權杖）；8081 的連線數全 add-on 共用。
  Nextcloud 的失敗登入節流推定以來源位址計：每個帳號都從同一個位址連 Nextcloud，一個帳號連續打錯 App 密碼可能讓別的帳號一起被延遲或擋下。完整清單見
  [操作指南的已知限制](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#已知限制開通後)。
- **回退**：HA 不能裝回舊版。要回到 0.4.14 只能還原升級前的 add-on 備份（升級後新增的帳號、輪替、撤銷全部消失；之後再升級請按「全部撤銷」、
  逐帳號重新產生）。要關掉多帳號得發一個版號更大的新版（推估一個工作天以上），期間可以停止 add-on，或在面板撤銷、刪除帳號、按「全部撤銷」。
  見 [回退與緊急關閉](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md#回退與緊急關閉多帳號產品開通後)。

## 已知限制

- 大小上限：`create_text_file`／`update_text_file` 的內容與 `read_text_file`、`get_file_content` 讀的文字檔最多 1 MiB（UTF-8，
  子程序的 `NEXTCLOUD_MCP_MAX_TEXT_BYTES`），`upload_file` 的檔案解碼後最多 10 MiB（`NEXTCLOUD_MCP_MAX_UPLOAD_BYTES`）；gateway
  每個 MCP 請求最多 16 MiB，10 MiB 檔案的 base64 約 13.4 MiB，在限制內。
- 檔名、資料夾名稱與行事曆 id 可以含一般的 `%`（例如 `100%-off.txt`、`%18 KDV.xlsx`、`frame_%04d.png`）。會被 `backend_policy`
  拒絕（`BACKEND_DESTINATION_DENIED`）的只有：名稱本身再解碼一次就會變成 `/`、`\`、`.`／`..`、`?`、`#`、NUL 或換行的寫法（例如
  `a%2fb`、`%2e%2e`、`%23 notes`），以及其他伺服器會當成跳脫字元的寫法（`%u` 加四個十六進位字，例如 `10%uface.txt`；`%` 後面接
  全形或其他文字的數字，例如 `%２０`）。直接讀寫這種檔案或資料夾都會失敗。`get_file_tree` 往下列子資料夾（depth 2–3）時遇到這種
  子資料夾會略過它、不中斷整個列表，並把 `truncated` 設為 true。
- `list_tasks` 不指定行事曆時，遇到 gateway 拒絕（例如 id 是 `a%2fb`）或無權讀取（403／404）的行事曆會略過，結果多一個
  `skipped_calendars` 計數。直接指定時：被 gateway 拒絕的行事曆回 `BACKEND_DESTINATION_DENIED`，
  無權讀取或已不存在的回 `BACKEND_HTTP_ERROR status=403` 或 `status=404`。
- 單一任務物件巢狀超過 32 層（或超過 1 MiB）會略過，計入 `skipped_large_objects`。
- 不能建立資料夾、不能修改任務、不展開重複任務；`list_tasks` 描述截 500 字。
- Nextcloud 的 etag 大約以秒為單位：同一個檔案在一秒內連續寫兩次，etag 可能不變。這時 `update_text_file`／`upload_file`
  的結果會多一個 `note` 欄位提醒，下一次有條件寫入前請等一秒。

## 網路、健康與更新

- `8099`：Ingress-only，無主機 mapping；不是 MCP endpoint。
- `8081/mcp`：Bearer Streamable HTTP；`8081/tcp: null` 預設不公開 LAN mapping。
- `8081/private_<token>/mcp`（0.1.14 起）：同一把權杖放在路徑，給無法帶 header 的 Claude.ai 網頁版自訂連接器；網址由管理面板「顯示 Claude.ai 連線網址」產生（需先設定 Claude.ai 連得到的 HTTPS 端點）。權杖錯誤或已撤銷回 404，允許 Origin，其他規則同 `/mcp`。**網址等同密碼**：只貼進 Claude.ai，外洩請重新產生權杖；見 [client 設定](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
- 工具呼叫被拒（0.1.14 起，`/mcp` 與密鑰網址相同）：帶 `Mcp-Session-Id`、格式正確的 tools/call，若工具不存在或未啟用、參數不符、寫入操作未開放或後端未設定，gateway 回 HTTP 200 的 JSON-RPC 錯誤說明原因（`-32602` `Unknown tool`／`Invalid params`／`Operation not permitted`，`-32603` `Backend not configured`；參數錯誤列出欄位與規則，不回顯參數值），讓 Claude 等 client 能自行修正重試；同樣不轉給子程序。沒帶 session 或格式錯誤的請求仍回 403 `{"error":"request denied"}`。
- 後端未設定或連不上時也能連線（0.2.2 起，`/mcp` 與密鑰網址相同）：initialize、`notifications/initialized`、tools/list 一律成功，tools/list 回完整工具清單與 schema（依停用與寫入授權過濾），不再回 HTTP 502，所以 Claude.ai 連接器在設定後端前也加得上去。tools/call 不轉給子程序：未設定回 `-32603` `Backend not configured`；後端連不上（最近一次完成的健康檢查，每 15 秒）回 `-32603` `Backend unreachable`，`data.reason` 附健康檢查得到的原因（憑證換成 `[REDACTED]`）；子程序沒在跑時原因是 `MCP_SERVER_NOT_READY`。這時 gateway 用 add-on 內附、與子程序一致的工具清單回答，並開自己的 session（`woow-local-…`）；設定好後端、子程序通過健康檢查後，這個 session 的下一個請求回 404，client 重新 initialize 即改連子程序。readiness 與管理面板不變（未設定或連不上仍 503）。詳見 [client 文件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
- `3000`：child loopback-only，永不暴露；子程序的 Host/Origin 檢查只接受 localhost／127.0.0.1。
- Session：先 initialize，之後每個請求都帶 `Mcp-Session-Id`。initialize 以外沒帶 `Mcp-Session-Id` 的請求一律回 400，不會開 session（0.1.8 起；這個檢查排在 Bearer 401、方法 405、Origin 403 與 policy 403 之後）。client 用完要送 `DELETE /mcp`（帶 `Mcp-Session-Id`）；沒送的 session 閒置 30 分鐘後由子程序結束（0.1.8 起；以前要等子程序重啟），之後用它的請求回 404（有 id 的請求與 GET 是 JSON-RPC 錯誤，通知與 DELETE 沒有內容），client 要重新 initialize。MCP child 重啟（含 Add-on 重啟）後舊 session 也會失效。詳見 [client 文件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。

後端健康檢查用子程序私有的 `woow_backend_probe`（不在工具清單，gateway 不列出也不授權）：每 15 秒用一個新的連線
讀一次 OCS `cloud/user`，只回 ok 與使用者 id，不佔用工具的連線，也不讀任何檔案；公開工具全部停用時照樣運作。
後端斷線時 readiness 回 503，但不重啟 Add-on（故意不設 watchdog）。資料夾權限、備份還原與更新流程同其他產品，
見 [操作指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md) 與 [更新備份回復](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md)。

## 發佈與尚未通過關卡

本產品尚需 source/license/secret、image、HA 實測（真實 Nextcloud 版本與受限帳號）、管理員及 non-admin、Ingress UX、
LAN client、backup/restore 與效能證據。其他產品通過不能替本產品背書。
