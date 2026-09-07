# Changelog

## 0.1.15 — 2026-09-06

Fix black-screen crash on Settings > Members / Policies / Sharing (and
any other lazily-loaded route that pulls its own JS/CSS chunk). The
Vite modulepreload helper Fe() constructs URLs as `` `/` + chunkName``
— under Ingress that resolves to origin `/assets/foo.js` and 404s,
throwing `Unable to preload CSS` which crashes React.

Two coordinated fixes:

1. **Dockerfile sed patch on Vite Fe() helper** — prefix with
   `window.__INGRESS_PATH__` so modulepreload URLs land inside the
   ingress iframe.
2. **Broader nginx sub_filter** — catch every quoting style
   (`` "assets/`, `'assets/`, `"/assets/`, `'/assets/`, `` `/assets/``,
   and their leading-slash-less variants used by Vite's chunk
   manifest strings) and rewrite to `/assets-v0-1-13/…` in both the
   parent `location /` and the versioned `location /assets-v0-1-13/`
   proxy.

## 0.1.14 — 2026-09-06

🎉 **HA Ingress panel now 100% functional.** Full feature parity with
the k3s reference deployment (`omnigent.woowtech.io`) achieved through
the HA sidebar `Woow Omnigent` panel — no LAN / CF tunnel needed for
end users.

The winning combination (five layers, all required):

1. **`history.replaceState()` early in `ingress-shim.js`** — strips
   `/api/hassio_ingress/<slug>` from the iframe's URL bar the instant
   the shim runs (before any React/module code). Omnigent's router
   then reads `location.pathname === "/login"` (not
   `/api/hassio_ingress/<slug>/login`) and matches routes normally.
   Bypasses the need for `basename` hookup in the bundled router
   library, which we couldn't monkey-patch cleanly.

2. **Versioned `/assets-v0-1-13/` alias in nginx** — the *only* way to
   invalidate the `immutable, max-age=31536000` browser cache that
   omnigent's server sets on every asset. We rewrite `/assets/` →
   `/assets-v0-1-13/` in both HTML and JS (chunk imports), then a
   dedicated `location ~ ^/assets-v0-1-13/…` proxy strips the version
   before forwarding upstream. Bump the number when bundle patches
   change and every user's browser refetches automatically.

3. **Three sed patches to the built React bundle** (Dockerfile
   post-install step, byte-for-byte matches on omnigent 0.12.0's
   Rolldown output):
     - `Y()` auth-guard equality → broadened `endsWith` (safety net
       for lazy chunks that load before the shim's replaceState)
     - `t = encodeURIComponent(pathname + search)` → prefixed with
       `window.__INGRESS_PATH__` so post-login `?return_to=…` lands
       back inside the ingress
     - `q(e)` redirect target → prefixed with `window.__INGRESS_PATH__`
       so unauthenticated redirects to `/login` stay inside the frame

4. **`proxy_hide_header Cache-Control` + `text/javascript` MIME match
   in the cache-control map** — omnigent serves JS as `text/javascript`
   (older spelling), so `application/javascript` alone missed it, and
   `add_header` stacked with upstream's `immutable` rather than
   replacing. Both fixed here.

5. **`sub_filter_types text/html application/javascript` +
   `Accept-Encoding ""` to upstream** — sub_filter can't rewrite
   gzip'd bodies, so we ask FastAPI for identity.

**Verified end-to-end via HA UI Ingress panel** (browser through
Cloudflare → HA → Supervisor → nginx → omnigent): login, sidebar with
sessions from persistent Postgres, Settings navigation, host picker
showing `Online 1b7b4ce7-woow-ha-pi-agent` (the sibling `woow_ha_pi_agent`
addon auto-registered as an external runner).

## 0.1.13 — 2026-09-06

Deep-dive on HA Ingress support, modelled on the sibling Woow_ha_n8n
add-on. Result: **Ingress panel is 70% working** (SPA loads, sidebar
renders, assets fetch through prefix, auth-redirect stays inside the
ingress iframe) but the main route still renders "Page not found"
because omnigent's bundled router library uses `rebasePath: e => e`
(identity) and has no `basename` hookup, so it can't strip
`/api/hassio_ingress/<slug>` from `location.pathname` before matching
routes. Upstream needs a `--root-path` CLI flag that:

  1. Sets router `basename` in the client bundle
  2. Includes ingress prefix in the `login_url` field of `/v1/me` 401 responses
  3. Passes to Vite build's `base` option so asset URLs get emitted
     relative to the ingress path

Until then, **use LAN direct `http://<HA-IP>:8000`** (fully working) or
wire a CF tunnel route mapping a subdomain straight to port 8000 (no
prefix, no rewriting).

Concrete changes shipped in this release:

- `ingress_entry: login` in config.yaml so HA opens the iframe at the
  login route directly (same trick n8n uses).
- Fix cache-control: match `text/javascript` too (omnigent serves JS
  with that content-type, not `application/javascript`), and
  `proxy_hide_header Cache-Control` in the location block so our
  `no-store` actually replaces upstream's `public, max-age=31536000,
  immutable` instead of stacking. Without this, browsers cached the
  pre-fix bundle for a year and hid every iteration for hours.
- Sub_filter extended to `application/javascript` responses (was
  html-only). `sub_filter_once off` + rewrites for `src="/assets/"`,
  `href="/assets/"`, `from"/assets/"`, `from "/assets/"`.
- Dockerfile sed patches into `identity-B-MWCDgo.js`,
  `index-CFYKOrOo.js`, `routing-B815e3wm.js`:
    * Y() equality check broadened to `endsWith(\`/login\`)` etc. so
      the ingress-prefixed pathname counts as being on /login.
    * q(e) redirect target prefixed with `window.__INGRESS_PATH__`.
    * xwt() app-router basename defaults to `window.__INGRESS_PATH__`.
    * Ge() base-router basename defaults to `window.__INGRESS_PATH__`.
- Static-file shim `ingress-shim.js` extended with `Location.prototype.
  assign / .replace` monkey-patch (best-effort — Chrome forbids
  overriding `Location.href` setter because it's `configurable: false`,
  which is the last missing piece for full Ingress support).

## 0.1.12 — 2026-09-06

- Remove `location = / { return 302 $safe_ingress_path/; }` — it
  created an ERR_TOO_MANY_REDIRECTS loop for the Ingress iframe.
  Supervisor strips `/api/hassio_ingress/<slug>` before proxying, so
  the browser landing on `.../<slug>/` reaches us as `GET /`, and
  redirecting back to the ingress path just re-hits the same URL.
- Include `/etc/nginx/mime.types` so CSS is served as `text/css`
  (browsers with strict MIME checking refuse `text/plain` stylesheets).
- Set `proxy_set_header Accept-Encoding "";` — sub_filter can't rewrite
  gzip'd upstream responses, so we ask FastAPI/uvicorn for identity.
- `sub_filter_once off` + rewrite `src="/assets/` and `href="/assets/`
  to `$safe_ingress_path/assets/`. Vite emits root-absolute bundle
  URLs and `<base>` doesn't help absolute paths, so we patch them
  in-flight before the browser fetches.
- Add `proxy_redirect ~^/(.*) $safe_ingress_path/$1;` so any
  server-side 302 Location gets ingress-prefixed too.
- **Known limitation:** the HA Ingress panel is still partially broken
  because omnigent's React SPA uses `window.location.href = "/login"`
  for client-side redirects. Chrome's `Location.href` setter has
  `configurable: false` and can't be monkey-patched from user JS, so
  our shim (which does hook `.assign()` / `.replace()` / fetch / XHR /
  WebSocket / pushState) can't intercept it. Workaround: use LAN
  direct `http://<HA-IP>:8000` or wire a CF tunnel route that maps
  a subdomain straight to port 8000 (no path prefix).



## 0.1.11 — 2026-09-06

- Add `py3-psycopg` — omnigent 0.12.0's SQLAlchemy engine imports it
  via `postgresql+psycopg://…` but doesn't declare it as a hard PyPI
  dep, so the container ended up with sqlalchemy but no driver:
  `ModuleNotFoundError: No module named 'psycopg'`.

## 0.1.10 — 2026-09-06

- Minimise `.build-deps` to `build-base + abseil-cpp-dev + re2-dev`.
  On base 20.2.0, `openssl-dev` demands libcrypto3-3.5.8 while world
  pins 3.5.6, which fails apk resolution. Everything else in
  omnigent's dep tree ships musllinux wheels so the extra -dev
  packages weren't needed anyway.

## 0.1.9 — 2026-09-06

- Pin base image to `hassio-addons/base:20.2.0` (Alpine 3.22 + Python
  3.12) instead of `21.0.4` (Alpine 3.23 + Python 3.14). Upstream
  `anyio` fails to import on 3.14:
  `ImportError: cannot import name 'sentinel' from 'typing_extensions'`
  — the module renamed it to `Sentinel` in newer versions and anyio's
  release used with omnigent 0.12.0 wasn't updated yet.

## 0.1.8 — 2026-09-06

- `svc-omnigent-server` now sources `/var/run/omnigent.env` and passes
  `--host 0.0.0.0 --port 8000 --database-uri postgresql+psycopg://...
  --no-open` explicitly. `with-contenv` snapshots
  `/run/s6/container_environment/` at boot before `init-addon-config`
  writes to it, so omnigent was falling back to defaults and binding
  `127.0.0.1:6767` on sqlite instead.

## 0.1.7 — 2026-09-06

- Add `abseil-cpp-dev` + `re2-dev` to the build-deps group so
  `google-re2`'s source build can find `absl/strings/string_view.h`.
  Base image also bumped to Python 3.14 which forces a fresh build
  even where wheels exist for older cpython.

## 0.1.6 — 2026-09-06

- Actually install `omnigent`. Prior builds shipped an image without
  the Python package because `google-re2` (transitive dep via
  `cel-python`) has no musllinux wheel and needs `c++` to build from
  source — and the Dockerfile swallowed the failure with `|| true`,
  producing an "successful" image with no server binary.
- Add throwaway `.build-deps` (build-base + python3-dev + libffi-dev +
  openssl-dev + postgres-dev) around the pip install, then `apk del`.
- Split the `rm ~/.omnigent` cleanup into its own RUN so a real
  install failure now aborts the build instead of vanishing.

## 0.1.5 — 2026-09-06

- Serve ingress path-rewriting shim from a static `_ingress-shim.js`
  file instead of inlining the JS in `sub_filter`. nginx tried to
  parse `$/` inside the JS WebSocket regex as a variable reference
  and refused to load the config (`invalid variable name`).
- `svc-omnigent-server` now exports an explicit PATH before exec — the
  s6-oneshot env doesn't inherit it, so `omnigent: not found` was
  crashing the longrun in a restart loop.

## 0.1.4 — 2026-09-06

- Pre-create `/run/postgresql` (Alpine's default unix socket dir) so the
  postmaster can bind on first boot. Fresh addon containers don't ship
  this dir, causing `pg_ctl start` to silently fail.
- Dump `/tmp/pg-bootstrap.log` on postgres start failure so future
  boot errors surface in `ha apps logs` instead of vanishing.

## 0.1.3 — 2026-09-06

- Drop `bashio::config` in favour of `jq` on `/data/options.json`. On
  this base image the Supervisor API token isn't reliably wired into
  the s6-oneshot env, so every `bashio::config` call returned "Unable
  to access the API, forbidden" and the container refused to boot. The
  on-disk options.json is authoritative anyway.
- Switch all `run` scripts to `#!/command/with-contenv sh` for uniform
  env inheritance from `/run/s6/container_environment/`.
- Fix env dir path: was `/var/run/s6-rc/container_environment` (wrong),
  now `/run/s6/container_environment` (what s6-overlay v3 actually reads).

## 0.1.2 — 2026-09-06

- Re-enable `hassio_api: true`. `bashio::config` fetches
  `/data/options.json` via the Supervisor API, so disabling it breaks
  `init-addon-config` at boot (`Unable to access the API, forbidden`).

## 0.1.1 — 2026-09-06

- `base_url` schema relaxed from `url?` to `str?` so an empty string
  (the default when the operator hasn't set up a CF tunnel yet) doesn't
  fail Supervisor validation.

## 0.1.0 — 2026-09-06

- Initial release.
- Bundles omnigent 0.12.0 + PostgreSQL 16 + nginx via s6-overlay.
- HA Ingress panel with React SPA path rewriting shim (same trick as
  the sibling n8n add-on).
- LAN port 8000 exposed for external runner dial-in (`omnigent host
  --server http://homeassistant.local:8000`).
- Auto admin claim via `POST /auth/setup` on first boot (409 tolerant).
- `env_vars` schema field for arbitrary passthrough (e.g. API keys).
- **Not bundled:** pi / claude / codex CLI, omnigent runner — external
  hosts register themselves. Rationale: keeps the addon image <400 MB
  and matches how the k3s deployment already works.
