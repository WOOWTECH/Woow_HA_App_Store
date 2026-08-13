"""Async client for the Home Assistant Supervisor API.

The add-on runs with ``hassio_api: true`` / ``hassio_role: manager`` so it can
read and write its OWN options (single source of truth), restart itself to
apply them, and stream its own logs. Only ``/addons/self/*`` endpoints are
used — the GUI never touches other add-ons.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, AsyncIterator, Optional

import aiohttp

SUPERVISOR_URL = os.environ.get("SUPERVISOR_API", "http://supervisor")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")


class SupervisorError(RuntimeError):
    """Raised when the Supervisor API returns an error result."""

    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.status = status


class SupervisorClient:
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        # Set when a restart request is rejected by the Supervisor, so the
        # GUI can surface "saved but not applied" instead of silent success.
        self.last_restart_error: Optional[str] = None

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}

    async def session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(base_url=SUPERVISOR_URL)
            return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        path: str,
        json: Any = None,
        timeout: float = 15.0,
    ) -> Any:
        session = await self.session()
        try:
            async with session.request(
                method,
                path,
                json=json,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.content_type == "application/json":
                    body = await resp.json()
                else:
                    text = await resp.text()
                    if resp.status >= 400:
                        raise SupervisorError(text or resp.reason, resp.status)
                    return text
        except aiohttp.ClientError as exc:
            raise SupervisorError(f"Supervisor unreachable: {exc}", 502) from exc
        except asyncio.TimeoutError as exc:
            raise SupervisorError("Supervisor request timed out", 504) from exc

        if isinstance(body, dict) and body.get("result") == "error":
            raise SupervisorError(body.get("message") or "Supervisor error", resp.status if resp.status >= 400 else 400)
        if isinstance(body, dict):
            return body.get("data", body)
        return body

    # ── self add-on endpoints ────────────────────────────────────────────

    async def ping(self) -> bool:
        try:
            await self._request("GET", "/supervisor/ping", timeout=5.0)
            return True
        except SupervisorError:
            return False

    async def self_info(self) -> dict:
        return await self._request("GET", "/addons/self/info")

    async def get_options(self) -> dict:
        info = await self.self_info()
        return info.get("options") or {}

    async def set_options(self, options: dict) -> None:
        """Store options. The Supervisor validates them against the add-on
        schema on write and rejects invalid payloads with a message."""
        await self._request("POST", "/addons/self/options", json={"options": options})

    async def restart_self(self) -> None:
        """Restart this add-on (invoked as a background task after the HTTP
        response is sent). The Supervisor call may be cut short when this
        process is torn down mid-restart — that is expected (not an error).
        A genuine rejection is recorded so the GUI can surface it."""
        self.last_restart_error = None
        try:
            await self._request("POST", "/addons/self/restart", timeout=60.0)
        except SupervisorError as exc:
            # Timeouts / dropped connections are the normal teardown race;
            # anything else is a real rejection worth surfacing.
            if exc.status not in (502, 504):
                self.last_restart_error = str(exc)
            logging.getLogger(__name__).error(
                "Supervisor restart request did not complete: %s", exc
            )

    async def logs(self, lines: int = 400) -> str:
        """Return a snapshot of the most recent add-on log lines."""
        session = await self.session()
        headers = {**self._headers, "Range": f"entries=:-{lines}:"}
        try:
            async with session.get(
                "/addons/self/logs",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15.0),
            ) as resp:
                if resp.status >= 400:
                    raise SupervisorError(await resp.text(), resp.status)
                return await resp.text()
        except aiohttp.ClientError as exc:
            raise SupervisorError(f"Supervisor unreachable: {exc}", 502) from exc

    async def stream_logs(self) -> AsyncIterator[str]:
        """Follow the add-on log journal, yielding lines as they appear."""
        session = await self.session()
        async with session.get(
            "/addons/self/logs/follow",
            headers=self._headers,
            timeout=aiohttp.ClientTimeout(total=None, sock_read=None),
        ) as resp:
            if resp.status >= 400:
                raise SupervisorError(await resp.text(), resp.status)
            async for raw in resp.content:
                yield raw.decode(errors="replace").rstrip("\n")
