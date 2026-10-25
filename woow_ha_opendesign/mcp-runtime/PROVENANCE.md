# Provenance of the vendored OpenDesign MCP server

`vendor/apps/opendesign/vendor/opendesign_mcp_server/od_mcp_server.py` is WoowTech's own code (owner decision
2026-10-14: treat it as WoowTech-owned).

| | |
|---|---|
| Original source (Gitea) | https://git-prod.woowtech.io/WOOWTECH/woow-mcp-server, commit `614ae663fadd91c76972f60017a76d2627bea87e`, file `apps/opendesign/opendesign_mcp_server/od_mcp_server.py` (sha256 `89caa06f96a62a6df663609fa468f00b41180970c835ceb03f3a1cf196f2e717`) |
| License | MIT, Copyright (c) 2026 WOOWTECH: `vendor/apps/opendesign/vendor/LICENSE`, byte-identical to `apps/opendesign/LICENSE` at that Gitea commit (sha256 `1b05bfafc14067beabe8885c164528c122ebf545eabe97984b222fe377143a69`) |
| Copied here from | https://github.com/WOOWTECH/Woow_ha_mcp_addons at the commit in `VENDOR.json`, which adapted the Gitea file: explicit `OD_API_BASE` (no private default host), HTTP through the reviewed `backend_policy.sync_client` (since 0.2.6: upstream's 60 s read timeout, 5 s connect), `@backend_errors` on the tool handlers (all 15 since 0.2.6) and, since 0.2.6, MCP Python SDK 2's `MCPServer` instead of `FastMCP`; its header records the Gitea snapshot. Current sha256 in `VENDOR.json` |
| Earlier history | The Gitea snapshot's file is AST-identical (apart from its module docstring) to `WOOWTECH/Woow_opendesign_mcp_server@d6d157ab9542cf18515d7168f5c8082c88b11331` (see `vendor/docs/provenance/opendesign-upstream-chain.md`) |

The rest of `vendor/` comes from WOOWTECH/Woow_ha_mcp_addons (see `vendor/LICENSE` and `vendor/THIRD_PARTY_NOTICES.md`).

Since 0.2.1 the add-on replaces four of that server's handlers at run time (`list_connectors`, `read_file`, `create_project`, `send_message`; since 0.2.6 also `list_runs`) with HA-owned bounded handlers in `ha_opendesign_mcp/od_tools.py` (see `README.md`); the vendored file itself is not modified. 0.2.1-0.2.5 vendored `apps/runtime/output_policy.py` (used by the vendored `list_runs` until the 0.4.0 runtime).

Management alignment 2026-10-23 (0.2.4-0.2.5): the VENDOR.json pin was a compatibility branch based on the prior pinned
runtime. It backported management capabilities, diagnostics, log redaction and UI only; the OpenDesign tool handlers,
policy and store migrations remained on the reviewed built-in lineage. Local runtime.py wires the fixed-backend hooks.

0.2.4 (MCP Python SDK 1.30.0): `vendor/apps/runtime/bounded_tools.py` and `vendor/apps/runtime/session_idle.py` were
byte-identical copies from commit `0e5f7de5c937d04b6fc29832c4226db1f471c3ea` of the same repository (its SDK 1.30.0
review, branch `deps/mcp-sdk-1.30-n8n-mcp-2.92.1`), recorded in `VENDOR.json` `file_sources`.

0.2.6 (MCP Python SDK 2.3.0): `source_commit` is `40a8e9e703610972254c4dae9ee9aed49231d891`, the merge of
WOOWTECH/Woow_ha_mcp_addons #22 (release 0.4.0) on its default branch `claude-delivery`: the runtime of the standalone HA
MCP add-ons (gateway, policy, store primitive, management contract and UI) with the OpenDesign server on SDK 2's
`MCPServer` and `apps/runtime/tool_error_text.py` (the port of the PaaS twin's `keep_error_text`, woow-mcp-server
`471efdf`). It replaces the built-in lineage of 0.2.4-0.2.5 (`6f420266`, a management backport on the 0.1.14 runtime).
What that lineage kept for the built-in server is now the HA overlay's (`ha_opendesign_mcp/`, see `README.md`): the
schema 3 state without migration (`state.py`), the bounded 15-tool table (`surface.py`), the list_runs projection
(`od_tools.py`, `od_rules.py`; `apps/runtime/output_policy.py` is gone from the source and no longer vendored) and
`product.runtime_version`. One vendored file comes from another commit: `vendor/apps/runtime/backend_policy.py` is the
0.2.5 pin's (`6f420266091085d45657fd2d979631d7177724d1`, `VENDOR.json` `file_sources`), byte for byte: the 0.4.0 file adds
the backend's own error text to every failure (the exception text, or the status line, request path and response body;
owner decision 2026-10-15 for the standalone add-ons), while the built-in server answers fixed public codes only, as
since 0.2.0. Every other vendored file comes from `source_commit`.
