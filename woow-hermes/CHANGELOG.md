## 0.1.11

- Include the reviewed Paseo Dashboard adapter: an enabled Paseo plugin can reload the Dashboard from Hermes, recover after restart, and stop its owned daemon before native Web disable/removal.
- Add optional `paseo_ingress_url` for the exact Home Assistant browser origin. The existing public Dashboard URL, LAN/OAuth behavior and login remain in place; foreign origins are still rejected.
- Preserve native plugin installation and explicit enablement; the add-on does not install the Paseo plugin or grant extra agent file tools automatically.
- Existing ports, architecture, user configuration and persistent data remain compatible. Use the updated Hermes Paseo plugin for HA Ingress support; see DOCS.

## 0.1.10

- Upgrade Hermes Agent to stable **v0.22.5**, commit `bf0203a794a07aac3ff764972ab9087baa4e4f4e`, using the immutable upstream image digest `sha256:9c5561579f3ffdf333401797094ac3a743738d6c25d40f4331c7bf77b694238d`.
- Adapt HA ingress to upstream's native prefix-aware login and OAuth flow; keep chunk loading, configuration links, isolated ingress cookies and WebSocket relay support.
- Preserve Supervisor-token isolation across exec boundaries, restored-volume ownership repair and session-scoped prompt cleanup, including the new local conversation lineage.
- Use upstream's unattended approval fixes and verify them against the built image. Keep application code root-owned and install the browser CLI through upstream's pinned package manager outside the HA data mount. Validate the CLI as the non-root runtime user.
- Fresh installs no longer try to enable the removed `moa` and `homeassistant` core toolsets. MoA remains available through its model-provider presets. Existing Home Assistant integrations are migrated to the official `homeassistant` plugin at gateway startup when lazy installs and network access permit; `HASS_TOKEN`, `HASS_URL` and platform settings remain unchanged. If migration cannot run, install/enable the plugin in Settings > Plugins or run `hermes plugins install homeassistant`; reconnect only if the saved credentials are invalid. See DOCS for recovery.
- Remove the legacy permissive OAuth issuer override. A server returning a different issuer must correct its OAuth metadata or callback; Hermes now keeps upstream validation. Reconnect affected integrations after correcting the server.
- Ports, architecture, add-on options, persistent data mount and HA login credentials remain unchanged. Take a Home Assistant backup before upgrading; restoring it is the rollback path after upstream database migrations.

# Changelog

## 0.1.9

- Fix: Hermes now starts after a Home Assistant cold backup restore. Supervisor
  restores private application directories (such as `platforms` and `plugins`)
  as root; startup now repairs ownership on the add-on's own `/opt/data` volume
  before dropping privileges. Modes are preserved, symlinks and nested mounts are
  skipped, and hardlinked files are refused.
- Add a real-image regression for the restore repair to candidate CI.
- Keep the pinned Hermes base and existing add-on configuration contract.

## Unreleased

- Repair ownership of the dedicated Home Assistant application volume after a
  Supervisor restore, before starting Hermes. This prevents restored private
  `platforms`, `plugins`, and `backups` directories from blocking startup.
- Preserve ordinary file permissions and exclude symlinks and nested mounts;
  refuse ownership changes to hardlinked files.

## 0.1.8

- Fix: deleting a session or an exact batch now reclaims only prompt records
  referenced by those deleted sessions and their existing delegate cascade.
  Shared prompts and unrelated unreferenced prompts remain intact.
- Keep existing deletion counts, branch handling and transaction rollback
  behavior. Add regressions for shared references, absent sessions and failures.
- Keep the pinned Hermes base and existing add-on configuration contract.

## 0.1.7

- Security: clear Supervisor token variables at the Hermes exec shim and main-wrapper
  handoff, including after s6 environment rehydration. Normal add-on initialization
  still uses the Supervisor API before removing its token environment files.
- CI: gate releases on synthetic real-image/s6 boot and exec UID/token smoke tests.
  This is environment hardening, not isolation from arbitrary root execution or a
  change to provider routing, model access, or tool policy.

## 0.1.6

- Security: dangerous commands from scheduled jobs, the OpenAI-compatible API and webhooks are
  refused, as `approvals.cron_mode` / `approvals.unattended_mode` (deny) say. Upstream Hermes
  auto-approved them through smart approval, because its gateway runs in ask mode.
- The agent's web page extraction works: search stays on DuckDuckGo, extraction uses Parallel
  (both keyless). It used to fail with "ddgs is a search-only backend".
- The browser tool works: it drives the image's Chromium through agent-browser, now preinstalled
  instead of downloaded into `/opt/data/.npm` on first use.
- Swagger (`/docs`) in the sidebar shows request URLs and curl commands with the ingress prefix.
- DOCS: where MCP OAuth sign-in and webhook senders need the public URLs.
- The image's `io.woowtech.hermes.base` label names the Hermes base image.

## 0.1.5

- Prebuilt image on GHCR (`ghcr.io/woowtech/woow-ha-hermes-amd64`): installs and updates pull it
  instead of building on the Home Assistant host, which took about 23 minutes.
- The official Hermes app icon as the add-on icon and logo.
- Listed in the WOOWTECH add-on store (Woow_HA_App_Store).

## 0.1.4

- Reloading the Home Assistant page (F5) keeps the sidebar on the page you were on, as a reload
  does on the LAN port. It used to return to Sessions.
- DOCS: keep a long random dashboard password (Hermes' login attempt limit can be sidestepped on
  the LAN port).

## 0.1.3

- The sidebar chat now ends the same way as on the LAN port. HA ingress turns every WebSocket
  close into a clean 1000, so a chat taken over by another tab, or whose agent exited, showed
  "[session ended (code 1000)]", and the chat and live feeds did not reconnect after an add-on
  restart. A small relay in the add-on records how Hermes closed each ingress WebSocket, and the
  sidebar page restores that code.
- The agent keeps Hermes' default approval settings. The podman stack's approval policy (no
  approvals, cron yolo) never actually took effect on this Hermes version; the dead code that
  looked like it applied it is removed, and the docs now describe the real behaviour.

## 0.1.2

- Fix: `platforms.webhook` was never written to config.yaml in 0.1.1, so the Webhooks page still
  showed the receiver as disabled.

## 0.1.1

- Sidebar and LAN port keep separate Hermes sessions: a login on `http://<ha-ip>:9119` no longer
  logs the sidebar in, and logging out of one no longer affects the other.
- Session export and Swagger "Try it out" now work in the sidebar.
- The Webhooks page shows the receiver as enabled (`platforms.webhook` is written to config.yaml
  on first start).
- Login page favicon loads inside the sidebar.

## 0.1.0

- First release: Hermes Agent v2026.8.31 (dashboard 0.21.0) with the Woow_podman_hermes `slim`
  additions, dashboard in the HA sidebar through Ingress, LAN ports 8642/9119/8644.
