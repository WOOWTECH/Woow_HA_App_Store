# Shared Pi, Claude Code and Codex state

At startup, the image runs `pi-agent-share-state.mjs` against the persistent
`/data/pi-agent` volume. Pi, Claude Code and Codex then use one shared skills
tree, one workspace and one Pi Web global MCP source:

| Shared item | Persistent source | Agent integration |
| --- | --- | --- |
| Agent Skills | `/data/pi-agent/skills` | Pi `~/.pi/agent/skills`, Claude `~/.claude/skills`, Codex/Pi `~/.agents/skills` are links to this tree |
| Workspace files | `/data/pi-agent/workspace` | `$HOME/workspace` points to this tree; all tools can open it |
| MCP servers | `/data/pi-agent/mcp.json` (`mcpServers`) | Pi reads it directly; Claude JSON and Codex TOML are updated from it |

Native Pi plugins/extensions stay within Pi Web and are not imported or translated for Claude Code or Codex. Skills distributed through the Pi Web Skills UI are shared because they are stored in the canonical skills tree; MCP servers configured in Pi Web are shared because its global `mcp.json` is the source of truth.

Claude and Codex launchers in `$HOME/.local/bin` refresh their translated MCP
settings before starting. They preserve Claude credentials and unrelated
settings. Codex's generated MCP block is marked in `~/.codex/config.toml`; other
Codex settings remain intact. New Pi sessions read the canonical MCP file;
use Pi's `/reload` after editing it in a running session.

Existing skills found in a former per-agent directory are copied into the
shared tree on first startup. Claude's credential/config file is merged without
replacing its other keys. Shared MCP names are owned by `mcp.json` and override
same-named Claude/Codex entries.
