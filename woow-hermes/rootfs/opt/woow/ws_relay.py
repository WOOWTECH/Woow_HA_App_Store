"""WebSocket relay for the HA ingress adapter.

HA ingress (Core and Supervisor) forwards WebSocket messages but not the close
frame: however Hermes closes a socket, the browser gets a clean 1000. The
dashboard depends on those codes (4409 another tab took the chat over, 4410 the
agent exited; an abnormal close means reconnect). nginx sends every ingress
WebSocket here. The relay forwards it to Hermes unchanged and records how
Hermes closed it, keyed by the __wcid query parameter that ingress-shim.js
adds. The shim reads the record from /__woow/wsclose when it sees a 1000 the
page did not ask for.

Only the ingress path uses this; the LAN port talks to Hermes directly.
"""
import asyncio
import collections
import sys
import time

import aiohttp
from aiohttp import web

TTL_SECONDS = 120
MAX_RECORDS = 2000
FORWARDED_HEADERS = (
    "Cookie",
    "Origin",
    "User-Agent",
    "X-Forwarded-For",
    "X-Forwarded-Host",
    "X-Forwarded-Prefix",
    "X-Forwarded-Proto",
)
ABNORMAL = {"code": 1006, "reason": "", "wasClean": False}
# Codes an endpoint may not send in a close frame.
UNSENDABLE = {1005, 1006, 1015}


class CloseRecords:
    def __init__(self):
        self._items = collections.OrderedDict()

    def put(self, cid, record):
        now = time.monotonic()
        self._items[cid] = (now, record)
        self._items.move_to_end(cid)
        while self._items:
            oldest, _ = next(iter(self._items.values()))
            if len(self._items) <= MAX_RECORDS and now - oldest <= TTL_SECONDS:
                break
            self._items.popitem(last=False)

    def get(self, cid):
        item = self._items.get(cid)
        if item is None or time.monotonic() - item[0] > TTL_SECONDS:
            return None
        return item[1]


async def _pump(src, dst):
    """Forward messages until src closes; return src's last message."""
    while True:
        msg = await src.receive()
        if msg.type is aiohttp.WSMsgType.TEXT:
            await dst.send_str(msg.data)
        elif msg.type is aiohttp.WSMsgType.BINARY:
            await dst.send_bytes(msg.data)
        elif msg.type is aiohttp.WSMsgType.PING:
            await dst.ping(msg.data)
        elif msg.type is aiohttp.WSMsgType.PONG:
            await dst.pong(msg.data)
        else:
            return msg


async def relay(request):
    records = request.app["records"]
    query = request.query.copy()
    cid = query.pop("__wcid", None)
    url = request.app["upstream"].with_path(request.path).with_query(query)
    headers = {name: request.headers[name] for name in FORWARDED_HEADERS if name in request.headers}
    headers["Host"] = request.host
    protocols = [p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()]

    try:
        upstream = await request.app["session"].ws_connect(
            url, headers=headers, protocols=protocols,
            autoclose=False, autoping=False, max_msg_size=0,
        )
    except aiohttp.WSServerHandshakeError as exc:
        if cid:
            records.put(cid, ABNORMAL)
        return web.Response(status=exc.status or 502)
    except aiohttp.ClientError:
        if cid:
            records.put(cid, ABNORMAL)
        return web.Response(status=502)

    down = web.WebSocketResponse(
        protocols=(upstream.protocol,) if upstream.protocol else (),
        autoclose=False, autoping=False, max_msg_size=0,
    )
    await down.prepare(request)

    from_hermes = asyncio.create_task(_pump(upstream, down))
    from_browser = asyncio.create_task(_pump(down, upstream))
    done, pending = await asyncio.wait({from_hermes, from_browser}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    if from_hermes in done and not from_hermes.cancelled() and from_hermes.exception() is None:
        last = from_hermes.result()
        if last.type is aiohttp.WSMsgType.CLOSE and last.data not in UNSENDABLE:
            code, reason = last.data, last.extra or ""
            record = {"code": code, "reason": reason, "wasClean": True}
        else:
            code, reason, record = 1011, "", ABNORMAL
        # Record before closing the browser side: the shim looks it up as soon
        # as that close arrives.
        if cid:
            records.put(cid, record)
        await upstream.close()
        await down.close(code=code, message=reason.encode())
    else:
        # The browser, HA or the network ended it; Hermes did not close it.
        code = down.close_code if down.close_code and down.close_code not in UNSENDABLE else 1000
        await upstream.close(code=code)
        await down.close()
    return down


async def wsclose(request):
    record = request.app["records"].get(request.query.get("id", ""))
    if record is None:
        raise web.HTTPNotFound()
    return web.json_response(record, headers={"Cache-Control": "no-store"})


async def _session(app):
    app["session"] = aiohttp.ClientSession()
    yield
    await app["session"].close()


def make_app(upstream):
    app = web.Application()
    app["upstream"] = aiohttp.client.URL(upstream)
    app["records"] = CloseRecords()
    app.cleanup_ctx.append(_session)
    app.router.add_get("/__woow/wsclose", wsclose)
    app.router.add_get("/{tail:.*}", relay)
    return app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9121
    web.run_app(make_app("http://127.0.0.1:9119"), host="127.0.0.1", port=port, access_log=None)
