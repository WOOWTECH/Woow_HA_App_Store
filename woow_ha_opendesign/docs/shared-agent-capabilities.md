# Shared agent capabilities

The add-on stores shared resources under `/data/opendesign/shared`, which is on Home Assistant's persistent `/data` volume and included in the add-on's cold backup.

| Resource | Shared behavior | Runtime details |
| --- | --- | --- |
| Agent Skills | One canonical `skills/` directory is linked into all four agents. Skill content and supporting files are the same underlying files. | Claude Code: `~/.claude/skills`; Codex: `~/.agents/skills`; Pi: `~/.pi/agent/skills`; OpenCode: `~/.config/opencode/skills`. Existing skill directories are copied into the canonical store before being retained as `.pre-shared` backups. Conflicting names are preserved under `skills/.migration-conflicts/<agent>/` and reported by startup diagnostics. |
| MCP servers | `mcp/servers.json` is the source of truth; startup generates native config for each CLI. Entries are named `ha-shared-<name>` in agent configs. | Formats differ. Server process and endpoint definitions synchronize; each agent still owns its authentication and approval flow. Existing entries outside the reserved `ha-shared-` namespace are preserved. Do not put tokens or passwords in the shared catalog. |
| Native plugins | Native plugin packages and executable hooks are not cross-compatible. | Each bundle uses `plugins/<bundle-name>/manifest.json`; portable entries reference common skills/MCP servers. Status reports whether each declared runtime adapter file exists. An adapter still must be installed and enabled through that runtime's own mechanism. See `shared-plugin-manifest.schema.json`. |
| Workspace files | `workspaces/` is the shared default working directory. | Start any CLI there (`cd "$(ha-opendesign-agents workspace)"`) to edit the same files. OpenDesign Local Agent sessions use the OpenDesign project's own working directory; files in that project are shared among agents started for that project. |

## MCP catalog

Create or edit `/data/opendesign/shared/mcp/servers.json` with this version 1 shape:

```json
{
  "version": 1,
  "servers": [
    { "name": "docs", "command": "npx", "args": ["-y", "@example/docs-mcp"] },
    { "name": "service", "url": "https://example.invalid/mcp", "headers": { "X-Region": "west" } }
  ]
}
```

Use only reviewed commands and endpoints. HTTP headers are copied to all native configs, so they must contain non-secret values. Add credentials through each agent's supported local authentication or environment mechanism. The catalog does not distribute OAuth tokens.

`enabled: false` excludes a server from generated configs. Run `ha-opendesign-agents sync` after editing the catalog; the launcher also synchronizes it during startup. `ha-opendesign-agents status` reports shared paths, skill links, and configured server count without printing configuration values.

For shared skills, create `skills/<skill-name>/SKILL.md`. Keep frontmatter compatible with the Agent Skills format. Skills authored by one agent become visible to the others through the same directory link.

The first boot preserves old skill directories as `<agent-skill-path>.pre-shared`. Check `ha-opendesign-agents status` and review any migration conflicts in `skills/.migration-conflicts/`.
