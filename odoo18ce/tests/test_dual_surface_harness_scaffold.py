#!/usr/bin/env python3
"""Credential-free state contracts for the Discuss/Calendar/Files/PDF dual-surface harness.

This module intentionally models evidence and acceptance states only.  It does not
read environment variables, start a browser, contact Odoo, or mutate services.
Run its pure self-tests with ``python3 odoo18ce/tests/test_dual_surface_harness_scaffold.py``.
"""
from __future__ import annotations

import hashlib
import re
import unittest
from dataclasses import dataclass
from typing import Iterable, Tuple
from urllib.parse import quote, unquote, urlencode, urlsplit


class ContractError(ValueError):
    """Raised when recorded harness evidence is outside the agreed contract."""


INGRESS_PREFIX = re.compile(r"^/api/hassio_ingress/[A-Za-z0-9_-]{16,128}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def normalize_odoo_route(route: str) -> str:
    """Return one canonical, local Odoo route without changing external state."""
    _require(isinstance(route, str) and route, "route must be a non-empty string")
    parsed = urlsplit(route)
    _require(not parsed.scheme and not parsed.netloc, "route must be local, not an absolute URL")
    _require(not parsed.fragment, "route fragments are not valid harness targets")
    path = unquote(parsed.path)
    _require("\\" not in path and not any(ord(char) < 32 for char in path), "route has unsafe characters")
    parts = []
    for part in path.split("/"):
        if not part or part == ".":
            continue
        _require(part != "..", "route traversal is not allowed")
        parts.append(part)
    _require(parts and parts[0] == "odoo", "route must remain below /odoo")
    canonical_path = "/" + "/".join(quote(part, safe="@:+,;=-._~") for part in parts)
    # Parsing and re-encoding makes query evidence deterministic and rejects no input.
    query = urlencode(sorted((key, value) for key, value in _query_pairs(parsed.query)))
    return canonical_path + ("?" + query if query else "")


def _query_pairs(query: str) -> Iterable[Tuple[str, str]]:
    """Parse a query without silently accepting malformed percent escapes."""
    if not query:
        return ()
    pairs = []
    for item in query.split("&"):
        _require(item, "empty query fields are not allowed")
        key, separator, value = item.partition("=")
        _require(separator and key, "query fields must use key=value")
        decoded_key, decoded_value = unquote(key), unquote(value)
        _require(
            not any(ord(char) < 32 for char in decoded_key + decoded_value),
            "query has unsafe characters",
        )
        pairs.append((decoded_key, decoded_value))
    return tuple(pairs)


def ingress_route(prefix: str, route: str) -> str:
    """Join a validated HA ingress prefix to a sanitized Odoo-only route."""
    _require(bool(INGRESS_PREFIX.fullmatch(prefix)), "invalid HA ingress prefix")
    return prefix + normalize_odoo_route(route)


@dataclass(frozen=True)
class HarnessPolicy:
    """Explicitly records that this scaffold is evidence-only and non-mutating."""

    credential_free: bool = True
    browser_calls_allowed: bool = False
    odoo_calls_allowed: bool = False
    service_or_config_changes_allowed: bool = False
    mutate_records_allowed: bool = False

    def validate(self) -> None:
        _require(self.credential_free, "credentials are forbidden")
        _require(not self.browser_calls_allowed, "browser calls are forbidden")
        _require(not self.odoo_calls_allowed, "Odoo calls are forbidden")
        _require(not self.service_or_config_changes_allowed, "service/config changes are forbidden")
        _require(not self.mutate_records_allowed, "record mutation is forbidden")


@dataclass(frozen=True)
class SurfaceTimingEvidence:
    surface: str
    route: str
    window_opened_at: float
    bundle_observed_at: float
    websocket_observed_at: float
    ready_at: float

    def validate(self) -> None:
        _require(self.surface in ("A", "B"), "surface must be A or B")
        _require(normalize_odoo_route(self.route) == "/odoo/discuss", "Discuss must target /odoo/discuss")
        _require(self.window_opened_at <= self.bundle_observed_at, "bundle predates its window")
        _require(self.window_opened_at <= self.websocket_observed_at, "websocket predates its window")
        _require(self.ready_at >= max(self.bundle_observed_at, self.websocket_observed_at), "ready predates evidence")


@dataclass(frozen=True)
class DiscussDualSurfaceScenario:
    """Two independently identified Discuss windows plus bundle/websocket timing."""

    windows: Tuple[str, str]
    evidence: Tuple[SurfaceTimingEvidence, SurfaceTimingEvidence]

    def validate(self) -> None:
        _require(len(self.windows) == 2 and len(set(self.windows)) == 2, "Discuss windows must be distinct")
        _require({item.surface for item in self.evidence} == {"A", "B"}, "A and B evidence is required")
        for item in self.evidence:
            item.validate()
        # Both windows must have been open before either surface is declared ready.
        opened = {item.surface: item.window_opened_at for item in self.evidence}
        ready = {item.surface: item.ready_at for item in self.evidence}
        _require(max(opened.values()) <= min(ready.values()), "Discuss surfaces were not simultaneous")


@dataclass(frozen=True)
class CalendarRecurrenceFlow:
    """A state model that prevents occurrence and recurring-series actions mixing."""

    series_id: str
    occurrence_id: str
    actions: Tuple[str, ...]

    def validate(self) -> None:
        _require(bool(self.series_id) and bool(self.occurrence_id), "Calendar identifiers are required")
        _require(self.series_id != self.occurrence_id, "occurrence and series must differ")
        _require(
            self.actions == ("open-occurrence", "update-occurrence", "open-series", "update-series"),
            "Calendar flow must separately update occurrence then series",
        )


@dataclass(frozen=True)
class FileIntegrityExpectation:
    filename: str
    sha256: str
    content: bytes

    def validate(self) -> None:
        _require(bool(self.filename), "filename is required")
        _require(bool(SHA256.fullmatch(self.sha256)), "SHA-256 must be lowercase hexadecimal")
        _require(hashlib.sha256(self.content).hexdigest() == self.sha256, "file SHA-256 mismatch")


@dataclass(frozen=True)
class PdfResponseExpectation:
    status: int
    content_type: str
    body: bytes
    required_marker: bytes

    def validate(self) -> None:
        _require(self.status == 200, "PDF status must be 200")
        _require(self.content_type.lower().split(";", 1)[0].strip() == "application/pdf", "PDF content type mismatch")
        _require(bool(self.body), "PDF body must be nonzero")
        _require(self.body.startswith(b"%PDF"), "PDF signature is missing")
        _require(bool(self.required_marker) and self.required_marker in self.body, "PDF marker is missing")


@dataclass(frozen=True)
class WorkerExclusiveWindowPlan:
    """A non-executing workers=2 window that restores the captured baseline."""

    original_global_workers: int = 0
    active_global_workers: int = 2
    restore_global_workers: int = 0
    exclusive_window: bool = False
    restore_plan: str = "restore the captured global worker count after evidence collection"

    def validate(self) -> None:
        _require(self.original_global_workers >= 0, "original global workers must be non-negative")
        _require(self.active_global_workers == 2, "global workers=2 is required during the exclusive window")
        _require(self.exclusive_window, "an exclusive window is required")
        _require(
            self.restore_global_workers == self.original_global_workers,
            "restore plan must restore the captured original worker count",
        )
        _require(bool(self.restore_plan), "restore plan is required")


@dataclass(frozen=True)
class DualSurfaceHarnessState:
    """Complete, immutable acceptance state for a future live runner."""

    policy: HarnessPolicy
    workers: WorkerExclusiveWindowPlan
    discuss: DiscussDualSurfaceScenario
    calendar: CalendarRecurrenceFlow
    file: FileIntegrityExpectation
    pdf: PdfResponseExpectation

    def validate(self) -> None:
        self.policy.validate()
        self.workers.validate()
        self.discuss.validate()
        self.calendar.validate()
        self.file.validate()
        self.pdf.validate()


def sample_state() -> DualSurfaceHarnessState:
    """Provide harmless in-memory evidence used exclusively by the self-tests."""
    file_content = b"dual-surface fixture\n"
    return DualSurfaceHarnessState(
        policy=HarnessPolicy(),
        workers=WorkerExclusiveWindowPlan(
            original_global_workers=0,
            active_global_workers=2,
            restore_global_workers=0,
            exclusive_window=True,
        ),
        discuss=DiscussDualSurfaceScenario(
            windows=("discuss-window-a", "discuss-window-b"),
            evidence=(
                SurfaceTimingEvidence("A", "/odoo/discuss", 1.0, 2.0, 2.5, 3.0),
                SurfaceTimingEvidence("B", "/odoo//discuss", 1.5, 2.1, 2.6, 3.1),
            ),
        ),
        calendar=CalendarRecurrenceFlow(
            "series-1", "occurrence-2026-08-17", ("open-occurrence", "update-occurrence", "open-series", "update-series")
        ),
        file=FileIntegrityExpectation("fixture.txt", hashlib.sha256(file_content).hexdigest(), file_content),
        pdf=PdfResponseExpectation(200, "application/pdf; charset=binary", b"%PDF-1.4\nmarker: harness\n", b"marker: harness"),
    )


class DualSurfaceHarnessSelfTest(unittest.TestCase):
    def test_complete_credential_free_state_validates(self) -> None:
        state = sample_state()
        state.validate()
        self.assertEqual(ingress_route("/api/hassio_ingress/abcdefghijklmnop", "/odoo//discuss?b=2&a=1"), "/api/hassio_ingress/abcdefghijklmnop/odoo/discuss?a=1&b=2")

    def test_route_sanitization_rejects_escape_and_external_urls(self) -> None:
        for route in ("/odoo/%2e%2e/web", "/odoo\\discuss", "https://example.invalid/odoo/discuss", "/web"):
            with self.assertRaises(ContractError):
                normalize_odoo_route(route)
        with self.assertRaises(ContractError):
            ingress_route("/api/hassio_ingress/short", "/odoo/discuss")

    def test_models_reject_the_required_failure_modes(self) -> None:
        with self.assertRaises(ContractError):
            WorkerExclusiveWindowPlan(
                original_global_workers=0,
                active_global_workers=2,
                restore_global_workers=2,
                exclusive_window=True,
            ).validate()
        with self.assertRaises(ContractError):
            WorkerExclusiveWindowPlan(
                original_global_workers=0,
                active_global_workers=1,
                restore_global_workers=0,
                exclusive_window=True,
            ).validate()
        with self.assertRaises(ContractError):
            CalendarRecurrenceFlow("series", "series", ("open-occurrence",)).validate()
        with self.assertRaises(ContractError):
            FileIntegrityExpectation("fixture", "0" * 64, b"different").validate()
        with self.assertRaises(ContractError):
            PdfResponseExpectation(200, "application/pdf", b"not a PDF", b"marker").validate()
        with self.assertRaises(ContractError):
            HarnessPolicy(browser_calls_allowed=True).validate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
