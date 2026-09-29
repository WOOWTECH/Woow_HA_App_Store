#!/usr/bin/env python3
"""Contracts for the two `location` writes the web client makes (issue #174).

Under Ingress, **Action menu > Download > PDF** on a posted invoice navigated
the Ingress iframe to ``<HA_BASE>/account/download_invoice_documents/<id>/pdf``
at the Home Assistant root, which answers 404 -- and the invoice form was gone
with it. No ``window.open`` was involved: the item is a plain dict from
``account.move.get_extra_print_items``, and ``ActionMenus.onItemSelected`` runs
``browser.location=item.url`` for an item that carries a ``url`` and no
``action``. That is a whole-frame navigation with a URL that arrives over RPC.

The Runtime shim cannot intercept a write to ``location`` (ADR 0004), and a
Literal rewrite cannot prefix a value that is not in the bundle. So the
*expression* is rewritten instead, and it calls the shim's own URL helper,
which the shim now publishes as ``__WOOW_INGRESS_URL__``. The generic
``ir.actions.act_url`` executor reaches ``location`` the same way through its
``target==="self"`` branch, and the ``home`` client action writes the identical
expression; one rule covers all three sites.

What is pinned here:

- **The global.** The rendered Runtime shim publishes the helper, read-only,
  only when the Ingress prefix is non-empty, and it behaves exactly like the
  ``path()`` the shim's own wrappers use -- because it *is* that function.
- **The rewrites match the bundle.** An unmatched ``sub_filter`` is a silent
  no-op, so each pattern is counted in bytes captured from bundles the control
  group serves, kept under ``fixtures/bundles/``.
- **The rewritten expressions behave.** Each is executed in node against a
  fake ``browser``, with the helper present and absent, and compared with the
  same expression before the rewrite -- so a rule that changes nothing fails.
- **Ingress only.** ``ingress_rule`` refuses a rule found outside the Ingress
  asset location, which would change what the Public origin serves.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from test_ingress_clipboard_fallback import INGRESS_PREFIX, clipboard_shim, directive_lines
from test_ingress_router_rewrite import TEMPLATE, ingress_rule, map_block, runtime_shim

FIXTURES = Path(__file__).resolve().parent / "fixtures/bundles"

GLOBAL_NAME = "__WOOW_INGRESS_URL__"
GLOBAL_MAP = "map $upstream_http_content_type $ingress_url_global_shim {"
RUNTIME_MAP = "map $upstream_http_content_type $ingress_runtime_shim {"

# Documentation addresses only (RFC 2606); no real host here.
HA_ORIGIN = "https://ha.example.test"
INVOICE_PDF = "/account/download_invoice_documents/7/pdf"

# Each rewrite: the fixture it was measured in, how many times the pattern
# occurs there, the exact expression the Ingress asset location rewrites, the
# slice of the fixture that can be executed, and a driver that runs it and
# reports the address the frame was sent to.
WRITES = {
    "Print menu URL item": {
        "fixture": "action_menu_url_item.js",
        "source": "browser.location=item.url",
        "occurrences": 1,
        "slice": ("async onItemSelected(item){", None),
        "driver": (
            "class ActionMenus{\n__SLICE__\n}\n"
            "result=(async()=>{const menu=new ActionMenus();"
            "menu.props={shouldExecuteAction:async()=>true};"
            'await menu.onItemSelected({key:"download_pdf",description:"PDF",'
            'type:"ir.actions.act_url",url:"%s",target:"download"});'
            "return browser.location})();" % INVOICE_PDF
        ),
        "before": INVOICE_PDF,
        "after": INGRESS_PREFIX + INVOICE_PDF,
    },
    "act_url self target": {
        "fixture": "act_url_self_target.js",
        "source": "browser.location.assign(url)",
        "occurrences": 1,
        "slice": ("function _executeActURLAction(action,options){", None),
        "driver": (
            "__SLICE__\n"
            "result=(()=>{_executeActURLAction("
            '{type:"ir.actions.act_url",url:"%s",target:"self"},{});'
            "return browser.location.assigned})();" % INVOICE_PDF
        ),
        "before": INVOICE_PDF,
        "after": INGRESS_PREFIX + INVOICE_PDF,
    },
    # The `home` client action writes the same expression, so the rule rewrites
    # it too. That is the fix for it and not a regression: today it sends the
    # Ingress frame to the Home Assistant root exactly as the print item does.
    "home client action": {
        "fixture": "home_client_action.js",
        "source": "browser.location.assign(url)",
        "occurrences": 1,
        "slice": ("async function home(){", None),
        "driver": (
            "__SLICE__\n"
            "result=(async()=>{await home();return browser.location.assigned})();"
        ),
        "before": "/?debug=1",
        "after": INGRESS_PREFIX + "/?debug=1",
    },
}

# The fake the rewritten expressions run against: `browser` as Odoo's
# `@web/core/browser/browser` exposes it, and the shim's global either
# published or absent.
HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const P = "/api/hassio_ingress/token";
const ORIGIN = "https://ha.example.test";

(async () => {
  for (const { name, scenario, program, expected } of JSON.parse(process.argv[1])) {
    const browser = {
      location: {
        assigned: undefined,
        search: "?debug=1",
        href: ORIGIN + P + "/odoo/action-2/7",
        assign(value) { this.assigned = value; },
      },
      open() { throw new Error(name + ": browser.open must not be reached"); },
      setTimeout(fn) { return fn(); },
    };
    const context = {
      browser,
      location: { href: ORIGIN + P + "/odoo/action-2/7", origin: ORIGIN },
      registry: { category() { return { add() {} }; } },
      rpc() { return Promise.resolve({}); },
      URL,
      result: undefined,
    };
    context.window = context;
    if (scenario.helper) vm.runInContext(scenario.helper, vm.createContext(context));
    else vm.createContext(context);
    vm.runInContext(program, context);
    const value = await context.result;
    assert.equal(value, expected, `${name} (${scenario.label})`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""

# The shim's own path(), lifted out of the rendered prefix script, standing in
# for the global the shim publishes. `test_the_runtime_shim_publishes_the_url_helper`
# proves the shim publishes that same function.
HELPER = 'var P="%s";window.%s=function(u){%%s};' % (INGRESS_PREFIX, GLOBAL_NAME)

# Enough of a DOM for the whole Runtime shim to run, the way the media-source
# and clipboard contracts build one: the shim as the page gets it, not an
# excerpt of it.
SHIM_HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { shim, emptyShim } = JSON.parse(process.argv[1]);
const P = "/api/hassio_ingress/token";
const ORIGIN = "http://ha.example:8123";
const PDF = "/account/download_invoice_documents/7/pdf";

function run(script) {
  function Element() {}
  Element.prototype.setAttribute = function () {};
  Element.prototype.setAttributeNS = function () {};
  function XMLHttpRequest() {}
  XMLHttpRequest.prototype.open = function () {};
  function History() {}
  History.prototype.pushState = function () {};
  History.prototype.replaceState = function () {};
  function WebSocket() {}
  const fetched = [];
  const context = {
    document: { body: {}, documentElement: {}, activeElement: null },
    navigator: { serviceWorker: undefined },
    location: { href: ORIGIN + P + "/odoo/action-2/7", origin: ORIGIN, host: "ha.example:8123" },
    sessionStorage: { getItem() { return null; }, setItem() {} },
    fetch(input) { fetched.push(input); return Promise.resolve(); },
    open() {},
    XMLHttpRequest,
    History,
    Element,
    WebSocket,
    URL,
    Request: function () {},
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(script, context, { filename: "ingress-runtime-shim.js" });
  return { context, fetched };
}

// Under Ingress the helper is published, and it is a function.
const { context, fetched } = run(shim);
const url = context.__WOOW_INGRESS_URL__;
assert.equal(typeof url, "function", "the Runtime shim must publish __WOOW_INGRESS_URL__");

// path()'s rules, every one of them.
assert.equal(url(PDF), P + PDF, "a root-relative URL gets the prefix");
assert.equal(url(P + PDF), P + PDF, "an already prefixed URL is unchanged");
assert.equal(url(P + P + PDF), P + PDF, "a double prefix is never produced");
assert.equal(url(ORIGIN + P + PDF), P + PDF, "an absolute same-origin URL keeps one prefix");
assert.equal(url(ORIGIN + PDF), P + PDF, "an absolute same-origin URL gets the prefix");
assert.equal(url("https://other.example/x"), "https://other.example/x", "cross-origin is unchanged");
assert.equal(url("blob:" + ORIGIN + "/9f1c"), "blob:" + ORIGIN + "/9f1c", "blob: is unchanged");
assert.equal(url("data:text/plain,x"), "data:text/plain,x", "data: is unchanged");
assert.equal(url("#anchor"), "#anchor", "a fragment-only value is unchanged");
for (const value of [null, undefined, 7, false]) {
  assert.equal(url(value), value, "a non-string is returned as it came");
}
const object = { toString() { return PDF; } };
assert.equal(url(object), object, "a non-string is not stringified");

// It is the same helper the shim's own wrappers use, not a copy of it.
context.fetch(PDF);
assert.deepEqual(fetched, [P + PDF], "fetch must prefix through the same helper");
assert.equal(url(PDF), fetched[0]);

// Read-only: a bundle cannot replace the helper a rewritten expression calls.
// Assignment to a non-writable property is silent outside strict mode, which
// is how an asset bundle runs.
try { context.__WOOW_INGRESS_URL__ = function (u) { return "https://attacker.example.test"; }; } catch (error) {}
assert.equal(context.__WOOW_INGRESS_URL__, url, "the global must be read-only");
try { delete context.__WOOW_INGRESS_URL__; } catch (error) {}
assert.equal(context.__WOOW_INGRESS_URL__, url, "the global must be non-configurable");

// With no Ingress prefix the shim returns before publishing anything, so the
// global does not exist -- and every rewritten expression falls back.
const empty = run(emptyShim).context;
assert.equal(empty.__WOOW_INGRESS_URL__, undefined, "no prefix, no global");
"""


def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def fixture(write: dict) -> str:
    return (FIXTURES / write["fixture"]).read_text(encoding="utf-8")


def runnable(text: str, write: dict) -> str:
    """The part of the fixture that can be executed, from its anchor on."""
    start, end = write["slice"]
    first = text.index(start)
    return text[first :] if end is None else text[first : text.index(end, first)]


def program(write: dict, text: str) -> str:
    return write["driver"].replace("__SLICE__", runnable(text, write))


def rewritten(write: dict) -> str:
    """The fixture as the Ingress asset location serves it."""
    replacement = ingress_rule(template(), write["source"], write["fixture"])
    assert GLOBAL_NAME in replacement, (
        "the rewrite must prefix through the helper the Runtime shim publishes"
    )
    return fixture(write).replace(write["source"], replacement)


def helper() -> str:
    """The shim's own path(), as the stand-in for the global it publishes."""
    shim = runtime_shim(template()).replace("$safe_ingress_path", INGRESS_PREFIX)
    body = re.search(r"var path=function\(u\)\{(.*?)\};var F=", shim)
    assert body, "the Runtime shim's path() helper was not found"
    return HELPER % body.group(1)


def run(cases: list[dict]) -> None:
    from conftest import require_tool

    result = subprocess.run(
        [require_tool("node"), "-e", HARNESS, json.dumps(cases)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def scenario(label: str, with_helper: bool) -> dict:
    return {"label": label, "helper": helper() if with_helper else ""}


# --- the global the Runtime shim publishes ------------------------------------

def rendered_shim(prefix: str) -> str:
    text = template()
    return "\n".join(
        script.replace("$safe_ingress_path", prefix).replace("%%INGRESS_CACHE_VERSION%%", "V")
        for script in (clipboard_shim(text), runtime_shim(text))
    )


def test_the_runtime_shim_publishes_the_url_helper() -> None:
    from conftest import require_tool

    payload = {"shim": rendered_shim(INGRESS_PREFIX), "emptyShim": rendered_shim("")}
    result = subprocess.run(
        [require_tool("node"), "-e", SHIM_HARNESS, json.dumps(payload)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_the_published_helper_is_the_shims_own_path() -> None:
    """One URL helper, published rather than copied (ADR 0004)."""
    text = template()
    shim = runtime_shim(text)
    assert shim.count("var path=function(u)") == 1, "there must be exactly one URL helper"
    assert "value:path" in map_block(text, GLOBAL_MAP), (
        "the global must carry the shim's own path(), not a second helper built beside it"
    )
    assert shim.count(GLOBAL_NAME) == 2, (
        f"{GLOBAL_NAME} is published once, by defineProperty with one fallback assignment"
    )


def test_the_helper_is_spliced_into_the_runtime_shim_and_nowhere_else() -> None:
    text = template()
    assert "$ingress_url_global_shim" in map_block(text, RUNTIME_MAP), (
        "the Runtime shim map must splice $ingress_url_global_shim in by variable reference"
    )
    references = [
        number
        for number, line in directive_lines(text)
        if "$ingress_url_global_shim" in line and not line.lstrip().startswith("map ")
    ]
    assert len(references) == 1, (
        "$ingress_url_global_shim must be referenced only inside $ingress_runtime_shim, "
        f"found it on lines {references}"
    )


# --- the rewrites -------------------------------------------------------------

@pytest.mark.parametrize("name", WRITES)
def test_the_rewrite_matches_the_bundle_the_expected_number_of_times(name: str) -> None:
    """A pattern that does not match is a silent no-op, so measure it."""
    write = WRITES[name]
    text = fixture(write)
    found = text.count(write["source"])
    assert found == write["occurrences"], (
        f"{name}: {write['fixture']} holds {found} occurrences of {write['source']!r}, "
        f"expected {write['occurrences']}; re-capture the fixture and re-measure the rewrite"
    )


@pytest.mark.parametrize("name", WRITES)
def test_every_rewrite_is_ingress_only(name: str) -> None:
    """A rule on the 8069 listener would change what the Public origin serves."""
    ingress_rule(template(), WRITES[name]["source"], name)


def test_one_rule_covers_both_assign_sites() -> None:
    """`ingress_rule` allows exactly one rule per expression, and both sites share one."""
    shared = [name for name, write in WRITES.items() if write["source"] == "browser.location.assign(url)"]
    assert sorted(shared) == ["act_url self target", "home client action"]
    replacements = {ingress_rule(template(), WRITES[name]["source"], name) for name in shared}
    assert len(replacements) == 1, "both sites must be served by the same single rule"


@pytest.mark.parametrize("name", WRITES)
def test_the_frame_leaves_for_the_home_assistant_root_without_the_rewrite(name: str) -> None:
    """The starting point: the bundle as Odoo ships it, run under Ingress."""
    write = WRITES[name]
    run([{
        "name": name,
        "scenario": scenario("as Odoo ships it", with_helper=True),
        "program": program(write, fixture(write)),
        "expected": write["before"],
    }])


@pytest.mark.parametrize("name", WRITES)
def test_the_rewrite_keeps_the_navigation_under_the_ingress_prefix(name: str) -> None:
    write = WRITES[name]
    assert write["after"].startswith(INGRESS_PREFIX), "the navigation must stay under the prefix"
    run([{
        "name": name,
        "scenario": scenario("under Ingress", with_helper=True),
        "program": program(write, rewritten(write)),
        "expected": write["after"],
    }])


@pytest.mark.parametrize("name", WRITES)
def test_without_the_global_the_rewrite_navigates_to_the_raw_value(name: str) -> None:
    """An Ingress page whose shim did not run must still navigate, not throw."""
    write = WRITES[name]
    run([{
        "name": name,
        "scenario": scenario("with no Runtime shim", with_helper=False),
        "program": program(write, rewritten(write)),
        "expected": write["before"],
    }])


@pytest.mark.parametrize("name", WRITES)
def test_an_already_prefixed_or_external_url_is_left_alone(name: str) -> None:
    """The rewrite prefixes through path(), so path()'s rules hold at the call site."""
    write = WRITES[name]
    if write["fixture"] == "home_client_action.js":
        pytest.skip("the home action builds its own URL; there is no value to pass it")
    cases = []
    for label, url, expected in (
        ("already prefixed", INGRESS_PREFIX + INVOICE_PDF, INGRESS_PREFIX + INVOICE_PDF),
        ("cross-origin", "https://other.example/x", "https://other.example/x"),
    ):
        cases.append({
            "name": f"{name}: {label}",
            "scenario": scenario(label, with_helper=True),
            "program": program(write, rewritten(write)).replace(INVOICE_PDF, url),
            "expected": expected,
        })
    run(cases)
