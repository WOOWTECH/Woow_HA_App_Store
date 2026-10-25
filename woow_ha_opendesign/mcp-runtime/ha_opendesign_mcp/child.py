"""Child entry of the built-in OpenDesign MCP server: the vendored apps/opendesign/launch.py on a Unix socket.

Started by the vendored lifecycle.Supervisor with the vendored child_spec environment (OD_API_BASE, PYTHONPATH of
the vendored OpenDesign tools and apps/runtime) plus HA_OD_MCP_CHILD_SOCKET. setup() repeats launch.py's own __main__
steps in the same order, and main() serves the result with uvicorn on the socket instead of 127.0.0.1:3000.

0.2.1: before BoundedTools wraps the synchronous tools, od_tools.install() replaces the vendored handlers of
list_connectors, read_file, create_project and send_message (0.2.6: and list_runs) with bounded ones (see od_tools.py).
The add-on root (/opt/woow) is APPENDED to sys.path for that import only, so nothing in it can shadow the child's own
modules.

0.2.6 (MCP Python SDK 2.3.0, runtime 0.4.0): the server is the SDK's MCPServer (1.x's FastMCP), which takes the
transport settings as arguments (1.x read mcp.settings). SDK 2 shows a client only 'Error executing tool <name>' for any
exception but a ToolError, so the vendored tool_error_text.keep_error_text() runs last, around the bounded workers, as
in launch.py: the client reads the same 'Error executing tool <name>: <code>' as with SDK 1.x. The session manager that
streamable_http_app() builds still ends a session after the vendored session_idle limit without a request (30 minutes;
WOOW_MCP_SESSION_IDLE_SECONDS in tests), holds at most the SDK's 10 000 sessions and accepts request bodies up to
session_idle.BODY_BYTES, the gateway's own ceiling (tests/unit/test_child_session.py). The loopback host keeps the
SDK's DNS-rebinding guard for the Host the gateway sends (127.0.0.1:3000).
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps' / 'opendesign'))
sys.path.append(str(ROOT))

import launch  # noqa: E402  vendored
from bounded_tools import BoundedTools  # noqa: E402  vendored apps/runtime
import opendesign_mcp_server.od_mcp_server as od  # noqa: E402  vendored (the module launch.py imports from)
import session_idle  # noqa: E402  vendored apps/runtime
from tool_error_text import keep_error_text  # noqa: E402  vendored apps/runtime (0.2.6)
import uvicorn  # noqa: E402

from ha_opendesign_mcp import od_tools  # noqa: E402

HOST = '127.0.0.1'  # what launch.py serves on; the gateway's Host header (vendored gateway child_url)
PATH = '/mcp'


def setup():
    """launch.py's __main__ steps up to serving, in its order: (ASGI app, backend client, workers)."""
    session_idle.install()  # before the session manager is built, as in launch.py
    mcp = launch.mcp
    client = launch._get_client()  # initialize once before workers start (launch.py)
    od_tools.install(mcp, od)
    workers = BoundedTools(mcp, capacity=4)
    try:
        keep_error_text(mcp)  # last, around the bounded workers (launch.py)
        return mcp.streamable_http_app(streamable_http_path=PATH, host=HOST), client, workers
    except BaseException:
        workers.close()
        client.close()
        raise


def main():
    socket_path = os.environ['HA_OD_MCP_CHILD_SOCKET']
    app, client, workers = setup()
    try:
        config = uvicorn.Config(app, uds=socket_path, log_level='warning', access_log=False, server_header=False)
        uvicorn.Server(config).run()
    finally:
        workers.close()
        client.close()


if __name__ == '__main__':
    main()
