# Odoo 操作說明

## 現況與範圍

**0.2.1（experimental，2026-10-15 上架商店）**：映像 `ghcr.io/woowtech/amd64-mcp-odoo:0.2.1`（GitHub tag／release `v0.2.1`，以映像建置 commit `88a707f` 為準）。0.2.1 起是完整版：上游 41 個工具全部開放，全部工具與寫入預設開啟（管理面板可逐一停用或取消寫入），後端錯誤回原始訊息（add-on 持有的憑證換成 `[REDACTED]`），見下方說明與 [CHANGELOG](CHANGELOG.md)。上架歷程：0.1.10（2026-10-13）、0.1.11、0.1.14（2026-10-14）與 0.2.1 已上架商店；0.1.12、0.1.13、0.2.0 映像只推 GHCR、未上架。下一段是 0.1.9 時的建置與回歸紀錄（測試 HA 的回歸紀錄目前到 0.1.9）。

**0.1.9 時的紀錄（experimental）**：映像 `ghcr.io/woowtech/amd64-mcp-odoo:0.1.9` 由候選 57c96f2 建置，通過 container/mock 與 supply-chain gate（2026-10-11）；只加上 Core 2026.10.1 支援，見 [CHANGELOG](CHANGELOG.md)。2026-10-11 已在測試 HA 回歸（[0.1.9 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.9.md)）；0.1.8 已在測試 HA 回歸（[0.1.8 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.8.md)）；0.1.7 已在測試 HA 回歸（[0.1.7 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.7.md)；0.1.6 見 [0.1.6 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.6.md)；0.1.5 見 [0.1.5 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.5.md)；0.1.4 見 [0.1.4 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.4.md)）。管理面板經 HA 管理角色驗證後可設定後端。0.1.1 於 2026-10-05 已在測試 HA 以真 Woow Odoo 18 實測（[HA 實測紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.1.md)）：讀取 12 個中 10 個通過、寫入與不支援工具 30 個全部拒絕、後端斷線回結構化錯誤。`list_models`、`schema_catalog` 需要讀 `ir.model`，Odoo 18 只有「存取權限」群組（`base.group_erp_manager`）可讀，最小權限帳號會回結構化錯誤（0.1.2 起照實回 `BACKEND_RPC_FAULT`，0.1.1 是 `BACKEND_RESPONSE_INVALID`）。同一台 HA 上的 Woow Odoo 預設擋掉 MCP 容器的連線（nginx `lan_networks`），需另行放行。0.1.0 的面板 fail closed，請使用 0.1.1。
0.1.1 起與 n8n 相同（負責人 2026-10-05 核准 `homeassistant_api`）：管理程序以 runtime `SUPERVISOR_TOKEN`
連固定 `ws://supervisor/core/websocket`，只查 `config/auth/list`，確認 Ingress 使用者是 active 的 owner 或
system-admin 才放行；token 只給管理程序，child 不繼承。此 token 具**廣泛 Core 管理能力**，負責人已知情核准。
不得注入 test verifier 或直接編輯 state 解鎖；`panel_admin` 不是角色授權。

**支援的 Core 版本**：管理面板只在本版審查過的 HA Core 版本運作（0.1.6–0.1.8：2026.7.2–2026.9.4 與 2026.10.0；0.1.9 起再加 2026.10.1）。
其他版本（含之後的 patch 與 beta）整個管理面板都回 403，看起來和「不是管理員」完全一樣（add-on 紀錄也沒有訊息）；
MCP 端點（Bearer token）不受影響。新的 Core 版本要等 add-on 發新版才支援，升級 Core 前請先對照這份清單。

本產品 runtime：**odoo-mcp 1.1.0 / MCP SDK 1.30.0**（0.3.4 起 SDK 1.30.0；套上 PaaS woow-mcp-server 的兩個 build patch：跨 session approval token、直接寫入開關）。**0.2.1 起完整版**（負責人 2026-10-15 決定）：上游 41 個工具全部開放，與原始 MCP server 及 PaaS 版功能一致；tools/list 用子程序自己的 inputSchema（經 provider-safe 正規化），tools/call 參數原樣轉給子程序驗證，輸出不再截斷或投影。子程序環境 `ODOO_MCP_ENABLE_WRITES=1`、`ODOO_MCP_ALLOW_DIRECT_WRITES=1`：`execute_method` 可直接 create／write／unlink，三步驟 `preview_write`→`validate_write`→`execute_approved_write` 也照常列出可用（approval token 跨 session 有效）；`ODOO_MCP_ALLOW_UNKNOWN_METHODS=1`：`execute_method` 也可呼叫未審查的副作用方法（例如 `action_confirm`、`action_post`）；`MCP_CHATTER_DIRECT=1`：`chatter_post` 直接送出，不必先 preview（帶了 `approval`／`confirm` 也照樣送出）。Odoo 的錯誤（例如 AccessError）原文回傳。逐名清單與分類見[工具表](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md)，轉送規則與保留的安全層見[工具範圍](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-expansion.md)。子程序新增但尚未分類的工具一律拒絕。

## 後端與設定主權

一個 Add-on 只有一組後端：**url、database、username、password**。
後端憑證／URL、token、policy、顯式 client endpoint 由 GUI/state 擁有；HA options
目前為空，不放 credentials、不覆寫 state。typed 表單已經 test-only role 連真 Core 驗證，
**不是正式 HA 管理可用宣稱**。需受限測試資料庫與 XML-RPC 相容性；不沿用 legacy wheel patches，使用 source-guarded launcher。

工具頁依實際 metadata 顯示每個工具的停用開關與寫入授權（寫入工具一個 grant，混合工具每個寫入 operation 一個）；保存取代全部
`enabled_write_tools` 並 `writes_enabled:false`，disabled 優先；失配／過期契約停止保存。
**全部工具與寫入預設開啟**：新安裝，以及從 0.1.x 升級時一次（state schema 4 遷移：寫入全開、0.1.x 的停用清單清空，token、連線與對外端點保留）；之後管理員取消的寫入或停用的工具，重啟與升級都維持。**風險：網址＝完整後端權限**；後端錯誤回傳原始訊息（可能含後端內部資訊，add-on 持有的憑證會換成 `[REDACTED]`）。後端帳號權限要設對，只保留需要的工具與寫入（見 [寫入預設開啟](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#寫入預設開啟)）。

## 網路與認證

- `8099`：Ingress-only，無主機 mapping；不是 MCP endpoint。
- `8081/mcp`：Bearer Streamable HTTP；`8081/tcp: null` 預設不公開 LAN mapping。
- `8081/private_<token>/mcp`（0.1.14 起）：同一把權杖放在路徑，給無法帶 header 的 Claude.ai 網頁版自訂連接器；網址由管理面板「顯示 Claude.ai 連線網址」產生（需先設定 Claude.ai 連得到的 HTTPS 端點）。權杖錯誤或已撤銷回 404，允許 Origin，其他規則同 `/mcp`。**網址等同密碼**：只貼進 Claude.ai，外洩請重新產生權杖；見 [client 設定](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
- 工具呼叫被拒（0.1.14 起，`/mcp` 與密鑰網址相同）：帶 `Mcp-Session-Id`、格式正確的 tools/call，若工具不存在或未啟用、參數不符、寫入操作未開放或後端未設定，gateway 回 HTTP 200 的 JSON-RPC 錯誤說明原因（`-32602` `Unknown tool`／`Invalid params`／`Operation not permitted`，`-32603` `Backend not configured`；參數錯誤列出欄位與規則，不回顯參數值），讓 Claude 等 client 能自行修正重試；同樣不轉給子程序。沒帶 session 或格式錯誤的請求仍回 403 `{"error":"request denied"}`。
- 後端未設定或連不上時也能連線（0.2.2 起，`/mcp` 與密鑰網址相同）：initialize、`notifications/initialized`、tools/list 一律成功，tools/list 回完整工具清單與 schema（依停用與寫入授權過濾），不再回 HTTP 502，所以 Claude.ai 連接器在設定後端前也加得上去。tools/call 不轉給子程序：未設定回 `-32603` `Backend not configured`；後端連不上（最近一次完成的健康檢查，每 15 秒）回 `-32603` `Backend unreachable`，`data.reason` 附健康檢查得到的原因（憑證換成 `[REDACTED]`）；子程序沒在跑時原因是 `MCP_SERVER_NOT_READY`。這時 gateway 用 add-on 內附、與子程序一致的工具清單回答，並開自己的 session（`woow-local-…`）；設定好後端、子程序通過健康檢查後，這個 session 的下一個請求回 404，client 重新 initialize 即改連子程序。readiness 與管理面板不變（未設定或連不上仍 503）。詳見 [client 文件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
- `3000`：child loopback-only，永不暴露。各容器內部 ports 可相同，LAN host ports 必須各異。
- Session：先 initialize，之後每個請求都帶 `Mcp-Session-Id`。initialize 以外沒帶 `Mcp-Session-Id` 的請求一律回 400，不會開 session（0.1.8 起；這個檢查排在 Bearer 401、方法 405、Origin 403 與 policy 403 之後）。client 用完要送 `DELETE /mcp`（帶 `Mcp-Session-Id`）；沒送的 session 閒置 30 分鐘後由子程序結束（0.1.8 起；以前要等子程序重啟），之後用它的請求回 404（有 id 的請求與 GET 是 JSON-RPC 錯誤，通知與 DELETE 沒有內容），client 要重新 initialize。MCP child 重啟（含 Add-on 重啟）後舊 session 也會失效。詳見 [client 文件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
- 同一台 HA 的 Woow Odoo 18 add-on：它的 8069 只放行 `lan_networks` 來源，HA add-on 網路（172.30.32.0/23）固定排除，所以從本 Add-on 用內部主機名或主機 LAN IP 連線都會被直接斷線；只有 Host 等於它 `public_url` 主機名的請求進入 public 層（只擋 db service）。本版連線固定目的主機、不能改 Host，可行做法是讓 `public_url` 網域可解析並經 tunnel 連入，backend url 填 `https://<public host>`。2026-10-06 已在測試 HA 以這個做法實測（Cloudflare tunnel 新增對外網址，`public_url` 改成同一個網址）：讀取、拒絕、斷線與 readiness 都和內部放行時相同，不必改 `lan_networks`。Cloudflare 的瀏覽器完整性檢查會擋 `Python-urllib` User-Agent；本 Add-on 用的 XML-RPC 不受影響。**不要**把 172.30.x 加進 Odoo 的 `lan_networks`：那會讓同網路的 tunnel 取得 LAN 層權限（含資料庫管理）。
- 使用實際安裝後 DNS placeholder，不能猜 repository hash 或從 iframe origin 推導。
  [client 範例](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md) 不含真實秘密。

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
