# mcp-runtime — built-in OpenDesign MCP server

The OpenDesign MCP server built into this add-on (0.2.0), replacing the separate *Woow OpenDesign MCP Server*
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
| `ha_opendesign_mcp/` | Local glue: fixed loopback backend, Unix sockets for admin and child, runtime entry. |
| `bin/ha-opendesign-mcp` | Root bootstrap started by the add-on launcher; owns `/data/mcp` and `/run/ha-opendesign-mcp`, drops to uid 10001. |
| `install.sh` | Build-time install (users `mcp` 10001 and `ha-ingress` 1002, venvs, checks). |
| `tests/verify_vendor.py` | Vendor/lock integrity check (run by `tests/run.sh`). |
| `tests/e2e/` | Container-level proof of the built add-on image (`run-proof.sh`, fake Supervisor peer, MCP/admin probes, Ingress browser check of the MCP entry). |

Re-pin to another source commit:

```sh
mcp-runtime/vendor.sh /path/to/Woow_ha_mcp_addons <full-sha>
python3 mcp-runtime/tests/verify_vendor.py
# if the source uv.lock files changed: update requirements/*.in, then requirements/lock.sh
```
