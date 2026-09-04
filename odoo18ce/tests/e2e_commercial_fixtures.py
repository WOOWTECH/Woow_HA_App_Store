#!/usr/bin/env python3
"""Credential-free fixture ledger for future commercial E2E lanes.

This module deliberately has no Odoo, browser, HTTP, or credential integration.
It records only locally supplied fixture metadata, produces cleanup and marker-scan
instructions, and persists a sanitized JSON ledger for a later lane to consume.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

SCHEMA_VERSION = 1
LEDGER_OWNER = "commercial-e2e-fixture-ledger"
_SENSITIVE_KEY = re.compile(r"(?:pass(?:word)?|secret|token|authorization|cookie|api[_-]?key|session)", re.I)
_INGRESS_TOKEN = re.compile(r"(?P<prefix>/?api/hassio_ingress/)[^/\s?#]+")
_QUERY = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://[^\s?#]+|/[^\s?#]+)\?[^\s#<>\"']*")
_BEARER = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_SENSITIVE_ASSIGNMENT = re.compile(r"(?i)((?:pass(?:word)?|secret|token|authorization|cookie|api[_-]?key|session)\s*=\s*)[^&\s,;]+")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class LedgerError(ValueError):
    """Raised when locally supplied fixture metadata is unsafe or inconsistent."""


class FixtureState(str, Enum):
    DECLARED = "declared"
    MATERIALIZED = "materialized"
    CLEANUP_PLANNED = "cleanup_planned"
    CLEANED = "cleaned"
    CLEANUP_FAILED = "cleanup_failed"


_ALLOWED_TRANSITIONS = {
    FixtureState.DECLARED: {FixtureState.MATERIALIZED, FixtureState.CLEANUP_PLANNED},
    FixtureState.MATERIALIZED: {FixtureState.CLEANUP_PLANNED},
    FixtureState.CLEANUP_PLANNED: {FixtureState.CLEANED, FixtureState.CLEANUP_FAILED},
    FixtureState.CLEANUP_FAILED: {FixtureState.CLEANUP_PLANNED},
    FixtureState.CLEANED: set(),
}


def utc_now() -> str:
    """Return a sortable, timezone-explicit timestamp without external I/O."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def create_run_id(prefix: str = "commercial") -> str:
    """Create a collision-resistant identifier suitable for fixture markers."""
    safe_prefix = _SAFE_NAME.sub("-", prefix).strip("-.")
    if not safe_prefix:
        raise LedgerError("run id prefix must contain an alphanumeric character")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{safe_prefix}-{stamp}-{uuid.uuid4().hex}"


def sanitize_artifact(value: Any) -> Any:
    """Redact credential-shaped data before it can enter a local artifact."""
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if _SENSITIVE_KEY.search(str(key)) else sanitize_artifact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_artifact(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_artifact(item) for item in value]
    if isinstance(value, str):
        value = _INGRESS_TOKEN.sub(r"\g<prefix><redacted>", value)
        value = _QUERY.sub(r"\1?<redacted>", value)
        value = _BEARER.sub(r"\1<redacted>", value)
        return _SENSITIVE_ASSIGNMENT.sub(r"\1<redacted>", value)
    return value


def safe_artifact_name(value: str, suffix: str = ".json") -> str:
    """Return a traversal-free local artifact name; no caller value becomes a path."""
    name = _SAFE_NAME.sub("-", value).strip(".-")
    if not name:
        raise LedgerError("artifact name must contain an alphanumeric character")
    return name + ("" if name.endswith(suffix) else suffix)


@dataclass(frozen=True)
class BaselineSnapshot:
    """A declaration of expected pre-run state; it never reads remote state."""

    name: str
    scope: tuple[str, ...]
    declared_at: str = field(default_factory=utc_now)
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.scope or any(not item for item in self.scope):
            raise LedgerError("baseline snapshot needs a name and at least one scope")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "scope": list(self.scope), "declared_at": self.declared_at, "fingerprint": self.fingerprint}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BaselineSnapshot":
        return cls(value["name"], tuple(value["scope"]), value["declared_at"], value.get("fingerprint"))


@dataclass(frozen=True)
class FixtureRecord:
    """One fixture owned by exactly one ledger marker."""

    fixture_id: str
    resource_type: str
    owner_marker: str
    dependencies: tuple[str, ...] = ()
    state: FixtureState = FixtureState.DECLARED
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.fixture_id or not self.resource_type or not self.owner_marker:
            raise LedgerError("fixture id, resource type, and owner marker are required")
        if self.fixture_id in self.dependencies:
            raise LedgerError(f"fixture {self.fixture_id} cannot depend on itself")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "resource_type": self.resource_type,
            "owner_marker": self.owner_marker,
            "dependencies": list(self.dependencies),
            "state": self.state.value,
            "metadata": sanitize_artifact(dict(self.metadata)),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FixtureRecord":
        return cls(
            fixture_id=value["fixture_id"], resource_type=value["resource_type"],
            owner_marker=value["owner_marker"], dependencies=tuple(value.get("dependencies", [])),
            state=FixtureState(value.get("state", FixtureState.DECLARED.value)),
            metadata=sanitize_artifact(value.get("metadata", {})), created_at=value.get("created_at", utc_now()),
        )


@dataclass(frozen=True)
class CleanupAction:
    fixture_id: str
    resource_type: str
    owner_marker: str
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class CleanupPlan:
    run_id: str
    marker: str
    actions: tuple[CleanupAction, ...]


@dataclass(frozen=True)
class MarkerScanPlan:
    """A request for a later read-only lane; this object does not perform a scan."""

    run_id: str
    marker: str
    resource_types: tuple[str, ...]
    include_cleaned: bool = False


@dataclass(frozen=True)
class LaneRequest:
    """Transport-neutral input a future browser/API lane may accept."""

    run_id: str
    marker: str
    cleanup: CleanupPlan
    marker_scan: MarkerScanPlan


class CommercialFixtureLane(Protocol):
    """Future lanes may implement this protocol; no live implementation is provided."""

    def execute(self, request: LaneRequest) -> Mapping[str, Any]:
        """Execute a supplied request and return sanitized evidence."""


@dataclass
class FixtureLedger:
    run_id: str
    marker: str
    baseline: BaselineSnapshot
    fixtures: dict[str, FixtureRecord] = field(default_factory=dict)
    owner: str = LEDGER_OWNER
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def create(cls, baseline: BaselineSnapshot, prefix: str = "commercial") -> "FixtureLedger":
        run_id = create_run_id(prefix)
        return cls(run_id=run_id, marker=f"e2e-{run_id}", baseline=baseline)

    def add_fixture(self, fixture: FixtureRecord) -> None:
        if fixture.owner_marker != self.marker:
            raise LedgerError("fixture owner marker does not belong to this ledger")
        if fixture.fixture_id in self.fixtures:
            raise LedgerError(f"duplicate fixture id: {fixture.fixture_id}")
        self.fixtures[fixture.fixture_id] = replace(fixture, metadata=sanitize_artifact(fixture.metadata))

    def transition(self, fixture_id: str, target: FixtureState) -> FixtureRecord:
        try:
            current = self.fixtures[fixture_id]
        except KeyError as error:
            raise LedgerError(f"unknown fixture: {fixture_id}") from error
        if target not in _ALLOWED_TRANSITIONS[current.state]:
            raise LedgerError(f"invalid transition: {current.state.value} -> {target.value}")
        if target is FixtureState.CLEANED:
            uncleaned_dependents = sorted(
                item.fixture_id
                for item in self.fixtures.values()
                if fixture_id in item.dependencies and item.state is not FixtureState.CLEANED
            )
            if uncleaned_dependents:
                raise LedgerError(
                    f"fixture {fixture_id} cannot be cleaned before dependents: {uncleaned_dependents}"
                )
        updated = replace(current, state=target)
        self.fixtures[fixture_id] = updated
        return updated

    def validate_graph(self) -> None:
        """Require local ownership and an acyclic dependency graph before cleanup."""
        for fixture in self.fixtures.values():
            if fixture.owner_marker != self.marker:
                raise LedgerError(f"fixture {fixture.fixture_id} is not owned by this ledger")
            unknown = set(fixture.dependencies) - set(self.fixtures)
            if unknown:
                raise LedgerError(f"fixture {fixture.fixture_id} has unknown dependencies: {sorted(unknown)}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(fixture_id: str) -> None:
            if fixture_id in visiting:
                raise LedgerError(f"dependency cycle includes {fixture_id}")
            if fixture_id in visited:
                return
            visiting.add(fixture_id)
            for dependency in self.fixtures[fixture_id].dependencies:
                visit(dependency)
            visiting.remove(fixture_id)
            visited.add(fixture_id)

        for fixture_id in sorted(self.fixtures):
            visit(fixture_id)

    def plan_cleanup(self) -> CleanupPlan:
        """Transition pending fixtures and order deletion before their dependencies."""
        self.validate_graph()
        pending = {key for key, item in self.fixtures.items() if item.state != FixtureState.CLEANED}
        for fixture_id in sorted(pending):
            state = self.fixtures[fixture_id].state
            if state in (FixtureState.DECLARED, FixtureState.MATERIALIZED, FixtureState.CLEANUP_FAILED):
                self.transition(fixture_id, FixtureState.CLEANUP_PLANNED)
        dependency_first: list[str] = []
        visited: set[str] = set()

        def visit_dependency_first(fixture_id: str) -> None:
            if fixture_id in visited or fixture_id not in pending:
                return
            visited.add(fixture_id)
            for dependency in sorted(self.fixtures[fixture_id].dependencies):
                visit_dependency_first(dependency)
            dependency_first.append(fixture_id)

        for fixture_id in sorted(pending):
            visit_dependency_first(fixture_id)
        # Reverse ordinary dependency order: a dependent must be removed before
        # the resource it references during cleanup.
        ordered = list(reversed(dependency_first))
        return CleanupPlan(self.run_id, self.marker, tuple(
            CleanupAction(item, self.fixtures[item].resource_type, self.marker, self.fixtures[item].dependencies)
            for item in ordered
        ))

    def plan_marker_scan(self, resource_types: Sequence[str], include_cleaned: bool = False) -> MarkerScanPlan:
        types = tuple(resource_types)
        if not types or any(not item for item in types):
            raise LedgerError("marker scan needs at least one resource type")
        return MarkerScanPlan(self.run_id, self.marker, types, include_cleaned)

    def lane_request(self, resource_types: Sequence[str]) -> LaneRequest:
        return LaneRequest(self.run_id, self.marker, self.plan_cleanup(), self.plan_marker_scan(resource_types))

    def to_dict(self) -> dict[str, Any]:
        self.validate_graph()
        return sanitize_artifact({
            "schema_version": SCHEMA_VERSION, "owner": self.owner, "run_id": self.run_id,
            "marker": self.marker, "created_at": self.created_at, "baseline": self.baseline.to_dict(),
            "fixtures": [self.fixtures[key].to_dict() for key in sorted(self.fixtures)],
        })

    def persist(self, directory: Path | str, artifact_name: str | None = None) -> Path:
        """Atomically persist a sanitized local JSON ledger with owner-only permissions."""
        target_directory = Path(directory)
        target_directory.mkdir(parents=True, exist_ok=True)
        target = target_directory / safe_artifact_name(artifact_name or f"fixture-ledger-{self.run_id}")
        if target.parent.resolve() != target_directory.resolve():
            raise LedgerError("artifact path escaped its directory")
        descriptor, temporary = tempfile.mkstemp(prefix=".fixture-ledger-", suffix=".tmp", dir=target_directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(self.to_dict(), output, ensure_ascii=False, indent=2, sort_keys=True)
                output.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    @classmethod
    def load(cls, path: Path | str) -> "FixtureLedger":
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA_VERSION:
            raise LedgerError("unsupported fixture ledger schema")
        ledger = cls(value["run_id"], value["marker"], BaselineSnapshot.from_dict(value["baseline"]), owner=value.get("owner", ""), created_at=value["created_at"])
        if ledger.owner != LEDGER_OWNER:
            raise LedgerError("unrecognized fixture ledger owner")
        for fixture_data in value.get("fixtures", []):
            ledger.add_fixture(FixtureRecord.from_dict(fixture_data))
        ledger.validate_graph()
        return ledger
