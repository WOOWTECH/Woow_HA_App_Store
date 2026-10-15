# n8n 操作說明

## 現況與範圍

**0.1.9（experimental）**：映像 `ghcr.io/woowtech/amd64-mcp-n8n:0.1.9` 由候選 57c96f2 建置，通過 container/mock 與 supply-chain gate（2026-10-11），可從本 repository 的 HA 商店安裝；只加上 Core 2026.10.1 支援，見 [CHANGELOG](CHANGELOG.md)。2026-10-11 已在測試 HA 回歸（[0.1.9 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.9.md)）；0.1.8 已在測試 HA 回歸（[0.1.8 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.8.md)）；0.1.7 已在測試 HA 回歸（[0.1.7 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.7.md)；0.1.6 見 [0.1.6 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.6.md)；0.1.5 見 [0.1.5 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.5.md)；0.1.4 見 [0.1.4 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.4.md)）。2026-10-05 已在測試 HA 實測 0.1.1（[HA 實測紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.1.md)）：0.1.0 升版、HA 備份還原、真 n8n 讀取 11 個中 10 個通過（資料夾工具在 n8n 2.12 回 NOT_FOUND，該版沒有資料夾 API）、寫入與不支援工具 24 個全部拒絕、後端斷線。以下試點段落是 0.1.0 的結果。**HA 試點**（2026-10-05，一台 HA 實機、真 n8n 2.12.3 後端）通過：管理員 Ingress 面板、後端設定與重啟後保留、Bearer 拒絕與 token 輪替／撤銷、MCP E2E（11 個可見工具讀到真 n8n 資料；未授權的讀取模式與 6 種寫入直接呼叫皆 403，n8n 端前後一致）、後端斷線（結構化錯誤、readiness 503、恢復後可用）、Add-on 重啟與 MCP child 異常重啟、資源量測。**未通過**：HA 還原（見下方已知問題）。**未測**：non-admin、LAN client、升版。
**HA 管理權限**：商店各支都有 `homeassistant_api: true`（n8n 自 0.1.0、其他五支自 0.1.1 起、Nextcloud 自 0.1.7 起），用來驗證管理面板的使用者是 HA owner 或系統管理員；這個 token 具廣泛的 Core 存取能力。
正式 fixed-WS verifier 已實作並經 component review；管理 HTML/assets/API 與 UI 已本地整合。
本地真 bootstrap→guard→n8n→provider fake WS／Chromium 已覆蓋設定與 token 操作；
真 HA 上管理員 Ingress 與 token 操作已通過（見上）；整合獨立規格及新安全審查仍待完成。
不得注入 test verifier 或直接編輯 state 解鎖；`panel_admin` 不是角色授權。

**支援的 Core 版本**：管理面板只在本版審查過的 HA Core 版本運作（0.1.6–0.1.8：2026.7.2–2026.9.4 與 2026.10.0；0.1.9 起再加 2026.10.1）。
其他版本（含之後的 patch 與 beta）整個管理面板都回 403，看起來和「不是管理員」完全一樣（add-on 紀錄也沒有訊息）；
MCP 端點（Bearer token）不受影響。新的 Core 版本要等 add-on 發新版才支援，升級 Core 前請先對照這份清單。

此 token 授予**廣泛 Core 管理能力**（使用者管理、可能透過服務間接影響
Supervisor／host），不是可強制的唯讀角色權限。批准不授權所有 HA 變更，亦不
允許修改／重啟既有 HA／後端。hassio_api/auth_api 保持 false，role 省略／預設，
protection mode 保持 on，無新增 host mounts、Docker socket 或 capabilities。

核准 verifier 固定連線 `ws://supervisor/core/websocket`，只查 `config/auth/list`；
不接受 options/state/client/env 覆寫 URL／command。runtime `SUPERVISOR_TOKEN`
只傳給 n8n 管理程序，不入 config/options/argv/log，不回傳 client；n8n child
以 allowlisted env 剝除；實際同 UID child 在 post-exec guard 下讀 parent procfs/mem 被拒（本地非 HA）。可信 Ingress socket peer＋唯一 user ID 必須
匹配目前 active、人類 owner 或 system-admin；敏感操作前 fresh query、無正向
快取，停權／降權／缺失／timeout／錯誤一律 fail closed。role query 不保證即時
撤銷 browser Ingress session 或已在執行的跨系統操作。詳見共用驗收文件。

本產品 runtime：**n8n-mcp 2.91.0 / Node 22.23.2**。**0.2.1 起完整版**（負責人 2026-10-15 決定）：上游 28 個工具全部開放，與原始 MCP server 及 PaaS 版功能一致；tools/list 用子程序自己的 inputSchema（經 provider-safe 正規化），tools/call 參數原樣轉給子程序驗證，輸出不再截斷或投影。管理類工具（workflow、executions、credentials、data table、資料夾、版本、agents 等）需先設定 n8n 網址與 API key。原生版本歷史、資料表欄位操作、`n8n_test_workflow` prepare／pinned／direct、`n8n_explore_node_resources`、`n8n_manage_agents` 另需選填的 **MCP Access Token**（0.2.1 起，管理面板「後端連線設定」；n8n 設定 → Instance-level MCP）。子程序以 `WEBHOOK_SECURITY_MODE=permissive` 執行（0.2.1 起，使用者決定關閉 webhook／URL SSRF 防護）：可連 HA 內網的 n8n，**MCP 也能經 n8n-mcp 連到 add-on 能到的任何內網位址**（上游只保留擋雲端 metadata 主機名）。逐名清單與分類見[工具表](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md)，轉送規則與保留的安全層見[工具範圍](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-expansion.md)。子程序新增但尚未分類的工具一律拒絕。

## 後端與設定主權

一個 Add-on 只有一組後端：**backend_url、backend_key（API base 不附 /api/v1）**。
後端憑證／URL、token、policy、顯式 client endpoint 由 GUI/state 擁有；HA options
目前為空，不放 credentials、不覆寫 state。UI 支援保留／完整替換／確認清除與三維健康，
**本地串接不代表已通過 HA**。第一個核准試點，僅受限非正式 workflow key；sql.js fallback，npm ci --ignore-scripts；沒有 runtime npm download。

工具頁依實際 metadata 顯示每個工具的停用開關與寫入授權（寫入工具一個 grant，混合工具每個寫入 operation 一個）；保存取代全部
`enabled_write_tools` 並 `writes_enabled:false`，disabled 優先；失配／過期契約停止保存。
**全部工具與寫入預設開啟**：新安裝，以及從 0.1.x 升級時一次（state schema 4 遷移：寫入全開、0.1.x 的停用清單清空，token、連線與對外端點保留）；之後管理員取消的寫入或停用的工具，重啟與升級都維持。**風險：網址＝完整後端權限**；後端錯誤回傳原始訊息（可能含後端內部資訊，add-on 持有的憑證會換成 `[REDACTED]`）。後端帳號權限要設對，只保留需要的工具與寫入（見 [寫入預設開啟](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#寫入預設開啟)）。

## 網路與認證

- `8099`：Ingress-only，無主機 mapping；不是 MCP endpoint。
- `8081/mcp`：Bearer Streamable HTTP；`8081/tcp: null` 預設不公開 LAN mapping。
- `8081/private_<token>/mcp`（0.1.14 起）：同一把權杖放在路徑，給無法帶 header 的 Claude.ai 網頁版自訂連接器；網址由管理面板「顯示 Claude.ai 連線網址」產生（需先設定 Claude.ai 連得到的 HTTPS 端點）。權杖錯誤或已撤銷回 404，允許 Origin，其他規則同 `/mcp`。**網址等同密碼**：只貼進 Claude.ai，外洩請重新產生權杖；見 [client 設定](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)。
- 工具呼叫被拒（0.1.14 起，`/mcp` 與密鑰網址相同）：帶 `Mcp-Session-Id`、格式正確的 tools/call，若工具不存在或未啟用、參數不符、寫入操作未開放或後端未設定，gateway 回 HTTP 200 的 JSON-RPC 錯誤說明原因（`-32602` `Unknown tool`／`Invalid params`／`Operation not permitted`，`-32603` `Backend not configured`；參數錯誤列出欄位與規則，不回顯參數值），讓 Claude 等 client 能自行修正重試；同樣不轉給子程序。沒帶 session 或格式錯誤的請求仍回 403 `{"error":"request denied"}`。
- `3000`：child loopback-only，永不暴露。各容器內部 ports 可相同，LAN host ports 必須各異。
- Session：所有 client **共用 20 個**同時 session，閒置 10 分鐘回收。先 initialize，之後每個請求都帶 `Mcp-Session-Id`；initialize 以外沒帶 `Mcp-Session-Id` 的請求一律回 400（0.1.8 起；沒有 session 的通知以前回 202；這個檢查排在 Bearer 401、方法 405、Origin 403 與 policy 403 之後）。client 用完要送 `DELETE /mcp`（帶 `Mcp-Session-Id`）。額滿時 initialize 回 HTTP 429，body 是 JSON-RPC 錯誤 -32000「Too Many Requests」（0.1.4 起 gateway 不轉送子程序的錯誤原文，看不到「Session limit reached」）。被 policy 以 403 拒絕的 tools/call 也可能耗盡名額：Python MCP SDK 1.x client 收到 403 會整段斷線、不送 DELETE，每次留下一個 session（見 [CHANGELOG](CHANGELOG.md) 0.1.6 已知問題）；0.1.14 起帶 session 的拒絕改回 HTTP 200 的 JSON-RPC 錯誤，Python client 的斷線行為尚未重測。MCP child 重啟（含 Add-on 重啟）後舊 session 失效，client 需重新 initialize；token 不變。
- initialize 的 protocolVersion：0.1.8 起只接受 2024-11-05、2025-03-26、2025-06-18、2025-11-25。n8n 子程序對要求 2024-06-25 的 client 會照回這個版本，這時 initialize 回 502，請改要求上面任一版本（n8n／langchain client 一律拿到 2024-11-05）。
- 使用實際安裝後 DNS placeholder，不能猜 repository hash 或從 iframe origin 推導。
  [client 範例](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md) 不含真實秘密。

## 操作、健康與更新

Stock image `init: true`；保護模式維持 on。bootstrap 只建立新 `/data/mcp`，之後
runtime/child uid/gid10001；0700 directory、0600 state。其他錯 owner、連結或特殊檔
停止不接管。**HA 還原**：0.1.0 還原後資料屬 root、啟動被拒（2026-10-05 實測）。0.1.1 起 bootstrap 只在資料剛好屬 root 時，第一遍核准有界的一般資料夾與單一連結檔（身分＝dev／inode／ctime），第二遍只把這些重驗身分後的項目改回 10001 與 0700／0600；任何新增、移除、替換、連結或外來擁有者仍拒絕。0.1.1 已在 HA 實測（n8n，2026-10-05）：cold backup→還原後 7 秒內啟動，log `bootstrap: re-owned 2 restored entries in /data/mcp`，權杖回到備份當時的值（還原後請輪替）；其他產品用同一份 bootstrap，未逐支做還原。管理／child／backend 三種 health 不同；backend outage readiness503
不重啟 Add-on，故意不設 watchdog。詳見 [操作指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md)。

更新須手動、固定版本且先讀 [CHANGELOG](CHANGELOG.md)；只有本 Add-on cold backup
會短暫停止 MCP，**不停止既有 backend／Core／Supervisor**。完整 `/data/mcp` backup
含秘密，限制存取／加密保管，不入 Git 或 artifacts。v1/v2 升 v3 保存設定並新增空 exact grants；v3 回退需相容的更新前
backup，不能只降 image 或改 schema。依 [更新備份回復](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md)
與 [失敗接受條件](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/acceptance.md) 逐產品驗證。

## 發佈與尚未通過關卡

source/license/secret、image 已通過 gate；管理員 Ingress、同 HA client 本機工具、
CPU/RSS/latency 已有 HA 證據。仍需真 n8n 後端與受限 credentials、non-admin、LAN client、
stream、backup/restore、升版證據。第一個核准試點，僅受限非正式 workflow key；sql.js fallback，npm ci --ignore-scripts；沒有 runtime npm download。
[發佈關卡](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/release.md) 預設關閉；其他產品通過不能替本產品背書。
