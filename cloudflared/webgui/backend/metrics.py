"""Query the cloudflared metrics endpoint for tunnel status.

The forked run.sh always starts cloudflared with ``--metrics=0.0.0.0:36500``;
its ``/ready`` endpoint reports connection readiness. When cloudflared is not
running yet (e.g. the prepare script is still waiting for the Cloudflare
login), the port is closed and the tunnel is reported as "stopped".
"""
from __future__ import annotations

import os

import aiohttp

from .models import TunnelStatus

METRICS_URL = os.environ.get("CLOUDFLARED_METRICS", "http://127.0.0.1:36500")


async def tunnel_status() -> TunnelStatus:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{METRICS_URL}/ready",
                timeout=aiohttp.ClientTimeout(total=3.0),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    ready = int(data.get("readyConnections") or 0)
                    return TunnelStatus(
                        status="running" if ready > 0 else "starting",
                        ready_connections=ready,
                        metrics_reachable=True,
                    )
                return TunnelStatus(status="starting", metrics_reachable=True)
    except Exception:
        return TunnelStatus(status="stopped", metrics_reachable=False)
