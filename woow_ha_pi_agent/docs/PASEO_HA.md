# Agent Connect in Home Assistant

This change retains the official Pi Web 0.12.0 npm build and its SDK 1.1
compatibility pins. It does **not** install the plugins' Pi Web 0.10 overlay.
The native desktop tabs and mobile picker are MCP → Omnigent → Agent Connect.

## Smart Tasks (0.15.26)

Agent Connect 0.1.25 adds Better Paseo 1.7.0 to the official Paseo 0.17.4 daemon as a verified built-in plugin. This supplies the Tasks board, sidebar entry and settings panel for both Smart brands. The daemon remains the official package; no Smart web client is replaced or served by HA.

Tasks default to enabled. Chat enhancements and automatic update checks default to disabled. The plugin's own Git/npm self-update commands are unavailable; updates arrive with a reviewed Agent Connect bundle. Existing explicit user preferences remain in effect.

The image carries runtime `0.17.4-r2-a651f42711da`. Restart the add-on to move a running `0.17.4-r1` daemon onto it. Pairing, server identity, keys, conversations and settings remain in the existing Paseo data directory, and Tasks data is stored alongside them. No re-pairing or reset is needed. For rollback, stop the daemon, restore the matching earlier add-on bundle and keep the data directory intact.

## Target selection

The Agent Connect settings page selects Paseo, Woowtech Smart or Apporo Smart.
It uses the shared plugin's `settings.target` and `saveConfig({target})` API;
missing target settings retain Paseo. The protected bridge projects only known
status fields and fixes each target's official origin: `https://app.paseo.sh`,
`https://smart.woowtech.io` and `https://smart.apporo.ai`.

Since 0.15.25 all three targets work the same way: the page links the official
site of the saved target and opens it in a new tab (`target="_blank"`,
`rel="noopener noreferrer"`). Agent Connect 0.1.23 removed the patched Paseo web
build that versions 0.1.9-0.1.22 downloaded and this add-on served at
`/paseo-web`, so Paseo no longer has a copy of its own. The bridge and the page
accept one pairing form only, `https://<target origin>/#offer=<base64url>`, with
the pairing data in the fragment; another scheme, host, port, userinfo, path,
query or fragment, a link of another target, or the retired `/paseo-web` path is
refused. Pair receipts are checked against the selected target before and after
the request. Draft changes and a pending daemon restart block pairing. Saving a
target does not interrupt a running conversation: stop and start the service
when convenient to apply the new target, then generate a fresh link.

The page forwards only the target to the plugin and refuses every other field.
The plugin keeps the settings a save leaves out, so this page cannot change the
display name or the "allow agents to collaborate" switch that Agent Connect
0.1.22 added (`agentCollaboration`, off by default). The page has no such
switch yet; it neither shows nor sets it.

The image pins the Agent Connect archive named in
`cli-runtime/versions.json`; its exact checksum is recorded there, in
`candidate-packages/manifest.json` and in `AGENT_CONNECT_CANDIDATE.md`. Builds
use the vendored archive whose bytes are verified against the published
[Agent Connect 0.1.25 GitHub release](https://github.com/pi-paseo-plugin/releases/tag/v0.1.25).
The selector remains disabled with an upgrade message when a user-selected
older plugin lacks target support. Image, Ingress, upgrade-comparison and
upgrade tests are required before publishing the HA add-on. Existing paths and
package identity remain compatible.

## Immutable image inputs

- Agent Connect plugin and the Paseo daemon it installs: version, SHA-256,
  source commit and runtime revision are written once, in
  `cli-runtime/versions.json` (`agentConnect`; the image keeps a copy at
  `/usr/local/share/woow-ha-pi-agent/versions.json`), and checked against
  `candidate-packages/manifest.json` and the archive itself by
  `tests/versions.test.mjs`. The archive carries no web client.
- Omnigent 0.3.34, source `d8652e971bdf66133d699052ab9003d39ff69159`, unpublished vendored archive SHA256
  `e9e80783881f8a036cbf922d2f50fad860dac3bd23e170dda768ab3c56107945`.
  HA 0.15.19 keeps authorized-host recovery and native Pi Web 0.12 settings;
  Omnigent setup runs only from Settings. There is no floating link, setup
  conversation or link to one (0.15.14, which had them, is withdrawn).
  Paseo pairing is available only through Settings.

The image builds the daemon dependencies for amd64 and aarch64. It downloads
and bundles no web client. Earlier versions baked one into
`/opt/woow/paseo-web` and copied it to `/data/pi-agent/pi-paseo/web-client/` at
start; the plugin now deletes that old copy when its service next starts (only
the entries those versions created), which gives the space back. The launcher honors an explicit `PI_PASEO_RUNTIME_DIR` unchanged. Otherwise it
asks the registered plugin's `runtimeReady` about the saved
`$HOME/.local/share/pi-paseo/runtime` and the image's `/opt/woow/paseo-runtime`.
A ready saved runtime wins. If only the image runtime is ready, it wins, so an
old or incomplete saved install does not trigger an avoidable ~0.7 GB `npm ci`
at first boot. If neither is ready or the plugin cannot be checked, the saved
path stays selected for compatibility and persistent installation. With no
saved path, the image path is used. Selection never edits either directory or
the daemon home, and uses the registered plugin's revision, including a custom
plugin override, rather than assuming the image's version. Provider login, live relay access and
conversations still require network.

## Ingress and authentication

`/paseo/setup`, `/api/paseo` and the page's own static files use a separate
Unix socket behind the existing nginx listener. The HA Supervisor-only
source-IP restrictions remain unchanged. No new public port is opened. Settings
API reads and writes require an in-memory token, same-origin checks and bounded
JSON requests. Passwords and pairing data are not included in status responses,
which carry a fixed set of fields (whether the plugin is installed and enabled,
its version and phase, selected and active target, pending state, whether the
daemon runs, each engine's status and modes), never the plugin's raw status,
paths, tokens or its other settings.

Nothing else is served. The bridge's nginx location covers `/paseo` and
`/api/paseo` only. `/paseo-web` (the retired client, and the old open link a
bookmark may still hold) has a location of its own that only does `return 404`:
nginx answers it itself and nothing is proxied. Left to Pi Web, the old link
`/paseo-web/` was seen (Pi Web 0.10.0) to be redirected to a URL without the
Ingress prefix, which leaves Ingress. `return` answers every client alike, so it discloses nothing,
and the server-level Supervisor-only allow/deny are unchanged. The bridge also
answers 404 for the path. The settings page keeps its strict CSP (`default-src
'none'`, same-origin scripts and connections, `frame-ancestors 'self'`); the
official sites it links are separate sites in their own tabs. HTML, setup and
API responses stay private/no-store.

Pairing is an explicit POST operation. The link it returns crosses nginx and HA
Ingress once, in the body of that response; it is never part of a requested
URL, so no access log records it. When the browser opens the link, the fragment
(`#offer=...`) is not sent to any server: the official site reads it in the
page. The persistent private pairing record is owned by the plugin; browser
logs/screenshots from real accounts must not be published. The Ingress URL is
session-specific: reopen from HA after it expires.

## Upgrade and lifecycle

**From 0.15.24 to 0.15.25 (Agent Connect 0.1.24, Paseo 0.17.4).** The Paseo option now opens
the official site https://app.paseo.sh/ in a new tab instead of the bundled
`/paseo-web`. Restart the add-on after the update so the new settings page,
nginx configuration and plugin run together (Supervisor restarts it when it
applies the update itself); a settings tab or `/paseo-web` page left open from
the old version stops working. A browser that was paired through `/paseo-web`
must pair once more on app.paseo.sh: open Settings → Agent Connect, generate a
link and open it. The same `/data/pi-agent/pi-paseo/daemon` home retains its
server ID, daemon keys, provider logins and conversations. Some Paseo settings
and agent records migrate as described below.

No HA options, ports, architectures or image name change. First install registers the
bundled plugin once; it does not create or open an onboarding conversation. The plugin supervisor prepares the service independently. Pairing requires a button press in Settings → Agent Connect.
A marker prevents reinstallation after removal; pre-existing package overrides
and explicit disabling are retained. Package enable/disable/removal is observed
without restarting Pi Web. A manual service pause survives container restart;
shutdown stops the owned supervisor without persisting a user pause.

The bundled runtime is `0.17.4-r2-a651f42711da`. If a daemon from a verified
older release is still running, the plugin leaves it serving and reports
`RESTART_REQUIRED`; status, pairing, reload and stop use that daemon's own
release. Stop and start in Settings to switch versions. An add-on update
normally restarts the container, so the old process has already ended. The
image contains only the new release; it cannot control a live old daemon if
its matching runtime is unavailable (`DAEMON_RELEASE_UNAVAILABLE`). Do not
copy modules across versions to work around that check.

Both native PID writers use the same persistent Linux flock guard. Automatic
stale-process recovery requires a private proof bound to the installation,
home, PID-file inode and Linux process birth; a PID/name alone is insufficient.
The image already includes util-linux `flock` and procps `ps`. The latter is
required for the new terminal-worker cleanup. Do not remove the guard file.
The image smoke verifies both pinned CLI/server versions and writer copies,
cross-boot recovery, and a controlled birth-proof recovery that retains fixture
identity files. It does not simulate a real Supervisor restart or kernel PID reuse.

The plugin's normal stop can wait up to 45 seconds for the daemon supervisor,
then terminal cleanup; its own supervisor budget is 81 seconds. HA's launcher
still exits within 5 seconds on container shutdown, leaving remaining processes
to s6's final cleanup. Actual stop/start and stale-state recovery across the
container boundary still require image/Supervisor acceptance.

Before the first new-version start, the plugin reads config through Paseo
0.17.4's own migration: legacy OpenAI speech credentials move from
`providers.openai` into the selected speech/dictation provider; omitted speech
providers become `local`, and unused local fields are removed. Invalid JSON
reports `CONFIG_CORRUPT`; unsupported settings report `CONFIG_INCOMPATIBLE`.
If an old daemon is still serving, fix those settings before stopping it. Agent
records migrate `config.featureValues` into `config.providerOptions` and
`features` to `controls` when rewritten.

Rollback requires stop/start too. Older Paseo may reject the migrated OpenAI
speech credentials or other new config fields with `CONFIG_INVALID`; move the
credentials back to `providers.openai` and remove unsupported fields before
starting the old version. Agent options rewritten by 0.17.4 need reselection
in 0.11.2. Runtime selection leaves the saved directories intact; the plugin
only prunes eligible releases in the selected directory after a healthy start,
retaining the newest older release and any releases still in use.

Two upstream defaults affect operation: `agents.idleRuntimeCleanup` closes idle
agent processes after 60 minutes (records remain; the next message reopens
them), and `daemon.usage.enabled` allows client-requested provider usage queries
using existing credentials. Set either to `false` in daemon config and reload
to opt out; these switches are not exposed by HA's settings bridge.

The Smart clients need the older relay encryption. Agent Connect sets
`daemon.relay.requireProtectedSecurity=false` for either Smart target on every
start and refuses a pairing offer requiring protected security
(`PAIRING_SECURITY_UNSUPPORTED`). Stop/start after changing that setting while
running. The Paseo target retains the client's security choice. HA's bridge
reports action failures generically; use the plugin CLI diagnostics for the
specific code. Smart mobile push remains unsupported, and real Smart app
compatibility with this daemon still needs acceptance.

New users still need to authorize the provider CLIs through their official
login flows. This integration does not migrate or create provider credentials.
The bundled Claude Code/Codex versions, shared skills/MCP and Omnigent bridge
are retained. Its existing `boot` call retains Omnigent authorized-host recovery in 0.3.24: only
matching private authorization receipts for this installation may resume the
recorded host. Disabled/disconnected or credential-only states do not silently
authorize a reconnect. Existing custom plugin paths remain user-controlled; one older than Agent
Connect 0.1.23 may still return a `/paseo-web` pairing link, which this add-on
now refuses.

Isolated HA 0.15.2→0.15.5 acceptance confirmed automatic recovery of the
original host after official upgrade and addon restart. A whole-VM restart
exposed `HOST_PROCESS_MISMATCH`: the saved PID belonged to an unrelated
process in a different boot, so the shared plugin safely refused recovery.
Omnigent 0.3.18 distinguishes a proven stale process receipt inside the
existing authorized launch lock. It adopts an exact current installation host
or starts the same authorized registered host; ambiguous identity fails closed.
Disconnect keeps its strict process check, and no unrelated process is signaled.
Omnigent 0.3.19 also recognizes a proven stale PID reused by a process under another UID after container restart; incomplete kernel identity still fails closed.
The original failed QA state is preserved for official HA 0.15.6 upgrade and
addon/VM restart acceptance. A read-only candidate classification passed on
that actual record; live recovery is a separate release acceptance gate.

## Validation and release scope

`tests/omnigent-native-browser.mjs` runs the real compiled Pi Web 0.12 through
the repository's actual nginx config. Only listener/socket/log paths are adapted
for local isolation; a small front proxy simulates Supervisor path stripping.
No browser JS override is used. It covers desktop/tablet/390px mobile, settings
order, the private API and pairing link, mobile scrolling, the official-site
link opening in a new tab (answered locally, no network), nginx's own 404 for
`/paseo-web`, CSP and absence of pairing offers in access logs.
`tests/paseo-browser.mjs` repeats the Agent Connect checks without nginx and Pi
Web, including a target switch that only pairs after a restart.
`tests/paseo-launch.test.mjs` runs the s6 entry point `launch.mjs` for real (a copy of
the rootfs layout, a stand-in for the Omnigent launcher) and the image smoke runs
it with the real Omnigent launcher and Pi Web, so a broken import cannot pass on
`node --check` alone. `tests/paseo-contract.test.mjs` drives the real Agent Connect archive's status,
target save and pairing-link code through this repository's bridge, and
`tests/versions.test.mjs` checks the archive against its pins. Provider
responses and the Agent Connect plugin in the browser tests are fixtures: this
is not live HA or paid three-engine chat acceptance. The Docker build runs real
CLI/SDK smoke tests with network disabled. PR builds exercise generated
local-source contexts on both architectures and never push images. Publication
follows the required PR and native image gates. Post-release checks verify both
registry manifests and Store/local-build synchronization. Live Supervisor and
real-account model acceptance remain separate; this fanout does not operate live
HA, VMs or Pi4.

The runtime in `/opt/woow/paseo-runtime` is two image layers, to keep each below
the 256 MiB limit that `tests/assert-image-layer-sizes.mjs` applies to new
layers on pushes to `main` (after the merge, never on a PR): the Claude Agent
SDK's platform binary under `node_modules/@anthropic-ai`, most of the runtime and
growing with the SDK, is layer b; everything else is layer a. Measured on
2026-11-25 (`tar | gzip -6`, `tests/measure-paseo-runtime-layers.mjs`): Paseo
0.11.2 is 162.3 MiB as one layer, 63.9 + 98.4 MiB as two; Paseo 0.17.4 is 235.6 MiB
as one layer (92% of the limit), 71.1 + 164.5 MiB as two. The files, modes, owners and
mtimes in the image are those of one copy; `tests/README.md` explains how. These
numbers do not replace the final registry manifest check after publication; that
gate remains part of post-release verification.
