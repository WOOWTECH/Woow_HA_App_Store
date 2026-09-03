# HAOS BYOK OpenDesign Add-on Implementation Plan

**Goal:** Deliver a public, multi-architecture Home Assistant add-on for OpenDesign 0.21.1 with HA Ingress, browser-local BYOK, persistent `/data` state, and headless HTML/PDF/image/screenshot-PPTX exports without local AI CLIs.

## Task 1 — Repository and add-on contract

Create the standalone add-on metadata and documentation:

- `repository.yaml`
- `config.yaml`
- `build.yaml`
- `README.md`, `README_zh-TW.md`, `DOCS.md`, `CHANGELOG.md`, `LICENSE`

Declare only amd64/aarch64, ingress-only networking, a watchdog, cold backup, `/data` persistence, and architecture-specific GHCR image names. Document browser-local key semantics and the screenshot-only PPTX scope.

## Task 2 — Runtime image and process lifecycle

Create a Dockerfile derived from pinned `ghcr.io/nexu-io/od:0.21.1`. Add nginx, Chromium, Playwright, required CJK/emoji fonts, and only renderer/runtime dependencies. Add a PID-1 launcher that:

- prepares `/data/opendesign`;
- starts OpenDesign on loopback through the custom headless entry;
- starts nginx on the ingress port;
- forwards termination and fails when either process exits.

Do not install or mount any local AI CLI.

## Task 3 — Headless export adapter

Implement a Node Playwright renderer and OpenDesign launcher. Inject `desktopSlideRenderer` and a PDF exporter into `startServer()`. Support:

- ordinary full-page capture;
- viewport pagination for PDF;
- deck slide capture;
- one-slide capture;
- vertically stitched deck image;
- PNG and JPEG;
- screenshot PDF/PPTX assembly through OpenDesign.

Reject editable PPTX clearly. Constrain output to the supplied absolute output directory and use bounded render timeouts.

## Task 4 — HA Ingress adaptation

Implement nginx configuration that:

- validates `X-Ingress-Path`;
- rewrites initial root-relative asset URLs;
- injects a prefix shim before application code;
- handles fetch, XHR, EventSource, WebSocket, history, and dynamic asset URLs;
- disables buffering/compression for streamed API responses;
- forwards only to loopback OpenDesign;
- supports large artifact uploads and downloads.

Add test fixtures that verify rewrites without requiring a live HA instance.

## Task 5 — CI and verification

Add GitHub Actions for:

- static validation and tests on pull requests/pushes;
- amd64/aarch64 Buildx builds;
- GHCR publication on main/tags;
- pinned image/version labels.

Add tests for metadata, forbidden host/CLI coupling, renderer syntax/contract helpers, ingress rewriting, and expected image contents. Build locally when container tooling is available; otherwise require CI build evidence before claiming live-image success.

## Task 6 — Main HA App Store integration

Add the add-on under `WOOWTECH/Woow_HA_App_Store` using that repository's established layout and release contract. Keep the standalone repository canonical, avoid duplicated mutable implementation where possible, validate Store metadata, commit, and push both repositories.

## Acceptance contract

- Repository is public at `https://github.com/WOOWTECH/Woow_ha_opendesign_add_on`.
- Add-on is discoverable after adding the standalone repository URL and through `Woow_HA_App_Store`.
- No LAN port is published.
- No host path, external volume, local AI CLI, or provider secret option exists.
- OpenDesign reports healthy through ingress.
- BYOK can be configured in the OpenDesign UI and remains browser-local.
- Projects survive add-on restart and HA backup/restore.
- HTML, ZIP, PDF, PNG/JPEG, and screenshot PPTX downloads work.
- amd64 and aarch64 images build and publish to GHCR.
