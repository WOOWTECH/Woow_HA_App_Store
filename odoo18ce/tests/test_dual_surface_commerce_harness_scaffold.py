#!/usr/bin/env python3
"""Pure contracts for the credential-free Website/Shop/Portal harness.

This module deliberately models scenarios only.  It has no Playwright, HTTP,
credential, fixture-ledger, or mutation dependency; a future runner may adapt
its safe fixtures through :class:`FixtureAvailability`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Mapping, Protocol
from urllib.parse import urlsplit


class Surface(str, Enum):
    """The two URLs that must expose the same Odoo route semantics."""

    PUBLIC = "public"
    HA_INGRESS = "ha_ingress"


class Phase(str, Enum):
    WEBSITE_EDITOR = "website_editor"
    SHOP_CART = "shop_cart"
    CHECKOUT = "checkout"
    PAYMENT = "payment"
    PORTAL_ORDER = "portal_order"
    PORTAL_AUTHORIZATION = "portal_authorization"


class EvidenceKind(str, Enum):
    NETWORK = "network"
    CONSOLE = "console"
    ROUTE = "route"
    SCREENSHOT = "screenshot"
    SEMANTIC = "semantic"


_REQUIRED_EVIDENCE = frozenset(EvidenceKind)
_INGRESS_PREFIX = re.compile(r"^/api/hassio_ingress/[A-Za-z0-9_-]{16,128}$")
_SENSITIVE_FIXTURE_WORDS = ("credential", "password", "secret", "token")


@dataclass(frozen=True)
class FixtureRequirement:
    """A declarative, non-secret prerequisite for a future test runner."""

    name: str
    test_only: bool = False

    def __post_init__(self) -> None:
        if not self.name.startswith("fixture:"):
            raise ValueError("fixture requirements must use the fixture: namespace")
        if any(word in self.name.lower() for word in _SENSITIVE_FIXTURE_WORDS):
            raise ValueError("fixture requirements must never name credentials or secrets")


class FixtureAvailability(Protocol):
    """Narrow adapter replacing any fixture ledger dependency.

    The harness can only ask whether a named, safe fixture is available.  It
    cannot provision, mutate, read credentials from, or otherwise control it.
    """

    def is_available(self, requirement: FixtureRequirement) -> bool:
        """Return availability without creating or changing the fixture."""


@dataclass(frozen=True)
class NormalizedRoute:
    surface: Surface
    path: str
    fragment: str = ""


def normalize_surface_route(
    surface: Surface, observed_url: str, *, ingress_prefix: str | None = None
) -> NormalizedRoute:
    """Reduce a public or HA ingress URL to the common Odoo route.

    Query data is intentionally excluded: it can contain transient state and
    must not become evidence.  HA normalization requires a validated ingress
    prefix and removes it exactly once; public routes may never carry one.
    """
    parsed = urlsplit(observed_url)
    path = parsed.path or "/"
    if not path.startswith("/"):
        raise ValueError("route path must be absolute")
    if surface is Surface.HA_INGRESS:
        if not ingress_prefix or not _INGRESS_PREFIX.fullmatch(ingress_prefix):
            raise ValueError("HA ingress normalization requires a validated prefix")
        if path == ingress_prefix:
            path = "/"
        elif path.startswith(ingress_prefix + "/"):
            path = path[len(ingress_prefix) :]
        else:
            raise ValueError("HA route does not start with the declared ingress prefix")
    elif path.startswith("/api/hassio_ingress/"):
        raise ValueError("public route must not contain an HA ingress prefix")
    return NormalizedRoute(surface=surface, path=path, fragment=parsed.fragment)


@dataclass(frozen=True)
class RouteExpectation:
    """A canonical path template evaluated after surface normalization."""

    canonical_path: str

    def __post_init__(self) -> None:
        if not self.canonical_path.startswith("/"):
            raise ValueError("canonical route must be absolute")

    def matches(
        self, surface: Surface, observed_url: str, *, ingress_prefix: str | None = None
    ) -> bool:
        normalized = normalize_surface_route(
            surface, observed_url, ingress_prefix=ingress_prefix
        )
        pattern = re.escape(self.canonical_path).replace(
            r"\{order_id\}", r"[^/?#]+"
        )
        return re.fullmatch(pattern, normalized.path) is not None


@dataclass(frozen=True)
class EvidenceAssertion:
    kind: EvidenceKind
    assertion: str

    def __post_init__(self) -> None:
        if not self.assertion.strip():
            raise ValueError("evidence assertions require semantic text")


@dataclass(frozen=True)
class EvidenceSchema:
    """Required semantic evidence categories for every modeled operation."""

    assertions: tuple[EvidenceAssertion, ...]

    def __post_init__(self) -> None:
        kinds = {assertion.kind for assertion in self.assertions}
        missing = _REQUIRED_EVIDENCE - kinds
        if missing:
            raise ValueError("missing evidence kinds: " + ", ".join(sorted(x.value for x in missing)))


STANDARD_EVIDENCE = EvidenceSchema(
    assertions=(
        EvidenceAssertion(EvidenceKind.NETWORK, "no request failure or HTTP 5xx"),
        EvidenceAssertion(EvidenceKind.CONSOLE, "no unignored console error"),
        EvidenceAssertion(EvidenceKind.ROUTE, "normalized route matches the operation expectation"),
        EvidenceAssertion(EvidenceKind.SCREENSHOT, "captured image shows the named surface state"),
        EvidenceAssertion(EvidenceKind.SEMANTIC, "named Odoo state is visible without inferring success from URL alone"),
    )
)


@dataclass(frozen=True)
class ScenarioStep:
    phase: Phase
    operation: str
    route: RouteExpectation
    fixtures: tuple[FixtureRequirement, ...] = ()
    evidence: EvidenceSchema = STANDARD_EVIDENCE


@dataclass(frozen=True)
class ScenarioModel:
    """Surface-independent semantic steps a future runner may observe."""

    name: str
    surfaces: tuple[Surface, ...]
    steps: tuple[ScenarioStep, ...]

    def __post_init__(self) -> None:
        if set(self.surfaces) != {Surface.PUBLIC, Surface.HA_INGRESS}:
            raise ValueError("the model must cover exactly public and HA ingress surfaces")
        if len({step.phase for step in self.steps}) != len(self.steps):
            raise ValueError("the model must define each phase only once")

    def step_for(self, phase: Phase) -> ScenarioStep:
        return next(step for step in self.steps if step.phase is phase)


TEST_PAYMENT_PROVIDER = FixtureRequirement("fixture:test-payment-provider", test_only=True)
SCENARIO_STEPS = (
    ScenarioStep(Phase.WEBSITE_EDITOR, "editor-ready", RouteExpectation("/website"), (FixtureRequirement("fixture:website-editor-enabled"),)),
    ScenarioStep(Phase.SHOP_CART, "cart-ready", RouteExpectation("/shop/cart"), (FixtureRequirement("fixture:published-product"),)),
    ScenarioStep(Phase.CHECKOUT, "checkout-ready", RouteExpectation("/shop/checkout")),
    ScenarioStep(Phase.PAYMENT, "test-payment-ready", RouteExpectation("/shop/payment"), (TEST_PAYMENT_PROVIDER,)),
    ScenarioStep(Phase.PORTAL_ORDER, "order-visible", RouteExpectation("/my/orders/{order_id}"), (FixtureRequirement("fixture:portal-order"),)),
    ScenarioStep(Phase.PORTAL_AUTHORIZATION, "authorization-visible", RouteExpectation("/my/orders/{order_id}"), (FixtureRequirement("fixture:portal-authorized-customer"),)),
)
DUAL_SURFACE_COMMERCE_SCENARIO = ScenarioModel(
    name="credential-free-website-shop-portal",
    surfaces=(Surface.PUBLIC, Surface.HA_INGRESS),
    steps=SCENARIO_STEPS,
)

PHASE_DEPENDENCIES: Mapping[Phase, frozenset[Phase]] = {
    Phase.WEBSITE_EDITOR: frozenset(),
    Phase.SHOP_CART: frozenset(),
    Phase.CHECKOUT: frozenset({Phase.SHOP_CART}),
    Phase.PAYMENT: frozenset({Phase.CHECKOUT}),
    # Keep Cart/Checkout -> Portal explicit even if a runner also records payment.
    Phase.PORTAL_ORDER: frozenset({Phase.SHOP_CART, Phase.CHECKOUT, Phase.PAYMENT}),
    Phase.PORTAL_AUTHORIZATION: frozenset({Phase.PORTAL_ORDER}),
}


@dataclass(frozen=True)
class ScenarioState:
    """Immutable phase state machine; completing a phase never runs an action."""

    completed: frozenset[Phase] = field(default_factory=frozenset)

    def complete(self, phase: Phase, fixtures: FixtureAvailability) -> "ScenarioState":
        missing_phases = PHASE_DEPENDENCIES[phase] - self.completed
        if missing_phases:
            raise ValueError("unmet phase dependencies: " + ", ".join(sorted(item.value for item in missing_phases)))
        step = DUAL_SURFACE_COMMERCE_SCENARIO.step_for(phase)
        unavailable = [item.name for item in step.fixtures if not fixtures.is_available(item)]
        if unavailable:
            raise ValueError("unavailable safe fixtures: " + ", ".join(unavailable))
        return ScenarioState(self.completed | {phase})


class _AvailableFixtures:
    """Self-test-only adapter; this is not a fixture ledger or live provider."""

    def __init__(self, names: set[str]) -> None:
        self.names = names

    def is_available(self, requirement: FixtureRequirement) -> bool:
        return requirement.name in self.names


def _assert_raises(message: str, callback: object) -> None:
    try:
        callback()  # type: ignore[operator]
    except ValueError as error:
        assert message in str(error), error
    else:
        raise AssertionError(f"expected ValueError containing {message!r}")


def self_test() -> None:
    """Exercise only pure model contracts; no credentials, browser, or I/O."""
    ingress = "/api/hassio_ingress/1234567890abcdef"
    assert normalize_surface_route(Surface.PUBLIC, "https://odoo.example/shop/cart?state=opaque").path == "/shop/cart"
    assert normalize_surface_route(Surface.HA_INGRESS, ingress + "/shop/cart", ingress_prefix=ingress).path == "/shop/cart"
    _assert_raises("validated prefix", lambda: normalize_surface_route(Surface.HA_INGRESS, "/shop/cart"))
    _assert_raises("public route", lambda: normalize_surface_route(Surface.PUBLIC, ingress + "/shop/cart"))
    assert DUAL_SURFACE_COMMERCE_SCENARIO.surfaces == (Surface.PUBLIC, Surface.HA_INGRESS)
    assert {Phase.SHOP_CART, Phase.CHECKOUT} <= PHASE_DEPENDENCIES[Phase.PORTAL_ORDER]
    portal_route = RouteExpectation("/my/orders/{order_id}")
    assert portal_route.matches(Surface.PUBLIC, "/my/orders/S00042")
    assert portal_route.matches(Surface.HA_INGRESS, ingress + "/my/orders/S00042", ingress_prefix=ingress)
    assert not portal_route.matches(Surface.PUBLIC, "/my/orders/S00042/lines")
    _assert_raises("missing evidence kinds", lambda: EvidenceSchema((EvidenceAssertion(EvidenceKind.NETWORK, "no 5xx"),)))
    _assert_raises("credentials or secrets", lambda: FixtureRequirement("fixture:password"))

    all_fixtures = _AvailableFixtures({requirement.name for step in SCENARIO_STEPS for requirement in step.fixtures})
    state = ScenarioState()
    _assert_raises("shop_cart", lambda: state.complete(Phase.CHECKOUT, all_fixtures))
    state = state.complete(Phase.SHOP_CART, all_fixtures)
    state = state.complete(Phase.CHECKOUT, all_fixtures)
    _assert_raises("test-payment-provider", lambda: state.complete(Phase.PAYMENT, _AvailableFixtures(set())))
    state = state.complete(Phase.PAYMENT, all_fixtures)
    state = state.complete(Phase.PORTAL_ORDER, all_fixtures)
    assert Phase.PORTAL_ORDER in state.completed
    assert Phase.PORTAL_AUTHORIZATION in state.complete(Phase.PORTAL_AUTHORIZATION, all_fixtures).completed


if __name__ == "__main__":
    self_test()
    print("dual-surface commerce harness scaffold self-test passed")
