#!/usr/bin/env python3
"""Contracts for the readonly html field's two render paths (issue #237).

ADR 0004's postscript named the readonly ``HtmlViewer`` as one of the markup
sites #210 left open, and as the only one that "reaches markup twice over".
Under Ingress every readonly html field rendered its record's stored markup
with root-relative URLs untouched, so the browser resolved them against the
Home Assistant root and got 404 -- the pictures and linked documents missing
on the far more common of the two paths, because a field is readonly on every
form the user cannot edit, on every record a portal shows (``project.webclient``,
the project-sharing client, carries the same bytes) and in the html field's
history dialog, which mounts the same component.

Nothing is stored wrong: a viewer has no save. This is a render escape, which
is why there is no ``OUT`` half here and why the issue carries
``severity: important`` where its siblings do not.

What is pinned here:

- **One more global.** ``__WOOW_INGRESS_MARKUP_IN_VALUE__`` is #210's ``IN``
  for a value that may be an OWL ``Markup`` object rather than a string. Every
  html field holds its value as ``markup(...)`` -- the relational model wraps
  an ``html`` field that way (``web/static/src/model/relational_model/utils.js``)
  -- and ``IN`` returns a non-string as it came, so calling ``IN`` at either
  site would have been a silent no-op. A test below executes exactly that
  no-op, so the reason this helper exists cannot be read as decoration.
- **Why it rebuilds the wrapper instead of returning a string.** OWL's
  ``safeOutput`` inserts a ``Markup`` as HTML and *escapes* everything else, so
  handing ``t-out`` a prefixed plain string would display the markup as text
  -- a worse bug than the 404. The helper puts the wrapper back through the
  value's own constructor, which is OWL's own ``class Markup extends String``.
- **Both insertions**, with the globals present and absent: the ``t-out`` of
  the plain path and ``iframeTarget.innerHTML`` of the iframe path, the latter
  with ``hasFullHtml`` set (``documentElement``) and with only ``cssAssetId``
  set (``#iframe_target``).
- **The template rewrite is a rewrite of a template**, so it is held to two
  things a JavaScript rewrite is not: the result must still parse as XML, and
  its fallback must be an **arrow** function. OWL compiles a template
  expression by rewriting every symbol it does not know into a ``ctx[...]``
  lookup, and a ``function``'s parameter is not exempt -- the
  ``function(h){return h}`` idiom the five #210 rules use compiles to
  ``function(ctx['h']){return ctx['h']}``, a syntax error in the compiled
  template. An arrow's parameter is tracked as a local, and ``window`` is one
  of OWL's reserved words. Verified against the ``owl.js`` the pinned deb
  ships; the test keeps the shape.
- **The counts.** An unmatched ``sub_filter`` is a silent no-op, so each
  pattern is counted in bytes derived from the pinned package through Odoo's
  own serve path, kept under ``fixtures/bundles/`` -- including the template,
  which the xml bundle appends to the JavaScript unminified and lxml
  re-serialises on the way, which is why neither the file's double space nor
  its space before ``/>`` is in the pattern.
- **Ingress only**, and no ``OUT``: ``ingress_rule`` refuses a rule found
  outside the Ingress asset location, and a readonly field has nothing to
  strip on the way back.
"""
import json
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from test_ingress_clipboard_fallback import INGRESS_PREFIX, directive_lines
from test_ingress_router_rewrite import TEMPLATE, ingress_rule, map_block
from test_ingress_todo_description import (
    HA_ORIGIN,
    HARNESS,
    SHIM_CONTEXT,
    TODO_PICTURES,
    node,
    rendered_shim,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures/bundles"

MARKUP_MAP = "map $upstream_http_content_type $ingress_markup_global_shim {"
IN_GLOBAL = "__WOOW_INGRESS_MARKUP_IN__"
IN_VALUE_GLOBAL = "__WOOW_INGRESS_MARKUP_IN_VALUE__"
OUT_GLOBAL = "__WOOW_INGRESS_MARKUP_OUT__"

# The div the plain path renders, as the xml bundle serves it -- lxml's
# re-serialisation of html_viewer.xml and not the file, which has two spaces
# after the `t-ref` and a space before the slash. The whole div is the anchor
# because `t-out="state.value"` on its own also occurs in
# `web.MonetaryField`'s ghost value, in the same bundle.
READONLY_DIV = '<div t-ref="readonlyContent" class="o_readonly" t-out="state.value"/>'

REWRITES = {
    "iframe": {
        "fixture": "html_viewer_iframe_content.js",
        "source": "iframeTarget.innerHTML=content;",
        "occurrences": 1,
        "global": IN_VALUE_GLOBAL,
    },
    "plain": {
        "fixture": "html_viewer_readonly_template.js",
        "source": READONLY_DIV,
        "occurrences": 1,
        "global": IN_VALUE_GLOBAL,
    },
}

# A readonly to-do description, as `todo_user_onboarding` writes it: the same
# two pictures #210 chased on the editable path.
STORED = (
    '<h1>Hey Administrator</h1>'
    '<img class="img-fluid d-none d-sm-block" src="%s" alt="todo-access"/>'
    '<p>Using the editor</p>'
    '<img class="img-fluid d-none d-sm-block" src="%s" alt="convert-todo"/>'
) % TODO_PICTURES

# OWL's Markup, as owl.js declares it: `class Markup extends String {}`. The
# field value the viewer renders is one of these, so every driver below builds
# its value through this class and reports whether it got one back -- a plain
# string here would mean OWL escapes the markup instead of inserting it.
#
# It is declared with `var` so that running this text inside a vm context puts
# the class on that context's global, and every harness below runs it in the
# *same* context as the shim. That is not a convenience: `instanceof String` is
# realm-scoped, and in a browser a page's OWL and that page's Runtime shim
# share one realm, so a test that built the value in the outer realm would be
# asking the helper a question no page asks.
MARKUP_CLASS = """
var Markup = class Markup extends String {};
function value(raw, asMarkup) { return asMarkup ? new Markup(raw) : raw; }
// What OWL's safeOutput() does with the value a `t-out` produces: a Markup is
// inserted as HTML, anything else becomes text.
function insertedAsHtml(result) { return result instanceof Markup; }
function requestedBy(html, page) {
  const requested = [];
  for (const match of String(html).matchAll(/src="([^"]*)"/g)) {
    requested.push(new URL(match[1], page).href);
  }
  return requested;
}
"""

# The iframe path. `updateIframeContent` picks its target from
# `hasFullHtml` -- the whole document on that path, the `#iframe_target` div on
# the `cssAssetId` one -- and the fake target resolves every src the way a
# browser resolves one against the page, which is what the iframe does: it is
# `about:blank` and inherits the page's base URL.
IFRAME_DRIVER = r"""
__MARKUP_CLASS__
const requested = [];
let written = null;
const target = (name) => ({
  set innerHTML(html) {
    written = name;
    requested.push(...requestedBy(html, PAGE));
  },
});
const documentElement = target("documentElement");
const iframeTarget = target("#iframe_target");
class HtmlViewer {
  constructor(config, state) {
    this.props = { config };
    this.state = state;
    this.iframeRef = {
      el: {
        contentWindow: {
          document: {
            documentElement,
            querySelector: (selector) =>
              selector === "#iframe_target" ? iframeTarget : null,
          },
        },
      },
    };
  }
  processReadonlyContent() {}
__SLICE__
}
const viewer = new HtmlViewer(__CONFIG__, { value: value(__RAW__, __AS_MARKUP__) });
viewer.updateIframeContent(viewer.state.value);
result = [written, requested];
"""

# The plain path: the `t-out` expression exactly as the rewritten template
# carries it, evaluated against a `state` the way the compiled template
# evaluates `ctx['state']`.
PLAIN_DRIVER = r"""
__MARKUP_CLASS__
const state = { value: value(__RAW__, __AS_MARKUP__) };
const rendered = __EXPRESSION__;
result = [
  insertedAsHtml(rendered),
  insertedAsHtml(rendered) ? requestedBy(rendered, PAGE) : [],
  String(rendered),
];
"""

# Everything the third global promises, executed against the rendered shim.
GLOBALS_HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { shim, emptyShim } = JSON.parse(process.argv[1]);
const P = "/api/hassio_ingress/token";
const ORIGIN = "http://ha.example:8123";
const PAGE = ORIGIN + P + "/odoo/action-454/5";
const PICTURE = "__PICTURE__";
const MARKUP_SOURCE = __MARKUP_SOURCE__;
__SHIM_CONTEXT__

function run(script) {
  const context = shimContext();
  // The page's OWL and the page's shim are one realm, so build the Markup
  // class in the same context the shim runs in.
  vm.runInContext(MARKUP_SOURCE, context);
  vm.runInContext(script, context, { filename: "ingress-runtime-shim.js" });
  return context;
}

const context = run(shim);
const Markup = context.Markup;
const markupIn = context.__WOOW_INGRESS_MARKUP_IN__;
const markupInValue = context.__WOOW_INGRESS_MARKUP_IN_VALUE__;
assert.equal(typeof markupInValue, "function",
  "the shim must publish __WOOW_INGRESS_MARKUP_IN_VALUE__");

const stored = '<h1>Hey</h1><img src="' + PICTURE + '" alt="todo-access"/>';
const prefixed = '<h1>Hey</h1><img src="' + P + PICTURE + '" alt="todo-access"/>';

// The reason this helper exists: #210's IN tests `typeof h === "string"`, and
// the value a readonly html field renders is an OWL Markup *object*, so IN is
// a no-op on it. Executed rather than asserted in prose.
const asMarkup = new Markup(stored);
assert.equal(markupIn(asMarkup), asMarkup, "IN returns a non-string as it came");
assert.equal(String(markupIn(asMarkup)), stored, "...so IN alone prefixes nothing here");

// A Markup in, a Markup out: same constructor, prefixed content. OWL's
// safeOutput inserts a value as HTML only if it `instanceof Markup`, so losing
// the wrapper would display the record's markup as text.
const wrapped = markupInValue(asMarkup);
assert.ok(wrapped instanceof Markup, "a Markup value must come back a Markup");
assert.equal(wrapped.constructor, Markup, "rebuilt through the value's own constructor");
assert.equal(String(wrapped), prefixed, "and its markup must carry the prefix");
assert.notEqual(wrapped, asMarkup, "the original is not mutated: String is immutable");
assert.equal(String(asMarkup), stored, "the state the component holds keeps the record's bytes");

// A primitive string is markup too -- that is what the iframe path assigns to
// innerHTML -- and it comes back a primitive, prefixed exactly as IN does it.
// One helper, not a second implementation.
const asString = markupInValue(stored);
assert.equal(typeof asString, "string", "a string value must come back a string");
assert.equal(asString, prefixed);
assert.equal(asString, markupIn(stored), "the prefixing must be IN's own, not a copy");

// Idempotent, because a viewer re-renders: onWillUpdateProps calls the same
// insertion again with the same state.
assert.equal(String(markupInValue(markupInValue(asMarkup))), prefixed,
  "no value may be prefixed twice");
assert.equal(markupInValue(markupInValue(stored)), prefixed);

// Everything that is neither comes back as it came. An empty html field is
// `false`, and `innerHTML = false` writes the word "false" -- so the helper
// must not turn one into a string on its way through.
for (const untouched of [null, undefined, false, 0, 7, true]) {
  assert.equal(markupInValue(untouched), untouched,
    "a non-string, non-Markup value is returned as it came: " + String(untouched));
}
// An object that is not a String object is not markup either.
const object = { toString() { return stored; } };
assert.equal(markupInValue(object), object);

// Read-only: a bundle cannot replace a helper a rewritten expression calls.
try { context.__WOOW_INGRESS_MARKUP_IN_VALUE__ = function () { return "owned"; }; }
catch (error) {}
assert.equal(context.__WOOW_INGRESS_MARKUP_IN_VALUE__, markupInValue,
  "__WOOW_INGRESS_MARKUP_IN_VALUE__ must be read-only");
try { delete context.__WOOW_INGRESS_MARKUP_IN_VALUE__; } catch (error) {}
assert.equal(context.__WOOW_INGRESS_MARKUP_IN_VALUE__, markupInValue,
  "__WOOW_INGRESS_MARKUP_IN_VALUE__ must be non-configurable");

// With no Ingress prefix the shim returns before publishing anything.
assert.equal(run(emptyShim).__WOOW_INGRESS_MARKUP_IN_VALUE__, undefined,
  "no prefix, no global");
""".replace("__SHIM_CONTEXT__", SHIM_CONTEXT).replace(
    "__MARKUP_SOURCE__", json.dumps(MARKUP_CLASS)
).replace("__PICTURE__", TODO_PICTURES[0])

def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def fixture(name: str) -> str:
    return (FIXTURES / REWRITES[name]["fixture"]).read_text(encoding="utf-8")


def rewritten(name: str) -> str:
    """The fixture as the Ingress asset location serves it."""
    rewrite = REWRITES[name]
    replacement = ingress_rule(template(), rewrite["source"], rewrite["fixture"])
    assert rewrite["global"] in replacement, (
        f"the {name} rewrite must go through {rewrite['global']}, the helper the shim publishes"
    )
    return fixture(name).replace(rewrite["source"], replacement)


def registered_template(text: str) -> str:
    """The third argument of ``registerTemplate(...)``: the template itself.

    The bundle writes it as a template literal, so the backticks delimit it and
    the escaping Odoo applies (``\\``, a backtick, ``${``) means an inner one
    cannot be mistaken for the end.
    """
    parts = text.split("`")
    assert len(parts) == 5, "the fixture must be one registerTemplate(name, `url`, `template`);"
    return parts[3]


def readonly_expression(text: str) -> str:
    """The ``t-out`` of the readonly div, parsed out of the template as XML."""
    root = ElementTree.fromstring(registered_template(text))
    divs = root.findall('.//div[@t-ref="readonlyContent"]')
    assert len(divs) == 1, "the template must hold one readonly div"
    return divs[0].get("t-out")


def iframe_program(text: str, config: dict, raw: str, as_markup: bool = True) -> str:
    """The fixture's ``updateIframeContent``, driven with one stored value."""
    body = text[text.index("updateIframeContent(content){"):].rstrip()
    return (
        IFRAME_DRIVER.replace("__MARKUP_CLASS__", MARKUP_CLASS)
        .replace("__SLICE__", body)
        .replace("__CONFIG__", json.dumps(config))
        .replace("__RAW__", json.dumps(raw))
        .replace("__AS_MARKUP__", "true" if as_markup else "false")
    )


def plain_program(text: str, raw: str, as_markup: bool = True) -> str:
    """The template's ``t-out`` expression, driven with one stored value."""
    return (
        PLAIN_DRIVER.replace("__MARKUP_CLASS__", MARKUP_CLASS)
        .replace("__EXPRESSION__", readonly_expression(text))
        .replace("__RAW__", json.dumps(raw))
        .replace("__AS_MARKUP__", "true" if as_markup else "false")
    )


def under_prefix(*pictures: str) -> list:
    return [HA_ORIGIN + INGRESS_PREFIX + picture for picture in pictures or TODO_PICTURES]


def at_the_ha_root(*pictures: str) -> list:
    return [HA_ORIGIN + picture for picture in pictures or TODO_PICTURES]


# --- the global the Runtime shim publishes ------------------------------------

def test_the_runtime_shim_publishes_the_markup_value_helper() -> None:
    node(GLOBALS_HARNESS, {"shim": rendered_shim(INGRESS_PREFIX), "emptyShim": rendered_shim("")})


def test_the_value_helper_is_in_terms_of_the_markup_helper_beside_it() -> None:
    """One prefixing implementation, as ADR 0004's one-URL-helper rule has it."""
    markup_map = map_block(template(), MARKUP_MAP)
    for published in (IN_GLOBAL, IN_VALUE_GLOBAL, OUT_GLOBAL):
        assert 'mP("%s"' % published in markup_map, (
            f"{published} must be published by the same map, beside the other two: this helper "
            "is the IN of the pair for a value that is not a string, not a second mechanism"
        )
    definition = markup_map[markup_map.index("mIV=function(v){"):]
    definition = definition[: definition.index("},")]
    assert "mIn(" in definition, (
        "__WOOW_INGRESS_MARKUP_IN_VALUE__ must prefix by calling the IN helper beside it, "
        "not by a second attribute walk of its own"
    )
    assert "path(" not in definition, (
        "...and it must not reach for path() directly either: IN owns which attributes are URLs"
    )
    assert markup_map.count("mT=/") == 1, "there must be exactly one start-tag pattern"


def test_the_value_helper_touches_no_dom() -> None:
    """ADR 0004's Group B stays uncovered: still three string functions."""
    markup_map = map_block(template(), MARKUP_MAP)
    for hook in (
        "innerHTML", "outerHTML", "insertAdjacentHTML", "defineProperty(Element",
        "setAttribute", "querySelectorAll", "childNodes", "adoptNode", "cloneNode",
    ):
        assert hook not in markup_map, (
            f"the markup helpers must not touch {hook}: a hook on markup insertion writes the "
            "Ingress prefix into the database, which is why ADR 0004 leaves Group B uncovered"
        )


# --- the rewrites -------------------------------------------------------------

@pytest.mark.parametrize("name", REWRITES)
def test_the_rewrite_matches_the_bundle_the_expected_number_of_times(name: str) -> None:
    """A pattern that does not match is a silent no-op, so measure it."""
    rewrite = REWRITES[name]
    found = fixture(name).count(rewrite["source"])
    assert found == rewrite["occurrences"], (
        f"{name}: {rewrite['fixture']} holds {found} occurrences of {rewrite['source']!r}, "
        f"expected {rewrite['occurrences']}; re-derive the fixture and re-measure the rewrite"
    )


@pytest.mark.parametrize("name", REWRITES)
def test_every_rewrite_is_ingress_only(name: str) -> None:
    """A rule on the 8069 listener would change what the Public origin serves."""
    ingress_rule(template(), REWRITES[name]["source"], name)


@pytest.mark.parametrize("name", REWRITES)
def test_no_rewrite_strips_on_a_path_that_never_stores(name: str) -> None:
    """A viewer has no save, so an `OUT` here would be a claim about nothing.

    What carries that is where the prefix goes on: *as the value is inserted*,
    on a new value the helper returns, so ``state.value`` and the revision the
    history dialog memoised still hold the record's own bytes --
    ``test_the_runtime_shim_publishes_the_markup_value_helper`` asserts exactly
    that about the original it was handed.

    Stated precisely, because the obvious reassurance is false: the dialog's
    "Restore history" does **not** reach ``HtmlField.updateValue``, so #210's
    ``OUT`` is not standing behind it. The only implementation of
    ``restoreRequested`` (``project_task_form_controller.js``) hands
    ``record.update()`` the memoised ORM revision directly. It is clean because
    nothing the viewer rendered is in that path.
    """
    replacement = ingress_rule(template(), REWRITES[name]["source"], name)
    assert OUT_GLOBAL not in replacement, (
        f"{name}: the readonly viewer stores nothing, so there is nothing to strip; "
        "a strip here would only say the opposite"
    )


def test_the_rewrites_name_nothing_route_scoped() -> None:
    """Still the render site and not the response the editor also saves through."""
    text = template()
    for forbidden in ("/web/dataset/call_kw", "project.task", "web_read"):
        offenders = [number for number, line in directive_lines(text) if forbidden in line]
        assert not offenders, (
            f"no directive may name {forbidden!r} (found on lines {offenders}): rewriting the "
            "response the HTML editor also saves through is what ADR 0004 decided against"
        )


# --- the template rewrite, which has to stay a template -----------------------

def test_the_rewritten_template_is_still_well_formed_xml() -> None:
    """OWL parses the template; a broken attribute would take the component out."""
    expression = readonly_expression(rewritten("plain"))
    assert IN_VALUE_GLOBAL in expression, "the readonly div must render through the helper"
    assert "state.value" in expression, "...on the value the component holds"
    # The rest of the template is untouched, sandbox attribute and all.
    before = registered_template(fixture("plain"))
    after = registered_template(rewritten("plain"))
    assert before.replace(READONLY_DIV, "") == after.replace(
        ingress_rule(template(), READONLY_DIV, "plain"), ""
    ), "the rewrite must change the readonly div and nothing else in the template"
    assert 'sandbox="allow-same-origin' not in after, "the sandbox stays Odoo's t-att-sandbox"


def test_the_rewritten_template_stays_a_javascript_template_literal() -> None:
    """The bundle serves the template inside backticks, so three bytes are out."""
    replacement = ingress_rule(template(), READONLY_DIV, "plain")
    for forbidden in ("`", "${", "\\"):
        assert forbidden not in replacement, (
            f"the template rewrite may not carry {forbidden!r}: the bundle writes the template "
            "as a template literal, and Odoo escapes those three on the way in -- a rewrite that "
            "introduces one is not escaped and ends the literal"
        )
    expression = readonly_expression(rewritten("plain"))
    for forbidden in ('"', "'"):
        assert forbidden not in expression, (
            "the expression is the value of a double-quoted XML attribute written inside that "
            f"literal, so it may not carry {forbidden!r} either"
        )


def test_the_template_fallback_is_an_arrow_and_not_a_function() -> None:
    """OWL rewrites a template expression's unknown symbols into ctx lookups.

    A ``function``'s parameter is not exempt, so the idiom the five #210 rules
    use -- ``(window.X||function(h){return h})(v)`` -- compiles to
    ``function(ctx['h']){return ctx['h']}`` and the whole template throws at
    compile time. An arrow's parameter is tracked as a local and survives;
    ``window`` is in OWL's reserved words, so the lookup does too. Checked
    against the ``owl.js`` the pinned deb ships.
    """
    expression = readonly_expression(rewritten("plain"))
    assert "function" not in expression, (
        "a function literal in an OWL template expression has its parameter rewritten into a "
        "ctx lookup; use an arrow"
    )
    assert "=>" in expression, "the fallback must be an arrow function"
    assert expression.startswith("(window."), (
        "the expression must read the helper off window, which OWL leaves alone, and fall back "
        "to the value when the shim did not run"
    )


# --- the plain path -----------------------------------------------------------

def test_the_plain_path_renders_from_the_home_assistant_root_without_the_rewrite() -> None:
    """The starting point: the template as Odoo ships it, under Ingress."""
    node(HARNESS, [{
        "name": "plain path, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": plain_program(fixture("plain"), STORED),
        "expected": [True, at_the_ha_root(), STORED],
    }])


def test_the_rewrite_renders_the_plain_path_under_the_ingress_prefix() -> None:
    """And it is still a Markup, so OWL inserts it as HTML rather than text."""
    prefixed = STORED.replace('src="/', 'src="%s/' % INGRESS_PREFIX)
    node(HARNESS, [{
        "name": "plain path, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": plain_program(rewritten("plain"), STORED),
        "expected": [True, under_prefix(), prefixed],
    }])


def test_without_the_globals_the_plain_path_renders_the_raw_value() -> None:
    """An Ingress page whose shim did not run must still render, not throw."""
    node(HARNESS, [{
        "name": "plain path, with no Runtime shim",
        "shim": "",
        "program": plain_program(rewritten("plain"), STORED),
        "expected": [True, at_the_ha_root(), STORED],
    }])


def test_a_string_value_on_the_plain_path_is_escaped_either_way() -> None:
    """The one value shape the rewrite reaches that `t-out` does not insert.

    No shipped caller passes one -- an html field's value is ``markup(...)``
    and the history dialog wraps its revision the same way -- but the helper
    prefixes a primitive string, because the iframe path assigns one to
    ``innerHTML`` where it *is* markup. On this path OWL would escape it and
    show the prefix as text; recorded as the stated cost rather than left to be
    discovered.
    """
    node(HARNESS, [{
        "name": "plain path, a primitive string value",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": plain_program(rewritten("plain"), STORED, as_markup=False),
        "expected": [False, [], STORED.replace('src="/', 'src="%s/' % INGRESS_PREFIX)],
    }])


# --- the iframe path ----------------------------------------------------------

FULL_HTML = {"hasFullHtml": True}
CSS_ASSET = {"hasFullHtml": False, "cssAssetId": "web.assets_readonly"}


@pytest.mark.parametrize(
    "config,target",
    [(FULL_HTML, "documentElement"), (CSS_ASSET, "#iframe_target")],
    ids=["hasFullHtml", "cssAssetId"],
)
def test_the_iframe_path_renders_from_the_home_assistant_root_without_the_rewrite(
    config: dict, target: str
) -> None:
    """Both targets escape, and which one is used is the config's own choice."""
    node(HARNESS, [{
        "name": "iframe path, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": iframe_program(fixture("iframe"), config, STORED),
        "expected": [target, at_the_ha_root()],
    }])


@pytest.mark.parametrize(
    "config,target",
    [(FULL_HTML, "documentElement"), (CSS_ASSET, "#iframe_target")],
    ids=["hasFullHtml", "cssAssetId"],
)
def test_the_rewrite_renders_the_iframe_path_under_the_ingress_prefix(
    config: dict, target: str
) -> None:
    """The helper runs in the parent realm on a string, so the sandbox on the
    full-HTML iframe is not in the way: the rewrite changes what is assigned,
    not who assigns it."""
    node(HARNESS, [{
        "name": "iframe path, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": iframe_program(rewritten("iframe"), config, STORED),
        "expected": [target, under_prefix()],
    }])


@pytest.mark.parametrize(
    "config,target",
    [(FULL_HTML, "documentElement"), (CSS_ASSET, "#iframe_target")],
    ids=["hasFullHtml", "cssAssetId"],
)
def test_without_the_globals_the_iframe_path_assigns_the_raw_value(
    config: dict, target: str
) -> None:
    node(HARNESS, [{
        "name": "iframe path, with no Runtime shim",
        "shim": "",
        "program": iframe_program(rewritten("iframe"), config, STORED),
        "expected": [target, at_the_ha_root()],
    }])


def test_the_iframe_path_prefixes_a_primitive_string_too() -> None:
    """`innerHTML` inserts a string as markup, so this one is not a cosmetic case."""
    node(HARNESS, [{
        "name": "iframe path, a primitive string value",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": iframe_program(rewritten("iframe"), FULL_HTML, STORED, as_markup=False),
        "expected": ["documentElement", under_prefix()],
    }])


# --- the fixtures -------------------------------------------------------------

@pytest.mark.parametrize("name", REWRITES)
def test_the_readme_records_the_pattern_that_ships(name: str) -> None:
    """A shortened stand-in in the table would measure a different pattern."""
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    source = REWRITES[name]["source"]
    rows = [
        line for line in readme.splitlines()
        if line.startswith("| `") and line.split("|")[1].strip().strip("`") == source
    ]
    assert len(rows) == 1, (
        f"{name}: fixtures/bundles/README.md must carry one measurement row whose pattern is "
        f"exactly the sub_filter source {source!r}"
    )


def test_the_fixtures_are_verbatim_regions() -> None:
    """Each excerpt is bundle bytes, so it must start and end where it says."""
    iframe = fixture("iframe")
    assert iframe.startswith("updateIframeContent(content){")
    assert iframe.rstrip().endswith("this.processReadonlyContent(iframeTarget);}")
    plain = fixture("plain")
    assert plain.startswith('registerTemplate("html_editor.HtmlViewer", `')
    assert plain.rstrip().endswith("`);")
    assert 't-name="html_editor.HtmlViewer" xml:space="preserve"' in plain, (
        "the xml bundle sets xml:space on every template it registers, so the excerpt has it"
    )
