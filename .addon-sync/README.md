# WOOW HA addon distribution

Source repositories publish validated snapshots to their own `woow-addon-sync/notification.json` branch using their own short-lived `GITHUB_TOKEN`. No cross-repository PAT is distributed to producers.

The Store workflow reads these public notifications, validates source identity, immutable commit/context/archive/config checksums, successful publisher workflow receipts, configured CI and per-architecture published images. It refuses downgrades and out-of-order snapshots. Store sidebar metadata policy is retained. Stable catalog: `.addon-sync/catalog.json`.

Every source repository's `woow-addon-sync.yml` calls the reusable [`woow-addon-publish.yml`](../.github/workflows/woow-addon-publish.yml) at `@main`, which checks out this Store's `main` tooling and registry at run time; a registry change (`ref_policy`, `required_workflows`) therefore reaches every publisher without editing a source repository. The consumer still re-applies this Store's checked-in registry policy itself, so a publisher run that started before a registry change cannot relax it: a `release` source must name a published, non-prerelease Release commit; a `main` source must name a commit on the registered default branch; every `required_workflows` entry must have succeeded for that commit (or for an unchanged runtime); and the publisher receipt must be a run of the default branch's `woow-addon-sync.yml`.

After a successful Store update, the same workflow uses the **ha-rebrand-only write deploy key** in the `store-sync` environment secret `REBRAND_SYNC_SSH_KEY` to update **only `release/addons/`**. The private repository is sparse-checked out; its application sources are not copied into the Store or uploaded as artifacts. This avoids a separate frequent private-repository Actions workflow. Deploy key permissions are repo-wide; the directory restriction is enforced by the synchronizer, not by GitHub's key permissions. Only runs on Store `main` can read it (see Store `main` protection below). Revoke/rotate the key through ha-rebrand Settings → Deploy keys and replace the `store-sync` environment secret. ha-rebrand itself is a private repository on a free personal account, so GitHub offers it no branch protection; this is an accepted risk (owner decision, 2026-10-12).

## Contract and limitations

- `release` sources ship only published, non-prerelease Releases. Sources create them after their own CI through the reusable [`woow-addon-release.yml`](../.github/workflows/woow-addon-release.yml) (`addon_sync.py release`), which tags each new stable addon version from this Store's registry: `v<version>` for a single-addon repository, `<slug>-v<version>` per addon otherwise. `main` sources (still being switched over) are eligible after configured tests/builds succeed.
- Source notification and distribution are eventually consistent. GitHub schedules may be delayed; this is not instantaneous cross-repository atomic publication. On this account scheduled runs have been observed 2–7 hours late, so the cron interval is an upper bound on frequency, not a latency guarantee. Prompt propagation comes from the sources: when a source's publish run writes a new notification, its `woow-addon-sync.yml` notify job sends `repository_dispatch` `woow-addon-ready` here with the source's `APP_STORE_DISPATCH_TOKEN` secret. A source without that secret only logs a warning, and its release waits for the next scheduled run (or a manual one).
- Private push failure is a failed workflow, not a silently successful delivery. A later run reconciles it without reinstalling anything.
- Notifications are trusted through GitHub repository permissions and HTTPS, with immutable source/digest checks. Independent cryptographic signing/attestation is not implemented.
- Published runtime availability/platform/digests are verified. Source-only packages are structurally validated; actual local Docker build and runtime health are **not certified**.
- Store manifests retain normal Supervisor image-tag installation semantics. Local Download instead wraps the exact recorded platform image digest in a local Dockerfile; this is **not source recompilation**.
- The downloader refuses existing directories and sets new contexts to manual boot. It does not install, start, uninstall, upgrade or migrate an appliance. Never uninstall an existing addon merely to switch packaging modes.
- Archived repositories, retired VSCode and prerelease channels are not silently added to the stable catalog. Registry lists explicit mappings/exclusions.
- Tailscale: since 2026-10-06 the individual repository `Woow_ha_vpn_tailscale_package` is canonical (owner decision). Its 0.1.2 carries the Store's 0.1.1 fix plus the current `bind-tools` pin, and its `Build` workflow must build `amd64` and `aarch64` before a snapshot is distributed. The downgrade guard still protects the Store copy.
- A missing or failed source notification leaves the previous Store context/catalog intact and appears in the workflow summary and as a `::warning` annotation on the run; partial progress is explicitly reported. CI that is still running is reported as `waiting`, not success.
- `release/addons/sync-state.json` names the Store commit that produced the published resources. When the catalog, downloader and README are unchanged, it keeps that commit, so unrelated Store commits do not create rebrand commits.

## Operations

Run **Synchronize validated WOOW addons and Local Download** manually; optional `only` input selects an addon ID for a pilot. Empty input selects every enabled stable mapping. Scheduled runs (every 5 minutes, offset from the top of the hour, best effort) and `woow-addon-ready` repository dispatches always process every enabled stable mapping. Repository dispatch payloads do not choose arbitrary repositories or files; the checked-in registry is the allowlist.

Source inventory, inclusion/exclusion reasons and the runbook (onboarding, publisher, failures, key rotation): [`SOURCES.md`](SOURCES.md).

To onboard a new source, review `registry.json`, add its `woow-addon-sync.yml` calling the reusable publisher at `@main`, run the publisher, then verify both Store catalog and rebrand `sync-state.json` report the same catalog ID. New repositories are not granted cross-repository write credentials automatically.

Shared tooling is not pinned in source workflows: Store `main` changes to `.addon-sync/` or `woow-addon-publish.yml` take effect in every source repository's next publisher run, under that repository's own `contents: write` token. They are therefore reviewed before they land; see below. Producer notification branches must not be mistaken for application release branches.

### Store `main` protection

A repository ruleset on `main` blocks deletion and force pushes and requires a pull request with one approval (stale approvals are dismissed; the approval must come after the last push). Nobody bypasses it, including the repository admin, except the **Store sync write deploy key** (`STORE_SYNC_DEPLOY_KEY`): `sync-upstreams.yml` checks out with it, so `rebrand_sync.py store-commit --push` writes `catalog.json` and addon directories directly. Both deploy keys are secrets of the `store-sync` environment, whose deployment branch policy allows only `main`; a workflow pushed on any other branch can neither push `main` nor read either key, and the workflow's own `GITHUB_TOKEN` is read-only. Do not add GitHub Actions or a role to the bypass list: any branch workflow would then reach `main` unreviewed. Because the owner works under two accounts, a change is authored under one and approved under the other (owner decision, 2026-10-12).

Tests: `python3 -m pip install -r .addon-sync/requirements.txt && python3 .addon-sync/test_addon_sync.py -v`.
