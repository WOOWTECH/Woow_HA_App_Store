# Architecture

## Process model

This add-on layers on `ghcr.io/hassio-addons/vscode/{amd64,aarch64}:7.0.0` and adds exactly one node to its s6-rc service graph. Everything else — `init-user`, `init-mysql`, `init-mosquitto`, `init-code-server`, `code-server` — is upstream, unmodified.

```
                    ┌──────────────┐
                    │  init-woow   │  (new, oneshot)
                    └──────┬───────┘
                           │ dependencies.d edge added by this add-on
                           ▼
                    ┌──────────────────┐        ┌───────────┐
                    │ init-code-server │───────▶│ code-server│ (longrun)
                    └──────────────────┘        └───────────┘
```

`init-woow` is wired as a dependency of `init-code-server` via a marker file at `rootfs/etc/s6-overlay/s6-rc.d/init-code-server/dependencies.d/init-woow` — s6-rc runs it to completion before `init-code-server` starts. This ordering is load-bearing: `init-code-server` calls `bashio::exit.nok` if the configured `config_path` directory does not already exist, and `init-woow` is what creates it.

**s6 bundle membership.** This base image (`hassio-addons/vscode:7.0.0`) does **not** ship a `/etc/s6-overlay/s6-rc.d/user/contents.d/` directory — verified empirically by inspecting the built image. Its s6-overlay version (3.2.3.2) instead uses the `/etc/s6-overlay/user-bundles.d/user/contents.d/` overlay mechanism, which is what actually holds the markers for `code-server`, `init-code-server`, `init-user`, `init-mysql`, `init-mosquitto`. `init-woow` and `nginx-direct` are added there, not under `s6-rc.d/user/contents.d/` (a different base image's convention — do not copy that path blindly onto a different base without checking first, the way this add-on's own recon initially assumed).

## What `init-woow` does, in order

1. Log level, timezone, `env_vars` — same idioms as the sibling `Woow_ha_pi_agent_add_on`'s `pi-web/run` (the `${SUPERVISOR_TOKEN:-}` guard under `set -u`, the `[A-Za-z_][A-Za-z0-9_]*` name validation).
2. POST `{"ingress_panel": true}` to the Supervisor API — auto-enables the sidebar entry.
3. `reset_pi_state`: if true, wipe `/data/pi-agent` and auto-revert the option.
4. Create `config_path` (default `/share/projects`) and seed a `pi` task into its `.vscode/tasks.json` if none exists — the F1 webview fallback.
5. Run `pi-seed` (shared byte-for-byte with the podman package and the k3s chart) to materialise `/data/pi-agent` from `/opt/pi-agent-skel`.
6. Bridge `$HOME/.pi/agent/skills` ↔ `$PI_CODING_AGENT_DIR/skills` (the same HOME-relative-vs-env-relative trap `Woow_ha_pi_agent_add_on` documents) and symlink `/root/.pi` at the seeded store.
7. Merge the 6 required `settings.json` keys (see `PARITY_CONTRACT.md` §2.5) into `/data/vscode/User/settings.json` with `jq -S '. * $acp[0]'` — idempotent, preserves unrelated user edits, and works even after upstream's own default-settings copy runs (see below).
8. Write `PI_AGENT_DATA_DIR`, `PI_CODING_AGENT_DIR`, `PI_TELEMETRY`, `PI_SKIP_VERSION_CHECK` into `/run/s6/container_environment/` — the s6-overlay v3 mechanism for publishing env to every later `with-contenv` service. Verified end-to-end: both the `code-server` process and its extension-host child process carry these in their real `/proc/<pid>/environ`.
9. `nginx-direct` (a separate, always-enabled longrun) self-gates on `direct_password` at its own startup rather than being toggled by `init-woow` — s6-rc compiles its bundle membership once per boot, so a service disabled this boot cannot be enabled again until the next one. Idling (`sleep infinity`) when off costs nothing.

## Why settings.json merge order is safe

`init-woow` runs **before** `init-code-server`. Trace through what happens on a fresh install:

1. `init-woow` creates `/data/vscode/User/settings.json` (copying upstream's own default if present, else `{}`) and merges in the 6 required keys.
2. `init-code-server` then checks `bashio::fs.file_exists '/data/vscode/User/settings.json'` — **true**, since step 1 already created it — so it does **not** overwrite it with the bare default.
3. `init-code-server`'s hash-upgrade check computes the file's sha512 and compares it against 14 known "this is still the untouched default" hashes. Since the file already carries our merged ACP keys, its hash will not match any of them, so this check is also a no-op.

Net effect: our merge always wins, upstream's default-settings logic never fires after the first boot, and a user's own edits to `settings.json` (anything outside the 6 required keys) survive every restart.

## Why there is no nginx, and must never be a `serviceWorker.register` shim

The upstream vscode image ships **no nginx at all** (verified: `/etc/nginx` does not exist in the base image before this add-on installs it) — HA Supervisor ingress talks to code-server's own HTTP server directly. The sibling `Woow_ha_pi_agent_add_on` add-on, by contrast, fronts its Next.js app with an nginx that does response-body rewriting: an `</head>` shim that **replaces `navigator.serviceWorker.register` with a fake stub**, needed there because that app's own client-side router breaks under a path-prefixed ingress URL.

**That pattern must never be copied here.** code-server does not need it — it already emits every asset, webview, and ServiceWorker URL as relative to wherever it's mounted (`data-settings='{"base":"."}'`), so the ingress prefix is transparent to it. Stubbing `serviceWorker.register` would not fix a problem code-server has; it would **create** one, by preventing the ACP chat webview's own ServiceWorker from ever registering. The only nginx in this add-on (`nginx-direct`) does pure `proxy_pass` + `auth_basic` + WebSocket-upgrade headers, no `sub_filter`, no body rewriting, and is off by default.

## Persistent state

| Path | What | Backed up |
|---|---|---|
| `/data/pi-agent` | pi's entire state (see DOCS.md) | yes, minus `models-store.json` and `*.jsonl.tmp` |
| `/data/vscode` | code-server's IDE settings/extensions/workbench state | yes, minus `logs/` and `CachedProfilesData/` |
| `config_path` (default `/share/projects`) | the actual workspace | governed by whatever backs up `/share` |

## Versioning discipline

`PI_CODING_AGENT_VERSION`, `PI_ACP_VERSION`, `ACP_CLIENT_VERSION` are pinned build args, matching `PARITY_CONTRACT.md`. Bump all three WOOWTECH code-server repos (this one, the podman package, the k3s chart) in the same PR set — see the contract for why (pi's session/skill/model schema must not drift between what each deployment's own build ships).

## Where to look when something breaks

| Symptom | Look here |
|---|---|
| Add-on won't start / immediately unhealthy | `ha addons logs woow_ha_code_server` — check for `init-woow` errors before `code-server` even attempts to start |
| `config_path does not exist` fatal from `init-code-server` | `init-woow` didn't run, or the dependency marker is missing — check `rootfs/etc/s6-overlay/s6-rc.d/init-code-server/dependencies.d/init-woow` exists in the built image |
| Terminal `pi` prompts for login even after `pi login` in the chat panel | Check `/run/s6/container_environment/PI_CODING_AGENT_DIR` inside the container, and confirm the shell session's parent went through `with-contenv` |
| ACP sidebar icon never appears | `settings.json`'s `security.workspace.trust.*` keys — verify with `tests/smoke-parity.sh` |
| Chat webview blank | Follow the F1/F2 ladder in DOCS.md; check for `SecurityError`/`ServiceWorker` in the browser console per `tests/smoke-acp-webview.md` |
| `reset_pi_state` seems to loop / re-wipe every boot | The Supervisor API POST to revert the option failed — check `SUPERVISOR_TOKEN` is present and the Supervisor is reachable |
