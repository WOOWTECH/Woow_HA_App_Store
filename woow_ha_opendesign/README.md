# Woow HA OpenDesign Add-on

OpenDesign **0.21.1**, packaged as a standalone Home Assistant add-on for `amd64` and `aarch64`.

- Home Assistant Ingress/sidebar access only; no LAN port is published.
- OpenDesign binds to `127.0.0.1`; unprivileged nginx fronts it on the Supervisor ingress port.
- HA Persistent BYOK Profiles use the bundled Pi Local CLI. Keys are stored in `/data/opendesign/credentials/byok-profiles.json`, readable by HA administrators, and included in cold backups.
- OpenDesign state is persisted under `/data/opendesign` and is included in cold backups.
- System Chromium, Playwright and Noto CJK/emoji fonts provide headless HTML rendering.
- Downloads supported by the pinned upstream application: standalone HTML, ZIP, screenshot PDF, PNG/JPEG, and screenshot-based PPTX. **Editable PPTX is unsupported** and returns a clear error.
- Pi `0.84.4` is bundled at an exact locked version. Profiles support Anthropic, OpenAI, Google, and OpenAI-compatible endpoints; the active profile/model applies to new runs.

[繁體中文](README_zh-TW.md) · [Add-on documentation](DOCS.md)

## Install

1. In Home Assistant, open **Settings → Add-ons → Add-on Store → Repositories**.
2. Add `https://github.com/WOOWTECH/Woow_ha_opendesign_add_on`.
3. Install **Woow HA OpenDesign**, start it, and open **OpenDesign** from the sidebar.
4. In **Settings**, create a **HA Persistent BYOK Profile**, select it as active, then use Pi Local CLI for new runs.

There are no add-on configuration options and no host directory mappings.

## Architecture

```text
browser → HA authenticated ingress → nginx :8099 → OpenDesign 127.0.0.1:7456
                                                   ↘ /data/opendesign
                                                   ↘ system Chromium renderer
```

nginx validates `X-Ingress-Path`, rewrites initial root-relative URLs, and injects early browser shims covering fetch, XHR, EventSource, WebSocket, history, workers, dynamically inserted asset URLs, and the two web-mode export gaps. In HA Ingress the PDF action is redirected from the desktop-JSON endpoint to the binary screenshot-PDF endpoint, while PNG/JPEG saves call the daemon's headless image endpoint. Buffering and upstream compression are disabled to preserve streams and allow response rewriting.

A root PID-1 launcher prepares Home Assistant's root-owned `/data` mount, then uses `su-exec` to run nginx and OpenDesign as upstream `open-design` UID/GID 1001. It forwards termination and stops the peer if either process exits; shutdown sends TERM, waits at most five seconds, then sends KILL and reaps. nginx keeps its PID and temporary files under `/tmp`.

## Development and validation

```sh
./tests/run.sh
```

The local suite requires Node.js and Python 3 with PyYAML, but not Docker. It validates metadata, forbidden host/runtime coupling, JavaScript and shell syntax, renderer/security helpers, export bridges, ingress rewrite fixtures, and the workflow's least-privilege/immutable-release policy. CI additionally builds an amd64 image and runs `tests/container-smoke.sh` before architecture builds: a real Chromium session traverses a Supervisor-style path-stripping proxy and exercises the injected fetch/XHR/SSE/WebSocket and PDF/image bridges, alongside health, persistence, renderer, and HTTP export checks. Pull-request and main-branch architecture builds never authenticate to GHCR and run with `contents: read` only. `amd64` and `aarch64` images are published only by a `v<config-version>` Git tag after a release preflight proves both version tags are unused. Published version tags are immutable; if a release publishes only one architecture, recovery requires bumping `config.yaml` and creating a new matching tag rather than overwriting the partial release.

## Security notes

Access control is delegated to authenticated HA Ingress. All HA administrators with access to this add-on may view and manage complete profile keys. Provider calls leave the add-on for the selected provider; cold-backup access is equivalent to provider-key access.

Renderer HTML is model-generated, so Chromium applies a request policy before every load: it allows `data:`, `blob:`, `about:`, the exact OpenDesign loopback origin used for project assets, and public HTTP(S) addresses only after DNS/IP validation and pinned connection. It blocks all WebSockets plus Supervisor, metadata/link-local, RFC1918, CGNAT, other loopback ports, and IPv6 private/link-local destinations. Render jobs are serialized and bounded by an absolute deadline, slide/pixel/output-byte budgets, and a shared remote-resource semaphore that covers DNS validation through pinned fetch completion, plus aggregate remote-byte limits. System fonts keep CJK/emoji capture independent of remote font CDNs.

## Upstream and license

The runtime derives from `ghcr.io/nexu-io/od:0.21.1`. The Dockerfile and release/CI builds pin its multi-architecture digest. Home Assistant's local add-on builder does not accept digest syntax in `build.yaml`, so that development-only path is pinned to the `0.21.1` tag instead. OpenDesign has its own upstream licensing and notices. The add-on packaging and integration code in this repository is MIT licensed; see [LICENSE](LICENSE).
