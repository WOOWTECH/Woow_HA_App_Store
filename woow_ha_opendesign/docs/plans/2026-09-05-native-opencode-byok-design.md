# Native OpenCode API BYOK — design

**Status:** approved
**Date:** 2026-09-05  
**Upstream:** OpenDesign `0.21.1` (pinned)  
**Target:** `0.1.4`

## Decisions

Use OpenDesign's native API BYOK flow only. Provider, model, and API key belong solely to the HA administrator browser's `localStorage`; they must not be written to `/data`, image layers, add-on options, logs, tests, or backups. Bundle exact-version OpenCode because upstream API mode uses the `byok-opencode` runtime, which detects `opencode-cli` then `opencode`. Pi and persistent BYOK profiles are removed entirely.

```text
browser localStorage -> authenticated HA Ingress -> nginx -> OpenDesign API mode
  -> byok-opencode -> locked OpenCode CLI -> selected provider API
```

The upstream daemon constructs temporary per-run OpenCode configuration/environment from the browser request. No add-on credential store or bridge is required.

## Removal and migration

Remove Pi package/wrapper, profile bridge/store, profile nginx route, profile sidecar, and third-peer launcher supervision. On add-on boot safely remove obsolete `/data/opendesign/credentials` without following symlinks, so keys from the withdrawn persistence feature cannot remain on disk. This intentionally deletes prior profiles; administrators re-enter settings in their browser.

## Packaging and verification

Use an official OpenCode release at an exact version with committed lockfile or immutable artifact. Prove real OpenCode works in the pinned Alpine base as UID 1001 on amd64/aarch64 and satisfies OpenDesign detection; do not use fake aliases or floating/runtime installation. Test a deterministic native `byok-opencode` OpenAI-compatible streaming run, inspect logs and `/data` for key leakage, and retain existing ingress/export/non-root/no-LAN regression coverage. Release only after both architecture images pass; HA validation stops when browser Ingress is ready for the administrator to enter a fresh OpenRouter key and start a native run.
