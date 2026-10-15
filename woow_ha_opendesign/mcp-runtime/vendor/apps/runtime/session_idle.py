"""0.1.8 (0.1.6 RC GATEWAY-3): end the MCP sessions a client leaves idle, in every Python child.

The pinned SDK (mcp 1.28.1, also under FastMCP 3.4.5) keeps a stateful session until the client sends DELETE or
the child restarts: neither FastMCP passes the session manager's session_idle_timeout. Clients often never DELETE
(the pinned TS SDK's close() only aborts; a crashed or killed client cannot), and each idle session holds its
transport, server task and per-session state. Measured locally (0.1.8, reviews-018/idle-session-measure.md): about
50-100 KiB per session in five children and about 350 KiB in Odoo, i.e. 70-500 MiB a day for a client that leaves
one session a minute.

install() makes every StreamableHTTPSessionManager this process builds end a session after SECONDS without a
request (the SDK cancels it and drops its transport; the client's next request gets 404 and MCP requires the client
to initialize again). The gateway bounds every request to 35 s and every stream to 120 s, so no request outlives
the limit. A child calls install() before its server builds the manager; stateless managers are left alone.
"""
import functools
import inspect
import os

ENV = 'WOOW_MCP_SESSION_IDLE_SECONDS'
DEFAULT_SECONDS = 1800.0  # 30 minutes (n8n-mcp, the n8n child, reaps after 10)
BOUNDS = (1.0, 86400.0)


def seconds():
    """The limit: DEFAULT_SECONDS unless the environment sets another (tests); anything invalid refuses to start."""
    value = os.environ.get(ENV)
    if value is None:
        return DEFAULT_SECONDS
    number = float(value)  # ValueError for text: the child does not start
    if not BOUNDS[0] <= number <= BOUNDS[1]:
        raise ValueError('session idle limit out of range')
    return number


def install():
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    original = StreamableHTTPSessionManager.__init__
    if getattr(original, 'woow_idle_seconds', None) is not None:
        return original.woow_idle_seconds
    limit = seconds()
    signature = inspect.signature(original)
    if 'session_idle_timeout' not in signature.parameters:
        raise RuntimeError('pinned MCP SDK without session_idle_timeout')

    @functools.wraps(original)
    def __init__(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        if bound.arguments.get('session_idle_timeout') is None and not bound.arguments.get('stateless', False):
            bound.arguments['session_idle_timeout'] = limit
        original(*bound.args, **bound.kwargs)

    __init__.woow_idle_seconds = limit
    StreamableHTTPSessionManager.__init__ = __init__
    return limit
