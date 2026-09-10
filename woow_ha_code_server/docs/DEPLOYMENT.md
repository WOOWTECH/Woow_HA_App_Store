# Deployment

Source of truth for what is actually running — every claim below is cross-referenced by file path, not aspirational.

## Install

### Via the WOOWTECH HA App Store (recommended, once registered)

1. HA → Settings → Add-ons → Add-on Store → ⋮ → Repositories → add `https://github.com/WOOWTECH/Woow_HA_App_Store` (if not already added).
2. `ha store reload` (or the equivalent UI action).
3. Install **Woow Code Server** from the store listing.

### Directly from this repository

1. HA → Settings → Add-ons → Add-on Store → ⋮ → Repositories → add `https://github.com/WOOWTECH/Woow_ha_code_server_add_on`.
2. Install **Woow Code Server**.

## First boot checklist (the contract's HA-target rows)

Run these after the add-on reports `started`:

```bash
# P01-P05: pi/pi-acp present and pinned
docker exec <container> pi --version           # expect 0.83.0
docker exec <container> which pi-acp

# P09-P12: settings.json required keys
docker exec <container> cat /data/vscode/User/settings.json | \
  jq '.["acp.agents"].pi.command, .["security.workspace.trust.enabled"]'

# P14, P19: shared-file hashes
docker exec <container> sh -c 'cd / && sha256sum -c /opt/SHA256SUMS'

# P26-P28: internal pi store exists and is seeded
docker exec <container> test -f /data/pi-agent/.woow-pi-store && echo seeded

# Then, in a terminal inside the add-on:
pi login
```

Or run `tests/smoke-parity.sh` with `PARITY_TARGET=ha` — see `tests/README` equivalent notes in this repo's `tests/` directory.

## The ACP webview gate (P32/P33) — manual, two minutes

The chat webview's rendering depends on Home Assistant ingress forwarding things correctly, which was verified live against this org's own instance but is not something CI can check (it needs a real browser + a real ingress session). Before considering a rollout complete:

1. Open the add-on's Web UI from the HA sidebar.
2. Open any file, then Command Palette → `Markdown: Open Preview` (or open a `.md` file and click the preview icon) — this is a built-in webview, zero add-on-specific code involved.
3. DevTools → Application → Service Workers. Expect a registration scoped under `.../stable-<commit>/.../webview/browser/pre/` with state `activated`.
4. If it activated: the ACP chat panel will render the same way. Done.
5. If it did not: follow the F1/F2 fallback ladder in `DOCS.md`.

## Namespace / slug collision check

This add-on's slug is `woow_ha_code_server`, distinct from the community mirror `vscode` add-on (slug `vscode` under whatever repository provides it) and from `Woow_ha_pi_agent_add_on` (slug `woow_ha_pi_agent`). All three can run side by side — different `/data`, different ingress tokens, no shared state.

## Store registration (maintainer-only)

1. In `WOOWTECH/Woow_HA_App_Store`, create `woow_ha_code_server/` seeded at **exactly** this repo's current `version:` in `config.yaml` — seeding ahead of the source trips the sync workflow's downgrade guard and reds out the nightly sync for every add-on in the store, not just this one.
2. Add `woow_ha_code_server|Woow_ha_code_server_add_on|.` to `MAPPINGS` in the store's `.github/workflows/sync-upstreams.yml`.
3. `workflow_dispatch` the sync once and confirm the commit body lists `woow_ha_code_server -> <version>`.

## Rollback

Uninstall the add-on from HA. `/data/pi-agent` and `/data/vscode` are Supervisor-managed per-add-on storage — removing the add-on removes them too (or leaves them if you choose "keep data" in the uninstall dialog, HA's own mechanism, not something this add-on controls). No other add-on or deployment is affected either way.
