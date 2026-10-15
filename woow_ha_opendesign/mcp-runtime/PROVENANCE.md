# Provenance of the vendored OpenDesign MCP server

`vendor/apps/opendesign/vendor/opendesign_mcp_server/od_mcp_server.py` is WoowTech's own code (owner decision
2026-10-14: treat it as WoowTech-owned).

| | |
|---|---|
| Original source (Gitea) | https://git-prod.woowtech.io/WOOWTECH/woow-mcp-server, commit `614ae663fadd91c76972f60017a76d2627bea87e`, file `apps/opendesign/opendesign_mcp_server/od_mcp_server.py` (sha256 `89caa06f96a62a6df663609fa468f00b41180970c835ceb03f3a1cf196f2e717`) |
| License | MIT, Copyright (c) 2026 WOOWTECH: `vendor/apps/opendesign/vendor/LICENSE`, byte-identical to `apps/opendesign/LICENSE` at that Gitea commit (sha256 `1b05bfafc14067beabe8885c164528c122ebf545eabe97984b222fe377143a69`) |
| Copied here from | https://github.com/WOOWTECH/Woow_ha_mcp_addons at the commit in `VENDOR.json`, which adapted the Gitea file: explicit `OD_API_BASE` (no private default host), HTTP through the reviewed `backend_policy.sync_client` with shorter timeouts, and `@backend_errors` on the tool handlers (public error codes only); its header records the Gitea snapshot. Current sha256 in `VENDOR.json` |
| Earlier history | The Gitea snapshot's file is AST-identical (apart from its module docstring) to `WOOWTECH/Woow_opendesign_mcp_server@d6d157ab9542cf18515d7168f5c8082c88b11331` (see `vendor/docs/provenance/opendesign-upstream-chain.md`) |

The rest of `vendor/` comes from WOOWTECH/Woow_ha_mcp_addons (see `vendor/LICENSE` and `vendor/THIRD_PARTY_NOTICES.md`).
