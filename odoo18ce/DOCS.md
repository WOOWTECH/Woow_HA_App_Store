# Odoo 18 CE — Home Assistant Add-on

## Overview

This add-on packages **Odoo 18 Community Edition** with **PostgreSQL 16** into a single
container managed by Home Assistant Supervisor. It is designed for SME (Small and
Medium Enterprise) deployment on Home Assistant OS hosts, including Raspberry Pi 5.

## Architecture

```
┌─────────────────────────────────┐
│  Home Assistant Supervisor      │
│  ┌───────────────────────────┐  │
│  │  Odoo 18 CE Add-on       │  │
│  │  ┌─────────┐ ┌────────┐  │  │
│  │  │ Odoo 18 │ │ PG 16  │  │  │
│  │  │ :8069   │ │ :5432  │  │  │
│  │  └────┬────┘ └────┬───┘  │  │
│  │       └─────┬─────┘      │  │
│  │         /data (persist)  │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

- **s6-overlay** manages PostgreSQL, Odoo, and nginx as supervised services
- PostgreSQL listens on `127.0.0.1:5432`
- Odoo listens only on `127.0.0.1:8070`
- nginx port `5691` provides authenticated Home Assistant Ingress at `/odoo`
- nginx port `8069` is the origin for both the Cloudflare tunnel and the LAN;
  callers are separated by source address, not by hiding the port
- `/websocket` automatically uses 8070 for `workers=0` or gevent 8073 for `workers>0`
- All persistent data is stored under `/data`

## Configuration

Configure via the **Add-on Settings** tab in Home Assistant.

### Required

| Option | Description |
|--------|-------------|
| `admin_passwd` | Odoo master password for database management |
| `db_password` | PostgreSQL password for the `odoo` role |

### System

| Option | Default | Description |
|--------|---------|-------------|
| `TZ` | `Asia/Taipei` | Timezone for Odoo and PostgreSQL |

### Database

| Option | Default | Description |
|--------|---------|-------------|
| `default_db` | _(empty)_ | Auto-create this database on first startup |
| `list_db` | `true` | Show database selector on login page |

### Performance

| Option | Default | Description |
|--------|---------|-------------|
| `workers` | `0` | Worker processes (0 = single-process mode) |
| `max_cron_threads` | `1` | Cron worker threads |
| `limit_memory_hard` | `2684354560` | Hard memory limit per worker (bytes) |
| `limit_memory_soft` | `2147483648` | Soft memory limit per worker (bytes) |
| `limit_time_cpu` | `60` | Max CPU seconds per request |
| `limit_time_real` | `120` | Max wall-clock seconds per request |

### Modules

| Option | Default | Description |
|--------|---------|-------------|
| `odoo_extra_addons` | _(empty)_ | Extra addons paths (comma-separated) |
| `auto_update_module` | _(empty)_ | Modules to update on each startup |
| `without_demo` | `true` | Skip demo data on database creation |

### SMTP

Configure `smtp_server` to enable email sending. All other SMTP fields are
optional and only used when `smtp_server` is set.

## Persistence

All data is stored under `/data` and persists across restarts and updates:

| Path | Content |
|------|---------|
| `/data/postgres` | PostgreSQL cluster data |
| `/data/odoo` | Odoo filestore, sessions, logs |
| `/data/odoo.conf` | Generated Odoo configuration |
| `/data/addons` | Runtime addon downloads |

## LAN access

Port `8069` serves two callers and gives them different privileges.

| Caller | How it is recognised | What it gets |
|---|---|---|
| LAN | source address inside `lan_networks` | the full application, database manager included |
| Cloudflare tunnel | arrives from the add-on network, presenting the `public_url` host | restricted: no database lifecycle, RPC behind the policy filter |
| anything else | neither of the above | refused (`444`, or `503` while `public_url` is unset) |

Docker preserves the real client address on a published host port, which is what
makes the split possible. The tunnel is the case to be careful about: it reaches
the add-on from inside the add-on network, and the default LAN range
`172.16.0.0/12` contains that network — so `172.30.32.0/23` and the add-on
network's IPv6 prefix are carved out of the LAN tier explicitly.

Set `lan_networks` to the narrowest ranges that cover your clients. Entries are
validated as IPv4/IPv6 CIDRs and a malformed one fails start-up. IPv6 callers are
denied unless you add their prefix; do not add a broad `fd00::/8`.

Two consequences worth knowing:

- The Home Assistant host itself reaches Odoo through the bridge address and is
  treated as LAN. Anything host-networked shares that address, so a
  host-networked reverse proxy pointed at `8069` would hand its callers the LAN
  tier.
- `8072` is behind the same gate. Odoo binds its workers to loopback, so nginx
  owns that port and the gevent worker sits on an internal `8073`; the port
  answers whether `workers` is 0 or more.

## Ports

| Port | Protocol | Description |
|------|----------|-------------|
| 5691 | TCP | HA Supervisor Ingress (container-internal) |
| 8069 | TCP | Odoo origin — LAN gets full access, the tunnel stays restricted |
| 8070 | TCP | Odoo HTTP backend bound to localhost |
| 8072 | TCP | WebSocket origin, same LAN gate as 8069 (worker itself on 8073) |

## External HTTPS

The add-on has two simultaneous entrances:

- **Home Assistant Ingress** — Open Web UI/sidebar opens `/odoo`; HA authentication is followed by normal Odoo authentication. The HA origin must use HTTPS because the Odoo session cookie is deliberately marked `Secure`.
- **Cloudflare Tunnel** — publish the complete root-path Odoo UI/API/WebSocket by routing the hostname to `http://<repo-hash>-odoo18ce:8069` on the internal add-on network.

The Cloudflare gateway blocks `/web/database/*`; database lifecycle management
stays available through HA Ingress and from the trusted LAN. Odoo itself remains HTTP on localhost while TLS terminates at HA or Cloudflare.

Set the required HTTPS `public_url` to the canonical Cloudflare URL so Odoo-generated website metadata, email links and callbacks never fall back to the internal HTTP origin. `default_db` is required when `public_url` or `auto_update_module` is configured.

## Custom Modules

Place custom Odoo modules in `/share/odoo_addons/` (mapped from HA's shared
storage). They will be automatically added to the addons path.

For additional paths, use the `odoo_extra_addons` configuration option.

## Backup

The add-on uses `cold` backup strategy. Home Assistant will stop the add-on
before creating a backup to ensure data consistency. Cache, logs, and sessions
are excluded from backups.

Backups include the PostgreSQL cluster, filestore, Odoo master/database passwords and optional SMTP credentials. Use encrypted HA backups, strictly control downloads, and rotate credentials after any suspected backup disclosure.
