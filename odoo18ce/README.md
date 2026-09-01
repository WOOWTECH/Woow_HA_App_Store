# Odoo 18 CE — Home Assistant Add-on

Odoo 18 Community Edition + PostgreSQL 16, bundled as a single Home Assistant add-on
for SME deployment.

## Features

- Odoo 18 Community Edition (nightly APT)
- PostgreSQL 16 (bundled, container-internal)
- CJK fonts + wkhtmltopdf for PDF report generation
- WOOWTECH custom modules pre-installed
- Multi-arch: amd64 + aarch64 (Raspberry Pi 5)
- Traditional Chinese / English translations
- Cold backup with automatic exclusions
- Auto-create database on first startup

## Quick Start

1. Set **Admin Master Password** and **Database Password** in the add-on settings
2. (Optional) Set **Default Database** name for automatic database creation
3. Click **Start**
4. Open **Web UI** or the **Woow Odoo** sidebar panel (HA Ingress)
5. For public access, point Cloudflare Tunnel to the add-on internal origin `http://<repo-hash>-odoo18ce:8069`

## Ports

| Port | Description |
|------|-------------|
| 5691 | HA Ingress adapter (internal) |
| 8069 | Cloudflare full UI/API origin (internal) |
| 8070 | Odoo localhost HTTP backend |
| 8072 | gevent WebSocket for workers > 0 |

## Documentation

See the **Documentation** tab for detailed configuration reference and architecture.

## License

LGPL-3.0
