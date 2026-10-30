## 0.4.8 — release candidate (2026-10-30; images pending)

- Synchronized 0.4.8 release with Nextcloud MCP v0.1.6; this product retains the 0.4.7 runtime and management contracts.
- Exact-source image gates and publication evidence are recorded separately.

## 0.4.7 — release candidate (2026-10-30; images pending)

- Require the exact reviewed configuration revision for every persisted admin mutation.
- Token rotation, revocation and child restart use durable operation IDs; query or explicitly resend the same ID after a lost response without repeating a completed effect.
- Recheck current administrator authority before receipt disclosure/replay; HA receipts belong to the original user. Replays never return historical tokens.
- Admin API clients must send If-Match and, for token/restart actions, Idempotency-Key. Token revoke now returns200 JSON instead of204. Include the hidden operation journal in data backups; unknown outcomes require state review, not blind retries.
- Six enabled images require fresh exact-image P1–P5, anonymous verification and provenance before release. OpenDesign remains disabled. See docs/operations/release-decision-0.4.7.md and upgrade-notes.yaml.

## 0.4.5

- Shared audited n8n operation policy; existing grants and schema 4 state preserved.
- Back up before upgrading; review operation restrictions before downgrade. See root upgrade-notes.yaml.

# Hermes Changelog

## 0.4.4 — 發佈候選（2026-10-29；映像待驗收）

- 管理面板顯示目前 MCP token 遮罩與最近最多五筆輪替／撤銷紀錄（只有時間、動作及舊 token 遮罩）。token 與紀錄同次原子儲存；重複撤銷不新增紀錄。
- schema 4 啟動時不重寫。首次 token 變更會保存 `token_history`，0.4.3 拒絕此欄位；升級前請建立 add-on 備份，降版時連同程式還原升級前備份，再檢查 token 與用戶端設定。
- 版本升至 0.4.4；映像建置、精確映像驗收、匿名讀回及正式發布尚未完成。
- 詳見 [upgrade-notes.yaml](../../upgrade-notes.yaml) 與 [0.4.4 發佈決策](../../docs/operations/release-decision-0.4.4.md)。

## 0.4.3 — 發佈候選（2026-10-28）

- **舊版安裝升級後第一次啟動就一次性全開（與 PaaS 一致；負責人 2026-10-27 決定）**：state schema 1/2/3（0.1.x 寫的）在建立設定儲存、啟動 MCP 子程序之前，自動改成與 0.3.0–0.4.1 升級確認頁 `all_on` 完全相同的設定（schema 4、寫入全開、全部寫入授權、停用清單清空；token、後端連線與對外端點保留），同一次原子寫入加上標記 `owner_defaults_20261025`（`applied`、`at`、`from_schema`）；寫入前先把舊設定的限制存成 `/data/mcp/owner-defaults-20261025-recovery.json`（0600，只有政策，不含 token 與後端）。MCP 立刻可用，不再回 503 `upgrade_review_required` 等管理員確認；add-on log 會有一行說明。**升級後請打開這個 add-on 的管理面板（開啟網頁介面）查看通知與升級前後差異**：除了 add-on log 的那一行，沒有其他提示。
- **升級確認頁改成事後通知**：管理面板每一頁顯示「已於 <時間> 自動套用預設全開」與升級前後差異，可選「還原升級前的限制」（與 0.1.x 實際能做的相同：舊設定停用的工具再停用；寫入只保留舊設定授權過的，其他寫入連同新版才有的寫入操作都取消；新版才有的工具不會被停用（讀取照常可用），不會像 0.3.0 的 `preserve` 那樣整個停用；升級後自己關掉的不會被打開）或「保持全開，不再提示」，兩者都記入標記、之後不再提示（保持全開後仍可在「診斷與維護」頁還原）。例：ws97 上 0.1.14 留下的設定（停用 `hermes_skill`、沒有任何寫入授權）升級後是 11 個工具全開；按還原後停用 `hermes_skill`、21 個寫入授權全部取消（0.1.14 沒授權任何寫入，新版的 13 個寫入也一樣），tools/list 是 9 個（只能寫入的 `hermes_chat` 不列出；0.3.0 的 `preserve` 會是 0 個）。
- 已是 schema 4 的設定（新安裝、0.2.0 之後寫的、或已在升級確認頁確認過的）一律不動；讀不到或壞掉的設定照舊 fail-safe：不遷移、不覆寫，add-on log 說明後停止（`runtime unavailable; local recovery required`），請還原更新前的備份。
- 回退：自動遷移過的設定帶有標記欄位，0.4.2 不接受；要退回 0.4.2 請還原更新前的 add-on 備份。沒有標記的 schema 4 設定與 0.4.2 相同。見 [upgrade-notes.yaml](../../upgrade-notes.yaml)、[legacy migration](../../docs/operations/legacy-migration.md)。
- 版本號升至 0.4.3；映像名稱、架構、選項、port 與工具不變。正式 0.4.3 映像須經精確映像驗收、匿名讀回和商店發版閘。

## 0.4.2 — 發佈候選（2026-10-27）

- 管理面板的 HA 管理員驗證（七支共用）多支援 Core 2026.10.2、2026.10.3、2026.10.4：逐檔比對被用到的 21 個 Core 檔與 4 個相鄰檔，只有 `auth/__init__.py` 改了刪除使用者時順便撤銷其 refresh token 的一段，與 `config/auth/list` 無關（[審查紀錄](../../docs/ha-role-core-contract.md)）。
- Core 版本不在清單時（含之後的 patch 與 beta），管理面板照舊拒絕，但改顯示「這個 HA Core 版本尚未審核：<版本>」，add-on 紀錄也記一行同樣的說明（不含權杖）；MCP 端點不經這項檢查，照常服務。
- 六個啟用產品改用新 0.4.2 映像；選項、port、工具、寫入授權與 state schema 都不變。OpenDesign 只更新商店停用的版本中繼資料。

## 0.4.1 — 發佈候選（2026-10-25）

- 共用 HA 管理面板包含 n8n 條件寫入說明；Hermes 工具、授權、依賴及 state schema 不變。
- 0.4.0 → 0.4.1 不需資料遷移；六個啟用產品的新映像仍須通過精確映像、匿名拉取與 Store gate，見[0.4.1 發佈決策](../../docs/operations/release-decision-0.4.1.md)。

## 0.4.0 — 發佈候選（2026-10-25）

- **MCP SDK 2 遷移（對齊 WOOW PaaS，issue #21）**：Python MCP SDK `mcp` 1.30.0 → 2.3.0（另加 `mcp-types` 2.3.0），子程序對後端的連線仍用 HTTPX 0.28.1；管理面板 UI 建置用的 Node 基底 22.23.4 → 26.12.1（2026-10-28 起 Active LTS）。
- Hermes MCP 原始檔重新對齊 woow-mcp-server main（server.py 最後一次變更 471efdf：SDK 2 `MCPServer`、工具錯誤文字維持 1.x），保留 HA 的修改：出站連線走 add-on 的 DNS 固定防護、穩定錯誤碼、hermes_chat 300 秒、`hermes_mcp` add 拒絕 loopback 網址（AI-HMCP-002-2）並允許區網；11 個工具與 schema 不變。
- 行為維持：工具失敗時 client 看到的錯誤文字與 0.3.4 相同（SDK 2 原本只回 `Error executing tool <名稱>`，add-on 補回原因）；閒置 30 分鐘結束 session、請求內容上限 16 MiB 照舊。
- client 相容：仍走 2025 世代的 initialize 握手；gateway 照舊自己回 `server/discover`（JSON-RPC -32601），且不再把 client 的 `MCP-Protocol-Version` 標頭帶進 initialize（SDK 2 子程序會拒絕這種 initialize）；raw JSON-RPC、Python MCP SDK 1.30 與 2.3、TypeScript SDK 1.32 的 client 經 gateway 連線、列工具、呼叫都已實測。
- 接在 0.3.4 之後。選項、port、映像名稱、架構、工具名稱與 state schema 4 都不變，從 0.3.4 或更早的 schema 4 版本升級不需確認或遷移；退回 0.3.4 不需資料轉換（同為 schema 4），未實測。
- 六個啟用產品共同升版。正式映像須以精確 commit 完成 container、secret/history、SBOM、CVE/license gates，發布相同 image ID 並匿名驗證 immutable digest；狀態見 [0.4.0 發佈紀錄](../../docs/operations/release-decision-0.4.0.md)。

## 0.3.4 — 2026-10-24 正式 Release

- **相依套件更新，對齊 WOOW PaaS**：Python MCP SDK `mcp` 1.28.1 → 1.30.0（GHSA-84m7-p3x7-pcfv：Streamable HTTP session 不會回收）、`certifi` 2026.10.19 → 2026.10.23，其他鎖定的 Python 套件升到同 major 最新（pydantic 2.14.1、pydantic-settings 2.16.1、starlette 1.9.0 等）；管理面板 UI 建置用的 Node 基底 22.23.2 → 22.23.4（安全性修正版）。
- SDK 1.30.0 本身會在沒有請求 30 分鐘後結束 session（與 add-on 原本的閒置上限相同，client 收到 404 後依 MCP 規範重新 initialize），請求 body 預設上限 4 MiB；add-on 維持閒置 30 分鐘，並把子程序的 body 上限設為 gateway 的 16 MiB，行為與之前相同。
- **恢復 AI-HMCP-002-2 的 loopback 拒絕**：`hermes_mcp` action=add 再次拒絕 loopback MCP server 網址（localhost、*.localhost、localhost.localdomain、127.0.0.0/8、::1、IPv4-mapped loopback），0.3.0–0.3.3 的區網友善檢查漏掉了這部分；區網位址照常可加入，metadata、link-local、0.0.0.0 照舊拒絕，被拒時不會送任何 API 請求到 Hermes dashboard。之前已用 loopback 網址註冊的 MCP server 不會被自動移除，請在 Hermes 檢查。
- Hermes MCP 原始檔對齊 woow-mcp-server main `a5db051`（0.3.0–0.3.3 已含相同程式碼，只更新來源紀錄）；11 個工具與 schema 不變。
- 接在 0.3.3 之後，本版只有相依與安全修正；0.3.2 不使用（原保留給本版，已改為 0.3.4）。沒有破壞性變更：選項、port、映像名稱、架構、工具名稱與 state schema 4 都不變，新安裝仍預設全部工具與寫入開啟；從 0.3.3 或更早的 schema 4 版本升級不需確認或遷移。退回 0.3.3 沒有資料轉換（同為 schema 4），但會失去本版的相依與安全修正，未實測。
- 六個啟用產品共同升版。正式映像須以精確 commit 完成 container、secret/history、SBOM、CVE/license gates，發布相同 image ID 並匿名驗證 immutable digest；狀態見 [0.3.4 發佈紀錄](../../docs/operations/release-decision-0.3.4.md)。

## 0.3.3 — 2026-10-24 正式 Release

- 0.3.2 已由另一個獨立 dependency-update PR17 保留；本修正改用 0.3.3，避免不同 source 共用映像 tag，不合併該 PR 的相依套件變更。

- 隨六個啟用產品共用核心版本同步至 0.3.3；本次功能修正限 n8n 的有效參數／六個混合操作選擇器與條件式 MCP 曝露寫入授權，本產品沒有另加工具、權限或後端行為。
- schema 4、token、相依套件、child pins 與 UI 原始碼不變；新安裝保留完整功能預設。schema 1/2/3 仍須在管理員驗證的升級頁確認預選 `all_on` 或明確選擇 `preserve`。
- 精確 source freeze／CI 與六支 0.3.3 映像驗收／掃描／發布仍待完成；[候選狀態與驗收邊界](../../docs/operations/release-decision-0.3.3.md)。0.3.1 映像與歷史證據保留，不宣稱已完成 0.3.1 正式 HAOS 升級。

## 0.3.1 — 2026-10-24 正式 Release

- 管理面板新增設定已保存／待套用／已套用／套用失敗狀態；「已套用」綁定目前子程序完成的協定檢查，後端健康分開顯示。token 與端點更新不代表子程序重啟。
- 修正設定狀態卡片初次顯示與更新時末尾出現字面 `null` 的問題，保留狀態說明與過期版本提示。
- 表單以載入時的 revision 搭配 `If-Match` 儲存；過期編輯回 409，不改資料、不重啟子程序，草稿保留至明確重新載入。管理程序重啟後也需重新載入舊表單。不帶條件 header 的舊 API client 維持相容，但沒有衝突保護。
- 已保存但子程序替換失敗時明確回覆 `saved:true`、503 與安全失敗狀態，管理面板不誤稱儲存失敗，也不自動重送變更。
- 共用 token 撤銷／輪替持久化後，取消進行中的 I/O、已開啟 GET/POST 串流與受阻的回應傳送，清理上游 iterator／reader／slot；不重啟子程序，已傳送內容與已送往後端的操作不會回滾。
- schema、相依套件與 child pins 不變。新安裝仍預設全部功能開啟；既有 schema 4 保留已存政策。schema 1/2/3 沿用 0.3.0 的啟動前管理員確認，預選 `all_on`，也可明確選 `preserve`；升級前備份，等待確認時開啟面板處理，token 不會自動恢復。
- 六支正式 0.3.1 映像尚待精確建置、container／供應鏈 gates 與匿名 immutable digest 驗證；[發佈狀態與驗收邊界](../../docs/operations/release-decision-0.3.1.md)。

## 0.3.0 — 2026-10-24 正式 Release

- 安全性相依套件修正：實際發布的 Python 環境鎖定 `certifi 2026.10.19`，移除受影響的 CA 信任鏈（GHSA-6q48-6c7w-9gw2）；依原 CVE/license 政策重新建置與驗收，不新增例外。
- **舊資料啟動流程改變**：schema 1/2/3 在建立 ProductStore 與啟動 MCP 子程序前，先進入經 HA 管理員驗證的 Ingress 升級確認頁。預設選擇 `all_on`（完整功能與寫入），管理員確認後才遷移並正常啟動；無人確認時持續等待，MCP/readiness 回 503。請升級前備份，升級後開啟管理面板，比較預覽並確認。新安裝與既有 schema 4 正常啟動不變。
- 可明確選擇 `preserve`：保留既有停用／精確授權，新增工具及需重新審查參數的工具預設停用；不宣稱重現舊版參數限制。管理面板支援逐 operation 停用與寫入授權，顯示已保存及實際生效狀態；新安裝仍預設全部功能開啟。
- 共用 token 的重新產生／撤銷持久化後，舊權杖的後續請求失效，不重啟 MCP 子程序；既有已送往後端的操作不會回滾。升級與政策恢復不會自動復活已撤銷 token。
- 新增離線 migration CLI 的預覽、明確套用與限制性政策恢復；恢復合併停用工具／operation，取較少寫入授權，不恢復舊 token。停 runtime 後才可操作。詳細步驟見 [migration](../../docs/operations/legacy-migration.md)。
- schema 仍為 4，但舊二進位未實作新增 operation 限制；不可把退回 0.2.2 當作等效政策恢復。二進位回退需要另行審核相容備份與當前 token 狀態。
- 六個啟用產品的 0.3.0 映像已完成精確 container、secret/history、SBOM、CVE/license gates 與匿名 immutable digest 驗證，正式 Release 已發布；證據與限制見 [0.3.0 發佈紀錄](../../docs/operations/release-decision-0.3.0.md)。

## 0.2.2 — 2026-10-21 正式 Release

- **後端未設定或連不上時也能連線**（使用者 2026-10-16 核准）：0.2.1 以前沒有後端時 initialize 回 HTTP 502（沒有子程序可轉送），Claude.ai 連接器加不上去。現在 initialize、`notifications/initialized`、tools/list 一律成功，tools/list 回完整工具清單與 schema（依停用與寫入授權過濾，與有後端時相同）；tools/call 回 JSON-RPC 錯誤說明原因，不轉給子程序。
- 未設定：沒有後端時沒有子程序，gateway 自己回 initialize、`notifications/initialized`、ping 與 tools/list（完整 11 個工具），tools/call 回 `-32603 Backend not configured`。
- 後端已設定但連不上：initialize 與 tools/list 照常由子程序回答（實測七支子程序在後端連不上時都照常列出全部工具）；需要後端的工具呼叫回 `-32603 Backend unreachable`，`data.reason` 是最近一次完成的健康檢查得到的原因（後端自己的錯誤文字，add-on 持有的憑證換成 `[REDACTED]`，最多 1000 字）。健康檢查每 15 秒一次：後端恢復後最多約 15 秒內恢復轉送；子程序剛重啟、還沒完成檢查時一律轉送。
- 子程序沒在跑（啟動中、退避重啟、失敗）：initialize 最多等 10 秒，之後由 gateway 自己回答；工具呼叫回 `Backend unreachable`，原因 `MCP_SERVER_NOT_READY`。子程序停掉後它開的 session 回 404。
- 工具清單來源：add-on 內附 `mcp_admin_core/tool_snapshot.py`，是建置前由真實子程序（每個工具都啟用）產生的 tools/list（名稱、說明、原始 inputSchema、annotations），經與子程序回覆相同的過濾；測試確認它與真實子程序逐字一致、與工具分類（surface.py）一致，子程序升級後不一致即測試失敗。
- gateway 自己開的 session id 以 `woow-local-` 開頭（閒置 30 分鐘結束、最多 256 個）；GET 回 405、DELETE 回 200。設定好後端、子程序通過一次健康檢查後，這個 session 的下一個請求回 404，client 依 MCP 規範重新 initialize 即改連子程序；Claude.ai 是否自動重連尚未實測。
- **`hermes_config` 讀取不再吐出後端憑證**（測試 VM 2026-10-16 實測 G1）：在 Hermes dashboard 設定自訂 OpenAI 相容端點後，`hermes_config {action:"get"}`（或 `key:"custom_providers"`）回覆含 `custom_providers[].api_key` 明文（上游原樣回傳 `/api/config`，`DENIED_CONFIG_KEYS` 只擋 set）。現在 get（整份或指定 key）與 `hermes_inspect` 的 config 摘要，把 secret 類欄位（`api_key`、`*_KEY`、`*_TOKEN`、`token`、`secret(s)`、`password`、`authorization`、`credentials`、`cookie`、`basic_auth` 等，含巢狀物件與 list）的值換成 `[REDACTED]`，保留欄位名；空字串、null 與布林不變，看得出「是否已設定」；網址中的帳密密碼也遮蔽；`max_tokens`、`auth_mode` 等非憑證欄位照常顯示。key 路徑上任一段是 secret（例如 `secrets.X`）時整個值遮蔽。set 行為不變。這是後端持有的憑證，不屬於「後端錯誤回原文」的範圍。
- **`hermes_chat` 逾時改為 300 秒**（測試 VM 2026-10-16 實測 G2）：原本與其他呼叫共用固定 30 秒，免費模型一輪約 28–30 秒，3 次有 2 次 `BACKEND_TIMEOUT`（Hermes 端其實完成了）。現在對話一輪最多 300 秒（子程序環境變數 `HERMES_MCP_CHAT_TIMEOUT`，1–3600 秒；連線 30 秒），其他 Gateway／Dashboard 呼叫維持 30 秒。
- gateway：tools/call 的回覆最多可閒置、總共可持續 330 秒（原為閒置 30 秒、總共 120 秒；Python SDK 子程序每 15 秒送 SSE 註解保持連線，所以實際卡住的是 120 秒總時限），配合 Hermes 對話最長 300 秒；其他請求維持原時限。長呼叫期間佔用 32 個同時連線名額之一；各子程序對後端的逾時不變。
- 不變：權杖檢查最先（401／404）、沒帶 session 400、policy 拒絕優先、readiness（未設定或連不上仍 503）、管理面板、子程序與後端的其他行為。
- 新版候選需獨立建置、掃描與 PaaS HAOS VM 驗收（含真實 Claude.ai 在未設定與後端離線時新增連接器）；既有 0.1.x、0.2.0、0.2.1 標籤不覆寫。

## 0.2.1 — 2026-10-15 公開（experimental）

- GitHub tag／release `v0.2.1`（以映像建置 commit `88a707f` 為準）。
- **0.2.0 未上架**：0.2.0 映像已推上 GHCR（標籤不可覆寫）並在測試 VM 實測，但不發佈到 Store；**0.1.14 直接升 0.2.1**，下方 0.2.0 段落的內容（完整版、寫入與工具預設全開、原始錯誤訊息）一併由 0.2.1 發佈。升級遷移與 0.2.0 相同：state schema 3→4 只遷移一次，寫入授權全開、0.1.x 的停用清單清空，token、連線與對外端點保留；0.2.0 寫的 schema 4 state 照樣載入（n8n 另補一個空的 MCP access token 欄位）。
- 後端拒絕請求時（例如 HTTP 422）改依狀態碼分類為 `BACKEND_HTTP_ERROR status=<碼>`，並附上「狀態、方法與路徑：後端回應內容」（最多 4096 字、不含查詢字串）；0.2.0 會誤標成 `BACKEND_UNAVAILABLE` 且只有 httpx 的文字（測試 VM 實測 Hermes 422）。add-on 持有的憑證仍換成 `[REDACTED]`。
- 新版候選需獨立建置、掃描與 PaaS HAOS VM 驗收；既有 0.1.x、0.2.0 標籤不覆寫。

## 0.2.0 — 未上架（映像只推 GHCR；內容隨 0.2.1 發佈）

- GitHub tag／release `v0.2.0`（以映像建置 commit `baac83b` 為準）。
- **完整版**（使用者 2026-10-15 決定）：與原始 MCP server 及 PaaS woow-mcp-server 功能一致，所有工具（含高風險）全部開放、全部預設開啟，管理介面可逐一停用工具或取消寫入。本產品開放上游 11 個工具全部（0.1.x 為 7 個有界子集）：tools/list 用子程序自己的 inputSchema（經 provider-safe 正規化），tools/call 參數原樣轉給子程序驗證，輸出不再截斷或投影。gateway 仍檢查工具名在分類名單內（上游新增但未分類的工具一律拒絕）、未停用、寫入工具或混合工具的寫入 operation 有 grant，被拒時回 JSON-RPC 錯誤（見下方 0.1.14 段落）。
- **寫入預設開啟**：新安裝的 state 每個寫入 grant 都開、`writes_enabled=true`；**既有安裝升級時一次遷移成全開**（state schema 3→4；token、連線與對外端點保留，**0.1.x 的停用清單清空**，升級後所有工具全開）。之後管理員取消的寫入或停用的工具，重啟與後續升級都維持。0.1.x 不接受 schema 4，回退請還原升級前的備份。
- **風險：網址（權杖）＝完整後端權限**。拿到權杖或 Claude.ai 密鑰網址的 client（包括 AI 助理誤判時）不需再授權即可以後端帳號的權限寫入；後端帳號權限要設對，只保留需要的工具與寫入，外洩時立刻重新產生權杖。說明見 [共用指南](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/guide.md#寫入預設開啟)。
- Hermes 子程序與 PaaS 版 hermes_mcp_server 一致：移除 session／cron 列表的白名單投影；chat、config set、mcp add／remove、webhook、cron create 等全部開放（server 本身拒絕 stdio／command transport 與危險設定鍵的保護仍在）；後端錯誤回傳原始訊息（見下）。
- 保留的安全層：Bearer／密鑰網址驗證（錯誤即 404）與 log 遮罩、session 與併發 slot、子程序出站 DNS pin／TLS／redirect 拒絕、回覆中憑證換成 `[REDACTED]`、原始碼 digest 守門、管理面板 HA 管理員驗證。請求上限提高到 16 MiB。
- 管理面板工具頁加上預設全開的風險提示。
- **後端錯誤回傳原始訊息**（使用者 2026-10-15 決定，與 PaaS 一致）：拿掉 0.1.x 對後端錯誤的固定代碼遮蔽（例如 `BACKEND_RPC_FAULT`、`BACKEND_UNAVAILABLE`），client 看到後端的實際錯誤文字（例如 Odoo 的 AccessError 訊息、LiteLLM／EMQX 的錯誤 body；傳輸失敗為「代碼: 原因」）。gateway 在每個轉送的回覆中把 add-on 自己持有的憑證（Add-on 權杖、child token、後端 API key／密碼與其 Basic 認證形式）換成 `[REDACTED]`；log 的密鑰網址遮罩不變。**原始錯誤可能含後端內部資訊**（模型、欄位、路徑、版本），請留意誰能拿到網址。
- 新版候選需獨立建置、掃描與 PaaS HAOS VM 驗收（含升級遷移、真實 Claude.ai 連線與完整工具實測）；既有 0.1.x 標籤不覆寫。

## 0.1.14 — 2026-10-14 公開（experimental）

- GitHub tag／release `v0.1.14`（以映像建置 commit `ed3122b` 為準）。
- 0.1.12、0.1.13 映像已推上 GHCR 但從未發佈到 Store，且不再使用（標籤不可覆寫）；以下原為 0.1.12、0.1.13 準備的內容一併改由 0.1.14 發佈。
- 工具呼叫被拒時改為正常回話說明原因（2026-10-14 經 Claude.ai 實測：參數不符的 tools/call 都只得到 HTTP 403，用戶端只看到傳輸錯誤、無法自行修正）：帶 `Mcp-Session-Id`、格式正確的 tools/call 遇到下列四種拒絕，gateway 回 HTTP 200 的 JSON-RPC 錯誤（`application/json`、`Cache-Control: no-store`）：工具不存在或未啟用 `-32602 Unknown tool`（不區分是哪一種）；參數驗證失敗 `-32602 Invalid params`，`data.errors` 列出欄位路徑、pydantic 錯誤類型與說明（最多 20 筆、每筆 300 字），**不回顯任何參數值**（自訂的鍵名顯示為 `*`，可能夾帶輸入值的錯誤類型改用固定說明）；寫入操作未開放 `-32602 Operation not permitted`（附管理員可在面板開啟的說明）；後端未設定 `-32603 Backend not configured`。權限本身不變：同樣的呼叫照樣被拒、不轉給子程序、不佔連線名額；權杖錯誤仍 401／404，沒帶 session 或格式錯誤的請求仍 403。`/mcp` 與 `/private_<token>/mcp` 相同。修正後尚未以真實 Claude.ai 重測。
- 修正真實 Claude.ai 自訂連接器連不上（2026-10-14 經 Cloudflare 到測試 VM 的實機紀錄）：Claude.ai 先送 `server/discover`、再退回 `initialize`，params 帶 MCP 保留欄位 `_meta`（traceparent 等），gateway 兩者都回 HTTP 403。現在每個允許的方法都接受選填 `params._meta`（必須是物件、序列化後至多 8 KiB，否則仍 403），並在轉給子程序前移除；不認識的 request（例如 `server/discover`、`resources/list`、`prompts/list`）由 gateway 自己回 HTTP 200 的 JSON-RPC `-32601 Method not found`，不認識的 notification 回 202，兩者都不轉給子程序、不需 session、不佔連線名額；權杖檢查仍最先（錯誤權杖仍 401／404）。只接受 `application/json` 的 client 收到 JSON 格式的 initialize 回覆。工具權限、參數驗證、寫入閘與 `/mcp`、`/private_<token>/mcp` 其他規則不變。修正後尚未以真實 Claude.ai 重測。
- 修正 HA 側邊欄打開管理面板顯示「網頁可能暫時離線」：manifest 移除 `ingress_entry: /`。Supervisor 2026.09 以 `/api/hassio_ingress/<token>/` 直接接上 ingress_entry，舊值讓入口變成 `…/<token>//`（404，0.1.11 起七支皆受影響）；不設此鍵即為根目錄。只改 manifest，映像不變。
- 開機預設由 `boot: manual` 改為 `boot: auto`（使用者 2026-10-14 決定）：HAOS／Supervisor 重開機後自動啟動，不必再手動啟動；packaging/validate.py 的 manifest 規則同步改為 auto。
- 新增 Claude.ai 網頁版自訂連接器用的密鑰網址 `/private_<token>/mcp`（七支共用 gateway）：Claude.ai 自訂連接器無法帶 Authorization header，改把同一把 Add-on 權杖放在路徑（重新產生／撤銷同時生效）；權杖錯誤、空白或已撤銷一律回與不存在路徑相同的 404，忽略請求自帶的 Authorization，允許 Origin（不轉給子程序）；`/mcp` 的 Bearer 行為不變（含 Origin 403）。所有 log 把 `/private_…/` 遮成 `/private_[REDACTED]/`。管理面板「連線與權杖」新增「顯示 Claude.ai 連線網址」（需先設定對外端點，經確認後短暫顯示並可複製）。**網址等同密碼，外洩請重新產生權杖。**說明見 [client 設定](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/clients.md)；尚未以真實 Claude.ai 實測。
- 除上述各項外本產品功能未變更；七支共用版本規則一致升版。
- 新版候選需獨立建置、掃描與 PaaS HAOS VM 驗收（含重開機後自動回來）；既有 0.1.11、0.1.12、0.1.13 標籤不覆寫。

## 0.1.13 — 未上架（映像只推 GHCR；內容隨 0.1.14 發佈）

- GitHub tag／release `v0.1.13`（以映像建置 commit `72b672e` 為準）；內容見 0.1.14 段落。

## 0.1.12 — 未上架（映像只推 GHCR；內容隨 0.1.14 發佈）

- GitHub tag／release `v0.1.12`（以映像建置 commit `439308f` 為準）；內容見 0.1.14 段落。

## 0.1.11 — 2026-10-14 公開（experimental）

- GitHub tag／release `v0.1.11`（以映像建置 commit `7e328f7` 為準）。
- 本產品功能未變更；依既有七支共用版本規則隨同 LiteLLM MCP metadata 修補升版。
- hosted CI 的完整 Python 測試階段使用 UID 0，以執行原有 UID10001 nondumpable proof；不略過測試，不改 builder admission。
- 新版候選需獨立建置、掃描與 PaaS HAOS VM 驗收；既有 0.1.10 標籤不覆寫。

## 0.1.10 — 2026-10-13 公開（experimental）

- GitHub tag／release `v0.1.10`（以映像建置 commit `9762a94` 為準）。
- 本產品功能未變更；依既有七支共用版本規則隨同 LiteLLM MCP metadata 修補升版。
- 建置、掃描與實機結果待候選證據；不覆寫 0.1.9 標籤。

## 0.1.9 — 2026-10-11 公開（experimental）

- 管理面板（HA 角色驗證）：支援的 Core 版本加上 2026.10.1（2026-10-10 發佈）。驗證器用到的 21 個 Core 檔案與 2026.10.0 完全相同（[審查紀錄](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/ha-role-core-contract.md)）。0.1.8 及更早的版本在 Core 2026.10.1 上整個管理面板回 403（MCP 端點不受影響），升 Core 前先更新本 add-on。
- 映像 `ghcr.io/woowtech/amd64-mcp-hermes:0.1.9`（候選 57c96f2，build／container／supply-chain gate 全過；審查沒有 High／Medium）；0.1.0–0.1.8 tag 不覆寫。

## 0.1.8 — 2026-10-11 公開（experimental）

- gateway（0.1.6 發佈候選審查 GATEWAY-2）：除了 initialize，沒帶 `Mcp-Session-Id` 的請求（ping、tools/list、tools/call、通知、GET、DELETE）改由 gateway 直接回 HTTP 400，不再轉給子程序。原本五支 Python 子程序（Odoo、Hermes、OpenDesign、EMQX、LiteLLM；Nextcloud 也一樣）會先為這種請求開一個新 session 再拒絕，而且不會回收：每分鐘一次就一天留下約 1,440 個，直到子程序重啟；n8n 子程序對這種請求、GET、DELETE 本來就回 400、不開 session，但沒有 session 的通知它回 202，現在一樣改回 400。回覆的形狀和以前 gateway 轉出子程序拒絕時相同（有 id 的請求與 GET 是 JSON-RPC 錯誤 -32000「Bad Request」，通知與 DELETE 是沒有內容的 400），只是不再帶子程序新開的 session id。照規範先 initialize 的 client 不受影響；Bearer 與 policy 檢查仍在前面（沒帶或帶錯 token 401、被拒的工具 403）。
- gateway（0.1.6 審查 R1 F6）：initialize 的回覆改由 gateway 自己組成，只保留子程序的 protocolVersion，而且必須是審查過的 MCP 版本（2024-11-05、2025-03-26、2025-06-18、2025-11-25；以前任何日期格式都接受，其他值一律回 502）；capabilities 一律是 `{"tools": {}}`，serverInfo 改成這支 add-on 的名稱與版本（`woow-mcp-hermes`、add-on 版號），不再是子程序自己的名稱與版本；子程序的 instructions 不再轉送（Claude Code 會把 instructions 放進模型的 system prompt；EMQX、LiteLLM 子程序的說明寫的是上游全部的工具，包括本 add-on 隱藏或拒絕的工具）。Hermes 子程序原本沒有送 instructions。
- 子程序（0.1.6 發佈候選審查 GATEWAY-3）：client 用完不送 DELETE 留下的 session，原本要等子程序重啟才結束（本機量測每個約 100 KiB，每分鐘留一個就一天多 70–140 MiB）。現在 30 分鐘沒有任何請求的 session 會被結束，client 下一個請求收到 404，依 MCP 規範重新 initialize 即可；使用中的 session 不受影響（gateway 對每個請求最多等 35 秒、每個 stream 最多 120 秒）。
- 映像 `ghcr.io/woowtech/amd64-mcp-hermes:0.1.8`（候選 04ae485，build／container／supply-chain gate 全過；0.1.8 的審查、複審與 RR-03 審查都沒有 High／Medium）；0.1.0–0.1.7 tag 不覆寫。

## 0.1.7 — 2026-10-08 公開（experimental）

- 2026-10-09 補充（映像與功能不變，不需要更新）：顯示名稱改為「Woow Hermes MCP Server」，圖示改用 Hermes Agent 的圖示（[來源](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/provenance/icons.md)）；同時上架 [WOOW HA App Store](https://github.com/WOOWTECH/Woow_HA_App_Store) 與 ha-rebrand 的 Local Download。兩個商店的同名 add-on 在 HA 裡是不同的 add-on，同一台 HA 只裝其中一個來源的。
- 本產品功能沒有變動。0.1.7 新增第七支產品 WOOW Nextcloud MCP；所有 add-on 共用同一個版號，所以隨同重建映像 `ghcr.io/woowtech/amd64-mcp-hermes:0.1.7`（候選 7cc8bcb，build／container／supply-chain gate 全過；本版的審查針對新增的 Nextcloud：R1 REQUEST CHANGES，修正後 R2、R3 APPROVE WITH NOTES，最後由交付線做差異檢查）；0.1.0–0.1.6 tag 不覆寫。
- 已知問題：0.1.6 列出的已知問題（延到 0.1.7 的那幾項）本版都沒有處理（本版刻意不改既有六支產品的行為），延到 0.1.8。

## 0.1.6 — 2026-10-08 公開（experimental）

- 管理面板（HA 角色驗證）：原本只認 Home Assistant Core 2026.7.2，Core 一升級，管理面板與管理 API 就全部回 403。改為經原始碼審查的版本清單 2026.7.2–2026.9.4 與 2026.10.0（驗證器用到的 Core 使用者清單 API、欄位、回應格式與管理員群組在這些版本間沒有變動；2026.10.0 改用 probatio，相關的 13 個檔案有改動，逐行審查後確認不影響；auth 訊息由 Supervisor 產生，審查紀錄見 docs/ha-role-core-contract.md）；清單外的版本照樣拒絕，auth_required 與 auth_ok 回報的版本也必須相同。MCP 端點不受影響（它用 Bearer token）。
- gateway（0.1.5 發佈候選審查 F3 與 0.1.6 審查）：tools/list 的結果由 gateway 重新組成，只留工具清單與字串型的 nextCursor，同名工具只留第一個。
  每個工具的名稱與 inputSchema 用 gateway 自己的定義；title、description、annotations.title 是子程序文字，只在是字串時保留；
  四個提示（readOnlyHint、destructiveHint、idempotentHint、openWorldHint）只保留保守的值，或本地定義沒有寫入路徑的工具才保留放寬的值
  （Claude Code 會把 readOnlyHint 當作唯讀）。outputSchema、execution、icons、_meta 與其他欄位不再轉送：TS client 會把 outputSchema 裡的
  子程序文字放進錯誤訊息、Python client 會去抓子程序指定的 $ref 網址，execution.taskSupport 為 required 時會拒絕呼叫該工具。
  影響：client 不再依子程序的 outputSchema 檢查 structuredContent（n8n validate_* 截斷結果時原本會失敗，現在正常）；
  n8n 給 Claude Code 的 `anthropic/maxResultSizeChars` 也不再轉送，Claude Code 會套用它預設的 MCP 輸出上限。
- gateway（0.1.5 R2 審查觀察）：gateway 拒絕 initialize 時（Bearer 在等待中被撤銷 401；回覆格式錯誤、過大、protocolVersion 不是日期、
  子程序回 401/403 或轉址 502；BACKEND_UNAVAILABLE 或狀態讀取失敗 503；子程序自己的 4xx/5xx 照轉但不帶 session id），子程序可能已經
  建立 session 並回了 Mcp-Session-Id。這個 id 不會交給 client，而本 add-on 的子程序（釘選的 Python MCP SDK 1.28.1 FastMCP）沒有設定閒置回收，
  這個 session 原本會一直留到子程序重啟（本機以釘選版本的 SDK 實測：改版前被扣住的 session 直接 ping 仍回 200，改版後回 404）。
  現在 gateway 會自己送一次 `DELETE /mcp` 結束該 session：只限 gateway 會轉送的 session id（可見 ASCII、1–256 字元），
  且不是 client 自己帶來的 id；先關閉子程序的回覆，在同一個請求名額內送出，最多等 2 秒，子程序的回應一律不讀、不轉送，
  錯誤一律忽略，session id 也不寫進任何紀錄。client 收到的回覆完全不變，最多晚 2 秒（本機以釘選版本的 SDK 實測，延遲沒有
  可量測的差別）；initialize 成功（含 JSON-RPC 錯誤回覆）時 session 照常交給 client，其他方法不受影響。
- gateway（0.1.6 AI 測試第 0 階段的發現，負責人決定 D21）：經 OpenRouter 實測，Claude 與 GPT 只要看到任一工具的
  inputSchema 頂層有 oneOf、anyOf 或 allOf（GPT 另含 enum、const、not），就拒收整個請求（HTTP 400）。本 add-on 的
  `hermes_skill`、`hermes_tools`、`hermes_session`、`hermes_cron` 頂層是 oneOf（各 action 需要或不得帶的欄位），
  所以原樣轉送工具清單給 Claude 或 GPT 的 client 先前在 Hermes 上一個工具都叫不到（n8n、Odoo
  也一樣）。現在 tools/list 宣告的 inputSchema 頂層一律是 `type: object`：拿掉頂層組合子，title、properties（含
  預設值）、required、additionalProperties 照舊，分支規則改寫成英文短句附在 schema 的 description，例如
  `Argument rules (checked by the server): action="list": omit name; action="enable": requires name; ...`。宣告的
  schema 比原本寬（是原本的超集），驗證完全不變：gateway 仍用原本嚴格的 pydantic 模型檢查每個呼叫（含分支規則），
  只違反分支規則的呼叫（例如 action=enable 沒帶 name）照樣回 403、不會送到子程序。其他工具的 schema 頂層本來就沒有
  這些關鍵字，內容不變；管理面板 bootstrap 顯示的仍是原本用來驗證的 schema。
- 映像 `ghcr.io/woowtech/amd64-mcp-hermes:0.1.6`（候選 302c96d，build／container／supply-chain gate 全過；發佈候選完整獨立審查與複審 APPROVE WITH NOTES）；0.1.0–0.1.5 tag 不覆寫。
- 已知問題（延到 0.1.7）：
  - 被 policy 拒絕的 tools/call 仍回 HTTP 403（0.1.5 發佈候選審查 F7；上面 R2 的修正只涵蓋被拒的 initialize）。Python MCP SDK
    1.x client 收到這個 403 會整段斷線、不送 DELETE，每次在子程序留下一個 session，一直留到子程序重啟（見下一項）。
  - 子程序沒有閒置回收：一般 session 也只在 client 送 `DELETE /mcp` 或子程序重啟（含 Add-on 重啟）時結束，client 當掉、斷線或
    結束時沒送 DELETE，session 就一直留著、佔用記憶體。沒帶 `Mcp-Session-Id` 的 initialize 以外請求（例如 ping、tools/list、
    GET、DELETE）也會讓子程序開一個新 session 並留下來。client 用完請送 `DELETE /mcp`（帶 `Mcp-Session-Id`）。

## 0.1.5 — 2026-10-06 公開（experimental）

- gateway（0.1.4 複審與 0.1.5 審查的縱深防禦建議）：client 收到的每個回覆都由 gateway 重新組成，只含 jsonrpc、id 與 result 或 error 其中一個，error 只保留 code（一律整數）、message、data；子程序加在回覆最外層的其他欄位不再轉送（TS client 會把未知的最外層欄位名稱放進錯誤訊息），error 裡多出的欄位也一併去掉，ping 成功一律回 `{}`，其他 result 照子程序內容轉送（工具清單與 capabilities 照舊過濾）。POST 的 SSE 串流只轉送這個請求自己的回覆，送出後立即結束；GET 串流不轉送任何回覆（各子程序都沒有可續傳的事件紀錄）。錯誤碼超出 32 位元範圍或 message 不是字串時，改成 gateway 自己的錯誤。initialize 回覆的 protocolVersion 必須是日期格式（YYYY-MM-DD），否則回 502。
- 來源紀錄（ledger）：補列 backend_policy.py 在六個 Python venv（五支商店服務加上封存的 Odoo Manage 原始碼）守住的 httpx／httpcore 原始碼、odoo_b2_scope.py 在 Odoo venv 漏列的 4 個原始碼，以及 bounded_tools.py 在 OpenDesign venv 守住的 MCP SDK 原始碼。測試以 Python 語法樹找出各服務載入哪些共用模組（各種 import 寫法、常數參數的動態載入與間接載入，掃描服務內所有 Python 檔），逐一確認對應 venv 都有列；判定不了的載入方式（exec／eval、非常數參數、改名或以字串取得的載入函式）會讓測試失敗。
- 基底映像：`python:3.13.16-slim-bookworm` 改釘 Docker Hub 2026-10-06 重建版（amd64 `f0408636…`），已內含 libpcre2-8-0 10.42-1+deb12u2 與 perl-base 5.36.0-7+deb12u4 安全更新；原本從 Debian snapshot 升級 libpcre2 的步驟已移除。
- 映像 `ghcr.io/woowtech/amd64-mcp-hermes:0.1.5`（候選 0c66bd0，build／container／supply-chain gate 全過；發佈候選完整獨立審查 APPROVE WITH NOTES）；0.1.0–0.1.4 tag 不覆寫。

## 0.1.4 — 2026-10-06 公開（experimental）

- gateway（0.1.2 審查留下的建議，經 0.1.4 發佈候選審查補強）：子程序對請求的 4xx／5xx 回應保留狀態碼（404 讓 client 重開 session、Retry-After 照轉），內容改由 gateway 產生（JSON-RPC 錯誤 -32000 與 HTTP 狀態說明），不再轉送子程序的文字；失敗的 initialize 不帶 session id；子程序回 401／403（拒絕的是 gateway 自己的權杖）以及任何請求、DELETE、通知收到 1xx／3xx 都回 502。子程序的通知只轉 `notifications/tools/list_changed`，而且是 gateway 固定的內容；progress、log 等其他通知不轉送。回覆必須正好帶 result 或 error 其中一個；錯誤碼不是 JSON 整數（例如字串 "-32042"）或為 URL elicitation（-32042）時，改成 gateway 自己的錯誤、不帶子程序資料（JSON、SSE、initialize 都適用）。
- 共用核心：原生探測名稱改由健康檢查實際使用的探測取得（0.1.3 發佈候選審查 #6，行為不變）。
- 映像 `ghcr.io/woowtech/amd64-mcp-hermes:0.1.4`（候選 73a40eb，build／container／supply-chain gate 全過；發佈候選完整獨立審查 APPROVE WITH NOTES）；0.1.0–0.1.3 tag 不覆寫。

## 0.1.3 — 2026-10-06 公開（experimental）

- gateway：`/mcp` 的所有 HTTP 方法都先驗 Bearer 再回 405（`Allow: GET, POST, DELETE`）；TRACE、PROPFIND 等以前由框架在驗證前就回 405，Allow 清單還列了 gateway 實際拒絕的方法（0.1.2 審查的 NIT）。
- 健康檢查：子程序回的 `protocolVersion` 須符合與 session id 相同的規則（可列印 ASCII、不含空白、1–256 字元）才沿用為標頭；否則該輪判定失敗，並照常帶 session id 關閉 session（以前遇到無法當標頭的值會在清理前出錯，留下子程序 session）。
- 映像 `ghcr.io/woowtech/amd64-mcp-hermes:0.1.3`（候選 a0db7d7，build／container／supply-chain gate 全過；獨立審查：Odoo 健康探測 APPROVE WITH NOTES、意見已修，發佈候選完整審查 APPROVE WITH NOTES）；0.1.0、0.1.1、0.1.2 tag 不覆寫。

## 0.1.2 — 2026-10-06 公開（experimental）

- 初始化時子程序沒有回覆（例如後端連不上、子程序無法建立連線階段），gateway 改回 HTTP 503＋JSON-RPC 錯誤 `BACKEND_UNAVAILABLE`（附 Retry-After），不再給出 200 空回應與失效的 session id；串流回應只保留回覆那個事件的 id／event／retry 行，其餘事件（heartbeat、通知）不轉送；過大或格式錯誤的回覆回 502。
- 成功回應只接受 gateway 能解析、過濾的格式（0.1.2 獨立資安審查與複審的建議，舊版即有的缺口）：GET 必須是 SSE；請求的回覆必須是 SSE 或 HTTP 200 的 JSON，其他 2xx、其他、重複或缺少的媒體型別回 502，且不轉送該回應的任何內容（即使宣稱長度為 0）；通知與 DELETE 的回應只帶狀態與轉送標頭；轉送的標頭值須合規（不合規就丟掉，避免子程序的怪字元讓 gateway 出錯並佔住連線名額）；HEAD／PUT／PATCH／OPTIONS 驗證後回 405、不轉給子程序；轉給子程序的 Accept 固定；子程序回 100–599 以外的狀態碼時回 502；initialize 回覆的 session id 無法轉送時回 502；會溢位成無限大的數字（如 `1e400`）視同 NaN 拒絕；媒體型別不分大小寫、不帶參數比對，送給 client 的固定是 `text/event-stream` 或 `application/json`。JSON 回覆一律解析、須回應同一個請求（id 與型別相同），過濾後重新序列化；批次回 502。SSE 事件依看得懂的行重組（data、合規的 id／event／retry 與純 ASCII 註解），BOM、未知欄位等不轉送，單獨的 CR 視為格式錯誤；空 data 的 priming 事件照常通過；子程序發起的反向請求（elicitation、sampling、roots 等）不轉送。請求內容任何位置含孤立 surrogate 回 400。轉給子程序的 initialize 一律帶 `capabilities: {}`（gateway 不轉 sampling／elicitation 等反向請求）。
- 健康檢查：子程序的異常回應（不合規的 session id、怪異內容）只會讓就緒狀態為 false，不再讓整個 add-on 停止（獨立審查發現的舊問題）。
- bootstrap 在 HA 還原修復後，等 `/data/mcp` 通過最後檢查才印 `re-owned` 訊息；修復時暫時調高的 soft `RLIMIT_NOFILE` 修完即還原，不再沿用到管理程序。
- 映像 `ghcr.io/woowtech/amd64-mcp-hermes:0.1.2`（候選 114f23a，build／container／supply-chain gate 全過；獨立 SPEC 與安全審 APPROVE WITH NOTES、意見已修，修正複審 APPROVE WITH NOTES）；0.1.0、0.1.1 tag 不覆寫。

## 0.1.1 — 2026-10-05 公開（experimental）

- HA 管理權限 `homeassistant_api: true`（負責人 2026-10-05 核准，與 n8n 相同的固定 WebSocket 角色驗證），讓 HA owner／system-admin 能在 Ingress 面板設定後端；provider 90153cb 已 SPEC＋安全審。
- bootstrap 把 runtime `SUPERVISOR_TOKEN` 交給本產品管理程序（僅此一個變數，child 不繼承），供 HA 管理角色驗證使用。
- 修正 HA 還原本 Add-on 後資料變成 root 擁有、無法啟動的問題：bootstrap 只在資料剛好屬 root 時，第一遍核准並握住每個 inode、第二遍只改這些重驗過的 inode（R1 修正 d687cad、19892a3，獨立 SPEC＋安全審）。
- 映像 `ghcr.io/woowtech/amd64-mcp-hermes:0.1.1`（候選 d2e1e3b，build／container／supply-chain gate 全過）；0.1.0 tag 不覆寫。

## 0.1.0 — 2026-10-05 公開（experimental）

- 新增獨立 amd64 root-context 封裝、Supervisor 2026.09.3 安全子集 manifest。
- runtime：vendored SDK MCP 1.28.1；11 個來源工具中支援 7，4 個明列 withheld，
  [工具對照](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/tool-surface.md) 尚未完成功能平齊。
- 8099 Ingress-only／8081 可選 LAN／3000 loopback；保護模式、init true；不設
  backend-dependent watchdog、不開 HA/Supervisor/Docker API 權限。
- 共用 UI 已本地整合，exact grants/typed forms 已接 Core；本產品正式角色路徑仍封鎖；未建置 image、未做 HA E2E。
- 資料 v3：完整 v1/v2 migration、新增空 exact grants；UI 保存完整 grants+global false，disabled 優先，其他產品不可匯入 n8n state。
- 手動更新前做受控 cold backup（只中斷本 Add-on，含秘密）；rollback 必須使用相容
  image+完整資料，不可盲目 downgrade。請見 [完整步驟](https://github.com/WOOWTECH/Woow_ha_mcp_addons/blob/claude-delivery/docs/operations/update-backup-rollback.md)。
- 授權／公開去密／映像／實際 backend／Ingress/client／備份還原驗收仍待批准。
