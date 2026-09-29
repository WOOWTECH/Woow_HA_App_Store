#!/usr/bin/env python3
"""Static-tier tests for the pure parts of the menu/action crawler adapter.

Nothing here opens a browser, a websocket or reads credentials.
"""
import json
import unittest

from e2e_menu_action_adapter import (
    EVIDENCE_SCHEMA,
    Masker,
    RunInfo,
    SurfaceObservation,
    addon_info_command,
    auth_message,
    count_signals,
    diff_runs,
    evidence_record,
    ingress_prefix_from_info,
    ingress_session_command,
    is_prefix_escape,
    parse_env_file,
    parse_viewport,
    plan_visits,
    read_records,
    scope_from_web_menus,
    skipped_record,
    url_literal_violation,
    validate_session_command,
    verdict_lines,
    websocket_url,
    ws_result,
)
from e2e_menu_action_crawler import (
    ActionRecord,
    Manifest,
    MenuRecord,
    NON_MUTATING_OPERATIONS,
    Surface,
)

HA = "http://ha.example:8123"
PREFIX = "/api/hassio_ingress/tok_ABC123"


def web_menus() -> dict:
    """The shape of Odoo's /web/webclient/load_menus response."""
    return {
        "root": {"id": "root", "name": "root", "children": [1, 10, 20]},
        1: {"id": 1, "name": "Contacts", "xmlid": "contacts.menu_contacts", "children": [2, 3],
            "actionModel": "ir.actions.act_window", "actionID": 100},
        2: {"id": 2, "name": "Contacts", "xmlid": "contacts.res_partner_menu_contacts", "children": [],
            "actionModel": "ir.actions.act_window", "actionID": 100},
        3: {"id": 3, "name": "Configuration", "xmlid": "contacts.res_partner_menu_config", "children": [4, 5],
            "actionModel": False, "actionID": False},
        4: {"id": 4, "name": "Tags", "xmlid": "contacts.menu_partner_category_form", "children": [],
            "actionModel": "ir.actions.act_window", "actionID": 101},
        5: {"id": 5, "name": "Merge", "xmlid": "contacts.menu_server_merge", "children": [],
            "actionModel": "ir.actions.server", "actionID": 102},
        10: {"id": 10, "name": "Project", "xmlid": "project.menu_main_pm", "children": [11],
             "actionModel": "ir.actions.client", "actionID": 200},
        11: {"id": 11, "name": "Deep", "xmlid": "project.deep1", "children": [12],
             "actionModel": False, "actionID": False},
        12: {"id": 12, "name": "Deeper", "xmlid": "project.deep2", "children": [13],
             "actionModel": False, "actionID": False},
        13: {"id": 13, "name": "Deepest", "xmlid": "project.deep3", "children": [14],
             "actionModel": "ir.actions.act_window", "actionID": 201},
        14: {"id": 14, "name": "Too deep", "xmlid": "project.deep4", "children": [],
             "actionModel": "ir.actions.act_window", "actionID": 202},
        20: {"id": 20, "name": "Sales", "xmlid": "sale.sale_menu_root", "children": [],
             "actionModel": "ir.actions.act_window", "actionID": 300},
    }


class ScopeAndPlanTests(unittest.TestCase):
    def test_scope_keeps_only_the_chosen_apps(self) -> None:
        scope = scope_from_web_menus(web_menus(), ["contacts"])
        self.assertEqual(
            {menu.id for menu in scope.manifest.menus},
            {"contacts.menu_contacts", "contacts.res_partner_menu_contacts",
             "contacts.res_partner_menu_config", "contacts.menu_partner_category_form",
             "contacts.menu_server_merge"},
        )
        self.assertEqual(scope.apps, {"contacts.menu_contacts": "contacts"})

    def test_unknown_app_is_a_harness_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "crawler configuration"):
            scope_from_web_menus(web_menus(), ["contacts", "hr"])

    def test_plan_visits_every_read_only_action_up_to_depth_three(self) -> None:
        scope = scope_from_web_menus(web_menus(), ["contacts", "project"])
        visits = plan_visits(scope)
        self.assertEqual(
            [(visit.menu_id, visit.route, visit.depth) for visit in visits],
            [
                ("contacts.menu_contacts", "/odoo/action-100", 0),
                ("contacts.res_partner_menu_contacts", "/odoo/action-100", 1),
                ("contacts.menu_partner_category_form", "/odoo/action-101", 2),
                ("project.menu_main_pm", "/odoo/action-200", 0),
                ("project.deep3", "/odoo/action-201", 3),
            ],
        )
        self.assertTrue(all(visit.operations <= NON_MUTATING_OPERATIONS for visit in visits))

    def test_a_server_action_is_skipped_never_planned(self) -> None:
        scope = scope_from_web_menus(web_menus(), ["contacts"])
        self.assertEqual(
            [(item.menu_id, item.action_ref) for item in scope.skipped],
            [("contacts.menu_server_merge", "ir.actions.server,102")],
        )
        self.assertNotIn("/odoo/action-102", [visit.route for visit in plan_visits(scope)])

    def test_a_manifest_with_a_writing_action_cannot_be_planned(self) -> None:
        scope = scope_from_web_menus(web_menus(), ["contacts"])
        tampered = Manifest(
            menus=(MenuRecord("m", "M", action_id="a"),),
            actions=(ActionRecord("a", "A", "/odoo/action-9", action_type="server"),),
        )
        with self.assertRaises(PermissionError):
            plan_visits(scope._replace(manifest=tampered))

    def test_control_identity_is_surface_independent(self) -> None:
        scope = scope_from_web_menus(web_menus(), ["contacts"])
        visit = plan_visits(scope)[0]
        self.assertEqual(
            scope.identity(visit),
            "menu:contacts.menu_contacts|ir.actions.act_window:100",
        )


class EnvFileTests(unittest.TestCase):
    def test_env_file_fills_only_unset_names(self) -> None:
        environ = {"KEEP": "from-shell"}
        parse_env_file([
            "# comment", "", "export A=1", "B = two words ", "C='quoted'", 'D="dq"',
            "KEEP=from-file", "E=", "not a pair",
        ], environ)
        self.assertEqual(environ, {"KEEP": "from-shell", "A": "1", "B": "two words", "C": "quoted", "D": "dq", "E": ""})


class WebsocketMessageTests(unittest.TestCase):
    def test_websocket_url_follows_the_scheme(self) -> None:
        self.assertEqual(websocket_url("http://ha.example:8123/"), "ws://ha.example:8123/api/websocket")
        self.assertEqual(websocket_url("https://ha.example"), "wss://ha.example/api/websocket")

    def test_messages_use_the_supervisor_api_route(self) -> None:
        self.assertEqual(auth_message("t"), {"type": "auth", "access_token": "t"})
        self.assertEqual(
            ingress_session_command(3),
            {"id": 3, "type": "supervisor/api", "endpoint": "/ingress/session", "method": "post"},
        )
        self.assertEqual(
            validate_session_command(4, "s"),
            {"id": 4, "type": "supervisor/api", "endpoint": "/ingress/validate_session",
             "method": "post", "data": {"session": "s"}},
        )
        self.assertEqual(
            addon_info_command(5, "local_odoo18ce"),
            {"id": 5, "type": "supervisor/api", "endpoint": "/addons/local_odoo18ce/info", "method": "get"},
        )
        with self.assertRaises(ValueError):
            addon_info_command(6, "../core")

    def test_results_are_matched_by_id_and_failures_raise(self) -> None:
        self.assertEqual(ws_result({"id": 3, "type": "result", "success": True, "result": {"session": "s"}}, 3),
                         {"session": "s"})
        self.assertIsNone(ws_result({"id": 2, "type": "result", "success": True, "result": {}}, 3))
        with self.assertRaisesRegex(RuntimeError, "unauthorized"):
            ws_result({"id": 3, "type": "result", "success": False,
                       "error": {"code": "unauthorized", "message": "Unauthorized"}}, 3)

    def test_ingress_prefix_is_validated(self) -> None:
        self.assertEqual(ingress_prefix_from_info({"ingress_entry": PREFIX}), PREFIX)
        for bad in ({}, {"ingress_entry": "/elsewhere"}, {"ingress_entry": PREFIX + "/../x"}):
            with self.assertRaises(ValueError):
                ingress_prefix_from_info(bad)


class MaskingTests(unittest.TestCase):
    def masker(self) -> Masker:
        return Masker(
            bases={"<PUBLIC_BASE>": "https://odoo.example", "<HA_BASE>": HA},
            ingress_prefix=PREFIX,
            secrets=("tester@example.com", "hunter2", "llat-secret", "sess-secret"),
        )

    def test_urls_become_base_codes_and_logical_paths(self) -> None:
        masker = self.masker()
        self.assertEqual(masker.text(HA + PREFIX + "/odoo/contacts?debug=1"), "<INGRESS_BASE>/odoo/contacts?<redacted>")
        self.assertEqual(masker.text("https://odoo.example/odoo/action-5"), "<PUBLIC_BASE>/odoo/action-5")
        self.assertEqual(masker.text(PREFIX + "/web/login"), "<INGRESS_PREFIX>/web/login")
        self.assertEqual(masker.text(HA + "/lovelace"), "<HA_BASE>/lovelace")

    def test_masking_twice_changes_nothing(self) -> None:
        masker = self.masker()
        once = masker.text("https://odoo.example/web/image/x?unique=1")
        self.assertEqual(once, "<PUBLIC_BASE>/web/image/x?<redacted>")
        self.assertEqual(masker.text(once), once)
        self.assertEqual(masker.value({"u": once}), {"u": once})

    def test_credentials_and_foreign_ingress_tokens_never_survive(self) -> None:
        masked = self.masker().value({
            "message": "login tester@example.com hunter2 failed with llat-secret on /api/hassio_ingress/other_tok/web",
            "nested": ["cookie sess-secret"],
            "password": "anything",
        })
        text = json.dumps(masked)
        for secret in ("tester@example.com", "hunter2", "llat-secret", "sess-secret", "other_tok", "anything", "tok_ABC123"):
            self.assertNotIn(secret, text)


class SignalTests(unittest.TestCase):
    def test_prefix_escape_on_ingress_is_a_same_origin_request_outside_the_prefix(self) -> None:
        check = lambda url: is_prefix_escape(url, Surface.HA_INGRESS, HA, PREFIX)
        self.assertFalse(check(HA + PREFIX + "/odoo/contacts"))
        self.assertFalse(check(HA + PREFIX))
        self.assertTrue(check(HA + "/odoo/contacts"))
        self.assertTrue(check(HA + PREFIX + "x/odoo"))
        self.assertTrue(check(HA + PREFIX + PREFIX + "/odoo"), "a doubled prefix is U-A2")
        self.assertTrue(check("ws://ha.example:8123/websocket"))
        self.assertFalse(check("https://fonts.example/x.woff"))
        self.assertFalse(check("data:image/png;base64,AAAA"))

    def test_prefix_escape_on_public_is_any_ingress_path(self) -> None:
        check = lambda url: is_prefix_escape(url, Surface.PUBLIC, "https://odoo.example", None)
        self.assertFalse(check("https://odoo.example/odoo/contacts"))
        self.assertTrue(check("https://odoo.example/api/hassio_ingress/t/odoo"))

    def test_url_literal_violations_follow_u_c5(self) -> None:
        self.assertIsNone(url_literal_violation("https://odoo.example/my/orders/4", HA))
        self.assertIsNone(url_literal_violation("/odoo/contacts", HA))
        self.assertIsNone(url_literal_violation(PREFIX + "/odoo/contacts", HA))
        self.assertIsNone(url_literal_violation("https://www.odoo.com/documentation", HA))
        self.assertEqual(url_literal_violation("http://127.0.0.1:8069/web", HA), "loopback")
        self.assertEqual(url_literal_violation("http://localhost/web", HA), "loopback")
        self.assertEqual(url_literal_violation(HA + "/odoo", HA), "ha_origin")
        self.assertEqual(url_literal_violation("https://x.example" + PREFIX + "/odoo", HA), "ingress_token")

    def test_signals_count_the_five_kinds(self) -> None:
        signals = count_signals(
            page_errors=["boom"],
            console=[("error", "x"), ("warning", "y"), ("error", "z")],
            failed_requests=["a"],
            responses=[(200, "u"), (404, "v"), (500, "w")],
            urls=[HA + PREFIX + "/odoo", HA + "/auth"],
            surface=Surface.HA_INGRESS, origin=HA, ingress_prefix=PREFIX,
        )
        self.assertEqual(signals, {
            "pageerror": 1, "console_error": 2, "failed_requests": 1,
            "http_4xx_5xx": 2, "route_escape": 1,
        })


ZERO = {"pageerror": 0, "console_error": 0, "failed_requests": 0, "http_4xx_5xx": 0, "route_escape": 0}
RUN = RunInfo(run_id="WOOW-PARITY-20260924T000000Z", target="local", database="example_db")


def observation(**overrides) -> SurfaceObservation:
    values = dict(available=True, result="loaded", signals=dict(ZERO), route="/odoo/action-100",
                  model="res.partner", view="kanban", url_literals=(), url_violations=())
    values.update(overrides)
    return SurfaceObservation(**values)


def record(surface: Surface, identity: str = "menu:contacts.menu_contacts|ir.actions.act_window:100", **overrides) -> dict:
    return evidence_record(RUN, surface, module="contacts", identity=identity, observation=observation(**overrides))


class EvidenceAndDiffTests(unittest.TestCase):
    def test_evidence_record_has_the_v1_shape_with_one_surface(self) -> None:
        item = record(Surface.HA_INGRESS)
        self.assertEqual(item["schema"], EVIDENCE_SCHEMA)
        self.assertEqual(EVIDENCE_SCHEMA, "odoo-parity-evidence/v1")
        self.assertEqual(item["item"], "U-C12")
        self.assertEqual(item["layer"], "L3")
        self.assertEqual(item["screen"], {"route": "/odoo/action-100", "model": "res.partner", "view": "kanban"})
        self.assertIn("ingress", item)
        self.assertNotIn("public", item)
        self.assertEqual(item["ingress"]["signals"], ZERO)
        self.assertIsNone(item["verdict"])
        json.dumps(item)

    def test_a_u_c5_violation_adds_its_root_cause(self) -> None:
        self.assertEqual(record(Surface.PUBLIC)["root_cause"], ["RC-1"])
        violated = record(Surface.PUBLIC, url_violations=({"literal": "x", "reason": "loopback"},))
        self.assertEqual(violated["root_cause"], ["RC-1", "RC-9"])

    def test_identical_clean_runs_are_parity(self) -> None:
        merged = diff_runs([record(Surface.PUBLIC)], [record(Surface.HA_INGRESS)])
        self.assertEqual([(item["verdict"], item["severity"]) for item in merged], [("PARITY", "none")])
        self.assertIn("public", merged[0])
        self.assertIn("ingress", merged[0])

    def test_each_difference_is_a_gap_with_a_reason(self) -> None:
        cases = {
            "signal": (observation(), observation(signals=dict(ZERO, console_error=1)), "important", "ingress console_error=1"),
            "escape": (observation(), observation(signals=dict(ZERO, route_escape=2)), "blocker", "ingress route_escape=2"),
            "view": (observation(), observation(view="list"), "important", "view: public=kanban ingress=list"),
            "route": (observation(), observation(route="/odoo/discuss"), "important", "route: public=/odoo/action-100 ingress=/odoo/discuss"),
            "literal": (observation(), observation(url_violations=({"literal": "<HA_BASE>/odoo", "reason": "ha_origin"},)),
                        "blocker", "ingress U-C5 ha_origin: <HA_BASE>/odoo"),
            "baseline": (observation(signals=dict(ZERO, http_4xx_5xx=1)), observation(), "important", "public http_4xx_5xx=1"),
            "5xx": (observation(), observation(signals=dict(ZERO, http_4xx_5xx=1), http_5xx=1), "blocker", "ingress http_4xx_5xx=1"),
            "literals": (observation(url_literals=("<PUBLIC_BASE>/my/orders/4", "/odoo/contacts")),
                         observation(url_literals=("<INGRESS_PREFIX>/odoo/contacts",)),
                         "important", "URL literals only on public: /my/orders/4"),
            "unavailable": (observation(), observation(available=False, result="error: timeout"), "blocker", "ingress unavailable: error: timeout"),
        }
        for name, (public, ingress, severity, note) in cases.items():
            with self.subTest(name):
                ident = "menu:x|ir.actions.act_window:1"
                merged = diff_runs(
                    [evidence_record(RUN, Surface.PUBLIC, module="contacts", identity=ident, observation=public)],
                    [evidence_record(RUN, Surface.HA_INGRESS, module="contacts", identity=ident, observation=ingress)],
                )
                self.assertEqual(merged[0]["verdict"], "GAP")
                self.assertEqual(merged[0]["severity"], severity)
                self.assertIn(note, merged[0]["notes"])

    def test_literals_compare_by_path_whatever_base_each_surface_writes(self) -> None:
        merged = diff_runs(
            [record(Surface.PUBLIC, url_literals=("<PUBLIC_BASE>/web/image/res.partner/3/avatar_128?<redacted>",))],
            [record(Surface.HA_INGRESS, url_literals=("<INGRESS_PREFIX>/web/image/res.partner/3/avatar_128?<redacted>",))],
        )
        self.assertEqual(merged[0]["verdict"], "PARITY", merged[0]["notes"])

    def test_an_action_seen_on_one_surface_only_is_a_gap(self) -> None:
        merged = diff_runs([record(Surface.PUBLIC, identity="menu:a|x:1")], [record(Surface.HA_INGRESS, identity="menu:b|x:2")])
        self.assertEqual([(item["control_identity"], item["verdict"]) for item in merged],
                         [("menu:a|x:1", "GAP"), ("menu:b|x:2", "GAP")])
        self.assertIn("absent on ingress", merged[0]["notes"])
        self.assertIn("absent on public", merged[1]["notes"])

    def test_duplicate_identities_are_ambiguous(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            diff_runs([record(Surface.PUBLIC), record(Surface.PUBLIC)], [record(Surface.HA_INGRESS)])

    def test_runs_must_come_from_their_own_surface(self) -> None:
        with self.assertRaisesRegex(ValueError, "surface"):
            diff_runs([record(Surface.HA_INGRESS)], [record(Surface.HA_INGRESS)])

    def test_skipped_menus_are_reported_not_judged(self) -> None:
        skip = lambda surface: skipped_record(RUN, surface, module="contacts",
                                              identity="menu:m|ir.actions.server:102", reason="server action may write")
        merged = diff_runs([record(Surface.PUBLIC), skip(Surface.PUBLIC)], [record(Surface.HA_INGRESS), skip(Surface.HA_INGRESS)])
        lines = verdict_lines(merged)
        self.assertEqual(lines, [
            "PARITY menu:contacts.menu_contacts|ir.actions.act_window:100",
            "SKIPPED menu:m|ir.actions.server:102: server action may write",
        ])

    def test_gap_lines_carry_their_notes(self) -> None:
        merged = diff_runs([record(Surface.PUBLIC)], [record(Surface.HA_INGRESS, view="list")])
        self.assertEqual(verdict_lines(merged),
                         ["GAP menu:contacts.menu_contacts|ir.actions.act_window:100: view: public=kanban ingress=list"])

    def test_read_records_rejects_foreign_schemas(self) -> None:
        good = json.dumps(record(Surface.PUBLIC))
        self.assertEqual(len(read_records([good, ""])), 1)
        with self.assertRaisesRegex(ValueError, "schema"):
            read_records([json.dumps({"schema": "other/v1"})])


class ViewportTests(unittest.TestCase):
    def test_the_default_client_is_the_desktop_baseline(self) -> None:
        self.assertEqual(record(Surface.PUBLIC)["client"], "desktop-chrome-1920x1080")

    def test_a_small_viewport_is_labelled_as_mobile_layout_emulation(self) -> None:
        self.assertEqual(parse_viewport("390x844"), ((390, 844), "mobile-emulation-chrome-390x844"))
        self.assertEqual(parse_viewport("1920x1080"), ((1920, 1080), "desktop-chrome-1920x1080"))

    def test_the_run_carries_its_client_into_every_record(self) -> None:
        run = RunInfo(run_id=RUN.run_id, target="local", database="example_db",
                      client="mobile-emulation-chrome-390x844")
        item = evidence_record(run, Surface.PUBLIC, module="contacts", identity="i", observation=observation())
        self.assertEqual(item["client"], "mobile-emulation-chrome-390x844")

    def test_a_malformed_viewport_is_refused(self) -> None:
        for bad in ("390", "x844", "0x844", "390x844x2", "abc"):
            with self.assertRaises(ValueError, msg=bad):
                parse_viewport(bad)


if __name__ == "__main__":
    unittest.main()
