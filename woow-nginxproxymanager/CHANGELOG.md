# Changelog

## v2.12.4-v2

### Fixed
- **logrotate never ran.** The rotation config is copied verbatim from
  upstream NPM, where it is written for the standalone NPM image, and it is
  wrong twice over inside a Home Assistant add-on: it targets `/data/logs`
  (patch 0001 relocates all state to `/config`) and it declares `su npm npm`
  (this image has no `npm` user — the same reason `nginx.conf` is rewritten
  to `user root`). logrotate treats an unknown user as fatal for the whole
  block, so every fire of NPM's rotation timer produced a `CommandError` and
  a stack trace in the add-on log while rotating nothing. Both blocks are now
  rewritten at build time, and `logrotate --debug` runs as a build-time guard
  so a future upstream reformat fails the build instead of silently restoring
  the broken timer.

  Inherited from `hassio-addons/addon-nginx-proxy-manager`, which carries the
  byte-identical defect — not a regression introduced by this fork.

### Notes
- `GET /api/` reports version `0.0.0`. Neither upstream NPM's add-on build nor
  this fork stamps the release into `package.json`, so the in-UI version and
  update check are cosmetic only. Behaviour is unaffected; left as-is to stay
  aligned with upstream.
- The add-on still ships NPM's stock first-run credentials
  (`admin@example.com` / `changeme`) and publishes ports 80/81/443 on the LAN.
  Change the password on first login.

## v2.12.4

### WOOWTECH Fork Changes
- Forked from hassio-addons/addon-nginx-proxy-manager v2.12.4
- Updated branding to WOOWTECH
- Added Traditional Chinese (zh-Hant) translation
- Added comprehensive Chinese README documentation
- Removed armv7 architecture support (focus on amd64/aarch64)
- Added test docker-compose files for local development

### Base
- Nginx Proxy Manager v2.12.4
- Nginx 1.28.0
- Node.js 22.16.0
- Certbot 4.0.0
- SQLite (built-in)
- Base image: ghcr.io/hassio-addons/base:18.2.0
