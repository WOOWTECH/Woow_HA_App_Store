# Changelog

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
