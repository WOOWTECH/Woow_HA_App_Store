# Changelog

## 0.14.3

- **Fix: 0.14.2's slash repair never ran on the request that breaks the page.** The diagnosis in 0.14.2 was right and is unchanged; the patch was applied in only one of three places.

  `FS()` was wired into `window.fetch` only on the branch that handles a **string** argument. Next.js's RSC fetch builds its URL as `new URL(href, location.origin)` and hands `fetch` a **URL object**, so the one request that 404s the page went through the untouched branch. Everything else the app fetches *is* a string, which is why `/api/sessions`, `/api/home`, `/api/models` and the rest were correctly prefixed while the page still died — the shim looked like it was working.

  Confirmed on the live box after deploying 0.14.2, from the browser's own network log:

  ```
  GET /api/hassio_ingress/<token>?_rsc=QLBdCDjfpGkLRHBX   404   <- RSC prefetch, no slash
  GET /api/hassio_ingress/<token>                         404   <- hard navigation, page dies
  ```

  `FS()` now runs on all three argument shapes (string, `URL`, `Request`).

- **Independently confirmed that this can only be fixed client-side.** Measured against HA Core directly from the box: the slash-less URL returns `404` and the add-on's own log does not move (102 lines before, 102 after), while the same URL with the slash reaches the add-on. Core rejects the request before the Supervisor or the add-on ever sees it, so no amount of nginx configuration in this add-on can repair it — only the browser can, before the request leaves.

- **`tests/shim-routes.mjs` covers the argument shapes.** Verified to discriminate: against the 0.14.2 shim the URL-object and Request-object cases fail (the string case passes, exactly matching the deployed behaviour); against 0.14.3, **32 passed, 0 failed**. A stub bug was fixed along the way — the fake `Request` copied `init.url` over the repaired URL, which the real constructor does not do and which produced one false failure.

## 0.14.2

- **Fix (the real one): the UI rendered correctly and then became a Home Assistant `404: Not Found` about a second later.** Introduced by 0.14.0; 0.13.2 was unaffected. **0.14.1 did not fix this** — see the note below.

  Root cause, reproduced end to end with a real browser against the live ingress URL. Next.js App Router fires an RSC prefetch ~0.5-1 s after hydration, and builds that URL from the canonical pathname with the **trailing slash normalised off**:

  ```
  GET /api/hassio_ingress/<token>?_rsc=QLBdCDjfpGkLRHBX     <- no slash after the token
  ```

  Home Assistant Core routes ingress as `/api/hassio_ingress/{token}/{path}`. With no slash the route does not match, so **HA Core returns 404 before the Supervisor or this add-on ever sees the request** — which is exactly why the add-on's own nginx log stayed clean while the user saw a 404. Next.js then takes its failure path (`"Error occurred during navigation, falling back to hard navigation"`) and hard-navigates the document to that same slash-less URL, so the whole page turns into `404: Not Found`.

  Verified on the box: HA Core direct with the trailing slash -> `200`; without it -> `404: Not Found`; without it plus `?_rsc=` (the exact browser URL) -> `404`. Repairing that single request re-inserted the slash and the app loaded and stayed up.

  The shim was passing it through because of its own "already prefixed, leave it alone" early-out (`if (p.indexOf("/api/hassio_ingress/") === 0) return false`), added to prevent double-prefixing. The slash-less URL starts with the prefix, so it matched that guard. The shim never removed the slash — Next.js did — but the shim is the only layer that can put it back, because HA Core rejects the request before anything downstream runs. `FS()` now re-inserts it for the bare prefix, prefix + query and prefix + fragment, at every entry point (fetch / EventSource / XHR / pushState / replaceState).

- **Fix: `/provider-icons.svg` escaped the ingress prefix.** The client renders `<use href="/provider-icons.svg#...">` for provider logos, and that path was not in the shim's allowlist, so it went to HA Core and 404'd. Found by code inspection, not observed in a trace — it only renders in provider-model UI the first screen does not reach, so it broke icons, not the page. Added to the allowlist.

- **`tests/shim-routes.mjs` covers both.** Checked for discriminating power rather than assumed: against the 0.14.1 shim the trailing-slash block fails all three of its cases, including the exact failing RSC prefetch URL; against 0.14.2, **29 passed, 0 failed**.

### Note on 0.14.1

0.14.1 was released against a **wrong diagnosis**. It attributed the 404 to pi-web 0.9.0's new push code obtaining Home Assistant's own service worker through `navigator.serviceWorker.getRegistration()`, which the 0.14.0 shim did not stub. Browser traces later showed `/sw.js` was never requested and no service worker was ever registered, so that was not the cause of this bug. The hardening 0.14.1 added is kept — stubbing the whole `ServiceWorkerContainer` surface rather than only `register()` is still correct for an add-on that is a guest on another application's origin — but it fixed nothing user-visible. Upgrade straight to 0.14.2.

## 0.14.1

- **Fix: the UI showed the correct screen and then turned into a Home Assistant 404 about a second later.** Introduced by 0.14.0 (pi-web 0.9.0); 0.13.2 was unaffected.

  Root cause. The add-on runs in an iframe on the Home Assistant origin, and **Home Assistant registers its own service worker at scope `/` on that same origin** (`GET /service_worker.js` -> 200, `hass_frontend/service_worker.js`). pi-web 0.9.0 added push-notification code that reaches for a service worker registration. The v0.14.0 ingress shim replaced only `navigator.serviceWorker.register()` — it did **not** replace `getRegistration()`, `getRegistrations()`, `ready` or `controller`. So pi-web's push code called `getRegistration()`, got **Home Assistant's** worker back, and subscribed its own VAPID key to it.

  Evidence, measured on the live box rather than inferred: the add-on's own nginx logged **zero** 404s (so the 404 was never served by the add-on), while the same log showed `GET /api/push/config` -> 200 followed by `POST /api/push/subscribe` -> 200 — and a push subscription can only succeed against a *real* registration, of which the only one on that origin is Home Assistant's. The 0.8.4 -> 0.9.0 delta confirms the trigger: `pushManager` appears **0** times in the 0.8.4 client bundle and **2** times in 0.9.0 (`serviceWorker` goes 2 -> 6). 0.8.4 also registered a worker, but the old shim's `register()` stub was enough to contain it; 0.9.0's push path goes around that stub.

  Fix: `rootfs/etc/nginx/nginx.conf` now neutralises the whole `ServiceWorkerContainer` surface — `register`, `getRegistration`, `getRegistrations`, `ready` (a promise that never settles) and `controller` (null) — so pi-web cleanly concludes there is no service worker and skips the push path instead of latching onto Home Assistant's.

  **This is add-on specific.** The Podman and k3s packages serve pi-web at the root of their own origin, where registering a worker at scope `/` is correct behaviour; only the add-on is a guest on another application's origin.

  **Note for anyone who ran 0.14.0:** your Home Assistant push subscription may have been overwritten while 0.14.0 was installed. If HA notifications stopped arriving, re-enable them in Home Assistant.

- **`tests/shim-routes.mjs` now covers the service-worker surface.** The harness stubs a Home-Assistant-like worker registered at scope `/` and asserts every accessor is neutralised. Verified to discriminate rather than merely pass: against the v0.14.0 shim it reports **4 failures** (`getRegistration`, `getRegistrations`, `controller`, `ready`); against 0.14.1, **24 passed, 0 failed**.

## 0.14.0

- **Upgrade to pi-web 0.9.0** (from 0.8.4) and the pi coding agent 0.85.1 (from 0.83.0).

- **New: a browser terminal inside the add-on UI.** pi-web 0.9.0 ships its own terminal — `POST /api/terminal` opens a PTY, `/api/terminal/<id>/events` streams the output back over SSE. It runs in the add-on container with the same `$HOME`, the same `/data/pi-agent` volume and the same `PATH` as the agent, so `pi install <skill>`, `pi config` and an interactive TUI session are all reachable from the HA sidebar without an SSH session. SSE is a good fit for Ingress: `ingress_stream: true` and the sidecar's `proxy_buffering off` were already in place for chat streaming.

- **`SHELL=/bin/bash` baked into the image.** The terminal spawns `process.env.SHELL || "/bin/sh"` with `["-l"]`. Debian's `/bin/sh` is dash, so without this every terminal session would silently lose history, tab completion and bash arrays while still looking like it worked.

- **The Dockerfile is now multi-stage, because 0.9.0 needs a C++ compiler to build.** The terminal depends on `node-pty` 1.1.0, a native addon that ships prebuilt binaries for darwin and win32 only — on linux its install script falls through to `node-gyp rebuild`. Measured against the 0.13.2 image, which has neither `make` nor `g++`: `gyp ERR! stack Error: not found: make`. A compiler is therefore required to *build* the add-on, but not to *run* it, and the agent's bash tool executes model-authored commands inside this container — so the toolchain lives in a builder stage and only the finished tree is copied into the shipped image. The builder deliberately uses the same `${BUILD_FROM}` base as the runtime stage rather than a plain Debian image: the add-on builds for amd64 and aarch64, and a native module compiled against a different glibc or Node ABI than the one that loads it produces a terminal that attaches and never prompts. A cross-stage `require()` assertion turns that into a failed build instead.

- **New: `pi` on `PATH` — without it the new terminal could not do the thing people open a terminal for.** Upstream installs `@earendil-works/pi-coding-agent` only as a *transitive* dependency of pi-web, so npm never links its `pi` bin and the CLI ships inside the image with no entry on `PATH`. That did not matter while the add-on had no terminal. It matters now: the first thing tried in the new terminal was `pi --version`, and it was command-not-found, which would have made `pi install <skill>`, `pi config` and the TUI all unreachable. Both sibling packages have carried this launcher since their first release; this add-on had not. `rootfs/usr/local/bin/pi` resolves the nested `dist/cli.js` at run time across four candidate paths with a `find` fallback, and the Dockerfile asserts `pi --version` at build time so a future layout change fails the build instead of shipping a broken terminal.

- **Fix: two `sub_filter` rules were missing for JSON-escaped asset paths.** 0.9.0 emits `/manifest.webmanifest` and `/icons/*` twice — once as real `<link>` tags in the SSR HTML (already rewritten) and once JSON-escaped inside the RSC flight payload React hydrates from (not rewritten). `nginx.conf` had escaped-form rules for `\"/_next/` and `\"/favicon` but not for those two. The client shim's property patches would have caught them when React applied them, so nothing was visibly broken — but that left the byte layer and the runtime layer disagreeing about the same URL, and the shim is the half that stops working first if upstream changes how it sets link hrefs. Measured before: 3 escaped paths left un-prefixed. After: 0, with the only remaining un-prefixed occurrences being the shim's own predicate string literals, which must stay literal.

- **Fix: the `SUPERVISOR_TOKEN` guard in `pi-web/run` was dead code.** `[ -z "${SUPERVISOR_TOKEN}" ]` was written to handle a missing token, but bashio runs under `set -u`, so the bare expansion aborted the script *before* the guard could test it. The failure mode was "pi-web never starts and nginx 502s forever", reachable only outside Home Assistant — i.e. exactly when someone is running the image locally to debug something and least wants a misleading error. Now `${SUPERVISOR_TOKEN:-}`, and the warning it was always meant to print actually prints.

- **New regression test: `tests/shim-routes.mjs`.** The Ingress URL shim in `nginx.conf` is what stops pi-web's absolute paths (`/api/...`, `/_next/...`) escaping the iframe and landing on HA Core. A route it fails to match does not error — one panel in the UI just breaks permanently, which is expensive to trace back to the shim. The test extracts the shim straight out of `nginx.conf` (so it cannot drift from what is served) and asserts the prefixing behaviour of `fetch`, `EventSource` and `XMLHttpRequest` across the whole 0.9.0 route surface, including the new `/api/terminal/<id>/events` SSE stream, `/api/subagents/*`, `/api/sessions/search`, `/api/tools/settings`, `/api/push/*` and `/api/app-update` — plus the two negative cases that matter: an already-prefixed path must not be double-prefixed, and an absolute external URL must not be touched. **19/19 against 0.9.0, with no shim change needed.**

- **No `nginx.conf` change was required, and that was checked rather than assumed.** Two halves had to hold. The client-side shim matches on the `/api/` prefix rather than a route list, so new routes pass through it unchanged — verified by `tests/shim-routes.mjs`, 19/19. The byte-level `sub_filter` rules match on prefixes too, and every absolute path 0.9.0 actually emits in its SSR HTML is still covered: `href="/favicon.ico?<hash>"`, `href="/manifest.webmanifest"`, `href="/icons/…"`, and `href=`/`src="/_next/…"`. (0.9.0 moved from `/manifest.json` to `/manifest.webmanifest`; the rule matches `href="/manifest`, so it caught the rename for free.) Upstream's added and removed routes (`/api/agent/running/events` and `/api/auth/all-providers` are gone in 0.9.0) pass through it unchanged. Two upstream changes were checked and have no effect here, both read out of the built `middleware.js` rather than release notes: the trust guard's matcher widened from `"/api/:path*"` to `["/", "/api/:path*"]`, so the HTML entry point is host-checked too and returns a plain-text `403 Untrusted request` on failure — the sidecar already rewrites `Host` to `localhost` for the whole `location /`, so this is inert, but it is the first thing to suspect if a future `nginx.conf` change breaks Ingress entirely rather than partially; and `PI_WEB_PASSWORD` now enables built-in HTTP Basic Auth, which this add-on does not set because HA's own authentication already sits in front of Ingress.

- **Known limitation, unchanged: web push does not work under Ingress.** 0.9.0 added `/api/push/*` and a service worker, but the shim fakes `navigator.serviceWorker.register()` success (it has done since 0.10.4, to silence a console error) and a service worker cannot be scoped to an ingress prefix anyway. Chat, streaming and the terminal are unaffected. Not a regression — there was no push support before either.

- **New: the CJK path patch, which this add-on was the last of the three packages to be missing.** Upstream folds U+00A0, U+2000–200A, U+202F, U+205F and **U+3000** to an ASCII space on every read, write and edit, and builds the read fallback chain from the already-folded path. Two silent consequences: a write to `台灣　報告.txt` lands at `台灣 報告.txt` while the success message is built from the original path ("Successfully wrote 10 bytes" to a file that does not exist), and two files differing only by space type **cross-read** — you ask for one and get the other's contents, with no error. U+3000 IDEOGRAPHIC SPACE is ordinary in Traditional Chinese filenames, so for a zh-TW add-on this is data loss with a success message rather than an edge case. `patches/fix-unicode-space-paths.mjs` makes the folding a read-only fallback (a path pasted with a non-breaking space still resolves) and never rewrites a write. It asserts every hunk, so an upstream bump fails the build instead of quietly dropping the fix. Still unfixed upstream at 0.85.1 — the only change to those files since 0.83.0 was renaming a `signal` parameter to `context`.

### Verification

Built for amd64 with `podman build --format=docker` and exercised locally.
The add-on cannot boot fully outside Home Assistant — the *base image's* own
`base-addon-log-level` service requires the Supervisor API and exits 1, which
brings the container down — so the end-to-end checks were run against nginx +
pi-web started directly, using the real `rootfs/etc/nginx/nginx.conf`:

- `tests/shim-routes.mjs` — 19/19 across the full 0.9.0 route surface.
- Ingress body rewriting with a valid `X-Ingress-Path`: 24 `_next` + 2
  `favicon` + 2 `manifest` + 4 `icons` occurrences prefixed; the only
  un-prefixed absolute paths left are the shim's own predicate literals.
- Header whitelisting: `X-Ingress-Path: "; alert(1); //` collapses to
  `window.__INGRESS_PATH__=""`, so the injected literal cannot be shaped by a
  client.
- 0.9.0 routes through the sidecar: `/api/home`, `/api/tools/settings`,
  `/api/agent/running` all `200`.
- Browser terminal through the sidecar: session created, SSE round-tripped,
  login shell `/bin/bash`, `pi --version` → `0.85.1` inside it.
- CJK: the U+3000 file reads its own contents and both space variants coexist
  as distinct files.
- Runtime image carries no `gcc`, `g++`, `make`, `cc` or `ld`.

**Not verified on real Home Assistant.** Ingress behaviour was simulated by
setting `X-Ingress-Path` by hand; the Supervisor sidebar POST, the watchdog and
the actual HAOS ingress proxy have not been exercised.

## 0.13.2

- **Fix skills downloaded via the Add-skill flow being invisible in the pi-web UI.** Regression introduced in 0.13.0: the run-script rewrite that stripped out per-provider bashio blocks also deleted the v0.12.0 `~/.pi/agent/skills` → `/data/pi-agent/skills` symlink block. Because we set `HOME=/data/pi-agent/home` and `PI_CODING_AGENT_DIR=/data/pi-agent`, the `skills` CLI (used by the Add-skill modal) writes to `${HOME}/.pi/agent/skills/` while pi-web itself reads from `${PI_CODING_AGENT_DIR}/skills/` — so every `Add skill` succeeded at the CLI level but the skill never showed up in the modal or in `<available_skills>`. Restored the pinning block in `rootfs/etc/s6-overlay/s6-rc.d/pi-web/run`: creates `/data/pi-agent/skills/`, migrates any pre-existing content out of `~/.pi/agent/skills/` (both `/root` and `${HOME}` variants) into it, then replaces the CLI's target with a symlink so both code paths land on the same on-disk directory. Skills downloaded on 0.13.0 / 0.13.1 are auto-migrated on first boot of 0.13.2 — no manual `cp` required.

## 0.13.1

- **Fix 413 Request Entity Too Large on image uploads from tablet / browser.** `rootfs/etc/nginx/nginx.conf` was missing `client_max_body_size`, so the ingress sidecar nginx fell back to its 1 MB default and rejected every image / attachment above ~1 MB with an HTML 413 (which was easy to mistake for a HAOS-ingress limit because the sidecar's own `sub_filter '</head>' '<script>...'` runs on the error page and inserts the `__INGRESS_PATH__` shim into the response body). Added `client_max_body_size 100M;` inside the `http { }` block, matching the 100 MB total / 25 MB per-file caps already enforced in pi-web's `/api/files/[...path]/route.ts`. Direct proof: `POST http://127.0.0.1:30142/` with a 2 MB body now returns 200 (was 413). No other changes.

## 0.13.0

- **BREAKING: AI provider API keys moved out of the addon Configuration tab into the pi-web UI.** The seven `password?` fields (`api_key`, `minimax_api_key`, `openai_api_key`, `openrouter_api_key`, `anthropic_api_key`, `deepseek_api_key`, `groq_api_key`) are gone. pi-web now owns provider configuration end-to-end via its own Models panel. Rationale: two places (HA options + pi-web UI) were racing to write `/data/pi-agent/models.json`, and pi-web's UI is where users actually think about model selection. **Migration**: after upgrade, open pi-web and re-enter each key inside the Models panel. Old `/data/pi-agent/models.json` is left in place (env-var placeholders like `"$GLM_API_KEY"` will resolve to empty strings and every chat will 401 until keys are re-entered — this is the expected transition state). No auto-migration; hard cut.
- **Addon Configuration now holds container-level knobs**, matching the layout of n8n / other mature HA addons:
  - `log_level` — radio `error|warn|info|debug`, default `info`. Applied to bashio via `bashio::log.level` and exported as `LOG_LEVEL` for pi-web's pino logger.
  - `timezone` — IANA name (`Asia/Taipei`, `America/New_York`, …), default empty = UTC. Sets `/etc/localtime` + `/etc/timezone` + exports `TZ` so Node.js picks it up. Empty falls back to base-image UTC.
  - `reset_video_tools` — bool, default `false`. Enabling + restarting nukes `.video-tools-installed` sentinel + `venv/` + `playwright-cache/` so the next boot re-runs `video-tools-init` from scratch. **Auto-reverts to `false` via Supervisor API** after execution so users don't burn ~720MB of download on every subsequent boot.
  - `env_vars` — list of `{name, value}`, default `[]`. Advanced escape hatch for proxy config, provider base-URL overrides, Playwright download mirrors, etc. Names validated against `^[A-Za-z_][A-Za-z0-9_]*$` before `export` so a typo doesn't crash the `set -e` init script.
- **`rootfs/etc/s6-overlay/s6-rc.d/pi-web/run` rewrite**. Deleted: the 7 `XXX_API_KEY="$(bashio::config …)"` reads, the `norm()` helper, the `bashio::log.fatal "No provider key configured"` guard, all 7 `*_provider_json()` writer functions (~200 lines of hardcoded provider templates), the `models.json` seed block, the `maybe_add_provider` idempotent-merge loop, the `check_provider` / `check_anthropic` self-probes, and every `export *_API_KEY`. Added: log_level + timezone + reset_video_tools + env_vars handling around the existing sidebar-panel-enable and video-pipeline env exports. Net: ~200 lines removed, ~60 lines added; startup is faster (no cold `curl` probes to 7 upstream APIs) and no longer coupled to any provider API surface.
- **New `translations/en.yaml` + `translations/zh-tw.yaml`.** The 4 new options render with proper labels + long-form descriptions in both English and Traditional Chinese — no more raw `snake_case` in the Configuration tab.
- **DOCS.md + README.md + README_zh-TW.md updated.** Configuration tables now list the 4 container-level options. "First-run bootstrap" and "Per-provider startup self-check" sections deleted (obsolete — that logic now lives inside pi-web). "Troubleshooting" reworked: `No provider key configured` line removed, `Chat returns 401` line points users to the pi-web Models panel instead of the addon Configuration tab.

## 0.12.0

- **Install `git` + `openssh-client` in the image** so pi-web's Add-skill flow can clone repos. `npx skills add <github-url>` (used by the Skills modal's Search button, the `owner/repo` shorthand, and skills.sh entries pointing at a repo) shells out to `git clone` via `simple-git`. Missing `git` caused every repo-backed install to fail with `spawn git ENOENT`. `openssh-client` enables the CLI's SSH clone fallback for private repos (public repos over HTTPS work without it, but the CLI's auth-failure retry path uses `ssh -o BatchMode=yes`). `gh` intentionally omitted (20MB+, only used for a swallowed `gh auth token` fallback). Verified against `skills` CLI 1.5.21 source — only git/ssh/gh are shelled out to; tar extraction uses node-tar; no submodule / lfs paths.

## 0.11.0

- **Video-production pipeline support**. Adds every CLI the `pitch_video` workflow needs (TTS → Playwright capture → ffmpeg segments/xfade/burn → rclone Drive push) so users can run the full 8-step pipeline inside the addon without leaving Home Assistant. Split into two persistence tiers to keep image size flat across upgrades:
  - **Baked into image (~300MB)**: `python3` + `python3-venv`/`python3-pip`, `ffmpeg` (bundles `ffprobe` + `libass` + `libx264` + `aac`), `fonts-noto-cjk` + `fonts-noto-color-emoji` + `fontconfig` (subtitle burn under CJK/emoji scripts — nothing else covers 中/日/韓 in libass), Chromium runtime .so set (`libnss3` + `libatk-bridge2.0-0` + `libcups2` + `libxcomposite1` + `libxdamage1` + `libxrandr2` + `libgbm1` + `libpango-1.0-0` + `libcairo2` + `libasound2` + `libatspi2.0-0`), and `rclone` (current .deb from downloads.rclone.org because Debian bookworm's package is a year behind).
  - **Downloaded to `/data/pi-agent/` on first boot (~720MB)**: Python venv (`playwright`, `edge-tts`, `pyyaml`, `mutagen`) + Chromium browser binary (`PLAYWRIGHT_BROWSERS_PATH=/data/pi-agent/playwright-cache`). Handled by a new `video-tools-init` s6-overlay oneshot with a sentinel at `/data/pi-agent/.video-tools-installed` so subsequent boots exit in <100ms. Non-fatal: pi-web starts in parallel and chat stays functional even if the download fails.
- **Env inheritance for spawned shells**. The `pi-web/run` script now exports `PATH=/data/pi-agent/venv/bin:$PATH`, `PLAYWRIGHT_BROWSERS_PATH`, and `RCLONE_CONFIG` before `exec pi-web`, so every shell the pi coding agent spawns picks up the venv python + browser cache + rclone config without the user having to source anything. `/etc/profile.d/pi-agent.sh` mirrors the same three variables for interactive addon-Terminal shells / `docker exec` sessions.
- **`backup_exclude` refined**. `**/playwright-cache/**` + `**/venv/**` skipped (rebuildable in <5min); `**/projects/**/clips/**` + `**/projects/**/segments/**` skipped (large intermediate video); `rclone.conf` stays inside snapshots so Google Drive tokens survive a restore.
- **DOCS.md `Video pipeline` section**. Documents the first-run `rclone config` step, layout under `/data/pi-agent/projects/`, and how to retry if `video-tools-init` fails (clear the sentinel + restart the addon).

## 0.10.4

- Silence the last remaining console error from v0.10.3. Rejecting `navigator.serviceWorker.register` still tripped pi-web's own `.catch()` handler that emits `console.error("Failed to register the Pi Web service worker:", err)` — 1 red line in the console on every load. Fix: resolve with a minimal fake `ServiceWorkerRegistration`-shaped object (`{scope:"/",installing:null,waiting:null,active:null,update()→resolve,unregister()→resolve(true),add/removeEventListener}`) so pi-web's success `.then()` runs silently. No functional change — SW still isn't actually registered — but the console is now clean.

## 0.10.3

- Neutralize pi-web `0.8.4`'s `navigator.serviceWorker.register('/sw.js?v=0.8.4', {scope: '/'})` call. Under HA Ingress this fails two ways: (a) the script URL resolves against HA Core (`/sw.js` → 404 from HA), and (b) even if we prefixed the URL, the `{scope: '/'}` option asks the browser to have the SW control the entire HA origin — which crosses the ingress boundary and would either be rejected by the SW's `Service-Worker-Allowed` policy or, worse, briefly hijack HA Core requests. Fix: extend the `</head>` shim to replace `navigator.serviceWorker.register` with a function that returns `Promise.reject(new Error("ServiceWorker disabled under HA Ingress"))`. Pi-web doesn't need offline PWA support inside HA (it's a local-network tool), so silently disabling registration removes 2 red console errors on every page load without any functional loss. Kept the try/catch around the shim block in case a future browser removes `navigator.serviceWorker` entirely.

## 0.10.2

- Actually fix the `/manifest.webmanifest` + `/icons/*.png` 404s from v0.10.1. The v0.10.1 approach — extending the client-side shim's `T()` predicate — was the wrong layer: `<link>` tags baked into the SSR HTML by Next.js are parsed as attributes by the browser directly, never routed through `Element.setAttribute()`, so the shim wrapper never fires on them. Confirmed via a browser-side DOM audit that showed all 3 PWA links still resolving against HA Core origin after the v0.10.1 deploy. Fix: two additional nginx `sub_filter` rules that rewrite `href="/manifest'` → `href="$safe_ingress_path/manifest` and the same for `href="/icons/`, matching the existing `_next/` and `favicon` rewrite pattern. Byte-level rewrite happens on the wire before the browser sees the HTML — same layer that has always handled `_next/*` correctly. The v0.10.1 predicate extension is kept for defense in depth (any late-injected PWA links via JS would still route through the shim), but the byte-level rules are what actually close the 404s.

## 0.10.1

- Extend the `</head>` shim's `T()` predicate to match `/manifest*` and `/icons/*` paths. pi-web `0.8.4` added three new PWA-related `<link>` tags to the head — `<link rel="manifest" href="/manifest.webmanifest">`, `<link rel="icon" href="/icons/icon-192.png">`, `<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">` — that the setAttribute wrapper saw but the predicate treated as "not one of our upstream paths", so they resolved against HA Core origin instead of the ingress prefix. The three links then 404'd (HA Core has no `/manifest.webmanifest` or `/icons/*` routes) — visible as three red network entries on every page load. Adding two literal prefix branches (`/manifest` covers both `.webmanifest` and future `.json` fallback; `/icons/` covers the whole PWA icon tree) restores 100% prefixed asset loading without any additional shim complexity. **This alone did not fix the 404s** — see v0.10.2 for the actual fix.

## 0.10.0

- **Add three new BYOK providers**: Anthropic direct, DeepSeek direct, and Groq. The catalog is now 7 providers (GLM / MiniMax / OpenAI / OpenRouter / Anthropic / DeepSeek / Groq). Rationale per provider:
  - **Anthropic direct** uses the `anthropic` API mode instead of the `openai-completions` bridge, so pi-web sees first-class thinking blocks and `cache_control` markers — the OpenRouter → Anthropic route loses both. Seeds Opus 4.7 / Sonnet 4.6 / Haiku 4.5.
  - **DeepSeek direct** is cheaper than DeepSeek-via-OpenRouter and exposes the native `deepseek-reasoner` (R1) with thinking tokens; the OpenRouter route currently strips them.
  - **Groq** LPU-hosted (~500 tok/s) covers the "cheap fast draft" tier — Llama 3.3 70B + Kimi K2. Useful as a scratch model while the flagship reasoner is thinking.
- Extend the boot self-check to cover the three new providers. Anthropic needs a special code path (`x-api-key` + `anthropic-version` headers instead of `Authorization: Bearer`, and Haiku for the probe because Sonnet/Opus reject `max_tokens=1`); the other two reuse the standard OpenAI-compatible probe.
- **Add HA Supervisor watchdog** via `watchdog: http://[HOST]:[PORT:30142]/api/home` in `config.yaml`. Supervisor probes the nginx front once per interval; a hung pi-web (crashloop, deadlocked event loop, wedged DB write) now triggers auto-restart instead of leaving the UI stuck. `/api/home` was chosen because it's the only pi-web route that a fresh install answers `200` on without a session context.
- **Persist pi coding-agent worktrees** by redirecting `HOME=/data/pi-agent/home`. Before this, `pi-cwd-<date>/` directories landed on the ephemeral container rootfs and vanished on every image update — users on v0.7.x → v0.9.1 lost their in-flight work whenever a new tag shipped. `/data/pi-agent/` is the persistent per-addon mount already backed up by HA snapshots. `backup_exclude` now also skips `node_modules` and `.cache` under the worktree tree to keep snapshots small.
- **Pin pi-web to `0.8.4`** in the Dockerfile (was `@latest`). The ingress shim rewrites 40+ hardcoded `/api/*` routes and the `T()` predicate assumes today's `_next` chunk shape / RSC prefetch behavior — an upstream refactor to any of those would silently regress the shim without any local code change. New pi-web releases now require a manual bump-and-verify in this repo, gated by the QA loop that produced v0.9.1.
- **Drop the `extra_allowed_hosts` config option**. Since v0.6.0 the nginx front rewrites `Host: localhost` before proxying to pi-web, so pi-web's `isApiRequestAllowed()` guard is unconditionally satisfied and the option had zero effect. Keeping a no-op option in the schema misled users into thinking it was a knob they should configure. Removed from `config.yaml` options + schema, the run script, and DOCS.md.

## 0.9.1

- Close the last set of console 404s uncovered in v0.9.0 QA: `.woff2` fonts (4×), a CSS asset served as `text/plain 404`, and `favicon.ico?<hash>` all failing to load. Root cause: after hydration, `ReactDOM.preinit()` and `next/font`'s runtime inject fresh `<link href="/_next/…">` and `<link href="/favicon.ico?…">` elements straight into the DOM — the browser fetches those assets by walking the element tree, so none of the v0.7.x fetch / EventSource / XMLHttpRequest wrappers ever see the URL. Cached CSS was masking the visual impact, but the network tab was loud and it would have bitten anyone on a cold cache or an offline reload.
  - Extend the `</head>` shim with a fourth interception layer: `Element.prototype.setAttribute` is wrapped so `href=` / `src=` writes go through the same `S() → T() → P+` normalizer used by fetch, and `HTMLLinkElement.prototype.href` / `HTMLScriptElement.prototype.src` / `HTMLImageElement.prototype.src` property setters are re-defined to do the same. React's DOM writes go through either path depending on the injection strategy, so we cover both.
  - No changes to `T()` — favicon and `/_next/` prefixes already matched, the URLs just weren't reaching it. Keeping the predicate untouched means script-tag hardcoded paths, RSC prefetches, and history rewrites still behave identically to v0.9.0.

## 0.9.0

- Broaden the built-in provider set from GLM+MiniMax to **GLM + MiniMax + OpenAI + OpenRouter**, so the addon isn't stuck on providers that require topping up a Chinese-side account. Real-world driver: the shipped GLM key hit `code 1113 余额不足` (out of credits) and MiniMax `1008 insufficient_balance` on the QA account; OpenAI + OpenRouter both returned 200 with the same self-check curl, so having them as first-class options removes the "install → chat 500s → open .jsonl → discover it's a credit issue" trap for new users.
  - New add-on options `openai_api_key` (`password?`) and `openrouter_api_key` (`password?`), both optional.
  - `api_key` (GLM) is now **optional** too — a hard runtime check enforces "at least one of the four must be set", failing fast on boot with a fatal log line so misconfiguration is obvious rather than showing an empty model dropdown.
  - `models.json` first-boot seed picks whichever provider the user configured first from the priority list `GLM → OpenAI → OpenRouter → MiniMax`; any additional providers whose keys are set get merged in via `jq` on subsequent boots, mirroring the idempotent additive pattern used for MiniMax since v0.4.0. Deleting a provider from `models.json` will not resurrect it — user edits win.
  - OpenRouter seed ships a curated 4-model set: `anthropic/claude-sonnet-4`, `openai/gpt-4o`, `deepseek/deepseek-chat`, `meta-llama/llama-3.3-70b-instruct` (covers the four common quality/speed tiers). OpenAI seed ships `gpt-4o` + `gpt-4o-mini`.
- Extend the v0.8.0 startup self-check to run **once per configured provider** and log the outcome per line, so a mixed-provider install (e.g., GLM out of credits + OpenAI healthy) shows both states in the Logs tab. Also add a new `HTTP 402|429` branch that reads "auth OK but limited — out of credits / rate-limited" — GLM's `1113` returns HTTP 429, MiniMax's `1008` returns HTTP 402; both used to fall through to a generic "unexpected HTTP N" warning that misdiagnosed the failure as a code bug when it's actually a billing issue.

## 0.8.0

- Fix the three latent operational gaps found by the browser + backend QA round on v0.7.3 (chat plumbing was correct but three papercuts made the failure modes look opaque to a new user):
  - **Sidebar auto-enable.** `panel_title` / `panel_icon` / `panel_admin` in `config.yaml` only supply *defaults* for the Supervisor's `ingress_panel` state — the actual sidebar entry only sticks after "Show in sidebar" is toggled on, which flips `ingress_panel=true`. Users were installing the addon, expecting the "Pi Agent" sidebar item, not seeing it, and giving up. Fix: on every boot the `pi-web` service posts `{"ingress_panel": true}` to `http://supervisor/addons/self/options` using `$SUPERVISOR_TOKEN`, so a fresh install just shows up in the sidebar without hunting for the toggle. Requires `hassio_api: true` (already set since v0.7.0).
  - **Provider startup self-check.** A bad `api_key` produced a silent failure — pi-web booted fine, UI came up, but every Send returned `401 "身份验证失败。"` from GLM and the user had to open the session `.jsonl` to diagnose. Fix: the run script now curls GLM's `/chat/completions` with `max_tokens=1` before `exec pi-web`, and logs a bashio warning on 401/403/timeout so the failure is visible in the addon Logs tab immediately. Kept non-fatal on purpose — the UI must still boot so the user can open Configuration and fix the key.
  - **stderr → s6 log.** pi-web writes some diagnostics to stderr; the s6 log service only captured stdout, so anything that crashed the node process left no trace in the addon Logs tab. Fix: `exec 2>&1` at the top of the run script merges both streams.
- Also add `ingress_stream: true` to `config.yaml` — HA Supervisor otherwise applies default 60s buffering to the ingress connection, which times out the chat SSE stream mid-generation on long responses. With the flag the Supervisor holds the connection open for the full response and pi-web's EventSource stays connected past the first minute.

## 0.7.3

- Third and final piece of the Next.js RSC-prefetch escape saga. Even with v0.7.2's `S()` normalization, `router.push('/')` was still landing on HA Core (`GET https://<HA-host>/?_rsc=<token>` → 200 dashboard HTML → Next.js router did a hard `location.href` fallback into HA's `/dashboard-home/overview`, blanking the iframe). Root cause: Next.js's `fetchServerResponse()` constructs the RSC URL via `new URL(pathname, location.origin)` and calls `fetch(urlObject, ...)` — passing a **URL object**, not a string and not a `Request`. The shim's fetch wrapper only had branches for `typeof i === "string"` and `i.url` (Request), so URL objects fell through untouched.
- Fix adds an explicit `i instanceof URL` branch that reads `.href` through `S()` (same normalizer as before) and rewrites to the ingress-prefixed string form (`fetch` accepts either string or URL as its first arg, so a string here is fine). All three input shapes — string / URL / Request — are now normalized through the same `S() → T()` pipeline.

## 0.7.2

- Fix the follow-on regression uncovered while validating v0.7.1 in the browser: Next.js's App Router prefetch was still landing on HA Core (`GET https://<HA-host>/?_rsc=<token>` → 200 dashboard HTML) even though the shim's `T()` predicate contained an `_rsc=` branch. Root cause: Next.js constructs the RSC probe URL with `new URL(href, location.href)` and passes the resulting **absolute-URL string** to `fetch(...)`. The shim's guard was `u.charAt(0) === "/"` — an absolute URL starts with `h` (as in `https://...`), so `T()` returned `false` and the fetch skipped the prefix.
- Fix wraps every URL input (fetch string arg, `Request.url`, `EventSource` URL, `XMLHttpRequest.open` URL, `history.pushState/replaceState` URL) through a new `S(u)` helper that strips a leading `location.origin` before `T()` inspects it. Same-origin absolute URLs are now normalized to their path form and routed through the prefix; cross-origin absolute URLs (analytics, CDNs, external APIs — none of which pi-web actually calls today, but keeping this clean matters if upstream adds any) pass through untouched because after strip they still fail the `charAt(0) === "/"` check.
- Also tightens the `history.pushState/replaceState` wrapper to run the same normalization so `router.push('https://<HA-host>/foo')` (unlikely from upstream, but not impossible) still lands inside the ingress prefix.

## 0.7.1

- Emergency hotfix for v0.7.0's regression: every `/_next/static/**` asset returned `404` with `text/plain` MIME (browser then refuses to execute the JS chunks, the whole Pi Agent UI shows a blank iframe). Root cause was a typo in the `map` block that was supposed to whitelist-validate `X-Ingress-Path` — the source variable had been rewritten from `$http_x_ingress_path` to `$safe_ingress_path` by a stray `replace_all`, so the map became `map $safe_ingress_path $safe_ingress_path { ... }` (self-referential, never defined, always coerced to `""`). Every `sub_filter '…$safe_ingress_path/_next/…'` template then substituted with an empty prefix, leaving `href="/_next/…"` in the HTML — the browser resolved that against HA Core, got 404, and everything downstream cascaded. The XSS-hardening intent of v0.7.0 is preserved; the fix is just restoring `$http_x_ingress_path` as the map's source variable.

## 0.7.0

- Fix the follow-on "iframe goes blank after picking a project" bug uncovered by Playwright browser QA. Root cause: pi-web's Next.js Router calls `router.push('/')` after the project picker resolves, which under the hood does two things v0.6.0's shim did not handle — (1) fetches an RSC payload on the current pathname with `?_rsc=<token>` appended (for the root that's `/?_rsc=…`, which starts with `/?` not `/api/`, so the shim's `isTargetPath()` filter passed it through unchanged and the browser resolved it against HA Core at `https://<HA-host>/?_rsc=…`, getting the HA dashboard HTML back and crashing the Next.js client with `TypeError: Failed to fetch`), and (2) updates the URL bar via `history.pushState('/')` which then makes every subsequent `location.pathname`-relative fetch escape the ingress prefix.
- Fix extends the shim in two places: `isTargetPath()` now also matches any path containing `_rsc=` (Next.js RSC probe), and `history.pushState` / `history.replaceState` are wrapped so any push to a path not already under the ingress prefix gets the prefix prepended. Net effect: the iframe stays inside `/api/hassio_ingress/<token>/…` for the entire life of the session — project picker → chat → skills → plugins → models all just work.
- Harden the sub_filter injection against the `X-Ingress-Path` XSS vector flagged by the security audit (F-01). Introduce an nginx `map $http_x_ingress_path $safe_ingress_path` guard that only accepts values matching `^/api/hassio_ingress/[A-Za-z0-9_-]{16,128}$` — anything else is coerced to `""` before it can reach any `sub_filter` template or the shim's `window.__INGRESS_PATH__` literal. HA Supervisor's Ingress layer already emits well-formed tokens, so this is defense-in-depth against a hypothetical misconfigured upstream proxy letting the client shape the header (`X-Ingress-Path: "; alert(1); //`).

## 0.6.0

- Fix the follow-on `403 "Untrusted API request"` bug where the project picker, Skills, Plugins, Models, and File-index panels all failed to load even though `/api/models-config` + `/api/sessions` returned 200. Root cause: pi-web's `isApiRequestAllowed()` (upstream `lib/request-security.ts`) checks two things on **every** `/api/*` request — (1) the `Host` header must be a loopback name / IP literal / entry in `PI_WEB_ALLOWED_HOSTS`, and (2) if an `Origin` header is present it must exactly equal `${protocol}://${host}` of the request. Under HA Ingress the browser hits `https://<HA-host>:8123/api/hassio_ingress/<token>/...`, so the forwarded `Host` was `homeassistant.local` (or the user's LAN IP / duckdns hostname) and forwarded `Origin` was `https://homeassistant.local` — neither matched pi-web's rules, so every auth-gated route returned 403.
- Fix is **two `proxy_set_header` lines in nginx**: rewrite `Host` to `localhost` (which pi-web treats as trusted unconditionally via `isLoopbackHostname`) and set `Origin` to `""` (which nginx interprets as "drop the header", satisfying the "no Origin = pass" branch of the check). No user configuration required — `extra_allowed_hosts` remains available but is no longer needed for the common case.
- Why not just document `extra_allowed_hosts` instead? Users don't always know their HA hostname (`homeassistant.local`, LAN IP, `<duckdns>.duckdns.org`, Nabu Casa remote URL — all different) and would have to add each one. Host rewriting works transparently regardless of how the user reaches HA.

## 0.5.0

- Fix the "everything 404" bug users hit as soon as they tried to chat or open the Skills panel. pi-web's client-side JS calls **over 40 distinct `/api/*` routes** on absolute paths (`/api/sessions`, `/api/skills`, `/api/agent/*`, `/api/auth/*`, `/api/files/*`, `/api/git/*`, `/api/plugins`, `/api/models*`, `/api/worktrees`, `/api/cwd/*`, `/api/file-index`, `/api/project-trust`, ...) plus 9 `EventSource` streams for chat/agent-events. Under HA Ingress the browser resolved those against `<HA-host>/api/...` — hit HA Core — 404. v0.3.0's sub_filter only handled `/_next/*` and `/favicon*`, not `/api/*`.
- Fix is a **fetch / EventSource / XMLHttpRequest shim injected at `</head>`** by nginx sub_filter. Shim reads the ingress prefix from `window.__INGRESS_PATH__` (nginx substitutes `$http_x_ingress_path` at request time) and prepends it to any absolute path starting with `/api/`, `/_next/`, or `/favicon` — but explicitly skips paths already under `/api/hassio_ingress/` so we don't double-prefix the one existing ingress URL that leaks into the JS bundle.
- Chose the shim over rewriting the bundle because a naive `"/api/` → `"$prefix/api/` sub_filter would clobber that embedded `/api/hassio_ingress/AeZVR…/_next/…` string. Shim is future-proof: any new pi-web `/api/*` route added upstream Just Works, no nginx changes needed.

## 0.4.0

- Add **MiniMax M3** as a second built-in provider alongside GLM-4.6 — team members can pick either model from pi-web's Models dropdown. Uses `openai-completions` at `https://api.minimax.io/v1` with `thinkingFormat: "deepseek"` so the `<think>...</think>` inline reasoning blocks surface as pi thinking tokens.
- New add-on option `minimax_api_key` (`password?`, optional). When set, the bootstrap adds a `minimax` provider entry to `models.json` on next start. Absent key means the addon behaves identically to v0.3.0 (GLM only).
- Bootstrap is now **idempotent + additive**: existing `models.json` from v0.3.0 keeps user edits; the MiniMax provider is merged in via `jq` only if the `minimax` key is missing. User can delete it and it will not be re-added unless they clear the whole file.
- The MiniMax API key is resolved from `$MINIMAX_API_KEY` at request time, mirroring the GLM key handling — rotating the key via the Configuration tab takes effect on restart.

## 0.3.0

- Fix the v0.2.0 caveat: pi-web's pre-built Next.js bundle emits absolute paths (`/_next/…`, `/favicon.ico`) that a browser resolves against the HA Core origin rather than the dynamic Ingress prefix. Add an **nginx sub_filter wrapper** as a second s6-overlay longrun service that reads the per-request `X-Ingress-Path` header from Supervisor and rewrites HTML / CSS / JS / RSC-flight bodies so lazy-loaded chunks, fonts, and favicon all round-trip through Ingress.
- nginx listens on `:30142` and is the new `ingress_port`; pi-web keeps `:30141` internally as the sub_filter upstream (no external binding).
- Upstream `Accept-Encoding` is stripped so sub_filter can inspect uncompressed bodies; HA Supervisor's ingress layer re-compresses for the browser.

## 0.2.0

- Switch UI exposure from published TCP port to **HA Supervisor Ingress** so the add-on works on standard HAOS without any firewall carve-out — LAN reachable via the Home Assistant UI at `/hassio/ingress/woow_ha_pi_agent`
- Add sidebar panel (`panel_title: Pi Agent`, `panel_icon: mdi:robot`, `panel_admin: true`) — admins see it directly in the HA sidebar
- Remove `ports:` / `webui:` — pi-web now only binds inside the container; Ingress proxies to `:30141`
- Known caveat: pi-web's pre-built Next.js assets are served from absolute `/_next/...` paths. If assets 404 under the Ingress prefix a future patch will add a rewriting reverse proxy in front of pi-web.

## 0.1.0

Initial release.

- Single `pi-web` s6-overlay longrun service on port 30141
- Pre-wired GLM (`glm-4.6`) via `openai-completions` at `https://open.bigmodel.cn/api/paas/v4` with `thinkingFormat: "zai"`
- API key injected via `$GLM_API_KEY` env-interp in `models.json` — rotate without file edits
- `models.json` seeded once on first start; UI edits are preserved across restarts
- amd64 + aarch64 build from `ghcr.io/hassio-addons/debian-base:9.1.0`, published to GHCR by GitHub Actions
