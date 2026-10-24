# OpenDesign native agent, plugin, and Skill setup

This add-on uses the plugin and Skill registries provided by its pinned OpenDesign 0.24.1 runtime (WoowTech core image). It does not need to copy an installed OpenDesign plugin into each CLI's global extension directory.

## What is shared

| Item | OpenDesign-native behavior |
| --- | --- |
| Plugins | Install from OpenDesign's **Plugins** page. Installed plugins are persistent OpenDesign data and can be selected from projects regardless of whether Claude Code, Codex, Pi, or OpenCode runs the task. |
| Skills | OpenDesign resolves the selected plugin/Skill, combines it with project context, and stages its files in that project's `.od-skills/` directory for the active run. The source remains managed by OpenDesign. |
| Project files | All agent adapters for a project receive the same project working directory. Choosing a different project means a different working directory. |
| MCP for an OpenDesign plugin | Plugin-provided MCP capabilities are handled as part of the OpenDesign run/plugin flow and its capability controls. This is distinct from synchronizing arbitrary global MCP servers into each standalone CLI. |
| CLI account login | The add-on's **CLI Terminal** runs as the OpenDesign user with `HOME=/data/opendesign/home`. CLI login state therefore survives add-on restarts and image updates. |
| OpenCode API providers | Configure through OpenDesign **Settings → API providers**. The existing BYOK provider/model/key fields are stored in that browser's local storage. |

The upstream plugin contract is based on a portable `SKILL.md`; the OpenDesign plugin page provides installation and project-level use. OpenDesign's runtime adapters pass selected Skills to the active agent rather than installing them in every agent's home directory. See the pinned [OpenDesign Plugins documentation](https://github.com/nexu-io/open-design/blob/open-design-v0.21.1/README.md) and [Skills Protocol](https://github.com/nexu-io/open-design/blob/open-design-v0.21.1/docs/skills-protocol.md).

## First-time setup in Home Assistant

1. Start the add-on, open it from the sidebar, and choose **Local AI → Rescan**.
2. Open **Plugins**, install a plugin, then open or create a project and select that plugin.
3. Select Claude Code, Codex, Pi, or the OpenCode API runtime for the project.
4. For account-based CLI authentication, open **Plugins** and click **Open** on the built-in **CLI Terminal** plugin (`<Ingress>/console/`):
   - Claude Code: run `claude`, then `/login` when prompted.
   - Codex: run `codex login --device-auth` and finish the device authorization in your browser.
   - Pi: run `pi` and use `/login` in its TUI.
5. OpenCode API models can be configured in **Settings → API providers**, without a terminal login.

The terminal shell's startup message lists these commands. Authentication files and CLI configuration are stored in `/data/opendesign/home` on Home Assistant's persistent `/data` volume. Provider entitlements and login are still managed by each CLI's provider.

## Boundaries

- OpenDesign plugins/Skills are shared by OpenDesign runs because the same daemon selects and stages them for the active runtime. Running `claude`, `codex`, `pi`, or `opencode` manually outside OpenDesign does not automatically load the project's plugin context.
- OpenDesign's `od mcp install <agent>` command registers OpenDesign's own MCP service for an external agent. It does not copy every arbitrary MCP server between all CLI configurations. OpenDesign plugins can provide their own MCP capabilities inside OpenDesign's controlled run flow.
- Native extensions specific to one CLI (for example, Claude hooks or a Codex-only plugin package) remain governed by that CLI's format and install mechanism. They do not become portable just by installing an OpenDesign plugin.
- The CLI Terminal is an interactive shell inside the add-on container. It is routed through Home Assistant Ingress and is not a general-purpose Home Assistant host shell.
