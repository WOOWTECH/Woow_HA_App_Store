# Persistent Pi Local-CLI BYOK profiles — design

**Status:** approved design; implementation has not started
**Date:** 2026-09-04
**Upstream:** OpenDesign `0.21.1` (pinned)
**Add-on scope:** HA Ingress only; amd64 and aarch64

## Confirmed product decisions

- Remove OpenCode completely; it is neither bundled nor retained as a fallback.
- Bundle an exact, lockfile-pinned version of the Pi Coding Agent CLI. It is upgraded only in reviewed, tested PRs; no build or runtime operation may resolve `latest`.
- Use OpenDesign's built-in `pi` Local CLI runtime (`pi-rpc`), not its API mode. The add-on will not fork or rebuild the pinned upstream OpenDesign source.
- Provider settings are entered from an overlay inside the OpenDesign Settings page, not a separate HA panel.
- Persist multiple named provider profiles in `/data`, with exactly one add-on-wide active profile. Changing it affects new runs only.
- A profile's model is authoritative. OpenDesign's model selector displays the active model but cannot override it.
- Supported profile kinds are Anthropic, OpenAI, Google, and OpenAI-compatible (including OpenRouter and compatible custom endpoints). Native Azure deployment URL behaviour is not promised until a compatibility spike passes.
- All Home Assistant administrators who can open the existing `panel_admin: true` add-on may view, edit, select, and delete full API keys. Credentials deliberately survive restarts and are included in Home Assistant cold backups.

These decisions supersede `2026-09-04-persistent-opencode-byok-design.md`.

## Why Pi Local CLI is the correct seam

OpenDesign `0.21.1` already defines the `pi` runtime. It probes `pi --version`, discovers models with `pi --list-models`, launches `pi --mode rpc`, and maps Pi RPC stream events, images, model selection, and thinking levels to an OpenDesign run. Installing Pi and selecting the daemon-mode `pi` runtime therefore uses an existing upstream integration seam.

This differs from upstream API mode: API-mode BYOK is hard-wired to `byok-opencode`, so installing Pi alone cannot satisfy that preflight. The Settings bridge instead configures the browser for the native Local CLI `pi` runtime. This avoids a source fork, an API-mode request rewrite, and an OpenCode compatibility dependency.

## Architecture

```text
HA administrator browser
  └─ authenticated HA Ingress
       └─ nginx :8099
            ├─ OpenDesign daemon :7456 (loopback)
            └─ profile sidecar :7457 (loopback; nginx-marked requests only)
                 └─ /data/opendesign/credentials/byok-profiles.json (0700/0600, UID 1001)

OpenDesign Settings page
  └─ ha-byok-profiles-bridge.js overlay
       ├─ profile CRUD against the sidecar
       ├─ selects active profile and configures Local CLI agent `pi`
       └─ locks display to the profile model

OpenDesign daemon
  └─ /usr/local/bin/pi profile wrapper
       ├─ reads an immutable snapshot of the active profile
       ├─ creates a private, short-lived Pi config directory
       ├─ writes models.json with $OD_PI_PROFILE_KEY interpolation only
       └─ execs the exact pinned real Pi CLI in RPC mode
```

The add-on launcher creates `credentials/` only after rejecting symlinks, changes ownership to `open-design:open-design` (UID/GID 1001), and applies mode `0700`. The JSON is atomically replaced with mode `0600`. The sidecar binds only `127.0.0.1:7457`, runs as UID 1001, never logs a request body or key, and stores no key outside the credential JSON. nginx has an exact `/api/ha-opendesign/byok/` location that removes any client-supplied internal-auth header and sets a private marker. The sidecar rejects requests without that marker. No LAN port is added.

The launcher supervises the daemon, nginx, and sidecar as a unit: an unexpected exit of any peer terminates and reaps the other two.

## Profile schema and provider mapping

```json
{
  "version": 1,
  "revision": 7,
  "activeProfileId": "openrouter-main",
  "profiles": {
    "openrouter-main": {
      "id": "openrouter-main",
      "label": "OpenRouter main",
      "protocol": "openai-compatible",
      "baseUrl": "https://openrouter.ai/api/v1",
      "authStyle": "bearer",
      "apiFlavor": "openai-completions",
      "apiKey": "<secret>",
      "model": "anthropic/claude-sonnet-4.6",
      "updatedAt": "2026-09-04T00:00:00.000Z"
    }
  }
}
```

The store validates schema version, ID grammar, label/model lengths, a bounded profile count, and protocol-specific fields. Anthropic, OpenAI, and Google have fixed official endpoints and map respectively to Pi's `anthropic-messages`, `openai-responses`, and `google-generative-ai` APIs. OpenAI-compatible profiles require an HTTPS base URL and select `openai-completions` or `openai-responses`; their supported authentication styles are `bearer` and `api-key`. Limited compatibility flags may be exposed for servers that do not accept `developer` role or reasoning effort.

OpenRouter and standard compatible proxies are in scope. Azure-like compatible gateways can use an `api-key` header. Official Azure deployment endpoints and `api-version` routing require a separate compatibility test before being advertised as supported.

A `PUT` supplies the prior `revision`; stale writers receive `409`. The active ID must refer to an existing profile or be null. The sidecar accepts only validated full-state replacement, increments revision, fsyncs a temporary sibling file, then renames it. It rejects symlinked credential directories/files before every read or write.

## Pi wrapper, model authority, and secret handling

The wrapper is the executable OpenDesign resolves as `pi`; it delegates harmless detection calls such as `--version` to the real pinned binary. For a run it validates and snapshots the active profile, creates a unique `0700` temporary Pi agent directory, and writes a provider configuration whose `apiKey`/`headers` reference `$OD_PI_PROFILE_KEY`. It exports that key only to the Pi child, forces the profile's provider/model, and removes the temporary directory after the child exits.

No API key is written to Pi `auth.json`, Pi `models.json`, Pi sessions, the image, logs, or any persistent path other than `byok-profiles.json`. The active-profile snapshot means a concurrent switch/delete affects only later runs. Missing, corrupt, invalid, or inactive profiles fail new runs with a bounded, key-free error.

The bridge makes `pi` the selected Local CLI agent and presents the active profile/model as authoritative. It must not monkey-patch private React state: it uses the same public browser configuration/storage events that OpenDesign observes. The ordinary upstream provider controls are session-only and the ordinary model selector is displayed but disabled/explained while Pi profiles are active.

## Security and operational consequences

- HA backups contain unencrypted profile JSON by design. Backup access is provider-key access.
- HA administrators can read every stored key by design; non-admin users cannot open the add-on under existing metadata.
- Keys may exist briefly in browser memory, sidecar request bodies, the wrapper process, and the Pi child environment. They must not occur in logs, test artifacts, image layers, Pi state, non-credential `/data`, OpenDesign run records, or generated artifacts.
- The store does not proxy provider traffic. Requests leave the add-on directly for the selected provider endpoint.
- A deleted profile is unavailable to new runs; already-running Pi processes retain their launch snapshot.

## Required verification seams

1. **Pi feasibility:** exact CLI works as UID 1001 on amd64 and aarch64, reports a version, exposes a configured model, and completes a Pi RPC call to a deterministic fake compatible provider.
2. **Profile-store HTTP API:** nginx/Ingress-shaped profile CRUD, full-key read, validation, conflict, private-marker rejection, no-store response, symlink escape rejection, and persistence/mode tests.
3. **Pi wrapper:** profile-to-Pi config mapping for all four protocols, model override rejection, immutable active snapshot, temporary-directory cleanup, and no secret persistence outside the approved file.
4. **Settings UI:** real Chromium under a Supervisor-style prefix; create/edit/select/delete profiles; full key visibility; reload/restart retention; runtime changes to Local CLI Pi; active model remains authoritative.
5. **Execution and regression:** real Pi executes against a fake provider after restart; key-leak scan; health, non-root processes, ingress navigation, renderer exports, no LAN port, and shutdown semantics remain intact.

## Documentation changes

Update English and Traditional-Chinese README/DOCS/security text to say profiles persist under `/data`, are included in cold backups, and are readable by HA administrators. Document the supported Pi provider kinds, active-profile semantics, model authority, rotation/deletion runbook, exact Pi version, and no-LAN posture. Remove statements describing OpenCode, OpenCode BYOK, or an OpenCode fallback.
