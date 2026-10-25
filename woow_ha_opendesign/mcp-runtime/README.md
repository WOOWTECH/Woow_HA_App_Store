# mcp-runtime — built-in OpenDesign MCP server

The OpenDesign MCP server built into this add-on (since 0.2.0), replacing the separate *Woow OpenDesign MCP Server*
add-on. Design: `docs/plans/2026-10-14-builtin-mcp-design.md`. The add-on Dockerfile builds the admin UI in its
`woow-mcp-ui` stage and runs `install.sh`; the launcher starts `bin/ha-opendesign-mcp` as its fourth required
process (`start_child mcp`); nginx serves `/mcp-admin/`; `config.yaml` declares the unmapped port `8081/tcp`.

| Path | What it is |
|---|---|
| `vendor/` | Pinned copy of `WOOWTECH/Woow_ha_mcp_addons` (gateway, policy, store, lifecycle, health, HA admin verifier, admin UI sources, vendored OpenDesign tools). Never edited by hand. |
| `VENDOR.json` | Source commit and sha256 of every vendored file; `file_sources` lists the files taken from another commit of the same repository (0.2.6: `apps/runtime/backend_policy.py`, below). |
| `PROVENANCE.md` | Origin and license of the vendored OpenDesign MCP server (WoowTech Gitea `woow-mcp-server`). |
| `vendor.sh` | Re-vendor from a local clone at a full commit sha; `<vendored file>=<full sha>` arguments take single files from another commit. |
| `requirements/` | Hash-pinned wheels for the base image's Python. Until 0.2.3 the versions of the source `uv.lock` files; 0.2.4-0.2.5 the newest releases that fit MCP Python SDK 1.x; since 0.2.6 MCP Python SDK 2.3.0, the rest at their newest releases within the vendored runtime's reviewed sources, starlette and sse-starlette in step with the WOOW PaaS and the HA MCP add-ons 0.4.0 (`lock.sh` explains). `lock.sh` regenerates. |
| `ha_opendesign_mcp/` | Local glue: fixed loopback backend, Unix sockets for admin and child, runtime entry, the 0.2.1 tool overlay and (0.2.6) the schema 3 state (below). |
| `bin/ha-opendesign-mcp` | Root bootstrap started by the add-on launcher; owns `/data/mcp` and `/run/ha-opendesign-mcp`, drops to uid 10001. |
| `install.sh` | Build-time install (users `mcp` 10001 and `ha-ingress` 1002, venvs, checks). |
| `tests/verify_vendor.py` | Vendor/lock integrity check (run by `tests/run.sh`). |
| `tests/unit/` | Overlay unit tests: `test_od_rules.py` (stdlib, run by `tests/run.sh`), `test_surface.py`, `test_state.py` (0.2.6: a 0.2.5 state stays as it is), `test_management.py`, `test_bootstrap.py` (the add-on version the root bootstrap passes on) and `test_unchanged_gateway.py` (management venv), `test_od_tools.py` (child venv, fake OpenDesign daemon on loopback), `test_child_session.py` (child venv: the session limits and request body ceiling of the child that `child.setup()` builds, idle expiry, DELETE), `test_unchanged_child.py` (child venv) and `test_gateway_child.py` (the gateway in front of the real child process: `server/discover`, the 2025 handshake, the body ceiling). `test_unchanged_*.py` compare with `fixtures/surface-0.2.5.json`, which `surface_capture.py` (child) and `gateway_capture.py` (gateway) recorded from v0.2.5: tools, schemas, results and failure texts. `run.sh <mgmt python> <child python>` runs them all, and `install.sh` runs it in the image build. Fixtures are modelled on OpenDesign 0.24.1's measured `/api/chat` events. |
| `tests/e2e/` | Container-level proof of the built add-on image (`run-proof.sh`, fake Supervisor peer, MCP/admin probes, Ingress browser check of the MCP entry, 0.2.1 tools on a real project) and `run-upgrade-proof.sh` (0.2.0 state -> 0.2.1 default grants, once). |

Re-pin to another source commit:

```sh
mcp-runtime/vendor.sh /path/to/Woow_ha_mcp_addons <full-sha> [<vendored file>=<full-sha> ...]
python3 mcp-runtime/tests/verify_vendor.py
# if the new runtime needs other package versions: update requirements/*.in, then requirements/lock.sh
```

0.2.6 was vendored with:

```sh
mcp-runtime/vendor.sh /path/to/Woow_ha_mcp_addons 40a8e9e703610972254c4dae9ee9aed49231d891 \
  apps/runtime/backend_policy.py=6f420266091085d45657fd2d979631d7177724d1
```

(0.2.4-0.2.5: `vendor.sh ... 6f420266091085d45657fd2d979631d7177724d1 apps/runtime/bounded_tools.py=0e5f7de5c937d04b6fc29832c4226db1f471c3ea
apps/runtime/session_idle.py=0e5f7de5c937d04b6fc29832c4226db1f471c3ea`.)

## 0.2.1 tool overlay (HA-owned; vendored files unchanged)

Owner decision 2026-10-15: the same 15 tools as the WOOW PaaS OpenDesign MCP, all on by default, safely bounded.

| File | Process | What it does |
|---|---|---|
| `surface.py` | management | `TABLE`: the pinned bounded table plus `list_connectors`, `read_file`, `create_project` and `send_message` (strict argument models, `extra='forbid'`); `install()` makes the vendored `products.TOOLS['opendesign']` this table, in place, before the state store opens (the store checks grants against it). 0.2.1-0.2.5 added the four to the vendored table; since 0.2.6 the vendored table is the standalone add-on's full surface and the 11 bounded tools come from `products.BOUNDED_TOOLS['opendesign']`. Refuses a pin whose bounded table changed or already defines one of the four. |
| `defaults.py` | management | `apply(store)`: once per state, grants the three writers unless the administrator disabled one, then writes `/data/mcp/ha-tool-defaults.json`; never again while that marker exists. |
| `od_tools.py` | child | `install(mcp, od)` replaces the vendored handlers of the same four tools (0.2.6: and `list_runs`) on the server (SDK 2's `MCPServer` since 0.2.6), before `BoundedTools` wraps them: projected connectors; `read_file` limited to listed, non-secret, text files up to 1 MiB; `/api/chat` followed with `od_rules.ChatStream` (time, bytes, text bounds; projected result; public error codes); at most two runs at a time; `list_runs` projected to id, projectId and status (`od_rules.run_rows`, the projection the vendored server applied until 0.2.5). |
| `od_rules.py` | both | Stdlib-only rules shared by both sides: secret-name deny-list, path rules, agent id pattern, connector projection, run projection (0.2.6), 0.24.1 SSE parser and result projection. |
| `state.py` | management | 0.2.6: `BuiltinStore`, the vendored store primitive for the schema 3 state of 0.2.0-0.2.5 (`BuiltinState`), loaded as it is and never migrated (the pinned runtime's own `ProductStore` would migrate it to schema 4 with every write granted and every disabled tool enabled again). |

Gateway protections are unchanged (Bearer / URL secret, strict accepted schemas, error redaction, session and stream limits; no child gets `SUPERVISOR_TOKEN`). The child appends `/opt/woow` to `sys.path` only to import the overlay. Re-vendoring: if a new source commit already defines one of the four tools in the bounded gateway table or changes that table, `surface.install()` fails the image build so the overlay is reviewed. 0.2.1-0.2.5 also vendored `apps/runtime/output_policy.py` (missing in 0.2.0, which broke `list_runs`); since 0.2.6 the overlay projects `list_runs` itself.

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

The source commit in `VENDOR.json` came from `feat/builtin-admin-parity-20261023` in the HA MCP source repository (0.2.4-0.2.5;
since 0.2.6 the 0.4.0 release, below). Use `vendor.sh` to refresh it; do not hand-edit the vendored copy. `tests/unit/test_management.py` checks this deployment's
identity, fixed-backend enforcement, accepted tool schemas and preservation of disabled writers through real ASGI routes.

## 0.2.4: MCP Python SDK 1.30.0

The child runs `mcp` 1.30.0 (was 1.28.1; WOOW PaaS security floor, GHSA-84m7-p3x7-pcfv) and both processes run the
newest releases that fit SDK 1.x (`requirements/lock.sh`), among them `certifi` 2026.10.23 (GHSA-6q48-6c7w-9gw2);
websockets stays on the newest 16.x (16.1.1) until the joint round of major updates with the WOOW PaaS.
In 0.2.4-0.2.5 two vendored runtime files were not those of the management commit but of the source repository's SDK 1.30.0 commit
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

## 0.2.6: MCP Python SDK 2.3.0 (runtime 0.4.0)

The vendored runtime is the HA MCP add-ons' release 0.4.0 (`40a8e9e7`, `claude-delivery`, #22), the joint MCP SDK 2 round
with the WOOW PaaS (woow-mcp-server #82). The child runs `mcp` 2.3.0 (was 1.30.0) with `mcp-types` 2.3.0; the management
process needs no SDK. The 0.2.4-0.2.5 built-in lineage (`6f420266`) is gone; what it kept for this add-on is the HA
overlay's now:

| Kept as in 0.2.5 | How |
|---|---|
| State schema 3, disabled tools, write grants, token, endpoint; an update migrates and grants nothing | `state.BuiltinStore` instead of the vendored `ProductStore` (schema 4: every write granted, every disabled tool enabled again, after an upgrade review page). `tests/unit/test_state.py` with a state v0.2.5 wrote. |
| The 15 tools, their gateway argument models and listed `inputSchema` | `surface.TABLE`: `products.BOUNDED_TOOLS['opendesign']` plus the four of 0.2.1, not the vendored full surface (any JSON object, the child's schema). |
| Tool results and failure texts (`Error executing tool <name>: <public code>`) | SDK 2's `MCPServer` shows only `Error executing tool <name>` for an exception that is not a `ToolError`; the vendored `tool_error_text.keep_error_text()` (port of the PaaS twin's, woow-mcp-server `471efdf`) runs last in `child.setup()`, as in `launch.py`. `backend_policy.py` stays the 0.2.5 pin's (public codes only; the 0.4.0 file adds the backend's own text). `list_runs` keeps its projection (overlay). |
| Session idle limit (30 minutes), 10 000 sessions, request bodies up to the gateway's ceiling | Vendored `session_idle.py` (0.4.0): SDK 2's `MCPServer` passes the SDK defaults explicitly, which it replaces as before. |
| Fixed loopback backend, Unix sockets, Ingress-only administration, `WOOW_ADDON_VERSION`, `product.runtime_version` | `runtime.py` (the vendored 0.4.0 capability contract has no `runtime_version`; `runtime.capability_snapshot` adds it). |

`tests/unit/test_unchanged_child.py` and `test_unchanged_gateway.py` compare the child's tools/list, 75 tools/call cases
(18 results, 57 failure texts) and the gateway's listing and handling of 23 tools/call requests in two policy states with
v0.2.5 on SDK 1.30.0 (`fixtures/surface-0.2.5.json`): equal.

What changes with the 0.4.0 runtime (gateway and management):

- MCP protocol: the gateway no longer forwards a client's `MCP-Protocol-Version` header with an initialize. An SDK 2
  child sends a request whose header is not an initialize-handshake revision (2026-07-28) to its 2026-07-28 handling,
  which refuses an initialize, so a client that keeps its `server/discover` header (Claude.ai, the Python SDK 2 client)
  could not connect otherwise. `server/discover` itself is still answered by the gateway (-32601) and the 2025
  handshake revisions are unchanged (`tests/unit/test_gateway_child.py`, `tests/container-smoke.sh`).
- Request bodies up to 16 MiB (was 256 KiB; the child's limit is the same), read within 60 s (was 10 s); a tools/call
  reply may take up to 330 s (was 120 s, other requests unchanged). The tools' own bounds are unchanged (prompts up to
  20,000 characters, runs followed for about 75 s).
- Rotating or revoking the token ends the requests in flight that use it at once (the shared runtime's token leases;
  the MCP Server page now says so).
- The MCP Server page shows whether the saved configuration has been applied to the tool process, and a save from a
  page opened before another change is refused until the page is reloaded (configuration revisions, `If-Match`).
- `initialize` reports `serverInfo.version` and `/api/capabilities` `product.runtime_version` `0.4.0` (was `0.1.14`).
- The vendored OpenDesign server reads with upstream's 60 s timeout (was 5 s, and 20 s for `list_agents`).
