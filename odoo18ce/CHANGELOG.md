# Changelog

## 0.4.4 — 2026-09-24

### Added
- The image now carries `python3-pycryptodome`, so WOOWTECH's ECPay
  e-invoice module (`ecpay_invoice_tw` from `ecpay_odoo18`, placed in
  `/share/odoo_addons/`) can be installed. It declares `pycryptodomex` and
  imports `Cryptodome`; Odoo refused it with "External dependency
  pycryptodomex not installed". The Debian package registers as
  `pycryptodomex` and provides `Cryptodome`, so no pip install is involved.
  The PR gate now runs Odoo's own external-dependency check for it in the
  built image. Issue #141.

### Changed
- The add-on's config folder is now mapped as `app_config:rw`, the name
  Supervisor 2026.07.1 gave it, instead of the legacy `addon_config:rw`.
  Nothing moves: Supervisor binds the same host folder to `/config`
  either way, and a local build no longer logs the legacy map-type
  warning. **The add-on now requires Supervisor 2026.07.1 or later**;
  older Supervisors reject the manifest and the store cannot load the
  add-on. Supported installs update Supervisor automatically. Issue #126.

## 0.4.3 — 2026-09-23

### Added
- The add-on now checks at every start that its database manager is closed
  to the Cloudflare tunnel. Once nginx answers, it requests
  `/web/database/manager` the way the tunnel does: from its own add-on
  network address (learned from the Supervisor, never loopback, which is
  LAN tier), on port 8069, with the host of `public_url` as `Host`. It
  starts normally on `404` with `public_url` set, or on `503` without it,
  and logs one line. On any other answer — `200`, a 5xx, or none at all —
  it logs an error naming the status and the route, sends a Home Assistant
  notification, and stops the container. This replaces the nightly
  Perimeter check's outside view. ADR 0005, issue #79.
- The Rewrite scan now tells you in Home Assistant when it acts. A round
  that adds Generated rewrites creates a persistent notification naming the
  new prefixes, and a round whose generation, validation or reload failed
  creates one naming the step; a round that changes nothing, and every
  round with **Apply Generated Rewrites** off, sends nothing. Ingress
  tokens are masked, a failure repeated every five minutes replaces its own
  notification rather than stacking, and a notification that cannot be
  sent is logged without changing the round. The add-on now asks for
  `homeassistant_api`, which this needs. ADR 0005, issue #78.
- The Rewrite scan now runs by itself. A new service scans once at start,
  as soon as PostgreSQL is ready, and every five minutes after that, so an
  application installed while the add-on is running has its navigation
  prefixes rewritten within five minutes and without a restart. Every
  round is written to the add-on log: the status of each database (`ok`,
  `failed`, `no bundles`) by name, whether the scan was complete, and —
  when bundles were read — what each one contains at each level, the
  exception hits and the prefixes now in the include file, with every
  Ingress token masked. A round that fails is a warning in the log and
  nothing more: the rules already in place stay live, Odoo is untouched,
  and the next round runs five minutes later. This is the first service in
  the image that does not stop the container when it exits, because Odoo
  must start and keep running whatever the scan does. ADR 0009, issue #94.
- The Rewrite scan now applies what it finds: the navigation prefixes no
  shipped rule covers become an nginx `include` file, which is validated
  with `nginx -t` against a rendered configuration that loads the candidate
  and is moved into place and reloaded only when nginx accepts it. A page
  that navigates to an address the Ingress rules do not cover yet is
  therefore fixed on the host, without a new Release. Four refusals guard
  it: an incomplete scan is never applied, a bundle whose bytes are missing
  fails its database, an unchanged generation is neither written nor
  reloaded, and a candidate nginx refuses leaves the last good file in
  place with Odoo still running. The new option **Apply Generated
  Rewrites** (`literal_rewrite_auto`, default on) freezes application: the
  scan and its report keep running and the rules already in place stay
  live. The image gains `python3-yaml`, because the exception list that
  ADR 0005 keeps applying is YAML and the container had no reader for it.
  ADR 0008, issue #93.
- A one-shot `odoo-rewrite-scan` command in the image prints, for every
  Odoo database, the asset bundle attachments it serves with their
  checksums, a per-database status, and whether a Rewrite scan is due. It
  is the read half of the Generated rewrites in ADR 0005 and it only
  reads: nothing is applied and no nginx rule changes yet. The bundles are
  read with one `psql` query plus the filestore rather than by starting an
  Odoo registry, which is about 60× cheaper per round and was measured
  before the choice was made. ADR 0007, issue #92.
- Ingress: the Runtime shim now publishes the Canonical URL to the page as
  a read-only `window.__WOOW_CANONICAL_URL__`. Odoo 18 builds some links
  for people outside in the browser, from the address in the address bar,
  and through Ingress that is the Home Assistant host, so the link is a
  Home Assistant 404 for whoever receives it; the lock on `web.base.url`
  cannot reach those values because they never pass through the server.
  This change publishes the value only. It moves no link yet — each one is
  moved onto that base by its own exact-expression rewrite, starting with
  the Discuss invitation link. Without a Canonical URL (Ingress-only and
  the Supervisor reports no LAN address) the global is empty and nothing
  changes. The Public origin is untouched. The rule that chooses the value
  stays in `canonical_url()` in the maintenance library, which the config
  rendering now calls through `odoo-canonical-url` and the maintenance
  bootstrap still calls for `web.base.url`. ADR 0006, issue #70.

### Fixed
- A LAN address that arrives a moment after the add-on starts no longer
  costs that start its Canonical URL. Without `public_url`, the address
  came from one Supervisor read at boot, and bashio caches an empty answer
  for the life of the container, so a DHCP lease that landed a few seconds
  late left the Runtime shim with no Canonical URL and `web.base.url`
  unwritten until the next restart. The read now waits up to 30 seconds,
  two seconds apart, with bashio's cache flushed in between; the published
  port is read again only while the Supervisor request itself fails; and
  the address and port the start settles on are handed to the maintenance
  bootstrap through the container environment, so one start has one LAN
  address and one port on both sides and the bootstrap never asks the
  Supervisor on its own. When no address comes, the start takes the
  no-Canonical-URL path it always took, and the log says the add-on
  waited. With `public_url` set nothing waits. Hosts
  that never have an IPv4 address (a bridge, bond, WWAN or tun uplink, an
  unmanaged interface, IPv6-only) pay the 30 seconds once per start, and
  so does a Supervisor that cannot be asked at all: the address and the
  port share the one budget. Issue #108.
- The Rewrite scan's Home Assistant notification now covers every step of
  a round. A state file or a database scan that raised used to end the
  round with a traceback and no notification; both now notify, naming the
  step (`state`, `scan`). A failure in the writes (the candidate, the move
  into place, the state write) is reported as the `apply` step, and one
  that came after the move says that the rules on disk are the new ones,
  naming them and whether nginx loaded them, instead of claiming the
  include file is untouched; the add-on log says the same, and the
  service's own failure line no longer claims the file kept its old rules.
  And a round that added rules before nginx was up says they take effect
  when nginx starts rather than that they are live now. Issue #120.
- The start-time self-check no longer stops a correct install because the
  Supervisor answered empty once. It read the add-on's own network address
  a single time at boot, and bashio caches an empty answer for the life of
  the container, so one late Supervisor reply became a failed check, a
  notification and a stopped add-on. The read is now retried for up to
  30 seconds, two seconds apart, with bashio's cache flushed in between,
  and only once nginx is up, so the Supervisor has the whole Odoo boot to
  learn the address first (`/usr/local/lib/supervisor-read.sh`, written
  for the LAN-address reads of issue #108 to use next). The Supervisor's
  placeholder `0.0.0.0`, which it answers
  before it has seen the container on the network, counts as no answer
  too, and the check refuses it and any loopback address the way it
  refuses an empty one. An address that never comes still fails the check,
  the log says the add-on waited and, when the Supervisor refused the
  request, what it said; the empty answer is not left in the cache. On pass the service logs one line; the "waiting for nginx" line
  moved to debug. Issue #119.
- A database created through the database manager on a host with no
  Canonical URL no longer has Odoo's install default,
  `http://localhost:8070`, locked in as its `web.base.url`. The start-up
  bootstrap now leaves that value unfrozen and logs a warning, so the next
  start that has a LAN address writes the Canonical URL over it; a value
  someone set is still kept and frozen as before. Issue #89.
- Ingress: a page's Share block no longer posts the Supervisor token to
  Facebook, X or WhatsApp on a host with no Canonical URL. The rewrite
  already moved the link onto that base; it now drops the Ingress prefix
  whether or not the base exists, because the alternative was handing a
  credential to a third party in exactly the deployment shapes where it is
  easiest to end up — an uplink that is a bridge, bond, WWAN or tun device,
  an interface NetworkManager does not manage, IPv6-only networking, or a
  DHCP lease that arrives after the add-on starts. Without a Canonical URL
  the link still points at the Home Assistant host and still does not work;
  it simply carries no token. ADR 0006 amendment, issues #70 and #108.
- Ingress: the three links Odoo builds in the browser for somebody
  outside to open now carry the Canonical URL instead of the Home
  Assistant host — the Discuss channel invitation link, the base shown
  before a page's path in Website → Pages, and the address a page's Share
  block hands to Facebook, X or WhatsApp. The share block was the worst of
  the three: it posted the full Ingress URL, Supervisor token included.
  Each one is moved by its own exact-expression rewrite, measured against
  the bundles the control group serves with the parity plan's 25
  applications installed and kept as a fixture; Odoo's shared URL helper is
  left alone, because it also builds the in-Ingress addresses for images,
  attachments and RPC. Without a Canonical URL nothing changes, and the
  Public origin is untouched. ADR 0006, issue #70.
- Three Prefix escapes under Ingress found by the Literal rewrite gate
  once the parity plan's 25 applications were installed on the control
  group: eCommerce's `redirect('/shop/cart')`, the payment flow's
  `window.location='/payment/status'` and a website tour's
  `window.location.href='/contactus'`. `/shop/`, `/payment/` and
  `/contactus` are now rewritten in the Ingress asset location in the
  three quote variants. Issue #58.
- Ingress: Odoo's copy buttons (share links, Discuss invitations, copy-to-
  clipboard widgets) work again when Home Assistant is opened over plain
  http on the LAN. That page is not a secure context, so the browser hides
  `navigator.clipboard` inside the Ingress iframe and every copy button
  failed silently or with "Oops! Something went wrong". The Runtime shim
  now supplies a `writeText` backed by `document.execCommand("copy")`
  whenever `navigator.clipboard` is absent; HA over https and the Public
  origin are untouched. Issue #60.
- A database created between two add-on starts no longer takes its
  Canonical URL from the first administrator login. Odoo writes
  `web.base.url` from the request it authenticated whenever
  `web.base.url.freeze` is unset, which is the state of every database the
  database manager creates after a start; through Ingress the value it
  wrote was the Home Assistant host, so every email, share, portal and
  report link pointed at Home Assistant until the next restart. The image
  now ships a server-wide module, `woow_base_url_guard`, that Odoo loads
  into every process and installs in no database and that removes the
  guess on every surface. The maintenance bootstrap stays the only writer
  of the Canonical URL; writing the value explicitly from Settings or over
  RPC is unaffected. Issue #67.

### Changed
- The Debian base image is pinned in the Dockerfile (`ARG BASE_IMAGE_TAG`,
  composed into `FROM` with `BUILD_ARCH`) and `build.yaml` is gone.
  Supervisor had deprecated `build.yaml` and passes a modernized local
  build only `BUILD_ARCH`, so a Dockerfile that took its base from
  `BUILD_FROM` could not be built on a host any more. The tag is the same
  `bookworm-2026.08.0` for both architectures; CI, the publish action and
  the weekly `odoo-bump` now read and write that one line instead of the
  YAML file. A local build on a host no longer logs the `build.yaml`
  deprecation warning. Issue #124, part of #110.
- The two Live-tier workflows, the Perimeter check and the Literal rewrite
  gate, no longer run on the nightly schedule; both are dispatch-only. The
  add-on now does both jobs on the host itself — the start-time self-check
  for the database-manager routes, the in-container Rewrite scan for the
  Literal rewrite — and the test host that served as the control group is
  being stopped, so a scheduled run would have had nothing to run against.
  `workflow_dispatch` stays on both for whenever a control group exists
  again, and release.yml still dispatches the perimeter check after a
  Release. ADR 0005, issue #80.
- The Literal rewrite gate CLI takes `--include-file`, a copy of the
  Generated rewrite include file the host under test applied, and merges
  its rules with the template's before evaluating. A run against a host
  that applied Generated rewrites then reports 0 unregistered `FAIL`
  instead of re-reporting the prefixes the add-on already covers there.
  Issue #80.

### Testing
- The Literal rewrite gate now identifies a bundle by its URL path, from
  `/web/assets/` on, instead of its file name. Odoo serves one name under a
  website-scoped `/web/assets/1/<unique>/<name>` and an unscoped
  `/web/assets/<unique>/<name>` with different content; the gate fetched
  and scanned only the first it saw, so a navigation literal in the other
  passed unreported. Both are now scanned, saved to separate files, kept
  apart by `--from-dir`, and named apart in the report. Results of earlier
  runs are a floor, not a complete count. Issue #98.
- The PR gate now fails when the Canonical URL guard is not applied. The
  `build (amd64)` job, which every pull request runs, including the Odoo
  nightly bumps, starts `odoo shell` in the image it just built, with the
  server-wide modules the add-on renders and no database, and checks that
  `res.users.authenticate` carries `woow_base_url_guard`'s flag. It runs a
  second time without the guard in `--load` and must then report it not
  applied. Before, a nightly that moved `authenticate` merged green: the
  guard's `ImportError` does not stop Odoo, whose server-wide loader logs
  it and serves unguarded. Issue #88.
- The Canonical URL guard gate proves more than the flag. The in-image
  probe now checks the last `res.users` class in Odoo's `res_users` module
  that declares `authenticate` (the one the registry runs), not the first
  flagged one, and checks that the upstream `authenticate` the wrapper
  wrapped still takes what the wrapper forwards by position (an added
  optional parameter fits; a renamed, reordered or keyword-only one does
  not), so a nightly that redefines the method later in the module or
  changes its parameters goes red instead of shipping the guess back or
  breaking every login. `build (amd64)` has a 30-minute limit, each
  `docker run` a 300 s one, and a container that never reaches the probe
  is reported as a container failure, not as the guard missing. Issue #121.
- New static-tier contract test `test_ingress_clipboard_fallback.py`
  executes the whole Runtime shim in a node `vm` context against a DOM
  stand-in and pins the clipboard fallback: absent clipboard resolves
  through one `execCommand("copy")`, removes its textarea and hands focus
  back; a present clipboard keeps the same reference; a refused copy
  rejects. It also fails when any quoted parameter in
  `nginx.conf.template` reaches nginx's 4096-byte limit, which a missing
  local nginx used to hide. Issue #60.
- New Live-tier Literal rewrite gate, `tests/e2e_literal_rewrite_gate.py`
  (issue #58, ADR 0004). It logs in to the control group's Public origin,
  collects every asset bundle the backend, Discuss, the website and each
  installed app's landing page load, extracts every root-relative string
  literal, classifies each by how the bundle consumes it (`FAIL` whole-page
  navigation, `WARN` path comparison, `INFO` anything the Runtime shim
  intercepts) and compares the prefixes against the `sub_filter` rules in
  the Ingress asset location of `nginx.conf.template`, parsed from the
  template itself. An unlisted prefix in a whole-page navigation fails the
  run unless `rootfs/usr/local/lib/literal_rewrite_exceptions.yaml`
  records it with a reason. Ingress tokens are masked in the output.
- The pure stages (extraction, classification, nginx rule parsing,
  exception matching, evaluation) ship in the image as
  `rootfs/usr/local/lib/literal_rewrite_gate.py`, next to the maintenance
  library, so the same code can serve inside the container and out. The
  static tier pins them in `test_literal_rewrite_gate.py`, which loads the
  module from the image the way the maintenance bootstrap tests do.
  Issue #75.
- New static-tier contract test `test_workflow_triggers.py`: the Perimeter
  check and the Literal rewrite gate declare `workflow_dispatch` and no
  `schedule`. `test_literal_rewrite_gate.py` gains the effective-rules
  cases — the include file parses as bare `sub_filter` lines, merged rules
  union the quote variants per prefix, and the CLI run with
  `--include-file` reports a `FAIL` prefix the file rewrites as covered.
  Issue #80.
- New workflow `literal-rewrite-gate.yml` runs the gate on demand against
  every origin in `ODOO_PUBLIC_URLS` with the `ODOO_TEST_LOGIN` /
  `ODOO_TEST_PASSWORD` secrets, failing early with the name of any missing
  secret.
- New static-tier test `test_base_url_guard.py` drives the patched login
  path against a stand-in of Odoo's `res.users`: a `user_agent_env`
  carrying a `base_location` produces no `web.base.url` write while the
  authentication result comes back unchanged, and the same stand-in is
  shown to make the write when nothing guards it. The config-script
  contract in `test_dual_gateway.py` now also pins the
  `server_wide_modules` line and the module's directory on the rendered
  `addons_path`. Issue #67.

## 0.4.2 — 2026-09-16

### Security
- The maintenance bootstrap now writes and freezes `web.base.url` on every
  Odoo database on every start, in every install shape. Before, it only did
  so when both `public_url` and `default_db` were set; an Ingress-only
  install was unprotected, and one admin login through Ingress wrote the
  Supervisor path `/api/hassio_ingress/<token>` into `web.base.url`, from
  where the token reached every email, share link, portal link and report.
  Without `public_url` the Canonical URL is now the Home Assistant host's
  LAN address with the published 8069 port, read from the Supervisor. A
  stored value that carries an Ingress token is never kept: it is replaced
  when a Canonical URL exists and removed otherwise. Issue #57.

### Added
- The default website's `domain` is set to the Canonical URL on every
  start when the `website` module is installed, so website-generated
  absolute links match email links.
- Manifest `hassio_api: true`, needed for the LAN-address fallback. The
  default role is enough; no `hassio_role` is requested.
- `DOCS.md`: a "Canonical URL" section explaining the three shapes, the
  Supervisor permission and the Ingress-only fallback.

### Changed
- `public_url` without `default_db` is a valid configuration; the add-on
  no longer refuses to start with "default_db is required". `default_db`
  is still required for `auto_update_module` and for the one-shot
  maintenance account file, which is now kept (with a warning) until a
  start with `default_db` set consumes it.
- A failure while processing one database is logged with the database
  name and the bootstrap continues with the next one; Odoo always starts.
  Only the `bootstrap-user.json` policy violations remain fatal.

### Testing
- New static-tier module `test_maintenance_bootstrap.py` runs the full
  decision matrix (`public_url` set/unset × `default_db` set/unset ×
  stored value clean/leaked/absent × LAN address available/unavailable)
  against the pure decision functions in
  `rootfs/usr/local/lib/odoo-maintenance.py`, without Odoo or the
  Supervisor.
- The perimeter check no longer reports a bare Odoo login page as blank. It
  polls for rendered body text instead of sampling once at `domcontentloaded`,
  where a database without `website` showed only "Powered by Odoo".

## 0.4.1 — 2026-09-14

First Release produced entirely by the pipeline: the weekly bump proposed
the Odoo package, a human merged it, and the Release workflow did the rest.
No database migration: none of the installed modules changed version
upstream in this window.

### Changed
- Odoo nightly package 18.0.20260806 -> 18.0.20260914.
- Debian base image bookworm -> bookworm-2026.08.0.
- `HEALTHCHECK` uses the exec (JSON) form. Same probe, no shell; hadolint
  3.5 flags the shell form (DL3025).

### Added
- Perimeter check workflow: after each Release and daily at 05:30 Taipei, a
  GitHub runner confirms from outside that every public origin listed in the
  `ODOO_PUBLIC_URLS` repository variable keeps `/web/database/*` and the
  XML-RPC/JSON-RPC database services closed, and that its basic pages load.
- Weekly Odoo nightly bump workflow: finds the newest 18.0 nightly package
  and dated Debian base-image tag, pins them with a fresh SHA256, records
  the change here, and opens a pull request that the PR gate builds. Never
  merged automatically.

## 0.4.0 — 2026-09-10

This Release changes how the add-on is installed. Supervisor now pulls a
prebuilt image instead of building the Dockerfile on your device, so this
update downloads an image once and later updates are pulls, not rebuilds.
Your database, filestore and options are untouched.

### Changed
- `image: ghcr.io/woowtech/woow-ha-odoo-{arch}`: prebuilt images for amd64
  and aarch64, published by the Release workflow with an immutable version
  tag. No more 245 MB Odoo download and PostgreSQL install on every update,
  and a released version stays installable even after nightly.odoo.com
  drops its package.
- The manifest `watchdog` URL is replaced by a Docker `HEALTHCHECK` that
  fetches the login page through nginx on loopback every 60 s, with a
  10-minute start period so first-boot database creation and post-upgrade
  module updates are not mistaken for a hang. The Watchdog toggle on the
  add-on page keeps working; it now reads container health.
- `webui` removed: with Ingress enabled the OPEN WEB UI button opens the
  sidebar panel. Direct LAN access on port 8069 is unchanged and documented
  under "LAN access".
- The Home Assistant add-on linter is now a blocking check.

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
- Release workflow: a version bump merged to `main` now builds and pushes
  `ghcr.io/woowtech/woow-ha-odoo-{amd64,aarch64}:<version>` (version tag
  only, never overwritten), creates the `v<version>` tag and a GitHub
  Release from this file's section, and asks the App Store to sync at once.
  Supervisor keeps building on-device until `image:` is added to
  `config.yaml` in a later Release.
- Image labels (`io.hass.*`, `org.opencontainers.image.*`) filled in by the
  publish workflow.
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
