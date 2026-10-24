"""Additive management v1 contract. Observing a child never expands gateway policy."""
import asyncio
from dataclasses import dataclass
import json

from . import VERSION, redact
from .health import SESSION_ID, protocol_reply
from .lifecycle import _join_transition
from .policy import enabled, has_grant


@dataclass(frozen=True)
class ManagementOptions:
    """Deployment-owned presentation/feature hooks; never an authentication override.

    Builtins may set kind='builtin', authority='ha-ingress' (or 'paas-password'),
    backend_mode='fixed', backend_can_edit=False. Their existing auth adapter still
    owns identity verification. Unsupported actions are omitted unless wired.
    """
    kind: str = "ha-addon"
    authority: str = "ha-admin"
    backend_mode: str = "manual"
    backend_can_edit: bool = True
    product_version: str | None = None

    def __post_init__(self):
        if (self.kind not in {"ha-addon", "paas", "builtin"}
                or self.authority not in {"ha-admin", "ha-ingress", "paas-password"}
                or self.backend_mode not in {"manual", "fixed"}
                or type(self.backend_can_edit) is not bool
                or self.product_version is not None and (not isinstance(self.product_version, str)
                    or not 0 < len(self.product_version) <= 64 or not self.product_version.isascii())
                or self.backend_mode == "fixed" and self.backend_can_edit):
            raise ValueError("invalid management options")


async def observe_tools(client, url, state):
    """Bounded initialize/list pagination, with an owned session even on cancellation.

    No tools/call, backend URL or credential leaves this local child connection.
    Failure returns None, never a fabricated empty/zero effective catalog.
    """
    headers = {"Authorization": "Bearer " + state.child_token, "Accept": "application/json, text/event-stream"}
    session = None
    try:
        async with asyncio.timeout(5):
            async with client.stream("POST", url, headers=headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "management-catalog", "version": "1"}}}) as response:
                session = response.headers.get("mcp-session-id")
                if session is not None and not SESSION_ID.fullmatch(session):
                    session = None
                    raise ValueError("invalid session")
                if session:
                    headers["Mcp-Session-Id"] = session
                init = await protocol_reply(response, 1)
                if (not isinstance(init, dict) or not isinstance(init.get("serverInfo"), dict)
                        or init.get("protocolVersion") not in {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}):
                    raise ValueError("invalid initialize")
                headers["MCP-Protocol-Version"] = init["protocolVersion"]
            async with client.stream("POST", url, headers=headers, json={
                    "jsonrpc": "2.0", "method": "notifications/initialized"}) as response:
                if response.status_code not in (200, 202, 204):
                    raise ValueError("initialized rejected")
            found, cursors, size = {}, set(), 0
            cursor = None
            for page in range(16):
                ident = page + 2
                async with client.stream("POST", url, headers=headers, json={
                        "jsonrpc": "2.0", "id": ident, "method": "tools/list",
                        "params": {"cursor": cursor} if cursor else {}}) as response:
                    result = await protocol_reply(response, ident)
                if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                    raise ValueError("invalid catalog")
                size += len(json.dumps(result).encode())
                if size > 8 * 1024 * 1024:
                    raise ValueError("catalog too large")
                for tool in result["tools"]:
                    if (not isinstance(tool, dict) or not isinstance(tool.get("name"), str)
                            or not 0 < len(tool["name"]) <= 128 or not isinstance(tool.get("inputSchema"), dict)
                            or not isinstance(tool.get("description", ""), str)):
                        raise ValueError("invalid tool")
                    found.setdefault(tool["name"], tool)
                if len(found) > 4096:
                    raise ValueError("too many tools")
                cursor = result.get("nextCursor")
                if cursor is None:
                    return list(found.values())
                if not isinstance(cursor, str) or not 0 < len(cursor) <= 4096 or cursor in cursors:
                    raise ValueError("invalid cursor")
                cursors.add(cursor)
            raise ValueError("too many pages")
    except Exception:
        return None
    finally:
        if session:
            async def close():
                try:
                    async with asyncio.timeout(2):
                        async with client.stream("DELETE", url, headers=headers):
                            pass
                except Exception:
                    pass
            await _join_transition(close())


def tool_catalog(registry, pinned, observed, state):
    catalog = {item["name"]: item for item in pinned or ()}
    actual = {item["name"]: item for item in observed or ()}
    names = dict.fromkeys([*registry, *catalog, *actual])
    items = []
    for name in names:
        tool = registry.get(name)
        metadata = actual.get(name, catalog.get(name, {}))
        allowed = enabled(name, registry, state)
        effective = (name in actual and allowed) if observed is not None else (None if allowed else False)
        reason = ("not_in_registry" if tool is None else "policy_disabled" if name in state.disabled
                  else "write_not_granted" if not allowed else "child_unavailable" if observed is None
                  else "not_registered_by_child" if name not in actual else None)
        item = {"name": name, "description": metadata.get("description", ""),
                "policy_enabled": allowed, "effective": effective}
        if reason:
            item["reason"] = reason
        if tool is not None and not getattr(tool, "child_schema", False):
            # Bounded adapters validate against their registry model. A wider
            # child schema would promise arguments the gateway cannot accept.
            item.update(inputSchema=tool.arguments.model_json_schema(), schema_source="registry")
        elif isinstance(metadata.get("inputSchema"), dict):
            item.update(inputSchema=metadata["inputSchema"], schema_source="child" if name in actual else "pinned")
        if tool is not None:
            item["write"] = tool.write
            item["write_grants"] = tool.grants(name)
            item["operation_parameter"] = tool.selector
            item["operations"] = [{"name": op, "write": op in tool.write_operations,
                                   "policy_enabled": allowed and (op in getattr(tool, "read_operations", ()) or
                                       f"{name}:{op}" in getattr(state, "enabled_write_tools", ()))}
                                  for op in (*getattr(tool, "read_operations", ()), *tool.write_operations)]
            if tool.write:
                item["write_enabled"] = allowed and has_grant(name, tool, state)
        items.append(item)
    return {"catalog_count": len(items), "policy_enabled_count": sum(i["policy_enabled"] for i in items),
            "effective_count": sum(i["effective"] is True for i in items) if observed is not None else None,
            "status": "observed" if observed is not None else "unknown", "items": items}


def capability_snapshot(options, state, health, catalog, *, can_test=False, can_restart=False, logs=False):
    return {"schema_version": 1, "deployment": {"kind": options.kind},
            "product": {"id": getattr(state, "product", "n8n"), "version": options.product_version or VERSION, "runtime_version": VERSION},
            "admin": {"authority": options.authority},
            "backend": {"mode": options.backend_mode, "can_test": can_test, "can_edit": options.backend_can_edit},
            "capabilities": {"tool_schema": True, "effective_tools": True, "operation_policy": True,
                             "logs": logs, "restart_child": can_restart, "revoke_token": True},
            "health": {"management": "ready" if health.get("management") == "alive" else health.get("management", "unknown"),
                       "child": health.get("child", {}).get("state", "unknown"),
                       "backend": health.get("backend", "unknown"), "public_endpoint": "unverified"},
            "tools": redact.redact_secrets(catalog, redact.secret_values(state))}
