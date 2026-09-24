#!/usr/bin/env python3
"""Live-tier Literal rewrite gate (issue #58, ADR 0004).

Logs in to the control group's Public origin, walks the routes that load the
backend, Discuss, the website and every installed app's landing page, and
keeps the body of every `/web/assets/…*.min.js` and `*.min.css` bundle the
browser fetched on the way. Each bundle is then scanned for root-relative
string literals; a literal whose prefix the nginx Literal rewrite does not
cover is reported at the level the bundle consumes it, and an unregistered
FAIL (a whole-page navigation) makes the run exit non-zero.

Environment, the same names as the other Live tests:

    ODOO_BASE_URL        the Public origin (required)
    ODOO_TEST_LOGIN      Odoo login (required)
    ODOO_TEST_PASSWORD   Odoo password (required)
    E2E_ARTIFACT_DIR     where the report, bundles and screenshots go
    IGNORE_HTTPS_ERRORS  "1" to accept a self-signed certificate

    python odoo18ce/tests/e2e_literal_rewrite_gate.py
    python odoo18ce/tests/e2e_literal_rewrite_gate.py --from-dir <artifact dir>/bundles
    python odoo18ce/tests/e2e_literal_rewrite_gate.py --include-file generated-rewrites.conf

`--from-dir` re-evaluates bundles saved by an earlier run without a browser,
for example after editing the nginx template or the exception list.

`--include-file` takes a copy of the Generated rewrite include file the host
under test applied (ADR 0005) and counts its rules as covered alongside the
template's, so a run against such a host reports what that host still leaves
uncovered instead of the prefixes the add-on already fixed for itself.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
LIB = HERE.parent / "rootfs/usr/local/lib/literal_rewrite_gate.py"
TEMPLATE = HERE.parent / "rootfs/etc/nginx/nginx.conf.template"
EXCEPTIONS = HERE.parent / "rootfs/usr/local/lib/literal_rewrite_exceptions.yaml"


def load_gate():
    spec = importlib.util.spec_from_file_location("literal_rewrite_gate", LIB)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves the module's lazy annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = load_gate()

# The routes every run visits after login, before the app landing pages.
# Extend this list when a surface loads a bundle none of these reach.
ROUTES = ("/web/login", "/odoo", "/odoo/discuss", "/")

BUNDLE_URL = re.compile(r"/web/assets/.*\.min\.(?:js|css)(?:\?|$)")
NAV_TIMEOUT = 120_000
SETTLE_MS = 4_000


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"error: {name} is required in the environment")
    return value


def bundle_path(url: str) -> str:
    """`/web/assets/1/8c63e6a/web.assets_web.min.js` from its full URL.

    A bundle is identified by its URL path, not its file name: Odoo serves
    one name under a website-scoped `/web/assets/1/<unique>/<name>` and an
    unscoped `/web/assets/<unique>/<name>` with different content, and both
    need scanning (issue #98). The in-container Rewrite scan keys its rows
    the same way (#92). Whatever precedes `/web/assets/` -- an Ingress
    prefix and its token -- is dropped, and so are the origin and query.
    A path without `/web/assets/` is masked, since it becomes a file name.
    """
    path = urlsplit(url).path
    index = path.find("/web/assets/")
    return path[index:] if index >= 0 else gate.mask(path)


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def bundle_filename(path: str) -> str:
    """The saved copy's name: one file per bundle path."""
    return safe_filename(path.lstrip("/"))


def collect_bundles(base: str, login: str, password: str, artifacts: Path) -> dict[str, str]:
    """Log in and return {bundle path: body} for every bundle the routes load."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

    ignore_https = os.environ.get("IGNORE_HTTPS_ERRORS", "0") == "1"
    seen: dict[str, str] = {}      # bundle path -> url, first sighting wins

    def url(path: str) -> str:
        return f"{base}/{path.lstrip('/')}" if path != "/" else f"{base}/"

    def on_response(response):
        if response.status == 200 and BUNDLE_URL.search(response.url):
            seen.setdefault(bundle_path(response.url), response.url)

    def visit(page, path: str, label: str):
        page.goto(url(path), wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except PlaywrightTimeoutError:
            pass  # a long-polling bus keeps the network busy; the bundles are in
        page.wait_for_timeout(SETTLE_MS)
        assert page.url.startswith(base + "/"), f"{label} escaped the origin: {gate.mask(page.url)}"
        page.screenshot(path=str(artifacts / f"{safe_filename(label)}.png"), full_page=False)
        print(f"visited {label}: {len(seen)} bundles so far", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=ignore_https, viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("response", on_response)

        page.goto(url("/web/login?redirect=/odoo"), wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        page.locator("input[name=login]").fill(login)
        page.locator("input[name=password]").fill(password)
        page.get_by_role("button", name="Log in", exact=True).click()
        page.locator(".o_main_navbar").wait_for(state="visible", timeout=60_000)

        for route in ROUTES:
            visit(page, route, route)

        # Every installed app once, landing page only, no deeper crawl.
        page.goto(url("/odoo"), wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        page.locator(".o_navbar_apps_menu button").click()
        apps = page.locator(".o_app")
        apps.first.wait_for(state="visible", timeout=30_000)
        app_names = [name.strip() for name in apps.all_inner_texts() if name.strip()]
        print(f"installed apps: {', '.join(app_names)}", flush=True)
        for app_name in app_names:
            page.goto(url("/odoo"), wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            page.locator(".o_navbar_apps_menu button").click()
            page.locator(".o_app").filter(has_text=app_name).first.click()
            visit(page, page.url.removeprefix(base), f"app {app_name}")

        # Fetch each bundle once through the logged-in context: the request
        # shares the session cookie, and a fresh GET avoids the body of an
        # already-navigated-away response being unavailable.
        bundles: dict[str, str] = {}
        bundle_dir = artifacts / "bundles"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        saved: dict[str, str] = {}   # file name -> the bundle path it holds
        for path, bundle_url in sorted(seen.items()):
            response = page.request.get(bundle_url)
            assert response.ok, f"{path}: HTTP {response.status} on re-fetch"
            text = response.text()
            bundles[path] = text
            # One file per path, so two bundles sharing a name never
            # overwrite each other's copy.
            filename = bundle_filename(path)
            assert saved.setdefault(filename, path) == path, f"{path} and {saved[filename]} both save as {filename}"
            # The saved copy is masked: against an Ingress base the bundles
            # carry the token in every rewritten literal, and the artifact
            # is uploaded on failure.
            (bundle_dir / filename).write_text(gate.mask(text), encoding="utf-8")
        browser.close()
    return bundles


def load_saved_bundles(directory: Path) -> dict[str, str]:
    """{file name: body}; a run saves one file per bundle path, so the
    file name tells apart two bundles that share a name."""
    files = sorted(p for p in directory.iterdir() if p.suffix in {".js", ".css"})
    if not files:
        sys.exit(f"error: no .js or .css bundles in {directory}")
    return {p.name: p.read_text(encoding="utf-8") for p in files}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-dir", type=Path, help="evaluate bundles saved by an earlier run instead of collecting")
    parser.add_argument(
        "--include-file",
        type=Path,
        help="the Generated rewrite include file the host applied; its rules count as covered too",
    )
    args = parser.parse_args(argv)

    artifacts = Path(os.environ.get("E2E_ARTIFACT_DIR", "/tmp/odoo-literal-rewrite-gate"))
    artifacts.mkdir(parents=True, exist_ok=True)

    # Read before collecting: a mistyped path should not cost a full login
    # and bundle walk first.
    rules = gate.rewrite_rules(TEMPLATE.read_text(encoding="utf-8"))
    include_header = ""
    if args.include_file:
        if not args.include_file.is_file():
            sys.exit(f"error: no Generated rewrite include file at {args.include_file}")
        generated = gate.include_rules(args.include_file.read_text(encoding="utf-8"))
        rules = gate.merge_rules(rules, generated)
        include_header = f"include: {args.include_file} ({len(generated)} prefixes)"

    header: list[str] = []
    if args.from_dir:
        bundles = load_saved_bundles(args.from_dir)
        header.append(f"source: {args.from_dir}")
    else:
        base = require_env("ODOO_BASE_URL").rstrip("/")
        login = require_env("ODOO_TEST_LOGIN")
        password = require_env("ODOO_TEST_PASSWORD")
        header.append(f"origin: {gate.mask(base)}")
        bundles = collect_bundles(base, login, password, artifacts)

    if include_header:
        header.append(include_header)
    exceptions = gate.load_exceptions(EXCEPTIONS.read_text(encoding="utf-8"))
    report = gate.evaluate(bundles, rules, exceptions)
    text = gate.format_report(report, header)
    (artifacts / "literal-rewrite-gate.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
