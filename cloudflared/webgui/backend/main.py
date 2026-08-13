"""Cloudflared Web GUI — FastAPI application entry point.

Served exclusively through Home Assistant Ingress (no host port is
published), so authentication is handled by Home Assistant itself. As
defense in depth, requests are only accepted from the Ingress proxy — see
``ingress_guard`` for the trust boundary and its diagnostics.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .ingress_guard import guard
from .instances import logwatcher, supervisor
from .routers import health, logs, options, wizard

STATIC_DIR = Path(os.environ.get("WEBGUI_STATIC", "/opt/webgui/static"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await logwatcher.start()
    yield
    await logwatcher.stop()
    await supervisor.close()


app = FastAPI(title="Cloudflared Web GUI", lifespan=lifespan)


@app.middleware("http")
async def ingress_only(request: Request, call_next):
    client = request.client.host if request.client else ""
    if not guard.allows(client):
        guard.reject(client, f"{request.method} {request.url.path}")
        return JSONResponse(
            {"detail": "Access is only allowed through Home Assistant Ingress"},
            status_code=403,
        )
    return await call_next(request)


app.include_router(health.router)
app.include_router(options.router)
app.include_router(logs.router)
app.include_router(wizard.router)

# Mounted last so /api/* keeps precedence. All frontend assets use relative
# paths (vite base './' + hash routing) so the app works under the dynamic
# ingress path prefix without any base-path configuration.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
