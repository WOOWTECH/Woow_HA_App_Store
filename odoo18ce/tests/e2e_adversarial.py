#!/usr/bin/env python3
"""Read-only adversarial browser matrix for Odoo public or HA-ingress URLs."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = os.environ["ODOO_BASE_URL"].rstrip("/")
LOGIN = os.environ.get("ODOO_TEST_LOGIN", "")
PASSWORD = os.environ.get("ODOO_TEST_PASSWORD", "")
DB_POLICY = os.environ.get("ODOO_DB_POLICY", "block")  # block | allow | skip
IGNORE_HTTPS_ERRORS = os.environ.get("IGNORE_HTTPS_ERRORS", "0") == "1"
EXPECT_WEBSITE_EDITOR = os.environ.get("ODOO_EXPECT_WEBSITE_EDITOR", "0") == "1"
CRAWL_APPS = os.environ.get("ODOO_CRAWL_APPS", "0") == "1"
ARTIFACTS = Path(os.environ.get("E2E_ARTIFACT_DIR", "/tmp/odoo-e2e"))
ARTIFACTS.mkdir(parents=True, exist_ok=True)

def url(path):
    return f"{BASE}/{path.lstrip('/')}" if path != "/" else f"{BASE}/"

def ignored_url(value):
    return "/cdn-cgi/" in value or "service-worker" in value

def relevant_console(text):
    ignored = ("Failed to load resource", "Service worker registration failed", "certificate error")
    return not any(x.lower() in text.lower() for x in ignored)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(ignore_https_errors=IGNORE_HTTPS_ERRORS, viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    failed, server_errors, console_errors, responses = [], [], [], []
    page.on("requestfailed", lambda req: failed.append((req.url, req.failure)) if not ignored_url(req.url) else None)
    page.on("response", lambda res: (responses.append((res.status, res.url)), server_errors.append((res.status, res.url)) if res.status >= 500 else None))
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" and relevant_console(msg.text) else None)

    # Unauthenticated basics and lifecycle perimeter.
    for route in ("/", "/web/login", "/odoo", "/shop", "/contactus"):
        response = page.goto(url(route), wait_until="domcontentloaded", timeout=120000)
        assert response and response.status < 500, (route, response.status if response else None)
        assert len(page.locator("body").inner_text()) > 20, f"blank page: {route}"
    if DB_POLICY != "skip":
        db_status = page.request.get(url("/web/database/manager")).status
        xmlrpc_status = page.request.get(url("/xmlrpc/2/db")).status
        db_rpc = page.request.post(url("/jsonrpc"), data={"jsonrpc":"2.0","method":"call","params":{"service":"db","method":"list","args":[]}})
        if DB_POLICY == "block":
            assert db_status == 404 and xmlrpc_status == 404 and db_rpc.status == 403, (db_status, xmlrpc_status, db_rpc.status)
        else:
            assert db_status == 200 and xmlrpc_status != 404 and db_rpc.status == 200, (db_status, xmlrpc_status, db_rpc.status)
    common_rpc = page.request.post(url("/jsonrpc"), data={"jsonrpc":"2.0","method":"call","params":{"service":"common","method":"version","args":[]}})
    assert common_rpc.status == 200

    if LOGIN and PASSWORD:
        page.goto(url("/web/login?redirect=/odoo"), wait_until="networkidle", timeout=120000)
        assert page.locator("input[name=login]").is_visible(), "login form hidden"
        page.locator("input[name=login]").fill(LOGIN)
        page.locator("input[name=password]").fill(PASSWORD)
        page.get_by_role("button", name="Log in", exact=True).click()
        page.wait_for_timeout(10000)
        assert page.locator(".o_main_navbar").count() == 1, "backend did not mount"
        assert page.url.startswith(BASE + "/"), f"escaped base path: {page.url}"

        # Adversarial basic-operation recursion: backend -> website -> commerce
        # -> portal -> backend, checking every page for blank/error regressions.
        routes = ("/odoo", "/odoo/discuss", "/", "/shop", "/shop/cart", "/contactus", "/my/home", "/odoo")
        for index, route in enumerate(routes):
            before = (len(failed), len(server_errors), len(console_errors))
            response = page.goto(url(route), wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(2500)
            assert response and response.status < 500, (route, response.status if response else None)
            assert len(page.locator("body").inner_text()) > 20, f"blank authenticated page: {route}"
            assert (len(failed), len(server_errors), len(console_errors)) == before, {
                "route": route, "failed": failed[before[0]:], "server": server_errors[before[1]:], "console": console_errors[before[2]:]
            }
            page.screenshot(path=str(ARTIFACTS / f"{index:02d}-{route.strip('/').replace('/','-') or 'home'}.png"), full_page=True)

        if EXPECT_WEBSITE_EDITOR:
            page.goto(url("/odoo"), wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(4000)
            page.locator(".o_navbar_apps_menu button").click()
            website = page.get_by_text("Website", exact=True)
            assert website.count() == 1, "Website app unavailable to E2E administrator"
            before = (len(failed), len(server_errors), len(console_errors))
            website.click()
            page.wait_for_timeout(15000)
            assert (len(failed), len(server_errors), len(console_errors)) == before, {
                "operation": "Website editor", "failed": failed[before[0]:], "server": server_errors[before[1]:], "console": console_errors[before[2]:]
            }
            assert any(status == 200 and "website.assets_all_wysiwyg_inside.min.js" in target for status, target in responses), "WYSIWYG JS bundle was not loaded"
            page.screenshot(path=str(ARTIFACTS / "website-editor.png"), full_page=True)

        if CRAWL_APPS:
            page.goto(url("/odoo"), wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(3000)
            page.locator(".o_navbar_apps_menu button").click()
            app_names = page.locator(".o_app").all_inner_texts()
            for index, app_name in enumerate(app_names):
                page.goto(url("/odoo"), wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(2000)
                page.locator(".o_navbar_apps_menu button").click()
                before = (len(failed), len(server_errors), len(console_errors))
                page.locator(".o_app").filter(has_text=app_name).first.click()
                page.wait_for_timeout(6000)
                assert page.url.startswith(BASE + "/"), f"app escaped base: {app_name} -> {page.url}"
                assert (len(failed), len(server_errors), len(console_errors)) == before, {
                    "app": app_name, "failed": failed[before[0]:], "server": server_errors[before[1]:], "console": console_errors[before[2]:]
                }
                page.screenshot(path=str(ARTIFACTS / f"app-{index:02d}-{app_name.replace(' ','-')}.png"), full_page=True)

        page.goto(url("/web/session/logout?redirect=/web/login"), wait_until="domcontentloaded", timeout=120000)
        page.goto(url("/odoo"), wait_until="domcontentloaded", timeout=120000)
        page.locator("input[name=login]").wait_for(state="visible", timeout=30000)
        assert page.locator("input[name=login]").is_visible(), "logout/protected redirect failed"

    print(json.dumps({"base": BASE, "failed": failed, "server_errors": server_errors, "console_errors": console_errors}, indent=2))
    assert not failed and not server_errors and not console_errors
    browser.close()
