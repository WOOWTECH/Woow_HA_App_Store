#!/usr/bin/env python3
"""Pure, credential-free contracts for a read-only Odoo menu/action/view crawler.

This module deliberately has no browser, HTTP, RPC, or Odoo dependencies.  A
runtime adapter may collect records and execute the plans produced here, but it
must not add write operations to the policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit, urlunsplit

MANIFEST_SCHEMA_VERSION = 1
MAX_TRAVERSAL_DEPTH = 3


class Surface(str, Enum):
    PUBLIC = "public"
    HA_INGRESS = "ha_ingress"


class Operation(str, Enum):
    READ_MENU = "read_menu"
    READ_ACTION = "read_action"
    READ_VIEW = "read_view"
    NAVIGATE = "navigate"


NON_MUTATING_OPERATIONS = frozenset(Operation)


@dataclass(frozen=True)
class OperationPolicy:
    """An allow-list: no create, edit, delete, submit, or RPC write exists."""

    allowed: frozenset[Operation] = NON_MUTATING_OPERATIONS

    def permits(self, operation: Operation) -> bool:
        return operation in self.allowed and operation in NON_MUTATING_OPERATIONS

    def require(self, operation: Operation) -> None:
        if not self.permits(operation):
            raise PermissionError("mutating or unknown crawler operation: %s" % operation)


READ_ONLY_POLICY = OperationPolicy()


@dataclass(frozen=True)
class NormalizedRoute:
    """A logical route shared by public and ingress manifests, never a URL."""

    path: str
    query: str = ""
    fragment: str = ""

    def as_string(self) -> str:
        return urlunsplit(("", "", self.path, self.query, self.fragment))


def _safe_path(path: str) -> str:
    if not path.startswith("/"):
        raise ValueError("route must be an absolute path")
    if "\\" in path or any(unquote(part) in {".", ".."} for part in path.split("/")):
        raise ValueError("route traversal is not allowed")
    # Do not silently coalesce slash variants: they can have different routing.
    return path


def _safe_ingress_prefix(prefix: str) -> str:
    parts = urlsplit(prefix)
    if parts.scheme or parts.netloc or parts.query or parts.fragment:
        raise ValueError("ingress prefix must be a path")
    path = _safe_path(parts.path).rstrip("/")
    if not re.fullmatch(r"/api/hassio_ingress/[A-Za-z0-9_-]{1,256}", path):
        raise ValueError("invalid HA ingress prefix")
    return path


def normalize_route(
    route: str, surface: Surface, *, ingress_prefix: str | None = None
) -> NormalizedRoute:
    """Convert a surface route to a manifest's logical route.

    Public routes must not contain an HA ingress prefix.  HA routes must start
    with the supplied, validated prefix, which is stripped rather than retained
    in a surface-independent manifest.
    """
    parts = urlsplit(route)
    if parts.scheme or parts.netloc or parts.username or parts.password:
        raise ValueError("route must not contain an origin or credentials")
    path = _safe_path(parts.path)
    if surface is Surface.PUBLIC:
        if path.startswith("/api/hassio_ingress/"):
            raise ValueError("public route must not use HA ingress")
        logical = path
    elif surface is Surface.HA_INGRESS:
        if not ingress_prefix:
            raise ValueError("HA ingress route requires ingress_prefix")
        prefix = _safe_ingress_prefix(ingress_prefix)
        if path == prefix:
            logical = "/"
        elif path.startswith(prefix + "/"):
            logical = path[len(prefix):]
        else:
            raise ValueError("HA ingress route is outside ingress_prefix")
    else:
        raise ValueError("unknown surface: %r" % surface)
    # Manifests must never retain URL query values. They can carry OAuth,
    # database-selection, and session credentials, and are not part of a logical
    # menu/action/view route.
    return NormalizedRoute(logical, "", parts.fragment)


@dataclass(frozen=True)
class MenuRecord:
    id: str
    name: str
    parent_id: str | None = None
    action_id: str | None = None
    sequence: int = 0


@dataclass(frozen=True)
class ActionRecord:
    id: str
    name: str
    route: str
    view_ids: tuple[str, ...] = ()
    action_type: str = "window"


@dataclass(frozen=True)
class ViewRecord:
    id: str
    name: str
    model: str
    view_type: str


@dataclass(frozen=True)
class Manifest:
    """Versioned, deterministic, surface-independent menu/action/view data."""

    menus: tuple[MenuRecord, ...] = ()
    actions: tuple[ActionRecord, ...] = ()
    views: tuple[ViewRecord, ...] = ()
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported manifest schema version")
        for records, label in ((self.menus, "menu"), (self.actions, "action"), (self.views, "view")):
            ids = [record.id for record in records]
            if any(not item for item in ids) or len(ids) != len(set(ids)):
                raise ValueError("%s IDs must be non-empty and unique" % label)
        action_ids, view_ids, menu_ids = self.action_ids, self.view_ids, self.menu_ids
        for menu in self.menus:
            if menu.parent_id is not None and menu.parent_id not in menu_ids:
                raise ValueError("menu parent is absent: %s" % menu.parent_id)
            if menu.action_id is not None and menu.action_id not in action_ids:
                raise ValueError("menu action is absent: %s" % menu.action_id)
        for action in self.actions:
            try:
                normalized_route = normalize_route(action.route, Surface.PUBLIC).as_string()
            except ValueError as error:
                raise ValueError("action route must be a logical absolute route") from error
            if normalized_route != action.route:
                raise ValueError("action route must be normalized")
            if not set(action.view_ids).issubset(view_ids):
                raise ValueError("action view is absent")

    @property
    def menu_ids(self) -> frozenset[str]:
        return frozenset(record.id for record in self.menus)

    @property
    def action_ids(self) -> frozenset[str]:
        return frozenset(record.id for record in self.actions)

    @property
    def view_ids(self) -> frozenset[str]:
        return frozenset(record.id for record in self.views)

    def normalized(self) -> dict[str, Any]:
        """Return the portable manifest schema with deterministic record order."""
        return {
            "schema_version": self.schema_version,
            "menus": [asdict(item) for item in sorted(self.menus, key=lambda item: item.id)],
            "actions": [asdict(item) for item in sorted(self.actions, key=lambda item: item.id)],
            "views": [asdict(item) for item in sorted(self.views, key=lambda item: item.id)],
        }


@dataclass(frozen=True)
class PlannedVisit:
    menu_id: str
    action_id: str
    route: str
    depth: int
    operations: frozenset[Operation] = NON_MUTATING_OPERATIONS


@dataclass(frozen=True)
class TraversalPlan:
    visits: tuple[PlannedVisit, ...]
    max_depth: int
    policy: OperationPolicy = READ_ONLY_POLICY


def plan_traversal(manifest: Manifest, *, max_depth: int = MAX_TRAVERSAL_DEPTH) -> TraversalPlan:
    """Plan menu-linked reads only; callers execute nothing through this API."""
    if not 0 <= max_depth <= MAX_TRAVERSAL_DEPTH:
        raise ValueError("max_depth must be between 0 and %d" % MAX_TRAVERSAL_DEPTH)
    menus = {item.id: item for item in manifest.menus}
    actions = {item.id: item for item in manifest.actions}
    children: dict[str | None, list[MenuRecord]] = {}
    for menu in manifest.menus:
        children.setdefault(menu.parent_id, []).append(menu)
    for siblings in children.values():
        siblings.sort(key=lambda item: (item.sequence, item.id))
    # Check the full tree before applying the depth cap, so deep valid trees
    # are not mistaken for cycles.
    for menu in manifest.menus:
        seen: set[str] = set()
        current = menu
        while True:
            if current.id in seen:
                raise ValueError("cyclic menu tree")
            seen.add(current.id)
            if current.parent_id is None:
                break
            current = menus[current.parent_id]

    visits: list[PlannedVisit] = []

    def walk(menu: MenuRecord, depth: int, ancestry: frozenset[str]) -> None:
        if menu.id in ancestry:
            raise ValueError("cyclic menu tree")
        if depth > max_depth:
            return
        if menu.action_id:
            action = actions[menu.action_id]
            visits.append(PlannedVisit(menu.id, action.id, action.route, depth))
        for child in children.get(menu.id, []):
            walk(child, depth + 1, ancestry | {menu.id})

    for root in children.get(None, []):
        walk(root, 0, frozenset())
    return TraversalPlan(tuple(visits), max_depth)


class FailureClass(str, Enum):
    AUTH = "auth"
    FRAME = "frame"
    HARNESS = "harness"
    PRODUCT = "product"


@dataclass(frozen=True)
class FailureRecord:
    category: FailureClass
    message: str


_AUTH_MARKERS = ("401", "403", "unauthorized", "forbidden", "login required", "authentication")
_FRAME_MARKERS = ("frame was detached", "frame has been detached", "execution context was destroyed", "iframe")
_HARNESS_MARKERS = ("missing environment", "invalid manifest", "crawler configuration", "playwright is not installed")


def classify_failure(error: BaseException | str) -> FailureClass:
    text = str(error).lower()
    if any(marker in text for marker in _AUTH_MARKERS):
        return FailureClass.AUTH
    if any(marker in text for marker in _FRAME_MARKERS):
        return FailureClass.FRAME
    if any(marker in text for marker in _HARNESS_MARKERS):
        return FailureClass.HARNESS
    return FailureClass.PRODUCT


_SECRET_KEY = re.compile(r"(authorization|cookie|password|secret|token|session|api[_-]?key)", re.I)
_INGRESS_TOKEN = re.compile(r"(?P<prefix>/?api/hassio_ingress/)[^/\s?#<>\"']+")
_QUERY = re.compile(r"\?[^\s#<>\"']*")
_BEARER = re.compile(r"(?i)(bearer\s+)[^\s,;]+")


def sanitize_diagnostic(value: Any) -> Any:
    """Redact ingress tokens, query strings, and secret-bearing mapping values."""
    if isinstance(value, str):
        value = _INGRESS_TOKEN.sub(lambda match: match.group("prefix") + "<redacted>", value)
        value = _QUERY.sub("?<redacted>", value)
        return _BEARER.sub(r"\1<redacted>", value)
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if _SECRET_KEY.search(str(key)) else sanitize_diagnostic(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(sanitize_diagnostic(item) for item in value)
    if isinstance(value, list):
        return [sanitize_diagnostic(item) for item in value]
    return value


@dataclass(frozen=True)
class ParityDifference:
    record_type: str
    record_id: str
    public: Any | None
    ha_ingress: Any | None


@dataclass(frozen=True)
class ParityReconciliation:
    differences: tuple[ParityDifference, ...] = ()

    @property
    def matches(self) -> bool:
        return not self.differences


def reconcile_parity(public: Manifest, ha_ingress: Manifest) -> ParityReconciliation:
    """Compare logical records only, so ingress tokens can never affect parity."""
    differences: list[ParityDifference] = []
    for field_name in ("menus", "actions", "views"):
        public_records = {item.id: asdict(item) for item in getattr(public, field_name)}
        ingress_records = {item.id: asdict(item) for item in getattr(ha_ingress, field_name)}
        for record_id in sorted(public_records.keys() | ingress_records.keys()):
            left, right = public_records.get(record_id), ingress_records.get(record_id)
            if left != right:
                differences.append(ParityDifference(field_name[:-1], record_id, left, right))
    return ParityReconciliation(tuple(differences))
