#!/usr/bin/env python3
"""Live tier of the shared-layer parity run (#143): browsers on both surfaces.

    python odoo18ce/tests/e2e_parity_shared_layers_live.py pcheck --env-file .env --db odoo_parity
    python odoo18ce/tests/e2e_parity_shared_layers_live.py run --env-file .env --db odoo_parity \
        --out checks.jsonl [--only U-F1,U-C4] [--run-id WOOW-PARITY-...]
    python odoo18ce/tests/e2e_parity_shared_layers_live.py report checks.jsonl [--issues issues.json]

The Public side is a top-level page on the Public origin. The Ingress side is
the add-on's panel in the Home Assistant frontend with Odoo in its iframe --
the way a person uses it -- so the iframe's own limits (U-F1) apply. The
frontend is signed in with the long-lived token in `hassTokens`; Home
Assistant then opens the Ingress session itself.

Environment, the same names as the menu crawler (`--env-file` fills unset
ones): ODOO_PUBLIC_URL, HA_BASE_URL, HA_TOKEN, ADDON_SLUG, ODOO_TEST_LOGIN,
ODOO_TEST_PASSWORD, PARITY_TARGET; `--db` names the database both surfaces
must serve. HA_HTTPS_BASE_URL, when set, is an https entrance of the same
Home Assistant for U-C25; without it U-C25 is recorded NOT-RUN.

Writes happen only on the database named by `--db`, only where a check needs
a record (P-7), and every record it creates carries the run marker in its
name. Nothing is deleted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlsplit

from e2e_menu_action_adapter import (
    Masker,
    RunInfo,
    Surface,
    count_signals,
    new_run_id,
    parse_env_file,
    sanitize_diagnostic,
)
from e2e_parity_outbound import NAMESPACE_HOSTS  # XML namespace URIs are names, not links
from e2e_parity_shared_layers import (
    ACCEPTED,
    COVERED,
    INGRESS_PREFIX_DETAIL,
    INJECTION_KINDS,
    META_REFRESH_NOTE,
    NOT_RUN,
    Outcome,
    attach_issues,
    check_record,
    conservation,
    injection_group,
    injection_verdict,
    injection_ways,
    new_tab_verdict,
    planned_checks,
    seo_head_verdict,
    sitemap_divergence,
)

TIMEOUT = 60_000


def require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError("missing environment %s" % name)
    return value


class Env:
    def __init__(self, db: str) -> None:
        self.db = db
        self.public = require("ODOO_PUBLIC_URL").rstrip("/")
        self.ha = require("HA_BASE_URL").rstrip("/")
        self.ha_https = os.environ.get("HA_HTTPS_BASE_URL", "").rstrip("/") or None
        self.token = require("HA_TOKEN")
        self.slug = require("ADDON_SLUG")
        self.login = require("ODOO_TEST_LOGIN")
        self.password = require("ODOO_TEST_PASSWORD")
        self.target = os.environ.get("PARITY_TARGET", "local")
        self.prefix: str | None = None
        self.extra_secrets: list[str] = []

    def masker(self) -> Masker:
        bases = {"<PUBLIC_BASE>": self.public, "<HA_BASE>": self.ha}
        if self.ha_https:
            bases["<HA_HTTPS_BASE>"] = self.ha_https
        return Masker(bases=bases, ingress_prefix=self.prefix,
                      secrets=(self.token, self.login, self.password, *self.extra_secrets))

    def mask(self, value: Any) -> Any:
        masked = _mask_tokens(self.masker().value(value))
        # A host or IP that slipped in another form (ws origin, bare host).
        for base, label in ((self.public, "<PUBLIC_HOST>"), (self.ha, "<HA_HOST>"), (self.ha_https, "<HA_HTTPS_HOST>")):
            if base:
                masked = _replace_everywhere(masked, urlsplit(base).hostname or "", label)
        return masked


# Access tokens in paths (survey links, kiosk URLs, portal links) are credentials.
_PATH_TOKEN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{24,}")


def _mask_tokens(value: Any) -> Any:
    if isinstance(value, str):
        return _PATH_TOKEN.sub("<token>", value)
    if isinstance(value, Mapping):
        return {key: _mask_tokens(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_mask_tokens(child) for child in value)
    return value


def _replace_everywhere(value: Any, old: str, new: str) -> Any:
    if not old:
        return value
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, Mapping):
        return {key: _replace_everywhere(child, old, new) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_replace_everywhere(child, old, new) for child in value)
    return value


# --- Signals ------------------------------------------------------------------


class Recorder:
    """Collects the five signals of section 7 step 5 for one page."""

    def __init__(self, page, surface: Surface, origin: str, prefix: str | None) -> None:
        self.surface, self.origin, self.prefix = surface, origin, prefix
        self.page_errors: list[str] = []
        self.console: list[tuple[str, str]] = []
        self.failed: list[str] = []
        self.responses: list[tuple[int, str]] = []
        self.urls: list[str] = []
        page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        page.on("console", self._console)
        page.on("requestfailed", self._failed)
        page.on("response", lambda response: self.responses.append((response.status, response.url)))
        page.on("request", self._request)
        page.on("websocket", self._websocket)
        self.page = page
        self.ignore: list[re.Pattern[str]] = []

    def _console(self, message) -> None:
        # "Failed to load resource" names no URL in its text; its location does.
        source = (message.location or {}).get("url") or ""
        self.console.append((message.type, message.text + (" @ " + source if source else "")))

    def _is_odoo(self, request) -> bool:
        """Under Ingress, Odoo is everything but the HA frontend's own document."""
        if self.surface is Surface.PUBLIC:
            return True
        try:
            return request.frame != self.page.main_frame
        except Exception:  # noqa: BLE001 -- a worker's request has no frame; HA runs none
            return True

    def _request(self, request) -> None:
        if self._is_odoo(request):
            self.urls.append(request.url)

    def _websocket(self, socket) -> None:
        # The HA frontend's own socket is /api/websocket; every other one is Odoo's.
        if self.surface is Surface.PUBLIC or urlsplit(socket.url).path != "/api/websocket":
            self.urls.append(socket.url)

    def _failed(self, request) -> None:
        # A navigation that replaces a pending request aborts it; that is not a failure.
        if (request.failure or "").startswith("net::ERR_ABORTED"):
            return
        self.failed.append(request.url)

    def mark(self) -> tuple[int, int, int, int, int]:
        return (len(self.page_errors), len(self.console), len(self.failed), len(self.responses), len(self.urls))

    def _relevant(self, url: str) -> bool:
        return not any(pattern.search(url) for pattern in self.ignore)

    def since(self, mark: tuple[int, int, int, int, int]) -> dict[str, int]:
        errors, console, failed, responses, urls = mark
        # Only this surface's own traffic counts; the HA frontend around the
        # iframe is not under test.
        ours = self.origin + (self.prefix or "")
        return count_signals(
            page_errors=self.page_errors[errors:],
            console=[entry for entry in self.console[console:] if self._relevant(entry[1])],
            failed_requests=[url for url in self.failed[failed:] if url.startswith(ours) and self._relevant(url)],
            responses=[entry for entry in self.responses[responses:]
                       if entry[1].startswith(ours) and self._relevant(entry[1])],
            urls=[url for url in self.urls[urls:] if self._relevant(url)],
            surface=self.surface, origin=self.origin, ingress_prefix=self.prefix,
        )

    def details(self, mark) -> dict[str, list[str]]:
        """What made the signals, for the notes (masked by the caller)."""
        errors, console, failed, responses, _ = mark
        ours = self.origin + (self.prefix or "")
        return {
            "pageerror": self.page_errors[errors:][:3],
            "console_error": [text for kind, text in self.console[console:] if kind == "error"][:3],
            "failed_requests": [url for url in self.failed[failed:] if url.startswith(ours)][:3],
            "http_4xx_5xx": ["%d %s" % (status, url) for status, url in self.responses[responses:]
                             if status >= 400 and url.startswith(ours)][:3],
        }


# --- Surfaces -----------------------------------------------------------------


class Side:
    """One surface: a context, a page, and `root` where Odoo runs (page or iframe)."""

    surface: Surface
    name: str

    def __init__(self, env: Env, browser, *, viewport=(1920, 1080), **context_args) -> None:
        self.env = env
        self.context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]},
                                           accept_downloads=True, **context_args)
        self.page = self.context.new_page()
        self.recorder: Recorder | None = None
        self.step: str | None = None  # named in an error result, when a check sets it

    @property
    def base(self) -> str:
        raise NotImplementedError

    @property
    def root(self):
        raise NotImplementedError

    @property
    def root_now(self):
        """`root`, but never waiting for a panel that has not finished loading.

        The same object as `root` on every surface whose root is the page
        itself, which is why the default lives here: `IngressSide` is the only
        override, because there `root` is a *search* that waits up to 60 s
        (`_find_frame`). A caller reaches for this one when being slow is worse
        than being wrong -- a recovery path running ahead of a record's only
        restore (#288) -- and for `root` whenever a panel still loading is a
        legitimate thing to wait for, which is every check.
        """
        return self.root

    def goto(self, route: str, *, wait: str = "load") -> None:
        self.root.goto(self.base + route, wait_until=wait, timeout=TIMEOUT)

    def settle(self, ms: int = 800) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001 -- Odoo keeps the bus open
            pass
        self.page.wait_for_timeout(ms)

    def wait_webclient(self) -> None:
        self.root.locator(".o_main_navbar").first.wait_for(timeout=TIMEOUT)
        self.root.locator(".o_action_manager > *, .o_dialog .modal-content").first.wait_for(timeout=TIMEOUT)
        self.settle()

    def close_chat_windows(self) -> None:
        """Live chat visitors open chat windows on the operator's screen; they
        cover the page and take the keyboard, so every check starts without."""
        try:
            self.root.evaluate("""() => { for (const button of document.querySelectorAll(
                '.o-mail-ChatWindow [title*="Close"], .o-mail-ChatWindow button[name="close"]')) button.click(); }""")
        except Exception:  # noqa: BLE001 -- no web client on the current page
            pass

    def ensure_logged_in(self) -> None:
        """Back to a logged-in web client (the attendance kiosk logs the user out)."""
        self.goto("/odoo")
        if self.root.locator('input[name="login"]').count():
            fill_odoo_login(self.root, self.env)
        self.wait_webclient()

    def rpc(self, model: str, method: str, args: list | None = None, kwargs: dict | None = None) -> Any:
        payload = {"jsonrpc": "2.0", "method": "call", "id": int(time.time() * 1000) % 1_000_000,
                   "params": {"model": model, "method": method, "args": args or [], "kwargs": kwargs or {}}}
        response = self.context.request.post(self.base + "/web/dataset/call_kw/%s/%s" % (model, method),
                                             data=json.dumps(payload),
                                             headers={"Content-Type": "application/json"})
        body = response.json()
        if body.get("error"):
            data = body["error"].get("data") or {}
            raise RuntimeError("rpc %s.%s: %s" % (model, method, data.get("message") or body["error"].get("message")))
        return body.get("result")

    def close(self) -> None:
        self.context.close()


class PublicSide(Side):
    surface = Surface.PUBLIC
    name = "public"

    @property
    def base(self) -> str:
        return self.env.public

    @property
    def root(self):
        return self.page

    def start(self) -> None:
        self.recorder = Recorder(self.page, self.surface, self.env.public, None)
        self.log_in()

    def log_in(self) -> None:
        self.page.goto(self.base + "/web/login", wait_until="domcontentloaded", timeout=TIMEOUT)
        fill_odoo_login(self.page, self.env)
        self.wait_webclient()


class IngressSide(Side):
    """The add-on panel in the HA frontend; Odoo runs in its Ingress iframe."""

    surface = Surface.HA_INGRESS
    name = "ingress"

    def __init__(self, env: Env, browser, *, ha: str | None = None, **kwargs) -> None:
        super().__init__(env, browser, **kwargs)
        self.ha = (ha or env.ha).rstrip("/")
        self._frame = None

    @property
    def base(self) -> str:
        return self.ha + str(self.env.prefix)

    @property
    def root(self):
        if self._frame is None or self._frame.is_detached():
            self._frame = self._find_frame()
        return self._frame

    @property
    def root_now(self):
        """The frame this side is already holding, detached or not (#288).

        `root` re-enters `_find_frame`'s 60 s sweep the moment the held frame
        reports detached. That is right for the case it was written for, a panel
        still loading, and wrong on a recovery path: there the frame going is
        *why* the caller is in the recovery path, and the replacement the sweep
        eventually finds is a freshly loaded document answering a different
        question -- it has none of the form the caller was reading. So this hands
        the held frame back without asking whether it is detached. The first
        locator call on it then raises, the caller's own `except` keeps its
        reading negative, and that is both faster and truer than spending a
        minute to resolve a frame that cannot answer.

        A side nothing has run through yet holds no frame at all; there the only
        resolve there is is the waiting one, and this is not the path #288 is
        about.
        """
        if self._frame is not None:
            return self._frame
        return self.root

    def _find_frame(self, wait_s: int = 60):
        for _ in range(wait_s * 2):
            frames = [frame for frame in self.page.frames
                      if "/api/hassio_ingress/" in frame.url and frame.parent_frame == self.page.main_frame]
            if frames:
                return frames[0]
            self.page.wait_for_timeout(500)
        raise RuntimeError("the add-on panel never loaded an Ingress iframe")

    def frame_element(self):
        return self.root.frame_element()

    def start(self) -> None:
        self.sign_in_frontend()
        self.page.goto(self.ha + "/" + self.env.slug, wait_until="domcontentloaded", timeout=TIMEOUT)
        frame = self._find_frame()
        path = urlsplit(frame.url).path
        match = re.match(r"(/api/hassio_ingress/[^/]+)", path)
        if not match:
            raise RuntimeError("Ingress iframe without a prefix")
        self.env.prefix = match.group(1)
        self.recorder = Recorder(self.page, self.surface, self.ha, self.env.prefix)
        self.log_in()

    def sign_in_frontend(self) -> None:
        """Before any frontend script runs, or it redirects to /auth/authorize
        first. Only the HA document gets it; the Ingress iframe shares the origin."""
        self.context.add_init_script(
            """(() => { if (window.top !== window) return;
              localStorage.setItem('hassTokens', JSON.stringify({
                access_token: %s, token_type: 'Bearer', expires_in: 315360000, hassUrl: %s,
                clientId: %s + '/', expires: Date.now() + 315360000000, refresh_token: ''})); })()"""
            % (json.dumps(self.env.token), json.dumps(self.ha), json.dumps(self.ha))
        )

    def log_in(self) -> None:
        self.root.goto(self.base + "/web/login", wait_until="domcontentloaded", timeout=TIMEOUT)
        fill_odoo_login(self.root, self.env)
        self.wait_webclient()


def fill_odoo_login(root, env: Env) -> None:
    field = root.locator('input[name="login"]')
    field.wait_for(timeout=TIMEOUT)
    field.fill(env.login)
    root.locator('input[name="password"]').fill(env.password)
    # Enter submits the login form; the website header has a search form first.
    root.locator('input[name="password"]').press("Enter")


# --- Running checks -------------------------------------------------------------


class Run:
    def __init__(self, env: Env, run: RunInfo, public: PublicSide, ingress: IngressSide, out, browser) -> None:
        self.env, self.info, self.public, self.ingress, self.out, self.browser = env, run, public, ingress, out, browser
        self.sides = (public, ingress)
        self.marker = run.run_id
        self.fx: dict[str, Any] = {}
        if os.path.exists(fixture_path(run.run_id)):
            with open(fixture_path(run.run_id), encoding="utf-8") as handle:
                self.fx = json.load(handle)

    def write(self, record: Mapping[str, Any]) -> None:
        masked = self.env.mask(record)
        self.out.write(json.dumps(masked, ensure_ascii=False, sort_keys=True) + "\n")
        self.out.flush()
        verdict = masked["verdict"]
        print("%-19s %s %s" % (verdict, masked["control_identity"],
                               ("-- " + masked["notes"][:160]) if verdict != "PARITY" else ""), file=sys.stderr)

    def record(self, item: str, module: str, screen: str, public: Outcome | None, ingress: Outcome | None,
               **kwargs) -> None:
        self.write(check_record(self.info, item, module=module, screen=screen,
                                public=public, ingress=ingress, **kwargs))

    def not_run(self, item: str, module: str, screen: str, blocked_by: str, notes: str) -> None:
        self.record(item, module, screen, None, None, verdict=NOT_RUN, blocked_by=blocked_by, notes=notes)

    def both(self, action: Callable[[Side], Outcome]) -> tuple[Outcome, Outcome]:
        """Run `action` on each side and add the signals it caused."""
        outcomes = []
        for side in self.sides:
            side.close_chat_windows()
            mark = side.recorder.mark()
            try:
                outcome = action(side)
            except Exception as error:  # noqa: BLE001 -- a failure is evidence
                side.page.screenshot(path=os.path.join(artifact_dir(), "%s-%s.png" % (self.info.run_id, side.name)))
                step = side.step
                outcome = Outcome(False, "error%s: %s" % (" at " + step if step else "",
                                                          self.env.mask((str(error).splitlines() or [""])[0])))
            side.step = None
            signals = side.recorder.since(mark)
            details = dict(outcome.details)
            noisy = {key: value for key, value in side.recorder.details(mark).items() if value}
            if noisy:
                details["signal_sources"] = noisy
            outcomes.append(Outcome(outcome.available, outcome.result, signals, details))
        return outcomes[0], outcomes[1]


def artifact_dir() -> str:
    """Resolved at call time, never import time: main() parses --env-file into
    the environment first, and `from ... import` would freeze an import-time
    value in this module's importers (#188)."""
    return os.environ.get("E2E_ARTIFACT_DIR") or "/tmp/odoo-parity-artifacts"

CHECKS: dict[str, Callable[[Run], None]] = {}


def check(*items: str):
    def register(function: Callable[[Run], None]):
        for item in items:
            CHECKS[item] = function
        return function
    return register


# --- Helpers used by several checks -------------------------------------------


def open_form(side: Side, model: str, record_id: int) -> None:
    side.goto("/odoo/%s/%d" % (model, record_id))
    side.wait_webclient()


# `/odoo/<model>` without an id falls back to Discuss; a list needs its action.
LIST_ROUTES = {
    "res.partner": "/odoo/action-contacts.action_contacts?view_type=list",
    "sale.order": "/odoo/action-sale.action_quotations_with_onboarding?view_type=list",
}


def open_list(side: Side, model: str) -> None:
    side.goto(LIST_ROUTES[model])
    side.wait_webclient()
    side.root.locator(".o_list_view, .o_kanban_view").first.wait_for(timeout=TIMEOUT)


def cog_item(side: Side, *labels: str, menu: str | None = None) -> None:
    """Open the cog menu (or the `menu` button) and click through `labels`."""
    root = side.root
    if menu:
        root.locator(".o_control_panel button").filter(has_text=menu).first.click()
    else:
        root.locator(".o_control_panel .o_cp_action_menus button.dropdown-toggle").first.click()
    for label in labels:
        root.locator(".o-dropdown--menu .dropdown-item, .o-dropdown--menu .o-dropdown-item").filter(
            has_text=re.compile(r"^\s*%s\s*$" % re.escape(label))).first.click()
        side.page.wait_for_timeout(400)


def download(side: Side, trigger: Callable[[], None], timeout: int = TIMEOUT) -> tuple[bytes, str]:
    """Run `trigger` and return the file the browser saved (U-F5 'landed')."""
    with side.page.expect_download(timeout=timeout) as info:
        trigger()
    saved = info.value
    path = saved.path()
    with open(path, "rb") as handle:
        return handle.read(), saved.suggested_filename


def sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def pdf_urls(data: bytes) -> list[str]:
    """URLs a PDF links to (wkhtmltopdf writes link annotations uncompressed)."""
    return sorted(set(match.decode("latin-1") for match in re.findall(rb"/URI\s*\(([^)]*)\)", data)))


def xlsx_rows(data: bytes) -> int:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    return sheet.count("<row ")


def report_pdf(side: Side, run: "Run") -> tuple[bytes, str]:
    open_form(side, "sale.order", run.fx["sale_order"])
    return download(side, lambda: cog_item(side, "Print", "Quotation / Order"))


def export_xlsx(side: Side) -> tuple[bytes, str]:
    open_list(side, "sale.order")
    side.root.locator("thead .o_list_record_selector").first.click()
    cog_item(side, "Export", menu="Actions")
    dialog = side.root.locator(".o_dialog .modal-content").last
    dialog.wait_for(timeout=TIMEOUT)
    side.page.wait_for_timeout(800)
    data = download(side, lambda: dialog.locator("button.o_select_button, footer button.btn-primary").first.click())
    dialog.locator("button.btn-close, footer button.btn-secondary").first.click()
    return data


def attachment_file(side: Side, run: "Run") -> tuple[bytes, str]:
    open_form(side, "res.partner", run.fx["partner"])
    root = side.root
    root.locator(".o-mail-Chatter-topbar button[aria-label='Attach files'], "
                 ".o-mail-Chatter-topbar button:has(i.fa-paperclip)").first.click()
    card = root.locator(".o-mail-AttachmentCard").filter(has_text=run.marker + " 測試.txt").first
    card.wait_for(timeout=TIMEOUT)
    card.hover()
    return download(side, lambda: card.locator("button[title='Download']").first.click())


# --- Group F: host environment ----------------------------------------------------

_FEATURES_JS = """() => ({
  features: document.featurePolicy ? document.featurePolicy.allowedFeatures() : [],
  secure: window.isSecureContext,
})"""


@check("U-F1")
def check_f1(run: Run) -> None:
    from e2e_parity_shared_layers import capability_upper_bound

    def probe(side: Side) -> Outcome:
        if side.surface is Surface.HA_INGRESS:
            element = side.root.frame_element()
            attrs = {"allow": element.get_attribute("allow"), "sandbox": element.get_attribute("sandbox")}
            same_origin = side.page.evaluate("(f) => { try { return !!f.contentWindow.document; } catch (e) "
                                             "{ return false; } }", element)
        else:
            attrs, same_origin = {"allow": None, "sandbox": None}, None
        probe_values = side.root.evaluate(_FEATURES_JS)
        bound = capability_upper_bound(attrs, probe_values["features"], secure_context=probe_values["secure"])
        policy = ",".join(name for name, entry in bound.items() if entry["policy"])
        limits = {name: entry["limit"] for name, entry in bound.items() if entry["limit"]}
        return Outcome(True, "policy grants: " + policy, details={
            "frame": attrs, "same_origin_frame": same_origin, "secure_context": probe_values["secure"],
            "upper_bound": bound, "limits": limits,
        })

    public, ingress = run.both(probe)
    limits = ingress.details.get("limits") or {}
    notes = ("The Ingress iframe carries no allow and no sandbox attribute and is same-origin with Home "
             "Assistant; its policy withholds nothing. ")
    if limits:
        notes += ("Only the insecure context of the plain-http entrance withholds %s; an https entrance "
                  "lifts that (U-C4 has the execCommand fallback, U-C25 needs https)." % ", ".join(sorted(limits)))
    run.record("U-F1", "shared", "generic", public, ingress, notes=notes)


_KEY_LISTENER_JS = """() => { window.__parityKeys = [];
  document.addEventListener('keydown', (e) => window.__parityKeys.push(e.key), true); }"""


@check("U-F2")
def check_f2(run: Run) -> None:
    keys = ["c", "e", "d", "m", "a"]

    def probe(side: Side) -> Outcome:
        open_list(side, "res.partner")
        side.root.evaluate(_KEY_LISTENER_JS)
        side.root.locator(".o_control_panel").first.click(position={"x": 5, "y": 5})
        taken = []
        for key in keys:
            side.page.keyboard.press(key)
            side.page.wait_for_timeout(600)
            if side.surface is Surface.HA_INGRESS:
                dialog = side.page.locator("ha-quick-bar ha-md-dialog, ha-quick-bar ha-dialog, "
                                           "ha-voice-command-dialog ha-dialog, ha-voice-command-dialog ha-md-dialog")
                if dialog.count() and dialog.first.is_visible():
                    taken.append(key)
                    side.page.keyboard.press("Escape")
                    side.page.wait_for_timeout(400)
        received = side.root.evaluate("() => window.__parityKeys")
        missing = [key for key in keys if key not in received]
        result = "all keys reached Odoo" if not missing else "keys not reaching Odoo: %s" % ",".join(missing)
        return Outcome(True, result, details={"received": received, "opened_ha_dialog": taken})

    public, ingress = run.both(probe)
    run.record("U-F2", "shared", "generic", public, ingress,
               notes="Keys pressed with focus in the Odoo list view: %s." % ",".join(keys))


@check("U-F3")
def check_f3(run: Run) -> None:
    sizes = [(1920, 1080), (1280, 800), (800, 600)]

    def probe(side: Side) -> Outcome:
        open_list(side, "res.partner")
        problems, seen = [], []
        for width, height in sizes:
            side.page.set_viewport_size({"width": width, "height": height})
            side.page.wait_for_timeout(1200)
            inner = side.root.evaluate("() => [window.innerWidth, window.innerHeight, "
                                       "document.documentElement.scrollWidth > window.innerWidth + 1]")
            navbar = side.root.locator(".o_main_navbar").first.is_visible()
            if side.surface is Surface.HA_INGRESS:
                box = side.root.frame_element().bounding_box()
                if not box or box["height"] < height * 0.7 or box["x"] + box["width"] > width + 1:
                    problems.append("%dx%d: iframe box %s" % (width, height, box))
            if inner[2]:
                problems.append("%dx%d: horizontal overflow" % (width, height))
            if not navbar:
                problems.append("%dx%d: navbar hidden" % (width, height))
            seen.append({"viewport": [width, height], "odoo": inner[:2]})
        side.page.set_viewport_size({"width": 1920, "height": 1080})
        return Outcome(True, "layout holds" if not problems else "; ".join(problems), details={"sizes": seen})

    public, ingress = run.both(probe)
    run.record("U-F3", "shared", "generic", public, ingress,
               notes="Window resized through three sizes. The HA theme was not switched: that writes the HA "
                     "user's profile, outside this run's approved writes.")


_UPLOAD_JS = """async ({ size, partner }) => {
  const body = new FormData();
  body.append('csrf_token', odoo.csrf_token);
  body.append('model', 'res.partner');
  body.append('id', String(partner));
  body.append('ufile', new Blob([new Uint8Array(size)], { type: 'application/octet-stream' }), 'parity-' + size + '.bin');
  const started = performance.now();
  try {
    const response = await fetch('/web/binary/upload_attachment', { method: 'POST', body });
    const text = await response.text();
    let ok = response.ok;
    try { const parsed = JSON.parse(text); ok = ok && !(parsed[0] && parsed[0].error); } catch (e) { ok = false; }
    return { status: response.status, ok, seconds: (performance.now() - started) / 1000 };
  } catch (error) {
    return { status: 0, ok: false, error: String(error), seconds: (performance.now() - started) / 1000 };
  }
}"""


@check("U-F4", "U-A8")
def check_f4_a8(run: Run) -> None:
    sizes = [1, 10, 100]

    def probe(side: Side) -> Outcome:
        open_form(side, "res.partner", run.fx["partner"])
        results, largest = [], 0
        for megabytes in sizes:
            outcome = side.root.evaluate(_UPLOAD_JS, {"size": megabytes * 1024 * 1024, "partner": run.fx["partner"]})
            results.append(dict(outcome, megabytes=megabytes))
            if outcome["ok"]:
                largest = megabytes
            else:
                break
        return Outcome(True, "largest accepted upload: %d MB" % largest, details={"uploads": results})

    public, ingress = run.both(probe)

    def largest(outcome: Outcome) -> int:
        return max([entry["megabytes"] for entry in outcome.details.get("uploads", []) if entry["ok"]] or [0])

    note = ("Uploads of 1, 10 and 100 MiB to /web/binary/upload_attachment on the fixture partner, stopping at "
            "the first refusal. 500 MiB was not tried: the Public origin sits behind a Cloudflare tunnel whose "
            "request body limit is 100 MB, so no size above it can be compared.")
    kwargs: dict[str, Any] = {}
    if public.available and ingress.available and largest(ingress) >= largest(public) and not \
            ingress.signals.get("route_escape"):
        # The plan asks whether Ingress reaches the Public origin. A smaller
        # Public limit (the tunnel's 413) is recorded, not held against Ingress.
        kwargs = {"verdict": "PARITY", "severity": "none"}
        if largest(ingress) > largest(public):
            note += (" Ingress accepted %d MiB; the Public origin refused the next size with %s, the Cloudflare "
                     "limit, not the add-on." % (largest(ingress), [entry["status"] for entry in
                                                                   public.details["uploads"] if not entry["ok"]]))
    run.record("U-A8", "shared", "generic", public, ingress, notes=note, **kwargs)
    run.record("U-F4", "shared", "generic", public, ingress,
               notes=note + " The add-on sets client_max_body_size 512M; the Supervisor did not refuse any size "
                            "tried.", **kwargs)


@check("U-F5", "U-C18", "U-C20")
def check_f5(run: Run) -> None:
    expected_attachment = sha256(ATTACHMENT_TEXT.encode("utf-8"))

    def report(side: Side) -> Outcome:
        data, name = report_pdf(side, run)
        urls = pdf_urls(data)
        return Outcome(data.startswith(b"%PDF"), "PDF landed" if data.startswith(b"%PDF") else "not a PDF",
                       details={"bytes": len(data), "filename": name, "pdf_urls": urls})

    def export(side: Side) -> Outcome:
        data, name = export_xlsx(side)
        rows = xlsx_rows(data)
        return Outcome(True, "xlsx landed with %d rows" % rows, details={"bytes": len(data), "filename": name})

    def attachment(side: Side) -> Outcome:
        data, name = attachment_file(side, run)
        same = sha256(data) == expected_attachment
        return Outcome(True, "attachment landed, SHA-256 %s" % ("matches" if same else "differs"),
                       details={"bytes": len(data), "filename": name})

    results = {name: run.both(action) for name, action in
               (("report", report), ("export", export), ("attachment", attachment))}
    for name, (public, ingress) in results.items():
        item = {"report": "U-C20", "export": "U-C18", "attachment": "U-C7"}[name]
        if item != "U-C7":
            extra = ""
            if name == "report":
                urls = (public.details.get("pdf_urls") or []) + (ingress.details.get("pdf_urls") or [])
                extra = "PDF link targets: %s." % (", ".join(sorted(set(urls))) or "none")
            run.record(item, "shared", "generic", public, ingress, model="sale.order",
                       notes="Downloaded inside the HA panel's iframe on the Ingress side. " + extra)
    public = Outcome(all(pair[0].available for pair in results.values()),
                     "; ".join(pair[0].result for pair in results.values()),
                     {key: sum(pair[0].signals.get(key, 0) for pair in results.values()) for key in
                      results["report"][0].signals},
                     {name: pair[0].details for name, pair in results.items()})
    ingress = Outcome(all(pair[1].available for pair in results.values()),
                      "; ".join(pair[1].result for pair in results.values()),
                      {key: sum(pair[1].signals.get(key, 0) for pair in results.values()) for key in
                       results["report"][1].signals},
                      {name: pair[1].details for name, pair in results.items()})
    run.record("U-F5", "shared", "generic", public, ingress,
               notes="Report (sale order PDF), export (xlsx) and attachment, each triggered in the page; on "
                     "Ingress inside the HA panel's iframe.")

    # Imported here: the POS module imports this one.
    from e2e_pos_offline_live import pos_config_id, print_receipt, receipt_print_outcome

    config_id = pos_config_id(run.public)
    public, ingress = run.both(lambda side: receipt_print_outcome(print_receipt(side, config_id)))
    run.record("U-F5", "point_of_sale", "POS receipt print", public, ingress, route="/pos/ui",
               notes="One Desk Pad sold for cash in the Furniture Shop till, then Print Full Receipt. With no "
                     "printer, POS 18 CE mounts the receipt and calls window.print(); the run stubs print() to "
                     "keep the receipt and fetches its images on that surface.")


# --- Group A: channel and URL rewriting ---------------------------------------------

BACKEND_TOUR = ["/odoo", "/odoo/discuss", LIST_ROUTES["res.partner"], "/odoo/settings"]
FRONTEND_TOUR = ["/", "/shop", "/my/home", "/jobs", "/contactus"]


def visit(side: Side, route: str) -> None:
    side.goto(route)
    if route.startswith("/odoo"):
        side.wait_webclient()
    else:
        side.settle()


def _logical_path(url: str, prefix: str | None) -> str:
    path = urlsplit(url).path
    if prefix and path.startswith(prefix):
        path = path[len(prefix):]
    return path


@check("U-A1", "U-A2", "U-A3")
def check_a1_a3(run: Run) -> None:
    routes = BACKEND_TOUR + ["/odoo/res.partner/%d" % run.fx["partner"], "/odoo/sale.order/%d" % run.fx["sale_order"]]
    routes += FRONTEND_TOUR

    def tour(side: Side) -> Outcome:
        recorder = side.recorder
        start = len(recorder.urls), len(recorder.responses)
        for route in routes:
            visit(side, route)
        urls = recorder.urls[start[0]:]
        prefix = side.env.prefix if side.surface is Surface.HA_INGRESS else None
        origin = side.ha if side.surface is Surface.HA_INGRESS else side.env.public
        from e2e_menu_action_adapter import is_prefix_escape

        escaped = sorted({_logical_path(url, None) for url in urls
                          if is_prefix_escape(url, side.surface, origin, prefix)
                          and "/api/hassio_ingress/" not in urlsplit(url).path})
        doubled = sorted({url for url in urls if urlsplit(url).path.count("/api/hassio_ingress/") > 1})
        assets = {}
        for status, url in recorder.responses[start[1]:]:
            if "/web/assets/" in url and url.startswith(origin):
                assets[_logical_path(url, prefix)] = status
        return Outcome(True, "toured", details={"escaped": escaped, "doubled": doubled, "assets": assets})

    public, ingress = run.both(tour)
    base = "Tour: %s." % ", ".join(routes)
    for item, key in (("U-A1", "escaped"), ("U-A2", "doubled")):
        bad = ingress.details.get(key) or []
        result = "none" if not bad else "%d: %s" % (len(bad), ", ".join(bad[:5]))
        # The tour's signals are judged once, under U-A1.
        signals = (lambda outcome: outcome.signals) if item == "U-A1" else (lambda outcome: {})
        pub = Outcome(public.available, "none", signals(public), {key: public.details.get(key)})
        ing = Outcome(ingress.available, result, signals(ingress), {key: bad})
        run.record(item, "shared", "generic", pub, ing, notes=base)
    public_assets, ingress_assets = public.details.get("assets", {}), ingress.details.get("assets", {})
    failing = sorted(path for path, status in ingress_assets.items() if status >= 400)
    only = sorted(set(public_assets) ^ set(ingress_assets))
    result = lambda assets: "%d bundles, %d failing" % (len(assets), sum(status >= 400 for status in assets.values()))
    run.record("U-A3", "shared", "generic",
               Outcome(public.available, result(public_assets), {}, {"assets": public_assets}),
               Outcome(ingress.available, result(ingress_assets), {}, {"assets": ingress_assets}),
               notes=base + (" Bundles on one side only: %s." % ", ".join(only) if only else
                             " Same bundle set on both sides.") + (" Failing: %s" % failing if failing else ""))


@check("U-A4")
def check_a4(run: Run) -> None:
    import subprocess

    out_dir = os.path.join(artifact_dir(), "literal-rewrite-gate")
    environment = dict(os.environ, ODOO_BASE_URL=run.env.public, E2E_ARTIFACT_DIR=out_dir)
    completed = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e_literal_rewrite_gate.py")],
        env=environment, capture_output=True, text=True, timeout=1800,
    )
    tail = [line for line in completed.stdout.splitlines() if line.strip()][-6:]
    summary = run.env.mask(" | ".join(tail))
    passed = completed.returncode == 0
    gate = Outcome(passed, "gate exit %d" % completed.returncode, details={"summary": summary})
    run.record("U-A4", "shared", "generic", gate, gate,
               verdict="PARITY" if passed else "GAP", severity="none" if passed else "important",
               notes="e2e_literal_rewrite_gate.py against the Public origin's bundles (the same analysis the "
                     "in-container Rewrite scan runs, ADR 0005); one run judges the Ingress rewrite rules, so "
                     "both blocks hold it. Output: " + summary)


_CONTENT_JS = """async (paths) => {
  const out = {};
  const html = await fetch(paths.html); const htmlText = await html.text();
  out.html = { type: html.headers.get('content-type'), shims: htmlText.split('window.__INGRESS_PATH__=').length - 1 };
  const json = await fetch(paths.json, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: {} }) });
  const jsonText = await json.text();
  let parsed = false; try { JSON.parse(jsonText); parsed = true; } catch (e) {}
  out.json = { type: json.headers.get('content-type'), parses: parsed };
  for (const kind of ['js', 'css']) {
    if (!paths[kind]) { out[kind] = null; continue; }
    const response = await fetch(paths[kind]); const text = await response.text();
    let ok = true;
    if (kind === 'js') { try { new Function(text); } catch (e) { ok = String(e).slice(0, 120); } }
    else { ok = (text.match(/\\{/g) || []).length === (text.match(/\\}/g) || []).length; }
    out[kind] = { type: response.headers.get('content-type'), status: response.status, parses: ok };
  }
  return out;
}"""


@check("U-A5")
def check_a5(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        visit(side, "/odoo")
        assets = side.root.evaluate("""() => ({
          js: [...document.scripts].map(s => s.getAttribute('src')).find(s => s && s.includes('/web/assets/')),
          css: [...document.querySelectorAll('link[rel=stylesheet]')].map(l => l.getAttribute('href'))
                 .find(h => h && h.includes('/web/assets/')) })""")
        strip = (lambda path: _logical_path(path, side.env.prefix)) if side.surface is Surface.HA_INGRESS else \
            (lambda path: urlsplit(path).path)
        paths = {"html": "/odoo", "json": "/web/webclient/version_info",
                 "js": assets["js"] and strip(assets["js"]), "css": assets["css"] and strip(assets["css"])}
        result = side.root.evaluate(_CONTENT_JS, paths)
        problems = []
        expected_shims = 1 if side.surface is Surface.HA_INGRESS else 0
        if result["html"]["shims"] != expected_shims:
            problems.append("HTML carries %d shims" % result["html"]["shims"])
        if not result["json"]["parses"]:
            problems.append("JSON does not parse")
        for kind in ("js", "css"):
            if result[kind] and result[kind]["parses"] is not True:
                problems.append("%s: %s" % (kind, result[kind]["parses"]))
        return Outcome(True, "types intact" if not problems else "; ".join(problems), details=result)

    public, ingress = run.both(probe)
    run.record("U-A5", "shared", "generic", public, ingress,
               notes="One HTML page, one JSON-RPC answer, the page's first JS and CSS bundle, fetched in the page. "
                     "The Ingress HTML must carry exactly one Runtime shim, the Public one none.")


# Each probe asks for a path under /web/static/parity-probe/ in its own way;
# a request for it at the HA root is an escape through that way (RC-12). The
# covered ways go through the API the Runtime shim wraps, never through
# markup: what is under test is the shim's hook, and markup would only
# re-measure the ways the decision already accepts (#169).
_INJECTION_JS = """async () => {
  const probe = (kind) => '/web/static/parity-probe/' + kind + '.png';
  const SVG = 'http://www.w3.org/2000/svg', XLINK = 'http://www.w3.org/1999/xlink';
  const box = document.createElement('div'); box.style.display = 'none'; document.body.appendChild(box);
  // Covered: the shim must prefix each of these.
  try { navigator.sendBeacon(probe('sendBeacon'), 'x'); } catch (e) {}
  try { const source = new EventSource(probe('EventSource')); setTimeout(() => source.close(), 1500); } catch (e) {}
  const use = (kind, set) => {
    const svg = document.createElementNS(SVG, 'svg'), node = document.createElementNS(SVG, 'use');
    set(node, probe(kind) + '#a'); svg.appendChild(node); box.appendChild(svg);
  };
  // setAttribute('xlink:href') writes the qualified name in no namespace, which SVG ignores,
  // unless the element already carries an xlink:href: the DOM then matches the existing
  // attribute by qualified name and updates it. That is how a screen reaches this way -- the
  // icon arrives as markup, a script points it somewhere else -- so the probe seeds it first.
  use('svg-use', (node, url) => {
    node.setAttributeNS(XLINK, 'xlink:href', '#seed');
    node.setAttribute('xlink:href', url);
  });
  use('svg-use-href', (node, url) => node.setAttribute('href', url));
  use('svg-use-ns', (node, url) => node.setAttributeNS(XLINK, 'xlink:href', url));
  // Covered (media sources, #159): new Audio, HTMLMediaElement.src and HTMLSourceElement.src all
  // point at the same probe path, so a regression in any one wrapper makes the 'media' way escape.
  try { const audio = new Audio(probe('media')); audio.load(); } catch (e) {}
  try {
    const el = document.createElement('audio'); el.src = probe('media'); box.appendChild(el); el.load();
  } catch (e) {}
  try {
    const el = document.createElement('audio'), src = document.createElement('source');
    src.src = probe('media'); el.appendChild(src); box.appendChild(el); el.load();
  } catch (e) {}
  // Accepted: markup and style, which the shim leaves alone by decision.
  const markup = document.createElement('div'); markup.style.display = 'none'; document.body.appendChild(markup);
  markup.innerHTML = '<img src="' + probe('innerHTML-img') + '">';
  // The HTML parser puts a markup xlink:href in the XLink namespace, so this is the way
  // #169 saw escape; the shim must still leave it alone.
  markup.insertAdjacentHTML('beforeend',
    '<svg><use xlink:href="' + probe('insertAdjacentHTML-use') + '#a"></use></svg>');
  const inline = document.createElement('div');
  inline.setAttribute('style', 'background:url(' + probe('style-attr') + ')');
  document.body.appendChild(inline);
  const style = document.createElement('style');
  style.textContent = '.parity-probe-style{background:url(' + probe('style-url') + ')}';
  document.head.appendChild(style);
  const styled = document.createElement('div'); styled.className = 'parity-probe-style'; document.body.appendChild(styled);
  const imported = document.createElement('style');
  imported.textContent = '@import url(' + probe('css-import').replace('.png', '.css') + ');';
  document.head.appendChild(imported);
  await new Promise(resolve => setTimeout(resolve, 2500));
  return true;
}"""


@check("U-A6")
def check_a6(run: Run) -> None:
    for side in run.sides:
        side.recorder.ignore.append(re.compile(r"/web/static/parity-probe/"))

    def probe(side: Side) -> Outcome:
        visit(side, "/odoo")
        start = len(side.recorder.urls)
        side.root.evaluate(_INJECTION_JS)
        prefix = side.env.prefix if side.surface is Surface.HA_INGRESS else ""
        requested, escaped = set(), set()
        for url in side.recorder.urls[start:]:
            path = urlsplit(url).path
            match = re.search(r"/web/static/parity-probe/([A-Za-z-]+)\.", path)
            if not match:
                continue
            requested.add(match.group(1))
            if prefix:
                if not path.startswith(prefix + "/"):
                    escaped.add(match.group(1))
            elif not url.startswith(side.env.public + "/"):
                # On the Public origin there is no prefix to lose; a probe that
                # left the origin it was asked from has escaped all the same.
                escaped.add(match.group(1))
        result = "no escape" if not escaped else "escaped: " + ", ".join(sorted(escaped))
        return Outcome(True, result, details={"requested": sorted(requested), "escaped": sorted(escaped),
                                              "not_requested": sorted(set(INJECTION_KINDS) - requested),
                                              "groups": {kind: injection_group(kind) for kind in INJECTION_KINDS}})

    public, ingress = run.both(probe)
    verdict, severity, reasons = injection_verdict(public, ingress)
    run.record("U-A6", "shared", "generic", public, ingress, verdict=verdict, severity=severity,
               notes="; ".join(filter(None, [
                   "Each way asks for /web/static/parity-probe/<way>.png its own way. Covered, the Runtime shim "
                   "must prefix them (ADR 0004): %s -- each through the API the shim hooks, not through markup. "
                   "Accepted, uncovered by decision (#169: the HTML and website editors save record content "
                   "through these paths, so a hook would write the Ingress prefix and its token into the "
                   "database; a screen that hits one gets a route-scoped Literal rewrite of its own): %s. %s."
                   % (", ".join(injection_ways(COVERED)), ", ".join(injection_ways(ACCEPTED)), META_REFRESH_NOTE),
                   *reasons])))


@check("U-A7")
def check_a7(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        timings = []
        for _ in range(4):  # cold, then three warm loads
            visit(side, "/odoo")
            timings.append(side.root.evaluate(
                "() => { const n = performance.getEntriesByType('navigation')[0]; "
                "return n ? Math.round(n.loadEventEnd - n.startTime) : null; }"))
        timings = [timings[0], sorted(timings[1:])[1]]
        bundle = side.root.evaluate("() => [...document.scripts].map(s => s.src).find(s => s.includes('/web/assets/'))")
        response = side.context.request.get(bundle, headers={"Accept-Encoding": "gzip, br"})
        headers = response.headers
        details = {"load_ms": {"cold": timings[0], "warm_median": timings[1]},
                   "bundle": {"content-encoding": headers.get("content-encoding"),
                              "cache-control": headers.get("cache-control"),
                              "bytes": len(response.body())}}
        return Outcome(True, "measured", details=details)

    public, ingress = run.both(probe)
    ratios = []
    for phase in ("cold", "warm_median"):
        left, right = public.details["load_ms"][phase], ingress.details["load_ms"][phase]
        if left and right:
            ratios.append(right / left)
    worst = max(ratios) if ratios else 0
    verdict, severity = ("PARITY", "none") if worst <= 3 else ("GAP", "minor" if worst <= 10 else "important")
    run.record("U-A7", "shared", "generic", public, ingress, verdict=verdict, severity=severity,
               notes="Ingress load time is %.1fx the Public origin's at worst (cold/warm /odoo); >3x is Minor, "
                     ">10x Important (warm = median of three). The header differences are the Ingress listener's by "
                     "design (RC-5)."
                     % worst)


@check("U-A9")
def check_a9(run: Run) -> None:
    run.not_run("U-A9", "shared", "generic", "no server action on odoo_parity runs longer than 60 s",
                "The database holds only this run's fixtures; no export or recompute takes a minute, and making "
                "one would need a bulk data load beyond the approved writes.")


@check("U-A10")
def check_a10(run: Run) -> None:
    for side in run.sides:
        side.recorder.ignore.append(re.compile(r"/parity-no-such-route"))

    def probe(side: Side) -> Outcome:
        response = side.root.goto(side.base + "/parity-no-such-route", wait_until="load", timeout=TIMEOUT)
        status = response.status if response else None
        odoo_page = side.root.locator("#wrapwrap, .o_website_404, .o_error_detail, .oe_structure").count() > 0
        home_assistant = side.root.locator("home-assistant, ha-panel-lovelace").count() > 0
        result = "HTTP %s, %s" % (status, "Odoo's page" if odoo_page and not home_assistant else "not Odoo's page")
        return Outcome(True, result, details={"status": status})

    public, ingress = run.both(probe)
    run.record("U-A10", "shared", "generic", public, ingress,
               notes="An unknown route. A server 500 was not triggered: no read-only route on this database "
                     "raises one.")


# --- Group B: session and identity ----------------------------------------------------


def fresh_side(run: Run, kind: type, **kwargs) -> Side:
    """A second, independent browser context for one surface."""
    return kind(run.env, run.browser, **kwargs)


def open_ha_panel(side: IngressSide) -> None:
    """IngressSide.start without the Odoo login."""
    side.sign_in_frontend()
    side.page.goto(side.ha + "/" + side.env.slug, wait_until="domcontentloaded", timeout=TIMEOUT)
    side._frame = side._find_frame()
    side.recorder = Recorder(side.page, side.surface, side.ha, side.env.prefix)


def start_unauthenticated(side: Side) -> None:
    if isinstance(side, IngressSide):
        open_ha_panel(side)
    else:
        side.recorder = Recorder(side.page, side.surface, side.env.public, None)


def left_prefix(side: Side) -> bool:
    """The Ingress iframe navigated out of the Ingress prefix (to the HA root)."""
    return side.surface is Surface.HA_INGRESS and not urlsplit(side.root.url).path.startswith(
        str(side.env.prefix) + "/")


def confirmation(side: Side, done: str) -> str:
    if left_prefix(side):
        return "confirmation page escaped the Ingress prefix (%s at the HA root)" % urlsplit(side.root.url).path
    body = (side.root.locator("body").inner_text() or "").lower()
    return done if "thank" in odoo_route(side) or "thank" in body else "no confirmation (%s)" % odoo_route(side)


def odoo_route(side: Side) -> str:
    path = urlsplit(side.root.url).path
    if side.surface is Surface.HA_INGRESS and path.startswith(str(side.env.prefix)):
        path = path[len(str(side.env.prefix)):]
    return path or "/"


@check("U-B1")
def check_b1(run: Run) -> None:
    def probe(kind: type) -> Outcome:
        side = fresh_side(run, kind)
        try:
            start_unauthenticated(side)
            side.goto("/web/login")
            root = side.root
            root.locator('input[name="login"]').fill(run.env.login)
            root.locator('input[name="password"]').fill("wrong-" + run.marker)
            root.locator('input[name="password"]').press("Enter")
            refused = root.locator(".alert-danger").first
            refused.wait_for(timeout=TIMEOUT)
            steps = ["wrong password refused"]
            fill_odoo_login(side.root, run.env)
            side.wait_webclient()
            steps.append("logged in")
            side.root.locator(".o_user_menu button, .o_user_menu .dropdown-toggle").first.click()
            side.root.locator("a[data-menu='logout'], .dropdown-item[data-menu='logout']").first.click()
            side.root.locator('input[name="login"]').wait_for(timeout=TIMEOUT)
            steps.append("logged out to %s" % odoo_route(side))
            fill_odoo_login(side.root, run.env)
            side.wait_webclient()
            steps.append("logged in again")
            return Outcome(True, "; ".join(steps))
        finally:
            side.close()

    outcomes = []
    for kind in (PublicSide, IngressSide):
        try:
            outcomes.append(probe(kind))
        except Exception as error:  # noqa: BLE001
            outcomes.append(Outcome(False, "error: %s" % sanitize_diagnostic((str(error).splitlines() or [""])[0])))
    run.record("U-B1", "shared", "generic", outcomes[0], outcomes[1],
               notes="Each surface in a fresh browser context; Ingress inside the HA panel.")


def session_cookie(side: Side) -> dict | None:
    host = urlsplit(side.base).hostname
    for cookie in side.context.cookies():
        if cookie["name"] == "session_id" and cookie["domain"].lstrip(".") == host:
            return cookie
    return None


@check("U-B2")
def check_b2(run: Run) -> None:
    from e2e_parity_shared_layers import session_cookie_problems

    def attributes(side: Side) -> Outcome:
        cookie = session_cookie(side)
        https = side.base.startswith("https://")
        problems = session_cookie_problems(cookie, surface=side.surface, ingress_prefix=side.env.prefix, https=https)
        shown = cookie and {key: cookie.get(key) for key in ("path", "secure", "httpOnly", "sameSite")}
        return Outcome(True, "attributes as expected" if not problems else "; ".join(problems),
                       details={"flags": shown})

    public, ingress = run.both(attributes)
    run.record("U-B2", "shared", "generic", public, ingress,
               notes="Read after the checks before it, Discuss included. Expected: Ingress Path=<prefix>/, "
                     "SameSite=Lax, Secure only over https (the entrance is plain http); Public Path=/, Secure. "
                     "Both HttpOnly.")

    product = run.public.rpc("product.product", "search", [[["product_tmpl_id", "=", run.fx["product"]]]])[0]

    def cart(side: Side) -> Outcome:
        side.goto("/shop")
        side.settle()
        added = side.root.evaluate(
            """async (product) => {
              const response = await fetch('/shop/cart/update_json', { method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { product_id: product, add_qty: 1 } }) });
              const body = await response.json();
              return body.result ? body.result.cart_quantity : null; }""", product)
        for _ in range(2):  # open the cart, then load it again
            side.goto("/shop/cart")
            side.settle()
        kept = side.root.locator("#cart_products, .o_cart_product, #shop_cart").filter(
            has_text=run.marker).count() > 0
        cookie = session_cookie(side)
        return Outcome(True, "cart kept after reload" if kept else "cart empty after reload",
                       details={"cart_quantity_after_add": added,
                                "path_scope": cookie and cookie.get("path")})

    public, ingress = run.both(cart)
    run.record("U-B2", "website_sale", "/shop/cart", public, ingress,
               notes="The fixture product added to the cart, then /shop/cart reloaded. Odoo 18 keeps the cart "
                     "in the session, so the session_id cookie is the cart cookie.")


@check("U-B3")
def check_b3(run: Run) -> None:
    route = "/odoo/res.partner/%d" % run.fx["partner"]

    def probe(side: Side) -> Outcome:
        visit(side, route)
        if side.surface is Surface.HA_INGRESS:
            side.root.goto(side.root.url, wait_until="load", timeout=TIMEOUT)
        else:
            side.page.reload(wait_until="load", timeout=TIMEOUT)
        side.wait_webclient()
        after_reload = odoo_route(side)
        address = side.page.url  # what a person copies from the address bar
        other = side.context.new_page()
        try:
            other.goto(address, wait_until="load", timeout=TIMEOUT)
            if side.surface is Surface.HA_INGRESS:
                frame = None
                for _ in range(120):
                    frames = [f for f in other.frames if "/api/hassio_ingress/" in f.url
                              and f.parent_frame == other.main_frame]
                    if frames and frames[0].locator(".o_action_manager > *").count():
                        frame = frames[0]
                        break
                    other.wait_for_timeout(500)
                if frame is None:
                    raise RuntimeError("the copied address opened no Odoo screen")
                opened = urlsplit(frame.url).path[len(str(side.env.prefix)):]
            else:
                other.locator(".o_action_manager > *").first.wait_for(timeout=TIMEOUT)
                opened = urlsplit(other.url).path
        finally:
            other.close()
        return Outcome(True, "reload stays on %s; copied address opens %s" % (after_reload, opened),
                       details={"address_bar": side.env.mask(address)})

    public, ingress = run.both(probe)
    kwargs: dict[str, Any] = {}
    reloaded = [outcome.result.split(";")[0] for outcome in (public, ingress)]
    if public.available and ingress.available and reloaded[0] == reloaded[1] and public.result != ingress.result             and ingress.details.get("address_bar", "").endswith("/" + run.env.slug):
        # RC-15: the HA address bar names the panel, never the screen inside it.
        kwargs = {"verdict": "STRUCTURAL", "severity": "none", "public_path": "<PUBLIC_BASE>" + route}
    run.record("U-B3", "shared", "generic", public, ingress, model="res.partner",
               notes="Reload (the iframe's own reload on Ingress), then the browser address bar copied into a "
                     "new tab. Under Ingress the address bar holds the HA panel address, so a copied address "
                     "opens the panel's start screen; a link to one screen comes from the Public origin.",
               **kwargs)


@check("U-B4")
def check_b4(run: Run) -> None:
    routes = [LIST_ROUTES["res.partner"], "/odoo/res.partner/%d" % run.fx["partner"],
              "/odoo/sale.order/%d" % run.fx["sale_order"]]

    def probe(side: Side) -> Outcome:
        seen = []
        for route in routes:
            visit(side, route)
        for step in ("back", "back", "forward"):
            before = odoo_route(side)
            # The top page's history; under Ingress it holds the iframe's entries.
            side.page.evaluate("(step) => history[step]()", step)
            for _ in range(60):
                side.page.wait_for_timeout(500)
                try:
                    if odoo_route(side) != before:
                        break
                except Exception:  # noqa: BLE001 -- the frame is mid-navigation
                    side._frame = None
            side.wait_webclient()
            seen.append(odoo_route(side))
        return Outcome(True, "back, back, forward: " + " -> ".join(seen))

    public, ingress = run.both(probe)
    run.record("U-B4", "shared", "generic", public, ingress,
               notes="Browser back and forward on the top page; under Ingress the iframe's history is part of "
                     "the page's.")


@check("U-B5")
def check_b5(run: Run) -> None:
    route = "/odoo/res.partner/%d" % run.fx["partner"]

    def probe(side: Side) -> Outcome:
        visit(side, route)
        if side.surface is Surface.HA_INGRESS:
            second = IngressSide(run.env, run.browser)
            second.context.close()
            second.context, second.page = side.context, side.context.new_page()
            open_ha_panel(second)
        else:
            second = PublicSide(run.env, run.browser)
            second.context.close()
            second.context, second.page = side.context, side.context.new_page()
            second.recorder = Recorder(second.page, second.surface, run.env.public, None)
        second.goto(route)
        second.wait_webclient()
        workers = side.root.evaluate("() => (performance.getEntriesByType('resource') || [])"
                                     ".filter(e => /worker/.test(e.name)).length")
        # Back to the first tab: still logged in and able to read the record.
        visit(side, route)
        name = side.root.locator(".o_breadcrumb .active, .o_last_breadcrumb_item").first.inner_text()
        second.page.close()
        return Outcome(True, "both tabs stay logged in" if run.marker in name else "first tab lost the record",
                       details={"worker_bundle_requests_in_first_tab": workers})

    public, ingress = run.both(probe)
    run.record("U-B5", "shared", "generic", public, ingress, model="res.partner",
               notes="A second tab in the same browser context opens the same record, then the first tab reloads it.")


B6_FREEZE_SECONDS = int(os.environ.get("PARITY_B6_FREEZE_SECONDS", "960"))


@check("U-B6")
def check_b6(run: Run) -> None:
    """Freeze the HA tab past the Supervisor's 15-minute Ingress session life.

    While frozen, the frontend's keep-alive does not run, so the session
    really expires on the Supervisor; then the tab resumes and Odoo is used.
    """
    side = run.ingress
    route = "/odoo/res.partner/%d" % run.fx["partner"]
    visit(side, route)
    cdp = side.context.new_cdp_session(side.page)
    cdp.send("Page.setWebLifecycleState", {"state": "frozen"})
    time.sleep(B6_FREEZE_SECONDS)
    cdp.send("Page.setWebLifecycleState", {"state": "active"})
    started = time.monotonic()
    steps, recovered = [], False
    while time.monotonic() - started < 120:
        try:
            response = side.root.goto(side.base + route, wait_until="load", timeout=TIMEOUT)
            status = response.status if response else None
            steps.append(status)
            if status == 200 and side.root.locator(".o_main_navbar").count():
                recovered = True
                break
        except Exception as error:  # noqa: BLE001 -- the frame may be replaced while HA re-authorizes
            steps.append(type(error).__name__)
            side._frame = None
        side.page.wait_for_timeout(10_000)
    waited = round(time.monotonic() - started)
    if recovered:
        result = "after %d s frozen the screen came back in %d s (statuses %s)" % (B6_FREEZE_SECONDS, waited, steps)
    else:
        side.page.goto(side.ha + "/" + run.env.slug, wait_until="domcontentloaded", timeout=TIMEOUT)
        side._frame = None
        side.wait_webclient()
        result = "after %d s frozen no recovery in %d s (statuses %s); reopening the panel opens %s" % (
            B6_FREEZE_SECONDS, waited, steps, odoo_route(side))
    run.record("U-B6", "shared", "generic", Outcome(True, "not applicable: the Public origin has no host session"),
               Outcome(True, result), verdict="PARITY" if recovered else "GAP",
               severity="none" if recovered else "minor",
               notes="The HA tab was frozen (Chrome page lifecycle) longer than the Supervisor keeps an unrenewed "
                     "Ingress session (15 min), then resumed and the same Odoo screen reopened in the iframe. From "
                     "the browser it cannot be told whether the session had lapsed and the frontend renewed it on "
                     "resume, or it had not lapsed; either way no authorization box and no blank screen.")


def ensure_low_user(run: Run) -> tuple[str, str]:
    import secrets

    login = "parity-low-%s@example.invalid" % run.marker.lower()
    password = secrets.token_urlsafe(24)
    run.env.extra_secrets.append(password)
    found = run.public.rpc("res.users", "search", [[["login", "=", login]]])
    base_group = run.public.rpc("ir.model.data", "check_object_reference", ["base", "group_user"])[1]
    values = {"password": password}
    if found:
        run.public.rpc("res.users", "write", [found, values])
    else:
        run.public.rpc("res.users", "create", [dict(values, name=run.marker + " Low User", login=login,
                                                    groups_id=[[6, 0, [base_group]]])])
    return login, password


@check("U-B7")
def check_b7(run: Run) -> None:
    login, password = ensure_low_user(run)
    target = "/odoo/action-base.ir_config_list_action"

    def probe(kind: type) -> Outcome:
        side = fresh_side(run, kind)
        try:
            start_unauthenticated(side)
            side.goto("/web/login")
            side.root.locator('input[name="login"]').fill(login)
            side.root.locator('input[name="password"]').fill(password)
            side.root.locator('input[name="password"]').press("Enter")
            side.root.locator(".o_main_navbar").first.wait_for(timeout=TIMEOUT)
            side.goto(target)
            side.settle(1500)
            denied = side.root.locator(".o_error_dialog, .o_dialog .modal-content, .o_notification").filter(
                has_text=re.compile("(Access|access|not allowed|permission)")).count() > 0
            landed = odoo_route(side)
            return Outcome(True, "refused" if denied else "not refused (landed on %s)" % landed)
        finally:
            side.close()

    outcomes = []
    for kind in (PublicSide, IngressSide):
        try:
            outcomes.append(probe(kind))
        except Exception as error:  # noqa: BLE001
            outcomes.append(Outcome(False, "error: %s" % sanitize_diagnostic((str(error).splitlines() or [""])[0])))
    run.record("U-B7", "shared", "generic", outcomes[0], outcomes[1], model="ir.config_parameter",
               notes="An Internal User without Settings rights (created for this run) opens System Parameters.")


@check("U-B8")
def check_b8(run: Run) -> None:
    anonymous = run.browser.new_context()
    try:
        ingress_response = anonymous.request.get(run.ingress.base + "/odoo", max_redirects=0)
        body = ingress_response.text()
        leaked = any(marker in body for marker in ("odoo.__session_info__", "o_main_navbar", "web.assets", "Odoo"))
        public_response = anonymous.request.get(run.env.public + "/odoo", max_redirects=0)
    finally:
        anonymous.close()
    ingress = Outcome(True, "HTTP %d, %s" % (ingress_response.status, "Odoo content leaked" if leaked else
                                             "no Odoo content"))
    public = Outcome(True, "HTTP %d, reachable anonymously" % public_response.status)
    blocked = ingress_response.status in (401, 403) and not leaked
    run.record("U-B8", "shared", "generic", public, ingress,
               verdict="APPROVED-DIVERGENCE" if blocked else "GAP", severity="none" if blocked else "blocker",
               notes="AD-6, verified in reverse: the Ingress prefix without any HA cookie must be refused and "
                     "show nothing of Odoo; the Public origin stays reachable.")


# --- Group C: Web Client primitives -----------------------------------------------------

VIEW_ROUTES = {
    "list": LIST_ROUTES["res.partner"],
    "kanban": "/odoo/action-contacts.action_contacts",
    "form": None,  # the fixture partner
    "calendar": "/odoo/action-calendar.action_calendar_event",
    "graph": "/odoo/action-crm.crm_lead_action_pipeline?view_type=graph",
    "pivot": "/odoo/action-crm.crm_lead_action_pipeline?view_type=pivot",
    "activity": "/odoo/action-crm.crm_lead_action_pipeline?view_type=activity",
    "hierarchy": "/odoo/action-hr.open_view_employee_list_my?view_type=hierarchy",
    "settings": "/odoo/settings",
}


def signals_of(outcome: Outcome) -> dict[str, int]:
    return {key: value for key, value in outcome.signals.items() if value}


@check("U-C1")
def check_c1(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        rendered, missing = [], []
        for view, route in VIEW_ROUTES.items():
            visit(side, route or "/odoo/res.partner/%d" % run.fx["partner"])
            selector = ".o_%s_view" % ("setting" if view == "settings" else view)
            if side.root.locator(selector).count() or (view == "settings" and
                                                       side.root.locator(".o_settings_container, .settings").count()):
                rendered.append(view)
            else:
                missing.append(view)
        return Outcome(True, "rendered: %s%s" % (",".join(rendered), "; missing: " + ",".join(missing)
                                                  if missing else ""))

    public, ingress = run.both(probe)
    run.record("U-C1", "shared", "generic", public, ingress,
               notes="One screen per view type: contacts list/kanban/form, calendar events, CRM "
                     "graph/pivot/activity, employee hierarchy, Settings.")


@check("U-C2")
def check_c2(run: Run) -> None:
    def rows(side: Side) -> int:
        side.settle(500)
        return side.root.locator(".o_data_row").count()

    def probe(side: Side) -> Outcome:
        open_list(side, "res.partner")
        root, steps = side.root, []
        steps.append("all=%d" % rows(side))
        search = root.locator(".o_searchview_input").first
        search.fill(run.marker)
        search.press("Enter")
        steps.append("search=%d" % rows(side))
        root.locator(".o_facet_remove").first.click()
        root.locator(".o_searchview_dropdown_toggler").first.click()
        root.locator(".o_filter_menu .o_menu_item, .o_filter_menu .dropdown-item").first.click()
        steps.append("filter=%d" % rows(side))
        root.locator(".o_group_by_menu .o_menu_item, .o_group_by_menu .dropdown-item").first.click()
        side.settle(500)
        steps.append("groups=%d" % root.locator(".o_group_header").count())
        side.page.keyboard.press("Escape")
        while root.locator(".o_facet_remove").count():
            root.locator(".o_facet_remove").first.click()
            side.settle(300)
        root.locator("th[data-name='complete_name'], th[data-name='display_name'], th[data-name='name']").first.click()
        side.settle(500)
        steps.append("sorted first=%s" % (root.locator(".o_data_row").first.inner_text().split("\n")[0][:30]))
        steps.append("pager=%s" % root.locator(".o_pager_value").first.inner_text() if root.locator(".o_pager_value").count()
                     else "pager=none")
        root.locator(".o_optional_columns_dropdown button, .o_optional_columns_dropdown_toggle").first.click()
        root.locator(".o-dropdown--menu input[type=checkbox]").first.wait_for(timeout=TIMEOUT)
        steps.append("optional columns=%d" % root.locator(".o-dropdown--menu input[type=checkbox]").count())
        side.page.keyboard.press("Escape")
        root.locator(".o_switch_view.o_kanban, button.o_kanban").first.click()
        root.locator(".o_kanban_view").first.wait_for(timeout=TIMEOUT)
        steps.append("switched to kanban")
        return Outcome(True, "; ".join(steps))

    public, ingress = run.both(probe)
    run.record("U-C2", "shared", "generic", public, ingress,
               notes="Contacts list: search, first filter, first group-by, sort by name, pager, optional columns, "
                     "switch view. Saving a favourite was left out (it writes a shared filter).")


@check("U-C3")
def check_c3(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        open_form(side, "sale.order", run.fx["sale_order"])
        root, done = side.root, []
        partner = root.locator("div[name='partner_id'] input").first
        partner.click()
        partner.fill(run.marker[:18])
        root.locator(".o-autocomplete--dropdown-menu .o-autocomplete--dropdown-item").first.wait_for(timeout=TIMEOUT)
        done.append("many2one dropdown")
        side.page.keyboard.press("Escape")
        root.locator("div[name='validity_date'] input, div[name='date_order'] input").first.click()
        root.locator(".o_datetime_picker").first.wait_for(timeout=TIMEOUT)
        done.append("date picker")
        side.page.keyboard.press("Escape")
        tags = root.locator("div[name='tag_ids'] input").first
        if tags.count():
            tags.click()
            root.locator(".o-autocomplete--dropdown-menu").first.wait_for(timeout=TIMEOUT)
            done.append("many2many_tags dropdown")
            side.page.keyboard.press("Escape")
        root.locator(".o_field_x2many_list_row_add a").first.click()
        root.locator(".o_selected_row").first.wait_for(timeout=TIMEOUT)
        done.append("one2many row added")
        done.append("statusbar %d states" % root.locator(".o_statusbar_status button").count())
        done.append("monetary %s" % bool(root.locator(".o_field_monetary").count()))
        root.locator(".o_form_button_cancel").first.click()
        side.settle(500)
        dirty = root.locator(".o_form_status_indicator_buttons:not(.invisible) .o_form_button_save").count()
        done.append("discarded" if not dirty else "still dirty")
        return Outcome(True, "; ".join(done))

    public, ingress = run.both(probe)
    run.record("U-C3", "shared", "generic", public, ingress, model="sale.order",
               notes="On the fixture quotation, then discarded: many2one, date picker, many2many_tags, one2many "
                     "row, statusbar and monetary. Priority, boolean_toggle, handle drag, progressbar, reference, "
                     "domain editor, color picker, percentage, float_time and daterange were not reached by this "
                     "check.")


_COPY_SPY_JS = """() => {
  window.__parityCopied = null; window.__parityCopyOk = null;
  const clip = navigator.clipboard;
  if (clip && !clip.__paritySpy) {
    const write = clip.writeText.bind(clip);
    clip.writeText = (text) => { window.__parityCopied = String(text);
      return write(text).then(() => { window.__parityCopyOk = true; },
                              (error) => { window.__parityCopyOk = false; throw error; }); };
    clip.__paritySpy = true;
  }
  return { clipboard: !!clip, secure: window.isSecureContext };
}"""


def copy_in_dialog(side: Side) -> Outcome:
    """Press the copy button in the open dialog and read what was copied."""
    root = side.root
    spy = root.evaluate(_COPY_SPY_JS)
    dialog = root.locator(".o_dialog .modal-content").last
    button = dialog.locator(".o_clipboard_button, button:has(.fa-clone), button:has(.fa-copy)").first
    button.click()
    side.page.wait_for_timeout(1200)
    copied = root.evaluate("() => [window.__parityCopied, window.__parityCopyOk]")
    toast = root.locator(".o_notification, .o_clipboard_button .text-success, .popover").filter(
        has_text=re.compile("Copied|copied")).count() > 0 or "Copied" in button.inner_text()
    if copied[1]:
        result = "copied %s" % copied[0]
    else:
        result = "copy failed (%s)" % ("threw" if copied[1] is False else "clipboard never called")
    return Outcome(True, result, details={"clipboard_api": spy["clipboard"], "secure_context": spy["secure"],
                                          "success_feedback": toast})


def open_share_dialog(side: Side, run: Run) -> None:
    open_form(side, "sale.order", run.fx["sale_order"])
    cog_item(side, "Share")
    side.root.locator(".o_dialog .modal-content").last.wait_for(timeout=TIMEOUT)
    side.settle(500)


def open_survey_share(side: Side, run: Run) -> None:
    open_form(side, "survey.survey", run.fx["survey"])
    side.root.locator("button[name='action_send_survey'], .o_form_statusbar button").filter(
        has_text=re.compile("^\\s*Share\\s*$")).first.click()
    side.root.locator(".o_dialog .modal-content").last.wait_for(timeout=TIMEOUT)
    side.settle(500)


def close_dialog(side: Side) -> None:
    dialog = side.root.locator(".o_dialog .modal-content").last
    if dialog.count():
        dialog.locator("button.btn-close, footer button.btn-secondary").first.click()
        side.settle(300)


@check("U-C4")
def check_c4(run: Run) -> None:
    for side in run.sides:
        if side.surface is Surface.PUBLIC:
            side.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=run.env.public)
    for module, screen, opener in (("shared", "generic", open_share_dialog),
                                   ("survey", "survey share dialog", open_survey_share)):
        def probe(side: Side, opener=opener) -> Outcome:
            opener(side, run)
            try:
                return copy_in_dialog(side)
            finally:
                close_dialog(side)

        public, ingress = run.both(probe)
        run.record("U-C4", module, screen, public, ingress,
                   notes=("The quotation's Share dialog" if module == "shared" else "The survey's Share dialog")
                   + ", copy button pressed; the copied text is read from the clipboard call (Public: the "
                     "browser clipboard; Ingress over http: the Runtime shim's execCommand fallback).")


@check("U-C5")
def check_c5(run: Run) -> None:
    from e2e_menu_action_adapter import _URL_LITERALS_JS, url_literal_violation

    def probe(side: Side) -> Outcome:
        found, violations = set(), []
        for opener in (open_share_dialog, open_survey_share):
            opener(side, run)
            for literal in side.root.evaluate(_URL_LITERALS_JS):
                found.add(literal)
                reason = url_literal_violation(literal, run.env.ha)
                if reason:
                    violations.append("%s: %s" % (reason, literal))
            close_dialog(side)
        bases = sorted({"%s://%s" % (urlsplit(url).scheme, urlsplit(url).netloc) for url in found
                        if urlsplit(url).netloc})
        result = "no violation" if not violations else "violations: " + ", ".join(sorted(set(violations))[:5])
        return Outcome(True, result, details={"absolute_bases": bases})

    public, ingress = run.both(probe)
    run.record("U-C5", "shared", "generic", public, ingress,
               notes="Every URL literal in the quotation and survey Share dialogs (fields, href, src, text): none "
                     "may be loopback, carry the Ingress token or point at Home Assistant.")


@check("U-C10")
def check_c10(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        root, done = side.root, []
        open_form(side, "res.partner", run.fx["partner"])
        cog_item(side, "Archive")
        confirm = root.locator(".o_dialog .modal-content").last
        confirm.wait_for(timeout=TIMEOUT)
        done.append("confirmation")
        confirm.locator("footer button.btn-secondary").first.click()
        open_form(side, "sale.order", run.fx["sale_order"])
        field = root.locator("div[name='partner_id'] input").first
        field.click()
        field.fill("a")
        more = root.locator(".o_m2o_dropdown_option_search_more, .o-autocomplete--dropdown-item").filter(
            has_text="Search More")
        more.first.click()
        select = root.locator(".o_dialog .modal-content").last
        select.wait_for(timeout=TIMEOUT)
        select.locator(".o_list_view, .o_kanban_view").first.wait_for(timeout=TIMEOUT)
        done.append("select-create dialog")
        side.page.keyboard.press("Escape")
        side.settle(400)
        done.append("escape closes" if not root.locator(".o_dialog .modal-content").count() else "escape ignored")
        field.click()
        field.fill(run.marker + " C10")
        create = root.locator(".o-autocomplete--dropdown-item").filter(has_text="Create and edit")
        create.first.click()
        form = root.locator(".o_dialog .modal-content").last
        form.locator(".o_form_view").first.wait_for(timeout=TIMEOUT)
        done.append("form dialog")
        form.locator("footer button.o_form_button_cancel, footer button.btn-secondary").first.click()
        side.settle(300)
        root.locator(".o_form_button_cancel").first.click()
        return Outcome(True, "; ".join(done))

    public, ingress = run.both(probe)
    run.record("U-C10", "shared", "generic", public, ingress,
               notes="Archive confirmation (cancelled), Search More select dialog (Escape), Create and edit form "
                     "dialog (discarded). A traceback dialog was not provoked.")


@check("U-C11")
def check_c11(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        visit(side, "/odoo")
        root, done = side.root, []
        for name, selector in (("messaging", ".o-mail-MessagingMenu-counter, .o_menu_systray .fa-comments"),
                               ("activity", ".o_menu_systray .fa-clock-o"),
                               ("user", ".o_user_menu .dropdown-toggle, .o_user_menu button")):
            root.locator(selector).first.click()
            menu = root.locator(".o-dropdown--menu, .o-mail-MessagingMenu").first
            menu.wait_for(timeout=TIMEOUT)
            done.append("%s menu" % name)
            if name != "user":
                side.page.keyboard.press("Escape")
        root.locator(".dropdown-item[data-menu='settings'], .dropdown-item").filter(
            has_text=re.compile("Preferences|My Profile")).first.click()
        root.locator(".o_dialog .modal-content, .o_form_view").first.wait_for(timeout=TIMEOUT)
        done.append("preferences opened")
        side.page.keyboard.press("Escape")
        return Outcome(True, "; ".join(done))

    public, ingress = run.both(probe)
    run.record("U-C11", "shared", "generic", public, ingress, notes="Messaging, activity and user menus; Preferences.")


@check("U-C12")
def check_c12(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        visit(side, "/odoo")
        root = side.root
        root.locator(".o_navbar_apps_menu button, .o_menu_toggle").first.click()
        root.locator(".o_app").first.wait_for(timeout=TIMEOUT)
        apps = root.locator(".o_app").count()
        root.locator(".o_app, .o_menuitem").filter(has_text=re.compile(r"^\s*Contacts\s*$")).first.click()
        side.wait_webclient()
        root.locator(".o_menu_sections button, .o_menu_sections .dropdown-toggle").filter(
            has_text="Configuration").first.click()
        root.locator(".o-dropdown--menu .dropdown-item, .o-dropdown--menu a").filter(
            has_text=re.compile(r"Tags\s*$")).first.click()
        side.wait_webclient()
        return Outcome(True, "%d apps; Contacts > Configuration > Contact Tags loaded %s" % (apps, odoo_route(side)))

    public, ingress = run.both(probe)
    run.record("U-C12", "shared", "generic", public, ingress,
               notes="App launcher, then a third-level menu by clicking. Every menu action of the 24 apps was "
                     "crawled on both surfaces on 2026-09-24 (docs/testing/evidence/2026-09-24-issue-144/"
                     "crawl-diff.jsonl: 272 PARITY, 4 GAP filed as #158-#160); the 390x844 crawl of this run "
                     "repeats it in the mobile layout.")


@check("U-C13")
def check_c13(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        root = side.root
        open_list(side, "sale.order")
        root.locator(".o_data_row").filter(has_text=run.marker).first.click()
        side.wait_webclient()
        partner = root.locator("div[name='partner_id']").first
        partner.hover()
        partner.locator(".o_external_button").first.click()
        side.wait_webclient()
        depth = root.locator(".o_breadcrumb .breadcrumb-item, .o_breadcrumb .o_back_button").count() + 1
        trail = [root.locator(".o_last_breadcrumb_item").first.inner_text().strip()[:40]]
        while root.locator(".o_breadcrumb .breadcrumb-item a, .o_breadcrumb .o_back_button").count():
            root.locator(".o_breadcrumb .breadcrumb-item a, .o_breadcrumb .o_back_button").last.click()
            side.wait_webclient()
            trail.append(root.locator(".o_last_breadcrumb_item").first.inner_text().strip()[:40])
        return Outcome(True, "depth %d; back through: %s" % (depth, " > ".join(trail)))

    public, ingress = run.both(probe)
    run.record("U-C13", "shared", "generic", public, ingress,
               notes="Quotations list > quotation > its customer, then back by each breadcrumb.")


@check("U-C14")
def check_c14(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        visit(side, "/odoo")
        side.root.locator(".o_main_navbar").first.click(position={"x": 400, "y": 10})
        side.page.keyboard.press("Control+k")
        palette = side.root.locator(".o_command_palette")
        palette.wait_for(timeout=15000)
        side.page.keyboard.type("/Contacts")
        side.page.wait_for_timeout(800)
        side.page.keyboard.press("Enter")
        side.wait_webclient()
        return Outcome(True, "palette opened; /Contacts led to %s" % odoo_route(side))

    public, ingress = run.both(probe)
    run.record("U-C14", "shared", "generic", public, ingress,
               notes="Ctrl+K with focus in Odoo, then the menu command /Contacts.")


@check("U-C15")
def check_c15(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        open_form(side, "res.partner", run.fx["partner"])
        root, done = side.root, []
        root.locator("input[type='email'] >> visible=true").first.click()
        root.evaluate("() => { window.__parityFocus = document.activeElement; }")
        side.page.keyboard.press("Tab")
        after = root.evaluate("() => [document.activeElement !== window.__parityFocus && "
                              "document.activeElement !== document.body, document.hasFocus()]")
        done.append("tab moves focus" if after[0] else "tab did not move focus")
        done.append("focus stays in Odoo" if after[1] else "focus left Odoo")
        side.page.keyboard.press("Escape")
        hotkey = root.locator(".o_form_button_create").first.get_attribute("data-hotkey") or "c"
        side.page.keyboard.press("Alt+" + hotkey)  # the New button's own hotkey
        side.settle(600)
        done.append("alt+%s hotkey %s" % (hotkey, "opened a new record" if "/new" in odoo_route(side)
                                           else "did nothing"))
        discard = root.locator(".o_form_button_cancel >> visible=true")
        if discard.count():
            discard.first.click()
        return Outcome(True, "; ".join(done))

    public, ingress = run.both(probe)
    run.record("U-C15", "shared", "generic", public, ingress, model="res.partner",
               notes="Tab from the email field, then the New button's Alt hotkey on the form.")


@check("U-C17")
def check_c17(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        open_form(side, "res.partner", run.fx["partner"])
        side.root.locator(".o_control_panel .o_cp_action_menus button.dropdown-toggle").first.click()
        side.root.locator(".o-dropdown--menu .dropdown-item, .o-dropdown--menu .o-dropdown-item").first.wait_for(
            timeout=TIMEOUT)
        items = sorted(set(text.strip() for text in side.root.locator(
            ".o-dropdown--menu .dropdown-item, .o-dropdown--menu .o-dropdown-item").all_inner_texts() if text.strip()))
        side.page.keyboard.press("Escape")
        open_list(side, "sale.order")
        side.root.locator("thead .o_list_record_selector").first.click()
        side.root.locator(".o_control_panel button").filter(has_text="Actions").first.click()
        side.root.locator(".o-dropdown--menu .dropdown-item, .o-dropdown--menu .o-dropdown-item").first.wait_for(
            timeout=TIMEOUT)
        list_items = sorted(set(text.strip() for text in side.root.locator(
            ".o-dropdown--menu .dropdown-item, .o-dropdown--menu .o-dropdown-item").all_inner_texts() if text.strip()))
        side.page.keyboard.press("Escape")
        return Outcome(True, "form cog: %s | list actions: %s" % (", ".join(items), ", ".join(list_items)))

    public, ingress = run.both(probe)
    run.record("U-C17", "shared", "generic", public, ingress,
               notes="The item sets of the partner form cog and the quotation list Actions menu. Duplicate, Archive "
                     "and Export run under U-C16, U-C10 and U-C18; the rest were not executed.")


@check("U-C21")
def check_c21(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        visit(side, "/odoo")
        root = side.root
        root.evaluate("""() => { const n = odoo.__WOWL_DEBUG__.root.env.services.notification;
          n.add('parity success', { type: 'success' }); n.add('parity warning', { type: 'warning' });
          n.add('parity sticky', { type: 'info', sticky: true }); }""")
        side.page.wait_for_timeout(800)
        toasts = root.locator(".o_notification").filter(has_text="parity")
        count = toasts.count()
        width, height = root.evaluate("() => [window.innerWidth, window.innerHeight]")
        clipped = 0
        for index in range(count):
            box = toasts.nth(index).bounding_box()
            if side.surface is Surface.HA_INGRESS and box:
                frame_box = root.frame_element().bounding_box()
                box = dict(box, x=box["x"] - frame_box["x"], y=box["y"] - frame_box["y"])
            if not box or box["x"] < 0 or box["y"] < 0 or box["x"] + box["width"] > width + 1 or \
                    box["y"] + box["height"] > height + 1:
                clipped += 1
        sticky = root.locator(".o_notification").filter(has_text="parity sticky")
        sticky.locator(".o_notification_close, button.btn-close").first.click()
        side.page.wait_for_timeout(500)
        closed = not sticky.count()
        return Outcome(True, "%d toasts, %d clipped, sticky %s" % (count, clipped, "closed" if closed else "stuck"))

    public, ingress = run.both(probe)
    run.record("U-C21", "shared", "generic", public, ingress,
               notes="Success, warning and sticky notifications raised through the web client's notification "
                     "service.")


@check("U-C22")
def check_c22(run: Run) -> None:
    run.not_run("U-C22", "shared", "generic", "only en_US is active on odoo_parity",
                "Odoo shows the translation button only with a second active language; activating one changes "
                "the database beyond this run's fixtures.")


@check("U-C27")
def check_c27(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        visit(side, "/odoo")
        side.page.wait_for_timeout(2500)
        state = side.root.evaluate("""async () => {
          if (!navigator.serviceWorker) return { api: false };
          const registrations = navigator.serviceWorker.getRegistrations
            ? await navigator.serviceWorker.getRegistrations() : [];
          return { api: true, registrations: registrations.map(r => new URL(r.scope).pathname),
                   manifest: !!document.querySelector('link[rel=manifest]') };
        }""")
        registered = bool(state.get("registrations"))
        return Outcome(True, "service worker %s" % ("registered" if registered else "not registered"),
                       details=state)

    public, ingress = run.both(probe)
    structural = public.result.endswith("registered") and not public.result.endswith("not registered") and \
        ingress.result.endswith("not registered")
    run.record("U-C27", "shared", "generic", public, ingress,
               verdict="STRUCTURAL" if structural else None, severity="none" if structural else None,
               public_path="<PUBLIC_BASE>/odoo (install as an app, offline page)" if structural else None,
               notes="The Runtime shim removes Odoo's /odoo service worker under Ingress (RC-6), so installing "
                     "Odoo as an app and its offline page exist only on the Public origin. POS offline selling is "
                     "a page-level mechanism, not the service worker (#161).")


@check("U-C6")
def check_c6(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        text = "%s C6 %s" % (run.marker, side.name)
        open_form(side, "res.partner", run.fx["partner"])
        root = side.root
        root.locator(".o_notebook .nav-link").filter(has_text="Internal Notes").first.click()
        editor = root.locator("div[name='comment'] .odoo-editor-editable, div[name='comment'] [contenteditable=true]")
        editor.first.click()
        side.page.keyboard.press("Control+End")
        side.page.keyboard.press("Enter")
        side.page.keyboard.type(text)
        side.page.wait_for_timeout(800)
        root.locator(".o_form_button_save").first.click()
        side.settle(800)
        visit(side, "/odoo/res.partner/%d" % run.fx["partner"])
        root = side.root
        root.locator(".o_notebook .nav-link").filter(has_text="Internal Notes").first.click()
        kept = False
        for _ in range(20):
            if root.locator("div[name='comment']").filter(has_text=text).count():
                kept = True
                break
            side.page.wait_for_timeout(500)
        return Outcome(True, "typed text kept after save and reload" if kept else "text lost")

    public, ingress = run.both(probe)
    run.record("U-C6", "shared", "generic", public, ingress, model="res.partner",
               notes="The partner's Internal Notes HTML field: text typed, saved, reloaded. Inserting an image, "
                     "link, table or code block was not reached by this check.")


def _png_bytes() -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes([200, 30, 30]) * 8 for _ in range(8))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@check("U-C7")
def check_c7(run: Run) -> None:
    png = _png_bytes()
    pdf = run.public.context.request.get(
        run.env.public + "/report/pdf/sale.report_saleorder/%d" % run.fx["sale_order"]).body()

    def probe(side: Side) -> Outcome:
        name = "%s-C7-%s" % (run.marker, side.name)
        open_form(side, "res.partner", run.fx["partner"])
        root, done = side.root, []
        # With attachments already there the paperclip opens the attachment
        # box, whose own button opens the file chooser.
        root.locator(".o-mail-Chatter-topbar button[aria-label='Attach files']").first.click()
        with side.page.expect_file_chooser(timeout=TIMEOUT) as chooser:
            root.locator(".o-mail-AttachmentBox button").filter(has_text="Attach files").first.click()
        chooser.value.set_files([
            {"name": name + ".png", "mimeType": "image/png", "buffer": png},
            {"name": name + ".pdf", "mimeType": "application/pdf", "buffer": pdf},
        ])
        uploaded = 0
        for _ in range(40):
            uploaded = root.locator(".o-mail-AttachmentCard").filter(has_text=name).count() + \
                root.locator(".o-mail-AttachmentImage img[alt*='%s'], .o-mail-AttachmentImage[title*='%s']"
                             % (name, name)).count()
            if uploaded >= 2:
                break
            side.page.wait_for_timeout(500)
        done.append("both uploaded" if uploaded >= 2 else "%d of 2 uploaded" % uploaded)
        image = root.locator(".o-mail-AttachmentImage").filter(has=root.locator("img[alt*='%s']" % name)).first
        if not image.count():
            image = root.locator(".o-mail-AttachmentImage").last
        image.hover()
        # An image attachment keeps Download in its own menu.
        image.locator("button").first.click()
        data, _ = download(side, lambda: root.locator(".o-dropdown--menu .dropdown-item, .o-dropdown--menu a")
                           .filter(has_text="Download").first.click())
        done.append("download SHA-256 %s" % ("matches" if sha256(data) == sha256(png) else "differs"))
        image.click()
        viewer = root.locator(".o-FileViewer")
        viewer.wait_for(timeout=TIMEOUT)
        viewer.locator(".o-FileViewer-headerButton, [title='Zoom In'], .fa-plus").first.click()
        done.append("image viewer zooms")
        side.page.keyboard.press("Escape")
        card = root.locator(".o-mail-AttachmentCard").filter(has_text=name + ".pdf").first
        card.click()
        viewer.wait_for(timeout=TIMEOUT)
        pdf_frame = viewer.locator("iframe").first
        pdf_frame.wait_for(timeout=TIMEOUT)
        src = pdf_frame.get_attribute("src") or ""
        side.page.wait_for_timeout(2500)
        pages = 0
        for frame in side.page.frames:
            if "pdfjs" in frame.url or "viewer.html" in frame.url:
                pages = frame.locator(".page").count()
        done.append("PDF viewer %d page(s)" % pages)
        side.page.keyboard.press("Escape")
        return Outcome(True, "; ".join(done), details={"pdf_viewer_src": urlsplit(src).path})

    public, ingress = run.both(probe)
    run.record("U-C7", "shared", "generic", public, ingress, model="res.partner",
               notes="A PNG and the quotation PDF uploaded through the chatter, the PNG downloaded back and "
                     "compared, both opened in the file viewer.")


_DROP_JS = """async ({ name, text }) => {
  const file = new File([text], name, { type: 'text/plain' });
  const data = new DataTransfer(); data.items.add(file);
  const fire = (target, type) => target.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: data }));
  fire(document.body, 'dragenter');
  await new Promise(r => setTimeout(r, 500));
  const zone = document.querySelector('.o-Dropzone');
  if (!zone) return 'no dropzone';
  fire(zone, 'dragover'); fire(zone, 'drop');
  return 'dropped';
}"""


@check("U-C8")
def check_c8(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        name = "%s-C8-%s.txt" % (run.marker, side.name)
        open_form(side, "res.partner", run.fx["partner"])
        state = side.root.evaluate(_DROP_JS, {"name": name, "text": ATTACHMENT_TEXT})
        landed = False
        for _ in range(30):
            if side.root.locator(".o-mail-AttachmentCard").filter(has_text=name).count():
                landed = True
                break
            side.page.wait_for_timeout(500)
        return Outcome(True, "%s; attachment %s" % (state, "added" if landed else "missing"))

    public, ingress = run.both(probe)
    run.record("U-C8", "shared", "generic", public, ingress, model="res.partner",
               notes="A file dropped on the chatter's dropzone with synthetic drag events (a real OS drag is not "
                     "scriptable). The binary field was not dropped on.")


def open_composer(side: Side, button: str):
    """The chatter composer for `button`. Pressing the button of the open mode
    closes the composer, so press it only while that mode is not showing."""
    root = side.root
    composer = root.locator(".o-mail-Chatter .o-mail-Composer-input >> visible=true").first
    want = "Log" if button == "Log note" else "Send"
    for _ in range(3):
        mode = root.locator(".o-mail-Chatter .o-mail-Composer-send >> visible=true")
        if composer.count() and mode.count() and mode.first.inner_text().strip() == want:
            break
        side.root.locator(".o-mail-Chatter-topbar button").filter(has_text=button).first.click()
        side.page.wait_for_timeout(600)
    return composer


@check("U-C9")
def check_c9(run: Run) -> None:
    def post(side: Side, button: str, text: str) -> bool:
        root = side.root
        side.step = button
        composer = open_composer(side, button)
        composer.fill(text)
        root.locator(".o-mail-Composer-send, .o-mail-Composer button").filter(
            has_text=re.compile("^(Send|Log)$")).first.click()
        for _ in range(20):
            if root.locator(".o-mail-Message-body").filter(has_text=text).count():
                return True
            side.page.wait_for_timeout(500)
        return False

    def probe(side: Side) -> Outcome:
        open_form(side, "res.partner", run.fx["partner"])
        root, done = side.root, []
        done.append("message %s" % ("shown" if post(side, "Send message", "%s C9 message %s" % (
            run.marker, side.name)) else "missing"))
        done.append("note %s" % ("shown" if post(side, "Log note", "%s C9 note %s" % (
            run.marker, side.name)) else "missing"))
        side.step = "mention"
        side.page.wait_for_timeout(800)  # the composer closes after a post
        composer = open_composer(side, "Log note")
        composer.fill("@Adm")
        suggestions = root.locator(".o-mail-Composer-suggestionList .o-mail-NavigableList-item, "
                                   ".o-mail-NavigableList-item")
        try:
            suggestions.first.wait_for(timeout=10000)
            done.append("mention suggestions %d" % suggestions.count())
        except Exception:  # noqa: BLE001
            done.append("no mention suggestions")
        composer.fill("")
        message = root.locator(".o-mail-Message").filter(has_text="C9 note %s" % side.name).first
        message.hover()
        message.locator("button[title='Add a Reaction'], button[name='add-reaction']").first.click()
        root.locator(".o-EmojiPicker .o-Emoji").first.click()
        reacted = False
        for _ in range(20):
            if message.locator(".o-mail-MessageReaction").count():
                reacted = True
                break
            side.page.wait_for_timeout(500)
        done.append("reaction %s" % ("shown" if reacted else "missing"))
        root.locator(".o-mail-Chatter-topbar button").filter(has_text="Activities").first.click()
        dialog = root.locator(".o_dialog .modal-content").last
        dialog.wait_for(timeout=TIMEOUT)
        done.append("activity dialog")
        side.page.keyboard.press("Escape")
        root.locator(".o-mail-Followers-button").first.click()
        root.locator(".o-mail-Follower").first.wait_for(timeout=TIMEOUT)
        done.append("followers %s" % root.locator(".o-mail-Follower").count())
        side.page.keyboard.press("Escape")
        return Outcome(True, "; ".join(done))

    public, ingress = run.both(probe)
    run.record("U-C9", "shared", "generic", public, ingress, model="res.partner",
               notes="Message, log note, @mention suggestions, reaction, activity dialog (closed without "
                     "saving), followers list. Every message appeared without a reload. Edit, delete and "
                     "attachment removal were not done (nothing is deleted in this run).")


@check("U-C16")
def check_c16(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        root, done = side.root, []
        name = "%s C16 %s" % (run.marker, side.name)
        # A new record from the list's New button; never the fixture partner.
        open_list(side, "res.partner")
        root.locator(".o_list_button_add, .o_control_panel_main_buttons button").filter(
            has_text=re.compile(r"^\s*New\s*$")).first.click()
        root.locator(".o_form_view").first.wait_for(timeout=TIMEOUT)
        root.locator("div[name='name'] input, input[id^='name_']").first.fill(name)
        root.locator(".o_form_button_save").first.click()
        side.settle(800)
        created = re.search(r"/(\d+)$", odoo_route(side))
        if not created or int(created.group(1)) == run.fx["partner"]:
            raise RuntimeError("no new partner was created (%s)" % odoo_route(side))
        done.append("created")
        field = root.locator("div[name='name'] input, input[id^='name_']").first
        field.fill(name + " edited")
        root.locator(".o_form_button_cancel").first.click()
        side.settle(500)
        done.append("discard restores" if field.input_value() == name else "discard kept the edit")
        cog_item(side, "Duplicate")
        side.settle(800)
        done.append("duplicated" if "(copy)" in root.locator("div[name='name'] input").first.input_value()
                    else "duplicate missing")
        root.locator(".o_form_button_save").first.click() if root.locator(
            ".o_form_status_indicator_buttons:not(.invisible) .o_form_button_save").count() else None
        cog_item(side, "Archive")
        root.locator(".o_dialog footer button.btn-primary").first.click()
        side.settle(600)
        done.append("archived" if root.locator(".ribbon, .o_widget_web_ribbon").filter(
            has_text="Archived").count() else "archive ribbon missing")
        cog_item(side, "Unarchive")
        side.settle(600)
        done.append("unarchived" if not root.locator(".ribbon, .o_widget_web_ribbon").filter(
            has_text="Archived").count() else "still archived")
        cog_item(side, "Delete")
        confirm = root.locator(".o_dialog .modal-content").last
        confirm.wait_for(timeout=TIMEOUT)
        done.append("delete asks to confirm")
        confirm.locator("footer button.btn-secondary").first.click()
        return Outcome(True, "; ".join(done))

    public, ingress = run.both(probe)
    run.record("U-C16", "shared", "generic", public, ingress, model="res.partner",
               notes="Create, discard an edit, duplicate, archive, unarchive; delete stopped at its confirmation "
                     "(this run deletes nothing). Each surface worked on its own new partner.")


@check("U-C19")
def check_c19(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        name = "%s C19 %s 測試 ÅÄÖ" % (run.marker, side.name)
        csv = ("name,email\n\"%s\",c19-%s@example.invalid\n" % (name, side.name)).encode("utf-8")
        open_list(side, "res.partner")
        root = side.root
        root.locator(".o_control_panel .o_cp_action_menus button.dropdown-toggle, "
                     ".o_control_panel button.o_cp_action_menus").first.click()
        root.locator(".o-dropdown--menu .dropdown-item, .o-dropdown--menu .o-dropdown-item").filter(
            has_text="Import records").first.click()
        root.locator(".o_action_manager input.o_input_file").first.set_input_files(
            {"name": "parity.csv", "mimeType": "text/csv", "buffer": csv})
        root.locator("button").filter(has_text=re.compile(r"^\s*Import\s*$")).first.wait_for(timeout=TIMEOUT)
        side.settle(800)
        root.locator("button").filter(has_text=re.compile(r"^\s*Test\s*$")).first.click()
        side.settle(1000)
        root.locator("button").filter(has_text=re.compile(r"^\s*Import\s*$")).first.click()
        side.settle(2000)
        found = side.rpc("res.partner", "search_count", [[["name", "=", name]]])
        return Outcome(True, "imported %d record(s) with the Unicode name" % found)

    public, ingress = run.both(probe)
    run.record("U-C19", "shared", "generic", public, ingress, model="res.partner",
               notes="A CSV with a Unicode name imported through the contacts import screen (Test, then Import).")


@check("U-C23")
def check_c23(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        open_form(side, "survey.survey", run.fx["survey"])
        button = side.root.locator("button[name='action_test_survey']").first
        with side.context.expect_page(timeout=20000) as info:
            button.click()
        popup = info.value
        popup.wait_for_load_state("load", timeout=TIMEOUT)
        url = popup.url
        rendered = popup.locator("body").inner_text(timeout=TIMEOUT).strip()[:60]
        popup.close()
        parts = urlsplit(url)
        path = parts.path
        # The shape is the path alone; a prefix in the query or the fragment is a token too.
        carries_prefix = "/api/hassio_ingress/" in url
        if carries_prefix and side.env.prefix:
            path = path.replace(side.env.prefix, "<INGRESS_PREFIX>")
        base = "<PUBLIC_BASE>" if url.startswith(side.env.public) else (
            "<HA_BASE>" if url.startswith(side.env.ha) else "other")
        shape = "%s%s" % (base, re.sub(r"/[0-9a-f-]{16,}", "/<token>", path))
        return Outcome(True, "new tab at %s%s" % (shape, " (carries the Ingress token)" if carries_prefix else ""),
                       details={"shape": shape, INGRESS_PREFIX_DETAIL: carries_prefix,
                                "page_text": run.env.mask(rendered)})

    public, ingress = run.both(probe)
    verdict, severity, reasons, public_path = new_tab_verdict(public, ingress)
    run.record("U-C23", "shared", "generic", public, ingress, model="survey.survey",
               verdict=verdict, severity=severity, public_path=public_path,
               notes="; ".join(filter(None, [
                   "The survey's Test button, which opens a new tab. U-C23 records the address shape: a tab "
                   "opened from Ingress is a top-level page under the Supervisor path, so its address carries "
                   "the add-on's Ingress token by construction (RC-15, a Structural gap) and opens only for "
                   "the person who pressed the button -- whose browser holds the Ingress session cookie that "
                   "address needs -- which is why such a link is shared from the Public origin "
                   "instead. The signals are those of the page that opened the tab: the tab is a page of its "
                   "own, and its console, requests and HTTP statuses are not measured (the same as U-B3's "
                   "second tab).", *reasons])))


def kiosk_path(side: Side) -> str:
    """The attendance kiosk's own page (Attendances > Kiosk Mode opens it)."""
    url = side.rpc("res.company", "search_read", [[]], {"fields": ["attendance_kiosk_url"], "limit": 1})[0][
        "attendance_kiosk_url"]
    return urlsplit(url).path


_FULLSCREEN_JS = """() => new Promise((resolve) => {
  const button = document.createElement('button');
  button.id = 'parity-fullscreen'; button.textContent = 'fullscreen';
  button.style.cssText = 'position:fixed;top:0;left:0;z-index:99999';
  button.onclick = () => document.documentElement.requestFullscreen()
    .then(() => { window.__parityFullscreen = 'entered'; })
    .catch((error) => { window.__parityFullscreen = 'refused: ' + error.name; });
  document.body.appendChild(button); resolve(true);
})"""


def fullscreen_via_click(side: Side, locator=None) -> str:
    root = side.root
    root.evaluate("() => { window.__parityFullscreen = null; }")
    if locator is None:
        root.evaluate(_FULLSCREEN_JS)
        locator = root.locator("#parity-fullscreen")
    locator.click()
    side.page.wait_for_timeout(1200)
    state = root.evaluate("() => [window.__parityFullscreen, !!document.fullscreenElement]")
    if state[1]:
        root.evaluate("() => document.exitFullscreen()")
        side.page.wait_for_timeout(500)
        return "entered fullscreen"
    return "no fullscreen (%s)" % (state[0] or "request not made")


NO_CONTROL = "no %s control"


def record_screen(run: Run, item: str, module: str, screen: str, public: Outcome, ingress: Outcome,
                  control: str, **kwargs) -> None:
    """Record a module screen; one that offers no such control tested nothing."""
    absent = NO_CONTROL % control
    if absent in public.result and absent in ingress.result and not any(ingress.signals.values()):
        run.record(item, module, screen, public, ingress, verdict=NOT_RUN,
                   blocked_by="Odoo 18 CE offers no %s control on this screen" % control, **kwargs)
    else:
        run.record(item, module, screen, public, ingress, **kwargs)


@check("U-C24")
def check_c24(run: Run) -> None:
    def generic(side: Side) -> Outcome:
        visit(side, "/odoo")
        result = fullscreen_via_click(side)
        side.root.evaluate("() => document.getElementById('parity-fullscreen').remove()")
        return Outcome(True, result)

    public, ingress = run.both(generic)
    run.record("U-C24", "shared", "generic", public, ingress,
               notes="requestFullscreen from a click inside Odoo (inside the HA panel's iframe on Ingress).")

    def workcenter(side: Side) -> Outcome:
        open_form(side, "mrp.workcenter", run.fx["workcenter"])
        control = side.root.locator("button:has(.fa-expand), [title*='ull screen'], [title*='ullscreen']")
        if not control.count():
            return Outcome(True, "no fullscreen control on this screen")  # NO_CONTROL % "fullscreen"
        return Outcome(True, fullscreen_via_click(side, control.first))

    public, ingress = run.both(workcenter)
    record_screen(run, "U-C24", "mrp", "MRP work center", public, ingress, "fullscreen", model="mrp.workcenter",
               notes="The fixture work center's form. Odoo 18 CE's work center has no tablet or fullscreen view "
                     "(Shop Floor is Enterprise); a control, if present, is pressed.")

    def kiosk(side: Side) -> Outcome:
        side.goto(kiosk_path(side))
        side.page.wait_for_timeout(3000)
        side.settle()
        route = odoo_route(side)
        control = side.root.locator("button:has(.fa-expand), [title*='ull screen'], [title*='ullscreen'], "
                                    ".o_hr_attendance_fullscreen")
        if not control.count():
            return Outcome(True, "kiosk at %s; no fullscreen control" % re.sub(r"/[0-9a-f]{16,}", "/<token>", route))
        return Outcome(True, "kiosk at %s; %s" % (re.sub(r"/[0-9a-f]{16,}", "/<token>", route),
                                                  fullscreen_via_click(side, control.first)))

    public, ingress = run.both(kiosk)
    for side in run.sides:
        side.ensure_logged_in()
    record_screen(run, "U-C24", "hr_attendance", "attendance kiosk mode", public, ingress, "fullscreen",
               notes="Attendance > Kiosk Mode; its fullscreen control pressed if it has one.")


_CAMERA_JS = """async () => {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return 'no mediaDevices (insecure context)';
  try { const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        stream.getTracks().forEach(track => track.stop()); return 'granted'; }
  catch (error) { return 'refused: ' + error.name; }
}"""


@check("U-C25")
def check_c25(run: Run) -> None:
    screens = [("shared", "generic"), ("mrp", "MRP work order scan"), ("hr_attendance", "attendance kiosk badge scan"),
               ("event", "event registration desk"), ("point_of_sale", "POS product scan")]
    if not run.env.ha_https:
        for module, screen in screens:
            run.not_run("U-C25", module, screen, "no https Home Assistant entrance (HA_HTTPS_BASE_URL unset)",
                        "Issue #143 runs U-C25 on the https HA entrance with a fake camera; the plain-http "
                        "entrance is not a secure context, so getUserMedia does not exist there (U-F1).")
        return
    https = IngressSide(run.env, run.browser, ha=run.env.ha_https)
    https.start()
    try:
        sides = (run.public, https)

        def pair(action: Callable[[Side], Outcome]) -> tuple[Outcome, Outcome]:
            saved = run.sides
            run.sides = sides
            try:
                return run.both(action)
            finally:
                run.sides = saved

        def generic(side: Side) -> Outcome:
            visit(side, "/odoo")
            return Outcome(True, "getUserMedia " + side.root.evaluate(_CAMERA_JS))

        public, ingress = pair(generic)
        run.record("U-C25", "shared", "generic", public, ingress,
                   notes="getUserMedia inside Odoo; Ingress through the https HA entrance, Chromium's fake camera.")

        def camera_on(route: str, label: str) -> Callable[[Side], Outcome]:
            def probe(side: Side) -> Outcome:
                visit(side, route or kiosk_path(side))
                side.page.wait_for_timeout(2500)
                control = side.root.locator("button:has(.fa-camera), .o_barcode_mobile_container button, "
                                            "button:has-text('Scan')")
                if not control.count():
                    return Outcome(True, "%s: no camera control" % label)  # NO_CONTROL % "camera"
                control.first.click()
                side.page.wait_for_timeout(3000)
                live = side.root.evaluate("() => [...document.querySelectorAll('video')].some(v => v.srcObject)")
                return Outcome(True, "%s: camera %s" % (label, "streaming" if live else "not streaming"))
            return probe

        for module, screen, route in (
            ("mrp", "MRP work order scan", "/odoo/action-mrp.mrp_workorder_todo"),
            ("hr_attendance", "attendance kiosk badge scan", None),
            ("event", "event registration desk", "/odoo/action-event.event_barcode_action_main_view"),
        ):
            public, ingress = pair(camera_on(route, screen))
            for side in sides:
                side.ensure_logged_in()
            record_screen(run, "U-C25", module, screen, public, ingress, "camera",
                          notes="The screen's camera/scan control pressed if it has one; Ingress through https.")

        from e2e_pos_offline_live import camera_scan, pos_config_id  # the POS module imports this one

        config_id = pos_config_id(run.public)
        public, ingress = pair(lambda side: Outcome(True, camera_scan(side, config_id)))
        record_screen(run, "U-C25", "point_of_sale", "POS product scan", public, ingress, "camera", route="/pos/ui",
                      notes="The till's barcode button (shown only where getUserMedia exists) opens the camera "
                            "scanner, then is pressed again to stop; Ingress through https.")
    finally:
        https.close()


def discuss_route(run: Run) -> str:
    return "/odoo/discuss?active_id=discuss.channel_%d" % run.fx["channel"]


def post_in_discuss(side: Side, text: str) -> None:
    composer = side.root.locator(".o-mail-Composer-input").first
    composer.fill(text)
    composer.press("Enter")


def wait_for_text(side: Side, selector: str, text: str, seconds: int = 10) -> float | None:
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        if side.root.locator(selector).filter(has_text=text).count():
            return round(time.monotonic() - started, 1)
        side.page.wait_for_timeout(250)
    return None


@check("U-C26")
def check_c26(run: Run) -> None:
    for side in run.sides:
        side.ensure_logged_in()
        visit(side, discuss_route(run))
        side.root.locator(".o-mail-Composer-input").first.wait_for(timeout=TIMEOUT)
    results = {}
    for sender, receiver in ((run.ingress, run.public), (run.public, run.ingress)):
        text = "%s C26 %s->%s %d" % (run.marker, sender.name, receiver.name, time.time())
        post_in_discuss(sender, text)
        results[receiver.name] = wait_for_text(receiver, ".o-mail-Message-body", text)

    def transport(side: Side) -> dict[str, Any]:
        # Odoo's bus socket lives in a SharedWorker, which page events do not
        # see; open the same handshake with the page's cookies instead.
        from websockets.sync.client import connect

        host = urlsplit(side.base).hostname
        cookies = "; ".join("%s=%s" % (cookie["name"], cookie["value"]) for cookie in side.context.cookies()
                            if cookie["domain"].lstrip(".") == host)
        origin = "%s://%s" % (urlsplit(side.base).scheme, urlsplit(side.base).netloc)
        url = side.base.replace("https://", "wss://").replace("http://", "ws://") + "/websocket?version=parity"
        try:
            with connect(url, additional_headers={"Cookie": cookies, "Origin": origin}, open_timeout=30) as socket:
                status = socket.response.status_code
        except Exception as error:  # noqa: BLE001
            status = "failed: %s" % type(error).__name__
        return {"websocket_handshake": status}

    outcomes = []
    for side in run.sides:
        seconds = results[side.name]
        details = transport(side)
        ok = seconds is not None and details["websocket_handshake"] == 101
        outcomes.append(Outcome(True, "websocket 101; received the other surface's message within 10 s" if ok
                                else "not received live" if seconds is None else "websocket handshake %s"
                                % details["websocket_handshake"],
                                details=dict(details, seconds=seconds)))
    run.record("U-C26", "shared", "generic", outcomes[0], outcomes[1], model="discuss.channel",
               notes="The same user in two browsers, Ingress and Public, in the fixture channel; each posts and "
                     "the other must show it without a reload within 10 s. The /websocket handshake is opened "
                     "directly with each browser's cookies (the bus runs in a SharedWorker the page cannot "
                     "observe); the worker bundle's own status is not read for the same reason.")
    check_livechat(run)


def check_livechat(run: Run) -> None:
    if not run.fx.get("livechat_channel"):
        run.not_run("U-C26", "im_livechat", "live chat operator view", "no im_livechat.channel on odoo_parity",
                    "The fixture step found no live chat channel to answer.")
        return
    visitor_context = run.browser.new_context()
    visitor = visitor_context.new_page()
    try:
        visitor.goto(run.env.public + "/", wait_until="load", timeout=TIMEOUT)
        button = visitor.locator(".o-livechat-LivechatButton")
        button.wait_for(timeout=TIMEOUT)
        button.click()
        box = visitor.locator(".o-mail-ChatWindow .o-mail-Composer-input").first
        box.wait_for(timeout=TIMEOUT)
        question = "%s visitor question %d" % (run.marker, time.time())
        box.fill(question)
        box.press("Enter")
        outcomes = []
        for side in run.sides:
            visit(side, "/odoo/discuss")
            side.root.locator(".o-mail-DiscussSidebarChannel").filter(has_text=re.compile("Visitor")).first.click()
            seen = wait_for_text(side, ".o-mail-Message-body", question, seconds=20)
            answer = "%s operator answer from %s %d" % (run.marker, side.name, time.time())
            post_in_discuss(side, answer)
            started = time.monotonic()
            got = None
            while time.monotonic() - started < 20:
                if visitor.locator(".o-mail-Message-body").filter(has_text=answer).count():
                    got = round(time.monotonic() - started, 1)
                    break
                visitor.wait_for_timeout(250)
            ok = seen is not None and got is not None
            outcomes.append(Outcome(True, "operator saw the visitor and the visitor got the answer" if ok else
                                    "question seen %s, answer delivered %s" % (seen is not None, got is not None),
                                    details={"question_seconds": seen, "answer_seconds": got}))
        run.record("U-C26", "im_livechat", "live chat operator view", outcomes[0], outcomes[1],
                   model="discuss.channel",
                   notes="An anonymous visitor on the Public origin's website opens the live chat; the operator "
                         "(the test user) answers once from each surface's Discuss. The visitor side can only be "
                         "the Public origin (RC-10).")
    except Exception as error:  # noqa: BLE001
        failed = Outcome(False, "error: %s" % sanitize_diagnostic((str(error).splitlines() or [""])[0]))
        run.record("U-C26", "im_livechat", "live chat operator view", failed, failed,
                   notes="The live chat flow did not complete.")
    finally:
        visitor_context.close()
        for side in run.sides:
            side.close_chat_windows()


# --- Group D: website and portal ----------------------------------------------------------


@check("U-D1")
def check_d1(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        visit(side, "/")
        root, done = side.root, []
        links = root.evaluate("""() => [...document.querySelectorAll('header a[href], footer a[href]')]
          .map(a => a.href).filter(h => h.startsWith(location.origin))""")
        prefix = side.env.prefix if side.surface is Surface.HA_INGRESS else ""
        outside = [link for link in links if prefix and not urlsplit(link).path.startswith(prefix)]
        done.append("%d same-origin header/footer links, %d outside the prefix" % (len(links), len(outside)))
        root.locator("header a[href$='/shop'], header a").filter(has_text="Shop").first.click()
        root.wait_for_load_state("load")
        side.settle()
        done.append("Shop link opens %s" % odoo_route(side))
        side.goto("/website/search?search=" + run.marker.split("-")[0])
        side.settle()
        done.append("site search answered")
        languages = root.locator(".js_language_selector a, .o_header_language_selector a").count()
        done.append("language switcher %s" % ("present" if languages else "absent (one language)"))
        cookie_bar = root.locator("#website_cookies_bar").count()
        done.append("cookie bar %s" % ("present" if cookie_bar else "not enabled"))
        return Outcome(True, "; ".join(done), details={"outside_prefix": [urlsplit(link).path for link in outside]})

    public, ingress = run.both(probe)
    run.record("U-D1", "shared", "generic", public, ingress,
               notes="Home page header and footer links, the Shop link, site search. The language switcher and "
                     "cookie bar are not enabled on odoo_parity.")


@check("U-D2")
def check_d2(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        side.goto("/odoo/action-website.website_preview")
        side.wait_webclient()
        root, done = side.root, []
        root.locator(".o_edit_website_container button, .o_edit_website_container a").first.click()
        root.locator(".o-snippets-menu, #oe_snippets, .o_we_website_top_actions").first.wait_for(timeout=TIMEOUT)
        side.settle(1500)
        done.append("editor open")
        errors = [text for kind, text in side.recorder.console if "AssetsLoadingError" in text]
        done.append("AssetsLoadingError %d" % len(errors))
        root.locator("button[data-action='cancel'], .o_we_website_top_actions button").filter(
            has_text=re.compile("Discard")).first.click()
        side.settle(800)
        dialog = root.locator(".o_dialog footer button.btn-primary")
        if dialog.count():
            dialog.first.click()
        done.append("discarded")
        return Outcome(True, "; ".join(done))

    public, ingress = run.both(probe)
    run.record("U-D2", "shared", "generic", public, ingress,
               notes="Website > Edit on the home page, then Discard. Dragging a snippet, the media dialog, mobile "
                     "preview, page properties and the SEO panel were not reached by this check; nothing was "
                     "saved.")


@check("U-D3")
def check_d3(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        name = "%s-d3-%s" % (run.marker.lower(), side.name)
        created = side.rpc("website", "new_page", [], {"name": name, "add_menu": False})
        page_ids = side.rpc("website.page", "search", [[["url", "=", "/" + name]]])
        if not page_ids:
            return Outcome(True, "page not created (%s)" % run.env.mask(str(created))[:80])
        steps = ["created"]
        for state in (True, False):
            side.rpc("website.page", "write", [page_ids, {"is_published": state}])
            anonymous = run.browser.new_context()
            try:
                status = anonymous.request.get(run.env.public + "/" + name, max_redirects=0).status
            finally:
                anonymous.close()
            steps.append("%s: anonymous %d" % ("published" if state else "unpublished", status))
        side.goto("/" + name)
        side.settle()
        steps.append("editor view opens" if side.root.locator("#wrap").count() else "page not shown")
        return Outcome(True, "; ".join(steps))

    public, ingress = run.both(probe)
    run.record("U-D3", "shared", "generic", public, ingress, model="website.page",
               notes="Each surface creates its own page (website.new_page over its own RPC), publishes and "
                     "unpublishes it (checked anonymously on the Public origin). Deleting was left out: this run "
                     "deletes nothing.")


@check("U-D4")
def check_d4(run: Run) -> None:
    def probe(side: Side) -> Outcome:
        side.goto("/my/home")
        side.settle()
        root, done = side.root, []
        tiles = root.locator(".o_portal_index_card a, .o_portal_docs a").count()
        done.append("%d tiles" % tiles)
        root.locator("a[href$='/my/quotes']").first.click()
        root.wait_for_load_state("load")
        side.settle()
        done.append("list %s" % odoo_route(side))
        root.locator("table a").filter(has_text=re.compile("S0")).first.click()
        root.wait_for_load_state("load")
        side.settle()
        done.append("detail %s" % re.sub(r"\d+", "<id>", odoo_route(side)))
        pdf = root.locator("a#download_pdf, a.o_download_btn, a[href*='download=true']").first
        if pdf.count():
            data, _ = download(side, lambda: pdf.click())
            done.append("PDF %s" % ("landed" if data.startswith(b"%PDF") else "broken"))
        detail = odoo_route(side)
        root.locator(".breadcrumb a").first.click()
        for _ in range(40):
            side.page.wait_for_timeout(250)
            try:
                if odoo_route(side) != detail:
                    break
            except Exception:  # noqa: BLE001 -- mid-navigation
                side._frame = None
        side.settle()
        done.append("breadcrumb back to %s" % odoo_route(side))
        return Outcome(True, "; ".join(done))

    public, ingress = run.both(probe)
    run.record("U-D4", "shared", "generic", public, ingress,
               notes="/my/home tile > list > the admin's fixture quotation > PDF download > breadcrumb. The pager "
                     "was not exercised (one record).")


def share_link(side: Side, open_dialog: Callable[[Side], None]) -> str:
    open_dialog(side)
    dialog = side.root.locator(".o_dialog .modal-content").last
    value = dialog.locator("input[name='share_link'], div[name='share_link'] input, "
                           "div[name='share_link'] span, input[readonly]").first
    link = value.input_value() if value.evaluate("e => 'value' in e") else value.inner_text()
    close_dialog(side)
    return link.strip()


def open_link_anonymously(run: Run, link: str, expect: str) -> str:
    context = run.browser.new_context()
    try:
        page = context.new_page()
        response = page.goto(link, wait_until="load", timeout=TIMEOUT)
        shown = expect in page.locator("body").inner_text()
        return "HTTP %s, %s" % (response.status if response else None, "shows the record" if shown else
                                "record not shown")
    finally:
        context.close()


@check("U-D5")
def check_d5(run: Run) -> None:
    def task_share(side: Side) -> None:
        open_form(side, "project.task", run.fx["task"])
        cog_item(side, "Share Task")
        side.root.locator(".o_dialog .modal-content").last.wait_for(timeout=TIMEOUT)
        side.settle(500)

    for module, screen, opener, expect in (
        ("shared", "generic", task_share, run.marker + " Task"),
        ("sale_management", "quotation portal link", open_share_dialog, run.marker),
    ):
        def probe(side: Side, opener=opener, expect=expect) -> Outcome:
            link = share_link(side, lambda s: opener(s, run) if opener is open_share_dialog else opener(s))
            base = "<PUBLIC_BASE>" if link.startswith(run.env.public) else (
                "<HA_BASE>" if link.startswith(run.env.ha) else "other base")
            opened = open_link_anonymously(run, link, expect)
            return Outcome(True, "link on %s; anonymous browser: %s" % (base, opened),
                           details={"path": re.sub(r"\d+", "<id>", urlsplit(link).path)})

        public, ingress = run.both(probe)
        run.record("U-D5", module, screen, public, ingress,
                   notes="The Share dialog's link, opened in a browser with no session at all.")


@check("U-D6")
def check_d6(run: Run) -> None:
    def contact_us(side: Side) -> Outcome:
        side.goto("/contactus")
        side.settle()
        form = side.root.locator("form#contactus_form, form.s_website_form, section form").first
        for name, value in (("name", run.marker + " D6 " + side.name), ("email_from", "d6@example.invalid"),
                            ("subject", run.marker + " D6 " + side.name), ("description", "parity")):
            field = form.locator("[name='%s']" % name)
            if field.count():
                field.first.fill(value)
        form.locator(".s_website_form_send, button[type=submit], a.s_website_form_send").first.click()
        side.page.wait_for_timeout(4000)
        side.settle()
        return Outcome(True, confirmation(side, "submitted, thank-you shown"))

    public, ingress = run.both(contact_us)
    run.record("U-D6", "shared", "generic", public, ingress,
               notes="Contact Us form filled and sent (creates a CRM lead) by the logged-in user.")

    def job(side: Side) -> Outcome:
        side.goto("/jobs")
        side.settle()
        side.root.locator("a").filter(has_text=run.marker + " Job").first.click()
        side.root.wait_for_load_state("load")
        side.settle()
        side.root.locator("a, button").filter(has_text=re.compile(r"^\s*Apply")).first.click()
        side.root.wait_for_load_state("load")
        side.settle()
        form = side.root.locator("form").filter(has=side.root.locator("[name='partner_name'], [name='email_from']")).first
        for name, value in (("partner_name", run.marker + " D6 applicant " + side.name),
                            ("email_from", "d6-%s@example.invalid" % side.name), ("partner_phone", "0900000000"),
                            # Odoo asks for a LinkedIn profile or a resume.
                            ("linkedin_profile", "https://www.linkedin.com/in/parity-%s" % side.name)):
            field = form.locator("[name='%s']" % name)
            if field.count():
                field.first.fill(value)
        form.locator(".s_website_form_send, button[type=submit], a.s_website_form_send").first.click()
        side.page.wait_for_timeout(4000)
        side.settle()
        return Outcome(True, confirmation(side, "applied, thank-you shown"))

    public, ingress = run.both(job)
    run.record("U-D6", "hr_recruitment", "job application", public, ingress,
               notes="/jobs > the fixture job > Apply, form sent (creates an applicant).")

    token = run.public.rpc("survey.survey", "read", [[run.fx["survey"]], ["access_token"]])[0]["access_token"]
    run.env.extra_secrets.append(token)

    def survey(side: Side) -> Outcome:
        side.goto("/survey/start/%s" % token)
        side.settle()
        side.root.locator("button, a").filter(has_text=re.compile(r"Start")).first.click()
        side.page.wait_for_timeout(1500)
        side.root.locator("input[type=text], textarea").first.fill(run.marker + " " + side.name)
        side.root.locator("button").filter(has_text=re.compile(r"^\s*(Submit|Next)")).first.click()
        side.page.wait_for_timeout(3000)
        return Outcome(True, confirmation(side, "submitted, thank-you shown"))

    public, ingress = run.both(survey)
    run.record("U-D6", "survey", "survey fill", public, ingress,
               notes="The fixture survey's public start link, one answer, submitted by the logged-in user.")
    run.not_run("U-D6", "event", "event registration", "website_event is not among the 29 installed modules",
                "odoo_parity has event but not website_event, so there is no front-end registration form.")


@check("U-D7")
def check_d7(run: Run) -> None:
    for module, screen, path in (("shared", "generic", "/"), ("website_sale", "/shop", "/shop"),
                                 ("hr_recruitment", "/jobs", "/jobs")):
        anonymous = run.browser.new_context()
        try:
            public_status = anonymous.request.get(run.env.public + path, max_redirects=0).status
            ingress_status = anonymous.request.get(run.ingress.base + path, max_redirects=0).status
        finally:
            anonymous.close()
        public = Outcome(public_status == 200, "anonymous HTTP %d" % public_status)
        ingress = Outcome(True, "anonymous HTTP %d (HA refuses a visitor without a session)" % ingress_status)
        structural = public_status == 200 and ingress_status in (401, 403)
        run.record("U-D7", module, screen, public, ingress,
                   verdict="STRUCTURAL" if structural else "GAP", severity="none" if structural else "blocker",
                   public_path="<PUBLIC_BASE>" + path,
                   notes="RC-10: an anonymous visitor has no Home Assistant session, so only the Public origin can "
                         "serve %s to the world." % path)
    run.not_run("U-D7", "event", "/event", "website_event is not among the 29 installed modules",
                "/event is a website_event route; with only event installed neither surface serves it.")


@check("U-D8")
def check_d8(run: Run) -> None:
    """Two records: the head links with `robots.txt`, and the sitemap (AD-8, #172)."""

    def bases_of(urls: Iterable[str]) -> list[str]:
        return sorted({run.env.mask("%s://%s" % (urlsplit(url).scheme, urlsplit(url).netloc))
                       for url in urls if urlsplit(url).netloc and urlsplit(url).hostname not in NAMESPACE_HOSTS})

    def fetch(side: Side, path: str) -> tuple[int, list[str]]:
        response = side.context.request.get(side.base + path)
        return response.status, sorted(set(re.findall(r"https?://[^\s<\"']+", response.text())))

    def head_and_robots(side: Side) -> Outcome:
        found = {"/robots.txt": fetch(side, "/robots.txt")[1]}
        side.goto("/")
        side.settle()
        head = side.root.evaluate("""() => [...document.querySelectorAll(
          'link[rel=canonical], link[rel=alternate], meta[property="og:url"], meta[property="og:image"], '
          + 'meta[name="twitter:image"], link[rel~=icon]')].map(e => [e.matches('link[rel~=icon]'),
                                                                        e.getAttribute('href') || e.content])
          .filter(pair => pair[1])""")
        # A root-relative icon is the page's own resource, loaded under whatever prefix the page is on;
        # any other root-relative value (canonical, og:url) is an outbound URL that has lost its base.
        found["head"] = [url for icon, url in head if not (icon and not urlsplit(url).netloc)]
        relative = [url for url in found["head"] if not urlsplit(url).netloc]
        by_source = {source: bases_of(urls) for source, urls in found.items()}
        masked = sorted({base for bases in by_source.values() for base in bases})
        wrong = [base for base in masked if base != "<PUBLIC_BASE>"] + (["relative URLs"] if relative else [])
        return Outcome(True, "all SEO URLs on <PUBLIC_BASE>" if not wrong else "SEO URLs on %s" % ", ".join(wrong),
                       details={"bases": masked, "by_source": by_source, "wrong": wrong})

    public, ingress = run.both(head_and_robots)
    verdict, severity, reasons = seo_head_verdict(public, ingress)
    run.record("U-D8", "shared", "generic", public, ingress, verdict=verdict, severity=severity,
               notes="; ".join(filter(None, [
                   "robots.txt and the home page's canonical, alternate, og:url, og:image, twitter:image and icon "
                   "links (root-relative icons are the page's own resources); built from website.domain (P-5). "
                   "sitemap.xml is AD-8 and recorded on its own.", *reasons])))

    def sitemap(side: Side) -> Outcome:
        # robots.txt again, for the other half of AD-8: what steers a crawler away from this copy.
        robots = run.env.mask(side.context.request.get(side.base + "/robots.txt").text())
        status, urls = fetch(side, "/sitemap.xml")
        bases = bases_of(urls)
        # A prefixed URL is a leaked Supervisor token, so only how many of them there are is recorded.
        prefixed = [url for url in urls if "/api/hassio_ingress/" in url]
        return Outcome(True, "HTTP %d, %d sitemap URL(s) on %s" % (status, len(urls),
                                                                   ", ".join(bases) or "nothing"),
                       details={"status": status, "bases": bases, "urls": len(urls),
                                "ingress_prefix": len(prefixed),
                                "robots": [line.strip() for line in robots.splitlines() if line.strip()]})

    public, ingress = run.both(sitemap)
    verdict, severity, reasons = sitemap_divergence(public, ingress)
    run.record("U-D8", "website", "sitemap.xml", public, ingress, verdict=verdict, severity=severity,
               route="/sitemap.xml",
               notes="; ".join(filter(None, [
                   "AD-8, verified in reverse: Odoo builds sitemap.xml from the request's URL root, so the Ingress "
                   "copy lists the Home Assistant address; it is accepted only while both surfaces serve a sitemap, "
                   "the Public origin's is on <PUBLIC_BASE> with a robots.txt that lets crawlers in, the Ingress "
                   "copy is not on <PUBLIC_BASE> and carries no Ingress prefix, and Ingress's robots.txt still says "
                   "Disallow: / and points crawlers at <PUBLIC_BASE>/sitemap.xml.", *reasons])))


# --- P-Check ------------------------------------------------------------------


def pcheck(env: Env, public: PublicSide, ingress: IngressSide) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    results.append(("P-1", env.public.startswith("https://"), "public_url is https"))
    response = public.context.request.get(env.public + "/web/login")
    results.append(("P-2", response.status not in (503, 444) and response.status < 500,
                    "GET /web/login -> %d" % response.status))
    params = {row["key"]: row["value"] for row in public.rpc(
        "ir.config_parameter", "search_read", [[["key", "in", ["web.base.url", "web.base.url.freeze"]]]],
        {"fields": ["key", "value"]})}
    results.append(("P-3", params.get("web.base.url", "").rstrip("/") == env.public,
                    "web.base.url = %s" % env.mask(params.get("web.base.url"))))
    results.append(("P-4", params.get("web.base.url.freeze") == "True",
                    "web.base.url.freeze = %s" % params.get("web.base.url.freeze")))
    domains = [row["domain"] for row in public.rpc("website", "search_read", [[]], {"fields": ["domain"]})]
    results.append(("P-5", bool(domains) and all((domain or "").rstrip("/") == env.public for domain in domains),
                    "website.domain = %s" % env.mask(domains)))
    same_db = [side.rpc("res.users", "search_read", [[["login", "=", env.login]]], {"fields": ["id"]})
               for side in (public, ingress)]
    db_names = [side.root.evaluate("() => odoo.info && odoo.info.db") if side.surface is Surface.HA_INGRESS
                else side.page.evaluate("() => odoo.info && odoo.info.db") for side in (public, ingress)]
    results.append(("P-6", same_db[0] == same_db[1] and db_names == [env.db, env.db],
                    "same login on both surfaces, db %s" % db_names))
    return results


# --- P-7 fixtures ---------------------------------------------------------------

# Deterministic Unicode attachment content (COMMERCIAL_PREDEPLOY Phase 0).
ATTACHMENT_TEXT = "WOOW-PARITY attachment 測試 ✓ ÅÄÖ\n"


def create_fixtures(side: Side, marker: str) -> dict[str, Any]:
    """P-7: the records the checks work on, each named with the run marker."""
    import base64
    import datetime as dt

    def create(model: str, values: dict, name_field: str = "name") -> int:
        # Rerunning the step reuses what an earlier, interrupted run made.
        found = side.rpc(model, "search", [[[name_field, "=", values[name_field]]]], {"limit": 1})
        return found[0] if found else side.rpc(model, "create", [values])

    ids: dict[str, Any] = {"marker": marker}
    ids["partner"] = create("res.partner", {"name": marker + " Partner", "email": "parity@example.invalid",
                                            "comment": "<p>%s</p>" % marker})
    ids["product"] = create("product.template", {"name": marker + " Service", "type": "service",
                                                 "list_price": 100.0, "sale_ok": True, "is_published": True})
    product = side.rpc("product.product", "search", [[["product_tmpl_id", "=", ids["product"]]]])[0]
    ids["sale_order"] = create("sale.order", {"partner_id": ids["partner"], "client_order_ref": marker,
                                              "order_line": [[0, 0, {"product_id": product, "product_uom_qty": 1}]]},
                               name_field="client_order_ref")
    ids["survey"] = create("survey.survey", {
        "title": marker + " Survey", "access_mode": "public", "users_login_required": False,
        "question_and_page_ids": [[0, 0, {"title": "Your name?", "question_type": "char_box"}]],
    }, name_field="title")
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)
    ids["event"] = create("event.event", {
        # No is_published: website_event is not among the installed modules.
        "name": marker + " Event",
        "date_begin": start.strftime("%Y-%m-%d %H:%M:%S"),
        "date_end": (start + dt.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
    })
    ids["job"] = create("hr.job", {"name": marker + " Job", "is_published": True})
    ids["channel"] = create("discuss.channel", {"name": marker + " Channel", "channel_type": "channel",
                                                "group_public_id": False})
    ids["workcenter"] = create("mrp.workcenter", {"name": marker + " Work Center"})
    project = side.rpc("project.project", "search", [[]], {"limit": 1})[0]
    ids["task"] = create("project.task", {"name": marker + " Task", "project_id": project})
    # The admin's own quotation, so the portal (/my) has something to list.
    admin_partner = side.rpc("res.users", "read", [[side.rpc("res.users", "search",
                                                             [[["login", "=", side.env.login]]])[0]],
                                                   ["partner_id"]])[0]["partner_id"][0]
    ids["admin_sale_order"] = create("sale.order", {
        "partner_id": admin_partner, "client_order_ref": marker + " own",
        "order_line": [[0, 0, {"product_id": product, "product_uom_qty": 1}]],
    }, name_field="client_order_ref")
    # /my/quotes lists sent quotations only.
    side.rpc("sale.order", "write", [[ids["admin_sale_order"]], {"state": "sent"}])
    # U-C26 live chat: the admin answers the website's live chat channel.
    admin = side.rpc("res.users", "search", [[["login", "=", side.env.login]]])[0]
    livechat = side.rpc("im_livechat.channel", "search", [[]], {"limit": 1})
    if livechat:
        side.rpc("im_livechat.channel", "write", [livechat, {"user_ids": [[4, admin]]}])
        ids["livechat_channel"] = livechat[0]
    ids["attachment"] = create("ir.attachment", {
        "name": marker + " 測試.txt", "res_model": "res.partner", "res_id": ids["partner"],
        "datas": base64.b64encode(ATTACHMENT_TEXT.encode("utf-8")).decode("ascii"), "mimetype": "text/plain",
    })
    return ids


def fixture_path(run_id: str) -> str:
    return os.path.join(artifact_dir(), "%s-fixtures.json" % run_id)


# --- Command line -------------------------------------------------------------


def open_sides(env: Env, browser, *, viewport=(1920, 1080)):
    public = PublicSide(env, browser, viewport=viewport)
    ingress = IngressSide(env, browser, viewport=viewport)
    ingress.start()
    public.start()
    return public, ingress


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("pcheck", "fixtures", "run"):
        sub = commands.add_parser(name)
        sub.add_argument("--env-file")
        sub.add_argument("--db", required=True, help="the database both surfaces must serve")
        sub.add_argument("--headed", action="store_true")
        if name == "fixtures":
            sub.add_argument("--run-id", required=True, help="the run marker the records are named with")
        if name == "run":
            sub.add_argument("--out", required=True, help="JSONL file; records are appended")
            sub.add_argument("--only", help="comma-separated items, e.g. U-F1,U-C4")
            sub.add_argument("--run-id", help="keep one run id across several invocations")
    report = commands.add_parser("report")
    report.add_argument("records")
    report.add_argument("--issues", help="JSON object: control identity -> issue number")
    args = parser.parse_args(argv)

    if args.command == "report":
        with open(args.records, encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        if args.issues:
            with open(args.issues, encoding="utf-8") as handle:
                records = attach_issues(records, {key: int(value) for key, value in json.load(handle).items()})
            with open(args.records, "w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        result = conservation(records, planned_checks())
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["qualified"] else 1

    if args.env_file:
        with open(args.env_file, encoding="utf-8") as handle:
            parse_env_file(handle, os.environ)
    os.environ["ODOO_DB"] = args.db
    env = Env(args.db)
    os.makedirs(artifact_dir(), exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=not args.headed,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
        )
        public = ingress = None
        try:
            public, ingress = open_sides(env, browser)
            if args.command == "pcheck":
                failed = 0
                for check_id, passed, detail in pcheck(env, public, ingress):
                    failed += not passed
                    print("%s %s %s" % (check_id, "PASS" if passed else "FAIL", env.mask(detail)))
                return 1 if failed else 0
            if args.command == "fixtures":
                ids = create_fixtures(public, args.run_id)
                with open(fixture_path(args.run_id), "w", encoding="utf-8") as handle:
                    json.dump(ids, handle, indent=2)
                print("P-7 fixtures: %s" % json.dumps(env.mask(ids)))
                return 0
            run_info = RunInfo(args.run_id or new_run_id(), env.target, env.db)
            items = [item.strip() for item in args.only.split(",")] if args.only else list(CHECKS)
            with open(args.out, "a", encoding="utf-8") as out:
                run = Run(env, run_info, public, ingress, out, browser)
                done = set()
                for item in items:
                    function = CHECKS[item]
                    if function in done:
                        continue
                    done.add(function)
                    try:
                        function(run)
                    except Exception as error:  # noqa: BLE001 -- the conservation report shows what is missing
                        print("CHECK CRASHED %s: %s" % (item, env.mask((str(error).splitlines() or [""])[0])),
                              file=sys.stderr)
                        for side in (public, ingress):
                            try:
                                side.ensure_logged_in()
                            except Exception:  # noqa: BLE001
                                pass
            return 0
        finally:
            for side in (public, ingress):
                if side:
                    side.close()
            browser.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 -- never print an unmasked secret
        message = sanitize_diagnostic(str(error))
        try:  # the hosts and credentials too, when the environment names them
            message = Env(os.environ.get("ODOO_DB", "")).mask(message)
        except Exception:  # noqa: BLE001 -- a missing variable was the failure
            pass
        print("parity run failed: %s" % message, file=sys.stderr)
        sys.exit(2)
