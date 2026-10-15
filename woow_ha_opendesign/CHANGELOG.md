# Changelog

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
