# Persistent Pi Local-CLI BYOK profiles — implementation plan

**Prerequisite:** approved `2026-09-04-persistent-pi-byok-design.md`.
**Execution model:** one TDD vertical slice at a time; do not combine image, storage, bridge, wrapper, and documentation changes into one unreviewable change.

## Task 0 — architecture feasibility spike (no product commit)

1. Select an exact `@earendil-works/pi-coding-agent` release from official metadata and create a temporary dedicated lockfile.
2. Build disposable images for `linux/amd64` and `linux/arm64`/QEMU against the pinned OpenDesign Alpine base.
3. As UID 1001, execute the real CLI's `--version`; exercise the wrapper's detection path; give it a generated non-secret `models.json`; and verify `--list-models` recognizes the configured provider/model.
4. Start a deterministic OpenAI-compatible fake provider on an isolated test network. Run `pi --mode rpc` through the wrapper with an active test profile and verify one expected authenticated/modelled request plus a completed RPC response.
5. Record exact version, lockfile integrity, executable path, license notice, image delta, elapsed build time, and both architecture outputs.
6. Stop if either architecture, RPC, or key-isolation check fails. Do not add `latest`, a runtime install, an unverified third-party binary, or OpenCode fallback. Produce a decision record instead.

**Evidence:** command output for both architectures and no resulting product source change.

## Task 1 — locked Pi image and wrapper slice

1. Add `runtime/pi/package.json` and its committed lockfile. Docker installs it with `npm ci --omit=dev` into a dedicated prefix, without OpenCode packages.
2. Add the Node-based Pi profile wrapper plus a stable path to the real Pi binary. It must safely pass through version/detection calls and never emit profile values.
3. Make the wrapper's actual-run path Red/Green: load/validate the active profile, create a unique `0700` temporary agent directory, generate `models.json` using only `$OD_PI_PROFILE_KEY` interpolation, force the profile model, exec Pi, and remove temporary state.
4. Remove all OpenCode runtime installation/detection assumptions and add assertions that neither `opencode` nor `opencode-cli` is bundled.
5. Build/run amd64 smoke and run an aarch64 build. Keep architecture runtime smoke blocking only when the measured PR critical path remains under 15 minutes; otherwise make it scheduled/nightly.

**Done when:** exact Pi CLI is used non-root on both architectures, OpenCode is absent, wrapper errors are bounded and key-free, existing export/Ingress smoke still passes.

## Task 2 — profile sidecar, filesystem, nginx, and launcher slice

1. Implement `/opt/ha-opendesign/ha-byok-store.mjs` on `127.0.0.1:7457`, exposing only `GET`/`PUT /api/ha-opendesign/byok/profiles` behind nginx's private marker.
2. Implement schema validation for the four Pi profile protocols, bounded fields/profile count, revision conflict handling, `Cache-Control: no-store`, redacted errors, symlink-safe parent/file checks, and atomic `0600` writes.
3. Extend `ha-opendesign` to prepare `/data/opendesign/credentials` as UID 1001/mode `0700`, launch/reap the sidecar, and stop every peer if one exits.
4. Add an nginx exact-location route that clears client-supplied marker headers then adds its trusted marker. Preserve existing route rewrite and streaming semantics.
5. TDD public seam tests: direct sidecar calls fail; nginx-routed ingress calls create/read full profiles; stale revisions return 409; invalid data preserves prior state; symlinked storage is rejected; restart preserves contents, ownership, and mode.

**Done when:** tests use real HTTP and a real `/data` mount, and never write a secret body to output/logs.

## Task 3 — Settings bridge and Pi Local-CLI selection slice

1. Add and nginx-inject `ha-byok-profiles-bridge.js` after the existing Ingress/export bridges on valid Ingress pages.
2. Implement accessible profile picker/create/duplicate/rename/edit/save/delete/set-active controls. It is the sole persistent-profile UI; upstream controls remain explicitly session-only.
3. Fetch with `cache: no-store`, use `revision` on save, show a reload/retry UI for 409, and never log profile data.
4. On active profile change, update OpenDesign through public configuration/storage events to select daemon-mode `pi`. Present the active profile's model and disable/explain the upstream model selector. Do not patch private React state.
5. TDD Chromium E2E through the Supervisor-style prefix: create multiple profiles; show full key under the approved policy; switch active profile; reload/restart persistence; set Pi Local CLI; verify profile model cannot be overridden; delete-active fallback; and import an existing browser-local setting as a profile when representable.

**Done when:** the E2E asserts user-visible behaviour and public configuration state without Playwright artifacts containing real keys.

## Task 4 — real Pi execution and provider compatibility slice

1. Use a deterministic isolated fake OpenAI-compatible provider to assert authorization header style, endpoint, model, and fixed streaming response for a real Pi RPC run.
2. Drive a run through the Settings/Ingress path and await its OpenDesign terminal status. Prove that a persisted profile executes after add-on restart without browser key re-entry.
3. Add focused mapping tests for Anthropic, OpenAI, Google, bearer compatible, and api-key compatible configuration. Ensure configured model authority overrides a changed OpenDesign model preference.
4. Test active-profile snapshot behaviour: a switch/delete after a wrapper has started does not alter that run, but blocks/newly changes later runs as applicable.
5. Add a native Azure deployment URL and `api-version` compatibility spike. Only document it as supported if the real Pi request shape succeeds; otherwise state that a compatible gateway is required.
6. Scan container logs, generated artifacts, OpenDesign run records, Pi temporary/persistent directories, and all non-credential `/data` paths for a fake test key. The credentials file alone may contain it.

**Done when:** real Pi—not a mocked internal runtime—handles a deterministic end-to-end run for every advertised protocol mapping.

## Task 5 — regression, documentation, and release policy slice

1. Add exact nginx, launcher three-peer lifecycle, profile-store HTTP, and wrapper tests; include all new files in syntax checks.
2. Extend container smoke with isolated port/volume cleanup, fake-provider orchestration, and redacted default artifacts.
3. Update README, Traditional-Chinese README, DOCS, architecture/security notes, changelog, and release instructions for persistent backup-included credentials, HA-admin visibility, four Pi provider kinds, active-profile/model semantics, rotation/deletion, exact Pi version, and no-LAN posture.
4. Mark the prior OpenCode design and implementation plans superseded; update the TDD test plan where its old assumptions no longer apply while retaining export and Ingress policy.
5. Run local validation, fresh amd64 build plus container smoke, aarch64 build, independent spec review, code-quality review, and complete CI before publication.

## Parallelization boundaries

- Read-only research can run in parallel: Pi Alpine compatibility, Pi provider mapping, upstream Local-CLI configuration seam, and test-matrix review.
- One writer owns wrapper/storage/launcher/nginx because these share secret and lifecycle invariants.
- One writer owns the injected Settings bridge and browser E2E after the sidecar contract is stable.
- Provider execution begins only after the exact CLI, wrapper, and store have verified seams.
- Documentation can be drafted in parallel but is integrated only after final behaviour is fixed.

## Hard stop conditions

Stop and obtain a decision if: Pi fails on either target architecture; OpenCode remains bundled or reachable; any key is written outside the approved credential file or the Pi child's transient environment; direct requests reach the sidecar without nginx's marker; the bridge cannot select Pi through a stable public browser seam; the profile model can be silently overridden; a key appears in logs/artifacts; or the PR critical path exceeds 15 minutes after eliminating duplicate work.
