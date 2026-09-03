#!/usr/bin/env python3
"""Real Settings route regression for Odoo public and HA Ingress surfaces.

Credentials are read exclusively from the environment.  The test does not save,
change, or open business configuration controls.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

HA_BASE = os.environ.get("HA_BASE_URL", "https://woowtech-ha.woowtech.io").rstrip("/")
PUBLIC_BASE = os.environ.get("ODOO_PUBLIC_URL", "https://woowtech-odooo.woowtech.io").rstrip("/")
HA_USER = os.environ.get("HA_TEST_USER")
HA_PASSWORD = os.environ.get("HA_TEST_PASSWORD")
ODOO_LOGIN = os.environ.get("ODOO_TEST_LOGIN")
ODOO_PASSWORD = os.environ.get("ODOO_TEST_PASSWORD")
BASELINE_TAB_KEYS = {"general_settings", "calendar", "website", "stock", "account", "point_of_sale"}
STAMP = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
RUN_ID = f"{STAMP}-{uuid.uuid4().hex}"
ARTIFACT_DIR = Path(os.environ.get("E2E_ARTIFACT_DIR", "/tmp/odoo-settings-e2e")) / RUN_ID
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def require(value, name):
    if not value:
        raise RuntimeError(f"{name} is required in the environment")
    return value


def sanitize_diagnostic(value):
    """Redact secrets from every diagnostic before it is stored or formatted."""
    if isinstance(value, str):
        value = re.sub(
            r"(?P<prefix>/?api/hassio_ingress/)[^/\s?#]+",
            lambda match: match.group("prefix") + "<redacted>",
            value,
        )
        # Query-only references occur in HA authorization diagnostics without
        # a path to anchor the general URL pattern below.
        value = re.sub(
            r"(?<![\w/])\?[^\s#<>\"']*(#[^\s<>\"']*)?",
            lambda match: "?<redacted>" + (match.group(1) or ""),
            value,
        )
        # Strip query values from absolute and root-relative URLs embedded in
        # Playwright errors, including HA OAuth callback code/state values.
        value = re.sub(
            r"([^\s?#<>\"']+)\?[^\s#<>\"']*(#[^\s<>\"']*)?",
            lambda match: match.group(1) + (match.group(2) or ""),
            value,
        )
        if value.startswith(("http://", "https://", "/")):
            parts = urlsplit(value)
            value = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
        return value
    if isinstance(value, tuple):
        return tuple(sanitize_diagnostic(item) for item in value)
    if isinstance(value, list):
        return [sanitize_diagnostic(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_diagnostic(item) for key, item in value.items()}
    return value


def assert_sanitizer_contract():
    """Keep credential-bearing relative diagnostics covered without secrets."""
    assert sanitize_diagnostic(
        "api/hassio_ingress/example-token/odoo/settings"
    ) == "api/hassio_ingress/<redacted>/odoo/settings"
    assert sanitize_diagnostic(
        "/api/hassio_ingress/example-token/odoo/settings"
    ) == "/api/hassio_ingress/<redacted>/odoo/settings"
    assert sanitize_diagnostic("?code=example-code&state=example-state") == "?<redacted>"
    assert sanitize_diagnostic(
        "https://ha.example/callback?code=example-code&state=example-state"
    ) == "https://ha.example/callback"


def diagnostic_text(value):
    """Return a safe, deterministic string for exceptions and stderr."""
    sanitized = sanitize_diagnostic(value)
    if isinstance(sanitized, str):
        return sanitized
    return json.dumps(sanitized, ensure_ascii=False, sort_keys=True)


def is_detached_frame_error(error):
    """Recognize only Playwright errors caused by replacement frame contexts."""
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "frame was detached",
            "frame has been detached",
            "execution context was destroyed",
            "cannot find context with specified id",
            "cannot find context",
        )
    )


def direct_ingress_frame(page):
    """Return only the current direct HA panel iframe, never a detached child."""
    for _ in range(100):
        frames = [
            frame for frame in page.frames
            if frame.parent_frame == page.main_frame and "/api/hassio_ingress/" in frame.url
        ]
        if frames:
            return frames[0]
        page.wait_for_timeout(200)
    raise AssertionError(
        "direct ingress iframe absent; frames="
        + diagnostic_text([frame.url for frame in page.frames])
    )


def add_evidence(page, evidence):
    page.on(
        "response",
        lambda response: evidence["http_failures"].append(
            sanitize_diagnostic({"status": response.status, "url": response.url})
        ) if response.status >= 400 else None,
    )
    page.on(
        "requestfailed",
        lambda request: evidence["request_failures"].append(
            sanitize_diagnostic({"url": request.url, "failure": request.failure})
        ),
    )
    page.on("pageerror", lambda error: evidence["page_errors"].append(diagnostic_text(str(error))))
    page.on(
        "console",
        lambda message: evidence["console_errors"].append(diagnostic_text(message.text))
        if message.type == "error" else None,
    )
    page.on("framenavigated", lambda frame: evidence["frame_navigations"].append(diagnostic_text(frame.url)))


def assert_no_http_failures(evidence):
    failures = sanitize_diagnostic(evidence["http_failures"])
    if failures:
        raise AssertionError(
            "HTTP >=400 responses: " + diagnostic_text(failures) + f"; artifacts: {ARTIFACT_DIR}"
        )


def save(page, evidence, surface):
    try:
        page.screenshot(path=str(ARTIFACT_DIR / f"{surface}-final.png"), full_page=True)
    finally:
        (ARTIFACT_DIR / f"{surface}-evidence.json").write_text(
            json.dumps(sanitize_diagnostic(evidence), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def login_ha_and_open_panel(page):
    require(HA_USER, "HA_TEST_USER")
    require(HA_PASSWORD, "HA_TEST_PASSWORD")
    # HA may complete its authorization-code callback after the login form has
    # disappeared.  Wait for the actual sidebar item rather than assuming a
    # fixed delay means the dashboard is ready.
    for attempt in range(3):
        page.goto(HA_BASE, wait_until="domcontentloaded", timeout=120000)
        for _ in range(100):
            username = page.locator('input[name="username"]')
            if username.count() and username.is_visible():
                username.fill(HA_USER)
                page.locator('input[name="password"]').fill(HA_PASSWORD)
                page.locator('input[name="password"]').press("Enter")
            panel = page.get_by_text("Woow Odoo", exact=True)
            if panel.count() and panel.is_visible():
                panel.click(timeout=30000)
                return direct_ingress_frame(page)
            page.wait_for_timeout(300)
        # Retry the root URL after an incomplete/expired HA authorization
        # callback; do not reuse an iframe or page handle from that attempt.
    raise AssertionError(
        "HA sidebar did not become ready after authentication; url="
        + diagnostic_text(page.url)
    )


def login_odoo_in_frame(page, frame):
    require(ODOO_LOGIN, "ODOO_TEST_LOGIN")
    require(ODOO_PASSWORD, "ODOO_TEST_PASSWORD")
    for _ in range(3):
        try:
            frame = direct_ingress_frame(page)
            if frame.locator('input[name="login"]').count():
                frame.locator('input[name="login"]').fill(ODOO_LOGIN)
                frame.locator('input[name="password"]').fill(ODOO_PASSWORD)
                frame.get_by_role("button", name="Log in", exact=True).click()
            break
        except PlaywrightError as error:
            if not is_detached_frame_error(error):
                raise
    else:
        raise AssertionError("Odoo login frame remained detached after retry")

    last = None
    for _ in range(100):
        frame = direct_ingress_frame(page)
        try:
            frame.locator(".o_main_navbar").wait_for(timeout=500)
            return frame
        except PlaywrightTimeoutError as error:
            last = diagnostic_text(str(error))
        except PlaywrightError as error:
            if not is_detached_frame_error(error):
                raise
            last = diagnostic_text(str(error))
    raise AssertionError("Odoo navbar did not become ready after login: " + diagnostic_text(last))


def open_ingress_settings(page):
    """Open Settings, retrying only HA parent re-auth/panel replacement."""
    last = None
    for _ in range(3):
        try:
            frame = direct_ingress_frame(page)
            frame.locator(".o_main_navbar").wait_for(timeout=15000)
            frame.locator(".o_navbar_apps_menu button").click()
            frame.locator('a.o_app[data-menu-xmlid="base.menu_administration"]').last.click()
            frame = direct_ingress_frame(page)
            frame.locator(".settings_tab").wait_for(timeout=20000)
            return frame
        except PlaywrightError as error:
            if not is_detached_frame_error(error):
                raise
            last = diagnostic_text(str(error))
            # Reopen/re-authenticate only when Playwright proves that the
            # current frame execution context was replaced.
            frame = login_ha_and_open_panel(page)
            login_odoo_in_frame(page, frame)
    raise AssertionError("could not open ingress Settings after detached-frame retry: " + diagnostic_text(last))


def discover_tab_keys(frame_getter):
    """Discover every visible, enabled tab, retrying only a detached frame."""
    last = None
    for _ in range(3):
        try:
            frame = frame_getter()
            tabs = frame.locator(".settings_tab a.tab[data-key]")
            keys = []
            for index in range(tabs.count()):
                tab = tabs.nth(index)
                key = tab.get_attribute("data-key")
                enabled = (
                    tab.get_attribute("aria-disabled") != "true"
                    and tab.get_attribute("disabled") is None
                )
                if key and enabled and tab.is_visible() and key not in keys:
                    keys.append(key)
            missing = BASELINE_TAB_KEYS.difference(keys)
            assert not missing, "baseline Settings tabs missing: " + diagnostic_text(
                {"missing": sorted(missing), "discovered": keys}
            )
            return keys
        except PlaywrightError as error:
            if not is_detached_frame_error(error):
                raise
            last = diagnostic_text(str(error))
    raise AssertionError("Settings tab discovery frame remained detached: " + diagnostic_text(last))


def wait_for_selected_tab(page, frame_getter, key):
    """Reacquire replacement frames until the requested Settings tab is active."""
    last = None
    for _ in range(100):
        try:
            frame = frame_getter()
            selected = frame.locator('.settings_tab a.tab.selected[data-key]')
            selected_key = selected.get_attribute("data-key") if selected.count() else None
            last = {"url": frame.url, "selected": selected_key}
            if selected_key == key and frame.locator(".settings").is_visible():
                return frame, selected_key
        except PlaywrightError as error:
            if not is_detached_frame_error(error):
                raise
            last = diagnostic_text(str(error))
        page.wait_for_timeout(100)
    raise AssertionError(
        "Settings tab did not become selected: "
        + diagnostic_text({"key": key, "last": last})
    )


def click_settings_tab(frame_getter, key):
    """Click one tab, retrying only if its frame execution context detaches."""
    last = None
    for _ in range(3):
        try:
            frame = frame_getter()
            tab = frame.locator(f'.settings_tab a.tab[data-key="{key}"]')
            tab.wait_for(timeout=20000)
            before = sanitize_diagnostic(
                {"url": frame.url, "href": tab.get_attribute("href")}
            )
            tab.click()
            return before
        except PlaywrightError as error:
            if not is_detached_frame_error(error):
                raise
            last = diagnostic_text(str(error))
    raise AssertionError(
        "Settings tab frame remained detached: "
        + diagnostic_text({"key": key, "last": last})
    )


def assert_tabs_in_frame(page, frame_getter, surface, evidence, post_click_frame_getter=None):
    post_click_frame_getter = post_click_frame_getter or frame_getter
    keys = discover_tab_keys(frame_getter)
    evidence["discovered_tabs"] = keys
    results = []
    for key in keys:
        before = click_settings_tab(frame_getter, key)
        frame, selected_key = wait_for_selected_tab(page, post_click_frame_getter, key)
        result = sanitize_diagnostic(
            {
                "key": key,
                "before_url": before["url"],
                "before_href": before["href"],
                "after_url": frame.url,
                "selected": selected_key,
            }
        )
        results.append(result)
        assert "/odoo/settings" in frame.url, diagnostic_text(result)
        assert "/odoo/discuss" not in frame.url, diagnostic_text(result)
        assert selected_key == key, diagnostic_text(result)
    evidence["tab_results"] = results
    return keys


def run_ingress(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    evidence = {"surface": "ingress", "started": dt.datetime.now(dt.timezone.utc).isoformat(), "http_failures": [], "request_failures": [], "console_errors": [], "page_errors": [], "frame_navigations": []}
    add_evidence(page, evidence)
    try:
        frame = login_ha_and_open_panel(page)
        login_odoo_in_frame(page, frame)
        keys = assert_tabs_in_frame(
            page,
            lambda: open_ingress_settings(page),
            "ingress",
            evidence,
            post_click_frame_getter=lambda: direct_ingress_frame(page),
        )
        assert_no_http_failures(evidence)
    finally:
        save(page, evidence, "ingress")
        page.close()
    return keys


def run_public(browser):
    require(ODOO_LOGIN, "ODOO_TEST_LOGIN")
    require(ODOO_PASSWORD, "ODOO_TEST_PASSWORD")
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    evidence = {"surface": "public", "started": dt.datetime.now(dt.timezone.utc).isoformat(), "http_failures": [], "request_failures": [], "console_errors": [], "page_errors": [], "frame_navigations": []}
    add_evidence(page, evidence)
    try:
        page.goto(f"{PUBLIC_BASE}/web/login?redirect=/odoo/settings", wait_until="domcontentloaded", timeout=120000)
        if page.locator('input[name="login"]').count():
            page.locator('input[name="login"]').fill(ODOO_LOGIN)
            page.locator('input[name="password"]').fill(ODOO_PASSWORD)
            page.get_by_role("button", name="Log in", exact=True).click()
        page.locator(".settings_tab").wait_for(timeout=30000)
        keys = assert_tabs_in_frame(page, lambda: page.main_frame, "public", evidence)
        assert_no_http_failures(evidence)
    finally:
        save(page, evidence, "public")
        page.close()
    return keys


def main():
    assert_sanitizer_contract()
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", choices=("ingress", "public", "both"), default="both")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            ingress_keys = run_ingress(browser) if args.surface in ("ingress", "both") else None
            public_keys = run_public(browser) if args.surface in ("public", "both") else None
            if args.surface == "both":
                assert set(ingress_keys) == set(public_keys), (
                    f"Settings tab mismatch: ingress={ingress_keys}; public={public_keys}"
                )
        finally:
            browser.close()
    print(f"Settings E2E artifacts: {ARTIFACT_DIR}")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, RuntimeError, PlaywrightError) as error:
        safe_error = diagnostic_text(str(error))
        print(
            f"Settings E2E failed; artifacts: {ARTIFACT_DIR}; error: {safe_error}",
            file=sys.stderr,
        )
        raise RuntimeError(safe_error) from None
