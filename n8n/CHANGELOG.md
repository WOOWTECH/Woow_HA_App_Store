# Changelog

## 2.43.6

**Before updating: take a Home Assistant backup that includes this add-on.** This release upgrades the bundled n8n and task runners from 2.12.3 to 2.43.6. On its first start n8n migrates the database one way; n8n 2.12.3 cannot use the migrated data. The only rollback is restoring the pre-update backup, which brings back add-on 2.12.17 with its unmigrated database. Let the first start finish (the log shows `Migrations in progress, please do NOT stop the process.`).

- n8n and Task Runner 2.43.6 (Node.js 26, Docker Hardened Images Alpine 3.24 base). The task runner launcher now comes from the runners image of the same release instead of a separately pinned download, and the runner configuration gains upstream's `NODE_PATH`, `N8N_RUNNERS_GRACEFUL_SHUTDOWN_TIMEOUT` and `N8N_RUNNERS_SHUTDOWN_FORCE_KILL_MARGIN` variables. The Code node module allow-lists are unchanged.
- After updating, re-create n8n API keys under *Settings → n8n API*: keys made before the upgrade lack scopes introduced since (such as publishing workflows), so some public API calls return 403. Update the tools that use them, for example the Woow n8n MCP add-on.
- Folders (for example the Woow n8n MCP `n8n_manage_folders` tool) need a re-created API key with the `folder:*` scopes and an instance registered for the free Community features (*Settings → Usage and plan*).
- New in n8n: *Settings → Instance-level MCP*. Its access token can be entered in the optional field of the Woow n8n MCP add-on 0.2.1.
- Home Assistant Ingress: the preload-helper rewrite now matches the URL builder by its body instead of its minified name, and every build checks it against the bundle actually shipped. Verified in headless Chromium through a Supervisor-style ingress proxy: sign-in, workflow canvas, no duplicate stylesheets, full-height editor and the `/rest/push` WebSocket under the ingress prefix.
- Watchdog: the Supervisor watchdog now checks n8n's readiness (`/healthz/readiness`, database connected and migrated) through `/_woow/watchdog`. Until n8n is ready for the first time after a start it reports "starting", so a long database migration is never interrupted by a watchdog restart; after one hour without becoming ready the watchdog takes over again.
- Clean shutdown: n8n now stops before its task runners (the 2.43 launcher otherwise waits about 50 seconds for the broker to drain, after which n8n would be killed without shutting down), and the add-on stop timeout is raised to 60 seconds so running executions can finish.
- Security: the Supervisor API token is dropped from the container environment after the start-up script that needs it, and no service (n8n, task runners, nginx, Redis) keeps it, so workflows can no longer read it through `$env` (which otherwise stays enabled for existing workflows), files or `/proc`. The task broker listens on loopback only and uses a random per-installation token in `/data` instead of the shared `n8n-runner` constant. Redis listens on loopback only with protected mode on and a private socket. Option values with secret-like names (now including `TOKEN`, `AUTH`, `CREDENTIAL`, `PRIVATE`, `DSN`, `PWD`) are masked in the log, URL credentials are removed, and settings are no longer copied into `/.env`, `/etc/environment` or `~/.bashrc`. See *Security notes* in the documentation for what Code nodes can still do.
- The Python Code node now runs on the runners image's own CPython (3.13 for n8n 2.43), the interpreter its virtualenv was built for, instead of the base image's `python3` (3.14). `python3` in shells and Execute Command nodes is unchanged.
- n8n no longer waits for Redis: n8n does not use it, so a Redis that cannot start (for example when its ARM64 kernel self-check fails) only affects workflows that use Redis.
- The add-on no longer sets the deprecated `WEBHOOK_URL` itself (n8n 2.43 warned about it on every start); a `WEBHOOK_URL` you configured is still honoured and mirrored to `N8N_WEBHOOK_URL`.
- `N8N_PROXY_HOPS` defaults to `1`: the ingress nginx now hands n8n a single `X-Forwarded-For` address (the client as seen by Home Assistant), the same shape cloudflared sends on the Cloudflare hostname, so n8n's rate limiter sees the real client and no longer logs `ERR_ERL_UNEXPECTED_X_FORWARDED_FOR`. An explicit `N8N_PROXY_HOPS` option still wins.
- `clean_redis` now deletes the actual Redis dump file (`dump.rdb`; it targeted `dump.rdd`).
- Release process: every pull request runs all tests, builds the amd64 image and smoke-tests the container; publishing refuses to overwrite an existing image tag; workflow actions are pinned to commit SHAs.

## 2.12.17

- Force the effective runtime `N8N_SECURE_COOKIE=false` on boot so existing installs that retained `true` can still open the n8n owner/sign-in UI over plain HTTP through direct LAN access or Home Assistant Ingress.
- This release keeps n8n and Task Runner pinned to 2.12.3 and does not run a database migration.

## 2.12.16

- Home Assistant Supervisor now pulls versioned, prebuilt add-on images from `ghcr.io/woowtech/woow-ha-n8n-{arch}` instead of building the add-on from Docker Hub during installation. Separate `amd64` and `aarch64` images are published with the exact add-on version tag.
- Release maintainers must wait for the `Publish n8n add-on images` workflow to publish and verify both architecture tags before announcing the add-on update. If a release image needs rebuilding, use the workflow's manual dispatch on the release revision; do not publish a configuration version whose GHCR images are unavailable.
- n8n and Task Runner remain pinned to 2.12.3; this packaging change does not run an n8n database migration.

## 2.12.15

- Prevent stale Home Assistant Ingress transforms under unchanged n8n asset hashes. The ingress nginx now clears client ETag/date validators before proxying and returns `Cache-Control: no-store` for HTML, JavaScript, and CSS responses whose bodies it may rewrite, rather than forwarding n8n's long-lived public cache policy.
- Preserve the upstream `Cache-Control` policy for unmodified response types such as images, fonts, icons, and other binary assets. Direct port 5678 remains unchanged, and n8n and Task Runner remain pinned to 2.12.3.
- After deploying, perform a one-time Cloudflare cache purge for the public HA ingress prefix ending in `/api/hassio_ingress`. Because an edge purge cannot remove existing browser entries, users who previously opened the affected ingress UI also need one hard refresh.
- Rollback: restore the pre-2.12.15 partial add-on backup to return to 2.12.14; no n8n database migration is involved.

## 2.12.14

- Fix the confirmed Home Assistant Ingress height collapse at its source: n8n 2.12.3's preload helper searched for root-path dependencies while the initial stylesheet links had already been rewritten to the token-prefixed ingress path. The helper now builds dependency URLs from the ingress-only `window.BASE_PATH`, so its native duplicate-link check finds the existing links.
- Prevent duplicate BaseLayout CSS from loading after the index stylesheet and overriding n8n's `height: 100vh` with `height: 100%`. Remove the 2.12.13 frame-height adapter, route, and injection because the Home Assistant panel and iframe were already correctly sized.
- Direct port 5678 and Cloudflare root-path access remain unchanged. n8n and Task Runner remain pinned to 2.12.3.
- Rollback: restore the pre-2.12.14 partial add-on backup to return to 2.12.13; no n8n database migration is involved.

## 2.12.13

- Fix the confirmed Home Assistant App-panel height collapse by loading a frame-height adapter only through the port 5690 ingress nginx. When the n8n iframe belongs to `ha-panel-app`, the adapter restores the host to the dynamic viewport height and the iframe to 100%; direct port 5678 and Cloudflare remain unchanged.
- Verified in Playwright at an 857px viewport: the reproduced 343px collapsed child expands to 857px, while loading the same adapter in a top-level page is a no-op with no page errors.
- Rollback: restore add-on 2.12.12 from a pre-update backup or prior source version; the bundled n8n and runners remain pinned to 2.12.3 and use the same data directory.

## 2.12.12

- Fix the confirmed blank-panel cause: n8n's runtime module preloader assigns root-absolute lazy chunk URLs through `HTMLLinkElement.href`, bypassing ordinary `setAttribute` rewriting. Patch link/script/image property setters and CSS font asset URLs into the HA ingress prefix.
- Verified with a Playwright ingress-prefix reproduction: the n8n sign-in form renders and lazy `SigninView` assets stay under the tokenized prefix.

## 2.12.11

- Redirect the ingress adapter's cached root URL to the token-prefixed `/signin` route, covering existing HA sidebar panels that retain the old root entry across an add-on update.

## 2.12.10

- Remove the leading slash from `ingress_entry` to prevent Supervisor from generating a double-slash `//signin` ingress URL.

## 2.12.9

- Open HA Ingress directly at `/signin` so n8n does not need to perform its root-to-auth client-side redirect inside the tokenized iframe. Authenticated n8n sessions still redirect to the workflow home normally.

## 2.12.8

- Fixed the blank HA Ingress panel after n8n loaded its initial assets: inject an ingress-aware `<base>` and runtime shim for Vue history navigation, lazy asset URLs, fetch/XHR, DOM URLs, and the `/rest/push` WebSocket.
- Removed the duplicate nginx MIME-type warning.

## 2.12.7

- Added Home Assistant Ingress on dedicated port 5690 with sidebar metadata, streaming, WebSocket forwarding, watchdog, and dynamic `X-Ingress-Path` rewriting.
- Kept the direct port 5678 unchanged so the complete root-path UI/API/Webhook/WebSocket remains available through Cloudflare Tunnel at the same time.
- Added an ingress-only nginx adapter; n8n itself remains rooted at `/`, so the Cloudflare public URL is not moved under the HA ingress token.

## 2.12.6

- Added first-class `N8N_EDITOR_BASE_URL`, `N8N_WEBHOOK_URL`, and `N8N_PROXY_HOPS` options for complete UI/API/WebSocket access through Cloudflare Tunnel.
- Mirror legacy `WEBHOOK_URL` and current `N8N_WEBHOOK_URL` at boot so the existing n8n 2.12.3 runtime and future n8n 2.35+ upgrades use the same public webhook URL.
- Added focused configuration/boot tests and documented the full-UI Cloudflare security boundary. The bundled n8n version remains pinned to 2.12.3; this release does not run an upstream database migration.

## 2.12.5

- **Harden s6-overlay + bashio + tempio downloads against flaky networks.** Changed `curl -L -s` to `curl -fL -sS --retry 5 --retry-delay 3 --retry-connrefused --connect-timeout 15 --max-time 120` in the RUN block that fetches from `github.com/objects.githubusercontent.com`. Reason: 2.12.4 build kept failing on Elmo HAOS with `xz: (stdin): File format not recognized` — the plain `-s` silently swallowed HTTP errors and pipe-through-tar choked on empty or HTML output. `-f` fails the pipe on non-2xx (surfaces the real problem), `-sS` keeps quiet but still shows curl errors, and `--retry 5` rides through transient CDN hiccups. No addon behaviour change.

## 2.12.4

- **Version scheme change: dropped the `-vN` fork-iteration suffix.** HA Supervisor's `awesomeversion` parses `X.Y.Z-suffix` as a SemVer pre-release, so `2.12.3-v1` was ordered BELOW the installed `2.12.3` and the Update button stayed disabled with "已最新" — every user stuck on 2.12.3 couldn't pick up the N8N_SECURE_COOKIE option shipped in 2.12.3-v1. Rebump to `2.12.4` (plain patch bump) so Supervisor orders it correctly. No addon behaviour change; content is identical to 2.12.3-v1.
- `Dockerfile`: pinned the `runners` FROM to `2.12.3` explicitly (was derived from `${BUILD_VERSION%-v*}`). Addon version now advances independently of upstream n8n, so the runner tag must stay pinned to the actual wrapped upstream version.

## 2.12.3-v1

- Added `N8N_SECURE_COOKIE` as a first-class add-on option.
- Defaulted secure cookies to `false` so the documented LAN HTTP URL can complete login.
- Documented setting `N8N_SECURE_COOKIE: true` for HTTPS-only deployments.

## 2.12.3 (WOOWTECH Fork)

### Changes from upstream (fabio-garavini/hassio-addons)
- Removed SSL/HTTPS requirement for LAN access
- Default protocol changed to HTTP (use Cloudflare Tunnel for external HTTPS)
- Removed `ssl`, `certfile`, `keyfile` options from config schema
- Added Traditional Chinese (zh-Hant) translations
- Updated healthcheck to use HTTP instead of HTTPS
- Changed default timezone to Asia/Taipei in test configs

### Upstream n8n 2.12.3
- core: Emit `leader-takeover` on leadership mismatch in `checkLeader`
- editor: Fix command bar not finding workflows
