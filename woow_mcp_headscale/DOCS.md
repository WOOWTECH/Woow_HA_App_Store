# Headscale 操作說明

## 目前狀態

**0.4.19 已發布並上架；0.4.20 是 2026-11-25 的維修版。** 0.4.19 起管理面板接受 Core 2026.11.2；0.4.20 的主因是管理面板接受 Core 2026.11.3（0.4.19 在 Core 2026.11.3 上拒絕每個管理面板請求，MCP 端點不受影響），並從 0.4.20 起自動放行已審查月份的後續修補版；另外帶出 0.4.19 之後合併的共用變更（還原之後的開機守門與面板的還原提示，逐項見本 add-on 的 CHANGELOG）。映像由 GitHub 託管的發版流程建置並驗收，已發佈的 digest 與驗收結果見[發佈紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/release-decision-headscale-0.4.20.md)。正式可用狀態以 [Release](https://github.com/WOOWTECH/Woow_ha_mcp_addons/releases) 和商店版號為準。

**0.5.0 是多帳號版（2026-11-25 準備，尚未發佈；發佈與上架以 Release 和商店版號為準）**：同一個 add-on 可以開預設帳號加最多 3 個額外帳號（見下方「多帳號」），新帳號預設不能用 `headscale_api_keys` 的寫入，子程式只認自己帳號的 child token，面板不再顯示現有權杖（要取得就重新產生）。發佈紀錄見[發佈紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/release-decision-headscale-0.5.0.md)。

## 從商店安裝

在 Home Assistant「設定 → Add-ons → Add-on 商店」加入自訂來源 `https://github.com/WOOWTECH/Woow_HA_App_Store`，重新整理商店，搜尋 **Woow Headscale MCP Server**。0.4.20 完成正式 Release 與商店同步後，確認商店版本為 0.4.20，再按「安裝」與「啟動」，開啟 Web UI。同步前商店顯示上一版 0.4.19；安裝與更新狀態以 Home Assistant 顯示為準。

## 連線與權限

在 HA 的 Ingress 管理面板填入一台 Headscale 控制伺服器的網址及**專用 API key**（0.5.0 起每個帳號一組：預設帳號加最多 3 個額外帳號，見下方「多帳號」）。網址填伺服器 origin，例如 `https://headscale.example.com`，也可填該 origin 的 `/api/v1`；不要填其他路徑、查詢參數或使用者資訊。子程序會自行加上 `/api/v1`，並拒絕 loopback 後端、轉址及未通過 TLS 驗證的連線。請優先使用 HTTPS，妥善保管 API key。連線設定及 MCP 政策保存在 `/data/mcp`，不是 HA Add-on options。

管理面板只允許 HA owner 或系統管理員進入。Add-on 為驗證身分使用 `homeassistant_api: true`，其 Supervisor token 具有廣泛的 HA Core 權限，只交給管理程序，不交給 Headscale 子程序。`hassio_api`、host 網路及 Docker API 均未啟用。

**支援的 Core 版本**：管理面板只在本版審查過的 HA Core 版本運作（0.4.13：2026.7.2–2026.10.4；0.4.14 起再加 2026.11.0–2026.11.1；0.4.19 起再加 2026.11.2；0.4.20 起再加 2026.11.3；和其他七支共用同一個驗證器）。0.4.20 起，已審查月份的後續修補版自動放行：版本字串要剛好是 `年.月.修補`（月份與修補號不補零，不接受前後空白、`v` 開頭、beta／rc／dev 或第四段），該年該月已有審過的版本，而且修補號大於該月審過的最大修補號（審過 2026.11.3 之後，2026.11.4 起放行；2026.7.0、2026.7.1 比審過的最早版本 2026.7.2 更早，不放行）；放行的版本沒有逐版審查，add-on 紀錄每個版本記一行，之後的 add-on 版本再補審。其他版本（新的月份、預覽版與其他格式）整個管理面板都回 403，管理面板顯示「這個 HA Core 版本尚未審核：<版本>」，add-on 紀錄也記一行同樣的說明（不含權杖）；MCP 端點（Bearer token）不經這項檢查，不受影響。新月份的 Core 版本要等 add-on 發新版才支援（同月份的後續修補版不用等），升級 Core 前請先對照這份清單。

新安裝時，11 個工具與 21 個寫入 grant 預設開啟；管理員可在面板逐一停用工具或撤銷寫入。這些工具涵蓋使用者、節點、註冊、預先授權金鑰、API 金鑰、ACL 政策、核准路由及健康檢查等 Headscale v0.29.4 操作。`headscale_routes_replace` **整組取代**節點已核准的路由，傳入空清單會撤銷全部；政策寫入也可能影響整個網路的存取。MCP 權杖代表所設定 API key 可執行的權限，請先在面板限制不需要的工具與寫入，再把權杖交給用戶端。本版不假設 Headscale API key 本身能設定細分權限。完整工具與參數以 [工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md) 為準。

## 多帳號（0.5.0 起）

0.5.0 起這個 add-on 開通多帳號（多帳號第二批 train B，與 Hermes、n8n 同版；Odoo、LiteLLM、Nextcloud、EMQX 在更早的版本開通）：除了預設帳號（就是 0.4.x 的設定與權杖，升級後不變），HA 管理員可以在管理面板再新增最多 3 個帳號。
升級後只用預設帳號的安裝，權杖、兩條網址、`state.json`、工具政策與子程式都不變；仍看得到的改變列在 [CHANGELOG](CHANGELOG.md) 0.5.0 段。完整規則見
[多帳號契約](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/multi-profile/contract.md)（開通後預設帳號會變的事：第 1.4 節）與[操作指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#多帳號產品開通後)。

- **每個帳號一組**：Headscale 連線（網址與專用 API key）、一把 MCP 權杖與它的兩條網址、一份工具政策、一個子程式。新帳號複製預設帳號當下的工具政策（之後各自獨立），但不複製 `headscale_api_keys` 的建立、作廢與刪除（見下面「新帳號預設不能用 API key 的寫入」），後端連線是空的，要另外設定。「MCP 用戶端端點」全 add-on 一個，
  在預設帳號設定。帳號上限（3）與記憶體數值（每個子程式 160 MiB）是暫定，目標硬體量測（HM-19c）後定案；可用記憶體或開檔數不夠時上限更低，新增帳號回 409。
- **同一台 Headscale 的帳號**：帳號可以接同一台 Headscale（各帳號不同的工具政策），也可以接不同台。Headscale 的 API key 是整台伺服器的管理權限，Headscale 沒有 key 層級的權限：同一台 Headscale 上的帳號，不論是否共用 key，彼此只靠工具政策分權。**要讓某個帳號真的受限，請在它的工具權限頁停用 `headscale_api_keys` 的建立、作廢與刪除**：建立會把一把新的整台管理 key 交給持有這個帳號權杖的人，在 add-on 外也能用，工具政策、「全部撤銷」與還原都管不到；作廢與刪除能停掉其他帳號的 key。**仍建議每個帳號在 Headscale 各建一把 API key**，不要共用：某個帳號不再使用時，就只撤銷它那一把；共用一把時，撤銷它會同時停掉共用的帳號。
- **新帳號預設不能用 API key 的寫入**：新增的帳號複製預設帳號當下的工具政策，但**不複製 `headscale_api_keys` 的建立、作廢與刪除**（列出 API key 照複製）；新帳號預設不能用這三個寫入，要用請到它的工具權限頁自行開啟。預設帳號與已經存在的帳號不變（新安裝時預設帳號的這些寫入預設開啟）。
- **每個帳號的子程式只讀自己的政策**：子程式每次呼叫都讀自己帳號的 `state.json`（含容器內直連子程式的呼叫），並檢查它的擁有者、權限、網址與 key、以及 state 裡的 child token 是否等於啟動時拿到的；不符的每個呼叫都回 `HEADSCALE_POLICY_UNAVAILABLE`、不送任何請求給 Headscale。
- **權杖不再顯示**（和 PaaS 一致；預設帳號也一樣）：面板沒有「顯示權杖」，`token/reveal` 回 404；「顯示 Claude.ai 連線網址」改成「產生新的 Claude.ai 連線網址」，會先重新產生權杖。要取得權杖就重新產生：舊權杖與兩條舊網址立即失效，新權杖只短暫顯示一次。新增的帳號也要重新產生一次才會顯示它的第一把權杖。
- **面板的帳號頁**：面板頂端的帳號選單（只有預設帳號時也有）切換、新增、改名、刪除帳號；刪除要兩段確認，先撤銷權杖、抹掉後端憑證再刪，
  不能復原；預設帳號不能改名或刪除。切到某個帳號後，「總覽」「後端連線」「工具權限」「連線與權杖」「診斷與維護」都是那個帳號的。選擇只放在
  頁面記憶體，重新整理回到預設帳號。開面板時瀏覽器 console 有一筆 400（`profile_id_required`）是預期的。
- **每個帳號的網址**：Bearer 一律是 `<端點>/mcp`、帶那個帳號的權杖；密鑰網址每個帳號各一條 `…/private_<那個帳號的權杖>/mcp`。只看權杖決定是
  哪個帳號（8081 不看 `X-MCP-Profile`、cookie 或查詢參數）；錯的、撤銷的、已刪帳號的權杖照舊：Bearer 401、密鑰網址 404。到那個帳號的
  「連線與權杖」顯示、複製、重新產生或撤銷它的權杖，不影響別的帳號；面板產生的範例名稱，額外帳號是 `woow-headscale-<帳號 id 前 8 碼>`。
  見 [client 文件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md#多帳號產品開通後)。
- **一個代理只接一個帳號**：每個帳號的 `serverInfo.name` 與工具名稱都相同（和 PaaS 一致）。同一個代理同時接兩個帳號時，模型分不出哪個工具是
  哪個帳號的，可能把寫入送到錯的帳號。要用兩個帳號就開兩個代理或兩個對話；Claude.ai 每個帳號各新增一個自訂連接器、各貼自己的密鑰網址。
- **換 key 或網址不會換權杖**：改網址或 key 時 MCP 權杖與兩條網址不變，只有那個帳號的子程式用新值重啟；存政策也只重啟那個帳號的子程式。網址改到另一台伺服器（scheme、host 或 port 變了）時要重新輸入 API key，否則不存（422；只是換寫法，例如 `/api/v1` 根、大小寫、預設 port，不算換伺服器）。後端網址不能填 loopback（127.0.0.0/8、::1、`localhost`；存檔回 400，子程式本來就拒絕連 loopback）。
- **Headscale 拒絕 key 時的健康檢查**：Headscale 伺服器拒絕某個帳號的 API key（401：撤銷、過期或打錯）時，那個帳號的健康檢查退避到 15、30、60、120、300 秒一次；存新連線、在面板重啟它或伺服器改回別的答案就結束退避。
- **密鑰網址的來源檢查**：Headscale 沒有服務層級的來源清單，每個帳號的密鑰網址都照同一條規則：沒有 Origin，或剛好是 `https://claude.ai`；其他來源回 403。Bearer `/mcp` 帶任何 Origin 都回 403。沒有 `origin-policy.json`，面板也沒有「瀏覽器來源檢查」卡片。
- **還原與核對**：還原的備份裡有額外帳號時，add-on 在服務前撤銷每個帳號（連預設帳號）的權杖：到預設帳號頁的核對卡逐帳號核對（名稱、後端身分、
  政策摘要都是備份當時的值），按「已核對」後才能重新產生權杖；讀不到設定的帳號會移到隔離區，只能刪除。備份裡沒有額外帳號時，權杖回到備份
  當時的值、不撤銷，面板顯示還原提示：備份後權杖可能外洩就重新產生。虛擬機或磁碟快照的還原、0.5.0 之前做的備份偵測不到：升到最新版後按「診斷與維護」的「全部撤銷」，再逐帳號重新產生。守門每一行 log 的
  意思見 [更新、備份與回復](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md#多帳號版本的還原回退與全部撤銷hm-13bhm-13c)。
- **事故處理**（懷疑某個子程式或帳號被攻破）：① 在「診斷與維護」按「全部撤銷」（面板打不開就停止 add-on）；② 在每一台 Headscale 列出所有 API key（`headscale apikeys list`），撤銷這個 add-on 用過的與不認得的每一把，再到面板逐帳號存新 key；③ 檢查每個帳號的政策與後端網址有沒有被改；④ 檢查帳號清單有沒有多出來的帳號、孤兒或
  隔離目錄；⑤ 必要時還原事故前的備份；⑥ 留 add-on log 與診斷頁（帳號只記 id 前 8 碼；不要貼權杖或密碼）。詳見
  [操作指南的事故處理](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#事故處理懷疑某個子程式或帳號被攻破)。
- **已知限制**：所有帳號的子程式都以同一個系統帳號執行，一個子程式被攻破（例如上游 MCP server 的漏洞）等於整個 add-on 與每個帳號都被完全
  控制，所以不宣稱多租戶，也不宣稱子程式之間隔離。帳號之間的隔離在請求層（各自的名額、位元組額度、權杖）；8081 的連線數全 add-on 共用。
  Headscale 的 API key 是整台伺服器的管理權限（見上面「同一台 Headscale 的帳號」）：帳號之間只靠工具政策分權。完整清單見
  [操作指南的已知限制](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#已知限制開通後)。
- **回退**：HA 不能裝回舊版。要回到 0.4.20 只能還原升級前的 add-on 備份（升級後新增的帳號、輪替、撤銷全部消失；之後再升級請按「全部撤銷」、
  逐帳號重新產生）。要關掉多帳號得發一個版號更大的新版（推估一個工作天以上），期間可以停止 add-on，或在面板撤銷、刪除帳號、按「全部撤銷」。
  見 [回退與緊急關閉](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md#回退與緊急關閉多帳號產品開通後)。

## 網路與日常操作

- `8099` 僅供 HA Ingress 管理面板使用，不映射到主機，也不是 MCP 端點。
- `8081/mcp` 是需要 Bearer 權杖的 Streamable HTTP 端點；`8081/tcp: null` 表示預設不對 LAN 開放。只有確實需要外部 MCP 用戶端時才設定主機映射。不能帶 Authorization header 的用戶端可使用面板產生的 `…/private_<token>/mcp` 密鑰網址；網址等同密碼。Headscale 密鑰網址接受沒有 Origin 的原生用戶端及 `https://claude.ai`，其他瀏覽器 Origin 回 403。Origin 不取代權杖；對外開埠時仍須 HTTPS 與網路來源限制。
- `3000` 是容器內的私有子程序埠，只監聽 loopback，不可對外映射。

後端尚未設定或暫時連不上時，管理面板仍可用，MCP 用戶端可 initialize 並列出目前允許的工具，但工具呼叫會回設定或連線錯誤。後端健康檢查只在 Headscale 回報 `databaseConnectivity: true` 時視為成功；斷線時 readiness 回 503，不會因此重啟 Add-on。更換連線或政策可能重啟子程序並使舊 MCP session 失效，用戶端須重新 initialize。

更新前請做冷備份。備份包含 Headscale API key、MCP 權杖及工具政策，應按密碼保護；還原到另一台主機後應輪替憑證。這是新產品，只接受現行 v4 狀態，沒有舊版 Headscale 設定遷移路徑。發佈與實機驗收狀態應以 [發佈關卡](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/release.md) 及本產品正式 Release 為準。
