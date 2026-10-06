"""The Ingress checks that have no adapter subcommand, driven one at a time.

`e2e_menu_action_adapter.py` opens a screen and judges it against the same
screen on the other surface. Three of the things a Live run has to see are not
that shape -- they are one action taken in one browser, on one surface, whose
result is read somewhere else:

    visit     one website page view through Ingress. What it proves is in
              `website.track`, not on the page (#160: the row carries the
              Canonical URL).
    editbtn   the website page's "Edit this content" link. Its literal is a
              two-surface question the adapter already answers; whether
              *following* it opens the page in the web client is a click
              (#211).
    todosave  the To-do form's description saved in the HTML editor. What it
              proves is in `project.task.description` afterwards: the stored
              `src` is still root-relative (#210).

So this driver takes the action and records what it saw. The reading that
judges it is taken on the host afterwards, and goes in the evidence beside this
file's records -- `visit` and `todosave` cannot judge themselves, because what
they are about is in a database row.

Two things are deliberately **not** reimplemented here, because getting either
subtly wrong would make a record that looks clean:

- **Prefix escape** is `adapter.is_prefix_escape`. A first version of this file
  asked "did the request go to the Home Assistant origin outside the prefix",
  which silently misses the one shape #211 is about: a doubled prefix is still
  *under* the prefix, so it answered no. The adapter's version knows that, and
  the pure parts here are tested at the Static tier
  (`test_e2e_ingress_hand_checks.py`) so a rewrite cannot quietly lose it again.
- The login, the Ingress session, the session cookie, the database reading and
  the `Masker` are `adapter.SurfaceDriver`'s, so a record written here hides
  the same credentials, prefixes and origins the adapter's records hide.

    ~/venvs/woow/bin/python odoo18ce/tests/e2e_ingress_hand_checks.py visit \
      --env-file /projects/Woow_ha_odoo/.env --out hand-checks.jsonl

Each run appends one JSON object to `--out` and mints its own run id, which the
evidence README carries the way it carries the adapter's. Writing: `visit`
creates a `website.visitor` / `website.track` row, `todosave` writes
`project.task.description` (its marker names the run, so a later reader can
tell whose text it is), `editbtn` writes nothing. The boundary is ADR 0012.

**How many** ambient rows an invocation left is its own figure since #256, and
#264 gave it to this driver: each invocation counts `website.track` and
`website.visitor` over its own session's RPC after the login and again after the
step, and appends the delta to `--out`'s name with `.ambient.json` for its
extension (`hand-checks.jsonl` -> `hand-checks.ambient.json`) -- counts only, no
URL and no visitor identity, one line per invocation because the records append
too. `visit` is the one subcommand where that figure is the measurement rather
than accounting: it exists to make the tracking write. The denominator is every
document GET the browser context made under the Ingress base, which is the only
way to count `editbtn`'s click-driven navigation and the website editor's own
preview fetches. It is accounting and not a verdict -- `diff` never reads it and
the conservation tally does not move for it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Mapping, MutableMapping, Sequence
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import e2e_menu_action_adapter as adapter  # noqa: E402

MARKER_PREFIX = "WOOW-PARITY hand check"
HTML_FIELD = ".o_field_html"
EDITABLE = HTML_FIELD + " .odoo-editor-editable"
EDIT_BUTTON = "a.o_frontend_to_backend_edit_btn"
TODO_FORM = "/odoo/action-project_todo.project_task_action_todo/5"
SAVE_BUTTON = ".o_form_button_save"
# An unsaved record keeps the save/discard pair on screen.
UNSAVED = ".o_form_status_indicator_buttons:not(.invisible)"


class Signals:
    """What one page did, in the adapter's vocabulary, read on one surface.

    The adapter collects the same things through `count_signals` over a planned
    visit; these three checks are not planned visits, so the collection lives
    here and the *judgement* of each url is still the adapter's.
    """

    def __init__(self) -> None:
        self.requested: list[str] = []
        self.failed_responses: list[str] = []
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []

    def watch(self, page) -> None:
        page.on("request", lambda request: self.requested.append(request.url))
        page.on("response", lambda response: self.failed_responses.append(
            "HTTP%d %s" % (response.status, response.url)) if response.status >= 400 else None)
        page.on("console", lambda message: self.console_errors.append(
            "%s: %s" % (message.type, message.text)) if message.type == "error" else None)
        page.on("pageerror", lambda error: self.page_errors.append(str(error)))

    def escapes(self, driver) -> list[str]:
        """The requests that left the Ingress prefix, judged by the adapter."""
        return sorted({
            url for url in self.requested
            if adapter.is_prefix_escape(
                url, adapter.Surface.HA_INGRESS, driver.origin, driver.prefix)
        })

    def into(self, record: MutableMapping[str, Any], driver) -> None:
        record["route_escape"] = self.escapes(driver)
        record["http_4xx_5xx"] = sorted(set(self.failed_responses))
        record["console_error"] = self.console_errors[:40]
        record["pageerror"] = self.page_errors[:40]


def route_of(driver, url: str) -> str | None:
    """`url` with the Ingress prefix taken off, or None when it is not on it.

    The `Masker` writes `<INGRESS_BASE>` for the origin and the prefix
    together, so a recorded URL alone does not say which page was reached.
    This is the adapter's own normalisation, which is what the two-surface
    records are joined on.
    """
    try:
        return adapter.normalize_route(
            urlsplit(url).path, adapter.Surface.HA_INGRESS,
            ingress_prefix=driver.prefix).as_string()
    except ValueError:
        return None


def marker_for(run_id: str) -> str:
    """The text typed into the to-do description, naming the run that typed it.

    `docs/agents/live-tier.md` wants every writing step marked with its run id,
    so the host stays readable and the next run can tell whose text is whose.
    """
    return "%s %s" % (MARKER_PREFIX, run_id)


def do_visit(page, driver, record: MutableMapping[str, Any], path: str) -> None:
    page.goto(driver.base + path, wait_until="load", timeout=120000)
    # The tracked row is written by the dispatch of this page view; the wait is
    # for the page to finish, not for the row.
    page.wait_for_timeout(3000)
    record["url_after"] = page.url
    record["route_after"] = route_of(driver, page.url)
    record["title"] = page.title()


def preview_frames(page, driver, preview_selector: str | None) -> list[dict[str, Any]]:
    """Every frame of the website editor's preview, and what it is showing.

    The editor holds two: the page and the hidden fallback it navigates
    through. Which one is first in the DOM is not a contract, so all of them
    are recorded and the page is the one showing the selector. A link that
    resolved to the wrong path leaves only the fallback, with nothing of the
    page in it.
    """
    frames = []
    for handle in page.locator(".o_website_preview iframe").element_handles():
        frame = handle.content_frame()
        if frame is None:
            frames.append({"route": None, "title": None, "shows_selector": None,
                           "unreadable": "no content frame"})
            continue
        here: dict[str, Any] = {"route": route_of(driver, frame.url), "title": frame.title(),
                                "shows_selector": None, "unreadable": None}
        if preview_selector:
            try:
                here["shows_selector"] = frame.locator(preview_selector).count() > 0
            except Exception as error:                    # a frame that navigated away
                here["unreadable"] = type(error).__name__
        frames.append(here)
    return frames


def do_editbtn(page, driver, record: MutableMapping[str, Any], path: str,
               preview_selector: str | None = None) -> None:
    page.goto(driver.base + path, wait_until="load", timeout=120000)
    page.wait_for_timeout(2000)
    buttons = page.locator(EDIT_BUTTON)
    record["button_count"] = buttons.count()
    if not record["button_count"]:
        record["error"] = "no %s on this page: the user cannot edit it" % EDIT_BUTTON
        return
    button = buttons.first
    # The attribute is what the bundle built; the property is what the browser
    # resolved it against. #211 is about the attribute, and a relative
    # attribute with the right property would still be a pass.
    record["href_attribute"] = button.get_attribute("href")
    record["href_resolved"] = button.evaluate("element => element.href")
    button.click()
    page.wait_for_load_state("load", timeout=120000)
    page.wait_for_timeout(5000)
    record["url_after"] = page.url
    record["route_after"] = route_of(driver, page.url)
    record["navbar"] = page.locator(".o_main_navbar").count() > 0
    record["website_preview"] = page.locator(".o_website_preview").count() > 0
    if record["website_preview"]:
        record["preview_iframe_src"] = page.locator(
            ".o_website_preview iframe").first.get_attribute("src")
        frames = preview_frames(page, driver, preview_selector)
        record["preview_frames"] = frames
        record["preview_shows_selector"] = (
            any(frame["shows_selector"] is True for frame in frames)
            if preview_selector else None)


def do_todosave(page, driver, record: MutableMapping[str, Any], marker: str,
                *, save: bool = True) -> None:
    page.goto(driver.base + TODO_FORM, wait_until="load", timeout=120000)
    editable = page.locator(EDITABLE).first
    editable.wait_for(timeout=60000)
    page.wait_for_timeout(3000)
    images = page.locator(HTML_FIELD + " img")
    # What the editor put in the DOM, what the browser resolved it to, and
    # whether the picture actually arrived. #210's fix is the first of these
    # carrying the prefix and the third being true.
    record["img_src_attribute"] = images.evaluate_all(
        "els => els.map(e => e.getAttribute('src'))")
    record["img_src_resolved"] = images.evaluate_all("els => els.map(e => e.src)")
    record["img_loaded"] = images.evaluate_all(
        "els => els.map(e => e.complete && e.naturalWidth > 0)")
    record["saved"] = save
    if not save:
        # Reading the editor without writing it: what the field rendered is
        # already the whole of #210's render-site half, and a run that is only
        # confirming the selectors still work should not write the record.
        return
    record["marker"] = marker
    editable.click()
    page.keyboard.press("End")
    page.keyboard.type(" " + marker)
    page.wait_for_timeout(1000)
    save_button = page.locator(SAVE_BUTTON).first
    record["save_button"] = save_button.count() > 0
    save_button.click()
    page.wait_for_timeout(8000)
    record["url_after"] = page.url
    record["unsaved_after_save"] = page.locator(UNSAVED).count() > 0


def run(command: str, out_path: str, *, path: str, marker: str | None = None,
        save: bool = True, preview_selector: str | None = None) -> int:
    from playwright.sync_api import sync_playwright

    ignore_https = os.environ.get("IGNORE_HTTPS_ERRORS", "0") == "1"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        driver = None
        try:
            driver = adapter.SurfaceDriver(
                adapter.Surface.HA_INGRESS, browser,
                ignore_https_errors=ignore_https, viewport=(1920, 1080),
            )
            driver.log_in()
            run_id = adapter.new_run_id()
            info = adapter.RunInfo(run_id=run_id, target=os.environ.get("PARITY_TARGET", "local"),
                                   database=adapter.session_database(driver.database))
            record: dict[str, Any] = {
                "check": command,
                "surface": adapter.Surface.HA_INGRESS.value,
                "database": info.database,
                "run_id": info.run_id,
                "target": info.target,
            }
            # The ambient rows this invocation leaves, counted by the invocation
            # itself (#256, #264). `visit` exists to make that write -- `U-C5` is
            # judged from the `website.track` row and not from the page -- so here
            # the figure is the point and not a footnote. The denominator is the
            # document counter and not `driver.navigations`: the three steps below
            # navigate with `page.goto`, `editbtn` navigates again by clicking a
            # link, and the website editor's preview iframe fetches documents of
            # its own, none of which `SurfaceDriver._goto` sees.
            ambient = adapter.SessionAmbientDriver(driver, reading=driver.ambient_reading)
            with adapter.ambient_accounting(ambient, info, adapter.Surface.HA_INGRESS, out_path,
                                            command=command, append=True,
                                            navigation_basis=adapter.AMBIENT_BASIS_DOCUMENTS):
                signals = Signals()
                page = driver.context.new_page()
                signals.watch(page)
                try:
                    if command == "visit":
                        do_visit(page, driver, record, path)
                    elif command == "editbtn":
                        do_editbtn(page, driver, record, path, preview_selector)
                    else:
                        do_todosave(page, driver, record, marker or marker_for(run_id), save=save)
                finally:
                    signals.into(record, driver)
                    page.close()
                line = json.dumps(driver.masker.value(record), ensure_ascii=False, sort_keys=True)
                with open(out_path, "a", encoding="utf-8") as out:
                    out.write(line + "\n")
                print(line)
            return 0
        finally:
            if driver is not None:
                driver.close()
            browser.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["visit", "editbtn", "todosave"])
    parser.add_argument("--out", required=True, help="JSONL evidence file; appended to")
    parser.add_argument("--path", default="/", help="website path for visit and editbtn")
    parser.add_argument("--marker", help="todosave: text typed into the description "
                                         "(default: the run id, so the host stays readable)")
    parser.add_argument("--env-file", help="read unset credentials from this NAME=value file")
    parser.add_argument("--preview-selector",
                        help="editbtn: a selector that must be inside the opened preview")
    parser.add_argument("--no-save", action="store_true",
                        help="todosave: read the editor and write nothing")
    args = parser.parse_args(argv)
    if args.env_file:
        with open(args.env_file, encoding="utf-8") as handle:
            adapter.parse_env_file(handle, os.environ)
    return run(args.command, args.out, path=args.path, marker=args.marker,
               save=not args.no_save, preview_selector=args.preview_selector)


if __name__ == "__main__":
    raise SystemExit(main())
