# HA native Omnigent packaging handoff — 2026-10-26

Base: `a296fffcaf50e178080de5148bee48fdd3cb9c5b` (released 0.2.6). Worktree: `ha/`, branch `feat/omnigent-channels-20261026`. This patch is for local cherry-pick; no push, merge, dispatch, image publication or real HA/runtime operation was performed.

## Outcome and retained pins

The add-on stops deleting the native plugin and stops retiring Omnigent data at every boot. The launcher clears inherited legacy home/server/status location overrides so the native service can use `OD_DATA_DIR/integrations/omnigent/host`. It neither copies nor adopts historical home/backup credentials. The original four engines, ingress, MCP, terminal, export entry, ports and options are retained.

Version remains **0.2.6**; no final version was chosen. All existing core references remain **20261024.0943**, digest `sha256:ffbb2bd070c488d79d960ee72fb7717f43791af6a4ae1585943598ad444a76e0`. This old core does **not** ship the restored integration. The new Dockerfile native-plugin/SDK contract deliberately rejects it. Main must supply the final immutable pin and reconcile the other team's 0.2.7/Paseo work before release. No files in that team's worktree were changed.

## Verification evidence

- `bash tests/run.sh`: PASS, including metadata, vendor integrity, 27 Python rules tests, sign-in patch/workflow policies, 71 Node tests (0 failures), 26 import-core cases (0 failures), pin-core and all Node/shell syntax checks.
- `node --test tests/launcher-state.test.mjs`: PASS. Executes the real launcher with isolated child processes and temporary paths: empty installation, inert legacy/retired data, private new state, restart, actual cold tar archive/restore, child environment stripping, signal delivery/reaping, and awaiting daemon shutdown.
- Two temporary mutation runs: restoring per-boot retirement and removing legacy-environment clearing each fail the launcher behavior test. The original regression cannot pass unnoticed.
- `nginx -t`: PASS using only the read-only nginx binary/libraries/mime.types from the user-specified rootfs. Config/runtime paths were copied or redirected to a temporary directory; no shared rootfs/runtime was changed. This checks syntax, not actual HA routing.
- `git diff --check`: PASS.
- Shellcheck is unavailable in this session and was explicitly skipped by the normal runner. Docker is unavailable; no image build, browser container smoke, authenticated host acceptance, or actual HA Supervisor test was run here.

## Container gates delivered, not yet executed

`tests/container-smoke.sh` now uses a real daemon/API and browser plugin form through the existing ingress proxy. It seeds only fake legacy values, requires the native bundled plugin and exactly four installed engines, rejects invalid/cross-origin/no-login actions, preserves disabled state across recreation/root-owner restoration, then checks enable/setup fields and cleared browser credentials. Existing MCP/BYOK/exports remain in the same smoke.

`tests/omnigent-connected-smoke.sh <candidate-image> <0600-private-login.json> [upgrade-image]` is opt-in. It owns all test containers/volumes, uses a read-only credential file, and checks actual four-engine reply/stop receipts, one unprivileged host/supervisor, automatic startup resume before any status request, identity persistence, cold archive restore with root owners, optional image replacement, disable/re-enable/new login/disconnect, and the supervisor's `stopped` receipt before reboot. Logs and API payloads are never dumped. Do not run it against a production account; model use and test-account session/host history are real.

Native host cleanup is an explicit incoming-core gate, not proven by the local stub test: the HA launcher currently allows 5 seconds before KILL, whereas the legacy kit has a longer fallback. The incoming daemon must close its managed host within the HA deadline, or the coordinator must reconcile and retest those budgets. The stopped receipt and no-KILL checks fail if namespace destruction only masks a surviving host.

## Upgrade and publication handoff

Retired 0.2.0/0.2.1 users must enter URL/account/password anew in the GUI; their archives are retained. New private state survives `/data` retention and backup. Backups contain Omnigent identity/tokens and archived credentials; stop the original identity before restoring elsewhere. Rollback to a release without this integration requires the pre-upgrade backup.

After the final core is public, main runs `.github/scripts/pin-core.sh <tag> <digest>`, updates this candidate wording, reconciles then-current main/Paseo, chooses an unused version and reruns all gates. Candidate CI invocation, only after the coordinator publishes the non-main candidate branch:

```sh
gh workflow run build.yml --repo WOOWTECH/Woow_ha_opendesign_add_on --ref <candidate-branch>
```

That branch takes the existing read-only validation/smoke/nonrelease path. Main's version-bump PR/check gates then govern immutable image/Release publishing and Store/Local Download synchronization. Actual HA backup/fresh-restore/Ingress acceptance remains the other release workstream's responsibility. Compare their final released source/version/catalog receipts; this patch does not publish the old 0.2.6 configuration as a new release.

## Changed files

- Packaging: `Dockerfile`, `rootfs/usr/local/bin/ha-opendesign`.
- Existing tests: `tests/container-ingress-browser-e2e.mjs`, `tests/container-smoke.sh`, `tests/core-base.test.mjs`, `tests/launcher.test.mjs`, `tests/validate.py`, `tests/run.sh` (also suppresses test-generated Python bytecode).
- New tests: `tests/launcher-state.test.mjs`, `tests/container-omnigent-contract.mjs`, `tests/omnigent-browser-contract.mjs`, `tests/container-omnigent-connected.mjs`, `tests/omnigent-connected-smoke.sh`.
- Documentation: `README.md`, `README_zh-TW.md`, `DOCS.md`, `CHANGELOG.md`, `docs/plans/2026-10-26-ha-omnigent-packaging.md`, this validation handoff.
