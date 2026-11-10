# code-server Paseo runtime adapter

This adapter is independent of Pi SDK/plugin lifecycle. It only uses installed
`claude`, `codex`, and `pi` executables and the deployment's existing private
provider homes. It does not install agents, log in, copy credentials, create a
conversation, or access the network on module import.

## Build and integration

Copy this directory to `/opt/woow-connectors/paseo`, then run during image build:

```sh
bash /opt/woow-connectors/paseo/install-runtime.sh /opt/woow-connectors/paseo
```

Requires Node 22.19+, util-linux `flock`, and Linux `procps` (`ps --ppid`). The installer uses the vendored npm
lock for `@getpaseo/cli`/server **0.11.2**, validates both pinned PID-lock modules
before applying the upstream WOOWTECH transition patch, and never starts a daemon.
Revision r2 also applies a hash-checked Claude SDK launch fix: root keeps normal
permission handling and does not request the optional bypass-permission capability.
An older running revision requires an owned-daemon stop/start after upgrading.
There is no package-level install/postinstall hook. Dependencies remain in
`runtime/node_modules`; the runtime is architecture-specific and must be built
in each target image. Do not put `runtime/node_modules` in Git or a VSIX.

The parent JSON CLI imports `handle(request)` from `index.mjs`. Exported
`allowedActions` lists the supported actions. No adapter logging goes to stdout.
State is private (directories 0700/files 0600) under:

```text
${WOOW_CONNECTOR_DATA_DIR:-${PI_AGENT_DATA_DIR:-/data/pi-agent}/connectors}/paseo
```

Runtime defaults to `/opt/woow-connectors/paseo/runtime`; a trusted deployment may
override `WOOW_PASEO_RUNTIME_DIR`. Neither requests nor workspace settings can
choose an executable/runtime/state path. `HOME`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`,
`PI_CODING_AGENT_DIR`, and `PI_AGENT_DATA_DIR` are inherited; missing provider dirs
default under the deployment's `/data/pi-agent`. This preserves its shared skills
and MCP mappings; actual tool invocation still needs deployment acceptance tests.

The existing container service should periodically call `restore`. No additional
supervisor is needed: Paseo owns its worker supervisor, and the parent service
restores that supervisor after container startup/crash. `restore` is a read-only
no-op before explicit `start` and after explicit `stop`. A healthy restore does
not rewrite configuration, reload providers, generate pairing material, or create
chats. Concurrent start/stop/configure/restore operations use a shared runtime
lock; recovery verifies installation, UID, kernel boot ID, process start ticks,
PID-file identity, and official supervisor environment before recovery/signaling.

## JSON contract

All examples are JSON sent on stdin to `/usr/local/bin/woow-connectors`:

```json
{"connector":"paseo","action":"configure","workspace":"/workspace","hostName":"code-server QA"}
{"connector":"paseo","action":"start"}
{"connector":"paseo","action":"status"}
{"connector":"paseo","action":"pair"}
{"connector":"paseo","action":"models","provider":"pi"}
{"connector":"paseo","action":"verify","provider":"pi","timeoutMs":180000}
{"connector":"paseo","action":"stop"}
```

- `configure`: accepts `workspace`/`workspaceRoot`/`cwd`, `hostName`/`displayName`,
  and optional loopback `port` (1024–65535), either directly or under `settings`.
  Changes do not implicitly start a daemon. Stop before changing a live port.
  Display name is a connector label; Paseo itself rejects `daemon.name`.
- `start`: enables persistent desired state, starts or safely reuses one daemon.
  Linux images require `procps` (`ps --ppid`) and util-linux `flock`; the installer
  and activation check these dependencies before provider probes can crash.
  Existing engine binaries remain image-pinned: `DISABLE_AUTOUPDATER=1` is forced
  during discovery and explicitly forwarded in Claude's provider/SDK environment.
- `stop`: writes disabled state before stopping the owned daemon. Restore respects
  this even if the stop operation itself fails.
- `restore`: no state/disabled means no start. Only explicitly enabled state may
  restore after process/container loss.
- `status`: distinguishes `daemon.running`, `daemon.reachable`, `relayEnabled`,
  `relayConnected` (null if the daemon does not report it), and `chatVerified`.
  An installed runtime with no configuration reports `not_configured`; one with
  workspace settings but no started daemon reports `not_started`.
  `online` means the local control connection is reachable, not proof that a Web
  client has paired or a model answered. It contains no pairing URL or raw state.
- `pair`: returns official `https://app.paseo.sh/...` URL and `sensitive:true` only
  on this explicit action. Never log, persist, or include the URL in diagnostics.
  The daemon binds loopback and uses the official encrypted relay for the Web app.
- `models`: live catalog for one provider, or independent per-provider results for
  all three. Empty/unavailable catalogs never become a hardcoded model list.
- `verify`: two actual turns with a fresh marker, checking only newly generated
  assistant timeline entries, then archives the test agent. `ok` and
  `requestedPassed` cover this request; `passed` covers all three accumulated
  results. Quota/auth failures, missing replies, and failed cleanup are failures.
  Optional `providers`, `models:{pi:"provider/model-id"}`, `modes`, `cwd`, and
  `timeoutMs` select authorized tests. Verification creates model calls only on
  this explicit action; no onboarding conversation is automatic.

The extension's `{engine:"pi",model:"provider/model-id"}` is accepted and maps
to only `provider:"pi"` plus `models:{pi:"provider/model-id"}`. Conflicting engine,
provider, provider-list, or model selections fail instead of testing a different
agent/model.

## Conversation and model-switch acceptance

```json
{"connector":"paseo","action":"chat","provider":"pi","model":"<catalog-id>","cwd":"/workspace","message":"Remember the marker ABC123. Reply with it."}
{"connector":"paseo","action":"continue","agentId":"<returned-id>","message":"What marker did I ask you to remember?"}
{"connector":"paseo","action":"switchModel","agentId":"<returned-id>","model":"<second-catalog-id>","message":"Reply with the marker from this conversation."}
{"connector":"paseo","action":"archive","agentId":"<returned-id>"}
```

`chat` returns `agentId`, provider/model, a new assistant `reply`, and status.
`continue`, `switchModel`, and `archive` reject agents not labeled as owned by this
installation. Switching validates the catalog and requires the daemon's
`runtimeInfo.model` to confirm the new selection before sending an optional test
message. `confirmed` records the daemon/provider selection; `replyVerified` is
separate and requires a new successful reply. `changed:false` is not a model
switch. Full client/provider behavior still must be checked through Paseo Web.
Changing provider creates another agent; context is not silently transferred.

Timeouts: local CLI 30s normally, daemon start 105s, local connect 5s, catalog up to
150s, each verification turn 10–600s, conversation turn 1–600s. The parent CLI and
UI must allow the requested total (three providers × two turns for `verify`).
Errors are `{ok:false,error:{code,message}}` and never include raw subprocess or
SDK errors. Pending conversation returns its agent ID, so a timeout is not a false
success. Pairing/Web authentication and actual model accounts remain distinct.

## Tests

```sh
node --test connectors/paseo/tests/adapter.test.mjs
WOOW_PASEO_RUNTIME_DIR=/absolute/prebuilt/runtime node connectors/paseo/tests/live-daemon.mjs
```

The first suite needs no runtime/network/model account. The explicit integration
test runs a fresh loopback daemon with empty provider homes and tests real startup,
concurrent ownership, pairing generation, restore and stop; it does not claim real
model replies or a paired browser. It always attempts owned-daemon cleanup.

### Genuine Paseo Web tests

`tests/live-web.mjs` uses the installed Chrome and Playwright Core. With no runtime
environment variable it checks the official welcome page only. With a prebuilt
runtime it starts an isolated credential-free daemon, visits its official pairing
link, confirms the browser's host-trust dialog, skips onboarding, and opens that
daemon's temporary directory through the real Web UI. It makes **no model calls**.
It closes the browser and stops/removes only its own test daemon/state.

```sh
node connectors/paseo/tests/live-web.mjs
WOOW_PASEO_RUNTIME_DIR=/absolute/prebuilt/runtime node connectors/paseo/tests/live-web.mjs
node --test connectors/paseo/tests/adapter.test.mjs connectors/paseo/tests/browser-contract.test.mjs
```

On 2026-11-10, the official client returned HTTP 200 and rendered **v0.15.3** in
Chrome 143.0.7499.169 / Playwright 1.61.1. Browser pairing to daemon 0.11.2 and
remote-directory opening succeeded. Therefore no extra self-hosted Web server or
proxy assets were added. See `browser-validation.json` for the separate Podman
QA run: all three authenticated providers passed two model turns, switching
models inside the same conversation, a shared MCP proof turn, and archive cleanup.
The HA QA run also passed all three agents after repairing a missing `procps`
dependency and the root Claude launch flag. Codex/Pi passed the initial run;
Claude alone was retried after applying revision r2. All conversations, including
the failed initial Claude attempt, were archived. Shared proof skill paths resolve
to one file, each provider recorded a fresh MCP proof, and Claude remained 2.1.285.
Both environments used the parent's directly installed pinned runtime in existing
QA containers. These results do not validate a newly built image or PaaS.

`tests/browser-acceptance.mjs` is the live three-agent harness. Put its JSON plan
in a current-user-owned **0600 file outside this Git checkout**; it contains the
secret pairing URL. Set `WOOW_PASEO_WEB_PLAN` to that absolute path. Example shape
(placeholders only; get real model IDs/labels from the live catalog):

```json
{
  "pairUrl": "https://app.paseo.sh/#AUTHORIZED-PAIRING-FRAGMENT",
  "workspace": "/workspace/connector-qa",
  "allowModelCalls": true,
  "turnTimeoutMs": 180000,
  "providers": [
    {"id":"claude","models":[{"id":"FIRST_ID","label":"First label"},{"id":"SECOND_ID","label":"Second label"}]},
    {"id":"codex","models":[{"id":"FIRST_ID","label":"First label"},{"id":"SECOND_ID","label":"Second label"}]},
    {"id":"pi","models":[{"id":"FIRST_ID","label":"First label"},{"id":"SECOND_ID","label":"Second label"}]}
  ]
}
```

Use `"mode":"pair"` with just `pairUrl` and `workspace` for a no-model pairing and
directory test. Full mode requires all three providers, two distinct models each,
and `allowModelCalls:true`; it does not silently choose cheaper/other models.
For a focused retry after fixing one provider, `runProviders:["claude"]` limits
execution while retaining the full catalog plan. Its result names the requested
providers and must not be presented as a new complete three-provider run.

The full harness creates every conversation through the Web UI, chooses the first
model, sends a marker, switches to the second model in the same conversation, and
asks for the remembered marker. It requires a **new assistant DOM node** plus a
new server timeline cursor, matching actual `runtimeInfo.model`, and confirmed
archive cleanup. No browser state, tokens, screenshots, HARs, traces, prompts or
assistant text are saved. Failure output contains a stable code/stage only.

For an explicitly prepared shared skill/MCP fixture, set `sharedProof:true` and
`proofRunPrefix:"paseo-podman"` (also `paseo-ha` or `paseo-paas`). The harness adds
a third Web turn requesting the `woow-connector-proof` skill. Its inspector must
also accept `{mode:"proof",run}` and return `{ok:true,rows:[{run,tool,proof}]}` from
the fixture's invocation log. Each run label is fresh; the baseline must be empty,
the MCP server must record a new `read_proof` call, and its generated proof must
appear in both the new assistant DOM node and the new server timeline entry.
Only proof labels/counts and success flags are reported, not conversation text.

Provide a read-only inspector module using `WOOW_PASEO_INSPECT_MODULE`. For a
browser running on the same deployment, use the absolute path to
`tests/inspect-local.mjs`; it inherits that deployment's connector environment.
For remote Podman/HA/PaaS use `tests/inspect-command.mjs` and point
`WOOW_PASEO_INSPECT_COMMAND_FILE` at a private JSON **argv array** invoking
`node /opt/woow-connectors/paseo/tests/inspect-local.mjs` inside the correct
container (for example via `kubectl exec -i`). The command must preserve stdin and
emit just the inspector's JSON stdout. No shell string or credential belongs in
that command file. This companion **only reads** provider/model/timeline/archive
state; it cannot start chats or switch models in place of browser interactions.

```sh
WOOW_PASEO_WEB_PLAN=/private/qa-plan.json \
WOOW_PASEO_INSPECT_MODULE=/absolute/connectors/paseo/tests/inspect-command.mjs \
WOOW_PASEO_INSPECT_COMMAND_FILE=/private/qa-inspector-command.json \
node connectors/paseo/tests/browser-acceptance.mjs
```

By default Playwright is loaded from the sibling `browser-tools/node_modules` and
Chrome from `/usr/bin/google-chrome`; overrides are `WOOW_PLAYWRIGHT_MODULE`
(absolute module entry path) and `WOOW_CHROME_PATH`. Run the real journey on each
assigned deployment; the harness and its synthetic contract tests alone do not
establish successful model conversations. Podman/HA evidence does not transfer to
PaaS or different provider credentials.

## Source and license

Derived from MIT-licensed `WOOWTECH/pi-paseo-plugin` commit
`2d5531fd65f80a58a15ed19c709a4f29e52d3723` (0.1.15). See `LICENSE` and
`provenance.json`. Reused process, locking, PID transition, birth-identity, reply
classification, timeline cursor and acceptance cleanup primitives retain the
original MIT notice. This adapter replaces Pi-specific paths/lifecycle,
auto-installation, web-client rewriting and provider setup. Optional voice
downloads are disabled, following `WOOWTECH/hermes-paseo-plugin`
`1101a5da63178e08bd0fdf849db8e2a5de4d6ef1`. No private runtime state is vendored.
