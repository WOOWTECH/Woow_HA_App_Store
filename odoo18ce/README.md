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
4. Open the Web UI at `http://<your-ha-ip>:8069`

## Ports

| Port | Description |
|------|-------------|
| 8069 | Odoo Web Interface + XML-RPC |
| 8072 | Longpolling / WebSocket |

## Documentation

See the **Documentation** tab for detailed configuration reference and architecture.

## License

LGPL-3.0
