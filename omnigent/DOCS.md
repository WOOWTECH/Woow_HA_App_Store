# Woow Omnigent

Omnigent 0.21.0 orchestration server, packaged as a HAOS add-on. Bundles a
private Postgres 16 so the add-on is self-contained — no MariaDB add-on
dependency, no external database wiring.

## Installation

1. Supervisor → **Add-on Store** → three-dot menu → **Repositories**
2. Add `https://github.com/WOOWTECH/Woow_ha_omnigent_addon`
3. Install **Woow Omnigent**
4. On the **Configuration** tab, set `admin_password` (required for a new install, no default);
   adjust the other options if you don't want their defaults
5. **Start**

The first boot takes ~30–60 s while Postgres inits + omnigent claims the
admin. The Ingress panel appears in the HA sidebar once ready.

## Configuration

| Option           | Default              | Purpose                                                                                        |
|------------------|----------------------|------------------------------------------------------------------------------------------------|
| `admin_username` | `woow`               | Local admin pre-seeded before the server accepts requests on first boot                       |
| `admin_password` | *(required)*         | Password of the admin account, used for the web UI. A new install does not start while it is empty; an existing install does, and keeps the account's current password |
| `base_url`       | *(empty)*            | Public URL runners dial in on. Empty = `http://homeassistant.local:8000`                       |
| `features`       | `usage_page,harness_install` | Comma-separated feature flags forwarded as `OMNIGENT_FEATURES=…`                       |
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

If you updated from 0.1.15 or earlier without ever saving the Configuration
tab, `admin_password` is empty. 0.1.16 refused to start in that state; since
0.1.17 the add-on starts, logs a warning, and the account keeps its current
password. That password may still be the retired default, so change it as
above and then fill in the option.

### Suggested `features`

- `usage_page` — enable the Usage report tab
- `harness_install` — allow one-click harness install from the web

Omnigent 0.21.0 also turns on `session_orchestration`, `claude_osc_status`
and `codex_plan_at_launch` by default. You do not need to list them; write
`-<name>` to turn one off. An unknown name stops the server from starting.

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
pip install omnigent==0.21.0

# Register as a host — this opens a tunnel back to the addon
omnigent host --server http://homeassistant.local:8000
```

Keep runners on the server's version when you can. A runner on omnigent
0.20.0 still connects to this 0.21.0 server (the host protocol is unchanged).
Since 0.21.0, `omnigent opencode` on a runner needs OpenCode 2.0 (2.0.18 or a
later 2.0.x); OpenCode 1.x (`opencode-ai`) is no longer supported.

For remote runners over the internet, pair with the **Cloudflared** HA
add-on: create a tunnel route
`omnigent-haos.example.com → http://<addon-slug>:8000`, then set
`base_url: https://omnigent-haos.example.com` in this addon's config so
the invite links match the public hostname.

## Backups

Add-on backups are cold and include `/data` — the full Postgres cluster
**including `pg_wal`**, artifacts, admin credentials, and Omnigent state.
Only logs are excluded. The WAL is needed to restore the database safely.

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

**The server still needs setup** — check the add-on logs for an admin
bootstrap error. New installs require `admin_password`; the server creates
the account before it accepts requests. An older install with an empty
option is checked against its existing database before the server starts.

**Runner registers but chat hangs** — pi extension conflict. Wipe the
runner's `~/.pi-agent/plugins/` and remove `openai-codex` from
`~/.pi-agent/auth.json`, then reconnect.

## Uninstall

Stopping the add-on preserves `/data`. To wipe:

```
ha addons uninstall woow-omnigent
rm -rf /addon_configs/*_woow_omnigent
```

(Backups keep working — install again to restore.)

## Hermes skills across Omnigent conversations

This add-on runs the Omnigent **server**. To create and reuse Hermes skills,
install the Hermes Omnigent plugin (`hermes-omnigent-plugin`, v0.1.0-rc.20 or
later) in the Hermes runtime on the same host as each Omnigent Hermes runner.
The plugin installs its own private Omnigent 0.20.0 for the runner, and that
runner connects to this 0.21.0 server. The runner must keep
its Hermes profile skills directory persistent and writable. This server image
alone does not install Hermes or the plugin.

Acceptance after the plugin is released: in one Omnigent Hermes conversation,
explicitly create a skill with `skill_manage(create)`; in a second conversation,
call `skill_view` for that skill and use it; then confirm native Hermes can see
and use the same skill. The plugin's skill ledger remains scoped to the
conversation, so ledger entries are not the cross-conversation proof. HAOS
runtime verification is pending.
