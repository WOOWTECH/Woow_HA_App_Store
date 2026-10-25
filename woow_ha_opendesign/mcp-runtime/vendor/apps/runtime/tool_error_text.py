"""0.4.0 (MCP SDK 2): the client reads a failed tool's 1.x error text again, in the SDK MCPServer children.

mcp 1.x's FastMCP answered any exception a tool raised with isError=true and 'Error executing tool <name>: <text>'.
mcp 2.1 and later (2.3.0 pinned) keep that text only for ToolError and ResourceError: any other exception becomes
'Error executing tool <name>' and the reason goes only to the child's log. The children rely on the text: the stable
backend error codes of backend_policy (BackendFailure is an httpx.HTTPError: 'BACKEND_UNAVAILABLE: ...'), Hermes's
input guards (GuardError), the bounded workers' BACKEND_BUSY, Odoo's private readiness probe (BACKEND_UNAVAILABLE,
which HealthMonitor reads after health.TOOL_ERROR_PREFIX) and the errors odoo-mcp and OpenDesign raise themselves.

keep_error_text(mcp) wraps every registered tool once: an exception other than ToolError, ResourceError or MCPError is
raised again as ToolError(str(exc)) from it, so the client reads exactly the 1.x text; MCPError stays a JSON-RPC
error and BaseExceptions (cancellation) pass. A sync tool stays sync and an async one async; names, schemas and
argument validation do not change; calling it again wraps nothing. Port of woow-mcp-server
mcp_admin_core/tool_error_text.py (#82, 471efdf), which this child cannot import (its PYTHONPATH is the vendor tree
and apps/runtime). It relies on Tool.run turning a ToolError into 'Error executing tool <name>: <text>' and on running
tool.fn, so the SDK file is source-guarded (the same file and digest BoundedTools checks).
"""
import functools
import hashlib
import inspect
from pathlib import Path

from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.shared.exceptions import MCPError

MARK = '_woow_keeps_error_text'
PASS_THROUGH = (ToolError, ResourceError, MCPError)


def wrap(fn):
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def run(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except PASS_THROUGH:
                raise
            except Exception as exc:
                raise ToolError(str(exc)) from exc
    else:
        @functools.wraps(fn)
        def run(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except PASS_THROUGH:
                raise
            except Exception as exc:
                raise ToolError(str(exc)) from exc
    setattr(run, MARK, True)
    return run


def keep_error_text(mcp):
    """Wrap every tool of *mcp* (an mcp.server.mcpserver.MCPServer); returns the names it wrapped now (sorted)."""
    from mcp.server.mcpserver.tools import base
    if hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest() != (
            'df4074d47d76ff65cad4df903fa2543cb95ca1dd27f3501b9c2a4c0e55045a99'):
        raise RuntimeError('SDK tool error handling requires source review')
    wrapped = []
    for tool in mcp._tool_manager.list_tools():
        if getattr(tool.fn, MARK, False):
            continue
        tool.fn = wrap(tool.fn)
        wrapped.append(tool.name)
    return sorted(wrapped)
