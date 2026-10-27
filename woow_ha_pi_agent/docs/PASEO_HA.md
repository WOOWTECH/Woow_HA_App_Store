# Paseo managed web client in Home Assistant

This change retains the official Pi Web 0.12.0 npm build and its SDK 1.1
compatibility pins. It does **not** install the plugins' Pi Web 0.10 overlay.
The native desktop tabs and mobile picker are MCP → Omnigent → Paseo.

## Immutable image inputs

- Paseo plugin 0.1.12, source `6796e48c6b3cce06e75c86742ba7b5d3ac121855` (public release archive verified with
  SHA256 `35eb66d3674d913cfa8e0adb795c6bd1c62ea6819fef29f3fb3757e0d9aa9b17`).
- Paseo daemon 0.11.2, locked runtime revision `0.11.2-r3-6d8dbe515479`.
- Fixed web client 0.13.0-woow.1, source
  `68388f19198f1f696efe18906df42049e208d135`, stream repair
  `043aa8286b90418eb1f4e9982ca1a349c84f2a3d`, archive SHA256
  `7e7495f70f721e96e121f76bd91573150cf91aa112143d9f4d51a3fcf9dc8bce`.
- Omnigent 0.3.27, source `f0c0efa2c4114863c826eb994c81c7833ea6d1f8`, public archive SHA256
  `28acbd22e2e2d28a3cdea76ede7ddd8e19a46779a34b2a2a6a896873a831ba53`.
  HA 0.15.14 keeps authorized-host recovery and native Pi Web 0.12 settings;
  a fresh Omnigent install creates one setup conversation and links it from Settings.
  Server account entry remains in Settings. Paseo pairing is available only through Settings.

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
bundled plugin once; it does not create or open an onboarding conversation. The plugin supervisor prepares the service independently. Pairing requires a button press in Settings → Paseo.
A marker prevents reinstallation after removal; pre-existing package overrides
and explicit disabling are retained. Package enable/disable/removal is observed
without restarting Pi Web. A manual service pause survives container restart;
shutdown stops the owned supervisor without persisting a user pause.

Paseo 0.1.12 uses the r3 runtime with verified patches in both native 0.11.2
PID-lock modules. All supported writers and recovery share one persistent
Linux flock guard. Automatic recovery requires a private proof bound to the
installation, home, lock inode and Linux process birth; a PID or process name
alone cannot authorize it. The existing util-linux runtime dependency provides
flock. The offline image test exercises both patched writers and competing
flock exclusion in a disposable home without launching a daemon or provider.

When a trusted r2 runtime remains available, status and normal owned stop
continue to work before r3 is installed. A healthy r2 daemon with r3 prepared
returns `RESTART_REQUIRED`; use the normal stop/start lifecycle. It does not
mint an r3 proof for the old daemon. A legacy record whose PID appears live
but cannot be tied to its original process remains rejected without trusted
proof and needs ownership diagnosis. Recovery does not delete that record
or signal the foreign process. Native 0.11.2 dead-process and cross-boot checks
remain in place. The image
bundles r3 only; it does not copy the previous image's r2 runtime directory.

New users still need to authorize the provider CLIs through their official
login flows. This integration does not migrate or create provider credentials.
The bundled Claude Code/Codex versions, shared skills/MCP and Omnigent bridge
are retained. Its existing `boot` call retains Omnigent authorized-host recovery in 0.3.24: only
matching private authorization receipts for this installation may resume the
recorded host. Disabled/disconnected or credential-only states do not silently
authorize a reconnect. Existing custom plugin paths remain user-controlled and
may need upgrading to support the managed web API.

Isolated HA 0.15.2→0.15.5 acceptance confirmed automatic recovery of the
original host after official upgrade and addon restart. A whole-VM restart
exposed `HOST_PROCESS_MISMATCH`: the saved PID belonged to an unrelated
process in a different boot, so the shared plugin safely refused recovery.
Omnigent 0.3.18 distinguishes a proven stale process receipt inside the
existing authorized launch lock. It adopts an exact current installation host
or starts the same authorized registered host; ambiguous identity fails closed.
Disconnect keeps its strict process check, and no unrelated process is signaled.
Omnigent 0.3.19 also recognizes a proven stale PID reused by a process under another UID after container restart; incomplete kernel identity still fails closed.
The original failed QA state is preserved for official HA 0.15.6 upgrade and
addon/VM restart acceptance. A read-only candidate classification passed on
that actual record; live recovery is a separate release acceptance gate.

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
architectures and never push images. Publication follows the required PR and native image gates. Post-release
checks verify both registry manifests and Store/local-build synchronization.
Live Supervisor and real-account model acceptance remain separate; this
fanout does not operate live HA, VMs or Pi4.

The measured local gzip runtime layer is about 164 MiB, below the 256 MiB
changed-layer budget. This estimate does not replace the final registry manifest
check after publication; that gate remains part of post-release verification.
