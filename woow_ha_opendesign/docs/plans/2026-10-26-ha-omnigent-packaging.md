# HA Omnigent packaging implementation plan

**Goal:** Restore the accepted native Omnigent integration in HA packaging without choosing a release version or publishing anything.

**Architecture:** OpenDesign's daemon owns the host and derives private state from `OD_DATA_DIR/integrations/omnigent`. HA keeps its ingress, MCP, terminal, renderer and four existing engines. Legacy home and retired backups remain inert; no global Omnigent home override is introduced.

**Tech stack:** Bash launcher, Docker, Node test runner/Playwright, Python metadata validation, existing GitHub build workflow.

1. Remove Dockerfile plugin deletion and launcher retirement. Clear inherited legacy Omnigent location overrides before child startup. Require the native plugin and preinstalled SDK at image build; retain all existing core/version pins pending coordinator delivery.
2. Execute the launcher against isolated child processes and temporary data. Cover fresh/legacy homes, configured private state, restart, cold archive restore, environment isolation and child shutdown. Replace only obsolete removal assertions.
3. Extend container smoke with native daemon fresh/disable/enable contracts, four-engine inventory, private persistent state and GUI setup through ingress. Add an authenticated, opt-in candidate lifecycle harness for real setup, managed-host resume, disable/re-enable, disconnect, cold backup restore and upgrade. Use a private credential file and never log its contents.
4. Update README files, DOCS and Unreleased changelog with the pending pin, fresh-login migration, sensitive backup contents, rollback and candidate workflow instructions. Leave config version unchanged; coordinator must reconcile parallel Paseo before release.
5. Run `tests/run.sh`, meaningful launcher tests and syntax checks. Report unavailable container checks honestly; no Docker or final core is available in this worktree session. Local commit only after passing checks.

The cross-channel plan is `../implementation-plan.md`. Native/core/chart source belongs to other agents; only this HA worktree is writable for this task. Publication is the coordinator's responsibility, through PR/check gates.
