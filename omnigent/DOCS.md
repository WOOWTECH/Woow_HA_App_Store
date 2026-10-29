# Woow Omnigent

Omnigent 0.12.0 orchestration server, packaged as a HAOS add-on. Bundles a
private Postgres 16 so the add-on is self-contained — no MariaDB add-on
dependency, no external database wiring.

## Installation

1. Supervisor → **Add-on Store** → three-dot menu → **Repositories**
2. Add `https://github.com/WOOWTECH/Woow_ha_omnigent_addon`
3. Install **Woow Omnigent**
4. On the **Configuration** tab, set `admin_password` (required, no default);
   adjust the other options if you don't want their defaults
5. **Start**

The first boot takes ~30–60 s while Postgres inits + omnigent claims the
admin. The Ingress panel appears in the HA sidebar once ready.

## Configuration

| Option           | Default              | Purpose                                                                                        |
|------------------|----------------------|------------------------------------------------------------------------------------------------|
| `admin_username` | `woow`               | Local admin created via `POST /auth/setup` on first boot                                       |
| `admin_password` | *(required)*         | Password of the admin account, used for the web UI. The add-on does not start while it is empty |
| `base_url`       | *(empty)*            | Public URL runners dial in on. Empty = `http://homeassistant.local:8000`                       |
| `features`       | *(empty)*            | Comma-separated feature flags forwarded as `OMNIGENT_FEATURES=…`                               |
| `env_vars`       | `[]`                 | Arbitrary passthrough — each item `{key, value}` becomes an env var (key must match `^[A-Z]…`) |

## Security

Port 8000 is open on your LAN, and a Cloudflared route makes the login page
reachable from the internet. The admin password is the only thing protecting
the server, so choose a long, unique one.

Releases up to 0.1.15 pre-filled `admin_password` with a default that was
readable in this repository. If you installed one of them and never changed the
password, change it now. The add-on creates the admin account only on first
boot, so editing the option afterwards does **not** change an existing account:

1. Sign in to the Omnigent web UI with the current password.
2. Change the password there. If your build offers no password page, call
   `POST /auth/users/me/password` while signed in, with the JSON body
   `{"old_password": "…", "new_password": "…"}` (answer: `204`).
3. Put the new password in the `admin_password` option too, so the
   Configuration tab matches what you use.

While the retired default is still the configured value, the add-on logs a
warning at every start.

### Suggested `features`

- `usage_page` — enable the Usage report tab
- `web_harness_setup` — expose the per-host harness config UI
- `harness_install` — allow one-click harness install from the web

### Example `env_vars` for OpenRouter or OpenAI keys

```yaml
env_vars:
  - key: OPENAI_API_KEY
    value: sk-proj-…
  - key: OPENROUTER_API_KEY
    value: sk-or-v1-…
```

These are visible to the server process only; runners bring their own
credentials.

## Connecting a runner

Server exposes port 8000 on the LAN (`ports:` in `config.yaml`). From any
machine on the same network:

```bash
# Install pi + omnigent runner
npm install -g @earendil-works/pi-coding-agent@0.85.1
pip install omnigent==0.12.0

# Register as a host — this opens a tunnel back to the addon
omnigent host --server http://homeassistant.local:8000
```

For remote runners over the internet, pair with the **Cloudflared** HA
add-on: create a tunnel route
`omnigent-haos.example.com → http://<addon-slug>:8000`, then set
`base_url: https://omnigent-haos.example.com` in this addon's config so
the invite links match the public hostname.

## Backups

Add-on backups include `/data` — that's the Postgres cluster, artifacts,
admin credentials, and omnigent state. `pg_wal` + logs are excluded via
`backup_exclude`.

Restoring a backup restores the DB and admin claim; runners re-register
themselves on next handshake.

## Ports

| Port | Where            | Purpose                                                              |
|------|------------------|----------------------------------------------------------------------|
| 8000 | LAN + optional CF| `omnigent server` — API, tunnel dial-in, `omnigent host`             |
| 8080 | Ingress only     | nginx → HA Ingress path-rewritten SPA (blocked from LAN)             |

The Ingress port is locked to `172.30.32.2` (Supervisor). Only the
Supervisor can proxy to it, matching the n8n add-on's threat model.

## Troubleshooting

**Web UI opens but immediately shows a login form** — the auto-claim ran
but you're using the wrong password. Check `admin_username` /
`admin_password` in the add-on config.

**Web UI shows an empty host list** — expected. Add-on doesn't bundle a
runner. Register at least one from the LAN or over a Cloudflared route
(see *Connecting a runner*).

**`POST /auth/setup` returns 500** — usually means Postgres never came
up. Check the add-on logs; `init-postgres` errors appear at the top of
each boot.

**Runner registers but chat hangs** — pi extension conflict. Wipe the
runner's `~/.pi-agent/plugins/` and remove `openai-codex` from
`~/.pi-agent/auth.json`, then reconnect. See upstream 0.12.0 notes in
the k3s addon's `docs/plans/`.

## Uninstall

Stopping the add-on preserves `/data`. To wipe:

```
ha addons uninstall woow-omnigent
rm -rf /addon_configs/*_woow_omnigent
```

(Backups keep working — install again to restore.)
