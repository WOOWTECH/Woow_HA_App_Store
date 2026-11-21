# Agent Connect release candidate — 2026-11-21

This is coordinated source preparation, not a published release or deployment.
The candidate archives are unpublished `npm pack` results, vendored in
`candidate-packages/` for reviewable builds without inventing release URLs.
Native pins use local `file://` inputs; HA uses verified `COPY` inputs. Their
SHA-256 values identify the actual bytes. Publishing or repacking later requires
coordinated consumer updates and the normal release gates.

| Input | Candidate version | SHA-256 |
| --- | --- | --- |
| `@woowtech/pi-agent-shared-runtime` | 0.1.6 | `0914069fb0cf83f258cf81034bb16573f6e4242e8779cea47b4a5e841f98a937` |
| `@woowtech/pi-paseo` (Agent Connect) | 0.1.20 | `1574c1bd1d0023c7b536c9feb773e1cdded929104d79cfb05b1deda5846203f8` |

| `@woowtech/pi-omnigent-plugin` | 0.3.34 | `e9e80783881f8a036cbf922d2f50fad860dac3bd23e170dda768ab3c56107945` |

HA retains official Pi Web 0.12.0 with its independent Ingress bridge. Its
Omnigent plugin is now the same frozen0.3.34 archive as native. HA does not
apply its 0.10 combined adapter; the official0.12 bridge remains in use. The Agent Connect GUI supports older user-selected
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
pending. HA addon version is unchanged: a successful no-version-change upgrade
comparison does not exercise a Supervisor upgrade. The current HA connector's
`/addons` call returned `Unknown command`, so installed-addon access is unconfirmed.

Agent Connect now uses persistent SQLite guards on macOS; Linux retains flock.
Actual Apple Silicon (Node 22.23.4) and Intel (Node 22.19.0) CI passed OS-lock,
state and onboarding tests, plus real daemon start, stop, restart and identity
retention. The macOS lifecycle uses no provider credentials or model turns.
[Mac verification run](https://github.com/WOOWTECH/pi-paseo-plugin/actions/runs/44867850835)
does not substitute for signed-installer or interactive provider acceptance.
Darwin stale daemon recovery remains conservative; this patch does not claim
Linux PID-birth recovery on macOS. Windows uses the supported WSL2 Linux path.

Agent Connect source `aea2da4a83dbd220d8e9aa532ff91f9ac4e2c206`, runtime
`0.11.2-r4-4cf9d40940bf`. This candidate adds selected-target brand identity.
An older running runtime requires explicit stop/start; non-Linux recognition
requires matching PID, startedAt and runtime revision in the persisted record.
Version 0.1.20 retains the 0.1.19 fix, extending the supervisor stop budget to 30 seconds around the
20-second nested daemon stop, including replacement shutdown. Full native Mac
first-stop, restart and identity gates must pass on this exact archive; prior
0.1.18 failures remain historical evidence. Publication and real-host provider
acceptance remain pending.

Joint freeze: Omnigent0.3.34 source `d8652e971bdf66133d699052ab9003d39ff69159` and Paseo0.1.20 source `aea2da4a83dbd220d8e9aa532ff91f9ac4e2c206`. The combined PiWeb metadata pins both versions exactly and its VM fixtures include the lifecycle-timeouts dependency. Full consumer results must be checked on this joint candidate.
