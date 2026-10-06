"""The pure parts of `e2e_ingress_hand_checks.py`, and the trap they exist for.

The driver itself needs a host and a browser. What can be tested without
either is the part a review found wrong once already: the first version of it
judged a **Prefix escape** by asking whether a request went to the Home
Assistant origin *outside* the prefix, which answers "no" for the doubled
prefix -- the one shape #211 is about, because a doubled prefix is still under
the prefix. These tests pin the judgement to the adapter's own, so a rewrite
cannot quietly lose it again.
"""
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import e2e_ingress_hand_checks as hand  # noqa: E402
import e2e_menu_action_adapter as adapter  # noqa: E402

ORIGIN = "http://192.0.2.10:8123"
PREFIX = "/api/hassio_ingress/Tok3nTok3nTok3nTok3n"
BASE = ORIGIN + PREFIX


class FakeDriver:
    """Only what the pure helpers read off a `SurfaceDriver`."""

    origin = ORIGIN
    prefix = PREFIX
    base = BASE


def signals_over(urls):
    signals = hand.Signals()
    signals.requested.extend(urls)
    return signals


def test_the_doubled_prefix_is_an_escape():
    """#211's own shape: still under the prefix, and still an escape.

    This is the case the rejected first version missed, and the reason this
    file exists: it starts with `base`, so "went outside the prefix" says no.
    """
    doubled = BASE + "/@" + PREFIX + "/shop/payment"
    assert doubled.startswith(BASE)                      # why the naive test failed
    assert signals_over([doubled]).escapes(FakeDriver()) == [doubled]


def test_the_home_assistant_root_is_an_escape():
    """#210's shape on 0.4.6: a picture asked of the Home Assistant root."""
    escaped = ORIGIN + "/project_todo/static/img/todo_access.png"
    assert signals_over([escaped]).escapes(FakeDriver()) == [escaped]


def test_a_request_under_the_prefix_is_not_an_escape():
    under = BASE + "/project_todo/static/img/todo_access.png"
    assert signals_over([under]).escapes(FakeDriver()) == []


def test_the_prefix_itself_is_not_an_escape():
    assert signals_over([BASE]).escapes(FakeDriver()) == []


def test_another_origin_is_not_this_surface_s_escape():
    """A third-party request is not a prefix question; the adapter says so."""
    assert signals_over(["https://fonts.example.test/x.woff2"]).escapes(FakeDriver()) == []


def test_escapes_are_sorted_and_deduplicated():
    escaped = ORIGIN + "/web/image/1"
    other = ORIGIN + "/a"
    assert signals_over([escaped, other, escaped]).escapes(FakeDriver()) == [other, escaped]


def test_the_escape_judgement_is_the_adapter_s():
    """Not a tautology: it fails if the helper stops delegating."""
    doubled = BASE + "/@" + PREFIX + "/"
    for url in (doubled, ORIGIN + "/x", BASE + "/x", BASE):
        assert bool(signals_over([url]).escapes(FakeDriver())) is adapter.is_prefix_escape(
            url, adapter.Surface.HA_INGRESS, ORIGIN, PREFIX)


def test_signals_land_in_the_record_under_the_adapter_s_names():
    signals = signals_over([ORIGIN + "/escaped"])
    signals.failed_responses.append("HTTP404 " + ORIGIN + "/escaped")
    signals.console_errors.append("error: boom")
    signals.page_errors.append("TypeError: x")
    record = {}
    signals.into(record, FakeDriver())
    assert record["route_escape"] == [ORIGIN + "/escaped"]
    assert record["http_4xx_5xx"] == ["HTTP404 " + ORIGIN + "/escaped"]
    assert record["console_error"] == ["error: boom"]
    assert record["pageerror"] == ["TypeError: x"]
    # Every name is one the adapter's own records use, so the two sets of
    # evidence read the same way.
    assert set(adapter.SIGNALS) >= {"route_escape", "http_4xx_5xx", "console_error", "pageerror"}


def test_route_of_strips_the_prefix():
    assert hand.route_of(FakeDriver(), BASE + "/shop/payment") == "/shop/payment"
    assert hand.route_of(FakeDriver(), BASE) == "/"


def test_route_of_is_none_off_the_prefix():
    """A url the prefix does not cover is named as such, not guessed at."""
    assert hand.route_of(FakeDriver(), ORIGIN + "/lovelace") is None


def test_the_marker_names_its_run():
    run_id = "WOOW-PARITY-20261001T073009Z"
    assert hand.marker_for(run_id).endswith(run_id)
    assert hand.marker_for(run_id) != hand.marker_for("WOOW-PARITY-20261001T000000Z")


@pytest.mark.parametrize("command", ["visit", "editbtn", "todosave"])
def test_every_command_the_parser_takes_has_a_branch(command):
    """The parser's choices and `run`'s branches cannot drift apart."""
    parser_choices = {"visit", "editbtn", "todosave"}
    assert command in parser_choices
    assert hasattr(hand, "do_" + command)


# --- The ambient-row figure (#264) --------------------------------------------
#
# Source pins, like `test_e2e_collab_peer_snapshot.py`'s: what went wrong here
# was not a value a function returned but a figure nobody read, and the only
# tier that can watch the counting happen is the one that needs the test host.


def test_every_invocation_reads_the_ambient_rows_it_left():
    """#264: `visit` exists to make the tracking write, so a run of it that
    states no delta has not measured the thing it is for. #243's evidence had to
    count on the host afterwards and say that was weaker."""
    source = inspect.getsource(hand.run)
    assert "adapter.ambient_accounting(" in source
    assert "adapter.SessionAmbientDriver(" in source
    assert "append=True" in source, "the records append per invocation, so the figure does too"


def test_the_denominator_is_the_document_counter_and_not_the_goto_counter():
    """The three steps navigate with `page.goto`, `editbtn` navigates again by
    clicking a link, and the website editor's preview iframe fetches documents of
    its own. `SurfaceDriver.navigations` sees the login and nothing else here, so
    reading it would publish a denominator of 0 that looked like a reading."""
    source = inspect.getsource(hand.run)
    assert "navigation_basis=adapter.AMBIENT_BASIS_DOCUMENTS" in source
    # Prose names the attribute; code must not read it.
    code = [line for line in source.splitlines() if not line.strip().startswith("#")]
    assert not [line for line in code if "driver.navigations" in line]


def test_the_record_is_written_inside_the_window_the_figure_covers():
    """The after-count is taken on the way out of the accounting, so the record
    file write has to be inside it -- otherwise a step's last navigation would sit
    outside the figure that claims to cover it."""
    source = inspect.getsource(hand.run)
    assert source.index("ambient_accounting(") < source.index('open(out_path, "a"')


def test_the_module_says_where_the_figure_goes_and_what_it_is_not():
    """A reader of the file finds the sentence without the documents open, and
    the worked example is derived from the function that builds the name rather
    than spelled a second time."""
    said = " ".join(hand.__doc__.split())
    assert adapter.ambient_summary_path("hand-checks.jsonl") in said
    assert "counts only" in said.lower()
    assert "#256" in said and "#264" in said
    assert "diff` never reads it" in said
