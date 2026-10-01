#!/usr/bin/env python3
"""Contracts for the legacy ``web_editor`` editor's markup round trip (issue #238).

Odoo 18 ships **two** HTML editors. #210 and #237 rewrote ``html_editor``, the
current one. Three field widgets still run the previous one out of
``web_editor``, and ADR 0004's postscript said it "carries none of these
expressions" -- which is literally true: its load and save sites are different
expressions, so not one of the eight rules those issues shipped fires on it.
Under Ingress a record edited there rendered its root-relative URLs against the
Home Assistant root and got 404, and -- the half that matters more -- a save
stored the Ingress prefix, Supervisor token and all, into the field.

**Which views reach it**, read out of the pinned package
(``ODOO_DEB_VERSION`` 18.0.20260930) rather than assumed:

- ``html_legacy`` -- **no shipped view uses it.** Outside its own registration,
  every occurrence in the package is a test
  (``web_editor/static/tests/html_field_tests.js``, ``banner_tests.js``,
  ``link_tests.js`` and ``list_tests.js``) -- four files, none of them a view. It
  is a compatibility registration with nothing behind it, recorded here as a
  finding rather than tested as a screen.
- ``mass_mailing_html`` -- **one** view, ``mass_mailing/views/mailing_mailing_views.xml``,
  the mailing body (``body_arch``), with ``inline-field: body_html`` and
  ``cssReadonly``. ``mass_mailing`` is installed on ``odoo_parity``, so Email
  Marketing's mail designer is the screen.
- ``account_payment_register_html`` -- **one** view,
  ``account/wizard/account_payment_register_views.xml``, and the issue did not
  name it. ``account`` subclasses the legacy field and inherits its template, so
  Register Payment's installments note renders through the plain readonly path
  below. Its value (``installments_switch_html``) is computed prose with no URL
  in it, so nothing escapes there today; the path is covered because the path is
  a markup insertion of a record value.

What is pinned here:

- **Ten rewrites**, six putting the prefix on at an insertion site and four
  taking it off at a write, each measured in the bytes the control group's
  bundles serve and each occurring exactly once in the whole package.
- **Two patterns that begin mid-identifier.** nginx reads ``$editable`` in a
  parameter as a variable and refuses to load the config, and there is no escape
  for ``$``, so the ``startEdition`` and code-view-off patterns start *after* the
  ``$`` of ``this.$editable`` / ``$codeview``. A test below proves each is a
  suffix of the real expression rather than a different one.
- **The save seam.** The strip goes on ``getEditingValue()``, the one read every
  save goes through, and not on the ``record.update`` beside it. Stripping later
  would leave ``updateValue`` comparing a prefixed editing value with the
  unprefixed ORM value, so every commit would look dirty and write the field; a
  test drives exactly that unchanged commit.
- **mass_mailing's second write.** ``commitChanges`` clones the editable into a
  ``srcdoc`` iframe, inlines it and stores that as ``body_html`` without going
  through ``getEditingValue`` at all.
- **The globals are reachable from where each expression runs.** Every rewritten
  expression is parent-page code. The mail designer's own iframe is built by
  ``document.write`` and never was an HTTP response, so no shim ran in it -- and
  it carries none of these files, which the fixtures' README records as a
  measured zero for ``web_editor.wysiwyg_iframe_editor_assets``.
- **Every value here is an OWL ``Markup`` object**, so the six insertions call
  ``__WOOW_INGRESS_MARKUP_IN_VALUE__`` (#237's third helper) and not the plain
  ``IN``, which returns a non-string as it came. The drivers below report the
  type they got back, because jQuery's ``.html()`` and OWL's ``t-out`` both
  branch on it.
- **Ingress only**, and each site driven with the globals present and absent.
"""
import json
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from test_ingress_clipboard_fallback import INGRESS_PREFIX, directive_lines
from test_ingress_router_rewrite import TEMPLATE, ingress_rule
from test_ingress_readonly_html_viewer import MARKUP_CLASS
from test_ingress_todo_description import (
    HA_ORIGIN,
    HARNESS,
    TODO_PICTURES,
    node,
    rendered_shim,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures/bundles"

IN_VALUE_GLOBAL = "__WOOW_INGRESS_MARKUP_IN_VALUE__"
OUT_GLOBAL = "__WOOW_INGRESS_MARKUP_OUT__"

# The `o_readonly` div of the legacy field's own template, as the xml bundle
# serves it: lxml re-serialises `html_field.xml` on the way in, so the source
# file's space before the `/>` is gone. A pattern copied from the file would
# match nothing, silently.
READONLY_DIV = '<div t-ref="readonlyElement" class="o_readonly" t-out="markupValue"/>'

# #237's `Markup` class and value helpers, plus one of this file's own: every
# URL the browser would fetch or follow out of a markup string. `href` counts
# here where #237 only needed `src`, because `href` is one of the four
# attributes `IN` prefixes and a linked document is the second thing a mail body
# carries.
MARKUP_HELPERS = MARKUP_CLASS + r"""
function urlsIn(html, page) {
  const out = [];
  for (const match of String(html).matchAll(/(?:src|href)="([^"]*)"/g)) {
    out.push(new URL(match[1], page).href);
  }
  return out;
}
"""

# `getEditingValue`'s body, which the rewrite keeps byte for byte inside an
# arrow IIFE -- so `this` is unchanged and the class gains no member.
RAW_EDITING_VALUE = (
    "const codeViewEl=this._getCodeViewEl();if(codeViewEl){return codeViewEl.value;}"
    "else{if(this.wysiwyg){return this.wysiwyg.getValue();}else{return null;}}"
)

REWRITES = {
    "editable load": {
        "fixture": "legacy_wysiwyg_start_edition.js",
        "source": "editable.html(options.value);",
        "occurrences": 1,
        "global": IN_VALUE_GLOBAL,
        "dollar": "this.$",
    },
    "editor reset": {
        "fixture": "legacy_editor_reset_content.js",
        "source": "this.editable.innerHTML=value;",
        "occurrences": 1,
        "global": IN_VALUE_GLOBAL,
    },
    "readonly refresh": {
        "fixture": "legacy_readonly_iframe.js",
        "source": "iframeTarget.innerHTML=this.props.record.data[this.props.name];",
        "occurrences": 1,
        "global": IN_VALUE_GLOBAL,
    },
    "readonly first load": {
        "fixture": "legacy_readonly_iframe.js",
        "source": "iframeTarget.innerHTML=value;",
        "occurrences": 1,
        "global": IN_VALUE_GLOBAL,
    },
    "readonly sandboxed": {
        "fixture": "legacy_readonly_iframe.js",
        "source": "cwindow.document.documentElement.innerHTML=value;",
        "occurrences": 1,
        "global": IN_VALUE_GLOBAL,
    },
    "readonly plain": {
        "fixture": "legacy_html_field_template.js",
        "source": READONLY_DIV,
        "occurrences": 1,
        "global": IN_VALUE_GLOBAL,
    },
    "editing value": {
        "fixture": "legacy_html_field_editing_value.js",
        "source": "getEditingValue(){%s}" % RAW_EDITING_VALUE,
        "occurrences": 1,
        "global": OUT_GLOBAL,
    },
    "inline field": {
        "fixture": "mass_mailing_inline_field.js",
        "source": "const inlineHtml=editableClone.innerHTML;",
        "occurrences": 1,
        "global": OUT_GLOBAL,
    },
    "code view on": {
        "fixture": "legacy_html_field_code_view.js",
        "source": "this.wysiwyg.odooEditor.toolbarHide();const value=this.wysiwyg.getValue();",
        "occurrences": 1,
        "global": OUT_GLOBAL,
    },
    "code view off": {
        "fixture": "legacy_html_field_code_view.js",
        "source": "codeview.val();this.props.record.update({[this.props.name]:value});",
        "occurrences": 1,
        "global": OUT_GLOBAL,
        "dollar": "$",
    },
}

INSERTIONS = [name for name, rewrite in REWRITES.items() if rewrite["global"] == IN_VALUE_GLOBAL]
WRITES = [name for name, rewrite in REWRITES.items() if rewrite["global"] == OUT_GLOBAL]

# A mailing body as the designer holds one: the two root-relative pictures #210
# chased on the other editor, in markup the mail designer would really carry.
STORED = (
    '<div class="o_mail_wrapper">'
    '<img src="%s" alt="todo-access"/>'
    '<a href="%s">the second one</a>'
    "</div>"
) % TODO_PICTURES

PREFIXED = STORED.replace('src="/', 'src="%s/' % INGRESS_PREFIX).replace(
    'href="/', 'href="%s/' % INGRESS_PREFIX
)


# --- the drivers --------------------------------------------------------------

# `Wysiwyg.startEdition`'s preamble, whose `this.$editable.html(options.value)`
# is the editable's first load. The stand-in records the value assigned and
# resolves every URL in it the way the browser resolves one against the page.
START_EDITION_DRIVER = r"""
__MARKUP_CLASS__
const requested = [];
let assigned = null;
const editable = {
  html(markup) { assigned = markup; requested.push(...urlsIn(markup, PAGE)); return this; },
};
class Wysiwyg {
  constructor(stored, asMarkup) {
    this.options = { value: value(stored, asMarkup) };
    this.$el = editable;
  }
__SLICE__
  }
}
result = (async () => {
  await new Wysiwyg(__RAW__, __AS_MARKUP__).startEdition();
  return [insertedAsHtml(assigned), requested];
})();
"""

# `OdooEditor.resetContent`, the load every *later* render goes through: a
# record switch, a discard, the collaboration stale-document reset, a mail theme
# switch, and the code view on its way back off.
RESET_CONTENT_DRIVER = r"""
__MARKUP_CLASS__
const requested = [];
let assigned = null;
const editable = {
  textContent: "x",
  firstChild: null,
  set innerHTML(markup) { assigned = markup; requested.push(...urlsIn(markup, PAGE)); },
};
class OdooEditor {
  constructor() {
    this.editable = editable;
    this.options = {};
    this._toRollback = true;
  }
__SLICE__
  sanitize() {}
  historyStep() {}
  multiselectionRefresh() {}
  _makeHint() {}
}
new OdooEditor().resetContent(value(__RAW__, __AS_MARKUP__));
result = [insertedAsHtml(assigned), requested];
"""

# The legacy field's readonly iframe, which reaches markup three times. The
# fake iframe keeps the `load` listener so the test can fire it, and every
# target reports what the browser would fetch.
READONLY_IFRAME_DRIVER = r"""
__MARKUP_CLASS__
window.top = window;
document.createTextNode = () => ({});
const requested = [];
let written = null;
const target = (name) => ({
  get innerHTML() { return "whatever the component rendered last time"; },
  set innerHTML(markup) {
    written = name;
    requested.push(...urlsIn(markup, PAGE));
  },
  append() {},
});
const documentElement = target("documentElement");
const iframeTarget = target("#iframe_target");
const element = () => ({ setAttribute() {}, append() {} });
const iframeDocument = {
  documentElement,
  head: { append() {} },
  body: { append() {}, scrollHeight: 120 },
  createElement: element,
  querySelector: (selector) => (selector === "#iframe_target" ? iframeTarget : null),
  open: () => ({ write() {} }),
};
let onLoad = null;
const retargetLinks = () => {};
class HtmlField {
  constructor(stored, sandboxedPreview, mounted) {
    this.sandboxedPreview = sandboxedPreview;
    this.iframePromise = mounted ? Promise.resolve("already mounted") : undefined;
    this._onUpdateIframeId = "onLoad_FieldHtml1";
    this.state = { iframeVisible: false };
    this.onIframeUpdated = () => {};
    this.cssReadonlyAsset = { cssLibs: ["/web/assets/mass_mailing.iframe_css_assets_edit.min.css"] };
    this.props = {
      name: "body_arch",
      cssReadonlyAssetId: "mass_mailing.iframe_css_assets_edit",
      record: { data: { body_arch: value(stored, __AS_MARKUP__) } },
    };
    this.iframeRef = {
      el: {
        style: {},
        contentDocument: iframeDocument,
        contentWindow: { document: iframeDocument },
        addEventListener: (name, listener) => { if (name === "load") onLoad = listener; },
        after() {},
      },
    };
  }
__SLICE__
}
result = (async () => {
  const field = new HtmlField(__RAW__, __SANDBOXED__, __MOUNTED__);
  const promise = field._setupReadonlyIframe();
  if (onLoad) { await onLoad(); } else { await promise; }
  return [written, requested];
})();
"""

# The plain readonly path: the `t-out` expression exactly as the rewritten
# template carries it, evaluated the way the compiled template evaluates it.
PLAIN_DRIVER = r"""
__MARKUP_CLASS__
const markupValue = value(__RAW__, __AS_MARKUP__);
const rendered = __EXPRESSION__;
result = [
  insertedAsHtml(rendered),
  insertedAsHtml(rendered) ? urlsIn(rendered, PAGE) : [],
  String(rendered),
];
"""

# `getEditingValue` and the `updateValue` that writes what it returns. The
# record stand-in reports what would be stored, and `null` reports that nothing
# would be.
SAVE_DRIVER = r"""
__MARKUP_CLASS__
let written = null;
const stripHistoryIds = (markup) => String(markup);
const codeViewEl = __CODE_VIEW__;
class HtmlField {
  constructor(editing, stored) {
    this.wysiwyg = { getValue: () => editing };
    this.props = {
      name: "body_arch",
      record: {
        data: { body_arch: value(stored, true) },
        model: { bus: { trigger() {} } },
        update(changes) { written = changes; },
      },
    };
  }
  _getCodeViewEl() { return codeViewEl; }
__SLICE__
}
result = (async () => {
  const field = new HtmlField(__EDITING__, __STORED__);
  await field.updateValue();
  return [written, field.currentEditingValue === undefined ? null : field.currentEditingValue];
})();
"""

# mass_mailing's second write: the inlined `body_html`, read off a clone in a
# `srcdoc` iframe by code that runs in the parent.
INLINE_DRIVER = r"""
__MARKUP_CLASS__
let written = null;
// Not named `editableClone`: the slice declares its own `const` of that name,
// which would shadow this one into its temporal dead zone.
const cloneInTheSrcdocIframe = { innerHTML: __EDITING__ };
const self = {
  wysiwyg: { odooEditor: { observerActive() {}, historyUnpauseSteps() {}, historyRevertCurrentStep() {} } },
  props: { inlineField: "body_html", record: { update(changes) { written = changes; } } },
};
const run = async function () {
  const iframe = {
    contentDocument: { querySelector: () => cloneInTheSrcdocIframe },
    remove() {},
  };
  const $editorEnable = { addClass() {}, removeClass() {} };
  const toInline = async () => {};
  const $ = (node) => node;
__SLICE__
};
result = (async () => {
  await run.call(self);
  return written;
})();
"""

# The code view's two writes, neither of which goes through `getEditingValue`.
CODE_VIEW_DRIVER = r"""
__MARKUP_CLASS__
const written = [];
const $ = (el) => ({ val: () => el.value });
class HtmlField {
  constructor(showCodeView, editableValue, textareaValue) {
    this.state = { showCodeView };
    this.codeViewRef = { el: { value: textareaValue } };
    this.wysiwyg = {
      getValue: () => editableValue,
      $editable: { remove() {} },
      odooEditor: { observerUnactive() {}, observerActive() {}, toolbarHide() {} },
    };
    this.props = { name: "txt", record: { update(changes) { written.push(changes); } } };
  }
__SLICE__
}
new HtmlField(__SHOW__, __EDITABLE__, __TEXTAREA__).toggleCodeView();
result = written;
"""


# --- helpers ------------------------------------------------------------------

def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def fixture(name: str) -> str:
    return (FIXTURES / REWRITES[name]["fixture"]).read_text(encoding="utf-8")


def replacement(name: str) -> str:
    """The replacement of the one ingress-only `sub_filter` for this rewrite."""
    rewrite = REWRITES[name]
    found = ingress_rule(template(), rewrite["source"], name)
    assert rewrite["global"] in found, (
        f"the {name} rewrite must go through {rewrite['global']}, the helper the shim publishes"
    )
    return found


def rewritten(name: str) -> str:
    """One rewrite's fixture as the Ingress asset location serves it.

    *Every* rule that reaches that fixture is applied and not only this one --
    three of the ten share `legacy_readonly_iframe.js` and two share
    `legacy_html_field_code_view.js`, and nginx has no way to serve one of them
    without the others. There is deliberately no one-rule-only variant: adding a
    second rule to a fixture would otherwise leave some caller testing
    half-rewritten bytes, silently.
    """
    assert name in REWRITES, name
    text = fixture(name)
    for other, rewrite in REWRITES.items():
        if rewrite["fixture"] == REWRITES[name]["fixture"]:
            text = text.replace(rewrite["source"], replacement(other))
    return text


def registered_template(text: str) -> str:
    """The third argument of ``registerTemplate(...)``: the template itself."""
    parts = text.split("`")
    assert len(parts) == 5, "the fixture must be one registerTemplate(name, `url`, `template`);"
    return parts[3]


def readonly_expression(text: str) -> str:
    """The ``t-out`` of the legacy field's readonly div, parsed out as XML."""
    root = ElementTree.fromstring(registered_template(text))
    divs = root.findall('.//div[@t-ref="readonlyElement"]')
    assert len(divs) == 1, "the template must hold one readonly div"
    return divs[0].get("t-out")


# Every placeholder the drivers above carry. Checked rather than pattern-matched,
# because the helper names in the replacements end in `__` themselves.
PLACEHOLDERS = (
    "__MARKUP_CLASS__", "__SLICE__", "__RAW__", "__AS_MARKUP__", "__SANDBOXED__",
    "__MOUNTED__", "__EXPRESSION__", "__EDITING__", "__STORED__", "__CODE_VIEW__",
    "__SHOW__", "__EDITABLE__", "__TEXTAREA__",
)


def program(driver: str, slice_from: str, text: str, **substitutions: str) -> str:
    body = text[text.index(slice_from):].rstrip()
    out = driver.replace("__MARKUP_CLASS__", MARKUP_HELPERS).replace("__SLICE__", body)
    for key, value in substitutions.items():
        out = out.replace("__%s__" % key, value)
    for placeholder in PLACEHOLDERS:
        assert placeholder not in out, (
            f"{placeholder} was left in the driver; a placeholder that is not substituted is a "
            "program that does not run the expression the test claims it runs"
        )
    return out


def start_edition_program(text: str, stored: str, as_markup: bool = True) -> str:
    return program(
        START_EDITION_DRIVER, "async startEdition(){", text,
        RAW=json.dumps(stored), AS_MARKUP="true" if as_markup else "false",
    )


def reset_content_program(text: str, stored: str, as_markup: bool = True) -> str:
    return program(
        RESET_CONTENT_DRIVER, "resetContent(value){", text,
        RAW=json.dumps(stored), AS_MARKUP="true" if as_markup else "false",
    )


def readonly_iframe_program(
    text: str, stored: str, sandboxed: bool, mounted: bool, as_markup: bool = True
) -> str:
    return program(
        READONLY_IFRAME_DRIVER, "async _setupReadonlyIframe(){", text,
        RAW=json.dumps(stored),
        SANDBOXED="true" if sandboxed else "false",
        MOUNTED="true" if mounted else "false",
        AS_MARKUP="true" if as_markup else "false",
    )


def plain_program(text: str, stored: str, as_markup: bool = True) -> str:
    return (
        PLAIN_DRIVER.replace("__MARKUP_CLASS__", MARKUP_HELPERS)
        .replace("__EXPRESSION__", readonly_expression(text))
        .replace("__RAW__", json.dumps(stored))
        .replace("__AS_MARKUP__", "true" if as_markup else "false")
    )


def save_program(text: str, editing: str, stored: str, code_view: bool = False) -> str:
    return program(
        SAVE_DRIVER, "getEditingValue(){", text,
        EDITING=json.dumps(editing),
        STORED=json.dumps(stored),
        CODE_VIEW=("{value: %s}" % json.dumps(editing)) if code_view else "null",
    )


def inline_program(text: str, editing: str) -> str:
    return program(INLINE_DRIVER, "const editableClone=", text, EDITING=json.dumps(editing))


def code_view_program(text: str, show: bool, editable: str, textarea: str) -> str:
    return program(
        CODE_VIEW_DRIVER, "toggleCodeView(){", text,
        SHOW="true" if show else "false",
        EDITABLE=json.dumps(editable),
        TEXTAREA=json.dumps(textarea),
    )


def under_prefix() -> list:
    return [HA_ORIGIN + INGRESS_PREFIX + picture for picture in TODO_PICTURES]


def at_the_ha_root() -> list:
    return [HA_ORIGIN + picture for picture in TODO_PICTURES]


# --- the rewrites themselves --------------------------------------------------

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
    replacement(name)


@pytest.mark.parametrize("name", REWRITES)
def test_no_pattern_or_replacement_carries_a_dollar(name: str) -> None:
    """nginx reads `$name` in a parameter as a variable, in either argument.

    There is no escape for it, and an unknown variable is a config nginx
    refuses to load -- so a pattern over this jQuery-flavoured code has to be
    written around every `$`, not with it.
    """
    for argument in (REWRITES[name]["source"], replacement(name)):
        assert "$" not in argument, (
            f"{name}: {argument!r} carries a `$`; nginx would read it as a variable reference"
        )


@pytest.mark.parametrize(
    "name", [name for name, rewrite in REWRITES.items() if "dollar" in rewrite]
)
def test_a_pattern_that_starts_after_a_dollar_is_a_suffix_of_the_real_expression(
    name: str,
) -> None:
    """The two patterns that begin mid-identifier must still be *that* expression.

    `this.$editable.html(options.value)` and `$codeview.val()` cannot be matched
    whole, so each pattern starts after the `$` and leaves the prefix outside
    the match. That is only safe if the prefix is really there in the bundle --
    otherwise the rule is matching some other expression that happens to end the
    same way.
    """
    rewrite = REWRITES[name]
    whole = rewrite["dollar"] + rewrite["source"]
    found = fixture(name).count(whole)
    assert found == rewrite["occurrences"], (
        f"{name}: the pattern must be the tail of {whole!r}, found {found} of those"
    )
    assert replacement(name).startswith(rewrite["source"].split("(")[0]), (
        f"{name}: the replacement must re-emit the matched head, so the `$` before it still "
        "reads as part of the same expression"
    )


def test_the_insertions_go_through_the_value_helper_and_the_writes_through_the_strip() -> None:
    """Six IN sites, four OUT sites, and no site that does both."""
    assert len(INSERTIONS) == 6 and len(WRITES) == 4, (REWRITES.keys(),)
    for name in INSERTIONS:
        assert OUT_GLOBAL not in replacement(name), (
            f"{name} is a render site: stripping there would take the prefix off as it goes on"
        )
    for name in WRITES:
        assert IN_VALUE_GLOBAL not in replacement(name), (
            f"{name} is a write: prefixing there is exactly the token write ADR 0004 forbids"
        )


def test_the_editing_value_rewrite_keeps_the_method_body_byte_for_byte() -> None:
    """The strip wraps the body in an arrow IIFE rather than rewriting it.

    An arrow keeps `this`, so the three branches behave as they did, and the
    class gains no member a subclass could collide with.
    """
    found = replacement("editing value")
    assert RAW_EDITING_VALUE in found, "the method's own body must survive unchanged"
    assert "(()=>{" in found and "})()" in found, "...inside an arrow IIFE, which keeps `this`"
    assert "function(" not in found.replace("function(v){return v}", ""), (
        "nothing but the fallback may be a `function`, whose `this` would be wrong"
    )


def test_no_rule_can_interfere_with_another() -> None:
    """nginx replaces in one stream pass; the tests replace sequentially in Python.

    The two models only agree while no pattern is a substring of another and no
    replacement reintroduces a pattern -- and three of the ten share a fixture,
    so the tests above would read as green on an order the gateway never takes.
    `iframeTarget.innerHTML=` opens two of these rules and `iframeTarget.innerHTML=content;`
    (a third, #237's) sits in the same bundle, which is exactly the neighbourhood
    where this goes wrong.
    """
    sources = {name: REWRITES[name]["source"] for name in REWRITES}
    replacements = {name: replacement(name) for name in REWRITES}
    for name, source in sources.items():
        for other, other_source in sources.items():
            if other == name:
                continue
            assert source not in other_source, (
                f"{name}'s pattern is inside {other}'s: whichever nginx matches first decides, "
                "and the loser is a silent no-op"
            )
        for other, other_replacement in replacements.items():
            assert source not in other_replacement, (
                f"{name}'s pattern appears in {other}'s replacement; nginx does not rescan a "
                "replacement but the tests' sequential replace does, so the two would disagree"
            )


def test_a_shared_fixture_rewrites_the_same_whatever_order_the_rules_run_in() -> None:
    """Executed rather than argued, for each fixture more than one rule reaches."""
    for fixture_name in ("legacy_readonly_iframe.js", "legacy_html_field_code_view.js"):
        names = [n for n, r in REWRITES.items() if r["fixture"] == fixture_name]
        assert len(names) > 1, f"{fixture_name} is expected to carry more than one rewrite"
        text = (FIXTURES / fixture_name).read_text(encoding="utf-8")
        forwards = text
        for name in names:
            forwards = forwards.replace(REWRITES[name]["source"], replacement(name))
        backwards = text
        for name in reversed(names):
            backwards = backwards.replace(REWRITES[name]["source"], replacement(name))
        assert forwards == backwards, f"{fixture_name}: the rules are order-dependent"
        for name in names:
            assert REWRITES[name]["source"] not in forwards, (
                f"{fixture_name}: {name}'s pattern survived, so one rule undid another"
            )


def test_the_rewrites_name_nothing_route_scoped() -> None:
    """Still the render and write sites, not the response the editor saves through."""
    text = template()
    for forbidden in ("/web/dataset/call_kw", "mailing.mailing", "web_save"):
        offenders = [number for number, line in directive_lines(text) if forbidden in line]
        assert not offenders, (
            f"no directive may name {forbidden!r} (found on lines {offenders}): rewriting the "
            "response the editor also saves through is what ADR 0004 decided against"
        )


# --- the template rewrite, which has to stay a template -----------------------

def test_the_rewritten_template_is_still_well_formed_xml() -> None:
    expression = readonly_expression(rewritten("readonly plain"))
    assert IN_VALUE_GLOBAL in expression, "the readonly div must render through the helper"
    assert "markupValue" in expression, "...on the getter the component exposes"
    before = registered_template(fixture("readonly plain"))
    after = registered_template(rewritten("readonly plain"))
    assert before.replace(READONLY_DIV, "") == after.replace(replacement("readonly plain"), ""), (
        "the rewrite must change the readonly div and nothing else in the template"
    )


def test_the_rewrite_leaves_the_attribute_account_inherits_the_div_by() -> None:
    """`account`'s `t-inherit` patch selects this div by `@t-ref='readonlyElement'`.

    It is applied in the browser, over the bytes this location served, so a
    rewrite that touched `t-ref` would silently drop Register Payment's
    `t-on-click` -- and OWL's xpath would match nothing with no error.
    """
    root = ElementTree.fromstring(registered_template(rewritten("readonly plain")))
    divs = root.findall('.//div[@t-ref="readonlyElement"]')
    assert len(divs) == 1, (
        "the readonly div must still be selectable by @t-ref='readonlyElement', which is the "
        "xpath account/static/src/components/account_payment_register_html patches on"
    )
    assert divs[0].get("class") == "o_readonly", "and its class, which the stylesheet keys on"


def test_the_rewritten_template_stays_a_javascript_template_literal() -> None:
    found = replacement("readonly plain")
    for forbidden in ("`", "${", "\\"):
        assert forbidden not in found, (
            f"the template rewrite may not carry {forbidden!r}: the bundle writes the template "
            "as a template literal and Odoo escapes those three on the way in"
        )
    expression = readonly_expression(rewritten("readonly plain"))
    for forbidden in ('"', "'"):
        assert forbidden not in expression, (
            "the expression is the value of a double-quoted XML attribute written inside that "
            f"literal, so it may not carry {forbidden!r} either"
        )


def test_the_template_fallback_is_an_arrow_and_not_a_function() -> None:
    """OWL rewrites a template expression's unknown symbols into ctx lookups.

    A `function`'s parameter is not exempt, so `function(h){return h}` compiles
    to `function(ctx['h']){return ctx['h']}` and the template throws at compile
    time. An arrow's parameter is tracked as a local; `window` is reserved.
    """
    expression = readonly_expression(rewritten("readonly plain"))
    assert "function" not in expression, "use an arrow in a template expression"
    assert "=>" in expression, "the fallback must be an arrow function"
    assert expression.startswith("(window."), (
        "the expression must read the helper off window, which OWL leaves alone"
    )


# --- the editable, in edit mode ------------------------------------------------

def test_the_editable_loads_from_the_home_assistant_root_without_the_rewrite() -> None:
    node(HARNESS, [{
        "name": "startEdition, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": start_edition_program(fixture("editable load"), STORED),
        "expected": [True, at_the_ha_root()],
    }])


def test_the_rewrite_loads_the_editable_under_the_ingress_prefix() -> None:
    """And hands jQuery the same shape it had, so `.html()` takes the same path."""
    node(HARNESS, [{
        "name": "startEdition, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": start_edition_program(rewritten("editable load"), STORED),
        "expected": [True, under_prefix()],
    }])


def test_without_the_globals_the_editable_loads_the_raw_value() -> None:
    node(HARNESS, [{
        "name": "startEdition, with no Runtime shim",
        "shim": "",
        "program": start_edition_program(rewritten("editable load"), STORED),
        "expected": [True, at_the_ha_root()],
    }])


def test_the_editor_reset_escapes_without_the_rewrite() -> None:
    node(HARNESS, [{
        "name": "resetContent, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": reset_content_program(fixture("editor reset"), STORED),
        "expected": [True, at_the_ha_root()],
    }])


def test_the_rewrite_keeps_the_editor_reset_under_the_prefix() -> None:
    """Every later load goes through here: a record switch, a discard, a theme."""
    node(HARNESS, [{
        "name": "resetContent, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": reset_content_program(rewritten("editor reset"), STORED),
        "expected": [True, under_prefix()],
    }])


def test_the_editor_reset_does_not_prefix_twice() -> None:
    """`_toInline` and the code view both reset the editable with what it held."""
    node(HARNESS, [{
        "name": "resetContent, over an already prefixed value",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": reset_content_program(rewritten("editor reset"), PREFIXED),
        "expected": [True, under_prefix()],
    }])


def test_without_the_globals_the_editor_reset_assigns_the_raw_value() -> None:
    node(HARNESS, [{
        "name": "resetContent, with no Runtime shim",
        "shim": "",
        "program": reset_content_program(rewritten("editor reset"), STORED),
        "expected": [True, at_the_ha_root()],
    }])


# --- the readonly render paths -------------------------------------------------

READONLY_PATHS = [
    pytest.param(False, True, "#iframe_target", id="refresh"),
    pytest.param(False, False, "#iframe_target", id="first-load"),
    pytest.param(True, False, "documentElement", id="sandboxed-preview"),
]


@pytest.mark.parametrize("sandboxed,mounted,target", READONLY_PATHS)
def test_the_readonly_iframe_renders_from_the_ha_root_without_the_rewrite(
    sandboxed: bool, mounted: bool, target: str
) -> None:
    """The reachable screen: a *sent* mailing, whose form is readonly."""
    node(HARNESS, [{
        "name": "readonly iframe, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": readonly_iframe_program(
            (FIXTURES / "legacy_readonly_iframe.js").read_text(encoding="utf-8"),
            STORED, sandboxed, mounted,
        ),
        "expected": [target, at_the_ha_root()],
    }])


@pytest.mark.parametrize("sandboxed,mounted,target", READONLY_PATHS)
def test_the_rewrites_render_the_readonly_iframe_under_the_ingress_prefix(
    sandboxed: bool, mounted: bool, target: str
) -> None:
    """All three branches, because which one runs is the component's own state."""
    node(HARNESS, [{
        "name": "readonly iframe, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": readonly_iframe_program(
            rewritten("readonly first load"), STORED, sandboxed, mounted,
        ),
        "expected": [target, under_prefix()],
    }])


@pytest.mark.parametrize("sandboxed,mounted,target", READONLY_PATHS)
def test_without_the_globals_the_readonly_iframe_renders_the_raw_value(
    sandboxed: bool, mounted: bool, target: str
) -> None:
    node(HARNESS, [{
        "name": "readonly iframe, with no Runtime shim",
        "shim": "",
        "program": readonly_iframe_program(
            rewritten("readonly first load"), STORED, sandboxed, mounted,
        ),
        "expected": [target, at_the_ha_root()],
    }])


def test_the_plain_readonly_path_renders_from_the_ha_root_without_the_rewrite() -> None:
    """Register Payment's installments note comes down this one."""
    node(HARNESS, [{
        "name": "plain readonly path, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": plain_program(fixture("readonly plain"), STORED),
        "expected": [True, at_the_ha_root(), STORED],
    }])


def test_the_rewrite_renders_the_plain_readonly_path_under_the_ingress_prefix() -> None:
    """And it is still a Markup, so OWL inserts it as HTML rather than text."""
    node(HARNESS, [{
        "name": "plain readonly path, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": plain_program(rewritten("readonly plain"), STORED),
        "expected": [True, under_prefix(), PREFIXED],
    }])


def test_without_the_globals_the_plain_readonly_path_renders_the_raw_value() -> None:
    node(HARNESS, [{
        "name": "plain readonly path, with no Runtime shim",
        "shim": "",
        "program": plain_program(rewritten("readonly plain"), STORED),
        "expected": [True, at_the_ha_root(), STORED],
    }])


# --- the writes ----------------------------------------------------------------

def test_the_editor_stores_the_ingress_prefix_without_the_rewrite() -> None:
    """The half that matters: the prefix carries the Supervisor token."""
    node(HARNESS, [{
        "name": "updateValue, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": save_program(fixture("editing value"), PREFIXED, STORED),
        "expected": [{"body_arch": PREFIXED}, PREFIXED],
    }])


def test_the_rewrite_stores_a_root_relative_value() -> None:
    node(HARNESS, [{
        "name": "updateValue, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": save_program(rewritten("editing value"), PREFIXED, STORED),
        "expected": [None, None],
    }])


def test_the_rewrite_stores_a_root_relative_value_for_a_real_change() -> None:
    """The unchanged case above writes nothing, so change something and look."""
    edited = PREFIXED.replace("the second one", "the second link")
    node(HARNESS, [{
        "name": "updateValue, under Ingress, a real edit",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": save_program(rewritten("editing value"), edited, STORED),
        "expected": [
            {"body_arch": STORED.replace("the second one", "the second link")},
            STORED.replace("the second one", "the second link"),
        ],
    }])


def test_the_code_view_value_is_stripped_on_the_way_to_the_record_too() -> None:
    """`getEditingValue` reads the textarea when one is open, so cover that branch."""
    node(HARNESS, [{
        "name": "updateValue from the code view, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": save_program(
            rewritten("editing value"),
            PREFIXED.replace("the second one", "the second link"),
            STORED,
            code_view=True,
        ),
        "expected": [
            {"body_arch": STORED.replace("the second one", "the second link")},
            STORED.replace("the second one", "the second link"),
        ],
    }])


def test_an_unchanged_commit_writes_nothing_which_is_why_the_strip_is_here() -> None:
    """The reason the strip is on `getEditingValue` and not on `record.update`.

    `updateValue` compares the editing value with the ORM value before writing.
    Strip at the write and the comparison is prefixed-against-unprefixed: every
    commit looks dirty, writes the field, and sets `currentEditingValue` to a
    value that makes the Wysiwyg reset its content on the next update. Both
    halves are driven here -- Odoo's own bytes write, the rewritten ones do not.
    """
    node(HARNESS, [
        {
            "name": "unchanged commit, as Odoo ships it: writes",
            "shim": rendered_shim(INGRESS_PREFIX),
            "program": save_program(fixture("editing value"), PREFIXED, STORED),
            "expected": [{"body_arch": PREFIXED}, PREFIXED],
        },
        {
            "name": "unchanged commit, under Ingress: writes nothing",
            "shim": rendered_shim(INGRESS_PREFIX),
            "program": save_program(rewritten("editing value"), PREFIXED, STORED),
            "expected": [None, None],
        },
    ])


def test_without_the_globals_the_save_stores_the_raw_value() -> None:
    node(HARNESS, [{
        "name": "updateValue, with no Runtime shim",
        "shim": "",
        "program": save_program(rewritten("editing value"), PREFIXED, STORED),
        "expected": [{"body_arch": PREFIXED}, PREFIXED],
    }])


def test_the_mailings_inline_field_stores_the_prefix_without_the_rewrite() -> None:
    """mass_mailing's second write, which `getEditingValue` is nowhere near."""
    node(HARNESS, [{
        "name": "body_html, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": inline_program(fixture("inline field"), PREFIXED),
        "expected": {"body_html": PREFIXED},
    }])


def test_the_rewrite_stores_a_root_relative_inline_field() -> None:
    """Miss this one and a mailing goes out with the Supervisor token in it."""
    node(HARNESS, [{
        "name": "body_html, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": inline_program(rewritten("inline field"), PREFIXED),
        "expected": {"body_html": STORED},
    }])


def test_without_the_globals_the_inline_field_stores_the_raw_value() -> None:
    node(HARNESS, [{
        "name": "body_html, with no Runtime shim",
        "shim": "",
        "program": inline_program(rewritten("inline field"), PREFIXED),
        "expected": {"body_html": PREFIXED},
    }])


CODE_VIEW_PATHS = [
    pytest.param(False, id="opening the code view"),
    pytest.param(True, id="closing the code view"),
]


@pytest.mark.parametrize("show", CODE_VIEW_PATHS)
def test_the_code_view_stores_the_prefix_without_the_rewrites(show: bool) -> None:
    """Both of `toggleCodeView`'s writes bypass `getEditingValue`."""
    node(HARNESS, [{
        "name": "toggleCodeView, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": code_view_program(
            (FIXTURES / "legacy_html_field_code_view.js").read_text(encoding="utf-8"),
            show, PREFIXED, PREFIXED,
        ),
        "expected": [{"txt": PREFIXED}],
    }])


@pytest.mark.parametrize("show", CODE_VIEW_PATHS)
def test_the_rewrites_strip_both_of_the_code_views_writes(show: bool) -> None:
    """Bounded by `odoo.debug && options.codeview`, and covered anyway: it writes."""
    node(HARNESS, [{
        "name": "toggleCodeView, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": code_view_program(
            rewritten("code view off"), show, PREFIXED, PREFIXED,
        ),
        "expected": [{"txt": STORED}],
    }])


@pytest.mark.parametrize("show", CODE_VIEW_PATHS)
def test_without_the_globals_the_code_view_stores_the_raw_value(show: bool) -> None:
    node(HARNESS, [{
        "name": "toggleCodeView, with no Runtime shim",
        "shim": "",
        "program": code_view_program(
            rewritten("code view off"), show, PREFIXED, PREFIXED,
        ),
        "expected": [{"txt": PREFIXED}],
    }])


# --- the fixtures and what the README has to record ----------------------------

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


# The two files the editable rules (1 and 2) live in. Which bundles carry them is
# the acceptance question about the mail designer's nested iframes, so it is
# resolved below rather than asserted in prose.
EDITOR_FILES = (
    "web_editor/static/src/js/wysiwyg/wysiwyg.js",
    "web_editor/static/src/js/editor/odoo-editor/src/OdooEditor.js",
)

IFRAME_BUNDLE = "web_editor.wysiwyg_iframe_editor_assets"
BACKEND_BUNDLE = "web_editor.backend_assets_wysiwyg"
FRONTEND_BUNDLE = "web_editor.assets_wysiwyg"


def membership() -> dict:
    """The captured manifest asset entries, closed under nested-bundle references."""
    path = FIXTURES / "legacy_editor_bundle_membership.json"
    return json.loads(path.read_text(encoding="utf-8"))["bundles"]


def _glob(pattern: str):
    """Odoo's asset glob as a regex. `**/` matches zero or more directories.

    `fnmatch` is wrong here, and wrong in the permissive-looking direction: its
    `*` crosses `/`, so `web_editor/static/src/js/backend/**/*` would *fail* to
    match a file directly inside `backend/`. Odoo resolves these with
    `glob(recursive=True)`.
    """
    out, index = [], 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append(r"(?:[^/]+/)*")
            index += 3
        elif pattern[index] == "*":
            out.append(r"[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append(r"[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(out) + r"\Z")


def carries(bundle: str, url: str, bundles: dict, seen: frozenset = frozenset()) -> bool:
    """Whether `bundle` has `url` as a member, resolving includes and removes."""
    assert bundle in bundles, (
        f"{bundle} is not in the captured membership fixture, so this resolution is not "
        "closed; re-capture it from the pinned package"
    )
    if bundle in seen:
        return False
    seen = seen | {bundle}
    member = False
    for _addon, entries in bundles[bundle]:
        for entry in entries:
            target = entry[-1] if isinstance(entry, list) else entry
            operation = entry[0] if isinstance(entry, list) else "include"
            if not isinstance(target, str):
                continue
            if "/" not in target and "." in target:
                hit = carries(target, url, bundles, seen)
            else:
                hit = bool(_glob(target.lstrip("/")).match(url))
            if hit:
                member = operation != "remove"
    return member


@pytest.mark.parametrize("url", EDITOR_FILES)
def test_the_editor_iframes_own_bundle_carries_no_rewritten_file(url: str) -> None:
    """The acceptance question: are the globals reachable where each rule runs?

    The mail designer's editor iframe is built by `document.open().write()`, so
    it never was an HTTP response and no Runtime shim ran in it. That is only
    harmless because the bundle `_loadIframe` injects there carries none of the
    files these rules rewrite -- so no rewritten expression is in that realm at
    all, and every one of the ten runs in the page's realm, where the globals are.

    Resolved against the captured manifest entries rather than stated in prose,
    because this is the claim in the change an Odoo bump could falsify silently:
    moving `wysiwyg.js` into that bundle would put a rewritten expression in a
    realm with no shim, where it falls back to the identity and renders from the
    Home Assistant root again -- with every other test here still green.
    """
    bundles = membership()
    assert not carries(IFRAME_BUNDLE, url, bundles), (
        f"{IFRAME_BUNDLE} now carries {url}. That bundle is injected into an iframe built by "
        "document.write, where no Runtime shim ran, so a rewritten expression there falls back "
        "to the identity: re-reason about this family before shipping"
    )


@pytest.mark.parametrize("url", EDITOR_FILES)
@pytest.mark.parametrize("bundle", [BACKEND_BUNDLE, FRONTEND_BUNDLE])
def test_the_bundles_that_do_carry_the_editor_are_the_ones_measured(
    bundle: str, url: str
) -> None:
    """The other half: the rewritten bytes have to reach somebody.

    `_lazyloadWysiwyg` fetches `backend_assets_wysiwyg` with `loadBundle`, which
    builds a `<script src>` the shim prefixes, so that request goes through the
    Ingress asset location. `assets_wysiwyg` is the frontend twin the website
    editor loads -- named here because rules 1 and 2 reach it too, which is the
    blast radius the gateway template's comment reasons about.
    """
    assert carries(bundle, url, membership()), (
        f"{bundle} no longer carries {url}: the counts in fixtures/bundles/README.md and the "
        "reasoning in the gateway template are measured against this membership"
    )


def test_the_membership_fixture_is_closed_and_names_its_package() -> None:
    """A resolution that silently gave up would read as a green `not carries`."""
    payload = json.loads(
        (FIXTURES / "legacy_editor_bundle_membership.json").read_text(encoding="utf-8")
    )
    assert "18.0.20260930" in payload["_comment"], (
        "the fixture must name the ODOO_DEB_VERSION it was captured from, like every other "
        "fixture in this directory"
    )
    bundles = payload["bundles"]
    for bundle, contributors in bundles.items():
        for _addon, entries in contributors:
            for entry in entries:
                target = entry[-1] if isinstance(entry, list) else entry
                if isinstance(target, str) and "/" not in target and "." in target:
                    assert target in bundles, (
                        f"{bundle} includes {target}, which is not captured: membership cannot "
                        "be resolved from this fixture, so every `carries` answer is a guess"
                    )


def test_the_glob_rule_matches_a_file_directly_under_a_recursive_pattern() -> None:
    """The resolver's own trap, driven rather than trusted.

    Every claim above is a `carries` answer, and the cheap wrong implementation
    (`fnmatch`) answers **no** for a file sitting directly in the globbed
    directory -- which would make `test_..._carries_no_rewritten_file` pass for
    the wrong reason.
    """
    pattern = "web_editor/static/src/js/backend/**/*"
    assert _glob(pattern).match("web_editor/static/src/js/backend/html_field.js"), (
        "`**/` must match zero directories too, or every `not carries` answer here is vacuous"
    )
    assert _glob(pattern).match("web_editor/static/src/js/backend/deeper/x.js")
    assert not _glob(pattern).match("web_editor/static/src/js/wysiwyg/wysiwyg.js")
    assert not _glob("web_editor/static/src/js/*.js").match(
        "web_editor/static/src/js/backend/html_field.js"
    ), "a single `*` must not cross a `/`"


def test_the_readme_records_what_each_of_those_bundles_carries() -> None:
    """The counts stay in the README, where the fixture standard keeps them."""
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    for bundle in (IFRAME_BUNDLE, BACKEND_BUNDLE):
        assert bundle in readme, (
            f"fixtures/bundles/README.md must record what {bundle} carries; the tests above "
            "execute the claim, the README is where a reader finds it"
        )


def test_the_fixtures_are_verbatim_regions() -> None:
    """Each excerpt is bundle bytes, so it must start and end where it says."""
    start_edition = fixture("editable load")
    assert start_edition.startswith("async startEdition(){const self=this;")
    assert start_edition.rstrip().endswith("if(options.value){this.$editable.html(options.value);}")

    reset = fixture("editor reset")
    assert reset.startswith("resetContent(value){value=value||'<p><br></p>';")
    assert reset.rstrip().endswith("this.multiselectionRefresh();}")

    readonly = (FIXTURES / "legacy_readonly_iframe.js").read_text(encoding="utf-8")
    assert readonly.startswith("async _setupReadonlyIframe(){const iframeTarget=")
    assert readonly.rstrip().endswith("this.iframeRef.el.after(this.iframeRef.el);});return this.iframePromise;}")

    editing = fixture("editing value")
    assert editing.startswith("getEditingValue(){const codeViewEl=")
    assert editing.rstrip().endswith("await this.props.record.update({[this.props.name]:value});}}")

    code_view = (FIXTURES / "legacy_html_field_code_view.js").read_text(encoding="utf-8")
    assert code_view.startswith("toggleCodeView(){this.state.showCodeView=")
    assert code_view.rstrip().endswith("this.props.record.update({[this.props.name]:value});}}")

    inline = fixture("inline field")
    assert inline.startswith("const editableClone=iframe.contentDocument.querySelector(")
    assert inline.rstrip().endswith("await this.props.record.update({[fieldName]:inlineHtml});")

    plain = fixture("readonly plain")
    assert plain.startswith('registerTemplate("web_editor.HtmlField", `')
    assert plain.rstrip().endswith("`);")
    assert 't-name="web_editor.HtmlField" xml:space="preserve"' in plain, (
        "the xml bundle sets xml:space on every template it registers, so the excerpt has it"
    )
