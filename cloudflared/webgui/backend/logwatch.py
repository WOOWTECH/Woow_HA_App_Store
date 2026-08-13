"""Watch the add-on's own logs via the Supervisor API.

Responsibilities:
- keep a ring buffer of recent log lines for the GUI log page,
- fan out new lines to WebSocket subscribers,
- detect the ``cloudflared tunnel login`` authorization URL that the
  (unmodified, forked) ``prepare`` script prints to the log, so the setup
  wizard can show it as a clickable link / QR code instead of making the
  user dig through the log tab.
"""
from __future__ import annotations

import asyncio
import re
from collections import deque
from typing import Optional

from .supervisor import SupervisorClient, SupervisorError

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LOGIN_URL_RE = re.compile(r"https://dash\.cloudflare\.com/argotunnel\S*")

# Secrets that can appear in the add-on log at debug/trace verbosity
# (e.g. run.sh logging the full cloudflared command line, or the prepare
# script dumping tunnel.json). The HA Log tab shows them regardless (same
# as upstream) — but the GUI must not become a second exposure surface.
REDACTIONS = [
    (re.compile(r"(--token[= ])\S+"), r"\1<redacted>"),
    (re.compile(r"(\"TunnelSecret\"\s*:\s*\")[^\"]+(\")"), r"\1<redacted>\2"),
    (re.compile(r"(tunnel_token[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9+/=_-]{8,}"), r"\1<redacted>"),
    (re.compile(r"eyJ[A-Za-z0-9+/=_-]{40,}"), "<redacted-token>"),
]


def clean_line(line: str) -> str:
    line = ANSI_RE.sub("", line)
    for pattern, repl in REDACTIONS:
        line = pattern.sub(repl, line)
    return line


class LogWatcher:
    def __init__(self, client: SupervisorClient, buffer_size: int = 1000):
        self._client = client
        self._lines: deque[str] = deque(maxlen=buffer_size)
        self._subscribers: set[asyncio.Queue] = set()
        self._task: Optional[asyncio.Task] = None
        self.login_url: Optional[str] = None
        self.follow_supported: bool = True

    # ── subscriptions ────────────────────────────────────────────────────

    def snapshot(self) -> list[str]:
        return list(self._lines)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        await self._seed()
        self._task = asyncio.create_task(self._follow_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ── internals ────────────────────────────────────────────────────────

    def _ingest(self, raw: str, broadcast: bool = True) -> None:
        line = clean_line(raw)
        if not line.strip():
            return
        self._lines.append(line)
        m = LOGIN_URL_RE.search(line)
        if m:
            self.login_url = m.group(0)
        if broadcast:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(line)
                except asyncio.QueueFull:
                    pass

    async def _seed(self) -> None:
        try:
            text = await self._client.logs(lines=400)
        except SupervisorError:
            return
        for raw in text.splitlines():
            self._ingest(raw, broadcast=False)

    async def _follow_loop(self) -> None:
        failures = 0
        while True:
            try:
                async for line in self._client.stream_logs():
                    failures = 0
                    self._ingest(line)
            except asyncio.CancelledError:
                raise
            except Exception:
                failures += 1
                if failures >= 3:
                    # Older Supervisors without /logs/follow: fall back to
                    # periodic snapshot polling so the GUI still updates.
                    self.follow_supported = False
                    await self._poll_once()
            await asyncio.sleep(3 if failures < 3 else 5)

    async def _poll_once(self) -> None:
        try:
            text = await self._client.logs(lines=400)
        except SupervisorError:
            return
        lines = [clean_line(x) for x in text.splitlines() if x.strip()]
        known = set(self._lines)
        for line in lines:
            if line not in known:
                self._ingest(line)
