# Odoo 操作說明

## 現況與範圍

**0.1.8（experimental）**：映像 `ghcr.io/woowtech/amd64-mcp-odoo:0.1.8` 由候選 04ae485 建置，通過 container/mock 與 supply-chain gate（2026-10-11）；變更見 [CHANGELOG](CHANGELOG.md)。測試 HA 回歸進行中；0.1.7 已在測試 HA 回歸（[0.1.7 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.7.md)；0.1.6 見 [0.1.6 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.6.md)；0.1.5 見 [0.1.5 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.5.md)；0.1.4 見 [0.1.4 回歸紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.4.md)）。管理面板經 HA 管理角色驗證後可設定後端。0.1.1 於 2026-10-05 已在測試 HA 以真 Woow Odoo 18 實測（[HA 實測紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/ha-test-0.1.1.md)）：讀取 12 個中 10 個通過、寫入與不支援工具 30 個全部拒絕、後端斷線回結構化錯誤。`list_models`、`schema_catalog` 需要讀 `ir.model`，Odoo 18 只有「存取權限」群組（`base.group_erp_manager`）可讀，最小權限帳號會回結構化錯誤（0.1.2 起照實回 `BACKEND_RPC_FAULT`，0.1.1 是 `BACKEND_RESPONSE_INVALID`）。同一台 HA 上的 Woow Odoo 預設擋掉 MCP 容器的連線（nginx `lan_networks`），需另行放行。0.1.0 的面板 fail closed，請使用 0.1.1。
0.1.1 起與 n8n 相同（負責人 2026-10-05 核准 `homeassistant_api`）：管理程序以 runtime `SUPERVISOR_TOKEN`
連固定 `ws://supervisor/core/websocket`，只查 `config/auth/list`，確認 Ingress 使用者是 active 的 owner 或
system-admin 才放行；token 只給管理程序，child 不繼承。此 token 具**廣泛 Core 管理能力**，負責人已知情核准。
不得注入 test verifier 或直接編輯 state 解鎖；`panel_admin` 不是角色授權。

**支援的 Core 版本**：管理面板只在本版審查過的 HA Core 版本運作（0.1.6–0.1.8：2026.7.2–2026.9.4 與 2026.10.0）。
其他版本（含之後的 patch 與 beta）整個管理面板都回 403，看起來和「不是管理員」完全一樣（add-on 紀錄也沒有訊息）；
MCP 端點（Bearer token）不受影響。新的 Core 版本要等 add-on 發新版才支援，升級 Core 前請先對照這份清單。

本產品 runtime：**odoo-mcp 1.1.0**。完整來源 41 tools，局部支援 13，
暫不支援 28；全部產品合計見[工具表](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md)，**不是 full functional parity**。
health/model list、res.partner 指定欄位 read/search/fields，及 exact-grant chatter preview+confirm；B1 增加 build_domain、generate_json2_payload、diagnose_odoo_call 純 preview（不執行 payload），以及按 active 分組的 id:count aggregate_records。有界輸出不含 ORM domain/context；不開放任意 model/method。
B2 增加 schema_catalog（固定 res.partner、limit1、兩個 metadata cache keys）、inspect_model_relationships（僅 parent_id/child_ids 自關係 metadata 深度1，絕不讀 relation values）、data_quality_report（只 missing_required、name/active、最多兩次 search_count，無樣本或私密值）。舊 record fields 不擴張。Cache 非即時；refresh=true 才強制更新。品質總數是缺值欄位次數，不是唯一 records；duplicates/format/orphan checks 仍禁止。詳見 [有界功能](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-expansion.md)；B2 待獨立 SPEC → NEW SECURITY。
逐名 schema／預設／operation／啟用限制／deferred reason 以
[工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md) 與 [machine manifest](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.json)
為準。未知與 withheld tools 即使開啟 writes 也不放行。

## 後端與設定主權

一個 Add-on 只有一組後端：**url、database、username、password**。
後端憑證／URL、token、policy、顯式 client endpoint 由 GUI/state 擁有；HA options
目前為空，不放 credentials、不覆寫 state。typed 表單已經 test-only role 連真 Core 驗證，
**不是正式 HA 管理可用宣稱**。需受限測試資料庫與 XML-RPC 相容性；不沿用 legacy wheel patches，使用 source-guarded launcher。

工具頁依實際 v3 metadata 顯示 exact tool/operation grants；保存取代全部
`enabled_write_tools` 並 `writes_enabled:false`，disabled 優先；失配／過期契約停止保存。
116 個延期工具是透明內部 backlog，並非完整遷移完成。

## 網路與認證

- `8099`：Ingress-only，無主機 mapping；不是 MCP endpoint。
- `8081/mcp`：Bearer Streamable HTTP；`8081/tcp: null` 預設不公開 LAN mapping。
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
