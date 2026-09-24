#!/usr/bin/env python3
"""Contracts for the Canonical URL the Runtime shim publishes (issue #70).

Odoo 18 builds some outbound links in the browser, from the address in the
address bar. Through Ingress that address is the Home Assistant host, so the
link is useless to the person it is sent to, and the lock the maintenance
bootstrap puts on ``web.base.url`` cannot reach it because the value never
passes through the server. The Runtime shim therefore carries the Canonical
URL into the page, as a read-only global, and each Literal rewrite that moves
a browser-built link onto that base is added afterwards, one exact expression
at a time.

Two properties are pinned here:

- **The value.** Rendering the template for each deployment shape must give
  the Public origin, the LAN origin, or an empty string, with no trailing
  slash, and the global must survive an assignment from bundle code.
- **The single rule.** cont-init renders the value and the maintenance
  bootstrap writes it into ``web.base.url``, at two different points of a
  start. Both must reach it through ``canonical_url()`` in the maintenance
  library rather than deriving it separately, or the address the browser is
  told and the address Odoo stores can drift apart.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_ingress_clipboard_fallback import NGX_CONF_BUFFER, directive_lines
from test_ingress_router_rewrite import TEMPLATE, map_block

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "rootfs/usr/local/bin/odoo-canonical-url"
LIB = ROOT / "rootfs/usr/local/lib/odoo-maintenance.py"
BOOTSTRAP = ROOT / "rootfs/usr/local/bin/odoo-maintenance-bootstrap"
CONT_INIT = ROOT / "rootfs/etc/cont-init.d/10-odoo-config.sh"
DOCKERFILE = ROOT / "Dockerfile"

CANONICAL_MAP = "map $upstream_http_content_type $ingress_canonical_url_shim {"
RUNTIME_MAP = "map $upstream_http_content_type $ingress_runtime_shim {"
PLACEHOLDER = "%%CANONICAL_URL%%"
GLOBAL_NAME = "__WOOW_CANONICAL_URL__"

# Documentation addresses only (RFC 5737, RFC 6761); no real host here.
PUBLIC = "https://odoo.example.test"
LAN_ORIGIN = "http://192.0.2.10:8069"
LAN_IPV4 = "192.0.2.10/24"

# The three deployment shapes, as the rendered template sees them.
SHAPES = {
    "public_url set": PUBLIC,
    "Ingress-only with a LAN address": LAN_ORIGIN,
    "Ingress-only without a LAN address": "",
}

HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");

for (const { shape, script, expected } of JSON.parse(process.argv[1])) {
  const window = {};
  vm.runInContext(script, vm.createContext({ window }));
  const value = window.__WOOW_CANONICAL_URL__;
  assert.equal(value, expected, `${shape}: wrong Canonical URL global`);
  assert.equal(typeof value, "string", `${shape}: the global must always be a string`);
  assert.ok(!value.endsWith("/"), `${shape}: the global must carry no trailing slash`);

  // Bundle code must not be able to move the base of an already rewritten
  // link. Assignment to a non-writable property is silent outside strict
  // mode, which is how an asset bundle runs.
  try { window.__WOOW_CANONICAL_URL__ = "https://attacker.example.test"; } catch (error) {}
  assert.equal(window.__WOOW_CANONICAL_URL__, expected, `${shape}: the global must be read-only`);
}
"""


def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def canonical_script(text: str) -> str:
    """The Canonical URL script as declared in its own map, injected for every value."""
    match = re.search(r"default '<script>(.*?)</script>';", map_block(text, CANONICAL_MAP), re.S)
    assert match, "Canonical URL script not found in its map"
    script = match.group(1)
    assert "$" not in script, (
        "the Canonical URL script must not reference nginx variables; the value "
        "arrives as a rendered placeholder so the script is the same on every host"
    )
    return script


def rendered(text: str, value: str) -> str:
    """The script as cont-init renders it for one deployment shape."""
    return canonical_script(text).replace(PLACEHOLDER, value)


# --- the value ----------------------------------------------------------------

def test_the_placeholder_is_rendered_in_exactly_one_place() -> None:
    text = template()
    assert text.count(PLACEHOLDER) == 1, (
        f"{PLACEHOLDER} must appear once, inside {CANONICAL_MAP.strip('{ ')}"
    )
    assert PLACEHOLDER in map_block(text, CANONICAL_MAP)


def test_every_deployment_shape_renders_its_canonical_url() -> None:
    from conftest import require_tool

    cases = [
        {"shape": shape, "script": rendered(template(), value), "expected": value}
        for shape, value in SHAPES.items()
    ]
    result = subprocess.run(
        [require_tool("node"), "-e", HARNESS, json.dumps(cases)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_the_global_is_defined_before_any_bundle_can_read_it() -> None:
    """The script is spliced into the Runtime shim, which nginx injects at `<head>`."""
    text = template()
    runtime_map = map_block(text, RUNTIME_MAP)
    assert "$ingress_canonical_url_shim" in runtime_map, (
        "the Runtime shim map must splice $ingress_canonical_url_shim in by variable reference"
    )
    references = [
        number
        for number, line in directive_lines(text)
        if "$ingress_canonical_url_shim" in line and not line.lstrip().startswith("map ")
    ]
    assert len(references) == 1, (
        "$ingress_canonical_url_shim must be referenced only inside $ingress_runtime_shim, "
        f"found it on lines {references}"
    )
    assert text.count("sub_filter '<head>' '<head>$ingress_runtime_shim';") == 1, (
        "the Runtime shim keeps a single injection point"
    )


def test_the_public_origin_never_receives_the_runtime_shim() -> None:
    """Only the Ingress listener injects the shim, so a Public origin page is unchanged."""
    text = template()
    lines = text.splitlines()
    ingress = next(
        number
        for number, line in enumerate(lines, start=1)
        if "# HA Supervisor Ingress adapter." in line
    )
    stray = [
        number
        for number, line in directive_lines(text)
        if "$ingress_runtime_shim" in line
        and not line.lstrip().startswith("map ")
        and number < ingress
    ]
    assert not stray, (
        "the Runtime shim must not be injected by the 8069 or 8072 listeners; "
        f"found a reference on lines {stray}"
    )


def test_the_canonical_url_map_fits_the_nginx_token_buffer() -> None:
    """Its own map, as the template's comment requires; check it stayed small."""
    size = len(canonical_script(template()).encode("utf-8"))
    assert size < NGX_CONF_BUFFER, (
        f"the Canonical URL script is {size} bytes; nginx rejects a quoted "
        f"parameter of {NGX_CONF_BUFFER} bytes or more"
    )


# --- the single rule ----------------------------------------------------------

def run_cli(public_url: str = "", lan_ipv4: str = "", port: str = "") -> str:
    environment = dict(
        os.environ,
        ODOO_MAINT_PUBLIC_URL=public_url,
        ODOO_MAINT_LAN_IPV4=lan_ipv4,
        ODOO_MAINT_PORT=port,
    )
    result = subprocess.run(
        [sys.executable, str(CLI), str(LIB)],
        text=True, capture_output=True, check=False, env=environment,
    )
    assert result.returncode == 0, (
        f"the CLI must never fail a start; stderr={result.stderr}"
    )
    return result.stdout.strip()


@pytest.mark.parametrize(
    "public_url,lan_ipv4,port,expected",
    [
        (PUBLIC, "", "", PUBLIC),
        (PUBLIC + "/", LAN_IPV4, "8069", PUBLIC),
        ("", LAN_IPV4, "8069", LAN_ORIGIN),
        ("", LAN_IPV4, "18069", "http://192.0.2.10:18069"),
        ("", LAN_IPV4, "", LAN_ORIGIN),
        ("", "", "8069", ""),
        ("", "", "", ""),
    ],
)
def test_the_cli_prints_what_the_shared_rule_decides(
    public_url: str, lan_ipv4: str, port: str, expected: str
) -> None:
    assert run_cli(public_url, lan_ipv4, port) == expected


def test_the_cli_prints_nothing_rather_than_failing_a_start() -> None:
    """A broken library leaves the shim without a value; it never stops the add-on."""
    result = subprocess.run(
        [sys.executable, str(CLI), str(ROOT / "rootfs/usr/local/lib/does-not-exist.py")],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_both_callers_reach_the_rule_through_the_same_function() -> None:
    cli = CLI.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    cont_init = CONT_INIT.read_text(encoding="utf-8")

    assert "canonical_url(" in cli and "odoo-maintenance.py" in cli, (
        "the cont-init caller must call canonical_url() in the maintenance library"
    )
    for name in ("ODOO_MAINT_PUBLIC_URL", "ODOO_MAINT_LAN_IPV4", "ODOO_MAINT_PORT"):
        assert name in cli, f"the CLI must read {name}"
        assert name in bootstrap, f"the bootstrap must still export {name}"
        assert name in cont_init, f"cont-init must pass {name} to the CLI"

    assert "/usr/local/bin/odoo-canonical-url" in cont_init, (
        "cont-init must derive the Canonical URL through the shared CLI"
    )
    # The rule is "public_url, else the LAN address with the published port".
    # Writing that shape again here would be the second derivation the whole
    # arrangement exists to prevent.
    assert "http://${CANONICAL_LAN_IPV4}" not in cont_init, (
        "cont-init must not rebuild the LAN origin; canonical_url() owns that rule"
    )


def test_cont_init_reads_the_supervisor_only_when_public_url_is_unset() -> None:
    cont_init = CONT_INIT.read_text(encoding="utf-8")
    call = "woow::supervisor.settle_canonical_inputs"
    assert call in cont_init, f"cont-init must read the Supervisor through {call} for the LAN fallback"
    guard = cont_init.index('if [ -z "${PUBLIC_URL}" ]; then')
    assert cont_init.index(call) > guard, (
        f"{call} must sit inside the no-public_url branch, as the bootstrap's does"
    )
    assert f's#{PLACEHOLDER}#${{CANONICAL_URL}}#g' in cont_init, (
        "cont-init must render the Canonical URL into the nginx template"
    )


def test_cont_init_settles_both_inputs_with_the_shared_helper_and_never_reads_them_bare() -> None:
    # Issue #108: one read at boot was cached empty by bashio for the life of
    # the container. Both reads now wait through the helper, and what it
    # settled on is what the bootstrap gets — cont-init publishes it, and
    # never calls the bare bashio reads itself.
    cont_init = CONT_INIT.read_text(encoding="utf-8")
    assert 'CANONICAL_LAN_IPV4="${WOOW_LAN_IPV4}"' in cont_init
    assert 'CANONICAL_PORT="${WOOW_LAN_PORT}"' in cont_init
    assert "bashio::network.ipv4_address" not in cont_init
    assert "bashio::addon.port" not in cont_init
    assert "supervisor-read.sh" in cont_init.split("woow::supervisor.settle_canonical_inputs", 1)[0], (
        "the helper is sourced before it is called"
    )


def test_a_value_that_is_not_a_bare_origin_is_dropped_not_escaped() -> None:
    """The value lands in a JS string inside an nginx quoted parameter."""
    cont_init = CONT_INIT.read_text(encoding="utf-8")
    assert "^https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?" in cont_init, (
        "cont-init must check the shape of the value before rendering it"
    )
    assert 'CANONICAL_URL=\'\'' in cont_init, (
        "a value of any other shape must become empty, leaving the browser origin in place"
    )


def test_the_image_makes_the_cli_executable() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "chmod a+rx /usr/local/bin/odoo-canonical-url" in dockerfile, (
        "the Dockerfile must make odoo-canonical-url executable"
    )
