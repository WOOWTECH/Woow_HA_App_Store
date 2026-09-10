# Woow Code Server (Home Assistant Add-on)

[![HA add-on](https://img.shields.io/badge/Home%20Assistant-Add--on-41BDF5)](https://www.home-assistant.io/)
[![code-server](https://img.shields.io/badge/code--server-4.135.0-blueviolet)](https://github.com/coder/code-server)
[![pi-coding-agent](https://img.shields.io/badge/pi--coding--agent-0.83.0-blue)](https://www.npmjs.com/package/@earendil-works/pi-coding-agent)
[![ACP](https://img.shields.io/badge/ACP%20client-formulahendry.acp--client%400.2.0-green)](https://open-vsx.org/extension/formulahendry/acp-client)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**English** · [繁體中文](README_zh-TW.md)

[`code-server`](https://github.com/coder/code-server) (the browser IDE) as a Home Assistant Supervisor add-on, layered on the Community App Store's [Studio Code Server](https://github.com/hassio-addons/addon-vscode) — everything upstream provides (HA ingress, the `ha` CLI, the Home Assistant/YAML/MDI extensions) stays intact. On top: the [pi coding agent](https://github.com/earendil-works/pi), [pi-acp](https://www.npmjs.com/package/pi-acp), and the [ACP Client](https://open-vsx.org/extension/formulahendry/acp-client) chat sidebar, pre-wired.

This is one of three aligned WOOWTECH code-server deployments — this add-on, a [podman package](https://github.com/WOOWTECH/Woow_podman_code_server_package), and a [k3s Helm chart](https://github.com/WOOWTECH/Woow_k3s_code_server_package) — sharing the same pi version and pi state layout. See [`PARITY_CONTRACT.md`](PARITY_CONTRACT.md).

pi's state here is **private to this add-on** — not shared with the separate `Woow HA Pi Agent` add-on or with the podman/k3s deployments.

---

## What you get

| | |
|---|---|
| **UI** | Home Assistant sidebar (ingress), auto-enabled on first boot |
| **IDE** | code-server 4.135.0 layered on `hassio-addons/vscode:7.0.0` — HA/YAML/MDI extensions, `ha` CLI, oh-my-zsh all still present |
| **Agent** | pi 0.83.0 in the ACP right-side chat panel, and as `pi` on every terminal PATH |
| **Workspace** | Configurable `config_path` (default `/share/projects`) |
| **Persistence** | pi state in this add-on's own `/data/pi-agent`; IDE settings in `/data/vscode` (both Supervisor-managed, both backed up) |
| **Fallback** | If the chat webview ever doesn't render for you: a seeded terminal `pi` task (always available) and an optional direct HTTP-Basic-gated port (opt-in) |

## How the pi wiring works — 30 seconds

A new s6-rc oneshot, `init-woow`, runs **before** upstream's own `init-code-server` (a dependency edge this add-on adds, without touching any upstream file). It seeds `/data/pi-agent` from the same skeleton the podman package and k3s chart use, merges the ACP + workspace-trust keys into `settings.json` with an idempotent `jq` merge, and publishes the `PI_*` environment to every later service — including code-server's own extension host and every integrated terminal (verified directly against the running process's `/proc/<pid>/environ`, not just claimed).

```
init-woow (new)  →  init-code-server (upstream)  →  code-server (upstream, longrun)
     │
     ├─ pi-seed → /data/pi-agent (byte-identical script across all 3 deployments)
     ├─ jq merge → /data/vscode/User/settings.json
     └─ /run/s6/container_environment/PI_* → inherited by code-server + extension host + terminals
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full s6-rc graph and why the settings-merge ordering is safe against upstream's own default-settings logic.

## Install

Via the WOOWTECH HA App Store, or directly:

1. HA → Settings → Add-ons → Add-on Store → ⋮ → Repositories → add `https://github.com/WOOWTECH/Woow_ha_code_server_add_on`.
2. Install **Woow Code Server**, start it.
3. Open the Web UI from the sidebar.
4. Open a terminal and run `pi login` — this add-on's pi has no credentials until you do this once.

Full checklist: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## The ACP chat webview

Verified end-to-end against a live Home Assistant instance: HA's ingress origin is a browser-trusted secure context, the ingress path prefix does not interfere with a webview's ServiceWorker registration (code-server emits every asset URL as relative), and a built-in webview (Markdown preview) renders and its ServiceWorker activates correctly through the real ingress URL. See [`tests/smoke-acp-webview.md`](tests/smoke-acp-webview.md) for the 2-minute manual check, and [`DOCS.md`](DOCS.md) for the F1 (terminal task, always on)/F2 (opt-in direct port) fallback ladder if your setup ever behaves differently.

## Layout

```
config.yaml / build.yaml         HA add-on manifest + per-arch base image
Dockerfile                       layers Node 22 + pi + pi-acp + ACP extension onto hassio-addons/vscode
rootfs/
  usr/local/bin/pi-code          HOME-scoping ACP command wrapper (byte-identical across all 3 deployments)
  usr/local/bin/pi-seed          idempotent pi-state seeder (byte-identical)
  etc/profile.d/pi.sh            terminal pi env scoping (byte-identical)
  opt/acp-settings.json          the 6 required settings.json keys
  opt/SHA256SUMS                 hashes of the 3 shared files above
  etc/s6-overlay/scripts/init-woow           the new oneshot's actual script
  etc/s6-overlay/s6-rc.d/init-woow/          type=oneshot, up->the script above
  etc/s6-overlay/s6-rc.d/init-code-server/dependencies.d/init-woow   dependency edge (upstream service, our marker)
  etc/s6-overlay/s6-rc.d/nginx-direct/       F2 fallback longrun (self-gates on direct_password)
  etc/s6-overlay/user-bundles.d/user/contents.d/{init-woow,nginx-direct}  s6 bundle membership markers
docs/ARCHITECTURE.md             s6-rc graph, settings-merge safety proof, "why no nginx shim"
docs/DEPLOYMENT.md               install checklist, store registration steps
DOCS.md                          the HA add-on page text (config reference, first run, fallback ladder)
tests/
  lib/parity.sh                  portable adapter, shared with the podman/k3s repos (PARITY_TARGET=ha)
  smoke-container.sh / smoke-acp.sh / smoke-pi-integration.sh   same assertions as the other two repos
  smoke-addon.sh                 checks the add-on's own state via the Supervisor REST API
  smoke-acp-webview.md           the manual 2-minute browser gate
translations/{en,zh-tw}.yaml     HA UI strings for every option
.github/workflows/build.yml      amd64 + aarch64 CI, ghcr on push/release, shared-hash verification gate
```

## Verifying a deployment

```bash
# Against a running container (needs a way to exec into it — see tests/lib/parity.sh):
SSHHA=/path/to/sshha.sh HA_ADDON_CONTAINER=app_woow_ha_code_server \
  PARITY_TARGET=ha bash tests/smoke-container.sh
PARITY_TARGET=ha bash tests/smoke-acp.sh
PARITY_TARGET=ha EXPECTED_PI_VERSION=0.83.0 bash tests/smoke-pi-integration.sh

# Against the Supervisor's own view of the add-on:
HA_URL=https://your-ha-host HA_TOKEN=... bash tests/smoke-addon.sh
```

All three container-internal scripts were run end-to-end during development against a real built image and a mock Supervisor API (not just eyeballed) — see `CHANGELOG.md` and `docs/ARCHITECTURE.md` for what was actually verified.

## Security

- HA Supervisor ingress is the only authentication gate by default — code-server itself runs `--auth none`.
- `/config`, `/backup`, `/addons`, `/share`, `/ssl`, `/media` and every other add-on's config are mounted read-write. This add-on has broad HAOS access by design — treat it like root shell access to your Home Assistant.
- The optional F2 direct port (1338) adds HTTP Basic auth via `direct_password` and must never be mapped without it set.
- pi's only credential is an OAuth pair in `/data/pi-agent/auth.json`. Anyone with a shell in this add-on's container can read it.

Full detail: [`DOCS.md`](DOCS.md#security).

## Related

- [`Woow_podman_code_server_package`](https://github.com/WOOWTECH/Woow_podman_code_server_package) — the same pi/ACP wiring, packaged for rootless Podman
- [`Woow_k3s_code_server_package`](https://github.com/WOOWTECH/Woow_k3s_code_server_package) — the same image, deployed on k3s via Helm + Cloudflare Tunnel
- [ACP Client (formulahendry)](https://open-vsx.org/extension/formulahendry/acp-client) — the VS Code extension that renders the chat panel
- [pi-acp](https://www.npmjs.com/package/pi-acp) — community bridge from ACP JSON-RPC to pi's `--mode rpc`
- [Woow_ha_pi_agent_add_on](https://github.com/WOOWTECH/Woow_ha_pi_agent_add_on) — a separate, unrelated HA add-on bundling pi-web; no state is shared with this add-on

## License

MIT
