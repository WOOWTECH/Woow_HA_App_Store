# Delist Six Add-ons Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove `netease_cloud_music_api`, `ytm_po_token_generator`, `local_audio`, `ha_mcp_webhook_proxy`, `ha_mcp`, and `woow_ha_core` from the central Store and Local Download.

**Architecture:** Keep source repositories and their release/upgrade checks operational. Add a consumer-only `store_enabled` flag, defaulting to true; mark these six mappings false, remove their tracked contexts and catalog entries, and recompute the catalog digest. Update the Store and source inventory documentation to describe the remaining 38 add-ons.

**Tech Stack:** Python standard library, PyYAML, packaging, GitHub Actions.

---

### Task 1: Prevent Store synchronization without disabling source releases

**Files:** `.addon-sync/addon_sync.py`, `.addon-sync/test_addon_sync.py`

1. Add behavior tests that replay valid source notifications for a Store-excluded component beside a retained component, including the manual `only` filter. Assert the excluded context/catalog entry stays absent and the retained entry is unchanged.
2. Add a test proving a Store-excluded component can still publish source notifications and create its normal release tag.
3. Run `python3 .addon-sync/test_addon_sync.py -v`; verify the notification replay test fails before changing the consumer.
4. Change the consumer filter to `publishes_releases(c) and c.get('store_enabled', True) and (not only or c['id'] in only)`. Leave publisher, release, and upgrade-comparison eligibility unchanged.

### Task 2: Apply the six exclusions and update the catalog

**Files:** `.addon-sync/registry.json`, `.addon-sync/catalog.json`, the six root add-on directories

1. Set `store_enabled: false` with a dated reason on exactly the six requested mappings; retain their `enabled`, channel, source paths, and provider settings.
2. Remove exactly those six tracked add-on directories.
3. Remove exactly those six catalog components and recompute `catalog_id` with `addon_sync.digest(addon_sync.canonical(catalog['components']))`.

### Task 3: Document, verify, and submit

**Files:** `README.md`, `.addon-sync/README.md`, `.addon-sync/SOURCES.md`

1. Update the inventory to 38 add-ons, remove the six active listing rows, add a dated delisting notice, and document `store_enabled` separately from `enabled`.
2. Include the already shipped Headscale MCP entry omitted from the old README, and reconcile the source table with all 52 registered contexts.
3. Run `python3 .addon-sync/test_addon_sync.py -v`, `python3 .addon-sync/test_upgrade_check.py -v`, and `python3 .github/scripts/sidebar_titles.py --check`.
4. Verify catalog checksum, 38 matching manifest/catalog/eligible IDs, unchanged content for all retained components, excluded paths absent, and `git diff --check`.
5. Commit and push the topic branch, open a PR, and inspect its checks. The existing main ruleset requires one approval after the last push; preserve that requirement.
