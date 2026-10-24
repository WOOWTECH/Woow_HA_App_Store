"""0.1.8 (0.1.6 RC GATEWAY-3): end the MCP sessions a client leaves idle, in every Python child.

The SDK pinned until 0.2.2 (mcp 1.28.1, also under FastMCP 3.4.5) kept a stateful session until the client sent
DELETE or the child restarted: neither FastMCP passed the session manager's session_idle_timeout. Clients often never
DELETE (the pinned TS SDK's close() only aborts; a crashed or killed client cannot), and each idle session holds its
transport, server task and per-session state. Measured locally (0.1.8, reviews-018/idle-session-measure.md): about
50-100 KiB per session in five children and about 350 KiB in Odoo, i.e. 70-500 MiB a day for a client that leaves
one session a minute.

install() makes every StreamableHTTPSessionManager this process builds end a session after SECONDS without a
request (the SDK cancels it and drops its transport; the client's next request gets 404 and MCP requires the client
to initialize again). A child calls install() before its server builds the manager; stateless managers are left alone.

0.2.3: mcp 1.30.0 (GHSA-84m7-p3x7-pcfv) ends a session itself after DEFAULT_SESSION_IDLE_TIMEOUT (30 minutes) with
no request in flight (a request being served or an open GET stream holds it), forgets a session at its DELETE or when
its opening request fails, and caps the sessions at 10 000. Its own FastMCP (Odoo, Hermes, OpenDesign) passes that
default explicitly, so the limit here replaces the SDK's default as it replaces None; any other explicit value is
kept. The limit is the same 30 minutes unless the environment sets another (tests), and an SDK without the
parameter still refuses to start.

0.2.3: mcp 1.30.0 also answers a request body larger than max_request_body_size (default 4 MiB) with 413 before parsing
it, in both FastMCP flavours (fastmcp 3.4.5 never passes it). The gateway admits bodies up to its MAX_REQUEST (16 MiB,
0.2.0: Nextcloud uploads up to 10 MiB as base64), so the same wrapper sets BODY_BYTES (equal to it, asserted by
tests/test_session_idle.py) for every manager, stateless or not, whose caller passed nothing or the SDK's default; an
explicit other value is kept. An SDK without the parameter has no such limit and is left as it is.
"""
import functools
import inspect
import os

ENV = 'WOOW_MCP_SESSION_IDLE_SECONDS'
DEFAULT_SECONDS = 1800.0  # 30 minutes (n8n-mcp, the n8n child, reaps after 10)
BOUNDS = (1.0, 86400.0)
BODY_BYTES = 16 * 1024 * 1024  # 0.2.3: = mcp_admin_core.gateway.MAX_REQUEST, the largest body the gateway forwards


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
    sdk_default = signature.parameters['session_idle_timeout'].default  # None in mcp 1.28.1, 1800 in 1.30.0
    body = signature.parameters.get('max_request_body_size')  # 0.2.3: mcp 1.30.0 (4 MiB); absent in 1.28.1

    @functools.wraps(original)
    def __init__(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        value = bound.arguments.get('session_idle_timeout')
        if (value is None or value == sdk_default) and not bound.arguments.get('stateless', False):
            bound.arguments['session_idle_timeout'] = limit
        if body is not None and bound.arguments.get('max_request_body_size', body.default) == body.default:
            bound.arguments['max_request_body_size'] = BODY_BYTES
        original(*bound.args, **bound.kwargs)

    __init__.woow_idle_seconds = limit
    StreamableHTTPSessionManager.__init__ = __init__
    return limit
