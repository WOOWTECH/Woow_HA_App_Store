# HA Omnigent image integration plan

**Goal:** Ship addon 0.15.0 with verified Omnigent plugin 0.3.11, offline startup dependencies, persistent opt-out, and usable HA Ingress settings while retaining Pi Web 0.12.0.

**Architecture:** Build the release tarball with SHA-256 verification and a separate Python 3.12/Omnigent 0.16.0 layer. A Node launcher seeds native package settings once, creates the plugin's setup conversation, watches its native lifecycle, and serves a small settings screen over a private Unix socket behind existing Supervisor-only nginx ingress. Use the plugin's safe DTO bridge; never apply the 0.10 Next.js patch to 0.12.

**Tech Stack:** Node 22, existing Pi SDK, Python 3.12, uv, nginx, Docker Buildx amd64/aarch64.

1. Add image bundle/dependency pins and build-time checks to Dockerfile. No runtime engine installs.
2. Add `pi-omnigent-ha` seed/loader/launcher, safe API bridge and responsive form. Respect disabled/removed/external packages and existing state. Persist no login inputs.
3. Wire ingress paths and startup. Preserve Pi session `PI_CODING_AGENT_DIR` through any inherited environment script.
4. Add behavioral lifecycle, actual SDK session, wrapper, HTTP security, ingress and browser-form tests. Run existing regression suite.
5. Bump config to 0.15.0, document settings entry point and compatibility limits, update CI for image smoke checks on both architectures.
6. Push release branch and open PR. Verify actual CI image builds. Do not merge; parent coordinates release and HA Store synchronization.

Commands: `node --test tests/omnigent-ha.test.mjs`; `node tests/shim-routes.mjs`; `node tests/shared-agent-state.mjs`; `node tests/cli-wrappers.mjs`; `node tests/haos-network-contract.mjs`; `node tests/cli-image-layers.mjs`; `node --test patches/tests/chatgpt-device-id.test.mjs`.

No provider credentials, transcripts or current Omnigent server identity are included in the image or fixtures.
