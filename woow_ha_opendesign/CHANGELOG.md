# Changelog

## 0.2.11

- Update the bundled Paseo runtime from 0.2.2 to the public 0.2.3 release. Provider home directories (`.codex`, `.claude`, `.pi/agent`) are created when the runtime context is built, so a service whose home volume lacks them no longer fails the Codex login or answers 503 for the Codex model list (this add-on's start script already created them). A model catalog that was cached empty (Pi before its login) or failed (a provider that could not start) is refreshed once and read again, so Pi models appear after login without restarting Paseo.
- The 0.2.3 package also contains the managed-runtime support merged as plugin PR #5. This add-on does not ship a managed runtime, so the runtime is still installed from the lock at first start. One visible difference: a **new** Paseo daemon home (a first install, or a restore without Paseo state) now starts with local dictation and voice mode off, so Paseo no longer downloads about 0.7 GiB of speech models from github.com when the daemon starts; an existing daemon home or an explicit choice is never changed.
- No option, port, architecture, image name, core digest or data-layout change: the core is still the w2.10 core `sha256:c8cd57f0…`, now named by its PaaS release tag `20261029.0033` (an additional tag for the same digest that 0.2.10 pinned as `20261027.1127`), so the add-on and the PaaS image share one core name. Existing provider directories are left untouched. Upgrading from 0.2.10 needs no migration.

## 0.2.10

- Restore the bundled native Omnigent plugin by removing the Dockerfile deletion guard. Require its adapter/host assets and preinstalled SDK 0.16.0 from the reviewed core; retain Claude Code, Codex, Pi and OpenCode as the only engines. The OpenDesign daemon owns host startup/shutdown; the legacy external supervisor stays disabled.
- Stop retiring Omnigent state on each HA boot. New setup uses the daemon-private `/data/opendesign/integrations/omnigent/host` and must ask for URL/username/password in the GUI. Ignore inherited legacy location overrides; neither `home/.omnigent` nor `.backup/omnigent-*` is automatically adopted or deleted. New setup survives restart/upgrade and cold backup restore.
- Allow 35 seconds for native cleanup with a 45-second Supervisor timeout; keep the Paseo 0.2.2 runtime shipped in 0.2.9, backup exclusions, native return navigation and credential-permission restore.
- Add executable launcher persistence/shutdown tests, native daemon and GUI ingress smoke, and an opt-in real-service candidate harness for four-engine reply/stop, host resume, disable/re-enable/disconnect, cold restore and image upgrade. Preserve existing ingress, terminal, MCP, BYOK and export behavior.
- **Migration/rollback:** retired users sign in again; already-configured new hosts retain `/data`. Backups contain Omnigent identity/login tokens and legacy archives. Stop the old host before restoring its identity elsewhere; rollback to a release without the integration requires the pre-upgrade backup. No HA option, port, architecture or image name changes.
- Keep the Omnigent plugin settings pages reloadable through Home Assistant Ingress: the page keeps its Ingress address, so a browser reload returns the page instead of an HA 404 (issue #28), and the other plugin pages (terminal, MCP server, Paseo setup) behave the same.
- Choosing **Configure** in the Omnigent plugin opens the setup in a daemon-created onboarding conversation: the page moves there and the connection dialog opens on top of it. Open the Omnigent card on the Plugins page again to return to the settings page.
- After a native backup restore, Supervisor leaves the known provider credential files readable (`0644`); the add-on repairs them to `0600` (private directories `0700`) at startup, before the service runs.
- Pin the w2.10 OpenDesign core `20261027.1127` (`sha256:c8cd57f0…`), copied to public GHCR without changing its digest. Home Assistant OS acceptance of this build (upgrade, Ingress reload, fresh and restored Omnigent connection, native backup restore) is recorded separately from this changelog.

## 0.2.9

- Update the bundled Paseo runtime from 0.2.1 to the public 0.2.2 release. Its setup page recognizes Claude Code's official `claude.com` authorization URL, accepts the authorization code in the protected page, sends it to the Claude CLI, and waits up to 15 minutes for the provider to complete login.
- Keep the OpenDesign core at the same immutable 20261026.1751 digest and retain the existing add-on slug, architecture, Ingress routes, options, data paths, projects, provider homes, and backup exclusions. Updating from 0.2.8 requires no data migration; a provider account that is not signed in still needs its own official authorization.

## 0.2.8

- Pin the public shared OpenDesign core 20261026.1751. The native Paseo plugin card and setup page open on first use; amd64 Home Assistant OS install and GUI acceptance are recorded separately from this source changelog.
- This release does not expose the bundled Omnigent plugin in Home Assistant; Omnigent HA setup is introduced in 0.2.10.

## 0.2.7

- 原生備份還原後，在服務啟動前恢復已知 CLI 憑證／設定檔的 0600 與
  provider 私有目錄的 0700；不改寫內容、不改專案權限，拒絕不安全的連結。

- Return from Paseo setup to the native Home Assistant OpenDesign app page,
  avoiding a top-level `/plugins` URL that fails on reload. The installed slug
  is discovered through a bounded root-only Supervisor self lookup; missing
  metadata returns to Home Assistant instead. Runtime package bytes are unchanged.

- Cold backups exclude only the reconstructible Paseo `packages/runtime`
  directory through native `backup_exclude`, avoiding runtime binary hardlinks
  that fail Supervisor's streaming restore. Credentials, projects, sessions,
  daemon identity, enabled intent, provider installations and npm cache are
  retained. Enabled startup or a later GUI start rebuilds from the bundled
  exact lock; package-source connectivity is required (offline recovery is
  not guaranteed). Existing archives are not rewritten.

- Report successful exit after a requested TERM/INT has stopped all supervised processes. The previous launcher propagated the interrupted wait's 143/130 and Supervisor showed `error` after a successful native stop. Unexpected required-process exits still stop peers and return failure. Cold backup had succeeded; restore failure is not claimed.
- Add the shared native Paseo launcher and supervised runtime with first-install onboarding, official provider login, model testing and pairing setup through HA Ingress.
- Persist runtime state and explicit manual stop beneath `/data`; share the existing provider home and preserve OpenDesign projects and other MCP entries through the native per-entry CAS API.
- Protect setup/API routes behind the actual Supervisor peer and a private Unix socket. Validate authenticated user, origin and Ingress subpath; discard forwarded-header claims. Keep native new-tab launches beneath the Ingress prefix.
- Increase graceful shutdown to 25 seconds with a 30-second Supervisor timeout. No option, public port, architecture, image name or stored data format is removed. Upgrade from 0.2.6 retains existing data; first Paseo activation needs package-registry access and target-local provider login.
- Pins the reviewed w2.5 core `20261026.0712` (`sha256:366e337d…`, native fork `c8ae390`), copied to public GHCR without changing its digest. Candidate image smoke and native HA acceptance remain release gates.

## 0.2.6

**Built-in MCP server on MCP Python SDK 2.3, the runtime of the HA MCP add-ons 0.4.0** (the joint SDK 2 round with the WOOW PaaS, woow-mcp-server #82; vendored from `WOOWTECH/Woow_ha_mcp_addons` `claude-delivery` `40a8e9e7`, release 0.4.0, #22):

- The MCP tool process runs `mcp` **2.3.0** (was 1.30.0) with `mcp-types` 2.3.0. SDK 2's HTTP stack (`httpx2`/`httpcore2` 2.16.0, `truststore` 0.10.5, `opentelemetry-api` 1.45.1) replaces `httpx-sse`, `pydantic-settings` and `python-dotenv`; the tools' OpenDesign client stays on HTTPX 0.28.1. Everything else is unchanged: `starlette` 1.9.0 and `sse-starlette` 3.5.0, the releases the WOOW PaaS and the HA MCP add-ons 0.4.0 run (not the 1.10.0 and 3.5.1 published on 2026-10-24), `certifi` 2026.10.23, pydantic 2.14.1, uvicorn 0.54.0, websockets 16.1.1 (no new major); the management process's packages are exactly 0.2.5's.
- **Unchanged for MCP clients:** the 15 tools with their names, order, descriptions and accepted arguments (`inputSchema`), their results and every failure text (`Error executing tool <name>: <code>`), compared case by case with 0.2.5 on SDK 1.30.0 (`mcp-runtime/tests/unit/fixtures/surface-0.2.5.json`: 75 tool calls, 57 of them failures, and the gateway's handling of 23 requests). SDK 2 alone would hide a failure's text (`Error executing tool <name>`); the runtime's `keep_error_text` (port of the PaaS fix, woow-mcp-server `471efdf`) keeps it. Failures keep naming only a public code, never OpenDesign's own message or paths, and `list_runs` keeps its projection (id, project id, status): the 0.4.0 runtime would add both.
- **Claude.ai and other SDK 2 clients:** their `server/discover` (MCP 2026-07-28) gets the gateway's own "Method not found" (-32601) and they continue with the 2025 handshake. The gateway no longer forwards their `MCP-Protocol-Version: 2026-07-28` header with an initialize, which an SDK 2 tool process refuses (HTTP 400); with 0.2.5's gateway such a client could not have connected.
- **Unchanged state:** the MCP state stays in 0.2.5's format (schema 3), with the tools you turned off, the write grants, the token and the endpoint as they are; the update migrates and grants nothing. The 0.4.0 runtime's own store would move it to schema 4 and turn every tool and write back on, so the add-on keeps its own (`mcp-runtime/ha_opendesign_mcp/state.py`). Administration through Ingress only, the fixed OpenDesign backend and the Unix sockets are unchanged.
- **Visible changes**, as in the HA MCP add-ons: MCP requests may be up to 16 MiB (was 256 KiB) and a tool call may take up to 330 s (was 120 s); the tools wait up to 60 s for a slow OpenDesign answer before `BACKEND_TIMEOUT` (was 5 s, 20 s for `list_agents`). The **MCP Server** page shows whether the saved settings are applied to the tool process, and a save from a page opened before another change is refused until the page is reloaded. `initialize` reports `serverInfo.version` and `/api/capabilities` `product.runtime_version` `0.4.0` (was `0.1.14`).

**Updating from 0.2.5:** nothing to do. The OpenDesign core (`20261024.0943`) is unchanged and the update changes nothing under `/data`; MCP clients keep their token and URL.

## 0.2.5

- **MCP Server and CLI Terminal are built-in plugins on OpenDesign's Plugins page** (core `20261024.0943`, fork `woow-od-v0.24.1-w2.4`, `b8a1371`; the same core as the WOOW PaaS OpenDesign, paas-odoo-ci #396 and #398, approval #401). In OpenDesign open **Plugins** (外掛 in Traditional Chinese, 插件 in Simplified Chinese): **MCP Server** and **CLI Terminal**, marked **Built-in**, lead both the default **Official** tab and the **Installed** tab (the tabs now read 官方／團隊／已安裝 in Traditional Chinese); **Open** opens the administration page or the terminal in a new tab. They cannot be uninstalled and never enter prompts, @-search or projects. The two buttons that 0.2.0–0.2.4 placed at the bottom right of the OpenDesign page are gone.
- **The CLI Terminal moves to `/console/`**, the path of the WOOW PaaS build: `<the add-on's Ingress page>/console/`. Links to the old `/terminal`, `/terminal/` and anything below them answer with a redirect to `/console/`. An open terminal tab from before the update must be reopened (its WebSocket path changed).
- The "agent is not signed in" hint now points at the **CLI Terminal** plugin on the Plugins page (zh-TW, zh-CN and English).
- Copied to `ghcr.io/woowtech/open-design-core:20261024.0943` (also `0.24.1-w2.4`) by digest `sha256:ffbb2bd0…`, byte-identical to the PaaS copy. Agent CLIs and tools are unchanged.

## 0.2.4

**Built-in MCP server: the same management as the standalone HA and PaaS MCP servers** (from #15, Codex's branch `feat/mcp-parity-20261023`; management code vendored from `WOOWTECH/Woow_ha_mcp_addons` `feat/builtin-admin-parity-20261023`, `6f420266`):

- The **MCP Server** page (Ingress `/mcp-admin/`) adds tool search, each tool's accepted argument schema, how many tools the policy enables and how many the server actually offers, a check of the (fixed) OpenDesign connection, a restart of the tool process and diagnostics: its recent output, kept in memory only (at most 200 lines, 128 KiB), with tokens and passwords removed before it is kept. A tool process that cannot be observed shows *unknown*, never zero tools.
- The authenticated `/api/capabilities` contract of the other WOOW MCP servers: deployment `builtin`, administration through Home Assistant Ingress, a fixed backend that cannot be edited; `product.version` is the add-on version (new image variable `WOOW_ADDON_VERSION`, which the MCP server's root bootstrap now passes to its management process; as merged in #15 it never arrived and every add-on reported `unknown`) and `product.runtime_version` the MCP runtime (`0.1.14`).
- Unchanged: the 15 tools, the state (schema 3), tools an administrator turned off, the write grants, the MCP token and URLs, Ingress-only administration, the Unix sockets and the loopback OpenDesign backend. Unlike the standalone MCP add-ons' 0.2.x/0.3.0, an update from 0.2.1 or later migrates nothing and grants nothing (from 0.2.0, the one-time default grants of 0.2.1 still apply).

**Built-in MCP server dependencies at their newest versions** (MCP Python SDK 1.x; 2.x is a separate migration):

- `mcp` 1.28.1 → **1.30.0**, the WOOW PaaS security floor (GHSA-84m7-p3x7-pcfv / CVE-2026-59951: Streamable HTTP sessions were never reclaimed). Sessions behave as documented: one with no request for 30 minutes ends, its id answers 404 and the client initializes again; DELETE ends it at once. New: an ended session is forgotten at once, and at most 10 000 sessions exist at a time (one more initialize gets 503).
- `certifi` 2026.7.22 → **2026.10.23** in both Python environments (GHSA-6q48-6c7w-9gw2: emSign roots whose intermediate CA keys were compromised).
- Every other package at its newest release: pydantic 2.14.1 (pydantic-core 2.50.1; was 2.13.5 in the tool process, 2.12.5 in the gateway), pydantic-settings 2.16.1, starlette 1.9.0 (was 1.7.0 / 1.3.1), uvicorn 0.54.0 in both (the gateway had 0.38.0), rpds-py 2026.9.1, pycparser 3.12; httpx 0.28.1 and httpcore 1.0.9 are already the newest. websockets moves to the newest 16.x, 16.1.1 (was 15.0.1), as on the WOOW PaaS and in the HA MCP add-ons: major updates (websockets 17, MCP SDK 2.x) come later, together.
- SDK 1.30.0 needs the MCP runtime's review of it: `bounded_tools.py` and `session_idle.py` come byte for byte from `Woow_ha_mcp_addons` `0e5f7de` (`mcp-runtime/vendor.sh` can now take single files from another commit, recorded in `VENDOR.json`). Without them the tool process would not start (1.30.0's tool dispatch is not the reviewed one) and the add-on's idle limit would no longer reach the SDK's session manager.

**Updating from 0.2.3:** nothing to do. The OpenDesign core (`20261018.1219`) is unchanged and the update changes nothing under `/data`; MCP clients keep their token and URL.

## 0.2.3

- **Same OpenDesign core as the WOOW PaaS.** The add-on now builds on core `20261018.1219` (was `20261015.0617`), the core the WOOW PaaS OpenDesign runs (paas-odoo-ci #359, approval #372), copied to `ghcr.io/woowtech/open-design-core` by digest (`sha256:f3496326…`, byte-identical to the PaaS copy). It is built from the same fork commit (`woow-od-v0.24.1-w2.2`, `1c7e697`) with the same agent CLIs (Claude Code `2.1.296`, Codex CLI `0.162.1`, Pi `1.1.0`, OpenCode `1.18.33`) and the same tools. The one change: the core sets `OD_APP_VERSION=0.24.1`, so OpenDesign's `/api/version` and the built-in MCP server's `version` tool now report the OpenDesign release `0.24.1` instead of the daemon package version `0.23.1`.
- The woow release train manifest (`woow-versions.yaml`) now tracks this core on both platforms; the HA and PaaS pins are equal again.

## 0.2.2

- **Fixed: the add-on did not start after a Home Assistant backup restore.** Restoring a backup returns the add-on's `/data` without the original file owners: OpenDesign's database and project files came back as `root`, so OpenDesign (which runs as UID 1001) stopped at once with `SQLITE_READONLY` and the add-on stayed in `error` (measured on HAOS 18.1 / Supervisor 2026.09.3; 0.2.0 and 0.2.1 are affected). At every start the launcher now returns everything under `/data/opendesign` to the OpenDesign user before anything starts (symbolic links are changed themselves, never followed) and logs how many paths it fixed. A normal start changes nothing. The built-in MCP server already did this for `/data/mcp`. If 0.2.0/0.2.1 is stuck after a restore, updating to 0.2.2 starts it again with the restored data.

## 0.2.1

**Omnigent removed** (until Omnigent is stable; the WOOW PaaS drops it too):

- The add-on no longer installs or starts the Omnigent host: the `omnigent-host` kit (`/etc/omnigent-host`), its CLI Terminal profile hook and the `omnigent-host-status` command are gone, and OpenDesign starts directly again. The CLI Terminal help no longer mentions Omnigent.
- The add-on now builds on core `20261015.0617` (fork `woow-od-v0.24.1-w2.2`), which is built without Omnigent: no `omnigent` CLI, no `omnigent-host-entry`, no bundled `woow-omnigent` plugin or skill. OpenDesign no longer opens the Omnigent setup project or connection dialog, its Settings show no Omnigent section, and its Omnigent status reports *not installed*. The add-on build still deletes and checks for the plugin and skill as a guard.
- **Updating from 0.2.0:** at the first start, `/data/opendesign/home/.omnigent` (Omnigent configuration, host identity, logs and **the stored Omnigent login token**) is **moved, not deleted**, to `/data/opendesign/.backup/omnigent-<UTC time>/` (mode 0700) and the add-on log names the folder. Delete it from the CLI Terminal when you no longer need it. `/data/opendesign/home/studio` (Omnigent's session folder) and the **Omnigent connection setup** project that 0.2.0 created are left as they are (the project opens as an ordinary project, without a dialog); delete them if you do not need them.

**Built-in MCP server: the same 15 tools as the WOOW PaaS OpenDesign MCP, all on by default** (owner decision 2026-10-15).

- New tools: `list_connectors`, `read_file`, `create_project`, `send_message` (0.2.0 offered 11; `delete_project` was off until granted). The full list: `health`, `version`, `list_agents`, `list_connectors`, `list_projects`, `get_project`, `create_project`, `delete_project`, `list_project_files`, `read_file`, `get_file_info`, `send_message`, `list_runs`, `list_plugins`, `list_skills`.
- **The three writers are on by default.** `create_project` and `send_message` start an OpenDesign agent run: it uses the model credits of the account that agent is signed in to and can create and change project files. `delete_project` permanently deletes a project. Anyone with the MCP token can use them; an administrator can turn any tool off on the MCP Server page. Note: OpenDesign's `opencode` agent runs even when no provider is configured and then calls an outside model service, so `create_project`/`send_message` with `agent_id: "opencode"` can create external usage without any sign-in.
- **Updating from 0.2.0:** at its first start 0.2.1 grants `create_project`, `delete_project` and `send_message` once, except a tool the administrator had disabled, and writes `/data/mcp/ha-tool-defaults.json` so it never does so again: later changes on the MCP Server page are kept across restarts and updates. A fresh install starts with all 15 on. To go back to 0.2.0, restore the backup taken before the update (0.2.0 refuses 0.2.1's grants).
- Bounds of the new tools (the PaaS server has none): `read_file` only reads a file that the project's own file list shows (OpenDesign leaves hidden files and symlinks out), refuses secret-like names (any hidden path segment, `*.pem`, `*.key`, `id_*`, `*credential*`, `*secret*`, `*password*` and more, also checked by the gateway), binary content and anything over 1 MiB. `list_connectors` returns only ids, names, provider, category, status, configured and tool names. `create_project`/`send_message` parse OpenDesign 0.24.1's `/api/chat` events (the pinned server's parser missed failures reported as a string `error` or only in `end`), follow a run for about 75 s within the gateway's 120 s stream limit (longer runs continue in OpenDesign: `status: "running"`), bound the stream to 8 MiB and the returned agent text to 8,000 characters, and answer `projectId`, `runId`, `status`, the agent text and a public `errorCode` with a fixed hint: no paths, URLs or raw errors. Prompts are limited to 20,000 characters and `agent_id` to a plain id (`claude` by default, as on PaaS); at most two runs are followed at a time; `send_message` refuses an unknown project; `create_project` registers the project so `list_projects` shows it.
- `list_runs` works again: 0.2.0 left out the pinned runtime's `output_policy.py`, so the tool always answered `BACKEND_UNAVAILABLE`. It is now vendored (`mcp-runtime/vendor.sh`, same source commit; every other vendored file is unchanged).
- Implementation: an HA overlay in `mcp-runtime/ha_opendesign_mcp/` (`surface.py`, `od_rules.py`, `od_tools.py`, `defaults.py`); the vendored gateway and server stay byte-identical. Unit tests (`mcp-runtime/tests/unit/`) run in the image build with the image's own Python and pinned packages.

## 0.2.0

**Upgrading from 0.1.x — please read:**

- After updating, open the add-on's **Info** tab and turn on **Watchdog**. Home Assistant leaves it off; without it the add-on stays stopped if one of its internal processes exits (with it on, it is back in about 11 seconds).
- The OpenDesign MCP server is now built in. If you used the separate *Woow OpenDesign MCP Server* add-on, open **MCP Server** at the bottom right of the OpenDesign page, create a token, update your MCP client with the new URL/token (LAN port `8081/tcp` is unmapped by default; Claude.ai uses the `/private_<token>/mcp` URL), then uninstall the old add-on. It no longer receives updates.
- Only amd64 is supported from this release.

- **Built on the shared WoowTech OpenDesign core image** instead of upstream `ghcr.io/nexu-io/od:0.21.1`: OpenDesign 0.24.1 from the WoowTech fork, the same build the WOOW PaaS runs, with its white-label, zh-TW locale and export patches, the bundled `woowtech-brand` skill and `woow-omnigent` plugin, and no `brainstorming` skill. The Dockerfile default is an all-zero placeholder digest of `ghcr.io/woowtech/open-design-core` until the core is published; builds pass `BUILD_FROM`.
- Agent CLIs now come from the core: Claude Code `2.1.296`, Codex CLI `0.162.1`, Pi `1.1.0` and OpenCode `1.18.33` (was the add-on's own OpenCode `1.18.29`). The build asserts every version as UID 1001 and fails on a different core.
- **Omnigent host:** the shared WOOW `omnigent-host` kit (woow-paas-charts `6a6d1f9`, sha256-verified) runs its supervisor next to OpenDesign. It waits for a login from OpenDesign's native Omnigent dialog or `omnigent login` in the CLI Terminal, then keeps `omnigent host` connected. State lives in `/data/opendesign/home/.omnigent`.
- amd64 only, like the core image. The image licence label now reads `Apache-2.0 AND MIT` (OpenDesign and the add-on code).
- Ingress fixes for OpenDesign 0.24.1: agent and model icons built from template literals and applied as inline `mask-image` styles are now prefixed by nginx (they were fetched from the HA root before the shim could react), inline style attribute updates are re-scoped, and redirects stay relative to the HA origin (`absolute_redirect off`). The white-label "Contact us" path `/_woow/support` redirects to WoowTech support.
- OpenDesign now stops on TERM: 0.24.1's `shutdown()` no longer closes the HTTP server, so the entry closes it and exits instead of waiting for the KILL deadline.
- The `open-design` passwd home is the persistent `/data/opendesign/home`, so tools that ignore `$HOME` (OpenCode's cache, data and state) persist too. Missing agent CLI homes (`.claude`, `.codex`, `.config`, `.pi/agent`) are created at startup; existing entries are left alone.
- The launcher supervises a list of named required processes, which makes adding one a single `start_child` line, and names the process that exited.
- The white-label "agent is not signed in" message points to the add-on's **CLI Terminal** (zh-TW, zh-CN and English) instead of the PaaS `/console/` path and service settings (`ha-patches/sign-in-hint.py`, which fails the build when the core text changes).
- **Built-in MCP server** (replaces the separate *Woow OpenDesign MCP Server* add-on): the pinned Woow MCP gateway and OpenDesign tools (`mcp-runtime/`, vendored from `WOOWTECH/Woow_ha_mcp_addons`, hashes in `VENDOR.json`) run as a fourth required process under their own UID, always on, with the add-on's own OpenDesign as the fixed backend. LAN MCP on container port `8081` (Bearer, or `/private_<token>/mcp` for Claude.ai; not mapped by default); administration at Ingress `/mcp-admin/`, opened from the new **MCP Server** entry next to **CLI Terminal** on the OpenDesign page (neither entry is added inside project previews any more). nginx now runs as its own UID `ha-ingress`, and no child process inherits the Supervisor token.

## 0.1.10

- Synchronize Agent Skills, MCP server definitions, portable plugin manifests, and a default working directory across Claude Code, Codex, Pi, and OpenCode.
- Preserve existing agent configs, migrate existing skills into the shared persistent directory with backups, and report plugin adapters without treating native plugin formats as interchangeable.
- Add `ha-opendesign-agents` status, workspace, and sync commands.

## 0.1.9

- Bundle Claude Code `2.1.296`, Codex CLI `0.162.1`, and Pi Coding Agent `1.1.0` in the Home Assistant image so OpenDesign can discover them at startup without a plugin or first-use download.
- Verify all three CLIs as the unprivileged OpenDesign user during image build and container smoke tests.

## 0.1.8

- **Pages taller than the capture viewport can be exported to PDF again.** They
  could not be, at all: the renderer passed Playwright a `clip` without
  `fullPage`, so `clip` was measured against the viewport and every segment
  past the first (y >= 1000) fell outside the captured area. The export died
  with `Clipped area is either empty or outside the resulting image`. A short
  page plans one segment and worked; anything article- or report-shaped plans
  two or more and always failed. Bisected on the running add-on: 1000 px
  exported, 1010 px did not. Verified after the fix at 1010 / 1200 / 1500 /
  2000 / 3000 / 6000 px, each producing `ceil(height / 1000)` pages with
  per-page content confirmed distinct.
- Screenshot options for a page segment now come from an exported
  `planPageScreenshot()` so the contract has a unit test.

## 0.1.6

- Preserve HA Ingress transport paths when project preview iframes use the History API, preventing post-load preview reload loops.

## 0.1.5

- Preserve the authenticated HA Ingress transport prefix for raw and scoped project-preview iframes, preventing preview reload loops and blank canvases.

## 0.1.4

- Restore OpenDesign native browser-local API BYOK; provider, model, and API-key settings are excluded from `/data`, logs, add-on options, and Home Assistant backups.
- Bundle exact OpenCode `1.18.29` for the native `byok-opencode` runtime.
- Remove Pi Local CLI, persistent BYOK profiles, credential sidecar/route/UI injection, and three-process supervision.
- On startup safely remove withdrawn legacy `/data/opendesign/credentials` without following symlinks.

## 0.1.3

- Replace OpenCode BYOK with locked Pi `0.84.4` Local CLI execution.
- Add HA Persistent BYOK Profile storage, Settings overlay, loopback sidecar, and administrator-visible cold-backup credentials.
- Support Anthropic, OpenAI, Google, and OpenAI-compatible profiles with an authoritative active model.

## 0.1.2

- Keep OpenDesign's client-side history on logical paths such as `/settings` and `/design-systems` while the network wrappers retain the authenticated HA Ingress transport prefix.
- Fix sidebar navigation updating the URL without changing the page content.
- Add real-browser regression coverage that opens Settings, verifies API-provider controls, returns home, and opens the Design systems page.

## 0.1.1

- Fix HA Ingress boot hanging forever at `Loading OpenDesign…`: include `text/javascript` in nginx response filtering and prefix both escaped RSC chunk references and Turbopack's runtime `/_next/` asset base.
- Make the real-browser container smoke wait for the OpenDesign client to finish booting, so asset-only ingress checks cannot regress silently.
- Rewrite dynamically assigned iframe `src` values before navigation, keeping previews inside the authenticated ingress prefix.

## 0.1.0

- Initial standalone Home Assistant add-on for pinned OpenDesign 0.21.1.
- Add amd64/aarch64 Ingress-only metadata, cold backup, sidebar entry, and watchdog.
- Persist daemon state at `/data/opendesign`; keep provider credentials browser-local.
- Add unprivileged nginx ingress adaptation for static paths, API requests, SSE, WebSocket, history, workers, and dynamic assets.
- Add system Chromium, Playwright 1.55.0, Noto CJK/emoji fonts, and an injected Node headless renderer.
- Support PNG/JPEG, screenshot PDF, screenshot PPTX, ordinary page/deck/slide/stitch/pagination capture; reject editable PPTX explicitly.
- Add watchdog process launcher, static/unit tests, and validation-gated multi-architecture GHCR workflow.
- Harden renderer output confinement against symlinked output/export roots and block model-authored renderer traffic from HA/private/link-local/loopback networks except the exact OpenDesign origin.
- Bridge HA browser PDF and PNG/JPEG actions to the working screenshot binary endpoints; remove the misleading desktop vector-PDF injection.
- Bound launcher shutdown with a five-second TERM grace followed by KILL/reap.
- Gate the architecture matrix on a real amd64 container smoke test covering health, restart persistence, UID/paths, local-runtime absence, installed Chromium rendering, and upstream image/PDF/PPTX assembly without BYOK.
- Block renderer WebSockets before page creation; serialize render jobs; add absolute abortable deadlines plus slide, aggregate pixel/output-byte, remote-byte, and remote-fetch concurrency limits; stitch slides without concurrent file loading.
- Preserve complete `Request` semantics when redirecting browser PDF exports.
- Exercise injected ingress/export scripts in Chromium through a Supervisor-style path-stripping proxy, including fetch, XHR, SSE, WebSocket, PDF, and image actions.
- Pin the upstream multi-architecture image by digest, pin GitHub Actions by commit, explicitly install/check bash, and publish architecture version tags only from an exactly matching release tag.
- Split non-release builds from release publishing so PR/main jobs retain only `contents: read`; add a release-only, fail-closed GHCR preflight that prevents overwriting either architecture version tag. Partial releases now require a version bump.
- Hold the remote-resource semaphore across DNS policy evaluation and pinned fetch completion, with an instrumented resolver-concurrency regression test.
- Assert in the Chromium ingress smoke that custom `Request` headers survive the Supervisor-style proxy during PDF export.
- Use and verify the upstream image's absolute `/usr/local/bin/npm` path so reduced build environments cannot lose npm from `PATH`.
- Keep Supervisor `build.yaml` on the supported `0.21.1` tag syntax (digest syntax is silently replaced by the default HA base), while retaining digest pins in Dockerfile and CI/release builds.
- Start a minimal root PID 1 to prepare HA's root-owned `/data` mount, then drop nginx and OpenDesign to UID/GID 1001 with `su-exec`; verify ownership and child UIDs in container smoke tests.
- Route nginx errors to its inherited `stderr` descriptor and disable access-log reopening after the UID drop, matching HA Supervisor's protected log pipes.
- Preserve all slide siblings during capture so structural CSS selectors such as `:first-of-type` and `:last-of-type` render distinct slides instead of duplicating the last slide's styling.
- Harden the container browser harness against dangling proxy sockets and verify fixture creation through OpenDesign's file API plus real two-color deck output.
- Reject symbolic links during privileged `/data` preparation and use no-follow ownership changes, preventing persisted state from redirecting root startup operations outside the add-on data tree.
- Make the CI browser smoke observe blob-anchor clicks instead of unreliable GitHub-hosted Playwright download events; binary endpoint checks and HAOS acceptance still verify real downloaded files.
- Serialize browser-bridge and renderer Chromium acceptance on small CI runners: deterministic binary stubs verify the bridge first, then a fresh container process namespace runs real image/PDF/PPTX endpoints.
- Give every Chromium launch an ephemeral writable HOME/XDG profile, preventing Alpine crashpad state from leaking across render jobs or persisted `/data` volumes.
- Query GHCR release-tag availability with GET instead of HTTP/2 HEAD, avoiding curl error 18 on bodyless manifest responses while preserving fail-closed status handling.
