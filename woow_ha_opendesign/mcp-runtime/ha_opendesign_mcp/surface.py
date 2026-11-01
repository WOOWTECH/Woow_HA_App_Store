"""The gateway's OpenDesign tool table: the 15 tools of the PaaS OpenDesign MCP (owner decision 2026-10-15), each with a
strict argument model (extra fields forbidden, as every vendored model).

0.2.1-0.2.5: the pinned gateway allowed 11 tools (vendored mcp_admin_core.products.TOOLS['opendesign']) and install()
added the other four of the vendored server:

  list_connectors  read   no arguments; the child returns od_rules.project_connectors()
  read_file        read   project UUID + FileInfo's relative path, minus secret-like names (od_rules.secret_like)
  create_project   write  prompt (1..PROMPT_MAX characters) + agent_id (a safe id pattern, default "claude")
  send_message     write  project UUID + prompt + agent_id

0.2.6 (runtime 0.4.0): the vendored TOOLS['opendesign'] is now the standalone add-on's full surface (its
surface.full_tools: ChildArguments, any JSON object, with the child's own inputSchema listed), and the bounded 0.1.x
table that 0.2.0-0.2.5 used remains as products.BOUNDED_TOOLS['opendesign']. TABLE is that bounded table plus the same
four tools, in 0.2.5's order; install() puts it into TOOLS['opendesign'] in place, before the state store is opened, so
the gateway keeps the bounded models and checks grants against them (state.BuiltinState, make_apps). This draft extends
only the project UUID and file path character patterns for six tools; the other model bounds stay as 0.2.5.
The child's handlers for the four tools (and,
since 0.2.6, list_runs) are replaced by od_tools.py. Which tools are on by default: defaults.py.
"""
from dataclasses import replace

from pydantic import Field, field_validator

from mcp_admin_core import products
from mcp_admin_core.policy import Tool
from mcp_admin_core.products import Arguments, FileInfo as PinnedFileInfo, Project as PinnedProject

from . import PRODUCT, od_rules


def prompt_field():
    return Field(min_length=1, max_length=od_rules.PROMPT_MAX, description=(
        'What the OpenDesign agent should do (plain text, at most %d characters).' % od_rules.PROMPT_MAX))


def agent_field():
    return Field(default=od_rules.DEFAULT_AGENT, pattern=od_rules.AGENT_ID_PATTERN, description=(
        'OpenDesign agent id from list_agents (e.g. claude, codex, opencode). The agent must be signed in or '
        'configured in OpenDesign.'))


class Project(PinnedProject):
    project_id: str = Field(pattern=od_rules.UUID_PATTERN)


class FileInfo(PinnedFileInfo):
    project_id: str = Field(pattern=od_rules.UUID_PATTERN)
    file_path: str = Field(min_length=1, max_length=256, pattern=od_rules.FILE_PATH_PATTERN)


class ReadFile(FileInfo):
    @field_validator('file_path')
    @classmethod
    def not_secret(cls, value):
        problem = od_rules.file_path_problem(value)
        if problem is not None:
            raise ValueError(problem)
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
# The 11 tools of the pinned bounded table (0.2.0-0.2.5), in its order; delete_project is its only writer.
BOUNDED = ('health', 'version', 'list_agents', 'list_projects', 'list_plugins', 'list_skills', 'get_project',
           'list_project_files', 'get_file_info', 'delete_project', 'list_runs')
# The PaaS OpenDesign MCP's 15 tools (woow-mcp-server apps/opendesign tool_registry.py).
NAMES = frozenset(('health', 'version', 'list_agents', 'list_connectors', 'list_projects', 'get_project',
                   'create_project', 'delete_project', 'list_project_files', 'read_file', 'get_file_info',
                   'send_message', 'list_runs', 'list_plugins', 'list_skills'))


def table():
    """The 15-tool table: the pinned bounded tools (refused when the pin changed them) plus ADDED."""
    bounded = products.BOUNDED_TOOLS[PRODUCT]
    for name in ADDED:
        if name in bounded:
            raise RuntimeError('pinned gateway already defines ' + name + '; review the HA overlay')
    if tuple(bounded) != BOUNDED or any(tool.child_schema for tool in bounded.values()):
        raise RuntimeError('unexpected pinned OpenDesign table; review the HA overlay')
    if {name for name, tool in bounded.items() if tool.write} != {'delete_project'}:
        raise RuntimeError('unexpected pinned OpenDesign writers; review the HA overlay')
    # Change only the four bounded entries that carry project ids/file paths.
    # Keep the vendored source byte-for-byte and retain every existing grant,
    # write flag, operation and default by replacing only each argument model.
    replacements = {
        'get_project': (PinnedProject, Project),
        'list_project_files': (PinnedProject, Project),
        'get_file_info': (PinnedFileInfo, FileInfo),
        'delete_project': (PinnedProject, Project),
    }
    for name, (pinned, _) in replacements.items():
        if bounded[name].arguments is not pinned:
            raise RuntimeError('unexpected pinned OpenDesign model: ' + name)
    result = dict(bounded)
    for name, (_, accepted) in replacements.items():
        result[name] = replace(bounded[name], arguments=accepted)
    result.update(ADDED)
    if set(result) != NAMES:
        raise RuntimeError('unexpected OpenDesign tool table; review the HA overlay')
    return result


TABLE = table()


def install():
    """Make the vendored TOOLS['opendesign'] this table, in place (idempotent); returns it."""
    current = products.TOOLS[PRODUCT]
    if len(current) != len(TABLE) or any(current.get(name) is not tool for name, tool in TABLE.items()):
        current.clear()
        current.update(TABLE)
    return current
