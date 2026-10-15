"""0.2.1: the gateway's OpenDesign tool table becomes the 15 tools of the PaaS OpenDesign MCP (owner decision 2026-10-15).

The pinned gateway (vendored mcp_admin_core.products.TOOLS['opendesign']) allows 11 tools. install() adds the other four
of the vendored server, each with a strict argument model (extra fields forbidden, as every vendored model):

  list_connectors  read   no arguments; the child returns od_rules.project_connectors()
  read_file        read   project UUID + FileInfo's relative path, minus secret-like names (od_rules.secret_like)
  create_project   write  prompt (1..PROMPT_MAX characters) + agent_id (a safe id pattern, default "claude")
  send_message     write  project UUID + prompt + agent_id

The table is the vendored dict itself, changed in place before the state store is opened: ProductState checks grants
against it (reviewed_grants) and make_apps() authorizes and filters tools/list with it. The child's handlers for these
four are replaced by od_tools.py. Which tools are on by default: defaults.py.
"""
from pydantic import Field, field_validator

from mcp_admin_core.policy import Tool
from mcp_admin_core.products import TOOLS, Arguments, FileInfo, Project

from . import PRODUCT, od_rules


def prompt_field():
    return Field(min_length=1, max_length=od_rules.PROMPT_MAX, description=(
        'What the OpenDesign agent should do (plain text, at most %d characters).' % od_rules.PROMPT_MAX))


def agent_field():
    return Field(default=od_rules.DEFAULT_AGENT, pattern=od_rules.AGENT_ID_PATTERN, description=(
        'OpenDesign agent id from list_agents (e.g. claude, codex, opencode). The agent must be signed in or '
        'configured in OpenDesign.'))


class ReadFile(FileInfo):
    @field_validator('file_path')
    @classmethod
    def not_secret(cls, value):
        if od_rules.secret_like(value):
            raise ValueError('secret-like file name refused')
        return value


class CreateProject(Arguments):
    prompt: str = prompt_field()
    agent_id: str = agent_field()


class SendMessage(Project):
    prompt: str = prompt_field()
    agent_id: str = agent_field()


ADDED = {
    'list_connectors': Tool(Arguments),
    'read_file': Tool(ReadFile),
    'create_project': Tool(CreateProject, write=True),
    'send_message': Tool(SendMessage, write=True),
}
# The PaaS OpenDesign MCP's 15 tools (woow-mcp-server apps/opendesign tool_registry.py).
NAMES = frozenset(('health', 'version', 'list_agents', 'list_connectors', 'list_projects', 'get_project',
                   'create_project', 'delete_project', 'list_project_files', 'read_file', 'get_file_info',
                   'send_message', 'list_runs', 'list_plugins', 'list_skills'))


def install():
    """Add the four tools to the vendored table (idempotent); refuse a pinned gateway that already defines one."""
    table = TOOLS[PRODUCT]
    for name, tool in ADDED.items():
        current = table.get(name)
        if current is None:
            table[name] = tool
        elif current is not tool:
            raise RuntimeError('pinned gateway already defines ' + name + '; review the HA overlay')
    if set(table) != NAMES:
        raise RuntimeError('unexpected OpenDesign tool table; review the HA overlay')
    return table
