"""Log endpoints — snapshot + live WebSocket stream.

The content is the add-on's own log as served by the Supervisor, i.e. exactly
what the HA add-on Log tab shows (bashio + cloudflared lines), minus ANSI
color codes.
"""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..ingress_guard import guard
from ..instances import logwatcher

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def get_logs() -> dict:
    return {
        "lines": logwatcher.snapshot(),
        "follow_supported": logwatcher.follow_supported,
    }


@router.websocket("/stream")
async def stream_logs(ws: WebSocket) -> None:
    # HTTP middleware does not cover WebSockets — enforce the ingress-only
    # guard here as well.
    client = ws.client.host if ws.client else ""
    if not guard.allows(client):
        guard.reject(client, "WebSocket /api/logs/stream")
        await ws.close(code=4403)
        return
    await ws.accept()
    for line in logwatcher.snapshot():
        await ws.send_text(line)
    queue = logwatcher.subscribe()
    try:
        while True:
            line = await queue.get()
            await ws.send_text(line)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        logwatcher.unsubscribe(queue)
