# Persistent OpenCode BYOK profiles — implementation plan

**Status:** superseded — OpenCode is fully removed in favour of Pi Local CLI profiles; see `2026-09-04-persistent-pi-byok-implementation.md`.
**Former prerequisite:** `2026-09-04-persistent-opencode-byok-design.md`.
**Execution model:** superseded; retained only as a decision record.

## Task 0 — architecture feasibility spike (no product commit)

1. In a disposable remote build context, create a temporary lockfile using an exact `opencode-ai` version selected from official release metadata.
2. Build temporary images for `linux/amd64` and `linux/arm64`/QEMU against the pinned OpenDesign Alpine base.
3. Run as UID 1001: `opencode --version`; confirm the detected executable is one of upstream's accepted runtime names and no unsupported native-library error occurs.
4. Record exact version, package-lock integrity, image size delta, executable path, license notice, and elapsed build time.
5. If either architecture fails, stop. Do not substitute `latest`, install at runtime, add an unverified third-party binary, or begin UI work. Produce an alternatives decision record.

**Evidence:** command output for both architectures, no resulting source change.

## Task 1 — locked CLI image slice

1. Add a dedicated lockfile-backed OpenCode runtime prefix. Docker must use `npm ci --omit=dev`; it must not call `npm install ...@latest`.
2. Add a Docker build assertion for exact binary availability/version and ensure package files are owned/readable by UID 1001.
3. Replace the smoke suite's `opencode` prohibition with exact-binary detection/version assertions while retaining prohibitions for every other unapproved local CLI.
4. Add a focused test that makes the build assertion Red when the binary is absent/wrong, then Green with the locked installation.
5. Build/run amd64 smoke; run aarch64 build. Only if measured PR critical path stays inside 15 minutes should aarch64 runtime smoke become blocking; otherwise make it nightly.

**Done when:** no floating package version; image is non-root at runtime; both architecture builds work; existing exports/integration smoke remains green.

## Task 2 — credential-store sidecar, filesystem, and launcher slice

1. Implement `/opt/ha-opendesign/ha-byok-store.mjs` on `127.0.0.1:7457`. It exposes only `GET`/`PUT /api/ha-opendesign/byok/profiles` and requires nginx's private marker header.
2. Implement schema validation, bounded fields/profile count, revision-based optimistic concurrency, `Cache-Control: no-store`, redacted errors, symlink-safe parent validation, and atomic `0600` writes.
3. Extend `ha-opendesign` launcher to prepare `/data/opendesign/credentials` as UID 1001/mode 0700, launch/reap the sidecar, and stop every peer when any exits.
4. Add nginx exact-location routing that clears any client-provided private marker then sets a trusted value. Existing routes must retain their current rewrite/streaming properties.
5. TDD public seam tests: no marker is rejected by the sidecar; nginx-routed valid ingress request can create/read profiles; stale revision gets 409; invalid profile does not replace prior content; symlink storage path is rejected before write; restart preserves state/modes.

**Done when:** storage tests use the HTTP endpoint and real `/data` mount, not private store functions; no secret body is written to test output/logs.

## Task 3 — Settings bridge overlay slice

1. Add `ha-byok-profiles-bridge.js`; inject it after `ha-ingress.js` in nginx only on valid ingress pages.
2. Build the overlay with accessibility labels and profile picker/create/edit/save/delete/set-active/import actions. It is the only persistent-profile UI; ordinary upstream controls remain explicitly session-only.
3. Load profiles with `cache: no-store`; supply revision on save; render a conflict/reload affordance after 409; never console-log profile data.
4. On active selection, update OpenDesign's browser config and emit the minimal storage/change events required for the upstream 0.21.1 run path. Do not monkey-patch OpenDesign private React state.
5. TDD browser E2E via existing Supervisor-style proxy: panel appears in Settings; creates multiple profiles; full key displays per approved policy; changing active profile changes submitted `byokProvider` provider/model/key; reload/restart retains it; import turns existing current browser config into a persisted profile; delete active profile has defined fallback.

**Done when:** E2E asserts user-visible UI and a public run payload, survives hard reload, and does not expose secret values in Playwright diagnostics/artifacts.

## Task 4 — actual BYOK OpenCode execution slice

1. Start a deterministic OpenAI-compatible fake provider on an isolated Docker network for test only. It validates the expected authorization key/model and returns a fixed streaming response; test keys are non-secret literals.
2. Drive the public run API through the real Settings/Ingress path with the selected persisted profile and wait for terminal status.
3. Assert the fake provider saw one correctly authenticated request and that OpenCode produced the expected completed run/artifact behaviour. Assert a deleted/invalid active profile blocks a new run before provider contact.
4. Check container logs, non-credential `/data` paths, generated artifacts, and persisted run records do not contain the test key. The credential file may contain it by design.
5. Repeat after add-on restart to prove persisted profile executes without browser re-entry.

**Done when:** the actual `byok-opencode` binary, not a mock internal runtime, handles a complete deterministic API run.

## Task 5 — regression, documentation, and release policy slice

1. Add exact-location/nginx static tests, launcher three-peer lifecycle tests, credential-store unit/HTTP tests, and include new files in syntax checks.
2. Extend the container smoke orchestration with isolated port/volume cleanup and artifacts redacted by default.
3. Update README, Traditional-Chinese README, DOCS, architecture/security notes, changelog, and release instructions to describe persistent backup-included credentials, HA-admin visibility, profile rotation/deletion, OpenCode version, and no-LAN posture.
4. Update the TDD test plan where its old browser-local/no-CLI assumptions no longer apply; retain export and ingress test policy.
5. Run local validation, fresh amd64 build+container smoke, aarch64 build, independent spec review, code-quality review, and complete CI before publication.

## Parallelization boundaries

- Read-only research can run in parallel: npm/architecture compatibility, upstream API route discovery, test-matrix review.
- One writer owns storage/launcher/nginx because those files share lifecycle and security invariants.
- One writer owns the injected bridge and its browser E2E; it begins only after the sidecar HTTP contract is stable.
- Runtime fake-provider execution begins after both CLI availability and profile store are verified.
- Documentation can be drafted in parallel but is integrated after final behaviour is fixed.

## Hard stop conditions

Stop and obtain a decision if: OpenCode cannot run on either target architecture; a profile key is written outside the approved credential file; direct requests can reach the sidecar without nginx's marker; injection cannot update the upstream runtime config through a stable public browser seam; a key appears in logs/artifacts; or PR critical path exceeds 15 minutes after eliminating duplicate work.
