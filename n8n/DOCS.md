# Home Assistant Add-on: Woow n8n by WOOWTECH

**n8n** is a workflow automation platform that gives technical teams the flexibility of code with the speed of no-code. With 400+ integrations, native AI capabilities, and a fair-code license, n8n lets you build powerful automations while maintaining full control over your data and deployments.

## All-in-One Components

This monolithic package includes:

- **n8n**: workflow automations, with external JavaScript and Python task runners (the Python Code node runs on upstream's CPython 3.13 from the n8n runners image; `python3` in the container shell is Alpine's 3.14)
- **Redis**: a local Redis for your workflows (for example the Redis node) on `localhost:6379`; n8n itself does not use it

[Official n8n Documentation](https://docs.n8n.io/)

---

## Key Difference: HTTP-Only for LAN

This is a fork of [fabio-garavini/hassio-addons](https://github.com/fabio-garavini/hassio-addons) with the following modification:

- **SSL/HTTPS has been removed** for local network (LAN) access
- The web UI runs on plain HTTP at port 5678
- For external HTTPS access, use **Cloudflare Tunnel** to establish a secure connection

This design simplifies the setup for users who access n8n only within their home network, while relying on Cloudflare Tunnel for secure external access.

---

## Installation Guide

1. **Install the Add-on**:
   - Navigate to **Home Assistant Supervisor** > **Add-on Store**
   - Add the WOOWTECH repository URL
   - Search for "Woow n8n" > Click **Install**
2. **Initial Setup**:
   - Start the add-on
   - Click **OPEN WEB UI** and follow the first-run wizard
3. **Configure Cloudflare Tunnel** (for complete external UI/API/WebSocket access):
   - Set up a Cloudflare Tunnel public hostname pointing to `http://<HA_IP>:5678` (or the Home Assistant internal hostname and port)
   - Configure the add-on:
     ```yaml
     N8N_HOST: n8n.example.com
     N8N_EDITOR_BASE_URL: https://n8n.example.com
     N8N_WEBHOOK_URL: https://n8n.example.com
     N8N_PROXY_HOPS: 1
     N8N_SECURE_COOKIE: false
     ```
   - Restart the add-on.

The bundled n8n (2.43) reads `N8N_WEBHOOK_URL`. A `WEBHOOK_URL` from an older configuration is still honoured (it is copied to `N8N_WEBHOOK_URL`), but n8n then warns that the name is deprecated; move the value to `N8N_WEBHOOK_URL`. `N8N_PROXY_HOPS` defaults to `1`, which is correct for both entrances: Cloudflare (cloudflared is the one proxy in front of port 5678) and HA Ingress (the add-on's ingress nginx passes n8n a single client address). Keep `N8N_PROTOCOL=http`: TLS terminates at Cloudflare while the add-on origin remains HTTP. The add-on forces the effective `N8N_SECURE_COOKIE=false` value at boot so the same installation remains browseable over direct HTTP and HA Ingress.

Cloudflare Tunnel supports WebSockets, so the editor's `/rest/push` connection works on the same public HTTPS hostname. This publishes the complete n8n entry point; protect the n8n owner account with a strong password. Cloudflare Access on the same hostname needs explicit bypass rules for public webhook paths.

The add-on also enables Home Assistant Ingress on port 5690. **Open Web UI** and the optional HA sidebar panel use this authenticated ingress adapter, including WebSocket and streaming support. The direct 5678 origin remains available for Cloudflare at the domain root, so both entrances work concurrently.

## Upgrading from 2.12.x to 2.43.x

Add-on 2.43.6 moves the bundled n8n from 2.12.3 to 2.43.6. Read this before you update.

- **The database migration is one-way.** On the first start n8n 2.43.6 migrates the database (workflows, credentials, executions) to its new schema. n8n 2.12.3 cannot use the migrated database, and there is no downgrade.
- **Make an add-on backup first.** In Home Assistant, take a backup that includes this add-on before updating (*Settings → System → Backups*, or tick *Backup before updating* in the update dialog). The backup holds both the n8n data in `/config` and the add-on's private `/data`.
- **Rollback means restoring that backup.** Installing the old add-on version on top of migrated data is not a rollback. Restore the pre-update backup instead; it brings back the 2.12.x add-on together with its unmigrated database.
- **Let the first start finish.** The first start can take several minutes on a large database. Do not stop or restart the add-on while the log shows `Migrations in progress, please do NOT stop the process.` The Supervisor watchdog reports the add-on as starting until n8n is ready for the first time, so it does not restart it in the middle of the migration (after one hour without becoming ready, the watchdog takes over again).
- **Re-create n8n API keys.** API keys created before the upgrade carry the scopes that existed when they were made; newer scopes (for example publishing workflows, from n8n 2.30) are missing, so some public API calls fail with 403. In n8n, open *Settings → n8n API*, create a new key with the scopes you need (*All*, *Read only* or *Custom*), update the tools that use it (for example the **Woow n8n MCP** add-on), then delete the old key.
- **Folders need a new key and a registered instance.** n8n 2.43's folder API (used by the Woow n8n MCP `n8n_manage_folders` tool) answers only to an API key that has the `folder:*` scopes, and only on an instance registered for the free Community features (*Settings → Usage and plan*). A key from 2.12 is refused even after registering.
- **Instance-level MCP (optional).** n8n 2.43 can expose its own MCP server: *Settings → Instance-level MCP → Enable MCP access*, choose the workflows to expose, and copy the access token from *Connection details*. The **Woow n8n MCP** add-on (0.2.1 and later) has an optional field for this token.

## Security notes

- **Supervisor token.** The add-on keeps `hassio_api` for its own start-up script, which is the only user of the Supervisor API. Once it has run, the token is removed from the container environment, and n8n, the task runners, nginx and Redis start without `SUPERVISOR_TOKEN` / `HASSIO_TOKEN`. Workflows can read it neither through `$env` nor from files or other processes in the container.
- **`$env` stays enabled.** `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` is kept so existing workflows that use `$env` keep working. Anyone who can edit workflows can read every variable you set under `env_vars`, including passwords and API tokens.
- **Code nodes are unrestricted.** The JavaScript and Python Code nodes may import any module and run as root inside the add-on container (unchanged, so existing workflows keep working). A user who can edit workflows can therefore read and change every file the add-on can reach (`/config`, `/data`, `/share`, `/media`), including n8n's database and its encryption key in `/config/.n8n`, which together reveal every stored credential. Give workflow-editing accounts only to people you would trust with those credentials, and use a strong owner password, particularly when the editor is published through Cloudflare.
- **Task broker.** The broker between n8n and its task runners only listens on `127.0.0.1` and uses a random token generated for each installation (`/data/n8n-runners-auth-token`, root-only, included in backups) instead of a shared constant.
- **Logs.** Option values whose name contains `PASS`, `PWD`, `SECRET`, `KEY`, `TOKEN`, `AUTH`, `CREDENTIAL`, `PRIVATE` or `DSN` (case-insensitive) are masked in the add-on log, and credentials embedded in URLs (`https://user:password@host`) are removed. Settings are no longer copied into `/.env`, `/etc/environment` or `~/.bashrc`.

## Prebuilt add-on images and release order

Supervisor pulls the versioned prebuilt image rather than building this add-on on the host: `ghcr.io/woowtech/woow-ha-n8n-amd64:X.Y.Z` or `ghcr.io/woowtech/woow-ha-n8n-aarch64:X.Y.Z`. The matching GHCR tag is required before that add-on version can install. Repository owners must keep both GHCR packages public because Supervisor does not supply registry credentials.

Every pull request runs the repository tests, builds the amd64 image and smoke-tests the container (**CI** workflow). Maintainers update `n8n/config.yaml` and `n8n/CHANGELOG.md`, merge the release version change to `main`, then wait for **Publish n8n add-on images** to run the same checks, publish both architecture tags and create the Release before announcing the update.

Published image tags are immutable: installed systems and backups refer to them by tag. The publish workflow refuses to overwrite an existing tag that was built from a different commit. To ship a fix, bump the version in `n8n/config.yaml`; never rebuild or re-push an existing version. Re-running the workflow on the same release commit is safe: it only publishes architectures that are still missing.

## Redis

Redis listens on `127.0.0.1` / `::1`, port `6379`, inside the add-on container only, without a password and with protected mode on. Use `localhost:6379` from workflows. It is not reachable from Home Assistant or other add-ons. `clean_redis: true` deletes the Redis dump (`/config/redis/dump.rdb`) at start-up.
