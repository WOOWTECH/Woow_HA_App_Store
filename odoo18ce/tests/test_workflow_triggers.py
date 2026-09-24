#!/usr/bin/env python3
"""Static-tier contract on the two Live-tier workflows' triggers (ADR 0005).

The Perimeter check and the Literal rewrite gate lost their nightly schedule
when the add-on took both jobs inside the container: the start-time
self-check for the perimeter, the Rewrite scan for the Literal rewrite. The
test host that served as the control group stops, so a scheduled run would
have nothing to run against. Both workflows stay runnable by hand for
whenever a control group exists again, and release.yml still dispatches the
perimeter check after a Release.
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
