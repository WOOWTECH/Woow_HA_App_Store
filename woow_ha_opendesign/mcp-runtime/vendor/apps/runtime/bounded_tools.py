"""Bound synchronous SDK tools without changing schemas or enabled surface.

No waiting work queue: one admitted job per worker. Cancellation never releases
capacity until the *actual* function returns. Process-group supervision owns the
hard shutdown deadline, including a peer that trickles bytes forever or hung DNS.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import contextvars
import functools
import hashlib
from pathlib import Path
import threading


class OwnedWorkers:
    """Owned threads for synchronous backend work, with immediate admission or BACKEND_BUSY."""

    def __init__(self, capacity, prefix='backend-tool'):
        self.slots = threading.BoundedSemaphore(capacity)
        self.executor = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix=prefix)

    async def run(self, fn, /, **kwargs):
        if not self.slots.acquire(blocking=False):
            raise ValueError('BACKEND_BUSY')
        try:
            future = self.executor.submit(contextvars.copy_context().run, functools.partial(fn, **kwargs))
        except BaseException:
            self.slots.release()
            raise
        future.add_done_callback(lambda _: self.slots.release())
        # Do not cancel the future or free a slot when the HTTP peer leaves.
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        return await asyncio.shield(wrapped)

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)


class BoundedTools(OwnedWorkers):
    def __init__(self, mcp, capacity):
        # 0.4.0 (mcp 2.3.0): FastMCP is MCPServer and its modules moved to mcp.server.mcpserver. Imported here, not at
        # module level: the archived Odoo Manage child (still mcp 1.30.0) imports this file for OwnedWorkers only.
        # Reviewed: Tool.run validates the arguments, then FuncMetadata.call_fn awaits tool.fn when tool.is_async and
        # otherwise runs it on an anyio worker thread (mcp 1.x called a sync tool on the event loop); a ToolError
        # keeps its text ('Error executing tool <name>: ...'), any other exception becomes the bare
        # 'Error executing tool <name>' (tool_error_text.keep_error_text restores the 1.x text). Setting tool.fn and
        # tool.is_async below still routes every sync tool through this class's owned workers, and nothing else.
        from mcp.server.mcpserver.tools import base
        from mcp.server.mcpserver.utilities import func_metadata
        for module, expected in ((base, 'df4074d47d76ff65cad4df903fa2543cb95ca1dd27f3501b9c2a4c0e55045a99'),
                                 (func_metadata, '83c857d42880f520f9ee34b2e180c3838e296b1240fb413c6212a087fbcbef54')):
            if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != expected:
                raise RuntimeError('SDK tool dispatch requires source review')
        super().__init__(capacity)
        for tool in mcp._tool_manager.list_tools():
            if not tool.is_async:
                tool.fn = self.wrap(tool.fn)
                tool.is_async = True

    def wrap(self, fn):
        @functools.wraps(fn)
        async def bounded(**kwargs):
            return await self.run(fn, **kwargs)
        return bounded
