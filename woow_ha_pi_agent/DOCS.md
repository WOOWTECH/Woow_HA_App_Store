# Woow HA Pi Agent

## What it is

A single Home Assistant Supervisor add-on that installs [`@agegr/pi-web`](https://github.com/agegr/pi-web) — a browser workspace for the [`pi`](https://github.com/earendil-works/pi) coding agent — plus the full [`pitch_video`](#video-pipeline-v0110) pipeline (ffmpeg / Playwright / edge-tts / rclone).

AI providers (GLM, MiniMax, OpenAI, OpenRouter, Anthropic, DeepSeek, Groq, …) are configured **inside the pi-web UI** — open the Models panel, paste a key, done. No addon restart, no HA config edit.

pi-web imports `@earendil-works/pi-coding-agent` as an in-process SDK, so there is no separate agent daemon — one process handles both UI and inference.

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

## Troubleshooting

- **UI loads but chat returns 401** — API key wrong. Open the **Models** panel inside pi-web, edit the failing provider, paste a fresh key, and hit **Test**. No addon restart needed. (Reminder: as of v0.13.0, keys live inside pi-web, **not** in the addon Configuration tab.)
- **Chat returns 402 / 429** — auth OK but out of credits / rate-limited. Refill the provider account or switch to another provider from the Models dropdown.
- **"Open Web UI" button does nothing / 404 from ingress** — reload HA (`ha core restart`); the ingress token is minted at add-on start and occasionally needs the Supervisor to re-register the panel.
- **Assets 404 under ingress prefix (blank page, network tab shows `/_next/...` 404s)** — should be handled by the nginx sub_filter wrapper + injected `</head>` shim (fetch / EventSource / XHR / history / setAttribute / property-setter interception). Check `ha addons logs b9cf5676_woow_ha_pi_agent` for nginx errors; look for a request path that does not start with `X-Ingress-Path`, which means Supervisor didn't inject the header.
- **Sidebar tile missing** — the Supervisor API POST during boot occasionally fails on slow supervisors. Toggle "Show in sidebar" manually on the add-on's Info tab.
- **Worktree disappeared after addon update** — should not happen since v0.10.0 (`HOME=/data/pi-agent/home`). If you upgraded from ≤v0.9.1, pre-existing worktrees were on the ephemeral rootfs and did not carry over — recreate them under `HOME` this time.
