"""Request-scoped shared-token leases; no child restart or persisted schema change."""
from __future__ import annotations

import asyncio
import hmac
from collections.abc import Awaitable, Callable

import anyio
from starlette.requests import ClientDisconnect

from .config import ConfigError


class AccessChanged(Exception):
    """The authenticated credential no longer authorizes this request."""


class TokenAccess:
    def __init__(self, store):
        self.store = store
        self.changed = asyncio.Event()

    def committed(self):
        """Publish only AFTER the token mutation has durably committed."""
        previous, self.changed = self.changed, asyncio.Event()
        previous.set()

    def lease(self, token):
        return TokenLease(self, token, self.changed)


class TokenLease:
    def __init__(self, access, token, changed):
        self.access, self.token, self.changed = access, token, changed

    def check(self):
        try:
            current = self.access.store.load().token
            valid = not self.changed.is_set() and current is not None and hmac.compare_digest(current, self.token)
        except ConfigError:
            valid = False
        if not valid:
            raise AccessChanged()

    async def invalidated(self):
        while True:
            try:
                self.check()
            except AccessChanged:
                return
            # Keep fail-closed detection for damaged/replaced state outside the admin API.
            try:
                await asyncio.wait_for(self.changed.wait(), .2)
            except TimeoutError:
                continue

    async def run(self, operation: Callable[[], Awaitable]):
        """Cancel and join pending I/O; its caller still owns acquired resources."""
        self.check()
        work = asyncio.create_task(operation())
        changed = asyncio.create_task(self.invalidated())
        try:
            await asyncio.wait((work, changed), return_when=asyncio.FIRST_COMPLETED)
            self.check()
            return await work
        finally:
            for task in (work, changed):
                if not task.done():
                    task.cancel()
            # A direct caller cancellation must not detach I/O or its cleanup.
            joined = asyncio.gather(work, changed, return_exceptions=True)
            cancelled = False
            with anyio.CancelScope(shield=True):
                while not joined.done():
                    try:
                        await asyncio.shield(joined)
                    except asyncio.CancelledError:
                        cancelled = True
            if cancelled:
                raise asyncio.CancelledError


class LeasedResponse:
    """Guard the whole response and each actual ASGI send, including backpressure."""
    def __init__(self, response, lease, refused):
        self.response, self.lease, self.refused = response, lease, refused

    async def __call__(self, scope, receive, send):
        started = False

        async def guarded_send(message):
            nonlocal started
            self.lease.check()
            if message['type'] == 'http.response.start':
                started = True
            await self.lease.run(lambda: send(message))

        try:
            await self.lease.run(lambda: self.response(scope, receive, guarded_send))
        except AccessChanged:
            if started:
                # An already-started HTTP response cannot be changed into a 401/404.
                raise ClientDisconnect() from None
            raise self.refused() from None
        finally:
            # Revocation may precede even the wrapped response's first instruction.
            owner = getattr(self.response, "owner", None)
            if owner is not None:
                await owner.close()
