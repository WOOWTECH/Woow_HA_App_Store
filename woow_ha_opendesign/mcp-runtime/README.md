# mcp-runtime — built-in OpenDesign MCP server

The OpenDesign MCP server built into this add-on (since 0.2.0), replacing the separate *Woow OpenDesign MCP Server*
add-on. Design: `docs/plans/2026-10-14-builtin-mcp-design.md`. The add-on Dockerfile builds the admin UI in its
`woow-mcp-ui` stage and runs `install.sh`; the launcher starts `bin/ha-opendesign-mcp` as its fourth required
process (`start_child mcp`); nginx serves `/mcp-admin/`; `config.yaml` declares the unmapped port `8081/tcp`.

| Path | What it is |
|---|---|
| `vendor/` | Pinned copy of `WOOWTECH/Woow_ha_mcp_addons` (gateway, policy, store, lifecycle, health, HA admin verifier, admin UI sources, vendored OpenDesign tools). Never edited by hand. |
| `VENDOR.json` | Source commit and sha256 of every vendored file; `file_sources` lists the files taken from another commit of the same repository (0.2.4: two runtime files, below). |
| `PROVENANCE.md` | Origin and license of the vendored OpenDesign MCP server (WoowTech Gitea `woow-mcp-server`). |
| `vendor.sh` | Re-vendor from a local clone at a full commit sha; `<vendored file>=<full sha>` arguments take single files from another commit. |
| `requirements/` | Hash-pinned wheels for the base image's Python. Until 0.2.3 the versions of the source `uv.lock` files; since 0.2.4 the newest releases that fit MCP Python SDK 1.x and the vendored runtime's reviewed sources (`lock.sh` explains). `lock.sh` regenerates. |
| `ha_opendesign_mcp/` | Local glue: fixed loopback backend, Unix sockets for admin and child, runtime entry, and the 0.2.1 tool overlay (below). |
| `bin/ha-opendesign-mcp` | Root bootstrap started by the add-on launcher; owns `/data/mcp` and `/run/ha-opendesign-mcp`, drops to uid 10001. |
| `install.sh` | Build-time install (users `mcp` 10001 and `ha-ingress` 1002, venvs, checks). |
| `tests/verify_vendor.py` | Vendor/lock integrity check (run by `tests/run.sh`). |
| `tests/unit/` | Overlay unit tests: `test_od_rules.py` (stdlib, run by `tests/run.sh`), `test_surface.py`, `test_management.py` and `test_bootstrap.py` (management venv: the add-on version the root bootstrap passes on), `test_od_tools.py` (child venv, fake OpenDesign daemon on loopback) and `test_child_session.py` (child venv: the session limits of the child that `child.setup()` builds, idle expiry, DELETE); `run.sh <mgmt python> <child python>` runs them all, and `install.sh` runs it in the image build. Fixtures are modelled on OpenDesign 0.24.1's measured `/api/chat` events. |
| `tests/e2e/` | Container-level proof of the built add-on image (`run-proof.sh`, fake Supervisor peer, MCP/admin probes, Ingress browser check of the MCP entry, 0.2.1 tools on a real project) and `run-upgrade-proof.sh` (0.2.0 state -> 0.2.1 default grants, once). |

Re-pin to another source commit:

```sh
mcp-runtime/vendor.sh /path/to/Woow_ha_mcp_addons <full-sha> [<vendored file>=<full-sha> ...]
python3 mcp-runtime/tests/verify_vendor.py
# if the new runtime needs other package versions: update requirements/*.in, then requirements/lock.sh
```

0.2.4 was vendored with:

```sh
mcp-runtime/vendor.sh /path/to/Woow_ha_mcp_addons 6f420266091085d45657fd2d979631d7177724d1 \
  apps/runtime/bounded_tools.py=0e5f7de5c937d04b6fc29832c4226db1f471c3ea \
  apps/runtime/session_idle.py=0e5f7de5c937d04b6fc29832c4226db1f471c3ea
```

## 0.2.1 tool overlay (HA-owned; vendored files unchanged)

Owner decision 2026-10-15: the same 15 tools as the WOOW PaaS OpenDesign MCP, all on by default, safely bounded.

| File | Process | What it does |
|---|---|---|
| `surface.py` | management | `install()` adds `list_connectors`, `read_file`, `create_project` and `send_message` (strict argument models, `extra='forbid'`) to the vendored `products.TOOLS['opendesign']` dict in place, before the state store opens (the store checks grants against that table). Refuses a pinned gateway that already defines one of them. |
| `defaults.py` | management | `apply(store)`: once per state, grants the three writers unless the administrator disabled one, then writes `/data/mcp/ha-tool-defaults.json`; never again while that marker exists. |
| `od_tools.py` | child | `install(mcp, od)` replaces the vendored handlers of the same four tools on the FastMCP server, before `BoundedTools` wraps them: projected connectors; `read_file` limited to listed, non-secret, text files up to 1 MiB; `/api/chat` followed with `od_rules.ChatStream` (time, bytes, text bounds; projected result; public error codes); at most two runs at a time. |
| `od_rules.py` | both | Stdlib-only rules shared by both sides: secret-name deny-list, path rules, agent id pattern, connector projection, 0.24.1 SSE parser and result projection. |

Gateway protections are unchanged (Bearer / URL secret, strict accepted schemas, error redaction, session and stream limits; no child gets `SUPERVISOR_TOKEN`). The child appends `/opt/woow` to `sys.path` only to import the overlay. Re-vendoring: if a new source commit already defines one of the four tools in the gateway table, `surface.install()` fails the image build so the overlay is reviewed. 0.2.1 also vendors `apps/runtime/output_policy.py` (missing in 0.2.0, which broke `list_runs`).

## 0.2.4: management parity (2026-10-23, from PR #15)

The built-in service now exposes the same authenticated `/api/capabilities` contract as the standalone HA and PaaS
management interfaces. It identifies its deployment as `builtin`, authority as `ha-ingress`, and backend as fixed.
The panel includes tool search, the gateway's accepted schemas, observed effective counts, saved-backend checks,
child restart, and bounded credential-redacted diagnostics. An unobserved child remains unknown.

This vendor pin is a management-only backport on the existing 0.1.14 runtime lineage. The 15-tool overlay, state schema,
existing disables, explicit write grants, Ingress authority, Unix sockets and fixed daemon address remain in effect.
It deliberately avoids the standalone 0.2.x migration that grants all tools during a legacy-state upgrade.
The capability contract reports the add-on build version as `product.version` and the compatibility core as
`product.runtime_version`; an unpackaged runtime without build metadata reports an unknown product version.
The version is the image's `WOOW_ADDON_VERSION` (Dockerfile); `bin/ha-opendesign-mcp` passes that one value (when it
has a version's shape) into the management process's otherwise fixed environment (0.2.4; without it every installed
add-on reported `unknown`), and `tests/container-smoke.sh` reads it back from `/api/capabilities`.

The source commit in `VENDOR.json` comes from `feat/builtin-admin-parity-20261023` in the HA MCP source repository.
Use `vendor.sh` to refresh it; do not hand-edit the vendored copy. `tests/unit/test_management.py` checks this deployment's
identity, fixed-backend enforcement, accepted tool schemas and preservation of disabled writers through real ASGI routes.

## 0.2.4: MCP Python SDK 1.30.0

The child runs `mcp` 1.30.0 (was 1.28.1; WOOW PaaS security floor, GHSA-84m7-p3x7-pcfv) and both processes run the
newest releases that fit SDK 1.x (`requirements/lock.sh`), among them `certifi` 2026.10.23 (GHSA-6q48-6c7w-9gw2);
websockets stays on the newest 16.x (16.1.1) until the joint round of major updates with the WOOW PaaS.
Two vendored runtime files are not those of the management commit but of the source repository's SDK 1.30.0 commit
`0e5f7de5c937d04b6fc29832c4226db1f471c3ea` (branch `deps/mcp-sdk-1.30-n8n-mcp-2.92.1`, `VENDOR.json` `file_sources`),
byte for byte; the builtin lineage (`6f420266`) has no SDK 1.30.0 review yet:

| File | Why |
|---|---|
| `apps/runtime/bounded_tools.py` | Reviewed digest of 1.30.0's `fastmcp/utilities/func_metadata.py` (only output-schema `$ref` inlining changed; `tools/base.py` is unchanged). With the 1.28.1 digest the child refuses to start (`SDK tool dispatch requires source review`). |
| `apps/runtime/session_idle.py` | 1.30.0's FastMCP passes the SDK's own 30-minute idle default explicitly; the 1.28.1 wrapper replaced only `None`, so the add-on limit (and `WOOW_MCP_SESSION_IDLE_SECONDS` in tests) no longer applied. It now replaces that default too, and sets the SDK's new request body limit (4 MiB by default) to `BODY_BYTES` (16 MiB). |

Session behaviour, as documented since 0.2.0: a session with no request for 30 minutes ends, its id answers 404 and
the client initializes again; a request in flight or an open stream keeps it; DELETE ends it at once. New in 1.30.0:
an ended session is forgotten at once (1.28.1 kept DELETEd and refused sessions registered), and at most 10 000
sessions exist at a time (the child answers 503 to another initialize, which the gateway relays). The gateway still
admits request bodies up to 256 KiB (`gateway.MAX_REQUEST` of this lineage), below the child's limit.
`tests/unit/test_child_session.py` checks all of this on the child that `child.setup()` builds. The SDK's other
1.30.0 changes (client redirects only within the endpoint's origin, the OAuth client's issuer check) concern MCP
clients; neither process uses the SDK's client or OAuth.
