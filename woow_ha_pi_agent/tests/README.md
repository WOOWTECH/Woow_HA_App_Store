# Smoke tests

## HA native Omnigent settings

`patches/tests/omnigent-settings.test.mjs` requires `PI_WEB_ROOT` to point at a
source-built `@agegr/pi-web@0.12.0` package produced from the pinned tag, lock
and Next 16.4.6 patch in `patches/pi-web-source/build-pins.json`. It tests the
actual compiled client/SSR files and flight references, repeated application,
and refusal of changed/ambiguous artifacts before any write.

```sh
PI_WEB_ROOT=/path/to/pristine/package node --test patches/tests/omnigent-settings.test.mjs
node patches/patch-omnigent-settings.mjs /path/to/runtime/package
PI_WEB_ROOT=/path/to/runtime/package EVIDENCE_DIR=/path/to/test-evidence \
  PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs \
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
paid model responses or real HA Supervisor ingress. So is Agent Connect: the
Agent Connect page must link the official site of the saved target in a new tab
(answered locally, no network), hand out only the exact pairing link, and the
retired `/paseo-web` paths (the old open link with its trailing slash included)
must get nginx's own fixed 404 page, from neither Pi Web nor the Paseo bridge.

CI runs these checks with Playwright 1.62.1 and retains screenshots/receipts.
Set `CHROMIUM_EXECUTABLE` to reuse an installed Chromium locally. Continue to
run `tests/omnigent-browser.mjs` for the independent fallback form. It also
covers an offline host after a confirmed login: the plugin's issue hint in the
page language (issue contract, plugin 0.3.30+), the code-and-message fallback
of plugin 0.3.34, and **重新連線** (resume). `tests/paseo-browser.mjs` is the same
independent check for the Agent Connect page (no nginx, no Pi Web): official-site
links in new tabs, a pairing link per target, a target switch that only pairs
after a restart, and `/paseo-web` answering 404, on desktop and phone widths.
A release also requires both architecture image builds and real Supervisor
acceptance; the compiled browser test does not replace them.

```sh
PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs CHROMIUM_EXECUTABLE=/path/to/chrome \
  node tests/paseo-browser.mjs
```

`tests/paseo-launch.test.mjs` runs `rootfs/usr/local/lib/pi-paseo-ha/launch.mjs`, the
file the s6 `pi-web` service executes, from a copy of the rootfs layout with a
stand-in for the Omnigent launcher: it must serve `/paseo/setup` on its private
socket, start its child by its own location, restore the lifecycle even when
registration fails, and stop inside its 5 s budget. `node --check` only parses
that file; a renamed export passes every unit test and then fails at link time.
`omnigent-image-smoke.mjs` starts the same entry point in the built image with
the real Omnigent launcher and Pi Web (`PI_PASEO_AUTO_SETUP=false`, so no
daemon), reads `/paseo/setup` and `/api/paseo` from `paseo-ha.sock`, and fails
on a SyntaxError, a missing module or a failed-start line in the launcher log.

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
`paseo-image-smoke.mjs`. It verifies the pinned runtime receipt, both CLI/server versions and both exact
patched PID modules, rejects a competing flock, and exercises acquire/update/refresh/release
in each compiled module copy. It checks PID inode preservation on update,
generation-aware release, previous-boot PID recovery and the persistent guard
inode. A controlled process-birth fixture exercises the frozen plugin's proof-based
stale recovery, refuses missing proof and a live incarnation, and checks retained
server-ID, daemon-key and config bytes. It does not force kernel PID reuse. All writes use a
temporary private home; no daemon, provider, pairing or model call is started
by this native writer probe. The surrounding smoke checks settings-only
registration (no conversation is created), removal, the CLI version, that the
image holds no bundled web client and that the plugin's status has none, and
that agent collaboration is off. It reads the expected Agent Connect and Paseo
versions from the image's `versions.json`.

`tests/paseo-runtime-dir.test.mjs` is part of the required Node CI job. It covers
fresh HOME, obsolete/incomplete saved releases, ready saved releases, explicit
plugin versions and fallback when neither runtime is ready or discovery fails.
The launcher tests cover explicit `PI_PASEO_RUNTIME_DIR` overrides; the frozen
contract asks the actual plugin, and the image smoke compares an old saved
release with the image's actual ready runtime. Selection must leave saved
runtime contents and daemon identity unchanged.

On hosts where mutation testing is prohibited, run the launcher suite with
`node --test --test-skip-pattern='a launcher that cannot link' tests/paseo-launch.test.mjs`.
This excludes the deliberate broken-import mutation; the actual launcher,
shutdown, override and named-import checks still run. Full CI retains that test.

## Version pins and the released Omnigent plugin

`cli-runtime/versions.json` is the only place the bundled Omnigent plugin and
Agent Connect (version, vendored archive, sha256, source commit; for Agent
Connect also the Paseo daemon version and the runtime revision), Omnigent CLI,
Claude Code and Codex versions are written. The Dockerfile's `pins` stage splits
it into one file per pin, the CI test job reads it with `jq`, and the image
smoke reads the image's copy at `/usr/local/share/woow-ha-pi-agent/versions.json`.
`tests/versions.test.mjs` checks that the Claude/Codex package locks, the
hash-locked Omnigent requirements, the reminder patch's validated version and
`candidate-packages/manifest.json` agree with it, that each vendored archive has
the pinned hash (and the Agent Connect one the pinned version, no bundled web
client and a runtime revision matching its lockfile), and that the Dockerfile,
CI and image checks do not repeat the values. A plugin bump changes only the
archive in `candidate-packages/` (exactly one Agent Connect archive; the
Dockerfile takes it by pattern), its entry in this file and its entry in
`manifest.json`; a CLI bump also regenerates that CLI's lock. Pi Web stays
pinned by the settings patch's artifact hashes.

`tests/omnigent-contract.test.mjs` drives the released plugin tarball through
this repository's seed, lifecycle and Settings bridge in about ten seconds,
before any image build: a fresh install, a same-path image upgrade that must
keep the confirmed login and receipts, and a switch between the image bundle
and a git install. Each add-on start runs `tests/omnigent-plugin-boot.mjs` in a
new process, which mirrors the launcher's package activation without the boot
worker; no server, login, network or Omnigent CLI is used.

`tests/paseo-contract.test.mjs` does the same for Agent Connect: the archive's
real `status()` (no web client, `agentCollaboration` off by default), a target
save that leaves the plugin's saved `agentCollaboration` and name alone, and the
pairing links its own code builds for the three targets against this
repository's validators. It writes only to a temporary data directory and starts
no daemon.

```sh
OMNIGENT_PLUGIN_TGZ="$(jq -r .omnigentPlugin.archive cli-runtime/versions.json)" PI_WEB_ROOT=/path/to/pi-web/package \
  node --test tests/versions.test.mjs tests/omnigent-contract.test.mjs
PASEO_PLUGIN_TGZ="$(jq -r .agentConnect.archive cli-runtime/versions.json)" PI_WEB_ROOT=/path/to/pi-web/package \
  node --test tests/paseo-contract.test.mjs
```

`PI_WEB_ROOT` is the pinned, source-built Pi Web package with the production
dependencies the CI step retains. A Pi Web session that loaded the extension from a
previous plugin root is outside this contract.

The Omnigent system-reminder patch in `patches/omnigent-reminder-patch/` is a
byte-identical copy of the PaaS image's (paas-odoo-ci
`pi-agent/omnigent-reminder-patch`). The image build applies it with `--strict`
and runs `patches/tests/omnigent-reminder-patch.test.py` against the patched
package; a different Omnigent version or a moved anchor fails the build.

## Smart Tasks source and image checks

The frozen Agent Connect archive carries `scripts/verify-smart-tasks.mjs`.
It checks the pinned Better Paseo payload against a prepared Paseo runtime,
including Tasks-on/chat-off defaults, retained user preference, zh-TW labels,
chunk exports, saved state after a server reload, and disabled self-update.
The HA image smoke runs the verifier against the actual baked runtime.
For an installed local runtime:

```sh
node path/to/agent-connect/scripts/verify-smart-tasks.mjs \
  /path/to/paseo-runtime/releases/0.17.4-r2-a651f42711da
```

This is a source/runtime contract check. Two-brand browser acceptance and the
native amd64/aarch64 image and Supervisor upgrade checks remain separate.

## The Paseo runtime is two image layers

CI's "Enforce transport-safe image layers" step (`tests/assert-image-layer-sizes.mjs`)
rejects any new or changed layer over 256 MiB compressed, the size at which pulls
on slow hosts ended in EOF. It runs on pushes to `main`, after the merge, never on a
PR, so a layer that grows past the limit is found only when it is too late to
change the PR. The managed Paseo runtime in `/opt/woow/paseo-runtime` is the
heaviest single thing in the image, and most of it is the Claude Agent SDK's
platform binary (`node_modules/@anthropic-ai/claude-agent-sdk-linux-<arch>`),
which grows with the SDK. Measured on 2026-11-25 with
`tests/measure-paseo-runtime-layers.mjs` (`tar | gzip -6`, musl SDK removed):

| Paseo | one layer | layer a (all but `@anthropic-ai`) | layer b (`@anthropic-ai`) |
| --- | --- | --- | --- |
| 0.11.2 | 162.3 MiB (63% of the limit) | 63.9 MiB | 98.4 MiB |
| 0.17.4 | 235.6 MiB (92%) | 71.1 MiB | 164.5 MiB (64%) |

So the runtime is two layers. Docker `COPY` cannot exclude a subdirectory (copying
the parent and the subdirectory would store the files twice), so
`patches/split-paseo-runtime.mjs` runs in the builder RUN that installs the runtime
and makes two trees below `/opt/woow/paseo-runtime-layers/{a,b}` that keep the full
destination path; the final stage copies each with a plain
`COPY --from=paseo-builder <tree>/ /`. The trees are hard links to the installed
files (plus recreated symlinks and directories), so every file keeps its inode,
bytes, mode, owner and mtime, and nothing is copied. Every file, symlink and
directory must end up in exactly one layer (only the directories above
`@anthropic-ai` are in both); the script checks that against a listing taken
before, refuses anything else and removes its output, and also refuses a hard link
that would straddle the layers. It takes the release directory from the plugin's
own runtime layout, knows no version or revision, and, run as a command, asks the
plugin whether the runtime is ready before the split and again with both layers
merged.

`tests/paseo-runtime-layers.test.mjs` covers it with a synthetic runtime (exact
coverage, inodes, modes, owners, mtimes, symlinks, the self-check refusing bad
output, refusals, idempotence, the command) and checks the Dockerfile: one RUN
builds and splits, the final stage has exactly the two plain copies in this
order, no wildcard or variable (the Store's source-build check refuses
substitution). `tests/paseo-image-smoke.mjs` checks in the built image that the
SDK package of layer b is there. To measure a lock or an installed runtime
(opt-in; it runs `npm ci`, so it needs the registry):

```sh
node tests/measure-paseo-runtime-layers.mjs --lock /path/to/runtime   # package.json + package-lock.json
node tests/measure-paseo-runtime-layers.mjs --archive candidate-packages/woowtech-pi-paseo-<version>.tgz
node tests/measure-paseo-runtime-layers.mjs --runtime /path/to/installed/paseo-runtime
```

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
