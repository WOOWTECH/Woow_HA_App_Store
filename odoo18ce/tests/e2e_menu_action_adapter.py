#!/usr/bin/env python3
"""Runtime adapter for the read-only menu/action crawler, and its two-surface diff.

`crawl` opens every menu action of the chosen apps on one surface, up to
`MAX_TRAVERSAL_DEPTH`, and writes one `odoo-parity-evidence/v1` JSONL record
per action: the five signals of the parity plan section 7 step 5 and every URL
literal on the screen (`U-C5`). `diff` joins a Public origin run and an Ingress
run by control identity and gives each action `PARITY` or `GAP`.

The adapter only reads. It fetches the menu tree with one GET and then
navigates to each action's route; it never clicks, types into Odoo records or
calls an RPC, and a menu whose action could write (a server action) is listed
as skipped, never planned.

Credentials come from the environment only:

  ODOO_TEST_LOGIN, ODOO_TEST_PASSWORD   both surfaces
  ODOO_PUBLIC_URL                       --surface public
  HA_BASE_URL, HA_TOKEN, ADDON_SLUG     --surface ha_ingress (HA_TOKEN is a
                                        long-lived access token)
  ODOO_DB, PARITY_TARGET, IGNORE_HTTPS_ERRORS   optional
  HA_BASE_URL on a public run                   optional; set it so a URL
                                        literal pointing at Home Assistant
                                        counts as a U-C5 violation

The Ingress session comes from the websocket `supervisor/api` route; the HTTP
`/api/hassio/...` proxy refuses long-lived tokens. The run then opens the
Ingress prefix as a top-level page with that session cookie.

The pure parts are tested in the static tier by test_e2e_menu_action_adapter.py.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import ipaddress
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, NamedTuple, Sequence
from urllib.parse import urlsplit

from e2e_menu_action_crawler import (
    MAX_TRAVERSAL_DEPTH,
    READ_ONLY_POLICY,
    ActionRecord,
    Manifest,
    MenuRecord,
    Operation,
    PlannedVisit,
    Surface,
    classify_failure,
    normalize_route,
    plan_traversal,
    sanitize_diagnostic,
)

EVIDENCE_SCHEMA = "odoo-parity-evidence/v1"
CLIENT = "desktop-chrome-1920x1080"
SIGNALS = ("pageerror", "console_error", "failed_requests", "http_4xx_5xx", "route_escape")
# Odoo action models the crawler may open. Opening one renders a view or a
# client component; nothing is saved until a user acts. A server action runs
# code on open, a report renders a document and a URL action leaves the web
# client, so those are skipped.
READ_ONLY_ACTION_TYPES = {"ir.actions.act_window": "window", "ir.actions.client": "client"}
_READ_ONLY_KINDS = frozenset(READ_ONLY_ACTION_TYPES.values())
_SKIP_REASONS = {
    "ir.actions.server": "server action may write",
    "ir.actions.report": "report action renders a document",
    "ir.actions.act_url": "URL action leaves the web client",
}
_SURFACE_KEY = {Surface.PUBLIC: "public", Surface.HA_INGRESS: "ingress"}


# --- Scope and plan -------------------------------------------------------


@dataclass(frozen=True)
class SkippedMenu:
    menu_id: str
    app: str
    action_ref: str
    reason: str


class CrawlScope(NamedTuple):
    """The menus of the chosen apps, as a manifest plus what it cannot hold."""

    manifest: Manifest
    apps: Mapping[str, str]  # root menu id -> app
    menu_apps: Mapping[str, str]  # menu id -> app
    action_models: Mapping[str, str]  # action id -> Odoo action model
    skipped: tuple[SkippedMenu, ...]

    def identity(self, visit: PlannedVisit) -> str:
        return control_identity(visit.menu_id, self.action_models[visit.action_id], visit.action_id)


def control_identity(menu_id: str, action_model: str, action_id: str) -> str:
    """Section 1.1 identity for a menu action: its menu xmlid and its action."""
    return "menu:%s|%s:%s" % (menu_id, action_model, action_id)


def _menu_key(entry: Mapping[str, Any]) -> str:
    return entry.get("xmlid") or "menu-%s" % entry["id"]


def scope_from_web_menus(web_menus: Mapping[Any, Any], apps: Iterable[str]) -> CrawlScope:
    """Build the crawl scope from Odoo's `/web/webclient/load_menus` response.

    An app is chosen by module name; its root menu is the top-level menu whose
    xmlid belongs to that module (`contacts.menu_contacts`).
    """
    entries = {str(key): value for key, value in web_menus.items()}
    wanted = list(dict.fromkeys(apps))
    roots: dict[str, str] = {}
    for child in entries["root"]["children"]:
        entry = entries[str(child)]
        module = (entry.get("xmlid") or "").split(".", 1)[0]
        if module in wanted and module not in roots.values():
            roots[str(child)] = module
    missing = [app for app in wanted if app not in roots.values()]
    if missing:
        raise ValueError("crawler configuration: no root menu for app(s) %s" % ", ".join(missing))

    menus: list[MenuRecord] = []
    actions: dict[str, ActionRecord] = {}
    action_models: dict[str, str] = {}
    menu_apps: dict[str, str] = {}
    skipped: list[SkippedMenu] = []

    def add(raw_id: str, parent: str | None, sequence: int, app: str) -> None:
        entry = entries[raw_id]
        key = _menu_key(entry)
        menu_apps[key] = app
        action_model, raw_action = entry.get("actionModel"), entry.get("actionID")
        action_id = None
        if action_model and raw_action:
            action_id = str(raw_action)
            if action_model in READ_ONLY_ACTION_TYPES:
                actions.setdefault(action_id, ActionRecord(
                    action_id, entry.get("name") or key, "/odoo/action-%s" % action_id,
                    action_type=READ_ONLY_ACTION_TYPES[action_model],
                ))
                action_models[action_id] = action_model
            else:
                skipped.append(SkippedMenu(
                    key, app, "%s,%s" % (action_model, action_id),
                    _SKIP_REASONS.get(action_model, "not a read-only action type"),
                ))
                action_id = None
        menus.append(MenuRecord(key, entry.get("name") or key, parent, action_id, sequence))
        for index, child in enumerate(entry.get("children") or ()):
            add(str(child), key, index, app)

    for index, (raw_id, app) in enumerate(roots.items()):
        add(raw_id, None, index, app)
    manifest = Manifest(menus=tuple(menus), actions=tuple(actions.values()))
    return CrawlScope(
        manifest,
        {_menu_key(entries[raw_id]): app for raw_id, app in roots.items()},
        menu_apps, action_models, tuple(skipped),
    )


def plan_visits(scope: CrawlScope, *, max_depth: int = MAX_TRAVERSAL_DEPTH) -> list[PlannedVisit]:
    """Plan the reads; any action that is not read-only makes planning fail."""
    READ_ONLY_POLICY.require(Operation.READ_MENU)
    actions = {action.id: action for action in scope.manifest.actions}
    visits = list(plan_traversal(scope.manifest, max_depth=max_depth).visits)
    for visit in visits:
        if actions[visit.action_id].action_type not in _READ_ONLY_KINDS:
            raise PermissionError("action %s is not read-only" % visit.action_id)
        for operation in visit.operations:
            READ_ONLY_POLICY.require(operation)
    return visits


# --- Home Assistant websocket messages -----------------------------------


def websocket_url(ha_base: str) -> str:
    parts = urlsplit(ha_base.rstrip("/"))
    scheme = {"http": "ws", "https": "wss"}[parts.scheme]
    return "%s://%s%s/api/websocket" % (scheme, parts.netloc, parts.path)


def auth_message(token: str) -> dict[str, str]:
    return {"type": "auth", "access_token": token}


def _supervisor(message_id: int, endpoint: str, method: str, data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"id": message_id, "type": "supervisor/api", "endpoint": endpoint, "method": method}
    if data is not None:
        message["data"] = dict(data)
    return message


def ingress_session_command(message_id: int) -> dict[str, Any]:
    return _supervisor(message_id, "/ingress/session", "post")


def validate_session_command(message_id: int, session: str) -> dict[str, Any]:
    return _supervisor(message_id, "/ingress/validate_session", "post", {"session": session})


def addon_info_command(message_id: int, slug: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9_]+", slug):
        raise ValueError("crawler configuration: invalid ADDON_SLUG")
    return _supervisor(message_id, "/addons/%s/info" % slug, "get")


def notifications_command(message_id: int) -> dict[str, Any]:
    # HA keeps persistent notifications behind the websocket only, not REST states.
    return {"id": message_id, "type": "persistent_notification/get"}


def ws_result(message: Mapping[str, Any], message_id: int) -> Any:
    """The result of command `message_id`, or None for any other message."""
    if message.get("type") != "result" or message.get("id") != message_id:
        return None
    if not message.get("success"):
        error = message.get("error") or {}
        raise RuntimeError("supervisor/api failed: %s %s" % (error.get("code"), error.get("message")))
    return message.get("result")


def ingress_prefix_from_info(info: Mapping[str, Any]) -> str:
    entry = str(info.get("ingress_entry") or "").rstrip("/")
    if not entry:
        raise ValueError("add-on info has no ingress_entry")
    # normalize_route validates the prefix and rejects traversal.
    normalize_route(entry, Surface.HA_INGRESS, ingress_prefix=entry)
    return entry


# --- Masking --------------------------------------------------------------


def _ws_variant(base: str) -> str | None:
    for http, ws in (("https://", "wss://"), ("http://", "ws://")):
        if base.startswith(http):
            return ws + base[len(http):]
    return None


@dataclass(frozen=True)
class Masker:
    """Turns URLs into base codes and removes credentials (section 12)."""

    bases: Mapping[str, str] = field(default_factory=dict)
    ingress_prefix: str | None = None
    secrets: Sequence[str] = ()

    def _replacements(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for code, base in self.bases.items():
            if not base:
                continue
            base = base.rstrip("/")
            variants = [base, _ws_variant(base)]
            for variant in filter(None, variants):
                if self.ingress_prefix and code == "<HA_BASE>":
                    pairs.append((variant + self.ingress_prefix, "<INGRESS_BASE>"))
                pairs.append((variant, code))
        if self.ingress_prefix:
            pairs.append((self.ingress_prefix, "<INGRESS_PREFIX>"))
        pairs.extend((secret, "<redacted>") for secret in self.secrets if secret)
        return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)

    def text(self, value: str) -> str:
        return self.value(value)

    def value(self, value: Any) -> Any:
        """Mask every string in `value`; masking a masked value changes nothing."""
        replacements = self._replacements()

        def walk(item: Any, on_string) -> Any:
            if isinstance(item, str):
                return on_string(item)
            if isinstance(item, Mapping):
                return {key: walk(child, on_string) for key, child in item.items()}
            if isinstance(item, (list, tuple)):
                return type(item)(walk(child, on_string) for child in item)
            return item

        def replace(text: str) -> str:
            for old, new in replacements:
                text = text.replace(old, new)
            return text

        masked = sanitize_diagnostic(walk(value, replace))
        # sanitize_diagnostic reads "?<redacted>" as a new query and redacts it again.
        return walk(masked, lambda text: re.sub(r"(?:<redacted>)+", "<redacted>", text))


# --- Signals --------------------------------------------------------------


def _netloc(url: str) -> str:
    parts = urlsplit(url)
    port = parts.port or {"http": 80, "ws": 80, "https": 443, "wss": 443}.get(parts.scheme)
    return "%s:%s" % ((parts.hostname or "").lower(), port)


def is_prefix_escape(url: str, surface: Surface, origin: str, ingress_prefix: str | None) -> bool:
    """A request or navigation that left the Ingress prefix (`U-A1`, `U-A2`)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https", "ws", "wss"):
        return False
    if surface is Surface.PUBLIC:
        return "/api/hassio_ingress/" in parts.path
    if _netloc(url) != _netloc(origin):
        return False
    if parts.path == ingress_prefix:
        return False
    if not parts.path.startswith(str(ingress_prefix) + "/"):
        return True
    # A second Ingress prefix under the first is the doubled prefix of U-A2.
    return "/api/hassio_ingress/" in parts.path[len(str(ingress_prefix)):]


def _is_loopback(host: str) -> bool:
    if host in ("localhost", "0.0.0.0") or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def url_literal_violation(literal: str, ha_origin: str | None) -> str | None:
    """Why an on-screen URL literal is not a Canonical URL (`U-C5`), if it is not.

    Root-relative literals are navigation and are fine; the Runtime shim puts
    the Ingress prefix on them. An absolute literal must not point at a
    loopback address, carry an Ingress token or point at Home Assistant.
    """
    parts = urlsplit(literal)
    if not parts.netloc:
        return None
    if _is_loopback((parts.hostname or "").lower()):
        return "loopback"
    if "/api/hassio_ingress/" in parts.path:
        return "ingress_token"
    if ha_origin and _netloc(literal) == _netloc(ha_origin):
        return "ha_origin"
    return None


def count_signals(
    *,
    page_errors: Sequence[str],
    console: Sequence[tuple[str, str]],
    failed_requests: Sequence[str],
    responses: Sequence[tuple[int, str]],
    urls: Sequence[str],
    surface: Surface,
    origin: str,
    ingress_prefix: str | None,
) -> dict[str, int]:
    """The five signals of parity plan section 7 step 5."""
    return {
        "pageerror": len(page_errors),
        "console_error": sum(1 for kind, _ in console if kind == "error"),
        "failed_requests": len(failed_requests),
        "http_4xx_5xx": sum(1 for status, _ in responses if status >= 400),
        "route_escape": sum(1 for url in urls if is_prefix_escape(url, surface, origin, ingress_prefix)),
    }


# --- Evidence and diff ----------------------------------------------------


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    target: str
    database: str
    client: str = CLIENT


@dataclass(frozen=True)
class SurfaceObservation:
    available: bool
    result: str
    signals: Mapping[str, int]
    route: str | None
    model: str | None
    view: str | None
    url_literals: Sequence[str] = ()
    url_violations: Sequence[Mapping[str, str]] = ()
    http_5xx: int = 0


# Odoo 18 switches to its small-screen layout below this width.
_SMALL_SCREEN_WIDTH = 768


def parse_viewport(text: str) -> tuple[tuple[int, int], str]:
    """`390x844` -> the viewport and the client label its records carry.

    A width Odoo lays out for small screens is labelled mobile-emulation: it
    is the desktop browser at phone size, not a phone or the Companion app.
    """
    match = re.fullmatch(r"([1-9][0-9]{1,4})x([1-9][0-9]{1,4})", text.strip())
    if not match:
        raise ValueError("viewport must look like 390x844, got %r" % text)
    width, height = int(match.group(1)), int(match.group(2))
    kind = "mobile-emulation-chrome" if width < _SMALL_SCREEN_WIDTH else "desktop-chrome"
    return (width, height), "%s-%dx%d" % (kind, width, height)


def new_run_id() -> str:
    return "WOOW-PARITY-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _base_record(run: RunInfo, module: str, identity: str, screen: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": EVIDENCE_SCHEMA,
        "run_id": run.run_id,
        "target": run.target,
        "database": run.database,
        "client": run.client,
        "layer": "L3",
        "item": "U-C12",
        "root_cause": ["RC-1"],
        "module": module,
        "screen": dict(screen),
        "control_identity": identity,
    }


def evidence_record(
    run: RunInfo, surface: Surface, *, module: str, identity: str, observation: SurfaceObservation
) -> dict[str, Any]:
    """One surface's record; `verdict` stays empty until `diff` joins two runs."""
    screen = {"route": observation.route, "model": observation.model, "view": observation.view}
    record = _base_record(run, module, identity, screen)
    record[_SURFACE_KEY[surface]] = {
        "available": observation.available,
        "result": observation.result,
        "screen": screen,
        "signals": {name: int(observation.signals.get(name, 0)) for name in SIGNALS},
        "url_literals": sorted(set(observation.url_literals)),
        "url_violations": [dict(item) for item in observation.url_violations],
        "http_5xx": int(observation.http_5xx),
    }
    if observation.url_violations:
        record["root_cause"] = ["RC-1", "RC-9"]
    record.update({"verdict": None, "severity": None, "artifacts": [], "notes": ""})
    return record


def skipped_record(run: RunInfo, surface: Surface, *, module: str, identity: str, reason: str) -> dict[str, Any]:
    record = _base_record(run, module, identity, {"route": None, "model": None, "view": None})
    record[_SURFACE_KEY[surface]] = {"available": False, "result": "skipped: " + reason}
    record.update({"verdict": None, "severity": None, "artifacts": [], "notes": "", "skipped": reason})
    return record


def read_records(lines: Iterable[str]) -> list[dict[str, Any]]:
    records = []
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("schema") != EVIDENCE_SCHEMA:
            raise ValueError("not an %s record: schema=%r" % (EVIDENCE_SCHEMA, record.get("schema")))
        records.append(record)
    return records


def _index(records: Iterable[Mapping[str, Any]], key: str) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if key not in record:
            raise ValueError("a %s run holds a record of another surface: %s" % (key, record.get("control_identity")))
        identity = record["control_identity"]
        if identity in indexed:
            raise ValueError("ambiguous control identity in the %s run: %s" % (key, identity))
        indexed[identity] = record
    return indexed


_BASE_CODES = ("<PUBLIC_BASE>", "<INGRESS_BASE>", "<INGRESS_PREFIX>")


def _logical_literals(block: Mapping[str, Any]) -> set[str]:
    """Masked literals as paths, so both surfaces compare.

    Odoo writes some URLs absolute on the Public origin and root-relative under
    Ingress; both name the same path. A literal on the wrong base is a U-C5
    violation and is reported as one, not here.
    """
    literals = set()
    for literal in block.get("url_literals") or ():
        for code in _BASE_CODES:
            if literal.startswith(code + "/"):
                literal = literal[len(code):]
                break
        literals.add(literal)
    return literals


def _literal_differences(public: Mapping[str, Any], ingress: Mapping[str, Any]) -> list[str]:
    """Section 1.1 item 3: the URLs on the screen point at the same places."""
    left, right = _logical_literals(public), _logical_literals(ingress)
    reasons = []
    for name, only in (("public", left - right), ("ingress", right - left)):
        if only:
            shown = sorted(only)
            more = " (+%d more)" % (len(shown) - 5) if len(shown) > 5 else ""
            reasons.append("URL literals only on %s: %s%s" % (name, ", ".join(shown[:5]), more))
    return reasons


def _judge(public: Mapping[str, Any], ingress: Mapping[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    blocker = False
    for name, block in (("public", public), ("ingress", ingress)):
        if not block.get("available"):
            reasons.append("%s unavailable: %s" % (name, block.get("result")))
            blocker = True
    for name, block in (("public", public), ("ingress", ingress)):
        for signal in SIGNALS:
            count = (block.get("signals") or {}).get(signal, 0)
            if count:
                reasons.append("%s %s=%d" % (name, signal, count))
                blocker = blocker or signal == "route_escape"
        # Section 1.3: a 5xx is a Blocker, a 4xx is Important.
        blocker = blocker or bool(block.get("http_5xx"))
        for violation in block.get("url_violations") or ():
            reasons.append("%s U-C5 %s: %s" % (name, violation.get("reason"), violation.get("literal")))
            blocker = True
    if public.get("available") and ingress.get("available"):
        for part in ("route", "model", "view"):
            left, right = (public.get("screen") or {}).get(part), (ingress.get("screen") or {}).get(part)
            if left != right:
                reasons.append("%s: public=%s ingress=%s" % (part, left, right))
        reasons.extend(_literal_differences(public, ingress))
    if not reasons:
        return "none", reasons
    return ("blocker" if blocker else "important"), reasons


def diff_runs(public_run: Iterable[Mapping[str, Any]], ingress_run: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Join two single-surface runs by control identity and judge each action."""
    public, ingress = _index(public_run, "public"), _index(ingress_run, "ingress")
    merged: list[dict[str, Any]] = []
    for identity in sorted(public.keys() | ingress.keys()):
        left, right = public.get(identity), ingress.get(identity)
        base = dict(left or right)
        base["runs"] = {"public": left and left["run_id"], "ingress": right and right["run_id"]}
        base["public"] = left and left["public"]
        base["ingress"] = right and right["ingress"]
        if left is None or right is None:
            missing = "ingress" if right is None else "public"
            base.update(verdict="GAP", severity="blocker", notes="absent on %s" % missing)
            base.pop("skipped", None)
        elif "skipped" in left or "skipped" in right:
            if "skipped" in left and "skipped" in right:
                base.update(verdict=None, severity=None, notes="skipped: " + left["skipped"])
            else:
                side = "public" if "skipped" in left else "ingress"
                base.pop("skipped", None)
                base.update(verdict="GAP", severity="important", notes="skipped on %s only" % side)
        else:
            severity, reasons = _judge(left["public"], right["ingress"])
            base.update(verdict="GAP" if reasons else "PARITY", severity=severity, notes="; ".join(reasons))
        merged.append(base)
    return merged


def verdict_lines(merged: Iterable[Mapping[str, Any]]) -> list[str]:
    lines = []
    for record in merged:
        identity = record["control_identity"]
        if record.get("skipped"):
            lines.append("SKIPPED %s: %s" % (identity, record["skipped"]))
        elif record["verdict"] == "PARITY":
            lines.append("PARITY %s" % identity)
        else:
            lines.append("%s %s: %s" % (record["verdict"], identity, record["notes"]))
    return lines


# --- Runtime (Live tier) --------------------------------------------------


def parse_env_file(lines: Iterable[str], environ: dict[str, str]) -> None:
    """Fill `environ` from `NAME=value` lines; a name already set wins."""
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or line.startswith("#") or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        environ.setdefault(name, value)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError("missing environment %s" % name)
    return value


class IngressSession:
    """An Ingress session opened and kept alive over the HA websocket."""

    REFRESH_SECONDS = 60

    def __init__(self, ha_base: str, token: str, slug: str, *, verify_tls: bool = True) -> None:
        from websockets.sync.client import connect

        ssl_context = None
        if websocket_url(ha_base).startswith("wss://") and not verify_tls:
            import ssl

            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        # websockets wants connect() entered as a context manager; the stack
        # keeps it open for the whole crawl and close() exits it.
        self._stack = contextlib.ExitStack()
        self._socket = self._stack.enter_context(
            connect(websocket_url(ha_base), ssl=ssl_context, open_timeout=30)
        )
        self._next_id = 1
        if json.loads(self._socket.recv(timeout=30)).get("type") != "auth_required":
            raise RuntimeError("HA websocket did not ask for authentication")
        self._socket.send(json.dumps(auth_message(token)))
        if json.loads(self._socket.recv(timeout=30)).get("type") != "auth_ok":
            raise RuntimeError("HA websocket authentication failed (unauthorized)")
        self.prefix = ingress_prefix_from_info(self._call(lambda i: addon_info_command(i, slug)))
        self.session = str(self._call(ingress_session_command)["session"])
        self._validated = time.monotonic()

    def _call(self, build) -> Any:
        message_id, self._next_id = self._next_id, self._next_id + 1
        self._socket.send(json.dumps(build(message_id)))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            message = json.loads(self._socket.recv(timeout=30))
            # Match the id first: a command may succeed with a null result.
            if message.get("type") == "result" and message.get("id") == message_id:
                return ws_result(message, message_id)
        raise RuntimeError("HA websocket gave no result for %s" % message_id)

    def keep_alive(self) -> None:
        if time.monotonic() - self._validated >= self.REFRESH_SECONDS:
            self._call(lambda i: validate_session_command(i, self.session))
            self._validated = time.monotonic()

    def notifications(self) -> list[dict[str, Any]]:
        """The persistent notifications Home Assistant holds now."""
        return self._call(notifications_command) or []

    def close(self) -> None:
        self._stack.close()


# An empty list or kanban view shows sample records with avatars of users
# picked at random on every load; they are not data, so their literals are
# left out or two runs of one screen would never agree.
_URL_LITERALS_JS = r"""() => {
  const out = new Set();
  const re = /\b(?:https?|wss?):\/\/[^\s"'<>]+/g;
  const skip = /^(?:data:|blob:|javascript:|mailto:|tel:|#)/i;
  for (const el of document.body.querySelectorAll('[href],[src],[action],[data-src]')) {
    if (el.closest('.o_view_sample_data')) continue;
    for (const name of ['href', 'src', 'action', 'data-src']) {
      const value = el.getAttribute(name);
      if (value && !skip.test(value.trim())) out.add(value.trim());
    }
  }
  for (const el of document.body.querySelectorAll('input,textarea')) {
    for (const match of (el.value || '').match(re) || []) out.add(match);
  }
  for (const match of (document.body.innerText || '').match(re) || []) out.add(match);
  return [...out];
}"""

# The action, model and view of the current controller. `__WOWL_DEBUG__`
# exposes the web client's root; the DOM class is the fallback for the view
# type. Without it the action cannot be checked and stays null.
_SCREEN_JS = r"""() => {
  let model = null, view = null, action = null;
  try {
    const controller = odoo.__WOWL_DEBUG__.root.env.services.action.currentController;
    action = (controller.action && controller.action.id) || null;
    model = (controller.action && controller.action.res_model) || null;
    view = (controller.view && controller.view.type) || null;
  } catch (error) {}
  if (!view) {
    const node = document.querySelector('.o_action_manager .o_view_controller');
    const match = node && [...node.classList].map(c => /^o_(\w+)_view$/.exec(c)).find(Boolean);
    view = match ? match[1] : null;
  }
  return {model, view, action};
}"""


class SurfaceDriver:
    """Logs in on one surface and opens planned visits, reading only."""

    def __init__(
        self, surface: Surface, browser, *, ignore_https_errors: bool, viewport: tuple[int, int] = (1920, 1080),
    ) -> None:
        self.surface = surface
        self.ingress: IngressSession | None = None
        self.login = _require_env("ODOO_TEST_LOGIN")
        self.password = _require_env("ODOO_TEST_PASSWORD")
        public_base = os.environ.get("ODOO_PUBLIC_URL", "").rstrip("/")
        ha_base = os.environ.get("HA_BASE_URL", "").rstrip("/")
        secrets = [self.login, self.password]
        if surface is Surface.PUBLIC:
            self.origin = _require_env("ODOO_PUBLIC_URL").rstrip("/")
            self.base = self.origin
            prefix = None
        else:
            self.origin = _require_env("HA_BASE_URL").rstrip("/")
            token = _require_env("HA_TOKEN")
            secrets.append(token)
            self.ingress = IngressSession(
                self.origin, token, _require_env("ADDON_SLUG"), verify_tls=not ignore_https_errors,
            )
            secrets.append(self.ingress.session)
            prefix = self.ingress.prefix
            self.base = self.origin + prefix
        self.prefix = prefix
        self.ha_origin = ha_base or None
        self.masker = Masker(
            bases={"<PUBLIC_BASE>": public_base, "<HA_BASE>": ha_base},
            ingress_prefix=prefix,
            secrets=tuple(secrets),
        )
        self.context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}, ignore_https_errors=ignore_https_errors,
        )
        if self.ingress:
            host = urlsplit(self.origin)
            self.context.add_cookies([{
                "name": "ingress_session", "value": self.ingress.session,
                "domain": host.hostname, "path": "/api/hassio_ingress/",
                "secure": host.scheme == "https", "httpOnly": False, "sameSite": "Lax",
            }])

    def log_in(self) -> None:
        page = self.context.new_page()
        try:
            db = os.environ.get("ODOO_DB")
            page.goto(self.base + "/web/login" + ("?db=" + db if db else ""), wait_until="domcontentloaded", timeout=120000)
            if page.locator('input[name="login"]').count():
                page.locator('input[name="login"]').fill(self.login)
                page.locator('input[name="password"]').fill(self.password)
                # Enter submits the login form itself; with `website` installed the
                # page header has a search form whose submit button comes first.
                page.locator('input[name="password"]').press("Enter")
            page.locator(".o_main_navbar").wait_for(timeout=60000)
        finally:
            page.close()

    def web_menus(self) -> Mapping[str, Any]:
        READ_ONLY_POLICY.require(Operation.READ_MENU)
        response = self.context.request.get(self.base + "/web/webclient/load_menus/%d" % time.time())
        if response.status != 200:
            raise RuntimeError("load_menus answered HTTP %d" % response.status)
        return response.json()

    def _route(self, url: str) -> str | None:
        try:
            parts = urlsplit(url)
            if _netloc(url) != _netloc(self.origin):
                return None
            return normalize_route(parts.path, self.surface, ingress_prefix=self.prefix).as_string()
        except ValueError:
            return None

    def observe(self, visit: PlannedVisit) -> SurfaceObservation:
        READ_ONLY_POLICY.require(Operation.NAVIGATE)
        if self.ingress:
            self.ingress.keep_alive()
        page = self.context.new_page()
        page_errors: list[str] = []
        console: list[tuple[str, str]] = []
        failed: list[str] = []
        responses: list[tuple[int, str]] = []
        urls: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: console.append((message.type, message.text)))
        page.on("requestfailed", lambda request: failed.append(request.url))
        page.on("response", lambda response: responses.append((response.status, response.url)))
        page.on("request", lambda request: urls.append(request.url))
        page.on("framenavigated", lambda frame: urls.append(frame.url) if frame == page.main_frame else None)
        page.on("websocket", lambda socket: urls.append(socket.url))
        available, result, screen, literals = True, "loaded", {}, []
        try:
            page.goto(self.base + visit.route, wait_until="load", timeout=60000)
            # An action with target "new" (a wizard) opens in a dialog and
            # leaves the action manager empty.
            page.locator(".o_action_manager > *, .o_dialog .modal-content").first.wait_for(timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:  # Odoo can keep a request open; the settle below still applies.
                pass
            page.wait_for_timeout(500)
            screen = page.evaluate(_SCREEN_JS) or {}
            literals = page.evaluate(_URL_LITERALS_JS)
            loaded = screen.get("action")
            if loaded is not None and str(loaded) != visit.action_id:
                # U-C12: the menu's action must load, not a fallback such as Discuss.
                available = False
                result = "loaded action %s instead of %s" % (loaded, visit.action_id)
        except Exception as error:  # noqa: BLE001 -- every failure is evidence, not a crash
            available = False
            result = "error (%s): %s" % (classify_failure(error).value, (str(error).splitlines() or [""])[0])
        signals = count_signals(
            page_errors=page_errors, console=console, failed_requests=failed, responses=responses,
            urls=urls, surface=self.surface, origin=self.origin, ingress_prefix=self.prefix,
        )
        route = self._route(page.url)
        page.close()
        violations = []
        for literal in literals:
            reason = url_literal_violation(literal, self.ha_origin)
            if reason:
                violations.append({"literal": self.masker.text(literal), "reason": reason})
        return SurfaceObservation(
            available=available, result=self.masker.text(result), signals=signals,
            route=route, model=screen.get("model"), view=screen.get("view"),
            url_literals=tuple(self.masker.text(literal) for literal in literals),
            url_violations=tuple(violations),
            http_5xx=sum(1 for status, _ in responses if status >= 500),
        )

    def close(self) -> None:
        self.context.close()
        if self.ingress:
            self.ingress.close()


def crawl(surface: Surface, apps: Sequence[str], out, *, viewport: str = "1920x1080") -> int:
    from playwright.sync_api import sync_playwright

    size, client = parse_viewport(viewport)
    run = RunInfo(new_run_id(), os.environ.get("PARITY_TARGET", "local"), os.environ.get("ODOO_DB", "default"), client)
    ignore_https = os.environ.get("IGNORE_HTTPS_ERRORS", "0") == "1"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        driver = None
        try:
            driver = SurfaceDriver(surface, browser, ignore_https_errors=ignore_https, viewport=size)
            driver.log_in()
            scope = scope_from_web_menus(driver.web_menus(), apps)
            visits = plan_visits(scope)
            for skipped in scope.skipped:
                identity = control_identity(skipped.menu_id, *skipped.action_ref.split(","))
                record = skipped_record(run, surface, module=skipped.app, identity=identity, reason=skipped.reason)
                out.write(json.dumps(driver.masker.value(record), ensure_ascii=False, sort_keys=True) + "\n")
            signalled = 0
            for visit in visits:
                observation = driver.observe(visit)
                record = evidence_record(
                    run, surface, module=scope.menu_apps[visit.menu_id],
                    identity=scope.identity(visit), observation=observation,
                )
                out.write(json.dumps(driver.masker.value(record), ensure_ascii=False, sort_keys=True) + "\n")
                out.flush()
                noisy = not observation.available or any(observation.signals.values()) or observation.url_violations
                signalled += bool(noisy)
                print("%s %s" % ("SIGNAL" if noisy else "CLEAN ", scope.identity(visit)), file=sys.stderr)
            print("%d actions, %d with signals, %d skipped; run %s"
                  % (len(visits), signalled, len(scope.skipped), run.run_id), file=sys.stderr)
            return 1 if signalled else 0
        finally:
            if driver:
                driver.close()
            browser.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    crawl_parser = commands.add_parser("crawl", help="open every menu action of the chosen apps on one surface")
    crawl_parser.add_argument("--surface", required=True, choices=[surface.value for surface in Surface])
    crawl_parser.add_argument("--apps", required=True, help="comma-separated module names, e.g. contacts,project")
    crawl_parser.add_argument("--out", required=True, help="JSONL evidence file to write")
    crawl_parser.add_argument("--env-file", help="read unset credentials from this NAME=value file")
    crawl_parser.add_argument("--viewport", default="1920x1080",
                              help="WIDTHxHEIGHT; below 768 wide Odoo uses its mobile layout (default 1920x1080)")
    diff_parser = commands.add_parser("diff", help="judge a Public origin run against an Ingress run")
    diff_parser.add_argument("public_run")
    diff_parser.add_argument("ingress_run")
    diff_parser.add_argument("--out", help="JSONL file for the joined records")
    args = parser.parse_args(argv)

    if args.command == "crawl":
        if args.env_file:
            with open(args.env_file, encoding="utf-8") as env_file:
                parse_env_file(env_file, os.environ)
        apps = [app.strip() for app in args.apps.split(",") if app.strip()]
        with open(args.out, "w", encoding="utf-8") as out:
            return crawl(Surface(args.surface), apps, out, viewport=args.viewport)

    with open(args.public_run, encoding="utf-8") as public, open(args.ingress_run, encoding="utf-8") as ingress:
        merged = diff_runs(read_records(public), read_records(ingress))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as out:
            for record in merged:
                out.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    for line in verdict_lines(merged):
        print(line)
    judged = [record for record in merged if not record.get("skipped")]
    gaps = sum(1 for record in judged if record["verdict"] == "GAP")
    print("%d judged = %d PARITY + %d GAP; %d skipped"
          % (len(judged), len(judged) - gaps, gaps, len(merged) - len(judged)))
    return 1 if gaps else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 -- never print an unmasked secret
        print("crawler failed (%s): %s" % (classify_failure(error).value, sanitize_diagnostic(str(error))), file=sys.stderr)
        sys.exit(2)
