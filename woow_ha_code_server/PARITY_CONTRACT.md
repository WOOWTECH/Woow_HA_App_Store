> **UNVERIFIED-AT-WRITE-TIME markers.** Two rows in §4 are marked `GATE`. They are the only assertions in this document that no one has observed end to end. Everything else traces to a file path or a command output captured in the recon phase.

# PARITY_CONTRACT.md

**功能完全對齊 — the single source of truth for the WOOWTECH code-server + pi trio**

| | |
|---|---|
| Version | 1.0 (2026-09-10) |
| Baseline | `Woow_podman_code_server_package` @ `2df94fc` — parity is levelled **UP** to this feature set |
| Targets | `Woow_podman_code_server_package` (exists), `Woow_ha_code_server_add_on` (new), `Woow_k3s_code_server_package` (new) |
| Authority | Where this file and a recon report, a README, or `docs/K3S_BLUEPRINT.md` disagree, **this file wins.** `docs/K3S_BLUEPRINT.md` is stale (StatefulSet / ingress-nginx / oauth2-proxy / Velero) and is superseded here by the realized `Woow_k3s_pi_agent_package` + `opendesign-2.0.0` house style. |
| Change control | Any change to §2 or §3 is one PR per repo, opened the same day, referencing the same contract version bump. A target may not ship a §2 value the other two do not have. |

---

## 1. What "對齊" means

Three deployments are at parity when, for a user sitting in front of the browser IDE:

1. The IDE is the same build, opens on a fixed folder with no picker, and has the same relevant settings.
2. The ACP Client sidebar is present, its agent is `pi`, and the status bar goes green.
3. The chat webview renders and completes a message round-trip.
4. Typing bare `pi` in the integrated terminal starts an **already-signed-in** agent — no re-login prompt.
5. Terminal `pi` and the chat sidebar read and write **the same** state directory, and that directory is **private to this deployment** — no cross-deployment volume, no shared credential file.
6. Killing and recreating the container/pod loses no pi state, no workspace file, and no IDE user setting.

Anything outside that list is either a pinned value in §2/§3 (so it cannot drift) or explicitly out of scope in §6.

---

## 2. Pinned values — copied verbatim by all three targets

These are identical on every platform. A target that cannot reach one of these values is **not at parity**; it does not get a per-platform exception.

### 2.1 Software pins

| Key | Value | Notes |
|---|---|---|
| `CODE_SERVER_VERSION` | `4.135.0` | Code `1.135.0`, commit `de89acbcdce9d9b870008a270c9f6466993d91f4`. Already true on podman **and** on the live HA add-on. |
| `PI_CODING_AGENT_VERSION` | `0.83.0` | npm `@earendil-works/pi-coding-agent@0.83.0`. **Not** 0.74.2 (HA live, unpinned accident) and **not** 0.85.1 (HA pi-agent add-on). 0.83.0 is the only version observed working end to end with `pi-acp@0.0.33` + `acp-client@0.2.0` (real ACP transcripts exist under `sessions/--workspace--/`). Bumping it is a separate, three-repo, single-PR operation. |
| `PI_ACP_VERSION` | `0.0.33` | npm `pi-acp@0.0.33`. 0.0.x — expect churn; pin hard. |
| `ACP_CLIENT_VERSION` | `0.2.0` | `formulahendry.acp-client`, fetched from **open-vsx only**. |
| `NODE_MAJOR` | `22` | pi runs as a subprocess and needs Node ≥ 22. code-server's own bundled Node is never touched. |
| Extension gallery | `https://open-vsx.org/vscode/gallery` / `https://open-vsx.org/vscode/item` | MS Marketplace ToS forbids third-party clients. Never `marketplace.visualstudio.com`. |
| Installed extension set | exactly `formulahendry.acp-client@0.2.0` (+ whatever the platform's base image already ships) | No other ACP adapter is pre-configured. Claude Code / Codex / Gemini stay visible-but-unwired, deliberately. |

### 2.2 pi data directory layout (identical on all three)

```
/data/pi-agent/                        # PI_AGENT_DATA_DIR / PI_CODING_AGENT_DIR. Must be a directory
├── .woow-pi-store                     #   marker shipped in the skeleton; proves the store was seeded
├── auth.json          0600            #   THE credential. OAuth pair, rewritten by pi on refresh -> must be RW, never a read-only Secret mount
├── settings.json      0600            #   {defaultProvider, defaultModel, packages[], theme}
├── models.json        0600            #   provider overrides; {"providers":{}} today
├── models-store.json  0600            #   refetchable catalogue cache — never migrated, never backed up
├── home/                              #   $HOME of the pi subprocess (set by pi-code ONLY)
│   └── .pi/
│       ├── agent/skills -> ../../skills
│       └── pi-acp/session-map.json    #   ACP<->pi bridge state, authored only by the IDE side
├── sessions/                          #   transcripts
└── skills/
```

Image also ships `/opt/pi-agent-skel/` — the canonical empty skeleton (`home/.pi`, `sessions`, `skills`, `.woow-pi-store`) that `pi-seed` copies from.

### 2.3 Environment variables

| Variable | Value | Where it must be set |
|---|---|---|
| `PI_AGENT_DATA_DIR` | `/data/pi-agent` | container env (default inside `pi-code` too) |
| `PI_CODING_AGENT_DIR` | `/data/pi-agent` | container env **and** `/etc/profile.d/pi.sh` |
| `PI_TELEMETRY` | `0` | container env + `pi.sh` + `pi-code` |
| `PI_SKIP_VERSION_CHECK` | `1` | container env + `pi.sh` + `pi-code` |
| `TZ` | `Asia/Taipei` | container env |
| `LANG`, `LC_ALL` | `C.UTF-8` | container env |
| `HOME` (pi subprocess only) | `/data/pi-agent/home` | exported **inside `pi-code` only**. Never globally — overriding the IDE's HOME breaks code-server's own config/extension lookups. |
| **BANNED** `PI_CODING_AGENT_SESSION_DIR` | must be unset | the live HA `pi-ha` wrapper sets it; the contract drops it. Sessions live at `$PI_CODING_AGENT_DIR/sessions`. |
| **BANNED** `DEFAULT_WORKSPACE` | must be unset | proven no-op (commit `1e7c35d`); `workingDir` is the only mechanism that works. |
| **BANNED** `--default-workspace` flag | must not be used | does not exist in code-server. |

### 2.4 Shared files — byte-identical across the three repos

Each repo vendors these at the same paths. CI in every repo asserts the sha256 against `rootfs/SHA256SUMS` published by **`Woow_podman_code_server_package` (source of truth)**. A change lands in all three repos in the same PR set.

| Path | sha256 (current) | Role |
|---|---|---|
| `/usr/local/bin/pi-code` | `3c39a8ad4934210fb34fffdf5a6fb9640994c843845f4ed5c48cce508ec64e73` | the **only** ACP entrypoint. exits `78` if `$PI_AGENT_DATA_DIR` is not a dir; exports `HOME`, `PI_CODING_AGENT_DIR`, `PI_TELEMETRY`, `PI_SKIP_VERSION_CHECK`, and `GIT_CONFIG_GLOBAL` (pointed at the **login** HOME's `.gitconfig`, captured before `HOME` is overwritten — see P45); `exec pi-acp "$@"`. |
| `/etc/profile.d/pi.sh` | `8be97cdabbf7998db582b64382e5e4c5bc01ef494b967d6131c35772c60d4116` | terminal-pi env. Exports the three PI_* vars, deliberately **not** `HOME`. |
| `/usr/local/bin/pi-seed` | `bbba98a7a123b76950c9f9f6ebd1250e01dcfa098b8353574722d4867ea5b18a` | idempotent `cp -an /opt/pi-agent-skel/. "$PI_AGENT_DATA_DIR"/` + `chmod 700` + optional `settings.json` defaults from `PI_DEFAULT_PROVIDER`/`PI_DEFAULT_MODEL`. Never overwrites. |
| `settings.json` seed | `399023d568a078ec528f74c0bd3a872a1b50cc6a8b5c00126da9209f836775c6` (podman/k3s form) | see §2.5. |

### 2.5 Required VS Code settings keys

Seven keys are load-bearing and must be present with these exact values, whatever the file path (§3):

```json
{
  "acp.agents": { "pi": { "command": "pi-code", "args": [], "env": {} } },
  "security.workspace.trust.enabled": false,
  "security.workspace.trust.startupPrompt": "never",
  "security.workspace.trust.banner": "never",
  "security.workspace.trust.emptyWindow": false,
  "extensions.autoUpdate": "off"
}
```

`acp.agents.pi.command` is the **bare name** `pi-code`, resolved via `PATH`. Any platform that overrides `PATH` must keep `/usr/local/bin` on it. Workspace Trust must be off on all four keys: the ACP Client extension declares no `untrustedWorkspaces.supported`, so under Restricted Mode its view container never activates and the sidebar icon silently never appears.

Cosmetic, aligned on podman/k3s only (see §6): `workbench.colorTheme: "Default Dark Modern"`, `terminal.integrated.defaultProfile.linux: "bash"`, `files.exclude` for `**/.git`, `**/.DS_Store`, `**/node_modules`.

### 2.6 Wrapper / binary names on `PATH`

| Name | Resolves to | Present on |
|---|---|---|
| `pi` | pi CLI 0.83.0 | all three |
| `pi-acp` | pi-acp 0.0.33 | all three |
| `pi-code` | `/usr/local/bin/pi-code` | all three |
| `pi-seed` | `/usr/local/bin/pi-seed` | all three |
| `node` | Node 22.x | all three |
| `pi-ha` | symlink → `pi` | **HA only**, muscle-memory compatibility with the current live add-on. Not a distinct behaviour. |

### 2.7 Health endpoint

`GET /healthz` on the container's own listening port → `200`. Probe cadence mirrors the podman `HEALTHCHECK`: interval 30 s, timeout 10 s, start period 15 s, 3 retries.

---

## 3. Per-platform values — where identical is impossible

| Value | podman | HA add-on | k3s | Why it cannot be identical |
|---|---|---|---|---|
| Listening port | `8080` (published `0.0.0.0:8443`) | `1337` | `8080` (Service `8080`) | HA Supervisor ingress is wired to upstream's `ingress_port: 1337` and its `code-server/run` hardcodes `--port 1337`. Changing it would mean replacing upstream's s6 run script. |
| Workspace path | `/workspace` ← host `~/Desktop` | `/share/projects` (option `config_path`) | `/workspace` ← Longhorn PVC | HA has no host bind; `/share` is the supervisor-granted, HA-visible surface and is already where the live add-on points. |
| How the folder is fixed | quadlet `WorkingDir=/workspace` | add-on option `config_path` (upstream's `code-server/run` `cd`s there and passes it positionally) | pod `workingDir: /workspace` | upstream `codercom` entrypoint hardcodes `code-server --bind-addr 0.0.0.0:8080 .`; only the CWD is honoured. HA's upstream run script takes the folder as an argument. |
| Run user / `HOME` | `coder` uid 1000, `HOME=/home/coder` | `root` uid 0, `HOME=/root` | `coder` uid 1000, `HOME=/home/coder` | HA add-ons run as root by supervisor convention; the upstream image is built that way. |
| VS Code user-data dir | `/home/coder/.local/share/code-server` | `/data/vscode` (upstream passes `--user-data-dir /data/vscode`) | `/home/coder/.local/share/code-server` | fixed by upstream's run script on HA. |
| settings.json path | `/home/coder/.local/share/code-server/User/settings.json` | `/data/vscode/User/settings.json` | same as podman | follows the user-data dir. |
| How settings get there | baked in the image (`/etc/skel` **and** the real path) | s6 oneshot `init-woow` seeds from `/root/.code-server/settings.json` if absent, then **idempotent `jq` merge** of the seven keys | initContainer seeds from ConfigMap if absent, then the same `jq` merge | HA's `/data/vscode` pre-exists on upgrade and upstream's hash-based default-upgrade mechanism (`PREVIOUS_DEFAULT_CONFIG_HASHES`) would ignore a new image default. The merge sidesteps it and preserves user edits. |
| Extension install mechanism | `code-server --install-extension` at build | unpack the open-vsx `.vsix` into `/usr/local/lib/code-server/lib/vscode/extensions/formulahendry.acp-client-0.2.0` **and** append `formulahendry.acp-client#0.2.0` to `/root/vscode.extensions` | same as podman (same image) | upstream's `init-code-server` purges `/data/vscode/extensions/<id>*` for every line in `vscode.extensions` on each boot, so a `/data`-installed copy would delete itself; the builtin dir is the only stable slot. |
| Node 22 source | NodeSource apt `node_22.x` | official `nodejs.org` tarball → `/opt/node22`, symlinks in `/usr/local/bin` | same image as podman | upstream vscode image exact-pins Debian 13 apt versions and ships **no** system node; a tarball avoids fighting those pins and avoids an untested NodeSource-on-trixie path. |
| pi state persistence | internal named volume `woow-code-server-pi-data` → `/data/pi-agent` | add-on `/data/pi-agent` (supervisor-managed persistent dir) | Longhorn PVC `code-server-pi-data` → `/data/pi-agent` | different storage substrates; the **mount path is identical and that is what the contract requires**. |
| IDE user-data persistence | internal volume `woow-code-server-ide` → `/home/coder/.local/share/code-server/User` | already persistent (`/data/vscode`) | PVC subPath `ide-user` → same path | — |
| Front door | code-server `PASSWORD` (env), plain HTTP `:8443` | HA Supervisor ingress, `--auth none` | Cloudflare Tunnel → ClusterIP; `PASSWORD` from a k8s Secret | one authenticated gate per platform; the mechanism differs, the property does not. |
| Credential storage | quadlet `EnvironmentFile=` (not committed) | none (HA session is the gate) | Secret `code-server-auth`, key `PASSWORD` | never a literal in git. |
| Supervision | Quadlet `Restart=always` + health timer | HA Supervisor + `watchdog:` | Deployment + kubelet probes | the systemd health timer has **no** counterpart elsewhere and must not be recreated. |
| Image | `ghcr.io/woowtech/woow-code-server-<arch>:<ver>` | `ghcr.io/woowtech/woow-ha-code-server-{arch}:<ver>` | **the podman image**, `ghcr.io/woowtech/woow-code-server-amd64`, pinned by digest | HA must layer on `ghcr.io/hassio-addons/vscode/<arch>:7.0.0` to keep ingress + s6 + `ha` CLI + the 8 vendored extensions; podman and k3s can and must share one image so the pi layer cannot drift. |
| Public hostname | none (LAN `:8443`) | `https://woowtech-ha.woowtech.io/api/hassio_ingress/<token>/` | `https://code-server-woow-k3s.woowtech.io` | — |

---

## 4. Parity checklist

Every row is a command. Define the target adapter first:

```bash
# --- podman ---
CX(){ podman exec -u coder code-server "$@"; }
BASE=http://127.0.0.1:8443            # 127.0.0.1, not the LAN IP — see P31

# --- HA (run from /home/woowtechcluster1/woow-code-server-align) ---
HAC=$(./sshha.sh 'docker ps --format "{{.Names}}" | grep woow_ha_code_server' | tr -d '\r')
CX(){ ./sshha.sh "docker exec $HAC $*"; }
BASE=https://woowtech-ha.woowtech.io/api/hassio_ingress/<token>   # needs an ingress_session cookie

# --- k3s ---
CX(){ kubectl --context woow-k3s -n code-server exec deploy/code-server -c code-server -- "$@"; }
BASE=https://code-server-woow-k3s.woowtech.io
```

### A. Identity and versions

| # | Assertion | Command | Expected |
|---|---|---|---|
| P01 | code-server version | `CX code-server --version \| head -1` | starts `4.135.0`, contains `with Code 1.135.0` |
| P02 | pi version | `CX pi --version` | `0.83.0` exactly |
| P03 | pi-acp on PATH | `CX sh -c 'command -v pi-acp'` | non-empty |
| P04 | pi-acp version | `CX sh -c 'pi-acp --version 2>/dev/null \|\| npm ls -g --depth 0 pi-acp'` | contains `0.0.33` |
| P05 | Node ≥ 22 | `CX node --version` | `v22.` prefix |
| P06 | Timezone | `CX sh -c 'echo $TZ; date +%Z'` | `Asia/Taipei` / `CST` |
| P07 | Base tooling | `CX sh -c 'for b in git ssh jq curl python3 python pip3 node npm pi pi-acp pi-code pi-seed; do command -v $b >/dev/null \|\| echo MISSING:$b; done'` | empty output |

### B. Extension + ACP wiring

| # | Assertion | Command | Expected |
|---|---|---|---|
| P08 | Extension installed at the pin | `CX code-server --list-extensions --show-versions \| grep -x 'formulahendry.acp-client@0.2.0'` | one match |
| P09 | Only one ACP adapter configured | `CX jq -r '.["acp.agents"] \| keys \| join(",")' "$SETTINGS"` | `pi` |
| P10 | ACP command is `pi-code` | `CX jq -e '.["acp.agents"].pi.command=="pi-code"' "$SETTINGS"` | exit 0 |
| P11 | Workspace Trust fully off (4 keys) | `CX jq -e '.["security.workspace.trust.enabled"]==false and .["security.workspace.trust.startupPrompt"]=="never" and .["security.workspace.trust.banner"]=="never" and .["security.workspace.trust.emptyWindow"]==false' "$SETTINGS"` | exit 0 |
| P12 | Extension auto-update off | `CX jq -e '.["extensions.autoUpdate"]=="off"' "$SETTINGS"` | exit 0 — **the string `"off"`, not `false`**. code-server 4.135.0 declares this setting as `{type:"string", enum:["on","off"], default:"on"}` and decides with `getAutoUpdateValue() !== "off"`, so a boolean leaves auto-update ON. |
| P13 | `pi-code` present + executable | `CX test -x /usr/local/bin/pi-code` | exit 0 |
| P14 | `pi-code` is byte-identical everywhere | `CX sha256sum /usr/local/bin/pi-code` | `3c39a8ad4934210fb34fffdf5a6fb9640994c843845f4ed5c48cce508ec64e73` |
| P15 | `pi-code` re-scopes HOME | `CX grep -c '^export HOME="${PI_AGENT_DATA_DIR}/home"' /usr/local/bin/pi-code` | `1` |
| P16 | `pi-code` execs the adapter, not pi | `CX grep -c '^exec pi-acp' /usr/local/bin/pi-code` | `1` |
| P17 | `pi-code` guard fires when the store is gone | `CX sh -c 'PI_AGENT_DATA_DIR=/nonexistent pi-code; echo $?'` | `78` |
| P18 | `/usr/local/bin` is on the extension host PATH | `CX sh -c 'echo $PATH \| tr : "\n" \| grep -qx /usr/local/bin'` | exit 0 |

`$SETTINGS` = `/home/coder/.local/share/code-server/User/settings.json` (podman, k3s) or `/data/vscode/User/settings.json` (HA).

### C. Terminal pi

| # | Assertion | Command | Expected |
|---|---|---|---|
| P19 | profile.d shipped byte-identical | `CX sha256sum /etc/profile.d/pi.sh` | `8be97cdabbf7998db582b64382e5e4c5bc01ef494b967d6131c35772c60d4116` |
| P20 | An interactive shell sees the state dir | `CX sh -lc 'echo $PI_CODING_AGENT_DIR'` | `/data/pi-agent` |
| P21 | Telemetry + version check off in a plain shell | `CX sh -lc 'echo $PI_TELEMETRY $PI_SKIP_VERSION_CHECK'` | `0 1` |
| P22 | Set at container level, not only in a wrapper | `CX env \| grep -E '^PI_(AGENT_DATA_DIR\|CODING_AGENT_DIR\|TELEMETRY\|SKIP_VERSION_CHECK)='` | 4 lines |
| P23 | `~/.pi` **skills bridge** symlink (NOT a state fallback — only `agent/skills` lives under it; auth/settings/sessions are one level up and reachable only via `PI_CODING_AGENT_DIR`) | `CX sh -c 'readlink -f $HOME/.pi'` | `/data/pi-agent/home/.pi` |
| P24 | Session-dir env is **not** set | `CX sh -lc 'test -z "$PI_CODING_AGENT_SESSION_DIR"'` | exit 0 |
| P25 | Bare `pi` is signed in (no login prompt) | `CX sh -lc 'pi --print "say ok" 2>&1 \| head -3'` | no `login`/`auth` prompt; a model reply |

### D. pi state — internal and private

| # | Assertion | Command | Expected |
|---|---|---|---|
| P26 | Store exists and is writable by the run user | `CX sh -c 'test -d /data/pi-agent && test -w /data/pi-agent'` | exit 0 |
| P27 | Store was seeded | `CX sh -c 'test -f /data/pi-agent/.woow-pi-store && test -d /data/pi-agent/home && test -d /data/pi-agent/sessions && test -d /data/pi-agent/skills'` | exit 0 |
| P28 | Credential present and private | `CX sh -c 'test -r /data/pi-agent/auth.json && stat -c %a /data/pi-agent/auth.json'` | `600` |
| P29 | **No cross-deployment sharing** | podman: `podman inspect code-server --format '{{range .Mounts}}{{.Name}} {{end}}' \| grep -c pi-agent-data` → `0`; k3s: `kubectl -n code-server get pvc code-server-pi-data -o jsonpath='{.spec.accessModes}'` → `["ReadWriteOnce"]`; HA: `CX sh -c 'ls /data/pi-agent'` reads the add-on's own `/data`, unreachable from any other add-on | no shared store |
| P30 | State survives recreation | recreate the container/pod, then re-run **P27 + P28** | both still pass |

### E. Transport and the chat webview

| # | Assertion | Command | Expected |
|---|---|---|---|
| P31 | Origin is a secure context | browser at `$BASE`, console: `window.isSecureContext` | `true` (HA/k3s via trusted cert; podman only via `http://127.0.0.1:8443`) |
| P32 `GATE` | Webview ServiceWorker registers | browser console: `navigator.serviceWorker.getRegistrations().then(r=>console.log(r.map(x=>x.scope)))` | includes a scope ending `/stable-de89acbcdce9d9b870008a270c9f6466993d91f4/static/out/vs/workbench/contrib/webview/browser/pre/` |
| P33 `GATE` | Chat webview renders and round-trips | open the ACP sidebar, send "say ok" | a reply renders; console free of `'crypto.subtle' is not available` and `Could not register service worker: SecurityError` |
| P34 | The webview host is served | `curl -o /dev/null -w '%{http_code}' "$BASE/stable-de89acbcdce9d9b870008a270c9f6466993d91f4/static/out/vs/workbench/contrib/webview/browser/pre/service-worker.js"` | `200` |
| P35 | The PWA SW scope header survives the proxy | `curl -sI "$BASE/_static/out/browser/serviceWorker.js" \| grep -i service-worker-allowed` | `Service-Worker-Allowed: /` |
| P36 | Long-lived WebSocket survives idle | leave the tab idle 150 s, then type in the editor | no "Connection lost" that fails to auto-recover (Cloudflare closes idle WS at 100 s on HA **and** k3s) |
| P37 | No ServiceWorker-stubbing shim is in the path | `CX sh -c 'test ! -f /etc/nginx/nginx.conf \|\| ! grep -q "SW.register" /etc/nginx/nginx.conf'` | exit 0 — the pi-agent add-on's `</head>` shim **must never** be copied here; it neutralises `navigator.serviceWorker` and would blank the chat panel |

### F. IDE behaviour and persistence

| # | Assertion | Command | Expected |
|---|---|---|---|
| P38 | `/healthz` is 200 in-container | `CX sh -c 'curl -sf http://127.0.0.1:$PORT/healthz >/dev/null'` (`PORT`=8080 or 1337) | exit 0 |
| P39 | Root URL is the IDE or the login gate, never anonymous workbench | `curl -o /dev/null -w '%{http_code}' "$BASE/"` | `200` or `302` |
| P40 | Opens on a fixed folder, no picker | `CX sh -c 'cat /proc/1/cmdline \| tr "\0" " "'` (podman/k3s) / `CX pgrep -af code-server` (HA) | contains the workspace path or CWD == workspace |
| P41 | Workspace is persistent | write a file in the workspace, recreate, re-read | file present |
| P42 | IDE user settings persist across recreation | edit an unrelated setting, recreate, re-check | edit still present, and P09–P12 still pass |
| P43 | Credential is not in git | `git -C <repo> grep -nE 'PASSWORD=|SUDO_PASSWORD=' -- . \| grep -v EnvironmentFile` | no literal secret |
| P44 | Same shared files in every repo | `sha256sum -c rootfs/SHA256SUMS` in each repo | all OK |

### J. Real-coding verification (2026-09-11)

Everything above this section tests plumbing — that pi is installed, that a
config key exists, that a path resolves. None of it ever made pi write a line
of code. This section records the first run that did: **5 functional projects
built on each of the 3 deployments through the real pi TUI, then independently
re-run by a different agent that was told to trust nothing.**

Result: **15/15 work, 0 overclaimed.** Each project targets a fix from the
2026-09 field test, so a regression surfaces as a broken project rather than a
silently-passing grep:

| Project | Targets | Independently verified by |
|---|---|---|
| `py-cli` unit converter + pytest | F2 (venv/pip) | `4 passed`, plus CLI values not in the tests |
| `node-lib` CSV parser + `node --test` | F6 (npm/PATH) | `# pass 3`, plus a quoted-comma assertion |
| `web-app` tip calculator + HTTP serve | control case | `COMPUTE_OK`, served page returns `200` |
| `git-flow` branch + `--no-ff` merge | F5 (git identity) | 3 commits, 2-parent merge, one non-empty author |
| `zhtw-unicode` U+3000 vs ASCII filenames | F1 (space folding) | two distinct inodes, `DISTINCT_OK`, byte-level filenames |

**P52 — the panel and the terminal commit as the same person.** This is the F5
fix proven end to end rather than asserted from a wrapper's source. Two real
git repositories were built on the same machine, one through each interface:

```
podman  ACP panel pi : WOOWTECH Code Server <woowtech@designsmart.com.tw>
podman  terminal  pi : WOOWTECH Code Server <woowtech@designsmart.com.tw>
ha      ACP panel pi : root <root@a020c0ec-woow-ha-code-server.local.hass.io>   (through ingress)
ha      terminal  pi : root <root@a020c0ec-woow-ha-code-server.local.hass.io>
```

All three deployments now have the panel side proven with a browser, not
inferred.

**P31/P32/P33 are now OBSERVED, not just specified** — the first time the chat
webview has been driven by a browser on this deployment set:

- **k3s** — over the public trusted-cert tunnel. `isSecureContext true`, the
  webview iframe renders at non-zero size, the agent quick-pick lists `pi`,
  the status bar reaches `ACP: pi`, and a prompt produced a working
  `to_roman()` that passed 7 independent cases.
- **podman** — over an SSH port-forward to `http://127.0.0.1:18443`. Confirms
  the README's workaround: **localhost is a secure context even on plain
  HTTP**, so the service worker registers and the panel works.
- **HA** — **verified through real Supervisor ingress**, which is the transport
  the add-on's own Dockerfile flags as the risky one. Four levels of nesting
  (HA page → ingress iframe → code-server → webview iframe → chat iframe) and
  it still works: the panel renders, the agent quick-pick lists `pi`, the
  adapter reports `pi ACP adapter` on `/share/projects`, and it picked up that
  workspace's `AGENTS.md` as context on its own.

  P32 is satisfied to the letter — the registered scopes include
  `…/api/hassio_ingress/<token>/stable-<commit>/static/out/vs/workbench/contrib/webview/browser/pre/`,
  i.e. the webview service worker registers *under the ingress path*. P33's two
  named errors are absent: `'crypto.subtle' is not available` × 0,
  `Could not register service worker` × 0, `SecurityError` × 0.

  Reaching it needs the sidebar panel route (`/<addon-slug>`) driven through
  the SPA — a hard GET to `/hassio/addon/<slug>/info` returns 404, and the
  `ingress_url` from `ha addons info` returns 401 on its own because the
  ingress session cookie has not been created yet.

  Two things that look like faults and are not: the **ACP Client icon hides in
  the activity bar's "Additional Views" overflow** below roughly 1000 px of
  viewport width, and the console carries ~108 `Error creating chat editing
  session content folder` lines. The latter is VS Code's **built-in** chat
  (no account connected), not the ACP panel, and it is present on all three
  deployments.

**P36 — OBSERVED on all three (2026-09-11).** This was the last unverified
assertion, because it is the only one that needs a genuinely idle wait rather
than a command. Method: open a file in the editor, leave the tab completely
untouched for 180+ s (no polling, no scripted interaction), then type and save
— and confirm the character reached the file **from inside the container**,
which is the only proof that the round trip actually happened.

| | Path | Idle | Result |
|---|---|---|---|
| k3s | Cloudflare tunnel | 180 s | PASS — edit landed |
| HA | Cloudflare **+ Supervisor ingress** | 185 s | PASS — edit landed |
| podman | LAN, no Cloudflare (control) | 185 s | PASS — edit landed |

No `Connection lost` / `Reconnecting` / `Disconnected` appeared on any of them,
and the status bar was unchanged after the wait.

**Why it passes, rather than passing by luck.** Cloudflare really does close
idle WebSockets at 100 s, so the connection must not be idle — and it is not.
code-server's `heartbeat` file was watched for 120 s while the tab sat
untouched:

```
00:56:46  →  00:57:46  →  00:58:46      (every 60 s, browser never touched)
```

The client pings roughly once a minute, comfortably inside the 100 s window, so
the TCP connection never goes quiet long enough for Cloudflare to reap it.
**This is the thing to re-check if a future proxy shortens its idle timeout
below ~60 s** — that, not the 100 s figure, is the real margin.

**Two operational gotchas found while doing this, both worth knowing:**

- **`pi --model gpt-5.5` silently picks an unauthenticated provider.** The bare
  model name resolves to `azure-openai-responses`, and the TUI dies with
  `No API key found for azure-openai-responses`. Only `openai-codex` is logged
  in. Always qualify: **`--model openai-codex/gpt-5.5`**. `settings.json` is
  unaffected because it stores `defaultProvider` separately — which is exactly
  why this only bites on the command line.
- **`pip install --user` is blocked by PEP 668** on this Debian base
  (`externally-managed-environment`), and **pytest is not in the image**. The
  working route, and the one to put in any Python project's instructions, is a
  venv on the workspace volume:
  `python3 -m venv .venv && .venv/bin/pip install pytest`. Verified: pytest
  9.1.1 installs and runs.

### G. Ship gates

- A target may be tagged **PARITY-A** when P01–P30 + P38–P44 pass.
- A target may be tagged **PARITY-FULL** only when P31–P37 also pass.
- podman is expected to be **PARITY-A** and PARITY-FULL only from `127.0.0.1` until a trusted-cert front door is decided (§7, open fork).
- HA ships **PARITY-A** in `0.1.0`; `0.2.0` claims PARITY-FULL only after P32/P33 are observed in a browser, otherwise the §5.2 fallback ladder applies.
- **P45–P51 (§H below) are part of PARITY-A.** Every one of them exists because something shipped broken and no existing check caught it.

### H. Regressions found by the 2026-09 field test

Every assertion here exists because something shipped broken and no existing
check caught it. They are part of **PARITY-A**.

| # | Assertion | Command | Expected |
|---|---|---|---|
| P45 | Terminal pi and panel pi agree on git identity — the check P15 could not make, because it only greps the wrapper's source | `CX sh -lc 'git config --global --list \| grep ^user.'` **and** `CX sh -lc 'PI_AGENT_DATA_DIR=/data/pi-agent HOME=/data/pi-agent/home GIT_CONFIG_GLOBAL="$HOME_ORIG/.gitconfig" git config --global --list \| grep ^user.'` | identical `user.name` / `user.email`, or both empty |
| P46 | `git commit` works out of the box in a fresh repo | `CX sh -lc 'cd $(mktemp -d) && git init -q . && git commit -q --allow-empty -m t; echo $?'` | `0` (was `128`: git's identity auto-detect needs a hostname containing a dot, which podman and k3s hostnames do not have) |
| P47 | Unicode-space paths resolve exactly — the shipped verifier, not a source grep | `CX node /opt/patches/f1-verify.mjs` | exit 0, `F1 OK` |
| P48 | The Unicode patch is actually present in every copy | `CX sh -c 'grep -lr "PATCHED (Woow pi-agent image)" $(dirname $(dirname $(readlink -f $(command -v pi)))) \| wc -l'` | `>= 2` (the original incident was a patch script that was never invoked — a build-time assertion cannot catch that) |
| P49 | pip and venv work for the run user | `CX sh -lc 'python3 -m pip --version && python3 -m venv /tmp/p49 && echo ok'` | `ok` |
| P50 | `npm install -g` works as the run user, and the result is on PATH in a **login** shell | `CX sh -lc 'npm install -g --silent cowsay@1.6.0 && command -v cowsay'` | a path under the npm prefix |
| P51 | `pi` is on PATH in a login shell, not only via the image ENV | `CX sh -lc 'command -v pi'` and `CX sh -c 'command -v pi'` | same path from both |


---

## 5. Per-target file plan (summary; detail in the three designs)

### 5.1 `Woow_podman_code_server_package` — change, do not rewrite

Change: `quadlet/code-server.container` (external volume out, two internal volumes in), two new `quadlet/*.volume` files, `Containerfile` (`/opt/pi-agent-skel` + `/data/pi-agent` skeleton, `pi-seed`, `SHA256SUMS`), `rootfs/usr/local/bin/pi-seed` (new), `scripts/install.sh`, `scripts/uninstall.sh`, `scripts/migrate-pi-state.sh` (new), `tests/*` (portable adapter + drop the three sibling-artefact checks), both READMEs, `docs/plans/`.
Reason: the wrapper contract (`pi-code`, `pi.sh`, the `~/.pi` symlink) all hardcode `/data/pi-agent`; only the *provider* of that path changes. Everything that documents the path as **shared** becomes false the moment it is internal, and there are 11 files that say so.

### 5.2 `Woow_ha_code_server_add_on` — new, layered

Layer on `ghcr.io/hassio-addons/vscode/{arch}:7.0.0` so HA ingress, s6-rc, the `ha` CLI, oh-my-zsh and the 8 vendored extensions keep working untouched. Add: Node 22, pi, pi-acp, the ACP extension into the *builtin* extensions dir, the three shared rootfs files, one s6 oneshot (`init-woow`) that seeds the store, `jq`-merges the seven settings keys and publishes the PI_* env into `/run/s6/container_environment/`, and one dependency edge so it runs before `init-code-server`.
Reason: the entire pi wiring today lives in unversioned supervisor options (`packages` + 7 `init_commands`) that vanish on any options reset, install network failures abort the whole add-on, and the install is unpinned so it froze at pi 0.74.2 forever.
**Do not** copy the pi-agent add-on's `nginx.conf`. code-server emits relative URLs and needs no prefix rewriting; that shim also stubs out `navigator.serviceWorker`, which would guarantee a blank chat panel (P37).

### 5.3 `Woow_k3s_code_server_package` — new, chart-only

Helm chart `charts/code-server` following `Woow_k3s_pi_agent_package` (Deployment + own cloudflared Deployment with git-tracked ingress rules + rendered manifest committed + credential-grep in CI) at the `opendesign-2.0.0` hardening bar (digest-pinned image, `automountServiceAccountToken: false`, `allowPrivilegeEscalation: false`, `capabilities: drop: [ALL]`).
No image build in this repo: it consumes `ghcr.io/woowtech/woow-code-server-amd64` from the podman repo, pinned by digest. One image, zero drift, and the cluster is amd64-only.

---

## 6. Deliberately NOT aligned

| Item | Decision | Why |
|---|---|---|
| Host-CLI passthrough (`~/.local/bin` → `/mnt/host-local-bin`, PATH-prefixed) | podman only | No HA or k3s analogue. Also non-functional today: its only entry, `claude`, is a symlink into `~/.local/share-vk-host` which is **not** mounted, so `/mnt/host-local-bin/claude` dangles. Kept because the user asked to keep the mounts; the README must stop claiming it works. |
| `~/.ssh` and `~/.gitconfig` host mounts | podman only | HA's analogue is `/data/.ssh` + `/data/git/.gitconfig` (created by upstream `init-user`); k3s uses projected Secrets. Also non-functional on the podman host today: `.gitconfig` is 0 bytes (so `git commit` fails with "Please tell me who you are") and `.ssh` has no private key. Both READMEs currently claim otherwise and must be corrected. |
| `SUDO_PASSWORD` / in-IDE `sudo` | podman only | HA runs as root (moot); k3s drops all capabilities and runs non-root by design. |
| Default terminal shell | podman/k3s `bash`; HA keeps upstream `zsh` + oh-my-zsh | On HA the PI_* env comes from `/run/s6/container_environment`, inherited by every shell, so shell choice no longer affects agent state. Forcing bash would throw away upstream's nicer terminal for no parity gain. |
| Runtime-installed extensions surviving recreation | HA yes (upstream persists `/data/vscode/extensions`); podman/k3s no | On podman/k3s only `User/` is persisted; extensions stay image-owned so the pinned set is deterministic. Matches `extensions.autoUpdate: "off"`. |
| Cross-deployment session visibility | **removed everywhere** | This was the point of the shared volume. After the cut, code-server's `sessions/--workspace--/` is private. pi-web and open-design keep their own; nothing else regresses (they each declare the mount independently). |
| `models-store.json` | never migrated, never backed up | Refetchable provider catalogue cache. |
| Shared pi credential across the three deployments | **not aligned, by design** | `auth.json` is an OAuth pair whose refresh token is rewritten by whichever pi refreshes first. One `pi login` per deployment (§7). "The user does not have to log in again" is explicitly **out of scope**. |
| The systemd health timer | podman only | kubelet probes and the HA watchdog already do this; recreating it elsewhere is dead scaffolding. |
| nginx / ingress path-prefix shim | none of the three | code-server is prefix-agnostic (`serverBasePath:"."`, `rootEndpoint:"."`, all assets relative) and HA Supervisor strips the prefix before proxying. The only nginx anywhere in this trio is the **optional** HA `direct_port` front (§ ha_design F2), and it does no body rewriting. |
| Registering with omnigent (`omni host`) | not done | The k3s pi-agents do it; this trio's pi is standalone, matching the podman/HA baseline. |
| `pi-agent-env.sh` sourcing in the pi wrapper | dropped | The pi-agent add-on's `/usr/local/bin/pi` sources a file it does not ship. This trio uses the real `pi` binary on PATH; no launcher shim, no silent no-op. |

---

## 7. pi authentication and seeding contract

**The finding that drives this:** the only provider credential on the podman host is `/data/pi-agent/auth.json`, a single `openai-codex` entry of `type: "oauth"` with `access` + `refresh` + `expires` + `accountId`. `models.json` is literally `{"providers": {}}` — there is **no** API key anywhere to put in an env var or a Secret. Both READMEs' claim that "provider keys live in `models.json`" is false and must be corrected in all three repos.

Consequences, binding on all three targets:

1. **`auth.json` is mutable state, not a secret to mount.** pi rewrites it on refresh. It must live on the RW persistent store, never on a read-only Secret/ConfigMap projection.
2. **Default provisioning = one interactive `pi login` per deployment**, run once in that deployment's own terminal. Three deployments, three logins. This is the only design that is safe under rotating refresh tokens.
3. **Copying `auth.json` between deployments is opt-in and warned.** A refresh in one copy may invalidate the others. `scripts/migrate-pi-state.sh` exists for the podman cut-over but defaults to *not* copying `auth.json`.
4. **API-key providers are supported but not required.** If a key-based provider is ever adopted, it is injected as `models.json` `providers.*` by `pi-seed` from `PI_PROVIDER_KEYS_JSON` (k3s Secret / HA option / podman `EnvironmentFile`). Nothing to do today.
5. **Model/provider defaults are seeded, not copied.** `pi-seed` writes `settings.json` `{defaultProvider, defaultModel}` only if the file is absent, from `PI_DEFAULT_PROVIDER` / `PI_DEFAULT_MODEL` (all three packages seed `openai-codex` / `gpt-5.6-sol`). **Do not expect the live machines to match that.** Because the seed is write-if-absent and `pi login` writes `settings.json` itself about a second after `auth.json`, whoever ran the login picked the live value: as of the 2026-09 field test k3s was on `gpt-5.6-terra` and podman/HA on `gpt-5.5`, i.e. none of the three ran the seeded value. That is by design, not drift — but it means **any cross-platform comparison must pin the model explicitly** (`pi --model <m>`), or differences get misattributed to packaging.
6. **The `woowtech-odoo-mcp` package** referenced by the live `settings.json` `packages[]` is pi-web state that code-server inherited by accident. It is **not** part of the parity set. If it is wanted later, it is added as an explicit `pi-seed` input, not by copying a `pi-cwd-*` worktree.

---

## 8. Version-bump procedure

One PR set, same day, three repos, in this order:

1. `Woow_podman_code_server_package`: bump the `ARG` in `Containerfile`, regenerate `rootfs/SHA256SUMS`, run the three smoke tests against a rebuilt image, tag → CI publishes `ghcr.io/woowtech/woow-code-server-{amd64,arm64}:<ver>`.
2. `Woow_k3s_code_server_package`: bump `image.digest` in `values-woow.yaml`, `helm template` → `deploy/rendered/`, `helm upgrade`, run smoke tests.
3. `Woow_ha_code_server_add_on`: bump the matching `ARG`s + `version:` in `config.yaml`, CHANGELOG entry, tag `vX.Y.Z` → CI publishes both arches → store sync picks it up.
4. Bump this file's version and the §2 table in the same PR set.

Never bump one target alone. The old lockstep rationale ("the shared volume schema must not drift") is gone, but a new one replaces it: **this contract is the only thing keeping the three from diverging.**

