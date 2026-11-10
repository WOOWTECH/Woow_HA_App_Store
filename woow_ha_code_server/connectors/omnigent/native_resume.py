"""Reload MCP inside an existing native Pi process; never resume or replace it.

The historic filename is retained for the connector integration contract. This
helper never calls native ensure, closes a terminal, injects a prompt, or creates
history. The extension owns the authoritative idle/persistence/identity checks.
"""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import time

_UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}")
_HASH = re.compile(r"[a-f0-9]{64}")
_CODES = frozenset({
    "SESSION_BUSY", "MCP_NATIVE_ID_CHANGED", "MCP_PERSISTENCE_MISSING",
    "MCP_NATIVE_UNAVAILABLE", "MCP_CONFIG_INVALID", "MCP_PREPARE_FAILED",
    "MCP_REQUEST_EXPIRED", "MCP_REFRESH_FAILED", "MCP_INVALID_REQUEST",
    "MCP_SYNC_FAILED", "MCP_UNSAFE_BRIDGE",
})


class NativeRefreshError(Exception):
    def __init__(self, code):
        self.code = code if code in _CODES else "MCP_REFRESH_FAILED"
        super().__init__(self.code)


def _bridge_for_session(session_id):
    from omnigent.harnesses.pi_native.bridge import bridge_dir_for_session_id
    return bridge_dir_for_session_id(session_id)


def _check_bridge(bridge):
    try:
        directory = bridge.lstat()
        endpoint = (bridge / "woow-mcp.sock").lstat()
        if (not stat.S_ISDIR(directory.st_mode) or not stat.S_ISSOCK(endpoint.st_mode)
                or directory.st_uid != os.getuid() or endpoint.st_uid != os.getuid()
                or directory.st_mode & 0o077 or endpoint.st_mode & 0o077):
            raise NativeRefreshError("MCP_UNSAFE_BRIDGE")
    except OSError:
        raise NativeRefreshError("MCP_NATIVE_UNAVAILABLE") from None


async def _exchange(bridge, payload):
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(bridge / "woow-mcp.sock"), limit=8192), timeout=3)
        peer = writer.get_extra_info("socket")
        _, uid, _ = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            raise NativeRefreshError("MCP_UNSAFE_BRIDGE")
        writer.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=35)
        result = json.loads(line)
        if not isinstance(result, dict):
            raise ValueError()
        if result.get("state") == "refused":
            raise NativeRefreshError(result.get("code"))
        return result
    except NativeRefreshError:
        raise
    except (OSError, ValueError, asyncio.TimeoutError):
        raise NativeRefreshError("MCP_NATIVE_UNAVAILABLE") from None
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


async def refresh_pi(session_id, info, *, sync):
    """Apply canonical MCP config to exactly info.external_session_id, if idle.

    ``sync`` is the caller's canonical synchronization function returning its
    configuration SHA-256. The authorized session detail must be obtained by the
    connector; request-supplied bridge/config paths are never accepted. Concurrent
    requests, including separate connector processes, receive SESSION_BUSY.
    """
    external_id = info.get("external_session_id") if isinstance(info, dict) else None
    if not isinstance(external_id, str) or not _UUID.fullmatch(external_id):
        raise NativeRefreshError("MCP_PERSISTENCE_MISSING")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
        raise NativeRefreshError("MCP_INVALID_REQUEST")
    bridge = Path(_bridge_for_session(session_id))
    _check_bridge(bridge)
    descriptor = None
    try:
        descriptor = os.open(bridge / "woow-mcp.lock",
                             os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        locked = os.fstat(descriptor)
        if not stat.S_ISREG(locked.st_mode) or locked.st_uid != os.getuid() or locked.st_mode & 0o077:
            raise NativeRefreshError("MCP_UNSAFE_BRIDGE")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise NativeRefreshError("SESSION_BUSY") from None
        payload = {"version": 1, "sessionId": session_id, "nativeSessionId": external_id,
                   "deadlineMs": int(time.time() * 1000) + 30000, "action": "probe"}
        ready = await _exchange(bridge, payload)
        if ready.get("state") != "ready" or ready.get("nativeSessionId") != external_id:
            raise NativeRefreshError("MCP_NATIVE_ID_CHANGED")
        try:
            digest = await asyncio.to_thread(sync)
        except Exception:
            raise NativeRefreshError("MCP_SYNC_FAILED") from None
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise NativeRefreshError("MCP_SYNC_FAILED")
        payload.update(action="refresh", configurationHash=digest,
                       deadlineMs=int(time.time() * 1000) + 30000)
        result = await _exchange(bridge, payload)
        if (result.get("state") != "applied" or result.get("nativeSessionId") != external_id
                or result.get("configurationHash") != digest
                or result.get("method") != "native-mcp-reload"
                or result.get("historyPreserved") is not True
                or result.get("inventoryVerified") is not True
                or result.get("toolsVerified") is not False
                or type(result.get("toolCount")) is not int or result["toolCount"] < 0):
            raise NativeRefreshError("MCP_REFRESH_FAILED")
        # Whitelist the receipt; do not forward arbitrary extension diagnostics.
        return {"sessionId": session_id, "engine": "pi", "refresh": {
            key: result[key] for key in ("state", "method", "historyPreserved", "nativeSessionId",
                                        "configurationHash", "inventoryVerified", "toolsVerified", "toolCount")}}
    except NativeRefreshError:
        raise
    except OSError:
        raise NativeRefreshError("MCP_UNSAFE_BRIDGE") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
