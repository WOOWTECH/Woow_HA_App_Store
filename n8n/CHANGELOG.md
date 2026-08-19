# Changelog

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
