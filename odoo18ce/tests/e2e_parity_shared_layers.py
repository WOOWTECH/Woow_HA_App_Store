#!/usr/bin/env python3
"""Shared-layer parity run: groups F, A, B, C and D of the parity plan (#143).

The menu crawler (`e2e_menu_action_adapter.py`) opens every menu and only
reads. This run does what a person does on a screen -- copy, download,
upload, fill a form, chat -- once on the Public origin and once inside the
Home Assistant panel, and writes one `odoo-parity-evidence/v1` record per
check (item x screen). Each record holds both surfaces and a verdict; a
conservation report (parity plan section 12) says whether the run is
complete.

Two kinds of screen per item: `generic`, the item on an ordinary screen, and
the module-specific screens the parity plan section 10 names for it
(`MODULE_SCREENS`). A check the run cannot do is recorded `NOT-RUN` with
what blocks it, so a skipped screen is visible instead of missing.

The pure parts are tested in the static tier by
test_e2e_parity_shared_layers.py; the Live part is in
e2e_parity_shared_layers_live.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from e2e_menu_action_adapter import CLIENT, EVIDENCE_SCHEMA, SIGNALS, RunInfo, Surface

VERDICTS = ("PARITY", "GAP", "APPROVED-DIVERGENCE", "STRUCTURAL")
NOT_RUN = "NOT-RUN"
SEVERITIES = ("blocker", "important", "minor", "none")


@dataclass(frozen=True)
class Item:
    id: str
    group: str
    layer: str
    root_cause: tuple[str, ...]
    title: str


def _items(group: str, layer: str, rows: Sequence[tuple[str, str, str]]) -> list[Item]:
    return [Item(item, group, layer, tuple(rc.split("/")) if rc else (), title) for item, rc, title in rows]


def _rc(text: str) -> str:
    """`RC-1/11` -> `RC-1/RC-11`, the way the plan's tables abbreviate them."""
    parts = text.split("/")
    return "/".join(part if part.startswith(("RC-", "AD-")) else "RC-" + part for part in parts)


# Parity plan section 6. Group E is run by e2e_parity_outbound.py (#145).
CATALOG: Mapping[str, Item] = {item.id: item for item in [
    *_items("F", "L0/L2", [
        ("U-F1", "RC-3", "iframe allow capability list"),
        ("U-F2", "RC-13", "HA keyboard shortcut conflicts"),
        ("U-F3", "RC-13", "HA theme and size"),
        ("U-F4", "RC-13", "Supervisor limits"),
        ("U-F5", "RC-3", "downloads"),
    ]),
    *_items("A", "L0/L1", [
        ("U-A1", "RC-1", "no route escape"),
        ("U-A2", "RC-2", "no doubled prefix"),
        ("U-A3", _rc("RC-1/11"), "assets all 200"),
        ("U-A4", "RC-11", "route prefix whitelist completeness"),
        ("U-A5", "RC-14", "content-type rewrite"),
        ("U-A6", "RC-12", "shim injection paths"),
        ("U-A7", "RC-5", "compression and cache"),
        ("U-A8", "RC-13", "large upload limit"),
        ("U-A9", _rc("RC-5/13"), "long request"),
        ("U-A10", "RC-1", "error pages"),
    ]),
    *_items("B", "L2", [
        ("U-B1", "RC-4", "log in, log out, log in again"),
        ("U-B2", "RC-4", "cookie attributes"),
        ("U-B3", "RC-15", "reload and deep link"),
        ("U-B4", "RC-1", "back and forward"),
        ("U-B5", _rc("RC-4/7"), "two tabs"),
        ("U-B6", "RC-13", "host session timeout recovery"),
        ("U-B7", "RC-9", "permissions"),
        ("U-B8", "AD-6", "anonymous boundary"),
    ]),
    *_items("C", "L3", [
        ("U-C1", "RC-1", "all view types"),
        ("U-C2", "RC-1", "control panel"),
        ("U-C3", _rc("RC-1/3"), "form widgets"),
        ("U-C4", "RC-3", "copy to clipboard"),
        ("U-C5", "RC-9", "URL field values"),
        ("U-C6", _rc("RC-1/12"), "HTML editor"),
        ("U-C7", _rc("RC-1/3"), "binary upload, download, preview"),
        ("U-C8", "RC-3", "drag and drop upload"),
        ("U-C9", _rc("RC-1/8"), "chatter"),
        ("U-C10", _rc("RC-1/14"), "dialogs"),
        ("U-C11", "RC-1", "systray"),
        ("U-C12", "RC-1", "app launcher and menu tree"),
        ("U-C13", "RC-1", "breadcrumbs"),
        ("U-C14", _rc("RC-3/13"), "command palette"),
        ("U-C15", "RC-3", "keyboard and focus"),
        ("U-C16", "RC-1", "record operations"),
        ("U-C17", "RC-1", "action and gear menus"),
        ("U-C18", "RC-3", "export"),
        ("U-C19", _rc("RC-1/3"), "import"),
        ("U-C20", _rc("RC-3/9"), "print report"),
        ("U-C21", "RC-1", "notification toasts"),
        ("U-C22", "RC-1", "translation editing"),
        ("U-C23", "RC-15", "open in a new tab"),
        ("U-C24", "RC-3", "fullscreen"),
        ("U-C25", "RC-3", "camera and barcode scan"),
        ("U-C26", _rc("RC-7/8"), "live messages (bus)"),
        ("U-C27", "RC-6", "service worker features"),
    ]),
    *_items("D", "L4", [
        ("U-D1", "RC-1", "website layout"),
        ("U-D2", _rc("RC-1/12/14"), "website editor"),
        ("U-D3", "RC-1", "page lifecycle"),
        ("U-D4", "RC-1", "portal tiles and lists"),
        ("U-D5", _rc("RC-9/10"), "portal access link"),
        ("U-D6", _rc("RC-1/10"), "front-end form"),
        ("U-D7", "RC-10", "anonymous front end"),
        ("U-D8", "RC-9", "SEO outputs"),
    ]),
    *_items("E", "L5", [
        ("U-E1", "RC-9", "web.base.url survives an Ingress login"),
        ("U-E2", "RC-9", "links in outgoing mail"),
        ("U-E3", "RC-9", "share link fields"),
        ("U-E4", "RC-9", "links and QR codes in reports"),
        ("U-E5", "RC-9", "absolute attachment URLs"),
        ("U-E6", "RC-10", "external callback entries"),
        ("U-E7", "RC-9", "URLs in exported files"),
    ]),
]}

# Issue #143's comment: parity plan section 10 screens a generic run misses.
MODULE_SCREENS: tuple[tuple[str, str, str], ...] = (
    ("U-C24", "mrp", "MRP work center"),
    ("U-C24", "hr_attendance", "attendance kiosk mode"),
    ("U-C25", "point_of_sale", "POS product scan"),
    ("U-C25", "mrp", "MRP work order scan"),
    ("U-C25", "hr_attendance", "attendance kiosk badge scan"),
    ("U-C25", "event", "event registration desk"),
    ("U-C4", "survey", "survey share dialog"),
    ("U-C26", "im_livechat", "live chat operator view"),
    ("U-D5", "sale_management", "quotation portal link"),
    ("U-D6", "event", "event registration"),
    ("U-D6", "hr_recruitment", "job application"),
    ("U-D6", "survey", "survey fill"),
    ("U-D7", "website_sale", "/shop"),
    ("U-D7", "hr_recruitment", "/jobs"),
    ("U-D7", "event", "/event"),
    ("U-B2", "website_sale", "/shop/cart"),
    ("U-F5", "point_of_sale", "POS receipt print"),
    # U-D8 minus the sitemap is one record; the sitemap is AD-8 and judged on its own (#172).
    ("U-D8", "website", "sitemap.xml"),
)


def planned_checks() -> list[tuple[str, str, str]]:
    """Every item of groups F, A, B, C, D once on a generic screen, then each module screen."""
    return [(item, "shared", "generic") for item, entry in CATALOG.items() if entry.group != "E"] + list(MODULE_SCREENS)


def check_identity(item: str, module: str, screen: str) -> str:
    return "check:%s|%s|%s" % (item, module, screen)


@dataclass(frozen=True)
class Outcome:
    """What one surface did for one check."""

    available: bool
    result: str
    signals: Mapping[str, int] = field(default_factory=dict)
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_block(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "result": self.result,
            "signals": {name: int(self.signals.get(name, 0)) for name in SIGNALS},
            "details": dict(self.details),
        }


def judge(public: Outcome, ingress: Outcome) -> tuple[str, str, list[str]]:
    """Section 1.1 for one check: the same result and no signals on either side."""
    reasons: list[str] = []
    blocker = False
    for name, outcome in (("public", public), ("ingress", ingress)):
        if not outcome.available:
            reasons.append("%s unavailable: %s" % (name, outcome.result))
            blocker = True
    for name, outcome in (("public", public), ("ingress", ingress)):
        for signal in SIGNALS:
            count = int(outcome.signals.get(signal, 0))
            if count:
                reasons.append("%s %s=%d" % (name, signal, count))
                blocker = blocker or signal == "route_escape"
    if public.available and ingress.available and public.result != ingress.result:
        reasons.append("result: public=%s ingress=%s" % (public.result, ingress.result))
    if not reasons:
        return "PARITY", "none", []
    return "GAP", ("blocker" if blocker else "important"), reasons


def check_record(
    run: RunInfo,
    item: str,
    *,
    module: str,
    screen: str,
    public: Outcome | None,
    ingress: Outcome | None,
    verdict: str | None = None,
    severity: str | None = None,
    notes: str = "",
    public_path: str | None = None,
    blocked_by: str | None = None,
    route: str | None = None,
    model: str | None = None,
    artifacts: Sequence[str] = (),
) -> dict[str, Any]:
    """One check as an `odoo-parity-evidence/v1` record with both surfaces."""
    entry = CATALOG[item]
    if verdict is None:
        if public is None or ingress is None:
            raise ValueError("%s: a check without both outcomes needs a verdict" % item)
        verdict, severity, reasons = judge(public, ingress)
        notes = "; ".join(filter(None, [notes, *reasons]))
    if verdict not in VERDICTS + (NOT_RUN,):
        raise ValueError("unknown verdict %r" % verdict)
    if verdict == "STRUCTURAL" and not public_path:
        raise ValueError("%s: a STRUCTURAL verdict must name the Public origin path that carries it" % item)
    if verdict == NOT_RUN:
        if not blocked_by:
            raise ValueError("%s: a NOT-RUN check must name what blocks it (blocked_by)" % item)
        severity = None
    elif severity not in SEVERITIES:
        raise ValueError("%s: severity must be one of %s" % (item, ", ".join(SEVERITIES)))
    record: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "run_id": run.run_id,
        "target": run.target,
        "database": run.database,
        "client": run.client or CLIENT,
        "layer": entry.layer,
        "item": item,
        "root_cause": list(entry.root_cause),
        "module": module,
        "screen": {"route": route, "model": model, "view": None, "name": screen},
        "control_identity": check_identity(item, module, screen),
        "public": public and public.as_block(),
        "ingress": ingress and ingress.as_block(),
        "verdict": verdict,
        "severity": severity,
        "artifacts": list(artifacts),
        "notes": notes,
    }
    if public_path:
        record["public_path"] = public_path
    if blocked_by:
        record["blocked_by"] = blocked_by
    return record


# --- U-F1 -------------------------------------------------------------------

# The browser grants these only to a secure context (https or localhost).
_SECURE_ONLY = ("clipboard-write", "camera", "microphone")
_POLICY_FEATURES = ("clipboard-write", "fullscreen", "camera", "microphone")


def capability_upper_bound(
    frame_attrs: Mapping[str, Any], allowed_features: Iterable[str], *, secure_context: bool,
) -> dict[str, dict[str, Any]]:
    """The U-F1 list: what the Ingress frame may do, and what stops the rest.

    It bounds U-C4, U-C24, U-C25 and U-F5: a feature the frame's policy or
    sandbox withholds cannot be fixed inside Odoo; one withheld only for an
    insecure context comes back on an https entrance.
    """
    allowed = set(allowed_features)
    bound: dict[str, dict[str, Any]] = {}
    for feature in _POLICY_FEATURES:
        policy = feature in allowed
        limit = None
        if not policy:
            limit = "iframe policy"
        elif feature in _SECURE_ONLY and not secure_context:
            limit = "insecure context"
        bound[feature] = {"policy": policy, "usable": limit is None, "limit": limit}
    sandbox = frame_attrs.get("sandbox")
    downloads = sandbox is None or "allow-downloads" in str(sandbox).split()
    bound["downloads"] = {"policy": downloads, "usable": downloads, "limit": None if downloads else "iframe sandbox"}
    return bound


# --- U-B2 -------------------------------------------------------------------


def session_cookie_problems(
    cookie: Mapping[str, Any] | None, *, surface: Surface, ingress_prefix: str | None, https: bool,
) -> list[str]:
    """How `session_id` differs from the attributes the plan's U-B2 expects."""
    if not cookie:
        return ["no session_id cookie"]
    if surface is Surface.HA_INGRESS:
        expected = {"path": "%s/" % ingress_prefix, "secure": https}
    else:
        expected = {"path": "/", "secure": True}
    expected.update(httpOnly=True, sameSite="Lax")
    labels = {"path": "Path", "secure": "Secure", "httpOnly": "HttpOnly", "sameSite": "SameSite"}
    return [
        "%s=%s (expected %s)" % (labels[key], cookie.get(key), value)
        for key, value in expected.items()
        if cookie.get(key) != value
    ]


def _details(outcome: Outcome) -> Mapping[str, Any]:
    return outcome.details or {}


# --- U-A6 -------------------------------------------------------------------

# RC-12: the ways a root-relative URL can reach the browser without passing
# through an API the Runtime shim wraps. #169 split them in two, and the
# check has to hold both, or it cannot tell a shim defect from a way left
# uncovered on purpose.
COVERED = "covered"
ACCEPTED = "accepted"


@dataclass(frozen=True)
class InjectionWay:
    """One way `U-A6` asks for its probe path, and what its group means.

    `covered`: the shim must prefix it (ADR 0004 makes the shim the Ingress
    URL authority for anything it can intercept), so an escape is a defect.
    `accepted`: the shim leaves it alone by decision. The HTML editor and the
    website editor load and save record content through markup and style, so
    a hook there would write the Ingress prefix -- which carries the Ingress
    token -- into the database, breaking the Public origin and leaking the
    token. A screen that hits one gets a route-scoped Literal rewrite of its
    own, filed as its own issue (`issues`).
    """

    kind: str
    group: str
    how: str
    issues: tuple[str, ...] = ()


INJECTION_WAYS: tuple[InjectionWay, ...] = (
    InjectionWay("sendBeacon", COVERED, "navigator.sendBeacon(url)"),
    InjectionWay("EventSource", COVERED, "new EventSource(url)"),
    InjectionWay("svg-use", COVERED, 'createElementNS <use>, an existing xlink:href updated with '
                 'setAttribute("xlink:href", url)'),
    InjectionWay("svg-use-href", COVERED, 'createElementNS <use>, setAttribute("href", url)'),
    InjectionWay("svg-use-ns", COVERED, 'createElementNS <use>, setAttributeNS(xlink, "xlink:href", url)'),
    # #159 wrapped the media-source setters (the Registration Desk's barcode error sound escaped
    # through new Audio); one covered way fires all three so a regression in any surfaces here.
    InjectionWay("media", COVERED, "new Audio(url), HTMLMediaElement.src, HTMLSourceElement.src"),
    InjectionWay("innerHTML-img", ACCEPTED, 'innerHTML with <img src="url">', ("#158",)),
    InjectionWay("insertAdjacentHTML-use", ACCEPTED, 'insertAdjacentHTML with <svg><use xlink:href="url">'),
    InjectionWay("style-attr", ACCEPTED, "style attribute with url(url)", ("#170",)),
    InjectionWay("style-url", ACCEPTED, "dynamic <style> element with url(url)"),
    InjectionWay("css-import", ACCEPTED, "dynamic <style> element with @import url(url)"),
)
INJECTION_KINDS: tuple[str, ...] = tuple(way.kind for way in INJECTION_WAYS)
INJECTION_GROUPS: Mapping[str, str] = {way.kind: way.group for way in INJECTION_WAYS}
# Odoo 18 redirects server-side, and the probe would navigate the page away
# from the screen under test, so this way is not tried at all.
META_REFRESH_NOTE = "<meta http-equiv=refresh> is not tried: Odoo 18 redirects server-side, and the probe " \
                    "would navigate the page away from the screen under test"


def injection_group(kind: str) -> str:
    """The group of a way. A way no decision knows is covered: nothing accepted it."""
    return INJECTION_GROUPS.get(kind, COVERED)


def injection_ways(group: str) -> list[str]:
    return [way.kind for way in INJECTION_WAYS if way.group == group]


def _way_issues(kinds: Iterable[str]) -> list[str]:
    """Each way with the screens filed against it, for the notes."""
    issues = {way.kind: way.issues for way in INJECTION_WAYS}
    return ["%s%s" % (kind, " (%s)" % ", ".join(issues[kind]) if issues.get(kind) else "") for kind in kinds]


def _way_how(kinds: Iterable[str]) -> list[str]:
    """Each way with the call that made it, so a gap names what to fix."""
    how = {way.kind: way.how for way in INJECTION_WAYS}
    return ["%s%s" % (kind, " (%s)" % how[kind] if kind in how else "") for kind in kinds]


def injection_verdict(public: Outcome, ingress: Outcome) -> tuple[str, str, list[str]]:
    """U-A6: which injection ways escaped, read against the two groups.

    A `GAP` only for a way the shim is meant to cover escaping under Ingress,
    or for any way escaping on the Public origin -- where a root-relative URL
    stays on the origin it was asked from, whatever the way. An escape in the
    `accepted` group is what the decision says it is, so the check stays
    `PARITY` and names the escaped ways and their screen issues in the notes.
    Everything else section 1.1 judges as usual: an unavailable surface or a
    route escape is a Blocker, a console error is Important.

    Each outcome carries `details["escaped"]` (the ways that left), plus
    `details["requested"]` and `details["not_requested"]`, which say which
    ways the browser asked for at all. A covered way that made no request
    proves nothing either way, so it is named in the notes rather than judged.
    """
    _, severity, reasons = judge(public, ingress)
    # judge() compares the two results, which name each surface's escaped ways: an
    # accepted escape under Ingress is expected, so that difference is not the gap.
    reasons = [reason for reason in reasons if not reason.startswith("result: ")]
    blocker = severity == "blocker"
    escaped_public = sorted(_details(public).get("escaped", []))
    escaped_ingress = sorted(_details(ingress).get("escaped", []))
    covered = [kind for kind in escaped_ingress if injection_group(kind) == COVERED]
    accepted = [kind for kind in escaped_ingress if injection_group(kind) == ACCEPTED]
    if escaped_public:
        reasons.append("public: a root-relative URL left the origin through %s" % ", ".join(escaped_public))
    if covered:
        reasons.append("ingress: the shim did not prefix %s" % ", ".join(_way_how(covered)))
    notes = []
    if accepted:
        notes.append("accepted escapes, uncovered by decision: %s" % ", ".join(_way_issues(accepted)))
    silent = [kind for kind in _details(ingress).get("not_requested", []) if injection_group(kind) == COVERED]
    if silent:
        notes.append("covered ways the browser never asked for: %s" % ", ".join(sorted(silent)))
    if reasons:
        return "GAP", ("blocker" if blocker else "important"), reasons + notes
    return "PARITY", "none", notes


# --- U-D8 -------------------------------------------------------------------

PUBLIC_BASE = "<PUBLIC_BASE>"
# AD-8: what `robots.txt` must still say under Ingress for the sitemap's own
# address to be harmless -- Odoo steers crawlers to the Canonical URL's copy.
AD8_DISALLOW = "Disallow: /"
AD8_SITEMAP = "Sitemap: %s/sitemap.xml" % PUBLIC_BASE
AD8_ROBOTS_LINES = (AD8_DISALLOW, AD8_SITEMAP)


def _robots(outcome: Outcome) -> set[str]:
    """One surface's `robots.txt` lines, whitespace and case normalised."""
    return {" ".join(line.split()).lower() for line in _details(outcome).get("robots", [])}


def seo_head_verdict(public: Outcome, ingress: Outcome) -> tuple[str, str, list[str]]:
    """U-D8 without the sitemap: the home page's head links and `robots.txt`.

    A comparison of the surfaces, plus the plan's absolute rule for the item:
    every URL base is the Canonical URL, so two surfaces wrong in the same way
    are a GAP as well. Each outcome's `details["wrong"]` names the bases that
    are not `<PUBLIC_BASE>` (and relative URLs, which have lost their base).
    """
    verdict, severity, reasons = judge(public, ingress)
    for name, outcome in (("public", public), ("ingress", ingress)):
        wrong = list(_details(outcome).get("wrong", []))
        if wrong:
            reasons.append("%s SEO URLs on %s" % (name, ", ".join(wrong)))
            verdict = "GAP"
            severity = "important" if severity == "none" else severity
    return verdict, severity, reasons


def sitemap_divergence(public: Outcome, ingress: Outcome) -> tuple[str, str, list[str]]:
    """AD-8 verified in reverse: `sitemap.xml` on each surface, and each `robots.txt`.

    Odoo builds the sitemap from the request's URL root, so the Ingress copy
    lists the Home Assistant address; that is accepted only while every
    statement of AD-8 still holds -- both surfaces serve a sitemap, the Public
    origin's is on the Canonical URL and its `robots.txt` lets crawlers in,
    the Ingress copy is not on the Canonical URL and carries no Ingress prefix,
    and Ingress's `robots.txt` says `Disallow: /` and points at the Canonical
    URL's sitemap. A divergence that disappeared is a failure of the reverse
    verification, and a `robots.txt` that no longer steers crawlers (an empty
    `website.domain`, P-5) leaves the Ingress copy unguarded: both are a GAP.
    An Ingress prefix inside a sitemap is a leaked credential, so it is a
    Blocker, as is a surface that could not be read at all (section 1.3).

    Each outcome carries the fetch's `details["status"]`, the masked sitemap
    bases in `details["bases"]`, how many of its URLs hold an Ingress prefix
    (`details["ingress_prefix"]`, a count: the URL itself must not be written)
    and its `robots.txt` lines in `details["robots"]`.
    """
    reasons: list[str] = []
    severity = "important"
    for name, outcome in (("public", public), ("ingress", ingress)):
        details = _details(outcome)
        if not outcome.available:
            reasons.append("%s unavailable: %s" % (name, outcome.result))
            severity = "blocker"
        elif details.get("status") != 200:
            reasons.append("%s sitemap.xml HTTP %s" % (name, details.get("status")))
        prefixed = int(details.get("ingress_prefix", 0))
        if prefixed:
            reasons.append("%s sitemap carries the Ingress prefix in %d URL(s)" % (name, prefixed))
            severity = "blocker"
    public_bases = list(_details(public).get("bases", []))
    ingress_bases = list(_details(ingress).get("bases", []))
    if public_bases != [PUBLIC_BASE]:
        reasons.append("public sitemap on %s" % (", ".join(public_bases) or "nothing"))
    if not ingress_bases:
        reasons.append("ingress sitemap has no URL")
    elif PUBLIC_BASE in ingress_bases:
        reasons.append("ingress sitemap on %s: AD-8 no longer holds" % PUBLIC_BASE)
    ingress_robots = _robots(ingress)
    for line in AD8_ROBOTS_LINES:
        if line.lower() not in ingress_robots:
            reasons.append("ingress robots.txt has no %r" % line)
    # The Public origin must stay crawlable: that half of AD-8 disappearing hides the site.
    if AD8_DISALLOW.lower() in _robots(public):
        reasons.append("public robots.txt says %r" % AD8_DISALLOW)
    if reasons:
        return "GAP", severity, reasons
    return "APPROVED-DIVERGENCE", "none", []


# --- U-C23 ------------------------------------------------------------------

HA_BASE = "<HA_BASE>"
INGRESS_PREFIX = "<INGRESS_PREFIX>"
# RC-15: every top-level page under Ingress lives below the Supervisor path,
# so a tab opened from there starts here and carries the session token.
INGRESS_TAB_BASE = HA_BASE + INGRESS_PREFIX
# The masked prefix is this session's own; a prefix the mask did not recognise
# (a stale one, #160) still reads as what it is.
INGRESS_PATH = "/api/hassio_ingress/"
# The evidence sanitiser redacts every value under a key that reads as a secret, whatever its
# type, so the flag is named for what it reports rather than for the token it looks for (#187):
# under a `token` key a boolean reached the file as the string `<redacted>` on both surfaces.
INGRESS_PREFIX_DETAIL = "ingress_prefix_in_url"


def new_tab_verdict(public: Outcome, ingress: Outcome) -> tuple[str, str, list[str], str | None]:
    """U-C23: where a tab Odoo opens in the browser lands on each surface.

    A tab opened from Ingress carries the Ingress token in its address by
    construction, which section 1.4 makes a `STRUCTURAL` gap (RC-15) rather
    than a defect: the confirmed shape is the same page in both tabs, the
    Ingress one under `<HA_BASE><INGRESS_PREFIX>/` and the Public one under
    `<PUBLIC_BASE>/`, and the Public origin's address is then the path that
    carries the capability -- the one to share, since the Ingress address
    opens only for the person whose session it holds. The two addresses
    differ by construction, so that difference alone is not a gap. Everything
    else is the `GAP` section 1.1 gives it: a tab that did not open, one off
    the Ingress prefix or off the Canonical URL, or a different page in it --
    and a blank tab, or the Ingress prefix inside the Public origin's address
    (a leaked token), is a Blocker by section 1.3. A doubled prefix on the
    Ingress side shows up as the two tabs being on different pages.

    Each outcome carries the masked address shape of the tab it opened in
    `details["shape"]`, that page's text in `details["page_text"]`, and
    `details[INGRESS_PREFIX_DETAIL]` -- a boolean -- for whether the whole
    address, query and fragment included (which the shape leaves out), holds an
    Ingress prefix. A flag that is not a `bool` says nothing either way.
    """
    verdict, severity, reasons = judge(public, ingress)
    # judge() compares the two results, which name the two addresses; those differ here by construction.
    reasons = [reason for reason in reasons if not reason.startswith("result: ")]
    blocker = severity == "blocker"
    routes: dict[str, str | None] = {}
    for name, outcome, base in (("public", public, PUBLIC_BASE), ("ingress", ingress, INGRESS_TAB_BASE)):
        shape = str(_details(outcome).get("shape", ""))
        routes[name] = shape[len(base):] if shape.startswith(base) else None
        if not outcome.available:
            continue
        flag = _details(outcome).get(INGRESS_PREFIX_DETAIL)
        # Only the probe's own boolean is evidence: a flag read back from a file, where an
        # older sanitiser left the truthy string `<redacted>`, must not invent a leak (#187).
        if name == "public" and (INGRESS_PREFIX in shape or INGRESS_PATH in shape or flag is True):
            # Section 1.3: the Supervisor token in an address outside Ingress is a leaked credential.
            reasons.append("public tab address carries the Ingress prefix")
            blocker = True
            routes[name] = None
        elif routes[name] is None:
            reasons.append("%s tab at %s, not under %s" % (name, shape or "nothing", base))
        if not str(_details(outcome).get("page_text", "")).strip():
            # Section 1.3 again: a blank screen, whatever its address.
            reasons.append("%s tab rendered no text" % name)
            blocker = True
    if all(route is not None for route in routes.values()):
        if routes["public"] != routes["ingress"]:
            reasons.append("the tabs opened different pages: public %s, ingress %s"
                           % (routes["public"], routes["ingress"]))
        elif _details(public).get("page_text") != _details(ingress).get("page_text"):
            reasons.append("the two tabs do not render the same page")
    if reasons:
        return "GAP", ("blocker" if blocker else "important"), reasons, None
    return "STRUCTURAL", "none", [], PUBLIC_BASE + str(routes["public"])


# --- Section 12 -------------------------------------------------------------


def attach_issues(records: Iterable[Mapping[str, Any]], issues: Mapping[str, int]) -> list[dict[str, Any]]:
    """Record the issue filed for each GAP, keyed by control identity."""
    out = []
    known = set()
    for record in records:
        record = dict(record)
        number = issues.get(record["control_identity"])
        if number is not None:
            if record["verdict"] != "GAP":
                raise ValueError("%s is not a GAP (%s)" % (record["control_identity"], record["verdict"]))
            record["issue"] = "#%d" % number
            known.add(record["control_identity"])
        out.append(record)
    unknown = set(issues) - known
    if unknown:
        raise ValueError("no record for %s" % ", ".join(sorted(unknown)))
    return out


def conservation(records: Iterable[Mapping[str, Any]], plan: Iterable[tuple[str, str, str]]) -> dict[str, Any]:
    """Observed = PARITY + GAP + APPROVED-DIVERGENCE + STRUCTURAL (+ NOT-RUN).

    The run qualifies only with no remainder: nothing planned is missing,
    nothing is unclassified or left NOT-RUN, every GAP has an issue and
    every STRUCTURAL names its Public origin path.
    """
    records = list(records)
    counts = {verdict: 0 for verdict in VERDICTS + (NOT_RUN,)}
    unclassified, gaps_without_issue, structural_without_path, not_run = [], [], [], []
    for record in records:
        verdict, identity = record.get("verdict"), record["control_identity"]
        if verdict not in counts:
            unclassified.append(identity)
            continue
        counts[verdict] += 1
        if verdict == "GAP" and not record.get("issue"):
            gaps_without_issue.append(identity)
        if verdict == "STRUCTURAL" and not record.get("public_path"):
            structural_without_path.append(identity)
        if verdict == NOT_RUN:
            not_run.append(identity)
    seen = [record["control_identity"] for record in records]
    planned = [check_identity(*check) for check in plan]
    report = {
        "observed": len(records),
        "counts": counts,
        "missing": sorted(set(planned) - set(seen)),
        "unplanned": sorted(set(seen) - set(planned)),
        "duplicates": sorted({identity for identity in seen if seen.count(identity) > 1}),
        "unclassified": unclassified,
        "gaps_without_issue": gaps_without_issue,
        "structural_without_path": structural_without_path,
        "not_run": not_run,
    }
    report["balanced"] = sum(counts.values()) + len(unclassified) == len(records)
    report["qualified"] = report["balanced"] and not any(
        report[key] for key in ("missing", "unplanned", "duplicates", "unclassified",
                                "gaps_without_issue", "structural_without_path", "not_run")
    )
    return report
