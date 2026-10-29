# Woow HA OpenDesign

## Configuration

This add-on intentionally has no options. Configure providers in the OpenDesign UI, not in Home Assistant.

Use OpenDesign's native **API BYOK** controls in Settings. Provider, model, and API-key values remain only in that administrator browser's localStorage; they are not written to `/data`, add-on options, logs, or Home Assistant cold backups. Re-enter settings in each browser after clearing browser storage.

## Access and persistence

Use **Open Web UI** or the **OpenDesign** sidebar item. **Open Web UI** enters the native **Plugins** page so Omnigent can be opened from its card. OpenDesign itself is ingress-only; the only declared LAN port is the optional built-in MCP endpoint below, which is not mapped unless you map it.

Projects, the OpenDesign database, application configuration, connector data, and generated state are stored beneath `/data/opendesign`. API BYOK credentials are deliberately excluded. The add-on requests cold backup so this directory is captured while the service is stopped.

## Trust and network exposure

- **Who can reach the add-on.** Port 8099 is the Ingress port and is not published. nginx admits only the Supervisor (`172.30.32.2`, which carries Ingress and the watchdog probe) and processes inside the container (`/mcp-admin` and the Paseo routes admit only the Supervisor); every other container on the Home Assistant network, and Home Assistant Core itself, is refused with HTTP 403 on every content route (five redirect-only routes answer with a bare redirect and show nothing). Home Assistant authenticates the person who opens the sidebar entry, and because the panel is declared admin-only (`panel_admin: true`) Supervisor and Home Assistant refuse everyone who is not an administrator; the add-on itself has no separate sign-in or administrator check, so Ingress is the access control. The check in nginx is on the source address inside the Home Assistant Docker network; it is not a credential. Anything that used to call port 8099 directly (a reverse proxy or tunnel add-on, a script in another add-on) now gets 403: use the sidebar entry. If the sidebar entry itself shows 403 after an update, look in the add-on log for `access forbidden by rule` lines: the `client:` address is the peer nginx refused.
- **The terminal is a shell.** The **CLI Terminal** plugin (`/console/`) is a writable login shell as the add-on's agent user (UID 1001) with that user's provider logins; anyone who may open the add-on panel may use it. The agents (and every Omnigent session) run as that same user. Since 0.2.12 they can no longer rewrite the scripts that nginx adds to OpenDesign's pages for Home Assistant (`/opt/ha-opendesign`), but the OpenDesign web application and daemon in the core image are still writable by that user, and the daemon runs as that user too, so treat an agent with a shell as able to change what the add-on serves through Ingress; this release does not change that.
- **Ingress shares Home Assistant's web origin.** Home Assistant serves the add-on under its own address, so scripts the add-on serves run in the Home Assistant web origin and can reach the signed-in administrator's session. Whoever can change what the add-on serves (an agent with the terminal, an Omnigent session) is therefore trusted with Home Assistant itself, not only with this add-on's data.
- **Connecting an Omnigent server.** Connecting means anyone who can start sessions for this host on the Omnigent server can run Claude Code, Codex, Pi or OpenCode on this add-on: shell-equivalent access as UID 1001 to the OpenDesign data (projects, provider logins, Omnigent state). There is no directory allow-list on this side. Use a dedicated, non-admin Omnigent account for this add-on and connect only servers you control.
- **Disconnect and backups.** **Disconnect** removes this add-on's local login; it does not revoke the login grant on the Omnigent server (grants live for the lifetime the server sets). Revoke the login on the Omnigent server too, especially before discarding the add-on or a backup; the host record also stays on the server, shown offline. Backups contain the Omnigent identity and login, so treat them as credentials and keep Home Assistant backups encrypted and private.

## Built-in MCP server

The add-on includes the Woow OpenDesign MCP server (it replaces the separate *Woow OpenDesign MCP Server* add-on). It always runs and always talks to this add-on's own OpenDesign; there is no connection to configure and no option to turn it off.

- **Administration:** under OpenDesign's **Plugins → Expert suites → Personal**, click **Open** on the built-in **MCP Server** plugin (it opens a new tab), or open `<the add-on's Ingress page>/mcp-admin/`. There you reveal, rotate or revoke the token, choose which tools are enabled, and record the client endpoint. Since 0.2.4 it also shows each tool's accepted arguments and whether the server really offers it, checks the connection to OpenDesign, restarts the MCP tool process and shows its recent output (in memory only, with tokens and passwords removed). Since 0.2.6 it also shows whether the saved settings have been applied to the MCP tool process, and a change saved elsewhere after you opened the page must be reloaded before you save again. Access is the add-on's Home Assistant Ingress login, the same as OpenDesign and its terminal: there is no separate administrator check, so any Home Assistant user who can open this add-on can reach this page.
- **LAN clients (Claude Code, Claude Desktop via a local bridge, other MCP clients):** map a host port to container port `8081/tcp` in the add-on's **Network** settings (unmapped by default), then connect to `http://<HA host>:<port>/mcp` with the header `Authorization: Bearer <token>`. Other add-ons on the Home Assistant network (for example a Cloudflare tunnel add-on) can reach `http://<this add-on's hostname>:8081/` without a host port.
- **Claude.ai custom connectors:** expose port 8081 through an HTTPS tunnel (for example Cloudflare) and use the connector URL shown on the administration page: `https://<tunnel host>/private_<token>/mcp`. Treat that URL like the token itself.
- **Tools:** the same 15 tools as the WOOW PaaS OpenDesign MCP, **all on by default**. An administrator can turn any of them off on the administration page.
  - Reads: `health`, `version`, `list_agents`, `list_connectors`, `list_projects`, `get_project`, `list_project_files`, `get_file_info`, `read_file`, `list_runs`, `list_plugins`, `list_skills`.
  - Writers: `create_project` and `send_message` start an OpenDesign agent run (Claude Code, Codex, OpenCode...). **A run uses the model credits of the account that agent is signed in to, and the agent can create and change files in the project.** `delete_project` permanently deletes a project and its files. Anyone holding the MCP token can do all of this; turn the writers off if your clients only need to read.
  - Bounds of this add-on (the PaaS server has none of them): `read_file` reads only files that `list_project_files` shows, refuses hidden files and secret-like names (`.env*`, `*.pem`, `*.key`, `id_*`, `*credential*`, `*secret*`, `*password*`...) and binary files, and returns at most 1 MiB of UTF-8 text. `list_connectors` returns only ids, names, provider, category, status, whether a connector is configured and its tool names. `create_project`/`send_message` follow a run for about 75 seconds; a longer run continues in OpenDesign and the tool answers `status: "running"` (check `list_runs` later). Their result is `projectId`, `runId`, `status`, the agent's text (shortened) and, on failure, a public `errorCode` with a hint, never paths or raw agent errors. At most two runs are followed at a time; `send_message` needs an existing project; prompts are limited to 20,000 characters.
  - An agent must be signed in (CLI Terminal) or configured in OpenDesign first; otherwise the run fails at once with `AGENT_AUTH_REQUIRED`. `byok-opencode` needs the provider settings that OpenDesign keeps in the administrator's browser, so it cannot be started over MCP. Note: OpenDesign's `opencode` agent can run without any sign-in (observed on a test system with no provider credentials: it answered), so a writer call with `agent_id: "opencode"` reaches an outside model service even when nothing is configured.
  - Updating from 0.2.0: at the first start, 0.2.1 grants `create_project`, `delete_project` and `send_message` once, except a tool you had disabled, and records this in `/data/mcp/ha-tool-defaults.json`. Later changes on the administration page are kept. Going back to 0.2.0 requires restoring the backup taken before the update (0.2.0 cannot read 0.2.1's grants).
- **Sessions:** a client session that sees no request for 30 minutes ends; the client's next request gets 404 and the client initializes a new session (MCP clients do this themselves). At most 10 000 sessions exist at a time.
- **Protocol (0.2.6, MCP Python SDK 2.3):** clients connect with the MCP 2025 handshake (protocol revisions 2024-11-05 to 2025-11-25). A client that first tries the 2026-07-28 revision's `server/discover` (Claude.ai, the MCP Python SDK 2 client) gets "Method not found" and falls back to that handshake on its own. Requests may be up to 16 MiB; a tool call may take up to 330 seconds (`create_project`/`send_message` still follow a run for about 75 seconds).
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

The container starts a minimal root PID 1 because Home Assistant mounts `/data` as root at runtime. It creates and assigns only add-on-owned directories, safely removes the withdrawn `/data/opendesign/credentials` path without following symlinks, then launches OpenDesign and a loopback-only `ttyd` login terminal through `su-exec` as UID/GID 1001, nginx as its own UID `ha-ingress` (1002), and the built-in MCP server, which drops itself to UID `mcp` (10001). None of them inherits the Supervisor token. Only authenticated HA Ingress can reach the terminal route; its shell uses the persistent OpenDesign home so CLI authentication survives restarts.

CI validates and smokes every build before architecture work. Pull requests and `main` build without pushing under `contents: read`; only a `main` run for a `config.yaml` version that has no Release yet (that is, a merged version-bump pull request) starts a publisher with `packages: write`; pushing a Git tag publishes nothing. Its preflight fails closed unless the amd64 version tag is absent from GHCR; the App Store's shared workflow then creates the `v<version>` tag and Release on that commit. Version tags are immutable: a failed release cannot be retried over the same version and requires another version-bump pull request. The image is amd64 only, like the core. This add-on targets the w2.10 core image (`ghcr.io/woowtech/open-design-core:20261029.0033`, the same digest that 0.2.10 pinned as `20261027.1127`) by digest. `build.yaml` uses the matching tag because Supervisor's local builder rejects digest syntax there and otherwise silently substitutes its default base image. Verify that the public tag resolves to the pinned digest before building or merging.

## Native API BYOK and OpenCode

The core image provides OpenCode `1.18.33`. OpenDesign's native API BYOK flow uses its `byok-opencode` runtime and discovers this executable on `PATH`. A first run after installation downloads OpenCode's model catalog once; on slow networks that first answer can take a minute. Configure the provider, model, and API key in the upstream Settings UI; those values are browser-local and are not persisted by the add-on. Clearing browser storage or using another browser requires fresh entry.

The core image also provides Claude Code `2.1.296`, Codex CLI `0.162.1`, and Pi Coding Agent `1.1.0` on `PATH` for OpenDesign's Local AI discovery. The add-on build checks each version under UID 1001; the add-on does not reinstall these provider CLIs on startup. The shared core also supplies the native Paseo launcher. Users can open Local AI and rescan after updating the add-on image. Use the built-in **CLI Terminal** plugin (**Plugins → Expert suites → Personal**; `<Ingress>/console/`) for interactive provider sign-in. OpenDesign's own Plugins page and daemon-managed Skill staging provide the same selected plugin/Skill context to its supported agent adapters.

## Omnigent plugin

Available since 0.2.10 on the w2.10 core `20261029.0033` (first published as `20261027.1127`) / `sha256:c8cd57f07adaef23b8dddbb22a8b75f97bdf8ca42c8bfbec1b284dc60ee5a4cf`. The settings pages reload through Ingress (a browser reload returns the page instead of an HA 404), Pi custom models are listed, and **Configure** opens the setup in a daemon-created onboarding conversation. It was accepted on Home Assistant OS: upgrade from the previous build, Ingress reload, fresh and restored connection, and native backup restore.

Choose **Open Web UI → Plugins → Omnigent → Open → Configure**. The native GUI asks for the Omnigent HTTPS server URL, username and password. It discovers only the four engines already in the image: Claude Code, Codex, Pi and OpenCode. Their provider sign-ins are separate; the integration does not install missing provider engines. Complete setup to see available models/modules and the real reply/stop verification results. No Omnigent credentials go into HA add-on options.

The native OpenDesign daemon owns the host and its lifecycle. The HA launcher continues to start OpenDesign directly and waits for its shutdown; there is no second `/etc/omnigent-host` supervisor. The chart's legacy `omnigentHost.enabled=false` remains correct. Native state lives in `/data/opendesign/integrations/omnigent/state.json`, with private host configuration, identity and tokens under `/data/opendesign/integrations/omnigent/host/`. The service derives this from `OD_DATA_DIR`. HA does not set a global `OMNIGENT_CONFIG_HOME`; the launcher clears inherited legacy `OMNIGENT_CONFIG_HOME`, `OMNIGENT_DATA_DIR` and `OG_*` location overrides before starting children.

- **First use or upgrade from the retired integration:** enter fresh credentials in the GUI. Neither the old `/data/opendesign/home/.omnigent` nor `/data/opendesign/.backup/omnigent-*` is restored, copied, moved again or adopted automatically. Existing legacy projects also remain. Archived login tokens are still sensitive; delete their archives yourself when no longer needed.
- **Restart or upgrade after new setup:** retain `/data`. The daemon keeps the new host identity and approved configuration and resumes the confirmed local host without opening a browser. The launcher no longer retires Omnigent state at each boot.
- **Disable / re-enable / disconnect:** disabling stops the daemon-managed host; re-enabling requires fresh GUI sign-in. Disconnect clears login approval and stops the host. Restarts preserve a disabled choice.
- **Cold backups:** `/data` includes both new Omnigent tokens/identity and any old archives, as well as MCP credentials. It does not include browser-local API BYOK keys. Treat the backup as a credential-bearing archive. Stop the original host before restoring the same identity elsewhere; concurrent copies must not both connect. Restore repairs OpenDesign ownership to UID/GID 1001. For rollback to a release without this integration, restore the backup taken before the upgrade; that older release cannot operate the new native integration.

### Candidate verification and release handoff

Before the stable release, verify the approved public core digest, review core CLI versions, and run `tests/run.sh`. On an isolated Docker builder, build the HA image and run `tests/container-smoke.sh <candidate-image>`. This mandatory smoke checks the real native daemon's fresh-login/disable/enable behavior, only-four-engine inventory, persisted disable state across container recreation and root ownership restore, and the real GUI form through the Supervisor-style ingress proxy, alongside existing MCP, terminal, BYOK and export checks. It never submits valid service credentials. Future core updates should use `.github/scripts/pin-core.sh <YYYYMMDD.HHMM> <sha256:digest>` to keep every build input aligned.

For authenticated acceptance, the coordinator can run:

```sh
./tests/omnigent-connected-smoke.sh <candidate-image> /private/test-login.json /private/provider-home [next-candidate-image]
```

The file must be mode `0600` with JSON keys `server`, `username`, `password`. Supply a third argument: a private directory containing the authorized Claude/Codex login files and Pi/OpenCode provider configuration, in their normal HOME-relative paths. `tests/validate-omnigent-provider-fixture.py` lists the accepted files and rejects symlinks, extra files, public permissions and any legacy Omnigent state. An Omnigent account alone does not configure local engines. The optional upgrade image is the fourth argument.

The harness creates only its own containers and volumes, mounts the credential file read-only, publishes no ports, prints no raw logs/responses, and removes its local resources afterwards. Provider files seed only the disposable HOME; they never enter the image or repository. It performs actual setup through the native API, requires real reply and stopped-session receipts for all four engines, checks one UID-1001 managed host, restarts before polling status (to prove automatic resume), archives cold `/data` and restores it to a separate volume with root ownership, optionally changes to a newer candidate image, then checks disable/re-enable/new login/disconnect and graceful host stop. It can incur model usage and leaves test-account host/session history. This is Docker packaging acceptance; actual HA Supervisor install/Ingress/backup/fresh restore acceptance remains a separate release gate.

The launcher allows 35 seconds for daemon/host cleanup; Supervisor's `timeout: 45` leaves an outer margin before it kills the container. This uses the [standard Supervisor stop timeout](https://contributors.home-assistant.io/apps/reference/configuration/).

The existing **Validate, build, and publish** workflow publishes a uniquely tagged, tested candidate from a **non-main branch** when supplied an immutable core:

```sh
gh workflow run build.yml --repo WOOWTECH/Woow_ha_opendesign_add_on \
  --ref <candidate-branch> \
  -f candidate_core_image="jcr-prod.woowtech.io/woow-paas-docker-local/open-design-core:<tag>-pending-approval@sha256:<digest>"
```

This branch-only path runs validation and full container smoke before publishing a unique `<version>-rc.<run>.<attempt>` image, verifies anonymous GHCR access, and records its source/core/image digest in the `ha-candidate-receipt` artifact. It does not create a stable Release or notify the Store. An imported immutable GHCR core is also accepted. Omitting the input runs ordinary checks against the checked-in approved core.

`tests/container-smoke.sh` creates a Docker network with the subnet `172.30.32.0/23` (Supervisor's hassio network, so that traffic from the host reaches nginx from `172.30.32.2` like Ingress traffic) and needs that subnet to be free: do not run it in parallel with `mcp-runtime/tests/e2e/run-proof.sh`, and not on a host that already has a Docker network with it. Outside Home Assistant, `docker run -p 8099:8099 <image>` makes every request arrive from the Docker bridge gateway instead of `172.30.32.2`, so every request is refused with 403.

After actual HA acceptance and the final version-bump PR merge, the existing immutable image → Release → Store notification/synchronization path remains authoritative. Store and Local Download must consume the released source/version and image digest; confirm their source SHA and catalog receipts after synchronization.

## Troubleshooting

- **Add-on stays in `error` after restoring a backup (`SQLITE_READONLY` in the log):** update to at least 0.2.2. A Home Assistant restore returns `/data` without its file owners; from 0.2.2 the add-on hands them back to OpenDesign at every start and logs `returned N path(s) under /data/opendesign to open-design`.
- **Stuck at “Loading OpenDesign…”:** reload without cache and confirm the add-on is at least 0.1.1. The Next/Turbopack runtime and escaped RSC chunk references both require ingress-prefix rewriting; the container browser smoke locks this boot path down.
- **Settings or Design systems changes the URL but not the page:** update to at least 0.1.2. OpenDesign route logic must see logical paths without HA's transport-only ingress prefix.
- **Blank page or missing assets:** restart the add-on, then reload the HA page without cache. Report the missing root-relative URL and add-on logs; ingress adaptation is coupled to the pinned OpenDesign version.
- **Generation cannot authenticate:** check the browser-local API BYOK provider, model, and key in Settings.
- **Key disappeared:** browser-local API BYOK settings are intentionally not backed up or shared. Re-enter them in Settings.
- **Editable PPTX fails:** expected. Choose the screenshot/image PPTX mode.
- **Image/PDF export says renderer failed:** check logs for Chromium errors and reduce page dimensions/length.
- **The sidebar entry shows 403 after updating to 0.2.12 or later:** nginx admits only the Supervisor (`172.30.32.2`) and processes inside the container. Open the add-on **Log** and look for `access forbidden by rule` lines: the `client:` address is the peer nginx refused. `172.30.32.2` must never be refused, so please report it; any other address is another container or add-on that used to call port 8099 directly and must use the sidebar entry instead.
- **Watchdog restart:** if nginx, OpenDesign, the terminal or the built-in MCP server exits, the launcher deliberately stops the others and exits so Supervisor can restart them together. Supervisor does this only when **Watchdog** is on (add-on **Info** tab); Home Assistant leaves it off for newly installed add-ons. With Watchdog off the add-on stays in `error` until you start it again.
- **Browser developer tools show `GET /api/amr/models` 500 and `GET /api/integrations/vela/status` 503 on page load:** expected. They belong to upstream OpenDesign's optional AMR runtime (the proprietary `vela` CLI), which the WoowTech core image does not ship, in the add-on or on the PaaS. Upstream defines `503 {"error":"amr-runtime-unavailable"}` as the authoritative "no AMR runtime" answer and returns `500 {"error":"AMR vela binary could not be resolved"}` for the model list (its own startup smoke test accepts 200 or 500). The web UI already handles both (the AMR model list comes back empty and the AMR sign-in check reads "not signed in"); other agents, BYOK, exports and MCP are not affected. To use AMR, the `vela` runtime would have to be provided separately.
- **MCP client gets 404 after a pause:** its session was idle for 30 minutes and has ended; the client must initialize again (most clients reconnect on their own).
- **MCP client gets 401:** the token was rotated or revoked; copy the current one from **MCP Server**. A browser-style request with an `Origin` header to `/mcp` is refused (403) by design; Claude.ai uses the `/private_<token>/mcp` URL instead.


## Paseo setup and persistence

From OpenDesign **Plugins → Expert suites → Personal**, open **Paseo**. The native
launcher opens a new tab inside this add-on's Home Assistant Ingress prefix.
Home Assistant login is required. There is no extra admin-role check beyond
access to this add-on's Ingress, matching the built-in MCP administration policy.

**← 返回 OpenDesign** returns to the native Home Assistant app page; select
Plugins there to open Paseo again. It does not deep-link into the Plugins page.
If startup cannot read its own app metadata, the link is instead
**← 返回 Home Assistant** and opens Home Assistant's root page. Metadata lookup
is bounded to three seconds, uses no environment proxy or redirects, and never
passes the Supervisor token or app options to the browser or service children.

On first start, the managed service downloads its pinned Paseo execution
packages and creates a marked **Paseo 連線初始化** project/conversation. The same
conversation is reconciled on later starts. This step requires outbound access
to the package registry; installation progress/errors appear in setup. Existing
OpenDesign projects, MCP entries and provider homes are retained on upgrade.

Select Claude Code, Codex or Pi, complete that provider's official login, read
its models, and run the two-turn conversation test. A fresh installation has no
provider credentials. A running daemon, model list or pairing link is not proof
of a successful model conversation or completed official App pairing.

**停止服務** persists the disabled intent. Restarting the add-on does not enable
it again; **安裝並啟動** resumes it. The bridge itself stays supervised and available
while Paseo is stopped. The add-on gives required processes up to 25 seconds to
shut down inside Supervisor's 30-second timeout.

Paseo state and installed runtime packages live under `/data/opendesign/paseo`;
provider credentials remain in `/data/opendesign/home`, shared with native
OpenDesign agent tools. Source material may also live in that home's
`.local/share/opendesign-paseo`. Cold HA backups retain these directories,
including CLI credentials, projects, conversations, daemon identity and the
saved enabled/disabled choice. They exclude only
`/data/opendesign/paseo/packages/runtime`, the downloaded Paseo execution
packages. Home Assistant's native `backup_exclude` prunes that subtree before
archiving, anchored to Supervisor's `/data/apps/data/<slug>` (or legacy
`/data/addons/data/<slug>`) root so identically named user project directories
are retained. Its npm binary hardlinks can otherwise fail Supervisor's streaming
restore. Provider installations and `packages/npm-cache` remain in the backup.

After restore, an enabled service rebuilds the missing packages from the
image's exact bundled lock using `npm ci`, then checks the CLI version and web
UI before starting Paseo. A manually stopped service stays stopped; selecting
**安裝並啟動** performs the same rebuild. The installed-version record alone is
not treated as proof that package files exist. Restore therefore requires
outbound access to the package registry and any locked package download hosts.
The retained npm cache may reduce downloads, but offline recovery is not
guaranteed. A failed install retains the enabled intent and the supervisor
retries with a bounded delay; setup reports installation errors. Restoring
connectivity allows recovery without deleting credentials or user state.
This exclusion applies to newly created backups; it does not repair an older
archive that already contains those hardlinks. The
bridge code is immutable image content at `/opt/opendesign-paseo`; its private
socket under `/run/ha-opendesign-paseo` is recreated at start. No bridge port is
mapped to the LAN, and Supervisor tokens are removed before every child starts.

The proxy permits Paseo requests only from the actual Supervisor peer
172.30.32.2. It supplies the authenticated user and validated Ingress prefix to
the Unix-socket bridge, preserves browser Host/Origin/Referer, and discards
forwarded-header claims. Mutations require the exact same-origin setup page.
Do not bypass that proxy or expose the socket. The setting page supports both
local HTTP Home Assistant and HTTPS; login/pairing links stay external and do
not receive an Ingress referrer.

Release maintainers: see [the 0.2.7 packaging/release gate](docs/paseo-release.md).


### 還原後的 CLI 憑證權限

啟動時會在 UID 1001 下收緊 `.codex/auth.json`、`.codex/config.toml`、
`.claude/.credentials.json`、`.claude/settings.json`、`.pi/agent/auth.json`、
`.pi/agent/models.json`、`.pi/agent/settings.json`、OpenCode 的
`.config/opencode/opencode.json`、`.config/opencode/opencode.jsonc` 與
`.local/share/opencode/auth.json` 為 `0600`，並將 `.codex`、`.claude`、`.pi`、
`.pi/agent`、`.config/opencode`、`.local/share/opencode` 設為 `0700`。
共享父目錄 `.config`、`.local`、`.local/share` 及未列出的 provider 路徑不會被 chmod。
檔案內容（包含 JSONC 註解）與專案權限不會改動，
不存在的設定不會被建立。這補足原生還原可能帶回 `0644` 權限的情況。
這些是持久化 HOME 中的 CLI 設定／登入資料；瀏覽器內的 API BYOK 設定仍不在備份中。

這些私有路徑必須是一般目錄與單一 hard link 的一般檔案。遇到 symlink、多重
hard link 或其他非一般檔案時會拒絕啟動；每一層祖先目錄也拒絕 symlink，
避免將權限修正套用到外部目標。
