"""Approved query-only use of a BROAD Core admin capability for n8n and six products.

No URL/command/token configuration surface; no authenticated socket or allow cache.
The private connector seam exists solely for fake/owned-loopback protocol tests.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import anyio
from websockets.asyncio.client import connect

from .config import strict_json

_URL = "ws://supervisor/core/websocket"
# Core releases whose consumed contract was source-reviewed (0.1.6, docs/ha-role-core-contract.md). Supervisor's
# WebSocket proxy sends the auth frames and advertises the Core version it has recorded; the Core side consumed here
# (config/auth/list behind require_admin, its user fields, the result envelope and the system-admin group) is unchanged
# from 2026.7.2 to 2026.9.4 and in 2026.10.0 (its probatio migration changed 13 of the files; reviewed line by line);
# 2026.10.1 (0.1.9) has the same 21 files, byte-identical to 2026.10.0.
# Any other advertised version, including pre-releases, denies until reviewed and added.
_HA_VERSIONS = frozenset({"2026.7.2", "2026.7.3", "2026.7.4", "2026.8.0", "2026.8.1", "2026.8.2", "2026.8.3",
                          "2026.9.0", "2026.9.1", "2026.9.2", "2026.9.3", "2026.9.4", "2026.10.0",
                          "2026.10.1"})
_QUERY_SECONDS = 2.25  # plus <= .2s cleanup, below the gateway's 3s guard
_MAX_RESPONSE = 1024 * 1024
_MAX_CONCURRENT = 8

# A private disabled logger, not a configurable named logger. WS debug logging
# otherwise prints authentication frames and the complete user directory.
_LOGGER = logging.Logger("ha-role-private")
_LOGGER.disabled = True


class _NoRedirectConnect(connect):
    def process_redirect(self, exc):
        return exc


def valid_user_id(value):
    # No whitespace, controls, DEL, non-ASCII or comma-combined identities.
    return (isinstance(value, str) and 1 <= len(value) <= 256
            and all(33 <= ord(char) <= 126 and char != "," for char in value))


def _message(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_RESPONSE:
        raise ValueError()
    value = strict_json(raw)
    if not isinstance(value, dict):
        raise ValueError()
    return value


def _auth_message(raw, expected, version=None):
    """The advertised Core version: a reviewed one, and the same in auth_required and auth_ok."""
    value = _message(raw)
    if (set(value) != {"type", "ha_version"} or value["type"] != expected
            or not isinstance(value["ha_version"], str) or value["ha_version"] not in _HA_VERSIONS
            or (version is not None and value["ha_version"] != version)):
        raise ValueError()
    return value["ha_version"]


def _allowed(raw, subject):
    value = _message(raw)
    if (set(value) != {"id", "type", "success", "result"}
            or type(value["id"]) is not int or value["id"] != 1
            or value["type"] != "result" or value["success"] is not True
            or not isinstance(value["result"], list)):
        return False
    seen = set()
    selected = None
    for user in value["result"]:
        # Only consumed role fields are required. Core's unrelated name,
        # username and credential-provider metadata are never used or returned.
        if (not isinstance(user, dict) or not valid_user_id(user.get("id"))
                or any(type(user.get(key)) is not bool for key in
                       ("is_active", "is_owner", "system_generated"))
                or not isinstance(user.get("group_ids"), list)
                or any(not isinstance(group, str) or not 1 <= len(group) <= 256
                       for group in user["group_ids"])
                or ("local_only" in user and type(user["local_only"]) is not bool)
                or user["id"] in seen):
            return False
        seen.add(user["id"])
        if user["id"] == subject:
            selected = user
    return bool(selected is not None and selected["is_active"] is True
                and selected["system_generated"] is False
                and (selected["is_owner"] is True or "system-admin" in selected["group_ids"]))


async def _close(socket):
    # No close handshake with an unresponsive peer; release the authenticated
    # transport immediately and join library tasks before releasing our slot.
    socket.transport.abort()
    async def join():
        try:
            async with asyncio.timeout(.2):
                await socket.wait_closed()
        except Exception:
            pass
    with anyio.CancelScope(shield=True):
        task = asyncio.create_task(join())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError


class _Verifier:
    def __init__(self, connector):
        self._connector = connector
        self._active = 0

    async def __call__(self, subject):
        if not valid_user_id(subject) or self._active >= _MAX_CONCURRENT:
            return False
        # Read anew: never retain even a missing/revoked machine token snapshot.
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token or len(token) > 8192 or any(not 33 <= ord(c) <= 126 for c in token):
            return False
        # No await between admission and increment: no waiting queue, one loop.
        self._active += 1
        socket = None
        try:
            async with asyncio.timeout(_QUERY_SECONDS):
                socket = await self._connector(
                    _URL, proxy=None, compression=None, max_size=_MAX_RESPONSE,
                    max_queue=1, open_timeout=2, close_timeout=.1,
                    ping_interval=None, logger=_LOGGER, user_agent_header=None,
                )
                version = _auth_message(await socket.recv(), "auth_required")
                await socket.send(json.dumps({"type": "auth", "access_token": token}))
                _auth_message(await socket.recv(), "auth_ok", version)
                await socket.send('{"id":1,"type":"config/auth/list"}')
                return _allowed(await socket.recv(), subject)
        except Exception:
            # No exception text, frames, directory, token or fallback authority.
            return False
        finally:
            token = None
            try:
                if socket is not None:
                    await _close(socket)
            finally:
                self._active -= 1


def make_ha_admin_verifier():
    """Production factory: fixed Supervisor URL and own runtime machine token."""
    return _Verifier(_NoRedirectConnect)
