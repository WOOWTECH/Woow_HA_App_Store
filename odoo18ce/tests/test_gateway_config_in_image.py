#!/usr/bin/env python3
"""The in-image gateway probe works, and the Build tier runs it.

`in_image/gateway_config_loads.py` is the only thing that reads the shipped
nginx config with the nginx the add-on ships. It runs in the Build tier, where
a broken probe would pass quietly -- so its logic is proven here, against the
runner's nginx and the repository's files, including both ways it goes red.

The probe's paths are module constants with the in-image values as defaults,
which is what lets this file point them at the repository instead. The Build
tier sets nothing and gets the image's paths.
"""
import importlib.util
from pathlib import Path

import pytest
import yaml

from conftest import require_tool

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests/in_image/gateway_config_loads.py"
TEMPLATE = ROOT / "rootfs/etc/nginx/nginx.conf.template"
CONT_INIT = ROOT / "rootfs/etc/cont-init.d/10-odoo-config.sh"
BUDGET_TEST = ROOT / "tests/test_nginx_parameter_budget.py"
CI_WORKFLOW = ROOT.parent / ".github/workflows/ci.yml"


def load_probe(**overrides):
    """The probe, with its in-image paths pointed at this repository."""
    spec = importlib.util.spec_from_file_location("gateway_config_loads", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.NGINX = require_tool("nginx")
    module.TEMPLATE = TEMPLATE
    module.CONT_INIT = CONT_INIT
    module.BUDGET_TEST = BUDGET_TEST
    for name, value in overrides.items():
        setattr(module, name, value)
    return module


def test_the_probe_passes_against_the_runners_nginx_and_the_repository():
    """Every assertion the probe makes holds here, so a red in CI means the image.

    The Build tier cannot tell a probe that found a real difference from one
    that was simply broken. This is the half that says it is not broken.
    """
    load_probe().main()


def test_the_probe_goes_red_when_the_canonical_url_cap_does_not_fit(tmp_path: Path):
    """A cap cont-init would allow but nginx would refuse has to fail the probe.

    This is the defect the probe exists for, injected: raise the cap without
    checking it against a real nginx and the budget reports headroom that the
    rendered parameter does not have.
    """
    script = tmp_path / "10-odoo-config.sh"
    script.write_text(
        CONT_INIT.read_text(encoding="utf-8").replace(
            "CANONICAL_URL_MAX=2048", "CANONICAL_URL_MAX=40000"
        ),
        encoding="utf-8",
    )
    assert "CANONICAL_URL_MAX=40000" in script.read_text(encoding="utf-8"), (
        "the cap's spelling in cont-init changed; this injection no longer injects anything"
    )
    with pytest.raises(SystemExit) as caught:
        load_probe(CONT_INIT=script).main()
    assert caught.value.code == 1


def test_the_probe_goes_red_when_the_budgets_token_limit_is_not_the_buffer(tmp_path: Path):
    """`TOKEN_LIMIT` larger than the nginx in front of it has to fail the probe.

    This is the other defect: the budget's constant is a measurement of one
    nginx, and the image is free to ship another.
    """
    budget = tmp_path / "test_nginx_parameter_budget.py"
    budget.write_text(
        BUDGET_TEST.read_text(encoding="utf-8").replace(
            "TOKEN_LIMIT = 4096", "TOKEN_LIMIT = 8192"
        ),
        encoding="utf-8",
    )
    assert "TOKEN_LIMIT = 8192" in budget.read_text(encoding="utf-8"), (
        "TOKEN_LIMIT's spelling changed; this injection no longer injects anything"
    )
    with pytest.raises(SystemExit) as caught:
        load_probe(BUDGET_TEST=budget).main()
    assert caught.value.code == 1


def test_the_probe_reads_every_number_from_the_file_that_owns_it():
    """No copy of `TOKEN_LIMIT` or the cap may live in the probe.

    A probe holding its own copy agrees with itself while the add-on
    disagrees, which is the failure both injections above stand in for.
    """
    source = PROBE.read_text(encoding="utf-8")
    assert "TOKEN_LIMIT = (" in source and "CANONICAL_URL_MAX=(" in source, (
        "the probe must read both numbers out of the files that state them"
    )
    for literal in ("4096", "2048"):
        assert literal not in source, (
            f"the probe states {literal} itself instead of reading it; that is the copy "
            "that drifts"
        )


def gateway_step():
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["build-amd64"]
    steps = [step for step in job["steps"] if "gateway_config_loads" in step.get("run", "")]
    assert len(steps) == 1, "build (amd64) needs exactly one step running the gateway probe"
    return job, steps[0]["run"]


def test_the_probe_runs_on_the_build_that_every_pull_request_gets():
    job, _ = gateway_step()
    # The aarch64 build only runs on a version bump. A change to the template
    # or to cont-init is not a version bump, so it would never get there.
    assert "if" not in job, "build (amd64) must stay unconditional"


def test_the_probe_runs_in_the_image_this_pull_request_built():
    _, run = gateway_step()
    assert "woow-ha-odoo-amd64:ci" in run, "the probe must read the image this build produced"
    # The probe imports the shared renderer, so the tests directory is mounted
    # rather than copied into the image.
    assert "/tests:ro" in run, "mount the tests directory read-only; the probe imports from it"
    assert "in_image/gateway_config_loads.py" in run


def test_the_probe_step_cannot_run_forever():
    _, run = gateway_step()
    assert "timeout" in run, "the step must bound the container's run time"


def test_the_probe_step_fails_the_build_when_the_probe_does():
    _, run = gateway_step()
    assert "set -euo pipefail" in run, "the step must stop on the probe's exit status"
    assert "::error::" in run, "the step must say what a red probe means"
