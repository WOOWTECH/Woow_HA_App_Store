#!/usr/bin/env python3
"""Static-tier tests for the pure parts of the peer-snapshot run (#234).

Nothing here opens a browser or a websocket, and nothing reads credentials.
What it does cover is everything the run decides *about* a value: the prefix
shape it looks for, the redaction that keeps a Supervisor token out of the
evidence, the verdict #234's criteria escalate on, and the report that says so.

Since #263 it also covers what the run decides about its own *steps*, because
that is where two false readings came from: `probe` claimed to write nothing
while writing the field on every run, and its marker was a constant, which made
`delivered` unfalsifiable once the field had ever held it. So the marker helper,
the wait's refusal of a pre-existing match and the probe's own verdict are driven
here, the two commands are pinned to the shape that cannot reproduce either
defect, and the three documents that state the behaviour are pinned to the code.

#243 took the measurement, so the browser steps are no longer unrun -- but they
are still not driven from here, and the redaction is still the thing that matters
most: the record the run writes exists to say *whose* prefix reached the field,
and getting that wrong means either an unreadable record or a token in the
repository.
"""
import contextlib
import inspect
import io
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from e2e_collab_peer_snapshot_live import (
    BUS_NOT_CONNECTED,
    CLEAN,
    COLLABORATION_STATE_JS,
    DELIVERED,
    DIFFERENT_CHANNEL,
    DISCARD_BUTTON,
    EVIDENCE_SCHEMA,
    HEALING_PAIR,
    MARKER_COLLISION,
    FOREIGN_PREFIX_STORED,
    INGRESS_PREFIX_SHAPE,
    NOT_COLLABORATIVE,
    NOT_JOINED,
    NOT_RUN,
    NO_DATA_CHANNEL,
    OWN_PREFIX_STORED,
    PAIRS,
    PROBE_RUN_PREFIX,
    UNATTRIBUTED,
    UNSAVED,
    UNKNOWN_PREFIX_STORED,
    await_marker,
    classify,
    discard_form,
    do_probe,
    do_run,
    evidence_record,
    final_verdict,
    focus_editable,
    heal_under_ingress,
    healing_not_performed,
    healing_read,
    ingress_prefixes,
    marker,
    mint_run_id,
    open_pair,
    probe_verdict,
    redact,
    discard_quietly,
    report,
    stage,
    stored_prefix_labels,
    transport_diagnosis,
    transport_note,
    wait_for_transport,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "rootfs/etc/nginx/nginx.conf.template"
PARITY_PLAN = Path(__file__).resolve().parents[2] / "docs/testing/INGRESS_VS_PUBLIC_PARITY.md"
LIVE_TIER_DOC = Path(__file__).resolve().parents[2] / "docs/agents/live-tier.md"

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
# The channel the collaboration plugin builds from the record and nothing else
# (`collaboration_odoo_plugin.js:134`), which is why two sessions on one to-do
# share it whatever surface each is on.
CHANNEL = "editor_collaboration:project.task:description:5"


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

    def test_the_record_carries_the_diagnosis_and_the_second_reading(self):
        """Both are #265's, and both are additive: the schema is still
        `woow.peer-snapshot.v1` because this is the same kind of record with two
        more fields, not a new kind of record."""
        record = evidence_record(**self.kwargs(
            collaboration={"cause": NOT_JOINED, "detail": "session(s) B never joined"},
            healing={"performed": True, "verdict": CLEAN, "saver": "A"}))
        self.assertEqual(record["collaboration"]["cause"], NOT_JOINED)
        self.assertEqual(record["healing"]["verdict"], CLEAN)
        self.assertEqual(record["schema"], EVIDENCE_SCHEMA)

    def test_a_record_without_either_still_says_which_it_has(self):
        record = evidence_record(**self.kwargs())
        self.assertEqual(record["collaboration"], {})
        self.assertIsNone(record["healing"],
                          "null rather than absent: a reader can tell no second reading was taken")

    def test_no_token_survives_in_either_field_the_record_grew(self):
        """A diagnosis can carry a Playwright message, and a Playwright message
        carries the URL it failed on -- which under Ingress is the prefix. The
        healing reading goes through the same redaction at the same boundary, so
        the guarantee does not depend on which helper built it."""
        record = evidence_record(**self.kwargs(
            collaboration={"sessions": {"B": {"unread": "timeout on %s/odoo" % PREFIX_C}}},
            healing={"performed": False, "reason": "timeout on %s/odoo" % PREFIX_C}))
        self.assertNotIn(TOKEN_C, json.dumps(record))
        self.assertIn("<ingress:unknown>", record["healing"]["reason"])

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
        base = {"verdict": verdict, "pair": "ingress-ingress", "transport": {"delivered": True},
                "healing": None}
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

    def test_a_clean_is_reported_with_the_transport_it_was_read_under(self):
        """#265's own criterion. #243's run recorded two `CLEAN`s while the
        transport delivered on neither pair, and ADR 0004, the parity plan and the
        evidence README then all quoted "measured, `CLEAN`" for a measurement of
        the save path. The two cannot be written as one sentence from here."""
        result = report([
            self.record(CLEAN, pair="ingress-ingress", transport={"delivered": False}),
            self.record(CLEAN, pair="ingress-public", transport={"delivered": True}),
        ])
        self.assertEqual(result["clean"], {"with_a_delivered_transport": ["ingress-public"],
                                          "with_no_delivery": ["ingress-ingress"]})
        self.assertIn("save path only", result["clean_means"])
        self.assertIn("ingress-ingress", result["clean_means"])
        self.assertIn("delivered snapshot", result["clean_means"])

    def test_a_fully_delivered_clean_run_says_nothing_about_a_save_path_caveat(self):
        result = report([self.record(CLEAN), self.record(CLEAN, pair="ingress-public")])
        self.assertEqual(result["clean"]["with_no_delivery"], [])
        self.assertNotIn("save path only", result["clean_means"])

    def test_a_confirmed_prefix_escalates_even_when_the_heal_removed_it(self):
        """#234's criterion is a **confirmed** stored foreign token, and a prefix the
        heal removed was confirmed: it was in the record. The first spelling of this
        read `final_verdict`, so a run that had just measured the Public peer writing
        a Supervisor token into `project.task.description` -- the escape #234 exists
        for -- printed `escalate_issue_234_to_blocker: false`. A report may not hide
        the confirmation behind the heal; it reports both, and whether the severity
        moves is #234's decision."""
        result = report([self.record(FOREIGN_PREFIX_STORED, pair="ingress-public", saver="B",
                                     healing={"performed": True, "verdict": CLEAN,
                                              "saver": "A"})])
        self.assertIs(result["escalate_issue_234_to_blocker"], True)
        self.assertEqual(result["escalated_on"],
                         [{"pair": "ingress-public", "verdict": FOREIGN_PREFIX_STORED,
                           "reading": "the peer's save"}])
        # And the heal is beside it, not instead of it.
        self.assertEqual(result["foreign_prefix_healed"][0]["pair"], "ingress-public")
        self.assertEqual(result["foreign_prefix_healed"][0]["stored_by"], "B")
        self.assertEqual(result["foreign_prefix_healed"][0]["healed_by"], "A")
        self.assertEqual(result["foreign_prefix_still_stored"], [],
                         "the record ends clean, which is a different question")
        self.assertEqual(result["final_verdicts"], {CLEAN: 1})
        self.assertEqual(result["verdicts"], {FOREIGN_PREFIX_STORED: 1})

    def test_a_prefix_that_survived_the_ingress_save_says_both_things(self):
        result = report([self.record(FOREIGN_PREFIX_STORED, pair="ingress-public",
                                     healing={"performed": True,
                                              "verdict": FOREIGN_PREFIX_STORED, "saver": "A"})])
        self.assertIs(result["escalate_issue_234_to_blocker"], True)
        self.assertEqual([reading["reading"] for reading in result["escalated_on"]],
                         ["the peer's save", "the Ingress healing save"])
        self.assertEqual(result["foreign_prefix_still_stored"], ["ingress-public"])
        self.assertEqual(result["foreign_prefix_healed"], [])

    def test_the_report_carries_the_rule_it_applied(self):
        """Because the rule has now been written two ways, and the one that reads
        only the end of the run answers "no" to the measurement that proves the
        escape exists."""
        result = report([self.record(CLEAN)])
        self.assertIn("confirmed", result["escalation_rule"])
        self.assertIn("#234's decision", result["escalation_rule"])

    def test_an_escalation_on_the_pair_with_no_healing_phase_names_that_reading(self):
        result = report([self.record(FOREIGN_PREFIX_STORED)])
        self.assertIs(result["escalate_issue_234_to_blocker"], True)
        self.assertEqual(result["escalated_on"][0]["reading"], "the peer's save")

    def test_a_heal_that_was_not_performed_is_in_the_report_with_its_reason(self):
        """Not silently absent: a reader comparing two runs has to see that one of
        them took one reading where the other took two."""
        result = report([
            self.record(CLEAN, pair="ingress-ingress",
                        healing={"performed": False, "reason": "no foreign write to heal"}),
            self.record(CLEAN, pair="ingress-public",
                        healing={"performed": True, "verdict": CLEAN, "saver": "A"}),
        ])
        self.assertEqual(result["healing"]["performed"], ["ingress-public"])
        self.assertEqual(result["healing"]["not_performed"],
                         {"ingress-ingress": "no foreign write to heal"})

    def test_the_report_carries_each_pairs_attributed_cause(self):
        result = report([self.record(CLEAN, transport={"delivered": False},
                                     collaboration={"cause": NOT_JOINED})])
        self.assertEqual(result["transport_causes"], {"ingress-ingress": NOT_JOINED})


class TransportDiagnosisTests(unittest.TestCase):
    """#265: a `delivered: false` has to be attributed by the run that read it.

    #243's run recorded two of them with nothing beside them, and the account that
    then went into ADR 0004, the parity plan and the evidence README -- "the two
    sessions never became collaboration peers" -- was an inference from a timeout.
    It happened to be true, and it was not measured. The ladder below is what the
    readings are worth and in which order.
    """

    def reading(self, **overrides):
        base = dict(is_collaborative=True, display_readonly=False, res_id=5,
                    plugin_present=True, channel=CHANNEL, ptp_joined=True,
                    ptp_created=True, peers=1, connected_peers=1,
                    bus_worker_state="CONNECTED", bus_connection_lost=False)
        base.update(overrides)
        return base

    def diagnose(self, *, transport=None, a=None, b=None, signalling=None):
        return transport_diagnosis(
            transport=transport if transport is not None else {"delivered": False},
            sessions={"A": a if a is not None else self.reading(),
                      "B": b if b is not None else self.reading()},
            signalling=signalling if signalling is not None else {"A": 3, "B": 2},
        )

    def test_a_delivered_transport_needs_no_cause_beyond_itself(self):
        result = self.diagnose(transport={"delivered": True, "waited_seconds": 1.5})
        self.assertEqual(result["cause"], DELIVERED)
        self.assertEqual(result["detail"], "")
        self.assertEqual(result["sessions"]["A"]["ptp_joined"], True,
                         "and the readings are in the record either way")

    def test_a_pre_existing_marker_makes_the_reading_void_and_not_negative(self):
        """And it is read before every other rung, because on that path nothing was
        measured: `await_marker` returns without waiting, so the two sessions may
        well have been peers and the snapshot may well have arrived. The run that
        hit this recorded `unattributed` beside two plainly connected sessions,
        which reads as a mystery rather than as a void reading."""
        result = self.diagnose(transport={"delivered": False, "marker_pre_existing": True,
                                          "waited_seconds": 0.0})
        self.assertEqual(result["cause"], MARKER_COLLISION)
        self.assertIn("void", result["detail"])
        self.assertIn("the pair", result["detail"])

    def test_a_field_that_is_not_collaborative_is_the_first_rung(self):
        """Before anything else, because without the plugin there is no channel to
        compare and no peer count to read."""
        result = self.diagnose(b=self.reading(is_collaborative=False, plugin_present=False,
                                              channel=None, ptp_joined=None))
        self.assertEqual(result["cause"], NOT_COLLABORATIVE)
        self.assertIn("session(s) B", result["detail"])

    def test_a_bus_that_never_connected_is_read_before_the_peer_state(self):
        """The signalling this transport needs goes over the bus, so a peer count
        taken without one says nothing. This is the rung that answers "is the bus
        reachable under Ingress and on the Public origin"."""
        result = self.diagnose(a=self.reading(bus_worker_state="DISCONNECTED",
                                             ptp_joined=False))
        self.assertEqual(result["cause"], BUS_NOT_CONNECTED)
        self.assertIn("A", result["detail"])

    def test_two_sessions_on_different_channels_are_named_as_such(self):
        result = self.diagnose(b=self.reading(channel=CHANNEL.replace(":5", ":6")))
        self.assertEqual(result["cause"], DIFFERENT_CHANNEL)
        self.assertIs(result["shared_channel"], False)

    def test_a_session_that_never_joined_the_peer_network_is_the_defect_265_found(self):
        """And the detail says *why* a session would not have joined, because the
        reason is not discoverable from the DOM, the console or a log: the plugin
        joins on the editable's `focus` and the unjoined session drops every
        notification it is sent."""
        result = self.diagnose(b=self.reading(ptp_joined=False, peers=0, connected_peers=0),
                               signalling={"A": 3, "B": 0})
        self.assertEqual(result["cause"], NOT_JOINED)
        self.assertIn("session(s) B", result["detail"])
        self.assertIn("focus", result["detail"])
        self.assertEqual(result["signalling_posts"], {"A": 3, "B": 0},
                         "and the wire says the same thing the client does")

    def test_peers_that_joined_with_no_data_channel_are_a_different_finding(self):
        """The bus carries the negotiation and never the content, so a joined pair
        with no connected peer is an RTC failure and not a signalling one."""
        result = self.diagnose(a=self.reading(connected_peers=0),
                               b=self.reading(connected_peers=0))
        self.assertEqual(result["cause"], NO_DATA_CHANNEL)
        self.assertIn("data channel", result["detail"])

    def test_nothing_accounting_for_it_says_so_rather_than_picking_a_rung(self):
        result = self.diagnose(a=self.reading(connected_peers=None),
                               b=self.reading(connected_peers=None))
        self.assertEqual(result["cause"], UNATTRIBUTED)

    def test_a_session_that_could_not_be_read_is_not_read_as_a_false_value(self):
        """An unread session must not satisfy a rung: `is_collaborative` missing is
        not `is_collaborative: false`, and saying "the field is not collaborative"
        on a page that never answered would be a worse account than none."""
        result = self.diagnose(b={"unread": "no __WOWL_DEBUG__ root on this page"})
        self.assertEqual(result["cause"], UNATTRIBUTED)
        self.assertIn("B", result["detail"])
        self.assertEqual(result["sessions"]["B"]["unread"],
                         "no __WOWL_DEBUG__ root on this page")

    def test_the_shared_channel_reading_is_none_when_one_side_has_no_channel(self):
        result = self.diagnose(b=self.reading(channel=None, is_collaborative=True,
                                              plugin_present=True))
        self.assertIsNone(result["shared_channel"])

    def test_the_route_the_posts_were_counted_on_is_in_the_record(self):
        """A count with no denominator named is not a reading a second run can
        compare with."""
        self.assertEqual(self.diagnose()["signalling_route"], "/html_editor/bus_broadcast")

    def test_the_state_expression_asks_for_no_secret_and_no_content(self):
        """It runs in a page whose URL carries the Supervisor token, and its answer
        goes into a record that is quoted in a pull request. Peer ids and documents
        are counted, never carried."""
        self.assertNotIn("innerHTML", COLLABORATION_STATE_JS)
        self.assertNotIn("location", COLLABORATION_STATE_JS)
        self.assertIn(".length", COLLABORATION_STATE_JS)
        self.assertIn("ptpJoined", COLLABORATION_STATE_JS)
        self.assertIn("workerState", COLLABORATION_STATE_JS)


class HealingReadTests(unittest.TestCase):
    """#265: the second half of the `ingress-public` measurement.

    ADR 0004 asked for it when it refined #234's Live row -- read after the Public
    peer saves, then save once under Ingress and read again -- and #243's run had
    no implementation of it and no subject for it. The two readings are not one
    reading twice: the Public origin stores what it is handed, and the Ingress
    strip's part is removing it on the next Ingress save.
    """

    def heal(self, **overrides):
        base = dict(loaded='<img src="%s%s"/>' % (PREFIX_A, PICTURE),
                    stored='<img src="%s"/>' % PICTURE, labels=LABELS, saver="A")
        base.update(overrides)
        return healing_read(**base)

    def test_a_prefix_the_public_peer_stored_and_the_ingress_save_removed(self):
        """What the fix does on this pair, and the only thing it can do: it cannot
        stop the Public peer writing."""
        healing = self.heal(loaded='<img src="%s%s"/>' % (PREFIX_B, PICTURE))
        self.assertIs(healing["performed"], True)
        self.assertEqual(healing["verdict"], CLEAN)
        self.assertEqual(healing["loaded_prefixes"], ["B"])
        self.assertIn("cannot prevent that write", healing["notes"])

    def test_a_prefix_that_survived_the_ingress_save_is_the_hole(self):
        healing = self.heal(loaded='<img src="%s%s"/>' % (PREFIX_B, PICTURE),
                            stored='<img src="%s%s"/>' % (PREFIX_B, PICTURE))
        self.assertEqual(healing["verdict"], FOREIGN_PREFIX_STORED)
        self.assertEqual(healing["stored_prefixes"], ["B"])
        self.assertIn("did not heal", healing["notes"])

    def test_a_clean_save_that_had_nothing_to_strip_says_so(self):
        """Which is the weaker statement, and the one every run so far could make:
        a `CLEAN` after a save that loaded no prefix is not evidence that the strip
        works."""
        healing = self.heal(loaded='<img src="%s"/>' % PICTURE)
        self.assertEqual(healing["verdict"], CLEAN)
        self.assertEqual(healing["loaded_prefixes"], [])
        self.assertIn("nothing to strip", healing["notes"])

    def test_the_sessions_own_prefix_in_the_loaded_value_is_still_a_subject(self):
        """The central case, and the one this function first got wrong. The
        `ingress-public` pair's two sessions are served **one** token -- the
        add-on's -- so the prefix the Public peer stored is the Ingress session's
        own, and a subject test of "whose label is it" called the measured case
        "nothing to strip". What makes it the harm is the token being in a record at
        all."""
        healing = self.heal(loaded='<img src="%s%s"/>' % (PREFIX_A, PICTURE))
        self.assertEqual(healing["loaded_prefixes"], ["A"])
        self.assertEqual(healing["verdict"], CLEAN)
        self.assertIn("cannot prevent that write", healing["notes"])

    def test_the_savers_own_prefix_surviving_is_not_called_healed(self):
        """`OWN-PREFIX-STORED` is `classify`'s "the strip did not run", so a healing
        save that leaves it has not healed anything."""
        healing = self.heal(loaded='<img src="%s%s"/>' % (PREFIX_A, PICTURE),
                            stored='<img src="%s%s"/>' % (PREFIX_A, PICTURE))
        self.assertEqual(healing["verdict"], OWN_PREFIX_STORED)
        self.assertNotIn("removed it", healing["notes"])

    def test_no_token_reaches_a_healing_record(self):
        healing = self.heal(stored='<img src="%s%s"/>' % (PREFIX_C, PICTURE))
        self.assertNotIn(TOKEN_C, json.dumps(healing))
        self.assertEqual(healing["verdict"], UNKNOWN_PREFIX_STORED)

    def test_a_heal_that_was_not_performed_carries_its_reason(self):
        healing = healing_not_performed("the Ingress healing save could not be taken: TimeoutError")
        self.assertIs(healing["performed"], False)
        self.assertIn("TimeoutError", healing["reason"])
        self.assertNotIn("verdict", healing,
                         "a reading that was not taken has no verdict to report")


class FinalVerdictTests(unittest.TestCase):
    """#265: which of a record's two verdicts #234's escalation rule reads."""

    def record(self, verdict, healing=None):
        return {"pair": "ingress-public", "verdict": verdict, "healing": healing,
                "saver": "B", "transport": {"delivered": True}}

    def test_without_a_healing_phase_it_is_the_peers_save(self):
        self.assertEqual(final_verdict(self.record(FOREIGN_PREFIX_STORED)),
                         FOREIGN_PREFIX_STORED)

    def test_with_one_it_is_the_value_the_record_ends_with(self):
        healed = self.record(FOREIGN_PREFIX_STORED,
                             {"performed": True, "verdict": CLEAN, "saver": "A"})
        self.assertEqual(final_verdict(healed), CLEAN)

    def test_a_heal_that_was_not_performed_falls_back_and_fails_closed(self):
        """A pair whose second reading could not be taken escalates on the one that
        was, rather than on a `CLEAN` nobody measured."""
        blocked = self.record(FOREIGN_PREFIX_STORED,
                              {"performed": False, "reason": "TimeoutError"})
        self.assertEqual(final_verdict(blocked), FOREIGN_PREFIX_STORED)


class MarkerTests(unittest.TestCase):
    """#263: a marker has to be unique to the run, and one helper has to mint it."""

    def test_both_sessions_markers_come_from_the_one_helper(self):
        self.assertEqual(marker("WOOW-PEER-20261002T015318Z", "A", "ingress-ingress"),
                         "WOOW-PEER-20261002T015318Z-ingress-ingress-A")
        self.assertEqual(marker("WOOW-PEER-20261002T015318Z", "B", "ingress-ingress"),
                         "WOOW-PEER-20261002T015318Z-ingress-ingress-B")

    def test_the_two_pairs_of_one_run_do_not_type_the_same_marker(self):
        """#265, found by the first run that delivered. A run is one `--run-id` over
        both pairs, and `run` *stores* its marker -- so the second pair opened a
        record already holding the first pair's `<run-id>-A`, the baseline guard
        fired and the transport reading was void. The run id makes a marker unique
        across runs; the pair makes it unique within one."""
        run_id = "WOOW-PEER-20261002T062800Z"
        self.assertNotEqual(marker(run_id, "A", PAIRS[0]), marker(run_id, "A", PAIRS[1]))
        for pair in PAIRS:
            self.assertIn(pair, marker(run_id, "A", pair))

    def test_no_command_can_forget_the_pair(self):
        """Positional and required, so a marker cannot be built without it."""
        parameter = inspect.signature(marker).parameters["pair"]
        self.assertIs(parameter.default, inspect.Parameter.empty)
        for command in (do_probe, do_run):
            for call in re.findall(r"marker\(run_id[^)]*\)", inspect.getsource(command)):
                self.assertIn("pair", call, command.__name__)

    def test_neither_command_stages_a_constant_marker(self):
        """The defect in one assertion. `probe` typed the literal
        `WOOW-PEER-PROBE`; because it also *wrote* the field, the next probe
        found that string in the receiving editable on its first poll and
        reported a delivery that never happened. A marker built from the run id
        cannot be satisfied by a value a previous run stored."""
        for command in (do_probe, do_run):
            source = inspect.getsource(command)
            self.assertIn("marker(run_id", source,
                          "%s must build its marker from the run id" % command.__name__)
            self.assertNotIn(PROBE_RUN_PREFIX, source,
                             "%s must not type a constant marker" % command.__name__)

    def test_a_minted_probe_run_id_is_the_shape_run_takes(self):
        minted = mint_run_id(datetime(2026, 10, 2, 1, 53, 18, tzinfo=timezone.utc))
        self.assertEqual(minted, "WOOW-PEER-PROBE-20261002T015318Z")
        self.assertTrue(minted.startswith(PROBE_RUN_PREFIX))

    def test_a_minted_run_id_is_different_for_a_different_run(self):
        """Uniqueness is the whole point of it, so it is checked and not assumed."""
        first = datetime(2026, 10, 2, 1, 53, 18, tzinfo=timezone.utc)
        self.assertNotEqual(mint_run_id(first), mint_run_id(first + timedelta(seconds=1)))

    def test_a_minted_run_id_is_utc_whatever_it_was_given(self):
        """`-<UTC timestamp>` is what the shape claims, and a naive local clock
        reaching this would make two runs an hour apart collide."""
        utc = datetime(2026, 10, 2, 1, 53, 18, tzinfo=timezone.utc)
        self.assertEqual(mint_run_id(utc.astimezone(timezone(timedelta(hours=8)))),
                         mint_run_id(utc))


class TransportWaitTests(unittest.TestCase):
    """#263: "it was already there" and "it arrived" are different readings."""

    def poll(self, *reads):
        """A reader that answers each call in turn, and a sleep that counts."""
        values = list(reads)
        slept = []
        return (lambda: values.pop(0) if values else ""), slept.append, slept

    def test_a_marker_already_in_the_baseline_is_not_a_delivery(self):
        read, sleep, slept = self.poll("the marker M is right here")
        result = await_marker(read, "M", baseline="a value holding M already",
                              sleep=sleep, seconds=30)
        self.assertIs(result["delivered"], False)
        self.assertIs(result["marker_pre_existing"], True)
        self.assertEqual(result["waited_seconds"], 0.0)
        self.assertEqual(slept, [], "a pre-existing marker is refused without waiting")

    def test_a_marker_that_arrives_is_a_delivery_with_the_seconds_it_took(self):
        read, sleep, slept = self.poll("nothing", "nothing", "here comes M")
        result = await_marker(read, "M", baseline="clean", sleep=sleep, seconds=30)
        self.assertIs(result["delivered"], True)
        self.assertIs(result["marker_pre_existing"], False)
        self.assertEqual(result["waited_seconds"], 1.0)
        self.assertEqual(slept, [500, 500])

    def test_an_arrival_on_the_first_read_is_zero_seconds_and_still_a_delivery(self):
        """The shape to distrust is not the shape to refuse. The receiving
        session joins *after* the sender typed, so the snapshot it is handed can
        legitimately carry the marker on the first poll -- what made #243's
        reading false was the baseline, not the clock. Both are recorded."""
        read, sleep, _ = self.poll("M arrived with the snapshot")
        result = await_marker(read, "M", baseline="clean", sleep=sleep, seconds=30)
        self.assertEqual((result["delivered"], result["waited_seconds"]), (True, 0.0))
        self.assertIs(result["marker_pre_existing"], False)

    def test_nothing_arriving_is_a_finding_and_not_a_failure(self):
        read, sleep, slept = self.poll()
        result = await_marker(read, "M", baseline="clean", sleep=sleep, seconds=2)
        self.assertIs(result["delivered"], False)
        self.assertIs(result["marker_pre_existing"], False)
        self.assertEqual(result["waited_seconds"], 2.0)
        self.assertIn("never arrived", result["detail"])
        self.assertEqual(len(slept), 4, "two polls a second for the whole wait")

    def test_an_empty_baseline_is_not_a_match(self):
        """A session whose editable read empty must not make every marker
        pre-existing, and `None` must not raise."""
        for baseline in (None, ""):
            read, sleep, _ = self.poll("M is here")
            result = await_marker(read, "M", baseline=baseline, sleep=sleep, seconds=1)
            self.assertIs(result["delivered"], True, repr(baseline))

    def test_the_guard_cannot_be_skipped_by_a_caller(self):
        """`baseline` is keyword-only with no default on both the pure loop and
        the browser wrapper, so a future caller cannot quietly drop the thing
        that distinguishes the two readings."""
        for function in (await_marker, wait_for_transport):
            parameter = inspect.signature(function).parameters["baseline"]
            self.assertIs(parameter.default, inspect.Parameter.empty, function.__name__)
            self.assertIs(parameter.kind, inspect.Parameter.KEYWORD_ONLY, function.__name__)

    def test_the_baseline_is_read_before_the_sender_types(self):
        """Which is the only order that makes it a baseline. Read from A, because
        B has not joined yet and both sessions load the same stored value."""
        source = inspect.getsource(stage)
        self.assertLess(source.index("baseline = editable_html(first)"),
                        source.index("type_marker(first"),
                        "the baseline must be read before anything is typed")
        self.assertIn("baseline=baseline", source)


class ReceiverJoinsThePeerNetworkTests(unittest.TestCase):
    """#265: the step whose absence made every run so far time out.

    Source pins, for this file's standing reason: what went wrong was a step the
    command did not do, and the only tier that can watch a browser join a peer
    network is the one that needs the test host. The mechanism, read from the
    deployed image: with no view setting `collaborative_trigger` the collaboration
    plugin registers a one-shot `focus` listener on the editable and joins there
    (`collaboration_odoo_plugin.js:91-99`), and a session whose `ptpJoined` is
    false discards every signalling notification it receives -- the other
    session's `ptp_join` included (`:156-158`). No log and nothing in the DOM says
    so, which is why two pairs waited out 30 seconds and the records said only
    that nothing arrived.
    """

    def test_the_receiving_session_is_focused_before_the_wait(self):
        source = inspect.getsource(stage)
        self.assertIn("focus_editable(second)", source)
        self.assertLess(source.index("open_todo(second"), source.index("focus_editable(second)"),
                        "the form has to be open before its editable can be focused")
        self.assertLess(source.index("focus_editable(second)"),
                        source.index("wait_for_transport(second"),
                        "a session focused after the wait is a session that never joined")

    def test_the_sender_is_focused_by_typing_and_the_order_still_holds(self):
        """A joined by accident -- typing needs a focused editable -- and that is
        why the sending half worked. The baseline still has to be read before it."""
        source = inspect.getsource(stage)
        self.assertLess(source.index("baseline = editable_html(first)"),
                        source.index("type_marker(first"))
        self.assertLess(source.index("type_marker(first"), source.index("open_todo(second"))

    def test_the_focus_step_touches_no_content(self):
        """`click()` lands in the middle of the loaded document, and the onboarding
        to-do's middle is a checklist whose items toggle through
        `/web_editor/checklist` -- a write, on the command whose whole claim is
        that it makes none."""
        source = inspect.getsource(focus_editable)
        self.assertIn(".focus()", source)
        self.assertNotIn(".click()", source)

    def test_both_commands_record_why_the_transport_did_what_it_did(self):
        for command in (do_probe, do_run):
            source = inspect.getsource(command)
            with self.subTest(command.__name__):
                self.assertIn("diagnosis", source)
                self.assertIn("collaboration", source)

    def test_the_diagnosis_is_read_before_anything_discards_or_saves(self):
        """A discard remounts the editor and takes the plugin's state with it, and a
        save does the same on the receiving session. The reading has to be inside
        `stage`, where neither has happened yet."""
        source = inspect.getsource(stage)
        self.assertIn("transport_diagnosis(", source)
        self.assertIn("collaboration_reading(first)", source)
        self.assertIn("collaboration_reading(second)", source)
        for command in (do_probe, do_run):
            self.assertNotIn("collaboration_reading(", inspect.getsource(command),
                             "%s must take the reading through `stage`" % command.__name__)

    def test_the_signalling_counter_is_attached_before_the_login(self):
        """So that no post can fall outside the count, and so that a session the
        pair opened always has one -- `_signalling_posts` reads zero rather than
        raising for a caller that built a side by hand."""
        source = inspect.getsource(open_pair)
        self.assertIn("SignallingCount(side.context)", source)
        self.assertLess(source.index("SignallingCount(side.context)"),
                        source.index("first.start()"))

    def test_the_healing_save_loads_the_record_again_before_it_saves(self):
        """A discard resets the form to the values the client already held, which
        are the ones A loaded *before* B saved. Only a fresh read hands A what B
        stored, and whether an Ingress save strips a prefix that arrived in the
        loaded value is the whole question."""
        source = inspect.getsource(heal_under_ingress)
        for earlier, later in (("discard_quietly(first)", "open_todo(first"),
                               ("open_todo(first", "loaded = editable_html(first)"),
                               ("loaded = editable_html(first)", "type_marker(first"),
                               ("type_marker(first", "save_form(first)")):
            self.assertLess(source.index(earlier), source.index(later),
                            "%s must come before %s" % (earlier, later))
        self.assertIn("healing_read(", source)


class TransportNoteTests(unittest.TestCase):
    """A record has to say *which* way its transport failed, not just that it did."""

    def test_a_delivered_transport_needs_no_note(self):
        self.assertEqual(transport_note({"delivered": True, "waited_seconds": 0.0}), "")

    def test_a_marker_that_never_arrived_says_so(self):
        note = transport_note(await_marker(lambda: "", "M", baseline="clean",
                                           sleep=lambda ms: None, seconds=1))
        self.assertIn("never arrived", note)
        self.assertIn("not evidence about the peer transport", note)

    def test_a_pre_existing_marker_is_not_described_as_one_that_never_arrived(self):
        """The two are different findings, and a pre-existing marker says the run
        id collided -- which makes the whole record suspect, not only its
        transport half. One fixed sentence for both would have been a false
        account of this case."""
        note = transport_note(await_marker(lambda: "M", "M", baseline="M was here",
                                           sleep=lambda ms: None, seconds=1))
        self.assertIn("already in the editable", note)
        self.assertNotIn("never arrived", note)

    def test_a_transport_with_no_detail_still_reads_as_a_sentence(self):
        self.assertEqual(transport_note({"delivered": False}),
                         "the marker did not arrive -- so the stored value is not "
                         "evidence about the peer transport")


class StoredPrefixLabelTests(unittest.TestCase):
    """A reading of which prefixes are in a value, separate from any verdict."""

    def test_the_labels_in_order(self):
        value = '<img src="%s%s"/><img src="%s%s"/>' % (PREFIX_B, PICTURE, PREFIX_A, PICTURE)
        self.assertEqual(stored_prefix_labels(value, LABELS), ["B", "A"])

    def test_a_clean_value_has_none(self):
        self.assertEqual(stored_prefix_labels('<img src="%s"/>' % PICTURE, LABELS), [])

    def test_an_unclaimed_prefix_is_unknown(self):
        self.assertEqual(stored_prefix_labels('<img src="%s"/>' % PREFIX_C, LABELS),
                         ["unknown"])

    def test_the_ingress_ingress_pair_collapses_to_one_label(self):
        """Which is why `probe` reports labels and no verdict. Both sessions are
        served the add-on's one `ingress_token`, so `labels_for` writes one entry
        and the later session wins it. Asking `classify` for a verdict with
        `saver="A"` then calls every prefix foreign -- the verdict the parity plan
        escalates #234 to `blocker` on -- for a value nobody saved."""
        collapsed = {PREFIX_A: "B"}  # what labels_for produces when A and B match
        value = '<img src="%s%s"/>' % (PREFIX_A, PICTURE)
        self.assertEqual(stored_prefix_labels(value, collapsed), ["B"])
        self.assertEqual(classify(value, collapsed, "A")[0], FOREIGN_PREFIX_STORED)
        self.assertEqual(classify(value, collapsed, "B")[0], OWN_PREFIX_STORED)

    def test_probe_reports_the_labels_and_asks_for_no_verdict(self):
        source = inspect.getsource(do_probe)
        self.assertIn("stored_prefix_labels(stored, labels)", source)
        self.assertNotIn("classify(", source,
                         "a saver-relative verdict has no saver on a step that saves nothing")


class ProbeVerdictTests(unittest.TestCase):
    """#263: `probe`'s claim to write nothing is measured, not asserted."""

    def verdict(self, **overrides):
        base = dict(transport={"delivered": True},
                    stored="<p>the onboarding to-do, untouched</p>",
                    run_id="WOOW-PEER-PROBE-20261002T015318Z",
                    discarded={"A": {"dirty": True, "discarded": True},
                               "B": {"dirty": False, "discarded": False}})
        base.update(overrides)
        return probe_verdict(**base)

    def test_a_probe_that_left_the_field_alone_passes(self):
        verdict = self.verdict()
        self.assertIs(verdict["wrote_nothing"], True)
        self.assertEqual(verdict["forms_left_dirty"], [])
        self.assertEqual(verdict["detail"], "")
        self.assertEqual(verdict["exit_code"], 0)

    def test_a_probe_whose_run_id_is_in_the_field_wrote_and_fails(self):
        run_id = "WOOW-PEER-PROBE-20261002T015318Z"
        verdict = self.verdict(stored="<p>to-do %s-A</p>" % run_id)
        self.assertIs(verdict["wrote_nothing"], False)
        self.assertIn("wrote the field", verdict["detail"])
        self.assertEqual(verdict["exit_code"], 1)

    def test_an_earlier_runs_marker_is_not_this_probes_write(self):
        """The field may still hold what the constant-marker probes left on a
        host nobody has cleaned. That is a pre-existing value, and reporting it
        as this run's write would make the check cry wolf forever."""
        verdict = self.verdict(stored="<p>to-do WOOW-PEER-PROBE WOOW-PEER-PROBE</p>")
        self.assertIs(verdict["wrote_nothing"], True)

    def test_a_probe_that_wrote_nothing_but_never_delivered_still_fails(self):
        """Both claims gate the exit code: a probe is also how the transport is
        attributed, and #243's run is the reason that reading is worth a code."""
        verdict = self.verdict(transport={"delivered": False})
        self.assertIs(verdict["wrote_nothing"], True)
        self.assertEqual(verdict["exit_code"], 1)

    def test_a_missing_delivered_is_not_a_pass(self):
        self.assertEqual(self.verdict(transport={})["exit_code"], 1)

    def test_a_form_left_dirty_fails_even_on_a_clean_read_back(self):
        """The read-back only sees writes that already happened. A session still
        holding unsaved content gets written afterwards -- by the unload or by the
        ungated `visibilitychange` save -- so a clean field here means "not yet".
        Reporting `wrote_nothing` and exiting 0 on that is the one outcome #263
        must not allow."""
        verdict = self.verdict(discarded={"A": {"dirty": True, "discarded": False},
                                          "B": {"dirty": True, "discarded": True}})
        self.assertIs(verdict["wrote_nothing"], True)
        self.assertEqual(verdict["forms_left_dirty"], ["A"])
        self.assertIn("not yet", verdict["detail"])
        self.assertEqual(verdict["exit_code"], 1)

    def test_a_form_that_was_never_dirty_is_not_a_form_left_dirty(self):
        """`discarded: False` on a clean form is the normal reading, not a fault."""
        verdict = self.verdict(discarded={"A": {"dirty": False, "discarded": False},
                                          "B": {"dirty": False, "discarded": False}})
        self.assertEqual(verdict["forms_left_dirty"], [])
        self.assertEqual(verdict["exit_code"], 0)

    def test_a_discard_that_raised_counts_as_left_dirty(self):
        verdict = self.verdict(discarded={"A": {"dirty": True, "discarded": False,
                                                "error": "TimeoutError"}})
        self.assertEqual(verdict["forms_left_dirty"], ["A"])
        self.assertEqual(verdict["exit_code"], 1)

    def test_an_actual_write_is_reported_over_a_dirty_form(self):
        """Both are wrong, and the one that already happened is the one to act on."""
        run_id = "WOOW-PEER-PROBE-20261002T015318Z"
        verdict = self.verdict(stored="%s-A" % run_id,
                               discarded={"A": {"dirty": True, "discarded": False}})
        self.assertIn("wrote the field", verdict["detail"])


class ProbeWritesNothingTests(unittest.TestCase):
    """#263: pinned at the shape, because the behaviour needs a host to see.

    These are source pins and they are deliberate. What went wrong was never a
    value a function returned -- it was a step the command did and a step it did
    not do, and the only tier that can watch the browser do it is the one that
    needs the test host. So the shape is held here: the discard happens, the
    read-back happens, and the navigation that did the writing is gone.

    One of them is no longer only a shape. The reading order -- B's editable
    before either form is discarded -- is driven through doubles since #282,
    because `probe`'s whole output is that one reading and because a pin that
    resolves on a bare name can stop meaning anything without going red. The
    test below says exactly which shape that is.
    """

    def test_probe_discards_both_sessions_forms(self):
        source = inspect.getsource(do_probe)
        self.assertIn("discard_quietly(side)", source)
        self.assertIn('("A", first), ("B", second)', source,
                      "both sessions' forms are dirty: A typed, and B may have received")

    def test_probe_no_longer_navigates_away_from_a_dirty_form(self):
        """The regression pin. `side.goto("/odoo")` in the old `finally` is what
        persisted the editor's content, on a step whose comment said that only a
        save writes the field."""
        source = inspect.getsource(do_probe)
        self.assertNotIn('goto("/odoo")', source)

    def test_probe_reads_the_field_back_and_reports_what_it_found(self):
        source = inspect.getsource(do_probe)
        self.assertIn("read_description(", source)
        self.assertIn("probe_verdict(", source)
        self.assertIn('"wrote_nothing"', source,
                      "the output must carry the claim, so the evidence can be read for it")
        # The exit code is the verdict's, wherever the statement sits. It is read
        # one line and returned the next since #264, outside the ambient
        # accounting: a `return` from inside it leaves the body exception-free, so
        # a figure that could not be written would be raised as the run's only
        # failure and `main`'s catch-all would turn this measured non-zero into a
        # harness error.
        self.assertIn('verdict["exit_code"]', source)
        self.assertIn("return exit_code", source)

    def test_probe_reads_the_receiving_editable_before_it_discards(self):
        """A discard reloads the record, so the delivered content is gone after
        it -- and that reading is the only thing in the report that says what the
        transport did.

        Matched on the **whole call line** and not on `discard_quietly` alone,
        and the reason is narrower than it looks. A plain reorder does not
        escape the bare name: the call text contains it, so moving the call
        above the read moves the first match with it and the old assertion goes
        red. What the bare name does not survive is the call leaving the call
        site -- renamed, or extracted into a helper -- while the comment above
        it still names `discard_quietly`. Then `index()` resolves in prose, the
        ordering claim is satisfied by a sentence, and the code discards first.
        That is #292's `is_visible()` trap in its weaker form: there the name
        was one `discard_form` never called at all. Matching the whole call line
        turns a rename into a red `assertIn` that has to be re-pointed on
        purpose. The behavioural guard is
        `test_probe_records_the_delivered_editable_and_not_the_discarded_one`
        below; this is the shape beside it."""
        source = inspect.getsource(do_probe)
        call = "discarded = {label: discard_quietly(side)"
        self.assertIn(call, source)
        self.assertLess(source.index("second_editable = "), source.index(call))

    def test_probe_records_the_delivered_editable_and_not_the_discarded_one(self):
        """The same ordering, driven rather than pinned (#282 item 5).

        A discard remounts the editor from the stored value, so a probe that
        discarded first would record what the record already held and report it
        as what the transport delivered -- which is exactly the reading a
        transport that delivered *nothing* produces, and the one `probe` exists
        to tell apart. The doubles make the two answers different: the editable
        reads `DELIVERED-...` while the form is still dirty and `STORED-...`
        once a discard has reset it, so a reordered `do_probe` records the
        second and fails here.
        """
        import e2e_collab_peer_snapshot_live as module

        class FakeEnv:
            prefix = ""
            target = "test-doubles"
            db = "nodb"

            def mask(self, value):
                return value

        class FakeSide:
            def __init__(self):
                self.env = FakeEnv()
                self.discarded = False
                self.closed = 0

            def close(self):
                self.closed += 1

        first, second = FakeSide(), FakeSide()
        read_order = []

        @contextlib.contextmanager
        def no_accounting(*args, **kwargs):
            yield

        def fake_editable_html(side):
            read_order.append("read")
            return "STORED-only" if side.discarded else "DELIVERED-marker"

        def fake_discard_quietly(side):
            read_order.append("discard")
            side.discarded = True
            return {"dirty": True, "discarded": True}

        for name, double in (
            ("open_pair", lambda env, browser, pair: (first, second)),
            ("ambient_figure", lambda a, b: None),
            ("ambient_accounting", no_accounting),
            ("stage", lambda a, b, task_id, marker_text: ({}, 5, {"delivered": True}, {})),
            ("editable_html", fake_editable_html),
            ("discard_quietly", fake_discard_quietly),
            ("read_description", lambda side, task_id: "nothing this run typed"),
        ):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, double)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exit_code = module.do_probe(FakeEnv(), None, "ingress-ingress", 5,
                                        "WOOW-PEER-PROBE-20260101T000000Z")
        record = json.loads(out.getvalue())

        self.assertEqual(record["second_session_editable"], "DELIVERED-marker",
                         "the reading is what B was served, not what a discard put back")
        self.assertEqual(read_order, ["read", "discard", "discard"],
                         "one reading, then both sessions' discards")
        self.assertEqual(exit_code, 0)
        self.assertTrue(first.discarded and second.discarded,
                        "and the discard still happens on both sessions")

    def test_run_discards_the_sending_sessions_leftover(self):
        """`run` is documented to store what B saved. A's form is still dirty
        with A's own marker when B is done, and leaving it dirty writes it on the
        way out -- the same defect, on the command that is allowed to write."""
        source = inspect.getsource(do_run)
        self.assertIn("discard_quietly(first)", source)
        self.assertLess(source.index("save_form(second)"),
                        source.index("discard_quietly(first)"),
                        "A is discarded after B's save, or B would never see A's marker")

    def test_a_step_that_comes_after_a_measurement_cannot_lose_it(self):
        """Cleanup must never be what loses a measurement, and since #265 the step
        after the first reading is not only cleanup: on the `ingress-public` pair
        it is the healing save, which discards A, navigates, types and saves, and
        every one of those can time out. So the whole of it is guarded and a
        failure becomes `healing_not_performed` in the record -- the record is
        still written, which is what the old ordering pin was protecting. By the
        time this runs the measurement has already cost a deploy, a host and a
        30-second wait."""
        source = inspect.getsource(do_run)
        self.assertIn("heal_under_ingress(", source)
        self.assertLess(source.index("heal_under_ingress("), source.index("handle.write("),
                        "the healing reading goes into the record, so it is taken first")
        self.assertIn("except Exception as error", source)
        self.assertIn("healing_not_performed(", source,
                      "a second reading that could not be taken is a reason, not an exception")
        self.assertLess(source.index("except Exception as error"), source.index("handle.write("))

    def test_the_discard_that_now_precedes_the_write_cannot_throw(self):
        """The other pair's step before the record is still cleanup, and it moved
        above the write — so what protects the measurement there is that it goes
        through `discard_quietly`, which returns the outcome of a discard that
        raised instead of raising. `discard_form` does raise: its `wait_for` times
        out whenever the form will not go clean."""
        source = inspect.getsource(do_run)
        self.assertLess(source.index("discard_quietly(first)"), source.index("handle.write("))
        self.assertNotIn("discard_form(", source)

    def test_the_healing_save_is_only_made_on_the_pair_that_needs_healing(self):
        """`ingress-ingress` has no foreign write to heal -- one prefix, one strip
        -- and saving a second time there would write the field for nothing."""
        source = inspect.getsource(do_run)
        self.assertIn("if pair != HEALING_PAIR:", source)
        self.assertLess(source.index("if pair != HEALING_PAIR:"),
                        source.index("heal_under_ingress("))
        self.assertEqual(HEALING_PAIR, "ingress-public",
                         "and the name still points at the pair with a Public peer")
        self.assertIn("discard_quietly(first)", source,
                      "the other pair still discards A's leftover rather than saving it")

    def test_run_reads_the_verdict_the_record_ends_with(self):
        """Not the peer's save: on the healing pair that one is allowed to carry a
        prefix, and the exit code must not call the fix working a failure."""
        source = inspect.getsource(do_run)
        self.assertIn("final_verdict(record) == CLEAN", source)

    def test_both_commands_discard_through_the_wrapper_that_cannot_throw(self):
        """One session's failed discard must not stop the other's, nor stop the
        report: on that path `probe` would read the field back on no run at all,
        while its own docstring promises every run."""
        for command in (do_probe, do_run):
            source = inspect.getsource(command)
            self.assertIn("discard_quietly(", source, command.__name__)
            self.assertNotIn("discard_form(", source,
                             "%s must go through the wrapper" % command.__name__)

    def test_a_failed_discard_is_a_reading_and_not_an_exception(self):
        class Unusable:
            @property
            def root(self):
                raise RuntimeError("the frame went away")

            @property
            def root_now(self):
                """The no-wait resolve, which on a page-rooted side *is* `root`
                -- that is the base-class default (`Side.root_now`), and the seam
                reaches for this one since #292. Present here so the double
                models `Side` rather than diverging from it: without it the
                unreadable side would raise `AttributeError` and this test would
                pin the wrong failure."""
                return self.root

        outcome = discard_quietly(Unusable())
        self.assertEqual(outcome["discarded"], False)
        self.assertEqual(outcome["error"], "RuntimeError")
        self.assertIs(outcome["dirty"], True,
                      "unknown is reported as dirty, because the verdict must fail closed")

    def test_the_discard_button_is_matched_on_visibility_not_on_dom_order(self):
        """`.first` takes the first match whatever its state, so one hidden
        earlier indicator -- a dialog's, a sub-form's -- would make the check
        decide the form has no discard button and skip the real one. This
        repository's idiom for the same button is `>> visible=true`."""
        source = inspect.getsource(discard_form)
        self.assertIn('DISCARD_BUTTON + " >> visible=true"', source)

    def test_a_discard_is_only_clicked_on_a_form_that_shows_the_button(self):
        """The button is in the DOM on a clean form too, behind
        `o_form_status_indicator_buttons.invisible`. Playwright's `click()` waits
        for visibility, so a clean form would burn the whole timeout -- #238's
        run lost a measurement to exactly that on the save button.

        The mechanism the code uses for that is `button.count()` on a
        visibility-filtered selector, read *before* the click. This assertion
        used to look for `is_visible()`, which `discard_form` has never called:
        it was green off the word appearing in a comment, and #292's rewrite of
        those comments is what exposed it (`source-shape-assertions`).

        Both halves are matched on the **whole gate line** and not on
        `button.count()` alone, which is the same trap one layer down: the
        comment above the locator names `button.count()` too, so a bare
        `index()` resolves inside prose that no edit to the code can move, and
        the ordering half would hold over a version that clicked first.
        `DiscardSeamTests.test_a_dirty_form_with_no_visible_button_is_left_dirty`
        is the behavioural guard; this is the shape beside it."""
        source = inspect.getsource(discard_form)
        gate = "if not dirty or not button.count():"
        self.assertIn(gate, source)
        self.assertLess(source.index(gate), source.index("button.click()"))
        self.assertIn("dirty", source, "and it reports whether there was anything to discard")

    def test_a_discard_is_waited_on_rather_than_clicked_and_left(self):
        """`FormController.discard()` is asynchronous and `click()` returns well
        before it resolves. Anything that navigates in that window leaves the
        field still dirty, and the form's `beforeunload` save -- a `sendBeacon`
        nothing can intercept or cancel -- writes it anyway. The wait on the
        indicator going clean is what closes that window."""
        source = inspect.getsource(discard_form)
        self.assertIn('wait_for(state="hidden"', source)
        self.assertLess(source.index("button.click()"),
                        source.index('wait_for(state="hidden"'))


class DiscardSeamTests(unittest.TestCase):
    """#292: the seam is driven here, not only pinned at its shape.

    The three readings `discard_form` produces were held by source assertions
    alone, and the one defect that mattered is invisible to those: on
    `IngressSide`, `side.root` is a *search* that re-enters `_find_frame`'s 60 s
    sweep whenever the held frame reports detached, and the frame of a re-mounted
    Ingress panel is exactly that. The sweep then answers with the replacement,
    whose freshly loaded document has no `UNSAVED` match -- so the entry read
    counted zero and the function reported "the form was never dirty" for a form
    that went with its frame, at the moment `beforeunload` fired its
    uninterceptable save. #280 removed that misreading from the markup driver's
    sibling seam and #288 shut this third door there; these drive it here.
    """

    class Locator:
        """What `Frame.locator` hands back, as this seam uses it."""

        def __init__(self, root, selector):
            self.root = root
            self.selector = selector

        @property
        def first(self):
            return self

        def count(self):
            if self.selector == UNSAVED:
                return 1 if self.root.dirty else 0
            # The visible-button selector: present on a dirty form unless the
            # form is readonly, where the button is absent from the DOM.
            return 1 if self.root.button else 0

        def click(self, **kwargs):
            self.root.clicks.append((self.selector, kwargs))

        def wait_for(self, **kwargs):
            self.root.waits.append((self.selector, kwargs))
            if self.selector == UNSAVED and kwargs.get("state") == "hidden" \
                    and self.root.never_clean:
                # Playwright's shape for the form that will not go clean: an
                # invalid record keeps the indicator up, so it never does.
                raise RuntimeError("Timeout %sms exceeded" % kwargs.get("timeout"))

    class ReplacementFrame:
        """What the waiting resolve finds once the panel has re-mounted: a
        freshly loaded document, with none of the form the caller was reading. It
        answers `UNSAVED` with zero, and zero reads as "never dirty".
        """

        dirty = False
        button = True
        never_clean = False

        def __init__(self):
            self.clicks = []
            self.waits = []

        def locator(self, selector):
            return DiscardSeamTests.Locator(self, selector)

    class DetachedFrame:
        """The held Ingress frame after the panel re-mounted.

        The raise comes from `count()` and not from `locator()`, which is
        Playwright's real shape: `Frame.locator` builds a selector object without
        touching the browser, so a frame that has gone raises nothing there and
        the detach surfaces at the first call that needs an answer.
        """

        def locator(self, selector):
            return self

        @property
        def first(self):
            return self

        def count(self):
            raise RuntimeError("Frame was detached")

    class FakeSide:
        """A form page as `discard_form` reads it, and the side around it.

        `detached` is the re-mounted panel: the side is *holding* a frame that
        has gone, while the waiting resolve would answer with the replacement it
        has since mounted. Both resolves are counted, because which one the seam
        reaches for is the whole difference.
        """

        def __init__(self, *, dirty=True, button=True, never_clean=False, detached=False):
            self.dirty = dirty
            self.button = button
            self.never_clean = never_clean
            self.detached = detached
            self.clicks = []
            self.waits = []
            self.settled = 0
            self.root_reads = 0
            self.root_now_reads = 0

        @property
        def root(self):
            self.root_reads += 1
            if self.detached:
                return DiscardSeamTests.ReplacementFrame()
            return self

        @property
        def root_now(self):
            self.root_now_reads += 1
            return DiscardSeamTests.DetachedFrame() if self.detached else self

        def locator(self, selector):
            return DiscardSeamTests.Locator(self, selector)

        def settle(self, ms=800):
            self.settled += 1

    def test_a_clean_form_reports_both_readings_negative_and_is_not_clicked(self):
        side = self.FakeSide(dirty=False)
        self.assertEqual(discard_form(side), {"dirty": False, "discarded": False})
        self.assertEqual(side.clicks, [], "nothing to discard, so nothing is clicked")

    def test_a_discard_that_came_off_reports_dirty_and_discarded(self):
        side = self.FakeSide()
        self.assertEqual(discard_form(side), {"dirty": True, "discarded": True})
        self.assertEqual([selector for selector, _ in side.clicks],
                         [DISCARD_BUTTON + " >> visible=true"])
        self.assertEqual([(selector, kwargs.get("state")) for selector, kwargs in side.waits],
                         [(UNSAVED, "hidden")], "and `true` means the form came clean")

    def test_a_dirty_form_with_no_visible_button_is_left_dirty(self):
        """A readonly form has no discard button in the DOM at all, and `.first`
        on a selector with no match would spend the click's whole timeout."""
        side = self.FakeSide(button=False)
        self.assertEqual(discard_form(side), {"dirty": True, "discarded": False})
        self.assertEqual(side.clicks, [])

    def test_a_confirmation_that_never_arrives_is_a_reading_through_the_wrapper(self):
        """The form that will not go clean: the click went in and the indicator
        is still up when the wait runs out. `discard_form` raises, and the
        wrapper is what turns that into the third reading."""
        side = self.FakeSide(never_clean=True)
        self.assertEqual(discard_quietly(side),
                         {"dirty": True, "discarded": False, "error": "RuntimeError"})
        self.assertEqual(side.settled, 0, "the seam did not reach its settle")

    def test_the_seam_resolves_the_no_wait_root_once_and_never_the_waiting_one(self):
        """Neither resolve is a field: both are properties, and the waiting one
        re-enters `_find_frame(wait_s=60)` whenever the Ingress iframe reports
        detached. So the seam takes `side.root_now` (#288) -- and takes it once,
        working through the frame it got (#280), on every path it has."""
        for side in (self.FakeSide(), self.FakeSide(dirty=False),
                     self.FakeSide(button=False)):
            discard_form(side)
            self.assertEqual(side.root_now_reads, 1)
            self.assertEqual(side.root_reads, 0)
        side = self.FakeSide(never_clean=True)
        discard_quietly(side)
        self.assertEqual(side.root_now_reads, 1)
        self.assertEqual(side.root_reads, 0)

    def test_a_detached_held_frame_is_reported_dirty_and_not_never_dirty(self):
        """The door #292 exists to shut. The panel re-mounted its Ingress iframe,
        so the frame the side holds is detached and the dirty form went with it.
        Reaching for the waiting resolve would hand back the replacement, count
        zero `UNSAVED` matches and report a form that was never dirty -- over a
        detach that is exactly when `beforeunload` fires its `sendBeacon`. Held
        once through `root_now`, the first locator call raises instead, and the
        wrapper's reading stays dirty: unknown fails closed."""
        side = self.FakeSide(detached=True)
        self.assertEqual(discard_quietly(side),
                         {"dirty": True, "discarded": False, "error": "RuntimeError"})
        self.assertEqual(side.root_reads, 0,
                         "the replacement frame is never consulted")

    def test_the_seam_says_why_the_no_wait_resolve_and_not_the_waiting_one(self):
        """The reason is not legible from the call, and the next reader of this
        seam is the one who has to not undo it: the entry read's replacement-frame
        door is the specific thing the explanation has to name."""
        source = inspect.getsource(discard_form)
        self.assertIn("root_now", source)
        self.assertNotIn("side.root.", source, "no reach for the waiting resolve is left")
        self.assertIn("_find_frame", source, "naming the search a read of `root` can enter")
        self.assertIn("replacement", source,
                      "and the frame a re-mounted panel resolves to instead")


class BehaviourIsWrittenDownTests(unittest.TestCase):
    """#263: three documents state what `probe` does, and all three were wrong.

    The docstring, `docs/agents/live-tier.md` and the parity plan all said the
    step wrote nothing while it wrote on every run. A reader trusted them and ran
    it on a host. So each is pinned to the code here -- not the prose, but the
    claim that misled: *how* nothing is written, and what a `delivered` of 0.0
    seconds is worth.
    """

    def test_the_module_says_discarding_is_what_makes_probe_safe(self):
        import e2e_collab_peer_snapshot_live as module

        docstring = module.__doc__
        self.assertIn("Discard", docstring,
                      "the module must say *how* `probe` writes nothing")
        self.assertIn("#263", docstring)
        self.assertIn("wrote_nothing", docstring,
                      "and that the claim is measured and reported")
        self.assertIn("Discard", inspect.getdoc(module.do_probe),
                      "and so must the command's own docstring")

    def test_the_module_records_the_write_path_a_discard_cannot_close(self):
        """Odoo also saves a form on `visibilitychange`, ungated on dirtiness, and
        the sending session is necessarily dirty while the receiving one opens.
        That cannot be designed away here, so it is written down -- and the
        read-back, not the discard, is what the module offers as the guarantee. A
        future editor tidying the docstring must not quietly drop it."""
        import e2e_collab_peer_snapshot_live as module

        self.assertIn("visibilitychange", module.__doc__)
        self.assertIn("read-back is the guarantee", module.__doc__)
        self.assertIn("visibilitychange", LIVE_TIER_DOC.read_text(encoding="utf-8"))

    def test_the_live_tier_doc_says_how_probe_writes_nothing(self):
        """It is the file an agent reads before the first command, and the one
        whose "writes nothing" a reader acted on."""
        doc = LIVE_TIER_DOC.read_text(encoding="utf-8")
        self.assertIn("e2e_collab_peer_snapshot_live.py", doc)
        self.assertIn("Discard", doc,
                      "the Live-tier doc must say that `probe` discards both forms")
        self.assertIn("#263", doc)

    def test_the_module_says_why_nothing_had_ever_been_delivered(self):
        """#265. The cause is a step this driver did not take, and it is invisible
        from the host: a reader who finds `delivered: false` and no explanation
        reaches for the gateway or the bus, which is what three documents did."""
        import e2e_collab_peer_snapshot_live as module

        said = " ".join(module.__doc__.split())
        self.assertIn("#265", said)
        self.assertIn("focus", said)
        self.assertIn("focus_editable", said)
        self.assertIn("heal_under_ingress", said)
        self.assertIn("focus", inspect.getdoc(module.focus_editable))

    def test_the_live_tier_doc_says_the_receiver_is_focused_and_why(self):
        """It is the file an agent reads before the first command, and the place a
        `delivered: false` will be read next time. It has to send that reader to
        the record's own `collaboration` block before the host."""
        doc = LIVE_TIER_DOC.read_text(encoding="utf-8")
        self.assertIn("#265", doc)
        self.assertIn("focus", doc)
        self.assertIn("collaborative_trigger", doc)
        self.assertIn("ingress-public", doc)

    def test_the_plan_registers_the_two_fields_the_record_grew(self):
        """Section 12 is where a record's fields and their readings are declared.
        The schema name did not change -- these are additive -- so the section is
        the only place that says a reader should expect them."""
        plan = PARITY_PLAN.read_text(encoding="utf-8")
        section = plan[plan.index("## 12. "):]
        for said in ("#265", "`collaboration`", "`healing`", "final_verdict",
                     "with_no_delivery", "marker(run_id, label, pair)"):
            self.assertIn(said, section, said)

    def test_the_evidence_conventions_distrust_a_zero_second_delivery(self):
        """Section 12 is where a record's fields and their readings are declared,
        and `waited_seconds: 0.0` is a reading: it is what a constant marker
        produced on #243's run while the transport delivered nothing."""
        plan = PARITY_PLAN.read_text(encoding="utf-8")
        section = plan[plan.index("## 12. "):]
        self.assertIn("waited_seconds", section,
                      "section 12 must name the field a reader has to distrust")
        self.assertIn("0.0", section)
        self.assertIn("#263", section)


class AmbientFigureTests(unittest.TestCase):
    """#264: this run counts the ambient rows it left, and does not assume them.

    Source pins, for this file's own reason: the counting happens in a browser
    against a host, and what went wrong in the family it belongs to was a figure
    nobody read rather than a value some function returned. #243's run left no
    figure at all and its evidence had to state an absolute count read on the
    host afterwards.
    """

    def test_both_commands_read_the_figure(self):
        for command in (do_probe, do_run):
            source = inspect.getsource(command)
            with self.subTest(command.__name__):
                self.assertIn("ambient_accounting(", source)
                self.assertIn("ambient_figure(first, second)", source)
                self.assertIn("navigation_basis=AMBIENT_BASIS", source)

    def test_the_window_opens_before_the_staging_navigates(self):
        """`stage` opens the to-do on both sessions, and those navigations have to
        be inside the figure. So the pair is opened by the command -- the first
        reading goes over a session's own RPC and cannot be taken before one
        exists -- and `stage` takes the two sessions it was given."""
        self.assertEqual(list(inspect.signature(stage).parameters),
                         ["first", "second", "task_id", "marker_text"])
        for command in (do_probe, do_run):
            source = inspect.getsource(command)
            with self.subTest(command.__name__):
                self.assertLess(source.index("open_pair("), source.index("ambient_accounting("))
                self.assertLess(source.index("ambient_accounting("), source.index("stage("))

    def test_a_failure_in_staging_now_closes_both_contexts(self):
        """It used to leave them to `browser.close()` in `main`, because `stage`
        both opened them and could raise before handing them back."""
        for command in (do_probe, do_run):
            source = inspect.getsource(command)
            with self.subTest(command.__name__):
                self.assertLess(source.index("open_pair("), source.index("try:"))
                self.assertIn("side.close()", source)

    def test_run_appends_its_figure_beside_the_records_it_appends(self):
        source = inspect.getsource(do_run)
        self.assertIn("out_path, command=\"run\", append=True", source)

    def test_probe_keeps_no_file_so_its_figure_is_printed(self):
        """`probe` prints and keeps nothing, which is the one thing about it that
        #263 did not change. A figure with nothing to sit beside is still read:
        "it writes nothing" is a claim about the field, never about the rows a
        page view leaves."""
        source = inspect.getsource(do_probe)
        self.assertIn("None, command=\"probe\"", source)

    def test_the_counts_come_over_the_session_and_never_over_ssh(self):
        """#256's rule, and the reason the figure is the run's own: a count read
        on the host afterwards is a different measurement, and two of them taken
        on different days cannot be subtracted."""
        import e2e_collab_peer_snapshot_live as module

        source = inspect.getsource(module.ambient_figure)
        self.assertIn("SessionAmbientDriver(first, second", source)
        self.assertNotIn("ssh", source)
        self.assertIn("mask=", source, "a reason in the record carries the host and the prefix")

    def test_a_measured_exit_code_is_returned_outside_the_accounting(self):
        """`ambient_accounting` raises a figure it could not write when the body
        left no exception of its own -- and a `return` from inside the `with` is
        exactly that. Both commands' exit codes are measurements: `probe`'s carries
        `wrote_nothing` (#263) and `run`'s carries the stored verdict, and `main`'s
        catch-all turns anything raised into exit 2. So the code is read inside the
        window and returned outside it, the way the adapter returns its own."""
        for command in (do_probe, do_run):
            source = inspect.getsource(command)
            lines = source.splitlines()
            opened = [len(line) - len(line.lstrip()) for line in lines
                      if line.lstrip().startswith("with ambient_accounting(")]
            returns = [len(line) - len(line.lstrip()) for line in lines
                       if line.lstrip().startswith("return ")]
            with self.subTest(command.__name__):
                self.assertEqual(len(opened), 1)
                self.assertTrue(returns)
                for indent in returns:
                    self.assertLessEqual(indent, opened[0],
                                         "a return inside the accounting makes its body look clean")

    def test_the_module_says_the_expected_zero_is_a_reading(self):
        """The delta here should be zero -- `/odoo/...` renders no tracked page --
        and that is the reason to read it rather than to skip it."""
        import e2e_collab_peer_snapshot_live as module

        said = " ".join(module.__doc__.split())
        self.assertIn("peer.ambient.json", said)
        self.assertIn("a zero that is read is a reading", said)
        self.assertIn("#264", said)
        self.assertIn("never over `ssh`", said)


if __name__ == "__main__":
    unittest.main()
