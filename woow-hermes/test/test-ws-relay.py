"""Tests for rootfs/opt/woow/ws_relay.py.

A fake Hermes closes WebSockets in the ways the dashboard cares about. The
client connects through a copy of HA's ingress forward loop (which turns every
close into 1000) and then the relay; the relay's /__woow/wsclose must still
report how Hermes closed each socket.
"""
import asyncio
import importlib.util
import pathlib
import sys

import aiohttp
from aiohttp import web

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ws_relay", HERE.parent / "rootfs/opt/woow/ws_relay.py")
ws_relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws_relay)

HERMES, RELAY, HA = 18911, 18912, 18913


async def fake_hermes(request):
    if request.path == "/api/refuse":
        raise web.HTTPForbidden()
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(request)
    await ws.send_json({
        "query": dict(request.query),
        "cookie": request.headers.get("Cookie"),
        "prefix": request.headers.get("X-Forwarded-Prefix"),
        "host": request.headers.get("Host"),
    })
    if request.path == "/api/pty":
        await ws.close(code=4409, message=b"superseded")
    elif request.path == "/api/exit":
        await ws.close(code=4410)
    elif request.path == "/api/drop":
        request.transport.close()
    elif request.path == "/api/echo":
        async for msg in ws:
            if msg.type is aiohttp.WSMsgType.TEXT:
                await ws.send_str(msg.data)
            elif msg.type is aiohttp.WSMsgType.BINARY:
                await ws.send_bytes(msg.data)
    return ws


# HA Core / Supervisor ingress: homeassistant/components/hassio/ingress.py.
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


async def ha_ingress(request):
    ws_server = web.WebSocketResponse(autoclose=False, autoping=False, max_msg_size=0)
    await ws_server.prepare(request)
    url = f"http://127.0.0.1:{RELAY}{request.path_qs}"
    headers = {"Cookie": "a=1", "X-Forwarded-Prefix": "/api/hassio_ingress/tok"}
    async with aiohttp.ClientSession() as s:
        try:
            async with s.ws_connect(url, headers=headers, autoclose=False, autoping=False, max_msg_size=0) as ws_client:
                await asyncio.wait(
                    [asyncio.create_task(_websocket_forward(ws_server, ws_client)),
                     asyncio.create_task(_websocket_forward(ws_client, ws_server))],
                    return_when=asyncio.FIRST_COMPLETED,
                )
        except aiohttp.WSServerHandshakeError:
            pass
    return ws_server


async def lookup(http, cid):
    async with http.get(f"http://127.0.0.1:{RELAY}/__woow/wsclose", params={"id": cid}) as r:
        return (r.status, await r.json() if r.status == 200 else None)


async def through_ha(http, path, cid):
    async with http.ws_connect(f"http://127.0.0.1:{HA}{path}?__wcid={cid}&ticket=t", max_msg_size=0) as ws:
        first = await ws.receive_json()
        msgs = [m async for m in ws]
        return first, ws.close_code, msgs


async def main():
    runners = []
    for port, handler in ((HERMES, fake_hermes), (HA, ha_ingress)):
        app = web.Application()
        app.router.add_route("GET", "/{tail:.*}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        runners.append(runner)
    relay_runner = web.AppRunner(ws_relay.make_app(f"http://127.0.0.1:{HERMES}"))
    await relay_runner.setup()
    await web.TCPSite(relay_runner, "127.0.0.1", RELAY).start()
    runners.append(relay_runner)

    try:
        async with aiohttp.ClientSession() as http:
            # HA really does flatten the code: this is the bug being fixed.
            first, code, _ = await through_ha(http, "/api/pty", "c1")
            assert code == 1000, code
            assert await lookup(http, "c1") == (200, {"code": 4409, "reason": "superseded", "wasClean": True})
            # __wcid is stripped, the rest of the query and the headers reach Hermes.
            assert first["query"] == {"ticket": "t"}, first
            assert first["cookie"] == "a=1" and first["prefix"] == "/api/hassio_ingress/tok", first
            assert first["host"] == f"127.0.0.1:{RELAY}", first

            await through_ha(http, "/api/exit", "c2")
            assert await lookup(http, "c2") == (200, {"code": 4410, "reason": "", "wasClean": True})

            # Hermes vanished mid-stream (add-on stopping): an abnormal close.
            await through_ha(http, "/api/drop", "c3")
            assert await lookup(http, "c3") == (200, {"code": 1006, "reason": "", "wasClean": False})

            # Hermes refused the upgrade: the LAN port sees a failed handshake.
            async with http.ws_connect(f"http://127.0.0.1:{HA}/api/refuse?__wcid=c4") as ws:
                _ = [m async for m in ws]
            assert await lookup(http, "c4") == (200, {"code": 1006, "reason": "", "wasClean": False})

            # Messages pass through unchanged, including large binary frames;
            # a close from the browser side leaves no record.
            big = bytes(range(256)) * (8 * 4096)
            async with http.ws_connect(f"http://127.0.0.1:{HA}/api/echo?__wcid=c5", max_msg_size=0) as ws:
                await ws.receive_json()
                await ws.send_str("hello")
                assert (await ws.receive()).data == "hello"
                await ws.send_bytes(big)
                assert (await ws.receive()).data == big
                await ws.close()
            await asyncio.sleep(0.2)
            assert await lookup(http, "c5") == (404, None)

            assert await lookup(http, "never") == (404, None)
    finally:
        for runner in runners:
            await runner.cleanup()
    print("ws relay: ok")


asyncio.run(main())
