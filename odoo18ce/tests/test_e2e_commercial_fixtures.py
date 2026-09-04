#!/usr/bin/env python3
"""Self-tests for the offline commercial fixture ledger."""
import json
import stat
import tempfile
import unittest
from pathlib import Path

from e2e_commercial_fixtures import (
    BaselineSnapshot,
    FixtureLedger,
    FixtureRecord,
    FixtureState,
    LedgerError,
    create_run_id,
    safe_artifact_name,
    sanitize_artifact,
)


class CommercialFixtureLedgerTest(unittest.TestCase):
    def setUp(self):
        self.ledger = FixtureLedger.create(BaselineSnapshot("before-commercial", ("product.template", "sale.order")))

    def fixture(self, fixture_id, dependencies=(), state=FixtureState.DECLARED, **metadata):
        return FixtureRecord(fixture_id, "demo.resource", self.ledger.marker, tuple(dependencies), state, metadata)

    def test_run_id_is_unique_and_marker_owned(self):
        self.assertNotEqual(create_run_id(), create_run_id())
        self.assertTrue(self.ledger.marker.endswith(self.ledger.run_id))
        with self.assertRaises(LedgerError):
            self.ledger.add_fixture(FixtureRecord("foreign", "resource", "another-run"))

    def test_sanitizer_redacts_nested_artifact_data(self):
        value = sanitize_artifact({"password": "not-stored", "nested": {"Authorization": "Bearer value"}, "url": "https://example.test/a?code=value", "ingress": "/api/hassio_ingress/value/odoo"})
        self.assertEqual("<redacted>", value["password"])
        self.assertEqual("<redacted>", value["nested"]["Authorization"])
        self.assertEqual("https://example.test/a?<redacted>", value["url"])
        self.assertEqual("/api/hassio_ingress/<redacted>/odoo", value["ingress"])
        self.assertEqual("password=<redacted>", sanitize_artifact("password=not-stored"))
        self.assertEqual("ledger.json", safe_artifact_name("../ledger", ".json"))

    def test_graph_rejects_unknown_and_cyclic_dependencies(self):
        self.ledger.add_fixture(self.fixture("orphan", ("missing",)))
        with self.assertRaisesRegex(LedgerError, "unknown dependencies"):
            self.ledger.validate_graph()

        cyclic = FixtureLedger.create(BaselineSnapshot("before", ("x",)))
        cyclic.add_fixture(FixtureRecord("a", "resource", cyclic.marker, ("b",)))
        cyclic.add_fixture(FixtureRecord("b", "resource", cyclic.marker, ("a",)))
        with self.assertRaisesRegex(LedgerError, "dependency cycle"):
            cyclic.validate_graph()

    def test_cleanup_requires_dependents_first_and_allows_valid_order(self):
        self.ledger.add_fixture(self.fixture("category"))
        self.ledger.add_fixture(self.fixture("product", ("category",), FixtureState.MATERIALIZED))
        self.ledger.add_fixture(self.fixture("line", ("product",), FixtureState.MATERIALIZED))
        plan = self.ledger.plan_cleanup()
        self.assertEqual(["line", "product", "category"], [action.fixture_id for action in plan.actions])
        self.assertTrue(all(item.state == FixtureState.CLEANUP_PLANNED for item in self.ledger.fixtures.values()))
        with self.assertRaisesRegex(LedgerError, "cannot be cleaned before dependents: \['product'\]"):
            self.ledger.transition("category", FixtureState.CLEANED)
        with self.assertRaisesRegex(LedgerError, "cannot be cleaned before dependents: \['line'\]"):
            self.ledger.transition("product", FixtureState.CLEANED)
        self.ledger.transition("line", FixtureState.CLEANED)
        self.ledger.transition("product", FixtureState.CLEANED)
        self.ledger.transition("category", FixtureState.CLEANED)
        self.assertTrue(all(item.state == FixtureState.CLEANED for item in self.ledger.fixtures.values()))
        with self.assertRaisesRegex(LedgerError, "invalid transition"):
            self.ledger.transition("line", FixtureState.CLEANUP_PLANNED)

    def test_marker_scan_and_lane_request_are_instructions_only(self):
        self.ledger.add_fixture(self.fixture("product"))
        request = self.ledger.lane_request(("product.template", "sale.order"))
        self.assertEqual(self.ledger.marker, request.marker_scan.marker)
        self.assertEqual(("product.template", "sale.order"), request.marker_scan.resource_types)
        with self.assertRaises(LedgerError):
            self.ledger.plan_marker_scan(())

    def test_json_persistence_is_sanitized_and_round_trips(self):
        self.ledger.add_fixture(self.fixture("order", token="should-not-persist", url="https://example.test/callback?state=value"))
        with tempfile.TemporaryDirectory() as directory:
            path = self.ledger.persist(directory, "../commercial-ledger")
            self.assertEqual(Path(directory), path.parent)
            self.assertEqual("commercial-ledger.json", path.name)
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("should-not-persist", text)
            self.assertNotIn("state=value", text)
            self.assertEqual(1, json.loads(text)["schema_version"])
            restored = FixtureLedger.load(path)
            self.assertEqual(self.ledger.run_id, restored.run_id)
            self.assertEqual(FixtureState.DECLARED, restored.fixtures["order"].state)


if __name__ == "__main__":
    unittest.main()
