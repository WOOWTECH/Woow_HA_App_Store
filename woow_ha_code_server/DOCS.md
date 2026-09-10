# Woow Code Server

## What it is

A Home Assistant Supervisor add-on that layers the [pi coding agent](https://github.com/earendil-works/pi), [pi-acp](https://www.npmjs.com/package/pi-acp), and the [ACP Client](https://open-vsx.org/extension/formulahendry/acp-client) chat sidebar onto the Home Assistant Community App Store's [Studio Code Server](https://github.com/hassio-addons/addon-vscode) (`code-server` 4.135.0). Everything upstream provides — ingress, the `ha` CLI, the Home Assistant / YAML / MDI extensions, the persistence conventions — is unchanged; this add-on adds exactly four things: Node 22, pi + pi-acp, the ACP Client extension, and one startup script.

This is one of three aligned WOOWTECH deployments (podman, this HA add-on, and a k3s Helm chart) that share the same pi version, the same pi state layout, and the same required `settings.json` keys. See [`PARITY_CONTRACT.md`](https://github.com/WOOWTECH/Woow_podman_code_server_package/blob/main/PARITY_CONTRACT.md) for the cross-platform contract.

pi's state (login, sessions, skills, model config) is **private to this add-on** — it is not shared with any other add-on, including the separate `Woow HA Pi Agent` add-on.

## First run

1. Install and start the add-on.
2. Open the web UI (sidebar panel, auto-enabled on first boot).
3. Open a terminal inside code-server and sign pi in:
   ```
   pi login
   ```
   This writes the credential (an OAuth pair) into this add-on's own `/data/pi-agent/auth.json`. Nothing is pre-configured — there is no shared provider key to inherit from anywhere.
4. Bottom status bar should show the ACP adapter connected; the right-side chat panel now talks to that login.

## Configuration

| Option | Type | Default | Notes |
|---|---|---|---|
| `log_level` | `trace`\|`debug`\|`info`\|`notice`\|`warning`\|`error`\|`fatal` | `info` | bashio verbosity for `init-woow`'s own startup log. |
| `config_path` | string | `/share/projects` | The folder code-server opens on startup. Must exist under one of the mapped shares. |
| `packages` | list of string | `[]` | Inherited from upstream. Escape hatch, unused by this add-on's own wiring. |
| `init_commands` | list of string | `[]` | Inherited from upstream. Escape hatch, unused by this add-on's own wiring. |
| `timezone` | string (optional) | empty | IANA timezone. Affects add-on log timestamps. |
| `pi_default_provider` | string (optional) | empty | Applied only when this add-on's pi has no `settings.json` yet — i.e. before the first `pi login`. |
| `pi_default_model` | string (optional) | empty | Paired with `pi_default_provider`. |
| `direct_password` | password (optional) | empty | **F2 fallback — see below.** Leave empty unless the ACP chat sidebar does not render under HA ingress for you. |
| `reset_pi_state` | bool | `false` | One-shot: wipes `/data/pi-agent` on next boot, then auto-reverts to `false`. |
| `env_vars` | list of `{name, value}` | `[]` | Advanced escape hatch, exported to code-server, its extension host, and every integrated terminal. |

## Where state lives / what is backed up

- `/data/pi-agent` — pi's entire state: `auth.json` (the login credential, mode 600), `settings.json` (provider/model choice), `sessions/`, `skills/`, `home/.pi/` (the pi CLI's own homedir-relative files). Included in HA backups except `models-store.json` (a refetchable cache) and `sessions/*.jsonl.tmp`.
- `/data/vscode` — code-server's own IDE settings, extensions the user installs into `/data` (not the built-in ones this add-on ships), and workbench state. Managed by upstream, unchanged by this add-on except the `settings.json` merge described below.
- `config_path` (default `/share/projects`) — your actual workspace files. Not add-on-specific; it is whatever you pointed `config_path` at.

## The ACP chat webview — status and fallback ladder

The right-side chat panel is a VS Code webview, and webviews need a browser-trusted secure context to register their ServiceWorker. Home Assistant's own ingress origin (`https://<your-ha-host>/...`) is normally exactly that, and the ingress path-prefix does not interfere with a webview's own relative-URL scoping — this has been verified end-to-end against a live Home Assistant instance (built-in webview rendering, ServiceWorker registering correctly under a real ingress token path, integrated terminal working over the ingress WebSocket).

- **F0 (default):** ship as-is. If it works for you (it should), there is nothing else to do.
- **F1 (always available, zero configuration):** the terminal `pi` command is the guaranteed-working surface regardless of webview status — a `pi` task is available in the Command Palette (`Tasks: Run Task` → `pi`) for one-keystroke access. The ACP Client extension's status bar and tree view work independently of its webview panel.
- **F2 (opt-in fallback):** if the chat sidebar genuinely does not render for you, set `direct_password` and map port `1338` in the add-on's Network settings. This puts code-server behind a second, non-ingress front on a path root with your own reverse-proxy/tunnel providing a trusted cert in front of it (e.g. a Cloudflare Tunnel route to `<home-assistant-host>:1338`), which is the same topology the k3s deployment uses and is provably compatible with webviews. **Never expose port 1338 without `direct_password` set** — the underlying code-server runs with its own authentication disabled (it normally relies entirely on HA's ingress session).

## Security

- Home Assistant Supervisor ingress is the only authentication gate by default; code-server itself runs `--auth none`.
- The optional F2 direct port (1338) adds HTTP Basic auth via `direct_password`, but that is a second gate you opt into, not a replacement for keeping the port unmapped by default.
- `/config`, `/backup`, `/addons`, `/share`, `/ssl`, `/media`, and all other add-ons' configs are mounted read-write — this add-on has broad HAOS access by design (it's a code editor for your whole HA install). Treat it like root shell access to your Home Assistant.
- pi's only credential is an OAuth pair in `/data/pi-agent/auth.json`. Anyone with a shell in this add-on's container (i.e. anyone who can reach the IDE) can read it.

## Migrating from the community `vscode` add-on mirror

Nothing required. This add-on has a different slug (`woow_ha_code_server`) and therefore its own `/data`, so its pi state starts empty and correctly versioned rather than inheriting anything from an older install. The community mirror add-on is untouched and can keep running side by side.
