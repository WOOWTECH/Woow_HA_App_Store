# Woow Omnigent — HAOS add-on

Runs [Omnigent](https://github.com/omnigent-ai/omnigent) 0.21.0 as a Home
Assistant OS add-on.

**Server-only build.** No pi / claude / codex CLI is bundled — external
runners register themselves against this addon over HTTP:

```
omnigent host --server http://homeassistant.local:8000
```

## What's inside

| Component        | Version | Notes                                                     |
|------------------|---------|-----------------------------------------------------------|
| omnigent         | 0.21.0  | verified WOOW MCP wheel (`mcp.1`)                                   |
| PostgreSQL       | 16      | bundled — loopback only, persisted in `/data/postgres`    |
| nginx            | latest  | HA Ingress path rewriter for the React SPA                |
| s6-overlay       | 3.2.1.0 | via `ghcr.io/hassio-addons/base`                          |

## First-run behaviour

1. `init-addon-config` reads `options.json` → `/var/run/omnigent.env`
2. `init-postgres` initdbs the cluster + creates `omnigent` role/db (idempotent)
3. `svc-postgres` starts the postmaster on `127.0.0.1:5432`
4. `svc-omnigent-server` starts on `0.0.0.0:8000`
5. `svc-omnigent-server` pre-seeds the configured admin before serving;
   `init-admin-claim` verifies that setup is complete
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

## Native MCP

Version 0.1.24 bundles the 0.21.0-based WOOW MCP build `mcp.1`, including
account-bound profiles and paginated session history. Configure
`mcp_public_base_url` with the complete external HTTPS base, then copy the
profile URL from **Settings → Admin → MCP Server**. HA Ingress remains the UI
entry point. See [DOCS.md](DOCS.md#native-mcp-connections) for proxy setup.

Take a backup before updating. The Store does not allow downgrades; to roll
back, restore the complete backup taken before the upgrade.
