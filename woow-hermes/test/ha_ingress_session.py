"""Open a Home Assistant ingress session for an add-on, the way the HA frontend does.

    python3 ha_ingress_session.py <ha-base-url> <addon-slug> <token-file>

Prints JSON {"ingress_url": ..., "session": ...}. The session goes in an
`ingress_session` cookie with Path=/api/hassio_ingress/. Keep the output private.
"""
import asyncio
import json
import pathlib
import sys

import aiohttp


async def main(base, slug, token_file):
    token = pathlib.Path(token_file).read_text().strip()
    ws_url = base.rstrip("/").replace("http", "ws", 1) + "/api/websocket"
    async with aiohttp.ClientSession() as http, http.ws_connect(ws_url) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        if (await ws.receive_json()).get("type") != "auth_ok":
            sys.exit("HA rejected the token")

        async def supervisor(msg_id, endpoint, method):
            await ws.send_json({"id": msg_id, "type": "supervisor/api", "endpoint": endpoint, "method": method})
            reply = await ws.receive_json()
            if not reply.get("success"):
                sys.exit(f"{endpoint}: {reply.get('error')}")
            return reply["result"]

        info = await supervisor(1, f"/addons/{slug}/info", "get")
        session = await supervisor(2, "/ingress/session", "post")
        print(json.dumps({"ingress_url": info["ingress_url"], "session": session["session"]}))


asyncio.run(main(*sys.argv[1:4]))
