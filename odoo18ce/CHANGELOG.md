# Changelog

## 0.3.4 — 2026-09-02

### Fixed
- Post-test user downgrade now removes both Settings (`base.group_system`) and Access Rights (`base.group_erp_manager`) privileges, leaving a normal Internal User.

## 0.3.3 — 2026-09-02

### Fixed
- Normalize duplicate HA ingress prefixes produced when Odoo's lazy asset loader combines an already rewritten `data-src` with the document base URL.
- Playwright token-prefix reproduction now renders the Odoo login form with all Odoo assets inside the ingress prefix.

## 0.3.2 — 2026-09-02

### Fixed
- Remove the empty `public_url` default; Home Assistant correctly rejects an explicitly present empty value for an optional `url?` field.

## 0.3.1 — 2026-09-02

### Added
- `public_url` option freezes Odoo `web.base.url` to the canonical Cloudflare HTTPS origin
- Secure one-shot `/config/bootstrap-user.json` maintenance hook for repeatable E2E account provisioning and post-test privilege downgrade

## 0.3.0 — 2026-09-02

### Added
- Home Assistant Ingress on port 5691, opening the Odoo backend at `/odoo`
- Dual nginx gateways for HA Ingress and the Cloudflare full public origin
- Ingress rewriting for Odoo/OWL assets, JSON-RPC, forms, redirects, cookies, history, and WebSocket
- Worker-aware `/websocket` routing (HTTP port for workers=0, gevent 8072 for workers>0)
- Focused dual-gateway regression tests

### Security
- Odoo is bound to localhost:8070 and trusts forwarded headers only from bundled nginx
- HA host mappings for 8069/8072 are disabled; cloudflared uses add-on internal DNS
- Public Cloudflare gateway blocks `/web/database/*`; HA Ingress retains database management access
- Odoo package pinned to 18.0.20260806 with SHA-256 verification

## 0.2.0 — 2026-05-25

### Changed
- Upgraded PostgreSQL 15 → 16 (aligned with Odoo 18 official image)

### Added
- Timezone (`TZ`) configuration for Odoo and PostgreSQL
- Resource limit settings: `max_cron_threads`, `limit_memory_hard`,
  `limit_memory_soft`, `limit_time_cpu`, `limit_time_real`
- Configurable extra addons path (`odoo_extra_addons`)
- Auto-create database on first startup when `default_db` is set
- Dynamic addons_path with automatic directory creation
- Translations: English (`en.yaml`) and Traditional Chinese (`zh-Hant.yaml`)
- `DOCS.md` — detailed configuration reference and architecture documentation
- `README.md` — installation guide and quick start
- Cold backup support with cache/logs/sessions exclusion

### Fixed
- Missing `/share/odoo_addons` directory causing module icon 500 errors
- All addons_path directories are now auto-created if they don't exist

## 0.1.0 — 2026-05-22

### Added
- Initial release
- Odoo 18 Community Edition from nightly APT
- PostgreSQL 15 bundled in the same container
- s6-overlay service management (cont-init.d + services.d)
- Auto-sync PostgreSQL password on every boot
- Configurable SMTP settings
- Auto-update modules on startup (`auto_update_module`)
- CJK fonts + wkhtmltopdf for PDF report generation
- WOOWTECH odoo-addons pre-installed from GitHub main branch
- Support for user custom modules via `/share/odoo_addons`
- Multi-architecture support: amd64 + aarch64
