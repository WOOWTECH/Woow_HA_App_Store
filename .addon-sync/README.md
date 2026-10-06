# WOOW HA addon distribution

Source repositories publish validated snapshots to their own `woow-addon-sync/notification.json` branch using their own short-lived `GITHUB_TOKEN`. No cross-repository PAT is distributed to producers.

The Store workflow reads these public notifications, validates source identity, immutable commit/context/archive/config checksums, successful publisher workflow receipts, configured CI and per-architecture published images. It refuses downgrades and out-of-order snapshots. Store sidebar metadata policy is retained. Stable catalog: `.addon-sync/catalog.json`.

The consumer re-applies this Store's checked-in registry policy itself, because a producer's pinned tooling carries an older copy of the registry: a `release` source must name a published, non-prerelease Release commit; a `main` source must name a commit on the registered default branch; every `required_workflows` entry must have succeeded for that commit (or for an unchanged runtime); and the publisher receipt must be a run of the default branch's `woow-addon-sync.yml`.

After a successful Store update, the same workflow uses the **ha-rebrand-only write deploy key** in `REBRAND_SYNC_SSH_KEY` to update **only `release/addons/`**. The private repository is sparse-checked out; its application sources are not copied into the Store or uploaded as artifacts. This avoids a separate frequent private-repository Actions workflow. Deploy key permissions are repo-wide; the directory restriction is enforced by the synchronizer, not by GitHub's key permissions. Protect Store workflow write access accordingly. Revoke/rotate the key through ha-rebrand Settings → Deploy keys and replace the corresponding Store Actions secret.

## Contract and limitations

- Main/default-branch updates are eligible after configured tests/builds succeed. Existing release-pinned Odoo and Hermes publication policies are retained.
- Source notification and distribution are eventually consistent. GitHub schedules may be delayed; this is not instantaneous cross-repository atomic publication. On this account scheduled runs have been observed 2–7 hours late, so the cron interval is an upper bound on frequency, not a latency guarantee. Prompt propagation needs a manual run or an existing upstream `repository_dispatch`.
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

Run **Synchronize validated WOOW addons and Local Download** manually; optional `only` input selects an addon ID for a pilot. Empty input selects every enabled stable mapping. Scheduled runs (every 5 minutes, offset from the top of the hour, best effort) and repository dispatches always process every enabled stable mapping. Repository dispatch payloads do not choose arbitrary repositories or files; the checked-in registry is the allowlist.

To onboard a new source, review `registry.json`, add its publisher workflow pinned to a reviewed Store tooling commit, run the publisher, then verify both Store catalog and rebrand `sync-state.json` report the same catalog ID. New repositories are not granted cross-repository write credentials automatically.

Shared tooling is commit-pinned in source workflows; tool changes require a reviewed pin update. Producer notification branches must not be mistaken for application release branches.

Tests: `python3 -m pip install -r .addon-sync/requirements.txt && python3 .addon-sync/test_addon_sync.py -v`.
