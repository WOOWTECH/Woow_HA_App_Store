# mcp-runtime — built-in OpenDesign MCP server

The OpenDesign MCP server built into this add-on (since 0.2.0), replacing the separate *Woow OpenDesign MCP Server*
add-on. Design: `docs/plans/2026-10-14-builtin-mcp-design.md`. The add-on Dockerfile builds the admin UI in its
`woow-mcp-ui` stage and runs `install.sh`; the launcher starts `bin/ha-opendesign-mcp` as its fourth required
process (`start_child mcp`); nginx serves `/mcp-admin/`; `config.yaml` declares the unmapped port `8081/tcp`.

| Path | What it is |
|---|---|
| `vendor/` | Pinned copy of `WOOWTECH/Woow_ha_mcp_addons` (gateway, policy, store, lifecycle, health, HA admin verifier, admin UI sources, vendored OpenDesign tools). Never edited by hand. |
| `VENDOR.json` | Source commit and sha256 of every vendored file. |
| `PROVENANCE.md` | Origin and license of the vendored OpenDesign MCP server (WoowTech Gitea `woow-mcp-server`). |
| `vendor.sh` | Re-vendor from a local clone at a full commit sha. |
| `requirements/` | Hash-pinned wheels for the base image's Python; versions equal the source `uv.lock` files. `lock.sh` regenerates. |
| `ha_opendesign_mcp/` | Local glue: fixed loopback backend, Unix sockets for admin and child, runtime entry, and the 0.2.1 tool overlay (below). |
| `bin/ha-opendesign-mcp` | Root bootstrap started by the add-on launcher; owns `/data/mcp` and `/run/ha-opendesign-mcp`, drops to uid 10001. |
| `install.sh` | Build-time install (users `mcp` 10001 and `ha-ingress` 1002, venvs, checks). |
| `tests/verify_vendor.py` | Vendor/lock integrity check (run by `tests/run.sh`). |
| `tests/unit/` | Overlay unit tests: `test_od_rules.py` (stdlib, run by `tests/run.sh`), `test_surface.py` (management venv), `test_od_tools.py` (child venv, fake OpenDesign daemon on loopback); `run.sh <mgmt python> <child python>` runs all three, and `install.sh` runs it in the image build. Fixtures are modelled on OpenDesign 0.24.1's measured `/api/chat` events. |
| `tests/e2e/` | Container-level proof of the built add-on image (`run-proof.sh`, fake Supervisor peer, MCP/admin probes, Ingress browser check of the MCP entry, 0.2.1 tools on a real project) and `run-upgrade-proof.sh` (0.2.0 state -> 0.2.1 default grants, once). |

Re-pin to another source commit:

```sh
mcp-runtime/vendor.sh /path/to/Woow_ha_mcp_addons <full-sha>
python3 mcp-runtime/tests/verify_vendor.py
# if the source uv.lock files changed: update requirements/*.in, then requirements/lock.sh
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
