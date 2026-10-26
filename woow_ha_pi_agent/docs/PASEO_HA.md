# Paseo managed web client in Home Assistant

This change retains the official Pi Web 0.12.0 npm build and its SDK 1.1
compatibility pins. It does **not** install the plugins' Pi Web 0.10 overlay.
The native desktop tabs and mobile picker are MCP → Omnigent → Paseo.

## Immutable image inputs

- Paseo plugin 0.1.9, source `eed990fe06899e42bf446cf2d584ed2c26ae6bed` (public release archive verified with
  SHA256 `31efd9184ec93aa6c6b4da85f235ac7570dc6f64e39195c21d6c23f8ce93fbdb`).
- Paseo daemon 0.11.2, locked runtime revision `0.11.2-r2-6d8dbe515479`.
- Fixed web client 0.13.0-woow.1, source
  `68388f19198f1f696efe18906df42049e208d135`, stream repair
  `043aa8286b90418eb1f4e9982ca1a349c84f2a3d`, archive SHA256
  `7e7495f70f721e96e121f76bd91573150cf91aa112143d9f4d51a3fcf9dc8bce`.
- Omnigent 0.3.16, source `7be342058bd8be5f7e9e079fa05ae59199063a94`,
  public archive SHA256
  `82cd8adda69a98a1d4274eb3358d5bbb20195dd49b27f1d36a55ba8d6e67dabe`.
  HA 0.15.5 is the candidate version, built on the merged HA 0.15.4
  Omnigent update (PR #15). This draft is not published or deployed.

The image builds daemon dependencies for amd64 and aarch64 and downloads the
web client at build time, checking the plugin's manifest and checksum. First
boot copies the web client to `/data/pi-agent/pi-paseo/web-client/`; it does
not require an npm install or web-client download. Existing user runtime paths
are preferred; otherwise the bundled runtime in `/opt/woow/paseo-runtime` is
used. Provider login, live relay access and conversations still require network.

## Ingress and authentication

`/paseo/setup`, `/api/paseo` and `/paseo-web/*` use a separate Unix socket behind
the existing nginx listener. The HA Supervisor-only source-IP restrictions
remain unchanged. No new public port is opened. Settings API reads and writes
require an in-memory token, same-origin checks and bounded JSON requests.
Passwords and pairing data are not included in status responses.

The client artifact has basePath `/paseo-web`. The server rewrites that base
in the actual HTML, CSS, JSON and JS responses to the validated
`/api/hassio_ingress/<token>/paseo-web` prefix. This covers Expo router base,
absolute assets and dynamic imports. Deep links use the client's index fallback.
The plugin response is read as identity bytes, rewritten and then gzip-compressed
when the browser accepts gzip. nginx forwards Accept-Encoding to this bridge.
HTML, setup and API responses remain private/no-store. Hash-named static assets
are private/immutable under each distinct prefixed URL. Response lengths and
strong ETags describe the selected encoded representation; HEAD and conditional
304 use the same validators. Vary includes Accept-Encoding and X-Ingress-Path.
A four-entry/32 MiB LRU holds rewritten static bytes and gzip bytes only in
memory; serialized transformation avoids duplicate peak allocations for the
23 MiB main bundle. HA session paths are never persisted in a cache.
The settings page retains a strict CSP; the Expo client retains its upstream
headers (including same-origin framing) without inheriting the settings CSP
that would block its runtime. The bridge always requests identity bytes from the
plugin for text responses;
unexpected upstream-encoded text is rejected instead of rewriting compressed
bytes. After prefix rewriting the bridge negotiates and generates gzip itself.
nginx forwards those final encoded bytes unchanged. Binary responses need no
prefix rewriting and retain their bytes and representation headers.

Pairing is an explicit POST operation. Its private fragment remains in the
browser URL and is not sent to nginx. The persistent private pairing record is
owned by the plugin; browser logs/screenshots from real accounts must not be
published. The Ingress URL is session-specific: reopen from HA after it expires.

## Upgrade and lifecycle

No options, ports, architectures, image name or existing data formats change.
Credentials, settings and sessions are preserved. First install registers the
bundled plugin once and creates one persisted SDK onboarding conversation without requiring a model account or spending tokens. The plugin supervisor performs initialization independently.
A marker prevents reinstallation after removal; pre-existing package overrides
and explicit disabling are retained. Package enable/disable/removal is observed
without restarting Pi Web. A manual service pause survives container restart;
shutdown stops the owned supervisor without persisting a user pause.

New users still need to authorize the provider CLIs through their official
login flows. This integration does not migrate or create provider credentials.
The bundled Claude Code/Codex versions, shared skills/MCP and Omnigent bridge
are retained. Its existing `boot` call now uses Omnigent 0.3.16 recovery: only
matching private authorization receipts for this installation may resume the
recorded host. Disabled/disconnected or credential-only states do not silently
authorize a reconnect. Actual persisted-login recovery still needs live HA
acceptance by the parent owner. Existing custom plugin paths remain user-controlled and may need
upgrading to support the managed web API.

## Validation and release scope

`tests/omnigent-native-browser.mjs` runs the real compiled Pi Web 0.12 and the
checksum-verified Paseo client through the repository's actual nginx config.
Only listener/socket/log paths are adapted for local isolation; a small front
proxy simulates Supervisor path stripping. No browser JS override is used.
It covers desktop/tablet/390px mobile, settings order, private API/pair link,
mobile scrolling, actual `/paseo-web/settings` reload, absolute assets, gzip
wire size, ETag/304/HEAD, CSP and absence of pairing fragments in access logs.
Provider responses are fixtures: this is not live HA or paid three-engine chat
acceptance. The Docker build runs real CLI/SDK/static-client smoke tests with
network disabled. PR builds exercise generated local-source contexts on both
architectures and never push images. Parent integration owns the release
version, merge, Store/local-build synchronization and live acceptance.

The measured local gzip runtime layer is about 164 MiB, below the 256 MiB
changed-layer budget. This estimate does not replace the final registry manifest
check after publication; that gate remains part of parent release verification.
