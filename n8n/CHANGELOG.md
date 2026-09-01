# Changelog

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
