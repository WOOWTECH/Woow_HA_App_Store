# Woow HA Pi Agent

## What it is

A single Home Assistant Supervisor add-on that installs [`@agegr/pi-web`](https://github.com/agegr/pi-web) — a browser workspace for the [`pi`](https://github.com/earendil-works/pi) coding agent — plus the full [`pitch_video`](#video-pipeline-v0110) pipeline (ffmpeg / Playwright / edge-tts / rclone).

AI providers (GLM, MiniMax, OpenAI, OpenRouter, Anthropic, DeepSeek, Groq, …) are configured **inside the pi-web UI** — open the Models panel, paste a key, done. No addon restart, no HA config edit.

pi-web imports `@earendil-works/pi-coding-agent` as an in-process SDK, so there is no separate agent daemon — one process handles both UI and inference.

## Installation capacity

Before selecting **Install** or **Update**, check the HAOS data disk and require
at least **10 GB free**. Downloading and unpacking the image needs temporary
space in addition to existing add-ons, backups and images. The 2026-10-26
Supervisor test filled the disk and failed when installing 0.15.0 with only
2.1 GB available. Recover capacity or expand storage before retrying; do not
treat the 10 GB threshold as a measurement of the installed image size.

Local source builds need more space for dependencies, build layers and caches.
Use the official GitHub image build workflow if the HAOS disk lacks that
capacity. Supervisor pulls the image before the add-on can start: runtime
checks cannot guard this earlier download. Perform the check before invoking
Supervisor's install/update operation.

## Configuration

The addon settings page holds **container-level knobs only**. Everything AI-related lives inside pi-web now.

| Option | Type | Default | Notes |
|---|---|---|---|
| `log_level` | `error` \| `warn` \| `info` \| `debug` | `info` | Applied to bashio (startup/init) AND exported as `LOG_LEVEL` for pi-web's Next.js pino logger. Switch to `debug` when troubleshooting video pipeline or Playwright issues; `warn` to silence chatty info messages. |
| `timezone` | string (optional) | empty = UTC | IANA name (e.g. `Asia/Taipei`, `America/New_York`). Writes `/etc/timezone` + symlinks `/etc/localtime` + exports `TZ` (Node.js reads `process.env.TZ`, not the file). Affects addon log timestamps, session record filenames, and video pipeline SRT cue timing. |
| `reset_video_tools` | bool | `false` | One-shot: on boot, wipes `/data/pi-agent/venv`, `/data/pi-agent/playwright-cache`, and the install sentinel, forcing `video-tools-init` to re-download the full 720MB tool set. **Auto-toggles back to `false` via Supervisor API after execution** so you don't get stuck in a redownload-every-restart loop. |
| `env_vars` | list of `{name, value}` | `[]` | Advanced escape hatch. Each entry becomes a `KEY=VALUE` export into the pi-web process (proxy config, provider base-URL overrides, Playwright download mirrors, etc.). `name` is validated against `^[A-Za-z_][A-Za-z0-9_]*$` — invalid names are skipped with a warning line in Logs rather than crashing the whole script. **Not** the place for AI provider keys — those live in the pi-web UI. |

### AI provider keys — migration from ≤v0.12.x

v0.13.0 removes the seven `*_api_key` addon options. If you had keys pasted there:

1. Upgrade the addon.
2. Open **Pi Agent** (sidebar) → **Models** panel.
3. Add each provider and paste its key. Keys are stored inside `/data/pi-agent/` (persistent, backed up by HA snapshots).
4. Removed values in your old `/data/options.json` are ignored — HA drops keys not present in the new schema on first save.

There is **no auto-import** from the old addon options — those values are only visible to the Supervisor, and pi-web has its own storage. The addon logs no longer show a per-provider self-check line either; use the Models panel's "Test" button in pi-web instead.

## Accessing the UI

pi-web is served through **HA Supervisor Ingress** at `/hassio/ingress/woow_ha_pi_agent` — no ports are published on the LAN. Two easy entry points:

- **Open Web UI** button on the add-on's Info tab
- **Pi Agent** entry in the HA sidebar (visible to admins only; controlled by `panel_admin: true` in `config.yaml`)

Because the URL rides on your existing Home Assistant hostname/port, it works transparently over HA's local network, Nabu Casa remote UI, or any reverse proxy already fronting HA. No `extra_allowed_hosts` / whitelist config is required — nginx rewrites the upstream `Host` header to `localhost` so pi-web's `isApiRequestAllowed()` always passes.

### HAOS virtual-machine networking

On the PaaS KubeVirt deployment, the HAOS VM uplink has MTU 1450 while HAOS's default `hassio` Docker bridge has MTU 1500. That mismatch can let DNS resolve while HTTPS traffic from an add-on stalls. The add-on therefore uses HAOS host networking for outbound traffic. Its nginx listener binds only the Supervisor bridge gateway `172.30.32.1:30142`, accepts only the Supervisor ingress peer `172.30.32.2`, and proxies to loopback-only pi-web on `127.0.0.1:30141`. Browser traffic still enters through authenticated Home Assistant Ingress; no LAN listener is opened.

The sidebar entry is enabled automatically on every boot via a Supervisor API POST — fresh installs get the sidebar tile without hunting for the "Show in sidebar" toggle.

## Watchdog

`config.yaml` declares `watchdog: http://[HOST]:[PORT:30142]/api/home`. HA Supervisor probes that URL periodically, and restarts the add-on if pi-web stops responding. The nginx front proxies `/api/home` to pi-web without auth so the Supervisor probe hits a live handler.

## Data locations

| Path | Contents | Persistent? |
|---|---|---|
| `/data/pi-agent/sessions/` | pi session `.jsonl` files (one per conversation) | Yes — per-addon, backed up by HA snapshots |
| `/data/pi-agent/models.json` | Provider + model registry (editable via pi-web UI) | Yes — user edits survive restarts |
| `/data/pi-agent/auth.json` | OAuth tokens for providers configured via `/login` | Yes |
| `/data/pi-agent/home/pi-cwd-*/` | Ephemeral worktrees created by the pi coding agent (via `HOME=$DATA_DIR/home`) | Yes — survives addon updates |

Before v0.10.0, `pi-cwd-*` worktrees landed on the container root filesystem and vanished on every image update. `HOME` is now redirected into `/data/pi-agent/home` so the pi coding agent's default workspaces persist alongside sessions.

## CJK filenames (v0.14.0)

Upstream `@earendil-works/pi-coding-agent` folds U+00A0, U+2000–200A, U+202F, U+205F and **U+3000 IDEOGRAPHIC SPACE** to an ASCII space on every read, write and edit, and builds its read fallback chain from the already-folded path. Untreated, that produces two silent failures:

- a write to `台灣　報告.txt` lands at `台灣 報告.txt`, while the success message is built from the path you asked for — *"Successfully wrote 10 bytes"* to a file that does not exist;
- two files differing only by space type **cross-read**: ask for `Q1　報告.txt` and you get the contents of `Q1 報告.txt`, with no error raised.

U+3000 is ordinary in Traditional Chinese and Japanese filenames, so this is data loss with a success message rather than an edge case.

Since v0.14.0 the image patches this at build time (`patches/fix-unicode-space-paths.mjs`). Folding becomes a **read-only fallback** — a path pasted with a non-breaking space from a web page still resolves — while writes always land exactly where you asked. The patch asserts every hunk it applies, so a future `PI_WEB_VERSION` bump fails the build rather than shipping an image that quietly lost the fix.

Still unfixed upstream as of pi-coding-agent 0.85.1.

## Video pipeline (v0.11.0+)

The addon ships every CLI the `pitch_video` workflow (TTS → capture → segments → xfade → SRT → burn → verify → Drive upload) needs. Split across two layers:

**Baked into the image** (survive addon restart automatically):

- `python3` + venv/pip
- `ffmpeg` / `ffprobe` (with `libass`, `libx264`, `aac`)
- `fonts-noto-cjk`, `fonts-noto-color-emoji`, `fontconfig` — CJK + emoji subtitle burn
- `rclone` (current .deb, not Debian's stale package)
- Chromium runtime shared libs (`libnss3`, `libatk-bridge2.0-0`, `libcups2`, `libxcomposite1`, `libxdamage1`, `libxrandr2`, `libgbm1`, `libpango-1.0-0`, `libcairo2`, `libasound2`, `libatspi2.0-0`)

**Downloaded to `/data/pi-agent/` on first boot** (persist across addon updates, ~720MB total):

- `/data/pi-agent/venv/` — Python venv with `playwright`, `edge-tts`, `pyyaml`, `mutagen`
- `/data/pi-agent/playwright-cache/` — Chromium browser binary (via `PLAYWRIGHT_BROWSERS_PATH`)

Bootstrap is handled by the `video-tools-init` s6-overlay oneshot, gated by the sentinel `/data/pi-agent/.video-tools-installed`. Cold-boot install runs once (may take 3-8 min on Raspberry Pi 4 / slow networks); subsequent boots exit in <100ms.

### First-run: configure rclone for Google Drive

The video pipeline's `push_drive.sh` uploads via `rclone`. The addon can't run `rclone config` non-interactively (OAuth needs a browser), so the token has to be minted once by the user:

```sh
# From the addon's Terminal tab (or `docker exec -it addon_woow_ha_pi_agent bash`):
rclone --config=/data/pi-agent/rclone/rclone.conf config
# Follow the prompts: n (new remote) → name it e.g. WOOWTECH → drive (Google Drive)
# → paste your client_id/secret (or use rclone's default) → autoconfig? y →
# a browser tab opens; sign in; paste the returned token back.
```

The `rclone.conf` file is **inside** the HA snapshot backup (unlike the venv and Chromium cache which are excluded), so restoring a snapshot restores your Drive token.

### Project layout

Place per-video project directories under `/data/pi-agent/projects/`:

```
/data/pi-agent/projects/pitch_video/
├── script.yaml
├── timeline.json
├── video/
│   ├── tts.py
│   ├── capture.py
│   ├── build_segments.sh
│   ├── concat_xfade.py
│   ├── build_srt.py
│   ├── build_final.sh
│   ├── verify.py
│   └── push_drive.sh
├── clips/          ← Playwright output (excluded from HA snapshot)
├── segments/       ← ffmpeg intermediate (excluded from HA snapshot)
└── final.mp4       ← included in snapshot
```

The `pi-web/run` script exports `PATH=/data/pi-agent/venv/bin:$PATH` + `PLAYWRIGHT_BROWSERS_PATH` + `RCLONE_CONFIG` before `exec pi-web`, so any shell the pi coding agent spawns to run `python3 video/tts.py` transparently picks up the venv python, the browser cache, and the rclone config.

### Retry a failed install

If `video-tools-init` fails mid-download (e.g. network blip) the pi-web UI still works, but the video pipeline steps will fail. To retry:

```sh
rm /data/pi-agent/.video-tools-installed
# Then restart the addon from the HA UI.
```

Logs from each retry show up in the addon Logs tab under the `video-tools-init` prefix.

### Env variables set for you

| Variable | Value | Used by |
|---|---|---|
| `PATH` (prefix) | `/data/pi-agent/venv/bin` | `python3`, `playwright`, `edge-tts` resolve to venv |
| `PLAYWRIGHT_BROWSERS_PATH` | `/data/pi-agent/playwright-cache` | Playwright locates its persistent Chromium |
| `RCLONE_CONFIG` | `/data/pi-agent/rclone/rclone.conf` | `rclone` uses the persistent OAuth token |

## Security notes

- pi-web has **no application-level authentication**. Access control is delegated to Home Assistant: only HA users can hit the ingress endpoint, and the sidebar tile is gated to admins via `panel_admin: true`.
- Provider API keys are stored **inside pi-web** under `/data/pi-agent/` (persistent, covered by HA snapshots). Neither the addon nor pi log the values. Since v0.13.0 the addon `options.json` no longer holds any AI keys — rotate them in the pi-web Models panel.
- The `env_vars` escape hatch is unvalidated *content-wise* — anything you set becomes a process env var. Do not paste secrets you would not otherwise trust in `/data/options.json`; that file lives on the HA host disk and is snapshotted with backups.
- The nginx `X-Ingress-Path` header is whitelist-validated against `^/api/hassio_ingress/[A-Za-z0-9_-]{16,128}$` before it can reach any `sub_filter` body-rewrite or the shim's `window.__INGRESS_PATH__` literal — defense-in-depth against a misconfigured upstream proxy letting the client shape the header.
- **The browser terminal (v0.14.0) is a root shell in the add-on container**, reachable from the UI at `POST /api/terminal`. This is not a new trust boundary: the agent's `bash` tool has always run arbitrary commands in the same container with the same privileges, so anyone who could open a chat could already do everything the terminal allows. What changed is that it is now direct rather than model-mediated. HA login plus `panel_admin: true` remain the controls. pi-web 0.12.0 includes the upstream password-bypass fix; its `PI_WEB_PASSWORD` Basic Auth is deliberately not set — a second password in front of an already-authenticated Ingress endpoint is friction without a matching gain.

## Troubleshooting

- **UI loads but chat returns 401** — API key wrong. Open the **Models** panel inside pi-web, edit the failing provider, paste a fresh key, and hit **Test**. No addon restart needed. (Reminder: as of v0.13.0, keys live inside pi-web, **not** in the addon Configuration tab.)
- **Chat returns 402 / 429** — auth OK but out of credits / rate-limited. Refill the provider account or switch to another provider from the Models dropdown.
- **"Open Web UI" button does nothing / 404 from ingress** — reload HA (`ha core restart`); the ingress token is minted at add-on start and occasionally needs the Supervisor to re-register the panel.
- **Assets 404 under ingress prefix (blank page, network tab shows `/_next/...` 404s)** — should be handled by the nginx sub_filter wrapper + injected `</head>` shim (fetch / EventSource / XHR / history / setAttribute / property-setter interception). Check `ha addons logs b9cf5676_woow_ha_pi_agent` for nginx errors; look for a request path that does not start with `X-Ingress-Path`, which means Supervisor didn't inject the header.
- **Sidebar tile missing** — the Supervisor API POST during boot occasionally fails on slow supervisors. Toggle "Show in sidebar" manually on the add-on's Info tab.
- **Worktree disappeared after addon update** — should not happen since v0.10.0 (`HOME=/data/pi-agent/home`). If you upgraded from ≤v0.9.1, pre-existing worktrees were on the ephemeral rootfs and did not carry over — recreate them under `HOME` this time.


## Omnigent

映像已包含固定的 `pi-omnigent-plugin v0.3.30`、Python 3.12 與 Omnigent SDK 0.16.0。首次啟動自動註冊插件，不建立設定對話；連線綁定資訊只在 **Settings → Omnigent** 輸入。

1. 開啟 HA 側邊欄的 Pi Agent，進入 **Settings → Omnigent**（緊接 MCP；手機從設定下拉選單選取）。原生設定分頁會開啟受 HA ingress 保護的設定表單。
2. 每次全新設定都需輸入 Server URL、帳號及密碼；不內建預設 server、不沿用另一容器的登入。密碼欄位遮罩，送出／離開頁面後清空，不存於對話。
3. 登入後查看目前已安裝引擎與模型。缺少供應商授權時，在同一 addon 的終端完成 Claude Code／Codex 官方登入，或在 Pi Web Models 設定 Pi 模型。
4. 選擇引擎及模型後按 **驗證實際對話**。此動作才會建立測試對話並使用模型額度；全部已安裝引擎實際回覆並停止測試後才顯示 ready。
5. 按 **開啟 Omnigent**，在服務端選擇主機、引擎、模型與模組進行一般對話。取消連線只影響此 addon；既有歷史對話保留。

主機離線時（例如 host 程序因記憶體不足結束），設定頁會顯示 **重新連線**：以此 addon 先前完成的登入恢復同一個 host，不需輸入密碼，也不發送模型訊息。設定頁會顯示插件回報的問題原因碼；插件提供提示時，依頁面語言顯示下一步。若主機身分已被另一個 Omnigent 帳號使用（`NEEDS_RESET_ID`），在 addon 終端執行 `omnigent host reset-id --yes`，再於設定頁重新登入；server 上原本的 host 記錄不會自動刪除。背景啟動與恢復的結果會以狀態與原因碼寫入 addon 日誌。

此版本保留 **Pi Web 0.12.0**，原生 Omnigent 設定分頁與獨立頁使用相同的私有 bridge。切換離開分頁會卸載登入表單；在表單按 Escape 可關閉設定。Addon 內的 `pi-omnigent` 會拒絕 `install-ui`、`activate`、`install-host` 與 `launch-web`：它們會建立只支援 Pi Web 0.10 的介面副本或第二個 Pi Web 啟動器；其他指令照常交給插件。連線資料只由設定頁表單處理。

既有自訂插件來源、連線資料與原生 Plugins 停用狀態都保留；移除插件後重啟不會自動裝回。需要恢復時在 Plugins 新增本機來源 `/opt/woow/pi-omnigent-plugin`，或安裝公開 GitHub source。來源與首次註冊記錄位於 `/data/pi-agent/omnigent-plugin/image-seed.json`。底層套件、host 身分及設定沿用原插件路徑並包含於 HA 備份。

本頁經由原有 Supervisor ingress 驗證與 nginx 來源限制，後端只監聽 `/data/pi-agent/omnigent-ha.sock`。不新增 LAN 連接埠。映像不包含 server 憑證或模型登入，不自動安裝或更新缺少的引擎。
