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
checksum-verified public 0.1.9 client and cover deep links, assets and gzip.

CI runs these checks with Playwright 1.62.1 and retains screenshots/receipts.
Set `CHROMIUM_EXECUTABLE` to reuse an installed Chromium locally. Continue to
run `tests/omnigent-browser.mjs` for the independent fallback form. A release
also requires both architecture image builds and real Supervisor acceptance;
the compiled browser test does not replace them.

The native browser suite also saves separate Omnigent and Paseo fixture
conversations through the real SDK. On a fresh untouched homepage it checks
zero-click exact Omnigent selection and visible setup instructions on desktop
and phone. It preserves all original transcript bytes; Pi Web may append its
normal runtime metadata when opening a saved session. No prompt is submitted.

Auto-open is restricted to a registered, active, enabled plugin with unfinished
setup. A small same-origin GET exposes only that eligibility and the saved ID;
the existing token requirement for settings and mutations is unchanged. Eligibility
reads only regular, same-UID, 0600 local state/onboarding files; it never calls
runtime status, dependency probes, Python, catalog or a remote Omnigent server.
Absent state during registered cold boot may wait but cannot open a stale
onboarding until enabled state is saved. Unreadable, malformed, unknown or
completed state stops immediately. The
client confirms the ID exists in the session summary catalog before navigating.
Explicit URLs, saved tab/workspace/terminal selection, drafts and interaction
(including before hydration) take precedence. Cold boot may retry for at most
30 seconds/30 attempts, stopping on disable, removal, completion or interaction.
A per-tab, Ingress-scoped marker prevents Back/reload loops. A missed deadline
leaves the homepage and its ordinary sidebar navigation usable.

These local fixtures prove selection and instruction rendering, not the real
plugin's interactive wizard. Official HA QA must separately prove the initial
blank URL input/setup prompt in a fresh browser after Supervisor reinstall,
after first completing the original host's upgrade/restart persistence tests.

The adapter intentionally accepts only the verified official 0.12.0 artifacts.
For another upstream release or rebuilt artifact, inspect SettingsPanel and
settings-navigation sources, update the compatibility hashes/anchors and all
asset references, and rerun the red/green browser test before changing the pin.

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
