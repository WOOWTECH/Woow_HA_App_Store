"""HA ingress stand-in for local tests, in front of the add-on's ingress port.

Follows homeassistant/components/hassio/ingress.py and supervisor/api/ingress.py:
the same request and response header filtering, the X-Ingress-Path and
X-Forwarded-* headers, a 404 for the bare prefix without a trailing slash, and
the same WebSocket forward loop. That loop forwards messages but not the close
frame, so the browser sees a clean 1000 however the add-on closed the socket.

    python3 ha_ingress_emulator.py <listen port> <add-on ingress base URL>
"""
import asyncio
import sys

import aiohttp
from aiohttp import hdrs, web
from multidict import CIMultiDict

ADDON = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else "http://172.30.33.10:9120"

DROP_REQUEST = {
    hdrs.CONTENT_LENGTH, hdrs.CONTENT_ENCODING, hdrs.TRANSFER_ENCODING,
    hdrs.SEC_WEBSOCKET_EXTENSIONS, hdrs.SEC_WEBSOCKET_PROTOCOL,
    hdrs.SEC_WEBSOCKET_VERSION, hdrs.SEC_WEBSOCKET_KEY,
    "X-Hass-Source", "X-Supervisor-Token", "X-Hassio-Key",
    "X-Remote-User-Id", "X-Remote-User-Name", "X-Remote-User-Display-Name",
    "X-Forwarded-Prefix",
}
DROP_RESPONSE = {hdrs.TRANSFER_ENCODING, hdrs.CONTENT_LENGTH, hdrs.CONTENT_TYPE, hdrs.CONTENT_ENCODING}

PANEL = """<!doctype html><html><body style="margin:0"><iframe id="f" style="width:100vw;height:100vh;border:0"></iframe>
<script>document.getElementById("f").src=new URLSearchParams(location.search).get("src")</script></body></html>"""


def request_headers(request, token):
    headers = CIMultiDict()
    for name, value in request.headers.items():
        if name not in DROP_REQUEST and name.lower() not in (h.lower() for h in DROP_REQUEST):
            headers.add(name, value)
    headers["X-Ingress-Path"] = f"/api/hassio_ingress/{token}"
    headers["X-Remote-User-Id"] = "test-user-id"
    headers["X-Remote-User-Name"] = "test"
    headers[hdrs.X_FORWARDED_FOR] = request.remote or "127.0.0.1"
    headers[hdrs.X_FORWARDED_HOST] = request.headers.get(hdrs.X_FORWARDED_HOST, request.host)
    headers[hdrs.X_FORWARDED_PROTO] = request.headers.get(hdrs.X_FORWARDED_PROTO, request.scheme)
    return headers


async def _websocket_forward(ws_from, ws_to):
    try:
        async for msg in ws_from:
            if msg.type is aiohttp.WSMsgType.TEXT:
                await ws_to.send_str(msg.data)
            elif msg.type is aiohttp.WSMsgType.BINARY:
                await ws_to.send_bytes(msg.data)
            elif msg.type is aiohttp.WSMsgType.PING:
                await ws_to.ping(msg.data)
            elif msg.type is aiohttp.WSMsgType.PONG:
                await ws_to.pong(msg.data)
            elif ws_to.closed:
                await ws_to.close(code=ws_to.close_code, message=msg.extra)
    except RuntimeError:
        pass


async def ingress(request):
    token = request.match_info["token"]
    url = f"{ADDON}/{request.match_info['path']}"
    if request.query_string:
        url += "?" + request.query_string
    headers = request_headers(request, token)
    session = request.app["session"]

    if request.headers.get(hdrs.UPGRADE, "").lower() == "websocket":
        protocols = [p.strip() for p in request.headers.get(hdrs.SEC_WEBSOCKET_PROTOCOL, "").split(",") if p.strip()]
        ws_server = web.WebSocketResponse(protocols=protocols, autoclose=False, autoping=False, max_msg_size=16 * 1024 * 1024)
        await ws_server.prepare(request)
        try:
            async with session.ws_connect(url, headers=headers, protocols=protocols, autoclose=False,
                                          autoping=False, max_msg_size=16 * 1024 * 1024) as ws_client:
                await asyncio.wait(
                    [asyncio.create_task(_websocket_forward(ws_server, ws_client)),
                     asyncio.create_task(_websocket_forward(ws_client, ws_server))],
                    return_when=asyncio.FIRST_COMPLETED,
                )
        except aiohttp.ClientError:
            pass
        return ws_server

    async with session.request(request.method, url, headers=headers, data=request.content,
                               allow_redirects=False, auto_decompress=False) as upstream:
        out_headers = CIMultiDict(
            (k, v) for k, v in upstream.headers.items() if k not in DROP_RESPONSE)
        response = web.StreamResponse(status=upstream.status, headers=out_headers)
        response.content_type = upstream.content_type
        await response.prepare(request)
        async for chunk in upstream.content.iter_chunked(65536):
            await response.write(chunk)
        await response.write_eof()
        return response


async def not_found(request):
    return web.Response(status=404, text="HA Core 404\n")


async def panel(request):
    return web.Response(text=PANEL, content_type="text/html")


async def _session(app):
    app["session"] = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
    yield
    await app["session"].close()


app = web.Application(client_max_size=0)
app.cleanup_ctx.append(_session)
app.router.add_get("/__ha_panel.html", panel)
app.router.add_route("*", r"/api/hassio_ingress/{token:[A-Za-z0-9_-]{16,128}}/{path:.*}", ingress)
app.router.add_route("*", "/{tail:.*}", not_found)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8080, access_log=None)
