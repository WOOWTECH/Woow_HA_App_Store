#!/usr/bin/env python3
"""Static-tier tests for the pure parts of the menu/action crawler adapter.

Nothing here opens a browser, a websocket or reads credentials.
"""
import contextlib
import itertools
import json
import unittest
from unittest import mock
from urllib.parse import urlsplit

from e2e_menu_action_adapter import (
    EVIDENCE_SCHEMA,
    GET_WRITING_ROUTES,
    _is_cart_update,
    _reached,
    WRITE_DATABASE,
    get_writing_route,
    is_configuration_error,
    session_database,
    Masker,
    OpenTarget,
    RunInfo,
    SurfaceDriver,
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
    parse_targets,
    parse_viewport,
    plan_visits,
    read_records,
    require_write_database,
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
    Operation,
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


class OpenTargetTests(unittest.TestCase):
    """`open` judges screens the menu crawler cannot reach (#163)."""

    def test_a_target_is_an_action_xmlid_or_a_route(self) -> None:
        action = OpenTarget(module="project_todo", target="project_todo.project_task_action_todo")
        self.assertTrue(action.is_action)
        self.assertEqual(action.route, "/odoo/action-project_todo.project_task_action_todo")
        self.assertTrue(action.backend)
        route = OpenTarget(module="ecpay_invoice_website", target="/shop/checkout")
        self.assertFalse(route.is_action)
        self.assertEqual(route.route, "/shop/checkout")
        self.assertFalse(route.backend)
        self.assertTrue(OpenTarget(module="m", target="/odoo/action-1?view_type=list").backend)

    def test_identity_is_the_target_itself_so_both_surfaces_join(self) -> None:
        # The identity must not carry the Ingress prefix, an origin or a record
        # of which surface opened it, or `diff` could not join the two runs.
        self.assertEqual(
            OpenTarget(module="project_todo", target="project_todo.project_task_action_todo").identity,
            "open:action:project_todo.project_task_action_todo",
        )
        # A query survives into the identity, but not as a query: masking
        # redacts everything after a `?`, and two targets that differ only
        # there would collapse into one ambiguous identity.
        self.assertEqual(
            OpenTarget(module="sale_management", target="/odoo/action-x?view_type=list").identity,
            "open:route:/odoo/action-x;view_type=list",
        )

    def test_parse_targets_reads_one_object_per_line(self) -> None:
        targets = parse_targets([
            "# the To-do views, opened without running the server action",
            "",
            '{"module": "project_todo", "target": "project_todo.project_task_action_todo",'
            ' "label": "To-do kanban", "expect_model": "project.task"}',
            '{"module": "ecpay_invoice_website", "target": "/shop/checkout",'
            ' "expect_selector": ".o_ecpay_einvoice", "cart": "/shop/product/desk-1"}',
        ])
        self.assertEqual([(item.module, item.target) for item in targets], [
            ("project_todo", "project_todo.project_task_action_todo"),
            ("ecpay_invoice_website", "/shop/checkout"),
        ])
        self.assertEqual(
            [item.target for item in parse_targets([
                '{"module": "m", "target": "/odoo/action-1?view_type=list", "expect_model": "m.m"}'])],
            ["/odoo/action-1?view_type=list"], "the view chooser is the one query a target may carry")
        self.assertEqual(targets[0].label, "To-do kanban")
        self.assertEqual(targets[0].expect_model, "project.task")
        self.assertIsNone(targets[0].cart)
        self.assertEqual(targets[1].cart, "/shop/product/desk-1")

    def test_a_malformed_target_is_a_configuration_error(self) -> None:
        cases = {
            "not json": ["nope"],
            "not an object": ['["project_todo"]'],
            "unknown field": ['{"module": "m", "target": "/shop", "expect_selector": "#x", "surface": "public"}'],
            "no target": ['{"module": "m", "expect_selector": "#x"}'],
            "no module": ['{"target": "/shop", "expect_selector": "#x"}'],
            "empty module": ['{"module": "", "target": "/shop", "expect_selector": "#x"}'],
            "not a string": ['{"module": "m", "target": 5, "expect_selector": "#x"}'],
            "nothing to check the screen by": ['{"module": "m", "target": "/shop"}'],
            "not an xmlid": ['{"module": "m", "target": "project_todo", "expect_model": "m.m"}'],
            "an origin": ['{"module": "m", "target": "https://odoo.example/shop", "expect_selector": "#x"}'],
            "traversal": ['{"module": "m", "target": "/shop/../../etc", "expect_selector": "#x"}'],
            "an ingress prefix": ['{"module": "m", "target": "%s/shop", "expect_selector": "#x"}' % PREFIX],
            "a semicolon, which the identity uses for a query":
                ['{"module": "m", "target": "/shop;a=1", "expect_selector": "#x"}'],
            "an expectation that says nothing":
                ['{"module": "m", "target": "/shop", "expect_selector": ""}'],
            "an empty second expectation":
                ['{"module": "m", "target": "/shop", "expect_selector": "#x", "expect_model": ""}'],
            "an expect_model on a website route":
                ['{"module": "m", "target": "/shop/payment", "expect_model": "sale.order"}'],
            "a fragment":
                ['{"module": "m", "target": "/my/orders/7#access_token=x", "expect_selector": "#x"}'],
            "a query that does not choose a view":
                ['{"module": "m", "target": "/odoo/action-1?db=other", "expect_model": "m.m"}'],
            "a cart with a query":
                ['{"module": "m", "target": "/shop", "expect_selector": "#x",'
                 ' "cart": "/shop/desk-1?add_qty=99"}'],
            "a cart that is not a route":
                ['{"module": "m", "target": "/shop", "expect_selector": "#x", "cart": "sale.order"}'],
            "duplicate": ['{"module": "m", "target": "/shop", "expect_selector": "#x"}',
                          '{"module": "other", "target": "/shop", "expect_selector": "#y"}'],
        }
        for name, lines in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, "crawler configuration"):
                    parse_targets(lines)

    def test_a_configuration_error_is_told_apart_from_evidence(self) -> None:
        # The run stops on a mistake of its own; a failure of the screen is
        # recorded instead, and the two must never be confused.
        self.assertTrue(is_configuration_error(ValueError("crawler configuration: target line 1 is empty")))
        self.assertTrue(is_configuration_error(RuntimeError("crawler configuration: a target fills a cart")))
        self.assertFalse(is_configuration_error(RuntimeError("the cart is still empty after adding /shop/x")))

    def test_a_cart_route_is_told_its_own_rule(self) -> None:
        with self.assertRaisesRegex(ValueError, "no query at all"):
            parse_targets(['{"module": "m", "target": "/shop", "expect_selector": "#x",'
                           ' "cart": "/shop/desk?add_qty=2"}'])
        with self.assertRaisesRegex(ValueError, "view_type"):
            parse_targets(['{"module": "m", "target": "/shop?add_qty=2", "expect_selector": "#x"}'])

    def test_a_run_that_cannot_name_its_database_does_not_run(self) -> None:
        # ODOO_DB is what the login asked for; only the session's answer is
        # what the run was really on, and there is no third answer.
        self.assertEqual(session_database("odoo_parity"), "odoo_parity")
        for missing in (None, ""):
            with self.assertRaisesRegex(RuntimeError, "did not report its database"):
                session_database(missing)

    def test_the_cart_write_is_refused_outside_the_parity_database(self) -> None:
        # The cart write is not an Operation on purpose: NON_MUTATING_OPERATIONS
        # is every member of that enum, so a WRITE member would be permitted by
        # the read-only policy instead of refused. ADR 0012 bounds it instead.
        self.assertEqual(WRITE_DATABASE, "odoo_parity")
        # `/shop` is the listing page: its controller writes nothing but the
        # session, so it is the reading half of this pair. A target that writes
        # on GET is the subject of the next test, not of this one.
        reading = parse_targets(['{"module": "m", "target": "/shop", "expect_selector": "#x"}'])
        writing = parse_targets(['{"module": "m", "target": "/shop", "expect_selector": "#x",'
                                 ' "cart": "/shop/product/desk-1"}'])
        require_write_database(reading, "odoo_test")
        require_write_database(reading, None)
        require_write_database(writing, WRITE_DATABASE)
        for unknown in ("odoo_test", None):
            # None is a session that did not say which database it is on; a run
            # that cannot say where it would write may not write.
            with self.assertRaisesRegex(RuntimeError, "odoo_parity"):
                require_write_database(writing, unknown)

    def test_a_route_that_writes_on_a_get_is_held_to_the_same_database(self) -> None:
        # `open` navigates with a plain GET, and Odoo's checkout writes while
        # rendering one, so a target naming such a route writes with no `cart:`
        # of its own. The bound is the cart's bound, and it is read off the
        # target list before any page is opened.
        checkout = parse_targets(['{"module": "m", "target": "/shop/checkout", "expect_selector": "#x"}'])
        for unknown in ("odoo_test", None):
            with self.assertRaisesRegex(RuntimeError, "/shop/checkout.*odoo_parity") as caught:
                require_write_database(checkout, unknown)
            self.assertTrue(is_configuration_error(caught.exception))
        # On the bound the same file runs, cart or no cart.
        require_write_database(checkout, WRITE_DATABASE)
        with_cart = parse_targets(['{"module": "m", "target": "/shop/checkout", "expect_selector": "#x",'
                                   ' "cart": "/shop/product/desk-1"}'])
        require_write_database(with_cart, WRITE_DATABASE)

    def test_the_guard_reads_a_target_list_it_can_only_walk_once(self) -> None:
        # The guard walks the targets twice -- once for a declared cart, once
        # for a writing route -- and it takes an `Iterable`, so a generator
        # would arrive empty at the second walk and permit the write.
        checkout = parse_targets(['{"module": "m", "target": "/shop/checkout", "expect_selector": "#x"}'])
        with self.assertRaisesRegex(RuntimeError, "/shop/checkout"):
            require_write_database((target for target in checkout), "odoo_test")

    def test_a_file_that_writes_both_ways_is_told_both(self) -> None:
        # Refusing one of them sends the operator back for another browser
        # launch and login, to be refused for the other.
        both = parse_targets([
            '{"module": "m", "target": "/shop", "expect_selector": "#x", "cart": "/shop/desk-1"}',
            '{"module": "m", "target": "/shop/confirm_order", "expect_selector": "#y"}',
        ])
        with self.assertRaises(RuntimeError) as caught:
            require_write_database(both, "odoo_test")
        self.assertIn("fills a cart", str(caught.exception))
        self.assertIn("/shop/confirm_order", str(caught.exception))
        self.assertIn(WRITE_DATABASE, str(caught.exception))

    def test_every_get_writing_route_is_named_with_where_its_write_was_read(self) -> None:
        # The list is the guard, so an entry with no citation is an entry nobody
        # can check against upstream `website_sale`.
        self.assertLessEqual({"/shop/checkout", "/shop/confirm_order", "/shop/address"},
                             set(GET_WRITING_ROUTES))
        # The list is not `website_sale`-only: a known GET write belongs on it
        # whichever module holds the route.
        self.assertIn("/my/orders/", GET_WRITING_ROUTES)
        for prefix, where in GET_WRITING_ROUTES.items():
            with self.subTest(prefix):
                # A prefix is matched against a target's path, so it has to be
                # one: no origin and no query. A trailing slash is allowed and
                # means "below this, not this" -- and is the only place one can
                # appear, since `get_writing_route` strips it off a path.
                self.assertEqual(prefix, urlsplit(prefix).path)
                self.assertTrue(prefix.startswith("/"))
                self.assertFalse(prefix.endswith("//"))
                self.assertTrue(where)

    def test_a_get_writing_route_is_matched_by_prefix_on_a_segment_boundary(self) -> None:
        # `/shop/payment/validate` is under `/shop/payment` and writes more than
        # it does; a route that only shares its characters is a different route.
        self.assertEqual(get_writing_route("/shop/payment/validate"), "/shop/payment/validate")
        self.assertEqual(get_writing_route("/shop/payment/anything_else"), "/shop/payment")
        self.assertEqual(get_writing_route("/shop/change_pricelist/3"), "/shop/change_pricelist")
        self.assertEqual(get_writing_route("/shop/checkout/"), "/shop/checkout")
        self.assertEqual(get_writing_route("/website/lang/fr_BE"), "/website/lang")
        # None means "not on this list", not "writes nothing": `/my/orders/<id>`
        # writes in `sale`, which this list does not cover -- see its comment.
        # A key ending in a slash bounds what is under it and not the path
        # itself: the order page writes, the order list page does not.
        self.assertEqual(get_writing_route("/my/orders/7"), "/my/orders/")
        self.assertIsNone(get_writing_route("/my/orders"))
        self.assertIsNone(get_writing_route("/my/orders/"))
        for outside in ("/shop", "/shop/cartons", "/shop/checkouts", "/my/home",
                        "/odoo/action-project_todo.project_task_action_todo"):
            with self.subTest(outside):
                self.assertIsNone(get_writing_route(outside))

    def test_a_get_writing_route_is_matched_as_odoo_routes_it(self) -> None:
        # `normalize_route` keeps percent-escapes and repeated slashes on
        # purpose, and werkzeug unquotes the path before matching, so a target
        # can spell a writing route in a way the literal prefix misses.
        for spelling in ("/shop/%63heckout", "/shop//checkout", "/shop/checkout%2F",
                         "/shop/%70ayment/validate",
                         # A language segment, which Odoo strips before routing:
                         # the ordinary spelling on a multilingual site.
                         "/zh_TW/shop/checkout", "/fr/shop/cart", "/en/website/lang/fr",
                         # A below-only prefix under a language segment: the
                         # stripped path is what has to be matched, and the
                         # trailing slash still has to reach the document page.
                         "/zh_TW/my/tasks/9", "/fr/my/invoices/overdue",
                         # Dot segments, which the browser resolves before it asks.
                         "/shop/./checkout", "/shop/x/../checkout", "/shop/%2e/checkout",
                         # A backslash, which the browser folds to a slash.
                         "/shop\\checkout", "/shop%5Ccheckout", "/shop\\checkout\\..\\checkout"):
            with self.subTest(spelling):
                self.assertIsNotNone(get_writing_route(spelling))
        # `//shop/checkout` never reaches here: `urlsplit` reads `//shop` as an
        # origin, and `parse_targets` refuses a target that carries one.
        with self.assertRaisesRegex(ValueError, "not a usable route"):
            parse_targets(['{"module": "m", "target": "//shop/checkout", "expect_selector": "#x"}'])

    def test_a_route_the_guard_cannot_read_is_refused_not_permitted(self) -> None:
        # `parse_targets` refuses both of these, so only a caller that skipped it
        # gets here -- and then a None would read as "this route is safe".
        for unreadable in ("shop/checkout", "//shop/checkout", "https://host/shop/checkout",
                           # A scheme with no authority: `urlsplit` leaves the
                           # path readable and the route is still not one.
                           "https:/my/orders/7", "mailto:/shop/checkout"):
            with self.subTest(unreadable):
                with self.assertRaisesRegex(ValueError, "crawler configuration"):
                    get_writing_route(unreadable)

    def test_the_longest_matching_prefix_is_the_one_reported(self) -> None:
        # Two entries can nest -- `/shop/payment` already reads as the wider one
        # over `/shop/payment/validate` -- and the narrower is what a reader
        # needs. Dict order must not decide it.
        wide, narrow = "/shop/payment", "/shop/payment/validate"
        for order in ((wide, narrow), (narrow, wide)):
            with self.subTest(order):
                with mock.patch.dict(
                    "e2e_menu_action_adapter.GET_WRITING_ROUTES",
                    {name: "cited" for name in order}, clear=True,
                ):
                    self.assertEqual(get_writing_route("/shop/payment/validate"), narrow)
                    self.assertEqual(get_writing_route("/shop/payment"), wide)

    def test_the_portal_routes_the_audit_read_a_write_on_are_bounded(self) -> None:
        # The portal audit this list records in its comment: one prefix per
        # write it read, and a route the audit read and found clean stays off.
        # A detail page's prefix ends in a slash, so the list page above it --
        # a parity path of its own, and a page the audit read as clean -- stays
        # open while every document under it is bounded.
        for route, prefix in (
            ("/my/orders/7", "/my/orders/"),
            ("/my/invoices/7", "/my/invoices/"),
            ("/my/purchase/7", "/my/purchase/"),
            ("/my/projects/7", "/my/projects/"),
            ("/my/projects/7/task/9", "/my/projects/"),
            ("/my/tasks/9", "/my/tasks/"),
            # The outdated spellings, which redirect into the two above --
            # `page.goto` follows a 30x, so the landing page's write is this
            # route's write.
            ("/my/project/7/task/9", "/my/project/"),
            ("/my/task/9", "/my/task/"),
            ("/mail/unfollow", "/mail/unfollow"),
            ("/digest/3/unsubscribe", "/digest/"),
            ("/digest/3/set_periodicity", "/digest/"),
            # The Discuss public pages, whose write a path alone reaches: no
            # query to bound it, unlike the rest of the deferred writes.
            ("/chat/tok_1", "/chat/"),
            ("/chat/tok_1/general", "/chat/"),
            ("/chat/7/tok_1", "/chat/"),
            ("/meet/tok_1", "/meet/"),
        ):
            with self.subTest(route):
                self.assertEqual(get_writing_route(route), prefix)
        # Read route by route and found clean: the portal list pages, the
        # account and security pages, the payment and donation forms, and the
        # rating pages, whose GET stopped writing in Odoo 18.
        for clean in ("/my", "/my/home", "/my/account", "/my/security",
                      "/my/orders", "/my/quotes", "/my/invoices", "/my/purchase", "/my/rfq",
                      "/my/projects", "/my/tasks", "/my/timesheets",
                      # Near misses of the two outdated prefixes: `/my/task/`
                      # must not reach `/my/tasks`, which writes nothing.
                      "/my/task", "/my/project",
                      "/terms", "/payment/pay", "/payment/confirmation", "/payment/status",
                      "/my/payment_method", "/donation/pay", "/rate/tok_1/5",
                      # The Discuss page that renders without the persona step,
                      # which is why `/discuss/` is not a key.
                      "/discuss/channel/7"):
            with self.subTest(clean):
                self.assertIsNone(get_writing_route(clean))

    def test_a_narrower_prefix_under_a_below_only_one_is_the_one_reported(self) -> None:
        # `/my/invoices/overdue` sits under `/my/invoices/`, which ends in a
        # slash, and writes something else -- it bumps a company sequence rather
        # than touching an invoice -- so it carries its own key and the longest
        # match has to report it. The invoice list page above both stays open.
        self.assertEqual(get_writing_route("/my/invoices/overdue"), "/my/invoices/overdue")
        self.assertEqual(get_writing_route("/my/invoices/7"), "/my/invoices/")
        self.assertIsNone(get_writing_route("/my/invoices"))

    def test_a_portal_target_is_refused_off_the_write_database(self) -> None:
        # Each prefix the portal audit added, at the seam that uses it: a target
        # naming one is refused before a browser opens, on the database the
        # write is not allowed on.
        for route in ("/my/invoices/7", "/my/invoices/overdue", "/my/purchase/7",
                      "/my/projects/7", "/my/projects/7/task/9", "/my/tasks/9",
                      "/my/project/7/task/9", "/my/task/9",
                      "/mail/unfollow", "/digest/3/unsubscribe",
                      "/chat/7/tok_1", "/meet/tok_1"):
            with self.subTest(route):
                targets = parse_targets([
                    json.dumps({"module": "m", "target": route, "expect_selector": "#x"}),
                ])
                with self.assertRaises(RuntimeError) as caught:
                    require_write_database(targets, "odoo_test")
                self.assertIn(route, str(caught.exception))
                self.assertIn(get_writing_route(route), str(caught.exception))
                # And permitted on the one database ADR 0012 allows it on.
                require_write_database(targets, WRITE_DATABASE)

    def test_the_get_writing_guard_did_not_move_into_the_operation_enum(self) -> None:
        # The enum only ever names reads: NON_MUTATING_OPERATIONS is every
        # member of it, so a WRITE member would be permitted rather than
        # refused. The guard stays at the target seam for that reason.
        self.assertEqual(NON_MUTATING_OPERATIONS, frozenset(Operation))


CART_TARGET = '{"module": "m", "target": "/shop/checkout", "expect_selector": "#x",' \
              ' "cart": "/shop/product/desk-1"}'


class FakeLocator:
    """The add-to-cart button, as much of it as the cart step touches."""

    def __init__(self, page, selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> "FakeLocator":
        return self

    def wait_for(self, **kwargs) -> None:
        self.page.log.append("wait:%s" % kwargs.get("state"))

    def is_enabled(self, **kwargs) -> bool:
        enabled = self.page.enabled.pop(0) if self.page.enabled else True
        self.page.log.append("enabled?%s" % enabled)
        if isinstance(enabled, Exception):
            raise enabled
        return enabled

    def click(self) -> None:
        self.page.log.append("click")
        if self.page.click_error is not None:
            raise self.page.click_error
        self.page.clicks += 1


class FakePage:
    """A page that answers only what the cart step asks of it, no browser.

    `carts` is what each `/shop/cart` reading reports, in order -- None for a
    page that did not say -- and `order` is the `data-order-id` on the badge.
    `badges` is what the badge on a product page reports, in order, 0 once they
    run out: on any page but the cart that reading can be a step behind, and the
    code treats it as a reading only when it is above zero.
    Every call lands in `log`, so a test can say what happened in what order.
    """

    def __init__(self, carts, *, order="7", orders=(), enabled=(), grew=True, badges=(), answered=True,
                 load_error=None) -> None:
        self.carts = list(carts)
        self.order = order
        # Per-cart-page-reading order ids, consumed in order; `order` when out.
        self.orders = list(orders)
        self.enabled = list(enabled)
        self.grew = grew
        self.badges = list(badges)
        self.answered = answered
        self.load_error = load_error
        # A `load` that fails on a page that did arrive, unless `arrives` says
        # the navigation never got there at all -- or `lands_at` says it
        # arrived somewhere else, the way a lapsed session lands on the login.
        self.url = ""
        self.arrives = True
        self.lands_at: str | None = None
        self.click_error: Exception | None = None
        self.path = ""
        self.log: list[str] = []
        self.opened: list[tuple[str, str]] = []
        self.clicks = 0
        self.closed = False

    def goto(self, url: str, **kwargs) -> None:
        self.url = url
        self.path = urlsplit(url).path
        self.opened.append((self.path, kwargs.get("wait_until")))
        self.log.append("goto:%s" % self.path)
        if self.load_error is not None and kwargs.get("wait_until") == "load":
            if not self.arrives:
                self.url = ""
            if self.lands_at is not None:
                self.url = self.lands_at
            raise self.load_error

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def evaluate(self, script: str, *args):
        # The one reading the step makes: the badge's count and order id in
        # one round-trip (`_CART_STATE_JS`).
        assert "data-order-id" in script, "the cart step reads the badge in one evaluate"
        order = self.order
        if self.path == "/shop/cart":
            count = self.carts.pop(0) if self.carts else None
            self.log.append("cart:%s" % count)
            if self.orders:
                order = self.orders.pop(0)
        else:
            count = self.badges.pop(0) if self.badges else 0
            self.log.append("badge:%s" % count)
        return {"count": count, "order": order}

    @contextlib.contextmanager
    def expect_response(self, matcher, **kwargs):
        yield
        self.log.append("answered?%s" % self.answered)
        if not self.answered:
            raise RuntimeError("Timeout 30000ms exceeded")

    def wait_for_function(self, script: str, **kwargs) -> None:
        self.log.append("grew?%s" % self.grew)
        if not self.grew:
            raise RuntimeError("Timeout 30000ms exceeded")

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.log.append("slept")

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class FakeContext:
    """Hands out the prepared pages in order; the cart step makes two at most."""

    def __init__(self, *pages, fail_after: int | None = None) -> None:
        self.pages = list(pages)
        self.fail_after = fail_after
        self.made = 0

    def new_page(self) -> FakePage:
        self.made += 1
        if self.fail_after is not None and self.made > self.fail_after:
            raise RuntimeError("Target page, context or browser has been closed")
        return self.pages.pop(0)


def cart_driver(context, *, database=WRITE_DATABASE) -> SurfaceDriver:
    """A driver holding only what the cart step reads off `self`.

    `__init__` wants a browser, a login and, on ingress, a live session; the
    cart step wants the database the write is bounded to, a context to make
    pages on, the base its URLs hang off and a masker for the route it names.
    """
    driver = SurfaceDriver.__new__(SurfaceDriver)
    driver.surface = Surface.PUBLIC
    driver.ingress = None
    driver.database = database
    driver.context = context
    driver.base = "https://odoo.example"
    driver.masker = Masker(bases={"<PUBLIC_BASE>": "https://odoo.example"}, ingress_prefix=None, secrets=())
    return driver


class CartStepTests(unittest.TestCase):
    """`ensure_cart` and what a failed cart step leaves behind. No browser."""

    def test_the_click_waits_for_a_button_that_is_attached_and_enabled(self) -> None:
        # At domcontentloaded the button exists before its handler does, so the
        # click waits for the element and for it to answer that it is enabled --
        # all of "the page is live" Playwright can see -- and only then clicks.
        page = FakePage([0, 1], enabled=(False, True))
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(page.log, [
            "goto:/shop/cart", "cart:0",
            "goto:/shop/product/desk-1", "badge:0",
            "wait:visible", "enabled?False", "slept", "enabled?True", "click", "answered?True",
            "goto:/shop/cart", "cart:1",
        ])
        # No badge wait after an answered click: the POST answering is what
        # says the add committed, and the cart reading above is the record.
        # The product page is opened on `load`, not `domcontentloaded`: the
        # handler comes with the website bundle, and `load` is every bundle
        # script fetched and run. The cart readings need no bundle.
        self.assertEqual(page.opened, [("/shop/cart", "domcontentloaded"),
                                       ("/shop/product/desk-1", "load"),
                                       ("/shop/cart", "domcontentloaded")])
        self.assertEqual(write, {"model": "sale.order", "id": "7", "items": 1,
                                 "how": "added the product on /shop/product/desk-1 to the cart (0 -> 1 items)"})
        self.assertTrue(page.closed)

    def test_a_reading_that_will_not_resolve_does_not_end_the_enabled_poll(self) -> None:
        # A button detached while the page hydrates makes the reading raise; that
        # is not the button answering "disabled", and the poll keeps its deadline.
        page = FakePage([0, 1], enabled=(RuntimeError("element is not attached"), True))
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual((page.clicks, write["items"]), (1, 1))

    def test_a_product_page_whose_load_never_fires_is_used_as_it_stands(self) -> None:
        # One sub-resource that never finishes would cost the target a blocker
        # GAP; the page is up, its bundle has very likely run, and the click's
        # retry is behind it. Navigating again would throw that away.
        page = FakePage([0, 1], load_error=RuntimeError("Timeout 60000ms exceeded"))
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual((page.clicks, write["items"]), (1, 1))
        self.assertEqual([wait for path, wait in page.opened if path == "/shop/product/desk-1"], ["load"])

    def test_a_navigation_that_never_arrived_is_the_failure_it_is(self) -> None:
        # Not a slow sub-resource: the page is not the product page at all, so
        # there is nothing to go on with.
        page = FakePage([0, 1], load_error=RuntimeError("net::ERR_CONNECTION_REFUSED"))
        page.arrives = False
        with self.assertRaisesRegex(RuntimeError, "ERR_CONNECTION_REFUSED"):
            cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")

    def test_a_button_that_never_becomes_enabled_fails_the_step_not_the_click(self) -> None:
        page = FakePage([0], enabled=(False, False))
        # A clock that answers every call, however many the path takes: two
        # exact values would fail this test with StopIteration on a third.
        with mock.patch("e2e_menu_action_adapter.time.monotonic",
                        side_effect=itertools.count(0.0, 31.0)):
            with self.assertRaisesRegex(RuntimeError, "add-to-cart button on /shop/product/desk-1 never became enabled"):
                cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(page.clicks, 0)

    def test_a_lost_click_is_clicked_once_more_and_the_record_says_it_was(self) -> None:
        # The handler race no wait can see: the click landed on a dead element,
        # so the cart reads empty. That is a flake, not a broken screen, and
        # failing the run on it costs a whole two-surface judgement.
        # The readings: empty before the step, empty after the first click,
        # empty again just before the second, filled after it, and the same
        # again -- two clicks are read until the cart stops moving.
        page = FakePage([0, 0, 0, 1, 1])
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(page.clicks, 2)
        self.assertEqual((write["items"], write["id"]), (1, "7"))
        self.assertEqual(write["how"], "added the product on /shop/product/desk-1 to the cart (0 -> 1 items)"
                                       "; the first 1 click(s) read as lost, so it was clicked 2 times")
        # Two clicks means two passes over the product page, and no third.
        self.assertEqual(page.log.count("goto:/shop/product/desk-1"), 2)

    def test_a_cart_that_took_both_clicks_is_reported_at_the_size_both_left_it(self) -> None:
        # The badge rising after the second click cannot say which click raised
        # it, so the reading taken after the grace that follows is the record.
        # `/shop/cart/update` increments the line it finds, so both clicks
        # landing leaves qty 2 -- a bigger cart than the other surface will
        # judge, and reporting one item would hide it. A product that adds
        # several at once looks the same from here, so the record names both
        # readings of it rather than asserting the one it cannot tell.
        # The first reading after the second click catches qty 1, mid-commit;
        # the reading after it catches the 2 the cart settled at, and that is
        # the one the record carries.
        page = FakePage([0, 0, 0, 1, 2, 2])
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual((page.clicks, write["items"]), (2, 2))
        self.assertEqual(write["how"], "added the product on /shop/product/desk-1 to the cart (0 -> 2 items)"
                                       "; the first 1 click(s) read as lost, so it was clicked 2 times,"
                                       " and the cart holds more than the one item the step meant to add"
                                       " -- a product that adds several, or a click that was not lost after all")

    def test_a_click_that_landed_late_is_not_clicked_again(self) -> None:
        # The add was still in flight when the reading called the cart empty. A
        # second click would put a second line in a one-product cart: another
        # row to account for, and a screen the plan did not mean to judge.
        page = FakePage([0, 0, 1])
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(page.clicks, 1)
        self.assertEqual(write["items"], 1)
        self.assertEqual(write["how"], "added the product on /shop/product/desk-1 to the cart (0 -> 1 items)"
                                       "; the click landed after the reading that called the cart empty,"
                                       " so it was not clicked again")

    def test_a_cart_that_filled_while_the_product_page_loaded_is_not_clicked(self) -> None:
        # The grace reading is taken before a navigation that can take a minute,
        # so the add can land during it. The badge on the page that comes up
        # says the cart is not empty, and clicking would add the quantity twice.
        page = FakePage([0, 0, 0, 1], badges=(0, 1))
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual((page.clicks, write["items"]), (1, 1))
        self.assertEqual(write["how"], "added the product on /shop/product/desk-1 to the cart (0 -> 1 items)"
                                       "; the click landed after the reading that called the cart empty,"
                                       " so it was not clicked again")

    def test_a_click_whose_update_never_answers_still_reaches_the_cart_reading(self) -> None:
        # A theme that adds by another route, or the dead element the retry is
        # for: no answer to wait for is not a failure of the click, and the cart
        # reading is what judges it either way.
        page = FakePage([0, 1], answered=False)
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual((page.clicks, write["items"]), (1, 1))

    def test_a_click_that_could_not_be_made_at_all_is_the_step_failing(self) -> None:
        # The suppression around the answer must not swallow the click itself.
        page = FakePage([0, 1])
        page.click_error = RuntimeError("element is not attached to the DOM")
        with self.assertRaisesRegex(RuntimeError, "not attached to the DOM"):
            cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")

    def test_a_product_page_that_contradicts_the_cart_page_clicks_nothing(self) -> None:
        # The badge says the cart holds something, the cart page says it is
        # empty, every pass. The step never clicked, so it does not report an
        # add that failed -- it reports the two readings disagreeing.
        page = FakePage([0, 0, 0, 0], badges=(1, 1, 1, 1))
        with self.assertRaisesRegex(RuntimeError, "the cart page reads empty and the product page for "
                                                 "/shop/product/desk-1 says otherwise"):
            cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(page.clicks, 0)

    def test_a_cart_that_was_never_empty_records_that_nothing_was_added(self) -> None:
        # Nothing was clicked at all, so the record must not say a product was
        # added: the cart filled between the reading and the page.
        page = FakePage([0, 4], badges=(4,))
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual((page.clicks, write["items"]), (0, 4))
        self.assertEqual(write["how"], "the cart held 4 item(s) by the time the product page"
                                       " for /shop/product/desk-1 was up; nothing was added")

    def test_a_cart_still_moving_after_three_readings_carries_the_last_of_them(self) -> None:
        # Bounded: the confirming readings stop at three whether they agree or
        # not, and what the record says is the last reading taken.
        page = FakePage([0, 0, 0, 1, 2, 3])
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(write["items"], 3)
        # And it says so: a size nothing confirmed is the last reading taken,
        # and the other surface reading a larger cart is a difference in the
        # evidence rather than in the screens.
        self.assertTrue(write["how"].endswith("; the cart was still changing when the run left it"), write["how"])
        # Six cart readings and no seventh: one before the step, one after each
        # click, the grace one before the second, and two confirming ones.
        self.assertEqual(page.log.count("goto:/shop/cart"), 6)

    def test_a_cart_kept_alive_that_will_not_refresh_still_gets_read(self) -> None:
        # The reading after a failed step is what keeps a cart the run filled in
        # `writes`; an ingress session that will not refresh must not cost it.
        # The two calls the loop makes are let through, the third is the one
        # `_cart_after_failure` makes and suppresses.
        target, = parse_targets([CART_TARGET])
        driver = cart_driver(FakeContext(FakePage([0, 0, 0, 0]), FakePage([1])))
        driver.ingress = mock.Mock()
        driver.ingress.keep_alive.side_effect = [None, None, RuntimeError("the websocket went away")]
        observation = driver.open_screen(target)
        self.assertEqual([write["items"] for write in observation.writes], [1])
        self.assertIn("cart not filled", observation.result)

    def test_a_run_stopped_by_the_session_names_the_line_it_had_already_added(self) -> None:
        # The run stops, so no record will be written and the line the first
        # click committed would go unaccounted for. The message carries it.
        target, = parse_targets([CART_TARGET])
        driver = cart_driver(FakeContext(FakePage([0, 0]), FakePage([1])))
        driver.ingress = mock.Mock()
        driver.ingress.keep_alive.side_effect = [None, RuntimeError("the websocket went away")]
        with self.assertRaises(RuntimeError) as caught:
            driver.open_screen(target)
        self.assertTrue(is_configuration_error(caught.exception))
        self.assertIn("no record will name the cart: sale.order:7 holding 1 item(s), "
                      "the cart holds 1 item(s) after the cart step failed", str(caught.exception))

    def test_a_run_stopped_by_the_session_masks_what_it_reports(self) -> None:
        # This message is re-raised rather than recorded, so it never reaches the
        # masker `open_screen` runs the `cart not filled` text through. The host
        # and the ingress token are in raw Playwright text, and they are what
        # every other message in this driver hides.
        target, = parse_targets([CART_TARGET])
        driver = cart_driver(FakeContext(FakePage([0, 0]), fail_after=1))
        driver.masker = Masker(bases={"<HA_BASE>": HA}, ingress_prefix=PREFIX, secrets=("hunter2",))
        driver.ingress = mock.Mock()
        driver.ingress.keep_alive.side_effect = [
            None, RuntimeError("Page.goto: failed at %s%s/shop/cart with hunter2" % (HA, PREFIX)),
        ]
        with self.assertRaises(RuntimeError) as caught:
            driver.open_screen(target)
        message = str(caught.exception)
        self.assertTrue(is_configuration_error(caught.exception))
        for secret in (HA, PREFIX.rsplit("/", 1)[-1], "hunter2"):
            self.assertNotIn(secret, message)

    def test_a_run_stopped_by_the_session_says_when_it_could_not_read_the_cart(self) -> None:
        # The reading it would have named the cart with failed too, so what the
        # click left is unknown -- and saying nothing would be the worse answer.
        target, = parse_targets([CART_TARGET])
        driver = cart_driver(FakeContext(FakePage([0, 0]), fail_after=1))
        driver.ingress = mock.Mock()
        driver.ingress.keep_alive.side_effect = [None, RuntimeError("the websocket went away")]
        with self.assertRaises(RuntimeError) as caught:
            driver.open_screen(target)
        self.assertIn("1 click(s) had been sent and the cart could not be read afterwards",
                      str(caught.exception))
        self.assertIn("so what it holds is unaccounted for", str(caught.exception))

    def test_a_cart_page_that_stops_answering_the_confirming_reading_says_that(self) -> None:
        # Two confirming readings that said nothing are not a cart that changed:
        # that is the distinction the whole step turns on.
        page = FakePage([0, 0, 0, 1, None, None])
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(write["items"], 1)
        self.assertTrue(write["how"].endswith("; the cart page stopped saying how many items it holds,"
                                             " so this size is the last reading that did"), write["how"])
        # A cart already seen moving is the bigger news, so a reading that says
        # nothing after one that said more does not take its place.
        grew = FakePage([0, 0, 0, 1, 2, None])
        write = cart_driver(FakeContext(grew)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(write["items"], 2)
        self.assertTrue(write["how"].endswith("; the cart was still changing when the run left it"), write["how"])

    def test_a_session_that_will_not_refresh_inside_the_loop_stops_the_run(self) -> None:
        # Anything the cart step raises but a configuration error becomes
        # `cart not filled` on the observation -- a blocker GAP on a screen
        # nobody judged. A dead ingress session is the harness, and `_open`
        # stops the run on the same fault, so this one stops it too.
        target, = parse_targets([CART_TARGET])
        driver = cart_driver(FakeContext(FakePage([0, 1])))
        driver.ingress = mock.Mock()
        driver.ingress.keep_alive.side_effect = RuntimeError("HA websocket gave no result for 5")
        with self.assertRaises(RuntimeError) as caught:
            driver.open_screen(target)
        self.assertTrue(is_configuration_error(caught.exception))
        self.assertIn("HA websocket gave no result for 5", str(caught.exception))

    def test_a_session_dead_before_the_screen_stops_the_run_the_same_way(self) -> None:
        # `_open`'s own refresh, before any page is made: a dead websocket
        # there is the harness too, and a raw websocket message would carry
        # the host every other message masks -- so it is raised as the
        # configuration error it is, masked.
        driver = cart_driver(FakeContext())
        driver.ingress = mock.Mock()
        driver.ingress.keep_alive.side_effect = RuntimeError(
            "ws to https://odoo.example gave no answer")
        with self.assertRaises(RuntimeError) as caught:
            driver._open("/odoo/action-1", backend=True)
        self.assertTrue(is_configuration_error(caught.exception))
        self.assertIn("before opening the screen", str(caught.exception))
        self.assertIn("<PUBLIC_BASE>", str(caught.exception))
        self.assertNotIn("https://odoo.example", str(caught.exception))

    def test_a_run_stopped_after_the_cart_write_names_the_unaccounted_cart(self) -> None:
        # The cart is filled, then the session dies before the screen opens:
        # `open_screens` will write no record for the target, so the line the
        # run just committed would be named nowhere -- the error names it, the
        # way `ensure_cart`'s own in-loop handler does.
        target, = parse_targets([CART_TARGET])
        driver = cart_driver(FakeContext(FakePage([0, 1])))
        driver.ingress = mock.Mock()
        driver.ingress.keep_alive.side_effect = [None, RuntimeError("HA websocket gave no result for 9")]
        with self.assertRaises(RuntimeError) as caught:
            driver.open_screen(target)
        self.assertTrue(is_configuration_error(caught.exception))
        self.assertIn("no record will name the cart: sale.order:7 holding 1 item(s)", str(caught.exception))

    def test_the_cart_answer_is_matched_by_path_and_status(self) -> None:
        # `/shop/cart/update` must not match the quantity editor's
        # `/shop/cart/update_json` (a substring did), an ingress prefix in
        # front is the same route, and an error answer committed nothing.
        response = mock.Mock()
        response.ok, response.url = True, "https://odoo.example/shop/cart/update"
        self.assertTrue(_is_cart_update(response))
        response.url = "https://ha/api/hassio_ingress/tok9/shop/cart/update"
        self.assertTrue(_is_cart_update(response))
        response.url = "https://odoo.example/website_sale/product_configurator/update_cart"
        self.assertTrue(_is_cart_update(response))
        response.url = "https://odoo.example/shop/cart/update_json"
        self.assertFalse(_is_cart_update(response))
        response.ok, response.url = False, "https://odoo.example/shop/cart/update"
        self.assertFalse(_is_cart_update(response))

    def test_a_load_that_failed_on_the_login_page_is_the_navigation_failing(self) -> None:
        # The old guard asked whether the URL contained the route anywhere:
        # `/web/login?redirect=/shop/product/desk-1` does, in its query, and
        # the step then polled the login page 30s for an add-to-cart button
        # and blamed the button. The path says where the navigation landed.
        self.assertTrue(_reached("https://odoo.example/shop/product/desk-1", "/shop/product/desk-1"))
        self.assertTrue(_reached("https://ha/ingress/tok/shop/product/desk-1/", "/shop/product/desk-1"))
        self.assertFalse(_reached("https://odoo.example/web/login?redirect=/shop/product/desk-1",
                                  "/shop/product/desk-1"))
        page = FakePage([0], load_error=RuntimeError("Timeout 60000ms exceeded"))
        page.lands_at = "https://odoo.example/web/login?redirect=/shop/product/desk-1"
        with self.assertRaisesRegex(RuntimeError, "Timeout 60000ms exceeded"):
            cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(page.clicks, 0)

    def test_an_enabled_poll_on_a_dead_page_raises_the_death_not_the_button(self) -> None:
        # A reading that raises because the page itself is gone is not a
        # button answering "disabled": no amount of polling answers it, and
        # "never became enabled" would mask the fault class that matters.
        page = FakePage([0])
        page.enabled = [RuntimeError("Target page, context or browser has been closed")]
        page.closed = True
        with self.assertRaisesRegex(RuntimeError, "has been closed"):
            cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(page.clicks, 0)

    def test_the_give_up_names_the_last_reading_that_raised(self) -> None:
        # A poll that spent its whole deadline on readings that raised should
        # say what they said: "never became enabled" alone reads as a disabled
        # button when the page was tearing itself down under the poll.
        page = FakePage([0])
        page.enabled = [RuntimeError("Execution context was destroyed, most likely because of a navigation")]
        with mock.patch("e2e_menu_action_adapter.time.monotonic",
                        side_effect=itertools.chain([0.0, 1.0], itertools.count(32.0, 31.0))):
            with self.assertRaisesRegex(RuntimeError, r"never became enabled \(the last reading said: "
                                                      r"Execution context was destroyed"):
                cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(page.clicks, 0)

    def test_a_two_click_cart_keeps_the_order_a_reading_then_lost(self) -> None:
        # The confirming readings can catch the badge without its
        # `data-order-id` for a moment; overwriting the id already named
        # would make the record say `sale.order:None` against the other
        # surface's real id -- a blocker GAP on two identical screens.
        page = FakePage([0, 0, 0, 1, 2, 2], orders=["7", "7", "7", "7", None, None])
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual((write["id"], write["items"]), ("7", 2))

    def test_the_retry_is_bounded_and_the_step_gives_up_saying_how_often_it_tried(self) -> None:
        page = FakePage([0, 0, 0, 0])
        with self.assertRaisesRegex(RuntimeError, r"the cart is still empty after adding "
                                                 r"/shop/product/desk-1 in 2 click\(s\)") as caught:
            cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertFalse(is_configuration_error(caught.exception))
        self.assertEqual(page.clicks, 2)
        self.assertTrue(page.closed)

    def test_a_cart_page_that_gives_no_count_is_not_a_cart_to_click_at_again(self) -> None:
        # None is "the page did not say", which no further click answers. Both
        # readings that could send the second click read it that way, and the
        # message carries what the run had clicked by then.
        page = FakePage([0, None])
        with self.assertRaisesRegex(RuntimeError, r"did not show its item count at "
                                                  r"/shop/product/desk-1 after 1 click\(s\)"):
            cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(page.clicks, 1)
        # The grace reading before the second click is the other one.
        grace = FakePage([0, 0, None])
        with self.assertRaisesRegex(RuntimeError, r"did not show its item count at /shop/product/desk-1 "
                                                  r"after 1 click\(s\), so the step did not click again"):
            cart_driver(FakeContext(grace)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(grace.clicks, 1)

    def test_a_cart_that_already_holds_something_is_left_alone(self) -> None:
        # Both surfaces judge the same cart, so the second run must not add to it.
        page = FakePage([3])
        write = cart_driver(FakeContext(page)).ensure_cart("/shop/product/desk-1")
        self.assertEqual(page.clicks, 0)
        self.assertEqual(write["items"], 3)
        self.assertIn("nothing was added", write["how"])

    def test_the_cart_write_is_still_refused_off_the_parity_database(self) -> None:
        page = FakePage([0, 1])
        driver = cart_driver(FakeContext(page), database="odoo_test")
        with self.assertRaises(RuntimeError) as caught:
            driver.ensure_cart("/shop/product/desk-1")
        self.assertTrue(is_configuration_error(caught.exception))
        self.assertEqual(page.clicks, 0)

    def test_an_empty_cart_the_failed_step_created_is_still_a_write(self) -> None:
        # The cart named no order before the step and names one after it, so
        # the run made that row: ADR 0012 has every mutation accounted for, and
        # returning None dropped it from the evidence.
        target, = parse_targets([CART_TARGET])
        filling, after = FakePage([0, 0, 0, 0], order=None), FakePage([0], order="7")
        observation = cart_driver(FakeContext(filling, after)).open_screen(target)
        self.assertFalse(observation.available)
        self.assertIn("cart not filled", observation.result)
        self.assertEqual(list(observation.writes), [
            {"model": "sale.order", "id": "7", "items": 0, "how": "created empty by the failed cart step"},
        ])

    def test_an_empty_order_the_run_only_found_is_not_one_it_created(self) -> None:
        # An earlier run can leave an empty draft order behind, and the
        # logged-in user's is revived on the way in rather than created. The
        # reading `ensure_cart` took before it clicked is what tells them
        # apart, and claiming a write that never happened is the other way this
        # evidence can say more than what happened.
        target, = parse_targets([CART_TARGET])
        filling, after = FakePage([0, 0, 0, 0], order="2"), FakePage([0], order="2")
        observation = cart_driver(FakeContext(filling, after)).open_screen(target)
        self.assertEqual(list(observation.writes), [
            {"model": "sale.order", "id": "2", "items": 0,
             "how": "the empty order the cart already held before the step; nothing was added"},
        ])

    def test_a_step_that_never_made_its_page_compares_against_no_earlier_reading(self) -> None:
        # The reset comes before `new_page`, so a target that never got a page
        # cannot be judged against the reading the previous target left.
        target, = parse_targets([CART_TARGET])
        driver = cart_driver(FakeContext(FakePage([0, 0, 0, 1]), fail_after=1))
        driver.ensure_cart("/shop/product/desk-1")  # leaves cart_before = "7"
        self.assertEqual((driver.cart_before, driver.cart_before_read), ("7", True))
        observation = driver.open_screen(target)
        self.assertEqual(list(observation.writes), [])
        self.assertIn("could not be read afterwards", observation.result)
        self.assertFalse(driver.cart_before_read)
        self.assertIsNone(driver.cart_before)

    def test_an_empty_cart_with_nothing_read_before_it_says_it_cannot_tell(self) -> None:
        # The step failed on its own first reading, so there is nothing to
        # compare against: the row is reported and the record says as much,
        # rather than crediting this run with a write it may not have made.
        target, = parse_targets([CART_TARGET])
        observation = cart_driver(
            FakeContext(FakePage([None]), FakePage([0], order="2")),
        ).open_screen(target)
        self.assertEqual(list(observation.writes), [
            {"model": "sale.order", "id": "2", "items": 0,
             "how": "empty after the failed cart step; the step got no reading from before it,"
                    " so whether this run created it is unknown"},
        ])

    def test_a_cart_that_could_not_be_read_is_no_write_and_the_record_says_why(self) -> None:
        target, = parse_targets([CART_TARGET])
        unreadable = cart_driver(FakeContext(FakePage([0, 0, 0, 0]), FakePage([None]))).open_screen(target)
        self.assertEqual(list(unreadable.writes), [])
        self.assertIn("did not show afterwards how many items", unreadable.result)
        # A cart page that could not even be opened is the same answer, with the
        # reason it gave: the failure that brought us here is still the headline.
        gone = cart_driver(FakeContext(FakePage([0, 0, 0, 0]), fail_after=1)).open_screen(target)
        self.assertEqual(list(gone.writes), [])
        self.assertIn("could not be read afterwards", gone.result)
        self.assertIn("cart not filled", gone.result)

    def test_an_empty_cart_naming_no_order_is_a_record_nobody_created(self) -> None:
        # The badge carries "0" until the session has an order, and an absent
        # attribute reads as None: a write row naming sale.order:0 would claim
        # a record that does not exist.
        target, = parse_targets([CART_TARGET])
        for missing in (None, "0", ""):
            observation = cart_driver(
                FakeContext(FakePage([0, 0, 0, 0]), FakePage([0], order=missing)),
            ).open_screen(target)
            self.assertEqual(list(observation.writes), [], msg=repr(missing))
            self.assertIn("named no order", observation.result)

    def test_a_cart_the_failed_step_did_fill_is_named_as_before(self) -> None:
        target, = parse_targets([CART_TARGET])
        # The click landed and something later in the step failed: the line is
        # this run's and the other surface will reuse it.
        observation = cart_driver(FakeContext(FakePage([0, 0, 0, 0]), FakePage([1]))).open_screen(target)
        self.assertEqual(list(observation.writes), [
            {"model": "sale.order", "id": "7", "items": 1,
             "how": "the cart holds 1 item(s) after the cart step failed"},
        ])


TODO_TARGET = OpenTarget(module="project_todo", target="project_todo.project_task_action_todo",
                         label="To-do kanban", expect_model="project.task")


def open_record(surface: Surface, target: OpenTarget = TODO_TARGET, **overrides) -> dict:
    values = dict(route=target.route, model="project.task", view="kanban")
    values.update(overrides)
    return evidence_record(RUN, surface, module=target.module, identity=target.identity,
                           observation=observation(**values), label=target.label)


class OpenEvidenceTests(unittest.TestCase):
    def test_an_open_record_is_the_same_v1_record_with_its_label(self) -> None:
        item = open_record(Surface.PUBLIC)
        self.assertEqual(item["schema"], EVIDENCE_SCHEMA)
        self.assertEqual(item["module"], "project_todo")
        self.assertEqual(item["control_identity"], "open:action:project_todo.project_task_action_todo")
        self.assertEqual(item["label"], "To-do kanban")
        self.assertNotIn("writes", item["public"])
        json.dumps(item)

    def test_diff_judges_two_open_runs_with_no_change(self) -> None:
        merged = diff_runs([open_record(Surface.PUBLIC)], [open_record(Surface.HA_INGRESS)])
        self.assertEqual([(item["control_identity"], item["verdict"], item["severity"]) for item in merged],
                         [("open:action:project_todo.project_task_action_todo", "PARITY", "none")])
        self.assertEqual(verdict_lines(merged), ["PARITY open:action:project_todo.project_task_action_todo"])

    def test_an_open_target_that_differs_on_one_surface_is_a_gap(self) -> None:
        merged = diff_runs(
            [open_record(Surface.PUBLIC)],
            [open_record(Surface.HA_INGRESS, available=False, result="the screen has no .o_kanban_view")],
        )
        self.assertEqual(merged[0]["verdict"], "GAP")
        self.assertEqual(merged[0]["severity"], "blocker")
        self.assertIn("ingress unavailable: the screen has no .o_kanban_view", merged[0]["notes"])

    def test_masking_a_record_leaves_an_identity_diff_can_join_on(self) -> None:
        masker = Masker(bases={"<PUBLIC_BASE>": "https://odoo.example", "<HA_BASE>": HA},
                        ingress_prefix=PREFIX, secrets=("hunter2",))
        target = OpenTarget(module="project_todo", target="/odoo/action-454?view_type=list")
        item = masker.value(evidence_record(RUN, Surface.HA_INGRESS, module=target.module,
                                            identity=target.identity, observation=observation()))
        self.assertEqual(item["control_identity"], "open:route:/odoo/action-454;view_type=list")

    def test_an_open_record_names_the_records_the_run_created(self) -> None:
        write = {"model": "sale.order", "id": "42", "how": "added the product on /shop/product/desk-1 to the cart"}
        item = evidence_record(RUN, Surface.PUBLIC, module="ecpay_invoice_website", identity="open:route:/shop/checkout",
                               observation=observation(writes=(write,)))
        self.assertEqual(item["public"]["writes"], [write])
        json.dumps(item)

    def test_two_surfaces_that_wrote_different_records_judged_different_screens(self) -> None:
        cart = lambda order_id, how, items=1: {"model": "sale.order", "id": order_id, "items": items, "how": how}
        judge = lambda right: diff_runs(
            [evidence_record(RUN, Surface.PUBLIC, module="m", identity="open:route:/shop/payment",
                             observation=observation(writes=(cart("2", "added one"),)))],
            [evidence_record(RUN, Surface.HA_INGRESS, module="m", identity="open:route:/shop/payment",
                             observation=observation(writes=right))],
        )[0]
        # The same cart, however each run came by it, is the case that judges.
        self.assertEqual(judge((cart("2", "the cart already held 1 item(s)"),))["verdict"], "PARITY")
        different = judge((cart("3", "added one"),))
        self.assertEqual((different["verdict"], different["severity"]), ("GAP", "blocker"))
        self.assertIn("records written: public=sale.order:2 holding 1 ingress=sale.order:3 holding 1",
                      different["notes"])
        self.assertIn("records written: public=sale.order:2 holding 1 ingress=none", judge(())["notes"])
        # The same cart is not the same screen once something else adds to it.
        grew = judge((cart("2", "the cart already held 2 item(s)", items=2),))
        self.assertEqual((grew["verdict"], grew["severity"]), ("GAP", "blocker"))
        self.assertIn("ingress=sale.order:2 holding 2", grew["notes"])

    def test_an_empty_cart_write_is_an_ordinary_write_row_to_diff(self) -> None:
        # No new evidence format for `items: 0`: it joins and compares by the
        # same "model:id holding n" reading as every other write row.
        empty = {"model": "sale.order", "id": "7", "items": 0,
                 "how": "created empty by the failed cart step"}
        filled = dict(empty, items=1, how="added one")
        judge = lambda left, right: diff_runs(
            [evidence_record(RUN, Surface.PUBLIC, module="m", identity="open:route:/shop/payment",
                             observation=observation(writes=left))],
            [evidence_record(RUN, Surface.HA_INGRESS, module="m", identity="open:route:/shop/payment",
                             observation=observation(writes=right))],
        )[0]
        self.assertEqual(judge((empty,), (empty,))["verdict"], "PARITY")
        differ = judge((empty,), (filled,))
        self.assertEqual((differ["verdict"], differ["severity"]), ("GAP", "blocker"))
        self.assertIn("records written: public=sale.order:7 holding 0 ingress=sale.order:7 holding 1",
                      differ["notes"])
        self.assertIn("records written: public=sale.order:7 holding 0 ingress=none", judge((empty,), ())["notes"])

    def test_two_runs_of_different_databases_are_not_comparable(self) -> None:
        other = RunInfo(run_id=RUN.run_id, target=RUN.target, database="odoo_test")
        with self.assertRaisesRegex(ValueError, "crawler configuration: the two runs are not on one database"):
            diff_runs(
                [record(Surface.PUBLIC)],
                [evidence_record(other, Surface.HA_INGRESS, module="contacts",
                                 identity="menu:contacts.menu_contacts|ir.actions.act_window:100",
                                 observation=observation())],
            )


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
