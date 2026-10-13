# Shared Pi, Claude Code and Codex state

At startup, the image runs `pi-agent-share-state.mjs` against the persistent
`/data/pi-agent` volume. Pi, Claude Code and Codex then use one shared skills
tree, one workspace and one portable MCP/plugin source:

| Shared item | Persistent source | Agent integration |
| --- | --- | --- |
| Agent Skills | `/data/pi-agent/skills` | Pi `~/.pi/agent/skills`, Claude `~/.claude/skills`, Codex/Pi `~/.agents/skills` are links to this tree |
| Workspace files | `/data/pi-agent/workspace` | `$HOME/workspace` points to this tree; all tools can open it |
| MCP servers | `/data/pi-agent/mcp.json` (`mcpServers`) | Pi reads it directly; Claude JSON and Codex TOML are updated from it |
| Portable plugins | `/data/pi-agent/plugins/<id>/plugin.json` | Their skills and MCP servers are loaded by all three; Pi extensions can live in `/data/pi-agent/plugins/pi` |

Claude and Codex launchers in `$HOME/.local/bin` refresh their translated MCP
settings before starting. They preserve Claude credentials and unrelated
settings. Codex's generated MCP block is marked in `~/.codex/config.toml`; other
Codex settings remain intact. New Pi sessions read the canonical MCP file;
use Pi's `/reload` after editing it in a running session.

Portable plugin layout:

```text
/data/pi-agent/plugins/example/
├── plugin.json
└── skills/
    └── example-skill/
        └── SKILL.md
```

`plugin.json` uses `{"skills":["skills/example-skill"],"mcpServers":{...}}`.
MCP server definitions use the Pi/Claude JSON shape (`command`, `args`, `env`,
`cwd`, or `url` and `headers`). Skills and MCP servers are the portable plugin
surface. Native Claude/Codex plugins and Pi extensions execute different
plugin APIs; they need an adapter for each runtime and are not made compatible
merely by sharing their files. Pi extension source belongs in
`/data/pi-agent/plugins/pi` and is loaded by Pi only.

Existing skills found in a former per-agent directory are copied into the
shared tree on first startup. Claude's credential/config file is merged without
replacing its other keys. Shared MCP names are owned by `mcp.json` and override
same-named Claude/Codex entries.
