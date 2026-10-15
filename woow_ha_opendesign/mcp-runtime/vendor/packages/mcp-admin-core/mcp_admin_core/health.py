"""Protocol readiness and separate read-only backend reachability (not E2E)."""
import asyncio
import re

import httpx

from .config import ConfigError, strict_json

SESSION_ID = re.compile(r"[\x21-\x7e]{1,256}")  # as the gateway accepts from clients


async def protocol_reply(response: httpx.Response, expected_id):
    """Read one bounded JSON/SSE RPC reply. Caller owns response cleanup."""
    pending = b""
    is_sse = response.headers.get("content-type", "").split(";")[0] == "text/event-stream"
    if response.status_code != 200:
        raise ValueError("protocol unavailable")
    async for chunk in response.aiter_bytes():
        pending += chunk
        if len(pending) > 8 * 1024 * 1024:
            raise ValueError("oversize protocol response")
        if is_sse:
            # SDK uses LF; tolerate CRLF and comments/heartbeat events.
            pending = pending.replace(b"\r\n", b"\n")
            while b"\n\n" in pending:
                event, pending = pending.split(b"\n\n", 1)
                data = b"\n".join(line[5:].lstrip(b" ") for line in event.splitlines() if line.startswith(b"data:"))
                if data:
                    result = strict_json(data)
                    if result.get("id") == expected_id:
                        if result.get("jsonrpc") != "2.0" or "result" not in result:
                            raise ValueError("failed protocol response")
                        return result["result"]
    if is_sse:
        raise ValueError("missing protocol response")
    result = strict_json(pending)
    if not isinstance(result, dict) or result.get("jsonrpc") != "2.0" or result.get("id") != expected_id or "result" not in result:
        raise ValueError("invalid protocol response")
    return result["result"]


class HealthMonitor:
    def __init__(self, store, process, client, child_url="http://127.0.0.1:3000/mcp"):
        self.store, self.process, self.client, self.child_url = store, process, client, child_url
        self.backend = "unconfigured"
        self.management = "alive"

    def snapshot(self):
        return {"management": self.management, "child": self.process.health(), "backend": self.backend}

    async def check(self):
        try:
            state = self.store.load()
        except ConfigError:
            self.management = "state_error"
            self.process.ready = False
            self.backend = "unknown"
            return
        self.management = "alive"
        self.process.ready = False
        configured = getattr(state, 'configured', bool(state.backend_url and state.backend_key))
        self.backend = "unreachable" if configured else "unconfigured"
        product = getattr(state, 'product', 'n8n')
        if product != 'n8n' and not configured:
            return
        if product == 'n8n':
            probe_name, probe_args = 'n8n_list_workflows', {'limit': 1}
        else:
            from .products import health_probe
            probe_name, probe_args = health_probe(product)
        headers = {"Authorization": "Bearer " + state.child_token, "Accept": "application/json, text/event-stream"}
        session = None
        try:
            async with asyncio.timeout(8):
                async with self.client.stream("POST", self.child_url, headers=headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "local-readiness", "version": "0"}}}) as response:
                    session = response.headers.get("mcp-session-id")
                    if session is not None and not SESSION_ID.fullmatch(session):
                        session = None  # never reused, not even by the cleanup DELETE
                        raise ValueError("invalid session id")
                    if session:
                        headers["Mcp-Session-Id"] = session
                    result = await protocol_reply(response, 1)
                    if not isinstance(result, dict) or not isinstance(result.get("serverInfo"), dict) or not isinstance(result.get("protocolVersion"), str):
                        raise ValueError("invalid initialization")
                    if not SESSION_ID.fullmatch(result["protocolVersion"]):
                        raise ValueError("invalid protocol version")  # never sent as a header; the session is closed
                    headers["MCP-Protocol-Version"] = result["protocolVersion"]
                if session:
                    headers["Mcp-Session-Id"] = session
                async with self.client.stream("POST", self.child_url, headers=headers, json={
                    "jsonrpc": "2.0", "method": "notifications/initialized"}) as response:
                    if response.status_code not in (200, 202, 204):
                        raise ValueError("initialized rejected")
                async with self.client.stream("POST", self.child_url, headers=headers, json={
                    "jsonrpc": "2.0", "id": 2, "method": "ping"}) as response:
                    if await protocol_reply(response, 2) != {}:
                        raise ValueError("invalid ping")
                self.process.ready = self.process.status == "running"
            if configured:
                # Use the SAME API client, destination validation and DNS-pinned
                # connection as tools. Never perform a second Python network path.
                async with asyncio.timeout(5):
                    async with self.client.stream("POST", self.child_url, headers=headers, json={
                        "jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                            "name": probe_name, "arguments": probe_args}}) as response:
                        reply = await protocol_reply(response, 3)
                        if isinstance(reply, dict) and not reply.get("isError"):
                            for item in reply.get("content", []):
                                if isinstance(item, dict) and item.get("type") == "text":
                                    payload = strict_json(item["text"])
                                    if product == 'n8n':
                                        valid = isinstance(payload, dict) and payload.get('success') is True
                                    else:
                                        from .products import health_probe_success
                                        valid = health_probe_success(product, payload)
                                    if valid:
                                        self.backend = "reachable"
        except Exception:
            # Whatever a misbehaving child provokes (odd headers, text or shapes) leaves readiness false and
            # the backend unreachable; it must never stop the monitor, which would stop the add-on.
            pass
        finally:
            if session:
                try:
                    async with asyncio.timeout(3):
                        async with self.client.stream("DELETE", self.child_url, headers=headers):
                            pass
                except Exception:
                    pass

    async def run(self):
        while True:
            await self.check()
            await asyncio.sleep(15)
