# Woow Omnigent — HAOS add-on

Runs [Omnigent](https://github.com/omnigent-ai/omnigent) 0.12.0 as a Home
Assistant OS add-on.

**Server-only build.** No pi / claude / codex CLI is bundled — external
runners register themselves against this addon over HTTP:

```
omnigent host --server http://homeassistant.local:8000
```

## What's inside

| Component        | Version | Notes                                                     |
|------------------|---------|-----------------------------------------------------------|
| omnigent         | 0.12.0  | pip-installed from PyPI                                   |
| PostgreSQL       | 16      | bundled — loopback only, persisted in `/data/postgres`    |
| nginx            | latest  | HA Ingress path rewriter for the React SPA                |
| s6-overlay       | 3.2.1.0 | via `ghcr.io/hassio-addons/base`                          |

## First-run behaviour

1. `init-addon-config` reads `options.json` → `/var/run/omnigent.env`
2. `init-postgres` initdbs the cluster + creates `omnigent` role/db (idempotent)
3. `svc-postgres` starts the postmaster on `127.0.0.1:5432`
4. `svc-omnigent-server` starts on `0.0.0.0:8000`
5. `init-admin-claim` POSTs `/auth/setup` with the configured admin creds
   (409 on re-run = fine, we exit clean)
6. `nginx` serves the HA Ingress panel on port 8080

## Access modes

| Path                                    | Who        | Purpose                        |
|-----------------------------------------|------------|--------------------------------|
| HA sidebar panel → Woow Omnigent        | HA users   | React SPA over Ingress         |
| `http://<ha>:8000` (LAN)                | runners    | tunnel dial-in + `omnigent host` |
| `https://<cf-tunnel-hostname>`          | remote     | CF add-on route → `:8000`      |

## Configuration

See `DOCS.md` inside the add-on.

## License

MIT.
