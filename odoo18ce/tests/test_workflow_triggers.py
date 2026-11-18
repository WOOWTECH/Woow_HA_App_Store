#!/usr/bin/env python3
"""Static-tier contract on the two Live-tier workflows' triggers (ADR 0005).

The Perimeter check and the Literal rewrite gate lost their nightly schedule
when the add-on took both jobs inside the container: the start-time
self-check for the perimeter, the Rewrite scan for the Literal rewrite. Both
workflows stay runnable by hand for whenever a Public origin exists again.

The test host that served as the control group was reinstalled for another
purpose (#314; ADR 0003, postscript 2026-10-27), so nothing dispatches the
Perimeter check any more: release.yml used to run it after every Release, and
with no Public origin left each run failed and sent an email.
"""
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github/workflows"
DISPATCH_ONLY = ("perimeter.yml", "literal-rewrite-gate.yml")


def triggers(name: str) -> dict:
    """The `on:` mapping of a workflow file."""
    document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # YAML 1.1 reads the unquoted key `on` as the boolean true, which is how
    # the file is written; accept the quoted spelling too.
    on = document.get(True, document.get("on"))
    assert isinstance(on, dict), f"{name}: expected a mapping of triggers, got {on!r}"
    return on


@pytest.mark.parametrize("name", DISPATCH_ONLY)
def test_the_live_tier_workflows_run_by_hand(name: str) -> None:
    assert "workflow_dispatch" in triggers(name), (
        f"{name}: the Live-tier workflows are dispatch-only, so workflow_dispatch is the way in"
    )


@pytest.mark.parametrize("name", DISPATCH_ONLY)
def test_the_live_tier_workflows_have_no_schedule(name: str) -> None:
    assert "schedule" not in triggers(name), (
        f"{name}: the in-container Rewrite scan and start-time self-check replaced "
        "the nightly run (ADR 0005); dispatch it by hand instead"
    )


def test_a_release_does_not_dispatch_the_perimeter_check() -> None:
    # A text check rather than a walk over the steps: it also catches a
    # dispatch by workflow name ("Perimeter check") or by file.
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "perimeter" not in release.lower(), (
        "release.yml mentions the Perimeter check again; the test host is gone (#314), "
        "so a dispatch after every Release would end in a failing run"
    )
