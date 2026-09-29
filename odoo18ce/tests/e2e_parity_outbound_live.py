#!/usr/bin/env python3
"""Live tier of the outbound-artefact parity run (#145): group E and U-D8.

    # 0. A capture SMTP sink inside the add-on container (never relays):
    #    docker exec -d <container> python3 /tmp/smtp_capture_sink.py --port 2525 --dir /tmp/woow-parity-mail
    python odoo18ce/tests/e2e_parity_outbound_live.py fixtures --env-file .env --db odoo_parity --run-id WOOW-PARITY-...
    python odoo18ce/tests/e2e_parity_outbound_live.py run --env-file .env --db odoo_parity --run-id ... --out checks.jsonl
    #    copy /tmp/woow-parity-mail out of the container into a local directory, then
    python odoo18ce/tests/e2e_parity_outbound_live.py mail --env-file .env --db odoo_parity --run-id ... \
        --mail-dir mail/ --out checks.jsonl
    #    open every anonymous link in <artifacts>/<run>-reach.json from a browser off the LAN and write
    #    [{identity, side, link, status, shown}] (`link` copied from the reach entry), then
    python odoo18ce/tests/e2e_parity_outbound_live.py report checks.jsonl [--issues issues.json] \
        [--off-lan results.json --off-lan-browser "..."]
    python odoo18ce/tests/e2e_parity_outbound_live.py teardown --env-file .env --db odoo_parity --run-id ...

Each artefact is produced once from the Public origin and once under Ingress, the same two surfaces as e2e_parity_shared_layers_live.py
(whose sides, login and masking this reuses). Mail is triggered through the
UI of each surface to a recipient named after that surface
(`e2-<what>-<surface>@example.invalid`), goes out through an `ir.mail_server`
pointing at the sink, and is judged from the captured messages.

The QR decoding needs `pip install pymupdf zxing-cpp pillow` (Live tier only).

Writes happen only on the database named by `--db`; every record carries the
run marker, and the capture mail server is archived by `teardown`. Nothing
is deleted. `<artifacts>/<run>-reach.json` holds unmasked links with access
tokens: it stays in the artefact directory and never goes into the repo.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from e2e_menu_action_adapter import RunInfo, new_run_id, parse_env_file, sanitize_diagnostic
from e2e_parity_outbound import (
    Bases,
    check_identity,
    classify_url,
    csv_strings,
    extract_urls,
    literal_findings,
    mail_urls,
    merge_off_lan,
    outbound_plan,
    outbound_record,
    qr_findings,
    url_shape,
    xlsx_strings,
)
from e2e_parity_shared_layers import Outcome, attach_issues, conservation
from e2e_parity_shared_layers_live import (
    CHECKS,
    TIMEOUT,
    Env,
    Run,
    Side,
    artifact_dir,
    cog_item,
    download,
    open_form,
    open_sides,
    pdf_urls,
)

SINK_HOST, SINK_PORT = "127.0.0.1", 2525
# Odoo turns record attachments into absolute download links when a mail
# would exceed its server's limit (mail_mail._prepare_outgoing_list); a tiny
# limit on the capture server makes every attachment a link (U-E5).
SINK_MAX_EMAIL_MB = 0.001
ATTACHMENT_TEXT = "WOOW-PARITY outbound attachment 測試\n"


def recipient(what: str, side: str) -> str:
    return "e2-%s-%s@example.invalid" % (what, side)


# --- Fixtures -------------------------------------------------------------------


def create_fixtures(side: Side, marker: str) -> dict[str, Any]:
    """The records each check works on, per surface where the artefact is per surface."""

    def create(model: str, values: dict, name_field: str = "name", **context) -> int:
        found = side.rpc(model, "search", [[[name_field, "=", values[name_field]]]],
                         {"limit": 1, "context": {"active_test": False}})
        return found[0] if found else side.rpc(model, "create", [values], {"context": context} if context else {})

    def xmlid(module: str, name: str) -> int:
        return side.rpc("ir.model.data", "search_read", [[["module", "=", module], ["name", "=", name]]],
                        {"fields": ["res_id"]})[0]["res_id"]

    ids: dict[str, Any] = {"marker": marker}
    ids["mail_server"] = create("ir.mail_server", {
        "name": marker + " capture sink", "smtp_host": SINK_HOST, "smtp_port": SINK_PORT,
        "smtp_encryption": "none", "sequence": 1, "max_email_size": SINK_MAX_EMAIL_MB,
    })
    customer = create("res.partner", {"name": marker + " E customer", "email": "e-customer@example.invalid"})
    ids["customer"] = customer
    product = side.rpc("product.product", "search", [[["sale_ok", "=", True], ["type", "=", "service"]]],
                       {"limit": 1})[0]
    ids["sale_order"] = create("sale.order", {
        "partner_id": customer, "client_order_ref": marker + " E",
        "order_line": [[0, 0, {"product_id": product, "product_uom_qty": 1}]]}, name_field="client_order_ref")
    ids["invoice"] = create("account.move", {
        "move_type": "out_invoice", "partner_id": customer, "ref": marker + " E invoice",
        "invoice_line_ids": [[0, 0, {"product_id": product, "quantity": 1, "price_unit": 100.0}]]},
        name_field="ref")
    state = side.rpc("account.move", "read", [[ids["invoice"]], ["state"]])[0]["state"]
    if state == "draft":
        side.rpc("account.move", "action_post", [[ids["invoice"]]])
    ids["purchase_order"] = create("purchase.order", {
        "partner_id": customer, "partner_ref": marker + " E",
        "order_line": [[0, 0, {"product_id": product, "product_qty": 1, "price_unit": 10.0}]]},
        name_field="partner_ref")
    ids["project"] = create("project.project", {"name": marker + " E project", "privacy_visibility": "portal"})
    ids["task"] = create("project.task", {"name": marker + " E task", "project_id": ids["project"]})
    ids["survey"] = create("survey.survey", {
        "title": marker + " E survey", "access_mode": "public", "users_login_required": False,
        "question_and_page_ids": [[0, 0, {"title": "Your name?", "question_type": "char_box"}]]}, name_field="title")
    ids["channel"] = create("discuss.channel", {"name": marker + " E channel", "channel_type": "channel"})
    # The U-E3 note: an invitation opens anonymously only without an Authorized Group.
    side.rpc("discuss.channel", "write", [[ids["channel"]], {"group_public_id": False}])
    ids["livechat_channel"] = side.rpc("im_livechat.channel", "search", [[]], {"limit": 1})[0]
    ids["link_tracker"] = create("link.tracker", {"url": side.env.public + "/contactus",
                                                  "title": marker + " E link"}, name_field="title")
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)
    event = create("event.event", {"name": marker + " E event",
                                   "date_begin": start.strftime("%Y-%m-%d %H:%M:%S"),
                                   "date_end": (start + dt.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")})
    ids["event_registration"] = create("event.registration", {
        "event_id": event, "name": marker + " E attendee", "email": "e-attendee@example.invalid"})
    list_model = side.rpc("ir.model", "search", [[["model", "=", "mailing.list"]]])[0]
    portal_group = xmlid("base", "group_portal")
    leave_type = side.rpc("hr.leave.type", "search", [[["requires_allocation", "=", "no"]]], {"limit": 1})
    admin = side.rpc("res.users", "search", [[["login", "=", side.env.login]]])[0]
    for name in ("public", "ingress"):
        per: dict[str, Any] = {}
        per["invite"] = create("res.partner", {"name": "%s E2 invite %s" % (marker, name),
                                               "email": recipient("invite", name)})
        per["reset_user"] = create("res.users", {
            "name": "%s E2 reset %s" % (marker, name), "login": recipient("reset", name),
            "email": recipient("reset", name), "groups_id": [[6, 0, [portal_group]]]}, name_field="login",
            no_reset_password=True)
        for what in ("notify", "attach"):
            partner = create("res.partner", {"name": "%s E2 %s %s" % (marker, what, name),
                                             "email": recipient(what, name)})
            side.rpc("res.partner", "message_subscribe", [[partner]], {"partner_ids": [partner]})
            per[what] = partner
        mailing_list = create("mailing.list", {"name": "%s E2 list %s" % (marker, name)})
        create("mailing.contact", {"name": "%s E2 contact %s" % (marker, name), "email": recipient("mm", name),
                                   "list_ids": [[6, 0, [mailing_list]]]}, name_field="email")
        per["mailing"] = create("mailing.mailing", {
            "subject": "%s E2 mailing %s" % (marker, name), "mailing_model_id": list_model,
            "contact_list_ids": [[6, 0, [mailing_list]]], "mail_server_id": ids["mail_server"],
            "body_html": '<p>%s <a href="%s/contactus">Contact us</a></p>'
                         '<p><a href="/unsubscribe_from_list">Unsubscribe</a></p>' % (marker, side.env.public),
        }, name_field="subject")
        for what in ("leave", "expense"):
            user = create("res.users", {"name": "%s E2 %s %s" % (marker, what, name), "login": recipient(what, name),
                                        "email": recipient(what, name)}, name_field="login", no_reset_password=True)
            side.rpc("res.users", "write", [[user], {"notification_type": "email"}])
            per[what + "_employee"] = create("hr.employee", {
                "name": "%s E2 %s %s" % (marker, what, name), "user_id": user, "work_email": recipient(what, name),
                "leave_manager_id": admin, "expense_manager_id": admin})
        if leave_type:
            day = next_weekday(dt.date.today() + dt.timedelta(days=30 + 3 * (name == "ingress"))).isoformat()
            per["leave"] = create("hr.leave", {
                "name": "%s E2 leave %s" % (marker, name), "employee_id": per["leave_employee"],
                "holiday_status_id": leave_type[0], "request_date_from": day, "request_date_to": day},
                name_field="name")
        expense = create("hr.expense", {"name": "%s E2 expense %s" % (marker, name),
                                        "employee_id": per["expense_employee"], "total_amount_currency": 12.0})
        per["expense_sheet"] = create("hr.expense.sheet", {
            "name": "%s E2 report %s" % (marker, name), "employee_id": per["expense_employee"],
            "expense_line_ids": [[6, 0, [expense]]]})
        sheet_state = side.rpc("hr.expense.sheet", "read", [[per["expense_sheet"]], ["state"]])[0]["state"]
        if sheet_state == "draft":
            side.rpc("hr.expense.sheet", "action_submit_sheet", [[per["expense_sheet"]]])
        per["meeting"] = create("calendar.event", {
            "name": "%s E3 meeting %s" % (marker, name), "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "stop": (start + dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")})
        side.rpc("calendar.event", "write", [[per["meeting"]], {"videocall_location": False}])
        ids[name] = per
    return ids


def next_weekday(day: dt.date) -> dt.date:
    """A leave on a weekend has no working day, and Odoo refuses to approve it."""
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return day


def fixture_path(run_id: str) -> str:
    return os.path.join(artifact_dir(), "%s-outbound-fixtures.json" % run_id)


def reach_path(run_id: str) -> str:
    return os.path.join(artifact_dir(), "%s-reach.json" % run_id)


def mail_plan_path(run_id: str) -> str:
    return os.path.join(artifact_dir(), "%s-mail-plan.json" % run_id)


# --- The run ------------------------------------------------------------------


class OutboundRun(Run):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with open(fixture_path(self.info.run_id), encoding="utf-8") as handle:
            self.fx = json.load(handle)
        self.reach_list: list[dict[str, Any]] = _load(reach_path(self.info.run_id), [])
        self.mail_plan: list[dict[str, Any]] = _load(mail_plan_path(self.info.run_id), [])

    @property
    def bases(self) -> Bases:
        return Bases(public=self.env.public, ha=tuple(filter(None, (self.env.ha, self.env.ha_https))),
                     prefix=self.env.prefix)

    def emit(self, item: str, module: str, screen: str, public: Outcome, ingress: Outcome, **kwargs) -> None:
        self.write(outbound_record(self.info, item, module, screen, public, ingress, bases=self.bases, **kwargs))

    def reach(self, identity: str, side: str, url: str, expect: str | None) -> dict[str, Any]:
        """Open `url` in a browser with no session (on the LAN) and remember it for the off-LAN pass."""
        link = self.env.mask(url_shape(url))  # what the evidence may show of it: no id or token
        self.reach_list = [entry for entry in self.reach_list
                           if (entry["identity"], entry["side"], entry["url"]) != (identity, side, url)]
        self.reach_list.append({"identity": identity, "side": side, "url": url, "expect": expect, "link": link})
        _save(reach_path(self.info.run_id), self.reach_list)
        context = self.browser.new_context()
        try:
            response = context.request.get(url, max_redirects=10, timeout=TIMEOUT)
            text = response.text() if response.ok and expect else ""  # a pixel or a file is not text
            status, final = response.status, response.url
        except Exception:  # noqa: BLE001 -- unreachable is the result
            return {"link": link, "status": None, "shown": False}
        finally:
            context.close()
        shown = (expect.lower() in text.lower()) if expect else (response.ok and "/web/login" not in final)
        return {"link": link, "status": status, "shown": shown}


def reach_summary(reached: list[dict[str, Any]]) -> str:
    return "; ".join("HTTP %s, %s" % (entry["status"], "shows the record" if entry["shown"] else "record not shown")
                     for entry in reached)


def _load(path: str, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    return default


def _save(path: str, value) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)


def base_code(run: OutboundRun, url: str) -> str:
    kind = classify_url(url, run.bases)
    return {"canonical": "<PUBLIC_BASE>", "ingress-token": "<INGRESS_BASE>", "ha": "<HA_BASE>"}.get(kind, kind)


def link_outcome(run: OutboundRun, identity: str, side: Side, links: list[str], anonymous: dict[str, str | None]) -> Outcome:
    """A share link (or links) as an Outcome: where it points, and what a visitor sees."""
    findings = literal_findings(links, run.bases)
    reached = [run.reach(identity, side.name, link, anonymous[link]) for link in links if link in anonymous]
    result = "links on %s" % ", ".join(sorted({base_code(run, link) for link in links})) if links else "no link"
    if reached:
        result += "; anonymous browser: %s" % reach_summary(reached)
    return Outcome(True, result, details={"literal": findings, "reach": reached,
                                          "paths": sorted({url_shape(link) for link in links})})


# --- U-E3: share dialogs ----------------------------------------------------------


def dialog(side: Side):
    box = side.root.locator(".o_dialog .modal-content").last
    box.wait_for(timeout=TIMEOUT)
    side.settle(500)
    return box


def read_link(container, *names: str) -> str:
    """The URL a share field shows: an input, a link or a text span."""
    for name in names:
        field = container.locator("[name='%s']" % name).first
        if not field.count():
            continue
        for selector in ("input", "a", "span"):
            inner = field.locator(selector).first if field.evaluate("e => e.tagName") != "INPUT" else field
            if inner.count():
                value = inner.evaluate("e => e.value || e.getAttribute('href') || e.textContent || ''").strip()
                if value.startswith("http"):
                    return value
    for inner in container.locator("input[readonly], input").all():
        value = (inner.input_value() or "").strip()
        if value.startswith("http"):
            return value
    raise RuntimeError("no link in the dialog")


def close_dialogs(side: Side) -> None:
    for _ in range(3):
        box = side.root.locator(".o_dialog .modal-content").last
        if not box.count():
            return
        box.locator("button.btn-close, footer button.btn-secondary").first.click()
        side.settle(300)


def share_from_cog(model: str, key: str, label: str, *field_names: str) -> Callable[[OutboundRun, Side], str]:
    def get(run: OutboundRun, side: Side) -> str:
        open_form(side, model, run.fx[key])
        cog_item(side, label)
        try:
            return read_link(dialog(side), *field_names)
        finally:
            close_dialogs(side)
    return get


def share_project(run: OutboundRun, side: Side) -> str:
    open_form(side, "project.project", run.fx["project"])
    side.root.locator("button[name='action_open_share_project_wizard']").first.click()
    try:
        return read_link(dialog(side), "share_link", "url")
    finally:
        close_dialogs(side)


def share_survey(run: OutboundRun, side: Side) -> str:
    open_form(side, "survey.survey", run.fx["survey"])
    side.root.locator("button[name='action_send_survey']").first.click()
    try:
        return read_link(dialog(side), "survey_start_url", "share_link")
    finally:
        close_dialogs(side)


def share_dashboard(run: OutboundRun, side: Side) -> str:
    side.goto("/odoo/action-spreadsheet_dashboard.ir_actions_dashboard_action")
    side.wait_webclient()
    side.root.locator(".o_spreadsheet_dashboard_action, .o-spreadsheet").first.wait_for(timeout=TIMEOUT)
    side.settle(1500)
    side.root.locator("button:has(.fa-share-alt)").first.click()
    # The share record is created when the dropdown opens; the link fills in after.
    span = side.root.locator(".spreadsheet_share_dropdown .o_field_CopyClipboardChar span").first
    span.wait_for(timeout=TIMEOUT)
    value = span.inner_text().strip()
    side.page.keyboard.press("Escape")
    if value.startswith("http"):
        return value
    raise RuntimeError("the dashboard Share dropdown showed no link")


def share_channel(run: OutboundRun, side: Side) -> str:
    side.goto("/odoo/discuss?active_id=discuss.channel_%d" % run.fx["channel"])
    side.wait_webclient()
    side.root.locator("button[title='Invite People'], button[title='Add Users'], button[name='add-users']").first.click()
    side.settle(800)
    panel = side.root.locator(".o-discuss-ChannelInvitation, .o-mail-ActionPanel").last
    panel.wait_for(timeout=TIMEOUT)
    for inner in panel.locator("input").all():
        value = (inner.input_value() or "").strip()
        if "/chat/" in value:
            return value
    raise RuntimeError("no invitation link in the invite panel")


def livechat_links(run: OutboundRun, side: Side) -> list[str]:
    open_form(side, "im_livechat.channel", run.fx["livechat_channel"])
    side.root.locator(".o_notebook .nav-link").filter(has_text=re.compile(r"^\s*Widget\s*$")).first.click()
    side.settle(500)
    page = side.root.locator(".o_notebook .tab-pane.active").first
    return extract_urls(page.inner_html())


def meeting_link(run: OutboundRun, side: Side) -> str:
    open_form(side, "calendar.event", run.fx[side.name]["meeting"])
    button = side.root.locator("button[name='set_discuss_videocall_location']")
    if button.count() and button.first.is_visible():
        button.first.click()
        side.settle(1500)
    field = side.root.locator("div[name='videocall_location']").first
    field.wait_for(timeout=TIMEOUT)
    value = field.evaluate("e => (e.querySelector('input') || {}).value || e.textContent || ''").strip()
    match = re.search(r"https?://\S+", value)
    if not match:
        raise RuntimeError("no meeting URL on the event")
    # The frontend builds the URL; it exists for Odoo only once the event is saved.
    save = side.root.locator(".o_form_button_save")
    if save.count() and save.first.is_visible():
        save.first.click()
        side.settle(1500)
    stored = side.rpc("calendar.event", "read", [[run.fx[side.name]["meeting"]], ["videocall_location"]])[0]
    if stored["videocall_location"] != match.group(0):
        raise RuntimeError("the saved meeting URL differs from the one the form showed")
    return match.group(0)


def check_e3(run: OutboundRun) -> None:
    rpc = run.public.rpc
    invoice_name = rpc("account.move", "read", [[run.fx["invoice"]], ["name"]])[0]["name"]
    po_name = rpc("purchase.order", "read", [[run.fx["purchase_order"]], ["name"]])[0]["name"]
    livechat_name = rpc("im_livechat.channel", "read", [[run.fx["livechat_channel"]], ["name"]])[0]["name"]
    marker = run.marker
    screens: list[tuple[str, str, Callable[[OutboundRun, Side], Any], str | None, str]] = [
        ("sale_management", "quotation Share", share_from_cog("sale.order", "sale_order", "Share", "share_link"),
         marker + " E customer", "Action menu > Share (portal.share) on a quotation."),
        ("account", "invoice Share", share_from_cog("account.move", "invoice", "Share", "share_link"),
         invoice_name, "Action menu > Share (portal.share) on a posted invoice."),
        ("purchase", "purchase order Share", share_from_cog("purchase.order", "purchase_order", "Share", "share_link"),
         po_name, "Action menu > Share (portal.share) on an RFQ."),
        ("project", "task Share", share_from_cog("project.task", "task", "Share Task", "share_link"),
         marker + " E task", "Action menu > Share Task (portal.share)."),
        ("project", "project Share", share_project, marker + " E project",
         "Share Project button (project.share.wizard) on a project visible to portal users."),
        ("survey", "survey Share", share_survey, marker + " E survey",
         "Share button (survey.invite) on a public survey."),
        ("spreadsheet_dashboard", "dashboard Share", share_dashboard, None,
         "Dashboards > Share (spreadsheet.dashboard.share): a frozen public copy."),
        ("mail", "Discuss channel invitation", share_channel, marker + " E channel",
         "Discuss > channel > Invite People: the invitation link, on a channel without an Authorized Group."),
        ("im_livechat", "live chat channel links", livechat_links, livechat_name,
         "Live Chat channel > Widget tab: the script URL and the direct chat page."),
        ("calendar", "meeting link", meeting_link, None,
         "Calendar event > Odoo meeting: the Videocall URL, set on each surface's own event."),
    ]
    for module, screen, get, expect, notes in screens:
        identity = check_identity("U-E3", module, screen)

        def probe(side: Side, get=get, expect=expect, module=module) -> Outcome:
            value = get(run, side)
            links = value if isinstance(value, list) else [value]
            if module == "im_livechat":  # the widget's script and loader are not pages
                anonymous = {link: expect for link in links if "/im_livechat/support/" in link}
            else:
                anonymous = {link: expect for link in links}
            return link_outcome(run, identity, side, links, anonymous)

        public, ingress = run.both(probe)
        run.emit("U-E3", module, screen, public, ingress, notes=notes)


# --- U-E4: PDF reports and their QR codes ------------------------------------------


def qr_payloads(pdf: bytes) -> list[str]:
    """Render each page and decode every QR code on it."""
    import pymupdf as fitz
    import zxingcpp
    from PIL import Image
    import io

    payloads: list[str] = []
    with fitz.open(stream=pdf, filetype="pdf") as document:
        for page in document:
            pixmap = page.get_pixmap(dpi=200)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            for result in zxingcpp.read_barcodes(image):
                if result.format == zxingcpp.BarcodeFormat.QRCode:
                    payloads.append(result.text)
    return payloads


def print_report(side: Side, model: str, record_id: int, labels: tuple[str, ...]) -> bytes:
    """The gear menu path to a PDF: an invoice has Download, other records Print > the report."""
    open_form(side, model, record_id)
    data, _ = download(side, lambda: cog_item(side, *labels), timeout=120_000)
    return data


def check_e4(run: OutboundRun) -> None:
    no_qr = ("the company has no QR payment method (Taiwan, Odoo CE), so the invoice carries no QR code; the "
             "ECPay e-invoice print needs an issued e-invoice (#146)")
    for module, screen, model, key, label, notes in (
        ("account", "invoice PDF", "account.move", "invoice", ("Download", "PDF"),
         "Action menu > Download > PDF on a posted invoice. The company has no QR payment method for Taiwan, so "
         "the invoice carries no QR code."),
        ("account", "invoice PDF without Payment", "account.move", "invoice", ("Download", "PDF without Payment"),
         "Action menu > Download > PDF without Payment: the invoice report through /report/, the path the "
         "Download > PDF action does not take."),
        ("event", "event ticket PDF", "event.registration", "event_registration", ("Print", "Full Page Ticket"),
         "Action menu > Print > Full Page Ticket for the attendee."),
    ):
        def probe(side: Side, model=model, key=key, label=label) -> Outcome:
            pdf = print_report(side, model, run.fx[key], label)
            payloads = qr_payloads(pdf)
            links = pdf_urls(pdf)
            findings = qr_findings(payloads, links, run.bases)
            kinds = sorted(findings["literal"]["counts"]) or ["none"]
            result = "%d QR code(s), %d carry a URL; PDF and QR links: %s" % (
                findings["qr"]["count"], findings["qr"]["urls"], ", ".join(kinds))
            literal = dict(findings["literal"], ok=findings["ok"])
            return Outcome(True, result, details={"literal": literal, "qr": findings["qr"],
                                                  "qr_payload_kinds": sorted({"url" if extract_urls(p) else "text"
                                                                              for p in payloads})})

        public, ingress = run.both(probe)
        run.emit("U-E4", module, screen, public, ingress, notes=notes,
                 blocked_by=no_qr if module == "account" else None)


# --- U-E7: exported files -----------------------------------------------------------


def export_file(side: Side, route: str, search: str, fmt: str, fields: list[tuple[str, str]]) -> bytes:
    """Export the marker's records; `fields` are (field id, label to search for) to add when missing."""
    side.goto(route)
    side.wait_webclient()
    root = side.root
    box = root.locator(".o_searchview_input").first
    box.fill(search)
    box.press("Enter")
    side.settle(800)
    root.locator("thead .o_list_record_selector").first.click()
    cog_item(side, "Export", menu="Actions")
    export = dialog(side)
    export.locator("input[value='%s'], label:has-text('%s') input" % (fmt, fmt.upper())).first.check()
    existing = export.locator(".o_export_field").all_inner_texts()
    for field_id, label in fields:
        if any(label in text for text in existing):
            continue
        export.locator(".o_export_search_input").first.fill(label)
        side.settle(600)
        row = export.locator(".o_export_tree_item[data-field_id='%s']" % field_id).first
        row.hover()
        row.locator(".o_add_field").first.click()
        side.settle(300)
    data, _ = download(side, lambda: export.locator("footer button.btn-primary, button.o_select_button").first.click())
    close_dialogs(side)
    return data


def check_e7(run: OutboundRun) -> None:
    for module, screen, route, search, fmt, fields in (
        ("mass_mailing", "link tracker export xlsx", "/odoo/action-link_tracker.link_tracker_action?view_type=list",
         run.marker + " E link", "xlsx", [("short_url", "Tracked URL")]),
        ("mass_mailing", "link tracker export csv", "/odoo/action-link_tracker.link_tracker_action?view_type=list",
         run.marker + " E link", "csv", [("short_url", "Tracked URL")]),
        ("calendar", "meeting export xlsx", "/odoo/action-calendar.action_calendar_event?view_type=list",
         run.marker + " E3 meeting", "xlsx", [("videocall_location", "Meeting URL")]),
        ("calendar", "meeting export csv", "/odoo/action-calendar.action_calendar_event?view_type=list",
         run.marker + " E3 meeting", "csv", [("videocall_location", "Meeting URL")]),
    ):
        def probe(side: Side, route=route, search=search, fmt=fmt, fields=fields) -> Outcome:
            data = export_file(side, route, search, fmt, fields)
            cells = xlsx_strings(data) if fmt == "xlsx" else csv_strings(data)
            urls = [url for cell in cells for url in extract_urls(cell)]
            findings = literal_findings(urls, run.bases)
            return Outcome(True, "%s with %d URL(s) on %s" % (fmt, len(urls), ", ".join(sorted(findings["counts"]))
                                                              or "nothing"),
                           details={"literal": findings})

        public, ingress = run.both(probe)
        run.emit("U-E7", module, screen, public, ingress,
                notes="List > the marker's records > Actions > Export as %s, with the %s column." % (
                    fmt, ", ".join(label for _, label in fields)))


# --- U-E2 / U-E5: mail triggers ------------------------------------------------------


def chatter_send(side: Side, model: str, record_id: int, text: str, attachment: tuple[str, bytes] | None = None) -> None:
    open_form(side, model, record_id)
    root = side.root
    root.locator(".o-mail-Chatter-topbar button").filter(has_text=re.compile(r"^\s*Send message\s*$")).first.click()
    composer = root.locator(".o-mail-Composer").first
    composer.wait_for(timeout=TIMEOUT)
    if attachment:
        name, content = attachment
        composer.locator("input[type=file]").first.set_input_files(
            files=[{"name": name, "mimeType": "text/plain", "buffer": content}])
        composer.locator(".o-mail-AttachmentCard, .o-mail-AttachmentList").filter(has_text=name).first.wait_for(
            timeout=TIMEOUT)
        side.settle(1000)
    composer.locator("textarea, .o-mail-Composer-input").first.fill(text)
    composer.locator("button").filter(has_text=re.compile(r"^\s*Send\s*$")).first.click()
    root.locator(".o-mail-Message").filter(has_text=text).first.wait_for(timeout=TIMEOUT)


def notify_order(side: Side, per: dict, marker: str) -> int:
    """A quotation for the surface's notify partner, who follows it."""
    ref = "%s E2 notify %s" % (marker, side.name)
    found = side.rpc("sale.order", "search", [[["client_order_ref", "=", ref]]], {"limit": 1})
    if found:
        return found[0]
    product = side.rpc("product.product", "search", [[["sale_ok", "=", True], ["type", "=", "service"]]],
                       {"limit": 1})[0]
    order = side.rpc("sale.order", "create", [{"partner_id": per["notify"], "client_order_ref": ref,
                                               "order_line": [[0, 0, {"product_id": product,
                                                                      "product_uom_qty": 1}]]}])
    side.rpc("sale.order", "message_subscribe", [[order]], {"partner_ids": [per["notify"]]})
    return order


def click_button(side: Side, name: str) -> None:
    side.root.locator("button[name='%s']:visible" % name).first.click()
    side.settle(1500)
    box = side.root.locator(".o_dialog .modal-content").last
    if box.count():  # a confirmation, when the action asks for one; an error is a failure
        title = box.locator(".modal-title").first.inner_text() if box.locator(".modal-title").count() else ""
        if box.locator(".o_error_dialog").count() or re.search(r"Error|Invalid|Warning", title):
            text = box.inner_text().strip().splitlines()
            box.locator("footer button").first.click()
            raise RuntimeError("%s: %s" % (title, " ".join(text[1:3])))
        box.locator("footer button.btn-primary").first.click()
        side.settle(1500)


def trigger_mail(run: OutboundRun, screens: set[str] | None = None, sides: set[str] | None = None) -> None:
    """Every mail-producing action on each surface (or only `screens`); the judging waits for the sink (`mail`)."""
    plan: list[dict[str, Any]] = []
    marker = run.marker
    actions: list[tuple[str, str, str, str, Callable[[Side, dict], None]]] = [
        ("U-E2", "portal", "portal invitation", "invite",
         lambda side, per: (open_form(side, "res.partner", per["invite"]), cog_item(side, "Grant portal access"),
                            dialog(side).locator("button[name='action_grant_access']").first.click(),
                            side.settle(2000), close_dialogs(side))),
        ("U-E2", "auth_signup", "password reset", "reset",
         # Settings > Users: /odoo/res.users/<id> alone opens a form without the header buttons.
         lambda side, per: (side.goto("/odoo/action-base.action_res_users/%d" % per["reset_user"]),
                            side.wait_webclient(), click_button(side, "action_reset_password"))),
        # On the customer's own quotation, so the notification carries its portal button.
        ("U-E2", "mail", "chatter notification", "notify",
         lambda side, per: chatter_send(side, "sale.order", notify_order(side, per, marker),
                                        "%s E2 notification from %s" % (marker, side.name))),
        ("U-E2", "mass_mailing", "tracking and unsubscribe", "mm",
         lambda side, per: (open_form(side, "mailing.mailing", per["mailing"]), click_button(side, "action_launch"))),
        ("U-E2", "hr_holidays", "time off approval", "leave",
         lambda side, per: (open_form(side, "hr.leave", per["leave"]), click_button(side, "action_approve"))),
        ("U-E2", "hr_expense", "expense approval", "expense",
         lambda side, per: (open_form(side, "hr.expense.sheet", per["expense_sheet"]),
                            click_button(side, "action_approve_expense_sheets"))),
        ("U-E5", "mail", "attachment links in outgoing mail", "attach",
         lambda side, per: chatter_send(side, "res.partner", per["attach"],
                                        "%s E5 attachment from %s" % (marker, side.name),
                                        ("%s E5 %s.txt" % (marker, side.name),
                                         (ATTACHMENT_TEXT + marker).encode("utf-8")))),
    ]
    for item, module, screen, what, action in actions:
        if screens and screen not in screens:
            continue
        for side in run.sides:
            if sides and side.name not in sides:
                continue
            entry = {"identity": check_identity(item, module, screen), "check": [item, module, screen], "side": side.name,
                     "recipient": recipient(what, side.name), "triggered": True, "error": None}
            side.close_chat_windows()
            try:
                action(side, run.fx[side.name])
            except Exception as error:  # noqa: BLE001 -- the mail step records it
                entry["triggered"] = False
                entry["error"] = run.env.mask((str(error).splitlines() or [""])[0])
                side.page.screenshot(path=os.path.join(artifact_dir(), "%s-%s-%s.png" % (run.info.run_id, what, side.name)))
                try:
                    close_dialogs(side)
                except Exception:  # noqa: BLE001
                    pass
            plan.append(entry)
            print("mail trigger %-45s %-8s %s" % (entry["identity"], side.name,
                                                  "ok" if entry["triggered"] else entry["error"]), file=sys.stderr)
    redone = {(entry["identity"], entry["side"]) for entry in plan}
    run.mail_plan = [entry for entry in run.mail_plan if (entry["identity"], entry["side"]) not in redone] + plan
    _save(mail_plan_path(run.info.run_id), run.mail_plan)
    flush_mail(run)


def flush_mail(run: OutboundRun) -> None:
    """Send what the actions queued now, instead of waiting for the crons."""
    rpc = run.public.rpc
    cron = rpc("ir.model.data", "search_read", [[["module", "=", "mass_mailing"],
                                                 ["name", "=", "ir_cron_mass_mailing_queue"]]], {"fields": ["res_id"]})
    if cron:
        rpc("ir.cron", "method_direct_trigger", [[cron[0]["res_id"]]])
    for _ in range(3):
        rpc("mail.mail", "process_email_queue", [])
        time.sleep(2)


# What an anonymous visitor may open in each kind of mail, and what it then shows.
ANONYMOUS_MAIL_LINKS: dict[str, list[tuple[str, str | None]]] = {
    "portal invitation": [(r"/web/(signup|login|reset_password)", "password")],
    "password reset": [(r"/web/(reset_password|signup)", "password")],
    # The notify partner is the quotation's customer: its View button carries an access token.
    "chatter notification": [(r"/mail/view", "quotation")],
    "tracking and unsubscribe": [(r"/r/[A-Za-z0-9]+", "contact"), (r"/mailing/\d+/confirm_unsubscribe", "subscri"),
                                 (r"/mail/track/", None)],
    "attachment links in outgoing mail": [(r"/web/content/\d+\?.*access_token", "WOOW-PARITY outbound attachment")],
}


def judge_mail(run: OutboundRun, mail_dir: str) -> None:
    messages = []
    for name in sorted(os.listdir(mail_dir)):
        if name.endswith(".eml"):
            with open(os.path.join(mail_dir, name), "rb") as handle:
                messages.append(mail_urls(handle.read()))
    by_identity: dict[str, dict[str, dict]] = {}
    for entry in run.mail_plan:
        by_identity.setdefault(entry["identity"], {})[entry["side"]] = entry
    for identity, sides in by_identity.items():
        item, module, screen = sides["public"]["check"]
        outcomes = []
        for side_name in ("public", "ingress"):
            entry = sides[side_name]
            if not entry["triggered"]:
                outcomes.append(Outcome(False, "not triggered: %s" % entry["error"]))
                continue
            mine = [message for message in messages if entry["recipient"] in [to.lower() for to in message["to"]]]
            if not mine:
                outcomes.append(Outcome(False, "no mail captured for the %s recipient" % side_name))
                continue
            urls = sorted({url for message in mine for url in message["urls"]})
            findings = literal_findings(urls, run.bases)
            reached, missing = [], []
            for pattern, expect in ANONYMOUS_MAIL_LINKS.get(screen, []):
                link = next((url for url in urls if re.search(pattern, url) and not url.startswith("/")), None)
                if link:
                    reached.append(run.reach(identity, side_name, link, expect))
                else:
                    missing.append(pattern)
            result = "%d mail(s), links on %s" % (len(mine), ", ".join(sorted(findings["counts"])) or "nothing")
            if reached:
                result += "; anonymous browser: %s" % reach_summary(reached)
            if missing:
                result += "; no link for %s" % ", ".join(missing)
            outcomes.append(Outcome(True, result, details={
                "literal": findings, "reach": reached, "subjects": sorted({message["subject"] for message in mine}),
                "paths": sorted({url_shape(url) for url in urls})}))
        run.emit(item, module, screen, outcomes[0], outcomes[1],
                notes="Triggered through the UI of each surface; captured by the SMTP sink, never relayed.")


# --- Command line -------------------------------------------------------------------

ORDER = {"U-E3": check_e3, "U-E4": check_e4, "U-E7": check_e7, "U-E2": trigger_mail,
         "U-D8": CHECKS["U-D8"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("fixtures", "run", "mail", "teardown"):
        sub = commands.add_parser(name)
        sub.add_argument("--env-file")
        sub.add_argument("--db", required=True)
        sub.add_argument("--headed", action="store_true")
        sub.add_argument("--run-id", required=name != "run")
        if name in ("run", "mail"):
            sub.add_argument("--out", required=True, help="JSONL file; records are appended")
        if name == "run":
            sub.add_argument("--only", help="comma-separated: U-E3,U-E4,U-E7,U-E2 (mail triggers),U-D8")
            sub.add_argument("--mail-screens", help="with U-E2: only these trigger screens, e.g. 'password reset'")
            sub.add_argument("--mail-sides", help="with --mail-screens: only these surfaces (public, ingress)")
        if name == "mail":
            sub.add_argument("--mail-dir", required=True, help="the sink's captured .eml files, copied out")
    report = commands.add_parser("report")
    report.add_argument("records")
    report.add_argument("--issues", help="JSON object: control identity -> issue number")
    report.add_argument("--off-lan", help="JSON list of {identity, side, status, shown} from the off-LAN browser")
    report.add_argument("--off-lan-browser", default="off-LAN browser")
    args = parser.parse_args(argv)

    if args.command == "report":
        with open(args.records, encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        changed = False
        if args.off_lan:
            with open(args.off_lan, encoding="utf-8") as handle:
                records = merge_off_lan(records, json.load(handle), browser=args.off_lan_browser)
            changed = True
        if args.issues:
            with open(args.issues, encoding="utf-8") as handle:
                records = attach_issues(records, {key: int(value) for key, value in json.load(handle).items()})
            changed = True
        if changed:
            with open(args.records, "w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        result = conservation(records, outbound_plan())
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
        browser = playwright.chromium.launch(headless=not args.headed)
        public = ingress = None
        try:
            public, ingress = open_sides(env, browser)
            if args.command == "fixtures":
                ids = create_fixtures(public, args.run_id)
                _save(fixture_path(args.run_id), ids)
                print("fixtures: %s" % json.dumps(env.mask(ids)))
                return 0
            if args.command == "teardown":
                fx = _load(fixture_path(args.run_id), {})
                public.rpc("ir.mail_server", "write", [[fx["mail_server"]], {"active": False}])
                print("capture mail server archived")
                return 0
            run_info = RunInfo(args.run_id or new_run_id(), env.target, env.db)
            with open(args.out, "a", encoding="utf-8") as out:
                run = OutboundRun(env, run_info, public, ingress, out, browser)
                if args.command == "mail":
                    judge_mail(run, args.mail_dir)
                    return 0
                items = [item.strip() for item in args.only.split(",")] if args.only else list(ORDER)
                for item in items:
                    try:
                        if item == "U-E2" and args.mail_screens:
                            trigger_mail(run, {screen.strip() for screen in args.mail_screens.split(",")},
                                         set(args.mail_sides.split(",")) if args.mail_sides else None)
                            continue
                        ORDER[item](run)
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
        try:
            message = Env(os.environ.get("ODOO_DB", "")).mask(message)
        except Exception:  # noqa: BLE001
            pass
        print("outbound parity run failed: %s" % message, file=sys.stderr)
        sys.exit(2)
