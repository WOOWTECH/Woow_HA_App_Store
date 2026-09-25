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

The dashboard is not meant to be published. To sign in to MCP servers with OAuth from anywhere,
publish only the callback path of the dashboard on the API hostname
(`^/api/mcp/oauth/callback/` → `http://homeassistant:9119`) and set **Dashboard public URL** to
`https://<api hostname>`.

Cloudflare limits apply to anything that goes through it, including the sidebar when Home
Assistant itself is reached through a tunnel: 100 MB request bodies and 125 s until the first
response byte (use `stream: true` for long completions).

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
wait for you to approve them in the chat, and scheduled jobs refuse them because nobody is there to
approve. You can change this under Config in the dashboard. Anyone who can use the dashboard, the
API key, or a webhook route that triggers the agent can still run the commands that need no
approval. The add-on removes the Supervisor token from
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
