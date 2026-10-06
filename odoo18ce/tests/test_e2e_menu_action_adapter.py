#!/usr/bin/env python3
"""Static-tier tests for the pure parts of the menu/action crawler adapter.

Nothing here opens a browser, a websocket or reads credentials.
"""
import contextlib
import io
import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from e2e_menu_action_adapter import (
    AMBIENT_BASIS_DOCUMENTS,
    AMBIENT_BASIS_GOTO,
    AMBIENT_MODELS,
    AMBIENT_SCHEMA,
    AmbientReading,
    CONVERGENT,
    EVIDENCE_SCHEMA,
    FIXTURE_CONSUMING,
    GET_WRITE_CLASSES,
    GET_WRITING_ROUTES,
    GetWrite,
    _is_cart_update,
    _reached,
    ambient_accounting,
    ambient_deltas,
    ambient_line,
    ambient_summary,
    ambient_summary_path,
    write_ambient_summary,
    WRITE_DATABASE,
    get_writing_route,
    is_configuration_error,
    session_database,
    Masker,
    NavigationCount,
    OpenTarget,
    RunInfo,
    SessionAmbientDriver,
    SurfaceDriver,
    SurfaceObservation,
    UNCLASSIFIED,
    addon_info_command,
    auth_message,
    count_signals,
    diff_runs,
    evidence_record,
    ingress_prefix_from_info,
    ingress_session_command,
    is_prefix_escape,
    open_screens,
    parse_env_file,
    parse_targets,
    parse_viewport,
    plan_visits,
    read_records,
    require_convergent_writes,
    require_write_database,
    scope_from_web_menus,
    skipped_record,
    url_literal_violation,
    validate_session_command,
    validated_count,
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
    OperationPolicy,
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

    def test_a_fixture_consuming_target_is_refused_on_every_database(self) -> None:
        # #225's rule, and the half a database bound cannot express: this write
        # confirms the draft order into a sale and resets the cart, so whichever
        # surface opens it first leaves the second surface no cart to judge. The
        # bound is upgraded to a ban -- `WRITE_DATABASE` is refused too.
        validate = parse_targets(['{"module": "m", "target": "/shop/payment/validate",'
                                  ' "expect_selector": "#x"}'])
        for database in (WRITE_DATABASE, "odoo_test", None):
            with self.subTest(database):
                with self.assertRaises(RuntimeError) as caught:
                    require_write_database(validate, database)
                message = str(caught.exception)
                self.assertIn("/shop/payment/validate", message)
                self.assertIn("confirms the draft order", message)
                self.assertIn(FIXTURE_CONSUMING, message)
                self.assertIn("every database", message)
                self.assertTrue(is_configuration_error(caught.exception))
        # The ban reads nothing but the target list, which is why `open_screens`
        # runs it before a browser launches rather than after the login.
        with self.assertRaisesRegex(RuntimeError, "/shop/payment/validate"):
            require_convergent_writes(validate)
        require_convergent_writes(parse_targets(
            ['{"module": "m", "target": "/shop/checkout", "expect_selector": "#x"}']))

    def test_an_unclassified_route_is_refused_on_every_database(self) -> None:
        # The default for an entry nobody has read against the convergence rule,
        # which is every prefix added after #225's decision: refused like the
        # fixture-consuming class until an audit promotes it. Over-refusing is
        # the direction this guard errs in.
        for route in ("/my/invoices/7", "/my/invoices/overdue", "/my/purchase/7",
                      "/my/projects/7", "/my/tasks/9", "/my/project/7/task/9", "/my/task/9",
                      "/mail/unfollow", "/digest/3/unsubscribe", "/chat/tok_1", "/meet/tok_1",
                      "/discuss/channel/7", "/web/image/123", "/mail/message/7", "/mail/view"):
            with self.subTest(route):
                targets = parse_targets([
                    json.dumps({"module": "m", "target": route, "expect_selector": "#x"}),
                ])
                for database in (WRITE_DATABASE, "odoo_test"):
                    with self.assertRaises(RuntimeError) as caught:
                        require_write_database(targets, database)
                    message = str(caught.exception)
                    self.assertIn(route, message)
                    self.assertIn(get_writing_route(route), message)
                    self.assertIn(UNCLASSIFIED, message)
                    self.assertTrue(is_configuration_error(caught.exception))

    def test_a_future_entry_with_no_classification_is_refused_rather_than_bounded(self) -> None:
        # The rule is the default and not a list: an entry added tomorrow with
        # `UNCLASSIFIED` is refused everywhere without anybody touching the
        # guard, which is what makes forgetting to classify safe.
        with mock.patch.dict(
            "e2e_menu_action_adapter.GET_WRITING_ROUTES",
            {"/shop/tomorrow": GetWrite("does something nobody has read", UNCLASSIFIED)},
        ):
            targets = parse_targets(['{"module": "m", "target": "/shop/tomorrow",'
                                     ' "expect_selector": "#x"}'])
            for database in (WRITE_DATABASE, "odoo_test", None):
                with self.subTest(database):
                    with self.assertRaisesRegex(RuntimeError, "/shop/tomorrow"):
                        require_write_database(targets, database)

    def test_the_convergent_routes_stay_bounded_rather_than_banned(self) -> None:
        # The eight #225 read as convergent -- each one recomputes or re-stores
        # the same values on a cart it leaves in place, so each surface's render
        # includes the effect of its own write and both surfaces judge one
        # screen. Today's behaviour, unchanged: allowed on the write database,
        # refused off it.
        for route in ("/shop/checkout", "/shop/address", "/shop/confirm_order",
                      "/shop/extra_info", "/shop/payment", "/shop/pricelist",
                      "/shop/change_pricelist/3", "/website/lang/fr_BE"):
            with self.subTest(route):
                targets = parse_targets([
                    json.dumps({"module": "m", "target": route, "expect_selector": "#x"}),
                ])
                require_write_database(targets, WRITE_DATABASE)
                require_convergent_writes(targets)
                for unknown in ("odoo_test", None):
                    with self.assertRaises(RuntimeError) as caught:
                        require_write_database(targets, unknown)
                    self.assertIn(get_writing_route(route), str(caught.exception))
                    self.assertIn(WRITE_DATABASE, str(caught.exception))

    def test_the_two_routes_the_audit_promoted_are_the_two_it_read(self) -> None:
        # #228's audit against the pinned Odoo: both routes write only idempotent
        # re-stores on the way to rendering, and the one branch of each that does
        # not converge needs a query a target may not carry. Promoted, and pinned
        # here so a later disagreement is one constant and this test.
        for route in ("/shop/cart", "/my/orders/"):
            with self.subTest(route):
                self.assertEqual(GET_WRITING_ROUTES[route].classification, CONVERGENT)
        for route in ("/shop/cart", "/my/orders/7"):
            with self.subTest(route):
                targets = parse_targets([
                    json.dumps({"module": "m", "target": route, "expect_selector": "#x"}),
                ])
                require_write_database(targets, WRITE_DATABASE)
                with self.assertRaisesRegex(RuntimeError, WRITE_DATABASE):
                    require_write_database(targets, "odoo_test")

    def test_the_promoted_routes_rest_on_the_query_a_target_may_not_carry(self) -> None:
        # What the promotion above rests on. `/shop/cart?access_token=...&revive=merge`
        # moves an abandoned cart's lines onto the session cart and cancels it (a
        # consumption), and `/my/orders/<id>?access_token=...` posts a
        # viewed-by-customer note once per session (an accumulation).
        # `_TARGET_QUERY` admits a view chooser and nothing else, so no target
        # reaches either -- and if that ever widens, this test is what says these
        # two entries have to be read again.
        for route in ("/shop/cart?access_token=tok_1&revive=merge",
                      "/shop/cart?access_token=tok_1",
                      "/my/orders/7?access_token=tok_1"):
            with self.subTest(route):
                with self.assertRaisesRegex(ValueError, "may not carry the query"):
                    parse_targets([
                        json.dumps({"module": "m", "target": route, "expect_selector": "#x"}),
                    ])

    def test_a_banned_route_and_a_bounded_write_are_both_reported(self) -> None:
        # The same reason the bound reports every refusal at once: an operator who
        # edits the banned route out of the file must not then be sent back for
        # the cart, or for a convergent route the session cannot write on.
        both = parse_targets([
            '{"module": "m", "target": "/shop/payment/validate", "expect_selector": "#x"}',
            '{"module": "m", "target": "/shop/confirm_order", "expect_selector": "#y",'
            ' "cart": "/shop/product/desk-1"}',
        ])
        with self.assertRaises(RuntimeError) as caught:
            require_write_database(both, "odoo_test")
        message = str(caught.exception)
        self.assertIn("/shop/payment/validate", message)
        self.assertIn("every database", message)
        self.assertIn("fills a cart", message)
        self.assertIn("/shop/confirm_order", message)
        self.assertIn(WRITE_DATABASE, message)

    def test_the_guard_reads_a_target_list_it_can_only_walk_once(self) -> None:
        # The guard walks the targets more than once -- for a declared cart, for
        # a route whose write does not converge, for one that does -- and it
        # takes an `Iterable`, so a generator would arrive empty at the second
        # walk and permit the write.
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
        for prefix, entry in GET_WRITING_ROUTES.items():
            with self.subTest(prefix):
                # A prefix is matched against a target's path, so it has to be
                # one: no origin and no query. A trailing slash is allowed and
                # means "below this, not this" -- and is the only place one can
                # appear, since `get_writing_route` strips it off a path.
                self.assertEqual(prefix, urlsplit(prefix).path)
                self.assertTrue(prefix.startswith("/"))
                self.assertFalse(prefix.endswith("//"))
                self.assertTrue(entry.write)
                # And a classification from the documented set: the guard reads
                # it, and an entry nobody classified is refused rather than
                # bounded, so a typo must not read as `CONVERGENT`.
                self.assertIn(entry.classification, GET_WRITE_CLASSES)

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
                    {name: GetWrite("cited", CONVERGENT) for name in order}, clear=True,
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
                      "/my/payment_method", "/donation/pay", "/rate/tok_1/5"):
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

    def test_a_portal_target_is_refused_whatever_the_database(self) -> None:
        # Each prefix the portal audit added, at the seam that uses it: a target
        # naming one is refused before a browser opens. #225's rule made that
        # refusal database-independent -- none of these was read against the
        # convergence criterion, and an unread write is refused.
        for route in ("/my/invoices/7", "/my/invoices/overdue", "/my/purchase/7",
                      "/my/projects/7", "/my/projects/7/task/9", "/my/tasks/9",
                      "/my/project/7/task/9", "/my/task/9",
                      "/mail/unfollow", "/digest/3/unsubscribe",
                      "/chat/7/tok_1", "/meet/tok_1"):
            with self.subTest(route):
                targets = parse_targets([
                    json.dumps({"module": "m", "target": route, "expect_selector": "#x"}),
                ])
                for database in ("odoo_test", WRITE_DATABASE):
                    with self.assertRaises(RuntimeError) as caught:
                        require_write_database(targets, database)
                    self.assertIn(route, str(caught.exception))
                    self.assertIn(get_writing_route(route), str(caught.exception))

    def test_the_mail_routes_the_sweep_read_a_write_on_are_bounded(self) -> None:
        # #247's sweep of `mail`'s 16 unread controllers, and it ends in one
        # write rather than five verdicts: `@add_guest_to_context`
        # (mail/models/discuss/mail_guest.py:30-33) updates the guest's timezone
        # on any route it decorates, so the thing to read is the decorator and
        # not the body. It is on both `discuss/binary.py` routes, on the bare
        # `@route()` that re-exposes `/web/image` (:65), on the Discuss page the
        # portal audit recorded clean, and on `/mail/message/<id>`.
        for route, prefix in (
            ("/discuss/channel/7/attachment/9", "/discuss/channel/"),
            ("/discuss/channel/7/image/9", "/discuss/channel/"),
            ("/discuss/channel/7/image/9/64x64", "/discuss/channel/"),
            # Recorded clean by #226 and not clean: it carries the decorator too.
            ("/discuss/channel/7", "/discuss/channel/"),
            # `/web/image` is a route itself, so its key carries no trailing
            # slash and has to match the bare path as well as all 17 spellings
            # of it in web/controllers/binary.py:164-182.
            ("/web/image", "/web/image"),
            ("/web/image/123", "/web/image"),
            ("/web/image/123-1699/64x64/logo.png", "/web/image"),
            ("/web/image/res.partner/3/image_128/64x64/avatar.png", "/web/image"),
            # The two routes in the file #226 read but recorded nothing about.
            ("/mail/view", "/mail/view"),
            ("/mail/message/7", "/mail/message/"),
        ):
            with self.subTest(route):
                self.assertEqual(get_writing_route(route), prefix)
        # Read and found clean: the two worklet routes, which answer from a file
        # on disk and reach no model at all. And the near misses of the new keys
        # -- neither `/discuss/channel` nor `/mail/message` is a route, and
        # `/web/images` only shares characters with `/web/image`.
        for clean in ("/mail/rtc/audio_worklet_processor", "/discuss/voice/worklet_processor",
                      "/discuss/channel", "/mail/message", "/web/images", "/web/imagery"):
            with self.subTest(clean):
                self.assertIsNone(get_writing_route(clean))

    def test_a_mail_sweep_target_is_refused_whatever_the_database(self) -> None:
        # Each prefix #247 added, at the seam that uses it. `/web/image` is the
        # one whose spelling is new to the list: a route `web` owns, on the list
        # only because `mail` re-exposes it, whose own bare path is a route with
        # 17 spellings under it -- so it is exercised both bare and nested. None
        # of them is classified either, so the refusal does not read the
        # database.
        for route in ("/discuss/channel/7", "/discuss/channel/7/attachment/9",
                      "/discuss/channel/7/image/9/64x64",
                      "/web/image", "/web/image/res.partner/3/image_128",
                      "/mail/view", "/mail/message/7"):
            with self.subTest(route):
                targets = parse_targets([
                    json.dumps({"module": "m", "target": route, "expect_selector": "#x"}),
                ])
                for database in ("odoo_test", WRITE_DATABASE):
                    with self.assertRaises(RuntimeError) as caught:
                        require_write_database(targets, database)
                    self.assertIn(route, str(caught.exception))
                    self.assertIn(get_writing_route(route), str(caught.exception))

    def test_a_banned_target_is_refused_before_a_browser_launches(self) -> None:
        # "Before any screen opens" is stronger than "before the first target":
        # the ban reads no database, so there is nothing to wait for the login to
        # report, and `open_screens` makes it before Playwright starts. A browser
        # launch would reach this patched launcher and fail the test.
        import playwright.sync_api

        targets = parse_targets(['{"module": "m", "target": "/shop/payment/validate",'
                                 ' "expect_selector": "#x"}'])
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "open.jsonl")
            with mock.patch.object(playwright.sync_api, "sync_playwright",
                                   side_effect=AssertionError("a browser was launched")):
                with self.assertRaisesRegex(RuntimeError, "/shop/payment/validate"):
                    open_screens(Surface.PUBLIC, targets, out)
            # And the evidence of whatever ran last is left where it was.
            self.assertFalse(os.path.exists(out))

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


CHECKOUT_TARGET = '{"module": "m", "target": "/shop/checkout", "expect_selector": "#x"}'
CHECKOUT_WRITE = GET_WRITING_ROUTES["/shop/checkout"].write


def screen_driver(context, *, database=WRITE_DATABASE) -> SurfaceDriver:
    """A cart driver whose navigation is already done, so `open_screen` is what runs.

    `_open` is the part that needs a browser; what this file is about is what
    `open_screen` records around it -- here, the draft order a GET-writing
    route left behind once its screen had rendered.
    """
    driver = cart_driver(context, database=database)
    driver._open = lambda *args, **kwargs: observation()
    return driver


class GetWriteEvidenceTests(unittest.TestCase):
    """What a target on a `GET_WRITING_ROUTES` route puts in `writes`. No browser."""

    def test_a_get_writing_target_names_the_draft_order_the_visit_left(self) -> None:
        # The navigation is a plain GET and Odoo writes while it renders, so the
        # record said nothing about a mutation ADR 0012 has accounted for -- and
        # `_judge` compared "none" with "none" whatever the two surfaces wrote.
        target, = parse_targets([CHECKOUT_TARGET])
        page = FakePage([1], order="7")
        observed = screen_driver(FakeContext(page)).open_screen(target)
        self.assertTrue(observed.available)
        self.assertEqual(list(observed.writes), [
            {"model": "sale.order", "id": "7", "items": 1,
             "how": "the draft order the session held after the visit to /shop/checkout,"
                    " which " + CHECKOUT_WRITE},
        ])
        # Read the way a failed cart step reads it: the cart page, once.
        self.assertEqual(page.opened, [("/shop/cart", "domcontentloaded")])

    def test_the_row_quotes_the_write_the_table_says_the_route_makes(self) -> None:
        # The `how` is not a sentence of its own: it names the prefix the target
        # fell under and the write `GET_WRITING_ROUTES` recorded for it, so an
        # entry re-read later says in the evidence what it says in the table.
        target, = parse_targets(['{"module": "m", "target": "/shop/pricelist", "expect_selector": "#x"}'])
        observed = screen_driver(FakeContext(FakePage([2], order="7"))).open_screen(target)
        self.assertEqual(observed.writes[0]["how"],
                         "the draft order the session held after the visit to /shop/pricelist, which "
                         + GET_WRITING_ROUTES["/shop/pricelist"].write)

    def test_an_empty_draft_order_after_the_visit_is_a_row_like_any_other(self) -> None:
        # `items: 0` is the #213 shape, and it joins and compares the same way:
        # an order that lost its lines on one surface only is the difference
        # this evidence exists to show.
        target, = parse_targets([CHECKOUT_TARGET])
        observed = screen_driver(FakeContext(FakePage([0], order="7"))).open_screen(target)
        self.assertEqual(list(observed.writes), [
            {"model": "sale.order", "id": "7", "items": 0,
             "how": "the draft order the session held after the visit to /shop/checkout,"
                    " which " + CHECKOUT_WRITE},
        ])

    def test_a_visit_that_left_no_draft_order_names_none_and_says_so(self) -> None:
        # The badge carries "0" until the session has an order: there is no row
        # to report, and a row naming `sale.order:0` would claim a record that
        # does not exist. #213 settled that for the cart step
        # (`test_an_empty_cart_naming_no_order_is_a_record_nobody_created`) and
        # a GET that wrote on no draft order is the same reading: both surfaces
        # say "none" because that is what the visit left, and the record says
        # so in words rather than inventing a row to break the tie with.
        target, = parse_targets([CHECKOUT_TARGET])
        for missing in (None, "0", ""):
            observed = screen_driver(FakeContext(FakePage([0], order=missing))).open_screen(target)
            self.assertEqual(list(observed.writes), [], msg=repr(missing))
            self.assertEqual(observed.result,
                             "loaded; the cart named no order after the visit to /shop/checkout,"
                             " so this run has no draft order to report")

    def test_a_draft_order_that_could_not_be_read_is_no_row_and_the_record_says_why(self) -> None:
        # Silence is what this issue is about, so a reading that failed is not
        # silence either: the screen still loaded and the record carries both.
        target, = parse_targets([CHECKOUT_TARGET])
        unreadable = screen_driver(FakeContext(FakePage([None]))).open_screen(target)
        self.assertEqual(list(unreadable.writes), [])
        self.assertTrue(unreadable.available)
        self.assertIn("did not show afterwards how many items", unreadable.result)
        self.assertTrue(unreadable.result.startswith("loaded; "), unreadable.result)
        gone = screen_driver(FakeContext(fail_after=0)).open_screen(target)
        self.assertEqual(list(gone.writes), [])
        self.assertIn("could not be read afterwards", gone.result)

    def test_a_target_under_no_listed_prefix_is_recorded_exactly_as_before(self) -> None:
        # The reading is a `/shop/cart` navigation, which writes: a target that
        # named no GET-writing route must not get one.
        target, = parse_targets(['{"module": "m", "target": "/odoo/action-1", "expect_model": "res.partner"}'])
        context = FakeContext()
        observed = screen_driver(context).open_screen(target)
        self.assertEqual(list(observed.writes), [])
        self.assertEqual(observed.result, "loaded")
        self.assertEqual(context.made, 0)

    def test_a_cart_target_names_the_cart_it_filled_and_the_order_the_visit_left(self) -> None:
        # Two writes, two rows: `ensure_cart` says what the run set up before
        # the screen, and this says what the screen's own GET left behind.
        target, = parse_targets([CART_TARGET])
        filling, after = FakePage([0, 1], order="7"), FakePage([1], order="7")
        observed = screen_driver(FakeContext(filling, after)).open_screen(target)
        self.assertEqual([(item["id"], item["items"]) for item in observed.writes], [("7", 1), ("7", 1)])
        self.assertIn("added the product on /shop/product/desk-1", observed.writes[0]["how"])
        self.assertIn("after the visit to /shop/checkout", observed.writes[1]["how"])

    def test_a_failed_cart_step_takes_no_reading_for_a_visit_it_never_made(self) -> None:
        # The cart step failed, so the screen was never opened and the route
        # never wrote: the only row is the one the cart step left.
        target, = parse_targets([CART_TARGET])
        observed = screen_driver(FakeContext(FakePage([0, 0, 0, 0]), FakePage([1]))).open_screen(target)
        self.assertFalse(observed.available)
        self.assertEqual([item["how"] for item in observed.writes],
                         ["the cart holds 1 item(s) after the cart step failed"])

    def test_the_reading_is_refused_off_the_parity_database(self) -> None:
        # The reading opens `/shop/cart`, which is itself a GET-writing route:
        # it is bounded where every other write in this driver is. A target
        # never gets here off `WRITE_DATABASE` -- `require_write_database`
        # refuses it first -- so this is the bound for a caller that skipped it.
        driver = screen_driver(FakeContext(), database="odoo_test")
        with self.assertRaises(RuntimeError) as caught:
            driver._draft_order_after_visit("/shop/checkout")
        self.assertTrue(is_configuration_error(caught.exception))
        self.assertIn("'odoo_test'", str(caught.exception))

    def test_a_difference_in_what_the_get_wrote_is_judged_like_a_cart_write(self) -> None:
        # The judgement this evidence unlocks: before it both surfaces reported
        # "none" and a real divergence in what the GET wrote could never fire.
        # No new evidence format -- `diff_runs` reads the same rows.
        row = lambda items: {"model": "sale.order", "id": "7", "items": items,
                             "how": "the draft order the session held after the visit to /shop/checkout,"
                                    " which " + CHECKOUT_WRITE}
        judge = lambda right: diff_runs(
            [evidence_record(RUN, Surface.PUBLIC, module="m", identity="open:route:/shop/checkout",
                             observation=observation(writes=(row(1),)))],
            [evidence_record(RUN, Surface.HA_INGRESS, module="m", identity="open:route:/shop/checkout",
                             observation=observation(writes=right))],
        )[0]
        self.assertEqual(judge((row(1),))["verdict"], "PARITY")
        differs = judge((row(2),))
        self.assertEqual((differs["verdict"], differs["severity"]), ("GAP", "blocker"))
        self.assertIn("records written: public=sale.order:7 holding 1 ingress=sale.order:7 holding 2",
                      differs["notes"])

    def test_a_reading_that_failed_on_one_surface_is_a_difference_and_not_a_silence(self) -> None:
        # The cost of leaving no row where the reading failed, written down: the
        # surface that could not read its cart compares as "none" against the
        # other surface's row and the pair is a blocker. That is the honest
        # verdict -- the comparison the row exists for cannot be made -- and the
        # `result` beside it in the joined record says it was the reading that
        # failed and not the database that differed.
        row = {"model": "sale.order", "id": "7", "items": 1,
               "how": "the draft order the session held after the visit to /shop/checkout,"
                      " which " + CHECKOUT_WRITE}
        judged = diff_runs(
            [evidence_record(RUN, Surface.PUBLIC, module="m", identity="open:route:/shop/checkout",
                             observation=observation(writes=(row,)))],
            [evidence_record(RUN, Surface.HA_INGRESS, module="m", identity="open:route:/shop/checkout",
                             observation=observation(
                                 result="loaded; the cart could not be read afterwards (Timeout 60000ms exceeded)"))],
        )[0]
        self.assertEqual((judged["verdict"], judged["severity"]), ("GAP", "blocker"))
        self.assertIn("records written: public=sale.order:7 holding 1 ingress=none", judged["notes"])
        self.assertIn("could not be read afterwards", judged["ingress"]["result"])


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


class FakeResponse:
    """What `context.request.post` answers: a status and a JSON-RPC body."""

    def __init__(self, body, status: int = 200) -> None:
        self.body = body
        self.status = status

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeRequest:
    """The session's request context, answering one `search_count` per model.

    `answers` maps a model to the count it reports, to an `Exception` the post
    raises, or to a `FakeResponse` for an answer that is not a count. Every call
    lands in `posted`, so a test can say what was asked and how.
    """

    def __init__(self, answers) -> None:
        self.answers = dict(answers)
        self.posted: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs):
        self.posted.append((url, kwargs.get("data")))
        answer = self.answers.get(urlsplit(url).path.split("/")[-2])
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, FakeResponse):
            return answer
        if answer is None:
            return FakeResponse({"error": {"message": "Object does not exist",
                                           "data": {"message": "Object website.track doesn't exist"}}})
        return FakeResponse({"result": answer})


class CountingContext(FakeContext):
    """A context whose `request` answers the counts, and makes no pages."""

    def __init__(self, answers) -> None:
        super().__init__()
        self.request = FakeRequest(answers)


def counted(**per_model) -> AmbientReading:
    """A reading that counted every model it was given."""
    return AmbientReading(counts=dict(per_model))


class AmbientAccountingTests(unittest.TestCase):
    """#256: a run names the ambient rows it left, in counts. No browser."""

    def test_the_delta_is_the_two_counts_subtracted(self) -> None:
        rows = ambient_deltas(counted(**{"website.track": 187, "website.visitor": 20}),
                             counted(**{"website.track": 206, "website.visitor": 21}))
        self.assertEqual(rows, {
            "website.track": {"before": 187, "after": 206, "delta": 19},
            "website.visitor": {"before": 20, "after": 21, "delta": 1},
        })

    def test_a_crawl_that_opened_no_tracked_page_says_zero_rather_than_nothing(self) -> None:
        # ADR 0012's postscript claims a crawl never makes the tracking write:
        # it navigates `/odoo/action-<id>`, whose response is not a tracked page.
        # A zero delta is that claim measured, which is why a run whose figure is
        # 0 still writes the figure.
        rows = ambient_deltas(counted(**{"website.track": 187, "website.visitor": 20}),
                              counted(**{"website.track": 187, "website.visitor": 20}))
        self.assertEqual([row["delta"] for row in rows.values()], [0, 0])

    def test_a_negative_delta_is_recorded_rather_than_clamped(self) -> None:
        # `website.visitor` has a GC cron and it takes the visitor's `website.track`
        # rows with it, so fewer rows after than before is a vacuum that ran
        # during the run. Clamping it to zero would report a count nobody read.
        rows = ambient_deltas(counted(**{"website.track": 187, "website.visitor": 20}),
                              counted(**{"website.track": 99, "website.visitor": 4}))
        self.assertEqual(rows["website.track"], {"before": 187, "after": 99, "delta": -88})

    def test_a_reading_that_failed_leaves_the_reason_in_place_of_a_delta(self) -> None:
        rows = ambient_deltas(AmbientReading.none("the session was not logged in"),
                              counted(**{"website.track": 206, "website.visitor": 21}))
        for model in AMBIENT_MODELS:
            with self.subTest(model):
                self.assertNotIn("delta", rows[model])
                self.assertIn("before the run", rows[model]["unread"])
                self.assertIn("the session was not logged in", rows[model]["unread"])

    def test_a_model_this_database_does_not_hold_is_unread_and_not_zero(self) -> None:
        # `website` uninstalled: the model does not exist, so there is no count
        # and no ambient write either. A zero would claim a reading nobody took.
        before = AmbientReading(counts={"website.visitor": 20},
                                unread={"website.track": "Object website.track doesn't exist"})
        rows = ambient_deltas(before, counted(**{"website.visitor": 21}))
        self.assertEqual(rows["website.visitor"]["delta"], 1)
        self.assertIn("website.track doesn't exist", rows["website.track"]["unread"])
        self.assertIn("after the run", rows["website.track"]["unread"])

    def test_both_sides_of_a_failed_reading_are_named(self) -> None:
        rows = ambient_deltas(AmbientReading.none("no session before"), AmbientReading.none("no session after"))
        said = rows["website.track"]["unread"]
        self.assertIn("before the run: no session before", said)
        self.assertIn("after the run: no session after", said)

    def test_the_summary_is_its_own_schema_so_diff_never_judges_it(self) -> None:
        summary = ambient_summary(RUN, Surface.HA_INGRESS, command="open", navigations=7,
                                  before=counted(**{"website.track": 187, "website.visitor": 20}),
                                  after=counted(**{"website.track": 206, "website.visitor": 21}))
        self.assertEqual(summary["schema"], AMBIENT_SCHEMA)
        self.assertEqual(AMBIENT_SCHEMA, "odoo-parity-ambient/v1")
        self.assertNotEqual(AMBIENT_SCHEMA, EVIDENCE_SCHEMA)
        # A summary that reached the evidence file is refused rather than joined:
        # a delta is one surface's property, and `_judge` would read an ordering
        # artefact as a difference between the surfaces.
        with self.assertRaises(ValueError):
            read_records([json.dumps(summary)])

    def test_the_summary_names_the_run_the_delta_belongs_to(self) -> None:
        summary = ambient_summary(RUN, Surface.HA_INGRESS, command="crawl", navigations=30,
                                  before=counted(**{"website.track": 1, "website.visitor": 1}),
                                  after=counted(**{"website.track": 1, "website.visitor": 1}))
        self.assertEqual(summary["run_id"], RUN.run_id)
        self.assertEqual(summary["database"], RUN.database)
        self.assertEqual(summary["target"], RUN.target)
        self.assertEqual(summary["client"], RUN.client)
        self.assertEqual(summary["surface"], "ingress")
        self.assertEqual(summary["command"], "crawl")
        self.assertEqual(summary["navigations"], 30)
        json.dumps(summary)

    def test_the_summary_says_what_the_number_is_not(self) -> None:
        # The figure is a net count over a window, not an authorship claim, and
        # the record has to say so where it is read -- a reader comparing two
        # surfaces' deltas would otherwise take an ordering artefact for a gap.
        said = ambient_summary(RUN, Surface.PUBLIC, command="open", navigations=1,
                               before=counted(**{"website.track": 1, "website.visitor": 1}),
                               after=counted(**{"website.track": 2, "website.visitor": 1}))["notes"]
        for promise in ("Counts only", "after the login", "another session", "cron", "`diff` does not judge it"):
            with self.subTest(promise):
                self.assertIn(promise, said)

    def test_the_summary_sits_beside_the_evidence_it_accounts_for(self) -> None:
        # The extension is replaced and not appended, so neither name carries two
        # of them and the pair sorts together in an evidence directory.
        self.assertEqual(ambient_summary_path("ingress-open.jsonl"), "ingress-open.ambient.json")
        self.assertEqual(ambient_summary_path("/tmp/a.b/open"), "/tmp/a.b/open.ambient.json")

    def test_the_summary_is_written_as_one_json_object(self) -> None:
        summary = ambient_summary(RUN, Surface.PUBLIC, command="open", navigations=2,
                                  before=counted(**{"website.track": 1, "website.visitor": 1}),
                                  after=counted(**{"website.track": 3, "website.visitor": 2}))
        with tempfile.TemporaryDirectory() as directory:
            written = write_ambient_summary(os.path.join(directory, "public-open.jsonl"), summary)
            self.assertEqual(os.path.basename(written), "public-open.ambient.json")
            with open(written, encoding="utf-8") as stored:
                self.assertEqual(json.load(stored), summary)

    def test_the_stderr_line_says_the_delta_per_model(self) -> None:
        summary = ambient_summary(RUN, Surface.PUBLIC, command="open", navigations=7,
                                  before=counted(**{"website.track": 187, "website.visitor": 20}),
                                  after=AmbientReading(counts={"website.visitor": 21},
                                                       unread={"website.track": "boom"}))
        line = ambient_line(summary)
        self.assertIn("website.visitor +1", line)
        self.assertIn("website.track unread", line)
        self.assertIn("7 navigation(s)", line)


class AmbientReadingTests(unittest.TestCase):
    """How the counts are read: one read-only RPC per model. No browser."""

    def test_the_count_is_one_read_only_search_count_per_model(self) -> None:
        context = CountingContext({"website.track": 187, "website.visitor": 20})
        reading = cart_driver(context).ambient_reading()
        self.assertEqual(reading.counts, {"website.track": 187, "website.visitor": 20})
        self.assertEqual(reading.unread, {})
        self.assertEqual([url for url, _ in context.request.posted], [
            "https://odoo.example/web/dataset/call_kw/website.track/search_count",
            "https://odoo.example/web/dataset/call_kw/website.visitor/search_count",
        ])
        # A count and nothing else: an empty domain, no fields, no records, and
        # no page -- a POST to `call_kw` renders no template, so the reading
        # cannot add to the ambient rows it is reading.
        for _, data in context.request.posted:
            self.assertEqual(data["params"]["method"], "search_count")
            self.assertEqual(data["params"]["args"], [[]])
            self.assertEqual(data["params"]["kwargs"], {})
        self.assertEqual(context.made, 0)

    def test_the_reading_passes_through_the_read_only_policy(self) -> None:
        # The enum is the seam for what this driver may do, so a request it makes
        # belongs in it rather than beside it -- and every member of it is
        # non-mutating, which is what makes the addition safe.
        self.assertIn(Operation.COUNT_ROWS, NON_MUTATING_OPERATIONS)
        without = OperationPolicy(allowed=NON_MUTATING_OPERATIONS - {Operation.COUNT_ROWS})
        with mock.patch("e2e_menu_action_adapter.READ_ONLY_POLICY", without):
            with self.assertRaises(PermissionError):
                cart_driver(CountingContext({"website.track": 1})).count_rows("website.track")

    def test_a_model_the_session_cannot_count_is_a_reason_and_not_a_zero(self) -> None:
        # `website` uninstalled, or a user without access: the other model still
        # reads, so the failure is recorded per model rather than for the run.
        context = CountingContext({"website.visitor": 20})
        reading = cart_driver(context).ambient_reading()
        self.assertEqual(reading.counts, {"website.visitor": 20})
        self.assertIn("website.track doesn't exist", reading.unread["website.track"])

    def test_an_answer_that_is_not_a_count_is_refused(self) -> None:
        for name, answer in {
            "a string": FakeResponse({"result": "187"}),
            "a boolean": FakeResponse({"result": True}),
            "no result": FakeResponse({}),
        }.items():
            with self.subTest(name):
                reading = cart_driver(CountingContext({"website.track": answer})).ambient_reading()
                self.assertNotIn("website.track", reading.counts)
                self.assertIn("website.track", reading.unread)

    def test_a_dead_session_is_told_from_a_model_that_is_not_installed(self) -> None:
        # The two reasons a count can be missing, and the record owes the
        # operator which one it was: a lapsed session and a gateway that answered
        # 502 both send HTML, so reading the body first would record a JSON parse
        # error where the status is the answer.
        gateway = FakeResponse(ValueError("Unexpected token '<'"), status=502)
        reading = cart_driver(CountingContext({"website.track": gateway})).ambient_reading()
        self.assertIn("HTTP 502", reading.unread["website.track"])
        html = FakeResponse(ValueError("Unexpected token '<'"))
        reading = cart_driver(CountingContext({"website.track": html})).ambient_reading()
        self.assertIn("no JSON", reading.unread["website.track"])

    def test_a_reading_that_raised_names_no_secret(self) -> None:
        # The reason goes in a record a pull request quotes, and a raw Playwright
        # message carries the host and the ingress token every other message in
        # this driver hides.
        driver = cart_driver(CountingContext(
            {"website.track": RuntimeError("connect to https://odoo.example/web failed")}))
        reading = driver.ambient_reading()
        self.assertNotIn("odoo.example", reading.unread["website.track"])
        self.assertIn("<PUBLIC_BASE>", reading.unread["website.track"])

    def test_the_figure_counts_the_navigations_the_driver_made_not_the_targets(self) -> None:
        # The denominator is per page view, and one target is several of them: a
        # cart target opens the product page and the cart page too, and both are
        # tracked website pages, so both write the rows being counted. Counting
        # the loop would publish a figure short by a factor.
        driver = cart_driver(CountingContext({"website.track": 187, "website.visitor": 20}))
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "open.jsonl")
            with ambient_accounting(driver, RUN, Surface.PUBLIC, out, command="open"):
                for _ in range(3):
                    driver.navigations += 1
            summary = json.load(open(ambient_summary_path(out), encoding="utf-8"))
        self.assertEqual(summary["navigations"], 3)

    def test_navigations_before_the_window_are_not_in_the_figure(self) -> None:
        # The login navigates too, and it is counted like everything else -- what
        # keeps it out of the figure is that the window opens at the first
        # reading, which cannot be taken before there is a session.
        driver = cart_driver(CountingContext({"website.track": 1, "website.visitor": 1}))
        driver.navigations = 9
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "open.jsonl")
            with ambient_accounting(driver, RUN, Surface.PUBLIC, out, command="open"):
                driver.navigations += 2
            summary = json.load(open(ambient_summary_path(out), encoding="utf-8"))
        self.assertEqual(summary["navigations"], 2)

    def test_the_accounting_writes_the_summary_even_when_the_run_fails(self) -> None:
        # A run that died is exactly when what it left behind is worth knowing,
        # and the reading is taken on the way out rather than at the end of a
        # loop that may not be reached.
        driver = cart_driver(CountingContext({"website.track": 187, "website.visitor": 20}))
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "open.jsonl")
            with self.assertRaisesRegex(RuntimeError, "the screen would not load"):
                with ambient_accounting(driver, RUN, Surface.PUBLIC, out, command="open"):
                    driver.navigations += 1
                    raise RuntimeError("the screen would not load")
            summary = json.load(open(ambient_summary_path(out), encoding="utf-8"))
        self.assertEqual(summary["navigations"], 1)
        self.assertEqual(summary["models"]["website.track"]["delta"], 0)

    def test_a_driver_whose_reading_raises_does_not_take_the_run_with_it(self) -> None:
        # `ambient_reading` answers a reason per model rather than raising, so
        # this is the bound for a driver that does not -- the figure is worth a
        # run and not the other way round.
        class Dead:
            def ambient_reading(self):
                raise RuntimeError("the context was closed")

        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "open.jsonl")
            with ambient_accounting(Dead(), RUN, Surface.PUBLIC, out, command="open"):
                pass
            summary = json.load(open(ambient_summary_path(out), encoding="utf-8"))
        self.assertEqual(summary["navigations"], 0)
        self.assertIn("the context was closed", summary["models"]["website.track"]["unread"])

    def test_the_accounting_never_replaces_the_run_s_own_failure(self) -> None:
        # The summary is written in a `finally`, so a failure to write it would
        # otherwise swallow the exception the run was already raising.
        driver = cart_driver(CountingContext({"website.track": 187, "website.visitor": 20}))
        with self.assertRaisesRegex(RuntimeError, "the screen would not load"):
            with ambient_accounting(driver, RUN, Surface.PUBLIC,
                                    os.path.join("no", "such", "directory", "open.jsonl"), command="open"):
                raise RuntimeError("the screen would not load")

    def test_a_summary_that_could_not_be_written_fails_a_run_that_otherwise_passed(self) -> None:
        # A figure nobody wrote and nobody missed is the thing #256 exists to
        # stop, so on a run with no other failure the accounting is the failure.
        driver = cart_driver(CountingContext({"website.track": 187, "website.visitor": 20}))
        with self.assertRaises(OSError):
            with ambient_accounting(driver, RUN, Surface.PUBLIC,
                                    os.path.join("no", "such", "directory", "open.jsonl"), command="open"):
                pass

    def test_an_earlier_run_s_summary_is_not_left_beside_this_run_s_records(self) -> None:
        # The summary is written at the end, so a run whose write failed would
        # otherwise leave the last run's numbers beside fresh records under a
        # different `run_id` -- and a runner told to quote the file would quote
        # them. `out_path` is truncated before the first visit; so is this.
        driver = cart_driver(CountingContext({"website.track": RuntimeError("no session")}))
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "open.jsonl")
            stale = ambient_summary_path(out)
            with open(stale, "w", encoding="utf-8") as earlier:
                earlier.write(json.dumps({"run_id": "WOOW-PARITY-19700101T000000Z"}))
            with ambient_accounting(driver, RUN, Surface.PUBLIC, out, command="open"):
                self.assertFalse(os.path.exists(stale))
            self.assertEqual(json.load(open(stale, encoding="utf-8"))["run_id"], RUN.run_id)


class FakeNavigationRequest:
    """What Playwright hands a `request` listener, of the two fields read."""

    def __init__(self, url: str, resource_type: str = "document") -> None:
        self.url = url
        self.resource_type = resource_type


class FakeEventContext(FakeContext):
    """A context that registers `request` listeners and can fire them."""

    def __init__(self, *pages) -> None:
        super().__init__(*pages)
        self.listeners: dict[str, list] = {}

    def on(self, event: str, handler) -> None:
        self.listeners.setdefault(event, []).append(handler)

    def fire(self, url: str, resource_type: str = "document") -> None:
        for handler in self.listeners.get("request", []):
            handler(FakeNavigationRequest(url, resource_type))


class FakeSession:
    """A `Side`-shaped session: a context, a base, and one generic `rpc`.

    `e2e_parity_shared_layers_live.Side` is what the three hand-driven Live
    drivers hold, and `rpc(model, method, args)` is all of it the ambient figure
    uses. `answers` maps a model to the count its `search_count` reports, or to
    an exception the call raises.
    """

    def __init__(self, base: str, answers=None) -> None:
        self.base = base
        self.context = FakeEventContext()
        self.answers = dict(answers or {})
        self.calls: list[tuple] = []

    def rpc(self, model: str, method: str, args=None, kwargs=None):
        self.calls.append((model, method, args, kwargs))
        answer = self.answers.get(model)
        if isinstance(answer, Exception):
            raise answer
        return answer


def counts_for(**per_model) -> dict:
    """`FakeSession` answers for the two models, by their short names."""
    return {"website." + name: count for name, count in per_model.items()}


class SharedAmbientFigureTests(unittest.TestCase):
    """#264: the figure the hand-driven Live drivers read. No browser.

    `crawl` and `open` have had it since #256. Three drivers did not -- the
    markup family's, the peer snapshot's and the hand checks' -- and #243's run
    on 0.4.10 had to fall back to counting on the host afterwards and say in its
    evidence that no delta could be stated. These are the parts that made the
    figure readable off a session that is not a `SurfaceDriver`, and off a run
    that does not navigate through one call.
    """

    def test_a_boolean_is_not_a_count_of_one(self) -> None:
        # `True` is an `int` in Python, so a controller that answered a boolean
        # would be recorded as one row. One guard, in one place, shared by
        # `SurfaceDriver.count_rows` and `SessionAmbientDriver.count_rows`.
        self.assertEqual(validated_count("website.track", 187), 187)
        for refused in (True, False, "187", 1.0, None):
            with self.subTest(repr(refused)):
                with self.assertRaisesRegex(RuntimeError, "answered no count"):
                    validated_count("website.track", refused)

    def test_a_document_get_under_the_base_is_a_navigation(self) -> None:
        context = FakeEventContext()
        counter = NavigationCount(context, "http://ha.example:8123" + PREFIX)
        context.fire("http://ha.example:8123" + PREFIX + "/odoo/project.task/5")
        context.fire("http://ha.example:8123" + PREFIX + "/contactus")
        self.assertEqual(counter.navigations, 2)

    def test_what_a_page_asks_for_after_it_loaded_is_not_a_navigation(self) -> None:
        # The figure is per page view. A bundle, an image and the `call_kw` POST
        # that takes the reading itself are all requests under the same base, and
        # counting them would publish a denominator in the hundreds.
        context = FakeEventContext()
        counter = NavigationCount(context, "https://odoo.example")
        for resource in ("stylesheet", "script", "image", "xhr", "fetch", "websocket"):
            context.fire("https://odoo.example/web/assets/1/x." + resource, resource)
        self.assertEqual(counter.navigations, 0)

    def test_a_document_off_the_base_belongs_to_another_surface(self) -> None:
        # The Home Assistant panel page is a document on the HA origin and *not*
        # under the Ingress prefix: it is how the add-on is reached and not a page
        # Odoo served, so it writes none of the rows being counted.
        context = FakeEventContext()
        counter = NavigationCount(context, "http://ha.example:8123" + PREFIX)
        context.fire("http://ha.example:8123/woow-odoo-ce")
        context.fire("http://ha.example:8123/auth/authorize")
        context.fire("https://odoo.example/contactus")
        self.assertEqual(counter.navigations, 0)

    def test_the_base_is_read_per_request_because_ingress_learns_it_late(self) -> None:
        # `IngressSide.base` is the HA origin plus the prefix, and the prefix is
        # read off the iframe URL by `start()`. A base captured at construction
        # would be the origin alone, which matches every HA document too.
        session = FakeSession("http://ha.example:8123")
        counter = NavigationCount(session.context, lambda: session.base)
        session.context.fire("http://ha.example:8123" + PREFIX + "/odoo")
        self.assertEqual(counter.navigations, 1)
        session.base = "http://ha.example:8123" + PREFIX
        session.context.fire("http://ha.example:8123/woow-odoo-ce")
        self.assertEqual(counter.navigations, 1)

    def test_a_listener_that_raises_does_not_raise_inside_playwright(self) -> None:
        # The listener runs in Playwright's dispatch, on whatever call happened to
        # be waiting, so an accounting failure there would surface as a failure of
        # an unrelated step. Counting is worth a run and not the other way round.
        class Exploding:
            @property
            def base(self):
                raise RuntimeError("the frame went away")

        session = Exploding()
        context = FakeEventContext()
        counter = NavigationCount(context, lambda: session.base)
        context.fire("https://odoo.example/contactus")
        self.assertEqual(counter.navigations, 0)

    def test_the_counts_come_over_the_session_s_own_rpc(self) -> None:
        # #256's rule, which #264 carries to the drivers that are not the
        # adapter: a figure the run read itself is the run's own evidence, and one
        # read on the host over `ssh` afterwards is a different measurement.
        session = FakeSession("https://odoo.example", counts_for(track=187, visitor=20))
        reading = SessionAmbientDriver(session).ambient_reading()
        self.assertEqual(reading.counts, {"website.track": 187, "website.visitor": 20})
        self.assertEqual(reading.unread, {})
        self.assertEqual(session.calls, [("website.track", "search_count", [[]], None),
                                         ("website.visitor", "search_count", [[]], None)])

    def test_the_count_passes_through_the_read_only_seam(self) -> None:
        # A request a driver makes belongs in the `Operation` enum rather than
        # beside it, and this one is the same request `SurfaceDriver.count_rows`
        # makes -- a domain in, an integer out.
        self.assertIn(Operation.COUNT_ROWS, NON_MUTATING_OPERATIONS)
        session = FakeSession("https://odoo.example", counts_for(track=1, visitor=1))
        without = OperationPolicy(allowed=NON_MUTATING_OPERATIONS - {Operation.COUNT_ROWS})
        with mock.patch("e2e_menu_action_adapter.READ_ONLY_POLICY", without):
            with self.assertRaises(PermissionError):
                SessionAmbientDriver(session).count_rows("website.track")
            # And the reading still answers a reason per model rather than
            # raising: the policy is a seam and not a second failure mode.
            self.assertIn("mutating or unknown",
                          SessionAmbientDriver(session).ambient_reading().unread["website.track"])

    def test_a_count_that_is_not_a_number_is_refused_here_too(self) -> None:
        session = FakeSession("https://odoo.example", counts_for(track=True, visitor=20))
        reading = SessionAmbientDriver(session).ambient_reading()
        self.assertEqual(reading.counts, {"website.visitor": 20})
        self.assertIn("answered no count", reading.unread["website.track"])

    def test_one_reason_per_model_and_not_one_per_reading(self) -> None:
        # A database without `website` has neither model and reports two reasons;
        # a session that lost one answer still reports the count it got.
        session = FakeSession("https://odoo.example",
                              {"website.track": RuntimeError("Object website.track doesn't exist"),
                               "website.visitor": 20})
        reading = SessionAmbientDriver(session).ambient_reading()
        self.assertEqual(reading.counts, {"website.visitor": 20})
        self.assertIn("doesn't exist", reading.unread["website.track"])

    def test_a_reason_is_masked_before_it_reaches_the_record(self) -> None:
        # The record is quoted in a pull request and a raw Playwright message
        # carries the host and the Ingress prefix.
        session = FakeSession("https://odoo.example",
                              {"website.track": RuntimeError("connect to https://odoo.example failed")})
        masker = Masker(bases={"<PUBLIC_BASE>": "https://odoo.example"}, ingress_prefix=None, secrets=())
        reading = SessionAmbientDriver(session, mask=masker.text).ambient_reading()
        self.assertNotIn("odoo.example", reading.unread["website.track"])
        self.assertIn("<PUBLIC_BASE>", reading.unread["website.track"])

    def test_the_counts_come_over_the_first_session_and_the_navigations_over_both(self) -> None:
        # The two models are database-wide, so one session's count is the figure
        # and `surface` says which took it. The denominator is both sessions': a
        # delta over a database-wide count cannot be split between two sessions
        # that were open at once, so counting one of them would publish a
        # fraction of the window's own page views.
        first = FakeSession("http://ha.example:8123" + PREFIX, counts_for(track=187, visitor=20))
        second = FakeSession("https://odoo.example", counts_for(track=999, visitor=999))
        figure = SessionAmbientDriver(first, second)
        self.assertEqual(figure.ambient_reading().counts, {"website.track": 187, "website.visitor": 20})
        self.assertEqual(second.calls, [])
        first.context.fire("http://ha.example:8123" + PREFIX + "/odoo/project.task/5")
        second.context.fire("https://odoo.example/odoo/project.task/5")
        second.context.fire("https://odoo.example/odoo/project.task/5")
        self.assertEqual(figure.navigations, 3)

    def test_a_driver_that_already_has_a_reading_hands_it_in(self) -> None:
        # The hand checks hold a `SurfaceDriver`, whose `ambient_reading` is the
        # same count through its own request context. What it does not have is a
        # navigation denominator that sees a click, which is the half it takes
        # from here -- so there is one implementation of the count and not two.
        session = FakeSession("https://odoo.example", counts_for(track=1, visitor=1))
        figure = SessionAmbientDriver(session, reading=lambda: counted(**{"website.track": 5}))
        self.assertEqual(figure.ambient_reading().counts, {"website.track": 5})
        self.assertEqual(session.calls, [])

    def test_a_figure_needs_a_session_to_be_read_over(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one session"):
            SessionAmbientDriver()

    def test_the_two_denominators_are_named_in_the_file_that_carries_them(self) -> None:
        # Both are page views and neither is the other, so a reader comparing one
        # driver's `navigations` with another's needs the sentence beside the
        # number. The default is this driver's own.
        self.assertNotEqual(AMBIENT_BASIS_GOTO, AMBIENT_BASIS_DOCUMENTS)
        self.assertIn("SurfaceDriver._goto", AMBIENT_BASIS_GOTO)
        self.assertIn("document GET", AMBIENT_BASIS_DOCUMENTS)
        self.assertIn("upper bound", AMBIENT_BASIS_DOCUMENTS)
        empty = AmbientReading()
        self.assertEqual(ambient_summary(RUN, Surface.PUBLIC, command="open", navigations=0,
                                         before=empty, after=empty)["navigation_basis"],
                         AMBIENT_BASIS_GOTO)
        said = ambient_summary(RUN, Surface.PUBLIC, command="visit", navigations=1,
                               before=empty, after=empty,
                               navigation_basis=AMBIENT_BASIS_DOCUMENTS)
        self.assertEqual(said["navigation_basis"], AMBIENT_BASIS_DOCUMENTS)

    def test_a_surface_key_says_a_run_that_drove_both_in_one_go(self) -> None:
        # The peer snapshot's run is a pair, not a surface, and `_SURFACE_KEY` has
        # two entries because an adapter run is one surface. The trap is that
        # `Surface` is a `str` subclass, so a `isinstance(surface, str)` test would
        # pass for both and write `ha_ingress` where every record says `ingress`.
        self.assertIsInstance(Surface.HA_INGRESS, str)
        empty = AmbientReading()
        for surface, key in ((Surface.HA_INGRESS, "ingress"), (Surface.PUBLIC, "public"),
                             ("ingress-public", "ingress-public"), ("ingress-ingress", "ingress-ingress")):
            with self.subTest(surface):
                self.assertEqual(ambient_summary(RUN, surface, command="run", navigations=0,
                                                 before=empty, after=empty)["surface"], key)

    def test_a_driver_whose_records_append_appends_its_figure(self) -> None:
        # `markup.jsonl` carries 38 records taken over a whole session, and
        # `peer.jsonl` one per pair. Truncating the figure there would leave the
        # last invocation's numbers standing for every invocation's rows.
        driver = cart_driver(CountingContext(counts_for(track=187, visitor=20)))
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "markup.jsonl")
            for navigations in (1, 2):
                with ambient_accounting(driver, RUN, Surface.PUBLIC, out, command="media-image-website",
                                        append=True, navigation_basis=AMBIENT_BASIS_DOCUMENTS):
                    driver.navigations += navigations
            with open(ambient_summary_path(out), encoding="utf-8") as written:
                lines = [json.loads(line) for line in written if line.strip()]
        self.assertEqual([line["navigations"] for line in lines], [1, 2])
        self.assertEqual(os.path.basename(ambient_summary_path(out)), "markup.ambient.json")

    def test_an_appending_driver_does_not_clear_the_earlier_invocations(self) -> None:
        # The clearing exists because this driver truncates `out_path` per run, so
        # a stale figure would sit beside fresh records. An appending driver's
        # earlier lines are earlier invocations' figures, which are not stale.
        driver = cart_driver(CountingContext(counts_for(track=1, visitor=1)))
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "peer.jsonl")
            with open(ambient_summary_path(out), "w", encoding="utf-8") as earlier:
                earlier.write(json.dumps({"run_id": "WOOW-PEER-20261002T015318Z"}) + "\n")
            with ambient_accounting(driver, RUN, Surface.PUBLIC, out, command="run", append=True):
                pass
            with open(ambient_summary_path(out), encoding="utf-8") as written:
                lines = [json.loads(line) for line in written if line.strip()]
        self.assertEqual([line["run_id"] for line in lines],
                         ["WOOW-PEER-20261002T015318Z", RUN.run_id])

    def test_every_figure_file_is_read_one_json_object_per_line(self) -> None:
        # The name is the one #256 gave it and #264 asked for, and an appending
        # driver puts more than one object in it -- so the file is read a line at a
        # time and this driver's is the *one-line* case of that reader, not a
        # second format under the same extension. A `json.load` over the whole file
        # is right only where the records truncate, which is why every document
        # that tells a runner to keep the file says "one JSON object per line".
        driver = cart_driver(CountingContext(counts_for(track=1, visitor=1)))
        with tempfile.TemporaryDirectory() as directory:
            truncating, appending = (os.path.join(directory, name)
                                     for name in ("ingress-open.jsonl", "markup.jsonl"))
            for _ in range(2):
                with ambient_accounting(driver, RUN, Surface.PUBLIC, truncating, command="open"):
                    pass
                with ambient_accounting(driver, RUN, Surface.PUBLIC, appending, command="codeview",
                                        append=True):
                    pass
            lines = {}
            for path in (truncating, appending):
                with open(ambient_summary_path(path), encoding="utf-8") as written:
                    lines[path] = [json.loads(line) for line in written if line.strip()]
            self.assertEqual(len(lines[truncating]), 1)
            self.assertEqual(len(lines[appending]), 2)
            # The one-line file is the only one a whole-file read may be used on.
            with open(ambient_summary_path(truncating), encoding="utf-8") as whole:
                self.assertEqual(json.load(whole), lines[truncating][0])
        for read in lines.values():
            with self.subTest(len(read)):
                self.assertEqual({line["schema"] for line in read}, {AMBIENT_SCHEMA})

    def test_a_subcommand_that_keeps_no_records_prints_the_figure(self) -> None:
        # The peer snapshot's `probe` writes no file, so there is nothing for the
        # figure to sit beside -- and it is still read, because "it writes nothing"
        # is a claim about the field and never about the rows a page view leaves.
        driver = cart_driver(CountingContext(counts_for(track=187, visitor=187)))
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            with ambient_accounting(driver, RUN, "ingress-public", None, command="probe"):
                driver.navigations += 2
        self.assertIn("website.track +0", said.getvalue())
        self.assertIn("2 navigation(s)", said.getvalue())
        self.assertIn("writes no records", said.getvalue())

# --------------------------------------------------------------------------
# The decision record: what a "read-only" run bounds, and what it does not.
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
ADR_0012 = REPO / "docs/adr/0012-sweeps-verify-on-the-test-host.md"
LIVE_TIER = REPO / "docs/agents/live-tier.md"
ADAPTER = ROOT / "tests/e2e_menu_action_adapter.py"
PLAN = REPO / "docs/testing/INGRESS_VS_PUBLIC_PARITY.md"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def collapsed(body: str) -> str:
    """`body` with its line wrapping collapsed, so a quoted sentence matches
    wherever the paragraph it lives in happens to break."""
    return " ".join(body.split())


def section(document: str, heading: str) -> str:
    """The one `## <heading>` section of a markdown document, wrapping collapsed.

    Two sections of that heading, or none, is the failure -- a document that
    says a thing twice has two copies to keep in step.
    """
    found = [part for part in document.split("\n## ") if part.startswith(heading)]
    assert len(found) == 1, "expected exactly one %r section, found %d" % (heading, len(found))
    return collapsed(found[0])


def github_anchor(heading: str) -> str:
    """GitHub's fragment for a markdown heading: lowercased, punctuation
    dropped, spaces hyphenated. Lets a test derive a cross-document link's
    anchor from the heading it points at instead of spelling it twice."""
    kept = [char for char in heading.lower() if char.isalnum() or char in " -_"]
    return "".join(kept).strip().replace(" ", "-")


class ReadOnlyBoundaryRecordTests(unittest.TestCase):
    """#227: the two writes no route list can bound are recorded, not re-derived."""

    def postscript(self) -> str:
        """The #227 postscript alone, wrapping collapsed."""
        return section(text(ADR_0012), "Postscript (2026-10-01, #227)")

    def test_the_record_says_read_only_means_no_business_writes_not_zero_rows(self) -> None:
        # The phrase this postscript exists to stop over-promising: ADR 0012's
        # own body says the standing permission "covered read-only Live runs
        # only", and a crawl of a website page has never been zero-write.
        tail = self.postscript().lower()
        self.assertIn("no business writes", tail)
        self.assertIn("zero rows", tail)

    def test_the_record_cites_both_mechanisms_where_they_were_read(self) -> None:
        # Both were read out of the pinned `.deb` during #212's audit. A
        # statement with no citation is one the next sweep has to re-derive.
        tail = self.postscript()
        self.assertIn("ir_http.py:203", tail)             # visitor tracking, any tracked page
        self.assertIn("templates.xml:13", tail)           # the header cart link's own write
        self.assertIn("/shop/products/recently_viewed_update", tail)   # the page's own JS

    def test_the_record_says_which_subcommand_each_write_reaches(self) -> None:
        # `crawl` navigates only `/odoo/action-<id>`, whose response is the web
        # client bootstrap and not a tracked page, so the tracking write is
        # `open`'s alone. Worth the sentence: the Issue that asked for this
        # record had it the other way round.
        tail = self.postscript()
        # Every driver that opens a website page makes the tracking write, so
        # the record names the hand-check driver beside `open` -- its `visit` is
        # the run that exists to make it. A review round caught the first
        # version calling it `open`'s alone.
        self.assertIn("the adapter's `open` with a website target", tail)
        self.assertIn("e2e_ingress_hand_checks.py", tail)
        self.assertIn("`crawl` is the exception", tail)
        self.assertIn("/odoo/action-<id>", tail)
        self.assertIn("a crawl never makes it", tail)

    def test_the_original_decision_is_untouched(self) -> None:
        adr = collapsed(text(ADR_0012))
        self.assertIn("an Iteration of a Sweep may deploy to the test host and run "
                      "Live-tier checks that write, without asking first", adr)
        self.assertIn("**Data a run creates is named after the run.**", adr)
        self.assertIn("## Postscript (2026-10-01, #228)", adr)
        # The postscripts are appended in the order they were decided.
        self.assertLess(adr.index("## Postscript (2026-10-01, #228)"),
                        adr.index("## Postscript (2026-10-01, #227)"))

    def test_the_route_list_points_at_the_record_rather_than_carrying_it(self) -> None:
        # #227's second acceptance criterion, as something a test can hold: the
        # route list names the writes and sends the reader to the record, and
        # the reasoning lives in the record rather than in both places.
        adapter = collapsed(text(ADAPTER))
        self.assertIn("docs/adr/0012-sweeps-verify-on-the-test-host.md", adapter)
        self.assertIn("ir_http.py:203", adapter)
        # What moved out, so the only copy is not back in the comment: the
        # reasoning about why bounding the tracking write would be a decision
        # about the guarantee as a whole.
        for moved in ("the read-only guarantee as a whole",
                      "would mean bounding every website page"):
            with self.subTest(moved):
                self.assertNotIn(moved, adapter)
                self.assertIn(moved, collapsed(text(ADR_0012)))

    def test_the_operational_half_points_at_the_same_record(self) -> None:
        # An operator reading what a run leaves behind on the host finds the
        # ambient rows there, not only in a test module's comment. The anchor is
        # derived from the heading rather than spelled a second time, so
        # rewording the heading fails here instead of leaving a link that
        # silently lands at the top of the ADR.
        heading = "Postscript (2026-10-01, #227)"
        self.assertIn("\n## %s\n" % heading, text(ADR_0012))
        live = text(LIVE_TIER)
        self.assertIn("website.track", live)
        self.assertIn("0012-sweeps-verify-on-the-test-host.md#%s" % github_anchor(heading), live)


class AmbientWriteAccountingRecordTests(unittest.TestCase):
    """#256: the per-run figure exists, and the documents say where to read it."""

    def test_the_boundary_record_points_at_the_figure_not_forward_at_an_issue(self) -> None:
        # #227 split this feature out and its postscript has carried the forward
        # reference since. A record that still says the figure is owed sends a
        # reader looking for an Issue where there is now a file.
        said = section(text(ADR_0012), "Postscript (2026-10-01, #227)")
        self.assertIn("ambient.json", said)
        self.assertIn("#256", said)
        self.assertNotIn("is a feature with an Issue of its own", said)
        self.assertNotIn("not part of this statement", said)

    def test_a_runner_is_told_to_keep_the_figure_with_the_evidence(self) -> None:
        # Where a runner looks before writing an evidence README, which is where
        # #227 put the operational half of the same boundary.
        live = collapsed(text(LIVE_TIER))
        self.assertIn("ambient.json", live)
        self.assertIn("#256", live)

    def test_the_plan_declares_the_schema_and_says_it_is_not_judged(self) -> None:
        # Section 12 declares every schema a run writes, and this one needs the
        # same carve-out `woow.peer-snapshot.v1` has: the conservation tally is
        # over control identities with verdicts, and a count delta is neither.
        plan = collapsed(text(PLAN))
        self.assertIn("`%s`" % AMBIENT_SCHEMA, plan)
        self.assertIn("`diff` 不讀它", plan)
        self.assertIn("不佔守恆檢查的分母", plan)

    def test_every_navigation_the_driver_makes_goes_through_one_chokepoint(self) -> None:
        # The figure is only as good as the chokepoint: a `page.goto` written
        # beside `_goto` would leave the denominator short while looking right,
        # and a navigation to a tracked page is exactly what writes the rows the
        # delta counts. Prose names the method without its parentheses.
        calls = [line.strip() for line in text(ADAPTER).splitlines()
                 if "page.goto(" in line and not line.strip().startswith("#")]
        self.assertEqual(calls, ["page.goto(self.base + route, **kwargs)"])

    def test_the_documents_spell_the_summary_s_name_the_way_it_is_built(self) -> None:
        # The extension is replaced, not appended, so `<out>.ambient.json` read
        # literally sends a reader looking for `public.jsonl.ambient.json`. Every
        # document carries the worked example instead, derived from the function.
        example = ambient_summary_path("ingress-open.jsonl")
        for document in (ADR_0012, LIVE_TIER, PLAN, ADAPTER):
            with self.subTest(document.name):
                self.assertIn(example, text(document))

    def test_the_figure_is_accounted_for_where_the_run_is_driven(self) -> None:
        # The driver says what the number is and what it is not, so the sentence
        # is not only in the documents a reader of the file may not have open.
        adapter = collapsed(text(ADAPTER))
        self.assertIn("ambient.json", adapter)
        self.assertIn("Counts only", adapter)


if __name__ == "__main__":
    unittest.main()
