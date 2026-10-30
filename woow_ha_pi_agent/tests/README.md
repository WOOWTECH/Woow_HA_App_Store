# Smoke tests

## HA native Omnigent settings

`patches/tests/omnigent-settings.test.mjs` requires `PI_WEB_ROOT` to point at a
pristine, extracted official `@agegr/pi-web@0.12.0` npm package. It tests the
actual compiled client/SSR files and flight references, repeated application,
and refusal of changed/ambiguous artifacts before any write.

```sh
PI_WEB_ROOT=/path/to/pristine/package node --test patches/tests/omnigent-settings.test.mjs
node patches/patch-omnigent-settings.mjs /path/to/runtime/package
PI_WEB_ROOT=/path/to/runtime/package EVIDENCE_DIR=/path/to/test-evidence \
  PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs \
  PASEO_PLUGIN_ROOT=/path/to/verified-paseo/package \
  node tests/omnigent-native-browser.mjs
```

The runtime package needs its production dependencies, with the same
`pi-codemode`, `pi-mcp` and `chord` 1.1.0 overrides as the Dockerfile. The browser
suite starts real compiled Next.js with a fresh HOME and uses the actual bridge
and a real nginx process using the production Ingress configuration, behind a
local proxy that simulates Supervisor path stripping. It checks desktop, tablet and
phone settings, the MCP-adjacent order, blank/masked credentials, two model
selections, disconnect confirmation, Escape, remount and the standalone page.
The Omnigent runtime is a fixture: these tests do not validate provider logins,
paid model responses or real HA Supervisor ingress. Paseo tests use the
checksum-verified public 0.1.15 client and cover deep links, assets and gzip.

CI runs these checks with Playwright 1.62.1 and retains screenshots/receipts.
Set `CHROMIUM_EXECUTABLE` to reuse an installed Chromium locally. Continue to
run `tests/omnigent-browser.mjs` for the independent fallback form. It also
covers an offline host after a confirmed login: the plugin's issue hint in the
page language (issue contract, plugin 0.3.30+), the code-and-message fallback
of plugin 0.3.30, and **重新連線** (resume). A release also requires both
architecture image builds and real Supervisor acceptance; the compiled browser
test does not replace them.

The native browser suite also saves separate Omnigent and Paseo fixture
conversations through the real SDK, plus a stale `onboarding.json` naming the
Omnigent one, as images before 0.15.11 left it. On the homepage it checks that
neither conversation opens, that there is no floating Omnigent or Paseo link,
and that the retired `/omnigent/onboarding`, `/omnigent/launcher.js` and
`/paseo/launcher.js` routes return 404. It preserves all original transcript
bytes; Pi Web may append its normal runtime metadata when opening a saved
session. No prompt is submitted.

Binding happens only in Settings → Omnigent: no setup conversation is created
or opened, and the homepage does not navigate on its own (0.15.11 removed
that). These local fixtures prove the settings form, not the real plugin's
server login. Official HA QA must separately prove a fresh login in Settings
after a Supervisor reinstall, after first completing the original host's
upgrade/restart persistence tests.

The adapter intentionally accepts only the verified official 0.12.0 artifacts.
For another upstream release or rebuilt artifact, inspect SettingsPanel and
settings-navigation sources, update the compatibility hashes/anchors and all
asset references, and rerun the red/green browser test before changing the pin.

The network-disabled image gate also calls `paseo-native-runtime.mjs` from
`paseo-image-smoke.mjs`. It verifies the r3 receipt and both exact patched PID
modules, rejects a competing flock, and exercises acquire/update/refresh/release
in each compiled module copy. It checks PID inode preservation on update,
generation-aware release and the persistent guard inode. All writes use a
temporary private home; no daemon, provider, pairing or model call is started
by this native writer probe. The surrounding smoke checks settings-only
registration (no conversation is created), removal, the CLI version and the
fixed client.

## Version pins and the released Omnigent plugin

`cli-runtime/versions.json` is the only place the bundled Omnigent plugin
(version, release URL, sha256), Omnigent CLI, Claude Code and Codex versions
are written. The Dockerfile's `pins` stage splits it into one file per pin, the
CI test job reads it with `jq`, and the image smoke reads the image's copy at
`/usr/local/share/woow-ha-pi-agent/versions.json`. `tests/versions.test.mjs`
checks that the Claude/Codex package locks, the hash-locked Omnigent
requirements and the reminder patch's validated version agree with it, and
that the Dockerfile, CI and image checks do not repeat the values. Among the
build and test inputs, a plugin bump changes only this file; a CLI bump also
regenerates that CLI's lock. Pi Web stays pinned by the settings patch's
artifact hashes and Paseo by its Dockerfile ARGs.

`tests/omnigent-contract.test.mjs` drives the released plugin tarball through
this repository's seed, lifecycle and Settings bridge in about ten seconds,
before any image build: a fresh install, a same-path image upgrade that must
keep the confirmed login and receipts, and a switch between the image bundle
and a git install. Each add-on start runs `tests/omnigent-plugin-boot.mjs` in a
new process, which mirrors the launcher's package activation without the boot
worker; no server, login, network or Omnigent CLI is used.

```sh
url="$(jq -r .omnigentPlugin.url cli-runtime/versions.json)"
curl -fLsS "$url" -o /tmp/omnigent-plugin.tgz   # then check the sha256 pin
OMNIGENT_PLUGIN_TGZ=/tmp/omnigent-plugin.tgz PI_WEB_ROOT=/path/to/pi-web/package \
  node --test tests/versions.test.mjs tests/omnigent-contract.test.mjs
```

`PI_WEB_ROOT` is the official Pi Web package with the production dependencies
the CI step installs. A Pi Web session that loaded the extension from a
previous plugin root is outside this contract.

The Omnigent system-reminder patch in `patches/omnigent-reminder-patch/` is a
byte-identical copy of the PaaS image's (paas-odoo-ci
`pi-agent/omnigent-reminder-patch`). The image build applies it with `--strict`
and runs `patches/tests/omnigent-reminder-patch.test.py` against the patched
package; a different Omnigent version or a moved anchor fails the build.

## Local source-build context

PR image builds use the Store downloader from the workflow's pinned
`.sync-tooling/.addon-sync` checkout. `source-build-context.py` archives the
committed candidate at HEAD, generates the real local source context, and
checks every retained source file's bytes and permissions, build inputs,
manual boot policy, manifest and source lock. It also checks that an existing
context cannot be overwritten. The subsequent amd64/aarch64 jobs compile
these generated contexts; their JSON receipts are retained as CI artifacts.
Release builds keep the repository-root context.

```sh
python3 tests/source-build-context.py --tooling .sync-tooling/.addon-sync \
  --arch amd64 --destination /tmp/ha-local-source \
  --receipt /tmp/ha-local-source-receipt.json
```

The helper stages an unpublished candidate without touching the live catalog,
HAOS or Supervisor. Running it alone proves context integrity, not an image
build, installed add-on health, or current HA Store synchronization.

After a version is released and synchronized to the Store, manually run
`validate-local-source.yml` with its exact `version` and immutable
`store_commit`. The workflow verifies the public catalog digest, stable
Release/tag/source SHA, source archive and manifest checksums before invoking
the pinned Store downloader. It builds the newly generated amd64 context on
the official runner, loads the image locally and runs its real Pi/Omnigent
smoke with networking disabled. It never pushes an image or installs an add-on.
The whole job is bounded to 45 minutes and the runtime check to 5 minutes;
source provenance and runtime logs are retained as artifacts. Normal PR build
cache scopes remain intact. A requested version absent from the specified
Store commit fails before any image build.

Two scripts, kept independent so you can run whichever part you care about.

## `smoke-providers.sh` — do the API keys actually work?

Hits the two upstream providers with a tiny completion request. Catches out-of-balance / revoked / wrong-region keys **before** a user tries to chat in pi-web and gets an opaque 401 / 429.

```bash
GLM_API_KEY=...  MINIMAX_API_KEY=...  ./tests/smoke-providers.sh
```

- `GLM_API_KEY` is required.
- `MINIMAX_API_KEY` is optional — the MiniMax check is skipped if unset (matches the add-on's behaviour).
- MiniMax check also asserts `<think>…</think>` shows up inline in the response, which is what `thinkingFormat: "deepseek"` in `models.json` relies on to surface reasoning tokens.

## `smoke-addon.sh` — is the deployed add-on healthy?

Talks to a live HA Supervisor via a long-lived token. Verifies four things:

1. Supervisor reports the add-on `installed` + `state=started` + no update pending.
2. Log tail contains the bootstrap lines proving `models.json` was seeded (GLM required, MiniMax optional).
3. Ingress `"/"` returns HTML with `/_next/…` paths rewritten to include the ingress prefix — this is the nginx sub_filter proving it works.

```bash
HA_URL=https://your-ha.example.com \
HA_TOKEN=eyJ...  \
ADDON_SLUG=b9cf5676_woow_ha_pi_agent \
./tests/smoke-addon.sh
```

Long-lived token: HA UI → your user profile → **Long-lived access tokens** → **Create token**.
