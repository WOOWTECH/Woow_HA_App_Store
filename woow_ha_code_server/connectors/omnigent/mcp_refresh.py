"""Refresh one existing native Codex thread without changing its model or auth."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile

import tomlkit


class RefreshError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def merge_managed_servers(existing, source, managed_names):
    """Replace owned definitions including removals; retain the private relay."""
    document = tomlkit.parse(existing)
    incoming = tomlkit.parse(source).get("mcp_servers", {})
    names = set(managed_names)
    if "omnigent" in names:
        raise RefreshError("MCP_RELAY_CONFLICT")
    servers = document.setdefault("mcp_servers", {})
    for name in names:
        servers.pop(name, None)
        if name in incoming:
            servers[name] = incoming[name]
    return tomlkit.dumps(document)


def private_replace(path, content):
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise RefreshError("MCP_UNSAFE_CONFIG")
    descriptor, temporary = tempfile.mkstemp(prefix=".mcp-refresh-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def synchronize():
    completed = subprocess.run(["/usr/local/bin/woow-agent-sync"], capture_output=True,
                               timeout=30, check=False)
    if completed.returncode != 0:
        raise RefreshError("MCP_SYNC_FAILED")
    try:
        return json.loads(completed.stdout)["configurationHash"]
    except (ValueError, KeyError):
        raise RefreshError("MCP_SYNC_FAILED") from None


async def refresh_codex(session_id, info, *, sync=synchronize):
    from omnigent.harnesses.codex_native.bridge import (
        CODEX_NATIVE_BRIDGE_ID_LABEL_KEY, bridge_dir_for_bridge_id, read_bridge_state,
    )
    from omnigent.harnesses.codex_native.app_server import client_for_transport

    bridge = bridge_dir_for_bridge_id((info.get("labels") or {}).get(CODEX_NATIVE_BRIDGE_ID_LABEL_KEY) or session_id)
    state = read_bridge_state(bridge)
    if state is None or state.session_id != session_id:
        raise RefreshError("MCP_SESSION_NOT_LOCAL")
    if state.active_turn_id:
        raise RefreshError("SESSION_BUSY")
    # Never let a caller-provided path select a config or another native session.
    home = Path(state.codex_home)
    # Containers may bind-mount this same volume at /home/coder and /data.
    # Compare filesystem identity, not only path spelling.
    try:
        local_home = home.samefile(bridge / "codex-home")
    except OSError:
        local_home = False
    if not local_home:
        raise RefreshError("MCP_UNSAFE_CONFIG")
    client = client_for_transport(state.socket_path, client_name="woow-shared-mcp-refresh")
    try:
        try:
            await client.connect()
        except Exception:
            raise RefreshError("MCP_NATIVE_UNAVAILABLE") from None
        thread = (await client.request("thread/read", {"threadId": state.thread_id, "includeTurns": False})).get("result", {}).get("thread", {})
        if thread.get("id") != state.thread_id or thread.get("status", {}).get("type") != "idle":
            raise RefreshError("SESSION_BUSY")
        digest = await asyncio.to_thread(sync)
        data = Path(os.environ.get("PI_AGENT_DATA_DIR", "/data/pi-agent"))
        managed = json.loads((data / "shared/managed.json").read_text())
        names = managed.get("managedServers", managed.get("servers", []))
        path = home / "config.toml"
        existing = path.read_text()
        source = (Path(os.environ.get("CODEX_HOME", str(data / "codex"))) / "config.toml").read_text()
        rendered = merge_managed_servers(existing, source, names)
        if path.read_text() != existing:
            raise RefreshError("MCP_CONFIG_CHANGED")
        private_replace(path, rendered)
        try:
            # The native API queues safely at the next turn boundary if a turn
            # starts after our idle check. It does not stop or inject a turn.
            await client.request("config/mcpServer/reload", {})
        except Exception:
            if path.read_text() == rendered:
                private_replace(path, existing)
            raise RefreshError("MCP_RELOAD_FAILED") from None
        return {"sessionId": session_id, "engine": "codex", "refresh": {
            "state": "queued", "method": "native-mcp-reload", "historyPreserved": True,
            "configurationHash": digest, "nativeSessionId": state.thread_id,
            "toolsVerified": False,
        }}
    finally:
        await client.close()
