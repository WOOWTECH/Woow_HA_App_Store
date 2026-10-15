# Woow HA OpenDesign

## Configuration

This add-on intentionally has no options. Configure providers in the OpenDesign UI, not in Home Assistant.

Use OpenDesign's native **API BYOK** controls in Settings. Provider, model, and API-key values remain only in that administrator browser's localStorage; they are not written to `/data`, add-on options, logs, or Home Assistant cold backups. Re-enter settings in each browser after clearing browser storage.

## Access and persistence

Use **Open Web UI** or the **OpenDesign** sidebar item. OpenDesign itself is ingress-only; the only declared LAN port is the optional built-in MCP endpoint below, which is not mapped unless you map it.

Projects, the OpenDesign database, application configuration, connector data, and generated state are stored beneath `/data/opendesign`. API BYOK credentials are deliberately excluded. The add-on requests cold backup so this directory is captured while the service is stopped.

## Built-in MCP server

The add-on includes the Woow OpenDesign MCP server (it replaces the separate *Woow OpenDesign MCP Server* add-on). It always runs and always talks to this add-on's own OpenDesign; there is no connection to configure and no option to turn it off.

- **Administration:** click **MCP Server** (bottom right of the OpenDesign page, next to **CLI Terminal**; it opens a new tab), or open `<the add-on's Ingress page>/mcp-admin/`. There you reveal, rotate or revoke the token, choose which tools are enabled, and record the client endpoint. Access is the add-on's Home Assistant Ingress login, the same as OpenDesign and its terminal: there is no separate administrator check, so any Home Assistant user who can open this add-on can reach this page.
- **LAN clients (Claude Code, Claude Desktop via a local bridge, other MCP clients):** map a host port to container port `8081/tcp` in the add-on's **Network** settings (unmapped by default), then connect to `http://<HA host>:<port>/mcp` with the header `Authorization: Bearer <token>`. Other add-ons on the Home Assistant network (for example a Cloudflare tunnel add-on) can reach `http://<this add-on's hostname>:8081/` without a host port.
- **Claude.ai custom connectors:** expose port 8081 through an HTTPS tunnel (for example Cloudflare) and use the connector URL shown on the administration page: `https://<tunnel host>/private_<token>/mcp`. Treat that URL like the token itself.
- **Tools:** read-only by default (health, version, agents, projects, project files, file info, plugins, skills, runs). `delete_project` is off until an administrator grants it. Agent runs (`create_project`, `send_message`), raw file reads and connector listings are not offered.
- **State:** `/data/mcp` (token, tool policy), included in the add-on's cold backup. A backup therefore contains the MCP token; rotate it after restoring a backup onto another system.
- **Moving from the separate MCP add-on:** the built-in server has its own new token. Update each client's URL and token, then uninstall *Woow OpenDesign MCP Server*. If that add-on had host port 8081 mapped, uninstall it first or map a different host port here.

## Exports

| Format | Support |
|---|---|
| Standalone HTML | Supported by OpenDesign |
| Project ZIP | Supported by OpenDesign |
| PNG / JPEG | Supported; the HA image dialog is bridged to `/export/image` |
| Screenshot PDF | Supported; the HA PDF action is bridged to the binary `/export/pdf-image` download |
| Screenshot PPTX | Supported; choose screenshot mode for one full-slide image per PowerPoint slide |
| Editable PPTX | **Unsupported**; the renderer returns an explicit error |

The add-on does not inject the desktop vector-PDF exporter: upstream's browser client interprets that endpoint as a desktop save and would download nothing. The narrow HA bridge instead redirects the existing browser PDF request to the screenshot PDF endpoint and triggers a normal browser download. The image bridge intercepts only PNG/JPEG saves; other upstream browser formats retain their upstream behavior.

Rendering is serialized and bounded by an absolute two-minute deadline, 64 slides, aggregate pixel/output-byte limits, canonical output-path confinement, capped remote-resource concurrency/bytes, and a network policy. Each remote-resource permit is held from DNS policy evaluation through pinned fetch completion, preventing model-authored HTML from starting unbounded DNS lookups. CJK and color emoji fonts are installed in the image. Oversized decks and pages fail with a bounded-size error instead of exhausting add-on memory. Renderer documents can load inline `data:`/`blob:` resources, project assets from the exact OpenDesign origin, and public HTTP(S) resources after DNS/IP validation and pinned connection. WebSockets are disabled; Supervisor, link-local, private, CGNAT, and other loopback destinations are blocked to keep model-authored HTML from reaching the HA network.

## Runtime ownership and release policy

The container starts a minimal root PID 1 because Home Assistant mounts `/data` as root at runtime. It creates and assigns only add-on-owned directories, safely removes the withdrawn `/data/opendesign/credentials` path without following symlinks, then launches OpenDesign (through the omnigent-host kit launcher) and a loopback-only `ttyd` login terminal through `su-exec` as UID/GID 1001, nginx as its own UID `ha-ingress` (1002), and the built-in MCP server, which drops itself to UID `mcp` (10001). None of them inherits the Supervisor token. Only authenticated HA Ingress can reach the terminal route; its shell uses the persistent OpenDesign home so CLI authentication survives restarts.

CI validates and smokes every build before architecture work. Pull requests and `main` build without pushing under `contents: read`; only an exact `v<config-version>` tag starts a publisher with `packages: write`. Its preflight fails closed unless the amd64 version tag is absent from GHCR. Version tags are immutable: a failed release cannot be retried over the same version and requires a version bump plus a new matching Git tag. The image is amd64 only, like the core. Dockerfile and CI/release inputs pin the WoowTech core image (`ghcr.io/woowtech/open-design-core`) by digest; `build.yaml` uses a tag because Supervisor's local builder rejects digest syntax there and otherwise silently substitutes its default base image. Until the core digest is published both are deliberate placeholders, and builds pass `BUILD_FROM`.

## Native API BYOK and OpenCode

The core image provides OpenCode `1.18.33`. OpenDesign's native API BYOK flow uses its `byok-opencode` runtime and discovers this executable on `PATH`. A first run after installation downloads OpenCode's model catalog once; on slow networks that first answer can take a minute. Configure the provider, model, and API key in the upstream Settings UI; those values are browser-local and are not persisted by the add-on. Clearing browser storage or using another browser requires fresh entry.

The core image also provides Claude Code `2.1.296`, Codex CLI `0.162.1`, and Pi Coding Agent `1.1.0` on `PATH` for OpenDesign's Local AI discovery. The add-on build checks each version under UID 1001; the add-on does not install them on startup or inject a Paseo plugin. Users can open Local AI and rescan after updating the add-on image. Use the **CLI Terminal** entry for interactive provider sign-in. OpenDesign's own Plugins page and daemon-managed Skill staging provide the same selected plugin/Skill context to its supported agent adapters.

## Omnigent host

The add-on carries the shared WOOW `omnigent-host` kit (byte-identical to `woow-paas-charts` `shared/omnigent-host`, verified against `rootfs/etc/omnigent-host/KIT.sha256`). Its supervisor runs next to OpenDesign as UID 1001 and only waits until you log in to an Omnigent server: use OpenDesign **Plugins → Omnigent** (the native connection dialog), or run `omnigent login <server-url>` in the CLI Terminal. The host then dials out to that server and stays connected across restarts. Login, host identity and logs live in `/data/opendesign/home/.omnigent` (cold backups include the stored login). Sessions start in `/data/opendesign/home/studio`. `omnigent-host-status` in the CLI Terminal shows the state. The machine appears in Omnigent as **Home Assistant OpenDesign**; telemetry is off.

## Troubleshooting

- **Stuck at “Loading OpenDesign…”:** reload without cache and confirm the add-on is at least 0.1.1. The Next/Turbopack runtime and escaped RSC chunk references both require ingress-prefix rewriting; the container browser smoke locks this boot path down.
- **Settings or Design systems changes the URL but not the page:** update to at least 0.1.2. OpenDesign route logic must see logical paths without HA's transport-only ingress prefix.
- **Blank page or missing assets:** restart the add-on, then reload the HA page without cache. Report the missing root-relative URL and add-on logs; ingress adaptation is coupled to the pinned OpenDesign version.
- **Generation cannot authenticate:** check the browser-local API BYOK provider, model, and key in Settings.
- **Key disappeared:** browser-local API BYOK settings are intentionally not backed up or shared. Re-enter them in Settings.
- **Editable PPTX fails:** expected. Choose the screenshot/image PPTX mode.
- **Image/PDF export says renderer failed:** check logs for Chromium errors and reduce page dimensions/length.
- **Watchdog restart:** if nginx, OpenDesign, the terminal or the built-in MCP server exits, the launcher deliberately stops the others and exits so Supervisor can restart them together. Supervisor does this only when **Watchdog** is on (add-on **Info** tab); Home Assistant leaves it off for newly installed add-ons. With Watchdog off the add-on stays in `error` until you start it again.
- **MCP client gets 401:** the token was rotated or revoked; copy the current one from **MCP Server**. A browser-style request with an `Origin` header to `/mcp` is refused (403) by design; Claude.ai uses the `/private_<token>/mcp` URL instead.
