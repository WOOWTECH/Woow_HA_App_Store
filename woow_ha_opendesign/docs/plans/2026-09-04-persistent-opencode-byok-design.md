# Persistent OpenCode BYOK profiles — design

**Status:** superseded — OpenCode is fully removed in favour of Pi Local CLI profiles; see `2026-09-04-persistent-pi-byok-design.md`.
**Date:** 2026-09-04  
**Upstream:** OpenDesign `0.21.1` (pinned)  
**Add-on scope:** HA Ingress only; amd64 and aarch64

## Confirmed product decisions

- The add-on bundles OpenCode CLI so OpenDesign BYOK API runs can execute.
- Provider settings are entered from an overlay inside the OpenDesign Settings page, not a separate HA panel.
- Multiple named profiles are stored persistently in `/data`.
- All Home Assistant administrators who can open the existing `panel_admin: true` add-on may view, create, edit, select, and delete full API keys.
- Credentials deliberately survive add-on restarts and are included in Home Assistant cold backups.
- OpenCode is installed at an exact locked version and upgraded only by a reviewed, tested PR; the image never installs `latest` at build or runtime.
- The thin wrapper around the pinned upstream image remains. We will not fork/rebuild OpenDesign source.

These decisions replace the older browser-local-only/no-local-CLI policy. Provider secrets must therefore be documented as add-on data, not as browser-only state.

## Why OpenCode is required

In upstream 0.21.1, API mode creates a daemon run with agent id `byok-opencode`; its runtime definition resolves `opencode-cli` and then `opencode`. OpenDesign turns the selected provider/model/key into a temporary OpenCode provider configuration and process environment for the run. Filling a provider form alone does not bypass that runtime. The current error is therefore the expected result of the intentionally CLI-free image.

## Architecture

```text
HA administrator browser
  └─ authenticated HA Ingress
       └─ nginx :8099
            ├─ OpenDesign daemon :7456 (loopback)
            └─ profile sidecar :7457 (loopback, only nginx-marked requests)
                 └─ /data/opendesign/credentials/byok-profiles.json (0700/0600, UID 1001)

OpenDesign Settings page
  └─ ha-byok-profiles-bridge.js overlay
       ├─ profile CRUD against sidecar
       ├─ copies active profile into OpenDesign's runtime config for this browser
       └─ OpenDesign sends the selected run config to byok-opencode
            └─ pinned OpenCode CLI, per-run provider environment/config
```

The add-on launcher creates `credentials/` only after rejecting symlinks, changes ownership to `open-design:open-design` (UID/GID 1001), and applies mode `0700`; the JSON file is created atomically with mode `0600`. The sidecar binds only `127.0.0.1:7457`, runs as UID 1001, never logs a request body or key, and stores no key outside the credentials JSON file. nginx has an exact `/api/ha-opendesign/byok/` location which removes any client-supplied internal-auth header and sets a private marker for the sidecar. The sidecar rejects calls without that marker. No LAN port is added.

The launcher supervises OpenDesign, nginx, and the sidecar as one unit: an unexpected exit of any peer terminates and reaps the other two. Its bounded TERM/KILL behaviour extends to the third child.

## Stored schema and concurrent administration

```json
{
  "version": 1,
  "revision": 7,
  "activeProfileId": "openrouter-main",
  "profiles": {
    "openrouter-main": {
      "id": "openrouter-main",
      "label": "OpenRouter main",
      "protocol": "openai",
      "baseUrl": "https://openrouter.ai/api/v1",
      "apiKey": "<secret>",
      "model": "anthropic/claude-sonnet-4.6",
      "updatedAt": "2026-09-04T00:00:00.000Z"
    }
  }
}
```

The store validates schema version, ID grammar, label length, supported protocol, HTTP(S) URL where applicable, non-empty model, and a bounded profile count/field length. A `PUT` supplies the prior `revision`; stale writers receive `409` rather than silently replacing another administrator's change. The active ID must refer to an existing profile or be null. The sidecar accepts only full-state replacement after validation, increments the revision, writes a temporary sibling file with `0600`, fsyncs, then renames it. It rejects symlinked credential directory/file paths before read or write.

`GET /api/ha-opendesign/byok/profiles` deliberately returns full API keys because the approved access model allows every HA administrator to read them. Responses have `Cache-Control: no-store`; browser bridge state must not create diagnostic logs or analytics events containing secrets.

## Settings overlay behaviour

nginx injects `ha-byok-profiles-bridge.js` after the existing ingress and export bridges. The script is versioned and pinned to upstream 0.21.1's Settings DOM by E2E tests. It inserts a clearly labelled **HA Persistent BYOK Profiles** panel with:

- profile picker and active-profile badge;
- create, duplicate, rename, edit, save, delete, and set-active controls;
- protocol, base URL, model, and full API-key fields;
- revision-conflict message with reload/retry action;
- an explicit **Import current OpenDesign settings** action for migration of a browser-local provider into `/data`.

On page load and active-profile change, the bridge copies the active profile into the browser's OpenDesign runtime config (`apiProtocol`, `baseUrl`, `model`, `apiKey`, and provider metadata) and dispatches the same storage/update events that the page observes. Consequently the existing upstream API-mode run path sends the active profile to `byok-opencode`; no upstream source patch is required. Editing upstream's ordinary provider controls outside the overlay affects only that browser's current session. The overlay communicates this explicitly and requires **Save profile** for persistent change.

## Pinned OpenCode installation

The Docker build uses a dedicated lockfile-backed runtime prefix, e.g. `runtime/opencode/package.json` and `package-lock.json`, installed with `npm ci --omit=dev --prefix /opt/opencode`. The exact `opencode-ai` version is selected only after the feasibility probe below; no floating tag/range is permitted. The daemon already falls back from `opencode-cli` to `opencode`, so no fake binary alias is necessary unless the probe demonstrates a packaging incompatibility.

Before committing the dependency, a temporary amd64 and aarch64/QEMU image must prove `opencode --version` works under the upstream Alpine base as UID 1001. If npm's package is not musl-compatible on either supported architecture, stop rather than adding an unpinned workaround. Evaluate the official versioned binary/image route, record its checksum/digest and licence, and obtain design review before proceeding.

## Security and operational consequences

- HA backups contain unencrypted profile JSON by design. Backup access is therefore equivalent to provider-key access.
- HA administrators can read every stored key by design. HA non-admin users cannot open the panel under the existing add-on metadata.
- Keys may exist in browser memory, the sidecar request body, daemon run request, and OpenCode child environment during execution. They must not be written to logs, tests, image layers, non-credential `/data` files, or run records. Upstream already sanitizes provider input from persisted run input; this must be regression-tested at the add-on boundary.
- The key store does not make model/provider traffic local: provider requests still leave the add-on to the selected remote endpoint.
- A deleted profile must no longer be offered to new runs; already-running child processes are not retroactively changed.

## Required verification seams

1. **Profile-store HTTP API:** through nginx/HA-Ingress-shaped requests, CRUD, full-key read (approved policy), validation, revision conflict, private-marker rejection, no-store cache header, no symlink escape.
2. **Persistent filesystem behaviour:** UID/GID/mode, atomic replacement, add-on restart persistence, corrupted file gives a bounded recoverable error rather than a crash.
3. **Settings UI:** real Chromium through the Supervisor-style prefix; create/save/select/edit/delete/import flows; reload keeps active profile; bridge updates the OpenDesign runtime config; full key is visible only inside the authenticated admin page.
4. **OpenCode runtime:** image detects exact pinned binary on amd64 and aarch64; a deterministic mock OpenAI-compatible provider receives one run with the selected model/key; no key occurs in container logs or non-credential data paths.
5. **Existing add-on behaviour:** health, non-root processes, ingress navigation, renderer exports, no LAN port, shutdown/restart behaviour remain intact.

## Documentation changes

Update English and Traditional-Chinese README/DOCS/security text to state that profiles are persisted under `/data`, included in cold backups, and readable by HA administrators. Remove the statements that keys never enter `/data`, never reach backups, and that no local AI runtime is installed. Add a provider-key rotation/delete runbook and the exact OpenCode version to release notes.
