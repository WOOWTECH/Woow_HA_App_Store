# Changelog

## Unreleased

### Added
- GitHub Actions PR gate: hadolint, shellcheck, yamllint, the Home Assistant
  add-on linter, a CRLF check, the static test tier, and an amd64 image build
  on every pull request. A pull request that bumps the version also builds
  aarch64 before it can merge.
- Release bookkeeping enforced by CI: the `config.yaml` version must head the
  CHANGELOG, versions must descend, and both translation files must cover the
  option schema exactly. An `## Unreleased` section is allowed only while the
  version is unchanged.
- LGPL-3.0 `LICENSE` file, matching the licence the README has always named.
- Dependabot for GitHub Actions, weekly, grouped into one pull request.
- The Home Assistant add-on linter runs on every pull request as advisory
  output. It also asks for `webui` to go (Ingress is enabled) and for
  `watchdog` to become a Docker `HEALTHCHECK`; both change runtime
  behaviour and are deferred to the 0.4.0 Release, after which the linter
  becomes blocking.

### Changed
- `config.yaml` no longer states `startup: application`, `boot: auto` and
  `panel_admin: true`; these are Supervisor defaults and the linter rejects
  restating them. Nothing changes for installed add-ons.
- The static tests are pytest modules under `odoo18ce/tests/` with one
  entrypoint, `pytest odoo18ce/tests`, replacing `test-dual-gateway.sh`.
- The Settings E2E harness no longer defaults to a real deployment; the HA
  and public URLs must be supplied through the environment.
- Dockerfile: `pipefail` for the piped downloads, `--no-install-recommends`
  on the PostgreSQL install, apt lists removed from the first layer, and the
  unused `lsb-release` package dropped. No runtime behaviour changes.

## 0.3.39 — 2026-09-08

### Changed
- Rename the add-on from `Odoo 18 CE` to `Woow Odoo 18`, matching every other
  WoowTech add-on in the store (`Woow EMQX`, `Woow Immich`, `Woow Nextcloud`,
  `Woow n8n`, …). The slug stays `odoo18ce`: Home Assistant keys an installed
  add-on by slug, so changing it would strand the running instance and its
  Odoo database behind a new identity. Supervisor picks the new name up on the
  next add-on update; no configuration or data changes.

## 0.3.38 — 2026-09-08

### Security
- Remove the add-on network bridge address `172.30.32.1` from the LAN tier.
  0.3.36 treated it as LAN so the Home Assistant host could reach Odoo directly,
  on the assumption the Cloudflare tunnel arrives from its own container
  address. On a real deployment the tunnel add-on is host-networked and arrives
  from the bridge, so it inherited the LAN tier and `/web/database/manager`
  answered `200` to the public internet. Traffic from the bridge is now off-LAN;
  anything on the host that needs the full application uses the ingress panel.

### Testing
- Assert the bridge address carries no LAN entry, so it cannot be promoted back.

## 0.3.37 — 2026-09-08

### Fixed
- Answer on the published `8072` host port. Odoo binds every listener to
  `http_interface`, which is loopback, so the gevent worker could never serve
  that port itself and it refused every LAN connection even with `workers` > 0.
  nginx now owns `8072` and the worker moves to an internal `8073`.

### Security
- The `8072` origin is behind the same source-address gate as `8069`, so the
  WebSocket worker is not exposed unfiltered to whatever can reach the host.

### Testing
- Assert nginx owns `8072`, that gevent is off it, and that both origins carry
  the deny gate.

## 0.3.36 — 2026-09-08

### Added
- Reach Odoo directly from the LAN on the published `8069` host port. The origin
  listener now classifies callers by source address — which Docker preserves on a
  published port — and serves the LAN the full application, database manager
  included, while the Cloudflare tunnel keeps its restricted tier.
- `lan_networks`: space-separated IPv4/IPv6 CIDRs that define the trusted LAN
  (default `192.168.0.0/16 10.0.0.0/8 172.16.0.0/12`). Malformed entries fail
  start-up rather than reaching the nginx `geo` block.

### Changed
- Publish `8069` and `8072` on the HA host by default. The privilege split is
  enforced by source address inside nginx, not by leaving the ports unmapped.
- Default `workers` is now `2`. The gevent WebSocket on `8072` only listens while
  Odoo runs multi-process, so a published `8072` was previously always dead.
- The 8069 origin forwards the scheme the caller actually used and only marks the
  session cookie `Secure` when that scheme is HTTPS. A `Secure` cookie is never
  returned over plain LAN http, which previously would have made a successful
  login bounce straight back to the login page.

### Security
- The Cloudflare tunnel reaches the add-on from inside the add-on network, which
  the default LAN range `172.16.0.0/12` contains. `172.30.32.0/23` and the
  add-on network's IPv6 prefix are carved out of the LAN tier explicitly so the
  tunnel can never inherit LAN privileges, and the carve-out is asserted in the
  test suite.
- IPv6 callers are denied unless an operator adds their own prefix, keeping the
  default fail-closed on a dual-stack LAN.
- With `public_url` unset, no `Host` maps to the public tier, so an off-LAN
  caller is refused instead of falling through to the LAN tier.

### Testing
- Assert the add-on network carve-out, the LAN-only gate on every database
  lifecycle route, the tier-selected RPC upstream, and the conditional cookie and
  forwarded scheme.
- Render and `nginx -t` both configurations — `public_url` set and unset — rather
  than only the configured one.

## 0.3.35 — 2026-09-03

### Fixed
- Prefix root `/web/assets/` `href` and `src` attributes only inside JSON-escaped Document Layout preview HTML on HA Ingress.
- Retry an explicitly allowlisted HA Settings control once when its direct ingress iframe is temporarily replaced by the Home Assistant authorization frame.

### Testing
- Extend the live nginx response harness to parse the rewritten preview JSON and prove its escaped asset attributes and the public response remain correct.
- Add credential-free Settings retry classification contracts for the authorization-frame condition and its approval, surface, and retry limits.

## 0.3.34 — 2026-09-03

### Fixed
- Restrict the HA Ingress runtime `<head>` shim to `text/html` upstream responses so Document Layout preview HTML embedded in JSON remains parseable, while retaining ingress JSON URL and icon rewrites.

### Testing
- Add a live nginx content-type response-filter harness covering HTML shim injection, JSON preview integrity, and JSON asset URL rewriting.

## 0.3.33 — 2026-09-03

### Fixed
- Prefix the exact SettingsViewCompiler fallback icon expression in HA Ingress assets and the encoding-independent General Settings icon path in Settings view responses.
- Open Settings once in the HA E2E flow, then reacquire only the current direct ingress frame for every dynamically discovered tab instead of repeatedly invoking the app action.
- Wait for a visible Odoo login form or an already loaded navbar so document rendering cannot be mistaken for an authenticated backend.

### Testing
- Add focused ingress-only contracts for generated module icons and explicit General Settings logos while proving the public listener is unchanged.

## 0.3.32 — 2026-09-03

### Fixed
- Normalize a cloned HA Ingress URL before Odoo Router parsing, so token-prefixed Settings routes retain their action instead of falling back to Discuss.
- Make Odoo's internal route-click predicate accept only exact token-prefixed `/odoo` path segments while rejecting lookalikes such as `/odoox`.
- Preserve fragment-only Settings links and remove the competing Settings-specific DOM click workaround.

### Testing
- Add Router contracts for prefix parsing, original-URL immutability, fragment routing, external/non-Odoo rejection, and exact path boundaries.
- Add real HA/Public Settings E2E with direct-frame reacquisition, secure diagnostics, HTTP failure capture, and dynamic discovery of current and future Settings tabs.
- Render the final nginx template and require `nginx -t` in the dual-gateway suite.

## 0.3.31 — 2026-09-02

### Fixed
- Replace the Settings CSS selector containing a single-quoted `#` inside nginx's single-quoted replacement string. The generated nginx config parsed `#` as invalid syntax and watchdog-restarted the add-on.

### Testing
- Release requires both extracted JavaScript `node --check` and fully rendered `nginx -t`; neither check alone is sufficient.

## 0.3.30 — 2026-09-02

### Fixed
- Rewrite Settings `module.imgurl` values so section icons stay under HA Ingress.
- Normalize Settings hash-tab anchors to the current tokenized `/odoo/settings#<section>` URL before browser default navigation, preventing clicks from restoring stale Discuss history.

## 0.3.29 — 2026-09-02

### Fixed
- Correct a missing closing brace in the injected ingress service-worker cleanup block. The whole early shim failed with `Unexpected token 'catch'`, disabling fetch/history/Worker/WebSocket URL rewriting and allowing native Odoo service-worker registration errors.

### Testing
- Extract and run `node --check` on the injected nginx JavaScript during gateway tests so malformed shims cannot be released again.

## 0.3.28 — 2026-09-02

### Fixed
- Support HA Ingress through both public HTTPS and VPN-direct HTTP origins. Preserve the browser-visible `X-Forwarded-Proto`, generate matching HTTP/WS or HTTPS/WSS semantics, and add/remove the session cookie `Secure` flag conditionally. VPN users opening `http://<tailscale-ip>:8123` can now retain Odoo login sessions.

## 0.3.27 — 2026-09-02

### Fixed
- Keep Odoo bus `params.serverURL` equal to `window.origin` and prefix only the SharedWorker script and WebSocket endpoint expressions. Prefixing `serverURL` triggered Odoo's cross-origin data-URL worker branch; Chromium could fail before requesting the worker bundle, producing a null `UncaughtClientError` immediately after mail initialization.

## 0.3.26 — 2026-09-02

### Fixed
- Replace the SharedWorker bundle cache-buster match containing JavaScript `${...}` syntax with a simple `websocket_worker_bundle?v=` substitution. nginx parsed the former as an invalid variable and stopped the add-on at startup.

## 0.3.25 — 2026-09-02

### Fixed
- Version the Discuss SharedWorker/Worker name and imported worker-bundle URL. Browsers keep a named SharedWorker alive across iframe/add-on reloads; reusing `odoo:websocket_shared_worker` preserved the pre-fix root `/websocket` target and emitted a null `UncaughtClientError` even after transformed assets were refreshed.

## 0.3.24 — 2026-09-02

### Fixed
- Prefix Calendar and Settings (`/calendar/*`, `/base_setup/*`) RPC literals discovered by recursive app-launcher testing.
- Rewrite module icon JSON values and responsive image `srcset` URLs so Apps icons do not escape to HA root.

### Verified
- Recursive app-launcher crawl now includes Discuss, Calendar, Dashboards, Point of Sale, Invoicing, Website, Inventory, Apps and Settings as a release-gating ingress operation.

## 0.3.23 — 2026-09-02

### Fixed
- Rewrite `{"src": "/web/assets/..."}` values returned by `/web/bundle`. Website editor injects WYSIWYG JS/CSS into a child iframe whose DOM prototypes do not inherit the parent ingress shim; unrewritten bundle JSON therefore loaded root HA URLs and raised `AssetsLoadingError`.

## 0.3.22 — 2026-09-02

### Fixed
- Unregister stale Odoo service workers whose `/odoo` scope or `/web/service-worker.js` script can keep intercepting transformed ingress assets after updates. Perform one version-scoped reload after cleanup, without touching Home Assistant's own service worker registrations or unrelated CacheStorage.

## 0.3.21 — 2026-09-02

### Fixed
- Cache-bust rewritten ingress JS/CSS references with the add-on version and mark transformed assets `no-store`. Odoo asset hashes remain unchanged when only the proxy transformation changes, so browsers otherwise retained the pre-fix bus `serverURL` bundle and continued reporting real-time loss after update.

## 0.3.20 — 2026-09-02

### Fixed
- Remove the older `/bus` literal substitutions after prefixing `busParametersService.serverURL`. Applying both mechanisms generated a double ingress token for the SharedWorker bundle, so the bundle returned 404 before it could open `/websocket`.

## 0.3.19 — 2026-09-02

### Fixed
- Prefix Odoo bus `serverURL` in the rewritten backend asset bundle. Discuss passed a root-origin `wss://<ha-host>/websocket` URL into its SharedWorker, bypassing window-level WebSocket shims and causing “Real-time connection lost” with no `/websocket` request reaching the add-on.

## 0.3.18 — 2026-09-02

### Diagnostics
- Log sent/upstream X-Frame-Options plus ingress Host and forwarded scheme without query strings, enabling live differentiation between frame denial, mixed-content headers and URL rewriting failures.

## 0.3.17 — 2026-09-02

### Fixed
- Remove Odoo backend's `X-Frame-Options: DENY` only on the HA Ingress listener. Chromium rejected the authenticated `/odoo` iframe before loading any assets, producing the broken-page icon while nginx logged only `GET /odoo 200`.

## 0.3.16 — 2026-09-02

### Fixed
- Force the documented HTTPS scheme on the HA Ingress upstream headers. Supervisor connects to the add-on over internal HTTP and may omit `X-Forwarded-Proto`; falling back to nginx `$scheme` made Odoo emit mixed-content/incorrect absolute URLs and could leave the embedded page as a browser error placeholder.

## 0.3.15 — 2026-09-02

### Fixed
- Keep portal `/my/*` counters and authenticated Website operations inside the HA ingress prefix.
- Stabilize logout/protected-route browser assertions by waiting for Odoo's lazy login form.

### Verified
- Recursive authenticated ingress journey passes: backend, Discuss, Website home, Shop, Cart, Contact, Portal and back to backend, followed by logout and protected-route redirect; zero failed requests, 5xx or console errors.

## 0.3.14 — 2026-09-02

### Fixed
- Allow the HA Ingress token root to proxy Odoo Website `/` instead of forcing every root navigation back to `/odoo`; this fixes backend-to-Website transitions and authenticated frontend pages.

### Testing
- Add an adversarial recursive browser matrix covering unauthenticated/authenticated Website, backend, shop, cart, contact, portal, logout, redirects, assets, console/network errors, DB-manager denial, APIs and navigation transitions.

## 0.3.13 — 2026-09-02

### Security
- Add a localhost JSON-RPC filter that rejects public `service: db` calls while preserving object/common API services; HA Ingress retains database service access.
- Fail the public origin closed until an HTTPS `public_url` supplies an exact Host guard and canonical scheme.
- Remove Referer from access logs and pin WOOWTECH custom addons to a reviewed commit.

## 0.3.12 — 2026-09-02

### Security
- Block public XML-RPC database services in addition to `/web/database/*`.
- Remove unused Supervisor API access and read-write backup mount.
- Enforce configured public hostname and canonical scheme at the internal Cloudflare origin.
- Remove query strings from nginx access logs to avoid leaking URL-carried tokens.
- Validate one-shot bootstrap file type, ownership, mode and password length.
- Preserve standard WebSocket static constants in the ingress shim.
- Create generated secret configuration under restrictive umask.
- Replace local PostgreSQL `trust` authentication with `peer` authentication.
- Fail clearly when `public_url`, maintenance bootstrap or module auto-update lacks a target `default_db`.

## 0.3.11 — 2026-09-02

### Fixed
- Scope root-route substitutions to `/web/assets/` responses so Odoo login hidden redirect values remain unmodified.
- Prefix authenticated HTML's inline menu/translation prefetch URLs.
- Patch Odoo router `stateToUrl` origin composition so OWL navigation remains under the Supervisor ingress token.

### Verified
- Actual rendered nginx template behind an HTTPS Supervisor-prefix simulator: login, authenticated `/odoo/discuss`, menus, translations, assets and browser console all pass with zero relevant 4xx/5xx, failed requests or console errors.

## 0.3.10 — 2026-09-02

### Fixed
- Remove broad server-side JavaScript route substitution after moving the runtime shim before Odoo assets; keeping both mechanisms double-prefixed OWL navigation. Early fetch/history/Worker shims are now the single runtime URL authority.

## 0.3.9 — 2026-09-02

### Fixed
- Inject the ingress runtime shim immediately after `<head>`, before Odoo's synchronous backend asset bundles capture browser APIs.
- Handle URL objects passed to History API and rewrite all quote variants of `/mail` and `/odoo` routes.

## 0.3.8 — 2026-09-02

### Fixed
- Rewrite Odoo login form's HTML-entity-encoded inline `this.action = '/web/login'`; this assignment bypassed both the static action attribute and some browser property interception paths.

## 0.3.7 — 2026-09-02

### Fixed
- Rewrite Odoo's computed `${serverURL}/bus/websocket_worker_bundle` path, which is not a simple quoted root literal.
- Provide a complete inert service-worker controller/registration shape so Odoo does not dereference a null controller in the embedded Ingress UI.

## 0.3.6 — 2026-09-02

### Fixed
- Keep Odoo bus SharedWorker/Worker bundle URLs inside the HA ingress prefix.
- Disable Odoo service-worker registration under Ingress because its root scope crosses the Supervisor token boundary; offline/PWA caching is unnecessary for the embedded admin UI.

## 0.3.5 — 2026-09-02

### Fixed
- Preserve relative redirect targets with named nginx regex captures and disable absolute redirects on the ingress listener.
- Rewrite Odoo root-absolute RPC/worker bundle routes (`/web`, `/websocket`, `/report`, `/mail`, `/website`) that execute outside window-level URL shims.
- Added an actual nginx + HTTPS Supervisor-prefix Playwright harness during validation, covering login and authenticated OWL startup.

## 0.3.4 — 2026-09-02

### Fixed
- Post-test user downgrade now removes both Settings (`base.group_system`) and Access Rights (`base.group_erp_manager`) privileges, leaving a normal Internal User.

## 0.3.3 — 2026-09-02

### Fixed
- Normalize duplicate HA ingress prefixes produced when Odoo's lazy asset loader combines an already rewritten `data-src` with the document base URL.
- Playwright token-prefix reproduction now renders the Odoo login form with all Odoo assets inside the ingress prefix.

## 0.3.2 — 2026-09-02

### Fixed
- Remove the empty `public_url` default; Home Assistant correctly rejects an explicitly present empty value for an optional `url?` field.

## 0.3.1 — 2026-09-02

### Added
- `public_url` option freezes Odoo `web.base.url` to the canonical Cloudflare HTTPS origin
- Secure one-shot `/config/bootstrap-user.json` maintenance hook for repeatable E2E account provisioning and post-test privilege downgrade

## 0.3.0 — 2026-09-02

### Added
- Home Assistant Ingress on port 5691, opening the Odoo backend at `/odoo`
- Dual nginx gateways for HA Ingress and the Cloudflare full public origin
- Ingress rewriting for Odoo/OWL assets, JSON-RPC, forms, redirects, cookies, history, and WebSocket
- Worker-aware `/websocket` routing (HTTP port for workers=0, gevent 8072 for workers>0)
- Focused dual-gateway regression tests

### Security
- Odoo is bound to localhost:8070 and trusts forwarded headers only from bundled nginx
- HA host mappings for 8069/8072 are disabled; cloudflared uses add-on internal DNS
- Public Cloudflare gateway blocks `/web/database/*`; HA Ingress retains database management access
- Odoo package pinned to 18.0.20260806 with SHA-256 verification

## 0.2.0 — 2026-05-25

### Changed
- Upgraded PostgreSQL 15 → 16 (aligned with Odoo 18 official image)

### Added
- Timezone (`TZ`) configuration for Odoo and PostgreSQL
- Resource limit settings: `max_cron_threads`, `limit_memory_hard`,
  `limit_memory_soft`, `limit_time_cpu`, `limit_time_real`
- Configurable extra addons path (`odoo_extra_addons`)
- Auto-create database on first startup when `default_db` is set
- Dynamic addons_path with automatic directory creation
- Translations: English (`en.yaml`) and Traditional Chinese (`zh-Hant.yaml`)
- `DOCS.md` — detailed configuration reference and architecture documentation
- `README.md` — installation guide and quick start
- Cold backup support with cache/logs/sessions exclusion

### Fixed
- Missing `/share/odoo_addons` directory causing module icon 500 errors
- All addons_path directories are now auto-created if they don't exist

## 0.1.0 — 2026-05-22

### Added
- Initial release
- Odoo 18 Community Edition from nightly APT
- PostgreSQL 15 bundled in the same container
- s6-overlay service management (cont-init.d + services.d)
- Auto-sync PostgreSQL password on every boot
- Configurable SMTP settings
- Auto-update modules on startup (`auto_update_module`)
- CJK fonts + wkhtmltopdf for PDF report generation
- WOOWTECH odoo-addons pre-installed from GitHub main branch
- Support for user custom modules via `/share/odoo_addons`
- Multi-architecture support: amd64 + aarch64
