# Changelog

## 1.0.3

Hardening and test coverage following live verification on HAOS. Both sides
of the Ingress trust boundary were confirmed on a running instance: a
neighbouring add-on calling the API directly on the container IP with
spoofed `X-Ingress-Path` / `X-Hass-Source` headers is refused, while the
real sidebar panel renders normally.

### Changed

- The Ingress allow-list no longer relies solely on the hard-coded
  `172.30.32.2`. The Supervisor's address is resolved at startup and added,
  so an install whose Supervisor sits elsewhere cannot lock the user out of
  their own GUI; the well-known address remains the fallback when DNS is
  unavailable.

### Added

- Rejected requests are now logged once per peer, with the offending address
  and the addresses that would have been accepted. A bare 403 with an empty
  log was not supportable in a commercial deployment.
- `cloudflared/tests/test_resilience_patches.sh` — 19 assertions covering the
  s6 / bash resilience patches. These paths never execute in remote-managed
  (token) mode, so a production token-mode instance cannot exercise them and
  they previously had no coverage. The harness runs the real committed
  scripts against a stubbed bashio / cloudflared / sleep: a failing prepare
  records its marker and still exits 0 (the container, and with it the Web
  GUI, survives), stale markers are cleared, and run.sh idles when
  unconfigured, retries a failed setup until it recovers, and otherwise
  starts cloudflared with the upstream flags unchanged.
- Trust-boundary unit tests covering both failure modes: letting a
  neighbouring add-on in, and locking the real user out.

## 1.0.2

Pre-launch hardening — every item below came out of a multi-agent review
pass plus live install testing on HAOS (replacing the original Cloudflared
add-on in production).

### Fixed

- **Token-mode users could not save** unrelated changes without re-entering
  their token: the minimal-config check ran before the stored token was
  merged. The check now runs in the router, after the merge (regression
  test added).
- A configuration whose setup fails mid-way (e.g. tunnel name mismatch,
  DNS route failure) no longer halts the whole container — the Web GUI
  stays up for repair, and the setup is retried every 5 minutes so
  transient failures (network not ready after reboot) self-heal.
- Logs page: the Connect button was permanently dead after Disconnect;
  repeated connects could leak duplicate WebSocket streams.
- TokenInput now re-syncs with the stored state after save/reset.
- A rejected restart is surfaced in the GUI ("saved but not applied")
  instead of silently pretending success; a fast restart no longer leaves
  the UI stuck in "restarting" for two minutes.
- Frontend hostname validation now matches the backend/upstream rules
  (umlaut hostnames allowed, uppercase rejected client-side with a clear
  message).
- Setup wizard no longer flashes raw fetch errors during the add-on
  restart it just asked for.
- Removed validate-options round-trip that used a wrong payload shape; the
  Supervisor's on-write validation is authoritative.

### Added

- `ingress_panel: true` — the GUI appears in the HA sidebar by default (as
  documented).
- Tunnel-token format validation: pasting the full `cloudflared service
  install eyJ...` command now extracts the token automatically; garbled or
  truncated tokens are rejected before they can take the tunnel down.
- Dashboard first-run guidance (unconfigured / setup-failed banners) and
  clearer error surfacing when the Supervisor is unreachable.
- Log stream redaction: tunnel tokens and tunnel.json secrets can no
  longer leak through the GUI log view at debug/trace log levels.

### Changed

- `tunnel_token` schema type `str?` → `password?` (same values accepted;
  the HA configuration UI now masks the secret).
- Backend dependencies fully pinned incl. transitive packages; frontend
  build no longer falls back from `npm ci` to unpinned `npm install`.
- English-only GUI copy (removed leftover Chinese strings from the
  standalone project).

## 1.0.1

### Fixed

- Web GUI crashed on startup (`ModuleNotFoundError: _zstd`): the base
  image's Python 3.14 on Alpine is built without the stdlib zstd module,
  which aiohttp 3.13.0 imports unconditionally. Bumped to aiohttp 3.14.3,
  which guards the import and falls back gracefully.

## 1.0.0

First release of **Cloudflared Web GUI** — a fork of
[homeassistant-apps/app-cloudflared](https://github.com/homeassistant-apps/app-cloudflared)
with a Web GUI on top of the unchanged tunnel core.

### Added

- Web GUI served through Home Assistant Ingress (sidebar panel, protected by
  HA login, no extra port).
  - Dashboard: live tunnel status (metrics `/ready`), add-on state, restart.
  - Setup wizard: captures the `cloudflared tunnel login` authorization URL
    from the log and presents it as a clickable link.
  - Config: full editor for all add-on options, read/written through the
    Supervisor API — the HA configuration page and the GUI always stay in
    sync (the Supervisor options remain the single source of truth).
  - Logs: live WebSocket stream of the add-on log (same content as the HA
    Log tab), with filter and download.

### Changed (vs upstream)

- When started with a completely empty configuration, the add-on no longer
  exits fatally; the Web GUI stays up (tunnel stopped) so first-time setup
  can be done in the browser. With any configuration present, behavior is
  identical to upstream.
- `hassio_role: manager` + Ingress enabled in `config.yaml` (required for
  the GUI to manage the add-on's own options).

All tunnel functionality, configuration options, and log output are
inherited unchanged from upstream app-cloudflared (based on upstream
cloudflared 2026.7.3).
