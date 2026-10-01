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
with one GET and then navigates to each action's route; it never clicks, types
into Odoo records or calls an RPC, and a menu whose action could write (a
server action) is listed as skipped, never planned. The exception is an `open`
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
a cart.

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
    `GET_WRITING_ROUTES`.
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
# Three limits on what that buys, none of them something a list keyed on the
# target's route can see. The controller is not the whole request:
# `views/templates.xml:13` calls `website.sale_get_order()` from the cart link of
# every page header, which writes the same way `/shop/checkout` does
# (models/website.py:457), so a page whose controller writes nothing can still
# write. The target's GET is not the whole navigation: the page's own JavaScript
# posts on its own account, and `/shop/products/recently_viewed_update`
# (controllers/main.py:2288) writes a `website.visitor` from a product page
# nobody asked to write. And the route navigated is not always the route
# answered: `page.goto` follows a 30x, so a route that redirects into a listed
# one writes behind the guard -- no `website_sale` route does (the set is closed
# under its own redirects), which is a property of today's Odoo and not of this
# list. `project`'s two outdated portal prefixes are redirects of exactly that
# shape and are listed below for it; they are the ones that were found, not the
# ones that exist.
#
# One write outside the list was read and left outside it:
# `website/models/ir_http.py:188-205` creates or touches a `website.visitor` on
# a GET whose response is a tracked page, whichever module serves it. It is out
# because it is not a property of the route: the gate is `view.track` on the
# template the response happened to render (`response_template` in its
# `qcontext`), so the same route can write on one website and not on another, and
# no list keyed on a route can say which. Bounding it would mean bounding every
# website page an `open` target can name -- `/`, `/contactus`, `/shop` -- which
# is a decision about whether `open` may judge a website page off
# `WRITE_DATABASE` at all, and that is the read-only guarantee as a whole and not
# this seam. (`crawl` is not affected either way: it navigates only
# `/odoo/action-<id>`, whose response is the web client bootstrap and not a
# tracked page, so it never makes this write.)
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
# bound, so all five still need their bodies read. #247 holds that sweep.
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
    "/shop/cart": "unlinks the cart lines of archived products",
    # controllers/main.py:1056 persists a delivery method and its price on the
    # draft order (`_set_delivery_method`); :1039 runs `_check_cart_and_addresses`,
    # which reaches `_check_cart` at :2038, which at :2073-2076 stores a
    # `shop_warning` on the order and its zero-priced lines. `sale_get_order`
    # itself writes too: models/website.py:457 moves the order onto the
    # logged-in partner when the two disagree.
    "/shop/checkout": "persists a delivery method on the draft sale.order",
    # controllers/main.py:1133 runs the same `_check_cart` before rendering the
    # address form, so the `shop_warning` writes at :2073-2076 apply here too.
    "/shop/address": "stores a shop_warning on the cart through _check_cart",
    # controllers/main.py:1797-1802 recomputes the order's taxes and prices and
    # re-applies its delivery method, all on the draft order.
    "/shop/confirm_order": "recomputes the draft order's taxes, prices and delivery method",
    # controllers/main.py:1820 runs `_check_cart` before rendering the extra
    # step, so the `shop_warning` writes at :2073-2076 apply.
    "/shop/extra_info": "stores a shop_warning on the cart through _check_cart",
    # controllers/main.py:1931 runs `_check_cart_and_addresses`, so the
    # `shop_warning` writes at :2073-2076 apply.
    "/shop/payment": "stores a shop_warning on the cart",
    # Under the same prefix, and its own entry because the longest match is what
    # a refusal reports and this write is not the one above: controllers/
    # main.py:1978-1979 confirms the draft order (`_check_cart_is_ready_to_be_paid`
    # then `_validate_order`), which is a sale and not a draft edit, and
    # `request.website.sale_reset()` then drops the cart the run was judging.
    "/shop/payment/validate": "confirms the draft order into a sale and resets the cart",
    # controllers/main.py:737 and :747 set the cart's pricelist and recompute
    # its prices (`_cart_update_pricelist`, `_recompute_prices`).
    "/shop/pricelist": "sets the cart's pricelist and recomputes its prices",
    # controllers/main.py:721 sets the cart's pricelist for the pricelist the
    # route names (`_cart_update_pricelist`).
    "/shop/change_pricelist": "sets the cart's pricelist and recomputes its prices",
    # `website`'s route, and `website_sale` overrides it to write: controllers/
    # website.py:72-79 is a bare `@route()` over `/website/lang/<lang>`
    # (website/controllers/main.py:210, `type='http'` and not `readonly`), and
    # its body marks the cart's order lines for a recompute of their `name` in
    # the new language, which the request flushes onto `sale.order.line`.
    "/website/lang": "recomputes the cart's order line names in the chosen language",
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
    "/my/orders/": "stores an access_token on an unpaid order and posts a viewed-by-customer note",
    # `account`'s invoice page: account/controllers/portal.py:153 renders
    # `/my/invoices/<int:invoice_id>` through `_invoice_get_page_view_values`
    # (:47), which reaches the portal pager and stores an `access_token` on the
    # invoices either side of this one. Slash-terminated for the same reason as
    # the orders key: `/my/invoices` (:81) only fills `request.session`. It
    # over-refuses `/my/invoices/page/<n>` (:81), which writes nothing.
    "/my/invoices/": "stores an access_token on the neighbouring invoices through the portal pager",
    # Under that prefix, and its own entry because the longest match is what a
    # refusal reports and this write is not the one above: the overdue-invoices
    # page (account_payment/controllers/portal.py:53) asks the company for a
    # batch payment reference at :85 whenever a partner has more than one overdue
    # invoice, and account/models/company.py:272 takes it from an `ir.sequence`
    # with `next_by_id()`, which bumps the sequence -- a write on the company's
    # numbering and not on any invoice.
    "/my/invoices/overdue": "bumps the company's batch payment sequence",
    # `purchase`'s order page: purchase/controllers/portal.py:145 renders
    # `/my/purchase/<int:order_id>` through :110, which reaches the portal pager.
    # With a query it writes more: :158, :160 and :162 take `?confirm=` as the
    # vendor's answer and flip `mail_reminder_confirmed` /
    # `mail_reception_confirmed` / `mail_reception_declined` with a chatter note
    # (purchase/models/purchase_order.py:1125, :1143 and :1152), and the last one
    # also schedules an activity (:1153). `/my/purchase` (:126) and `/my/rfq`
    # (:112) write nothing; `/my/purchase/page/<n>` is over-refused.
    "/my/purchase/": "stores an access_token on the neighbouring purchase orders and answers ?confirm= on the order",
    # `project`'s project page and the task pages under it:
    # project/controllers/portal.py:209 calls `generate_access_token()` on every
    # attachment of the task it is about to render, and
    # base/models/ir_attachment.py:691 writes an `access_token` on each; :125 and
    # :197 both reach the portal pager through :58 and :304. `/my/projects` (:69)
    # writes nothing. Over-refuses `/my/projects/<id>/page/<n>` (:125),
    # `/my/projects/<id>/project_sharing` (:186) and the subtask and recurrent
    # task lists (:214, :247), none of which write.
    "/my/projects/": "stores access_tokens on a task's attachments and on the neighbouring records",
    # `project`'s standalone task page: project/controllers/portal.py:556 is the
    # same `generate_access_token()` write (ir_attachment.py:691), and :561
    # reaches the portal pager through :304. `/my/tasks` (:514) writes nothing.
    "/my/tasks/": "stores access_tokens on a task's attachments and on the neighbouring tasks",
    # The outdated spellings of the two above, and on the list because of what
    # they redirect into: project/controllers/portal.py:110 and :118 answer
    # `/my/project/...` and `/my/task/...` with a 30x onto `/my/projects/...` and
    # `/my/tasks/...`, and `page.goto` follows a 30x, so the landing page's write
    # is this route's write. Both keys end in a slash: `/my/task` redirects onto
    # the task list page, which writes nothing, and `/my/project` is not a route.
    "/my/project/": "redirects onto /my/projects/<id>, which writes",
    "/my/task/": "redirects onto /my/tasks/<id>, which writes",
    # `mail`'s route, which `portal` overrides to add the portal layout
    # (portal/controllers/mail.py:172, a bare `@route()` over
    # mail/controllers/mail.py:217 -- `type='http'`, no `methods`, so a GET
    # reaches it): mail/controllers/mail.py:225 unsubscribes the partner the
    # query names from the record's followers, which unlinks a `mail.followers`
    # row. The token check in front of it (:219) is not a write bound; a wrong
    # token raises instead, and a guard errs towards refusing.
    "/mail/unfollow": "unsubscribes a follower from the record",
    # `digest`'s two GET-reachable routes, one key because the prefix is static
    # and the digest id is not: digest/controllers/portal.py:25 takes
    # `methods=['GET', 'POST']` and unsubscribes a user at :51 or :54
    # (digest/models/digest.py:119 writes `user_ids`), and :62 carries no
    # `methods` at all and sets the digest's periodicity at :70
    # (digest/models/digest.py:128). The POST-only one-click route (:14) is under
    # the same prefix and is refused with them, which costs nothing: a GET never
    # reaches it.
    "/digest/": "unsubscribes a user from a digest and sets the digest's periodicity",
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
    # step and writes nothing, which is why the key is not `/discuss/`.
    "/chat/": "creates a mail.guest and a discuss.channel.member, and a discuss.channel from an unknown token",
    "/meet/": "creates a discuss.channel from an unknown token, and a mail.guest in it",
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


def require_write_database(targets: Iterable[OpenTarget], database: str | None) -> None:
    """A target that writes the two ways a target can say so is bounded.

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
    """
    if database == WRITE_DATABASE:
        return
    # Read once: this walks the targets twice, and an `Iterable` may be a
    # generator, which the first walk would leave empty for the second.
    targets = tuple(targets)
    # Every reason at once. A file can hold both kinds, and reporting one of
    # them sends the operator back for another browser launch and login to be
    # refused for the other.
    reasons = ["a target fills a cart, which writes"] if any(target.cart for target in targets) else []
    for target in targets:
        prefix = get_writing_route(target.route)
        if prefix is not None:
            reasons.append("target %s writes on a plain GET -- %s %s"
                           % (target.target, prefix, GET_WRITING_ROUTES[prefix]))
    if reasons:
        raise RuntimeError("crawler configuration: %s; that write is allowed on %s only, and the "
                           "session's database is %r"
                           % ("; also ".join(reasons), WRITE_DATABASE, database))


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
    # The records an `open` target created to reach its screen -- the cart
    # `ensure_cart` filled, or the one a failed cart step left empty, and
    # nothing else. Empty does not mean the run wrote nothing: a target on
    # `GET_WRITING_ROUTES` writes while its screen renders,
    # bounded to `WRITE_DATABASE` but not reported here, and so do the page's own
    # templates and JavaScript. Read it as "what the run set up", not as "what
    # the database got".
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
        # cart and the other run reuses it. Two different records mean the two
        # screens were rendered from different data, and nothing below them can
        # be attributed to the surface.
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
            self.database = page.evaluate("() => (odoo.info && odoo.info.db) || null")
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
        return self._open(visit.route, backend=True, expect_action=visit.action_id)

    def open_screen(self, target: OpenTarget) -> SurfaceObservation:
        """Open one named screen, the way `observe` opens a planned menu action.

        A target whose route writes on a plain GET is refused off
        `WRITE_DATABASE`, the way `ensure_cart` refuses the declared cart write:
        `open_screens` checks the whole target list before the first screen so a
        misaimed run stops at once, and this is the check for every other caller
        of this driver.
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
            raise RuntimeError(self.masker.text(str(error) + detail)) from None
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
            page.goto(self.base + product_route, wait_until="load", timeout=60000)
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
        page = None
        try:
            if self.ingress:
                # Best effort, and suppressed: this reading is the one thing
                # standing between a cart the run filled and a `writes` that
                # never names it, so a session that will not refresh must not
                # cost it. A page that then fails is what the reason is for.
                with contextlib.suppress(Exception):
                    self.ingress.keep_alive()
            page = self.context.new_page()
            items, order = self._cart(page)
        except Exception as error:  # noqa: BLE001 -- the failure that brought us here is the story
            return None, ("the cart could not be read afterwards (%s)"
                          % (str(error).splitlines() or [""])[0])
        finally:
            if page is not None:
                with contextlib.suppress(Exception):
                    page.close()
        if items is None:
            return None, "the cart page did not show afterwards how many items the cart holds"
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

    def _cart(self, page) -> tuple[int | None, str | None]:
        """The number of items in the session's cart, and the order it is.

        The count is None when the cart page did not show one.
        """
        page.goto(self.base + "/shop/cart", wait_until="domcontentloaded", timeout=60000)
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
            page.goto(self.base + route, wait_until="load", timeout=60000)
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
            with open(out_path, "w", encoding="utf-8") as out:
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
            # The database the session is on, not the one ODOO_DB names: a
            # mono-database deployment ignores the `?db=` the login carries, so
            # the environment can name one database while the run reads and
            # writes another.
            database = session_database(driver.database)
            require_write_database(targets, database)
            driver.check_selectors(targets)
            run = RunInfo(new_run_id(), os.environ.get("PARITY_TARGET", "local"), database, client)
            signalled = 0
            with open(out_path, "w", encoding="utf-8") as out:
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
    open_parser = commands.add_parser(
        "open", help="open named screens the menu crawler cannot reach, on one surface")
    open_parser.add_argument("--surface", required=True, choices=[surface.value for surface in Surface])
    open_parser.add_argument(
        "--targets", required=True,
        help='JSONL file, one target per line: {"module": ..., "target": ..., and an "expect_model" '
             'or an "expect_selector" that says the right screen loaded}')
    open_parser.add_argument("--out", required=True, help="JSONL evidence file to write")
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
