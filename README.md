# WoowTech HA App Store

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_HA_App_Store)

一鍵加入 43 個 WOOWTECH 自製／鏡像維護 Home Assistant App 的統一 store repo。

## 使用方式

### 方法一：一鍵加入（推薦）
點選上方藍色按鈕（需在 HA UI 內），跳出「加入 add-on repository」對話框後按 **Add**。

### 方法二：手動加入
1. HA UI → **Settings** → **Add-ons** → **Add-on Store**
2. 右上角 ⋮ → **Repositories**
3. 貼上：
   ```
   https://github.com/WOOWTECH/Woow_HA_App_Store
   ```
4. 按 **Add** → 關閉 → 頁面下拉即可看到 43 個 App

### 方法三：CLI (HAOS SSH)
```bash
ha store add https://github.com/WOOWTECH/Woow_HA_App_Store
```

## 內含 Apps（43 個）

> 版本為 2026-10-13 的 catalog；即時版本以各目錄的 `config.yaml` 與 `.addon-sync/catalog.json` 為準。
> 「本機建置」= 沒有預建映像，安裝時由 Supervisor 在裝置上 build，耗時且吃記憶體，小機器請留意。

### 🏢 WOOWTECH 自主開發
| Slug | 名稱 | Ver | 安裝 | 用途 |
|---|---|---|---|---|
| `cloudflared` | Woow Cloudflared | 1.0.4 | 預建映像 | Cloudflare Tunnel 遠端存取（含 web GUI） |
| `odoo18ce` | Woow Odoo 18 | 0.4.11 | 預建映像 | Odoo 18 社群版 + PostgreSQL 16 一站式 |
| `woow-emqx` | Woow EMQX | 5.9.0 | 本機建置 | EMQX 5.x MQTT broker（企業級，內建 ngrok） |
| `woow-headscale` | Woow Headscale VPN | 0.1.0 | 本機建置 | 自架 Headscale + Headplane GUI |
| `woow-tailscale` | Woow Tailscale | 0.1.2 | 本機建置 | Tailscale / Headscale VPN 用戶端 |
| `woow-immich` | Woow Immich | 2.5.7 | 本機建置 | 自架相簿（Google Photos 替代） |
| `woow_lan_gateway` | Woow LAN Gateway | 0.1.6 | 本機建置（amd64） | 工廠註冊 LAN 的 fail-closed 公網 IPv4 閘道 |
| `woow-n8n` | Woow n8n | 2.12.17 | 預建映像 | AI/自動化 workflow |
| `woow-hermes` | Woow Hermes Agent | 0.1.6 | 預建映像（amd64） | Hermes Agent（NousResearch）：HA 側邊欄 dashboard + 聊天終端機，OpenAI 相容 API 與 Webhook 可經 Cloudflare Tunnel 對外 |
| `woow-nextcloud-office` | Woow Nextcloud Office | 0.2.3 | 預建映像（amd64） | Nextcloud + 內建 PostgreSQL／Redis／Collabora Online |
| `woow-nginxproxymanager` | Woow Nginx Proxy Manager | 2.12.4-v2 | 本機建置 | Nginx Proxy Manager 的 WOOWTECH 版（與社群版 slug 不同） |
| `woow_ha_code_server` | Woow Code Server | 0.1.6 | 預建映像 | code-server + pi coding agent + Claude Code + ACP 側邊欄（取代原 `vscode` 鏡像） |
| `woow_ha_pi_agent` | Woow HA Pi Agent | 0.14.5 | 預建映像 | pi-web + coding agent SDK + 影音管線 |
| `woow_ha_opendesign` | Woow HA OpenDesign | 0.1.9 | 預建映像 | Ingress-only BYOK 設計工作台 + PDF／圖片／PPTX 匯出 |
| `woow-omnigent` | Woow Omnigent | 0.1.15 | 預建映像 | Omnigent 編排伺服器 + 內建 Postgres（外部 runner 註冊制） |

### 🤖 MCP Server（WOOWTECH 自主開發，experimental）

把對應軟體的部分工具以 MCP（Streamable HTTP，Bearer token）提供給 AI client；預設只開讀取工具，寫入要由 HA 管理員在 add-on 面板逐支授權。圖示與所連接的軟體相同。來源與完整文件：[WOOWTECH/Woow_ha_mcp_addons](https://github.com/WOOWTECH/Woow_ha_mcp_addons)。
同一套 add-on 也在該 repo 自己的 store；兩個 store 的同名 add-on 在 HA 裡是不同的 add-on（slug 前綴不同，設定不互通），同一台 HA 只裝其中一個來源的。
下面 6 支只同步正式 Release，和其他來源 repo 一樣：升版的 PR 通過該 repo 的 `WOOW addon release` 檢查並合併後，自動發 `<slug>-v<版本>` 正式 Release，本 store 才會前進到該版本。原本的第 7 支 `woow_mcp_opendesign` 已於 2026-10-15 下架（見下方說明）。

| Slug | 名稱 | Ver | 安裝 | 用途 |
|---|---|---|---|---|
| `woow_mcp_n8n` | Woow n8n MCP Server | 0.1.9 | 預建映像（amd64） | n8n 的 MCP server |
| `woow_mcp_odoo` | Woow Odoo MCP Server | 0.1.9 | 預建映像（amd64） | Odoo 的 MCP server |
| `woow_mcp_hermes` | Woow Hermes MCP Server | 0.1.9 | 預建映像（amd64） | Hermes Agent 的 MCP server |
| `woow_mcp_emqx` | Woow EMQX MCP Server | 0.1.9 | 預建映像（amd64） | EMQX 的 MCP server |
| `woow_mcp_litellm` | Woow LiteLLM MCP Server | 0.1.9 | 預建映像（amd64） | LiteLLM（本 store 沒有 LiteLLM add-on，需自備） 的 MCP server |
| `woow_mcp_nextcloud` | Woow Nextcloud MCP Server | 0.1.9 | 預建映像（amd64） | Nextcloud（一個帳號的檔案、行事曆與任務） 的 MCP server |

### 🧩 HA Core 實例
| Slug | 名稱 | Ver | 安裝 | 用途 |
|---|---|---|---|---|
| `woow_ha_core_1..5` | Woowtech HA Core 1-5 | 2.3.0 | 本機建置 | 巢狀 HA Core 實例（每個獨立 onboarding，預設 port 8124-8128） |
| `apporo_ha_core_1..5` | Apporo HA Core 1-5 | 2.3.0 | 本機建置 | Apporo 品牌的巢狀 HA Core 實例。**與同編號的 `woow_ha_core_N` 預設使用相同 host port**，不要同時啟用，或先改其中一個的 port |
| `woow_ha_core` | Home Assistant Core (official image) | 2026.9.1-1 | 本機建置 | 獨立的官方 HA Core 2026.9.1，無品牌改動或預設設定；manifest 標為 **experimental** |

### 🪞 WOOWTECH 鏡像維護（防上游失聯）
| Slug | 名稱 | Ver | 安裝 | 上游 |
|---|---|---|---|---|
| `dnsmasq-dhcp` | Dnsmasq-DHCP | 5.1.1 | 預建映像 | [f18m/ha-addon-dnsmasq-dhcp](https://github.com/f18m/ha-addon-dnsmasq-dhcp) |
| `hamh` | Home-Assistant-Matter-Hub | 2.0.58 | 預建映像 | [riddix/home-assistant-matter-hub](https://github.com/riddix/home-assistant-matter-hub) |
| `frigate` | Frigate | 0.18.0 | 預建映像 | [blakeblackshear/frigate-hass-addons](https://github.com/blakeblackshear/frigate-hass-addons) |
| `jellyfin` | Jellyfin | 0.2.2 | 預建映像 | [hassio-addons/app-jellyfin](https://github.com/hassio-addons/app-jellyfin) |
| `music_assistant` | Music Assistant | 2.10.6 | 預建映像 | [music-assistant.io](https://music-assistant.io) |
| `local_audio` | Local Audio | 0.1.13 | 預建映像 | [music-assistant/local-audio-addon](https://github.com/music-assistant/local-audio-addon)；manifest 標為 **experimental** |
| `netease_cloud_music_api` | NetEase Cloud Music API | 0.1.1 | 本機建置 | [NeteaseCloudMusicApiEnhanced/api-enhanced](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced)（Music Assistant 用） |
| `ytm_po_token_generator` | YT Music PO Token Generator | 2.0.1 | 預建映像 | [Brainicism/bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) |
| `knxd` | KNXD daemon | 0.6.1 | 預建映像 | [da-anda/hass-io-addons](https://github.com/da-anda/hass-io-addons/tree/main/knxd) |
| `ha_mcp` | Home Assistant MCP Server | 7.14.1 | 預建映像（上游 homeassistant-ai 映像） | [homeassistant-ai/ha-mcp](https://github.com/homeassistant-ai/ha-mcp) |
| `ha_mcp_webhook_proxy` | Webhook Proxy for HA MCP | 2.0.4 | 本機建置 | [homeassistant-ai/ha-mcp](https://github.com/homeassistant-ai/ha-mcp) |

## 相依 store（HA 內建，非本 repo）

以下 addon 走 HA 原生 store，本 repo 不打包：
- **Advanced SSH & Web Terminal**, **Mosquitto**, **Node-RED**, **Glances** → 從「Community Add-ons」store 安裝
- **Nginx Proxy Manager**、**Tailscale** 的社群版同樣走 Community store；本 store 另提供 WOOW 版 `woow-nginxproxymanager`、`woow-tailscale`。slug 不同，是不同的 addon，不會自動取代已安裝的社群版
- **File editor**, **Samba share**, **Matter Server**, **ESPHome** → Official/Community store

> Jellyfin 原本要從 Community Apps store 安裝，現已改為本 repo 的 WOOWTECH 鏡像
> （`jellyfin`），不再依賴上游 store。
>
> **Woow OpenDesign MCP Server（`woow_mcp_opendesign`）已於 2026-10-15 下架**，OpenDesign 的
> MCP server 改為內建在 **Woow HA OpenDesign（`woow_ha_opendesign`）0.2.0** 裡。已安裝舊 add-on 的人
> 請到 OpenDesign 頁面右下角的 **MCP Server** 建立新 token、更新用戶端網址後，再移除舊 add-on；
> 舊 add-on 不會被自動移除，但本 store 不再提供或更新它。
>
> **Studio Code Server（`vscode`）已於 2026-09-11 下架**，由 WOOWTECH 自有的
> `woow_ha_code_server` 取代。兩者是**不同的 addon**（slug、選項 schema、映像都不同），
> 不是版本升級 —— 已安裝舊 `vscode` 的人不會被自動換掉，但本 store 不再提供它。

## 版本策略與同步

### 放行：通過必要檢查的升版合併

（管線工作區 ADR-0005，2026-10-21 起。）

- **放行就是合併一個修改 addon 版本、且通過所有必要檢查的 PR。** 不需要特定的人核准，必要檢查本身就是把關。合併後，該 repo 的 CI 在合併後的 commit 上發正式 Release，Store 才會同步（ADR-0002：只有正式 Release 才能出貨）。
- **WOOWTECH 自己開發的來源 repo 都採同一套分支規則**（`Woow_ha_odoo` 的「main: PR and green checks」形式），套在預設分支上（`Woow_ha_mcp_addons` 是 `claude-delivery`）：
  - 一律走 PR；禁止刪除分支與強制推送（non-fast-forward）。
  - 必要檢查是該 repo 在 PR 上會跑、而且會通過的 CI job；PR 的 CI 不設 path filter，否則必要檢查會一直等不到結果。
  - 核准數 0、不用 CODEOWNERS、`bypass_actors` 為空，誰都不能繞過。
  - 每個 repo 的 `AGENTS.md` 寫了給 agent 與人的三條規則：只能走 PR、升版 PR 必須通過必要檢查（包括 `Upgrade comparison / compare`）、破壞性變更要照下面的格式寫進 `upgrade-notes.yaml`。
- **發 Release 的方式可以不同，但都保證**：tag 不重複、每個架構的映像都已推送、Release 只發在合併後的 commit 上。`Woow_ha_odoo` 用自己的 `release.yml`，其他 repo 都用共用的 [`woow-addon-release.yml`](.github/workflows/woow-addon-release.yml)。推 tag 不會發 Release（推 tag 不經過 PR）。（OpenDesign 從推 tag 改成合併後發、Hermes 與 Nextcloud 改用共用 workflow 的 PR 在 2026-10-21 等負責人審查，合併前它們仍用舊方式。）
- **每個來源在 registry 的 `branch_rules`**：受管的 repo 列出 `required_checks`（ruleset 裡必須有的檢查名稱），而且 `required_workflows` 不能是空的。`required_checks` 要包含 `Upgrade comparison / compare`；還沒接上升版比對的 repo 改寫 `upgrade_comparison_pending`，內容是負責接上的 ticket（兩者只能有一個）。不受管的寫 `exempt` 與原因：
  - mirror（Dnsmasq、Frigate、Jellyfin、Matter Hub、Music Assistant）：由 `mirror-sync` 推送預設分支，不需要放行；發 Release 前的檢查見 pipeline #91。
  - `Woow_ha_ai_mcp`：上游 fork，上游帶來的 workflow 會直接推 `master`。
  - `Woow_ha_vscode_add_on`：已退役。
  
  `test_addon_sync.py` 檢查每個來源都屬於其中一種，也檢查每個受管 repo 不是列了 `Upgrade comparison / compare`，就是寫了 `upgrade_comparison_pending`。

  `required_workflows` 的意思和必要檢查不同：發布與同步前，這些 workflow 檔要在發布的 commit 上有一次成功、而且不是 PR 觸發的 run（`addon_sync.ci_gate`）。所以 `Upgrade comparison` 的呼叫端 job 要放在已經列在 `required_workflows`、push 到預設分支也會跑的 workflow 裡（odoo 的 `ci.yml`、omnigent 的 `publish-omnigent-addon-images.yml`），push 時它直接通過；不要另開只在 PR 觸發的 workflow 檔再列進 `required_workflows`，否則每次發布都會被擋。
- **每日監測**：[`branch-rules.yml`](.github/workflows/branch-rules.yml)（`.addon-sync/branch_rules.py`）每天讀 registry，逐一檢查受管 repo 的預設分支規則：四條規則都在、`required_checks` 都還是必要檢查（沒寫 `upgrade_comparison_pending` 的 repo 一定要有 `Upgrade comparison / compare`，即使 registry 漏列）、核准數 0、不要求 CODEOWNERS 審查、預設分支沒換。不符合就讓 run 失敗，訊息列出哪個 repo、哪一條，GitHub 會寄信。`WOOWTECH` 是共用帳號，拿到它的人（包括 agent）都能改規則；這個風險已經接受，靠監測讓改動一定會被發現。
  - `bypass_actors` 只有具 Administration 讀取權的 token 看得到。它放在 `branch-rules` environment 的 secret `BRANCH_RULES_TOKEN`（fine-grained PAT，resource owner `WOOWTECH`，選所有受管的來源 repo，權限 Administration: read-only），environment 只允許 `main`。沒設時 run 不會失敗，但會警告「沒檢查 bypass」。
  - 管線工作區的 issue monitor 也顯示最近一次的結果。
- 新增受管來源時：先在來源 repo 開 PR 讓 CI 跑一次、記下 check 名稱，套用 ruleset（照 `Woow_ha_odoo` 的形式），再在 registry 填 `required_checks`。接上升版比對也一樣：呼叫端合併後，先在 ruleset 加上 `Upgrade comparison / compare`，再改 registry（拿掉 `upgrade_comparison_pending`、在 `required_checks` 加上這個名稱）；順序反過來，Store PR 的規則監測會失敗。

### 升版比對與 `upgrade-notes.yaml`

（管線工作區 #89，ADR-0005。）

- **每個受管來源 repo 的每個 PR 都跑必要檢查 `Upgrade comparison / compare`**，由共用的 [`woow-addon-upgrade-check.yml`](.github/workflows/woow-addon-upgrade-check.yml) 提供（呼叫端 job 名稱 `Upgrade comparison`，GitHub 把檢查名稱寫成「呼叫端 job / 內部 job」）。呼叫方式寫在那個檔案開頭；不設 path filter。
  - PR 沒有修改任何 addon 的版本：十幾秒內通過（仍要取出兩個 repo、安裝兩個釘選的小套件 PyYAML 與 packaging（約 5 秒），並讀 PR base 上的 `config.yaml`）。PR 刪除或搬移了 registry 列出的 `config.yaml`（PR base 上有、PR 裡沒有）時檢查失敗：放回原處，或照下面「搬移 `config.yaml`」的步驟做。PR 和 PR base 都沒有 registry 列出的路徑時也失敗（registry 路徑寫錯是工具錯誤，不放行）。只比對會發 Release 的 addon（和 `addon_sync.release` 同一個條件：沒停用、`channel` 是 stable），刪除已停用 addon 的 `config.yaml` 不會讓檢查失敗。
  - **搬移 `config.yaml`**（換目錄或檔名；`config.yaml` 放在 addon 目錄的最上層）：
    1. 先合併 Store PR：把該 addon 的 registry 設定改成新位置（`source_path`、`config_file`），並加上 `previous_config: <舊的 config.yaml 在 repo 裡的路徑>`。
    2. 之後來源 repo 的 PR 不論先後都能合併：任何一邊（PR、PR base、比對對象的 Release、`addon_sync.release` 發 Release 的 commit、發布用的 `releases/latest`、已送到 Store 的通知）在新路徑找不到 `config.yaml` 時，都改讀 `previous_config` 和它旁邊的 `upgrade-notes.yaml`（`config.yaml` 是空檔也一樣）。Store 裡的 config 一律用 registry 的新檔名，不會留下舊檔名的檔案。只搬移沒升版的 PR 算「版本沒變」。
    3. 最新的正式 Release 已經是新路徑、而且已發布到 Store 後（`ref_policy: main` 是搬移 PR 合併、發布之後），再開 Store PR 拿掉 `previous_config`。在那之前開的、還是舊路徑的 PR，要先 rebase 到搬移之後。
    - 搬移 PR 比 Store PR 先開時，它的檢查會失敗並指向這裡；Store PR 合併後重跑即可。
  - **新增 addon**：先在來源 repo 合併加入新 addon `config.yaml` 的 PR（registry 還沒有這個 addon，檢查不會比對它），再開 Store PR 在 registry 加上這個 component。順序反過來時，registry 列出的路徑在 PR 和 PR base 都找不到，該 repo 每個 PR 的檢查都會失敗，`addon_sync.release` 和發布也會擋下這個 addon。
  - 有修改：把每個改了版本的 addon 和**比對對象**相比。比對對象是該 addon 目前最新的正式 Release（tag 規則同上：`v<版本>` 或 `<slug>-v<版本>`；哪些算正式 Release、tag 怎麼對應、怎麼排序，和 Release 說明共用 `addon_sync.py` 的同一套規則，由 `upgrade_check.py comparison-target` 判斷），`ref_policy: main` 是 PR base 上的版本；只有整個版本號都讀得懂的 tag（PEP 440，或 `-v<N>`、`-<N>` 重建後綴）才能當比對對象，`nightly`、`v9.0-test` 這類零散 tag 直接略過。**PR 的版本必須比比對對象新**，否則檢查失敗（PR 的版本無法和比對對象排序時也失敗）：Release 只從預設分支發，每個都標成 latest、發布也只送 `releases/latest`，所以在 1.3.0 之後發 1.2.5 是讓 1.3.0 的使用者降版，不是修舊線。`addon_sync.release` 也照同一條規則，不論有沒有 `upgrade-notes.yaml`，版本不比最新正式 Release 新就不發 Release。PR 檢查和 Release 說明都只看（比對對象, 新版本] 的宣告。第一次發布的 addon 沒有比對對象，不做比對並在報告註明；`upgrade-notes.yaml` 有空的 `migration` 或 `reason` 時仍會擋下。
  - PR 的版本號、比對對象的 tag、映像與版本號含換行、tab 等控制字元時檢查直接失敗；其他來自 PR 或 Release 的文字印到 log 前都先跳脫，GitHub 不會把它當成工作流程指令。
  - 結果只寫在 job summary，不在 PR 上留言。檢查工具出錯（拉不到舊映像、漏洞資料庫下載失敗或超過 120 小時）時檢查失敗，不放行，重跑即可。
- **第 1 類 設定相容性**：比較新舊 `config.yaml`。下表的破壞性變更都要在 `upgrade-notes.yaml` 宣告，否則擋下。`key` 用 schema 的路徑，例如 `database.port`。

  | `change` | 意思 | `key` |
  |---|---|---|
  | `option-removed` | 拿掉一個舊版 `options` 有預設值的 schema key | schema 路徑 |
  | `schema-removed` | 拿掉一個舊版 `options` 沒有預設值的 schema key | schema 路徑 |
  | `schema-retyped` | 型別或結構改變（`match()` 的 pattern 改變也算） | schema 路徑 |
  | `made-required` | 選填（`type?`）改成必填 | schema 路徑 |
  | `range-narrowed` | `int`／`float`／`str` 的範圍變窄或新加上限制 | schema 路徑 |
  | `enum-value-removed` | `list(a\|b)` 少了某個值 | schema 路徑 |
  | `required-added` | 新增必填 key，而 `options` 沒有預設值（`null` 不算預設值） | schema 路徑 |
  | `arch-removed` | 拿掉一個 arch | arch，例如 `aarch64` |
  | `port-removed` | 拿掉一個 port，或改了容器端 port、通訊協定 | port，例如 `8069/tcp` |
  | `image-changed` | `image` 改變、新增或拿掉 | `image` |

  只寫進報告、不擋：預設值改變（`default-changed`）、只改主機端預設 port（`host-port-changed`）。不擋也不報告：範圍變寬、列舉加值、必填改選填、新增選填 key、新增有預設值的 key。
- **第 4 類 漏洞比對**（只限有預先建置映像的 addon）：新映像由 repo 自己的 amd64 PR 建置，用 Store 的 [`addon-sbom`](.github/actions/addon-sbom/action.yml) 步驟交出 SBOM；舊映像從 GHCR 拉比對對象的 amd64 映像。兩邊用同一份 Grype DB 掃描（Grype、Syft 依 checksum 釘選）；任一邊的掃描結果沒寫出 DB（`descriptor.db.status` 的 `built` 與 `from`）或兩邊 DB 不同，檢查直接失敗。以（漏洞 ID, 套件）比對，**新映像才有、嚴重度 Critical 或 High、Grype `fix.state` 是 `fixed`** 的是「新增可修補漏洞」，沒宣告接受就擋下；同一組（漏洞 ID, 套件）Grype 列出多筆時，任一筆符合就算，報告的嚴重度與修補版本取自符合的那筆。舊映像就有的、沒有修補版本的、嚴重度不到 High 的只算進報告的數量。在裝置上建置的 addon 不做第 4 類，報告註明交由 #90。呼叫端傳 `skip_vulnerability_scan: "<原因>"`（任何非空的文字都算，加引號，否則 ` #` 之後會被 YAML 當成註解）時，這次呼叫的所有 addon 都不做第 4 類（例如 knxd 出貨的是第三方映像）；第 1 類照常比對。只有 Store registry 裡該 provider 有 `upgrade_comparison.skip_vulnerability_scan`（核准的原因與票號，目前只有 knxd #122、mcp_addons #123，第 4 類移到 #90）才能這樣傳，報告寫出的是 registry 裡核准的原因，不是呼叫端傳的文字；其他呼叫端傳了，檢查直接失敗。呼叫端不對建置 job 設 `needs:`：有版本變更時才等這次 run attempt 的 SBOM artifact，重跑請用 Re-run all jobs。
- **`upgrade-notes.yaml`** 放在每個 addon 的 `config.yaml` 旁邊，只有需要宣告時才建立：

  ```yaml
  "1.3.0":                     # 新版本號，加引號
    breaking:
      - change: option-removed # 和報告完全相同的 change 與 key
        key: ssl_port
        migration: 改用 ports 設定的 443/tcp。
    accepted_vulnerabilities:
      - id: CVE-2026-1234      # 和報告完全相同的 ID 與套件
        package: openssl
        reason: 上游 base image 還沒更新，預計 1.3.1 換掉。
  ```

  - 只讀版本號在（比對對象, 新版本] 之間的段落；更早的段落不算數，不會蓋掉這次新出現的變更。
  - 版本先照 PEP 440 排序（`2026.9.1-1` 是 2026.9.1 之後的修訂）；不符合時用點分數字加上 `-v<N>`／`-<N>` 重建序號（`2.12.4-v2` < `2.12.4-v3`，沒有序號的排最前）。無法排序的版本號會讓檢查失敗。
  - 每項破壞性變更要有 `change`、`key` 完全相同的一筆；接受的漏洞要有 `id`、`package` 完全相同的一筆。`migration`、`reason` 不能是空的；Release 說明會刊出它們，所以不論有沒有比對對象、有沒有做第 4 類都會檢查。報告會列出可以直接貼上的 `change`／`key`。
  - 寫了宣告、但檢查沒找到對應的變更：只寫進報告，不擋。
- **Release 說明**：發 Release 時，比對對象（版本比它低的最新正式 Release）之後各版的宣告自動整理成「破壞性變更與遷移方式」「已接受的漏洞」兩段，放在 GitHub 自動產生的說明前面；共用的 `woow-addon-release.yml` 和 `Woow_ha_odoo` 的 `release.yml` 都這樣做。沒有宣告就不加；檔案格式錯誤時不發 Release。
- 判定規則與 `change` 名稱的權威說明在 [`.addon-sync/upgrade_check.py`](.addon-sync/upgrade_check.py) 開頭，`upgrade-notes.yaml` 的格式、版本排序與 Release 說明在 [`.addon-sync/addon_sync.py`](.addon-sync/addon_sync.py)（`REBUILD` 上方的說明）；兩者不一致時以程式為準，並修正本段。

### 同步流程

- 每個 App 目錄都從**對應的 WOOWTECH 個別 repo 單向同步**，不在本 repo 直接修改。唯一例外是側欄標題政策 `.github/scripts/sidebar_titles.py`。來源、路徑與政策的對照表在 [`.addon-sync/registry.json`](.addon-sync/registry.json)。
- 流程：
  0. 來源 repo 的 CI 通過後，由共用的 [`woow-addon-release.yml`](.github/workflows/woow-addon-release.yml) 替新的 addon 版本發正式 Release（單一 addon 的 repo tag 為 `v<版本>`，多個 addon 的 repo 為 `<slug>-v<版本>`）。[`Woow_ha_mcp_addons`](https://github.com/WOOWTECH/Woow_ha_mcp_addons) 的映像在建置 VM 建置，所以它的 CI 另外檢查映像已公開、而且要發的版本有建置 VM 的發佈紀錄。
  1. 個別 repo 的 `woow-addon-sync.yml` 確認必要 CI 與各架構映像都通過，再把固定 commit、雜湊與映像 digest 寫進該 repo 的 `woow-addon-sync` 分支。
  2. 本 repo 的 `sync-upstreams.yml` 依 registry 重新驗證：正式 Release、CI、預設分支、各架構映像、防降版、防亂序。
  3. 全部通過後才更新 App 目錄與 [`.addon-sync/catalog.json`](.addon-sync/catalog.json)。
  
  細節見 [`.addon-sync/README.md`](.addon-sync/README.md)。
- **只同步正式 Release**（ADR-0002）：43 個 App 裡 32 個（含 6 個 `woow_mcp_*`）。以下 11 個仍跟隨來源 repo 的預設分支，正在逐步切換：`apporo_ha_core_1..5`、`woow_ha_core`、`ha_mcp`、`ha_mcp_webhook_proxy`、`frigate`、`jellyfin`、`woow-nginxproxymanager`。每個來源的設定以 [`registry.json`](.addon-sync/registry.json) 的 `ref_policy` 為準。
- 觸發方式（盡力而為，不是即時）：
  - 排程每 5 分鐘一次，錯開整點。此帳號的 GitHub 排程實測常延遲 2–7 小時。
  - 來源 repo 寫出新的通知後（共用發布 workflow 的 output `ready` 為 `true`），由該 repo `woow-addon-sync.yml` 的 `notify-store` job 送 `repository_dispatch`（`woow-addon-ready`），幾分鐘內同步。來源 repo 要設 `APP_STORE_DISPATCH_TOKEN`，沒設時等排程。27 個來源 repo 都已設（2026-10-13）；token 的權限與輪替見 `.addon-sync/SOURCES.md` 的「Store dispatch token」。
  - 手動執行 workflow。
- 驗證失敗或來源版本較舊時保留現有版本，並在 workflow 頁面以 warning 標示；不會清空目錄。
- 開發／beta／nightly 通道（例如 `music_assistant_beta`、`hamh-alpha`、`ha_mcp_dev`）不會進入本 store。
- `woow-tailscale`：自 2026-10-06（0.1.2）起以個別 repo [`Woow_ha_vpn_tailscale_package`](https://github.com/WOOWTECH/Woow_ha_vpn_tailscale_package) 為權威，已併入原 store 0.1.1 的修正。
- `knxd`：來源是 WOOWTECH 鏡像 repo [`Woow_ha_knxd_add_on`](https://github.com/WOOWTECH/Woow_ha_knxd_add_on)，釘在上游 0.6.1；要升版需先更新鏡像 repo。
- 想單獨安裝：加入對應的**個別 repo URL**（例如 `WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on`）
- 想用單一入口：加入**本 store URL**

## 本機下載（Local Download）

`.addon-sync/download_addon.py` 只需 Python 3 標準函式庫，可把 catalog 中的 App 下載成 HAOS `/addons/` 的 local addon 目錄：

```sh
python3 download_addon.py --list
python3 download_addon.py woow_ha_pi_agent --destination ./local-addons --arch amd64
```

- 驗證 catalog ID、來源封存檔與 manifest 雜湊。
- 拒絕覆寫既有目錄；新下載的目錄一律 manual boot。
- 不會安裝、啟動、升級或解除安裝任何 App。
- 有預建映像的項目會包成固定 digest 的 local Dockerfile，這**不是重新編譯原始碼**；「本機建置」項目則在安裝時 build。

## 授權

各 addon 保留其原始授權：
- WOOWTECH 自主 addon：見各子目錄 LICENSE
- 鏡像 addon（`dnsmasq-dhcp`, `frigate`, `hamh`, `jellyfin`, `knxd`, `music_assistant`, `local_audio`, `netease_cloud_music_api`, `ytm_po_token_generator`, `ha_mcp`, `ha_mcp_webhook_proxy`）：
  各自沿用 upstream 授權。Dnsmasq-DHCP、Frigate（blakeblackshear）與 Jellyfin
  （hassio-addons）皆為 MIT

## 維護

- 維護者：WOOWTECH `<woowtech@designsmart.com.tw>`
- Baseline 目標：HAOS 18.x、HA Core 2026.7.x、amd64 / aarch64
- 各 add-on 的實機驗證狀態以其個別 repository 與 release 紀錄為準
