"""Child entry of the built-in OpenDesign MCP server: the vendored apps/opendesign/launch.py on a Unix socket.

Started by the vendored lifecycle.Supervisor with the vendored child_spec environment (OD_API_BASE, PYTHONPATH of
the vendored OpenDesign tools and apps/runtime) plus HA_OD_MCP_CHILD_SOCKET. Importing launch applies its
/api/agents read-timeout patch; main() repeats launch.py's own __main__ steps in the same order, except that
uvicorn binds the socket instead of 127.0.0.1:3000.

0.2.1: before BoundedTools wraps the synchronous tools, od_tools.install() replaces the vendored handlers of
list_connectors, read_file, create_project and send_message with bounded ones (see od_tools.py). The add-on root
(/opt/woow) is APPENDED to sys.path for that import only, so nothing in it can shadow the child's own modules.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps' / 'opendesign'))
sys.path.append(str(ROOT))

import launch  # noqa: E402  vendored; module import patches od._api_get
from bounded_tools import BoundedTools  # noqa: E402  vendored apps/runtime
import session_idle  # noqa: E402  vendored apps/runtime
import uvicorn  # noqa: E402

from ha_opendesign_mcp import od_tools  # noqa: E402


def main():
    socket_path = os.environ['HA_OD_MCP_CHILD_SOCKET']
    session_idle.install()  # before the session manager is built, as in launch.py
    mcp = launch.mcp
    mcp.settings.streamable_http_path = '/mcp'
    client = launch._get_client()  # initialize once before workers start (launch.py)
    od_tools.install(mcp, launch.od)
    workers = BoundedTools(mcp, capacity=4)
    try:
        config = uvicorn.Config(mcp.streamable_http_app(), uds=socket_path, log_level='warning',
                                access_log=False, server_header=False)
        uvicorn.Server(config).run()
    finally:
        workers.close()
        client.close()


if __name__ == '__main__':
    main()
