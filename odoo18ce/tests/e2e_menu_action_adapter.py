#!/usr/bin/env python3
"""Runtime adapter for the read-only menu/action crawler, and its two-surface diff.

`crawl` opens every menu action of the chosen apps on one surface, up to
`MAX_TRAVERSAL_DEPTH`, and writes one `odoo-parity-evidence/v1` JSONL record
per action: the five signals of the parity plan section 7 step 5 and every URL
literal on the screen (`U-C5`). `open` writes the same record for screens
`crawl` cannot reach -- a module with no menu of its own, or one whose only
menu runs a server action -- named one by one in a target file. `diff` joins a
Public origin run and an Ingress run by control identity and gives each
`PARITY` or `GAP`; it judges an `open` run exactly as it judges a crawl.

The adapter only reads, with one named exception. It fetches the menu tree
with one GET, counts the rows of two models with one read-only RPC each
(`count_rows`, the ambient accounting below) and then navigates to each
action's route; it never clicks, types into Odoo records or calls an RPC that
writes, and a menu whose action could write (a server action) is listed as
skipped, never planned. The exception is an `open`
target that asks for a cart: reaching the website checkout needs one, so
`SurfaceDriver.ensure_cart` adds a product to the logged-in user's cart when it
is empty, and the record names the `sale.order` that made. That write is
outside the crawler's `OperationPolicy` on purpose -- see `ensure_cart` -- and
`require_write_database`
keeps it on the one database ADR 0012 allows it on.

Navigating writes too where Odoo writes on a plain GET: the checkout routes
edit the draft order while rendering it. `GET_WRITING_ROUTES` names those
routes and `require_write_database` holds them to the same database, so a
target reaches one only on a run allowed to write -- whether or not it declared
a cart. The record names that write as well: after such a navigation the run
reads the session's draft order and puts it in the record's `writes`, on both
surfaces, so `diff` judges a difference in what the GET wrote the way it judges
one in what a cart step added.

Being allowed to write is not enough to be judged, so a targets file may name
such a route only when its write **converges**: a second visit re-derives the
same state and renders the same screen -- a recompute or a re-store, never an
accumulation and never a consumption. That is what makes the two surfaces see
one screen whichever of them goes first, which is why the rule is
order-independent, and `ensure_cart` leaving a non-empty cart alone is the
existing example of it. A target naming a route that consumes the fixture
(`/shop/payment/validate`), or one nobody has read against the rule, is a
configuration error on **every** database -- `require_convergent_writes` refuses
it before a browser launches. `GET_WRITING_ROUTES` carries the rule, the class
of every route and the reason for each.

Every run also accounts for the rows it leaves that no targets file can bound.
Serving a tracked page writes a `website.visitor` and a `website.track` row and
the page's own JavaScript writes too, so a read-only run makes no business
writes but never leaves zero rows -- ADR 0012's postscript 2026-10-01 (#227)
says which writes and where they were read. `crawl` and `open` count both
models after the login and again after the last navigation, and write the delta
beside the evidence under the same name with `.ambient.json` for its extension
(`ingress-open.jsonl` -> `ingress-open.ambient.json`): counts only, no URL and
no visitor identity. It is accounting and not a verdict -- `diff` never reads that file,
`read_records` refuses its schema, and the parity plan's conservation tally does
not move for it -- which is why it sits beside the records rather than in them.
A `crawl`'s figure is the interesting zero: it navigates `/odoo/action-<id>`,
which renders no tracked page, so the claim that a crawl leaves nothing is now
measured per run rather than asserted.

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
import posixpath
import re
import sys
import time
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, NamedTuple, Sequence
from urllib.parse import unquote, urlsplit

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
# The one database an `open` target may write on. ADR 0012 allows the test
# host's databases, `odoo_test` included; #163 is narrower on purpose -- the
# Public origin serves `odoo_parity`, so that is the one both surfaces judge.
WRITE_DATABASE = "odoo_parity"


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


# --- Open targets ---------------------------------------------------------


_XMLID = re.compile(r"[a-z0-9_]+\.[A-Za-z0-9_][A-Za-z0-9_.]*")
# The only query a target may carry. Odoo's view chooser is the reason a target
# has a query at all, and everything else is refused: a query is opened as
# written (`?db=` would move the session off the database the run authorised),
# and it is kept in the identity, which the record holds in the clear.
_TARGET_QUERY = re.compile(r"view_type=[a-z_]+")
_OPEN_FIELDS = ("module", "target", "label", "expect_model", "expect_selector", "cart")


@dataclass(frozen=True)
class OpenTarget:
    """One screen `open` judges: a window action or a route, and what it owns.

    `target` is a window-action xmlid (`project_todo.project_task_action_todo`)
    or a route relative to the surface's Odoo root (`/shop/checkout`). It names
    the same screen on both surfaces -- no origin, no Ingress prefix -- so it is
    also the control identity `diff` joins the two runs on.

    `expect_model` (a back-office screen) and `expect_selector` (a website one)
    are the `open` form of the crawler's U-C12 check: without them a fallback
    screen that loads cleanly on both surfaces would read as `PARITY`.
    `cart` names a product page to add to the cart before opening the target;
    it is the only field that writes. The `target` itself can write as well,
    when it names a route Odoo writes on while rendering a GET -- see
    `GET_WRITING_ROUTES`, which also says which of those routes a target may
    name at all: only one whose write converges, so that both surfaces judge the
    same screen whichever opens it first.
    """

    module: str
    target: str
    label: str = ""
    expect_model: str | None = None
    expect_selector: str | None = None
    cart: str | None = None

    @property
    def is_action(self) -> bool:
        return not self.target.startswith("/")

    @property
    def route(self) -> str:
        return "/odoo/action-%s" % self.target if self.is_action else self.target

    @property
    def identity(self) -> str:
        # A query chooses the view (`?view_type=list`), so it tells two targets
        # apart and belongs in the identity -- but masking redacts everything
        # after a `?`, because a query can carry credentials. Keep it after a
        # `;`, so the masked record still holds an identity `diff` can join on.
        return "open:%s:%s" % ("action" if self.is_action else "route", self.target.replace("?", ";"))

    @property
    def backend(self) -> bool:
        """A web-client screen, as opposed to a website page: it has an action manager."""
        return self.is_action or urlsplit(self.route).path.split("/")[1:2] == ["odoo"]


def _check_route(route: Any, what: str, *, query: bool = True) -> None:
    if not isinstance(route, str) or not route.startswith("/"):
        raise ValueError("crawler configuration: %s must be a route or an action xmlid" % what)
    try:
        # Refuses an origin, credentials, traversal and an Ingress prefix. The
        # query is dropped here but kept by the target, which is opened as
        # written, so it is checked separately.
        normalize_route(route, Surface.PUBLIC)
    except ValueError as error:
        raise ValueError("crawler configuration: %s is not a usable route (%s)" % (what, error)) from None
    if urlsplit(route).fragment:
        raise ValueError("crawler configuration: %s may not carry a fragment; Odoo routes its screens by "
                         "path, and a fragment would ride into the identity as written" % what)
    found = urlsplit(route).query
    if found and not (query and _TARGET_QUERY.fullmatch(found)):
        rule = ("a target's query can only choose a view (view_type=...)" if query
                else "a cart route may carry no query at all")
        raise ValueError("crawler configuration: %s may not carry the query %r; %s" % (what, found, rule))


def parse_targets(lines: Iterable[str]) -> tuple[OpenTarget, ...]:
    """Read a target file: one JSON object per line, blank lines and `#` skipped."""
    targets: list[OpenTarget] = []
    seen: dict[str, int] = {}
    for number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            entry = json.loads(text)
        except ValueError as error:
            raise ValueError("crawler configuration: target line %d is not JSON (%s)" % (number, error)) from None
        if not isinstance(entry, dict):
            raise ValueError("crawler configuration: target line %d is not an object" % number)
        unknown = sorted(set(entry) - set(_OPEN_FIELDS))
        if unknown:
            raise ValueError("crawler configuration: target line %d has unknown field(s): %s"
                             % (number, ", ".join(unknown)))
        for name, value in entry.items():
            if value is not None and not isinstance(value, str):
                raise ValueError("crawler configuration: target line %d: %s must be a string" % (number, name))
            # An empty string is a field that was meant to say something: as an
            # expectation it would fail every screen, and as a cart it would
            # ask for a write of nothing.
            if value == "":
                raise ValueError("crawler configuration: target line %d: %s is empty" % (number, name))
        if not entry.get("module") or not entry.get("target"):
            raise ValueError("crawler configuration: target line %d needs a module and a target" % number)
        if not entry.get("expect_model") and not entry.get("expect_selector"):
            # Without one of them nothing says the screen asked for is the
            # screen that loaded, and a fallback that renders cleanly on both
            # surfaces would be judged PARITY.
            raise ValueError("crawler configuration: target line %d needs an expect_model or an expect_selector"
                             % number)
        if ";" in entry["target"]:
            # `identity` writes a query after a `;`, so a `;` already in the
            # target would make two different targets share one identity.
            raise ValueError("crawler configuration: target line %d must not contain a ';'" % number)
        target = OpenTarget(**entry)
        if target.is_action:
            if not _XMLID.fullmatch(target.target):
                raise ValueError("crawler configuration: target line %d: %r is neither an xmlid nor a route"
                                 % (number, target.target))
        else:
            _check_route(target.target, "target line %d" % number)
        if target.expect_model and not target.backend:
            raise ValueError("crawler configuration: target line %d is a website route, which has no action "
                             "model; judge it with an expect_selector" % number)
        if target.cart is not None:
            _check_route(target.cart, "the cart of target line %d" % number, query=False)
        if target.identity in seen:
            raise ValueError("crawler configuration: target line %d repeats the target of line %d"
                             % (number, seen[target.identity]))
        seen[target.identity] = number
        targets.append(target)
    if not targets:
        raise ValueError("crawler configuration: the target file has no target")
    return tuple(targets)


def session_database(reported: str | None) -> str:
    """The database a run records and is judged on: the one the session reported.

    `ODOO_DB` is what the login asked for, which a mono-database deployment
    ignores, so a run that could not read the answer names no database at all
    rather than repeating the question.
    """
    if not reported:
        raise RuntimeError("crawler configuration: the session did not report its database")
    return reported


# How a GET write behaves when the same screen is opened twice. The guard
# branches on `CONVERGENT` alone; the other two names are what a refusal tells
# the operator it refused for. See the rule in the comment below.
CONVERGENT = "convergent"
FIXTURE_CONSUMING = "fixture-consuming"
UNCLASSIFIED = "unclassified"
GET_WRITE_CLASSES = (CONVERGENT, FIXTURE_CONSUMING, UNCLASSIFIED)
NOT_CONVERGENT_REASON = {
    FIXTURE_CONSUMING: "its write consumes the state the other surface has to judge",
    UNCLASSIFIED: "its write has not been read against the convergence rule, and an unread write is refused",
}


class GetWrite(NamedTuple):
    """One `GET_WRITING_ROUTES` entry: the write that was read, and its class."""

    write: str
    classification: str

    @property
    def converges(self) -> bool:
        """Whether a targets file may aim at this route at all -- the #225 rule."""
        return self.classification == CONVERGENT


# Routes that write while rendering a plain GET, and where that write was read.
#
# `open` navigates a target with `page.goto`, which is a GET and nothing more,
# so a route that writes on GET mutates the run's database whether or not the
# target declared a `cart:`. Both older guards key on that declaration --
# `ensure_cart` refuses the explicit write, `require_write_database` refuses a
# target file that asks for one -- so a target naming such a route sailed past
# both. The target list is the seam: the route is known before the first page
# is opened, and the enum cannot help (`NON_MUTATING_OPERATIONS` is every
# member of `Operation`, so nothing named there is ever refused).
#
# Being on this list bounds a route; it does not make the route aimable. #225
# decided that on 2026-09-30 and #228 recorded it here: a targets file may name a
# GET-writing route only when the route's write **converges** -- a second visit
# re-derives the same state and renders the same screen, a recompute or a
# re-store, never an accumulation and never a consumption. Convergence is what
# makes such a write cross-surface deterministic: each surface's render includes
# the effect of its own write, so both surfaces judge one screen. The rule is
# therefore **order-independent** -- no ordering of the two surfaces is fixed,
# and none may become load-bearing. The precedent is `ensure_cart`, which has
# obeyed the rule since it was written: a non-empty cart is left exactly as it
# is, precisely so both surfaces judge the same cart.
#
# Each entry carries its class beside its citation, and the guard
# (`require_convergent_writes`) reads nothing else:
#
#   CONVERGENT         Allowed, bounded to `WRITE_DATABASE` the way it always
#                      was. The eight #225 read -- `/shop/checkout`,
#                      `/shop/address`, `/shop/confirm_order`,
#                      `/shop/extra_info`, `/shop/payment`, `/shop/pricelist`,
#                      `/shop/change_pricelist` and `/website/lang`, each of
#                      which recomputes or re-stores the same values on a cart it
#                      leaves in place -- plus the two #228 audited and promoted,
#                      `/shop/cart` and `/my/orders/`.
#   FIXTURE_CONSUMING  Refused on **every** database, `WRITE_DATABASE` included,
#                      before the first screen opens. `/shop/payment/validate`
#                      alone: it confirms the draft order into a sale and
#                      `sale_reset()`s the cart, so the surface that opens it
#                      second has no cart to judge at all and `ensure_cart` would
#                      silently build a *different* order.
#   UNCLASSIFIED       Refused the same way, and the default for every entry
#                      nobody has read against the rule: the 15 portal and `mail`
#                      prefixes #226 and #247 added, and anything added tomorrow.
#                      Over-refusing is the direction this guard errs in, and no
#                      targets file aims at any of them.
#
# `/shop/cart` and `/my/orders/` are the two #225 left pending; #228 read both
# against the criterion at the pinned Odoo and promoted both, and their entries
# below carry the audit. Each has one branch that does not converge -- the cart's
# abandoned-cart revival, the order page's viewed-by-customer note -- and a query
# is the only way to reach either (`access_token`, `revive`), which
# `_TARGET_QUERY` refuses: a target may carry a view chooser and nothing else.
# That dependency is the promotion's footing rather than a detail, so a static
# test ties the two together; if the query rule ever widens, both entries have to
# be read again. It is the reading this list already uses two entries below, for
# `/payment/pay` and `/my/payment_method`: a write only a refused query reaches is
# a write no target can make.
#
# A key is a prefix, so promoting these two promotes everything under them, and
# what bounds the rest is that `open` makes a GET and nothing else. Under
# `/shop/cart`: `/shop/cart/update` (controllers/main.py:803) accumulates a line
# per call and is `methods=['POST']`, and `/shop/cart/update_json` (:838),
# `/shop/cart/quantity` (:948) and `/shop/cart/clear` (:954, which empties the
# cart) are `type='json'`. Under `/my/orders/`: `/my/orders/<id>/decline` (sale/
# controllers/portal.py:329) is `methods=['POST']`, and `/accept` (:279),
# `/transaction` (:382) and `website_sale`'s `/my/orders/reorder_modal_content`
# (controllers/reorder.py:38) are `type='json'`. The two siblings a GET does
# reach -- `/my/orders/page/<n>` (:110) and `/my/orders/<id>/document/<n>`
# (:361) -- are the ones the entry below already records as writing nothing.
#
# One of the two promotions is load-bearing rather than theoretical, which #225
# did not know when it wrote that no targets file aims at either:
# `docs/testing/evidence/2026-09-30-issue-213/targets.jsonl` aims at `/shop/cart`,
# and it is the Live check PR #229 owes. Refusing the route would have made that
# check unrunnable, so the audit above is what the check rests on -- read it
# again before changing either.
#
# A key is a route prefix: it bounds the route itself and everything under it,
# so `/shop/change_pricelist` covers the `/shop/change_pricelist/<id>` the route
# is actually spelled as, and a route under a prefix needs its own key only when
# its write is not the one the prefix cites -- `/shop/payment/validate` has one
# for that reason, and the longest key is the one a refusal names. A key that
# ends in a slash bounds only what is *under* it and not the path itself, which
# is how `/my/orders/<id>` is bounded while the `/my/orders` list page, which
# writes nothing and is a parity path of its own, stays open. The value
# cites the write in upstream Odoo at the version odoo18ce/Dockerfile pins --
# 18.0.20260930, `ODOO_DEB_VERSION` -- read from that `.deb` under
# `usr/lib/python3/dist-packages/odoo/addons/`; a path with no module in front
# of it is under `website_sale/`, the module #212 audited route by route.
#
# That audit covers every `type='http'` route of `website_sale` the navigation
# itself can reach -- every `@route` of `controllers/`, including the bare
# `@route()` overrides of `website`'s own routes, whose route is the parent's:
# one not listed here is either unreachable by that navigation
# (`methods=['POST']`, `type='json'`) or its body was read and writes nothing --
# nothing but `request.session` (`/shop`), or nothing at all (`/shop/<product>`,
# `/shop/<product>/document/<id>`, `/shop/confirmation`, `/shop/print`,
# `/shop/product/<id>`). The body is what
# was read, not the `readonly=True` flag two of them carry: that flag is not a
# bound, because `odoo/http.py:2157-2168` rolls a read-only transaction back and
# re-runs the handler on a read/write cursor, so a `readonly` route that writes
# writes anyway.
#
# Four limits on what that buys, none of them something a list keyed on the
# target's route can see. Three are writes a GET makes outside its own
# controller, and what they mean for the read-only guarantee -- "no business
# writes", not zero rows -- is recorded in
# `docs/adr/0012-sweeps-verify-on-the-test-host.md` (postscript 2026-10-01,
# #227) rather than here: the cart link of every page header calls
# `website.sale_get_order()` from the template (`views/templates.xml:13`) and
# writes the way `/shop/checkout` does (models/website.py:457); the page's own
# JavaScript posts on its own account
# (`/shop/products/recently_viewed_update`, controllers/main.py:2288); and
# serving a tracked page writes a `website.visitor` and a `website.track` row
# (`website/models/ir_http.py:203`), gated on the template the response rendered
# rather than on the route, which is why no key can bound it. The fourth limit
# is this list's own: the route navigated is not always the route answered,
# since `page.goto` follows a 30x, so a route that redirects into a listed one
# writes behind the guard -- no `website_sale` route does (the set is closed
# under its own redirects), which is a property of today's Odoo and not of this
# list. `project`'s two outdated portal prefixes are redirects of exactly that
# shape and are listed below for it; they are the ones that were found, not the
# ones that exist.
#
# Most of the `/my/...` keys below are one write seen from several routes.
# `_get_page_view_values` (portal/controllers/portal.py:437) calls
# `get_records_pager`, which at :93 and :100 calls `_portal_ensure_token()` on
# the record either side of this one in the session's browsing history, and
# portal/models/portal_mixin.py:33 writes a fresh `access_token` on each. Every
# portal document page calls it, on a GET with no query and no form. Each of
# those keys ends in a slash for that reason: the write is on the document page,
# while the list page above it writes nothing and is a parity path of its own.
# `get_records_pager` writes only when the record is in the session's history
# (portal/controllers/portal.py:85), which the list page fills -- so whether a
# given navigation writes depends on what the run opened before it. A list keyed
# on a route cannot see the session, and a guard that asked would be guessing, so
# the prefix bounds the page either way.
#
# A known write belongs on the list whatever module holds it -- an entry bounds
# it, and leaving it off to keep the list tidy would leave the hole #212 was
# about. Two kinds of entry below are deliberately wider than what a target can
# ask for. A write reachable only through a query (`?confirm=reminder`,
# `?report_type=pdf`) is bounded anyway, because `get_writing_route` keys on the
# path and `parse_targets` already refuses every query but `view_type=`. And a
# route whose only write is the one it redirects into is bounded at the route
# navigated, because `page.goto` follows the 30x.
#
# The portal audit #226 asked for read, `@route` by `@route`, every portal
# controller of the installed modules and their dependency closure at the pinned
# Odoo: portal (portal.py, mail.py, attachment.py, message_reaction.py,
# thread.py, web.py), sale, sale_management, account (portal.py,
# download_docs.py, terms.py), account_payment, project, hr_timesheet, purchase,
# payment (portal.py, post_processing.py), website_payment, digest, portal_rating
# and rating. What it read and found clean, so the next audit need not read it
# again: the portal home and its counters (`/my`, `/my/home`, `/my/counters` --
# `request.session` only), `/my/account` (portal/controllers/portal.py:208) and
# `/my/security` (:262), which write on their POST branch only; every list page
# (`/my/orders`, `/my/quotes`, `/my/invoices`, `/my/purchase`, `/my/rfq`,
# `/my/projects`, `/my/tasks`, `/my/timesheets`); the project-sharing page
# (project/controllers/portal.py:186, which renders the web client); `/terms`;
# the payment result pages (`/payment/confirmation`, `/payment/status`) and
# `/donation/pay`, whose `payment_utils.generate_access_token` is an hmac and not
# a record and whose only other write is `request.session`; the downloads
# (`/account/download_invoice_attachments`, `/account/download_invoice_documents`,
# `/my/orders/<id>/document/<id>`), whose PDF path renders without storing
# because the report records read carry no `attachment`
# (base/models/ir_actions_report.py:1037 is what the flag gates); the chatter's
# author avatar (portal/controllers/mail.py:25, which streams an image through
# `ir.binary` and writes nothing); and both rating pages --
# rating/controllers/main.py:27 records that `/rate/<token>/<rate>` stopped
# writing on GET, and `/rate/<token>/submit_feedback` writes on its POST branch
# only (:60). A `type='json'` route and a `methods=['POST']` one are
# outside this audit the way they are outside `website_sale`'s: a GET does not
# reach them.
#
# Two routes that sweep read are clean on a bare GET and not clean in general,
# which is a weaker thing than the clean list above claims of its entries.
# `/payment/pay`
# (payment/controllers/portal.py:37) and `/my/payment_method` (:193) end in
# `_get_extra_payment_form_values`, which `account_payment` overrides
# (account_payment/controllers/payment.py:114) to store an `access_token` on the
# invoice at :149 whenever the request names an `invoice_id` -- a `?invoice_id=`
# in the query and nothing else. They are off the list because `parse_targets`
# refuses every query but `view_type=`, which is a narrower bound than the path:
# loosen that rule and these two become entries.
#
# Where this audit stopped, for the next one. Of `mail` it read only the two
# controllers the entries above cite -- controllers/mail.py and
# controllers/discuss/public_page.py -- and not the other 16. Sixteen and not
# eight, which this comment said first: `controllers/discuss/` is a directory of
# eight files of its own, and a listing of the top level alone misses it -- the
# same directory `/chat/` turned out to live in. Walk the tree.
#
# Those 16 carry 51 `@route` declarations, of which 5 are the shape this list
# cares about -- `type='http'` and not `methods=['POST']`, so a plain GET reaches
# them: discuss/binary.py:12, :35 and :65, discuss/rtc.py:111 and
# discuss/voice.py:10. All five carry `readonly=True`, which is not a write
# bound. #247 read all five out of the pinned `.deb`, and three of them write --
# not in their bodies, which are clean, but in a decorator they share. The
# entries below cite it; what it means for the next sweep is that reading a
# `mail` route means reading its decorators first.
#
# That write survives `readonly=True` for a second reason, beyond the rollback
# and re-run at odoo/http.py:2157-2168 this comment already records. Its guard is
# `not req.env.cr.readonly` (mail/models/discuss/mail_guest.py:30), and on this
# add-on that cursor is not readonly: `Registry.cursor(readonly=True)` hands back
# a read/write cursor unless `_db_readonly` is set (odoo/modules/registry.py:1015
# and :1028), which happens only when a `db_replica_host` is configured
# (registry.py:166), and cont-init writes none
# (rootfs/etc/cont-init.d/10-odoo-config.sh:97-100). So a guard that reads as a
# write bound on a replica holds nothing here, and no `ReadOnlySqlTransaction` is
# raised to say so. A `readonly=True` route is not just re-run after a write --
# on this product it was never on a read-only cursor to begin with.
#
# Read clean, so the next sweep need not read them again: the two worklet routes
# (discuss/rtc.py:111 and discuss/voice.py:10), which answer with a file read off
# the disk through `file_open`, reach no model at all and carry no decorator.
# Clean too, and the reason the three above are entries rather than clean: the
# bodies of all three only search a channel and stream an attachment through
# `ir.binary`, which writes nothing at the pinned Odoo -- no create, write or
# unlink in base/models/ir_binary.py, `_get_image_stream_from` (:160) resizes in
# memory, and `ir.attachment`'s `validate_access` (:723) and `_to_http_stream`
# (:805) write nothing either.
#
# The same sweep read the two routes in controllers/mail.py that #226 counted as
# read while recording only `/mail/unfollow` out of it: `/mail/view` (:182) and
# `/mail/message/<id>` (:237). Both write, both are entries below.
#
# Where #247 stopped. The decorator is not `mail`'s to carry alone -- `im_livechat`
# (controllers/main.py:76, :110, :215, :248, :255 and :261, chatbot.py:11, :22,
# :38 and :112, rtc.py:12, attachment.py:14), `cloud_storage`
# (controllers/attachment.py:11) and `website_livechat` (models/website.py:14)
# apply it too, and `im_livechat` is installed. Those are the next thing to read,
# and reading them is one `type=`/`methods=` check per route rather than 13
# bodies, because the write is already read.
#
# Untouched: the non-portal controllers of every other module (website's
# `main.py` and `form.py`, and the controllers of web, web_editor, html_editor,
# survey, event, im_livechat, point_of_sale, mass_mailing, product, stock,
# delivery, crm, calendar, bus, auth_signup and the hr_* modules), and the four
# add-on modules that are not in the pinned `.deb` at all -- `ecpay_invoice_tw`,
# `ecpay_invoice_website`, `payment_ecpay` and
# `payment_ecpay_ecpg`. `/chat/` and `/meet/` below are a warning about what that
# leaves: they were found only because a review round went looking outside the
# portal, and they are the first writes on this list that no query rule bounds.
GET_WRITING_ROUTES = {
    # controllers/main.py:796 unlinks the cart lines of archived products, and
    # :785-786 rewrites an abandoned cart's lines onto the session cart and
    # cancels it when `?access_token=` revives one.
    # #228's convergence audit, and the reason this is `CONVERGENT`: every write
    # a target can reach is idempotent. :796 has nothing left to unlink on a
    # second visit, and the surface that ran first already rendered the cart
    # without those lines; :767 `sale_get_order()` moves the order onto the
    # logged-in partner only while the two disagree (models/website.py:455-457);
    # and :798 reaches sale/controllers/portal.py:270, whose
    # `_portal_ensure_token()` stores an `access_token` only when the order has
    # none (portal/models/portal_mixin.py:31-33), so the second surface reads the
    # token the first one stored rather than minting another. The one
    # consumption is :785-786, and it needs `?access_token=...&revive=merge`,
    # which `_TARGET_QUERY` refuses.
    "/shop/cart": GetWrite("unlinks the cart lines of archived products", CONVERGENT),
    # controllers/main.py:1056 persists a delivery method and its price on the
    # draft order (`_set_delivery_method`); :1039 runs `_check_cart_and_addresses`,
    # which reaches `_check_cart` at :2038, which at :2073-2076 stores a
    # `shop_warning` on the order and its zero-priced lines. `sale_get_order`
    # itself writes too: models/website.py:457 moves the order onto the
    # logged-in partner when the two disagree.
    "/shop/checkout": GetWrite("persists a delivery method on the draft sale.order", CONVERGENT),
    # controllers/main.py:1133 runs the same `_check_cart` before rendering the
    # address form, so the `shop_warning` writes at :2073-2076 apply here too.
    "/shop/address": GetWrite("stores a shop_warning on the cart through _check_cart", CONVERGENT),
    # controllers/main.py:1797-1802 recomputes the order's taxes and prices and
    # re-applies its delivery method, all on the draft order.
    "/shop/confirm_order": GetWrite("recomputes the draft order's taxes, prices and delivery method", CONVERGENT),
    # controllers/main.py:1820 runs `_check_cart` before rendering the extra
    # step, so the `shop_warning` writes at :2073-2076 apply.
    "/shop/extra_info": GetWrite("stores a shop_warning on the cart through _check_cart", CONVERGENT),
    # controllers/main.py:1931 runs `_check_cart_and_addresses`, so the
    # `shop_warning` writes at :2073-2076 apply.
    "/shop/payment": GetWrite("stores a shop_warning on the cart", CONVERGENT),
    # Under the same prefix, and its own entry because the longest match is what
    # a refusal reports and this write is not the one above: controllers/
    # main.py:1978-1979 confirms the draft order (`_check_cart_is_ready_to_be_paid`
    # then `_validate_order`), which is a sale and not a draft edit, and
    # `request.website.sale_reset()` then drops the cart the run was judging.
    "/shop/payment/validate": GetWrite("confirms the draft order into a sale and resets the cart", FIXTURE_CONSUMING),
    # controllers/main.py:737 and :747 set the cart's pricelist and recompute
    # its prices (`_cart_update_pricelist`, `_recompute_prices`).
    "/shop/pricelist": GetWrite("sets the cart's pricelist and recomputes its prices", CONVERGENT),
    # controllers/main.py:721 sets the cart's pricelist for the pricelist the
    # route names (`_cart_update_pricelist`).
    "/shop/change_pricelist": GetWrite("sets the cart's pricelist and recomputes its prices", CONVERGENT),
    # `website`'s route, and `website_sale` overrides it to write: controllers/
    # website.py:72-79 is a bare `@route()` over `/website/lang/<lang>`
    # (website/controllers/main.py:210, `type='http'` and not `readonly`), and
    # its body marks the cart's order lines for a recompute of their `name` in
    # the new language, which the request flushes onto `sale.order.line`.
    "/website/lang": GetWrite("recomputes the cart's order line names in the chosen language", CONVERGENT),
    # `sale`'s route, not `website_sale`'s, and on the list because the write was
    # read: sale/controllers/portal.py:270 `_portal_ensure_token()` stores a
    # fresh `access_token` on any order `_has_to_be_paid()`, and :168 posts a
    # "Quotation viewed by customer" note on a draft or sent order a portal user
    # opens with a token. It also writes with neither of those: :199 reaches the
    # portal pager, which stores an `access_token` on the orders either side of
    # this one. The key ends in a slash because the write is on
    # `/my/orders/<int:order_id>` (:123) and not on `/my/orders` itself (:110),
    # which only fills `request.session`. It over-refuses two siblings that write
    # nothing -- `/my/orders/page/<n>` (:110) and `/my/orders/<id>/document/<n>`
    # (:361) -- because no static prefix separates an order id from them, and
    # over-refusing is the direction a guard errs in.
    # #228's convergence audit, and the reason this is `CONVERGENT`: both writes
    # a target reaches are the same guarded re-store -- :270's
    # `_portal_ensure_token()` and the pager's two at :199
    # (portal/controllers/portal.py:93 and :100), all three of them
    # portal/models/portal_mixin.py:31-33, which writes only when the record has
    # no token -- so the second surface renders the token the first one stored.
    # The accumulation is :168's "Quotation viewed by customer" note, and it
    # needs a share user *and* a truthy `access_token`, which only a query
    # supplies; its `view_quote_<id>` session guard (:157-161) is per-session and
    # two surfaces are two sessions, so what keeps the note out of a run is the
    # query rule and not that guard.
    "/my/orders/": GetWrite(
        "stores an access_token on an unpaid order and posts a viewed-by-customer note", CONVERGENT),
    # `account`'s invoice page: account/controllers/portal.py:153 renders
    # `/my/invoices/<int:invoice_id>` through `_invoice_get_page_view_values`
    # (:47), which reaches the portal pager and stores an `access_token` on the
    # invoices either side of this one. Slash-terminated for the same reason as
    # the orders key: `/my/invoices` (:81) only fills `request.session`. It
    # over-refuses `/my/invoices/page/<n>` (:81), which writes nothing.
    "/my/invoices/": GetWrite(
        "stores an access_token on the neighbouring invoices through the portal pager", UNCLASSIFIED),
    # Under that prefix, and its own entry because the longest match is what a
    # refusal reports and this write is not the one above: the overdue-invoices
    # page (account_payment/controllers/portal.py:53) asks the company for a
    # batch payment reference at :85 whenever a partner has more than one overdue
    # invoice, and account/models/company.py:272 takes it from an `ir.sequence`
    # with `next_by_id()`, which bumps the sequence -- a write on the company's
    # numbering and not on any invoice.
    "/my/invoices/overdue": GetWrite("bumps the company's batch payment sequence", UNCLASSIFIED),
    # `purchase`'s order page: purchase/controllers/portal.py:145 renders
    # `/my/purchase/<int:order_id>` through :110, which reaches the portal pager.
    # With a query it writes more: :158, :160 and :162 take `?confirm=` as the
    # vendor's answer and flip `mail_reminder_confirmed` /
    # `mail_reception_confirmed` / `mail_reception_declined` with a chatter note
    # (purchase/models/purchase_order.py:1125, :1143 and :1152), and the last one
    # also schedules an activity (:1153). `/my/purchase` (:126) and `/my/rfq`
    # (:112) write nothing; `/my/purchase/page/<n>` is over-refused.
    "/my/purchase/": GetWrite(
        "stores an access_token on the neighbouring purchase orders and answers ?confirm= on the order", UNCLASSIFIED),
    # `project`'s project page and the task pages under it:
    # project/controllers/portal.py:209 calls `generate_access_token()` on every
    # attachment of the task it is about to render, and
    # base/models/ir_attachment.py:691 writes an `access_token` on each; :125 and
    # :197 both reach the portal pager through :58 and :304. `/my/projects` (:69)
    # writes nothing. Over-refuses `/my/projects/<id>/page/<n>` (:125),
    # `/my/projects/<id>/project_sharing` (:186) and the subtask and recurrent
    # task lists (:214, :247), none of which write.
    "/my/projects/": GetWrite(
        "stores access_tokens on a task's attachments and on the neighbouring records", UNCLASSIFIED),
    # `project`'s standalone task page: project/controllers/portal.py:556 is the
    # same `generate_access_token()` write (ir_attachment.py:691), and :561
    # reaches the portal pager through :304. `/my/tasks` (:514) writes nothing.
    "/my/tasks/": GetWrite(
        "stores access_tokens on a task's attachments and on the neighbouring tasks", UNCLASSIFIED),
    # The outdated spellings of the two above, and on the list because of what
    # they redirect into: project/controllers/portal.py:110 and :118 answer
    # `/my/project/...` and `/my/task/...` with a 30x onto `/my/projects/...` and
    # `/my/tasks/...`, and `page.goto` follows a 30x, so the landing page's write
    # is this route's write. Both keys end in a slash: `/my/task` redirects onto
    # the task list page, which writes nothing, and `/my/project` is not a route.
    "/my/project/": GetWrite("redirects onto /my/projects/<id>, which writes", UNCLASSIFIED),
    "/my/task/": GetWrite("redirects onto /my/tasks/<id>, which writes", UNCLASSIFIED),
    # `mail`'s route, which `portal` overrides to add the portal layout
    # (portal/controllers/mail.py:172, a bare `@route()` over
    # mail/controllers/mail.py:217 -- `type='http'`, no `methods`, so a GET
    # reaches it): mail/controllers/mail.py:225 unsubscribes the partner the
    # query names from the record's followers, which unlinks a `mail.followers`
    # row. The token check in front of it (:219) is not a write bound; a wrong
    # token raises instead, and a guard errs towards refusing.
    "/mail/unfollow": GetWrite("unsubscribes a follower from the record", UNCLASSIFIED),
    # `digest`'s two GET-reachable routes, one key because the prefix is static
    # and the digest id is not: digest/controllers/portal.py:25 takes
    # `methods=['GET', 'POST']` and unsubscribes a user at :51 or :54
    # (digest/models/digest.py:119 writes `user_ids`), and :62 carries no
    # `methods` at all and sets the digest's periodicity at :70
    # (digest/models/digest.py:128). The POST-only one-click route (:14) is under
    # the same prefix and is refused with them, which costs nothing: a GET never
    # reaches it.
    "/digest/": GetWrite("unsubscribes a user from a digest and sets the digest's periodicity", UNCLASSIFIED),
    # `mail`'s Discuss public pages, and the only writes found outside a portal
    # controller that a *path* alone reaches -- no query, so the rule that bounds
    # `?confirm=` and `?report_type=` does not reach them, and the Runtime shim
    # rewrites the invitation link that leads here
    # (rootfs/etc/nginx/nginx.conf.template:591), so it is a route this product
    # navigates. mail/controllers/discuss/public_page.py:42 takes the channel's
    # uuid in the path and reaches :96 `_find_or_create_persona_for_channel`,
    # which creates a `mail.guest` and its `discuss.channel.member` for whoever
    # opened the link; :14 and :27 take a token that names no channel yet and
    # create the `discuss.channel` itself at :69 -- and on a concurrent insert
    # the handler calls `request.env.cr.commit()` at :81, which a rollback cannot
    # take back. The `/chat/...` creation is gated on the `mail.chat_from_token`
    # config parameter (:63) and the guest creation on nothing but the uuid. Both
    # keys end in a slash because neither `/chat` nor `/meet` is a route.
    # `/discuss/channel/<id>` (:52) renders the same page without the persona
    # step, which is why the key is not `/discuss/`. This comment also said that
    # page writes nothing: it carries `@add_guest_to_context` (:53), so it writes
    # what the four keys below write, and `/discuss/channel/` bounds it there.
    "/chat/": GetWrite(
        "creates a mail.guest and a discuss.channel.member, and a discuss.channel from an unknown token", UNCLASSIFIED),
    "/meet/": GetWrite("creates a discuss.channel from an unknown token, and a mail.guest in it", UNCLASSIFIED),
    # #247's sweep of `mail`'s other 16 controllers, and one write answers for
    # the first three keys: `@add_guest_to_context`
    # (mail/models/discuss/mail_guest.py:18) updates the guest's timezone at
    # :30-33, through the raw `UPDATE mail_guest` at :105-114, on every route it
    # decorates. It needs two cookies and no query -- the `dgid` a Discuss public
    # page above left behind (:136) and a `tz` holding a name `pytz` knows (:90).
    # Nothing in the pinned Odoo sets `tz` itself, so the write is dormant on a
    # browser that has only ever been here; under Ingress the page is served from
    # the Home Assistant origin, where another application's cookie reaches Odoo.
    # These are keys and not a "clean on a bare GET" note like `/payment/pay`
    # above for that reason: that one is held off the list by a rule
    # `parse_targets` enforces, and a cookie by nothing.
    #
    # The channel pages: the attachment stream and the image stream
    # (mail/controllers/discuss/binary.py:12 and :35, decorated at :19 and :45)
    # and the public page `/discuss/channel/<id>` (discuss/public_page.py:52,
    # decorated at :53). The POST-only JSON routes under the same prefix
    # (discuss/channel.py) are refused with them, which costs nothing: a GET
    # never reaches one. `/discuss/channel` is not a route, hence the slash.
    "/discuss/channel/": GetWrite("updates a guest's timezone through mail's guest-context decorator", UNCLASSIFIED),
    # `web`'s image route, which `mail` re-exposes to put that decorator on it:
    # discuss/binary.py:65 is a bare `@route()` whose body is a plain `super()`
    # call (:68) and whose routing is web/controllers/binary.py:164-182 -- 17
    # paths, `type='http'`, `readonly=True` and no `methods`, so a GET reaches
    # every one of them -- with the decorator at :66. No trailing slash, because
    # `/web/image` itself is the first of the 17.
    "/web/image": GetWrite("updates a guest's timezone through mail's guest-context decorator", UNCLASSIFIED),
    # `mail`'s message redirect, in the controller #226 counted as read while
    # recording only `/mail/unfollow` out of it: mail/controllers/mail.py:237
    # carries the decorator at :238, and it redirects through
    # `_redirect_to_record` (:72), which is the write on the key below. Both
    # writes, one route. Slash-terminated because `/mail/message` is not a route;
    # the JSON routes under it (`/mail/message/post`, `/mail/message/reaction`,
    # `/mail/message/translate`, `/mail/message/update_content`) are refused with
    # it and a GET never reaches one.
    "/mail/message/": GetWrite(
        "updates a guest's timezone and stores an access_token on the record it redirects to", UNCLASSIFIED),
    # The same controller's notification entry point (mail/controllers/mail.py:182),
    # which carries no decorator and writes anyway: `_redirect_to_record` asks the
    # record for its access action (:129 and :131), and
    # portal/models/portal_mixin.py:68 overrides that for a share user -- which an
    # `auth='public'` visitor is -- to return `_get_share_url()` (:99), whose
    # `_portal_ensure_token()` (:59) writes a fresh `access_token` at :33 on any
    # portal record that has none. The portal pager's write, reached from a
    # notification link instead of a portal page. An internal user's branch ends
    # in `get_formview_action` (base/models/ir_ui_view.py:2427), which writes
    # nothing -- so whether this route writes depends on who is logged in, the way
    # the pager's depends on what was opened before it, and the prefix bounds the
    # route either way.
    "/mail/view": GetWrite("stores an access_token on the record the notification link names", UNCLASSIFIED),
}


def get_writing_route(route: str) -> str | None:
    """The `GET_WRITING_ROUTES` prefix `route` falls under, or None.

    A prefix matches the route itself and anything below it, on a path segment
    boundary: `/shop/payment/validate` is under `/shop/payment`, and a route
    that merely starts with the same characters (`/shop/cartons`) is not. A
    prefix that ends in a slash matches only what is below it, so `/my/orders/`
    bounds `/my/orders/7` and leaves `/my/orders` alone. The longest match wins,
    so adding a narrower entry under a wider one reports the narrower one rather
    than whichever the dict happens to hold first. The query is ignored -- it
    cannot make a writing route a reading one.

    A route that is not an absolute path is refused rather than answered.
    `parse_targets` refuses one too, so reaching this is a caller that skipped
    it, and a guard that cannot read the route must not say it is safe.

    The path is compared as Odoo routes it, not as it was typed, three ways.
    Percent-escapes and repeated slashes: `normalize_route` keeps both on purpose
    because they can route differently, and werkzeug unquotes before matching, so
    `/shop/%63heckout` reaches `/shop/checkout`. Dot segments and backslashes: the
    browser resolves the first and folds the second to `/` before it asks, so
    `/shop/x/../checkout` and `/shop\\checkout` both ask for `/shop/checkout` --
    `normalize_route` refuses both outright (`_safe_path`), so only a target
    nobody parsed brings one here, which is the caller this helper cannot rely
    on. And the language segment: Odoo's frontend
    takes the first segment of a path it cannot route as a language code and
    routes what is left (`http_routing/models/ir_http.py:390-392` at the pinned
    Odoo), which makes `/zh_TW/shop/checkout` the ordinary spelling of the
    checkout on a multilingual site. Every one of them can only refuse more than
    the literal spelling would, which is the safe direction for a guard.
    """
    parts = urlsplit(route)
    if parts.scheme or parts.netloc or not parts.path.startswith("/"):
        raise ValueError("crawler configuration: %r is not an absolute path, so whether it writes "
                         "on a plain GET cannot be judged" % route)
    # A backslash is a separator to the browser, which folds it to `/` before it
    # asks. `normpath` then resolves the dot segments the browser would resolve
    # for itself; it runs after the unquote so a `%2e` or a `%5c` counts, and
    # after the collapse so a leading `//` it would keep is already gone.
    path = unquote(parts.path).replace("\\", "/")
    path = posixpath.normpath(re.sub(r"/{2,}", "/", path))
    head, _, rest = path.lstrip("/").partition("/")
    candidates = [path] + (["/" + rest] if head and rest else [])
    found: str | None = None
    for candidate in candidates:
        trimmed = candidate.rstrip("/") or "/"
        for prefix in GET_WRITING_ROUTES:
            if prefix.endswith("/"):
                # Below the prefix only: `trimmed` carries no trailing slash, so
                # the prefix's own path cannot match it.
                if not trimmed.startswith(prefix):
                    continue
            elif trimmed != prefix and not trimmed.startswith(prefix + "/"):
                continue
            if found is None or len(prefix) > len(found):
                found = prefix
    return found


def _writing_entries(targets: Sequence[OpenTarget]) -> list[tuple[OpenTarget, str, GetWrite]]:
    """Each target that names a GET-writing route, with the prefix and entry it hit."""
    found = []
    for target in targets:
        prefix = get_writing_route(target.route)
        if prefix is not None:
            found.append((target, prefix, GET_WRITING_ROUTES[prefix]))
    return found


def _non_convergent_reasons(targets: Sequence[OpenTarget]) -> list[str]:
    """One reason per target naming a GET-writing route whose write does not converge."""
    return ["target %s names %s, which %s (%s: %s)"
            % (target.target, prefix, entry.write, entry.classification,
               # A class added without a reason still refuses: a guard may not
               # raise a KeyError where it owes the operator a sentence.
               NOT_CONVERGENT_REASON.get(entry.classification, "its write does not converge"))
            for target, prefix, entry in _writing_entries(targets) if not entry.converges]


def _refused_everywhere_message(reasons: Sequence[str]) -> str:
    """The refusal every non-convergent target gets, in one sentence."""
    return ("%s; such a target is refused on every database, %s included -- a targets file may name a "
            "GET-writing route only when its write converges (see GET_WRITING_ROUTES)"
            % ("; also ".join(reasons), WRITE_DATABASE))


def require_convergent_writes(targets: Iterable[OpenTarget]) -> None:
    """A target may name a GET-writing route only when that write converges.

    #225's rule (2026-09-30), and the half the database bound cannot express: a
    bound says *where* a write is allowed, this says which writes may be aimed
    at in the first place. A write that consumes or accumulates leaves the
    second surface a different screen than the first surface judged, on
    `WRITE_DATABASE` as much as anywhere else -- so this reads the target list
    and no database, which is why `open_screens` runs it before a browser
    launches rather than after the login. `GET_WRITING_ROUTES` carries the
    classification and states the rule.

    `require_write_database` makes the same refusal from the same helper, so the
    driver's per-target check and every other caller of that guard get it from
    the call they already make -- and get it in one message with whatever the
    database bound refuses, rather than in two runs.
    """
    reasons = _non_convergent_reasons(tuple(targets))
    if reasons:
        raise RuntimeError("crawler configuration: %s" % _refused_everywhere_message(reasons))


def require_write_database(targets: Iterable[OpenTarget], database: str | None) -> None:
    """A target that writes the two ways a target can say so is bounded, or refused.

    ADR 0012 allows the write on one database only, and a target says it writes
    two ways: it declares a `cart:`, or it names a route on `GET_WRITING_ROUTES`.
    Both are refused here, before the first screen is opened, so a misaimed run
    is a configuration error and not a mutated database.

    Not every write a run can make is one of those two -- the audits behind the
    list are `website_sale`'s controllers and the portal controllers of the
    installed modules, and a page writes through its own templates and
    JavaScript as well. `GET_WRITING_ROUTES` says what is outside it and why.
    This guard is as good as that list, not better.

    `database` is what the session reported it is on. `None` -- it reported
    nothing -- refuses the write like any other wrong answer: a run that cannot
    say where it would write may not write.

    The bound is not the whole rule: a route whose write does not converge is
    refused on `WRITE_DATABASE` too -- the #225 rule `require_convergent_writes`
    is named after. That refusal is made here as well, from the same helper and
    before the bound is read, so it applies whatever the session answered.
    """
    # Read once: this walks the targets several times, and an `Iterable` may be a
    # generator, which the first walk would leave empty for the rest.
    targets = tuple(targets)
    banned = _non_convergent_reasons(targets)
    bounded: list[str] = []
    if database != WRITE_DATABASE:
        # Every reason at once. A file can hold both kinds, and reporting one of
        # them sends the operator back for another browser launch and login to be
        # refused for the other. A banned route is reported as banned and not
        # again as bounded: editing the file is the only answer to it, whatever
        # database the next run is on.
        bounded = ["a target fills a cart, which writes"] if any(target.cart for target in targets) else []
        bounded += ["target %s writes on a plain GET -- %s %s" % (target.target, prefix, entry.write)
                    for target, prefix, entry in _writing_entries(targets) if entry.converges]
    if not banned and not bounded:
        return
    said = [_refused_everywhere_message(banned)] if banned else []
    if bounded:
        said.append("%s; that write is allowed on %s only, and the session's database is %r"
                    % ("; also ".join(bounded), WRITE_DATABASE, database))
    raise RuntimeError("crawler configuration: %s" % ". Also: ".join(said))


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
    # The records an `open` target created to reach its screen and the draft
    # order its screen's own GET left behind -- the cart `ensure_cart` filled,
    # or the one a failed cart step left empty, and the reading
    # `_draft_order_after_visit` takes after a target on `GET_WRITING_ROUTES`.
    # Empty still does not mean the run wrote nothing: that reading covers
    # `sale.order` and no other model -- the `access_token` a portal route
    # stores is outside it -- and the page's own templates and JavaScript write
    # where nothing reads them. Read it as "what the run set up and what the
    # draft order held after it", not as "what the database got".
    writes: Sequence[Mapping[str, Any]] = ()


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
    run: RunInfo, surface: Surface, *, module: str, identity: str, observation: SurfaceObservation,
    label: str = "",
) -> dict[str, Any]:
    """One surface's record; `verdict` stays empty until `diff` joins two runs."""
    screen = {"route": observation.route, "model": observation.model, "view": observation.view}
    record = _base_record(run, module, identity, screen)
    if label:
        record["label"] = label
    record[_SURFACE_KEY[surface]] = {
        "available": observation.available,
        "result": observation.result,
        "screen": screen,
        "signals": {name: int(observation.signals.get(name, 0)) for name in SIGNALS},
        "url_literals": sorted(set(observation.url_literals)),
        "url_violations": [dict(item) for item in observation.url_violations],
        "http_5xx": int(observation.http_5xx),
    }
    if observation.writes:
        record[_SURFACE_KEY[surface]]["writes"] = [dict(item) for item in observation.writes]
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


def _written(block: Mapping[str, Any]) -> list[str]:
    """The records a surface's run created or reused, and how much each holds.

    The size matters as much as the identity: the same cart with another line
    in it renders another screen, and one run adding a line the other did not
    see is exactly what this comparison is for.
    """
    return sorted("%s:%s holding %s" % (item.get("model"), item.get("id"), item.get("items"))
                  for item in block.get("writes") or ())


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
    left_writes, right_writes = _written(public), _written(ingress)
    if left_writes != right_writes:
        # Both surfaces share the logged-in user, so a cart target fills one
        # cart and the other run reuses it, and a target on a GET-writing route
        # reports the draft order its own navigation left. Two different records
        # mean the two screens were rendered from different data, and nothing
        # below them can be attributed to the surface.
        reasons.append("records written: public=%s ingress=%s"
                       % (", ".join(left_writes) or "none", ", ".join(right_writes) or "none"))
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
    # Two databases are two sets of data, and every difference between them
    # would be read here as a difference between the surfaces.
    databases = {record.get("database") for record in (*public.values(), *ingress.values())}
    if len(databases) > 1:
        raise ValueError("crawler configuration: the two runs are not on one database: %s"
                         % ", ".join(sorted(repr(name) for name in databases)))
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


# --- Ambient writes -------------------------------------------------------

AMBIENT_SCHEMA = "odoo-parity-ambient/v1"
# The two models a run's page views write without being aimed at. ADR 0012's
# postscript 2026-10-01 (#227) reads both writes out of the pinned Odoo: serving
# a tracked page upserts a `website.visitor` and inserts a `website.track` row in
# one statement (`website/models/website_visitor.py:288-300` and `:239-251`), so
# on a tracked page's GET the two counts move together -- and apart everywhere
# else, because `/shop/products/recently_viewed_update`, which a product page's
# own JavaScript calls, creates a visitor and no track row.
AMBIENT_MODELS = ("website.track", "website.visitor")
# What the figure is, said where it is read. A delta is an accounting row and
# not a verdict, and a reader who takes it for one has a parity signal that does
# not exist: see `ambient_summary`.
AMBIENT_NOTE = (
    "Counts only, and a net figure over one surface's run. The window runs from after the login to "
    "after the last navigation, so a row the login itself left is outside it; another session writing "
    "on the same database during the run is inside it; and the `website.visitor` GC cron takes a "
    "visitor's `website.track` rows with it, so a delta below zero is a vacuum that ran during the run "
    "and not a deletion the run made. No URL and no visitor identity is read -- nothing here to mask. "
    "`diff` does not judge it: both surfaces visit the same pages, so an unequal delta is an ordering "
    "artefact -- the visitor the first run created already exists for the second -- and not a gap. "
    "Why these rows exist and why no targets file can bound them: ADR 0012, postscript 2026-10-01 "
    "(#227)."
)
# What the `navigations` denominator counted, said in the file that carries it.
# Two drivers count two different things and both are page views, so the number
# is not comparable across files without this sentence: this driver counts the
# navigations it issued, and the hand-driven drivers count the document GETs
# their browser context made -- which is the only way to see a navigation a
# click caused or one the website editor's preview iframe made for itself.
AMBIENT_BASIS_GOTO = (
    "Every navigation this run issued, counted in `SurfaceDriver._goto` -- the one place this driver "
    "navigates. A page's own subsequent requests are not navigations and are not counted, and neither "
    "is the login, which falls before the first reading."
)
AMBIENT_BASIS_DOCUMENTS = (
    "Every document GET this run's browser context(s) made under the surface's base URL, counted off "
    "Playwright's request event (`NavigationCount`): a click's navigation, a redirect hop and a "
    "document the website editor's preview iframe fetched for itself all count, because what writes "
    "the rows is a GET being served and this driver does not navigate through one call. It is "
    "therefore an upper bound on page views rather than a count of them -- a redirect's own response "
    "renders no tracked page. Requests off the base (the Home Assistant frontend's own documents) are "
    "outside it, and so is the login, which falls before the first reading."
)


@dataclass(frozen=True)
class AmbientReading:
    """One count per `AMBIENT_MODELS` model at one moment, and why any is missing.

    Per model rather than per reading: `website` uninstalled leaves neither
    count, but a user who may count visitors and not tracks leaves one, and a
    reading that reported one count and called itself failed would throw the
    count away.
    """

    counts: Mapping[str, int] = field(default_factory=dict)
    unread: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def none(cls, reason: str) -> "AmbientReading":
        """No reading at all -- the same reason against every model."""
        return cls(unread={model: reason for model in AMBIENT_MODELS})


def _ambient_unread(model: str, before: AmbientReading, after: AmbientReading) -> str:
    """Why `model` has no delta: whichever of the two readings is missing it."""
    return "; ".join("%s the run: %s" % (when, reading.unread.get(model) or "no count was taken")
                     for when, reading in (("before", before), ("after", after))
                     if model not in reading.counts)


def ambient_deltas(before: AmbientReading, after: AmbientReading) -> dict[str, dict[str, Any]]:
    """Per model: the two counts and `after - before`, or the reason for neither.

    The subtraction is the whole arithmetic, and it is deliberately not clamped
    or signed away. Zero is a reading and not a silence -- it is how a `crawl`
    shows the claim ADR 0012's postscript makes about it, that navigating
    `/odoo/action-<id>` reaches no tracked page -- and a negative delta is the
    GC cron, which the summary's note says rather than hiding by taking an
    absolute value.
    """
    rows: dict[str, dict[str, Any]] = {}
    for model in AMBIENT_MODELS:
        if model in before.counts and model in after.counts:
            rows[model] = {"before": before.counts[model], "after": after.counts[model],
                           "delta": after.counts[model] - before.counts[model]}
        else:
            rows[model] = {"unread": _ambient_unread(model, before, after)}
    return rows


def ambient_summary(
    run: RunInfo, surface: Surface | str, *, command: str, navigations: int,
    before: AmbientReading, after: AmbientReading,
    navigation_basis: str = AMBIENT_BASIS_GOTO,
) -> dict[str, Any]:
    """One surface's run and the ambient rows it left, as its own record.

    Its own schema, and its own file beside the evidence (`ambient_summary_path`),
    for the reason `diff` does not judge it: a delta is a property of one run,
    not of a control identity, and `_judge` reads every difference between two
    surfaces as a difference the surfaces caused. Both surfaces visit the same
    pages, so their deltas differ whenever one of them went first -- the visitor
    row the first run upserted is already there for the second -- and judging
    that would raise a Blocker on the order the two runs happened to run in.
    `read_records` refuses this schema, so a summary that reached the evidence
    file is a refusal rather than a verdict.

    It is none of the parity plan's conservation tally's business either: that
    tally is over control identities with verdicts (section 12), and this record
    holds neither.

    `navigation_basis` says what the denominator counted, because the drivers do
    not count the same thing: this one counts its own `_goto` calls, and a
    hand-driven driver counts the document GETs its browser context made
    (`NavigationCount`). Both are page views and neither is the other, so a
    reader comparing two files' `navigations` needs the sentence beside the
    number rather than under it.

    `surface` takes a key as well as a `Surface`, for the drivers that drive both
    in one run: `_SURFACE_KEY` has two entries because an adapter run is one
    surface, and a peer-snapshot run is a pair. The test is `isinstance(...,
    Surface)` and not `isinstance(..., str)`, because `Surface` *is* a `str`
    subclass -- a string test passes for both and would write `ha_ingress` where
    every existing record says `ingress`.
    """
    return {
        "schema": AMBIENT_SCHEMA,
        "run_id": run.run_id,
        "target": run.target,
        "database": run.database,
        "client": run.client,
        "surface": _SURFACE_KEY[surface] if isinstance(surface, Surface) else str(surface),
        "command": command,
        "navigations": int(navigations),
        "navigation_basis": navigation_basis,
        "models": ambient_deltas(before, after),
        "notes": AMBIENT_NOTE,
    }


def ambient_summary_path(out_path: str) -> str:
    """The summary's path: `out_path`'s extension replaced by `.ambient.json`.

    `ingress-open.jsonl` -> `ingress-open.ambient.json`, so the pair sorts
    together in an evidence directory and neither name carries two extensions.
    """
    return os.path.splitext(out_path)[0] + ".ambient.json"


def clear_ambient_summary(out_path: str) -> None:
    """Remove any earlier run's summary from beside `out_path`."""
    with contextlib.suppress(FileNotFoundError):
        os.remove(ambient_summary_path(out_path))


def write_ambient_summary(out_path: str, summary: Mapping[str, Any], *, append: bool = False) -> str:
    """Write the summary beside `out_path` and answer where it went.

    `append` follows the records the summary accounts for. This driver truncates
    `out_path` per run, so one object is the whole figure and a second run
    replaces it. The hand-driven drivers append one record per invocation to a
    records file an evidence directory keeps across a whole session
    (`markup.jsonl` carries 38 of them), so their figure appends too -- one JSON
    object per line, in the order the invocations ran. Truncating there would
    leave the last invocation's figure standing for every invocation's rows.

    So **a figure file is read one JSON object per line**, and this driver's is
    the one-line case of that -- not a different format under the same name. The
    extension stays `.ambient.json` because the name is the one #256 gave it and
    #264 asked for (`ingress-open.jsonl` -> `ingress-open.ambient.json`), and the
    documents that tell a runner to keep the file say how to read it; a
    `json.load` over a whole file is right only where the records truncate.
    """
    path = ambient_summary_path(out_path)
    with open(path, "a" if append else "w", encoding="utf-8") as out:
        out.write(json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def ambient_line(summary: Mapping[str, Any]) -> str:
    """The one line the run prints, so the figure is read without the file."""
    said = ["%s %+d" % (model, row["delta"]) if "delta" in row else "%s unread (%s)" % (model, row["unread"])
            for model, row in summary["models"].items()]
    return "%s over %d navigation(s)" % (", ".join(said), summary["navigations"])


def _ambient_navigations(driver) -> int:
    """How many navigations this driver has made (`SurfaceDriver._goto`).

    Read before and after like the row counts, and for the same reason: what the
    figure is per is the page views *inside* the window, and only the driver
    knows how many it made. Counting the loop instead would count a cart target
    once when it opened the product page and the cart page too -- both of which
    are tracked website pages, so both write the rows being counted.
    """
    return int(getattr(driver, "navigations", 0))


def _ambient_reading(driver) -> AmbientReading:
    """A reading that never raises -- the accounting may not break the run.

    `SurfaceDriver.ambient_reading` already answers a reason per model rather
    than raising, so this is the bound for a driver that does not: the figure is
    worth a run and not the other way round.
    """
    try:
        return driver.ambient_reading()
    except Exception as error:  # noqa: BLE001 -- the reason belongs in the record, not in a traceback
        return AmbientReading.none(sanitize_diagnostic(str(error)))


@contextlib.contextmanager
def ambient_accounting(driver, run: RunInfo, surface: Surface | str, out_path: str | None, *,
                       command: str, append: bool = False,
                       navigation_basis: str = AMBIENT_BASIS_GOTO):
    """Count the ambient rows around a run's navigations and write the summary.

    The reading before is taken as early as a reading can be: it goes over the
    session's own RPC, so the login has to have happened, and a row the login
    left is therefore outside the window the summary reports -- which is what its
    note says. The reading after is taken on the way out rather than at the end
    of the loop, so a run that failed still accounts for what it left, which is
    when the figure is worth the most.

    The accounting may not replace the run's own failure: a summary that cannot
    be read or written says so on stderr and lets the exception through, because
    an operator debugging a dead run must see why it died and not why its
    accounting did. On a run that otherwise passed it is raised instead -- an
    accounting that failed quietly is the thing #256 exists to stop.

    Any summary of an earlier run is removed first, the way `out_path` is
    truncated before the first visit. A figure is written at the end, so without
    that a run whose summary could not be written would leave the last run's
    numbers sitting beside this run's records under a different `run_id`. On an
    `append` driver there is nothing to clear for the same reason it appends:
    the earlier lines are earlier invocations' figures and not this one's.

    `out_path` may be `None`, for a subcommand that writes no records -- the peer
    snapshot's `probe`. There is then nothing to sit beside, so the figure is
    printed and not written; a driver that only prints it still read it, which is
    the distinction #256 draws between a zero that is read and one that is
    assumed.
    """
    if out_path is not None and not append:
        clear_ambient_summary(out_path)
    before, navigated = _ambient_reading(driver), _ambient_navigations(driver)
    ran = False
    try:
        yield
        ran = True
    finally:
        try:
            summary = ambient_summary(run, surface, command=command,
                                      navigations=_ambient_navigations(driver) - navigated,
                                      before=before, after=_ambient_reading(driver),
                                      navigation_basis=navigation_basis)
            written = ("not written: this subcommand writes no records" if out_path is None
                       else write_ambient_summary(out_path, summary, append=append))
            print("ambient rows: %s; %s" % (ambient_line(summary), written), file=sys.stderr)
        except Exception as error:  # noqa: BLE001 -- said either way, raised only when it is the only failure
            print("ambient accounting failed (%s)" % sanitize_diagnostic(str(error)), file=sys.stderr)
            if ran:
                # The run itself passed, so this is the run's only failure and
                # swallowing it would leave a figure nobody wrote and nobody
                # missed -- which is the thing #256 exists to stop. When the run
                # was already failing, that failure is the one the operator needs.
                raise


def validated_count(model: str, count: Any) -> int:
    """`count` as the integer a `search_count` answered, or the reason it is not.

    One place, because the trap is one line wide and reachable from every caller:
    `True` is an `int` in Python and would pass as a count of one, so a method
    that answered a boolean -- which is what a controller that refused answers --
    would be recorded as "one row". `SurfaceDriver.count_rows` and the
    hand-driven drivers' `SessionAmbientDriver` both read their count through
    here rather than each writing the test.
    """
    if not isinstance(count, int) or isinstance(count, bool):
        raise RuntimeError("%s.search_count answered no count: %r" % (model, count))
    return count


class NavigationCount:
    """Every document GET one browser context made under a base URL.

    The ambient figure's denominator, for a driver that does not navigate through
    one call the way `SurfaceDriver._goto` does. Three of this repository's Live
    drivers do not: the hand checks' `editbtn` navigates by clicking a link, the
    markup driver drives the website editor, whose preview iframe fetches
    documents on its own account, and the peer snapshot opens a form on two
    sessions. A counter at the call sites would have to be written beside every
    one of them and would still miss both of those -- a click and an iframe are
    not calls this code makes.

    So it counts what actually went over the wire. `resource_type == "document"`
    is Playwright's own name for a navigation request, main frame or sub-frame,
    which is exactly the GET that writes the rows being counted: serving a
    tracked page upserts the visitor and inserts the track row (ADR 0012,
    postscript 2026-10-01). The base filter keeps the Home Assistant frontend's
    own documents out -- the panel page is on the HA origin but not under the
    Ingress prefix -- and it is read per request rather than at construction,
    because `IngressSide.base` does not exist until the iframe has been found.

    What it over-counts, and the summary's `navigation_basis` says so: a redirect
    hop is a document GET whose response renders no page, and whether a request
    is a hop is not known when it is made.
    """

    def __init__(self, context, base_of) -> None:
        self.navigations = 0
        self._base_of = base_of if callable(base_of) else (lambda: base_of)
        context.on("request", self._seen)

    def _seen(self, request) -> None:
        # A listener that raised would raise inside Playwright's dispatch, on
        # whatever call happened to be waiting, and an accounting failure may not
        # become the run's failure (`ambient_accounting`).
        with contextlib.suppress(Exception):
            base = self._base_of()
            if request.resource_type == "document" and base and request.url.startswith(base):
                self.navigations += 1


class SessionAmbientDriver:
    """The ambient figure read off sessions that are not a `SurfaceDriver`.

    `ambient_accounting` asks its driver two questions -- how many navigations
    are inside the window, and the counts now -- and `SurfaceDriver` answers both.
    The hand-driven Live drivers hold a `Side` instead
    (`e2e_parity_shared_layers_live.py`), or hold a `SurfaceDriver` whose
    navigations do not go through `_goto`. This answers the same two questions off
    either, so the figure is read the one way for every driver rather than three
    ways.

    The counts go over a session's own RPC and never over `ssh`, which is #256's
    point: a figure the run itself read is the run's own evidence, and one read on
    the host afterwards is a different measurement that cannot be a delta. One
    session is enough, because the two models are database-wide -- so the first
    session named is the one that counts, and `surface` says which it was.

    The navigation denominator is every session's, summed. A delta over a
    database-wide count has no way to attribute a row to one of two sessions that
    were both open, so a denominator covering only one of them would be a
    fraction of the figure's own window.
    """

    def __init__(self, *sessions, reading=None, mask=None) -> None:
        if not sessions:
            raise ValueError("the ambient figure needs at least one session")
        self.sessions = sessions
        self.counters = [NavigationCount(session.context, lambda session=session: session.base)
                         for session in sessions]
        self._reading = reading
        self._mask = mask or (lambda value: value)

    @property
    def navigations(self) -> int:
        return sum(counter.navigations for counter in self.counters)

    def count_rows(self, model: str) -> int:
        """`search_count` with an empty domain, over the first session's own RPC.

        `READ_ONLY_POLICY` is the seam here too (`Operation.COUNT_ROWS`): a
        request a driver makes belongs in the enum rather than beside it, and this
        request is the same one `SurfaceDriver.count_rows` makes -- a domain goes
        in and an integer comes out, with no record to name and no field to read.
        """
        READ_ONLY_POLICY.require(Operation.COUNT_ROWS)
        return validated_count(model, self.sessions[0].rpc(model, "search_count", [[]]))

    def ambient_reading(self) -> AmbientReading:
        """A count of each `AMBIENT_MODELS` model now, and the reason for any missing.

        One reason per model, not one per reading, for `SurfaceDriver.ambient_reading`'s
        reason: a database without `website` has neither model and reports two
        reasons, while a session that lost one answer still reports the count it
        got. A driver that already has a reading of its own (the hand checks hold a
        `SurfaceDriver`) hands it in, so there is one implementation of the count
        and not two.
        """
        if self._reading is not None:
            return self._reading()
        counts: dict[str, int] = {}
        unread: dict[str, str] = {}
        for model in AMBIENT_MODELS:
            try:
                counts[model] = self.count_rows(model)
            except Exception as error:  # noqa: BLE001 -- why a count is missing is the record's answer
                # Masked: the reason goes into a record a pull request quotes, and
                # a raw Playwright message carries the host and the Ingress token.
                unread[model] = str(self._mask((str(error).splitlines() or [""])[0]))
        return AmbientReading(counts=counts, unread=unread)


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


# The website's navbar cart badge: the number of items in the session's cart,
# and the sale order it belongs to (`data-order-id`), in one round-trip -- the
# two must come from the same DOM state, or a count and an id read either side
# of an update would pair a size with an order it never had.
# null, not 0: an unreadable badge is not an empty cart, and a write this run
# made must never be denied by a reading that failed. `''` is unreadable too:
# Number('') is 0, which is an answer the badge did not give.
_CART_STATE_JS = """() => {
  const node = document.querySelector('.my_cart_quantity');
  if (!node) return {count: null, order: null};
  const text = (node.textContent || '').trim();
  const value = Number(text);
  return {count: text && Number.isFinite(value) ? value : null,
          order: node.getAttribute('data-order-id')};
}"""
_CART_GREW_JS = """(before) => {
  const node = document.querySelector('.my_cart_quantity');
  return !!node && Number((node.textContent || '').trim()) > before;
}"""


# What answers an add: the product page's own form posts to `/shop/cart/update`
# (as does the cart page's quantity editor, at `/shop/cart/update_json`), and a
# product with optional or combo products adds through the configurator instead.
_CART_UPDATE_ROUTES = ("/shop/cart/update", "/website_sale/product_configurator/update_cart")


def _is_cart_update(response) -> bool:
    """Whether a response is the cart answering an add.

    By path, not substring: `/shop/cart/update` must not match the quantity
    editor's `/shop/cart/update_json`, which answers without adding anything --
    a wait it satisfied would read the cart before the add committed, and the
    retry would then double the line. An error answer is no add either: a 500
    did not commit, so the wait keeps waiting and the cart reading says what
    really happened.
    """
    if not response.ok:
        return False
    path = urlsplit(response.url).path
    return any(path == route or path.endswith(route) for route in _CART_UPDATE_ROUTES)


def _reached(url: str | None, route: str) -> bool:
    """Whether a navigation's final URL is the route it was aimed at.

    The path alone, unquoted, query dropped and an ingress prefix in front
    tolerated: `/web/login?redirect=<route>` names the route in its query and
    is the login page, not the product -- a substring test over the whole URL
    called that arrival.
    """
    path = unquote(urlsplit(url or "").path).rstrip("/")
    aimed = unquote(urlsplit(route).path).rstrip("/")
    return bool(aimed) and (path == aimed or path.endswith(aimed))


# Every theme the parity plan covers renders one of these.
_ADD_TO_CART = "#add_to_cart, a[data-action='add_to_cart'], button:has-text('Add to cart')"
# How long a click that may still be in flight has to show up before the retry
# clicks again: an add that lands after the reading that called the cart empty
# would otherwise be doubled by the second click.
_CART_SETTLE_MS = 2000
# How long the badge has to rise after a click whose POST never answered: the
# response wait has already given the add 30s, so this covers only a theme
# that adds by a route `_is_cart_update` does not name -- its XHR had those
# 30s too -- without paying the full bound twice for a dead element.
_CART_BADGE_GRACE_MS = 5000
# How many times the add-to-cart button is clicked before the step gives up.
# Two: one click, and one more for the handler race no wait can see. A third
# would start guessing at a shop that is simply broken, and a broken shop is
# evidence the run should record rather than keep clicking at.
_CART_CLICK_ATTEMPTS = 2


def is_configuration_error(error: BaseException) -> bool:
    """Whether a failure is a mistake in the target file or the environment.

    Those are not evidence about the product: they fail both surfaces alike,
    and a record of one would read as a `GAP` on a screen nobody has judged.
    The run stops on them instead.
    """
    return str(error).startswith("crawler configuration:")


def _screen_of(page, *, expect_model: str | None) -> dict[str, Any]:
    """What the screen says it is; waits for an answer when one is expected.

    A target that names a model is judged on it strictly -- "the web client
    has not said yet" is not an answer -- so the reading is retried for as
    long as a screen takes to mount, the way `_shows` waits for a selector.
    """
    screen = page.evaluate(_SCREEN_JS) or {}
    if expect_model is None:
        return screen
    deadline = time.monotonic() + 15
    while screen.get("model") is None and time.monotonic() < deadline:
        page.wait_for_timeout(500)
        screen = page.evaluate(_SCREEN_JS) or {}
    return screen


def _shows(page, selector: str, *, timeout: int = 15000) -> bool:
    """Whether the screen shows `selector`, giving it the time a screen takes.

    A single reading answers at once, and the settle around it is best effort,
    so a screen still mounting would be recorded as the wrong screen: this
    keeps looking until the deadline. Any match counts, not the first in the
    DOM -- Odoo ships responsive pairs of the same block, one of which is
    always hidden, and judging on whichever came first in the document would
    fail both surfaces alike. A selector that cannot be read at all never gets
    here: `check_selectors` refuses it before the first target.
    """
    deadline = time.monotonic() + timeout / 1000
    while True:
        matches = page.locator(selector)
        if any(matches.nth(index).is_visible() for index in range(matches.count())):
            return True
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(250)


class SurfaceDriver:
    """Logs in on one surface and opens planned visits, reading only."""

    # What `ensure_cart` read before it touched anything, for
    # `_cart_after_failure` to tell a cart this run created from one it found:
    # the order the cart page named, and whether there was a reading at all.
    # Class attributes, so a driver that has opened no cart still answers.
    cart_before: str | None = None
    cart_before_read: bool = False
    # Every navigation this driver has made, for the ambient-row figure to be
    # read per page view. A class attribute like the two above, so a driver that
    # has navigated nowhere still answers.
    navigations: int = 0

    def __init__(
        self, surface: Surface, browser, *, ignore_https_errors: bool, viewport: tuple[int, int] = (1920, 1080),
    ) -> None:
        self.surface = surface
        self.ingress: IngressSession | None = None
        # The database the session ends up on; read at login, not assumed.
        self.database: str | None = None
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

    def _goto(self, page, route: str, **kwargs) -> None:
        """Navigate `page` to a route on this surface, and count it.

        The one place this driver navigates, because the ambient-row figure
        (`ambient_accounting`) is read *per navigation* and a `page.goto` written
        beside this one would leave that denominator short while looking right.
        What counts is the GET being made, not its landing: a navigation that
        timed out still asked, and asking is what writes.

        The login is counted here like any other, and falls outside the figure
        for a different reason -- the window opens at the first reading, which
        cannot be taken until a session exists.
        """
        self.navigations += 1
        page.goto(self.base + route, **kwargs)

    def log_in(self) -> None:
        page = self.context.new_page()
        try:
            db = os.environ.get("ODOO_DB")
            self._goto(page, "/web/login" + ("?db=" + db if db else ""),
                       wait_until="domcontentloaded", timeout=120000)
            if page.locator('input[name="login"]').count():
                page.locator('input[name="login"]').fill(self.login)
                page.locator('input[name="password"]').fill(self.password)
                # Enter submits the login form itself; with `website` installed the
                # page header has a search form whose submit button comes first.
                page.locator('input[name="password"]').press("Enter")
            page.locator(".o_main_navbar").wait_for(timeout=60000)
            self.database = page.evaluate("() => (odoo.info && odoo.info.db) || null")
        finally:
            page.close()

    def web_menus(self) -> Mapping[str, Any]:
        READ_ONLY_POLICY.require(Operation.READ_MENU)
        response = self.context.request.get(self.base + "/web/webclient/load_menus/%d" % time.time())
        if response.status != 200:
            raise RuntimeError("load_menus answered HTTP %d" % response.status)
        return response.json()

    def count_rows(self, model: str) -> int:
        """`search_count` with an empty domain, over the session's own RPC.

        The one RPC this driver makes, and it is a read: a domain goes in and an
        integer comes out, so there is no record to name, no field to read and
        nothing a mutation could ride in on. `READ_ONLY_POLICY` is still the seam
        it passes through (`Operation.COUNT_ROWS`), because a request this driver
        makes belongs in the enum rather than beside it, and the RPC the shared
        layers' Live harness already uses is the shape it is read off
        (`e2e_parity_shared_layers_live.py`).

        Taking the reading does not add to what it reads. The ambient write this
        counts is gated on the `track` flag of the template a *response*
        rendered (ADR 0012, postscript 2026-10-01), and a `call_kw` POST renders
        no template -- so the count is not a count of itself.
        """
        READ_ONLY_POLICY.require(Operation.COUNT_ROWS)
        response = self.context.request.post(
            self.base + "/web/dataset/call_kw/%s/search_count" % model,
            data={"jsonrpc": "2.0", "method": "call", "params": {
                "model": model, "method": "search_count", "args": [[]], "kwargs": {},
            }},
        )
        # The status before the body, the way `web_menus` reads it: a lapsed
        # session and a gateway that answered 502 both send HTML, and a JSON
        # parse error would record "Expecting value: line 1 column 1" where the
        # record owes the operator the status -- the per-model reason exists to
        # tell "the session died" from "the model is not installed".
        if response.status != 200:
            raise RuntimeError("%s.search_count answered HTTP %d" % (model, response.status))
        try:
            body = response.json()
        except Exception as error:  # noqa: BLE001 -- an answer that is not JSON is the reason
            raise RuntimeError("%s.search_count answered no JSON (%s)"
                               % (model, (str(error).splitlines() or [""])[0])) from None
        error = body.get("error") or {}
        if error:
            raise RuntimeError("%s.search_count failed: %s"
                               % (model, (error.get("data") or {}).get("message")
                                  or error.get("message") or "no message"))
        # A method that answered something other than a number did not answer
        # this one, and `True` would pass as a count of one: `validated_count` is
        # the one place that test is written, shared with `SessionAmbientDriver`.
        return validated_count(model, body.get("result"))

    def ambient_reading(self) -> AmbientReading:
        """A count of each `AMBIENT_MODELS` model now, and the reason for any missing.

        One failure per model, not one for the reading: a database without
        `website` has neither model and a run on it reports two reasons, while a
        session that lost one answer still reports the count it got. The reason
        is masked, because it goes into a record a pull request quotes and a raw
        Playwright message carries the host and the ingress token.

        The session is refreshed first and a refresh that fails is suppressed,
        the way `_reread_cart` suppresses it: a dead websocket is a reason for the
        count to be missing, which the reading already records, and not a reason
        for the run to stop.
        """
        if self.ingress:
            with contextlib.suppress(Exception):
                self.ingress.keep_alive()
        counts: dict[str, int] = {}
        unread: dict[str, str] = {}
        for model in AMBIENT_MODELS:
            try:
                counts[model] = self.count_rows(model)
            except Exception as error:  # noqa: BLE001 -- why a count is missing is the record's answer
                unread[model] = self.masker.text((str(error).splitlines() or [""])[0])
        return AmbientReading(counts=counts, unread=unread)

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
        return self._open(visit.route, backend=True, expect_action=visit.action_id)

    def open_screen(self, target: OpenTarget) -> SurfaceObservation:
        """Open one named screen, the way `observe` opens a planned menu action.

        A target whose route writes on a plain GET is refused off
        `WRITE_DATABASE`, the way `ensure_cart` refuses the declared cart write,
        and refused on every database when that write does not converge:
        `open_screens` checks the whole target list before the first screen -- the
        convergence half before the browser even launches -- so a misaimed run
        stops at once, and this is the check for every other caller of this
        driver.

        One that is allowed through writes while its screen renders, so the
        observation carries what that left: `_draft_order_after_visit` reads
        the session's draft order after the navigation and the row joins
        whatever `ensure_cart` put there. A target under no `GET_WRITING_ROUTES`
        prefix takes no such reading -- the reading is a `/shop/cart`
        navigation, which writes -- and records exactly what it always did.
        """
        READ_ONLY_POLICY.require(Operation.NAVIGATE)
        require_write_database((target,), self.database)
        writes: tuple[Mapping[str, Any], ...] = ()
        if target.cart:
            try:
                writes = (self.ensure_cart(target.cart),)
            except Exception as error:  # noqa: BLE001 -- a failed cart is evidence too, not a crash
                if is_configuration_error(error):
                    # Masked at this boundary too, not only where each message
                    # is raised: one callsite forgetting `masker.text` must
                    # not be what puts the host in the run log.
                    raise RuntimeError(self.masker.text(str(error))) from None
                # Judging the screen now would judge whatever the cart happened
                # to hold, so the target is unavailable on this surface and the
                # record says why. The click may have landed before whatever
                # failed, so the cart is read once more: a line this run created
                # is named even then, and the other surface will reuse it. An
                # order the run created and never filled counts as one too, and
                # when there is no record the `unread` half says why not.
                cart, unread = self._cart_after_failure()
                return SurfaceObservation(
                    available=False,
                    result=self.masker.text("cart not filled (%s): %s%s"
                                            % (classify_failure(error).value, (str(error).splitlines() or [""])[0],
                                               "; " + unread if unread else "")),
                    signals={name: 0 for name in SIGNALS}, route=None, model=None, view=None,
                    writes=(cart,) if cart else (),
                )
        try:
            observation = self._open(
                target.route, backend=target.backend,
                expect_model=target.expect_model, expect_selector=target.expect_selector,
            )
        except Exception as error:  # noqa: BLE001 -- only a configuration error escapes `_open`
            if not is_configuration_error(error):
                raise
            detail = ""
            if writes:
                # This stops the run before `open_screens` writes a record, so
                # the cart line `ensure_cart` just committed would go
                # unaccounted -- the message carries it, the way the in-loop
                # handler in `ensure_cart` carries its own.
                write = writes[0]
                detail = ("; no record will name the cart: %s:%s holding %s item(s), %s"
                          % (write["model"], write["id"], write["items"], write["how"]))
            # No draft-order reading is taken on this path: a configuration
            # error from `_open` can be the ingress session failing *before*
            # the navigation, and the message cannot say which, so a reading
            # taken here would credit a GET that was never made.
            raise RuntimeError(self.masker.text(str(error) + detail)) from None
        prefix = get_writing_route(target.route)
        if prefix is not None:
            # The navigation above was a plain GET and Odoo wrote while it
            # rendered, so the record says what it left: the draft order, on
            # both surfaces, which is what lets `_judge` compare them. Only a
            # navigation that was actually made gets a reading -- a cart step
            # that failed returns above, before its target ever asked for the
            # route. A screen that loaded the wrong thing asked for it all the
            # same, so it gets its row like any other.
            left, unread = self._draft_order_after_visit(prefix)
            if left is not None:
                writes += (left,)
            else:
                # A reading that said nothing is not the silence this row
                # exists to end: it goes on the observation beside the screen
                # it was taken after, the way a failed cart step's does. It
                # leaves no row, so a reading that failed on one surface only
                # is a write difference at blocker severity -- which is the
                # honest verdict (the comparison the row exists for cannot be
                # made), and the `result` beside it in the joined record says
                # it was the reading and not the database that differed.
                observation = replace(observation, result="%s; %s" % (observation.result, unread))
        return replace(observation, writes=writes)

    def ensure_cart(self, product_route: str) -> dict[str, Any]:
        """Make sure the logged-in user's cart holds something, so a checkout opens.

        An empty cart gets one product; a cart that already holds something is
        left exactly as it is. Both surfaces share the user, so the second run
        must not add a second line: the two runs would then judge two carts of
        different sizes, and a difference in the page's own content would read
        as a difference between the surfaces.

        Refuses to write unless the session is on `WRITE_DATABASE`, the bound
        on this write, whoever the caller is.

        The line it adds carries no run marker, unlike the fixtures the Live
        scripts create: the cart is the logged-in user's own draft order and
        both surfaces have to judge the same one, so naming it after the run
        would edit the very screen under judgement. The record names the
        order and its size instead, and it carries the run id.

        The click is bounded but not quick: with every wait in it timing out,
        one cart target costs about twelve minutes -- two passes of a `load`
        navigation, the button waits, the badge wait and the cart readings,
        including the ones that confirm a two-click cart settled -- against
        about four before the retry existed. A run that sizes a timeout around
        this step should size it for that, and the loop refreshes the ingress
        session as it goes so the window does not lapse inside it.

        This writes, and is deliberately not an `Operation`:
        `NON_MUTATING_OPERATIONS` is every member of that enum, so a WRITE
        member added there would be *permitted* by `READ_ONLY_POLICY` rather
        than refused, and the read-only guarantee would quietly weaken. The
        write lives here instead, named, bounded by the check above, and
        reported in the record.
        """
        if self.database != WRITE_DATABASE:
            # `open_screens` checks this before the first target so a misaimed
            # run stops at once; this is the check for every other caller of
            # this driver. Both read the answer the session gave at login,
            # which is the only answer this driver has.
            raise RuntimeError("crawler configuration: the cart write is allowed on %s only; "
                               "the session's database is %r" % (WRITE_DATABASE, self.database))
        # Reset before the page, so a `new_page` that fails cannot leave the
        # previous target's reading for `_cart_after_failure` to compare with.
        self.cart_before, self.cart_before_read = None, False
        page = self.context.new_page()
        try:
            # Both readings are taken on the cart page: the badge on another
            # page can be a step behind, and a low reading there would let an
            # add that never landed pass for one that did.
            before, order = self._cart(page)
            if before is None:
                raise RuntimeError("the cart page did not show how many items the cart holds")
            # An order named here is one the run found, not one it made, and
            # that is what tells a created cart from a reused one if this step
            # fails further down.
            self.cart_before, self.cart_before_read = order, True
            if before:
                return {"model": "sale.order", "id": order, "items": before,
                        "how": "the cart already held %d item(s); nothing was added" % before}
            clicks, filled_first = 0, False
            # Bound where a two-click cart is read until it settles, further
            # down; the `elif clicks > 1` branch of `how` is the only reader
            # and cannot run before that. Initialised here so the names exist
            # on every path, not because any path reads these values.
            moved, unread, confirmed = False, False, False
            for attempt in range(1, _CART_CLICK_ATTEMPTS + 1):
                if self.ingress:
                    # Minutes of waits live in this loop, against the
                    # Supervisor's fifteen-minute ingress window (U-B6): a
                    # session that lapses here makes every request after it read
                    # as a product GAP. A refresh that fails is the harness
                    # losing its session, so it is raised as one -- `open_screen`
                    # swallows anything else into `cart not filled`, which would
                    # file a dead websocket as a blocker GAP on a screen nobody
                    # judged, and `_open` stops the run on the same fault.
                    try:
                        self.ingress.keep_alive()
                    except Exception as error:  # noqa: BLE001 -- turned into the harness error it is
                        # This stops the run, so there will be no record to put
                        # a cart in: a line the first click already committed
                        # would go unaccounted for. The message carries it, on
                        # the one database ADR 0012 allows the write on.
                        left, why = self._cart_after_failure() if clicks else (None, None)
                        if left:
                            # Its own `how` says whether the run made this cart
                            # or found it; claiming either here would be the
                            # guess the rest of the step refuses to make.
                            detail = ("; no record will name the cart: %s:%s holding %s item(s), %s"
                                      % (left["model"], left["id"], left["items"], left["how"]))
                        elif clicks:
                            detail = ("; %d click(s) had been sent and the cart could not be read afterwards"
                                      " (%s), so what it holds is unaccounted for" % (clicks, why))
                        else:
                            detail = ""
                        # This one masks itself -- a raw websocket message
                        # carries the host and the ingress token every other
                        # message in this driver hides -- and `open_screen`
                        # masks configuration errors once more at its
                        # boundary, for any callsite this discipline misses.
                        raise RuntimeError("crawler configuration: the ingress session could not be refreshed "
                                           "during the cart step (%s)"
                                           % self.masker.text((str(error).splitlines() or [""])[0] + detail)
                                           ) from None
                if attempt > 1:
                    # The add may still have been in flight when the reading
                    # above called the cart empty, and clicking again would add
                    # its quantity twice -- `/shop/cart/update` increments the
                    # line it finds, so the one line ends at qty 2: a cart
                    # bigger than the plan meant on the judged screen, and a
                    # size the other surface will not match. So a cart that
                    # filled late gets its moment and one more reading, and
                    # ends the step here instead of growing again.
                    page.wait_for_timeout(_CART_SETTLE_MS)
                    after, read_order = self._cart(page)
                    # A reading that lost the badge's order id for a moment
                    # must not erase the one an earlier reading named: a
                    # success row with `id: None` against the other surface's
                    # real id is a blocker GAP on two identical screens.
                    order = read_order or order
                    if after is None:
                        # Not empty -- unreadable, the same answer the reading
                        # after a click gives, and no reason to click again.
                        raise RuntimeError("the cart page did not show its item count at %s after %d click(s), "
                                           "so the step did not click again"
                                           % (self.masker.text(product_route), clicks))
                    if after:
                        filled_first = True
                        break
                clicked = self._click_add_to_cart(page, product_route)
                if clicked:
                    clicks += 1
                    if clicked == "unanswered":
                        try:
                            # No POST `_is_cart_update` names answered this
                            # click: a theme that adds by another route, or the
                            # dead element the retry exists for. The navbar
                            # badge is the signal left -- some themes navigate
                            # to the cart first, and it is on that page too --
                            # and it gets a short grace, not the full bound the
                            # response wait already spent on the same click.
                            # An answered click needs neither: its own POST
                            # answering is what says the add committed.
                            page.wait_for_function(_CART_GREW_JS, arg=0, timeout=_CART_BADGE_GRACE_MS)
                        except Exception:  # noqa: BLE001 -- the cart page below is the real check
                            pass
                    if clicks > 1:
                        # A badge that rose cannot say which of the two clicks
                        # raised it, so the second click gets the same grace the
                        # reading before it got and the cart is read after that.
                        # What that reading says is what the record says: a cart
                        # that took both clicks is reported at the quantity both
                        # left it, not the one the wait happened to see.
                        page.wait_for_timeout(_CART_SETTLE_MS)
                else:
                    # The product page came up with a cart already holding
                    # something, so there was nothing to click: the add landed
                    # while that navigation was loading, which is the same late
                    # add the grace above catches and the same doubling.
                    filled_first = True
                after, read_order = self._cart(page)
                order = read_order or order
                if after is None:
                    # The page could not say, which is not the same as empty and
                    # is not something another click would answer. The count is
                    # in the message: what the run clicked is what it has to
                    # account for, whatever the page would not say.
                    raise RuntimeError("the cart page did not show its item count at %s after %d click(s)"
                                       % (self.masker.text(product_route), clicks))
                if after and clicks > 1:
                    moved, unread, confirmed = False, False, False
                    # More than one click means the record has to name the
                    # quantity the cart settled at. A reading taken while the
                    # second update was still committing names the smaller one;
                    # the other surface then records the larger and `_judge`
                    # calls two identical screens a blocker GAP. So the cart is
                    # read until two readings in a row agree, three at most.
                    for _ in range(2):
                        page.wait_for_timeout(_CART_SETTLE_MS)
                        again, again_order = self._cart(page)
                        if again is None:
                            # Not a cart that moved -- a page that stopped
                            # saying, which is the distinction the whole step
                            # turns on. Another reading may still settle it, and
                            # a cart already seen moving stays the bigger news.
                            unread = True
                            continue
                        if again == after:
                            confirmed = True
                            break
                        # `or order`: a confirming reading that momentarily
                        # lost the order id must not overwrite the one already
                        # named -- see the readings above.
                        after, order, moved = again, again_order or order, True
                if after:
                    break
                # The badge that said otherwise was wrong, or what it saw is
                # gone; either way this is the empty cart the retry is for.
                filled_first = False
                if attempt == _CART_CLICK_ATTEMPTS:
                    # Without this the run would judge a checkout the cart never
                    # made reachable, or record a write that never happened.
                    if not clicks:
                        # Every pass found the product page's badge holding
                        # something the cart page then said was not there. The
                        # step cannot add to a cart it cannot read the size of,
                        # and it never clicked, so it does not say it added.
                        raise RuntimeError("the cart page reads empty and the product page for %s says otherwise, "
                                           "so nothing was clicked" % self.masker.text(product_route))
                    raise RuntimeError("the cart is still empty after adding %s in %d click(s)"
                                       % (self.masker.text(product_route), clicks))
                # An empty cart after a click Playwright delivered to an enabled
                # button is the handler race `_click_add_to_cart` cannot see:
                # the element was there, its listener was not. The next pass
                # re-opens the product page and clicks again, and that is the
                # whole retry -- the bound above is what keeps it one.
            if not clicks:
                # Nothing was clicked, so nothing here added anything: the cart
                # filled between the reading that called it empty and the page
                # that would have been clicked.
                how = ("the cart held %d item(s) by the time the product page for %s was up; nothing was added"
                       % (after, self.masker.text(product_route)))
            else:
                how = "added the product on %s to the cart (0 -> %d items)" % (self.masker.text(product_route), after)
                if filled_first:
                    how += ("; the click landed after the reading that called the cart empty,"
                            " so it was not clicked again")
                elif clicks > 1:
                    how += "; the first %d click(s) read as lost, so it was clicked %d times" % (clicks - 1, clicks)
                    if after > 1:
                        how += (", and the cart holds more than the one item the step meant to add"
                                " -- a product that adds several, or a click that was not lost after all")
                    if not confirmed and moved:
                        # Read as "this size is the last reading, not a settled
                        # one": an update still committing lands after it, and
                        # the other surface reading the larger cart is then a
                        # difference in the evidence and not in the screens.
                        how += "; the cart was still changing when the run left it"
                    elif not confirmed and unread:
                        how += ("; the cart page stopped saying how many items it holds,"
                                " so this size is the last reading that did")
            return {"model": "sale.order", "id": order, "items": after, "how": how}
        finally:
            page.close()

    def _click_add_to_cart(self, page, product_route: str) -> str | bool:
        """Open the product page and click add-to-cart once it can be clicked.

        False when it found nothing to click for: the badge on the page this
        navigation just rendered already shows a cart with something in it, so
        an add landed while it was loading and clicking would add the quantity
        twice. A badge on a page other than the cart can be a step behind, so a
        low reading proves nothing and is not trusted -- a reading above zero is
        the cart saying it is not empty, and that is all this asks of it.

        A click comes back as `"answered"` -- its POST to a cart route drew an
        answer, which is what says the add committed -- or `"unanswered"`: no
        such answer inside the wait's bound, so the caller still has the badge
        and the cart reading to consult. Both are true, the way the old bool
        was; only False means nothing was clicked.

        `domcontentloaded` is when the button exists, not when it works: the
        handler is attached by the website bundle, which is still loading then,
        so a click at that moment can land on a dead element and the cart never
        grows. This navigation waits for `load` instead -- every bundle script
        fetched and run, which is the closest thing to "the handlers are on"
        Playwright can wait for. `networkidle` would wait for more than that and
        for things that never settle; the button's own state is the rest.

        Being visible is attached and laid out where a click reaches it. Being
        enabled is worth asking of the `button` some themes render; on the
        `<a class="a-submit">` Odoo's own template renders there is nothing to
        disable and Playwright always answers yes. Neither says the listener is
        attached, which nothing can, and that is why the caller clicks again on
        a cart that stayed empty rather than failing the run on the first miss.
        """
        try:
            self._goto(page, product_route, wait_until="load", timeout=60000)
        except Exception:  # noqa: BLE001 -- re-raised below unless the page arrived
            # One sub-resource that never finishes would otherwise cost the whole
            # target a blocker GAP, and the page is up: its bundle has very
            # likely run, and the click's own retry is the guard behind it. So
            # the step goes on with the page it has -- navigating again would
            # throw that away and land exactly where `load` was waiting to get
            # past. A navigation that never arrived is a real failure, and so
            # is one that arrived somewhere else: a login page naming the
            # product in its `redirect=` is the session lapsing, not the
            # product page, and polling its DOM for an add-to-cart button
            # would report the wrong fault. `_reached` reads the path only.
            if not _reached(page.url, product_route):
                raise
        if ((page.evaluate(_CART_STATE_JS) or {}).get("count") or 0) > 0:
            return False
        button = page.locator(_ADD_TO_CART).first
        # A button that is not there 30s after `load` is a shop the run should
        # report on, not wait for -- 30s is what a bare `click()` would have
        # given it to appear, and nothing retries a step this aborts: only an
        # empty cart is clicked at again. The enabled poll below keeps the
        # same bound, for a themed `button[disabled]` waiting on its own
        # combination XHR -- that takes seconds, not the whole of it.
        button.wait_for(state="visible", timeout=30000)
        deadline = time.monotonic() + 30
        last_error: Exception | None = None
        while True:
            # Checked first, and each reading is bounded by what is left of
            # the deadline: a reading that kept raising for its full 5s would
            # otherwise overshoot the bound by up to one reading.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                detail = ""
                if last_error is not None:
                    detail = (" (the last reading said: %s)"
                              % self.masker.text((str(last_error).splitlines() or [""])[0]))
                raise RuntimeError("the add-to-cart button on %s never became enabled%s"
                                   % (self.masker.text(product_route), detail))
            try:
                # The reading carries its own timeout: Playwright's default is
                # 30s, and a button that stopped resolving would report a raw
                # Playwright timeout instead of what happened here.
                if button.is_enabled(timeout=min(5000, max(100, int(remaining * 1000)))):
                    break
            except Exception as error:  # noqa: BLE001 -- a button detached mid-hydration; bounded above
                # Not the button answering "disabled", so the poll goes on --
                # unless the page itself is gone, which no amount of polling
                # answers and which the run should name as what it is.
                if page.is_closed():
                    raise
                last_error = error
            page.wait_for_timeout(250)
        clicked = False
        answered = False
        try:
            # The badge rising says some add landed, not that this click's did:
            # on a retry the first click's late add satisfies that wait at once
            # and the second add then has no wait of its own. This click's own
            # POST answering is what says its add committed before the cart is
            # read. A click that draws no such answer -- a theme that adds by
            # another route, or the dead element this retry exists for -- is
            # reported as such, and the caller falls back to the badge and the
            # cart reading in `ensure_cart`.
            with page.expect_response(_is_cart_update, timeout=30000):
                button.click()
                clicked = True
            answered = True
        except Exception:  # noqa: BLE001 -- see above; a click that failed is re-raised
            if not clicked:
                raise
        return "answered" if answered else "unanswered"

    def check_selectors(self, targets: Iterable[OpenTarget]) -> None:
        """Refuse an `expect_selector` Playwright cannot read, before judging.

        It is a mistake in the target file, like the ones `parse_targets`
        refuses; without a browser it cannot be caught there. Left to the run
        it would fail every surface alike and read as a `GAP` on screens that
        are fine.
        """
        page = self.context.new_page()
        try:
            for target in targets:
                if not target.expect_selector:
                    continue
                try:
                    page.locator(target.expect_selector).count()
                except Exception as error:  # noqa: BLE001 -- turned into the harness error it is
                    raise ValueError("crawler configuration: expect_selector %r cannot be read (%s)"
                                     % (target.expect_selector, (str(error).splitlines() or [""])[0])) from None
        finally:
            page.close()

    def _cart_after_failure(self) -> tuple[dict[str, Any] | None, str | None]:
        """What the cart holds after a cart step that failed part-way, and why not.

        An empty cart and an unreadable cart are not the same thing. A cart
        that reads empty and still names its order is a row the checkout will
        use, and ADR 0012 has it accounted for on this database like any other:
        it goes into `writes` with `items: 0`. Whether this run *created* it is
        a separate question, and the reading `ensure_cart` took before it
        clicked is the only thing that answers it -- an earlier run can leave
        an empty draft order behind, and the logged-in user's is revived rather
        than created on the way in, so `how` says which of the two this is
        rather than claiming a write that never happened.

        Only a cart nobody could read is no record at all -- then the record is
        None and the second half of the answer is the reason, which the caller
        puts on the observation beside the failure that brought us here.
        """
        items, order, unread = self._reread_cart()
        if unread is not None:
            return None, unread
        if not items:
            if not order:
                # Read, and empty, and naming no order: there is no row to
                # report, and nothing failed to be read either.
                return None, "the cart read empty and named no order, so this run created none"
            if order == self.cart_before:
                how = "the empty order the cart already held before the step; nothing was added"
            elif self.cart_before_read:
                how = "created empty by the failed cart step"
            else:
                how = ("empty after the failed cart step; the step got no reading from before it, "
                       "so whether this run created it is unknown")
            return {"model": "sale.order", "id": order, "items": 0, "how": how}, None
        return ({"model": "sale.order", "id": order, "items": items,
                 "how": "the cart holds %d item(s) after the cart step failed" % items}, None)

    def _draft_order_after_visit(self, prefix: str) -> tuple[dict[str, Any] | None, str | None]:
        """The draft order a target on a GET-writing route left behind, and why none.

        `open` navigates with `page.goto`, which is a GET and nothing more, and
        the routes on `GET_WRITING_ROUTES` write while they render it: the run
        mutates the database whether or not the target declared a `cart:`.
        `require_write_database` has always bounded that write and no record
        ever named it, so ADR 0012's "every mutation is accounted" held in the
        bound alone and `_judge` compared "none" with "none" on both surfaces --
        a cross-surface difference in what the GET wrote could not fire. This is
        the row that makes it fire: the session's draft order after the
        navigation, read the way `_cart_after_failure` reads it, so `diff_runs`
        and `_judge` take it as the write row it is and need no new format.

        It is a state reading and not a claim of authorship, which is what lets
        one reading answer for every aimable prefix. Most of them write on the
        cart itself (`/shop/checkout` persists a delivery method on it); the
        two that do not -- `/my/orders/`, whose write is an `access_token`, and
        `/website/lang`, whose write is on the order's lines -- still render a
        screen the draft order is behind, and the row says what the order held
        after the visit rather than what the route put there. The `how` names
        the prefix and quotes the write `GET_WRITING_ROUTES` records for it, so
        the record says which of the two kinds this row is.

        Not covered, and deliberately: what the page's own templates and
        JavaScript write, and any model but `sale.order` -- the `access_token`
        the quoted write names for `/my/orders/` included, which is why the row
        is a reading of the cart and not a reading of that token. `writes` says
        what the run set up and what the draft order held after it, not
        everything the database got.

        It costs one more navigation per such target -- the cart page, with the
        same minute's bound every other reading of it carries -- which a run
        sizing its timeout around a GET-writing target should count.

        Refuses to read unless the session is on `WRITE_DATABASE`: the reading
        opens `/shop/cart`, which is itself on `GET_WRITING_ROUTES`, so it is
        bounded where every other write in this driver is. `open_screen` has
        already refused such a target off that database through
        `require_write_database`, so nothing reaches this check by the ordinary
        path -- it is the bound for a caller that skipped it, the way
        `ensure_cart` keeps its own.
        """
        if self.database != WRITE_DATABASE:
            raise RuntimeError("crawler configuration: reading what a GET-writing target wrote opens the cart "
                               "page, which writes, and that is allowed on %s only; the session's database "
                               "is %r" % (WRITE_DATABASE, self.database))
        items, order, unread = self._reread_cart()
        if unread is not None:
            return None, unread
        if not order:
            # The badge renders "0" until the session has an order and
            # `_cart` reads that as no order: there is nothing this run can
            # name, and a row naming `sale.order:0` would claim a record that
            # does not exist. Both surfaces say the same thing by saying
            # nothing, which is the one case where silence is the reading.
            return None, ("the cart named no order after the visit to %s, so this run has no draft order "
                          "to report" % prefix)
        return {"model": "sale.order", "id": order, "items": items,
                "how": "the draft order the session held after the visit to %s, which %s"
                       % (prefix, GET_WRITING_ROUTES[prefix].write)}, None

    def _reread_cart(self) -> tuple[int | None, str | None, str | None]:
        """The cart read again on a page of its own: the count, the order, and why neither.

        The reading both after-the-fact readers take -- the one after a cart
        step that failed and the one after a visit to a GET-writing route -- so
        a cart page that will not answer reads the same way in both records.
        "Afterwards", in the reasons below, is after whichever of the two the
        caller just did. The reason is None exactly when there is a reading: a
        caller gets a count to report or a sentence saying why there is none.
        """
        page = None
        try:
            if self.ingress:
                # Best effort, and suppressed: this reading is the one thing
                # standing between a write the run made and a `writes` that
                # never names it, so a session that will not refresh must not
                # cost it. A page that then fails is what the reason is for.
                with contextlib.suppress(Exception):
                    self.ingress.keep_alive()
            page = self.context.new_page()
            items, order = self._cart(page)
        except Exception as error:  # noqa: BLE001 -- why the reading failed is the whole answer here
            return None, None, ("the cart could not be read afterwards (%s)"
                                % (str(error).splitlines() or [""])[0])
        finally:
            if page is not None:
                with contextlib.suppress(Exception):
                    page.close()
        if items is None:
            return None, None, "the cart page did not show afterwards how many items the cart holds"
        return items, order, None

    def _cart(self, page) -> tuple[int | None, str | None]:
        """The number of items in the session's cart, and the order it is.

        The count is None when the cart page did not show one.
        """
        self._goto(page, "/shop/cart", wait_until="domcontentloaded", timeout=60000)
        # website_sale puts both on every page's navbar badge; one reading, so
        # the count and the order id come from the same DOM state.
        state = page.evaluate(_CART_STATE_JS) or {}
        order = state.get("order")
        # An absent attribute, and the "0" the templates render before the
        # session has an order, are both "no order": a write row naming
        # `sale.order:0` would claim a record nobody created, and the empty-cart
        # reading in `_cart_after_failure` turns on telling those apart.
        return state.get("count"), (str(order) if order and str(order) != "0" else None)

    def _open(
        self, route: str, *, backend: bool, expect_action: str | None = None,
        expect_model: str | None = None, expect_selector: str | None = None,
    ) -> SurfaceObservation:
        if self.ingress:
            try:
                self.ingress.keep_alive()
            except Exception as error:  # noqa: BLE001 -- the harness losing its session, not the screen
                # The same fault `ensure_cart` names inside its loop: a dead
                # websocket here is not evidence about the screen, and a raw
                # Playwright message would carry the host and the ingress
                # token every other message in this driver hides.
                raise RuntimeError("crawler configuration: the ingress session could not be refreshed "
                                   "before opening the screen (%s)"
                                   % self.masker.text((str(error).splitlines() or [""])[0])) from None
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
        available, result, screen, literals, shown = True, "loaded", {}, [], True
        try:
            self._goto(page, route, wait_until="load", timeout=60000)
            if backend:
                # An action with target "new" (a wizard) opens in a dialog and
                # leaves the action manager empty.
                page.locator(".o_action_manager > *, .o_dialog .modal-content").first.wait_for(timeout=30000)
            # Before the settle and the readings below, not after them: what
            # the target expects is also what says the screen has finished
            # arriving, and a screen read half-built would be recorded that way
            # on the slower surface and judged a difference.
            shown = expect_selector is None or _shows(page, expect_selector)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:  # Odoo can keep a request open; the settle below still applies.
                pass
            page.wait_for_timeout(500)
            screen = _screen_of(page, expect_model=expect_model)
            literals = page.evaluate(_URL_LITERALS_JS)
            if shown and expect_selector is not None:
                # Still shown once the screen has settled: waiting for it above
                # is what says the screen has arrived, and this is what says it
                # stayed. A block that renders and is then hidden is not on the
                # screen the target asked to judge -- but a re-render that
                # detaches the node for a moment is not that, so this waits too,
                # for long enough to tell the two apart.
                shown = _shows(page, expect_selector, timeout=5000)
            loaded = screen.get("action")
            if expect_action is not None and loaded is not None and str(loaded) != expect_action:
                # U-C12: the menu's action must load, not a fallback such as Discuss.
                available = False
                result = "loaded action %s instead of %s" % (loaded, expect_action)
            elif expect_model is not None and screen.get("model") != expect_model:
                # Strictly, null included: `_screen_of` has already waited for
                # the web client to say, and a target that names a model is not
                # judged on a screen that never said what it is.
                available = False
                result = "loaded model %s instead of %s" % (screen.get("model"), expect_model)
            elif not shown:
                # Shown, not merely present: a block the page renders and then
                # hides is not the screen the target asked to judge.
                available = False
                result = "the screen does not show %s" % expect_selector
        except Exception as error:  # noqa: BLE001 -- every failure is evidence, not a crash
            if is_configuration_error(error):
                page.close()
                raise
            available = False
            result = "error (%s): %s" % (classify_failure(error).value, (str(error).splitlines() or [""])[0])
        signals = count_signals(
            page_errors=page_errors, console=console, failed_requests=failed, responses=responses,
            urls=urls, surface=self.surface, origin=self.origin, ingress_prefix=self.prefix,
        )
        final_route = self._route(page.url)
        page.close()
        violations = []
        for literal in literals:
            reason = url_literal_violation(literal, self.ha_origin)
            if reason:
                violations.append({"literal": self.masker.text(literal), "reason": reason})
        return SurfaceObservation(
            available=available, result=self.masker.text(result), signals=signals,
            route=final_route, model=screen.get("model"), view=screen.get("view"),
            url_literals=tuple(self.masker.text(literal) for literal in literals),
            url_violations=tuple(violations),
            http_5xx=sum(1 for status, _ in responses if status >= 500),
        )

    def close(self) -> None:
        self.context.close()
        if self.ingress:
            self.ingress.close()


def crawl(surface: Surface, apps: Sequence[str], out_path: str, *, viewport: str = "1920x1080") -> int:
    """Open every menu action of the chosen apps on one surface.

    `out_path` is opened once the login has passed, so a run that cannot even
    name its database leaves the evidence of the last one where it was.
    """
    from playwright.sync_api import sync_playwright

    size, client = parse_viewport(viewport)
    ignore_https = os.environ.get("IGNORE_HTTPS_ERRORS", "0") == "1"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        driver = None
        try:
            driver = SurfaceDriver(surface, browser, ignore_https_errors=ignore_https, viewport=size)
            driver.log_in()
            run = RunInfo(new_run_id(), os.environ.get("PARITY_TARGET", "local"),
                          session_database(driver.database), client)
            scope = scope_from_web_menus(driver.web_menus(), apps)
            visits = plan_visits(scope)
            signalled = 0
            with open(out_path, "w", encoding="utf-8") as out, \
                    ambient_accounting(driver, run, surface, out_path, command="crawl"):
                for skipped in scope.skipped:
                    identity = control_identity(skipped.menu_id, *skipped.action_ref.split(","))
                    record = skipped_record(run, surface, module=skipped.app, identity=identity, reason=skipped.reason)
                    out.write(json.dumps(driver.masker.value(record), ensure_ascii=False, sort_keys=True) + "\n")
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


def open_screens(surface: Surface, targets: Sequence[OpenTarget], out_path: str, *, viewport: str = "1920x1080") -> int:
    """Open each target on one surface and write the same records `crawl` writes.

    `out_path` is opened once the login and the write guard have passed, so a
    run that is refused leaves the evidence of the last one where it was.

    A target naming a GET-writing route whose write does not converge is refused
    here, before a browser launches: that refusal reads no database, so there is
    nothing to wait for the login to report (#225's rule, `GET_WRITING_ROUTES`).
    The database bound still needs the session's answer and is checked after it.
    """
    from playwright.sync_api import sync_playwright

    require_convergent_writes(targets)
    size, client = parse_viewport(viewport)
    ignore_https = os.environ.get("IGNORE_HTTPS_ERRORS", "0") == "1"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        driver = None
        try:
            driver = SurfaceDriver(surface, browser, ignore_https_errors=ignore_https, viewport=size)
            driver.log_in()
            # The database the session is on, not the one ODOO_DB names: a
            # mono-database deployment ignores the `?db=` the login carries, so
            # the environment can name one database while the run reads and
            # writes another.
            database = session_database(driver.database)
            require_write_database(targets, database)
            driver.check_selectors(targets)
            run = RunInfo(new_run_id(), os.environ.get("PARITY_TARGET", "local"), database, client)
            signalled = 0
            with open(out_path, "w", encoding="utf-8") as out, \
                    ambient_accounting(driver, run, surface, out_path, command="open"):
                for target in targets:
                    observation = driver.open_screen(target)
                    record = evidence_record(
                        run, surface, module=target.module, identity=target.identity,
                        observation=observation, label=target.label,
                    )
                    out.write(json.dumps(driver.masker.value(record), ensure_ascii=False, sort_keys=True) + "\n")
                    out.flush()
                    noisy = not observation.available or any(observation.signals.values()) or observation.url_violations
                    signalled += bool(noisy)
                    print("%s %s" % ("SIGNAL" if noisy else "CLEAN ", target.identity), file=sys.stderr)
            print("%d targets, %d with signals; run %s" % (len(targets), signalled, run.run_id), file=sys.stderr)
            return 1 if signalled else 0
        finally:
            if driver:
                driver.close()
            browser.close()


_OUT_HELP = ("JSONL evidence file to write; the run's ambient-row figure goes beside it, this name "
             "with .ambient.json for its extension (ingress-open.jsonl -> ingress-open.ambient.json): "
             "counts only, judged by nothing")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    crawl_parser = commands.add_parser("crawl", help="open every menu action of the chosen apps on one surface")
    crawl_parser.add_argument("--surface", required=True, choices=[surface.value for surface in Surface])
    crawl_parser.add_argument("--apps", required=True, help="comma-separated module names, e.g. contacts,project")
    crawl_parser.add_argument("--out", required=True, help=_OUT_HELP)
    crawl_parser.add_argument("--env-file", help="read unset credentials from this NAME=value file")
    crawl_parser.add_argument("--viewport", default="1920x1080",
                              help="WIDTHxHEIGHT; below 768 wide Odoo uses its mobile layout (default 1920x1080)")
    open_parser = commands.add_parser(
        "open", help="open named screens the menu crawler cannot reach, on one surface")
    open_parser.add_argument("--surface", required=True, choices=[surface.value for surface in Surface])
    open_parser.add_argument(
        "--targets", required=True,
        help='JSONL file, one target per line: {"module": ..., "target": ..., and an "expect_model" '
             'or an "expect_selector" that says the right screen loaded}')
    open_parser.add_argument("--out", required=True, help=_OUT_HELP)
    open_parser.add_argument("--env-file", help="read unset credentials from this NAME=value file")
    open_parser.add_argument("--viewport", default="1920x1080",
                             help="WIDTHxHEIGHT; below 768 wide Odoo uses its mobile layout (default 1920x1080)")
    diff_parser = commands.add_parser("diff", help="judge a Public origin run against an Ingress run")
    diff_parser.add_argument("public_run")
    diff_parser.add_argument("ingress_run")
    diff_parser.add_argument("--out", help="JSONL file for the joined records")
    args = parser.parse_args(argv)

    if args.command in ("crawl", "open"):
        if args.env_file:
            with open(args.env_file, encoding="utf-8") as env_file:
                parse_env_file(env_file, os.environ)
        if args.command == "open":
            with open(args.targets, encoding="utf-8") as targets_file:
                targets = parse_targets(targets_file)
            return open_screens(Surface(args.surface), targets, args.out, viewport=args.viewport)
        apps = [app.strip() for app in args.apps.split(",") if app.strip()]
        return crawl(Surface(args.surface), apps, args.out, viewport=args.viewport)

    with open(args.public_run, encoding="utf-8") as public, open(args.ingress_run, encoding="utf-8") as ingress:
        public_records, ingress_records = read_records(public), read_records(ingress)
    # Which runs these are, before they are joined, so a file left by an
    # earlier run -- a run that failed leaves the last one where it was -- is
    # seen whether the join succeeds or refuses.
    for name, records in (("public", public_records), ("ingress", ingress_records)):
        print("%s run(s): %s" % (name, ", ".join(sorted({record["run_id"] for record in records}))))
    merged = diff_runs(public_records, ingress_records)
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
