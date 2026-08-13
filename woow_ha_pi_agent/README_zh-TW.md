<p align="center">
  <img src="docs/screenshots/main_ui.png" alt="Woow HA Pi Agent — pi-web 工作區嵌入 Home Assistant" width="820"/>
</p>

<h1 align="center">Woow HA Pi Agent 附加元件</h1>

<p align="center">
  <b>將 <a href="https://github.com/agegr/pi-web">pi-web</a> 工作區打包成 Home Assistant Supervisor 附加元件，內建完整 <code>pitch_video</code> 影片產線。</b><br/>
  <sub>AI 服務（GLM · MiniMax · OpenAI · OpenRouter · Anthropic · DeepSeek · Groq · …）在 <b>pi-web UI 內</b> 設定 —— 不用改 HA 設定，不用重啟。</sub>
</p>

<p align="center">
  <a href="https://github.com/WOOWTECH/Woow_ha_pi_agent_add_on/releases"><img src="https://img.shields.io/github/v/release/WOOWTECH/Woow_ha_pi_agent_add_on?label=release&color=blue" alt="Release"/></a>
  <img src="https://img.shields.io/badge/HA%20add--on-Supervisor-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant Add-on"/>
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-lightgrey" alt="Architectures"/>
  <img src="https://img.shields.io/badge/base-debian--base%209.1.0-red?logo=debian&logoColor=white" alt="Base image"/>
  <img src="https://img.shields.io/badge/node-22.x-339933?logo=node.js&logoColor=white" alt="Node 22"/>
  <img src="https://img.shields.io/badge/pi--web-0.8.4-8A2BE2" alt="pi-web version"/>
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"/>
</p>

<p align="center">
  <a href="#快速上手">快速上手</a> ·
  <a href="#功能總覽">功能</a> ·
  <a href="#架構">架構</a> ·
  <a href="#畫面截圖">截圖</a> ·
  <a href="#設定">設定</a> ·
  <a href="#skills-技能系統">技能</a> ·
  <a href="#相關套件">套件</a> ·
  <a href="#安全性">安全</a> ·
  <a href="#疑難排解">排障</a> ·
  <a href="README.md">English</a>
</p>

---

## 概觀

**Woow HA Pi Agent** 是單一個 Home Assistant Supervisor 附加元件，內建 [`@agegr/pi-web`](https://www.npmjs.com/package/@agegr/pi-web) —— [pi coding agent](https://github.com/earendil-works/pi) 的瀏覽器工作區 —— 加上完整影片產線。安裝一次、開側欄圖示、在 pi-web 內加你要的 provider，全 HA 管理員即可在每個 session 自由挑模型。

- **零開埠安裝。** UI 走 HA Ingress，不需動 LAN 或防火牆。
- **BYOK 在 pi-web 內管理。** 從 Models 面板新增 provider —— 不用重啟附加元件、不用改 HA 設定。v0.13.0 之後，附加元件設定頁只剩容器層旋鈕（log level、時區、影片工具重置、環境變數逃生門）。
- **狀態隨升級保留。** Session、models.json、skill worktree、provider 金鑰全部落在 `/data/pi-agent/`，隨 HA 快照備份。
- **內建 skill store。** UI 直接從 GitHub URL、`owner/repo` 或本地路徑安裝技能（v0.12.0 已把 `git`+`openssh-client` 打進映像檔）。
- **影片產線。** ffmpeg + Playwright + edge-tts + rclone 全部預裝，可直接跑 `pitch_video` 工作流（v0.11.0）。設定頁有一鍵重下工具（v0.13.0）。
- **Watchdog。** Supervisor 探測 `/api/home`，卡死自動重啟。

## 快速上手

| 步驟 | 動作 |
|---:|---|
| 1 | **設定 → 附加元件 → 附加元件商店 → ⋮ → 儲存庫** |
| 2 | 加入 `https://github.com/WOOWTECH/Woow_ha_pi_agent_add_on`，安裝 **Woow HA Pi Agent** |
| 3 | **啟動** —— 設定頁保持預設即可，也可自行調 `log_level` / `timezone` |
| 4 | 從 HA 側欄的 **Pi Agent** 進入（僅管理員可見） → **Models** 面板 → 新增 provider 貼上金鑰 |

新安裝約 10 秒後就能在側欄看到入口。詳細設定選項說明請看 [`DOCS.md`](DOCS.md)。

## 功能總覽

### 服務目錄（在 pi-web 內管理）

附加元件不再釘服務清單 —— 全部從 pi-web **Models** 面板動態新增，持久化到 `/data/pi-agent/models.json`。團隊常並列比對的幾家：

| 服務 | API 模式 | 代表模型 | 為什麼 |
|---|---|---|---|
| **GLM-4.6**（智譜清言） | `openai-completions` + `thinkingFormat: "zai"` | `glm-4.6` | 中國區推理模型、支援 thinking blocks、價格具競爭力 |
| **MiniMax M3** | `openai-completions` + `thinkingFormat: "deepseek"` | `MiniMax-M2` / `abab7-chat-preview` | 超長上下文（最高 1M）、便宜草稿層 |
| **OpenAI** | `openai-completions` | `gpt-4o` / `gpt-4o-mini` | 基準線、支援影像輸入 |
| **OpenRouter** | `openai-completions` | `anthropic/claude-sonnet-4` · `openai/gpt-4o` · `deepseek/deepseek-chat` · `meta-llama/llama-3.3-70b-instruct` | 一把金鑰通用多家、便宜備援 |
| **Anthropic direct** | `anthropic` | `claude-opus-4-7` · `claude-sonnet-4-6` · `claude-haiku-4-5` | 原生 thinking blocks + `cache_control`（走 OpenRouter 會遺失兩者） |
| **DeepSeek direct** | `openai-completions` | `deepseek-chat` · `deepseek-reasoner`（R1） | 比 OpenRouter 便宜；R1 原生 thinking tokens 完整 |
| **Groq** | `openai-completions` | `llama-3.3-70b-versatile` · `kimi-k2-instruct` | LPU 服務（約 500 tok/s）、便宜快速草稿層 |

用 Models 面板的 **Test** 按鈕驗證每家新加的 provider —— v0.13.0 起附加元件已移除開機自檢（連 api_key 選項一起拿掉）。

### 執行與運維

- **In-process SDK。** `pi-web` 直接 import `@earendil-works/pi-coding-agent`，單一 Node 行程處理 UI + 推理。
- **HA Ingress + 側欄自動啟用。** 不公開任何 port；首次開機自動 POST Supervisor API 開啟側欄圖示（v0.8.0 修正）。
- **s6-overlay supervisor。** `nginx`（前端）+ `pi-web`（後端）+ `video-tools-init`（oneshot）。
- **Models 在 pi-web 內管理。** `/data/pi-agent/models.json` 由 pi-web UI 直接寫入，新增／改名／換金鑰都不用重啟附加元件。
- **Worktree 永續化。** `HOME=/data/pi-agent/home`，`pi-cwd-*/` 與已安裝的 skill 都能撐過映像檔升級（v0.10.0）。
- **冷備份策略。** `backup_exclude` 排除可重建的 cache（`playwright-cache/`、`venv/`、`**/clips/**`、`**/segments/**`），快照保持精簡；`rclone.conf` 留在快照內，還原後 Google Drive token 仍可用。
- **影片工具可自癒。** `reset_video_tools` 開關會在下次開機清掉 Python venv + Playwright cache，執行完自動透過 Supervisor API 撥回 `false` —— 不會卡在每次開機重下的迴圈（v0.13.0）。

## 架構

### 執行拓撲

```mermaid
flowchart LR
    Browser["瀏覽器<br/>(HA 管理員)"] -->|HTTPS + HA cookie| HA["Home Assistant<br/>Core + Supervisor"]
    HA -->|Ingress proxy<br/>X-Ingress-Path| Nginx["nginx (30142)<br/>sub_filter 重寫"]
    Nginx -->|Host: localhost| PiWeb["pi-web (Next.js 16)<br/>Node 22 · port 30141"]
    PiWeb -->|in-process SDK| Agent["@earendil-works/<br/>pi-coding-agent"]
    Agent -->|BYOK HTTPS| GLM[(GLM-4.6)]
    Agent --> Claude[(Anthropic)]
    Agent --> OAI[(OpenAI)]
    Agent --> OR[(OpenRouter)]
    Agent --> DS[(DeepSeek)]
    Agent --> Groq[(Groq LPU)]
    Agent --> MM[(MiniMax)]
    PiWeb -.持久狀態.-> Data["/data/pi-agent/<br/>sessions · models.json ·<br/>home/pi-cwd-* · skills/"]
```

**為什麼把 nginx 擺在 pi-web 前面：** 上游會出絕對路徑資產（`/_next/...`、`/api/...`、`/manifest.webmanifest`、`/icons/*`），而 HA Ingress 每個安裝都會把 URL 前綴改掉。nginx 層透過 `sub_filter` 位元組級重寫，再加上塞進 `</head>` 的 JS shim，把 `fetch`、`EventSource`、`XMLHttpRequest`、`history.pushState/replaceState`、`Element.setAttribute` 以及屬性 setter（`href`/`src`）通通包起來 —— React 的 DOM 寫入、RSC prefetch、`next/font` runtime 注入、`router.push('/')` 全部會走進 ingress 前綴，不會漏到 HA Core。`X-Ingress-Path` header 在進 body-rewrite 前會先過白名單驗證（`^/api/hassio_ingress/[A-Za-z0-9_-]{16,128}$`），防止上游 proxy 設定錯誤讓 client 塑形 header（v0.7.0 收斂的 CVE 類）。

### Skill 安裝流程（v0.12.0）

```mermaid
sequenceDiagram
    autonumber
    participant U as HA 管理員 瀏覽器
    participant W as pi-web Skills modal
    participant S as skills CLI 1.5.21
    participant G as git 或 ssh
    participant D as /data/pi-agent/skills/
    U->>W: 貼上 GitHub URL、owner-repo 或本地路徑
    W->>S: spawn npx skills add TARGET
    alt GitHub 或 owner-repo
        S->>G: git clone 透過 simple-git
        G-->>S: repo 內容
        S->>G: fallback ssh -o BatchMode=yes 若 HTTPS 認證失敗
    else 本地路徑
        S->>D: 以 node-tar 複製
    end
    S->>D: 在 skills/NAME/ 寫入 SKILL.md 與資產
    S-->>W: exit 0
    W-->>U: modal 刷新並列出 skill
    Note over W,D: 下一個 session 的 system prompt 會抓到 available_skills block
```

**為什麼要在 base image 裡帶 `git` + `openssh-client`：** `skills` CLI 對每一種 repo 安裝路徑（Skills modal 的 Search 按鈕、`owner/repo` 縮寫、`skills.sh` 內指向 repo 的條目）都會透過 `simple-git` 呼叫 `git clone`。少了 `git` 會讓 99% 的安裝失敗（`spawn git ENOENT` —— 就是 v0.12.0 上線的那個事件）。`openssh-client` 讓 CLI 對私有 repo 的 `ssh -o BatchMode=yes` 重試路徑生效。`gh` 刻意不裝（20 MB+，只在被吞掉的 `gh auth token` fallback 用得到）。

### s6-overlay 開機序列

```mermaid
flowchart TD
    Start(["容器啟動"]) --> S6["s6-overlay init<br/>（先跑 oneshots）"]
    S6 --> Init["video-tools-init<br/>（oneshot）"]
    Init -->|sentinel 已存在| Skip["exit &lt;100ms"]
    Init -->|首次開機| Bootstrap["mkdir /data/pi-agent<br/>python -m venv → pip install<br/>playwright install chromium"]
    Bootstrap --> Sentinel["touch .video-tools-installed"]
    Skip --> Longrun["長駐服務"]
    Sentinel --> Longrun
    Longrun --> Nginx["nginx service<br/>（port 30142）"]
    Longrun --> PiWeb["pi-web service<br/>exec 2>&amp;1<br/>套用 log_level / TZ<br/>reset_video_tools（一次性）<br/>export env_vars<br/>POST ingress_panel=true<br/>exec pi-web"]
    Nginx --> Ready(["watchdog OK<br/>UI 上線"])
    PiWeb --> Ready
```

完整架構寫在：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。逐檔部屬紀錄：[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)。k3s 版本設計藍圖：[`docs/K3S_BLUEPRINT.md`](docs/K3S_BLUEPRINT.md)。

## 畫面截圖

以下都是從 WoowTech HA（`woowtech-ha.woowtech.io`）實機抓的畫面。

### Home Assistant 整合

| ![HA 側欄](docs/screenshots/ha_sidebar.png) | ![HA 附加元件資訊](docs/screenshots/ha_addon_info.png) |
|:---:|:---:|
| **側欄圖示（僅管理員）。** `panel_admin: true` 鎖住這個入口，每次開機透過 Supervisor API 自動啟用 —— 新安裝不必去找「顯示於側欄」開關。 | **附加元件 Info 頁。** 顯示版本、主機名稱、「Open Web UI」按鈕（Ingress 路由）以及標準 Supervisor 控制項。 |
| ![HA 附加元件設定](docs/screenshots/ha_addon_config.png) | ![HA 附加元件日誌](docs/screenshots/ha_addon_logs.png) |
| **設定頁（v0.13.0）。** 只留容器層旋鈕：`log_level` 單選、`timezone`（IANA）、`reset_video_tools` 一次性開關、`env_vars` 巢狀清單。AI provider 金鑰改到 pi-web Models 面板管理。 | **Logs 頁。** bashio 與 pi-web（Next.js pino）日誌交錯輸出；設定頁的 `LOG_LEVEL` 同時控制兩者的詳細度。 |

### pi-web 工作區

| ![主 UI](docs/screenshots/main_ui.png) | ![Session 檢視](docs/screenshots/pi_web_session.png) |
|:---:|:---:|
| **主工作區。** 新 session 撰寫框、模型下拉、模式選擇 —— 全部嵌在 HA iframe 內，沒有任何看得見的 ingress 管線。 | **Session 檢視。** 推理逐字稿、tool-call 區塊、inline diff 的呈現和獨立 pi-web 一模一樣。 |
| ![Skills modal](docs/screenshots/skills_modal.png) | ![Models 面板](docs/screenshots/models_panel.png) |
| **Skills modal。** 從 GitHub URL、`owner/repo` 或本地路徑加入 —— v0.12.0 的修正（`git`+`openssh-client` 進 image）解鎖了所有 repo 型安裝路徑。 | **Models 面板。** 即時編輯 `/data/pi-agent/models.json` —— 新增 provider、改模型名稱、調 `contextWindow`/`maxTokens` 都不用重啟附加元件。 |

| ![含 skills 的 system prompt](docs/screenshots/system_prompt_skills.png) |
|:---:|
| **`<available_skills>` block 出現在 system prompt。** Skill 探測在 session 開始時發生 —— `/data/pi-agent/skills/` 下每個 `SKILL.md` 的 `description` frontmatter 都會被塞進去，讓模型知道什麼情境該叫什麼 skill。撰寫 description 時請用命令式的「Use when…」句型。 |

## 設定

附加元件設定頁只有 **容器層旋鈕**（v0.13.0）。所有 AI 相關設定改到 pi-web Models 面板。

| 選項 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `log_level` | `error` \| `warn` \| `info` \| `debug` | `info` | 同時控制 bashio（啟動 / init）與 pi-web（Next.js pino logger）的輸出詳細度。排查影片管線或 Playwright 問題時切 `debug`；要清靜切 `warn` |
| `timezone` | 字串（可空） | 空 = UTC | IANA 名稱（例如 `Asia/Taipei`、`America/New_York`）。會寫 `/etc/timezone`、symlink `/etc/localtime`、export `TZ`（Node.js 讀的是 env 不是檔）。影響 addon 日誌時戳、session 記錄檔名、影片管線 SRT 字幕時序 |
| `reset_video_tools` | bool | `false` | 一次性：下次開機清 `venv` + `playwright-cache` + sentinel，強制 `video-tools-init` 重下約 720MB 工具。**執行完自動透過 Supervisor API 撥回 `false`** —— 不用怕忘了手動關 |
| `env_vars` | `{name, value}` 清單 | `[]` | 進階逃生門 —— 每一筆會變成 `KEY=VALUE` 塞進 pi-web 行程（proxy 設定、provider baseURL 覆寫、Playwright 下載鏡像等）。`name` 必須符合 `^[A-Za-z_][A-Za-z0-9_]*$`，否則會跳過並在 log 留警告。**不要**在這裡放 AI provider 金鑰 |

### AI provider 金鑰放在哪

v0.13.0 起附加元件不再保留任何 provider API 金鑰。改到 **Pi Agent**（側欄）→ **Models** 面板管理 —— pi-web 擁有 `/data/pi-agent/models.json` 與自己的金鑰儲存，金鑰隨附加元件升級保留，也被 HA 快照包含。

[`examples/models/`](examples/models/) 只保留設定檔形狀的文件範例，**不要**直接複製到 `/data/pi-agent/`。請透過 Models 面板加 provider，讓 pi-web 的寫入路徑保持權威：
- [`glm-only.json`](examples/models/glm-only.json) —— 最小的 GLM-4.6（附 `thinkingFormat: "zai"`）
- [`multi-provider.json`](examples/models/multi-provider.json) —— 完整 5 家 provider 版型

## Skills 技能系統

Skill 預設為 user-scope —— `PI_CODING_AGENT_DIR/skills/` 下每個資料夾一個 skill（附加元件把這個路徑釘在 `/data/pi-agent/skills/`，讓 skill 撐過映像檔升級）。

```
/data/pi-agent/skills/hello-world/
├── SKILL.md            ← 必要，frontmatter 決定被探測到
└── scripts/greet.sh    ← 從 SKILL.md 引用
```

三種安裝路徑，都能從 **pi-web → Skills → Add skill** 走到：

1. **GitHub URL** —— `https://github.com/owner/repo`（支援 branch 與子路徑）
2. **`owner/repo` 縮寫** —— 展開等同上面
3. **本地路徑** —— 從附加元件的可寫掛載中複製

最小範例 skill 放在 [`examples/skills/hello-world/`](examples/skills/hello-world/)。把整個資料夾丟進 `/data/pi-agent/skills/hello-world/`（或用 pi-web Add-skill 的本地路徑選項），下一個 session 的 `<available_skills>` block 就會看到它。

寫 `description` 時請用命令式的「Use when…」句型 —— 那就是 pi 模型會看到的原字串。

## 相關套件

執行時期由以下套件組成（全部包在 image 內）：

| 套件 | 版本 | 角色 |
|---|---|---|
| [`@agegr/pi-web`](https://www.npmjs.com/package/@agegr/pi-web) | `0.8.4`（釘死） | Next.js 16 瀏覽器工作區 —— 走 nginx 從 port 30141 對外 |
| [`@earendil-works/pi-coding-agent`](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) | transitive | pi SDK —— pi-web 直接 in-process import，沒有獨立 daemon |
| [`skills`](https://www.npmjs.com/package/skills) | `1.5.21` | Add-skill 用的 CLI；會 shell 出 `git` / `ssh` / `gh` |
| `simple-git` | 隨 `skills` | 包裝 `git clone` 給 repo 型安裝 |
| `node-tar` | 隨 `skills` | tarball 型安裝的解壓 |
| Node.js | `22.x`（nodesource） | Runtime —— pi-web 需 ≥22.19.0 |
| nginx | Debian bookworm | Ingress 前端；sub_filter 重寫；白名單驗 `X-Ingress-Path` |
| ffmpeg + ffprobe | Debian bookworm | 影片產線（v0.11.0）—— segment、xfade、字幕燒錄 |
| Chromium runtime `.so` set | Debian bookworm | Playwright 用的瀏覽器（實際 binary 落在 `/data/pi-agent/playwright-cache/`） |
| edge-tts / pyyaml / mutagen | Python venv | `pitch_video` 用的 TTS 與 timeline 生成 |
| rclone | 取自 `downloads.rclone.org` 的當代 .deb | Google Drive 上傳 |
| s6-overlay | 隨 `hassio-addons/debian-base:9.1.0` | 服務 supervisor |

**釘版本的理由。** `@agegr/pi-web` 釘死（非 `@latest`），因為上游丟了 40+ 條硬編的 `/api/*` 路由與絕對路徑資產，nginx shim 完全靠這些形狀運作。上游若重構 `_next` chunk 名、RSC prefetch 形狀、或新增 `/api/*` 路由，都可能讓 shim 在無 code change 的情況下悄悄壞掉。要升級請人工做完 e2e 驗證再 bump。

### 容器映像

Multi-arch 映像由 [`.github/workflows/build.yml`](.github/workflows/build.yml) 建置後推到 GHCR：

- `ghcr.io/woowtech/woow-ha-pi-agent-amd64:<version>`
- `ghcr.io/woowtech/woow-ha-pi-agent-aarch64:<version>`

Base：`ghcr.io/hassio-addons/debian-base:9.1.0`。

## 安全性

| 層 | 保證 | Trust boundary |
|---|---|---|
| HA Ingress | 只有經 HA 驗證的使用者才能打到 `/api/hassio_ingress/<token>/*` | HA session cookie |
| 側欄圖示 | 僅管理員（`panel_admin: true`） | HA admin 角色 |
| `X-Ingress-Path` | 進 body-rewrite 前先過白名單（`^/api/hassio_ingress/[A-Za-z0-9_-]{16,128}$`） | 對抗上游 proxy 設定錯誤的縱深防禦 |
| API 金鑰 | 存在 pi-web 內（`/data/pi-agent/` 底下，被 HA 快照涵蓋）。v0.13.0 起附加元件 `options.json` 不再保留任何 AI 金鑰 | HA 主機檔案系統 |
| `env_vars` 逃生門 | 值會原字串塞進 pi-web 行程，**內容不驗證**。只有 `name` 有 regex 驗證 | 視同 `/data/options.json` —— 不要放你不敢丟進 `/data/options.json` 的秘密 |
| pi-web 應用層驗證 | **沒有。** 存取控制交給 HA。 | 有 HA admin 權限 = 完整 pi-web 權限 |
| `rclone.conf` | 留在 HA 快照內（跟 cache 不同），還原後 Drive token 仍可用 | HA 備份加密 |

若你需要 pi-web 自己的使用者級驗證，請在 HA 前面掛 auth-proxy —— 不要試著在 pi-web 內加 auth（ingress 層在 pi-web 看到 header 之前就把它們剝掉了）。

## 測試

- **pi-web 內的 provider Test 按鈕** —— 用 Models 面板隨時對任一 provider 發探測（v0.13.0 取代原本的開機自檢）。
- **HA Supervisor watchdog** —— 週期性探測 `http://[HOST]:[PORT:30142]/api/home`，卡死自動重啟。
- **End-to-end 驗證節奏。** 每個 tag 出前跑：(a) 全新安裝 → 側欄圖示可見 → 在 pi-web 內加 provider → 第一次聊天成功；(b) Skills → 從 GitHub URL 加 skill → skill 出現在 `<available_skills>`；(c) `pitch_video` dry-run 過 `python video/verify.py`。錄下來的 fixture 放在 [`tests/`](tests/)。

## 疑難排解

| 症狀 | 原因 / 修法 |
|---|---|
| 升級後設定頁沒有 api_key 欄位 | 這是預期行為 —— v0.13.0 把金鑰搬進 pi-web。從側欄圖示 → **Models** 面板管理 provider |
| UI 上線但每次聊天都 `401` | provider 金鑰錯了。打開 pi-web **Models** 面板 → 編輯該 provider → 貼新金鑰 → 按 **Test**。不用重啟附加元件 |
| 聊天返回 `402` / `429` | 驗證成功但沒額度 / 被限流。儲值或從 Models 下拉切另一家 |
| 「Open Web UI」按鈕 404 | `ha core restart`；ingress token 偶爾需要 Supervisor 重新登錄 panel |
| iframe 空白、network 顯示 `/_next/...` 404 | nginx sub_filter 或 shim 出問題。`ha addons logs b9cf5676_woow_ha_pi_agent` 抓 nginx error；確認 request 上有 `X-Ingress-Path` |
| 全新安裝找不到側欄圖示 | 從 Info 頁手動切「顯示於側欄」開關（慢速 Supervisor 上，那個 POST 偶爾會 race） |
| Skills → Add 失敗 `spawn git ENOENT` | v0.12.0 之前的 image。升到 ≥0.12.0 —— `git` + `openssh-client` 現在都在 image 裡 |
| 附加元件升級後 worktree 不見 | v0.10.0 之後不該發生。若從 ≤v0.9.1 升上來，舊 worktree 原本在 ephemeral rootfs —— 這次請在 `HOME=/data/pi-agent/home` 底下重建 |
| 影片產線跑到一半失敗 | 設定頁把 `reset_video_tools` 切成 `true` → 重啟附加元件 → `video-tools-init` 會重下 venv + Chromium（會自動撥回 off） |
| 日誌時戳時區不對 | 設定頁把 `timezone` 設成 `Asia/Taipei`（或你的 IANA 名稱），重啟附加元件 |

完整排障清單看 [`DOCS.md`](DOCS.md#troubleshooting)。

## 開發

### 目錄

```
Woow_ha_pi_agent_add_on/
├── config.yaml              附加元件 manifest —— arch、ingress、watchdog、schema
├── build.yaml               Multi-arch build args
├── Dockerfile               Debian base → Node 22 → ffmpeg/rclone → pi-web 釘版
├── DOCS.md                  HA 附加元件 info 頁顯示的使用者文件
├── CHANGELOG.md             每個 release，含 rationale（0.1.0 → 0.13.0）
├── translations/            HA 附加元件 UI 翻譯（en、zh-tw）
├── README.md                英文版
├── README_zh-TW.md          本檔
├── repository.yaml          HA add-on 儲存庫 manifest
├── rootfs/                  s6-overlay 服務樹 + nginx conf + init 腳本
│   ├── etc/s6-overlay/
│   │   ├── s6-rc.d/pi-web/run
│   │   ├── s6-rc.d/nginx/run
│   │   └── scripts/video-tools-init
│   └── etc/nginx/           nginx.conf + sub_filter 規則 + 注入 shim
├── examples/
│   ├── ha/panel_iframe.yaml       側欄 pin 的 YAML 設定
│   ├── models/glm-only.json       最小單一 provider 版
│   ├── models/multi-provider.json 完整 5 家 provider 版
│   └── skills/hello-world/        參考 skill 樣板
├── docs/
│   ├── ARCHITECTURE.md      深度解析 —— 行程模型、ingress shim、備份
│   └── screenshots/         README 與 docs 用的 PNG
├── tests/                   Boot / self-check / ingress smoke test
└── .github/workflows/build.yml    Multi-arch GHCR publish
```

### 本機建置

```bash
docker buildx build \
  --build-arg BUILD_FROM=ghcr.io/hassio-addons/debian-base-amd64:9.1.0 \
  --build-arg BUILD_ARCH=amd64 \
  --build-arg BUILD_VERSION=0.13.0-dev \
  -t local/woow-ha-pi-agent-amd64:0.13.0-dev .
```

### 升 pi-web

編輯 `Dockerfile`：

```dockerfile
ARG PI_WEB_VERSION=0.8.4   # ← 改這行
```

然後跑完整 e2e 再打 tag —— shim 依賴上游確切的 asset 形狀。

## 支援

- **Issue / feature request** —— [github.com/WOOWTECH/Woow_ha_pi_agent_add_on/issues](https://github.com/WOOWTECH/Woow_ha_pi_agent_add_on/issues)
- **上游 pi-web** —— [github.com/agegr/pi-web](https://github.com/agegr/pi-web)
- **上游 pi coding agent** —— [github.com/earendil-works/pi](https://github.com/earendil-works/pi)
- **Skills CLI** —— [github.com/anthropics/skills](https://github.com/anthropics/skills)（上游 `skills` npm 套件）

## 授權

MIT © [WOOWTECH](https://github.com/WOOWTECH)。完整條款見 [`LICENSE`](LICENSE)。

打包的上游套件各自保留原授權（`@agegr/pi-web` MIT、`@earendil-works/pi-coding-agent` MIT、`skills` MIT、ffmpeg LGPL/GPL 依 build 而定、Chromium BSD、rclone MIT）。

---

<p align="center">
  <sub>由 <a href="https://github.com/WOOWTECH">WOOWTECH</a> 打造 · 內建 <a href="https://github.com/earendil-works/pi">pi</a> · 由 <a href="https://www.home-assistant.io/">Home Assistant</a> 承載</sub>
</p>
