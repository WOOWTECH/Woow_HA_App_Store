# HA Agent Connect 0.1.24 implementation plan

**Goal:** Finish the 0.15.25 candidate with frozen Agent Connect 0.1.24 and avoid reinstalling a runtime already supplied by the image after a persisted-HOME upgrade.

**Architecture:** Keep HA's official Pi Web 0.12 bridge and existing Omnigent pin. Ask the registered Agent Connect plugin whether the saved or bundled runtime is ready; explicit runtime overrides remain authoritative. Preserve the two runtime COPY layers introduced by `8cfecab`.

**Tech stack:** Node.js 22, Node test runner, Playwright, nginx, frozen npm archives, multi-stage Dockerfile (inspection only locally).

## 1. Inspect and preserve prior work

- Read root and ancestor AGENTS.md / CLAUDE.md, the frozen plugin README, launcher, lifecycle, runtime layout, image smoke and CI.
- Record starting status/diff and archive checksums under `.local-validation/ha-agent-connect-20261126/` in this worktree. Keep the initial dirty work; do not reset or amend.
- Confirm the archive/source/runtime pins in `candidate-packages/manifest.json` and `cli-runtime/versions.json`. Root add-on version remains 0.15.25.

## 2. Finish runtime choice and launcher coverage

- Review `rootfs/usr/local/lib/pi-paseo-ha/{launch,lifecycle,runtime-dir}.mjs` and `tests/paseo-{launch,runtime-dir,contract}.test.mjs`.
- Cover fresh HOME, old/incomplete saved runtime, a ready saved runtime, unavailable/custom plugin, unavailable image runtime and explicit overrides. Assert saved files and identity are retained.
- Use the frozen plugin's readiness check and package discovery; keep selection free of installs, lifecycle operations and data migration.
- Keep `tests/paseo-runtime-dir.test.mjs` in the required build workflow's Node test job.

## 3. Match native verification to the new runtime

- Update `tests/paseo-native-runtime.mjs` and `tests/paseo-image-smoke.mjs` for the frozen plugin's exact native module layout, PID protocol and readiness receipts.
- Verify stale PID recovery without signalling a real host process, owner generation protection and persistent guard identity. Cover daemon identity bytes across runtime selection.
- Preserve `patches/split-paseo-runtime.mjs` and both plain final COPYs. Local synthetic layer tests cannot establish final compressed layer sizes.

## 4. Document the candidate and upgrade behavior

- Update README variants, CHANGELOG.md, DOCS.md, docs/PASEO_HA.md, docs/AGENT_CONNECT_CANDIDATE.md and tests/README.md.
- Describe saved-runtime selection, retained identity, restart/config migration, rollback limits, the Smart protected-security constraint and new upstream defaults.
- Explain why HA retains its distinct bridge and Omnigent pin despite the native combined adapter's 0.1.24/0.3.39 pair.

## 5. Verify and commit locally

- Run relevant Node suites (including pins, lifecycle, runtime selection, launcher shutdown, layers, Ingress and settings), frozen-package contracts and available browser checks with isolated data inside the persistent worktree.
- Exclude mutation tests on this host. Do not build images, deploy, push, open/update PRs or mutate remotes.
- Record exact commands, results, skips and limitations in persistent logs and a handoff. Inspect the final diff and commit only after checks pass, using the repository's historical author identity and `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Remaining release acceptance: native amd64/aarch64 final images, each compressed layer below 256 MiB, offline image smoke, real Supervisor persisted-data upgrade and branded client/provider pairing.
