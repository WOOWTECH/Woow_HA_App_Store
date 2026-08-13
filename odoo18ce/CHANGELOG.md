# Changelog

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
