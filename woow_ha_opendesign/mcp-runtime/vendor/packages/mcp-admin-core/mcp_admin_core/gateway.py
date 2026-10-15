"""Independent Ingress-only admin and token-authenticated Streamable HTTP applications.

Management fails closed without an explicit role provider (installed only by n8n).
No legacy SSE /sse or /messages endpoints are exposed. The MCP endpoint is /mcp with a Bearer header and, from 0.1.12,
/private_<token>/mcp with the same token in the path (Claude.ai custom connectors cannot send headers).
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
from http import HTTPStatus
import json
import re
import secrets
from typing import Awaitable, Callable

import anyio
import httpx
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, request_response
from starlette.middleware import Middleware

from . import redact, ui

from . import VERSION
from .config import ConfigError, State, Store, strict_json
from .policy import Denied, ToolCallRefused, UnknownMethod, authorize, filter_list
from .ha_role import valid_user_id

MAX_REQUEST = 262144
MAX_RESPONSE = 8 * 1024 * 1024
STREAM_SECONDS = 120
EVENT_BOUNDARY = re.compile(rb"\r?\n\r?\n")
FORWARDED_HEADERS = {"mcp-session-id": re.compile(r"[\x21-\x7e]{1,256}"),
                     "mcp-protocol-version": re.compile(r"[\x21-\x7e]{1,256}"),
                     "retry-after": re.compile(r"[0-9]{1,10}"),
                     "content-type": re.compile(r"[\x20-\x7e]{1,256}")}
LONE_CR = re.compile(rb"\r(?!\n)")
SSE_FIELD = re.compile(rb"(?:id|event):[ ]?[\x21-\x7e]{0,256}|retry:[ ]?[0-9]{1,10}")  # id as Last-Event-ID allows
SSE_COMMENT = re.compile(rb":[\x20-\x7e]{0,1024}")
# 0.1.4: the only child notification a client gets, and only as these fixed bytes (no child params). Progress is
# never relayed: authorize removes params._meta before dispatch (0.1.13; refused it before), so no client can ask for
# it and any progress event is unsolicited child text (the pinned TS client puts unknown-token progress into an error
# message); log messages and resource updates carry child text or name surfaces the gateway never exposes.
LIST_CHANGED = b'data: {"jsonrpc":"2.0","method":"notifications/tools/list_changed"}'
# 0.1.5 (R1 #6): the pinned TS client puts an unsupported protocolVersion into an error, so no child text may pass.
# 0.1.8 (review 6b): only the reviewed MCP revisions, not any date. The pinned children negotiate within this set,
# except n8n-mcp, which echoes "2024-06-25" to a client that asks for it: that initialize is now refused (502).
PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})
# 0.1.6 (R2): the bound of the gateway's own DELETE that ends an initialize session no client received.
SESSION_END_SECONDS = 2
# 0.1.8 (0.1.6 R1 F6): the name the initialize answer gives when the caller names no product.
SERVER_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def sse_frame(frame: bytes):
    """Split one SSE event (boundary removed) into (kept field lines, data lines), or None if unsafe.

    Only printable-ASCII id/event/retry fields and comments are kept besides data lines; anything else
    (a BOM, unknown fields, blank lines, non-ASCII) is dropped, so no client can read it as data that the
    gateway did not see. A lone CR ends a line for some SSE parsers but not for this scan: refused.
    """
    if LONE_CR.search(frame):
        return None
    kept, data = [], []
    for line in frame.split(b"\n"):
        line = line[:-1] if line.endswith(b"\r") else line
        if line.startswith(b"data:"):
            data.append(line)
        elif SSE_FIELD.fullmatch(line) or SSE_COMMENT.fullmatch(line):
            kept.append(line)
    return kept, data


def sse_data(data_lines):
    return b"\n".join(line[5:].lstrip(b" ") for line in data_lines)


def same_id(value, ident):
    """JSON-RPC ids match only with the same JSON type: true is not 1."""
    return type(value) is type(ident) and value == ident


def backend_unavailable(ident):
    """initialize without a reply from the child: no dead session id; clients may retry later."""
    return json_reply({"jsonrpc": "2.0", "id": ident, "error": {"code": -32000, "message": "BACKEND_UNAVAILABLE"}},
                      503, {"Retry-After": "5", "Cache-Control": "no-store"})


def one_reply(value):
    """A JSON-RPC response object: exactly one of result and error (a client may parse both as an error)."""
    return isinstance(value, dict) and "method" not in value and (("result" in value) != ("error" in value))


def gateway_reply(value, method=None):
    """The reply a client gets is the gateway's own object (0.1.5): jsonrpc, id and exactly one of result or error,
    no other top-level member, and an error with only code (an integer), message and data: the pinned TS client's
    strict schemas put an unknown key's name (child text) into an error. The same holds for ping's empty result
    (R1 #3), so a successful ping is always {}; other results are relayed (tools/capabilities filtered by the caller).
    An error the gateway cannot vouch for becomes its own (0.1.4): a URL elicitation error (-32042) asks the user to
    open a child-chosen URL (the gateway declares no elicitation capability); a code that is not a 32-bit JSON integer
    (e.g. "-32042", which a Python client coerces; integral floats count, as for clients) or a message that is not a
    string is malformed."""
    if "result" in value:
        return {"jsonrpc": "2.0", "id": value.get("id"), "result": {} if method == "ping" else value["result"]}
    error = value["error"]
    code = error.get("code") if isinstance(error, dict) else None
    if (not (type(code) is int or type(code) is float and code.is_integer()) or not -2 ** 31 <= code < 2 ** 31
            or not isinstance(error.get("message"), str)):
        error = {"code": -32000, "message": "Invalid error from the MCP server"}
    elif code == -32042:
        error = {"code": -32000, "message": "URL elicitation is not supported"}
    else:
        error = {"code": int(code), "message": error["message"], **({"data": error["data"]} if "data" in error else {})}
    return {"jsonrpc": "2.0", "id": value.get("id"), "error": error}


def child_status_reply(ident, status, headers):
    """0.1.4: a non-2xx child reply keeps its status (404 ends a session, Retry-After still applies) but never the
    child's bytes; MCP clients put error bodies into user-visible messages (0.1.2 review note)."""
    try:
        text = HTTPStatus(status).phrase
    except ValueError:
        text = "HTTP %d" % status
    return json_reply({"jsonrpc": "2.0", "id": ident, "error": {"code": -32000, "message": text}}, status, headers)


def json_reply(value, status, headers):
    """Re-serialized JSON with ASCII escapes, so a lone surrogate from a child cannot make the reply unencodable."""
    headers = {k: v for k, v in headers.items() if k != "content-type"}
    return Response(json.dumps(value, separators=(",", ":")).encode(), status_code=status,
                    media_type="application/json", headers=headers)
RoleVerifier = Callable[[str], Awaitable[bool]]


class UpstreamOwner:
    """Own the reader, response and slot across ASGI cancellation and handoff (0.1.6: and the end of an initialize
    session that no client received)."""
    def __init__(self, slots):
        self.slots = slots
        self.response = None
        self.reader = None
        self.closed = False
        self.overflowed = False  # chunks() stopped at MAX_RESPONSE, not at the end of the reply
        self.end_session = None  # 0.1.6 (R2): set while the child's new session id is withheld from the client

    async def close(self):
        if self.closed:
            return
        self.closed = True

        async def cleanup():
            try:
                async with asyncio.timeout(3):
                    if self.reader is not None:
                        if not self.reader.done():
                            self.reader.cancel()
                        await asyncio.gather(self.reader, return_exceptions=True)
                    if self.response is not None:
                        await self.response.aclose()
            except (TimeoutError, httpx.HTTPError):
                pass
            finally:
                try:
                    if self.end_session is not None:
                        # After the reply is closed (its connection is free) or the budget above cut that close, and
                        # inside this request's slot, so these DELETEs never outnumber the slots. Bounded; no Exception
                        # leaves it (a BaseException such as a cancellation can, and the slot is still released).
                        await self.end_session()
                finally:
                    self.slots.release()

        # ASGI 2.3 level cancellation and direct asyncio cancellation both must
        # join this bounded cleanup. No reader/cleanup task is detached.
        with anyio.CancelScope(shield=True):
            task = asyncio.create_task(cleanup())
            cancelled = False
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
            task.result()
            if cancelled:
                raise asyncio.CancelledError


class OwnedStreamingResponse(StreamingResponse):
    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Includes headers/send failures where a generator may never start.
            await self.owner.close()


class AnyMethod:
    """An ASGI endpoint, so Starlette hands every method to the handler: the Bearer check comes first, then 405."""
    def __init__(self, handler):
        self.app = request_response(handler)

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


class BadRequest(Exception):
    def __init__(self, status=400):
        self.status = status


async def body(request: Request):
    content = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                content.extend(chunk)
                if len(content) > MAX_REQUEST:
                    raise BadRequest(413)
    except ClientDisconnect:
        raise BadRequest(403) from None
    except TimeoutError:
        raise BadRequest(408) from None
    return bytes(content)


async def json_body(request):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise BadRequest(415)
    try:
        value = strict_json(await body(request))
        # A lone surrogate (e.g. an id "\ud800") parses but cannot be encoded back into a reply.
        json.dumps(value, ensure_ascii=False).encode("utf-8")
        return value
    except (ValueError, RecursionError):  # UnicodeEncodeError is a ValueError
        raise BadRequest() from None


def prefix(request):
    values = request.headers.getlist("x-ingress-path")
    if len(values) > 1:
        raise BadRequest()
    value = values[0] if values else ""
    if value and (not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)+", value) or len(value) > 512):
        raise BadRequest()
    return value


def token_valid(request, state):
    values = request.headers.getlist("authorization")
    return (state.token is not None and len(values) == 1
            and hmac.compare_digest(values[0].encode(), ("Bearer " + state.token).encode()))


def secret_valid(secret, state):
    """0.1.12: the /private_<secret>/mcp credential is the add-on token itself (rotate and revoke apply at once).

    Both sides are hashed to fixed-length digests before hmac.compare_digest, so neither the token's length nor how
    much of a guess matches shows in the timing; there is no separate length or charset check to leak through. A
    revoked token (None) matches nothing."""
    if state.token is None:
        return False
    supplied = hashlib.sha256(secret.encode("utf-8", "replace")).digest()
    return hmac.compare_digest(supplied, hashlib.sha256(state.token.encode()).digest())


def json_only(request):
    """0.1.13: the client's Accept names application/json and neither text/event-stream nor */*."""
    accept = ",".join(request.headers.getlist("accept")).lower()
    return "application/json" in accept and "text/event-stream" not in accept and "*/*" not in accept


async def error_handler(_, exc):
    if isinstance(exc, ConfigError):
        return JSONResponse({"error": "state unavailable"}, status_code=503)
    return JSONResponse({"error": "request denied"}, status_code=exc.status)


def make_apps(store: Store, tools, child: httpx.AsyncClient, *,
              verify_admin: RoleVerifier | None = None,
              child_url="http://127.0.0.1:3000/mcp", health=None, backend_changed=None,
              server_name="woow-mcp", instructions: str | None = None):
    if not SERVER_NAME.fullmatch(server_name) or instructions is not None and not (
            isinstance(instructions, str) and 0 < len(instructions) <= 4096):
        raise ValueError("invalid server identity")
    redact.install()  # 0.1.12: a request path may now carry the token; no log record may show it
    csrf_key = secrets.token_bytes(32)
    mutation_lock = asyncio.Lock()
    slots = asyncio.Semaphore(32)
    admin_slots = asyncio.Semaphore(16)

    def snapshot():
        return health() if health else {"management": "alive", "child": {"state": "not_started", "transport_ready": False}, "backend": "unconfigured"}

    def admin_identity(request):
        # Uvicorn MUST have proxy_headers=False; request.client is the socket peer.
        if not request.client or request.client.host != "172.30.32.2" or verify_admin is None:
            raise BadRequest(403)
        identities = request.headers.getlist("x-remote-user-id")
        if len(identities) != 1 or not valid_user_id(identities[0]):
            raise BadRequest(403)
        user = identities[0]
        base = prefix(request)
        csrf = hmac.new(csrf_key, (user + "\0" + base).encode(), hashlib.sha256).hexdigest()
        if request.method not in ("GET", "HEAD"):
            values = request.headers.getlist("x-csrf-token")
            if len(values) != 1 or not hmac.compare_digest(values[0].encode(), csrf.encode()):
                raise BadRequest(403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                raise BadRequest(403)
        return user, base, csrf

    async def final_role(user):
        try:
            async with asyncio.timeout(3):
                allowed = await verify_admin(user)
        except Exception:
            allowed = False
        if allowed is not True:
            raise BadRequest(403)

    async def admin_action(request, user, base, csrf, value, peer_disconnected, committed):
        name = request.path_params["operation"]
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        # Bounded lock wait; the role check occurs AFTER waiting and validating.
        try:
            async with asyncio.timeout(2):
                await mutation_lock.acquire()
        except TimeoutError:
            raise BadRequest(503) from None
        try:
            state = store.load()
            changes = None
            if name in ("backend", "policy", "endpoint") and request.method == "PUT":
                try:
                    if not isinstance(value, dict):
                        raise ValueError()
                    if name == "backend":
                        if getattr(state, 'product', 'n8n') == 'n8n':
                            if set(value) != {"url", "key"}:
                                raise ValueError()
                            changes = dict(backend_url=value["url"], backend_key=value["key"])
                        else:
                            if set(value) != {"connection"}:
                                raise ValueError()
                            changes = value
                    elif name == "endpoint":
                        if set(value) != {"endpoint"}:
                            raise ValueError()
                        changes = value
                    else:
                        if (set(value) not in ({"writes_enabled", "disabled"}, {"writes_enabled", "disabled", "enabled_write_tools"}) or not isinstance(value["disabled"], list)
                                or any(not isinstance(t, str) or t not in tools for t in value["disabled"])):
                            raise ValueError()
                        changes = value
                    # Validate without writing. Store.update revalidates on commit.
                    type(state).model_validate({**state.model_dump(), **changes})
                except ValueError:
                    raise BadRequest() from None
            if peer_disconnected.is_set():
                raise BadRequest(403)
            await final_role(user)
            if peer_disconnected.is_set():
                raise BadRequest(403)
            # No awaited work between this final decision and disclosure/commit.
            if name == "__ui__" and hasattr(request.state, "ui_path") and request.method in ("GET", "HEAD"):
                return ui.response(request.state.ui_path, base)
            if name == "bootstrap" and request.method == "GET":
                return JSONResponse({"base_path": base, "api_base": base + "/api", "csrf": csrf,
                    "endpoint": state.endpoint, "backend_url": state.backend_url,
                    "backend_key_set": state.backend_key is not None, "token_active": state.token is not None,
                    "product": getattr(state, 'product', 'n8n'),
                    "connection_configured": getattr(state, 'configured', bool(state.backend_url and state.backend_key)),
                    "writes_enabled": state.writes_enabled, "disabled": state.disabled,
                    "policy_contract": "woow-v3-exact-grants",
                    "enabled_write_tools": getattr(state, 'enabled_write_tools', []),
                    "tools": {k: {"write": v.write, "write_grants": v.grants(k),
                                  "operation_parameter": v.selector, "legacy_write": v.legacy_write,
                                  "inputSchema": v.arguments.model_json_schema()} for k, v in tools.items()}, "health": snapshot()}, headers=headers)
            if name == "token/reveal" and request.method == "POST":
                return JSONResponse({"token": store.load().token}, headers=headers)
            if name == "token/rotate" and request.method == "POST":
                updated = store.update(token=secrets.token_urlsafe(32))
                return JSONResponse({"token": updated.token}, headers=headers)
            if name == "token/revoke" and request.method == "POST":
                store.update(token=None)
                return Response(status_code=204, headers=headers)
            if changes is not None:
                updated = store.update(**changes)
                # No yield between durable commit and lifecycle ownership transfer.
                # An authorized mutation is not undone by losing its HTTP caller.
                committed.set()
                if (name == "backend" or (name == "policy" and getattr(state, 'product', 'n8n') in ('emqx', 'litellm', 'nextcloud'))) and backend_changed:
                    await backend_changed(updated)
                return JSONResponse({"saved": True}, headers=headers)
            return Response(status_code=404)
        finally:
            mutation_lock.release()

    async def admin_api(request):
        user, base, csrf = admin_identity(request)
        # Reject saturation rather than accumulating unbounded body/lock waiters.
        if admin_slots.locked():
            raise BadRequest(503)
        await admin_slots.acquire()
        tasks = []
        action = None
        committed = asyncio.Event()
        try:
            name = request.path_params["operation"]
            if name in ("backend", "policy", "endpoint") and request.method == "PUT":
                value = await json_body(request)
            else:
                if await body(request):
                    raise BadRequest()
                value = None

            peer_disconnected = asyncio.Event()

            async def disconnected():
                # Body is fully consumed: this task exclusively owns receive now.
                while (await request.receive())["type"] != "http.disconnect":
                    pass
                # Deny even when role completion and disconnect wake together,
                # before the outer waiter has had a chance to cancel the action.
                peer_disconnected.set()

            watcher = asyncio.create_task(disconnected())
            action = asyncio.create_task(admin_action(request, user, base, csrf, value, peer_disconnected, committed))
            tasks = [watcher, action]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if watcher in done:
                raise BadRequest(403)
            return action.result()
        finally:
            for task in tasks:
                if task is not action or not committed.is_set():
                    task.cancel()
            # Before commit: cancel/join role cleanup with zero effects. After
            # commit: join the lifecycle callback without cancelling it; action
            # retains mutation_lock until stop/reap/restart finishes. Neither
            # ASGI nor repeated direct cancellation may detach that ownership.
            cancelled = False
            with anyio.CancelScope(shield=True):
                if tasks:
                    joined = asyncio.gather(*tasks, return_exceptions=True)
                    while not joined.done():
                        try:
                            await asyncio.shield(joined)
                        except asyncio.CancelledError:
                            cancelled = True
            admin_slots.release()
            if cancelled:
                raise asyncio.CancelledError

    async def admin_page(request):
        # The same admission, bounded body, lock, fresh role and disconnect
        # ownership as the API apply to every asset; no unbounded WS fan-out.
        _, base, _ = admin_identity(request)
        raw = request.scope.get("raw_path", b"")
        if b"%" in raw or b"\\\\" in raw or request.url.query:
            raise BadRequest()
        path = request.url.path
        if base and (path == base or path.startswith(base + "/")):
            path = path[len(base):] or "/"
        if path.startswith("/api/"):
            request.path_params["operation"] = path[5:]
        else:
            if request.method not in ("GET", "HEAD"):
                raise BadRequest(404)
            request.path_params["operation"] = "__ui__"
            request.state.ui_path = path
        return await admin_api(request)

    def still_authorized(token):
        try:
            current = store.load().token
            return current is not None and hmac.compare_digest(current, token)
        except ConfigError:
            return False

    async def chunks(owner, token):
        """Bound total bytes/time; poll revocation even while upstream is idle."""
        iterator = owner.response.aiter_bytes()
        total = 0
        try:
            async with asyncio.timeout(STREAM_SECONDS):
                while True:
                    pending = owner.reader = asyncio.create_task(anext(iterator))
                    while not pending.done():
                        await asyncio.wait({pending}, timeout=0.2)
                        if not still_authorized(token):
                            return
                    try:
                        chunk = pending.result()
                    except StopAsyncIteration:
                        return
                    if not still_authorized(token):
                        return
                    total += len(chunk)
                    if total > MAX_RESPONSE:
                        owner.overflowed = True
                        return
                    yield chunk
        except (httpx.HTTPError, TimeoutError):
            return

    async def end_session(child_token, session):
        """0.1.6 (R2 review): end a session the child opened for an initialize whose answer withholds its id (401,
        502, 503, a refused child status, a state error); otherwise it stays open until the child's idle reaping (n8n:
        10 minutes, with 20 sessions shared by all clients; the pinned Python SDK children kept it until they restarted
        until 0.1.7, and from 0.1.8 end it after 30 idle minutes, apps/runtime/session_idle.py). One DELETE with the
        gateway's own headers and none of the client's; best effort and bounded: nothing of the child's reply is read or
        relayed (it is streamed and closed unread: a body may be large or never end, and a reply left open would keep its
        pooled connection) and no Exception escapes, since the client's answer is already decided and must not change."""
        try:
            async with asyncio.timeout(SESSION_END_SECONDS):
                async with child.stream("DELETE", child_url, follow_redirects=False, headers={
                        "Authorization": "Bearer " + child_token, "Accept": "application/json, text/event-stream",
                        "Accept-Encoding": "identity", "mcp-session-id": session}):
                    pass  # the child's status, headers and body are never read
        except Exception:
            pass

    async def initialize_reply(owner, token, is_sse, ident):
        """Read the child's reply to initialize: (outcome, message, SSE frame lines other than data).

        outcome is "ok", "missing" or "invalid". Stops at the JSON-RPC response with the request's id
        (an SSE stream may stay open after it). "missing": the child answered 200 and ended without a
        reply, e.g. its per-session lifespan could not reach the backend (Odoo Manage, 0.1.1 HA test),
        so the session id it sent is dead.
        """
        def reply(value):
            """"ok" for this request's reply, "invalid" when it has both result and error (0.1.4), None for another
            message (a request, a notification, another id, or neither result nor error: skipped as in 0.1.2)."""
            if "method" in value or not same_id(value.get("id"), ident) or not ("result" in value or "error" in value):
                return None
            return "ok" if one_reply(value) else "invalid"

        pending = bytearray()
        reader = chunks(owner, token)
        try:
            async for chunk in reader:
                start = max(0, len(pending) - 3)  # only new bytes, plus a boundary split across chunks
                pending.extend(chunk)
                while is_sse and (match := EVENT_BOUNDARY.search(pending, start)):
                    parsed = sse_frame(bytes(pending[:match.start()]))
                    del pending[:match.end()]
                    start = 0
                    if parsed is None:
                        return "invalid", None, None
                    kept, data_lines = parsed
                    payload = sse_data(data_lines)
                    if not payload.strip():
                        continue  # no data, or an empty priming event (MCP 2025-11-25 resumability)
                    try:
                        value = strict_json(payload)
                    except (ValueError, RecursionError):
                        return "invalid", None, None
                    if not isinstance(value, dict):
                        return "invalid", None, None  # a batch: the gateway never sends one
                    outcome = reply(value)
                    if outcome == "ok":
                        return "ok", value, [line for line in kept if not line.startswith(b":")]
                    if outcome == "invalid":
                        return "invalid", None, None
        finally:
            await reader.aclose()
        if owner.overflowed:
            return "invalid", None, None
        if is_sse or not pending.strip():
            return "missing", None, None  # a truncated SSE event is not dispatched
        try:
            value = strict_json(bytes(pending))
        except (ValueError, RecursionError):
            return "invalid", None, None
        if not isinstance(value, dict):
            return "invalid", None, None
        outcome = reply(value)
        return ("ok", value, None) if outcome == "ok" else ("invalid" if outcome else "missing", None, None)

    async def stream(owner, token, request=None):
        """Relay a child's SSE 200 (the only stream the caller hands over). request is the (id, method) of the POST
        this stream answers, None for a GET stream."""
        # Every event is rebuilt from the lines the gateway understood (sse_frame), so nothing it did not filter
        # can reach a client as data.
        pending = bytearray()
        async for chunk in chunks(owner, token):
            start = max(0, len(pending) - 3)  # only new bytes, plus a boundary split across chunks
            pending.extend(chunk)
            while match := EVENT_BOUNDARY.search(pending, start):
                parsed = sse_frame(bytes(pending[:match.start()]))
                del pending[:match.end()]
                start = 0
                if parsed is None:
                    return
                kept, data_lines = parsed
                payload = sse_data(data_lines)
                final = False
                if data_lines and not payload.strip():
                    data_lines = [b"data:"]  # an empty (priming) event stays empty
                elif data_lines:
                    try:
                        value = strict_json(payload)
                        if not isinstance(value, dict):
                            return  # a batch: never sent by the gateway, never filtered element by element
                        if "method" in value:
                            if "id" in value or value["method"] != "notifications/tools/list_changed":
                                continue  # a server-to-client request (elicitation, sampling, roots: the client
                                # could not answer it through the gateway) or a notification other than 0.1.4's one
                            data_lines = [LIST_CHANGED]
                        elif "result" not in value and "error" not in value:
                            continue  # not a reply: never relayed as one
                        elif not one_reply(value):
                            return  # both result and error: malformed, never relayed, never guessed
                        elif request is None or not same_id(value.get("id"), request[0]):
                            # 0.1.5: a reply to another request (the TS client reports it with its text). A GET
                            # stream carries no reply at all (R1 #2): MCP allows one only when resuming a stream,
                            # and no pinned child keeps an event store.
                            continue
                        else:
                            checked = gateway_reply(value, request[1])
                            if (isinstance(checked.get("result"), dict)
                                    and {"tools", "capabilities"} & checked["result"].keys()):
                                checked = filter_list(checked, tools, store.load())
                            data_lines = [b"data: " + json.dumps(checked, separators=(",", ":")).encode()]
                            final = True  # R1 #1: the reply ends the stream (MCP: the server SHOULD close it)
                    except (ValueError, ConfigError, RecursionError):
                        return
                lines = kept + data_lines
                if lines:
                    yield b"\n".join(lines) + b"\n\n"
                if final:
                    return  # a duplicate reply or anything after it is never relayed
        # A truncated SSE event is intentionally not dispatched.

    async def mcp(request):
        return await serve(request, None)

    async def private_mcp(request):
        return await serve(request, request.path_params["secret"])

    async def serve(request, secret):
        """secret is None on /mcp (Bearer header) and the path segment on /private_<secret>/mcp.

        On the secret path a wrong, revoked or unset token is the same 404 as any unknown path (Starlette's own
        HTTPException(404): same status, body and headers, no WWW-Authenticate), so the reply never says whether
        the path exists, the token was revoked or the guess was close. The request's own Authorization header is
        never read there, and an Origin header is allowed (never forwarded: the child only gets the gateway's own
        headers). /mcp is unchanged: 401 with WWW-Authenticate, Origin 403.

        0.1.14: on both paths, a well-formed tools/call the policy refuses (policy.ToolCallRefused) is answered HTTP 200
        with a JSON-RPC error giving the reason, when it carries a session id; without one it stays 403 as before."""
        def authorized(state):
            return token_valid(request, state) if secret is None else secret_valid(secret, state)

        def refused():
            return BadRequest(401) if secret is None else HTTPException(404)

        def unauthorized():
            if secret is not None:
                raise refused()
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})

        def tool_refusal(ident, refusal):
            """0.1.14: a refused well-formed tools/call is answered as JSON-RPC (ToolCallRefused.error()), not 403."""
            return json_reply({"jsonrpc": "2.0", "id": ident, "error": refusal.error()}, 200, {"Cache-Control": "no-store"})

        state = store.load()
        if not authorized(state):
            return unauthorized()
        if request.method not in ("GET", "POST", "DELETE"):  # any other method, only after the token check
            return Response(status_code=405, headers={"Allow": "GET, POST, DELETE"})
        if secret is None and request.headers.get("origin") is not None:
            raise BadRequest(403)  # Browser clients not in the Bearer contract; the secret path is for Claude.ai.
        if request.url.query:
            raise BadRequest()
        method = message = refusal = None
        content = b""
        if request.method == "POST":
            message = await json_body(request)
            try:
                method = authorize(message, tools, state)
            except ToolCallRefused as refused_call:
                # 0.1.14: answered below with its reason when the request also carries usable session headers (as any
                # tools/call needs), never with a slot or the child; otherwise still 403, as in 0.1.13.
                method, refusal = "tools/call", refused_call
            except UnknownMethod as unknown:
                # 0.1.13: answered here, before the session check, a slot or the child (Claude.ai sends server/discover
                # first and needs a JSON-RPC answer to fall back to initialize). Only after the token check above.
                if not unknown.request:
                    return Response(status_code=202, headers={"Cache-Control": "no-store"})
                return json_reply({"jsonrpc": "2.0", "id": message["id"],
                                   "error": {"code": -32601, "message": "Method not found"}},
                                  200, {"Cache-Control": "no-store"})
            except Denied:
                raise BadRequest(403) from None
        elif await body(request):
            raise BadRequest()
        headers = {"Authorization": "Bearer " + state.child_token, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",  # fixed: the gateway reads both itself
                   "Accept-Encoding": "identity"}
        for name in ("mcp-session-id", "mcp-protocol-version", "last-event-id"):
            values = request.headers.getlist(name)
            if len(values) > 1 or (values and (len(values[0]) > 256 or not re.fullmatch(r"[\x21-\x7e]+", values[0]))):
                raise BadRequest(403 if refusal is not None else 400)
            if values:
                headers[name] = values[0]
        if refusal is not None and "mcp-session-id" not in headers:
            raise BadRequest(403)  # a refused call without a session: unchanged from 0.1.13
        if method != "initialize" and "mcp-session-id" not in headers:
            # 0.1.8 (0.1.6 RC GATEWAY-2): every child is stateful, so anything but initialize needs the session it
            # opened (MCP: such a server SHOULD answer 400). Forwarded, the pinned Python SDK children opened a new
            # session for it before refusing it, and kept it until they restarted (until 0.1.7; from 0.1.8 idle sessions
            # end after 30 minutes, GATEWAY-3).
            # The answer has the shape a refusing child's answer was relayed in (child_status_reply; a bare 400 for a
            # notification or DELETE), minus the child's new session id. n8n-mcp, which opens no session for these,
            # accepted a notification without one (202); it now gets 400 like every other request.
            if request.method == "DELETE" or request.method == "POST" and not (isinstance(message, dict)
                                                                                and "id" in message):
                return Response(status_code=400, headers={"Cache-Control": "no-store"})
            return child_status_reply(message.get("id") if request.method == "POST" else None, 400,
                                      {"Cache-Control": "no-store"})
        if refusal is not None:
            # Decided again on fresh state (reading the body yielded): a revoked token is still refused as above, and a
            # call the policy now allows takes the normal path below.
            state = store.load()
            if not authorized(state):
                return unauthorized()
            try:
                authorize(message, tools, state)
            except ToolCallRefused as refused_call:
                return tool_refusal(message["id"], refused_call)
            except Denied:
                raise BadRequest(403) from None
        try:
            async with asyncio.timeout(1):
                await slots.acquire()
        except TimeoutError:
            raise BadRequest(503) from None
        upstream = None
        owner = UpstreamOwner(slots)
        handed_off = False
        try:
            # Revalidate after yielding for body/concurrency; sessions do not cache policy.
            state = store.load()
            if not authorized(state):
                raise refused()
            if request.method == "POST":
                try:
                    authorize(message, tools, state)
                except ToolCallRefused as refused_call:
                    # The policy changed while this call waited for a slot: the same answer as above (the slot is
                    # released by the finally below; the child is never reached).
                    return tool_refusal(message["id"], refused_call)
                except Denied:
                    raise BadRequest(403) from None
                forwarded = message
                if method == "initialize" and isinstance(message.get("params"), dict):
                    # The gateway answers no server-to-client requests (sampling, elicitation, roots): the
                    # child must not expect any, whatever the real client declared.
                    forwarded = {**message, "params": {**message["params"], "capabilities": {}}}
                content = json.dumps(forwarded, separators=(",", ":")).encode()
            outgoing = child.build_request(request.method, child_url, headers=headers, content=content,
                                           timeout=httpx.Timeout(30, connect=3, pool=3))
            async with asyncio.timeout(35):
                upstream = owner.response = await child.send(outgoing, stream=True, follow_redirects=False)
            # Only well-formed values of four headers are forwarded (a non-Latin-1 value from a child could
            # not be encoded into the reply); session/protocol values follow the same rule as request headers.
            response_headers = {k: v for k, v in upstream.headers.items()
                                if k in FORWARDED_HEADERS and FORWARDED_HEADERS[k].fullmatch(v)}
            response_headers["Cache-Control"] = "no-store"
            session = response_headers.get("mcp-session-id")
            if method == "initialize" and session not in (None, headers.get("mcp-session-id")):
                # 0.1.6 (R2): the child opened this session for this initialize. Until an answer hands its id to the
                # client the gateway owns it, and every other way out ends it (UpstreamOwner.close). Only a usable
                # id (one the gateway would forward), and never one the client sent itself: that session is the
                # client's (a child may echo it).
                owner.end_session = functools.partial(end_session, state.child_token, session)
            if not still_authorized(state.token):
                raise refused()
            if not 200 <= upstream.status_code <= 599 or 300 <= upstream.status_code < 400:
                raise BadRequest(502)  # no interim reply (an ASGI server cannot send it), no child redirect
            if upstream.status_code in (401, 403):
                raise BadRequest(502)  # the child refused the gateway's own token or Host: not a client credential issue
            media = upstream.headers.get("content-type", "").split(";")[0].strip().lower()
            is_sse = media == "text/event-stream"
            if is_sse:  # the gateway re-frames events itself: never forward the child's parameters (charset)
                response_headers["content-type"] = "text/event-stream"
            request_id = request.method == "POST" and isinstance(message, dict) and "id" in message
            if request.method == "DELETE" or request.method == "POST" and not request_id:
                # Replies to a notification or a session DELETE carry nothing a client needs: status and the
                # forwarded headers only, never the child's bytes.
                return Response(status_code=upstream.status_code,
                                headers={k: v for k, v in response_headers.items() if k != "content-type"})
            if upstream.status_code >= 400:
                if method == "initialize":
                    response_headers.pop("mcp-session-id", None)  # no session for a failed initialize
                return child_status_reply(message.get("id") if request_id else None, upstream.status_code,
                                          response_headers)
            if 200 <= upstream.status_code < 300 and (request.method == "GET" or request_id):
                # A success body must be one the gateway parses and filters itself: an SSE stream, or (for a
                # request) a plain 200 JSON reply. Nothing else is relayed, not even a body declared empty:
                # framing headers can lie (Content-Length: 0 with chunked encoding still carries a body).
                if not (is_sse and upstream.status_code == 200 or
                        request_id and media == "application/json" and upstream.status_code == 200):
                    if method == "initialize" and upstream.headers.get("content-length") == "0":
                        return backend_unavailable(message.get("id"))  # the child sent no reply
                    raise BadRequest(502)
            if method == "initialize" and upstream.status_code == 200:
                outcome, value, frame = await initialize_reply(owner, state.token, is_sse, message.get("id"))
                if not still_authorized(state.token):
                    raise refused()
                if outcome == "missing":
                    return backend_unavailable(message.get("id"))
                try:
                    if outcome != "ok":
                        raise ValueError("invalid initialize response")
                    if "mcp-session-id" in upstream.headers and "mcp-session-id" not in response_headers:
                        raise ValueError("unusable session id")  # a client could not continue the session
                    value = gateway_reply(value)
                    if "result" in value:
                        version = value["result"].get("protocolVersion") if isinstance(value["result"], dict) else None
                        if not (isinstance(version, str) and version in PROTOCOL_VERSIONS):
                            raise ValueError("unusable protocol version")
                        # 0.1.8 (0.1.6 R1 F6): the result is the gateway's own; only the child's protocolVersion (one of
                        # the reviewed revisions) remains. serverInfo names this add-on, not the child (n8n-mcp calls itself
                        # "n8n-documentation-mcp"), and the child's instructions are never relayed: Claude Code puts
                        # instructions into the model's system prompt, and EMQX's and LiteLLM's describe their whole
                        # upstream tool set, including tools this gateway hides or refuses (Odoo's is a generic line).
                        # The caller may pass reviewed fixed text.
                        value["result"] = {"protocolVersion": version,
                                           "capabilities": {"tools": {}},
                                           "serverInfo": {"name": server_name, "version": VERSION},
                                           **({"instructions": instructions} if instructions else {})}
                except ValueError:
                    raise BadRequest(502) from None
                if frame is None or json_only(request):
                    # 0.1.13: a client that accepts only application/json gets the initialize answer as JSON even when
                    # the child framed it as an SSE event (the gateway holds the parsed reply either way).
                    answer = json_reply(value, 200, response_headers)
                else:
                    # The child's event framing (id/event/retry lines) with the filtered data.
                    frame.append(b"data: " + json.dumps(value, separators=(",", ":")).encode())
                    answer = Response(b"\n".join(frame) + b"\n\n", status_code=200, headers=response_headers)
                owner.end_session = None  # the answer hands the session id over: ending it is the client's call
                return answer
            if request_id and not is_sse and upstream.status_code == 200:
                # Every JSON reply is parsed, must answer this request, is filtered and re-serialized: a child
                # cannot hand a client an unfiltered list under another request's id or in a batch.
                result = bytearray()
                async for chunk in chunks(owner, state.token):
                    result.extend(chunk)
                if not still_authorized(state.token):
                    raise refused()
                try:
                    if owner.overflowed:
                        raise ValueError("oversize reply")
                    value = strict_json(bytes(result))
                    if not (one_reply(value) and same_id(value.get("id"), message.get("id"))):
                        raise ValueError("not this request's reply")
                    value = filter_list(gateway_reply(value, method), tools, store.load())
                except (ValueError, RecursionError):
                    raise BadRequest(502) from None
                return json_reply(value, 200, response_headers)
            if not (is_sse and upstream.status_code == 200):
                raise BadRequest(502)  # unreachable (R1 #8): every other success body was answered or refused above
            response = OwnedStreamingResponse(stream(owner, state.token, (message.get("id"), method) if request_id else None),
                                              owner=owner, status_code=200, headers=response_headers)
            # This answer hands any session id it carries over to the client, so the end of its stream must never
            # DELETE that session (an initialize never streams today: it is answered or refused above).
            owner.end_session = None
            handed_off = True  # only once the response owns the slot: a failed constructor must release it
            return response
        except (httpx.HTTPError, TimeoutError):
            raise BadRequest(502) from None
        finally:
            if not handed_off:
                await owner.close()

    async def readiness(_):
        value = snapshot()
        try:
            state = store.load()
            ready = bool(value["child"]["transport_ready"]
                         and getattr(state, 'configured', bool(state.backend_url and state.backend_key))
                         and value["backend"] == "reachable")
        except ConfigError:
            ready = False
        # Minimal public status exception, never an unconditional watchdog success.
        return JSONResponse({"ready": ready}, status_code=200 if ready else 503)

    exceptions = {BadRequest: error_handler, ConfigError: error_handler}
    admin = Starlette(routes=[Route("/{path:path}", admin_page, methods=["GET", "HEAD", "PUT", "POST"])],
                      middleware=[Middleware(ui.SecurityHeaders)], exception_handlers=exceptions)
    mcp_app = Starlette(routes=[Route("/mcp", AnyMethod(mcp)), Route("/private_{secret}/mcp", AnyMethod(private_mcp)),
                                Route("/health/ready", readiness)],
                        exception_handlers=exceptions)
    admin.router.redirect_slashes = False
    mcp_app.router.redirect_slashes = False
    return admin, mcp_app
