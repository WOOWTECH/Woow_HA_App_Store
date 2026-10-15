# OpenDesign add-on 內建 MCP server — 設計（P3b，team ha-mcp，2026-10-14）

> 分支：GitHub `WOOWTECH/Woow_ha_opendesign_add_on` 的 `team/ha-mcp-builtin`（自 origin/main `ab7d749`）。
> 新檔全部在 `mcp-runtime/`。原型階段改既有檔的部分曾以 `mcp-runtime/integration.patch` 交付；**0.2.0 已整合**（team ha-integrate，分支 `team/ha-integrate-0.2.0`）：patch 的意圖已直接套在核心映像版的 Dockerfile、launcher（`start_child mcp`）、nginx、config.yaml、DOCS 與測試上，patch 檔與 core-standin 證明用 Dockerfile 已移除，`run-proof.sh` 改為直接測正式建出的 add-on 映像（見 §13）。
> 證據：本目錄 `evidence/`（builder VM 實測）。本文件同時放在 repo `docs/plans/2026-10-14-builtin-mcp-design.md`。

## 1. 結論

- **沿用 Woow MCP runtime（gateway＋vendored OpenDesign tools），不橋接上游 `od mcp`。** gateway、工具政策、state store、子程序監管、健康檢查、管理 UI、15 支工具的 vendored server 全部原封不動（釘 commit、記檔案雜湊；HA 管理員角色查詢依使用者決定不使用），本地只加約 250 行膠水（`mcp-runtime/ha_opendesign_mcp/`）。
- 後端**固定**為同容器的 OpenDesign daemon `http://127.0.0.1:7456`，沒有連線設定。
- LAN MCP：容器 `8081/tcp`＋Bearer（`ports: 8081/tcp: null`，預設不映射）；同一個 listener 也支援 `/private_<token>/mcp`（vendored 版本已含 cc588488 的密鑰網址實作）。
- 管理（顯示／輪替／撤銷 token、工具權限）：`<Ingress>/mcp-admin/`，只有 Supervisor Ingress 來源可進；**以 HA Ingress 登入為準，不另查 HA 管理員角色、不開 `homeassistant_api`**（使用者決定 2026-10-14，接受風險見 §5）。
- 已在 builder VM 用「核心映像替身＋真的 add-on launcher／nginx／rootfs＋本 patch」跑通：initialize → tools/list → tools/call、401／403／404、token 輪替撤銷、權限授予、管理頁、daemon 暫停／崩潰後恢復、Claude Code 2.1.296 以 Bearer 和密鑰網址連線（§12）。

## 2. 架構

```
                HA Supervisor (172.30.32.2)                       LAN / 其他 add-on / CF tunnel
                   │ Ingress :8099                                     │ :8081（使用者自行映射主機埠）
┌──────────────────┼───────────────────────────── add-on 容器 ─────────┼─────────────────────────────┐
│  nginx (uid ha-ingress 1002) :8099                                    │                             │
│   ├─ /            → 127.0.0.1:7456  OpenDesign daemon (uid open-design 1001)                        │
│   ├─ /terminal/   → 127.0.0.1:7681  ttyd (uid 1001)                   │                             │
│   └─ /mcp-admin/  allow 172.30.32.2 only                              │                             │
│        → unix:/run/ha-opendesign-mcp/admin.sock (dir 0750 mcp:ha-ingress)                           │
│                         │                                             │                             │
│  MCP management (uid mcp 10001, not dumpable, no_new_privs)  ◄────────┘ 0.0.0.0:8081 /mcp (Bearer)   │
│   vendored gateway: admin app ＋ MCP app ＋ policy ＋ store /data/mcp     /private_<token>/mcp       │
│   └─ unix:/run/ha-opendesign-mcp/child/child.sock (dir 0700 mcp)                                     │
│        vendored OpenDesign MCP server（15 工具，對外只開 10＋1）── http://127.0.0.1:7456 ──► daemon  │
│                                                                                                     │
│  launcher (root, tini PID1)：od / nginx / ttyd / mcp 四個程序，任一結束 → 全部停、整個 add-on 重啟    │
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

三個身分，彼此隔離（實測見 `evidence/06-container.txt`）：

| uid | 程序 | 能碰 | 碰不到 |
|---|---|---|---|
| open-design 1001 | daemon、agents、ttyd shell | `/data/opendesign`、loopback 7456／3000 等 | `/data/mcp`（0700）、`/run/ha-opendesign-mcp`、MCP 程序的 environ；沒有 `SUPERVISOR_TOKEN` |
| ha-ingress 1002（新） | nginx | `admin.sock` | `child.sock`、`/data/mcp`；沒有 `SUPERVISOR_TOKEN` |
| mcp 10001（新） | gateway＋child | `/data/mcp`、兩個 socket | 沒有 `SUPERVISOR_TOKEN`（不需要任何 HA／Supervisor API） |

## 3. 執行環境選擇

| 方案 | 優點 | 缺點 |
|---|---|---|
| **A. Woow gateway＋vendored server（採用）** | 與其他 6 支 HA MCP 同一份 gateway：Bearer、Origin 規則、精確寫入授權、回應過濾、session 閒置回收、log 遮罩、`/private_<token>/mcp`；工具面與舊 add-on／PaaS 相同（15 支，對外 bounded 11）；已審過 | 多一份 Python runtime（+~90 MB 映像、+~115 MB RSS）；需追 vendored commit |
| B. 橋接上游 `od mcp`（stdio） | 不用 Python | `od mcp` 是給容器內 CLI 的 stdio server，工具約 25 支且含 `write_file`／`delete_file`／`start_run`／`create_project` 等寫入與 agent 執行；沒有認證、沒有逐工具政策；要另寫 stdio↔HTTP 橋＋重做整套政策，等於重寫 gateway |

容器內 CLI 照舊用 `od mcp`（stdio），不受影響。

## 4. 後端與 daemon 認證

- `BACKEND_URL = http://127.0.0.1:7456`（launcher 固定 `OD_BIND_HOST=127.0.0.1 OD_PORT=7456`）。每次啟動 `pin_backend()` 把 state 的 connection 寫成這個值；管理 API `PUT /api/backend` 一律 403（`IngressSocketPeer`，實測 `evidence/03-admin.txt`）。
- daemon 認證：上游 `OD_API_TOKEN` 未設定時 API token middleware 不啟用（`apps/daemon/src/api-token-auth.ts`），launcher 沒設它，daemon 只綁 loopback，對外唯一入口是 nginx。vendored server 不送後端 Authorization（舊 add-on 的 `OpenDesignConnection` 本來就只有 URL）。實測不帶 token 即可 `health`／`list_projects`。
- 若日後核心映像或 add-on 開啟 `OD_API_TOKEN`：child 需要帶 header（vendored server 不支援，要在 `ha_opendesign_mcp/child.py` 給 httpx client 加 header，從只有 uid mcp 可讀的檔案讀入），屆時再評估；目前不需要。
- backend_policy（vendored）不擋 127.0.0.0/8，loopback 目的地可用。

## 5. Token 生命週期與管理頁

- **產生**：第一次啟動由 vendored `Store._initial_state()` 產生（`secrets.token_urlsafe(32)`，43 字元），存 `/data/mcp/state.json`（0600 mcp:mcp）。另有內部 `child_token`（gateway→child，child 不驗，僅沿用）。
- **顯示／輪替／撤銷**：管理頁 `POST /api/token/{reveal,rotate,revoke}`，需 CSRF＋Ingress 使用者。輪替／撤銷**立即**對 Bearer 與密鑰網址生效，進行中的串流也會被切（gateway 每 0.2 s 重新檢查）。實測：舊 token 401、新 token 200、撤銷後 Bearer 401／密鑰網址 404、再輪替恢復（`evidence/05-token-lifecycle.txt`）。
- **管理頁位置**：`<add-on Ingress>/mcp-admin/`。路徑：HA → Supervisor（172.30.32.2）→ nginx `/mcp-admin/`（`allow 172.30.32.2; deny all;`，其他來源 403，實測）→ `admin.sock`（只有 ha-ingress 群組能開）→ `IngressSocketPeer`（把「經由此 socket」轉成 vendored `admin_identity()` 要的 peer）→ vendored admin app：仍要求剛好一個 `X-Remote-User-Id`（Supervisor Ingress 設定）、`X-Ingress-Path` 與 CSRF。
- **不查 HA 管理員角色（使用者決定 2026-10-14）**：不開 `homeassistant_api`。做法是**設定而非改 vendored 檔**：傳給 vendored `make_apps(verify_admin=...)` 的角色提供者換成本地的 `ingress_user()`（只用 vendored `valid_user_id` 檢查 user id 格式，不呼叫任何 Supervisor／Core API）。vendored 的 `ha_role.make_ha_admin_verifier` 不再使用，vendored 檔案零修改（`VENDOR.json` 雜湊不變），所以不需要 overlay。實測：測試網路上 172.30.32.2 只是一個什麼都不提供的容器（沒有 Core WebSocket），管理頁照常可用；不帶使用者 403、無 CSRF 403、非 Supervisor 來源 403（`evidence/03-admin.txt`）。
- **接受的風險**：任何能打開本 add-on Ingress 的 HA 使用者都能進 `/mcp-admin/`（顯示／輪替／撤銷 token、開寫入授權），與 OpenDesign 本身和 ttyd 終端機同一道門。實測「另一個 HA 使用者」也是 200（`evidence/03-admin.txt`）。DOCS.md 與 nginx 註解都寫明。
- launcher 讓四個子程序（OpenDesign、nginx、ttyd、MCP bootstrap）全部以 `env -u SUPERVISOR_TOKEN -u HASSIO_TOKEN` 啟動（main 上前三者原本會繼承 Supervisor token），bootstrap 的 exec 環境也不再帶入；Supervisor token 只留在 root launcher。
- 管理 UI 是 vendored 的共用 UI，「後端連線」頁仍會出現（顯示已設定，送出會被拒）；要隱藏需改共用 UI（cc588488 的 repo）或本地覆寫，列為後續。management 程序仍設為不可 dump（vendored guard），同 uid 的 child 讀不到它記憶體中的 token。

## 6. 工具政策預設

> **0.2.1 更新（使用者決定 2026-10-15）**：改為與 PaaS 相同 15 支、預設全開（含 `create_project`／`send_message`／`delete_project`），以 HA 自有 overlay 補上界限（`mcp-runtime/README.md`「0.2.1 tool overlay」）；0.2.0 既有狀態於首次啟動一次性授予三支寫入工具（管理員已停用者除外）。以下為 0.2.0 當時的設計。

- 對外 bounded 11 支：讀取 10 支預設開（`health`、`version`、`list_agents`、`list_projects`、`get_project`、`list_project_files`、`get_file_info`、`list_plugins`、`list_skills`、`list_runs`），`delete_project` 預設關、需在管理頁精確授予。
- 上游另 4 支 `create_project`、`send_message`（會跑 agent、花費、SSE 未界定）、`read_file`（任意私檔）、`list_connectors`（未投影 connector 設定）**不在 allowlist，無法開**（同舊 add-on 0.1.11 的 `docs/tool-surface.md`）。
- 實測：child 直接列出 15 支（`evidence/06-container.txt`）；gateway 預設列 10 支，授予 `delete_project` 後 11 支，撤回後 10 支（`evidence/04-policy.txt`）。

## 7. 8081 對外

- `ports: 8081/tcp: null`＋說明，預設不映射，使用者在 add-on「網路」自行開；`tests/validate.py` 改成「只允許這一個且必須是 null」。
- `/mcp`：Bearer 必要；帶 `Origin` → 403（瀏覽器不在 Bearer 合約內）；無／錯 token → 401＋`WWW-Authenticate: Bearer`。
- `/private_<token>/mcp`：給 Claude.ai 網頁連接器（不能帶 header）；允許 Origin；錯 token 回與未知路徑相同的 404。
- 同 hassio 網路的其他 add-on（例如 cloudflared）可直接連 `http://<add-on 主機名>:8081/...`，不必映射主機埠；主機名＝`<repo 前綴>-woow-ha-opendesign`（本機建置為 `local-woow-ha-opendesign`）。
- 舊 MCP add-on 若已把主機 8081 映射走，新 add-on 映射時要換主機埠或先移除舊 add-on。

## 8. 密鑰網址（URL secret）怎麼接 cc588488 的修改

- 現況：cc588488 的實作在 `Woow_ha_mcp_addons` 分支 `boot-auto-0112`（PR #3，未合併），頭為 `72b672e22ae301132b43a5acd204f61d3be2bc29`（serverInfo 版本 0.1.13：`/private_<token>/mcp`、`redact.py` 遮罩 log、`params._meta` 接受與未知方法回應）。`claude-delivery`（已發佈 0.1.11）是 `1113955`，沒有密鑰網址。
- **原型釘 `72b672e`**（`mcp-runtime/VENDOR.json` 記 36 檔 sha256）。方式：`mcp-runtime/vendor.sh <clone> <full sha>` 用 `git archive` 只取需要的路徑；`mcp-runtime/tests/verify_vendor.py`（patch 後由 `tests/run.sh` 執行）檢查 vendor 沒被改、requirements 與 `.in` 完全一致。
- **已改釘（2026-10-14，team ha-integrate）**：PR #3 已合併進 `claude-delivery`，合併 commit `93727eaab0e05245d63eec7400294fe14f3cf6b9`（serverInfo 0.1.14）；`vendor.sh` 重釘後 36 檔中只有 `mcp_admin_core/{__init__,gateway,policy}.py` 改變（ed3122b：被拒的 tools/call 改回 HTTP 200＋JSON-RPC -32602／-32603 與欄位原因、不回顯輸入；其他不合格請求仍 403），uv.lock 未變。原本：等 PR #3 合併、cc588488 回報合併後 commit，重跑 `vendor.sh` 改釘那個 SHA（永不追分支），再跑 `mcp-runtime/tests/e2e/run-proof.sh`；若 uv.lock 版本有變，更新 `requirements/*.in` 後跑 `requirements/lock.sh`。
- 本地沒有改 vendored 檔，所以重新釘版只會換 `vendor/` 與 `VENDOR.json`；本地膠水只依賴 `make_apps`、`ProductStore`、`child_spec`、`Supervisor`、`HealthMonitor`、`valid_user_id`、`redact`、`run_product.Listener` 這幾個介面。

## 9. Python 與依賴

- 核心映像替身（`od-p1-candidate:local`）是 Alpine 3.24、`/usr/bin/python3`＝CPython 3.14.8；上游 lock 是 3.13。做法：用映像自己的 python3 建兩個 venv（management、child，與上游同結構），只裝 `--require-hashes --only-binary=:all: --no-deps` 的 wheel；**版本與上游 `uv.lock` 完全相同**，只是重新為 3.14／musl 產生雜湊（含 aarch64 wheel）。
- build 時自檢：vendored `backend_policy.check_sources()`（httpx／httpcore 原始碼雜湊）、`BoundedTools`（MCP SDK 原始碼雜湊）、child 15 支工具、gateway opendesign 11 支。
- 上游 gateway 單元測試子集（secret path、Claude.ai connector、boundary、HA role、health、lifecycle、initialize、schemas、policy/security）：3.14 與 3.13 都是 934 passed、27 failed、14 errors，**失敗集合完全相同**，全部是測試環境缺各產品 child venv／n8n node_modules（`evidence/pytest-py31{3,4}.txt`），沒有 3.14 特有失敗。
- 3.14 有一個 pydantic-settings `IncompleteFieldDefinitionWarning`（FastMCP Settings 的 `lifespan`），功能實測正常；列為觀察。
- 若 ha-shell 最後仍在 0.21.1 基底（其 python3 版本不同），需用該版本重跑 `requirements/lock.sh <版本>`。

## 10. 記憶體與映像

- 實測（閒置、無專案，`evidence/06-container.txt`）：management RSS ≈ 53 MB、child RSS ≈ 62 MB（PSS 55 MB），合計 ≈ **115 MB RSS**；整個容器 cgroup ≈ 300 MB（daemon RSS ≈ 240 MB）。落在原估 +100～170 MiB 內；session 多時每個約 50～100 KiB（上游量測），閒置 30 分回收。
- 映像增加：install 層約 75 MB＋UI dist 約 15 MB，≈ **+90 MB**。

## 11. 程序監管、備份、遷移

- **監管**：launcher 從 3 個變 4 個（`mcp_pid`），`wait -n` 任一結束 → TERM 全部、5 s 後 KILL → 非 0 結束 → Supervisor（watchdog）重啟。child 由 gateway 自己的 `lifecycle.Supervisor` 管（3 次退避重試，之後 `failed`，readiness 503，但不拖垮 OpenDesign）。
- daemon 短暫不可用（SIGSTOP）：MCP 不掛，工具回 `BACKEND_TIMEOUT`、readiness 503；恢復後約 7 s 回到 200（`evidence/07-daemon-pause.txt`）。daemon 崩潰（SIGKILL）：整組停、容器約 2 s 內重啟、18 s 就緒，**同一個 token 照用**（`evidence/08-daemon-restart.txt`）。
- **重啟空窗（0.2.0 整合後實測，`run-proof.sh` step 14，每秒一次完整握手）**：daemon 被 SIGKILL 的瞬間 MCP 仍在，initialize／tools/list 200、工具回 `BACKEND_UNAVAILABLE`；接著整組重啟約 2 s 連不上（ConnectError）；容器回來後有約 1 s initialize 回 **502**（gateway 已聽 8081、child 還沒起來，與另外六支「後端未設定時 502」同一個 vendored 行為），之後 initialize／tools/list 200、工具回 `BACKEND_UNAVAILABLE`，約 6 s 後工具正常。要消掉那 1 s 的 502 需改 vendored gateway（cc588488 的 repo），本 repo 不改 vendored 檔。
- **SIGTERM（0.2.0）**：ha-shell 的 `headless-entry.mjs` 修正後，對 daemon 送 TERM 會印 `SIGTERM received` 並以 0 結束；`docker stop` 整組約 1.5 s、沒有 KILL fallback（team ha-integrate `stop-timing.log`）。下一點是 0.1.x／core-standin 時的舊觀察。
- **觀察（OpenDesign 端、給 ha-shell）**：在核心映像替身上單獨對 daemon 送 SIGTERM，`headless-entry.mjs` 印出 `SIGTERM received` 後 240 s 內沒有結束；第一次試跑時拖了約 1 分鐘後以 status 134（Aborted, core dumped）結束。HA 正常停止會走 launcher 的 5 s 後 KILL，影響有限，但停機會卡滿寬限期。
- **備份／還原**：`/data/mcp` 在 `backup: cold` 內（token 明文在備份裡，與舊 add-on 相同）；還原後 root-owned 的樹由 vendored `entrypoint.prepare_data()` 的有界修復改回 10001。還原到另一台 HA 後建議輪替 token。**尚未在 HA 實機驗證**。
- **遷移**：舊 add-on 的 `/data/mcp` 屬於另一個 add-on，不搬；內建版第一次啟動產生新 token。使用者步驟：更新 OpenDesign add-on → 開 `/mcp-admin/` 設定端點、複製 token／Claude.ai 網址 → 各用戶端換新網址與 token → 移除 Woow OpenDesign MCP Server。DOCS.md 文字在 patch 內。

## 12. 測試計畫與現況

| 層級 | 內容 | 狀態 |
|---|---|---|
| repo 靜態 | patch 後 `tests/run.sh`（validate.py、launcher 測試、vendor 完整性） | ✅ 本機通過 |
| 容器（builder VM） | `mcp-runtime/tests/e2e/run-proof.sh`：假 hassio 網路 172.30.32.0/23、172.30.32.2 只當 Ingress 來源（不提供任何 API）、真 launcher；01～10 證據；最後檢查證據裡沒有任何拋棄式 token | ✅ |
| 上游單元測試 3.14 | 子集 934 passed，失敗集合與 3.13 相同（環境缺件） | ✅ |
| Claude Code（Bearer） | 2.1.296 `claude mcp add --header Authorization…` → `✔ Connected`；密鑰網址 `✔ Connected`；無認證 → 失敗（`evidence/09-claude-code.txt`） | ✅（容器內） |
| HA 實機（非正式站的測試 HAOS） | 真 Ingress（含 `X-Remote-User-Id` 與 `X-Ingress-Path`）、備份還原、boot auto、aarch64、Supervisor 本機建置能否處理多階段 Dockerfile | ⏳ 需測試用 HAOS（不得用 svc-f1a3c502／woowtech-ha） |
| Claude Desktop | `npx mcp-remote http://<HA>:<port>/mcp --header "Authorization: Bearer …"` | ⏳ 需桌機 |
| Claude.ai | Cloudflare tunnel → add-on `:8081/private_<token>/mcp`，含 Host header、長連線斷線重連 | ⏳ 等 PR #3 合併＋測試 tunnel |

## 13. 整合說明（0.2.0 已套用；以下為原 patch 的內容，供追溯）

原 `integration.patch` 會改（現已直接改在對應檔案；launcher 改用 ha-shell 的 `start_child`，四個子程序都以 `"${no_supervisor_env[@]}"` 啟動）：
1. `Dockerfile`：最前面多一個 `woow-mcp-ui` 階段（用基底自己的 npm 建 UI，`--include=dev` 因基底 `NODE_ENV=production`）；主階段末尾 3 行（COPY dist、COPY mcp-runtime、RUN install.sh）。換 FROM 時這兩塊原樣保留即可。
2. `rootfs/usr/local/bin/ha-opendesign`：`mcp_pid`、nginx 改 `su-exec ha-ingress:ha-ingress`、nginx 暫存目錄改 ha-ingress 擁有、四個子程序都去掉 Supervisor token、第 4 個程序 `/opt/woow/bin/ha-opendesign-mcp &`。
3. `rootfs/etc/nginx/nginx.conf`：`/mcp-admin` 兩個 location。
4. `config.yaml`：`ports`／`ports_description`（8081）；**不加** `homeassistant_api`（`tests/validate.py` 檢查它、`hassio_api`、`full_access` 都沒開）。
5. `DOCS.md`：「Built-in MCP server」一節。
6. `tests/validate.py`、`tests/launcher.test.mjs`、`tests/run.sh`：配合上述。
與 main 的差異都集中在以上幾段，FROM／CLI 版本相關行不碰。

## 14. 使用者決定（2026-10-14）與後續

1. 管理員驗證：**只靠 HA Ingress 登入**，不開 `homeassistant_api`，保留 nginx 只收 Supervisor 來源 —— 已實作（§5），接受風險已寫入 DOCS.md。
2. **不提供**關閉內建 MCP 的選項，永遠啟動（原型本來就沒有此選項，`options: {}` 不變）。
3. MCP 程序結束 → 整個 add-on 重啟 —— 維持現狀（§11）。
4. vendored `opendesign_mcp_server` 視為 WoowTech 自有程式碼；來源與授權註記見 repo `mcp-runtime/PROVENANCE.md`（Gitea `WOOWTECH/woow-mcp-server@614ae663`，MIT © WOOWTECH，LICENSE 與該 commit 的 `apps/opendesign/LICENSE` 逐位元相同）。
5. 原型曾釘 `72b672e`；PR #3 合併後已改釘合併 commit `93727ea`（0.1.14，§8）。
6. **後續（未決定）**：在 OpenDesign 介面放 `/mcp-admin/` 的入口連結；目前只能手動開網址（DOCS.md 已寫）。

## 15. 風險／未驗證

- 未在真 HA Supervisor 上跑（Ingress 標頭、還原修復、Supervisor 本機 build 對多階段 Dockerfile 的支援都只在模擬或文件層面）。
- 未驗 aarch64（wheel 雜湊已含 aarch64）。
- 未驗 Claude.ai 經 Cloudflare。
- 核心映像替身的 daemon 回報版本是 `0.23.1`：已確認為正常（OpenDesign 0.24.1 的 daemon 套件版本就是 0.23.1）。
