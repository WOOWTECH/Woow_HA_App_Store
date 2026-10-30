"""Host-level Dashboard control, available before any plugin API is loaded.

Installed by the operator beside the native CLI; does not open a listener or
grant shell/Kubernetes access. Every request uses Hermes's existing auth gate.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import threading
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

PREFIX = '/api/hermes-paseo-host'
HEADERS = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
           'X-Content-Type-Options': 'nosniff'}


def origin(value, allow_trailing_slash=False):
    # This adapter is installed before the plugin and survives its removal.
    # Keep the strict syntax aligned with hermes_paseo.validate_dashboard_origin.
    if not isinstance(value, str) or not value or len(value) > 2048 or re.search(r'[\s\x00-\x1f\x7f\\?#]', value):
        return None
    try:
        p = urlsplit(value)
        label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
        authority = rf'(?:{label}(?:\.{label})*\.?|\[[0-9A-Fa-f:.]+\])(?::[0-9]+)?'
        if (p.scheme not in ('http', 'https') or not p.hostname
                or not re.fullmatch(authority, p.netloc)
                or p.username is not None or p.password is not None
                or p.path not in (('', '/') if allow_trailing_slash else ('',))
                or p.query or p.fragment
                or (p.port is not None and not 1 <= p.port <= 65535)):
            return None
        return p.scheme, p.hostname.lower(), p.port or (443 if p.scheme == 'https' else 80)
    except (ValueError, TypeError):
        return None


def allowed_origins(primary, required=True):
    """The origins this Dashboard accepts, or 503 when the host cannot name one.

    A malformed ingress origin was always reported; an unset or malformed public URL
    was swallowed into an empty set instead, which is a worse failure in both
    directions: a browser request then got ORIGIN_DENIED, blaming the caller for the
    host's own misconfiguration, while a request carrying no Origin header at all was
    never compared against anything. Both now say INVALID_DASHBOARD_ORIGIN.

    `required=False` reports an unusable public URL as an empty set for the one caller
    that must keep working without it: turning the plugin off. It does NOT relax a
    malformed ingress origin, which stays closed on every route — that value is set
    deliberately, so a broken one is a signal rather than an absence.
    """
    # Preserve the public URL callback (including its historical root slash).
    expected = origin(primary, allow_trailing_slash=True)
    ingress = os.environ.get('HERMES_PASEO_INGRESS_ORIGIN')
    extra = origin(ingress) if ingress is not None else None
    if ingress is not None and extra is None:
        raise HTTPException(503, detail='INVALID_DASHBOARD_ORIGIN')
    if required and expected is None:
        raise HTTPException(503, detail='INVALID_DASHBOARD_ORIGIN')
    # Ingress supplements, never replaces, the required public URL.
    return {expected, extra} - {None} if expected else set()


def check_origin(request, primary, require_metadata=False, require_origin_config=True):
    for name in ('origin', 'sec-fetch-site', 'sec-fetch-mode', 'content-type',
                 'content-length', 'content-encoding', 'host'):
        if len(request.headers.getlist(name)) > 1:
            raise HTTPException(400, detail='INVALID_REQUEST')
    if request.query_params:
        raise HTTPException(400, detail='INVALID_REQUEST')
    site = request.headers.get('sec-fetch-site')
    if site not in (('same-origin', 'none') if require_metadata else (None, 'same-origin', 'none')):
        raise HTTPException(403, detail='ORIGIN_DENIED')
    if request.headers.get('sec-fetch-mode') in ('navigate', 'no-cors'):
        raise HTTPException(403, detail='ORIGIN_DENIED')
    expected = allowed_origins(primary, required=require_origin_config)
    actual = request.headers.get('origin')
    if actual is not None:
        # An empty set is reachable only for a caller that passed
        # require_origin_config=False. Fetch metadata is then the whole gate, and
        # require_metadata has already narrowed it to same-origin/none, which a
        # cross-site page cannot forge.
        if expected and origin(actual) not in expected:
            raise HTTPException(403, detail='ORIGIN_DENIED')
    elif request.method not in ('GET', 'HEAD', 'OPTIONS') and site != 'same-origin':
        raise HTTPException(403, detail='ORIGIN_REQUIRED')
    return expected


def supervised_pid():
    try:
        result = subprocess.run(
            ['/command/s6-svstat', '-o', 'pid', '/run/service/dashboard'],
            capture_output=True, text=True, timeout=2, check=True,
        )
        return int(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class Control:
    def __init__(self, pid_reader=supervised_pid, signaler=os.kill, delay=0.8):
        self.generation = uuid.uuid4().hex
        self.pid_reader, self.signaler, self.delay = pid_reader, signaler, delay
        self.pending = False
        self.lock = threading.Lock()

    def supported(self):
        return self.pid_reader() == os.getpid()

    def reserve(self):
        with self.lock:
            if self.pending:
                raise HTTPException(409, detail='RELOAD_PENDING')
            if not self.supported():
                raise HTTPException(503, detail='SUPERVISOR_UNAVAILABLE')
            self.pending = True

    async def restart(self):
        await asyncio.sleep(self.delay)
        try:
            # Recheck immediately before signalling. Never accept a PID from a client.
            if not self.supported():
                raise RuntimeError('Supervisor changed')
            self.signaler(os.getpid(), signal.SIGTERM)
        except Exception:
            with self.lock:
                self.pending = False


def make_router(require_auth, public_origin, enabled, control=None, lifecycle=None):
    control = control or Control()
    router = APIRouter(prefix=PREFIX)

    def check(request):
        require_auth(request)
        expected = check_origin(request, public_origin())
        if not enabled():
            raise HTTPException(403, detail='PLUGIN_DISABLED')
        return expected

    @router.get('/capabilities')
    def capabilities(request: Request):
        # check() already refused an unusable origin configuration with 503, so
        # reaching here means the accepted set is non-empty.
        check(request)
        return JSONResponse({'supported': control.supported(),
                             'generation': control.generation, 'pending': control.pending,
                             'lifecycleError': lifecycle.error if lifecycle else None},
                            headers=HEADERS)

    @router.post('/reload')
    async def reload(request: Request):
        check(request)
        if request.headers.get('content-encoding', 'identity').lower() != 'identity':
            raise HTTPException(415, detail='UNSUPPORTED_ENCODING')
        if request.headers.get('content-type', '').split(';')[0].lower().strip() != 'application/json':
            raise HTTPException(415, detail='JSON_REQUIRED')
        length = request.headers.get('content-length')
        if length is not None and (not length.isdecimal() or int(length) > 128):
            raise HTTPException(413, detail='REQUEST_TOO_LARGE')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 128:
                raise HTTPException(413, detail='REQUEST_TOO_LARGE')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate key')
                result[key] = value
            return result
        try:
            body = json.loads(data, object_pairs_hook=unique)
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(400, detail='INVALID_REQUEST') from None
        if not isinstance(body, dict) or set(body) != {'confirm'} or body['confirm'] is not True:
            raise HTTPException(400, detail='CONFIRMATION_REQUIRED')
        control.reserve()
        return JSONResponse({'ok': True, 'generation': control.generation}, status_code=202,
                            headers=HEADERS, background=BackgroundTask(control.restart))

    return router


def install(server, enabled=None, public_origin=None, control=None, lifecycle=None):
    if getattr(server.app.state, 'hermes_paseo_host_installed', False):
        return
    if enabled is None:
        from hermes_cli.plugins_cmd import _get_enabled_set, _get_disabled_set
        enabled = lambda: 'hermes-paseo' in _get_enabled_set() and 'hermes-paseo' not in _get_disabled_set()
    public_origin = public_origin or (lambda: os.environ.get('HERMES_DASHBOARD_PUBLIC_URL', ''))
    if lifecycle is None and control is None:
        from profile_lifecycle import ProfileLifecycle, prepare_profile_origin
        lifecycle = ProfileLifecycle(Path(os.environ.get('HERMES_HOME', '/opt/data')), enabled, public_origin)
        try:
            prepare_profile_origin(lifecycle.home, public_origin())
        except Exception:
            lifecycle.error = 'PROFILE_ORIGIN_SETUP_REQUIRED'
    existing = list(server.app.router.routes)
    server.app.include_router(make_router(
        server._require_token,
        public_origin, enabled, control, lifecycle,
    ))
    # Hermes calls mount_spa(app) while importing web_server. Exact control
    # routes must precede its /{full_path:path} fallback. Middleware/auth still
    # runs first, and only these fixed paths are moved ahead of existing routes.
    server.app.router.routes[:] = server.app.router.routes[len(existing):] + existing
    server.app.openapi_schema = None
    if lifecycle is not None:
        original_lifespan = server.app.router.lifespan_context
        @asynccontextmanager
        async def lifespan(app):
            async with original_lifespan(app):
                task = asyncio.create_task(lifecycle.run())
                try:
                    yield
                finally:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
        server.app.router.lifespan_context = lifespan
        async def stop_before_removal(request, call_next):
            changing = ((request.method == 'POST' and request.url.path == '/api/dashboard/agent-plugins/hermes-paseo/disable')
                        or (request.method == 'DELETE' and request.url.path == '/api/dashboard/agent-plugins/hermes-paseo'))
            if changing:
                try:
                    server._require_token(request)
                    # Turning the plugin off must not depend on the origin
                    # configuration being usable: this middleware is installed by
                    # the adapter and survives the plugin, so refusing here left a
                    # host whose public URL was unset or malformed unable to disable
                    # or remove the plugin at all. A verified native session plus
                    # same-origin fetch metadata still gate it.
                    check_origin(request, public_origin(), require_metadata=True,
                                 require_origin_config=False)
                    await asyncio.to_thread(lifecycle.stop_for_disable, False)
                except HTTPException as error:
                    return JSONResponse({'detail': error.detail}, status_code=error.status_code, headers=HEADERS)
                except Exception:
                    return JSONResponse({'detail': 'PLUGIN_STOP_PENDING'}, status_code=409, headers=HEADERS)
            response = await call_next(request)
            if changing and 200 <= response.status_code < 300:
                await asyncio.to_thread(lifecycle.mark_disabled)
            return response
        # Hermes versions register their auth gate at different startup stages.
        # Place this control inside every existing user middleware so a verified
        # native session exists before _require_token is evaluated. Gates added
        # later also stay outside it through Starlette's prepend semantics.
        server.app.user_middleware.append(Middleware(BaseHTTPMiddleware, dispatch=stop_before_removal))
    server.app.state.hermes_paseo_host_installed = True
