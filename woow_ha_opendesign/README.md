# Woow HA OpenDesign Add-on

OpenDesign **0.24.1** from the shared WoowTech OpenDesign core image (the same build the WOOW PaaS runs), packaged as a standalone Home Assistant add-on for `amd64`.

- Home Assistant Ingress/sidebar access only. The one declared LAN port is the built-in MCP server's `8081/tcp`, unmapped unless you map it.
- OpenDesign binds to `127.0.0.1`; unprivileged nginx fronts it on the Supervisor ingress port.
- OpenDesign native API BYOK stores provider, model, and API-key settings only in each administrator browser's local storage. Keys are not written to `/data`, add-on options, logs, or Home Assistant backups.
- OpenDesign project and application state is persisted under `/data/opendesign` and is included in cold backups.
- System Chromium, Playwright and Noto CJK/emoji fonts provide headless HTML rendering.
- Downloads supported by the pinned upstream application: standalone HTML, ZIP, screenshot PDF, PNG/JPEG, and screenshot-based PPTX. **Editable PPTX is unsupported** and returns a clear error.
- The native **Paseo** plugin opens a protected setup page through HA Ingress. Its managed runtime, login state and onboarding conversation survive add-on restarts; manual stop remains stopped. See [setup and persistence](DOCS.md#paseo-setup-and-persistence).
- The core image provides Claude Code `2.1.296`, Codex CLI `0.162.1`, Pi Coding Agent `1.1.0`, and OpenCode `1.18.33` (OpenDesign's native `byok-opencode` API runtime). The add-on build asserts each version as UID 1001; these agent CLIs do not require a first-use download.
- WoowTech changes from the core: white-label UI, Traditional Chinese (zh-TW) locale fixes, export fixes, the bundled `woowtech-brand` skill, and no `brainstorming` skill.
- **Omnigent 0.2.10 candidate:** restores the native plugin GUI and daemon-managed host with fresh login and private `/data` persistence. An isolated HA install and restart passed; the first-run settings route and connected GUI conversation still require a new core candidate and acceptance (see [setup, migration and verification](DOCS.md#omnigent-029-candidate)).
- OpenDesign owns installed plugins and skills in its persistent data directory. Install them from OpenDesign's **Plugins** page; the daemon stages the selected skill into the project and supplies it to whichever installed agent runtime runs that project.
- A Home Assistant authenticated **CLI Terminal** (a built-in plugin on OpenDesign's **Plugins** page, at `<Ingress>/console/`) lets you complete interactive logins for Claude Code, Codex, and Pi. OpenCode's additional model providers can be configured in OpenDesign **Settings → API providers**.
- A **built-in OpenDesign MCP server** (replacing the separate *Woow OpenDesign MCP Server* add-on) serves MCP clients on `8081/tcp` with a Bearer token, or `/private_<token>/mcp` for Claude.ai connectors. It offers the same 15 tools as the WOOW PaaS OpenDesign MCP, all on by default, including the writers `create_project`, `send_message` (they run an OpenDesign agent) and `delete_project`. Its administration (token, tool permissions) is the built-in **MCP Server** plugin on the **Plugins** page, reachable only through HA Ingress. See [DOCS.md](DOCS.md#built-in-mcp-server).

[繁體中文](README_zh-TW.md) · [Add-on documentation](DOCS.md)

## Install

1. In Home Assistant, open **Settings → Add-ons → Add-on Store → Repositories**.
2. Add `https://github.com/WOOWTECH/Woow_ha_opendesign_add_on`.
3. Install **Woow HA OpenDesign**. On its **Info** tab turn on **Watchdog** (Home Assistant leaves it off for new add-ons; without it the add-on stays stopped after an internal process exits), then start it and choose **Open Web UI**. In the 0.2.10 candidate this opens **Plugins** directly.
4. In **Settings**, configure API BYOK with your provider, model, and key. Those settings remain local to that browser.
5. Open **Local AI → Rescan** after installation or image updates. In OpenDesign, open **Plugins**, install the workflow you want, then select it in a project. Its Skills and plugin context are resolved by the native OpenDesign daemon for Claude Code, Codex, Pi, or OpenCode runs.
6. In OpenDesign open **Plugins → Expert suites → Personal** and click **Open** on the built-in **CLI Terminal** plugin; it opens the authenticated terminal in a new tab. Run `claude` and `/login`, `codex login --device-auth`, or `pi` and use its `/login` command. The terminal uses the persistent `/data/opendesign/home` profile. OpenCode API providers can instead be entered in **Settings → API providers**.
7. On the same **Plugins → Expert suites → Personal** page, open **Paseo** for its connection setup, provider login, model selection and service controls. See [Paseo setup and persistence](DOCS.md#paseo-setup-and-persistence).
8. In the 0.2.10 candidate, open **Plugins → Omnigent → Open → Configure** and enter the server URL, username and password. Complete provider sign-in for each installed engine you want to use. See [Omnigent setup](DOCS.md#omnigent-029-candidate).

There are no add-on configuration options and no host directory mappings.

See [agent and plugin setup](docs/shared-agent-capabilities.md) for how OpenDesign shares installed plugins/Skills across agent runtimes and how login/configuration is persisted.

## Architecture

```text
browser → HA authenticated ingress → nginx :8099 → OpenDesign 127.0.0.1:7456
                                        ↘ loopback ttyd :7681 (CLI login TTY)
                                        ↘ /mcp-admin/ → MCP admin (Unix socket, Supervisor peer only)
MCP client → :8081 (Bearer or /private_<token>/mcp) → built-in MCP gateway (UID 10001) → OpenDesign 127.0.0.1:7456
                                        ↘ /data/opendesign
                                        ↘ system Chromium renderer
```

nginx validates `X-Ingress-Path`, rewrites initial root-relative URLs, and injects early browser shims covering fetch, XHR, EventSource, WebSocket, history, workers, dynamically inserted asset URLs, and the two web-mode export gaps. In HA Ingress the PDF action is redirected from the desktop-JSON endpoint to the binary screenshot-PDF endpoint, while PNG/JPEG saves call the daemon's headless image endpoint. Buffering and upstream compression are disabled to preserve streams and allow response rewriting.

A root PID-1 launcher prepares Home Assistant's root-owned `/data` mount, safely removes the withdrawn legacy `/data/opendesign/credentials` path without following symlinks, then uses `su-exec` to run OpenDesign and loopback-only ttyd as `open-design` UID/GID 1001, nginx as `ha-ingress` (1002), and the built-in MCP server, which drops itself to `mcp` (10001). No child inherits the Supervisor token. The terminal is reachable only through HA-authenticated Ingress and starts a login shell in the persistent home directory. Every supervised process is required: when one exits, the launcher stops the others and exits so Supervisor restarts them together (only while **Watchdog** is on; measured: back and healthy in about 11 s, while with Watchdog off the add-on stays in `error`); nginx keeps its PID and temporary files under `/tmp`.

## Development and validation

```sh
./tests/run.sh
```

The local suite requires Node.js and Python 3 with PyYAML, but not Docker. It validates metadata, forbidden host/runtime coupling, JavaScript and shell syntax, renderer/security helpers, export bridges, ingress rewrite fixtures, and the workflow's least-privilege/immutable-release policy. CI additionally builds an amd64 image and runs `tests/container-smoke.sh` before architecture builds: a real Chromium session traverses a Supervisor-style path-stripping proxy and exercises the injected fetch/XHR/SSE/WebSocket and PDF/image bridges, alongside health, persistence, renderer, and HTTP export checks. Pull-request and main-branch builds never authenticate to GHCR and run with `contents: read` only. A release is merging a pull request that bumps the `config.yaml` version into `main` (pushing a Git tag does not publish anything, because it would skip the pull request checks). The first `main` run for a version without a Release passes a release preflight proving the image version tag is unused, publishes the `amd64` image, and then the App Store's shared workflow creates the `v<version>` tag and Release on that commit; later `main` runs leave a released version alone. Published version tags are immutable; recovery from a failed release requires another pull request that bumps `config.yaml` rather than overwriting the image.

## Security notes

Access control is delegated to authenticated HA Ingress. API BYOK provider, model, and key values stay in the administrator's browser local storage; they are not shared between browsers and are excluded from Home Assistant backups. Provider calls leave the add-on for the selected provider.

Renderer HTML is model-generated, so Chromium applies a request policy before every load: it allows `data:`, `blob:`, `about:`, the exact OpenDesign loopback origin used for project assets, and public HTTP(S) addresses only after DNS/IP validation and pinned connection. It blocks all WebSockets plus Supervisor, metadata/link-local, RFC1918, CGNAT, other loopback ports, and IPv6 private/link-local destinations. Render jobs are serialized and bounded by an absolute deadline, slide/pixel/output-byte budgets, and a shared remote-resource semaphore that covers DNS validation through pinned fetch completion, plus aggregate remote-byte limits. System fonts keep CJK/emoji capture independent of remote font CDNs.

## Upstream and license

The target runtime derives from the WoowTech OpenDesign 0.24.1 core built from the WoowTech fork. This review branch pins `ghcr.io/woowtech/open-design-core:20261027.1127@sha256:c8cd57f07adaef23b8dddbb22a8b75f97bdf8ca42c8bfbec1b284dc60ee5a4cf`; its public import is pending the Gitea approval for that exact JCR candidate. Home Assistant's local add-on builder rejects digest syntax in `build.yaml`, so that development path uses the matching tag `ghcr.io/woowtech/open-design-core:20261027.1127`. Build and release only after the public tag resolves to the pinned digest.

OpenDesign is licensed under Apache-2.0; the core image carries its license and a notice of the WoowTech changes. The add-on packaging and integration code in this repository is MIT licensed; see [LICENSE](LICENSE). The image is therefore labelled `Apache-2.0 AND MIT`.
