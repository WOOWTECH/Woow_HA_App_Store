# Woow Hermes Agent

[Hermes Agent](https://github.com/NousResearch/hermes-agent) by NousResearch, packaged from
[Woow_podman_hermes](https://github.com/WOOWTECH/Woow_podman_hermes) (the `slim` image).

## Entrances

| What | Where | Auth |
|---|---|---|
| Dashboard + chat terminal | Home Assistant sidebar (**Hermes**) | Home Assistant login, then the Hermes login |
| Dashboard + chat terminal | `http://<Home Assistant IP>:9119` | Hermes login |
| OpenAI-compatible API | `http://<Home Assistant IP>:8642/v1` | `Authorization: Bearer <Gateway API key>` |
| Webhook receiver | `http://<Home Assistant IP>:8644/webhooks/<route>` | HMAC with the webhook secret |

The sidebar and the LAN port run the same dashboard process with the same accounts, sessions,
chats, skills and settings. The sidebar goes through an adapter on port 9120 that only rewrites
URLs for the Home Assistant ingress path.

Browser-local preferences (theme, language) are stored per address, so the sidebar and the LAN
port keep their own. The LAN port is plain HTTP, so the browser disables clipboard access there.

## First start

Leave the password, API key and webhook secret empty. They are generated on the first start and
saved into the Configuration tab, where you can reveal them. Sign in with `admin` (or your
`dashboard_username`) and the dashboard password.

Provider keys (MiniMax, OpenRouter, GitHub) set here are written to Hermes only when you change
them, so keys you edit in the dashboard's Keys page are kept across restarts.

## Cloudflare Tunnel

With the Cloudflared add-on on the same Home Assistant, point public hostnames at the host ports:

```yaml
additional_hosts:
  - hostname: hermes-api.example.com
    service: http://homeassistant:8642
  - hostname: hermes-hook.example.com
    service: http://homeassistant:8644
```

Changing or disabling a host port in the Network tab breaks the matching tunnel rule.

The dashboard is not meant to be published. When you sign in to an MCP server with OAuth, the
provider sends your browser back to **Dashboard public URL**. Left empty, that is
`http://<Home Assistant IP>:9119`, which only works from the LAN. To sign in from anywhere, publish
only the callback path of the dashboard on the API hostname
(`^/api/mcp/oauth/callback/` → `http://homeassistant:9119`) and set **Dashboard public URL** to
`https://<api hostname>`.

Cloudflare limits apply to anything that goes through it, including the sidebar when Home
Assistant itself is reached through a tunnel: 100 MB request bodies and 125 s until the first
response byte (use `stream: true` for long completions).

## Web and browser tools

Web search uses DuckDuckGo (`ddgs`) and page extraction uses Parallel, both without an API key.
The browser tool drives the Chromium bundled in the image. The add-on sets these on start only
while they are empty, so a backend you pick in the dashboard stays.

## After installing

Turn on **Start on boot** and **Watchdog** on the add-on's Info tab. Home Assistant does not
switch them on for you.

## Known differences between the sidebar and the LAN port

- The sidebar and `http://<Home Assistant IP>:9119` keep separate logins. Signing in or out on one
  does not affect the other.
- The Webhooks page shows `http://localhost:8644/...`. Senders outside the add-on must use
  `http://<Home Assistant IP>:8644/webhooks/<route>` or the Cloudflare hostname.
- Through Cloudflare, a single upload is limited to 100 MB. Upload larger files on the LAN.

## Security

The agent runs shell commands with Hermes' default approval settings: low-risk commands run
directly, risky ones (deleting files, installing packages, `sudo`, piping downloads into a shell)
wait for you to approve them in the chat. Runs with nobody there to approve (scheduled jobs, the
OpenAI-compatible API and webhooks) refuse them. You can change this under Config in the
dashboard (`approvals.cron_mode`, `approvals.unattended_mode`). Anyone who can use the dashboard,
the API key, or a webhook route that triggers the agent can still run the commands that need no
approval.

Upstream Hermes auto-approves those risky commands in unattended runs, because its gateway runs in
ask mode; the add-on patches that so the deny settings apply. The add-on removes the Supervisor token from
the agent's environment. Home Assistant backups of this add-on contain its secrets and
conversation history.

Keep the generated dashboard password, or use an equally long random one. Hermes limits wrong
login attempts per client address, but it takes that address from a header the client can set, so
on the LAN port the limit can be sidestepped. A long random password cannot be guessed either way.

## Data

Hermes' home (`/opt/data`) is the add-on's config folder, `/addon_configs/<slug>/`. It is in the
add-on backup, except `logs`, `lazy-packages`, `.cache` and `.npm`. Backups are cold: Hermes stops
while the backup runs.

## Memory

Home Assistant cannot limit an add-on's memory. Hermes with a browser session can use 3-6 GiB;
the log warns when less than 4 GiB is available at start.


## Upgrading to add-on 0.1.10 / Hermes 0.22.5

The data mount, add-on options, ports and dashboard credentials are preserved.
Take a Home Assistant backup before upgrading; restore that backup to roll back
upstream database migrations.

Home Assistant's former core integration is now the official `homeassistant`
plugin. Upstream gateway startup detects an existing `HASS_TOKEN`, enabled
`platforms.homeassistant`, or selected Home Assistant toolset and attempts the
catalog migration. It retains `HASS_TOKEN`, `HASS_URL`, platform configuration
and `ha_*` tool names. Automatic installation requires network access and
`security.allow_lazy_installs`; an intentionally removed plugin is not silently
reinstalled after a successful migration.

If the integration is missing after upgrade, open Settings > Plugins and
install/enable **Home Assistant**, or use `hermes plugins install homeassistant`
for the affected profile. Check the plugin's dependency-install result and
connection status. Existing valid credentials can be reused; reconnect or issue
a new Home Assistant token only if the existing credentials no longer work.
Fresh installs should configure this integration explicitly. The HA Supervisor
bootstrap token remains isolated from Hermes and is not an integration token.

MoA is still available as a model provider with named presets (`hermes moa` and
`/moa`); it is no longer a core toolset to enable with `hermes tools enable moa`.
The add-on does not start `hermes mcp serve`; the separately packaged WOOW MCP
bridge continues to use the HTTP gateway API.

OAuth issuer validation now follows upstream. A server that advertises one
issuer but returns another must correct its OAuth metadata or callback, then
be reconnected. The old permissive issuer override is not reapplied.
