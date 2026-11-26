# Agent Connect release candidate — 2026-11-21

This is coordinated source preparation, not a published release or deployment.
Updated 2026-11-26 for HA Pi Agent 0.15.25: Agent Connect 0.1.20 → 0.1.24 (below);
the shared runtime and Omnigent rows are unchanged. The pins themselves are
written once, in `cli-runtime/versions.json`; this table is the readable record.
The candidate archives are unpublished `npm pack` results, vendored in
`candidate-packages/` for reviewable builds without inventing release URLs.
Native pins use local `file://` inputs; HA uses verified `COPY` inputs. Their
SHA-256 values identify the actual bytes. Publishing or repacking later requires
coordinated consumer updates and the normal release gates.

| Input | Candidate version | SHA-256 |
| --- | --- | --- |
| `@woowtech/pi-agent-shared-runtime` | 0.1.6 | `0914069fb0cf83f258cf81034bb16573f6e4242e8779cea47b4a5e841f98a937` |
| `@woowtech/pi-paseo` (Agent Connect) | 0.1.24 | `a8ffeda600318f3c42e5e0f86d87b860f69c15b5f915286df64f7ba05a51f831` |
| `@woowtech/pi-omnigent-plugin` | 0.3.34 | `e9e80783881f8a036cbf922d2f50fad860dac3bd23e170dda768ab3c56107945` |

HA retains official Pi Web 0.12.0 with its independent Ingress bridge. Its
Omnigent plugin retains the frozen 0.3.34 archive used by the earlier native candidate. HA does not
apply its 0.10 combined adapter; the official 0.12 bridge remains in use. The Agent Connect GUI supports older user-selected
Paseo plugins by disabling the new selector while retaining Paseo pairing.

Agent Connect preserves package IDs and paths. Existing installations default
to Paseo; users may choose Woowtech Smart or Apporo Smart. A running daemon
continues until the user stops and starts it to apply a target change. Pairing
is blocked while that change is pending.

Before publication, run each platform's existing acceptance and upgrade gates
using the exact candidate image or installer. Local Linux tests and browser
fixtures do not substitute for macOS/Windows host acceptance, a multiarch
container build, HA Supervisor upgrade tests or actual branded relay pairing.

## Shared resources in this candidate

The distribution installs the same shared-runtime archive as k3s and calls its
`src/distribution.mjs` at startup and provider refresh. Fresh eligible settings
receive the bundle once. Explicit disablement, removal and external package
choices survive subsequent starts. Migration retires only unchanged MCP entries
recorded by the former helper; modified/unowned entries and existing skills stay.
Original changed provider configs receive private backups before migration.

Common memory lives under `<canonical-data>/shared-runtime/memory`; Claude,
Codex and Pi retain separate native histories. Switching Agent Connect brands
does not change this host-local root. Drain old shared-runtime/MCP processes
before upgrading from the former directory-lock implementation to SQLite locks,
then restart sessions to load new resource configuration. No native transcripts
are imported automatically.

## Extension-free resource scans and current validation

Shared source `e51849dfa340a2f91bcc7041092749d1b4859c70` is frozen as the
`0914069fb0cf83f258cf81034bb16573f6e4242e8779cea47b4a5e841f98a937` archive
listed above. Consumers copy these exact bytes without repacking. The source
receipt reports 61/61 full SDK1.4 tests; its previous archive's image and SDK
results do not establish acceptance of this replacement.

`loadResources` resolves authoritative skills without importing package, global
or project extensions. The explicit bridge runtime loads only its MCP adapter.
Resource scans and `run-cli` leave normal provider children with their original
extension flags. Distribution helpers additionally scope bridge mode to the
short-lived helper, preserving the actual Pi CLI environment and credentials.

Shared 0.1.6 additionally initializes the SDK theme before headless MCP extension
binding. Its installed `tests/mcp-adapter.test.mjs` starts a real cold bridge,
discovers and calls a stdio tool, retains the metadata cache, then starts a
second warm bridge and requires empty `runtimeErrors` plus another tool call.
The frozen source receipt reports SDK1.4 full61/61 and SDK1.0/1.1/1.6 focused12/12,
all without skips. These upstream results do not replace consumer installation CI.

Native CI and both offline HA final-image builds require resource authority,
resource boundary, extension scan, bridge and MCP adapter tests from the installed
016 bundle (21 named tests; the MCP test runs both cold and warm processes),
with the actual platform SDK. Native's canonical release
artifact workflow requires the same group before packaging. Replacement-archive
full Mac and HA image CI must pass on this draft head; previous Shared015 green
runs are preserved as historical evidence only.

Actual macOS, Ubuntu, Windows/WSL2 and HA Supervisor/provider acceptance remain
pending. The current HA add-on candidate is 0.15.25 and requires the version-changing
Supervisor upgrade gate. Earlier no-version-change comparisons did not exercise it. The current HA connector's
`/addons` call returned `Unknown command`, so installed-addon access is unconfirmed.

Agent Connect now uses persistent SQLite guards on macOS; Linux retains flock.
Actual Apple Silicon (Node 22.23.4) and Intel (Node 22.19.0) CI passed OS-lock,
state and onboarding tests, plus real daemon start, stop, restart and identity
retention. The macOS lifecycle uses no provider credentials or model turns.
[Mac verification run](https://github.com/WOOWTECH/pi-paseo-plugin/actions/runs/44867850835)
does not substitute for signed-installer or interactive provider acceptance.
Darwin stale daemon recovery remains conservative; this patch does not claim
Linux PID-birth recovery on macOS. Windows uses the supported WSL2 Linux path.

Historical Agent Connect 0.1.23 source `152e1c3afe4b7081fa859f40aa316059cc3fa4fd`, runtime
`0.11.2-r4-4cf9d40940bf` (the Paseo daemon stays 0.11.2 and the runtime lockfile
is byte-identical to 0.1.20's). It keeps selected-target brand identity: an older running runtime requires explicit
stop/start, and non-Linux recognition requires matching PID, startedAt and
runtime revision in the persisted record. It keeps the 0.1.20 supervisor stop
budget of 30 seconds around the 20-second nested daemon stop, including
replacement shutdown. What 0.1.21-0.1.23 add:

- 0.1.21 accepts a group-writable (0664) `paseo.pid` inside the private daemon
  home, which Paseo creates under umask 002; other-write still fails closed.
- 0.1.22 adds the boolean setting `agentCollaboration` (off by default). It is
  accepted by `saveConnectionSettings` and shown in `settings`; the HA settings
  page does not expose it and forwards only the target, so HA never changes it.
- 0.1.23 removes the bundled Paseo web client (`src/web-client.mjs`,
  `runtime/web-client.json`, `web()` and `webClient` in `status()`). The Paseo
  target now has `openUrl` `https://app.paseo.sh/` and every target's pairing
  link is `<appUrl>/#offer=<base64url>`; `pair()` no longer raises
  `WEB_CLIENT_NOT_READY`, and activation deletes the old `<stateDir>/web-client`
  copy. Browsers paired through `/paseo-web` must pair again on the official
  site; the host identity, logins and conversations are unchanged.

Full native Mac first-stop, restart and identity gates must pass on this exact
archive; prior 0.1.18 failures remain historical evidence. Publication and
real-host provider acceptance remain pending.

Joint freeze of 2026-11-21 (native combined adapter): Omnigent 0.3.34 source
`d8652e971bdf66133d699052ab9003d39ff69159` and Paseo 0.1.20 source
`aea2da4a83dbd220d8e9aa532ff91f9ac4e2c206`; its combined Pi Web metadata pins
both versions exactly and its VM fixtures include the lifecycle-timeouts
dependency. HA does not use that adapter: HA Pi Agent 0.15.25 bundles Agent
Connect 0.1.24 with the same Omnigent 0.3.34 archive. Full consumer results must
be checked on this candidate.

## HA 0.15.25 freeze and runtime upgrade — 2026-11-26

Agent Connect 0.1.24 is source `ee8f9b437dc8e7e4041dc0c9ef73755951cd5bbb`,
Paseo daemon 0.17.4, runtime `0.17.4-r1-a651f42711da`. The archive above is copied
unchanged. The native combined adapter's matching Omnigent 0.3.39 archive is
SHA-256 `a5eb78fedabb3671cc4d70cc88e5826e1bf6d60075eba444288f3c4478a1ff58`,
source `b2c6d12c171013cb7575fb4161afe17d92d76d87`; the combined patch is
`5e2c36b43f56e9ca8c3c2873d94102a86c75b74973cc23b278c34a2556e678a5`.
Those are an exact pair for that adapter. HA does not apply the combined patch
or use its Pi Web 0.10 overlay: its separate Pi Web 0.12 bridge retains the
0.3.34 Omnigent archive in the table. No Omnigent upgrade is implied here.

The image prebuilds the new runtime in the two layers introduced by `8cfecab`.
The launcher asks the registered plugin about its saved runtime before choosing
it: an obsolete/incomplete saved copy cannot hide a ready image copy. A ready
saved copy remains preferred, explicit `PI_PASEO_RUNTIME_DIR` overrides remain
authoritative, and an unknown plugin or two unready copies retain the saved
path. Selection never changes saved files or daemon identity.

The new daemon has config/agent-record migrations, longer terminal cleanup,
usage and idle-cleanup defaults, and Smart protected-security constraints.
See [HA upgrade and rollback details](PASEO_HA.md#upgrade-and-lifecycle) and the
frozen plugin's README. Local fixtures and checks against an isolated copied
runtime are not final-image or live Supervisor acceptance. Both native images,
compressed layer limits, persisted-data upgrades, stop/restart identity and
actual provider/Smart/Paseo pairing remain release gates.
