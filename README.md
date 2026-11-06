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

> 單一 App 的版本欄會隨 catalog 同步更新；即時版本以各目錄的 `config.yaml` 與 `.addon-sync/catalog.json` 為準。
> 「本機建置」= 沒有預建映像，安裝時由 Supervisor 在裝置上 build，耗時且吃記憶體，小機器請留意。

### 🏢 WOOWTECH 自主開發
| Slug | 名稱 | Ver | 安裝 | 用途 |
|---|---|---|---|---|
| `cloudflared` | Woow Cloudflared | 1.1.2 | 預建映像 | Cloudflare Tunnel 遠端存取（含 web GUI） |
| `odoo18ce` | Woow Odoo 18 | 0.4.12 | 預建映像 | Odoo 18 社群版 + PostgreSQL 16 一站式 |
| `woow-emqx` | Woow EMQX | 5.9.1 | 本機建置 | EMQX 5.x MQTT broker（企業級，內建 ngrok） |
| `woow-headscale` | Woow Headscale VPN | 0.1.0 | 本機建置 | 自架 Headscale + Headplane GUI |
| `woow-tailscale` | Woow Tailscale | 0.1.3 | 本機建置 | Tailscale / Headscale VPN 用戶端 |
| `woow-immich` | Woow Immich | 2.5.7 | 本機建置 | 自架相簿（Google Photos 替代） |
| `woow_lan_gateway` | Woow LAN Gateway | 0.1.7 | 本機建置（amd64） | 工廠註冊 LAN 的 fail-closed 公網 IPv4 閘道 |
| `woow-n8n` | Woow n8n | 2.43.6 | 預建映像 | AI/自動化 workflow |
| `woow-hermes` | Woow Hermes Agent | 0.1.14 | 預建映像（amd64） | Hermes Agent（NousResearch）：HA 側邊欄 dashboard + 聊天終端機，OpenAI 相容 API 與 Webhook 可經 Cloudflare Tunnel 對外 |
| `woow-nextcloud-office` | Woow Nextcloud Office | 0.2.3 | 預建映像（amd64） | Nextcloud + 內建 PostgreSQL／Redis／Collabora Online |
| `woow-nginxproxymanager` | Woow Nginx Proxy Manager | 2.12.4-v2 | 本機建置 | Nginx Proxy Manager 的 WOOWTECH 版（與社群版 slug 不同） |
| `woow_ha_code_server` | Woow Code Server | 0.1.6 | 預建映像 | code-server + pi coding agent + Claude Code + ACP 側邊欄（取代原 `vscode` 鏡像） |
| `woow_ha_pi_agent` | Woow HA Pi Agent | 0.15.21 | 預建映像 | pi-web + coding agent SDK + 影音管線 |
| `woow_ha_opendesign` | Woow HA OpenDesign | 0.2.15 | 預建映像 | Ingress-only BYOK 設計工作台 + PDF／圖片／PPTX 匯出 |
| `woow-omnigent` | Woow Omnigent | 0.1.16 | 預建映像 | Omnigent 編排伺服器 + 內建 Postgres（外部 runner 註冊制） |

### 🤖 MCP Server（WOOWTECH 自主開發）

把對應軟體的完整工具以 MCP（Streamable HTTP，Bearer token）提供給 AI client；所有工具與寫入預設開啟，HA 管理員可在 add-on 面板逐支停用工具或取消寫入。0.4.11 起 manifest 標為 `stage: stable`，商店不再顯示「實驗性」。圖示與所連接的軟體相同。來源與完整文件：[WOOWTECH/Woow_ha_mcp_addons](https://github.com/WOOWTECH/Woow_ha_mcp_addons)。
同一套 add-on 也在該 repo 自己的 store；兩個 store 的同名 add-on 在 HA 裡是不同的 add-on（slug 前綴不同，設定不互通），同一台 HA 只裝其中一個來源的。
下面 6 支只同步正式 Release，和其他來源 repo 一樣：升版的 PR 通過該 repo 的 `WOOW addon release` 檢查並合併後，自動發 `<slug>-v<版本>` 正式 Release，本 store 才會前進到該版本。原本的第 7 支 `woow_mcp_opendesign` 已於 2026-10-15 下架（見下方說明）。

| Slug | 名稱 | Ver | 安裝 | 用途 |
|---|---|---|---|---|
| `woow_mcp_n8n` | Woow n8n MCP Server | 0.4.11 | 預建映像（amd64） | n8n 的 MCP server |
| `woow_mcp_odoo` | Woow Odoo MCP Server | 0.4.11 | 預建映像（amd64） | Odoo 的 MCP server |
| `woow_mcp_hermes` | Woow Hermes MCP Server | 0.4.11 | 預建映像（amd64） | Hermes Agent 的 MCP server |
| `woow_mcp_emqx` | Woow EMQX MCP Server | 0.4.11 | 預建映像（amd64） | EMQX 的 MCP server |
| `woow_mcp_litellm` | Woow LiteLLM MCP Server | 0.4.11 | 預建映像（amd64） | LiteLLM（本 store 沒有 LiteLLM add-on，需自備） 的 MCP server |
| `woow_mcp_nextcloud` | Woow Nextcloud MCP Server | 0.4.11 | 預建映像（amd64） | Nextcloud（一個帳號的檔案、行事曆與任務） 的 MCP server |

### 🧩 HA Core 實例
| Slug | 名稱 | Ver | 安裝 | 用途 |
|---|---|---|---|---|
| `woow_ha_core_1..5` | Woowtech HA Core 1-5 | 2.3.0 | 本機建置 | 巢狀 HA Core 實例（每個獨立 onboarding，預設 port 8124-8128） |
| `apporo_ha_core_1..5` | Apporo HA Core 1-5 | 2.3.0 | 本機建置 | Apporo 品牌的巢狀 HA Core 實例。**與同編號的 `woow_ha_core_N` 預設使用相同 host port**，不要同時啟用，或先改其中一個的 port |
| `woow_ha_core` | Home Assistant Core (official image) | 2026.9.1-1 | 本機建置 | 獨立的官方 HA Core 2026.9.1，無品牌改動或預設設定；manifest 標為 **experimental** |

### 🪞 WOOWTECH 鏡像維護（防上游失聯）
| Slug | 名稱 | Ver | 安裝 | 上游 |
|---|---|---|---|---|
| `dnsmasq-dhcp` | Dnsmasq-DHCP | 5.1.3 | 預建映像 | [f18m/ha-addon-dnsmasq-dhcp](https://github.com/f18m/ha-addon-dnsmasq-dhcp) |
| `hamh` | Home-Assistant-Matter-Hub | 2.0.59 | 預建映像 | [riddix/home-assistant-matter-hub](https://github.com/riddix/home-assistant-matter-hub) |
| `frigate` | Frigate | 0.18.2 | 預建映像 | [blakeblackshear/frigate-hass-addons](https://github.com/blakeblackshear/frigate-hass-addons) |
| `jellyfin` | Jellyfin | 0.2.2 | 預建映像 | [hassio-addons/app-jellyfin](https://github.com/hassio-addons/app-jellyfin) |
| `music_assistant` | Music Assistant | 2.10.9 | 預建映像 | [music-assistant.io](https://music-assistant.io) |
| `local_audio` | Local Audio | 0.2.0 | 預建映像 | [music-assistant/local-audio-addon](https://github.com/music-assistant/local-audio-addon)；manifest 標為 **experimental** |
| `netease_cloud_music_api` | NetEase Cloud Music API | 0.1.1 | 本機建置 | [NeteaseCloudMusicApiEnhanced/api-enhanced](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced)（Music Assistant 用） |
| `ytm_po_token_generator` | YT Music PO Token Generator | 2.0.2 | 預建映像 | [Brainicism/bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) |
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

Hermes Paseo 的最新[安裝與首次 project 建立教學](https://github.com/WOOWTECH/hermes-paseo-plugin/blob/main/docs/install.zh-TW.md#home-assistant-add-on)及[HA 實機驗收報告](https://github.com/WOOWTECH/hermes-paseo-plugin/blob/main/docs/ha-acceptance-20261026.zh-TW.md)由插件來源 repo 維護。商店套件版本以 `woow-hermes/config.yaml` 與正式 Release 為準；支援 amd64。

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
  - 有修改：把每個改了版本的 addon 和**比對對象**相比。比對對象是該 addon 目前最新的正式 Release（tag 規則同上：`v<版本>` 或 `<slug>-v<版本>`；哪些算正式 Release、tag 怎麼對應、怎麼排序，和 Release 說明共用 `addon_sync.py` 的同一套規則，由 `upgrade_check.py comparison-target` 判斷），`ref_policy: main` 是 PR base 上這個 addon 目前的版本第一次出現的那個 commit（見下一點）；只有整個版本號都讀得懂的 tag（PEP 440，或 `-v<N>`、`-<N>` 重建後綴）才能當比對對象，`nightly`、`v9.0-test` 這類零散 tag 直接略過。**PR 的版本必須比比對對象新**，否則檢查失敗，訊息是「version … is not newer than …; raise the version」；同一個版本換個寫法（例如比對對象 `1.3`、PR 寫 `1.3.0`）也算沒有比較新，訊息會加上「(the same version, written differently)」。PR 的版本無法和比對對象排序時（例如 `1.0-test` 對 `1.0`）也失敗，訊息要你改用整個都讀得懂的版本號（PEP 440，或 `-v<N>` 重建後綴）。比對對象是 Release 時，它的 tag 和它的 `config.yaml` 都寫了版本，兩者用同一套排序比較（`v1.3` 和 `1.3.0` 算一致）；不一致或無法排序時檢查失敗，訊息是「the comparison target … is version X by its tag but Y by <config 路徑>; correct that Release…」，請修正那個 Release 讓 tag 和 config 一致，再重跑檢查。比對對象的 `config.yaml` 沒有 `version` 時，訊息是「the comparison target … has no version in <config 路徑>; correct that Release…」（`ref_policy: main` 則要你在預設分支的 config 補上版本），問題在比對對象，不是 PR 的版本。`config.yaml` 的版本一律照 Home Assistant Supervisor 的讀法（先讀 YAML 再轉成文字，`upgrade_check.py version`／`addon_sync.config_version`，PR 檢查各步驟和 `addon_sync.release` 共用）：沒加引號的 `version: 1.10` 是數字，讀成 `1.1`，使用者跑的就是 1.1。PR 的版本（以及要發 Release 的版本）讀出來必須和寫的字一樣，否則檢查失敗，訊息是「version 1.10 is read by YAML, and by Home Assistant Supervisor, as 1.1; quote it: version: "1.10"」，請把版本加上引號；`config.yaml` 沒有 `version` 也會失敗。Release 只從預設分支發，每個都標成 latest、發布也只送 `releases/latest`，所以在 1.3.0 之後發 1.2.5 是讓 1.3.0 的使用者降版，不是修舊線。`addon_sync.release` 也照同一條規則，不論有沒有 `upgrade-notes.yaml`，版本不比最新正式 Release 新就不發 Release。所以預設分支上的版本如果已經不比最新正式 Release 新、又沒有同版本的 Release（例如有人手動發了更高版本的 Release，或版本被改回較低的值），之後每次 push 到預設分支的 release run（`woow-addon-release.yml`；`Woow_ha_odoo` 是它自己的 `release.yml`）都會失敗，訊息是「version … is not newer than …」。修法：開一個升版 PR，把版本調到比最新正式 Release 新，合併後就會發 Release、恢復正常；不要刪掉較高版本的 Release 來繞過，那是使用者正在用的版本。PR 檢查和 Release 說明都只看（比對對象, 新版本] 的宣告。第一次發布的 addon 沒有比對對象，不做比對並在報告註明；`upgrade-notes.yaml` 有空的 `migration` 或 `reason` 時仍會擋下。
  - `ref_policy: main` 的比對對象（#129）：PR base 上這個 addon 目前的版本**第一次出現的那個 commit**。使用者裝的是這個版本，之後同版本的 commit 再改設定都算進比對，所以把破壞性變更（例如拿掉一個選項）放進一個沒升版的 PR，下一個升版 PR 仍會被擋下。做法：從 PR base 往回，用 GitHub API 列出動過 `config.yaml`（搬移中時也含 `previous_config`）的 commit，照 Supervisor 的讀法讀各 commit 的版本，找到版本不同或沒有 config 的前一個為止；版本從 config 建立後就沒改過時是建立 config 的 commit，PR base 沒有這個 config 時當新 addon。列 commit 或讀 config 時 API 失敗，檢查就失敗（訊息結尾「so the commit where the version first appeared is unknown; re-run this check」），不會退回 PR base。同版本的 commit 改了 `config.yaml` 時，`addon_sync.publish` 不會把它同步到 Store（「Runtime changed without an addon version bump」），所以這個比對不會比使用者手上的更鬆。commit 依 committer date 排序，前提是歷史是線性的（squash 或 rebase 合併）。
  - PR 的版本號、比對對象的 tag、比對對象 `config.yaml` 的版本號與映像含換行、tab 等控制字元時檢查直接失敗；其他來自 PR 或 Release 的文字印到 log 前都先跳脫，GitHub 不會把它當成工作流程指令。
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
  | `required-added` | 新增必填 key，而 `options` 沒有預設值（`null` 不算預設值）。新增的 map 一律算必填，子項全選填也一樣；`options` 給這個 map 預設值（`{}` 也算）就不算。子項照樣逐一比對 | schema 路徑 |
  | `arch-removed` | 拿掉一個 arch | arch，例如 `aarch64` |
  | `port-removed` | 拿掉一個 port，或改了容器端 port、通訊協定 | port，例如 `8069/tcp` |
  | `image-changed` | `image` 改變、新增或拿掉 | `image` |

  只寫進報告、不擋：預設值改變（`default-changed`）、只改主機端預設 port（`host-port-changed`）。不擋也不報告：範圍變寬、列舉加值、必填改選填、新增選填 key（map 不算，見 `required-added`）、新增有預設值的 key。
- **第 2 類 升級測試**（#137 啟動、#138 資料檢查、#144 在裝置上建置的 addon）：在 workflow 的 `runtime` job 執行，`compare` 等它跑完並把結果併入判定，必要檢查名稱不變。每個改了版本、有比對對象的 addon 都測，新舊兩個 amd64 映像依 addon 的種類取得（不推 PR tag 到 GHCR）：**有預先建置映像的 addon**，新映像由 repo 自己的 amd64 PR 建置，用 Store 的 [`addon-image`](.github/actions/addon-image/action.yml) 步驟 `docker save` 後交出（呼叫端傳 `image_artifact: upgrade-comparison-image-*`，`runtime` 不重建；沒傳的報告為「not run」並指向推廣的 #143），舊映像從 GHCR 拉比對對象的 amd64 映像；Store registry 核准 `scan_published_image` 的 provider（見第 4 類，#154）出貨的是 `config.yaml` 的 `image` 指到的已發布映像，不是 PR 建的，所以新映像也從映像 registry 拉：`image` 的 amd64、tag 是 PR 的版本號，呼叫端不傳 `image_artifact`；這個 tag 還沒發布（或 registry 連不到）時算 PR 的錯，該 addon 檢查失敗，訊息同第 4 類，其他 addon 照常測試；**在裝置上建置的 addon**（`config.yaml` 沒有 `image`）沒有映像可拉或交出，`runtime` 照 Supervisor 的方式（`build.yaml` 的 `build_from`、`args`，`Dockerfile.amd64` 或 `Dockerfile`；`upgrade_check.py build-args`）自己建兩個：先從 PR checkout 建新版（建不出來是 PR 的錯），再從比對對象的原始碼建舊版（有正式 Release 用其 tag，`ref_policy: main` 用 PR base 上該版本第一次出現的 commit，由 GitHub 的 tarball 下載，同一個比對對象只下載一次），呼叫端不需要傳 `image_artifact`；比對對象下載或重建不出來算比對對象失敗（見下方 #140）。兩邊各取一邊時（例如比對對象在裝置上建置、PR 改成預先建置）各照自己的方式。[`upgrade_runtime.py`](.addon-sync/upgrade_runtime.py) 先啟動比對對象、停掉，再用同一組資料目錄啟動新版本：`/data` 加上 `config.yaml` `map` 的每一項，各掛在該項的 `path`（沒寫用 Supervisor 的預設位置；`upgrade_check.py mounts`）。兩者都跑在模擬的 Supervisor 下（[`mock_supervisor.py`](.addon-sync/mock_supervisor.py)）：hassio bridge 網路 `172.30.32.0/23`、addon 在 `172.30.33.10`、Supervisor 在 `172.30.32.2`（主機名稱 `supervisor`、`hassio`）、假的 `SUPERVISOR_TOKEN`／`HASSIO_TOKEN`、`/data/options.json` 見下方「測試用的 options」，回應 `/addons/self/info`、`/info`、`/os/info`、`/core/info`、`/network/info` 等。`config.yaml` 寫 `host_network: true` 的版本（新舊各看自己的 `config.yaml`，#158）照 Supervisor 的方式跑在主機的網路 namespace（`docker --network host`），其中有 bridge gateway `172.30.32.1`（GitHub runner 上就是模擬網路的 docker bridge 位址）；addon 的位址是這個 gateway（同 Supervisor 的 `DockerAddon.ip_address`）：探測的 `[HOST]`、hook 的 `ADDON_URL`／`ADDON_HOST`、`/addons/self/info` 的 `ip_address` 都用 `172.30.32.1`，仍以 `supervisor`／`hassio` 連到模擬的 Supervisor。主機網路的其他效果（主機 port、主機上的其他服務）不模擬，`privileged` 不套用。`/addons/self/info` 的 `ingress_entry` 與 `ingress_url` 照 Supervisor 的方式給（#161）：有 ingress 時 `ingress_entry` 是 `/api/hassio_ingress/<token>`（沒有結尾斜線，不論 `config.yaml` 有沒有寫 `ingress_entry`），`ingress_url` 是它加上 `/` 再接上 `config.yaml` 的 `ingress_entry`（照字串相接，`ingress_entry: /` 會得到 `//`）；沒有 ingress 時兩個都是 `null`。token 每次升級測試產生一次（形式同 Supervisor 的 `secrets.token_urlsafe()`），新舊兩版用同一個，和 Supervisor 升級時沿用 token 一致。addon 目錄的 `upgrade-check/supervisor/` 可以用「API 路徑對應 JSON 檔」補上回應（#142）：檔案內容是回應的 `data`，路徑去掉 query 與結尾的 `/`，例如 `/services/mqtt` → `supervisor/services/mqtt.json`、`/addons/self/info` → `supervisor/addons/self/info.json`（`/addons/self`、`/addons/<slug>/…` 也讀 `addons/self/…`；每種 HTTP method 都一樣）；fixture 優先於框架的預設回應，但 `addons/self/info.json` 必須是物件，只覆蓋它寫到的 key（框架為每個版本寫的 version、options、ingress_port 等保留），`/supervisor/ping` 不能覆寫。`upgrade-check/supervisor/` 本身或其中的檔案不可以是指向 `upgrade-check/` 外的 symlink（工具錯誤）。兩者都沒有的路徑回 404，不能用的 fixture（不是合法 JSON，或 info 不是物件）回 500；報告依版本列出「未模擬的 Supervisor 呼叫」（每版最多 30 個路徑，次數多的在前）與不能用的 fixture（路徑、次數），以及 `config.yaml` `map` 中 Supervisor 會忽略的項目，這些都只是提示、不會讓測試失敗。「能啟動」從 Supervisor 的位址判斷（`upgrade_check.py startup-probe`）。先依序選**一種**探測方式：`watchdog` 回應成功（HTTP 小於 300，或 TCP port 接受連線）→ `ingress_port` 有回應（HTTP 小於 500）→ `webui` 的 port 有回應。選的是 `config.yaml` 有寫的第一種；它沒回應時不會改用下一種。`ingress_port: 0`（Supervisor 安裝時才從 62000–65500 指定 port）仍算 ingress：測試指定 port 62000，新舊版都在模擬 Supervisor 的 `/addons/self/info` 回報它，並探測這個 port。探測要在 300 秒內有回應；之後容器還要撐 60 秒（`stable_seconds`）沒退出、沒重啟。三種都沒寫時，只看這 60 秒。addon 目錄的 `upgrade-check/settings.yaml` 可以覆寫：`startup_timeout`、`stable_seconds`、`hook_timeout`（正整數秒）。比對對象或新版本起不來時檢查失敗並寫明原因與最後幾行 log。**測試用的 options（#157）：** 兩個版本的 `/data/options.json`（也是模擬 Supervisor `/addons/self/info` 的 `options`）由各自 `config.yaml` 的 `options` 預設值產生，再疊上 addon 目錄的 `upgrade-check/options.yaml`（PR 這邊的同一份，兩版共用；比照 Supervisor 合併使用者 options：mapping 逐 key 合併，其他值直接取代；只採用該版 schema 有的 key，巢狀 mapping 也一樣），最後去掉 null 值。之後 schema 中必填的密碼欄位（`password` 或 `password(min,max)`，沒有 `?`；包括巢狀 mapping，缺少的必填 mapping 會建立；不含 list 的項目）若仍缺少、為 null 或空字串，由框架產生隨機英數字，每次測試產生一次、兩版相同：只要有一個版本必填，就寫進每個保留這個欄位的版本（該版 schema 有這個 key，不論是 `password?` 或其他型別，或該版沒有 schema），取代該版自己的預設值，和真的升級沿用使用者的值一致；長度是 32 個字元，或收到這個值的各版本密碼長度範圍（含 `password?`）交集內最接近的長度（範圍沒有交集時寫明原因並無法執行，請在 `options.yaml` 給值）；hook 一律從 `$DATA_DIR_DATA/options.json` 讀取最終的值。repo 在 `options.yaml` 寫的值優先（只供測試，只出現在 CI 的臨時容器）。其他必填但仍為 null 或空的欄位維持原樣（null 的不寫進 `options.json`；真的 Supervisor 這時會拒絕啟動 addon，測試則交給 addon 自己判斷），需要時在 `options.yaml` 給值。`options.yaml` 必須是 `option: value` 的 mapping（空檔案等於沒有設定）；以下情況在任何容器啟動前以「could not run」寫明原因（只寫 key 或型別，不引用檔案內容）：YAML 格式錯誤、不是 mapping、是指向 `upgrade-check/` 外的 symlink、寫了兩版 schema 都沒有的 key（任何巢狀層級；Supervisor 會略過並警告，值永遠到不了 addon）、密碼欄位的值不是字串（Supervisor 的 password 型別只收字串；只要有一版的 schema 是密碼欄位就檢查，另一版沒有 schema 也一樣）。其他值不依 schema 檢查型別。報告與結果不印出密碼：產生的密碼與 `options.yaml` 給的密碼（密碼型別欄位的值；名稱含 pass、secret、token、api_key、private_key、credential 的欄位，不論型別，它的字串值也算；沒有 schema 的版本只看名稱。原樣與 JSON 跳脫後的樣子）在 hook 輸出與 log（截成最後幾行之前）、說明、原因與工具錯誤中都換成 `[password]`；addon 名稱與各版本的 image、version 不遮蔽，`config.yaml` 預設值裡的密碼是公開的、也不遮蔽。報告只列出 `options.yaml` 設定的 key 與產生密碼的欄位名稱；repo 的密碼短於 8 個字元、或出現在 addon 的 name、slug、image、version 中時，報告會警告（遮蔽會把 log 裡的這些字一起蓋掉），請改用只供測試的較長值。**資料檢查（#138）：** addon 目錄的 `upgrade-check/` 可放兩支可執行的 hook（任何有 `#!` 的語言）：`seed` 在比對對象啟動後執行一次、寫入資料，`verify` 在新版本啟動後執行、確認資料還在。hook 在模擬 Supervisor 的容器裡執行（`python:3.12-alpine`：python3、busybox 的 sh／wget），所以從 Supervisor 的位址連到 addon；repo 不自己 `docker run`。環境變數：`ADDON_URL`（依序取 webui 的 scheme 與 port → ingress port → `http://ADDON_HOST`；有 webui 時一律用 webui，即使也有 ingress，要連 ingress 請自己用 `ADDON_HOST` 組網址）、`ADDON_HOST`、`ADDON_IMAGE`、`ADDON_VERSION`、`PHASE`（`old`／`new`）、`REPORT_DIR`、`HOOK_STATE_DIR`（從 `seed` 留給 `verify`，不掛進 addon）、每個資料目錄的實際路徑 `DATA_DIR_<TYPE>`（`DATA_DIR_DATA` 是 `/data`，其餘是 `map` 的 type，例如 `DATA_DIR_ADDON_CONFIG`、`DATA_DIR_SHARE`）、模擬 Supervisor 的 `SUPERVISOR_URL` 與 `SUPERVISOR_TOKEN`。exit 0 為通過；可寫 `$REPORT_DIR/<hook>.json`：`{"checks":[{"name":"…","result":"pass|fail|skip","detail":"…"}]}`，有 `fail` 的項目或格式錯誤也算失敗。每項檢查列進 runtime 與 compare 的 step summary。`seed` 或 `verify` 失敗、或超過 `hook_timeout`（`settings.yaml`，預設 600 秒，涵蓋整個 `docker exec`）時檢查失敗並寫明原因。hook 結束前不能留下背景程序。hook 檔案不能是指到 `upgrade-check/` 以外的 symlink（只有這個目錄會被掛進去），`#!` 只能用 python3 或 busybox sh（沒有 bash），行尾要是 LF。只有 `verify` 真的執行了才算「已檢查資料」；沒有 `verify` 時報告與 step summary 寫明「只檢查啟動，沒有檢查資料」，在 `verify` 之前就失敗時寫明沒有檢查資料。**比對對象本身失敗（#140）：** 比對對象的映像拉不到（在裝置上建置的 addon 是重建不出來，#144）、起不來（包括 `docker run` 就失敗）、或 `seed` 失敗時，該 addon 的升版比對失敗並寫明原因，因為無法證明升級安全；workflow 的步驟用 `log.sh` 的 `target_failed` 寫下該 addon 的結果。真的無法做升級測試的 addon，由 Store registry 在該 addon（component）寫 `upgrade_comparison.skip_upgrade_test: "<原因與票號>"` 核准：第 2、3 類都不做，報告與 step summary 寫出 registry 的原因（`upgrade_check.py upgrade-test-skip`）。只有 registry 能決定，沒有呼叫端的 input；來源 repo 在 `upgrade-check/settings.yaml` 寫 `skip_upgrade_test`（只有非空字串算要求；`false`、`null`、空字串都不算）而 registry 沒有核准時檢查失敗，訊息說明要到 registry 核准（有核准時完全不讀這個檔案，它的文字不採用）。registry 的值格式錯誤（`upgrade_comparison` 不是 mapping、原因不是非空字串）時檢查失敗並寫明是哪個 addon 的 registry 項目。一個 addon 的比對對象映像拉不到時，其他 addon 照常測試，最後整個 job 失敗；只有映像本身的問題（找不到、拉不到、entrypoint 不能執行）算比對對象起不來，名稱或位址衝突、bind mount、daemon 等 runner 的問題是工具錯誤。目前核准的：woow_lan_gateway（#158，負責人決定永久跳過：升級測試會用主機網路執行它，但它還需要 `NET_ADMIN`、固定名稱的網卡 `enp2s0`／`enp1s0`、nftables 與主機已啟用的 IPv4 forwarding，runner 給不了，假網卡也測不到 NAT 與 fail-closed 行為；由 Enrollment LAN 上的實機驗證涵蓋，見母專案 `.out-of-scope/lan-gateway-upgrade-test-on-runner.md`）。woow-tailscale（#164，暫時：比對對象 v0.1.3 重建不了，它釘住的 `bind-tools`、`nginx` 版本 Alpine 已不提供；0.1.4 成為正式 Release 後移除）。等新映像 artifact 的方式和 SBOM 相同（`image_wait_minutes`，預設 40）。
- **第 3 類 回歸比對**（#139，和第 2 類在同一個升級測試裡執行）：addon 目錄的 `upgrade-check/` 可放第三支 hook `smoke`（介面與 `seed`／`verify` 相同，報告寫 `$REPORT_DIR/smoke.json`）。它在比對對象上跑一次（在 `seed` 之後，`seed` 通過才跑），在新版本上跑一次（在 `verify` 之後；第 2 類已經失敗時不跑，報告寫明 smoke 沒在新版本執行與原因，第 3 類整個未比對），所以兩次都看到 `seed` 寫入的資料。**`smoke` 只讀不改：** 它在 `seed` 與 `verify` 之間、用同一組資料目錄執行，不能改動或刪除 `seed` 寫入、`verify` 要讀回的資料（透過 addon 的 API 另建自己的資料可以）；它的 `HOOK_STATE_DIR` 是自己的目錄（從比對對象留到新版本），不是 `seed` 交給 `verify` 的那個。`smoke` 失敗本身不算失敗，而是依檢查的 `name` 逐項比對（規則是 `upgrade_check.py` 的 `regression()`，由 `upgrade_runtime.py` 呼叫；`upgrade_check.py regression --result <結果>.json` 可對結果重算）：比對對象 `pass`、新版本不是 `pass`（`fail`、`skip` 或報告裡沒有這項）→ 失敗；比對對象不是 `pass` → 只寫進報告（未比對）；只在新版本出現的檢查必須 `pass`（比對對象的 `smoke` 寫了能讀的報告就算，不論 exit code：有一項檢查失敗的 hook 會 exit 非 0，但報告仍列出每一項；比對對象的 `smoke` 沒寫報告或報告不能讀時，例如超時或寫報告前就當掉，才未比對）。檢查名稱 `(the hook)` 保留給 hook 本身，報告用了它就算格式錯誤。hook 本身的結果也算一項（`(the hook)`：exit 0 且報告能讀才算 `pass`；報告不能讀時，裡面的檢查一項都不比對），沒寫 JSON 時就只比這一項，也就是比 exit code：比對對象 0、新版本非 0 → 失敗；比對對象非 0 → 報告「未比對」。沒有 `smoke` 時第 3 類只比「能啟動」。有回歸時升版比對失敗並寫明是哪幾項；runtime 與 compare 的 step summary 列出每一項在比對對象與新版本的結果和比對結論。
- **第 4 類 漏洞比對**（只限有預先建置映像的 addon）：新映像由 repo 自己的 amd64 PR 建置，用 Store 的 [`addon-sbom`](.github/actions/addon-sbom/action.yml) 步驟交出 SBOM；舊映像從 GHCR 拉比對對象的 amd64 映像。兩邊用同一份 Grype DB 掃描（Grype、Syft 依 checksum 釘選）；任一邊的掃描結果沒寫出 DB（`descriptor.db.status` 的 `built` 與 `from`）或兩邊 DB 不同，檢查直接失敗。以（漏洞 ID, 套件）比對，**新映像才有、嚴重度 Critical 或 High、Grype `fix.state` 是 `fixed`** 的是「新增可修補漏洞」，沒宣告接受就擋下；同一組（漏洞 ID, 套件）Grype 列出多筆時，任一筆符合就算，報告的嚴重度與修補版本取自符合的那筆。舊映像就有的、沒有修補版本的、嚴重度不到 High 的只算進報告的數量。在裝置上建置的 addon 不做第 4 類，報告註明交由 #90。出貨的不是呼叫端 PR 建的映像、而是 `config.yaml` 的 `image` 指到的已發布映像時（knxd 出貨第三方 da-anda 映像 #147；mcp_addons 只在 `woow-disposable-builder` 建映像、`readiness` 檢查要求新版映像合併前已能從 GHCR 拉取 #148），Store registry 在該 provider 寫 `upgrade_comparison.scan_published_image`（核准的原因與票號，目前是 knxd #147 與 mcp_addons #148）：新舊版都從映像 registry（knxd 與 mcp_addons 都是 GHCR）拉 `image` 的 amd64 映像、tag 是各自的版本號，不等 SBOM artifact，呼叫端也不傳 `sbom_artifact`；PR 版本號的 tag 還沒發布時檢查失敗，訊息寫明這個映像還沒發布（第三方映像由上游發布，其他由 repo 自己發布映像）。它和 `skip_vulnerability_scan` 不能同時寫。呼叫端傳 `skip_vulnerability_scan: "<原因>"`（任何非空的文字都算，加引號，否則 ` #` 之後會被 YAML 當成註解）時，這次呼叫的所有 addon 都不做第 4 類；第 1 類照常比對。只有 Store registry 裡該 provider 有 `upgrade_comparison.skip_vulnerability_scan`（核准的原因與票號；目前沒有 provider 有，mcp_addons 原本的 #123 已由 #148 換成 `scan_published_image`）才能這樣傳，報告寫出的是 registry 裡核准的原因，不是呼叫端傳的文字；其他呼叫端傳了，檢查直接失敗。呼叫端不對建置 job 設 `needs:`：有版本變更時才等這次 run attempt 的 SBOM artifact，重跑請用 Re-run all jobs。
- **資料檢查期限**（第 2 類，#141）：有資料庫的 addon 在 Store registry 的該 addon（component）寫 `upgrade_comparison.data_check_due: "YYYY-MM-DD"`（UTC 日期），期限前要在 `upgrade-check/` 補上 `verify`（資料檢查最低標準見母專案 #90）。`compare` 的「Upgrade test result」對升級測試有跑的 addon（通過或失敗）判斷（`upgrade_check.py data-check-due`）：PR 的 `upgrade-check/verify` 存在時不看期限；沒有 `verify` 時，到期限當天（剩 0 天）為止都通過，step summary 寫「資料檢查期限 YYYY-MM-DD，剩 N 天」，期限隔天（UTC）起失敗，訊息說明期限已過、要補資料檢查。`data-check-due` 的 exit code：0 通過（包括沒有期限、有 `verify`）、3 期限已過、2 工具錯誤（例如 registry 格式錯誤）；workflow 只把 3 寫成「期限已過」，其他非 0 都是「無法判斷」。升級測試沒跑的 addon 只有兩種不判斷：沒有比對對象（第一次發布，沒有可升級的來源）、registry 核准跳過（`skip_upgrade_test`）；其他沒跑的原因（例如呼叫端沒傳 `image_artifact`，或 workflow 不認得的原因）一樣判斷，因為只有 registry 能決定，呼叫端的 input 不能免除期限：期限前 step summary 寫剩幾天，期限隔天起失敗，訊息另外說明升級測試沒跑的原因（沒傳 `image_artifact` 時：補 `verify`，並照 #143 傳 `image_artifact` 讓升級測試執行）；在裝置上建置的 addon 自 #144 起有升級測試，同樣適用。每個 PR 都會檢查該 repo 所有 addon 的 `data_check_due`（`upgrade_check.py components`），日期不是合法的 YYYY-MM-DD、或 `upgrade_comparison` 不是 mapping 時，即使升級測試沒跑也檢查失敗並寫明原因。期限是在 CI 執行當天（UTC）判斷，不是合併當天：期限前跑過、仍是綠燈的結果在期限後仍可能被合併。目前的期限：woow-n8n 2026-11-17；odoo18ce、woow-nextcloud-office 2026-12-08；woow-immich、woow-headscale 2026-12-29。
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
- **Release 說明**：發 Release 時，比對對象（一律是最新的正式 Release，新版本必須比它新；PR base 上目前版本第一次出現的 commit 只用在 `ref_policy: main` 的 PR 檢查）之後各版的宣告自動整理成「破壞性變更與遷移方式」「已接受的漏洞」兩段，放在 GitHub 自動產生的說明前面；共用的 `woow-addon-release.yml` 和 `Woow_ha_odoo` 的 `release.yml` 都這樣做。沒有宣告就不加；檔案格式錯誤時不發 Release。
- 判定規則與 `change` 名稱的權威說明在 [`.addon-sync/upgrade_check.py`](.addon-sync/upgrade_check.py) 開頭，`upgrade-notes.yaml` 的格式、版本排序與 Release 說明在 [`.addon-sync/addon_sync.py`](.addon-sync/addon_sync.py)（`REBUILD` 上方的說明）；兩者不一致時以程式為準，並修正本段。

### 同步流程

- 每個 App 目錄都從**對應的 WOOWTECH 個別 repo 單向同步**，不在本 repo 直接修改。唯一例外是側欄標題政策 `.github/scripts/sidebar_titles.py`。來源、路徑與政策的對照表在 [`.addon-sync/registry.json`](.addon-sync/registry.json)。
- 流程：
  0. 來源 repo 的 CI 通過後，由共用的 [`woow-addon-release.yml`](.github/workflows/woow-addon-release.yml) 替新的 addon 版本發正式 Release（單一 addon 的 repo tag 為 `v<版本>`，多個 addon 的 repo 為 `<slug>-v<版本>`）。[`Woow_ha_mcp_addons`](https://github.com/WOOWTECH/Woow_ha_mcp_addons) 的映像在建置 VM 建置，所以它的 CI 另外檢查映像已公開、而且要發的版本有建置 VM 的發佈紀錄。
  1. 個別 repo 的 `woow-addon-sync.yml` 確認必要 CI 與各架構映像都通過，再把固定 commit、雜湊與映像 digest 寫進該 repo 的 `woow-addon-sync` 分支。
  2. 本 repo 的 `sync-upstreams.yml` 依 registry 重新驗證：正式 Release、CI、預設分支、各架構映像、防降版、防亂序。
  3. 全部通過後才更新 App 目錄與 [`.addon-sync/catalog.json`](.addon-sync/catalog.json)。
  
  細節見 [`.addon-sync/README.md`](.addon-sync/README.md)。
- **只同步正式 Release**（ADR-0002）：43 個 App 裡 34 個（含 6 個 `woow_mcp_*`）。以下 9 個仍跟隨來源 repo 的預設分支，正在逐步切換：`apporo_ha_core_1..5`、`ha_mcp`、`ha_mcp_webhook_proxy`、`frigate`、`jellyfin`。每個來源的設定以 [`registry.json`](.addon-sync/registry.json) 的 `ref_policy` 為準。
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
