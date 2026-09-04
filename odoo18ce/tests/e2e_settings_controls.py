#!/usr/bin/env python3
"""Isolated Settings control E2E for Odoo public and HA Ingress surfaces.

Every action/object/dialog control is exercised in its own browser context so a
Home Assistant authorization refresh or a detached ingress frame cannot poison
subsequent results. Credentials are accepted only through environment variables.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

import e2e_settings_ingress as shared

RUN_ID = (
    dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    + "-"
    + uuid.uuid4().hex
)
ARTIFACT_ROOT = (
    Path(os.environ.get("E2E_CONTROLS_ARTIFACT_DIR", "/tmp/odoo-settings-controls-e2e"))
    / RUN_ID
)
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
EXTERNAL_NAME_RE = re.compile(r"(?:buy\s+credits|purchase|upgrade)", re.I)
EXECUTABLE_CATEGORIES = frozenset({"action", "object", "dialog"})


def parse_safe_controls(raw):
    """Return exact accessible names explicitly approved for a control click."""
    return frozenset(name.strip() for name in (raw or "").split(",") if name.strip())


def control_execution_policy(item, safe_controls):
    """Never infer approval for a Settings control from its visible label."""
    if item["category"] not in EXECUTABLE_CATEGORIES:
        return {"allowed": False, "reason": "not-an-executable-control"}
    if item["name"] in safe_controls:
        return {"allowed": True, "reason": "explicit-safe-allowlist"}
    return {"allowed": False, "reason": "not-approved"}


def mutation_policy(environment):
    """Require an explicit text field for each mutating Settings scenario."""
    selector = environment.get("ODOO_SETTINGS_MUTATION_SELECTOR")
    save_value = environment.get("ODOO_SETTINGS_SAVE_VALUE")
    if not selector:
        return {
            "selector": None,
            "discard_allowed": False,
            "save_allowed": False,
            "discard_reason": "ODOO_SETTINGS_MUTATION_SELECTOR is required; no setting was mutated",
            "save_reason": "ODOO_SETTINGS_MUTATION_SELECTOR is required; no setting was mutated",
        }
    return {
        "selector": selector,
        "discard_allowed": True,
        "save_allowed": save_value is not None,
        "discard_reason": None,
        "save_reason": (
            None
            if save_value is not None
            else "ODOO_SETTINGS_SAVE_VALUE is required; no setting was saved"
        ),
        "save_value": save_value,
    }


def is_transient_ingress_detach(error):
    message = str(error).lower()
    return "frame was detached" in message or "/auth/authorize" in message


def should_retry_control(surface, item, safe_controls, attempt, error):
    """Retry one explicitly approved ingress control after auth/frame loss."""
    approval = control_execution_policy(item, safe_controls)
    return (
        surface == "ingress"
        and approval["allowed"]
        and attempt == 0
        and is_transient_ingress_detach(error)
    )


def classify_control(control):
    """Classify a serialized visible Settings button through public attributes."""
    name = (control.get("name") or "").strip()
    href = (control.get("href") or "").strip()
    odoo_type = (control.get("odoo_type") or "").strip().lower()
    html_type = (control.get("html_type") or "").strip().lower()
    aria_haspopup = (control.get("aria_haspopup") or "").strip().lower()
    toggle = (control.get("toggle") or "").strip().lower()

    external_href = False
    if href.startswith(("http://", "https://")):
        external_href = urlsplit(href).netloc not in {
            urlsplit(shared.HA_BASE).netloc,
            urlsplit(shared.PUBLIC_BASE).netloc,
        }
    if external_href or EXTERNAL_NAME_RE.search(name):
        return "external-skip"
    if odoo_type in {"action", "object"}:
        return odoo_type
    if name in {"Save", "Discard"} or html_type == "submit":
        return "form-control"
    if aria_haspopup == "dialog" or toggle == "modal":
        return "dialog"
    return "other"


def assert_self_tests():
    shared.assert_sanitizer_contract()
    cases = [
        ({"name": "Manage Users", "odoo_type": "action"}, "action"),
        (
            {"name": "Manage Users", "odoo_type": "action", "html_type": "submit"},
            "action",
        ),
        ({"name": "Update Info", "odoo_type": "object"}, "object"),
        ({"name": "Open", "aria_haspopup": "dialog"}, "dialog"),
        ({"name": "Save", "html_type": "button"}, "form-control"),
        ({"name": "Buy Credits", "href": "/iap"}, "external-skip"),
        ({"name": "Vendor", "href": "https://external.invalid/buy"}, "external-skip"),
        ({"name": "Internal", "href": shared.PUBLIC_BASE + "/odoo/settings"}, "other"),
        ({"name": "Internal tab", "href": "/odoo/settings", "target": "_blank"}, "other"),
    ]
    for payload, expected in cases:
        assert classify_control(payload) == expected, (payload, expected)
    assert normalized_control_name("Manage\n  Users") == "Manage Users"
    assert parse_safe_controls(None) == frozenset()
    assert parse_safe_controls(" Manage Users, Add Languages,Manage Users, ") == {
        "Manage Users",
        "Add Languages",
    }
    action = {"name": "Manage Users", "category": "action"}
    assert control_execution_policy(action, frozenset()) == {
        "allowed": False,
        "reason": "not-approved",
    }
    assert control_execution_policy(action, {"Manage Users"}) == {
        "allowed": True,
        "reason": "explicit-safe-allowlist",
    }
    no_mutation = mutation_policy({})
    assert not no_mutation["discard_allowed"] and not no_mutation["save_allowed"]
    discard_only = mutation_policy({"ODOO_SETTINGS_MUTATION_SELECTOR": "input[type=text]"})
    assert discard_only["discard_allowed"] and not discard_only["save_allowed"]
    explicit_save = mutation_policy(
        {
            "ODOO_SETTINGS_MUTATION_SELECTOR": "input[type=text]",
            "ODOO_SETTINGS_SAVE_VALUE": "test",
        }
    )
    assert explicit_save["discard_allowed"] and explicit_save["save_allowed"]
    detach = PlaywrightError("Frame was detached")
    assert not should_retry_control("ingress", action, frozenset(), 0, detach)
    assert should_retry_control("ingress", action, frozenset({"Manage Users"}), 0, detach)
    assert not should_retry_control("ingress", action, frozenset({"Manage Users"}), 1, detach)
    assert not should_retry_control("public", action, frozenset({"Manage Users"}), 0, detach)
    assert not should_retry_control(
        "ingress", {"category": "form-control", "name": "Save"}, frozenset({"Save"}), 0, detach
    )
    assert is_transient_ingress_detach(RuntimeError("frames=[.../auth/authorize]"))
    secret = {
        "url": "api/hassio_ingress/token-value/odoo/settings?code=secret&state=secret",
        "nested": ["?code=secret&state=secret"],
    }
    rendered = json.dumps(shared.sanitize_diagnostic(secret), sort_keys=True)
    assert "token-value" not in rendered
    assert "code=secret" not in rendered
    assert "state=secret" not in rendered

    class FakePage:
        def __init__(self):
            self.events = []

        def on(self, event, callback):
            self.events.append((event, callback))

    class FakeBrowserContext:
        def __init__(self):
            self.page = FakePage()

        def new_page(self):
            return self.page

    class FakeBrowser:
        def __init__(self):
            self.context = FakeBrowserContext()
            self.context_options = None

        def new_context(self, **options):
            self.context_options = options
            return self.context

    fake_browser = FakeBrowser()
    context, page, evidence = new_evidence_session(fake_browser, "public", "viewport-contract")
    assert context is fake_browser.context
    assert page is context.page
    assert fake_browser.context_options == {"viewport": {"width": 1440, "height": 1100}}
    assert evidence["surface"] == "public"


def evidence_template(surface, scenario):
    return {
        "surface": surface,
        "scenario": scenario,
        "started": dt.datetime.now(dt.timezone.utc).isoformat(),
        "http_failures": [],
        "request_failures": [],
        "console_errors": [],
        "page_errors": [],
        "frame_navigations": [],
    }


def safe_slug(value):
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return (slug or "unnamed")[:80]


def save_artifact(page, evidence, scenario):
    directory = ARTIFACT_ROOT / safe_slug(scenario)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(directory / "final.png"), full_page=True)
    except PlaywrightError as error:
        evidence["screenshot_error"] = shared.diagnostic_text(str(error))
    (directory / "evidence.json").write_text(
        json.dumps(shared.sanitize_diagnostic(evidence), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def assert_clean(evidence):
    problems = {
        key: evidence[key]
        for key in ("http_failures", "request_failures", "console_errors", "page_errors")
        if evidence[key]
    }
    if problems:
        raise AssertionError("browser errors: " + shared.diagnostic_text(problems))


def wait_settings_loaded(page, frame_getter):
    last = None
    for _ in range(120):
        try:
            frame = frame_getter()
            save = frame.get_by_role("button", name="Save", exact=True)
            if save.count() and save.is_visible() and save.is_enabled():
                return frame
            last = {"url": frame.url, "save_count": save.count()}
        except PlaywrightError as error:
            if not shared.is_detached_frame_error(error):
                raise
            last = shared.diagnostic_text(str(error))
        page.wait_for_timeout(250)
    raise AssertionError("Settings controls did not load: " + shared.diagnostic_text(last))


def new_evidence_session(browser, surface, scenario):
    """Create resources before navigation so callers always own their cleanup."""
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    page = context.new_page()
    evidence = evidence_template(surface, scenario)
    shared.add_evidence(page, evidence)
    return context, page, evidence


def prepare_surface(page, surface):
    """Authenticate one isolated page and return its reacquiring frame getter."""
    if surface == "ingress":
        frame = shared.login_ha_and_open_panel(page)
        shared.login_odoo_in_frame(page, frame)
        shared.open_ingress_settings(page)
        frame_getter = lambda: shared.direct_ingress_frame(page)
    else:
        shared.require(shared.ODOO_LOGIN, "ODOO_TEST_LOGIN")
        shared.require(shared.ODOO_PASSWORD, "ODOO_TEST_PASSWORD")
        page.goto(
            f"{shared.PUBLIC_BASE}/web/login?redirect=/odoo/settings",
            wait_until="domcontentloaded",
            timeout=120000,
        )
        login = page.locator('input[name="login"]')
        if login.count():
            login.wait_for(state="visible", timeout=30000)
            login.fill(shared.ODOO_LOGIN)
            page.locator('input[name="password"]').fill(shared.ODOO_PASSWORD)
            page.get_by_role("button", name="Log in", exact=True).click()
        page.locator(".settings_tab").wait_for(timeout=30000)
        frame_getter = lambda: page.main_frame
    wait_settings_loaded(page, frame_getter)
    return frame_getter


def serialized_controls(frame):
    root = frame.locator(".o_action_manager")
    controls = root.get_by_role("button")
    serialized = []
    name_occurrences = {}
    for index in range(controls.count()):
        control = controls.nth(index)
        if not control.is_visible() or not control.is_enabled():
            continue
        item = control.evaluate(
            """element => ({
                name: (element.getAttribute('aria-label') || element.innerText ||
                       element.getAttribute('title') || '').trim(),
                odoo_type: element.getAttribute('type'),
                html_type: element.type || null,
                href: element.getAttribute('href'),
                target: element.getAttribute('target'),
                aria_haspopup: element.getAttribute('aria-haspopup'),
                toggle: element.getAttribute('data-bs-toggle'),
            })"""
        )
        item = shared.sanitize_diagnostic(item)
        item["category"] = classify_control(item)
        item["dom_index"] = index
        item["name_occurrence"] = name_occurrences.get(item["name"], 0)
        name_occurrences[item["name"]] = item["name_occurrence"] + 1
        item["id"] = f"{item['category']}:{item['name']}:{item['name_occurrence']}"
        serialized.append(item)
    return serialized


def discover_controls(browser, surface):
    scenario = f"{surface}-inventory"
    context, page, evidence = new_evidence_session(browser, surface, scenario)
    try:
        frame_getter = prepare_surface(page, surface)
        controls = serialized_controls(frame_getter())
        evidence["controls"] = controls
        assert controls, "no visible Settings controls discovered"
        assert_clean(evidence)
        return controls
    finally:
        try:
            save_artifact(page, evidence, scenario)
        finally:
            context.close()


def normalized_control_name(value):
    """Normalize browser whitespace before comparing a discovered control."""
    return " ".join((value or "").split())


def locate_control(frame, item):
    """Reacquire a control by its discovered DOM position, then verify its text."""
    matches = frame.locator(".o_action_manager").get_by_role("button")
    index = item["dom_index"]
    if matches.count() <= index:
        raise AssertionError(
            "Settings control disappeared: "
            + shared.diagnostic_text({"id": item["id"], "count": matches.count()})
        )
    control = matches.nth(index)
    actual_name = normalized_control_name(
        control.evaluate(
            """element => (element.getAttribute('aria-label') || element.innerText ||
            element.getAttribute('title') || '').trim()"""
        )
    )
    expected_name = normalized_control_name(item["name"])
    assert actual_name == expected_name, shared.diagnostic_text(
        {"id": item["id"], "expected": expected_name, "actual": actual_name}
    )
    return control


def observe_outcome(page, frame_getter, before_url):
    last = None
    for _ in range(100):
        frame = frame_getter()
        dialogs = frame.locator(".modal.show, .o_dialog")
        visible_dialog = next(
            (dialogs.nth(i) for i in range(dialogs.count()) if dialogs.nth(i).is_visible()),
            None,
        )
        if visible_dialog is not None:
            title = visible_dialog.locator(".modal-title, .o_dialog_title")
            return {
                "kind": "dialog",
                "url": frame.url,
                "dialog_title": title.first.inner_text().strip() if title.count() else None,
            }
        last = frame.url
        if frame.url != before_url:
            return {"kind": "navigation", "url": frame.url, "dialog_title": None}
        page.wait_for_timeout(100)
    return {"kind": "same-page", "url": last, "dialog_title": None}


def execute_control(browser, surface, item, safe_controls):
    """Run one approved non-mutating control, with one fresh ingress retry."""
    result = {"id": item["id"], "name": item["name"], "category": item["category"]}
    for attempt in range(2):
        scenario = f"{surface}-{item['id']}-attempt-{attempt + 1}"
        context, page, evidence = new_evidence_session(browser, surface, scenario)
        try:
            frame_getter = prepare_surface(page, surface)
            frame = frame_getter()
            control = locate_control(frame, item)
            before_url = frame.url
            control.click(timeout=30000)
            outcome = shared.sanitize_diagnostic(observe_outcome(page, frame_getter, before_url))
            result.update(outcome)
            assert "/odoo/discuss" not in outcome["url"], shared.diagnostic_text(result)
            assert_clean(evidence)
            result["status"] = "passed"
            if attempt:
                result["recovered_after_detach"] = True
            return result
        except (AssertionError, RuntimeError, PlaywrightError) as error:
            if should_retry_control(surface, item, safe_controls, attempt, error):
                evidence["result"] = {"status": "retrying-after-detach"}
                continue
            result.update({"status": "failed", "error": shared.diagnostic_text(str(error))})
            return result
        finally:
            evidence.setdefault("result", result)
            try:
                save_artifact(page, evidence, scenario)
            finally:
                context.close()
    raise AssertionError("unreachable control retry state")


def explicit_text_field(frame, selector, scenario):
    field = frame.locator(selector).first
    field.wait_for(state="visible", timeout=30000)
    assert field.is_enabled(), f"explicit {scenario} field is disabled"
    tag_name = field.evaluate("element => element.tagName.toLowerCase()")
    field_type = (field.get_attribute("type") or "text").lower()
    assert tag_name == "input" and field_type == "text", (
        f"{scenario} only permits a non-server-side text input, not {tag_name}[type={field_type}]"
    )
    return field


def run_discard(browser, surface):
    scenario = f"{surface}-discard"
    policy = mutation_policy(os.environ)
    if not policy["discard_allowed"]:
        return {"scenario": "discard", "status": "blocked", "reason": policy["discard_reason"]}
    context, page, evidence = new_evidence_session(browser, surface, scenario)
    result = {"scenario": "discard", "selector_supplied": True}
    try:
        frame_getter = prepare_surface(page, surface)
        frame = frame_getter()
        field = explicit_text_field(frame, policy["selector"], "Discard")
        original = field.input_value()
        changed = f"e2e-discard-{RUN_ID[-8:]}"
        if changed == original:
            changed += "x"
        requests = []
        page.on(
            "request",
            lambda request: requests.append(
                {"method": request.method, "url": shared.sanitize_diagnostic(request.url)}
            )
            if request.method not in {"GET", "HEAD", "OPTIONS"}
            else None,
        )
        field.fill(changed)
        assert field.input_value() == changed, "text field did not change before Discard"
        frame.get_by_role("button", name="Discard", exact=True).click()
        frame = wait_settings_loaded(page, frame_getter)
        restored = explicit_text_field(frame, policy["selector"], "Discard").input_value()
        assert restored == original, {"original": original, "after_discard": restored}
        assert not requests, "Discard produced a server request: " + shared.diagnostic_text(requests)
        assert "/odoo/discuss" not in frame.url
        assert_clean(evidence)
        result.update({"status": "passed", "restored": True, "url": shared.sanitize_diagnostic(frame.url)})
    except (AssertionError, RuntimeError, PlaywrightError) as error:
        result.update({"status": "failed", "error": shared.diagnostic_text(str(error))})
    finally:
        evidence["result"] = result
        try:
            save_artifact(page, evidence, scenario)
        finally:
            context.close()
    return result


def run_save_restore(browser, surface):
    scenario = f"{surface}-save-restore"
    policy = mutation_policy(os.environ)
    if not policy["save_allowed"]:
        return {"scenario": "save-restore", "status": "blocked", "reason": policy["save_reason"]}
    context, page, evidence = new_evidence_session(browser, surface, scenario)
    result = {"scenario": "save-restore", "selector_supplied": True, "save_value_supplied": True}
    try:
        frame_getter = prepare_surface(page, surface)
        frame = frame_getter()
        field = explicit_text_field(frame, policy["selector"], "Save")
        original = field.input_value()
        field.fill(policy["save_value"])
        frame.get_by_role("button", name="Save", exact=True).click()
        frame = wait_settings_loaded(page, frame_getter)
        persisted = explicit_text_field(frame, policy["selector"], "Save")
        assert persisted.input_value() == policy["save_value"], "saved value did not persist"
        persisted.fill(original)
        frame.get_by_role("button", name="Save", exact=True).click()
        frame = wait_settings_loaded(page, frame_getter)
        restored = explicit_text_field(frame, policy["selector"], "Save")
        assert restored.input_value() == original, "original value was not restored"
        assert "/odoo/discuss" not in frame.url
        assert_clean(evidence)
        result.update({"status": "passed", "restored": True, "field_type": "text"})
    except (AssertionError, RuntimeError, PlaywrightError) as error:
        result.update({"status": "failed", "error": shared.diagnostic_text(str(error))})
    finally:
        evidence["result"] = result
        try:
            save_artifact(page, evidence, scenario)
        finally:
            context.close()
    return result


def comparable_controls(controls):
    return {
        (item["name"], item["name_occurrence"], item["category"])
        for item in controls
        if item["category"] in {"action", "object", "dialog", "external-skip"}
    }


def run_surface(browser, surface):
    controls = discover_controls(browser, surface)
    safe_controls = parse_safe_controls(os.environ.get("ODOO_SETTINGS_SAFE_CONTROLS"))
    results = []
    for item in controls:
        if item["category"] == "external-skip":
            results.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "category": item["category"],
                    "status": "skipped",
                    "reason": "external/IAP purchase control is never clicked",
                }
            )
        elif item["category"] in EXECUTABLE_CATEGORIES:
            policy = control_execution_policy(item, safe_controls)
            if policy["allowed"]:
                results.append(execute_control(browser, surface, item, safe_controls))
            else:
                results.append(
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "category": item["category"],
                        "status": "blocked",
                        "reason": policy["reason"],
                    }
                )
    discard = run_discard(browser, surface)
    save_restore = run_save_restore(browser, surface)
    return {
        "surface": surface,
        "controls": controls,
        "results": results,
        "discard": discard,
        "save_restore": save_restore,
    }


def assert_surface_success(report):
    failures = [item for item in report["results"] if item["status"] == "failed"]
    assert not failures, shared.diagnostic_text(failures)
    assert report["discard"]["status"] in {"passed", "blocked"}, shared.diagnostic_text(
        report["discard"]
    )
    assert report["save_restore"]["status"] in {"passed", "blocked"}, shared.diagnostic_text(
        report["save_restore"]
    )


def assert_parity(ingress, public):
    assert comparable_controls(ingress["controls"]) == comparable_controls(public["controls"]), (
        "Settings controls differ: "
        + shared.diagnostic_text(
            {
                "ingress": sorted(comparable_controls(ingress["controls"])),
                "public": sorted(comparable_controls(public["controls"])),
            }
        )
    )
    ingress_outcomes = {
        item["id"]: item.get("kind")
        for item in ingress["results"]
        if item["status"] == "passed"
    }
    public_outcomes = {
        item["id"]: item.get("kind")
        for item in public["results"]
        if item["status"] == "passed"
    }
    assert ingress_outcomes == public_outcomes, (
        "Settings control outcomes differ: "
        + shared.diagnostic_text({"ingress": ingress_outcomes, "public": public_outcomes})
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", choices=("ingress", "public", "both"), default="both")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    assert_self_tests()
    if args.self_test:
        print("Settings controls self-tests passed")
        return
    reports = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            if args.surface in {"ingress", "both"}:
                reports["ingress"] = run_surface(browser, "ingress")
                assert_surface_success(reports["ingress"])
            if args.surface in {"public", "both"}:
                reports["public"] = run_surface(browser, "public")
                assert_surface_success(reports["public"])
            if args.surface == "both":
                assert_parity(reports["ingress"], reports["public"])
        finally:
            browser.close()
    (ARTIFACT_ROOT / "summary.json").write_text(
        json.dumps(shared.sanitize_diagnostic(reports), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Settings controls E2E artifacts: {ARTIFACT_ROOT}")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, RuntimeError, PlaywrightError) as error:
        safe_error = shared.diagnostic_text(str(error))
        print(
            f"Settings controls E2E failed; artifacts: {ARTIFACT_ROOT}; error: {safe_error}",
            file=sys.stderr,
        )
        raise RuntimeError(safe_error) from None
