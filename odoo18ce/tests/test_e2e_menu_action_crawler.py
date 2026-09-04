#!/usr/bin/env python3
"""Pure self-tests for the credential-free menu/action/view crawler contracts."""
import unittest

from e2e_menu_action_crawler import (
    ActionRecord,
    FailureClass,
    MANIFEST_SCHEMA_VERSION,
    Manifest,
    MenuRecord,
    NON_MUTATING_OPERATIONS,
    Operation,
    OperationPolicy,
    Surface,
    ViewRecord,
    classify_failure,
    normalize_route,
    plan_traversal,
    reconcile_parity,
    sanitize_diagnostic,
)


def sample_manifest() -> Manifest:
    return Manifest(
        menus=(
            MenuRecord("root", "Root", action_id="root_action", sequence=2),
            MenuRecord("child", "Child", parent_id="root", action_id="child_action"),
            MenuRecord("grandchild", "Grandchild", parent_id="child", action_id="grand_action"),
            MenuRecord("deep", "Deep", parent_id="grandchild", action_id="deep_action"),
        ),
        actions=(
            ActionRecord("root_action", "Root action", "/odoo"),
            ActionRecord("child_action", "Child action", "/odoo/contacts", ("form",)),
            ActionRecord("grand_action", "Grand action", "/odoo/sales"),
            ActionRecord("deep_action", "Deep action", "/odoo/deep"),
        ),
        views=(ViewRecord("form", "Contact form", "res.partner", "form"),),
    )


class RouteTests(unittest.TestCase):
    def test_surface_routes_normalize_to_same_query_free_logical_route(self) -> None:
        public = normalize_route("/odoo/sales?debug=1&db=hidden#view", Surface.PUBLIC)
        ingress = normalize_route(
            "/api/hassio_ingress/token_123/odoo/sales?code=secret&state=secret#view",
            Surface.HA_INGRESS,
            ingress_prefix="/api/hassio_ingress/token_123",
        )
        self.assertEqual(public, ingress)
        self.assertEqual(public.as_string(), "/odoo/sales#view")
        self.assertNotIn("debug=1", public.as_string())
        self.assertNotIn("hidden", public.as_string())
        self.assertNotIn("secret", ingress.as_string())

    def test_surface_boundaries_and_unsafe_paths_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_route("/api/hassio_ingress/token/odoo", Surface.PUBLIC)
        with self.assertRaises(ValueError):
            normalize_route("/odoo", Surface.HA_INGRESS, ingress_prefix="/api/hassio_ingress/token")
        with self.assertRaises(ValueError):
            normalize_route("https://example.invalid/odoo", Surface.PUBLIC)
        with self.assertRaises(ValueError):
            normalize_route("/odoo/%2e%2e/web", Surface.PUBLIC)
        self.assertEqual("/odoo", normalize_route("/odoo?access_token=secret", Surface.PUBLIC).as_string())


class ManifestAndPlanningTests(unittest.TestCase):
    def test_normalized_schema_is_deterministic_surface_and_query_free(self) -> None:
        manifest = sample_manifest()
        normalized = manifest.normalized()
        self.assertEqual(normalized["schema_version"], MANIFEST_SCHEMA_VERSION)
        self.assertEqual([item["id"] for item in normalized["menus"]], ["child", "deep", "grandchild", "root"])
        self.assertNotIn("surface", str(normalized))
        self.assertNotIn("api/hassio_ingress", str(normalized))
        self.assertNotIn("?", str(normalized))
        for query in ("?code=oauth-secret", "?state=opaque", "?db=private-db"):
            with self.assertRaisesRegex(ValueError, "normalized"):
                Manifest(actions=(ActionRecord("query", "Query", "/odoo" + query),))

    def test_plan_is_read_only_ordered_and_limited_to_depth_three(self) -> None:
        plan = plan_traversal(sample_manifest())
        self.assertEqual([(visit.menu_id, visit.depth) for visit in plan.visits], [
            ("root", 0), ("child", 1), ("grandchild", 2), ("deep", 3),
        ])
        self.assertTrue(all(visit.operations == NON_MUTATING_OPERATIONS for visit in plan.visits))
        with self.assertRaises(ValueError):
            plan_traversal(sample_manifest(), max_depth=4)
        with self.assertRaises(PermissionError):
            OperationPolicy().require("write")  # type: ignore[arg-type]

    def test_cycles_and_bad_references_are_rejected(self) -> None:
        cyclic = Manifest(menus=(MenuRecord("a", "A", parent_id="b"), MenuRecord("b", "B", parent_id="a")))
        with self.assertRaisesRegex(ValueError, "cyclic"):
            plan_traversal(cyclic)
        with self.assertRaisesRegex(ValueError, "menu action"):
            Manifest(menus=(MenuRecord("a", "A", action_id="missing"),))


class FailureSanitizationAndParityTests(unittest.TestCase):
    def test_failure_classification(self) -> None:
        self.assertEqual(classify_failure("HTTP 403 forbidden"), FailureClass.AUTH)
        self.assertEqual(classify_failure("Frame was detached"), FailureClass.FRAME)
        self.assertEqual(classify_failure("missing environment ODOO_BASE_URL"), FailureClass.HARNESS)
        self.assertEqual(classify_failure("unexpected 500 traceback"), FailureClass.PRODUCT)

    def test_sanitization_redacts_nested_secrets_and_bearer_values(self) -> None:
        diagnostic = sanitize_diagnostic({
            "Authorization": "Bearer real-secret",
            "headers": {"authorization": "Basic another-secret"},
            "url": "https://ha.invalid/api/hassio_ingress/actual-token/odoo?code=secret",
            "nested": ["/api/hassio_ingress/another-token/web?state=secret"],
            "message": "upstream sent Bearer standalone-secret; retry denied",
        })
        self.assertEqual(diagnostic["Authorization"], "<redacted>")
        self.assertEqual(diagnostic["headers"]["authorization"], "<redacted>")
        self.assertEqual("Bearer <redacted>", sanitize_diagnostic("Bearer standalone-secret"))
        self.assertNotIn("actual-token", str(diagnostic))
        self.assertNotIn("another-token", str(diagnostic))
        self.assertNotIn("code=secret", str(diagnostic))
        self.assertNotIn("standalone-secret", str(diagnostic))
        self.assertIn("<redacted>", str(diagnostic))

    def test_parity_compares_logical_records(self) -> None:
        public = sample_manifest()
        self.assertTrue(reconcile_parity(public, sample_manifest()).matches)
        changed = Manifest(
            menus=public.menus,
            actions=public.actions[:-1] + (ActionRecord("deep_action", "Deep action", "/odoo/changed"),),
            views=public.views,
        )
        result = reconcile_parity(public, changed)
        self.assertFalse(result.matches)
        self.assertEqual([(item.record_type, item.record_id) for item in result.differences], [("action", "deep_action")])


if __name__ == "__main__":
    unittest.main()
