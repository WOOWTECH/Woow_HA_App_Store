# HAOS BYOK OpenDesign Add-on Design

**Date:** 2026-09-03  
**Repository:** `WOOWTECH/Woow_ha_opendesign_add_on`

## Goal

Package OpenDesign for Home Assistant OS as an ingress-only add-on. AI execution uses OpenDesign's native BYOK API mode. The add-on must not install, mount, or discover host AI CLIs. Durable OpenDesign state belongs under the add-on `/data` mount. Users configure provider keys in OpenDesign itself; the upstream browser-local key behavior is preserved.

## Confirmed product decisions

- Public standalone GitHub repository, also published through `WOOWTECH/Woow_HA_App_Store`.
- Pin upstream `ghcr.io/nexu-io/od:0.21.1`; never follow `latest` implicitly.
- Support `amd64` and `aarch64`.
- HA Ingress and sidebar only; publish no LAN port.
- Keep the upstream Local CLI settings page, but install and mount no local AI CLI.
- Preserve upstream BYOK storage: provider keys remain in browser `localStorage`, per browser, and are not included in HA backups.
- Include reliable HTML, ZIP, PDF, PNG/JPEG, and screenshot-based PPTX downloads. Editable PPTX is outside scope.

## Chosen architecture

Use a thin image derived from the pinned upstream OpenDesign container. Add nginx for HA Ingress adaptation, system Chromium, Playwright, CJK/emoji fonts, and a small Node launcher that imports OpenDesign's exported `startServer()` function and injects a headless slide renderer.

The add-on contains two long-running processes in one Supervisor-owned container:

1. OpenDesign binds only to `127.0.0.1:7456`.
2. nginx listens on the fixed HA ingress port and proxies to OpenDesign.

A PID-1 launcher starts both, forwards termination, and exits if either child exits. HA Supervisor then owns restart policy.

## Data flow

1. The browser enters through authenticated HA Ingress.
2. nginx validates `X-Ingress-Path`, rewrites root-relative static paths, and injects a small browser shim for root-relative API, SSE, WebSocket, navigation, and dynamic asset URLs.
3. nginx forwards requests to loopback OpenDesign.
4. BYOK chat calls travel from browser configuration through the OpenDesign daemon proxy to the selected provider.
5. OpenDesign writes projects, SQLite data, app configuration, connector data, and generated artifacts beneath `OD_DATA_DIR=/data/opendesign`.
6. Visual export routes call the injected Playwright renderer. The renderer loads the artifact with a scoped loopback base URL, waits for fonts/images, captures page or slide images, and returns only files beneath the daemon-created export scratch directory. OpenDesign assembles screenshot PDF/PPTX itself.

## Security boundaries

- No host networking, host paths, shared external volumes, glibc mounts, or sibling Pi deployment.
- No Claude, Codex, OpenCode, Pi, or other local AI CLI package is added.
- OpenDesign binds to loopback and is reachable only through the ingress nginx process.
- The externally reachable add-on port is the HA Ingress endpoint; daemon API authentication may be disabled only on the loopback hop.
- The ingress prefix header is accepted only when it matches Home Assistant's opaque ingress-path format.
- Provider secrets are never accepted as add-on options and must not be printed in logs.
- Renderer navigation is limited to artifact HTML supplied by OpenDesign; its output paths are constrained by OpenDesign's existing export contract.

## Failure handling

- If OpenDesign or nginx exits, the launcher terminates the peer and exits non-zero so Supervisor restarts the add-on.
- Health checks use OpenDesign's `/api/health` through nginx.
- Renderer timeouts return a structured failed renderer result instead of hanging the daemon.
- Unsupported editable-PPTX requests return a clear message directing users to screenshot mode.
- Missing Chromium fails image build validation rather than downloading a browser at first boot.

## Validation

- Static checks for YAML, shell, nginx configuration, and JavaScript syntax.
- Container smoke test: health endpoint, no detected local AI CLI, persistent `OD_DATA_DIR`, and ingress-prefixed HTML/API requests.
- Renderer contract tests for a page, a multi-slide deck, image stitching, PDF, and screenshot PPTX.
- Multi-architecture image builds for amd64/aarch64.
- Live HAOS acceptance: sidebar launch, refresh/navigation, BYOK connection test and generation, SSE completion, state across restart, HTML/PDF/image/PPTX downloads, and snapshot restore.

## Residual risks

- HA Ingress rewriting is coupled to the pinned OpenDesign web build and requires regression testing on every upstream bump.
- Browser-local BYOK keys are intentionally per-browser and absent from HA backups.
- Chromium materially increases image size and peak memory use.
- Upstream exposes local runtime choices even though none are installed; this is intentional to avoid maintaining a frontend fork.
