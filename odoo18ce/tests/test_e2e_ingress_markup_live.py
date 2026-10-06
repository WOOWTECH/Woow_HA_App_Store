"""The pure parts of `e2e_ingress_markup_live.py`, and the traps they exist for.

The driver needs a host and a browser. What can be tested without either is
every judgement it makes, and there are four places where getting one subtly
wrong would produce a record that reads clean:

1. **A picture's verdict is surface-dependent.** Under Ingress a root-relative
   `src` must resolve *under* the prefix; on the Public origin the same `src`
   must resolve at the origin *root*, and a prefix appearing there at all is a
   `sub_filter` that leaked out of the Ingress asset location. One function
   answers both, and it must not answer the Ingress question on the Public
   surface -- which is what a hardcoded `Surface.HA_INGRESS` would do, the way
   `e2e_ingress_hand_checks.Signals.escapes` was written when it only ever ran
   on one surface.
2. **Prefix escape is `adapter.is_prefix_escape`, never a local rewrite.** The
   shape this file refuses to reimplement is the doubled prefix: still *under*
   the prefix, and still an escape. `test_e2e_ingress_hand_checks.py` exists
   because a review caught exactly that, and the same trap is reachable here.
3. **A stored value's verdict is the gateway's own prefix shape.** It comes
   from `e2e_collab_peer_snapshot_live.ingress_prefixes`, whose shape is
   derived from the gateway template and pinned against it, so this module
   cannot grow a second, drifting regex.
4. **No Supervisor token may reach a record.** Every value written out goes
   through the redaction, including the stored field values the whole run is
   about.
"""
import base64
import inspect
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import e2e_collab_peer_snapshot_live as peer  # noqa: E402
import e2e_ingress_markup_live as markup  # noqa: E402
import e2e_menu_action_adapter as adapter  # noqa: E402

HA_ORIGIN = "http://192.0.2.10:8123"
PREFIX = "/api/hassio_ingress/Tok3nTok3nTok3nTok3n"
INGRESS_BASE = HA_ORIGIN + PREFIX
PUBLIC_ORIGIN = "https://odoo.example.test"

PICTURE = "/web/image/res.company/1/logo"
INGRESS = adapter.Surface.HA_INGRESS
PUBLIC = adapter.Surface.PUBLIC


def ingress_verdict(resolved, loaded=True):
    return markup.picture_verdict(INGRESS, HA_ORIGIN, PREFIX, resolved, loaded)


def public_verdict(resolved, loaded=True):
    return markup.picture_verdict(PUBLIC, PUBLIC_ORIGIN, None, resolved, loaded)


# --- 1. The picture verdict, on each surface ----------------------------------


def test_the_prefixed_picture_is_what_the_ingress_surface_wants():
    """#237 checks 1 and 2, #240 (a), #239's image lines: the fix working."""
    assert ingress_verdict(INGRESS_BASE + PICTURE) == markup.UNDER_PREFIX


def test_the_home_assistant_root_is_the_escape_the_fix_removed():
    """The 0.4.9 shape of an unfixed readonly field: asked of the HA root."""
    assert ingress_verdict(HA_ORIGIN + PICTURE) == markup.ESCAPED


def test_the_doubled_prefix_is_an_escape_and_not_a_pass():
    """Still under the prefix, so "did it leave the prefix" answers no.

    The one shape a local rewrite of the judgement loses. It is reachable here
    because every rule in this family prefixes a value that may already carry
    one.
    """
    doubled = INGRESS_BASE + PREFIX + PICTURE
    assert doubled.startswith(INGRESS_BASE)
    assert ingress_verdict(doubled) == markup.ESCAPED


def test_the_origin_root_is_what_the_public_surface_wants():
    """#237 check 3: the half that says a `sub_filter` did not leak."""
    assert public_verdict(PUBLIC_ORIGIN + PICTURE) == markup.AT_ORIGIN_ROOT


def test_an_ingress_prefix_on_the_public_origin_is_an_escape():
    """A leaked rule: the Public origin serves no shim and no rewrite.

    This is the assertion that fails if the function judges every surface as
    Ingress -- under that reading the path is simply "not the HA origin" and
    passes.
    """
    leaked = PUBLIC_ORIGIN + PREFIX + PICTURE
    assert public_verdict(leaked) == markup.ESCAPED


def test_the_two_surfaces_disagree_about_the_same_resolved_url():
    """The whole reason the surface is a parameter and not a constant."""
    at_root = HA_ORIGIN + PICTURE
    assert ingress_verdict(at_root) == markup.ESCAPED
    assert markup.picture_verdict(PUBLIC, HA_ORIGIN, None, at_root, True) == markup.AT_ORIGIN_ROOT


def test_the_escape_half_of_the_verdict_is_the_adapter_s():
    """Not a tautology: it fails if the module stops delegating.

    Every url is asked of both, and the verdict's escape branch has to agree
    with the adapter on every one of them.
    """
    cases = [
        (INGRESS, HA_ORIGIN, PREFIX, INGRESS_BASE + PICTURE),
        (INGRESS, HA_ORIGIN, PREFIX, HA_ORIGIN + PICTURE),
        (INGRESS, HA_ORIGIN, PREFIX, INGRESS_BASE + PREFIX + PICTURE),
        (INGRESS, HA_ORIGIN, PREFIX, INGRESS_BASE),
        (PUBLIC, PUBLIC_ORIGIN, None, PUBLIC_ORIGIN + PICTURE),
        (PUBLIC, PUBLIC_ORIGIN, None, PUBLIC_ORIGIN + PREFIX + PICTURE),
    ]
    for surface, origin, prefix, url in cases:
        escaped = adapter.is_prefix_escape(url, surface, origin, prefix)
        verdict = markup.picture_verdict(surface, origin, prefix, url, True)
        assert (verdict == markup.ESCAPED) is escaped, url


def test_a_picture_that_resolved_right_but_never_arrived_is_not_a_pass():
    """`complete && naturalWidth > 0` is the half that says the byte arrived.

    A rule can prefix a URL correctly and still name nothing, which is a 404
    and a `http_4xx_5xx` -- but the picture verdict has to say so on its own,
    because the signal counts are for the whole page.
    """
    assert ingress_verdict(INGRESS_BASE + PICTURE, loaded=False) == markup.NOT_LOADED
    assert public_verdict(PUBLIC_ORIGIN + PICTURE, loaded=False) == markup.NOT_LOADED


def test_an_escape_outranks_a_picture_that_did_not_load():
    """Both are true of an unfixed field under Ingress; the escape is the finding."""
    assert ingress_verdict(HA_ORIGIN + PICTURE, loaded=False) == markup.ESCAPED


def test_no_picture_at_all_is_named_rather_than_passed():
    """An empty screen must not read as a clean one.

    The shape this catches is a selector that stopped matching: #240's own row
    warns that a full-HTML value renders no editor, and #237's that the
    `cssAssetId` branch renders a different target.
    """
    assert ingress_verdict(None) == markup.ABSENT
    assert markup.screen_verdict([]) == markup.ABSENT


def test_a_third_party_picture_is_not_this_surface_s_question():
    """And it is *named* as such rather than counted as a prefixed picture.

    `is_prefix_escape` answers `False` both for "this is fine" and for "this is
    none of my business", so a verdict built on it alone would report
    `UNDER-PREFIX` -- asserting the prefix was involved when it never was.
    """
    assert ingress_verdict("https://cdn.example.test/logo.png") == markup.NOT_A_PREFIX_QUESTION


# --- The screen's verdict: the worst picture on it ----------------------------


def test_the_screen_takes_the_worst_verdict_of_its_pictures():
    assert markup.screen_verdict([markup.UNDER_PREFIX, markup.UNDER_PREFIX]) == markup.UNDER_PREFIX
    assert markup.screen_verdict([markup.UNDER_PREFIX, markup.NOT_LOADED]) == markup.NOT_LOADED
    assert markup.screen_verdict([markup.NOT_LOADED, markup.ESCAPED]) == markup.ESCAPED
    assert markup.screen_verdict([markup.UNDER_PREFIX, markup.ABSENT]) == markup.ABSENT


def test_every_picture_verdict_has_a_rank():
    """A new verdict cannot be added without deciding how bad it is."""
    for verdict in markup.PICTURE_VERDICTS:
        assert verdict in markup.PICTURE_SEVERITY


def test_a_screen_verdict_is_a_pass_only_on_the_two_expected_values():
    """`PASSING` is what the evidence table reads; the rest are findings."""
    assert markup.PASSING == frozenset({markup.UNDER_PREFIX, markup.AT_ORIGIN_ROOT})
    for verdict in markup.PICTURE_VERDICTS:
        assert markup.is_pass(verdict) is (verdict in markup.PASSING)


def test_the_expected_verdict_for_a_surface_is_the_one_the_run_compares_against():
    """Each surface has exactly one passing verdict, and they are not the same."""
    assert markup.expected_verdict(INGRESS) == markup.UNDER_PREFIX
    assert markup.expected_verdict(PUBLIC) == markup.AT_ORIGIN_ROOT


# --- 3. The stored value -----------------------------------------------------


def test_a_root_relative_stored_value_is_clean():
    """#237 check 4, #240 (b), #238's two fields: nothing stored a prefix."""
    stored = '<p>x</p><img src="%s">' % PICTURE
    assert markup.stored_verdict(stored) == (markup.CLEAN, 0)


def test_a_stored_prefix_is_the_finding_the_read_back_exists_for():
    stored = '<img src="%s%s">' % (PREFIX, PICTURE)
    assert markup.stored_verdict(stored) == (markup.PREFIX_STORED, 1)


def test_two_different_stored_prefixes_are_both_counted():
    other = "/api/hassio_ingress/0therT0kenMoreThan16"
    stored = '<img src="%s/a"><img src="%s/b">' % (PREFIX, other)
    assert markup.stored_verdict(stored) == (markup.PREFIX_STORED, 2)


def test_an_empty_html_field_is_clean_rather_than_an_error():
    """An html field with no value comes back `False` from the ORM, not `""`."""
    for empty in (None, "", False):
        assert markup.stored_verdict(empty) == (markup.CLEAN, 0)


def test_the_stored_shape_is_the_peer_snapshot_s_and_not_a_second_regex():
    """Not a tautology: it fails if this module grows its own pattern.

    The shape is the gateway's `$safe_ingress_path` map, and
    `test_e2e_collab_peer_snapshot.py` derives it from the template and refuses
    a difference. A second copy here would drift away from the add-on without
    anything noticing.
    """
    assert markup.ingress_prefixes is peer.ingress_prefixes
    for value in vars(markup).values():
        if isinstance(value, re.Pattern) and "hassio_ingress" in value.pattern:
            assert value is peer.INGRESS_PREFIX_SHAPE, (
                "this module may hold the peer snapshot's own shape and nothing else "
                "that matches an Ingress prefix")
    # And not in a string either (#266). The document-operand probe reads the
    # served method for a *prefixed* literal, and it spelled the shape out in
    # JavaScript -- twice -- until the shape was handed in instead. A copy there
    # is as free to drift as a second `re.Pattern` and is invisible to the loop
    # above, so both probes are checked as text.
    for name in ("_DOCUMENT_OPERAND_PROBE", "_RULE_PROBE"):
        assert "hassio_ingress" not in getattr(markup, name), name
    assert "spec.prefix_shape" in markup._DOCUMENT_OPERAND_PROBE
    assert "prefix_shape" in inspect.getsource(markup.document_operand_reading)
    assert "INGRESS_PREFIX_SHAPE" in inspect.getsource(markup.document_operand_reading)


def test_a_token_too_short_for_the_gateway_is_not_a_prefix():
    """The shape's own bound, reached through the delegation."""
    assert markup.stored_verdict('<img src="/api/hassio_ingress/short/a">') == (markup.CLEAN, 0)


# --- 4. Redaction ------------------------------------------------------------


def test_the_stored_value_in_a_record_carries_no_token():
    """The run reads a field whose whole point is what prefix is in it."""
    stored = '<img src="%s%s">' % (PREFIX, PICTURE)
    record = markup.evidence_record(
        check="readonly-plain", issue=237, run_id="WOOW-MARKUP-20261001T000000Z",
        database="odoo_parity", target="local", surface=INGRESS,
        screen="/odoo/project.task/7", pictures=[], stored={"project.task.description": stored},
        readings={"project.task.description": markup.STATE_BOUNDING},
    )
    line = markup.json.dumps(record, sort_keys=True)
    assert PREFIX not in line
    assert "Tok3nTok3nTok3nTok3n" not in line
    assert "<ingress:" in line


def test_the_redaction_is_the_peer_snapshot_s():
    """Same reason as the shape: one implementation, already tested."""
    assert markup.redact is peer.redact


def test_a_clean_value_survives_redaction_unchanged():
    stored = '<p>x</p><img src="%s">' % PICTURE
    assert markup.redact(stored, {}) == stored


# --- The record and the registry ---------------------------------------------


def test_the_record_names_its_schema_and_issue():
    record = markup.evidence_record(
        check="readonly-plain", issue=237, run_id="R", database="odoo_parity",
        target="local", surface=INGRESS, screen="/x", pictures=[], stored={},
    )
    assert record["schema"] == markup.EVIDENCE_SCHEMA
    assert record["issue"] == 237
    assert record["check"] == "readonly-plain"
    assert record["surface"] == INGRESS.value


def test_a_record_with_no_reading_is_not_run_rather_than_a_pass():
    record = markup.evidence_record(
        check="readonly-plain", issue=237, run_id="R", database="odoo_parity",
        target="local", surface=INGRESS, screen="/x", pictures=None, stored={},
    )
    assert record["verdict"] == markup.NOT_RUN


def test_the_record_s_verdict_is_the_screen_s():
    record = markup.evidence_record(
        check="readonly-plain", issue=237, run_id="R", database="odoo_parity",
        target="local", surface=INGRESS, screen="/x",
        pictures=[{"verdict": markup.UNDER_PREFIX}, {"verdict": markup.ESCAPED}], stored={},
    )
    assert record["verdict"] == markup.ESCAPED


def test_a_stored_prefix_fails_the_record_even_when_the_screen_rendered():
    """#237 check 4's point: the screen passing says nothing about the write."""
    stored = '<img src="%s%s">' % (PREFIX, PICTURE)
    record = markup.evidence_record(
        check="codeview", issue=240, run_id="R", database="odoo_parity",
        target="local", surface=INGRESS, screen="/x",
        pictures=[{"verdict": markup.UNDER_PREFIX}],
        stored={"res.users.signature": stored},
        readings={"res.users.signature": markup.WRITE_BOUNDING},
    )
    assert record["verdict"] == markup.PREFIX_STORED
    assert record["stored_verdict"] == markup.PREFIX_STORED


@pytest.mark.parametrize("check", sorted(markup.CHECKS))
def test_every_check_the_parser_takes_has_a_branch_and_a_row(check):
    """The parser's choices, `run`'s branches and the register cannot drift."""
    assert hasattr(markup, "do_" + check.replace("-", "_"))
    row = markup.CHECKS[check]
    assert row["issue"] in {234, 237, 238, 239, 240}
    assert isinstance(row["writes"], bool)
    assert row["surfaces"]
    for surface in row["surfaces"]:
        assert surface in {"ingress", "public"}


def test_every_register_row_this_module_carries_has_at_least_one_check():
    """#243's register has five rows; #234's is the peer snapshot's own module."""
    covered = {row["issue"] for row in markup.CHECKS.values()}
    assert covered == {237, 238, 239, 240}


def test_the_read_only_checks_are_named_so_they_can_be_run_first():
    """ADR 0012: a run says what it writes, and the cheap read-only checks go
    first so a failure costs nothing on the host."""
    read_only = {name for name, row in markup.CHECKS.items() if not row["writes"]}
    assert read_only
    assert all(not markup.CHECKS[name]["writes"] for name in read_only)
    assert markup.read_only_first(list(markup.CHECKS)) == sorted(
        markup.CHECKS, key=lambda name: (markup.CHECKS[name]["writes"], name))


def test_the_full_html_seed_value_parses_with_a_non_empty_head():
    """`computeContainsComplexHTML()` is what chooses the iframe path, and it
    chooses it for a value whose parse yields a non-empty `<head>`. A seed
    without one would render the plain path and measure check 1 twice."""
    assert "<head>" in markup.FULL_HTML_VALUE
    assert "<style" in markup.FULL_HTML_VALUE
    assert 'src="/' in markup.FULL_HTML_VALUE
    assert PREFIX not in markup.FULL_HTML_VALUE


def test_the_seeded_value_is_root_relative_so_the_read_back_means_something():
    """Check 4 reads the field back expecting root-relative. If the seed were
    written with a prefix the check could not tell a write from the seed."""
    assert markup.stored_verdict(markup.FULL_HTML_VALUE) == (markup.CLEAN, 0)


def test_the_signature_seed_is_a_fragment_and_not_full_html():
    """#240's row: a full-HTML value renders the readonly viewer and no editor,
    so `toggleCodeView` never reaches the assignment the rules patch."""
    assert "<head>" not in markup.SIGNATURE_VALUE
    assert 'src="/' in markup.SIGNATURE_VALUE
    assert markup.stored_verdict(markup.SIGNATURE_VALUE) == (markup.CLEAN, 0)


def test_the_marker_names_its_run():
    assert markup.marker_for("WOOW-MARKUP-20261001T073009Z").endswith("WOOW-MARKUP-20261001T073009Z")
    assert markup.marker_for("A") != markup.marker_for("B")


def test_the_scratch_task_name_says_it_is_this_run_s_and_disposable():
    """The run must be able to find and delete what it made, and a reader of
    the host must be able to tell it from the onboarding to-do #235 reads."""
    name = markup.scratch_task_name("WOOW-MARKUP-20261001T073009Z")
    assert "WOOW-MARKUP-20261001T073009Z" in name
    assert "scratch" in name.lower()


def test_the_report_counts_each_verdict_and_names_the_failures():
    records = [
        {"check": "readonly-plain", "issue": 237, "surface": "ha_ingress", "verdict": markup.UNDER_PREFIX},
        {"check": "readonly-plain", "issue": 237, "surface": "public", "verdict": markup.AT_ORIGIN_ROOT},
        {"check": "codeview", "issue": 240, "surface": "ha_ingress", "verdict": markup.ESCAPED},
    ]
    summary = markup.summarise(records)
    assert summary["passed"] == 2
    assert summary["failed"] == 1
    assert summary["failures"] == ["codeview/ha_ingress: " + markup.ESCAPED]


def test_the_report_says_which_checks_never_ran():
    """A partial run has to be legible as partial; #243 may be cut short."""
    summary = markup.summarise([
        {"check": "readonly-plain", "issue": 237, "surface": "ha_ingress", "verdict": markup.UNDER_PREFIX},
    ])
    assert "readonly-iframe" in summary["not_run"]
    assert "readonly-plain" not in summary["not_run"]


def test_a_check_s_extra_readings_cannot_overwrite_the_verdict():
    """`extra` is merged flat into the record, so a key collision would let a
    flow silently replace the verdict or the schema with one of its own
    readings. The eight flows use no such key today; the guard is for the ninth.
    """
    with pytest.raises(ValueError, match="verdict"):
        markup.evidence_record(
            check="codeview", issue=240, run_id="R", database="odoo_parity",
            target="local", surface=INGRESS, screen="/x",
            pictures=[{"verdict": markup.ESCAPED}], stored={},
            extra={"verdict": markup.UNDER_PREFIX},
        )


def test_an_extra_reading_with_its_own_name_is_kept():
    record = markup.evidence_record(
        check="codeview", issue=240, run_id="R", database="odoo_parity",
        target="local", surface=INGRESS, screen="/x",
        pictures=[{"verdict": markup.UNDER_PREFIX}], stored={},
        extra={"uid": 2, "debug": "1"},
    )
    assert record["uid"] == 2 and record["debug"] == "1"
    assert record["verdict"] == markup.UNDER_PREFIX


def test_every_flow_s_extra_keys_stay_clear_of_the_record_s_own():
    """A standing check on the names the nine flows actually use."""
    used = {"task_id", "created_task", "deleted_task", "rendered_iframe", "sandbox",
            "mailing_id", "uid", "signature_before", "signature_restored", "debug",
            "code_view_shown", "code_view_bytes", "element", "dialog", "editor",
            "replace_control", "theme", "saved", "unsaved_after_save", "body_arch_before",
            "body_restored", "revisions", "has_description_history", "form",
            # #266's two fixture-building media checks
            "fixture", "fixture_removed", "element_after_select", "operand",
            "replace_control_present", "replace_control_visible",
            "replace_control_found_in", "discarded", "read_back_error",
            # #274's reading: where the mailing came from
            "mailing_source",
            # #276: did `commitChanges` inline `body_html` at all, and #279:
            # whether the marker that reading looks for was there beforehand
            "body_html_inlined", "body_html_marker_before", "save_visible",
            "typing_error", "save_incomplete",
            "help_restored"}
    assert not (used & markup.RESERVED_RECORD_KEYS)


# --- The entrypoint, and the ordering bug that made the driver unrunnable ------


def test_the_entrypoint_guard_comes_after_every_handler():
    """The driver was once entirely unrunnable, and no test noticed.

    `if __name__ == "__main__": raise SystemExit(main())` sat above the eight
    `do_*` definitions, so executing the file -- the only way it is ever used --
    reached `handler_for` before those names were bound and every subcommand died
    with `KeyError: 'do_readonly_plain'`. Importing the module binds everything
    first, which is why `hasattr` passed and the bug survived a green suite and a
    `--help` smoke test (both exit before the lookup).
    """
    source = open(markup.__file__, encoding="utf-8").read().split("\n")
    guard = [n for n, line in enumerate(source) if line.startswith('if __name__ ==')]
    handlers = [n for n, line in enumerate(source) if line.startswith("def do_")]
    assert guard, "the module has no __main__ guard"
    assert handlers
    assert guard[0] > max(handlers), (
        "the __main__ guard is above a do_* handler, so running the file cannot "
        "resolve it: move the guard to the end of the module")


def test_resolving_every_handler_is_what_running_the_file_does():
    """`handler_for`, not `hasattr` -- the lookup the driver actually performs."""
    for check in markup.CHECKS:
        assert callable(markup.handler_for(check))


# --- A URL the prefix has no claim on ------------------------------------------


@pytest.mark.parametrize("url", ["data:image/png;base64,iVBORw0KGgo=",
                                 "blob:http://192.0.2.10:8123/a-b-c",
                                 "https://cdn.example.test/x.png"])
def test_a_source_the_prefix_has_no_claim_on_is_named_not_passed(url):
    """`data:` and `blob:` sources are routine in the mail designer and the
    website preview, so this is the common case, not an edge one."""
    assert ingress_verdict(url) == markup.NOT_A_PREFIX_QUESTION
    assert not markup.is_pass(markup.NOT_A_PREFIX_QUESTION)


def test_such_a_source_neither_outvotes_a_real_picture_nor_rescues_a_screen():
    assert markup.screen_verdict(
        [markup.UNDER_PREFIX, markup.NOT_A_PREFIX_QUESTION]) == markup.UNDER_PREFIX
    assert markup.screen_verdict(
        [markup.ESCAPED, markup.NOT_A_PREFIX_QUESTION]) == markup.ESCAPED
    # All of them: the screen measured nothing, which is ABSENT for the same
    # reason an empty screen is.
    assert markup.screen_verdict([markup.NOT_A_PREFIX_QUESTION]) == markup.ABSENT


def test_the_same_origin_test_is_the_adapter_s_netloc():
    """One notion of same-origin, so this cannot disagree with is_prefix_escape."""
    assert markup.is_prefix_question(INGRESS_BASE + PICTURE, INGRESS, HA_ORIGIN)
    assert not markup.is_prefix_question("data:image/png;base64,x", INGRESS, HA_ORIGIN)
    # A default port spelled out is still the same origin, which is the case a
    # string comparison would get wrong.
    assert markup.is_prefix_question("https://odoo.example.test:443" + PICTURE,
                                     PUBLIC, PUBLIC_ORIGIN)


# --- A stored prefix is never erased ------------------------------------------


def test_a_stored_prefix_outranks_an_unreadable_screen():
    """The worst finding this run can make must not be filed as NOT-RUN.

    `summarise` skips `NOT-RUN`, and the check *was* seen so it is not in
    `not_run` either -- so the old order dropped a prefix-reached-a-write out of
    the tally entirely. `do_readonly_iframe` reaches this: it returns no pictures
    when the field renders no iframe, and still reads the field back.
    """
    stored = '<img src="%s%s">' % (PREFIX, PICTURE)
    record = markup.evidence_record(
        check="readonly-iframe", issue=237, run_id="R", database="odoo_parity",
        target="local", surface=INGRESS, screen="/x", pictures=None,
        stored={"project.task.description": stored},
        readings={"project.task.description": markup.WRITE_BOUNDING},
    )
    assert record["verdict"] == markup.PREFIX_STORED
    summary = markup.summarise([record])
    assert summary["failed"] == 1
    assert summary["failures"] == ["readonly-iframe/ha_ingress: " + markup.PREFIX_STORED]


# --- The values this driver writes name their run -----------------------------


def test_both_seeded_values_name_the_run_that_wrote_them():
    """ADR 0012 / live-tier.md: a writing step is marked with its run id. These
    two replace a real user's signature and a real mailing's body, so attributing
    them later matters more than for a scratch record that can be deleted."""
    run_id = "WOOW-MARKUP-20261001T073009Z"
    assert run_id in markup.signature_value(run_id)
    assert run_id in markup.mailing_body_value(run_id)
    # And they are still the shapes the checks need.
    assert "<head>" not in markup.signature_value(run_id)
    assert 'src="/' in markup.signature_value(run_id)
    assert markup.stored_verdict(markup.signature_value(run_id)) == (markup.CLEAN, 0)
    assert markup.stored_verdict(markup.mailing_body_value(run_id)) == (markup.CLEAN, 0)


def test_a_retried_check_is_counted_once_by_its_last_record():
    """A run that re-ran a check after fixing a fixture must not be tallied twice.

    #243's own run retried five of the eight checks -- a selector, a missing
    editable wait, a fixture that was not an attachment -- and every attempt is
    kept in the records, because a past reading is what it recorded. But the
    *verdict* is the last attempt, so the tally has to dedupe by check and
    surface or it reports a fixed check as a failure forever.
    """
    records = [
        {"check": "media-image-todo", "issue": 239, "surface": "ha_ingress", "verdict": markup.ABSENT},
        {"check": "media-image-todo", "issue": 239, "surface": "ha_ingress", "verdict": markup.UNDER_PREFIX},
        {"check": "media-image-todo", "issue": 239, "surface": "public", "verdict": markup.AT_ORIGIN_ROOT},
    ]
    summary = markup.summarise(records)
    assert summary["passed"] == 2
    assert summary["failed"] == 0
    assert summary["failures"] == []
    assert summary["attempts"] == 3


def test_the_two_surfaces_of_one_check_are_counted_separately():
    records = [
        {"check": "codeview", "issue": 240, "surface": "ha_ingress", "verdict": markup.UNDER_PREFIX},
        {"check": "codeview", "issue": 240, "surface": "public", "verdict": markup.ESCAPED},
    ]
    summary = markup.summarise(records)
    assert summary["passed"] == 1 and summary["failed"] == 1


# --- 5. The ambient-row figure (#264) -----------------------------------------
#
# Source pins. The counting needs a browser and a host, and what #264 fixed was
# not a wrong value but a missing reading: #243's run drove the website editor,
# whose preview iframes load tracked pages, and its evidence could only state an
# absolute count read on the host afterwards.


def test_each_surface_reads_the_ambient_rows_it_left():
    source = inspect.getsource(markup.run_check)
    assert "adapter.ambient_accounting(" in source
    assert "adapter.SessionAmbientDriver(side, mask=env.mask)" in source
    assert "command=check" in source, "the check name is this driver's command"
    assert "append=True" in source, "the records append per invocation, so the figure does too"


def test_the_figure_is_per_surface_because_the_session_is():
    """Each surface opens its own `Side`, so the count goes over that session's
    own RPC and the record names which surface it was taken on. A delta over a
    database-wide count cannot be split between two surfaces afterwards."""
    source = inspect.getsource(markup.run_check)
    assert source.index("open_one(env, browser, surface)") < source.index("ambient_accounting(")
    assert "surface, out_path, command=check" in source


def test_the_denominator_counts_the_documents_the_editor_fetched_for_itself():
    """`side.goto` is the only navigation call in this file, and it is not the
    only navigation: `media-image-website` clicks Edit, and the editor loads the
    website page into two preview iframes. Those are the page views that write
    the rows being counted."""
    source = inspect.getsource(markup.run_check)
    assert "navigation_basis=adapter.AMBIENT_BASIS_DOCUMENTS" in source


def test_a_surface_that_already_has_a_record_does_not_get_a_second_one():
    """`summarise` reads the *last* record for a check and surface as its
    verdict, so a failure after the record is on disk -- the accounting raises
    when it is a passing run's only failure -- must not append a `NOT-RUN` line
    that overwrites a verdict this run measured."""
    source = inspect.getsource(markup.run_check)
    assert "if surface.value in kept:" in source
    assert source.index("if surface.value in kept:") < source.index('"the surface could not be driven')


def test_the_module_says_where_the_figure_goes_and_which_check_needs_it():
    said = " ".join(markup.__doc__.split())
    assert adapter.ambient_summary_path("markup.jsonl") in said
    assert "media-image-website" in said
    assert "#256" in said and "#264" in said
    assert "counts only" in said.lower()


def test_a_figure_that_could_not_be_written_does_not_cost_the_other_surface_its_run():
    """`ambient_accounting` raises when the figure is a passing run's only failure
    (#256). Raised where it arrives, on the first surface of a `--surface both`
    run, it would leave the second surface never opened, never measured and with
    no record at all -- not even the `NOT-RUN` fallback, so `summarise` could not
    report the gap either. It is held and raised once every surface has run."""
    source = inspect.getsource(markup.run_check)
    assert "unaccounted.append(error)" in source
    assert "raise unaccounted[0]" in source
    assert source.index("unaccounted.append(error)") < source.index("raise unaccounted[0]")
    # And after the loop, not inside it: the raise sits outside the `for`.
    lines = source.splitlines()
    loop = next(len(line) - len(line.lstrip()) for line in lines if line.lstrip().startswith("for name in"))
    raised = next(len(line) - len(line.lstrip()) for line in lines if line.lstrip() == "raise unaccounted[0]")
    assert raised < loop


def test_a_record_counts_as_kept_only_once_it_is_on_disk():
    """The guard above reads `kept` as "this surface's record is on disk", and the
    `--out` write is the one step in `keep` that can fail. Marking it kept first
    would make that claim false in exactly the case it is consulted, and would
    count a line the file never got as something the run recorded."""
    source = inspect.getsource(markup.run_check)
    assert source.index('open(out_path, "a"') < source.index("kept.add(")
    assert source.index('open(out_path, "a"') < source.index("records.append(")


# --- #239's two owed lines, and the fixtures they needed (#266) ---------------
#
# #243's run reached both and measured neither, for the same reason both times:
# nothing on the host could execute the branch. So the fixtures *are* the
# measurement, and what they contain is as load-bearing as any verdict here.


ATTACHMENT = {"id": 7, "name": "woow-document-fixture-woow-x.txt",
              "mimetype": "text/plain", "checksum": "abc123", "image_src": None}

IMAGE_ATTACHMENT = {"id": 8, "name": "woow-image-fixture-woow-x.png",
                    "mimetype": "image/png", "checksum": "def456",
                    "image_src": "/web/image/8-def456/woow-image-fixture-woow-x.png"}

MEDIA_FLOWS = {
    "media-image-todo": (markup.do_media_image_todo,
                         markup._media_image_todo_after_seeding),
    "media-image-website": (markup.do_media_image_website, markup._website_after_seeding),
    "media-document-todo": (markup.do_media_document_todo,
                            markup._media_document_todo_after_seeding),
    "media-document-mailing": (markup.do_media_document_mailing,
                               markup._document_mailing_after_seeding),
}


def test_the_media_flows_this_file_pins_are_every_media_check():
    """So a tenth check cannot be added without being pinned below."""
    assert set(MEDIA_FLOWS) == {name for name in markup.CHECKS if name.startswith("media-")}


@pytest.mark.parametrize("check", sorted(MEDIA_FLOWS))
def test_every_media_check_records_data_original_src(check):
    """#266 asks for the attribute on **both surfaces for every media check**.

    Including the two document ones, where it is structurally absent: an `<a>`
    has no `src` for the image tools to have optimised, so `None` is the reading
    and an omitted key could not be told apart from a record taken before the
    key existed. The verdict of either document line turns on the `href`, not on
    this -- which is exactly why it has to be recorded rather than inferred.
    """
    source = "".join(inspect.getsource(flow) for flow in MEDIA_FLOWS[check])
    assert '"data_original_src"' in source
    assert 'get_attribute("data-original-src")' in source


def test_the_website_fixture_compares_an_attachment_against_itself():
    """The one property the measurement rests on: `data-original-src` holds the
    attachment's own `image_src`, which is the comparison's other operand. A
    fixture whose two sides were different values could never select a tile, and
    would read exactly like a rule that failed."""
    section = markup.website_fixture_section("WOOW-X", IMAGE_ATTACHMENT)
    assert 'src="%s"' % IMAGE_ATTACHMENT["image_src"] in section
    assert 'data-original-src="%s"' % IMAGE_ATTACHMENT["image_src"] in section


def test_the_website_fixture_carries_what_stops_the_attribute_being_overwritten():
    """`loadImageInfo` early-returns only when **both** `data-original-src` and
    `data-mimetype-before-conversion` are present (`image_processing.js:490-496`).

    Without the second one it would re-fetch the image info in the window
    between the click and the dialog and overwrite the first with the
    root-relative value the ORM just returned -- so under Ingress the branch
    would compare two unprefixed values and pass whether or not rule 2 shipped.
    That is a false pass, and this attribute is what prevents it."""
    section = markup.website_fixture_section("WOOW-X", IMAGE_ATTACHMENT)
    assert 'data-mimetype-before-conversion="image/png"' in section
    assert 'data-original-id="8"' in section


def test_the_website_fixture_is_root_relative_and_names_its_run():
    """It is written into stored arch, so a prefix in it would be a prefix in the
    database -- and `live-tier.md` wants every writing step marked with its run."""
    section = markup.website_fixture_section("WOOW-X", IMAGE_ATTACHMENT)
    assert markup.stored_verdict(section) == (markup.CLEAN, 0)
    assert "WOOW-X" in section
    assert 'alt="%s"' % markup.FIXTURE_IMAGE_ALT in section


def test_the_website_check_finds_its_own_image_and_not_the_first_visible_one():
    """#243 picked "the first visible image" in the preview frame and got
    `/web/image/website/1/logo/My%20Website` -- a record-field image with no
    `data-original-src` at all, which is how that run measured nothing. The
    element under test is named now, so another image cannot stand in for it."""
    source = inspect.getsource(markup._website_after_seeding)
    assert 'img[alt="%s"]' in source and "FIXTURE_IMAGE_ALT" in source
    assert 'locator("img")' not in source


def test_the_website_check_reads_the_attribute_again_after_the_click():
    """`ImageTools._initializeImage` **deletes** the whole `data-original-*`
    group when `loadImage(data-original-src)` is rejected
    (`snippets.options.js:7679-7686`), and that runs between the click and the
    dialog. A record carrying only the before-reading could not tell "the
    attribute was dropped" from "the comparison disagreed"."""
    source = inspect.getsource(markup._website_after_seeding)
    assert '"element_after_select"' in source
    assert source.index('extra["element"]') < source.index("image.click()")
    assert source.index("image.click()") < source.index('extra["element_after_select"]')


def test_each_surface_builds_its_own_fixture_page():
    """`U-D3`'s reason: the two surfaces are separate invocations against one
    database, so a shared name would make the second reuse the first's page."""
    names = {markup.fixture_page_name("WOOW-X", surface)
             for surface in (INGRESS, PUBLIC)}
    assert len(names) == 2
    for name in names:
        assert "woow-x" in name
        assert "_" not in name


def test_the_document_fixture_is_the_dialogs_own_spelling():
    """`createElements` builds `` /web/content/${id}?unique=${checksum}&download=true ``,
    sets `title` and `data-mimetype` (`document_selector.js:69-89`), and
    `media_dialog.js:260` adds `o_image`. A different shape would measure a
    document no user has."""
    markup_text = markup.document_link_markup(ATTACHMENT)
    assert 'class="o_image"' in markup_text
    assert 'href="/web/content/7?unique=abc123&amp;download=true"' in markup_text
    assert 'data-mimetype="text/plain"' in markup_text
    assert ATTACHMENT["name"] in markup_text


def test_the_document_fixture_carries_a_query_string_the_comparison_must_strip():
    """Rule 3's left operand is compared against
    `getAttribute('href').replace(/[?].*/, '')`. A fixture with no query string
    leaves that half of the premise unexercised, so the strip is part of what
    this fixture is for."""
    assert "?" in markup.document_link_markup(ATTACHMENT)
    assert "/web/content/7?" in markup.document_link_markup(ATTACHMENT)


def test_the_document_fixture_body_is_root_relative_and_names_its_run():
    body = markup.mailing_document_body_value("WOOW-X", ATTACHMENT)
    assert markup.stored_verdict(body) == (markup.CLEAN, 0)
    assert "WOOW-X" in body
    assert markup.document_link_markup(ATTACHMENT) in body


def test_the_document_check_looks_for_the_control_before_falling_back():
    """#266 asks for the tile *or* the control that was looked for. Both are
    recorded: `#media-replace` is un-hidden for any `.o_image`, but the same
    function hides the whole toolbar for a media whose `data-mimetype` is not an
    image -- which every dialog-inserted document has. So the fallback is
    expected to be the one that works, and a record that did not say which
    control opened the dialog would not answer the question."""
    source = inspect.getsource(markup._document_mailing_after_seeding)
    assert "REPLACE_LEGACY" in source
    assert '"replace_control_present"' in source
    assert '"replace_control_visible"' in source
    assert '"dblclick"' in source
    assert source.index('"replace_control_present"') < source.index('"dblclick"')


def test_the_document_check_reads_the_two_mailing_fields_back_into_stored():
    """Nothing here is meant to be saved, and that sentence is not the guarantee.
    Clicking inside the designer's editable can leave the form dirty, and an Odoo
    form persists a dirty editor on `beforeunload` and on `visibilitychange`
    without the record being dirty (#263 is the same mechanism on the To-do
    form). The read-back is in `stored`, where `stored_verdict` names a prefix
    that reached the database."""
    source = inspect.getsource(markup._document_mailing_leaving)
    assert '"mailing.mailing.body_arch"' in source
    assert '"mailing.mailing.body_html"' in source
    assert "_discard_unsaved_form(" in source
    assert "DISCARD_BUTTON" in inspect.getsource(markup._discard_unsaved_form)
    assert "return {" in source and '"stored": stored' in source


def test_both_mailing_checks_leave_the_form_clean_behind_them():
    """`run_check` closes the session *after* the handler returns, and an Odoo
    form persists a dirty editor on `beforeunload`. Both mailing checks click
    inside the designer's editable, so both have to leave through the discard --
    the editable one too (#276), because `--mailing-id` is still a real campaign
    and the typing is deliberate there."""
    for leaving in (markup._document_mailing_leaving, markup._mailing_editable_leaving):
        assert "_discard_unsaved_form(" in inspect.getsource(leaving), leaving.__name__


# Every handler that types into a form and then writes a record back. The
# recovery paths matter more than the success path, not less: the typing is
# already done when a later step fails, so the form is certainly dirty.
RESTORING_HANDLERS = (markup.do_mailing_editable, markup.do_media_document_mailing,
                      markup.do_codeview)


@pytest.mark.parametrize("handler", RESTORING_HANDLERS, ids=lambda f: f.__name__)
def test_a_handler_that_restores_a_record_discards_before_it_does(handler):
    """A restore the session's own `beforeunload` then undoes is worse than no
    restore, because the record says `body_restored` / `help_restored` is true.

    `run_check` closes the session after the handler has returned -- outside
    every reading -- and an Odoo form persists a dirty editor on `beforeunload`
    and on an ungated `visibilitychange` (#263 is the same mechanism on the To-do
    form). So the discard belongs on **both** recovery paths of every handler
    that puts a record back, and the success path's own exit, and a review of
    #276 found all three handlers leaving one of them open.
    """
    source = inspect.getsource(handler)
    ordinary, interrupted = source.split("except BaseException:")
    # On the name the outer handler binds, not on `except Exception`: each of
    # these paths has a nested `except Exception` of its own guarding the restore.
    ordinary = ordinary.split("except Exception as error:")[-1]
    for where, body in (("except Exception", ordinary),
                        ("except BaseException", interrupted)):
        assert "_discard_unsaved_form(" in body, (
            "%s's %s path restores a record without leaving the form clean"
            % (handler.__name__, where))


def test_the_codeview_check_leaves_the_real_action_s_form_clean():
    """The one of the three that writes a record it can neither delete nor
    rebuild: `ir.actions.act_window.help` on a real action. The discard has to
    come after the read-back -- which is the reading -- and before the restore.

    The restore anchor is the **call with its arguments**, not `if cleanup:` as
    it was until #297 and not the bare helper name, which the comment above the
    call also carries: an `index()` whose target can resolve in prose stops being
    a guard the moment the call text moves or is renamed (#292's `is_visible()`
    pin, and #282 item 5's narrower version of it)."""
    source = inspect.getsource(markup._codeview_after_seeding)
    assert source.index('read_field(side, "ir.actions.act_window"') \
        < source.index("_discard_unsaved_form(side, extra)") \
        < source.index("_restore_borrowed_help(side, uid, before, extra)")


# --- #297: a borrowed record goes back whatever `--cleanup` says ---------------
#
# `--cleanup` deletes what a check **created**. Leaving a scratch row named after
# the run is a legible choice and #183's and #265's evidence make it on purpose.
# Handing back a record the driver merely borrowed is a different question, and
# three success paths used to answer it with the same flag -- so a run taken
# without it left a real `ir.actions.act_window.help` and, under `--mailing-id`,
# a real campaign's body holding this run's marker. #282's run paid for the first
# one on `odoo_parity`.


class HelpAction:
    """The `ir.actions.act_window` `codeview` borrows, behind the RPC seam.

    `pick_help_action` creates nothing -- it takes the lowest id -- so this fake
    starts with the record already there, which is the whole point of the ticket.
    """

    def __init__(self, help_value="", fail_write=False):
        self.records = {1: {"help": help_value}}
        self.fail_write = fail_write
        self.calls = []

    def rpc(self, model, method, args, kwargs=None):
        self.calls.append((model, method, args))
        assert model == "ir.actions.act_window", model
        if method == "search":
            return sorted(self.records)[:1]
        if method == "read":
            return [dict({"id": key},
                         **{field: self.records[key].get(field, False)
                            for field in args[1]})
                    for key in args[0]]
        if method == "write":
            if self.fail_write:
                raise RuntimeError("the action could not be written")
            for key in args[0]:
                self.records[key].update(args[1])
            return True
        raise AssertionError(method)


def test_the_borrowed_help_goes_back_with_no_flag_in_the_question():
    """The fix, driven: the restore takes a side, the record and the value read
    before the seed, and `--cleanup` is not one of its arguments."""
    side = HelpAction(help_value="<p>a real action's help</p>")
    before = markup.read_field(side, "ir.actions.act_window", 1, "help")
    markup.write_field(side, "ir.actions.act_window", 1, "help",
                       markup.signature_value(RUN))
    assert RUN in side.records[1]["help"], "the seed replaced a real value"

    extra = {}
    markup._restore_borrowed_help(side, 1, before, extra)
    assert side.records[1]["help"] == "<p>a real action's help</p>"
    assert extra == {"help_restored": True}
    assert "cleanup" not in inspect.signature(markup._restore_borrowed_help).parameters


def test_an_empty_help_is_put_back_as_false_and_not_as_a_marker():
    """The value #282's run found on `odoo_parity`: `help_before` was `""`, and
    `write_field(..., before or False)` is what makes an empty field empty again
    rather than leaving the seed in place."""
    side = HelpAction(help_value="")
    before = markup.read_field(side, "ir.actions.act_window", 1, "help")
    markup.write_field(side, "ir.actions.act_window", 1, "help",
                       markup.signature_value(RUN))
    markup._restore_borrowed_help(side, 1, before, {})
    assert side.records[1]["help"] is False


def test_a_restore_that_could_not_be_written_is_a_reading_and_not_a_raise():
    """`false` is the third of the three readings, and raising here would be
    worse than reporting it: the success path would fall into the handler's
    `except Exception` and a measured record would be rewritten as `NOT-RUN`."""
    side = HelpAction(fail_write=True)
    extra = {}
    markup._restore_borrowed_help(side, 1, "<p>was here</p>", extra)
    assert extra == {"help_restored": False}


def test_help_restored_is_written_in_exactly_one_place():
    """The three readings are three only while one function owns the key: `true`,
    `false`, and **absent** when the handler never got as far as seeding. A
    second writer -- an inline one under a flag, which is what this ticket
    removed -- is how the absent reading stopped meaning that."""
    assignment = 'extra["help_restored"] = '
    everywhere = [line for line in inspect.getsource(markup).splitlines()
                  if line.strip().startswith(assignment)]
    in_the_helper = [line for line
                     in inspect.getsource(markup._restore_borrowed_help).splitlines()
                     if line.strip().startswith(assignment)]
    assert len(everywhere) == len(in_the_helper) == 2, everywhere


def test_the_codeview_handler_no_longer_takes_the_flag_it_cannot_use():
    """It creates nothing, so there is nothing for `--cleanup` to delete -- and a
    parameter threaded through to no reader reads as a gate somebody forgot.
    `run_check` passes it to every handler, so the signature must still swallow
    it."""
    for handler in (markup.do_codeview, markup._codeview_after_seeding):
        assert "cleanup" not in inspect.signature(handler).parameters, handler.__name__
    # Exactly the call `run_check` makes, which `**_` has to keep accepting.
    inspect.signature(markup.do_codeview).bind(
        object(), RUN, task_id=None, mailing_id=None, cleanup=True)


# The three success paths that hand a borrowed record back, and the call each
# one makes. The restore sits at the function's own indentation: nested under
# `if cleanup:` it would be four spaces deeper, which is what this measures.
BORROWED_RESTORE_SITES = (
    (markup._codeview_after_seeding, "_restore_borrowed_help(side, uid, before, extra)"),
    (markup._mailing_editable_leaving, "_restore_borrowed_mailing_body(side, fixture, extra)"),
    (markup._document_mailing_leaving, "_restore_borrowed_mailing_body(side, fixture, extra)"),
)


@pytest.mark.parametrize("leaving,call", BORROWED_RESTORE_SITES,
                         ids=lambda value: getattr(value, "__name__", ""))
def test_no_success_path_puts_a_borrowed_restore_behind_cleanup(leaving, call):
    """The standing check that the gate cannot come back. Comment lines are
    dropped first, so the prose above each call can neither satisfy this nor
    break it."""
    lines = [line for line in inspect.getsource(leaving).splitlines()
             if not line.strip().startswith("#")]
    restore = next(index for index, line in enumerate(lines) if line.strip() == call)
    assert lines[restore].startswith("    " + call), \
        "the restore is nested inside something: %r" % lines[restore]
    assert all(index > restore for index, line in enumerate(lines)
               if line.strip() == "if cleanup:"), \
        "a `--cleanup` gate reaches the restore in %s" % leaving.__name__


def test_a_borrowed_mailing_is_restored_without_cleanup_and_still_not_deleted():
    """`media-document-mailing` borrows on its `found` branch, which is every run
    on a database that carries a draft -- `odoo_parity` does. The removal stays
    behind the flag, because the attachment is this run's own."""
    side = FakeSide(mailings={4: {"state": "draft", "subject": "Real campaign",
                                  "body_arch": BORROWED, "body_html": BORROWED}})
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["mailing_source"] == "found"
    assert side.mailings[4]["body_arch"] != BORROWED, "the seed overwrote the body"

    outcome = leave(side, fixture, cleanup=False)
    assert side.mailings[4]["body_arch"] == BORROWED
    assert side.mailings[4]["body_html"] == BORROWED
    assert outcome["extra"]["body_restored"] is True
    # What the flag still owns, and it was not asked for.
    assert "fixture_removed" not in outcome["extra"]
    assert fixture["attachment"]["id"] in side.attachments
    assert not side.did("mailing.mailing", "unlink")


def test_the_campaign_mailing_id_named_is_restored_without_cleanup():
    """The worst version of this defect in the driver, because this is the check
    that **saves**: without the restore a real campaign in `draft` -- a row that
    can still be sent -- kept this run's marker in `body_arch` and in the inlined
    `body_html` that leaves the installation with the mail."""
    side = FakeSide(mailings={9: {"state": "draft", "subject": "Real campaign",
                                  "body_arch": BORROWED, "body_html": BORROWED}})
    fixture = seed_editable_mailing(side, mailing_id=9)
    assert fixture["extra"]["mailing_source"] == "given"
    assert side.mailings[9]["body_arch"] != BORROWED, "the seed overwrote the body"

    outcome = leave_editable(side, fixture, cleanup=False)
    assert side.mailings[9]["body_arch"] == BORROWED
    assert side.mailings[9]["body_html"] == BORROWED
    assert outcome["extra"]["body_restored"] is True
    assert 9 in side.mailings and not side.did("mailing.mailing", "unlink")
    assert "fixture_removed" not in outcome["extra"]


def test_a_row_this_run_owns_is_not_restored_just_because_the_gate_went():
    """The reading the gate was never what protected: `body_restored` must stay
    absent for a scratch row, or it would say a real campaign was put back when
    none was. `_restore_borrowed_mailing_body`'s own first line is that test."""
    side = FakeSide()
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["mailing_source"] == "created"
    outcome = leave(side, fixture, cleanup=False)
    assert "body_restored" not in outcome["extra"]
    assert fixture["mailing_id"] in side.mailings, "no cleanup was asked for"


# --- `_discard_unsaved_form`'s three readings (#280) ---------------------------
#
# The function has no browser-free surface of its own beyond these: a page that
# says whether it is dirty, a button, and a click that either comes off or does
# not. The readings are what a reader of the record checks the restore against,
# so they are tested rather than asserted on the source.


class DiscardLocator:
    """One selector on `DiscardPage`, answering only what the seam asks it.

    The discard button answers *by selector*, because which of the two spellings
    the seam reaches for is the difference between clicking the real button and
    spending the bound on a hidden earlier one.
    """

    VISIBLE_DISCARD = markup.DISCARD_BUTTON + " >> visible=true"

    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def count(self):
        if self.page.unreadable:
            raise RuntimeError("Target page, context or browser has been closed")
        if self.selector == markup.UNSAVED:
            return 1 if self.page.dirty else 0
        return 1 if self.page.button else 0

    def click(self, **kwargs):
        self.page.clicks.append((self.selector, kwargs))
        if self.page.hidden_first_button and self.selector == markup.DISCARD_BUTTON:
            # Playwright's own shape for a click that waited out its bound on an
            # element that is in the DOM and not visible.
            raise RuntimeError("element is not visible")
        if self.page.click_error is not None:
            raise self.page.click_error

    def wait_for(self, **kwargs):
        self.page.waits.append((self.selector, kwargs))
        if self.selector == markup.UNSAVED and kwargs.get("state") == "hidden" \
                and self.page.still_dirty:
            raise RuntimeError("Timeout %sms exceeded" % kwargs.get("timeout"))


class DetachedFrame:
    """The held Ingress frame after the panel re-mounted.

    The raise comes from the locator's `count()` and **not** from `locator()`,
    which is Playwright's real shape: `Frame.locator` builds a selector object
    without touching the browser, so it raises nothing on a frame that has gone,
    and the detach surfaces at the first call that needs the frame to answer. A
    fake that raised from `locator()` would pass a seam that built its locator
    inside the `try` and read it outside.
    """

    def __init__(self):
        self.counts = 0

    def locator(self, selector):
        return self

    @property
    def first(self):
        return self

    def count(self):
        self.counts += 1
        raise RuntimeError("Frame was detached")


class DiscardPage:
    """A form page as `_discard_unsaved_form` reads it, and the side around it.

    `unreadable` is the frame that navigated away or the context that closed --
    the case where the seam cannot tell a dirty form from a clean one, and so
    must not claim either. `detached` is the sharper shape of the same case: the
    side is *holding* a frame that has gone, while the waiting resolve would
    answer with the replacement the panel has since mounted.
    """

    def __init__(self, *, dirty=True, button=True, click_error=None,
                 unreadable=False, still_dirty=False,
                 hidden_first_button=False, detached=None):
        self.dirty = dirty
        self.button = button
        self.click_error = click_error
        self.unreadable = unreadable
        # The form that never came clean: the click went in and the unsaved
        # indicator is still up when the wait runs out.
        self.still_dirty = still_dirty
        # A hidden earlier match for `DISCARD_BUTTON`, which `count()` passes and
        # a click can never reach.
        self.hidden_first_button = hidden_first_button
        self.detached = detached
        self.clicks = []
        self.waits = []
        self.settled = []
        # How many times the seam reached for each of the two resolves. On the
        # real `IngressSide`, `root` re-enters `_find_frame(wait_s=60)` whenever
        # the held frame reports detached, so a read of it is a chance to spend a
        # minute inside a seam that sits in front of the restore it runs ahead of;
        # `root_now` hands the held frame back and never enters that search
        # (#288). Both counted, because which one the seam reaches for is the
        # difference.
        self.root_reads = 0
        self.root_now_reads = 0

    @property
    def root(self):
        self.root_reads += 1
        return self

    @property
    def root_now(self):
        self.root_now_reads += 1
        return self.detached if self.detached is not None else self

    def locator(self, selector):
        return DiscardLocator(self, selector)

    def settle(self, ms=800):
        self.settled.append(ms)


def test_a_page_with_nothing_to_discard_adds_no_key():
    """The absence of the key is the "already clean" reading, which is why a
    failed discard may not share it."""
    extra = {}
    side = DiscardPage(dirty=False)
    markup._discard_unsaved_form(side, extra)
    assert extra == {}
    assert side.clicks == []


def test_a_discard_that_came_off_reads_true():
    extra = {}
    side = DiscardPage()
    markup._discard_unsaved_form(side, extra)
    assert extra == {"discarded": True}
    assert len(side.clicks) == 1


def test_a_discard_whose_click_failed_reads_false():
    """A modal over the button, a page that stopped responding: `UNSAVED`
    matched, so the form is dirty, and the restore that follows is now
    checkable against a reading that says the discard did not come off."""
    extra = {}
    markup._discard_unsaved_form(
        DiscardPage(click_error=RuntimeError("Timeout 2000ms exceeded")), extra)
    assert extra == {"discarded": False}


def test_a_dirty_form_with_no_discard_button_reads_false():
    """Same collision as the failed click: the form is dirty and nothing
    discarded it, so it may not read like a page that was already clean."""
    extra = {}
    markup._discard_unsaved_form(DiscardPage(button=False), extra)
    assert extra == {"discarded": False}


def test_the_seam_does_not_settle_on_a_caller_s_behalf():
    """The seam used to `side.settle(2000)` after confirming, for the restore's
    RPC "which wants the page quiet" (#288). No caller wants it: every step any
    of them takes after this seam -- `read_field`/`write_field`, the borrowed-body
    restore, the fixture removal, the document check's record read-back -- goes
    through `Side.rpc`, which posts through the request context and touches
    neither a page nor a frame. `Side.settle` runs an 8 s `networkidle` that
    Odoo's open bus makes time out and *then* sleeps, so that was about 10 s
    between an operator's Ctrl+C and the only restore that record gets, bought
    for nobody."""
    extra = {}
    side = DiscardPage()
    markup._discard_unsaved_form(side, extra)
    assert side.settled == []
    # And the reading is unchanged by its going: confirmed, then recorded, with
    # nothing after the record that can fail.
    assert extra == {"discarded": True}
    assert [wait[1].get("state") for wait in side.waits] == ["hidden"]
    # Nor on any other reading: no path through the seam spends a wait made for
    # somebody else.
    for page in (DiscardPage(dirty=False), DiscardPage(button=False),
                 DiscardPage(still_dirty=True), DiscardPage(unreadable=True),
                 DiscardPage(click_error=RuntimeError("Timeout 2000ms exceeded"))):
        markup._discard_unsaved_form(page, {})
        assert page.settled == [], page.settled


def test_a_page_that_cannot_be_read_adds_no_key():
    """Nothing was attempted and nothing is known, which is not the same
    reading as a discard that failed."""
    extra = {}
    markup._discard_unsaved_form(DiscardPage(unreadable=True), extra)
    assert extra == {}


def test_a_form_that_never_came_clean_reads_false():
    """`true` has to mean the form came clean, not that the click did not raise.
    A dialog raised over the discard, or an invalid record the form refuses to
    leave, keeps the unsaved indicator up -- and `run_check`'s `side.close()`
    then has a dirty form to save, which is the whole reason this seam exists."""
    extra = {}
    side = DiscardPage(still_dirty=True)
    markup._discard_unsaved_form(side, extra)
    assert extra == {"discarded": False}
    assert [wait[1].get("state") for wait in side.waits] == ["hidden"]


def test_a_hidden_earlier_discard_button_does_not_take_the_click():
    """`.first` takes the first DOM match whatever its state, so one hidden
    earlier button -- a dialog's, a sub-form's -- would spend the bound on an
    element that can never be clicked while the real button is never reached.
    `>> visible=true` is this repository's existing idiom for the same button
    (`e2e_collab_peer_snapshot_live.discard_form`)."""
    extra = {}
    side = DiscardPage(hidden_first_button=True)
    markup._discard_unsaved_form(side, extra)
    assert extra == {"discarded": True}
    assert [click[0] for click in side.clicks] == [DiscardLocator.VISIBLE_DISCARD]


def test_the_discard_click_is_bounded_by_a_short_timeout():
    """No `set_default_timeout` is applied anywhere in this driver, so a click
    with no `timeout=` takes Playwright's 30 s default. `do_codeview`'s
    `except BaseException` runs this discard *before* it puts a real
    `ir.actions.act_window.help` back, so those 30 s sit between an operator's
    Ctrl+C and the only restore that record will get -- and a second Ctrl+C
    inside the window raises through to leave the marker text on the action.
    """
    side = DiscardPage()
    markup._discard_unsaved_form(side, {})
    assert side.clicks and "timeout" in side.clicks[0][1], \
        "the discard click takes Playwright's 30 s default"
    timeout = side.clicks[0][1]["timeout"]
    assert 0 < timeout <= 5_000, timeout
    assert timeout < markup.TIMEOUT
    # And so is the wait for the form to come clean, the other half of the window.
    assert side.waits and side.waits[0][1].get("timeout"), side.waits
    assert 0 < side.waits[0][1]["timeout"] < markup.TIMEOUT


def test_an_interrupt_inside_the_discard_leaves_the_failed_reading_and_propagates():
    """The second Ctrl+C: `KeyboardInterrupt` is not an `Exception`, so it still
    continues out of the handler -- and `extra` keeps the reading that the
    discard did not come off rather than nothing at all. `run_check` catches
    `Exception` only, so that path writes no evidence line for the surface
    whatever is in `extra`; the reading is for every other path that writes one."""
    extra = {}
    with pytest.raises(KeyboardInterrupt):
        markup._discard_unsaved_form(DiscardPage(click_error=KeyboardInterrupt()), extra)
    assert extra == {"discarded": False}


def test_the_seam_resolves_the_no_wait_root_once_and_never_the_waiting_one():
    """Neither resolve is a field: both are properties, and the waiting one
    re-enters `_find_frame(wait_s=60)` whenever the Ingress iframe reports
    detached. A read of it is a chance to spend a minute inside a seam
    `do_codeview`'s interrupt path runs *ahead of* the only restore a real
    `ir.actions.act_window.help` will get, so the seam takes `side.root_now`
    (#288) -- and takes it once, working through the frame it got (#280)."""
    for page in (DiscardPage(), DiscardPage(still_dirty=True), DiscardPage(button=False),
                 DiscardPage(dirty=False)):
        markup._discard_unsaved_form(page, {})
        assert page.root_now_reads == 1, page.root_now_reads
        assert page.root_reads == 0, page.root_reads


def test_a_detached_held_frame_is_unreadable_and_not_an_already_clean_form():
    """The third door to #280's misreading, shut at the entry read (#288).

    The side is holding a frame the re-mounted panel detached, and the waiting
    resolve would answer with the **replacement** -- whose freshly loaded
    document has no unsaved indicator, so a zero `count()` there reads as "a page
    with nothing to discard" and adds no key, while the dirty form sat in the
    frame that went and its detach is exactly when `beforeunload` fires. Reaching
    for the held frame instead, the read raises and the same absent key means
    what it says: nothing was attempted, nothing is known."""
    detached = DetachedFrame()
    # `dirty=False` is the replacement frame this fake's *waiting* resolve would
    # hand back: clean, and so an answer about the wrong document.
    side = DiscardPage(dirty=False, detached=detached)
    extra = {}
    markup._discard_unsaved_form(side, extra)
    assert extra == {}
    # Asked of the held frame, which raised -- not of the clean replacement.
    assert detached.counts == 1
    assert side.root_reads == 0
    assert side.clicks == [] and side.waits == []


def test_the_clean_bound_covers_the_designer_s_commit_pipeline():
    """A discard on the mail designer pays the whole inlining pipeline before
    the indicator can clear, so this bound cannot be the small one.

    `Record.discard` does `await this.model._askChanges()` before `_discard()`
    (`web/static/src/model/relational_model/record.js:183-188`); `_discard()`
    itself (`:565`) is purely local -- no RPC, so there is no reload to wait on.
    `_askChanges` raises `NEED_LOCAL_CHANGES`, the html field answers it with
    `commitChanges()` (`html_editor/static/src/fields/html_field.js:78`), and
    the designer's override clones the editable into an `srcdoc` iframe, awaits
    that iframe's `load`, and runs `toInline`
    (`mass_mailing/static/src/js/mass_mailing_html_field.js:147-186`).

    This driver's own budget for that same pipeline on the **save** path is
    `side.settle(6000)` -- an 8 s `networkidle` Odoo's open bus normally runs
    out, then a 6 s sleep -- and `extra["save_incomplete"]` exists because that
    is sometimes still not enough. So the discard's confirmation may not be
    bounded tighter than the save's, or a discard that came off records
    `discarded: false`: the misreading #280 exists to remove, from the other
    side."""
    assert markup.DISCARD_CLEAN_TIMEOUT >= 14_000, markup.DISCARD_CLEAN_TIMEOUT
    # Still a bound, and still well under the explicit one the driver uses for
    # waits that are allowed to take as long as a page load.
    assert markup.DISCARD_CLEAN_TIMEOUT < markup.TIMEOUT
    # The click is the half that genuinely needs nothing but an actionable
    # button, and it stays small -- the two are not one number by accident.
    assert markup.DISCARD_TIMEOUT < markup.DISCARD_CLEAN_TIMEOUT


def test_a_body_html_the_save_never_inlined_is_not_a_pass():
    """Building the row makes `False` the baseline for `body_html`, and an empty
    field is `CLEAN` -- correctly, since there is no prefix in it. So a save that
    stored `body_arch` and never inlined `body_html` would score `PARITY` for the
    one field this check exists to measure: rule 8's, the one that leaves the
    installation with the mail. The marker the designer **typed** is the
    discriminator, because of which *field* the seed writes: `body_arch`, where
    the marker also sits, leaving `body_html` as the created row left it."""
    assert markup.stored_verdict(False) == (markup.CLEAN, 0)
    assert markup.stored_verdict("") == (markup.CLEAN, 0)
    assert markup.body_html_inlined(RUN, {"body_html": False},
                                    {"body_html": markup.marker_for(RUN)})
    assert not markup.body_html_inlined(RUN, {"body_html": False},
                                        {"body_html": markup.MAILING_BODY_VALUE})
    source = inspect.getsource(markup._mailing_after_seeding)
    assert '"body_html_inlined"' in source
    assert 'body_html_inlined(run_id, body_html_baseline(fixture), after)' in source


def test_a_marker_already_in_body_html_is_not_this_save_inlining_it():
    """#279. `--run-id` is one value for the whole invocation and `--surface both`
    drives both surfaces against one database, so without `--cleanup` the second
    surface's `scratch_mailing_id` reclaims the first's scratch row -- by design,
    since the subject is this run's. That row's `body_html` already holds
    `marker_for(run_id)` from the first surface's save, so a marker merely
    *present* after the second save says nothing about whether `commitChanges`
    ran. Only a marker that is **newly** present does, and the same reading
    closes a re-run of one surface under one run id."""
    typed = markup.marker_for(RUN)
    reclaimed = {"body_html": "<div>%s</div>" % typed}
    assert not markup.body_html_inlined(RUN, reclaimed, reclaimed)
    # A body that changed around an already-present marker is no evidence either:
    # the designer types the marker on every save, so a marker already in the
    # field cannot say which save put it there. `False` both ways is the direction
    # to fail in -- "inlined" is the claim that needs evidence.
    assert not markup.body_html_inlined(
        RUN, reclaimed, {"body_html": "<div><p>%s</p></div>" % typed})
    # An earlier run's marker is a different string, so it does not mask this one.
    assert markup.body_html_inlined(RUN, {"body_html": markup.marker_for("WOOW-OLD")},
                                    {"body_html": typed})


def test_the_record_says_whether_the_marker_was_there_before_the_seed():
    """Two `false` readings of `body_html_inlined` mean different things -- "the
    save never inlined" and "the marker was already in the field, so this row
    cannot say" -- and on a reclaimed row only the second is available. A record
    carrying this run's marker in the stored `body_html` beside
    `body_html_inlined: false` is unreadable without it. It is read where the
    `before` read happens, so it is in the record on the give-up paths too."""
    assert markup.body_html_marked(RUN, {"body_html": markup.marker_for(RUN)})
    assert not markup.body_html_marked(RUN, {"body_html": markup.MAILING_BODY_VALUE})
    assert not markup.body_html_marked(RUN, {"body_html": False})
    source = inspect.getsource(markup.seed_editable_mailing_fixture)
    assert 'extra["body_html_marker_before"] = body_html_marked(run_id, before)' in source
    assert source.index('fixture["before"] = before') \
        < source.index('extra["body_html_marker_before"]') \
        < source.index('side.rpc("mailing.mailing", "write", [[mailing_id], seed])')


def test_the_newly_present_reading_survives_an_unset_body_html():
    """`create_fixture_mailing` leaves `body_html` as `False`, and `read` returns
    that `False` rather than a string -- on both sides of the comparison, since a
    save that never inlined leaves the field untouched."""
    assert not markup.body_html_inlined(RUN, {"body_html": False}, {"body_html": False})
    assert not markup.body_html_inlined(RUN, {}, {})
    assert markup.body_html_inlined(RUN, {}, {"body_html": markup.marker_for(RUN)})


# Anything that undoes part of a fixture. A handler's error path has to name at
# least one of these; which one depends on what that check made.
CLEANUP_NAMES = (
    "remove_media_task", "_remove_media_todo_quietly", "_leave_media_todo",
    "remove_website_fixture_page", "_leave_website_media",
    "_remove_fixture_attachment", "_restore_mailing_body",
    # #274: the document mailing check now removes a mailing it made, and
    # restores one it borrowed -- two outcomes, so two names. #276 gives the
    # editable check the same pair.
    "_remove_mailing_fixture", "_restore_borrowed_mailing_body",
)

SEEDING_FLOWS = {
    "media-image-todo": (markup.do_media_image_todo,
                         markup._media_image_todo_after_seeding,
                         markup._leave_media_todo),
    "media-document-todo": (markup.do_media_document_todo,
                            markup._media_document_todo_after_seeding,
                            markup._leave_media_todo),
    "media-image-website": (markup.do_media_image_website,
                            markup._website_after_seeding,
                            markup._leave_website_media),
    "media-document-mailing": (markup.do_media_document_mailing,
                               markup._document_mailing_after_seeding,
                               markup._document_mailing_leaving),
    # #276: the one writing check outside the media family that builds a record
    # before its first navigation, and so has the same trap.
    "mailing-editable": (markup.do_mailing_editable,
                         markup._mailing_after_seeding,
                         markup._mailing_editable_leaving),
}


@pytest.mark.parametrize("check", sorted(SEEDING_FLOWS))
def test_a_fixture_building_check_cannot_leave_its_fixture_behind(check):
    """Every exit from a seeding check goes through its one leaving function.

    This is the trap and not a tidiness rule. All five create their fixture
    *before* the first navigation, and `run_check` **discards a handler's return
    value when it raises** -- so a step failing between the seed and the verdict
    leaves a public `ir.attachment`, and a scratch to-do, a `website.page` or a
    `mailing.mailing` beside it, on the host with nothing in the evidence naming
    them. Two of them were written exactly that way and a review caught it.
    """
    handler, browser_half, leaving = SEEDING_FLOWS[check]

    # The browser half runs entirely after the seed, so every one of its exits
    # -- and three of the four are give-up paths -- goes through one door.
    returns = [line for line in inspect.getsource(browser_half).splitlines()
               if line.strip().startswith("return ")]
    assert returns, browser_half.__name__
    assert all(leaving.__name__ + "(" in line for line in returns), (
        "%s has a return that does not go through %s"
        % (browser_half.__name__, leaving.__name__))

    # The handler holds the seed and the browser half inside **two** guards, so
    # a `KeyboardInterrupt` or a `SystemExit` removes the fixture too and not
    # only an ordinary failure.
    source = inspect.getsource(handler)
    assert "except Exception" in source and "except BaseException:" in source, handler.__name__
    ordinary, interrupted = source.split("except BaseException:")
    ordinary = ordinary.split("except Exception")[-1]
    for where, body in (("except Exception", ordinary), ("except BaseException", interrupted)):
        assert any(name in body for name in CLEANUP_NAMES), (
            "%s's %s path removes nothing it created" % (handler.__name__, where))


@pytest.mark.parametrize("seeder", [markup.seed_media_task, markup.seed_website_fixture_page,
                                   markup.seed_document_mailing_fixture])
def test_a_seeder_that_raises_half_way_removes_what_it_already_made(seeder):
    """All three raise *after* a `create`: `seed_media_task` when the image
    attachment has no `image_src`, `seed_website_fixture_page` when
    `website.new_page` returns no url, `seed_document_mailing_fixture` when the
    attachment or the body write fails on a mailing it has already made (#274).
    The row already exists at that point."""
    source = inspect.getsource(seeder)
    assert "except BaseException:" in source
    assert source.index("create_fixture_attachment(") < source.index("except BaseException:")
    assert "raise" in source.split("except BaseException:")[1]


def test_every_exit_from_the_document_check_cleans_up_and_reads_back():
    """One exit point, because a check that gave up early must still discard,
    still read the record back and still remove its fixture -- and there are four
    places it can give up."""
    source = inspect.getsource(markup._document_mailing_after_seeding)
    returns = [line for line in source.splitlines() if line.strip().startswith("return ")]
    assert returns
    assert all("_document_mailing_leaving(" in line for line in returns)


@pytest.mark.parametrize("check", sorted(MEDIA_FLOWS))
def test_every_media_check_declares_itself_as_a_write(check):
    """All four build what they measure (#266), and ADR 0012 wants a check to
    say so: `read_only_first` orders on this flag, so one left marked read-only
    would run before the cheap ones and would misdescribe itself in the
    register."""
    assert markup.CHECKS[check]["writes"] is True


def test_the_todo_fixtures_are_scratch_records_and_not_the_onboarding_one():
    """#243's rule, and the reason the iframe check has the same one: #235's
    checks read the onboarding to-do's stored `src`, so a write there would be
    read as their result."""
    source = inspect.getsource(markup.seed_media_task)
    assert "scratch_task_name(run_id)" in source
    assert "onboarding_todo_id" not in source
    assert '"element_survived"' in source


def test_the_todo_fixtures_read_the_description_back():
    """`project.task.description` is `sanitize_tags=True`, and this driver has
    already been caught by that field once -- #237's check 2 seeded a full-HTML
    value into it and got back the bare `<img>`. The anchor's attributes are all
    whitelisted, so it is expected to survive; the read-back is what replaces
    "expected to"."""
    source = inspect.getsource(markup.seed_media_task)
    assert "read_field(side, \"project.task\"" in source
    assert '"element_survived": wanted in stored' in source


def test_the_image_todo_fixture_carries_no_data_original_src():
    """Rule 2's branch `return`s before the `src` comparison, so an image
    carrying that attribute would measure rule 2 on the screen whose whole point
    is rule 1 -- and the attribute would be root-relative here anyway, because a
    field value arrives over `call_kw` with its quotes escaped and the generic
    HTML location's bare `src="/` cannot claim a position inside `src=\\"/`.
    Rule 2 has a screen of its own for exactly that reason."""
    source = inspect.getsource(markup.seed_media_task)
    assert 'data-original-src="' not in source
    assert "FIXTURE_IMAGE_ALT" in source
    # And the one screen that does carry it is the one that needs it.
    assert 'data-original-src="' in markup.WEBSITE_FIXTURE_SECTION


def test_the_module_says_what_the_two_media_fixtures_create():
    """The docstring's `Writing:` paragraph is where a reader looks before
    running this against the host, so the two new fixtures belong in it."""
    said = " ".join(markup.__doc__.split())
    assert "website.page" in said
    assert "ir.attachment" in said
    assert "--cleanup" in said
    assert "media-document-mailing" in said


def test_the_image_fixture_is_a_real_png():
    """The dialog's domain is `['mimetype', 'in', IMAGE_MIMETYPES]` and
    `image_src` is only computed for a supported image mimetype, so a fixture
    that was not really a PNG would be listed by nothing and compared to
    nothing."""
    raw = base64.b64decode(markup.FIXTURE_PNG_BASE64)
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in raw
    assert raw.endswith(b"IEND\xaeB\x60\x82")


def test_the_attachment_fixture_is_public_and_newest_rather_than_searched_for():
    """Two selector properties, both relied on and neither obvious.

    `public=True` is what lists it whatever record the dialog was opened from --
    the website editor's dialog is opened from an `ir.ui.view` and would not list
    the record-scoped attachment #243 used. And `order: 'id desc'` with a limit
    of 30 is why the newest attachment is the first tile: the preselection runs
    inside the first page's own loop, so a tile on page two would never be
    compared and the check would have to type a search."""
    source = inspect.getsource(markup.create_fixture_attachment)
    assert '"public": True' in source
    assert "id desc" in source
    assert '"image_src"' in source and '"checksum"' in source


def test_the_fixture_removal_says_what_went_rather_than_swallowing_it():
    """`website.page.unlink` may take the view with it, so unlinking the view
    afterwards raises on a record that is correctly gone. A silent `except` would
    read as "removed" for a fixture still on the host."""
    source = inspect.getsource(markup.remove_website_fixture_page)
    assert source.count("except Exception") == 2, (
        "the page/view unlink and the attachment unlink are guarded separately, "
        "so one failing does not hide the other's outcome")
    assert "removed[label] = False" in source
    assert 'removed["attachment"] = False' in source
    assert "return removed" in source


def test_both_media_dialogs_are_probed_for_the_rule():
    """Rule 2 is the single pattern the two dialogs spell identically, and the
    two media image checks open *different* ones -- the backend form opens
    `html_editor`'s, the website editor opens the legacy `web_editor` one. A
    probe that only read the current editor's method would report a rule that
    reached a dialog the check never drove. The #243 key names are kept so the
    two runs stay comparable."""
    assert "@html_editor/main/media/media_dialog/image_selector" in markup._RULE_PROBE
    assert "@web_editor/components/media_dialog/image_selector" in markup._RULE_PROBE
    assert '"rule_in_served_method"' in markup._RULE_PROBE
    assert '"legacy_"' in markup._RULE_PROBE


def test_the_document_operand_probe_takes_the_dialog_as_a_parameter():
    """Odoo ships the document comparison twice and the Static tier records both
    as measured-and-left-alone. The legacy reading is the one that belongs beside
    a tile the legacy dialog actually showed."""
    assert markup.CURRENT_DOCUMENT_SELECTOR.startswith("@html_editor/")
    assert markup.LEGACY_DOCUMENT_SELECTOR.startswith("@web_editor/")
    assert "spec.module" in markup._DOCUMENT_OPERAND_PROBE
    assert "spec.dialog" in markup._DOCUMENT_OPERAND_PROBE
    source = inspect.getsource(markup._document_mailing_after_seeding)
    assert "LEGACY_DOCUMENT_SELECTOR" in source


# --- #274: the last media check that did not build what it measures -----------
#
# `media-document-mailing` built its attachment and only *looked up* its
# mailing, so on a database with no draft mailing -- a fresh install, a
# catch-up database, the local add-on's own -- it returned `NOT-RUN` with
# nothing measured. #271's Live run hit exactly that on `catchup164b`, where
# `mass_mailing` had been installed minutes earlier, and had to seed a mailing
# by hand over `odoo shell`: the one thing that stopped that run being
# unattended.
#
# What this section pins is #266's lesson in both directions. A record the run
# **made** is deleted; a record it **borrowed** is restored and never deleted.
# A check that deletes what it did not create is how the next run ends up with
# nothing to measure, and a check that restores what it is about to delete
# reports a borrowed body that nobody borrowed.


class FakeRoot:
    """No unsaved-changes bar, and nothing to discard.

    The browser half has no static tests at all (the module says so); these
    tests are about the writes, and `_document_mailing_leaving` asks the page
    one question before it makes any.
    """

    def locator(self, selector):
        return self

    def count(self):
        return 0


class FakeEnv:
    """Only what the seam reads off it: the login `current_user_id` looks up."""

    login = "parity@woow.invalid"


class FakeSide:
    """The driver's RPC seam, with a toy database behind it.

    The seeding and cleanup split is a *sequence of writes*, and an assertion on
    the source would pin its spelling rather than its behaviour -- "`unlink` was
    never reached for a mailing this run did not create" is the property. Every
    step the seeder and the leaving function take goes through `side.rpc`, so
    this is their whole surface.
    """

    def __init__(self, mailings=None, create_state="draft", fail_attachment=False,
                 fail_write=False, fail_unlink=False, user_email="parity@woow.invalid"):
        self.mailings = {key: dict(value) for key, value in (mailings or {}).items()}
        self.attachments = {}
        self.models = {"mailing.list": 11}
        self.create_state = create_state
        self.fail_attachment = fail_attachment
        self.fail_write = fail_write
        self.fail_unlink = fail_unlink
        self.user_email = user_email
        self.calls = []
        self.root = FakeRoot()
        self.env = FakeEnv()
        self._next_id = 100

    @property
    def root_now(self):
        """The no-wait resolve, which on a page-rooted side is `root` itself.

        Present because `_discard_unsaved_form` reaches for it (#288) and these
        tests run the leaving functions that call it: without it the seam would
        swallow an `AttributeError` and read "nothing to discard" for the wrong
        reason, which is the fake diverging from `Side` rather than modelling it.
        """
        return self.root

    def rpc(self, model, method, args, kwargs=None):
        kwargs = kwargs or {}
        self.calls.append((model, method, args, kwargs))
        return getattr(self, "_%s_%s" % (model.replace(".", "_"), method))(args, kwargs)

    def did(self, model, method):
        return [call for call in self.calls if call[0] == model and call[1] == method]

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    def _mailing_mailing_search(self, args, kwargs):
        """The two searches this driver makes: by state, and by state and subject.

        The subject clause is spelled `=like` with a trailing `%` (#276), and
        that spelling is asserted rather than worked around: a `like` or an
        `ilike` would match a real campaign whose subject merely *contains* the
        scratch words, which is the one thing a reclaim must not do.
        """
        clauses = {clause[0]: clause for clause in args[0]}
        states = clauses["state"][2]
        subject = clauses.get("subject")
        if subject is not None:
            assert subject[1] == "=like" and subject[2].endswith("%"), subject
        found = []
        for key, record in sorted(self.mailings.items()):
            if record.get("state") not in states:
                continue
            if subject is not None and not (
                    record.get("subject") or "").startswith(subject[2][:-1]):
                continue
            found.append(key)
        return found[:kwargs.get("limit", len(found))]

    def _mailing_mailing_create(self, args, kwargs):
        record = {"body_arch": False, "body_html": False}
        record.update(args[0])
        # What the server made, which is not necessarily what was asked for.
        record["state"] = self.create_state
        key = self._new_id()
        self.mailings[key] = record
        return key

    def _mailing_mailing_read(self, args, kwargs):
        return [dict({"id": key}, **{field: self.mailings[key].get(field, False)
                                     for field in args[1]}) for key in args[0]]

    def _mailing_mailing_write(self, args, kwargs):
        if self.fail_write:
            raise RuntimeError("the body could not be written")
        for key in args[0]:
            self.mailings[key].update(args[1])
        return True

    def _mailing_mailing_unlink(self, args, kwargs):
        if self.fail_unlink:
            raise RuntimeError("the mailing could not be unlinked")
        for key in args[0]:
            del self.mailings[key]
        return True

    def _res_users_search(self, args, kwargs):
        wanted = next(clause[2] for clause in args[0] if clause[0] == "login")
        return [2] if wanted == self.env.login else []

    def _res_users_read(self, args, kwargs):
        return [{"id": key, "email_formatted": self.user_email} for key in args[0]]

    def _ir_model_search(self, args, kwargs):
        wanted = next(clause[2] for clause in args[0] if clause[0] == "model")
        found = self.models.get(wanted)
        return [found] if found else []

    def _ir_attachment_create(self, args, kwargs):
        if self.fail_attachment:
            raise RuntimeError("the attachment could not be created")
        key = self._new_id()
        self.attachments[key] = dict(args[0])
        return key

    def _ir_attachment_read(self, args, kwargs):
        return [{"id": key, "checksum": "abc123",
                 "mimetype": self.attachments[key].get("mimetype"),
                 "image_src": False} for key in args[0]]

    def _ir_attachment_search(self, args, kwargs):
        """The id filter #277's reclaim makes, so a dangling href is dropped
        rather than raising the `MissingError` a real `unlink` would."""
        wanted = next(clause[2] for clause in args[0] if clause[0] == "id")
        return [key for key in sorted(self.attachments) if key in wanted]

    def _ir_attachment_unlink(self, args, kwargs):
        if self.fail_unlink:
            raise RuntimeError("the attachment could not be unlinked")
        for key in args[0]:
            del self.attachments[key]
        return True


RUN = "WOOW-MARKUP-20261003T123902Z"
BORROWED = "<div class=\"o_layout\"><p>a real campaign</p></div>"


def seed_document_mailing(side, mailing_id=None):
    return markup.seed_document_mailing_fixture(side, RUN, mailing_id)


def leave(side, fixture, **kwargs):
    return markup._document_mailing_leaving(
        side, fixture, fixture["extra"], "/screen",
        pictures=None, notes="", **kwargs)


def test_a_database_with_no_draft_mailing_gets_one_this_run_made():
    """#274's reading, and the check's own premise: the search that did not find
    a mailing is satisfied by what the seed leaves behind."""
    side = FakeSide()
    assert markup.editable_mailing_id(side) is None
    fixture = seed_document_mailing(side)
    assert fixture["scratch_mailing"] is not None
    mailing_id = fixture["mailing_id"]
    assert markup.editable_mailing_id(side) == mailing_id
    # Named after the run, the way `live-tier.md` asks of every writing step.
    assert side.mailings[mailing_id]["subject"] == markup.scratch_task_name(RUN)
    assert RUN in side.mailings[mailing_id]["subject"]


def test_the_mailing_this_run_made_is_recorded_beside_the_attachment():
    """`extra["fixture"]` is what a later reader consults to know what is on the
    host, and #271's hand-seeded mailing was in no record at all."""
    side = FakeSide()
    fixture = seed_document_mailing(side)
    recorded = fixture["extra"]["fixture"]
    assert recorded["mailing_id"] == fixture["mailing_id"]
    assert recorded["mailing_subject"] == markup.scratch_task_name(RUN)
    assert recorded["mailing_state"] in markup.EDITABLE_MAILING_STATES
    assert recorded["attachment_id"] == fixture["attachment"]["id"]
    assert fixture["extra"]["mailing_source"] == "created"


def test_a_mailing_this_run_made_is_deleted_and_not_restored():
    side = FakeSide()
    fixture = seed_document_mailing(side)
    outcome = leave(side, fixture, cleanup=True)
    assert outcome["extra"]["fixture_removed"] == {"attachment": True, "mailing": True}
    assert not side.mailings and not side.attachments
    # Restoring a row that is being deleted would report a borrowed body nobody
    # borrowed, which is the reading `body_restored` exists to give.
    assert "body_restored" not in outcome["extra"]


def test_a_borrowed_mailing_is_restored_and_never_deleted():
    """#266's own lesson: a check that deletes what it did not create is how the
    next run ends up with nothing to measure."""
    side = FakeSide(mailings={4: {"state": "draft", "subject": "Real campaign",
                                  "body_arch": BORROWED, "body_html": BORROWED}})
    fixture = seed_document_mailing(side)
    assert fixture["scratch_mailing"] is None
    assert fixture["mailing_id"] == 4
    assert fixture["extra"]["mailing_source"] == "found"
    # The fixture block is what this run made, and it made no mailing here.
    assert "mailing_id" not in fixture["extra"]["fixture"]
    assert side.mailings[4]["body_arch"] != BORROWED, "the seed overwrote the body"

    outcome = leave(side, fixture, cleanup=True)
    assert side.mailings[4]["body_arch"] == BORROWED
    assert side.mailings[4]["body_html"] == BORROWED
    assert outcome["extra"]["body_restored"] is True
    assert outcome["extra"]["fixture_removed"] == {"attachment": True}
    assert not side.did("mailing.mailing", "unlink")


def test_mailing_id_still_means_reuse_this_one_and_nothing_else():
    """`--mailing-id`'s meaning is unchanged by #274: do not look, do not
    create, do not delete -- and do not second-guess the state the operator
    named, which is why this one is `done`."""
    side = FakeSide(mailings={9: {"state": "done", "subject": "Sent",
                                  "body_arch": BORROWED, "body_html": BORROWED}})
    fixture = seed_document_mailing(side, mailing_id=9)
    assert fixture["mailing_id"] == 9 and fixture["scratch_mailing"] is None
    assert fixture["extra"]["mailing_source"] == "given"
    assert not side.did("mailing.mailing", "create")
    assert not side.did("mailing.mailing", "search")

    outcome = leave(side, fixture, cleanup=True)
    assert 9 in side.mailings
    assert side.mailings[9]["body_arch"] == BORROWED
    assert outcome["extra"]["fixture_removed"] == {"attachment": True}


def test_a_mailing_that_came_back_uneditable_is_removed_rather_than_measured():
    """The row the seed makes has to satisfy the predicate the search applies:
    the designer's body field is `readonly="state in ('sending','done')"`, so a
    check driven against one of those would measure a readonly screen and read
    like a fixture that did not survive its field."""
    side = FakeSide(create_state="sending")
    with pytest.raises(RuntimeError, match="state"):
        seed_document_mailing(side)
    assert not side.mailings, "the row it made is still on the host"
    assert not side.attachments


def test_a_seed_that_fails_after_making_the_mailing_removes_it():
    """`run_check` discards a handler's return value when it raises, so a row
    left behind here would be on the host with nothing in the evidence naming
    it -- the trap #266's review caught twice."""
    side = FakeSide(fail_attachment=True)
    with pytest.raises(RuntimeError):
        seed_document_mailing(side)
    assert not side.mailings


def test_the_states_the_seed_must_satisfy_are_the_search_s_own():
    """One constant, so the row the seed makes cannot drift away from the row
    the lookup would have accepted."""
    assert markup.EDITABLE_MAILING_STATES == ("draft", "in_queue")
    assert "EDITABLE_MAILING_STATES" in inspect.getsource(markup.editable_mailing_id)
    assert "EDITABLE_MAILING_STATES" in inspect.getsource(markup.create_fixture_mailing)
    # #276's scratch search answers the same predicate: a reclaimed row the
    # designer renders readonly reads exactly like a fixture that did not
    # survive its field.
    assert "EDITABLE_MAILING_STATES" in inspect.getsource(markup.scratch_mailing_id)


def test_the_seeded_body_is_what_keeps_the_theme_chooser_off_the_screen():
    """The one thing that could stand between a brand-new mailing and the
    editable, and the reason it does not. The chooser is appended only when
    `value === "" || value === blankEditable`
    (`mass_mailing_html_field.js:520-534`), and the value it reads is the
    `body_arch` the seeder has already written -- so a mailing this run created
    reaches the same screen as one it borrowed. That holds only while the seeded
    body is a non-empty `.o_layout`, which is this half of the premise."""
    body = markup.mailing_document_body_value(RUN, ATTACHMENT)
    assert body.startswith('<div class="o_layout">')
    assert markup.document_link_markup(ATTACHMENT) in body


@pytest.mark.parametrize("check", sorted(MEDIA_FLOWS))
def test_no_media_check_gives_up_because_the_database_had_no_record(check):
    """#266 moved three of the four off records they did not create, #274 the
    fourth. All four now build their screen, so none of them can report "there
    was nothing here to measure" on a database that is merely fresh."""
    source = "".join(inspect.getsource(flow) for flow in MEDIA_FLOWS[check])
    assert "on this database" not in source


# --- #274's three review findings ---------------------------------------------


def test_the_scratch_mailing_carries_a_sender_when_the_orm_cannot_reach_one():
    """`email_from` is the one required field whose precompute can come back
    empty: with no `mail_server_id` it resolves to
    `create_uid.email_formatted or env.user.email_formatted`
    (`mailing.py:260-275`), and `email_formatted` is False for a user whose
    partner has no email -- the fresh or catch-up database this seed exists for.
    A required stored field is `NOT NULL` in Postgres (`fields.apply_required`),
    so that is an `IntegrityError` on the create, not an odd record."""
    side = FakeSide(user_email=False)
    fixture = seed_document_mailing(side)
    assert (side.mailings[fixture["mailing_id"]]["email_from"]
            == markup.SCRATCH_MAILING_EMAIL_FROM)
    # Unroutable on purpose: the draft is deleted without being sent, and an
    # address that could reach somebody is not what a placeholder is for.
    assert markup.SCRATCH_MAILING_EMAIL_FROM.endswith(".invalid")


def test_the_orm_keeps_its_own_sender_wherever_it_has_one():
    """The fallback is a fallback. Where the compute can reach a value, the row
    this seed makes is the row the form would have made."""
    side = FakeSide(user_email="someone@woow.invalid")
    fixture = seed_document_mailing(side)
    assert "email_from" not in side.mailings[fixture["mailing_id"]]


def test_a_scratch_mailing_an_earlier_run_left_is_reclaimed_not_borrowed():
    """The trap in `--surface both` without `--cleanup`: the ingress surface
    leaves its scratch mailing, the public surface's search finds it, and
    reading that as borrowed would restore *this run's own* fixture body while
    recording `body_restored: true` -- and would make the row permanent, because
    every later run would read it the same way and no `--cleanup` could ever
    delete it."""
    earlier = markup.scratch_task_name("WOOW-MARKUP-20261003T010101Z")
    side = FakeSide(mailings={5: {"state": "draft", "subject": earlier,
                                  "body_arch": "<p>an earlier fixture</p>",
                                  "body_html": False}})
    fixture = seed_document_mailing(side)
    assert fixture["mailing_id"] == 5
    assert fixture["extra"]["mailing_source"] == "reclaimed"
    assert fixture["extra"]["fixture"]["mailing_id"] == 5
    assert fixture["extra"]["fixture"]["mailing_reclaimed"] is True

    outcome = leave(side, fixture, cleanup=True)
    assert 5 not in side.mailings
    assert outcome["extra"]["fixture_removed"] == {"attachment": True, "mailing": True}
    assert "body_restored" not in outcome["extra"]


def test_a_real_mailing_is_not_reclaimed_by_a_subject_that_merely_looks_like_one():
    """The reclaim test is the prefix, so a real campaign that happens to
    mention the words keeps every protection a borrowed row has."""
    mentions = "Re: " + markup.SCRATCH_NAME_PREFIX + "what is this?"
    side = FakeSide(mailings={6: {"state": "draft", "subject": mentions,
                                  "body_arch": BORROWED, "body_html": BORROWED}})
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["mailing_source"] == "found"
    assert fixture["scratch_mailing"] is None
    leave(side, fixture, cleanup=True)
    assert side.mailings[6]["body_arch"] == BORROWED


def test_the_name_the_seed_writes_is_the_name_the_reclaim_reads():
    """A round trip, so the two halves cannot drift apart: whatever
    `scratch_task_name` writes, `reclaimable_scratch_mailing` must recognise."""
    assert markup.scratch_task_name(RUN).startswith(markup.SCRATCH_NAME_PREFIX)
    side = FakeSide(mailings={3: {"state": "draft",
                                  "subject": markup.scratch_task_name(RUN),
                                  "body_arch": "<p>an earlier fixture</p>"}})
    # `body_arch` comes back in the same call as the test, because this is the
    # last moment it says anything: the seeder's body write replaces the href it
    # carries and the delete takes the row (#277).
    assert markup.reclaimable_scratch_mailing(side, 3) == {
        "id": 3, "subject": markup.scratch_task_name(RUN), "state": "draft",
        "body_arch": "<p>an earlier fixture</p>"}


def test_a_compensation_that_could_not_remove_its_rows_says_so(capsys):
    """`run_check` discards a handler's return value when it raises, so `extra`
    -- and with it `fixture_removed` -- never reaches the evidence from the
    seeder. A silent `except` would then read as "removed" for a public
    attachment and a mailing still on the host, which is the trap
    `_remove_mailing_fixture` reports outcomes to avoid."""
    side = FakeSide(fail_write=True, fail_unlink=True)
    with pytest.raises(RuntimeError, match="body could not be written"):
        seed_document_mailing(side)
    said = capsys.readouterr().err
    assert "media-document-mailing left a fixture behind" in said
    assert str(next(iter(side.mailings))) in said
    assert str(next(iter(side.attachments))) in said
    assert '"mailing": false' in said and '"attachment": false' in said


# --- #276: the editable check builds its own mailing and borrows nothing -------
#
# The same two halves as #274, on the one check #274 left alone -- and the
# decision is **not** the same one. `mailing-editable` types in the designer and
# clicks save, because #238's whole subject is the save seam: `body_arch` through
# `getEditingValue`, and `body_html`, which `commitChanges` inlines separately.
# A run therefore stored this run's marker body in *both* fields of a mailing
# somebody else made, and `--cleanup` is optional. So this check creates its own
# mailing and borrows nothing unless `--mailing-id` names one: nothing measured
# is lost, because the designer, `getEditingValue` and `commitChanges` do not
# care which record they are on.


def seed_editable_mailing(side, mailing_id=None):
    return markup.seed_editable_mailing_fixture(side, RUN, mailing_id)


def leave_editable(side, fixture, **kwargs):
    return markup._mailing_editable_leaving(
        side, fixture, fixture["extra"], "/screen",
        pictures=None, stored={}, readings={}, notes="", **kwargs)


def test_a_database_with_no_mailing_at_all_gets_one_the_editable_check_made():
    """#276's reading: on a fresh install, a catch-up database or the local
    add-on's own, this check recorded `NOT-RUN` and measured nothing."""
    side = FakeSide()
    fixture = seed_editable_mailing(side)
    mailing_id = fixture["mailing_id"]
    assert fixture["scratch_mailing"] is not None
    assert fixture["extra"]["mailing_source"] == "created"
    assert side.mailings[mailing_id]["subject"] == markup.scratch_task_name(RUN)
    # The body the designer will open on, seeded over RPC so the measured value
    # is exactly the seeded one.
    assert side.mailings[mailing_id]["body_arch"] == markup.mailing_body_value(RUN)
    assert fixture["extra"]["fixture"]["mailing_id"] == mailing_id
    assert fixture["extra"]["fixture"]["mailing_reclaimed"] is False


def test_the_editable_check_does_not_save_over_a_real_campaign():
    """The decision this issue owns, and the reason it differs from #274's.

    This check *saves*: a borrowed row would keep this run's marker body in both
    `body_arch` and `body_html` -- the field that leaves the installation with
    the mail -- if the run were killed between the save and the restore, or taken
    without `--cleanup`, which is optional. So a real draft on the database is
    left exactly as it was found, and the check builds its own row beside it.
    """
    side = FakeSide(mailings={4: {"state": "draft", "subject": "Real campaign",
                                  "body_arch": BORROWED, "body_html": BORROWED}})
    fixture = seed_editable_mailing(side)
    assert fixture["mailing_id"] != 4
    assert fixture["extra"]["mailing_source"] == "created"
    assert side.mailings[4]["body_arch"] == BORROWED
    assert side.mailings[4]["body_html"] == BORROWED

    outcome = leave_editable(side, fixture, cleanup=True)
    assert 4 in side.mailings and side.mailings[4]["body_arch"] == BORROWED
    assert fixture["mailing_id"] not in side.mailings
    assert outcome["extra"]["fixture_removed"] == {"mailing": True}
    # Nothing was borrowed, so nothing may report a borrowed body put back.
    assert "body_restored" not in outcome["extra"]


def test_the_editable_check_reclaims_a_scratch_mailing_it_left_behind():
    """`--cleanup` is optional, so a run without it leaves this check's scratch
    mailing on the database -- and `--surface both` leaves the ingress surface's
    for the public surface to find. Reclaiming it is what stops a row per run
    accumulating under a name no `--cleanup` would ever reach, because this
    check no longer searches for anything else."""
    earlier = markup.scratch_task_name("WOOW-MARKUP-20261003T010101Z")
    side = FakeSide(mailings={5: {"state": "draft", "subject": earlier,
                                  "body_arch": "<p>an earlier fixture</p>",
                                  "body_html": False}})
    fixture = seed_editable_mailing(side)
    assert fixture["mailing_id"] == 5
    assert fixture["extra"]["mailing_source"] == "reclaimed"
    assert fixture["extra"]["fixture"]["mailing_reclaimed"] is True
    assert not side.did("mailing.mailing", "create")

    outcome = leave_editable(side, fixture, cleanup=True)
    assert 5 not in side.mailings
    assert outcome["extra"]["fixture_removed"] == {"mailing": True}
    assert "body_restored" not in outcome["extra"]


def test_a_real_campaign_is_never_reclaimed_by_a_subject_that_merely_looks_like_one():
    """The search is `=like` on the prefix and the read-back repeats the test, so
    a real campaign that happens to quote the words is not deleted. It is not
    borrowed either: this check builds its own."""
    mentions = "Re: " + markup.SCRATCH_NAME_PREFIX + "what is this?"
    side = FakeSide(mailings={6: {"state": "draft", "subject": mentions,
                                  "body_arch": BORROWED, "body_html": BORROWED}})
    fixture = seed_editable_mailing(side)
    assert fixture["mailing_id"] != 6
    assert fixture["extra"]["mailing_source"] == "created"
    leave_editable(side, fixture, cleanup=True)
    assert side.mailings[6]["body_arch"] == BORROWED


def test_mailing_id_is_the_one_way_the_editable_check_still_borrows():
    """The operator named the row, so it is reused, not created, not deleted --
    and its two fields are written back, which is the whole reason the restore
    stays in this check at all."""
    side = FakeSide(mailings={9: {"state": "done", "subject": "Sent",
                                  "body_arch": BORROWED, "body_html": BORROWED}})
    fixture = seed_editable_mailing(side, mailing_id=9)
    assert fixture["mailing_id"] == 9 and fixture["scratch_mailing"] is None
    assert fixture["extra"]["mailing_source"] == "given"
    assert not side.did("mailing.mailing", "create")
    assert not side.did("mailing.mailing", "search")
    assert side.mailings[9]["body_arch"] != BORROWED, "the seed overwrote the body"

    outcome = leave_editable(side, fixture, cleanup=True)
    assert 9 in side.mailings
    assert side.mailings[9]["body_arch"] == BORROWED
    assert side.mailings[9]["body_html"] == BORROWED
    assert outcome["extra"]["body_restored"] is True
    assert not side.did("mailing.mailing", "unlink")
    assert outcome["extra"]["fixture_removed"] == {}


def test_a_borrowed_mailing_is_restored_even_when_the_check_gave_up_early():
    """Three of the browser half's four exits are give-up paths, and the body was
    seeded over RPC *before* the first navigation. A `--cleanup` run that gave up
    at the iframe used to leave this run's marker body in `body_arch`, because the
    restore sat only on the path that had saved."""
    side = FakeSide(mailings={9: {"state": "draft", "subject": "Real campaign",
                                  "body_arch": BORROWED, "body_html": BORROWED}})
    fixture = seed_editable_mailing(side, mailing_id=9)
    outcome = leave_editable(side, fixture, cleanup=True)
    assert side.mailings[9]["body_arch"] == BORROWED
    assert outcome["extra"]["body_restored"] is True


def test_the_two_mailing_checks_differ_only_in_whether_they_borrow():
    """One seam, and the decision each check makes on it. The document check does
    not save, so borrowing a draft costs its owner a `body_arch` this run writes
    back; the editable check saves, so it builds its own."""
    real = {4: {"state": "draft", "subject": "Real campaign",
                "body_arch": BORROWED, "body_html": BORROWED}}
    borrowing = markup.fixture_mailing(FakeSide(mailings=dict(real)), RUN, None, borrow=True)
    assert (borrowing["mailing_id"], borrowing["source"]) == (4, "found")
    assert borrowing["scratch"] is None

    building = markup.fixture_mailing(FakeSide(mailings=dict(real)), RUN, None, borrow=False)
    assert building["source"] == "created" and building["mailing_id"] != 4
    assert building["scratch"] is not None


def test_the_scratch_search_reads_the_name_the_seed_writes():
    """The round trip the reclaim rests on, now that it is a `search` and not a
    read of whatever the state search happened to return first."""
    side = FakeSide(mailings={
        3: {"state": "draft", "subject": "Real campaign"},
        4: {"state": "done", "subject": markup.scratch_task_name(RUN)},
        5: {"state": "draft", "subject": markup.scratch_task_name(RUN)},
    })
    # Not the real campaign, and not a scratch row the designer would render
    # readonly: the state bound is the lookup's own.
    assert markup.scratch_mailing_id(side) == 5
    assert markup.scratch_mailing_id(FakeSide()) is None


def test_a_seed_that_fails_after_making_the_editable_mailing_removes_it():
    """`run_check` discards a handler's return value when it raises, so the row
    would be on the host with nothing in the evidence naming it."""
    side = FakeSide(fail_write=True)
    with pytest.raises(RuntimeError, match="body could not be written"):
        seed_editable_mailing(side)
    assert not side.mailings


def test_an_editable_seed_that_could_not_remove_its_mailing_says_so(capsys):
    """The console is the only place left: `extra` never reaches the evidence
    from a seeder that raises."""
    side = FakeSide(fail_write=True, fail_unlink=True)
    with pytest.raises(RuntimeError, match="body could not be written"):
        seed_editable_mailing(side)
    said = capsys.readouterr().err
    assert "mailing-editable left a fixture behind" in said
    assert str(next(iter(side.mailings))) in said
    assert '"mailing": false' in said


def test_the_editable_check_gives_up_on_no_database_of_its_own():
    """The `NOT-RUN` sentence #276 is about, gone from both halves."""
    source = (inspect.getsource(markup.do_mailing_editable)
              + inspect.getsource(markup._mailing_after_seeding))
    assert "on this database" not in source


def test_the_editable_check_declares_the_rows_it_now_creates():
    """`read_only_first` orders on this flag and the register describes the
    check by it; the check wrote before #276 and creates a row now."""
    assert markup.CHECKS["mailing-editable"]["writes"] is True


# --- #286: the stored `body_html` is only ever what this save wrote -----------
#
# `stored["mailing.mailing.body_html"]` is meant as a **Write-bounding reading**:
# a prefix in it is *this* save's `commitChanges` leaking. On a **Reclaimed row**
# whose save stores only `body_arch` it had quietly become a State-bounding one --
# the value read back was the earlier surface's inlined leftover, and
# `stored_verdict` judges every field it is handed, so the record attributed to
# one surface a prefix the other surface's save wrote. ADR 0014 refuses to
# suppress that judgement: the fix is at the **write**, so the field is empty
# when the browser half begins.

# What an earlier surface's save left inlined: this run's typed marker, because
# `--run-id` is one value for the whole invocation (#279), and a prefixed `src`,
# because that surface's save is exactly what #238 is about.
INLINED_LEFTOVER = (
    '<div class="o_layout"><p>%s</p><img src="%s" alt="logo"></div>'
    % (markup.marker_for(RUN), PREFIX + PICTURE))


def reclaimed_with_inlined_body(body_html=INLINED_LEFTOVER):
    """This driver's own scratch row, carrying the `body_html` a save left in it.

    The subject is an **earlier** run's, the way `scratch_mailing_id` finds one:
    what makes the row reclaimable is the prefix, not the run id in it.
    """
    return FakeSide(mailings={5: {
        "state": "draft",
        "subject": markup.scratch_task_name("WOOW-MARKUP-20261003T010101Z"),
        "body_arch": "<p>an earlier fixture</p>", "body_html": body_html}})


def test_the_seed_clears_the_body_html_it_is_about_on_a_row_it_owns():
    """The row is this driver's own litter, so the field can be emptied before the
    designer opens -- and then whatever is read back afterwards is this save's."""
    side = reclaimed_with_inlined_body()
    fixture = seed_editable_mailing(side)
    assert fixture["mailing_id"] == 5
    assert fixture["extra"]["mailing_source"] == "reclaimed"
    assert side.mailings[5]["body_arch"] == markup.mailing_body_value(RUN)
    assert side.mailings[5]["body_html"] is False
    # The reading of what the seed left the field as, which is what
    # `body_html_inlined` now compares the save against.
    assert fixture["seeded"] == {"body_html": False}


def test_the_seed_and_the_clear_are_one_write():
    """Two fields, one `write` -- the shape `_restore_mailing_body` already uses
    on this model, rather than two sequential single-field writes."""
    side = reclaimed_with_inlined_body()
    seed_editable_mailing(side)
    [write] = side.did("mailing.mailing", "write")
    assert write[2][1] == {"body_arch": markup.mailing_body_value(RUN),
                           "body_html": False}


def test_the_clear_never_touches_the_row_the_operator_named():
    """The gate is `_restore_borrowed_mailing_body`'s own guard inverted, and that
    is what makes the clear safe: the one row this check does not own is the one
    `--mailing-id` named, whose inlined body an ungated clear would blank -- with
    the restore running under `--cleanup` only."""
    side = FakeSide(mailings={9: {"state": "draft", "subject": "Real campaign",
                                  "body_arch": BORROWED, "body_html": BORROWED}})
    fixture = seed_editable_mailing(side, mailing_id=9)
    assert fixture["scratch_mailing"] is None and fixture.get("seeded") is None
    assert side.mailings[9]["body_html"] == BORROWED, "the campaign kept its body"
    [write] = side.did("mailing.mailing", "write")
    assert write[2][1] == {"body_arch": markup.mailing_body_value(RUN)}


def test_the_pre_run_body_html_is_still_the_fixture_s_own_reading():
    """`fixture["before"]` is both the restore source and the evidence of what was
    on the row, and the same fixture shape is shared with the document-mailing
    seeder -- so the clear gets a reading of its own rather than overwriting it."""
    side = reclaimed_with_inlined_body()
    fixture = seed_editable_mailing(side)
    assert fixture["before"]["body_html"] == INLINED_LEFTOVER
    assert fixture["before"]["body_arch"] == "<p>an earlier fixture</p>"
    # #279's reading keeps its meaning and its place: the marker was on the row
    # before this run touched it.
    assert fixture["extra"]["body_html_marker_before"] is True


def test_a_reclaimed_row_can_now_say_that_this_save_inlined():
    """#279 could only read `false` on this row, whichever way the save went,
    because the marker was in the field before the seed. The clear makes the
    reading two-way there, which is the second half of this fix."""
    side = reclaimed_with_inlined_body()
    fixture = seed_editable_mailing(side)
    baseline = markup.body_html_baseline(fixture)
    assert not markup.body_html_marked(RUN, baseline)
    assert markup.body_html_inlined(RUN, baseline,
                                    {"body_html": markup.marker_for(RUN)})
    assert not markup.body_html_inlined(RUN, baseline, {"body_html": False})
    source = inspect.getsource(markup._mailing_after_seeding)
    assert "body_html_inlined(run_id, body_html_baseline(fixture), after)" in source


def test_the_baseline_is_the_pre_run_read_wherever_the_seed_cleared_nothing():
    """On the `given` branch #279's reading stands exactly as it was: a marker in
    a row named by `--mailing-id` is not evidence that *this* save put it there."""
    typed = markup.marker_for(RUN)
    side = FakeSide(mailings={9: {"state": "draft", "subject": "Real campaign",
                                  "body_arch": BORROWED,
                                  "body_html": "<div><p>%s</p></div>" % typed}})
    fixture = seed_editable_mailing(side, mailing_id=9)
    baseline = markup.body_html_baseline(fixture)
    assert baseline is fixture["before"]
    assert not markup.body_html_inlined(RUN, baseline, {"body_html": typed})
    # And a fixture that never reached its `before` read has nothing to compare
    # against rather than a KeyError, the way the give-up paths leave it.
    assert markup.body_html_baseline({"before": {}}) == {}


def test_a_prefix_the_other_surface_inlined_is_not_judged_as_this_save_s():
    """The judged half, and the whole of #286. `stored_verdict` is unchanged and
    still judges every field it is handed -- what changes is that the field holds
    this save's output. Before the clear, the leftover scored `PREFIX-STORED`
    against the surface that did not write it, and on the Public origin a stored
    prefix is the leaked-`sub_filter` finding, so the mis-attribution landed on the
    surface where that verdict means something else entirely."""
    assert markup.stored_verdict(INLINED_LEFTOVER)[0] == markup.PREFIX_STORED
    side = reclaimed_with_inlined_body()
    fixture = seed_editable_mailing(side)
    # A save that stores only `body_arch`, which is the case the stale value
    # reached a verdict through.
    markup.write_field(side, "mailing.mailing", 5, "body_arch",
                       markup.MAILING_BODY_VALUE)
    after = side.rpc("mailing.mailing", "read", [[5], ["body_arch", "body_html"]])[0]
    record = markup.evidence_record(
        check="mailing-editable", issue=238, run_id=RUN, database="odoo_parity",
        target="local", surface=PUBLIC, screen="/x",
        pictures=[{"verdict": markup.AT_ORIGIN_ROOT}],
        stored={"mailing.mailing.body_arch": after.get("body_arch"),
                "mailing.mailing.body_html": after.get("body_html")},
        readings={"mailing.mailing.body_arch": markup.WRITE_BOUNDING,
                  "mailing.mailing.body_html": markup.mailing_body_html_reading(fixture)},
        extra=fixture["extra"])
    assert record["stored"]["mailing.mailing.body_html"] == {
        "verdict": markup.CLEAN, "prefixes": 0, "reading": markup.WRITE_BOUNDING}
    assert record["verdict"] == markup.AT_ORIGIN_ROOT

# --- #277: a reclaim deletes the attachments the reclaimed body links ----------
#
# `--cleanup` removed the attachment *this* run created and the scratch mailing,
# whoever made it. So a run taken without `--cleanup` left mailing M whose
# `body_arch` links public attachment A, and the next run reclaimed and deleted
# M -- stranding A, which is in no fixture dict any run holds afterwards. A
# scratch row's body is only ever this driver's own fixture body, so the
# attachment ids in it are this driver's and removing them keeps "delete what
# the driver made" true.

EARLIER = "WOOW-MARKUP-20261003T010101Z"


def earlier_document_body(attachment_id, **overrides):
    """The body an earlier run's `media-document-mailing` left on its scratch row."""
    attachment = dict(ATTACHMENT, id=attachment_id, **overrides)
    return markup.mailing_document_body_value(EARLIER, attachment)


def scratch_with_document(attachment_id, body=None):
    """A FakeSide carrying that earlier run's litter: the mailing and its attachment."""
    side = FakeSide(mailings={5: {
        "state": "draft", "subject": markup.scratch_task_name(EARLIER),
        "body_arch": body if body is not None else earlier_document_body(attachment_id),
        "body_html": False}})
    side.attachments[attachment_id] = {"name": "woow-document-fixture-old.txt",
                                       "mimetype": "text/plain", "public": True}
    return side


def test_a_reclaimed_mailing_s_attachment_goes_with_it():
    """The one-check case, which predates #276: run the document check without
    `--cleanup`, run it again, and the public attachment the first run's body
    links must not survive the second run's reclaim. It goes with the **reclaim**
    and not with the cleanup, so it is already gone when the seed returns."""
    side = scratch_with_document(77)
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["mailing_source"] == "reclaimed"
    assert fixture["attachment"]["id"] != 77, "this run built its own"
    assert 77 not in side.attachments
    assert fixture["extra"]["fixture"]["reclaimed_attachments_removed"] is True

    outcome = leave(side, fixture, cleanup=True)
    assert 5 not in side.mailings
    # The reclaim is not part of this run's fixture, so it is not in the key
    # that reports what the cleanup removed.
    assert outcome["extra"]["fixture_removed"] == {"attachment": True, "mailing": True}
    assert not side.attachments, "the earlier run's attachment is still on the host"


def test_a_run_without_cleanup_still_takes_the_reclaimed_attachment():
    """**The half `--cleanup` cannot own**, and the review of the first cut of
    this fix is where it came from. The seeder's body write replaces the only
    href naming the stranded row and runs whatever the flag says, so a reclaim
    without `--cleanup` left a mailing that no longer named the attachment -- and
    the next `--cleanup` run then read a body naming nothing and deleted the row,
    stranding it for good. `--cleanup` asks "leave the host as this run found
    it"; an earlier run's abandoned litter is not an answer to that question."""
    side = scratch_with_document(77)
    fixture = seed_document_mailing(side)
    outcome = leave(side, fixture, cleanup=False)
    assert 77 not in side.attachments
    # Everything this run owns is still there, which is what no `--cleanup` means.
    assert 5 in side.mailings
    assert fixture["attachment"]["id"] in side.attachments
    assert "fixture_removed" not in outcome["extra"]


def test_the_reclaim_runs_before_the_attachment_this_run_builds():
    """It is the first step inside the seeder's guard, because every step after
    it can fail and the compensation deletes the reclaimed row -- taking the
    body those ids are read from with it."""
    side = scratch_with_document(77)
    side.fail_attachment = True
    with pytest.raises(RuntimeError, match="attachment could not be created"):
        seed_document_mailing(side)
    assert 77 not in side.attachments
    assert not side.mailings, "the reclaimed row was still deleted"


def test_the_editable_check_reclaiming_the_other_check_s_mailing_takes_its_attachment():
    """#276's half: both mailing checks now write the same `SCRATCH_NAME_PREFIX`
    subject, so `mailing-editable` can reclaim a row `media-document-mailing`
    left -- and it builds no attachment of its own to confuse the reading."""
    side = scratch_with_document(77)
    fixture = seed_editable_mailing(side)
    assert fixture["mailing_id"] == 5
    assert fixture["extra"]["mailing_source"] == "reclaimed"

    assert 77 not in side.attachments, "the reclaim took it, not the cleanup"
    outcome = leave_editable(side, fixture, cleanup=True)
    assert outcome["extra"]["fixture_removed"] == {"mailing": True}
    assert not side.attachments and 5 not in side.mailings


def test_the_ids_are_read_off_the_reclaim_and_not_off_the_seeded_body():
    """The bound is `scratch_mailing`'s own `body_arch`, which only
    `reclaimable_scratch_mailing` sets. `fixture["before"]` is the same value for
    a reclaim, but it is *not* the same thing: it is read for a borrowed row too,
    and reading somebody's campaign for attachment ids is the one thing this must
    never do."""
    body = '<a href="/web/content/77?download=true"></a>'
    assert markup.reclaimed_attachment_ids(
        {"scratch_mailing": {"id": 5, "body_arch": body}}) == [77]
    assert markup.reclaimed_attachment_ids({"before": {"body_arch": body}}) == []
    # A row this run created: `create_fixture_mailing` returns no body at all.
    assert markup.reclaimed_attachment_ids({"scratch_mailing": {"id": 5}}) == []


def test_the_ids_a_reclaim_will_delete_are_in_the_record():
    """`extra["fixture"]` is what a later reader consults to know what this run
    is answerable for -- and the only place the ids appear when the unlink comes
    back false."""
    side = scratch_with_document(77)
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["fixture"]["reclaimed_attachment_ids"] == [77]
    assert fixture["extra"]["fixture"]["mailing_reclaimed"] is True


def test_a_reclaimed_body_naming_two_attachments_loses_both():
    """The body is read for ids rather than for the one id this driver's template
    writes, because a reclaimed row's body is whatever an earlier run of *either*
    mailing check left in it."""
    side = scratch_with_document(77, body=(
        '<div class="o_layout"><p>%s</p><p>%s</p><p>%s</p></div>' % (
            markup.marker_for(EARLIER),
            markup.document_link_markup(dict(ATTACHMENT, id=77)),
            markup.document_link_markup(dict(ATTACHMENT, id=78)))))
    side.attachments[78] = {"name": "woow-document-fixture-older.txt",
                            "mimetype": "text/plain", "public": True}
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["fixture"]["reclaimed_attachment_ids"] == [77, 78]
    leave(side, fixture, cleanup=True)
    assert not side.attachments


def test_a_borrowed_campaign_s_own_attachments_are_never_unlinked():
    """The whole reason the scan is bounded by the reclaim. A real campaign's
    body links a real company's real attachments; this driver deletes what it
    made, and it did not make those."""
    body = ('<div class="o_layout"><p>our newsletter</p>'
            '<a href="/web/content/77?download=true">the price list</a></div>')
    side = FakeSide(mailings={4: {"state": "draft", "subject": "Real campaign",
                                  "body_arch": body, "body_html": body}})
    side.attachments[77] = {"name": "price-list.pdf", "mimetype": "application/pdf"}
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["mailing_source"] == "found"
    # Not in the record either: `extra["fixture"]` says what this run will
    # delete, and naming somebody's price list there is its own wrong reading.
    assert "reclaimed_attachment_ids" not in fixture["extra"]["fixture"]

    outcome = leave(side, fixture, cleanup=True)
    assert 77 in side.attachments
    assert outcome["extra"]["fixture_removed"] == {"attachment": True}
    assert "reclaimed_attachments" not in outcome["extra"]["fixture_removed"]
    assert side.mailings[4]["body_arch"] == body


def test_a_mailing_the_operator_named_keeps_its_attachments():
    """`--mailing-id`'s meaning is unchanged: do not look, do not create, do not
    delete -- and that reaches the rows its body links as well as the row."""
    body = ('<div class="o_layout"><p>sent</p>'
            '<a href="/web/content/77?download=true">the price list</a></div>')
    side = FakeSide(mailings={9: {"state": "done", "subject": "Sent",
                                  "body_arch": body, "body_html": body}})
    side.attachments[77] = {"name": "price-list.pdf", "mimetype": "application/pdf"}
    fixture = seed_document_mailing(side, mailing_id=9)
    assert "reclaimed_attachment_ids" not in fixture["extra"]["fixture"]
    outcome = leave(side, fixture, cleanup=True)
    assert 77 in side.attachments
    assert "reclaimed_attachments" not in outcome["extra"]["fixture_removed"]


def test_a_mailing_this_run_made_names_no_reclaimed_attachment():
    """A created row's body is empty when it is read, so there is nothing to
    scan -- and a key saying "nothing to remove" would read as a removal."""
    side = FakeSide()
    fixture = seed_document_mailing(side)
    assert "reclaimed_attachment_ids" not in fixture["extra"]["fixture"]
    outcome = leave(side, fixture, cleanup=True)
    assert outcome["extra"]["fixture_removed"] == {"attachment": True, "mailing": True}


def test_a_href_whose_attachment_is_already_gone_does_not_block_the_reclaim():
    """The dangling case is reachable: `_remove_mailing_fixture` unlinks the
    attachment before the mailing and reports each separately, so a run whose
    mailing unlink failed left exactly this -- a body linking an id that no
    longer exists. Unlinking a missing id is a `MissingError`, which would make
    the reclaim fail for litter that is already gone, so the ids are filtered
    through a search first."""
    side = scratch_with_document(77)
    del side.attachments[77]
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["fixture"]["reclaimed_attachments_removed"] is True
    assert all(77 not in call[2][0] for call in side.did("ir.attachment", "unlink"))
    outcome = leave(side, fixture, cleanup=True)
    assert outcome["extra"]["fixture_removed"] == {"attachment": True, "mailing": True}
    assert 5 not in side.mailings


def test_a_reclaimed_attachment_that_could_not_be_removed_is_reported_not_swallowed():
    """`remove_website_fixture_page`'s reason, and `_remove_mailing_fixture`'s:
    a silent `except` reads as "removed" for a public attachment still on the
    host."""
    side = scratch_with_document(77)
    side.fail_unlink = True
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["fixture"]["reclaimed_attachments_removed"] is False
    assert fixture["extra"]["fixture"]["reclaimed_attachment_ids"] == [77]
    assert 77 in side.attachments
    # The seed itself is unaffected: the litter is not what this check measures.
    assert side.mailings[5]["body_arch"] == markup.mailing_document_body_value(
        RUN, fixture["attachment"])


def test_a_seeder_that_could_not_remove_a_reclaimed_attachment_names_it(capsys):
    """`extra` -- and with it `fixture_removed` -- never reaches the evidence from
    a seeder that raises, so the ids have to be on the console or nowhere."""
    side = scratch_with_document(77)
    side.fail_write = True
    side.fail_unlink = True
    with pytest.raises(RuntimeError, match="body could not be written"):
        seed_document_mailing(side)
    said = capsys.readouterr().err
    assert "media-document-mailing left a fixture behind" in said
    assert '"reclaimed_attachment_ids": [77]' in said
    assert '"reclaimed_attachments_removed": false' in said


def test_a_failed_reclaim_is_named_even_when_the_fixture_came_off_cleanly(capsys):
    """`removed` cannot carry the reclaim's outcome -- the reclaim ran before
    anything in the seeder could fail -- so the console condition reads it from
    the record instead. Otherwise a compensation whose mailing and attachment
    came off cleanly would say nothing at all about the public attachment it
    could not remove, and `extra` never reaches the evidence from a seeder."""
    side = scratch_with_document(77)
    extra = {"fixture": {"reclaimed_attachment_ids": [77],
                         "reclaimed_attachments_removed": False}}
    fixture = {"mailing_id": 5, "scratch_mailing": dict(side.mailings[5], id=5),
               "attachment": None, "before": {}, "extra": extra}
    markup._abandon_mailing_fixture(side, fixture, extra, "media-document-mailing")
    assert 5 not in side.mailings, "the row itself came off cleanly"
    said = capsys.readouterr().err
    assert '"reclaimed_attachment_ids": [77]' in said
    assert '"reclaimed_attachments_removed": false' in said
    assert '"mailing": true' in said


def test_the_scan_reads_an_href_the_designer_rewrote_under_the_prefix():
    """The litter this reclaim finds was left by a check that *saves*, and the
    whole subject of #238 is that the save may store the href prefixed. The id
    is found inside the longer path for the same reason the pattern is not
    anchored."""
    side = scratch_with_document(77, body=(
        '<div class="o_layout"><p>%s</p>'
        '<a class="o_image" href="/abcd1234_odoo/web/content/77?download=true"></a>'
        '</div>' % markup.marker_for(EARLIER)))
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["fixture"]["reclaimed_attachment_ids"] == [77]
    leave(side, fixture, cleanup=True)
    assert not side.attachments


def test_the_module_no_longer_declares_a_gap_in_what_cleanup_removes():
    """The docstring said `--cleanup` "removes all five, with one gap", and the
    gap was this. A reader takes that paragraph as the account of what a run
    leaves behind, so it is wrong in either direction."""
    writing = markup.__doc__.split("Writing:")[1].split("**The ambient")[0]
    assert "with one gap" not in writing
    assert "reclaimed" in writing and "#277" in writing


# --- #289: which kind of Stored reading a field carries ------------------------
#
# `stored_verdict` judges every field a check hands it and `evidence_record`
# promotes a `PREFIX-STORED` to that check's whole verdict ahead of every other
# branch. That rule is #237 check 4's and it is not in question here. What the
# record could not say is *which kind of reading* it just judged, and five of
# this driver's readings are on a field the check never wrote -- so a check whose
# register row says `writes: False` could be printed as the author of a write,
# which on the Public origin is the leaked-`sub_filter` finding and a more
# serious claim than "this row has held a prefix since before the run".
#
# ADR 0014 rules out the repair that suppresses such a verdict. These tests pin
# the admissible one: the kind is **declared per field by the flow that took the
# reading**, both kinds are still reported, and no verdict or exit code moves.

PREFIXED_VALUE = '<img src="%s%s">' % (PREFIX, PICTURE)
CLEAN_VALUE = '<img src="%s">' % PICTURE


def stored_record(check="readonly-plain", **kwargs):
    """A record for a check that read one field back, with the kind declared."""
    options = {
        "issue": 237, "run_id": "R", "database": "odoo_parity", "target": "local",
        "surface": PUBLIC, "screen": "/x",
        "pictures": [{"verdict": markup.AT_ORIGIN_ROOT}],
        "stored": {"project.task.description": PREFIXED_VALUE},
        "readings": {"project.task.description": markup.STATE_BOUNDING},
    }
    options.update(kwargs)
    return markup.evidence_record(check=check, **options)


def test_the_two_kinds_are_the_whole_taxonomy():
    """Q3 of #289's grilling: `--task-id` and `--mailing-id` reach the second kind
    by a different road, they do not make a third. The reading that says *why* --
    `mailing_source`, `created_template`, `record_id` -- is already in `extra` at
    every one of those sites, and that is a reading rather than a kind."""
    assert markup.READING_KINDS == (markup.WRITE_BOUNDING, markup.STATE_BOUNDING)
    assert len(set(markup.READING_KINDS)) == 2
    # And a kind is never a verdict, so the two vocabularies cannot be confused
    # by a reader or by an `==` against the wrong constant.
    verdicts = set(markup.PICTURE_VERDICTS) | {markup.CLEAN, markup.PREFIX_STORED,
                                               markup.NOT_RUN}
    assert not verdicts & set(markup.READING_KINDS)


def test_the_record_carries_the_kind_beside_the_verdict():
    """The per-field entry is where it lands: additive, so `verdict`,
    `stored_verdict` and `stored_values` keep the shape every existing evidence
    file has."""
    record = stored_record()
    assert record["stored"]["project.task.description"] == {
        "verdict": markup.PREFIX_STORED, "prefixes": 1,
        "reading": markup.STATE_BOUNDING,
    }


def test_the_kind_is_not_folded_into_the_verdict_string():
    """Where this differs from the peer snapshot driver's `classify`, which
    composes `OWN-`/`FOREIGN-`/`UNKNOWN-PREFIX-STORED` because *there* the kind is
    the verdict -- three findings with a severity order between them. Here the
    kind moves no verdict, and `do_report` filters on an equality against
    `PREFIX_STORED` which a composed string would break."""
    record = stored_record()
    assert record["stored_verdict"] == markup.PREFIX_STORED
    assert record["stored"]["project.task.description"]["verdict"] == markup.PREFIX_STORED


def test_a_state_bounding_prefix_still_fails_the_run(tmp_path):
    """Q2, and the half ADR 0014 settles. A prefix in that row **is** in the
    database, so the finding stands, is counted, and still exits non-zero. A
    per-check "judge but do not fail" policy would be the valve ADR 0014 refuses,
    one layer out: the finding would still vanish from the exit code, the tally
    and the sweep gate."""
    record = stored_record()
    assert record["verdict"] == markup.PREFIX_STORED, "ahead of the passing screen"
    summary = markup.summarise([record])
    assert summary["failed"] == 1
    assert summary["failures"] == ["readonly-plain/public: " + markup.PREFIX_STORED]
    records = tmp_path / "markup.jsonl"
    records.write_text(markup.json.dumps(record) + "\n", encoding="utf-8")
    assert markup.do_report(str(records)) == 1


def test_the_report_names_the_kind_and_only_the_prefixed_field(tmp_path, capsys):
    """What #289 actually buys. The same line used to read as an accusation
    against a check the register declares non-writing; naming the kind makes it a
    witness statement. The `CLEAN` field is dropped from the sentence because it
    was never part of the claim."""
    record = stored_record(
        check="mailing-readonly", issue=238,
        stored={"mailing.mailing.body_arch": CLEAN_VALUE,
                "mailing.mailing.body_html": PREFIXED_VALUE},
        readings={"mailing.mailing.body_arch": markup.STATE_BOUNDING,
                  "mailing.mailing.body_html": markup.STATE_BOUNDING})
    records = tmp_path / "markup.jsonl"
    records.write_text(markup.json.dumps(record) + "\n", encoding="utf-8")
    markup.do_report(str(records))
    printed = capsys.readouterr().out
    assert "PREFIX STORED by mailing-readonly/public in " in printed
    assert "mailing.mailing.body_html (state-bounding)" in printed
    assert "body_arch" not in printed, "a CLEAN field is not part of the claim"


def test_a_record_written_before_the_kind_existed_still_reports(tmp_path, capsys):
    """The schema stays `woow.ingress-markup/v1` because this is additive, and
    `report` reads any JSONL it is handed -- including the three evidence files
    already in this repo, every `stored` entry of which is `CLEAN`."""
    record = stored_record()
    del record["stored"]["project.task.description"]["reading"]
    records = tmp_path / "markup.jsonl"
    records.write_text(markup.json.dumps(record) + "\n", encoding="utf-8")
    assert markup.do_report(str(records)) == 1
    assert "project.task.description (kind not recorded)" in capsys.readouterr().out


def test_the_schema_is_unchanged_by_the_kind():
    assert markup.EVIDENCE_SCHEMA == "woow.ingress-markup/v1"


def test_the_redacted_values_keep_their_flat_shape():
    """Why the declaration travels beside `stored` rather than inside its values.
    `stored_values` is built straight off `stored` and is the one place a reader
    sees what was stored; making its values composite would nest that map a level
    deeper for every reader and every evidence file, to no end."""
    record = stored_record(stored={"project.task.description": CLEAN_VALUE})
    assert record["stored_values"] == {"project.task.description": CLEAN_VALUE}


# --- The guards: no default kind, and no incoherent one -----------------------


def test_a_stored_value_with_no_declared_kind_is_refused():
    """No default, because whichever constant a default named would be wrong at
    some site -- and the site it was wrong at is the one nobody looked at."""
    with pytest.raises(ValueError, match="which kind it is"):
        markup.evidence_record(
            check="readonly-plain", issue=237, run_id="R", database="odoo_parity",
            target="local", surface=INGRESS, screen="/x", pictures=[],
            stored={"project.task.description": CLEAN_VALUE})


def test_a_declaration_for_a_field_that_was_not_read_is_refused():
    """The other direction of the same mistake: a renamed field or a typo, which
    would read as "declared" while judging nothing."""
    with pytest.raises(ValueError, match="did not read back"):
        stored_record(readings={"project.task.description": markup.STATE_BOUNDING,
                                "project.task.desciption": markup.STATE_BOUNDING})


def test_a_kind_this_module_does_not_name_is_refused():
    with pytest.raises(ValueError, match="write-bounding or state-bounding"):
        stored_record(readings={"project.task.description": "incidental"})


@pytest.mark.parametrize("check", sorted(
    name for name, row in markup.CHECKS.items() if row["writes"] is False))
def test_a_check_that_writes_nothing_cannot_have_written_what_it_read(check):
    """The incoherent pairing is #289's own false claim, stated by the flow
    instead of inferred by a reader -- so the record refuses it. `readonly-plain`
    and `mailing-readonly` are the two rows this pins, and it is parametrized off
    the register so a row whose flag flips is covered either way."""
    with pytest.raises(ValueError, match="registered as writing nothing"):
        stored_record(check=check, issue=markup.CHECKS[check]["issue"],
                      readings={"project.task.description": markup.WRITE_BOUNDING})


def test_a_check_the_register_has_never_heard_of_is_left_alone():
    """The tests above build records for names the register does not carry, and a
    guard that refused them would be checking this file rather than the driver."""
    record = stored_record(check="not-a-registered-check",
                           readings={"project.task.description": markup.WRITE_BOUNDING})
    assert record["stored"]["project.task.description"]["reading"] == markup.WRITE_BOUNDING


# --- Every site declares, and a seventh cannot be added silently --------------

# The six places in the driver that build a non-empty `stored`. The guard above
# costs a surface its record rather than stopping a run -- it lands in
# `run_check`'s outer `except`, the way the `RESERVED_RECORD_KEYS` collision does
# -- so this is the test that actually keeps the sites honest.
STORED_SITES = {
    "do_readonly_iframe": {"mail.template.body_html"},
    "do_mailing_readonly": {"mailing.mailing.body_arch", "mailing.mailing.body_html"},
    "_codeview_after_seeding": {"ir.actions.act_window.help"},
    "do_readonly_plain": {"project.task.description"},
    "_mailing_after_seeding": {"mailing.mailing.body_arch", "mailing.mailing.body_html"},
    "_document_mailing_leaving": {"mailing.mailing.body_arch", "mailing.mailing.body_html"},
}

STORED_ASSIGNMENT = re.compile(r"\bstored(?::\s*dict\[str, Any\])? = \{(?!\})")


def stored_building_functions():
    """Every function in the driver that builds a non-empty `stored` mapping."""
    found = set()
    for name, value in sorted(vars(markup).items()):
        if not inspect.isfunction(value) or value.__module__ != markup.__name__:
            continue
        if STORED_ASSIGNMENT.search(inspect.getsource(value)):
            found.add(name)
    return found


def test_the_sites_that_read_a_field_back_are_the_ones_this_file_pins():
    """A seventh read-back has to join the table rather than arrive unnoticed --
    which is how four of the five mis-attributed readings got there in the first
    place: each was right about its own field and nobody held the set."""
    assert stored_building_functions() == set(STORED_SITES)


@pytest.mark.parametrize("name", sorted(STORED_SITES))
def test_every_site_that_reads_a_field_back_declares_its_kind(name):
    source = inspect.getsource(getattr(markup, name))
    assert "readings" in source, "%s reads a field back and declares no kind" % name
    for field in STORED_SITES[name]:
        assert field in source


# --- The two declarations a flag or a baseline decides ------------------------


def test_the_iframe_check_s_kind_follows_whether_it_seeded_the_template():
    """By default it creates the scratch template and seeds the full-HTML value,
    so the read-back is its own write. Under `--task-id` it seeds nothing and
    reads back a template the operator named -- same field, same line, and
    `writes: True` on the register row is true of the check and not of this field
    on this invocation."""
    source = inspect.getsource(markup.do_readonly_iframe)
    assert "WRITE_BOUNDING if created is not None else STATE_BOUNDING" in source
    # And `created` is set on exactly the branch that seeds.
    assert "task_id = created = seed_scratch_template(side, run_id)" in source


def test_the_editable_check_s_body_html_kind_follows_the_clear():
    """#286 cleared this field on a row the check owns, which is what makes the
    reading write-bounding there. On the one row the clear is withheld on -- the
    campaign `--mailing-id` named -- it is not, and that branch is #289's fifth
    site."""
    side = FakeSide()
    owned = seed_editable_mailing(side)
    assert owned["extra"]["mailing_source"] == "created"
    assert markup.mailing_body_html_reading(owned) == markup.WRITE_BOUNDING

    borrowed = FakeSide(mailings={9: {"state": "draft", "subject": "Real campaign",
                                      "body_arch": BORROWED,
                                      "body_html": "<p>a real campaign's body</p>"}})
    given = seed_editable_mailing(borrowed, mailing_id=9)
    assert given["extra"]["mailing_source"] == "given"
    assert "seeded" not in given, "the clear is withheld on a row the operator named"
    assert markup.mailing_body_html_reading(given) == markup.STATE_BOUNDING


def test_the_document_check_derives_its_body_html_kind_from_the_baseline():
    """The site where a flat declaration would throw the reading away. The check
    never writes this field, so on a borrowed draft the value is the campaign's
    own -- but if the discard did not hold, the save that got through is exactly
    what inlines `body_html`, and a prefix in what *it* wrote is this check's own
    leak. Only the change separates them."""
    fixture = {"before": {"body_arch": BORROWED, "body_html": "<p>as found</p>"}}
    assert markup.document_mailing_body_html_reading(
        fixture, {"body_html": "<p>as found</p>"}) == markup.STATE_BOUNDING
    assert markup.document_mailing_body_html_reading(
        fixture, {"body_html": "<p>the save got through</p>"}) == markup.WRITE_BOUNDING
    # An unset field on both sides is unchanged, and `stored_verdict(False)` is
    # `CLEAN` anyway -- the kind is still recorded rather than left out.
    assert markup.document_mailing_body_html_reading(
        {"before": {"body_html": False}}, {"body_html": False}) == markup.STATE_BOUNDING


def test_a_fixture_that_never_read_its_baseline_claims_nothing():
    """The give-up paths leave `before` empty. That is state-bounding rather than
    unknown, and it is not merely the cautious answer: a handler that got no
    further than its seed never navigated, so no save of its own could have
    reached the field."""
    assert markup.document_mailing_body_html_reading(
        {"before": {}}, {"body_html": PREFIXED_VALUE}) == markup.STATE_BOUNDING
    assert markup.document_mailing_body_html_reading(
        {}, {"body_html": PREFIXED_VALUE}) == markup.STATE_BOUNDING


def test_the_document_check_declares_one_field_of_each_kind():
    """Which is why the declaration is per field and not the register's `writes`
    row: one check, one write-bounding field and one state-bounding one, so no
    per-check flag can express it."""
    side = FakeSide(mailings={9: {"state": "draft", "subject": "Real campaign",
                                  "body_arch": BORROWED,
                                  "body_html": "<p>a real campaign's body</p>"}})
    fixture = seed_document_mailing(side)
    assert fixture["extra"]["mailing_source"] == "found", "borrowed, so body_html is theirs"
    outcome = leave(side, fixture, cleanup=True)
    assert outcome["readings"] == {
        "mailing.mailing.body_arch": markup.WRITE_BOUNDING,
        "mailing.mailing.body_html": markup.STATE_BOUNDING,
    }
    # And the pair survives into a record, which is the shape `evidence_record`
    # refuses to assemble from a half-declared one.
    record = markup.evidence_record(
        check="media-document-mailing", issue=239, run_id=RUN, database="odoo_parity",
        target="local", surface=PUBLIC, screen="/x",
        pictures=[{"verdict": markup.AT_ORIGIN_ROOT}],
        stored=outcome["stored"], readings=outcome["readings"])
    assert record["stored"]["mailing.mailing.body_arch"]["reading"] == markup.WRITE_BOUNDING
    assert record["stored"]["mailing.mailing.body_html"]["reading"] == markup.STATE_BOUNDING


def test_a_read_back_that_failed_leaves_both_mappings_empty():
    """The only shape `evidence_record` accepts of a check that read nothing: a
    field with no kind raises, and a kind with no field raises too."""
    side = FakeSide(mailings={9: {"state": "draft", "subject": "Real campaign",
                                  "body_arch": BORROWED, "body_html": False}})
    fixture = seed_document_mailing(side)
    # After the seed, so the baseline read it needs has already happened: the
    # window this covers is the read-back, which `run_check` closes the session
    # right after.
    unreachable = side.rpc

    def gone(model, method, args, kwargs=None):
        if method == "read":
            raise RuntimeError("the session is gone")
        return unreachable(model, method, args, kwargs)

    side.rpc = gone
    outcome = leave(side, fixture, cleanup=False)
    assert outcome["stored"] == {} and outcome["readings"] == {}
    assert fixture["extra"]["read_back_error"] == "RuntimeError"
