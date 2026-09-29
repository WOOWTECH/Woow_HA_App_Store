#!/usr/bin/env python3
"""Static-tier tests for the pure parts of the ECPay stage payment run (#146).

Nothing here opens a browser, reads credentials or talks to ECPay.
"""
import unittest

from e2e_ecpay_stage_live import (
    callback_hits,
    callback_outcome,
    callback_urls_outcome,
    ecpay_records,
    einvoice_outcome,
    log_entries,
    rendering_urls,
)
from e2e_menu_action_adapter import RunInfo
from e2e_parity_outbound import Bases
from e2e_parity_shared_layers import Outcome

RUN = RunInfo(run_id="WOOW-PARITY-20260927T000000Z", target="local", database="example_db")
BASES = Bases(public="https://odoo.example.com", ha=("http://192.0.2.10:8123",),
              prefix="/api/hassio_ingress/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789")


def form(**overrides):
    fields = {
        "ReturnURL": "https://odoo.example.com/payment/ecpay/result_notify",
        "OrderResultURL": "https://odoo.example.com/payment/ecpay/website_return",
        "ClientBackURL": "https://odoo.example.com/payment/ecpay/website_return",
        "PaymentInfoURL": "https://odoo.example.com/payment/ecpay/info_notify",
        "MerchantTradeNo": "odoo10927101010",
    }
    fields.update(overrides)
    return fields


class CallbackUrlTests(unittest.TestCase):
    def test_every_callback_and_return_url_on_the_canonical_url_over_https_passes(self) -> None:
        outcome = callback_urls_outcome(form(), BASES)
        self.assertTrue(outcome.available)
        self.assertEqual(outcome.result, "callback and return URLs on the Canonical URL over https")
        self.assertEqual(outcome.details["urls"]["ReturnURL"],
                         {"kind": "canonical", "url": "https://odoo.example.com/payment/ecpay/result_notify"})

    def test_a_return_url_under_the_ingress_prefix_is_a_token_leak(self) -> None:
        outcome = callback_urls_outcome(
            form(ReturnURL="http://192.0.2.10:8123" + BASES.prefix + "/payment/ecpay/result_notify"), BASES)
        self.assertEqual(outcome.result, "1 callback URL off the Canonical URL")
        self.assertEqual(outcome.details["urls"]["ReturnURL"]["kind"], "ingress-token")
        self.assertNotIn(BASES.prefix, str(outcome.details))

    def test_a_url_on_home_assistant_is_off_the_canonical_url(self) -> None:
        outcome = callback_urls_outcome(
            form(OrderResultURL="http://192.0.2.10:8123/payment/ecpay/website_return"), BASES)
        self.assertEqual(outcome.details["urls"]["OrderResultURL"]["kind"], "ha")
        self.assertEqual(outcome.result, "1 callback URL off the Canonical URL")

    def test_plain_http_on_the_public_host_is_not_enough_for_ecpay(self) -> None:
        plain = {name: url.replace("https:", "http:") for name, url in form().items()}
        outcome = callback_urls_outcome(plain, Bases(public="http://odoo.example.com"))
        self.assertEqual(outcome.details["urls"]["ReturnURL"]["kind"], "not-https")
        self.assertEqual(outcome.result, "4 callback URLs off the Canonical URL")

    def test_a_form_without_return_url_has_no_callback_to_judge(self) -> None:
        fields = form()
        del fields["ReturnURL"]
        outcome = callback_urls_outcome(fields, BASES)
        self.assertFalse(outcome.available)
        self.assertEqual(outcome.result, "no ReturnURL in the redirect form")

    def test_fields_that_are_not_urls_stay_out_of_the_evidence(self) -> None:
        outcome = callback_urls_outcome(form(), BASES)
        self.assertEqual(sorted(outcome.details["urls"]),
                         ["ClientBackURL", "OrderResultURL", "PaymentInfoURL", "ReturnURL"])


ACCESS_OK = ('172.30.33.0 - - [27/Sep/2026:10:12:51 +0800] "POST /payment/ecpay/result_notify HTTP/1.1" '
             '200 4 "-" "Mozilla/4.0" xfo="-" up')
ACCESS_OTHER = ('172.30.33.0 - - [27/Sep/2026:10:15:03 +0800] "POST /web/dataset/call_kw HTTP/1.1" '
                '200 43 "-" "Mozilla/5.0" xfo="-" up')
# The add-on log as Odoo writes it: a dict payload runs over several lines.
RENDERING = """2026-09-27 02:04:00,558 506 INFO example_db odoo.addons.payment.models.payment_transaction: provider-specific rendering values for transaction with reference S00022:
{'api_url': 'https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5',
 'parameters': {'CheckMacValue': 'ABCDEF',
                'ClientBackURL': 'https://odoo.example.com/payment/ecpay/website_return',
                'CustomField1': 'S00022',
                'OrderResultURL': 'https://odoo.example.com/payment/ecpay/website_return',
                'PaymentInfoURL': 'https://odoo.example.com/payment/ecpay/info_notify',
                'ReturnURL': 'https://odoo.example.com/payment/ecpay/result_notify',
                'TotalAmount': 100}}
2026-09-27 02:04:00,568 506 INFO example_db werkzeug: 172.30.33.0 - - "POST /shop/payment/transaction/22 HTTP/1.1" 200 -
""".splitlines()
RECEIVED = """2026-09-27 02:12:51,451 506 INFO example_db odoo.addons.payment_ecpay.controllers.main: ECPay payment notification received: {'CheckMacValue': 'ABCDEF',
 'CustomField1': 'S00022',
 'PaymentType': 'Credit_CreditCard',
 'RtnCode': '1',
 'RtnMsg': 'OK',
 'SimulatePaid': '0',
 'TradeAmt': '100'}
""".splitlines()
OTHER_ORDER = [line.replace("S00022", "S00021").replace("'RtnCode': '1'", "'RtnCode': '10100284'")
               for line in RECEIVED]
MAC_FAILED = ["2026-09-27 02:12:51,500 57 WARNING example_db odoo.addons.payment_ecpay.controllers.main: "
              "ECPay CheckMacValue verification failed"]
RETURN = ["2026-09-27 02:12:52,325 504 INFO example_db odoo.addons.payment_ecpay.controllers.main: "
          "ECPay customer return, post data: {'CustomField1': 'S00022',", " 'RtnCode': '1'}"]


class LogEntryTests(unittest.TestCase):
    def test_continuation_lines_belong_to_the_entry_above(self) -> None:
        entries = log_entries(RENDERING)
        self.assertEqual(len(entries), 2)
        self.assertIn("'ReturnURL'", entries[0])

    def test_the_rendered_redirect_form_is_found_by_its_reference(self) -> None:
        urls = rendering_urls(RENDERING, "S00022")
        self.assertEqual(urls["ReturnURL"], "https://odoo.example.com/payment/ecpay/result_notify")
        self.assertEqual(sorted(urls), ["ClientBackURL", "OrderResultURL", "PaymentInfoURL", "ReturnURL"])

    def test_another_reference_has_no_rendered_form(self) -> None:
        self.assertEqual(rendering_urls(RENDERING, "S00099"), {})


class CallbackLogTests(unittest.TestCase):
    def test_the_callback_post_and_this_orders_notification_are_counted(self) -> None:
        hits = callback_hits(RECEIVED + RETURN, [ACCESS_OTHER, ACCESS_OK], "S00022")
        self.assertEqual(hits, {"result_notify_posts": [200], "mac_failures": 0, "customer_returns": 1,
                                "notifications": [{"rtn_code": "1", "payment_type": "Credit_CreditCard",
                                                   "simulated": False}]})

    def test_nothing_secret_of_the_payload_is_kept(self) -> None:
        self.assertNotIn("ABCDEF", str(callback_hits(RECEIVED, [ACCESS_OK], "S00022")))

    def test_another_orders_notification_does_not_count(self) -> None:
        hits = callback_hits(OTHER_ORDER, [ACCESS_OK], "S00022")
        self.assertEqual(hits["notifications"], [])

    def test_a_notification_from_a_simulated_payment_says_so(self) -> None:
        simulated = [line.replace("'SimulatePaid': '0'", "'SimulatePaid': '1'") for line in RECEIVED]
        hits = callback_hits(simulated, [ACCESS_OK], "S00022")
        self.assertTrue(hits["notifications"][0]["simulated"])

    def test_a_callback_with_a_good_mac_and_a_done_transaction_passes(self) -> None:
        outcome = callback_outcome(callback_hits(RECEIVED, [ACCESS_OK], "S00022"), {"state": "done"})
        self.assertTrue(outcome.available)
        self.assertEqual(outcome.result, "callback reached the Public origin; transaction done")

    def test_no_callback_in_the_log_is_its_own_result(self) -> None:
        outcome = callback_outcome(callback_hits([], [ACCESS_OTHER], "S00022"), {"state": "pending"})
        self.assertEqual(outcome.result, "no callback in the add-on log; transaction pending")

    def test_log_entries_from_before_the_transaction_was_rendered_do_not_count(self) -> None:
        earlier_failure = [line.replace("02:12:51,500", "01:00:00,000") for line in MAC_FAILED]
        earlier_post = ACCESS_OK.replace("10:12:51", "09:00:00")
        hits = callback_hits(earlier_failure + RENDERING + RECEIVED, [earlier_post, ACCESS_OK], "S00022")
        self.assertEqual((hits["mac_failures"], hits["result_notify_posts"]), (0, [200]))

    def test_a_post_before_the_rendering_is_not_this_transactions_callback(self) -> None:
        earlier_post = ACCESS_OK.replace("10:12:51", "09:00:00")
        hits = callback_hits(RENDERING + RECEIVED, [earlier_post], "S00022")
        self.assertEqual(hits["result_notify_posts"], [])

    def test_a_callback_whose_mac_failed_does_not_pass(self) -> None:
        outcome = callback_outcome(callback_hits(RECEIVED + MAC_FAILED, [ACCESS_OK], "S00022"), {"state": "pending"})
        self.assertEqual(outcome.result, "callback arrived but its CheckMacValue failed; transaction pending")

    def test_a_callback_that_arrived_but_left_the_transaction_open_does_not_pass(self) -> None:
        outcome = callback_outcome(callback_hits(RECEIVED, [ACCESS_OK], "S00022"), {"state": "error"})
        self.assertEqual(outcome.result, "callback arrived; transaction error")

    def test_a_simulated_payment_is_not_the_card_payment_the_run_asks_for(self) -> None:
        simulated = [line.replace("'SimulatePaid': '0'", "'SimulatePaid': '1'") for line in RECEIVED]
        outcome = callback_outcome(callback_hits(simulated, [ACCESS_OK], "S00022"), {"state": "done"})
        self.assertEqual(outcome.result, "callback reached the Public origin; simulated payment")


def move(**overrides):
    record = {"id": 9, "name": "INV/2026/00002", "state": "posted", "uniform_state": "invoiced",
              "ecpay_invoice_id": [3, "GS20004636"], "amount_total": 100.0}
    record.update(overrides)
    return record


class EinvoiceTests(unittest.TestCase):
    def test_a_posted_invoice_with_an_ecpay_number_is_issued(self) -> None:
        outcome = einvoice_outcome(move())
        self.assertTrue(outcome.available)
        self.assertEqual(outcome.result, "e-invoice issued")
        self.assertEqual(outcome.details["uniform_invoice"], "GS20004636")

    def test_an_invoice_still_to_invoice_is_not_issued(self) -> None:
        outcome = einvoice_outcome(move(uniform_state="to invoice", ecpay_invoice_id=False))
        self.assertEqual(outcome.result, "e-invoice not issued (to invoice)")

    def test_a_number_that_is_not_a_taiwan_uniform_invoice_number_does_not_count(self) -> None:
        outcome = einvoice_outcome(move(ecpay_invoice_id=[3, "pending"]))
        self.assertEqual(outcome.result, "e-invoice number is not a uniform invoice number")

    def test_the_form_must_show_the_issued_number(self) -> None:
        self.assertEqual(einvoice_outcome(move(), shown="GS20004636").result, "e-invoice issued")
        self.assertEqual(einvoice_outcome(move(), shown="").result, "e-invoice number not shown on the invoice form")

    def test_no_invoice_at_all(self) -> None:
        outcome = einvoice_outcome(None)
        self.assertFalse(outcome.available)
        self.assertEqual(outcome.result, "no posted invoice for the order")


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.urls = callback_urls_outcome(form(), BASES)
        self.callback = callback_outcome(callback_hits(RECEIVED, [ACCESS_OK], "S00022"), {"state": "done"})
        issued = einvoice_outcome(move(), shown="GS20004636")
        same = Outcome(True, "form opens; MerchantID shown")
        self.records = ecpay_records(RUN, self.urls, self.callback, [
            ("ECPay provider form", same, same),
            ("ECPay e-invoice on the invoice form", issued, issued)])

    def by_screen(self, records=None):
        return {record["screen"]["name"]: record for record in records or self.records}

    def test_the_inbound_parts_are_structural_and_name_their_public_path(self) -> None:
        for screen in ("ECPay callback and return URLs", "ECPay stage payment callback"):
            record = self.by_screen()[screen]
            self.assertEqual(record["verdict"], "STRUCTURAL", screen)
            self.assertEqual(record["public_path"], "/payment/ecpay/result_notify")
            self.assertEqual(record["item"], "U-E6")
            self.assertIsNone(record["ingress"])

    def test_a_structural_record_whose_public_side_failed_is_a_gap(self) -> None:
        failed = callback_outcome(callback_hits([], [], "S00022"), {"state": "pending"})
        record = self.by_screen(ecpay_records(RUN, self.urls, failed, []))["ECPay stage payment callback"]
        self.assertEqual(record["verdict"], "GAP")
        self.assertEqual(record["severity"], "blocker")

    def test_the_e_invoice_is_back_office_and_judged_on_both_surfaces(self) -> None:
        record = self.by_screen()["ECPay e-invoice on the invoice form"]
        self.assertEqual(record["verdict"], "PARITY")
        self.assertEqual(record["ingress"]["result"], "e-invoice issued")

    def test_back_office_screens_are_judged_on_both_surfaces(self) -> None:
        record = self.by_screen()["ECPay provider form"]
        self.assertEqual(record["verdict"], "PARITY")


if __name__ == "__main__":
    unittest.main()
