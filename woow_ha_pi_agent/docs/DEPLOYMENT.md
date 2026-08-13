# Deployment — Currently Deployed Method, Content, Flow

Source of truth for **what is actually running** as of v0.12.0 (2026-07). Everything below is grounded in the files in this repo — cross-referenced by path so you can jump straight to the code.

- **Manifest** [`config.yaml`](../config.yaml) · [`build.yaml`](../build.yaml)
- **Image** [`Dockerfile`](../Dockerfile)
- **Service tree** [`rootfs/etc/s6-overlay/`](../rootfs/etc/s6-overlay/)
- **Ingress front** [`rootfs/etc/nginx/nginx.conf`](../rootfs/etc/nginx/nginx.conf)
- **CI publish** [`.github/workflows/build.yml`](../.github/workflows/build.yml)
- **E2E smoke** [`tests/smoke-addon.sh`](../tests/smoke-addon.sh) · [`tests/smoke-providers.sh`](../tests/smoke-providers.sh)

## 1. Delivery channel

| Layer | Value | File |
|---|---|---|
| Distribution model | HA Supervisor add-on (via HA "Add-on Store → Repositories") | `repository.yaml` |
| Repository URL added by user | `https://github.com/WOOWTECH/Woow_ha_pi_agent_add_on` | — |
| Add-on slug (Supervisor) | `woow_ha_pi_agent` (fully-qualified: `<hash>_woow_ha_pi_agent`, e.g. `b9cf5676_woow_ha_pi_agent`) | `config.yaml` |
| Image (per arch) | `ghcr.io/woowtech/woow-ha-pi-agent-{amd64,aarch64}:<version>` + `:latest` | `config.yaml`, workflow |
| Base image | `ghcr.io/hassio-addons/debian-base:9.1.0` (both archs) | `build.yaml` |
| Startup class | `application`, `boot: auto`, `init: false` (s6-overlay owns pid 1) | `config.yaml` |
| Ingress | `ingress: true`, `ingress_port: 30142`, `ingress_stream: true` | `config.yaml` |
| Sidebar tile | `panel_icon: mdi:robot`, `panel_title: Pi Agent`, `panel_admin: true` | `config.yaml` |
| Watchdog | `http://[HOST]:[PORT:30142]/api/home` | `config.yaml` |
| Backup class | `cold` with excludes for rebuildable caches; `rclone.conf` kept | `config.yaml` |
| Persistent mount | `map: addon_config` → `/data` inside container → `/data/pi-agent/` used by app | `config.yaml` |

## 2. Image composition

Full spec: [`Dockerfile`](../Dockerfile). Summary of what's baked in:

- **Runtime** — Node.js 22 (from nodesource; pi-web requires ≥22.19.0), Debian bookworm base, bashio (via HA base image) for `bashio::config` / `bashio::log.*`, s6-overlay v3 as PID 1.
- **App layer** — `npm install -g --omit=dev @agegr/pi-web@0.8.4` (pinned; see rationale in [`ARCHITECTURE.md`](ARCHITECTURE.md#9-versioning-discipline)). `@earendil-works/pi-coding-agent` comes in transitively — no separate agent daemon.
- **Ingress front** — `nginx` (Debian bookworm), config in [`rootfs/etc/nginx/nginx.conf`](../rootfs/etc/nginx/nginx.conf).
- **Skill install path** (v0.12.0) — `git`, `openssh-client`. `gh` deliberately not installed.
- **Video pipeline** (v0.11.0) — `python3` + venv/pip (for a `/data`-mounted venv); `ffmpeg`; `fonts-noto-cjk` + `fonts-noto-color-emoji` + `fontconfig`; Chromium runtime `.so` set (`libnss3`, `libatk-bridge2.0-0`, `libcups2`, `libxcomposite1`, `libxdamage1`, `libxrandr2`, `libgbm1`, `libpango-1.0-0`, `libcairo2`, `libasound2`, `libatspi2.0-0`); `rclone` (current .deb from `downloads.rclone.org`, arch-detected via `dpkg --print-architecture`).
- **Env baked into image** — `LANG=C.UTF-8`, `NODE_ENV=production`, `npm_config_cache=/tmp/npm-cache`, `NPM_CONFIG_UPDATE_NOTIFIER=false`, `PI_TELEMETRY=0`, `PI_SKIP_VERSION_CHECK=1`.
- **OCI labels** — from `build.yaml` + build-args in the workflow (title, description, vendor, source URL, revision, version, created).

## 3. s6-overlay service tree

Layout under `rootfs/etc/s6-overlay/s6-rc.d/`:

```
s6-rc.d/
├── user/contents.d/          <-- enable list — pi-web, nginx, video-tools-init
│   ├── nginx
│   ├── pi-web
│   └── video-tools-init
├── nginx/                    (longrun, no explicit deps)
│   ├── type                  = "longrun"
│   └── run                   → exec nginx -c /etc/nginx/nginx.conf
├── pi-web/                   (longrun, no explicit deps → starts in parallel with nginx and video-tools-init)
│   ├── type                  = "longrun"
│   └── run                   ← 425-line bashio script; see §4
└── video-tools-init/         (oneshot, no explicit deps → parallel with pi-web)
    ├── type                  = "oneshot"
    └── up                    → /etc/s6-overlay/scripts/video-tools-init
```

Why no `dependencies.d/` linking video-tools-init → pi-web: cold-boot Chromium install is ~720 MB, taking 3–8 min on slow networks. Blocking pi-web on that would make the chat UI unreachable during first boot for no functional reason — pi-web + chat work fine without the video pipeline; only video steps fail. Sentinel `/data/pi-agent/.video-tools-installed` gates the oneshot to a <100 ms noop after first success.

## 4. `pi-web` run script — boot sequence

Full source: [`rootfs/etc/s6-overlay/s6-rc.d/pi-web/run`](../rootfs/etc/s6-overlay/s6-rc.d/pi-web/run). Steps in order:

1. **`exec 2>&1`** — merge stderr into stdout so pi-web crash traces reach the addon Logs tab (fixed in v0.8.0; before this, stderr was silently dropped).
2. **`mkdir -p /data/pi-agent/{sessions,home}`** — create persistent dirs on first ever boot.
3. **Sidebar auto-enable** — `curl -X POST http://supervisor/addons/self/options -d '{"ingress_panel": true}'` using `$SUPERVISOR_TOKEN`. Requires `hassio_api: true` in `config.yaml`. Non-fatal on failure.
4. **Read config from HA UI** — `bashio::config` for each of the 7 provider keys; `null` → `""`.
5. **Fail-fast if all 7 keys unset** — `bashio::log.fatal` + `exit 1`. Otherwise the model dropdown is empty and every chat fails cryptically.
6. **Seed `/data/pi-agent/models.json`** if it doesn't exist — pick the first present key in priority order `GLM → Anthropic → OpenAI → OpenRouter → DeepSeek → Groq → MiniMax`. Provider snippets are inline heredocs in the run script (see the `*_provider_json()` bash functions, lines 55–283).
7. **Idempotent merge** — for every provider whose key is set, run `jq '.providers.<name> = $p'` **only if the key is missing** from the file. User edits to `models.json` always win: renaming a provider or removing one is honored across restarts. Only wiping the whole file re-triggers seed.
8. **Per-provider self-check** — one `curl` per configured provider (`max_tokens=1` for OpenAI-compatible; Anthropic uses its own `x-api-key` + `anthropic-version` headers with Haiku because Sonnet/Opus reject `max_tokens=1`). HTTP result logged per line: `200` → OK; `401`/`403` → key wrong; `402`/`429` → out of credits or rate-limited; `000` → unreachable; other → warn. **Non-fatal** — UI must always boot so user can fix bad keys.
9. **Export env for pi-web** — all 7 `*_API_KEY` vars, plus `PI_CODING_AGENT_DIR=/data/pi-agent`, `PI_WEB_HOSTNAME=0.0.0.0`, `PI_WEB_NO_OPEN=1`, `PORT=30141`, `HOME=/data/pi-agent/home`, `PATH=/data/pi-agent/venv/bin:$PATH` (only if venv exists — guarded by `[ -x /data/pi-agent/venv/bin/python3 ]`), `PLAYWRIGHT_BROWSERS_PATH=/data/pi-agent/playwright-cache`, `RCLONE_CONFIG=/data/pi-agent/rclone/rclone.conf`.
10. **`cd $HOME`** — pi-web creates worktrees under CWD.
11. **`exec pi-web`** — hands control to Node 22 process. Serves `127.0.0.1:30141` (never exposed to the LAN — nginx proxies from `:30142`).

## 5. `nginx` front — request path

Full config: [`rootfs/etc/nginx/nginx.conf`](../rootfs/etc/nginx/nginx.conf). Listens on `:30142` (matches `ingress_port` in `config.yaml`). Per-request:

1. **Whitelist-validate `X-Ingress-Path`** — the `map` clause reduces the header to `""` unless it matches `^/api/hassio_ingress/[A-Za-z0-9_-]{16,128}$`. Any body-rewrite that references `$safe_ingress_path` becomes a no-op if the header is invalid — kills the `"; alert(1); //` XSS class before it can be stored.
2. **Rewrite outbound `Host: localhost` + strip `Origin`** — pi-web's `isApiRequestAllowed()` guard needs a loopback Host and no cross-origin Origin. Without this, every auth-gated route 403s "Untrusted API request" and there's no user-facing config to fix it.
3. **Forward `X-Ingress-Path` + `X-Real-IP` + `X-Forwarded-*`** — first is for the JS shim's `window.__INGRESS_PATH__`; the rest are diagnostic breadcrumbs.
4. **`proxy_pass http://127.0.0.1:30141`** with `http_version 1.1`, `Upgrade`/`Connection: upgrade` headers for WebSocket, `proxy_buffering off` / `proxy_request_buffering off` for chat SSE, `proxy_read_timeout 3600s` / `proxy_send_timeout 3600s` for long generations.
5. **Body-rewrite** — `sub_filter` rules over `text/html text/css application/javascript application/x-javascript` (5 rule families):
   - HTML absolute-path attrs: `href="/_next/`, `src="/_next/`, `href="/favicon`, `href="/manifest`, `href="/icons/` → all prepended with `$safe_ingress_path`
   - RSC flight payloads (JSON-escaped): `\"/_next/`, `\"/favicon`
   - CSS: `url(/_next/`
   - Webpack chunk-loader JS constants: `"/_next/`
   - `</head>` — injects a ~2 KB JS shim (details in §6)
6. **Force uncompressed upstream** — `Accept-Encoding: ""` header to pi-web, otherwise gzip'd bodies bypass `sub_filter` entirely.

## 6. The `</head>` shim

The single-line JS blob at line 116 of `nginx.conf` wraps every DOM path that constructs URLs at runtime:

| Wrapped API | Why |
|---|---|
| `fetch(input, init)` | Handles `string` / `URL` / `Request` — Next.js RSC prefetch uses `new URL(...)` |
| `EventSource(url, opts)` | Chat SSE stream — subclassed via `NE` factory so `constants` are preserved |
| `XMLHttpRequest.prototype.open` | Any legacy XHR call |
| `history.pushState` / `replaceState` | `router.push('/foo')` writes ingress-prefixed history entries |
| `Element.prototype.setAttribute('href'\|'src', ...)` | React DOM writes post-hydration |
| `HTMLLinkElement.prototype.href` / `HTMLScriptElement.prototype.src` / `HTMLImageElement.prototype.src` setters | Direct property assignment path React can take |
| `navigator.serviceWorker.register` | No-op stub returning fake registration — pi-web 0.8.4 registers `/sw.js?v=0.8.4` with `{scope: "/"}`, which either 404s or crosses the ingress boundary |

Path predicate `T(u)`: strip leading `location.origin` via `S(u)`, then match against `/api/`, `/_next/`, `/favicon`, `/manifest`, `/icons/`, or `?_rsc=`. Explicit deny for `/api/hassio_ingress/` (that literal is baked into the bundle in one place — must not be double-prefixed).

## 7. `video-tools-init` oneshot — first-boot bootstrap

Full source: [`rootfs/etc/s6-overlay/scripts/video-tools-init`](../rootfs/etc/s6-overlay/scripts/video-tools-init). Guarded by `/data/pi-agent/.video-tools-installed`. On first boot:

1. `mkdir -p /data/pi-agent{,/playwright-cache,/rclone,/projects}`
2. `python3 -m venv /data/pi-agent/venv`
3. `pip install --no-cache-dir --quiet --upgrade pip`
4. `pip install --no-cache-dir --quiet playwright edge-tts pyyaml mutagen`
5. `PLAYWRIGHT_BROWSERS_PATH=/data/pi-agent/playwright-cache playwright install chromium` (~600 MB)
6. Log a hint if `/data/pi-agent/rclone/rclone.conf` doesn't exist (Google Drive OAuth requires an interactive `rclone config` run)
7. `touch /data/pi-agent/.video-tools-installed`

Every step is `if ! ... ; then bashio::log.warning ; exit 0 ; fi` — non-fatal. pi-web keeps running.

## 8. Persistent state layout

Everything under `/data/pi-agent/` (HA-supervised, per-addon, HA-snapshot backed):

| Path | Written by | Excluded from snapshot |
|---|---|---|
| `sessions/*.jsonl` | pi coding agent | no |
| `models.json` | pi-web run script (seed) + user (via UI or file edit) | no |
| `auth.json` | pi coding agent `/login` OAuth | no |
| `home/` (= `$HOME`) with `pi-cwd-*/` worktrees, `skills/` (via `PI_CODING_AGENT_DIR`) | pi coding agent | `home/**/node_modules/**` + `home/**/.cache/**` |
| `venv/` | video-tools-init | **yes** — rebuildable |
| `playwright-cache/` | video-tools-init | **yes** — rebuildable |
| `projects/<name>/{clips,segments}/` | user pipeline runs | **yes** — rebuildable |
| `projects/<name>/final.mp4` | user pipeline runs | no |
| `rclone/rclone.conf` | user (manual `rclone config`) | **no** — losing this breaks every Drive push |

`config.yaml` `backup_exclude` list is the source of truth. Note the `.tmp` session exclusion: `**/sessions/*.jsonl.tmp` — in-flight session writes.

## 9. CI publish

[`.github/workflows/build.yml`](../.github/workflows/build.yml):

- Trigger — push to `main` or tag `v*` when any of `config.yaml`, `build.yaml`, `Dockerfile`, `rootfs/**`, or the workflow itself changes. Also `workflow_dispatch` with a `push: bool` input for build-only sanity checks.
- Concurrency — `${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: true` so a rapid re-push kills the older run.
- Matrix — `amd64` (linux/amd64) and `aarch64` (linux/arm64) in parallel (`fail-fast: false`).
- Metadata step — `yq '.name' config.yaml`, `.version`, `.description`, `.build_from.<arch>` → all fed into `docker/build-push-action` as build args.
- Build backend — Docker Buildx via QEMU, `provenance: false` (HA Supervisor image pull rejects OCI provenance attestations).
- Tags — `ghcr.io/woowtech/woow-ha-pi-agent-<arch>:<version>` + `...:latest`.
- Cache — GHA cache scoped per-arch (`scope=${{ matrix.arch }}, mode=max`).
- Auth — `GITHUB_TOKEN` with `packages: write` permission; login only when the run actually pushes.

Publish flow: **bump `version` in `config.yaml` + add a `CHANGELOG.md` entry → commit → push tag `vX.Y.Z` → workflow builds both arches and pushes to GHCR → HA Store shows update available (may need `ha store reload` if the store cache is stale) → user clicks Update.**

## 10. Watchdog + operational cadence

- Supervisor watchdog target: `http://[HOST]:[PORT:30142]/api/home` — the only pi-web route that answers `200` on a fresh install without a session context. `/api/home` is unauth. Interval is Supervisor default (~1 min).
- `ingress_stream: true` — disables Supervisor's default 60 s buffering on the ingress connection so long chat responses don't get chopped mid-generation.
- Update path: HA Supervisor pulls the new image, stops container (s6 tears down cleanly), starts new container. `/data/pi-agent/` state carries over because it's an addon-config mount. First boot after upgrade re-runs the video-tools-init sentinel check (noop) + re-runs the models.json merge (noop for existing providers, additive for new ones).

## 11. E2E verification checklist

Run before tagging every release (also captured in `tests/`):

- **Fresh install** — `ha store reload && ha addons install <slug> && ha addons start <slug>`. Sidebar tile appears. First chat succeeds. `tests/smoke-addon.sh` returns 0.
- **Skill install** — pi-web → Skills → Add skill → paste a public GitHub URL → skill appears in the list → new session's `<available_skills>` block includes it.
- **Video pipeline** — `python video/verify.py` in a `projects/pitch_video/` directory succeeds; `rclone --config=... about <remote>:` succeeds.
- **Per-provider probe** — `tests/smoke-providers.sh` (curls each provider's endpoint with `max_tokens=1`, expects HTTP 200).
- **Snapshot round-trip** — `ha backup new`, restore, verify `sessions/`, `models.json`, `home/pi-cwd-*/`, `rclone/rclone.conf` all intact; `venv/` and `playwright-cache/` empty (rebuild via `video-tools-init` on next boot).

## 12. Currently deployed environment

The reference install is on `https://woowtech-ha.woowtech.io`:

- HA Core running at the URL above; admin login `admin` / (stored elsewhere).
- Addon slug `b9cf5676_woow_ha_pi_agent`, ingress token `Y8CEY_PaGC63_jYf9gh6ir6WprqcmY_xoTU6oyqwr1g` (visible in `examples/ha/panel_iframe.yaml`).
- Version at time of writing: **0.12.0** (git ENOENT fix for skill installs baked in).
- Provider keys configured: at least GLM + Anthropic + OpenAI in the QA account.
- Skills installed in the QA account: `slide-video-pipeline`, `boss-job-search` (both visible in `docs/screenshots/skills_modal.png`).

Debug commands from a machine that can reach the HA host:

```bash
# Addon state + version
curl -H "Authorization: Bearer $HA_TOKEN" \
     https://woowtech-ha.woowtech.io/api/hassio/addons/b9cf5676_woow_ha_pi_agent/info | jq '.data | {state, version, version_latest, ingress_url, watchdog}'

# Live logs
curl -H "Authorization: Bearer $HA_TOKEN" \
     https://woowtech-ha.woowtech.io/api/hassio/addons/b9cf5676_woow_ha_pi_agent/logs

# Force store re-read after publishing a new version
ha store reload
```

## 13. Where deployment breaks (and how it's caught)

| Failure mode | Signal | Where handled |
|---|---|---|
| All 7 keys unset | Fatal log line, `exit 1` — addon marked "not started" in Supervisor | `pi-web/run` §5 above |
| One key wrong | Per-provider self-check line `HTTP 401 — fix key in Configuration tab` | `pi-web/run` §8 |
| Provider out of credits | Per-provider self-check line `HTTP 402/429 — out of credits / rate-limited` | `pi-web/run` §8 |
| Node process crash | Supervisor watchdog restarts within probe interval | `config.yaml` watchdog |
| Blank UI (`/_next/*` 404) | Missing/invalid `X-Ingress-Path` — grep for it in nginx access log | `nginx.conf` §5 |
| Sidebar tile missing on fresh install | Supervisor POST during boot raced/failed — `ingress_panel: true` toggle on Info tab | `pi-web/run` step 3 |
| Skill install `spawn git ENOENT` | Image pre-v0.12.0 — `git`/`openssh-client` missing from apt install list | `Dockerfile` line 35 |
| Worktree gone after upgrade | User was on ≤v0.9.1 (worktrees on ephemeral rootfs) | `pi-web/run` `HOME=$DATA_DIR/home` (v0.10.0) |
| Chromium download hang | `video-tools-init` exits 0 with a warning; retry via `rm /data/pi-agent/.video-tools-installed` + restart | `scripts/video-tools-init` §7 |
