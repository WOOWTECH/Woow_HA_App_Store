"""Authenticated upgrade review before ProductStore or any child is constructed.

Legacy schema1/2/3 waits for the administrator's choice. New/current installs
start normally. The default selection is all_on; no browser visit applies it.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
import signal

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import redact, ui
from .admin_auth import AdminAuthority, BadRequest
from .config import ConfigError, strict_json
from .ha_role import make_ha_admin_verifier
from .lifecycle import _join_transition
from .migration import (MigrationError, POLICIES, _existing_writer,
                        apply_migration_locked, plan_migration, read_document)


def needs_review(directory, product):
    path = Path(directory) / 'state.json'
    if not path.exists() and not path.is_symlink():
        return False
    value = read_document(path)
    # Validate before serving any report, but never construct a migrating Store.
    return plan_migration(value, product, policy='all_on').report['source_schema'] < 4


class UpgradeReview:
    def __init__(self, writer, product):
        self.writer = writer
        self.product = product
        self.completed = asyncio.Event()

    def plans(self):
        if self.writer._poisoned:
            raise ConfigError('state unavailable')
        source = read_document(self.writer.path)
        plans = {policy: plan_migration(source, self.product, policy=policy).report for policy in POLICIES}
        if plans['all_on']['source_schema'] >= 4:
            raise MigrationError('source is no longer awaiting legacy upgrade')
        return plans

    def apply(self, payload):
        if self.completed.is_set():
            raise MigrationError('upgrade already applied')
        if (not isinstance(payload, dict) or set(payload) != {'policy', 'expected_sha256'}
                or payload['policy'] not in POLICIES
                or not isinstance(payload['expected_sha256'], str)
                or len(payload['expected_sha256']) != 64
                or any(c not in '0123456789abcdef' for c in payload['expected_sha256'])):
            raise BadRequest()
        self.plans()  # rejects a replaced/current source before reporting success
        apply_migration_locked(self.writer, self.product, **payload)
        # Synchronous durable commit and completion; disconnect cannot split them.
        self.completed.set()


async def _small_body(request):
    data = bytearray()
    try:
        async with asyncio.timeout(5):
            async for part in request.stream():
                data.extend(part)
                if len(data) > 4096:
                    raise BadRequest(413)
    except ClientDisconnect:
        raise BadRequest(403) from None
    except TimeoutError:
        raise BadRequest(408) from None
    return bytes(data)


def make_upgrade_apps(review, *, verify_admin=None):
    authority = AdminAuthority(verify_admin)
    slots = asyncio.Semaphore(8)
    lock = asyncio.Lock()

    async def error(_, exc):
        status = exc.status if isinstance(exc, BadRequest) else (503 if isinstance(exc, ConfigError) else 409)
        return JSONResponse({'error': 'upgrade request unavailable; refresh review or inspect protected state'}, status_code=status)

    async def admin(request):
        user, base, csrf = authority.identity(request)
        raw = request.scope.get('raw_path', b'')
        if b'%' in raw or b'\\' in raw or request.url.query:
            raise BadRequest()
        path = request.url.path
        if base and (path == base or path.startswith(base + '/')):
            path = path[len(base):] or '/'
        apply = path == '/api/upgrade/apply' and request.method == 'POST'
        if not apply and request.method not in ('GET', 'HEAD'):
            raise BadRequest(404)
        if slots.locked():
            raise BadRequest(503)
        await slots.acquire()
        tasks = []
        try:
            raw_body = await _small_body(request)
            payload = None
            if apply:
                if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                    raise BadRequest(415)
                try:
                    payload = strict_json(raw_body)
                except (ValueError, RecursionError):
                    raise BadRequest() from None
            elif raw_body:
                raise BadRequest()
            disconnected = asyncio.Event()

            async def watch():
                while (await request.receive())['type'] != 'http.disconnect':
                    pass
                disconnected.set()

            async def action():
                try:
                    async with asyncio.timeout(2):
                        await lock.acquire()
                except TimeoutError:
                    raise BadRequest(503) from None
                try:
                    await authority.verify(user)
                    if disconnected.is_set():
                        raise BadRequest(403)
                    # No awaited work between final role check and disclosure/write.
                    if apply:
                        review.apply(payload)
                        return JSONResponse({'saved': True, 'stage': 'starting'}, status_code=202)
                    if path == '/api/bootstrap':
                        if review.completed.is_set():
                            return JSONResponse({'stage': 'starting'}, status_code=503)
                        return JSONResponse({'base_path': base, 'api_base': base + '/api',
                            'csrf': csrf, 'product': review.product, 'stage': 'upgrade_review',
                            'default_policy': 'all_on', 'plans': review.plans()})
                    if path.startswith('/api/'):
                        return Response(status_code=404)
                    return ui.response(path, base, entrypoint='upgrade')
                finally:
                    lock.release()

            watcher = asyncio.create_task(watch())
            task = asyncio.create_task(action())
            tasks = [watcher, task]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if watcher in done:
                raise BadRequest(403)
            return task.result()
        finally:
            for task in tasks:
                task.cancel()
            # The verifier owns an authenticated socket; always join cancellation.
            cancelled = False
            with anyio.CancelScope(shield=True):
                joined = asyncio.gather(*tasks, return_exceptions=True)
                while not joined.done():
                    try:
                        await asyncio.shield(joined)
                    except asyncio.CancelledError:
                        cancelled = True
            slots.release()
            if cancelled:
                raise asyncio.CancelledError

    async def pending(_):
        return JSONResponse({'error': 'upgrade_review_required'}, status_code=503,
                            headers={'Retry-After': '5'})

    exceptions = {BadRequest: error, ConfigError: error, MigrationError: error}
    admin_app = Starlette(routes=[Route('/{path:path}', admin, methods=['GET', 'HEAD', 'POST', 'PUT'])],
                          exception_handlers=exceptions, middleware=[Middleware(ui.SecurityHeaders)])
    mcp_app = Starlette(routes=[Route('/{path:path}', pending, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'])],
                        middleware=[Middleware(ui.SecurityHeaders)])
    return admin_app, mcp_app


class _Listener(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        yield


async def run_upgrade_review(args, product):
    """Return False on shutdown, True when normal runtime may start."""
    try:
        if not needs_review(args.data, product):
            return True
        with _existing_writer(args.data) as writer:
            review = UpgradeReview(writer, product)
            review.plans()
            admin, mcp = make_upgrade_apps(review, verify_admin=make_ha_admin_verifier())
            servers = [_Listener(uvicorn.Config(app, host=args.host, port=port, proxy_headers=False,
                        access_log=False, log_level='warning', server_header=False, lifespan='off',
                        limit_concurrency=32, timeout_keep_alive=5))
                       for app, port in ((admin, args.admin_port), (mcp, args.mcp_port))]
            loop = asyncio.get_running_loop()
            stop = asyncio.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
            redact.install()
            redact.guard_handlers(*redact.UVICORN_LOGGERS)
            serving = []
            waits = []
            try:
                serving = [asyncio.create_task(server.serve()) for server in servers]
                waits = [asyncio.create_task(review.completed.wait()), asyncio.create_task(stop.wait())]
                done, _ = await asyncio.wait([*serving, *waits], return_when=asyncio.FIRST_COMPLETED)
                if any(task in done for task in serving):
                    raise RuntimeError('upgrade listener stopped') from None
            finally:
                async def shutdown():
                    try:
                        for server in servers:
                            server.should_exit = True
                        for task in waits:
                            task.cancel()
                        await asyncio.gather(*waits, return_exceptions=True)
                        try:
                            async with asyncio.timeout(5):
                                await asyncio.gather(*serving)
                        except TimeoutError:
                            for task in serving:
                                task.cancel()
                            await asyncio.gather(*serving, return_exceptions=True)
                    finally:
                        for sig in (signal.SIGINT, signal.SIGTERM):
                            loop.remove_signal_handler(sig)
                await _join_transition(shutdown())
            # A stop can arrive while committed HTTP responses/listeners drain.
            # Decide only after the final awaited cleanup, before returning to startup.
            return review.completed.is_set() and not stop.is_set()
    except MigrationError:
        raise ConfigError('upgrade review unavailable; inspect protected state') from None
