# Changelog

## 33.0.2

### Added
- **Automatic Cloudflare Tunnel (cloudflared) support.** `init-nextcloud-config`
  now detects a cloudflared add-on running on the same Home Assistant OS and,
  when present, automatically trusts the local hassio Docker subnet as a
  reverse proxy (`trusted_proxies`) and adds a catch-all `*` to
  `trusted_domains`. Nextcloud therefore accepts whatever public hostname the
  tunnel uses, with no per-install `trusted_domains` / `OVERWRITEHOST`
  configuration — URL-agnostic by design.
- `hassio_role: manager` — required so the add-on can list installed add-ons
  (`GET /addons`) for the cloudflared detection above.

## 33.0.1

- **Version scheme change: dropped the `-vN` fork-iteration suffix.** HA Supervisor's `awesomeversion` parses `X.Y.Z-suffix` as a SemVer pre-release, so `33.0.0-v4` was ordered BELOW an installed plain `33.0.0` and the Update button stayed disabled. Rebumped to `33.0.1` (plain patch bump) so Supervisor orders it correctly. No addon behaviour change; content is identical to 33.0.0-v4. Upstream Nextcloud is still on 33.0.0 (`linuxserver/nextcloud:33.0.0-ls421`); our patch number now advances independently of upstream.

## v33.0.0-v4

### Fixed
- **Trusted domain error on first start.** `init-nextcloud-config` only touched
  `trusted_domains` when the user had filled in the `trusted_domains` option,
  so a default install was left with `localhost` alone and every LAN request
  was rejected with "Access through untrusted domain". The script now always
  reconciles the list: user-supplied entries first, then `localhost`,
  `127.0.0.1`, the container hostname, the Supervisor-reported hostname
  (and its `.local` form), and every IPv4 address the Supervisor reports for
  the host's interfaces. Entries are de-duplicated and CIDR suffixes stripped.
- The same routine used to print `trusted_domains updated successfully`
  unconditionally, including on the path where it updated nothing. It now logs
  only the domains it actually applied, and warns actionably if no host IP
  could be determined.

### Changed
- `hassio_api: true` — required to read the host's LAN IPv4 from the Supervisor
  (`GET /network/info`, `GET /network/interface/<name>/info`). Both endpoints
  are granted to the default add-on role; no elevated role is requested.
- Removed `image:` so Supervisor builds the add-on locally. The published
  `woowtech/woow-nextcloud` image does not exist, which made the add-on
  uninstallable from a clean state.
- `db_password` and `ADMIN_PASS` now default to `null` rather than a literal.
  Home Assistant rejects known-breached passwords, and the old `nextcloud`
  default was one — installs failed validation instead of starting.

## v33.0.0-v3

### WOOWTECH Fork Changes
- Replaced MariaDB with PostgreSQL 16 for better performance and compatibility
- Removed SSL/HTTPS (HTTP-only for LAN; use Cloudflare Tunnel for external HTTPS)
- Added `db_password` option for configurable PostgreSQL password
- Added Traditional Chinese (zh-Hant) translation
- Added comprehensive Chinese README documentation
- Updated branding to WOOWTECH
- Based on fabio-garavini/hassio-addons nextcloud add-on

### Base
- Nextcloud 33.0.0
- PostgreSQL 16
- Redis (Unix socket)
- LSIO base image (ghcr.io/linuxserver/nextcloud:33.0.0-ls421)
