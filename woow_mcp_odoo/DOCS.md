# Odoo 操作說明

**0.4.4 候選**：工具頁可調整四個 Odoo 子操作開關，缺欄仍採既有全開值；下文 `=1` 描述的是此預設。儲存後由實際設定決定直接／核准寫入，外層工具授權仍先作用；精確 `model.method` 白名單編輯尚未提供。失敗結果回 MCP `isError:true`，保留 JSON 與 structuredContent 結構，traceback 縮為最後例外行。存入 `odoo_write_switches` 或 token 變更後的 `token_history` 都會讓 0.4.3 拒絕 state；請在升級前備份，降版時還原該備份。映像尚待建置與驗收。


## 現況與範圍

**0.2.1（experimental，2026-10-15 上架商店）**：映像 `ghcr.io/woowtech/amd64-mcp-odoo:0.2.1`（GitHub tag／release `v0.2.1`，以映像建置 commit `88a707f` 為準）。0.2.1 起是完整版：上游 41 個工具全部開放，全部工具與寫入預設開啟（管理面板可逐一停用或取消寫入），後端錯誤回原始訊息（add-on 持有的憑證換成 `[REDACTED]`），見下方說明與 [CHANGELOG](CHANGELOG.md)。上架歷程：0.1.10（2026-10-13）、0.1.11、0.1.14（2026-10-14）與 0.2.1 已上架商店；0.1.12、0.1.13、0.2.0 映像只推 GHCR、未上架。下一段是 0.1.9 時的建置與回歸紀錄（測試 HA 的回歸紀錄目前到 0.1.9）。

**0.1.9 時的紀錄（experimental）**：映像 `ghcr.io/woowtech/amd64-mcp-odoo:0.1.9` 由候選 57c96f2 建置，通過 container/mock 與 supply-chain gate（2026-10-11）；只加上 Core 2026.10.1 支援，見 [CHANGELOG](CHANGELOG.md)。2026-10-11 已在測試 HA 回歸（[0.1.9 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.9.md)）；0.1.8 已在測試 HA 回歸（[0.1.8 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.8.md)）；0.1.7 已在測試 HA 回歸（[0.1.7 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.7.md)；0.1.6 見 [0.1.6 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.6.md)；0.1.5 見 [0.1.5 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.5.md)；0.1.4 見 [0.1.4 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.4.md)）。管理面板經 HA 管理角色驗證後可設定後端。0.1.1 於 2026-10-05 已在測試 HA 以真 Woow Odoo 18 實測（[HA 實測紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.1.md)）：讀取 12 個中 10 個通過、寫入與不支援工具 30 個全部拒絕、後端斷線回結構化錯誤。`list_models`、`schema_catalog` 需要讀 `ir.model`，Odoo 18 只有「存取權限」群組（`base.group_erp_manager`）可讀，最小權限帳號會回結構化錯誤（0.1.2 起照實回 `BACKEND_RPC_FAULT`，0.1.1 是 `BACKEND_RESPONSE_INVALID`）。同一台 HA 上的 Woow Odoo 預設擋掉 MCP 容器的連線（nginx `lan_networks`），需另行放行。0.1.0 的面板 fail closed，請使用 0.1.1。
0.1.1 起與 n8n 相同（負責人 2026-10-05 核准 `homeassistant_api`）：管理程序以 runtime `SUPERVISOR_TOKEN`
連固定 `ws://supervisor/core/websocket`，只查 `config/auth/list`，確認 Ingress 使用者是 active 的 owner 或
system-admin 才放行；token 只給管理程序，child 不繼承。此 token 具**廣泛 Core 管理能力**，負責人已知情核准。
不得注入 test verifier 或直接編輯 state 解鎖；`panel_admin` 不是角色授權。

**支援的 Core 版本**：管理面板只在本版審查過的 HA Core 版本運作（0.1.6–0.1.8：2026.7.2–2026.9.4 與 2026.10.0；0.1.9 起再加 2026.10.1；0.4.2 起再加 2026.10.2–2026.10.4；0.4.14 起再加 2026.11.0–2026.11.2；0.5.2 起再加 2026.11.3）。
0.5.2 起，已審查月份的後續修補版自動放行：版本字串要剛好是 `年.月.修補`（月份與修補號不補零，不接受前後空白、`v` 開頭、beta／rc／dev 或第四段），該年該月已有審過的版本，而且修補號大於該月審過的最大修補號（審過 2026.11.3 之後，2026.11.4 起放行；2026.7.0、2026.7.1 比審過的最早版本 2026.7.2 更早，不放行）；放行的版本沒有逐版審查，add-on 紀錄每個版本記一行，之後的 add-on 版本再補審。其他版本（新的月份、預覽版與其他格式）整個管理面板都回 403；0.4.1 以前看起來和「不是管理員」完全一樣（add-on 紀錄也沒有訊息），0.4.2 起管理面板改顯示「這個 HA Core 版本尚未審核：<版本>」，add-on 紀錄也記一行同樣的說明（不含權杖）；
MCP 端點（Bearer token）不經這項檢查，不受影響。新月份的 Core 版本要等 add-on 發新版才支援（同月份的後續修補版不用等），升級 Core 前請先對照這份清單。0.4.3 起，舊版升級後自動全開的設定在未審核的 Core 上也無法用管理面板還原或調整：請先把 add-on 更新到審過這個 Core 的版本，再到管理面板「還原升級前的限制」；需要立刻限制 MCP 時先停止 add-on（進階的離線還原步驟見 [legacy migration](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/legacy-migration.md#when-the-panel-refuses-an-unreviewed-core)）。

本產品 runtime：**odoo-mcp 1.3.0 / MCP SDK 2.3.0**（0.4.0 起；0.3.4 是 odoo-mcp 1.1.0 / SDK 1.30.0；套上 PaaS woow-mcp-server 的兩個 build patch：跨 session approval token、直接寫入開關；13 個工具的 structuredContent 不再包一層 `result`，見 [upgrade-notes.yaml](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/upgrade-notes.yaml)）。**0.2.1 起完整版**（負責人 2026-10-15 決定）：上游 41 個工具全部開放，與原始 MCP server 及 PaaS 版功能一致；tools/list 用子程序自己的 inputSchema（經 provider-safe 正規化），tools/call 參數原樣轉給子程序驗證，輸出不再截斷或投影。子程序環境 `ODOO_MCP_ENABLE_WRITES=1`、`ODOO_MCP_ALLOW_DIRECT_WRITES=1`：`execute_method` 可直接 create／write／unlink，三步驟 `preview_write`→`validate_write`→`execute_approved_write` 也照常列出可用（approval token 跨 session 有效）；`ODOO_MCP_ALLOW_UNKNOWN_METHODS=1`：`execute_method` 也可呼叫未審查的副作用方法（例如 `action_confirm`、`action_post`）；`MCP_CHATTER_DIRECT=1`：`chatter_post` 直接送出，不必先 preview（帶了 `approval`／`confirm` 也照樣送出）。Odoo 的錯誤（例如 AccessError）原文回傳。逐名清單與分類見[工具表](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md)，轉送規則與保留的安全層見[工具範圍](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-expansion.md)。子程序新增但尚未分類的工具一律拒絕。

**MCP 提供的內容**：這個 add-on 透過 MCP 只提供工具（tools）：`initialize` 宣告的能力只有 `tools`，`prompts/list`、`resources/list` 等請求回 -32601（Method not found）。子程序自己的 server instructions 不轉送。WOOW PaaS 的 Odoo MCP 另外提供 prompts、resources（含 resource template）與 server instructions；負責人 2026-11-07 決定維持只提供工具。

## 後端與設定主權

每個帳號一組後端：**url、database、username、password**（0.5.1 起一個 Add-on 可以有預設帳號＋最多 5 個額外帳號，見下方「多帳號」）。
後端憑證／URL、token、policy、顯式 client endpoint 由 GUI/state 擁有；HA options
目前為空，不放 credentials、不覆寫 state。typed 表單已經 test-only role 連真 Core 驗證，
**不是正式 HA 管理可用宣稱**。需受限測試資料庫與 XML-RPC 相容性；不沿用 legacy wheel patches，使用 source-guarded launcher。

工具頁依實際 metadata 顯示每個工具的停用開關與寫入授權（寫入工具一個 grant，混合工具每個寫入 operation 一個）；保存取代全部
`enabled_write_tools` 並 `writes_enabled:false`，disabled 優先；失配／過期契約停止保存。
**全部工具與寫入預設開啟**：新安裝，以及從 0.1.x 升級時一次（state schema 4 遷移：寫入全開、0.1.x 的停用清單清空，token、連線與對外端點保留）；之後管理員取消的寫入或停用的工具，重啟與升級都維持。**從 0.1.x 升級**：0.3.0–0.4.1 會先停在管理面板的升級確認頁（MCP 回 503，直到管理員確認）；**下一版起（未發版，負責人 2026-10-27 決定）**第一次啟動就自動一次性全開，MCP 立刻可用，舊設定的限制存成 `/data/mcp/owner-defaults-20261025-recovery.json`，管理面板事後顯示「已於 <時間> 自動套用預設全開」與升級前後差異（只在管理面板與 add-on log 的一行，沒有其他提示：升級後請打開管理面板查看），可選「還原升級前的限制」（關回舊設定停用的工具；寫入只保留舊設定授權過的，新版才有的寫入操作也取消，與 0.1.x 實際能做的相同；新版才有的工具不會被停用（讀取照常可用））或「保持全開，不再提示」；已是 schema 4 的設定一律不動，讀不到或壞掉的設定不遷移、不覆寫，add-on 停止並在 log 說明（[legacy migration](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/legacy-migration.md)）。**風險：網址＝完整後端權限**；後端錯誤回傳原始訊息（可能含後端內部資訊，add-on 持有的憑證會換成 `[REDACTED]`）。後端帳號權限要設對，只保留需要的工具與寫入（見 [寫入預設開啟](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#寫入預設開啟)）。

## 網路與認證

- `8099`：Ingress-only，無主機 mapping；不是 MCP endpoint。
- `8081/mcp`：Bearer Streamable HTTP；`8081/tcp: null` 預設不公開 LAN mapping。
- `8081/private_<token>/mcp`（0.1.14 起）：同一把權杖放在路徑，給 Claude.ai 網頁版自訂連接器（Bearer `/mcp` 帶 Origin 一律 403；Claude.ai 送不送 Origin 還沒實測，所以用這條）；網址由管理面板「顯示 Claude.ai 連線網址」產生（需先設定 Claude.ai 連得到的 HTTPS 端點）。權杖錯誤或已撤銷回 404，接受 Origin（0.5.1 起照全 add-on 一份來源清單：預設只有 `https://claude.ai`、report-only，清單外照常服務、只在 add-on log 記一行；面板可切 enforce，見下方「多帳號」），其他規則同 `/mcp`。**網址等同密碼**：只貼進 Claude.ai，外洩請重新產生權杖；見 [client 設定](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
- 工具呼叫被拒（0.1.14 起，`/mcp` 與密鑰網址相同）：帶 `Mcp-Session-Id`、格式正確的 tools/call，若工具不存在或未啟用、參數不符、寫入操作未開放或後端未設定，gateway 回 HTTP 200 的 JSON-RPC 錯誤說明原因（`-32602` `Unknown tool`／`Invalid params`／`Operation not permitted`，`-32603` `Backend not configured`；參數錯誤列出欄位與規則，不回顯參數值），讓 Claude 等 client 能自行修正重試；同樣不轉給子程序。沒帶 session 或格式錯誤的請求仍回 403 `{"error":"request denied"}`。
- 後端未設定或連不上時也能連線（0.2.2 起，`/mcp` 與密鑰網址相同）：initialize、`notifications/initialized`、tools/list 一律成功，tools/list 回完整工具清單與 schema（依停用與寫入授權過濾），不再回 HTTP 502，所以 Claude.ai 連接器在設定後端前也加得上去。tools/call 不轉給子程序：未設定回 `-32603` `Backend not configured`；後端連不上（最近一次完成的健康檢查，每 15 秒）回 `-32603` `Backend unreachable`，`data.reason` 附健康檢查得到的原因（憑證換成 `[REDACTED]`）；子程序沒在跑時原因是 `MCP_SERVER_NOT_READY`。這時 gateway 用 add-on 內附、與子程序一致的工具清單回答，並開自己的 session（`woow-local-…`）；設定好後端、子程序通過健康檢查後，這個 session 的下一個請求回 404，client 重新 initialize 即改連子程序。readiness 與管理面板不變（未設定或連不上仍 503）。詳見 [client 文件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
- `3000`：child loopback-only，永不暴露（0.5.1 起額外帳號的子程式在容器內 18000 起的 port，一樣只聽 loopback、要帶自己的 child bearer）。各容器內部 ports 可相同，LAN host ports 必須各異。
- Session：先 initialize，之後每個請求都帶 `Mcp-Session-Id`。initialize 以外沒帶 `Mcp-Session-Id` 的請求一律回 400，不會開 session（0.1.8 起；這個檢查排在 Bearer 401、方法 405、Origin 403 與 policy 403 之後）。client 用完要送 `DELETE /mcp`（帶 `Mcp-Session-Id`）；沒送的 session 閒置 30 分鐘後由子程序結束（0.1.8 起；以前要等子程序重啟），之後用它的請求回 404（有 id 的請求與 GET 是 JSON-RPC 錯誤，通知與 DELETE 沒有內容），client 要重新 initialize。MCP child 重啟（含 Add-on 重啟）後舊 session 也會失效。詳見 [client 文件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
- 同一台 HA 的 Woow Odoo 18 add-on：它的 8069 只放行 `lan_networks` 來源，HA add-on 網路（172.30.32.0/23）固定排除，所以從本 Add-on 用內部主機名或主機 LAN IP 連線都會被直接斷線；只有 Host 等於它 `public_url` 主機名的請求進入 public 層（只擋 db service）。本版連線固定目的主機、不能改 Host，可行做法是讓 `public_url` 網域可解析並經 tunnel 連入，backend url 填 `https://<public host>`。2026-10-06 已在測試 HA 以這個做法實測（Cloudflare tunnel 新增對外網址，`public_url` 改成同一個網址）：讀取、拒絕、斷線與 readiness 都和內部放行時相同，不必改 `lan_networks`。Cloudflare 的瀏覽器完整性檢查會擋 `Python-urllib` User-Agent；本 Add-on 用的 XML-RPC 不受影響。**不要**把 172.30.x 加進 Odoo 的 `lan_networks`：那會讓同網路的 tunnel 取得 LAN 層權限（含資料庫管理）。
- 使用實際安裝後 DNS placeholder，不能猜 repository hash 或從 iframe origin 推導。
  [client 範例](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md) 不含真實秘密。

## 多帳號（0.5.1 起）

0.5.1 起這個 add-on 開通多帳號（多帳號首發，R1）：除了預設帳號（就是 0.4.x 的設定與權杖，升級後不變），HA 管理員可以在管理面板再新增最多 5 個帳號。
升級後只用預設帳號的安裝，權杖、兩條網址、`state.json`、工具政策與子程式都不變；仍看得到的改變列在 [CHANGELOG](CHANGELOG.md) 0.5.1 段。完整規則見
[多帳號契約](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/multi-profile/contract.md)（開通後預設帳號會變的事：第 1.4 節）與[操作指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#多帳號產品開通後)。

- **每個帳號一組**：Odoo 連線（url、database、username、password 或 API key）、一把 MCP 權杖與它的兩條網址、一份工具政策（含四個子操作開關與
  方法例外）、一個子程式。新帳號複製預設帳號當下的工具政策（之後各自獨立），後端連線是空的，要另外設定。「MCP 用戶端端點」全 add-on 一個，
  在預設帳號設定。帳號上限與記憶體數值是暫定，目標硬體量測（HM-19c）後定案；可用記憶體或開檔數不夠時上限更低，新增帳號回 409。
- **回覆併發**：`initialize`、`ping` 以外帶 id 的 POST 請求，每個預留 64 MiB 到回覆結束；同時最多預設帳號 3 個、每個額外帳號 1 個，全 add-on 合計最多 512 MiB；額度滿時回 HTTP 200、`-32003`、`Retry-After: 5`（帶請求自己的 id），請求不送到子程式、不排隊，稍後重試。GET 事件串流（0.5.1 起）不占這個額度：每個帳號的串流上限是預設帳號 24 條、每個額外帳號 8 條，再開一條回 HTTP 429、JSON-RPC `-32003`、`Retry-After: 30`；串流開滿時 POST 照常運作。每條串流自己有小上限：交給伺服器但用戶端還沒收走的位元組 1 MiB、子程式的單一事件 128 KiB，超過時閘道乾淨地結束那條串流（用戶端會重連）並在 log 記一行警告（不含權杖與內容）。額度拒絕都帶 `Cache-Control: no-store`。
- **常見用法**（和 WOOW PaaS 相同）：同一個 Odoo 資料庫，預設帳號接管理員，額外帳號各接一個只給需要權限的 Odoo 使用者；每個 AI 代理只拿自己
  那個帳號的網址。看得到什麼由 Odoo 的權限與紀錄規則決定：管理員看得到全部，受限使用者只看得到自己有權限的紀錄。帳號之間的權限邊界是各帳號
  的 Odoo 使用者，不是這個 add-on。
- **面板的帳號頁**：面板頂端的帳號選單（只有預設帳號時也有）切換、新增、改名、刪除帳號；刪除要兩段確認，先撤銷權杖、抹掉後端憑證再刪，
  不能復原；預設帳號不能改名或刪除。切到某個帳號後，「總覽」「後端連線」「工具權限」「連線與權杖」「診斷與維護」都是那個帳號的。選擇只放在
  頁面記憶體，重新整理回到預設帳號。開面板時瀏覽器 console 有一筆 400（`profile_id_required`）是預期的。
- **每個帳號的網址**：Bearer 一律是 `<端點>/mcp`、帶那個帳號的權杖；密鑰網址每個帳號各一條 `…/private_<那個帳號的權杖>/mcp`。只看權杖決定是
  哪個帳號（8081 不看 `X-MCP-Profile`、cookie 或查詢參數）；錯的、撤銷的、已刪帳號的權杖照舊：Bearer 401、密鑰網址 404。到那個帳號的
  「連線與權杖」顯示、複製、重新產生或撤銷它的權杖，不影響別的帳號；面板產生的範例名稱，額外帳號是 `woow-odoo-<帳號 id 前 8 碼>`。
  見 [client 文件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md#多帳號產品開通後)。
- **一個代理只接一個帳號**：每個帳號的 `serverInfo.name` 與工具名稱都相同（和 PaaS 一致）。同一個代理同時接兩個帳號時，模型分不出哪個工具是
  哪個帳號的，可能把寫入送到錯的帳號。要用兩個帳號就開兩個代理或兩個對話；Claude.ai 每個帳號各新增一個自訂連接器、各貼自己的密鑰網址。
- **換後端身分會換權杖**：改 url、database 或 username（含清空連線）時，同一次存檔換新的 MCP 權杖，兩條舊網址立即失效：到「連線與權杖」複製
  新的，更新所有用戶端。只改密碼、第一次設定、權杖已撤銷時不換。網址改到另一台伺服器（scheme、host 或 port 變了）時要一起重填密碼或
  API key，否則不存（422）。存檔回 503 時重新啟動 add-on，重啟後到「連線與權杖」確認網址（權杖可能已換）。後端網址不能填 loopback
  （127.0.0.0/8、::1、`localhost`；0.5.1 之前存的照樣讀得出來，但連不上，健康檢查只顯示 `BACKEND_UNAVAILABLE`）。
- **密鑰網址的來源檢查**：全 add-on 一份清單、所有帳號共用，預設只有 `https://claude.ai`、模式 report-only：清單外的來源照常服務，只在
  add-on log 記一行 `decision=would_deny`（帶帳號 id 前 8 碼）。在「連線與權杖」的「瀏覽器來源檢查」卡片可切 enforce（清單外 403）；
  切之前先看 log 把需要的來源加進清單。政策檔壞掉時每個帳號的密鑰網址都回 503，到面板存一份新的就好。
- **還原與核對**：還原的備份裡有額外帳號時，add-on 在服務前撤銷每個帳號（連預設帳號）的權杖：到預設帳號頁的核對卡逐帳號核對（名稱、後端身分、
  政策摘要都是備份當時的值），按「已核對」後才能重新產生權杖；讀不到設定的帳號會移到隔離區，只能刪除。備份裡沒有額外帳號時，權杖回到備份
  當時的值、不撤銷，面板顯示還原提示：備份後權杖可能外洩就重新產生。還原也把來源檢查設定帶回備份當時的值，沒有提示，還原後到「連線與權杖」
  看一次。虛擬機或磁碟快照的還原、0.5.1 之前做的備份偵測不到：升到最新版後按「診斷與維護」的「全部撤銷」，再逐帳號重新產生。守門每一行 log 的
  意思見 [更新、備份與回復](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md#多帳號版本的還原回退與全部撤銷hm-13bhm-13c)。
- **事故處理**（懷疑某個子程式或帳號被攻破）：① 在「診斷與維護」按「全部撤銷」（面板打不開就停止 add-on）；② 在 Odoo 換掉每個帳號用的密碼或
  API key（全部帳號都要換），再到面板逐帳號存新憑證；③ 檢查每個帳號的政策與後端網址有沒有被改；④ 檢查帳號清單有沒有多出來的帳號、孤兒或
  隔離目錄；⑤ 必要時還原事故前的備份；⑥ 留 add-on log 與診斷頁（帳號只記 id 前 8 碼；不要貼權杖或密碼）。詳見
  [操作指南的事故處理](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#事故處理懷疑某個子程式或帳號被攻破)。
- **已知限制**：所有帳號的子程式都以同一個系統帳號執行，一個子程式被攻破（例如上游 MCP server 的漏洞）等於整個 add-on 與每個帳號都被完全
  控制，所以不宣稱多租戶，也不宣稱子程式之間隔離。帳號之間的隔離在請求層（各自的名額、位元組額度、權杖）；8081 的連線數全 add-on 共用。
  Odoo 依來源 IP 節流登入失敗：每個帳號都從同一個來源連 Odoo，一個帳號連續打錯密碼可能讓別的帳號一起被冷卻。完整清單見
  [操作指南的已知限制](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#已知限制開通後)。
- **回退**：HA 不能裝回舊版。要回到 0.4.14 只能還原升級前的 add-on 備份（升級後新增的帳號、輪替、撤銷全部消失；之後再升級請按「全部撤銷」、
  逐帳號重新產生）。要關掉多帳號得發一個版號更大的新版（推估一個工作天以上），期間可以停止 add-on，或在面板撤銷、刪除帳號、按「全部撤銷」。
  見 [回退與緊急關閉](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md#回退與緊急關閉多帳號產品開通後)。

## 操作、健康與更新

Stock image `init: true`；保護模式維持 on。bootstrap 只建立新 `/data/mcp`，之後
runtime/child uid/gid10001；0700 directory、0600 state。其他錯 owner、連結或特殊檔
停止不接管。**HA 還原**：0.1.0 還原後資料屬 root、啟動被拒（2026-10-05 實測）。0.1.1 起 bootstrap 只在資料剛好屬 root 時，第一遍核准有界的一般資料夾與單一連結檔（身分＝dev／inode／ctime），第二遍只把這些重驗身分後的項目改回 10001 與 0700／0600；任何新增、移除、替換、連結或外來擁有者仍拒絕。0.1.1 已在 HA 實測（n8n，2026-10-05）：cold backup→還原後 7 秒內啟動，log `bootstrap: re-owned 2 restored entries in /data/mcp`，權杖回到備份當時的值（還原後請輪替）；其他產品用同一份 bootstrap，未逐支做還原。管理／child／backend 三種 health 不同；backend outage readiness503
不重啟 Add-on，故意不設 watchdog。0.1.3 起後端狀態只驗證能否登入 Odoo（沒有 `ir.model` 讀取權的最小權限帳號也算可連線），健康檢查在自己的執行緒執行，不佔工具唯一的工作槽（DNS 解析的 4 個名額仍與工具共用）。詳見 [操作指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md)。

更新須手動、固定版本且先讀 [CHANGELOG](CHANGELOG.md)；只有本 Add-on cold backup
會短暫停止 MCP，**不停止既有 backend／Core／Supervisor**。完整 `/data/mcp` backup
含秘密，限制存取／加密保管，不入 Git 或 artifacts。v1/v2 升 v3 保存設定並新增空 exact grants；v3 回退需相容的更新前
backup，不能只降 image 或改 schema。依 [更新備份回復](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md)
與 [失敗接受條件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/acceptance.md) 逐產品驗證。

## 發佈與尚未通過關卡

本產品仍需 source/license/secret、image、HA／真實版本與受限 credentials、
管理員及 non-admin、Ingress UX、同 HA／LAN clients、stream、backup/restore、
CPU/RSS/latency 證據。需受限測試資料庫與 XML-RPC 相容性；不沿用 legacy wheel patches，使用 source-guarded launcher。
[發佈關卡](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/release.md) 預設關閉；其他產品通過不能替本產品背書。
