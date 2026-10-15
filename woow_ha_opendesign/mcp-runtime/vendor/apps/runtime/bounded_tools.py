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

from mcp.server.fastmcp.tools import base
from mcp.server.fastmcp.utilities import func_metadata


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
        for module, expected in ((base, '87626ba624d33218ffb7542140dc888453e33130fdefeadc8909d47bc600ca54'),
                                 (func_metadata, '72f72f1dc9195b91280b84c2ae8db466e8c289ca3069e18dfa8dfeb0df59deb2')):
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
