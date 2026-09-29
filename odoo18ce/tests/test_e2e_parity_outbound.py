#!/usr/bin/env python3
"""Static-tier tests for the pure parts of the outbound-artefact parity run (#145).

Nothing here opens a browser or reads credentials; the SMTP sink runs on
the loopback interface only.
"""
import csv
import io
import os
import smtplib
import tempfile
import threading
import unittest
import zipfile
from email.message import EmailMessage

from e2e_menu_action_adapter import RunInfo
from e2e_parity_outbound import (
    OUTBOUND_SCREENS,
    Bases,
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
from e2e_parity_shared_layers import CATALOG, Outcome, planned_checks
import smtp_capture_sink

PUBLIC = "https://odoo.example.test"
HA = "http://ha.example.test:8123"
PREFIX = "/api/hassio_ingress/tok_ABC123"
BASES = Bases(public=PUBLIC, ha=(HA, "https://ha-secure.example.test"), prefix=PREFIX)
RUN = RunInfo(run_id="WOOW-PARITY-20260925T000000Z", target="local", database="example_db")


class PlanTests(unittest.TestCase):
    def test_group_e_is_catalogued_but_stays_out_of_the_shared_layer_plan(self) -> None:
        self.assertEqual(sorted(i for i in CATALOG if i.startswith("U-E")),
                         ["U-E1", "U-E2", "U-E3", "U-E4", "U-E5", "U-E6", "U-E7"])
        self.assertFalse([check for check in planned_checks() if check[0].startswith("U-E")])

    def test_the_plan_covers_every_artefact_kind_the_issue_names(self) -> None:
        plan = outbound_plan()
        self.assertEqual(len(set(plan)), len(plan))
        self.assertEqual({item for item, _, _ in plan}, {"U-E2", "U-E3", "U-E4", "U-E5", "U-E7", "U-D8"})
        for screen in ("portal invitation", "password reset", "chatter notification",
                       "tracking and unsubscribe", "time off approval", "expense approval"):
            self.assertIn(screen, [s for item, _, s in plan if item == "U-E2"])
        self.assertIn(("U-E4", "event", "event ticket PDF"), plan)
        self.assertIn(("U-D8", "shared", "generic"), plan)
        self.assertIn(("U-D8", "website", "sitemap.xml"), plan)
        for item, module, screen in OUTBOUND_SCREENS:
            self.assertIn(item, CATALOG)
            self.assertTrue(module and screen)


class ClassifyTests(unittest.TestCase):
    def test_each_kind_of_url(self) -> None:
        cases = {
            PUBLIC + "/my/orders/7?access_token=x": "canonical",
            PUBLIC: "canonical",
            HA + PREFIX + "/odoo": "ingress-token",
            PUBLIC + PREFIX + "/web": "ingress-token",
            HA + "/web/image/1": "ha",
            "https://ha-secure.example.test/web": "ha",
            "/web/content/5": "relative",
            "https://www.odoo.com/app/crm": "external",
            "http://www.w3.org/1999/xhtml": "namespace",
            "http://schema.org/ViewAction": "namespace",
            "mailto:someone@example.invalid": "not-a-link",
            "#top": "not-a-link",
        }
        for url, kind in cases.items():
            with self.subTest(url=url):
                self.assertEqual(classify_url(url, BASES), kind)

    def test_a_public_origin_with_a_path_is_not_matched_by_prefix_alone(self) -> None:
        self.assertEqual(classify_url("https://odoo.example.test.evil.invalid/x", BASES), "external")

    def test_findings_pass_only_without_ingress_ha_or_relative_urls(self) -> None:
        clean = literal_findings([PUBLIC + "/r/abc", "https://www.odoo.com"], BASES)
        self.assertTrue(clean["ok"])
        self.assertEqual(clean["counts"], {"canonical": 1, "external": 1})
        dirty = literal_findings([PUBLIC + "/a", HA + PREFIX + "/b", "/web/c"], BASES)
        self.assertFalse(dirty["ok"])
        self.assertEqual(dirty["problems"], [HA + "/api/hassio_ingress/<token>/b", "/web/c"])

    def test_findings_without_any_url_are_not_ok(self) -> None:
        self.assertFalse(literal_findings([], BASES)["ok"])
        self.assertTrue(literal_findings([], BASES, allow_empty=True)["ok"])


class ExtractTests(unittest.TestCase):
    def test_href_src_and_bare_urls_from_html_and_text(self) -> None:
        html = ('<a href="%s/web/signup?token=abc&amp;db=x">Accept</a> <img src="/web/image/1"/>'
                ' visit %s/contactus. <a href="mailto:a@example.invalid">m</a>' % (PUBLIC, PUBLIC))
        # Sorted and unique; entities decoded; trailing punctuation dropped.
        self.assertEqual(extract_urls(html), [
            "/web/image/1", PUBLIC + "/contactus", PUBLIC + "/web/signup?token=abc&db=x",
        ])

    def test_a_captured_mail_yields_its_urls_from_every_part(self) -> None:
        message = EmailMessage()
        message["Subject"] = "Invitation"
        message["To"] = "e2-public@example.invalid"
        message.set_content("Open %s/web/login\n" % PUBLIC)
        message.add_alternative('<p><a href="%s/mail/view?x=1">View</a>'
                                '<img src="%s/mail/track/1/blank.gif"/></p>' % (PUBLIC, HA + PREFIX), subtype="html")
        parsed = mail_urls(message.as_bytes())
        self.assertEqual(parsed["subject"], "Invitation")
        self.assertEqual(parsed["to"], ["e2-public@example.invalid"])
        self.assertEqual(parsed["urls"], [HA + PREFIX + "/mail/track/1/blank.gif",
                                          PUBLIC + "/mail/view?x=1", PUBLIC + "/web/login"])

    def test_quoted_printable_soft_breaks_do_not_split_a_url(self) -> None:
        raw = ("Subject: t\r\nTo: x@example.invalid\r\nMIME-Version: 1.0\r\n"
               "Content-Type: text/html; charset=utf-8\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\n"
               '<a href=3D"%s/unsubscribe_from_list?very_long_param=\r\n=3D1">x</a>\r\n' % PUBLIC).encode()
        self.assertEqual(mail_urls(raw)["urls"], [PUBLIC + "/unsubscribe_from_list?very_long_param=1"])

    def test_xlsx_and_csv_cells(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("xl/sharedStrings.xml",
                             '<sst><si><t>Tracked URL</t></si><si><t>%s/r/Ab1</t></si></sst>' % PUBLIC)
            archive.writestr("xl/worksheets/sheet1.xml",
                             '<worksheet><sheetData><row><c t="inlineStr"><is><t>%s/calendar/join_videocall/z'
                             '</t></is></c></row></sheetData></worksheet>' % PUBLIC)
        self.assertEqual(xlsx_strings(buffer.getvalue()),
                         ["Tracked URL", PUBLIC + "/r/Ab1", PUBLIC + "/calendar/join_videocall/z"])
        text = io.StringIO()
        csv.writer(text).writerows([["Tracked URL", "Name"], [PUBLIC + "/r/Ab1", "x"]])
        self.assertEqual(csv_strings(text.getvalue().encode("utf-8")), ["Tracked URL", "Name", PUBLIC + "/r/Ab1", "x"])


class ShapeTests(unittest.TestCase):
    def test_ids_and_tokens_in_a_path_never_survive(self) -> None:
        cases = {
            PUBLIC + "/chat/9/Ab3TeQtHr7gg?x=1": PUBLIC + "/chat/<id>/<token>",
            PUBLIC + "/survey/start/5fe1b2c3-0000-4aaa-b111-22db3c4d5e6f": PUBLIC + "/survey/start/<token>",
            PUBLIC + "/calendar/join_videocall/d41c8b0bf7ec9dbe2": PUBLIC + "/calendar/join_videocall/<token>",
            PUBLIC + "/im_livechat/support/1": PUBLIC + "/im_livechat/support/<id>",
            PUBLIC + "/im_livechat/assets_embed.js": PUBLIC + "/im_livechat/assets_embed.js",
            PUBLIC + "/r/aB3x": PUBLIC + "/r/<token>",
            PUBLIC + "/r/NOf/m/1": PUBLIC + "/r/<token>/m/<id>",
            PUBLIC + "/unsubscribe_from_list": PUBLIC + "/unsubscribe_from_list",
            "/web/content/12?download=1&access_token=z": "/web/content/<id>",
        }
        for url, shape in cases.items():
            with self.subTest(url=url):
                self.assertEqual(url_shape(url), shape)


class QrTests(unittest.TestCase):
    def test_a_qr_that_carries_no_url_passes_and_says_so(self) -> None:
        findings = qr_findings(["123456789012"], [PUBLIC + "/my/invoices/1"], BASES)
        self.assertTrue(findings["ok"])
        self.assertEqual(findings["qr"], {"count": 1, "urls": 0})

    def test_a_qr_url_off_the_canonical_url_fails(self) -> None:
        findings = qr_findings([HA + PREFIX + "/report/x"], [], BASES)
        self.assertFalse(findings["ok"])

    def test_a_pdf_without_any_qr_is_not_ok(self) -> None:
        self.assertFalse(qr_findings([], [], BASES)["ok"])


class RecordTests(unittest.TestCase):
    def outcome(self, urls, result=None):
        findings = literal_findings(urls, BASES)
        return Outcome(True, result or ("clean" if findings["ok"] else "leak"), details={"literal": findings})

    def test_equal_clean_results_are_parity(self) -> None:
        record = outbound_record(RUN, "U-E2", "portal", "portal invitation",
                                 self.outcome([PUBLIC + "/a"]), self.outcome([PUBLIC + "/b"]), bases=BASES)
        self.assertEqual((record["verdict"], record["severity"]), ("PARITY", "none"))

    def test_the_same_leak_on_both_surfaces_is_still_a_gap(self) -> None:
        # The Canonical URL is an absolute requirement, not a comparison.
        leak = [HA + PREFIX + "/web/signup"]
        record = outbound_record(RUN, "U-E2", "portal", "portal invitation", self.outcome(leak), self.outcome(leak),
                                 bases=BASES)
        self.assertEqual((record["verdict"], record["severity"]), ("GAP", "blocker"))
        self.assertIn("ingress-token", record["notes"])

    def test_an_ha_url_without_the_token_is_important(self) -> None:
        record = outbound_record(RUN, "U-E7", "calendar", "meeting export xlsx",
                                 self.outcome([PUBLIC + "/a"]), self.outcome([HA + "/b"]), bases=BASES)
        self.assertEqual((record["verdict"], record["severity"]), ("GAP", "important"))

    def test_an_artefact_with_nothing_to_judge_is_not_run_and_says_why(self) -> None:
        # A PDF without a QR code, or a mail without a link, cannot pass a check about them.
        empty = Outcome(True, "0 QR code(s)", details={"literal": qr_findings([], [], BASES)})
        with self.assertRaises(ValueError):
            outbound_record(RUN, "U-E4", "account", "invoice PDF without Payment", empty, empty, bases=BASES)
        record = outbound_record(RUN, "U-E4", "account", "invoice PDF without Payment", empty, empty, bases=BASES,
                                 blocked_by="no QR payment method for Taiwan in CE")
        self.assertEqual((record["verdict"], record["blocked_by"]), ("NOT-RUN", "no QR payment method for Taiwan in CE"))

    def test_a_link_an_anonymous_browser_cannot_open_is_a_gap_even_on_both_sides(self) -> None:
        def reached(shown):
            findings = literal_findings([PUBLIC + "/a"], BASES)
            return Outcome(True, "same", details={"literal": findings,
                                                  "reach": [{"link": "<PUBLIC_BASE>/a", "status": 404, "shown": shown}]})
        record = outbound_record(RUN, "U-E3", "project", "task Share", reached(False), reached(False), bases=BASES)
        self.assertEqual((record["verdict"], record["severity"]), ("GAP", "important"))
        self.assertIn("public anonymous: <PUBLIC_BASE>/a not shown (HTTP 404)", record["notes"])
        self.assertEqual(outbound_record(RUN, "U-E3", "project", "task Share", reached(True), reached(True),
                                         bases=BASES)["verdict"], "PARITY")

    def test_off_lan_results_merge_into_their_record(self) -> None:
        record = outbound_record(RUN, "U-E3", "project", "task Share",
                                 self.outcome([PUBLIC + "/a"]), self.outcome([PUBLIC + "/b"]), bases=BASES)
        merged = merge_off_lan([record], [
            {"identity": record["control_identity"], "side": "public", "status": 200, "shown": True, "link": "/a"},
            {"identity": record["control_identity"], "side": "ingress", "status": 200, "shown": True, "link": "/b"},
            {"identity": record["control_identity"], "side": "ingress", "status": 404, "shown": False, "link": "/c"},
        ], browser="browserless cloud, egress off the LAN")
        details = merged[0]["ingress"]["details"]["off_lan"]
        self.assertEqual(details, {"browser": "browserless cloud, egress off the LAN", "links": [
            {"link": "/b", "status": 200, "shown": True}, {"link": "/c", "status": 404, "shown": False}]})
        self.assertEqual((merged[0]["verdict"], merged[0]["severity"]), ("GAP", "important"))
        self.assertIn("ingress off-LAN: /c not shown (HTTP 404)", merged[0]["notes"])
        self.assertEqual(merged[0]["public"]["details"]["off_lan"]["links"], [{"link": "/a", "status": 200, "shown": True}])

    def test_merging_twice_replaces_the_earlier_off_lan_result(self) -> None:
        record = outbound_record(RUN, "U-E3", "project", "task Share",
                                 self.outcome([PUBLIC + "/a"]), self.outcome([PUBLIC + "/b"]), bases=BASES)
        result = {"identity": record["control_identity"], "side": "public", "status": 200, "shown": True, "link": "/a"}
        once = merge_off_lan([record], [result], browser="b")
        twice = merge_off_lan(once, [result], browser="b")
        self.assertEqual(twice[0]["public"]["details"]["off_lan"]["links"], [{"link": "/a", "status": 200, "shown": True}])

    def test_off_lan_results_for_an_unknown_record_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            merge_off_lan([], [{"identity": "check:U-E3|x|y", "side": "public", "status": 200, "shown": True}],
                          browser="b")


class SinkTests(unittest.TestCase):
    def test_the_sink_stores_each_message_and_never_relays(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = smtp_capture_sink.make_server("127.0.0.1", 0, directory)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                message = EmailMessage()
                message["Subject"] = "hello"
                message["From"] = "odoo@example.invalid"
                message["To"] = "someone@example.invalid"
                message.set_content(".leading dot line\nsecond\n")
                with smtplib.SMTP("127.0.0.1", port, timeout=10) as client:
                    client.ehlo()
                    client.send_message(message)
                    client.send_message(message)
            finally:
                server.shutdown()
                server.server_close()
            names = sorted(os.listdir(directory))
            self.assertEqual(len(names), 2)
            with open(os.path.join(directory, names[0]), "rb") as handle:
                stored = handle.read()
            self.assertIn(b"X-Capture-Rcpt: someone@example.invalid", stored)
            self.assertIn(b"\n.leading dot line", stored)
            self.assertIn(b"Subject: hello", stored)


if __name__ == "__main__":
    unittest.main()
