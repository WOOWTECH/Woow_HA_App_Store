"""0.2.1: bounded handlers for the four OpenDesign tools the gateway now offers (child process, uid mcp).

The vendored server (vendor/apps/opendesign/vendor/opendesign_mcp_server/od_mcp_server.py) registers all 15 tools, but
its list_connectors, read_file, create_project and send_message return raw daemon data and raw errors, and its
/api/chat parser does not understand OpenDesign 0.24.1's events (an error whose `error` is a string, failures reported
only in `end`/`run_retry_finished`). install() replaces exactly those four handlers on the FastMCP server, before
BoundedTools wraps the synchronous tools, keeping their names and parameters (the PaaS server's):

  list_connectors()                          od_rules.project_connectors() of GET /api/connectors
  read_file(project_id, file_path)           only a regular file the project's own file list shows, not secret-like,
                                             at most 1 MiB, UTF-8 text only
  create_project(prompt, agent_id)           POST /api/chat for a new project id, followed for a bounded time and
  send_message(project_id, prompt, agent_id) size (od_rules.ChatStream); projected result; create_project registers
                                             the project (vendored _register_project) so list_projects shows it;
                                             send_message only for an existing project

Every failure is a fixed public code (vendored backend_policy.backend_errors / public_backend_error, or one of
REFUSALS): never a daemon message, path, URL or token. At most CHAT_SLOTS agent runs are followed at a time.
"""
import threading
import uuid

import httpx
from backend_policy import BackendFailure, backend_errors, sync_client

from . import od_rules

CHAT_SLOTS = 2
_chats = threading.BoundedSemaphore(CHAT_SLOTS)
REFUSALS = ('FILE_PATH_REFUSED', 'FILE_NOT_FOUND', 'FILE_TOO_LARGE', 'FILE_NOT_TEXT', 'PROJECT_NOT_FOUND',
            'INVALID_ARGUMENTS', 'BACKEND_BUSY')
REPLACED = ('list_connectors', 'read_file', 'create_project', 'send_message')


class Refused(BackendFailure):
    """A refusal with one of REFUSALS as its whole text (backend_errors passes a BackendFailure's code through)."""

    def __init__(self, code):
        assert code in REFUSALS
        self.code = code
        httpx.HTTPError.__init__(self, code)


class Server:
    """The vendored module's daemon access (its _get_client and _register_project), injectable for tests."""

    def __init__(self, od):
        self.od = od

    def client(self):
        return self.od._get_client()

    def chat_client(self):
        return sync_client(base_url=self.od.OD_API_BASE,
                           timeout=httpx.Timeout(od_rules.CHAT_READ_SECONDS, connect=5.0))


def _project_id(value):
    if not isinstance(value, str) or not od_rules.UUID.fullmatch(value):
        raise Refused('INVALID_ARGUMENTS')
    return value


def _chat_arguments(prompt, agent_id):
    if (not isinstance(prompt, str) or not 0 < len(prompt) <= od_rules.PROMPT_MAX or not isinstance(agent_id, str)
            or not od_rules.AGENT_ID.fullmatch(agent_id)):
        raise Refused('INVALID_ARGUMENTS')


def make_handlers(server):
    """The four handlers (plain functions; FastMCP derives the child's input schema from their signatures)."""

    @backend_errors
    def list_connectors() -> dict:
        """List OpenDesign's external connectors (GitHub, Notion, Google Drive...) with their status and tool names.

        Only ids, names, provider, category, status, whether it is configured and tool names are returned."""
        response = server.client().get('/api/connectors')
        return od_rules.project_connectors(response.json())

    @backend_errors
    def read_file(project_id: str, file_path: str) -> str:
        """Read a text file of a project (UTF-8, at most 1 MiB).

        Only files shown by list_project_files can be read; hidden files and secret-like names (keys, certificates,
        credentials, .env...) are refused, and so are binary files.

        Args:
            project_id: UUID of the project
            file_path: Relative path of the file within the project (e.g. 'index.html')
        """
        _project_id(project_id)
        if od_rules.file_path_problem(file_path) is not None:
            raise Refused('FILE_PATH_REFUSED')
        client = server.client()
        size = od_rules.listed_file(client.get('/api/projects/%s/files' % project_id).json(), file_path)
        if size is None:
            raise Refused('FILE_NOT_FOUND')
        if size > od_rules.READ_FILE_MAX_BYTES:
            raise Refused('FILE_TOO_LARGE')
        data = bytearray()
        with client.stream('GET', '/api/projects/%s/files/%s' % (project_id, file_path)) as response:
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > od_rules.READ_FILE_MAX_BYTES:
                    raise Refused('FILE_TOO_LARGE')
        text = od_rules.decode_text(bytes(data))
        if text is None:
            raise Refused('FILE_NOT_TEXT')
        return text

    @backend_errors
    def create_project(prompt: str, agent_id: str = od_rules.DEFAULT_AGENT) -> dict:
        """Create a new design project by sending an initial prompt to an OpenDesign AI agent.

        This runs the agent (it may use paid model credits of the signed-in account). The call follows the run for
        about 75 seconds at most; a longer run keeps going in OpenDesign (status "running": check list_runs or
        list_project_files later). The result has projectId, runId, status (succeeded, failed, cancelled, running,
        unknown), the agent's text (shortened) and, on failure, errorCode with a hint.

        Args:
            prompt: The initial design prompt (e.g. 'Create a landing page for a coffee shop')
            agent_id: Agent id from list_agents (e.g. 'claude', 'codex', 'opencode'). Default: 'claude'
        """
        _chat_arguments(prompt, agent_id)
        project_id = str(uuid.uuid4())
        result = _chat(server, project_id, prompt, agent_id)
        if result['runId'] is not None:
            # The daemon's /api/chat creates the project directory but no project record (vendored note).
            try:
                server.od._register_project(project_id, prompt)
                result['registered'] = True
            except Exception:
                result['registered'] = False
        return result

    @backend_errors
    def send_message(project_id: str, prompt: str, agent_id: str = od_rules.DEFAULT_AGENT) -> dict:
        """Send a follow-up message to an existing project's OpenDesign AI agent.

        This runs the agent (it may use paid model credits of the signed-in account). The call follows the run for
        about 75 seconds at most; a longer run keeps going in OpenDesign (status "running"). The result has the
        same fields as create_project.

        Args:
            project_id: UUID of the project to continue
            prompt: The message to send to the AI agent
            agent_id: Agent id from list_agents. Default: 'claude'
        """
        _project_id(project_id)
        _chat_arguments(prompt, agent_id)
        try:
            server.client().get('/api/projects/' + project_id)
        except httpx.HTTPError as error:
            if getattr(error, 'status', None) == 404:
                raise Refused('PROJECT_NOT_FOUND') from None
            raise
        return _chat(server, project_id, prompt, agent_id)

    return {'list_connectors': list_connectors, 'read_file': read_file, 'create_project': create_project,
            'send_message': send_message}


def _chat(server, project_id, prompt, agent_id):
    """POST /api/chat and follow its event stream within od_rules' bounds; at most CHAT_SLOTS at a time."""
    if not _chats.acquire(blocking=False):
        raise Refused('BACKEND_BUSY')
    try:
        stream = od_rules.ChatStream()
        client = server.chat_client()
        try:
            with client.stream('POST', '/api/chat', json={'message': prompt, 'agentId': agent_id,
                                                            'projectId': project_id}) as response:
                media = response.headers.get('content-type', '').split(';')[0].strip().lower()
                if media != 'text/event-stream':
                    raise ValueError('unexpected chat response')
                for chunk in response.iter_bytes():
                    if not stream.feed(chunk):
                        break
                else:
                    stream.interrupted()
        except httpx.HTTPError:
            # A transport error while reading, or while closing a stream left early. Before any event the tool fails
            # with the public code; after the run started, the result says what was seen.
            if stream.run_id is None and stream.error_code is None and stream.end is None:
                raise
            stream.interrupted()
        finally:
            try:
                client.close()
            except httpx.HTTPError:
                pass
        return od_rules.chat_result(stream, project_id)
    finally:
        _chats.release()


def install(mcp, od):
    """Replace the vendored handlers of REPLACED on the FastMCP server (same names, same parameters)."""
    from mcp.server.fastmcp.tools.base import Tool
    tools = mcp._tool_manager._tools
    handlers = make_handlers(Server(od))
    for name in REPLACED:
        if name not in tools or tools[name].is_async:
            raise RuntimeError('unexpected vendored tool ' + name)
        tools[name] = Tool.from_function(handlers[name], name=name)  # same key: tools/list order unchanged
    if len(tools) != 15:
        raise RuntimeError('unexpected OpenDesign tool count')
    return handlers
