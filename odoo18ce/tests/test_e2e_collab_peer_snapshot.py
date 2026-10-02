#!/usr/bin/env python3
"""Static-tier tests for the pure parts of the peer-snapshot run (#234).

Nothing here opens a browser or a websocket, and nothing reads credentials.
What it does cover is everything the run decides *about* a value: the prefix
shape it looks for, the redaction that keeps a Supervisor token out of the
evidence, the verdict #234's criteria escalate on, and the report that says so.

The run itself is unrun -- #243 owns the measurement -- so these are the only
executed statements the script has, and the redaction is the one that matters
most: the record it writes exists to say *whose* prefix reached the field, and
getting that wrong means either an unreadable record or a token in the
repository.
"""
import json
import re
import unittest
from pathlib import Path

from e2e_collab_peer_snapshot_live import (
    CLEAN,
    EVIDENCE_SCHEMA,
    FOREIGN_PREFIX_STORED,
    INGRESS_PREFIX_SHAPE,
    NOT_RUN,
    OWN_PREFIX_STORED,
    PAIRS,
    UNKNOWN_PREFIX_STORED,
    classify,
    evidence_record,
    ingress_prefixes,
    redact,
    report,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "rootfs/etc/nginx/nginx.conf.template"
PARITY_PLAN = Path(__file__).resolve().parents[2] / "docs/testing/INGRESS_VS_PUBLIC_PARITY.md"

# Documentation-only tokens of the length Supervisor's `secrets.token_urlsafe`
# default produces (43 characters of the class the gateway accepts).
TOKEN_A = "Hs3-kQ9fR2tV7wXz_bC4dE6gJ8mN1pS5uY0aL2oZ4qT"
TOKEN_B = "Zq7_mB2xT5yD8hJ1kL4nP6rS9vW0cF3gN5tQ8uX1zA6"
TOKEN_C = "Nf1-tR8wY2bK5mD9pL3sV6xA0cJ7hQ4uZ8eG1nT5oW2"
PREFIX_A = "/api/hassio_ingress/" + TOKEN_A
PREFIX_B = "/api/hassio_ingress/" + TOKEN_B
PREFIX_C = "/api/hassio_ingress/" + TOKEN_C
PICTURE = "/project_todo/static/img/todo_access.png"
LABELS = {PREFIX_A: "A", PREFIX_B: "B"}


class PrefixShapeTests(unittest.TestCase):
    def test_the_shape_is_the_gateways_own(self):
        """Derived from the template, so the run cannot measure a shape the
        add-on does not serve. The gateway's map is the authority (ADR 0004);
        the markup strip of #234 reads it too, and
        `test_ingress_peer_snapshot_prefix.py` holds that pair together."""
        gateway = re.search(
            r'"~\^(/api/hassio_ingress/\[[^\]]+\]\{\d+,\d+\})\$"\s+\$http_x_ingress_path;',
            TEMPLATE.read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(gateway, "the $safe_ingress_path map must state the prefix shape")
        self.assertEqual(
            INGRESS_PREFIX_SHAPE.pattern,
            gateway.group(1) + "(?![A-Za-z0-9_-])",
            "the run must look for the prefix shape the gateway validates, plus the "
            "lookahead that refuses a token longer than it accepts",
        )

    def test_every_distinct_prefix_in_order(self):
        value = '<img src="%s%s"/><img src="%s%s"/><a href="%s/web">x</a>' % (
            PREFIX_B, PICTURE, PREFIX_A, PICTURE, PREFIX_B)
        self.assertEqual(ingress_prefixes(value), [PREFIX_B, PREFIX_A])

    def test_what_is_not_a_prefix(self):
        for value in (
            "",
            '<img src="%s"/>' % PICTURE,
            # Short of the bound, over it, and a character the class refuses.
            "/api/hassio_ingress/" + "x" * 15,
            "/api/hassio_ingress/" + "x" * 129,
            "/api/hassio_ingress/" + "x" * 8 + "." + "x" * 8,
            "/api/hassio_ingres/" + TOKEN_A,
            "<p>served under /api/hassio_ingress/ and nowhere else</p>",
        ):
            self.assertEqual(ingress_prefixes(value), [], value)

    def test_a_token_at_the_bound_is_taken_whole(self):
        """The same rule the strip has: a token over the bound is left alone
        rather than matched to the bound, so a report never shows half a
        token joined to the path after it."""
        self.assertEqual(ingress_prefixes("/api/hassio_ingress/" + "x" * 128),
                         ["/api/hassio_ingress/" + "x" * 128])
        self.assertEqual(ingress_prefixes("/api/hassio_ingress/" + "x" * 129), [])


class RedactionTests(unittest.TestCase):
    def test_a_prefix_becomes_the_label_of_the_session_it_belongs_to(self):
        value = '<img src="%s%s"/>' % (PREFIX_A, PICTURE)
        self.assertEqual(
            redact(value, LABELS),
            '<img src="/api/hassio_ingress/<ingress:A>%s"/>' % PICTURE,
        )

    def test_a_prefix_no_session_claims_is_still_never_printed(self):
        value = '<img src="%s%s"/>' % (PREFIX_C, PICTURE)
        redacted = redact(value, LABELS)
        self.assertNotIn(TOKEN_C, redacted)
        self.assertEqual(redacted,
                         '<img src="/api/hassio_ingress/<ingress:unknown>%s"/>' % PICTURE)

    def test_no_token_survives_anywhere_in_a_record(self):
        record = evidence_record(
            run_id="WOOW-PEER-20261001T000000Z", database="odoo_parity", target="local",
            pair="ingress-ingress", task_id=5,
            prefixes={"A": PREFIX_A, "B": PREFIX_B},
            transport={"delivered": True},
            stored='<img src="%s%s"/><img src="%s%s"/>' % (PREFIX_A, PICTURE, PREFIX_C, PICTURE),
            labels=LABELS, saver="B",
        )
        text = json.dumps(record)
        for token in (TOKEN_A, TOKEN_B, TOKEN_C):
            self.assertNotIn(token, text, "a Supervisor token must never reach the evidence")

    def test_structures_are_walked_and_other_values_untouched(self):
        self.assertEqual(redact({"a": [PREFIX_A], "b": 7, "c": None}, LABELS),
                         {"a": ["/api/hassio_ingress/<ingress:A>"], "b": 7, "c": None})


class VerdictTests(unittest.TestCase):
    def test_a_clean_value(self):
        self.assertEqual(classify('<img src="%s"/>' % PICTURE, LABELS, "B"), (CLEAN, []))

    def test_another_sessions_prefix_is_the_hole_issue_234_is_about(self):
        verdict, present = classify('<img src="%s%s"/>' % (PREFIX_A, PICTURE), LABELS, "B")
        self.assertEqual((verdict, present), (FOREIGN_PREFIX_STORED, ["A"]))

    def test_the_savers_own_prefix_means_the_strip_did_not_run(self):
        verdict, present = classify('<img src="%s%s"/>' % (PREFIX_B, PICTURE), LABELS, "B")
        self.assertEqual((verdict, present), (OWN_PREFIX_STORED, ["B"]))

    def test_a_prefix_nobody_claims_is_read_like_a_foreign_one(self):
        verdict, present = classify('<img src="%s%s"/>' % (PREFIX_C, PICTURE), LABELS, "B")
        self.assertEqual((verdict, present), (UNKNOWN_PREFIX_STORED, ["unknown"]))

    def test_both_prefixes_in_one_value_is_foreign(self):
        """What the receiving peer's editable holds: `setAttribute` hands a
        foreign prefix to the shim's `path()`, which prefixes it again."""
        verdict, present = classify(
            '<img src="%s%s%s"/>' % (PREFIX_B, PREFIX_A, PICTURE), LABELS, "B")
        self.assertEqual(verdict, FOREIGN_PREFIX_STORED)
        self.assertEqual(sorted(present), ["A", "B"])


class RecordTests(unittest.TestCase):
    def kwargs(self, **overrides):
        base = dict(
            run_id="WOOW-PEER-20261001T000000Z", database="odoo_parity", target="local",
            pair="ingress-ingress", task_id=5,
            prefixes={"A": PREFIX_A, "B": PREFIX_A},
            transport={"delivered": True}, stored='<img src="%s"/>' % PICTURE,
            labels={PREFIX_A: "A"}, saver="B",
        )
        base.update(overrides)
        return base

    def test_equal_prefixes_are_recorded_as_the_expected_reading(self):
        """Two Ingress sessions on one add-on share the prefix: the token in
        the path is the add-on's, not the session's. The record says it rather
        than leaving a reader to compare two redacted labels."""
        record = evidence_record(**self.kwargs())
        self.assertIs(record["prefixes_equal"], True)
        self.assertEqual(record["verdict"], CLEAN)

    def test_different_prefixes_are_recorded_too(self):
        record = evidence_record(**self.kwargs(
            prefixes={"A": PREFIX_A, "B": PREFIX_B}, labels=LABELS))
        self.assertIs(record["prefixes_equal"], False)

    def test_a_public_peer_has_no_prefix_of_its_own(self):
        record = evidence_record(**self.kwargs(
            pair="ingress-public", prefixes={"A": PREFIX_A, "B": None}))
        self.assertIsNone(record["prefixes"]["B"])
        self.assertIsNone(record["prefixes_equal"])

    def test_no_value_read_back_is_not_run_and_not_clean(self):
        record = evidence_record(**self.kwargs(stored=None))
        self.assertEqual(record["verdict"], NOT_RUN)
        self.assertIsNone(record["stored"])

    def test_the_record_names_the_field_the_issue_is_about(self):
        record = evidence_record(**self.kwargs())
        self.assertEqual(record["field"], "project.task.description")
        self.assertEqual(record["issue"], 234)
        self.assertIn(record["pair"], PAIRS)

    def test_the_schema_is_the_one_the_parity_plan_registers(self):
        """Section 12 of the plan is where evidence schemas are declared, and
        this one is not `odoo-parity-evidence/v1` for reasons recorded there.
        A record whose schema no document names is a record nobody reading an
        evidence directory can place."""
        record = evidence_record(**self.kwargs())
        self.assertEqual(record["schema"], EVIDENCE_SCHEMA)
        plan = PARITY_PLAN.read_text(encoding="utf-8")
        section = plan[plan.index("## 12. "):]
        self.assertIn(EVIDENCE_SCHEMA, section,
                      "the parity plan's section 12 must register this schema")
        self.assertIn("conservation", section,
                      "and say that it does not feed the conservation check")


class ReportTests(unittest.TestCase):
    def record(self, verdict, **overrides):
        base = {"verdict": verdict, "pair": "ingress-ingress", "transport": {"delivered": True}}
        base.update(overrides)
        return base

    def test_a_clean_run_does_not_escalate(self):
        result = report([self.record(CLEAN), self.record(CLEAN, pair="ingress-public")])
        self.assertEqual(result["verdicts"], {CLEAN: 2})
        self.assertIs(result["escalate_issue_234_to_blocker"], False)
        self.assertEqual(result["pairs"], ["ingress-ingress", "ingress-public"])

    def test_a_stored_foreign_token_escalates_issue_234(self):
        """#234's own acceptance criteria: a confirmed stored foreign token
        makes it `severity: blocker` by parity plan section 1.3."""
        result = report([self.record(CLEAN), self.record(FOREIGN_PREFIX_STORED)])
        self.assertIs(result["escalate_issue_234_to_blocker"], True)

    def test_an_unaccounted_prefix_escalates_as_well(self):
        result = report([self.record(UNKNOWN_PREFIX_STORED)])
        self.assertIs(result["escalate_issue_234_to_blocker"], True)

    def test_a_run_whose_transport_never_delivered_is_visible(self):
        result = report([self.record(CLEAN, transport={"delivered": False})])
        self.assertEqual(result["transport_delivered"], [False])


if __name__ == "__main__":
    unittest.main()
