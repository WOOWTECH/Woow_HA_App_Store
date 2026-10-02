#!/usr/bin/env python3
"""Contracts for the HTML editor's code view round trip (issue #240).

ADR 0004's postscript named ``toggleCodeView`` as the first of the markup
sites #210 left open, and it is the last of them to close. Toggling the code
view **back off** assigns the record's own value straight into the editable::

    async toggleCodeView() {
        await this.commitChanges();
        this.state.showCodeView = !this.state.showCodeView;
        if (!this.state.showCodeView && this.editor) {
            this.editor.editable.innerHTML = this.value;   // <-- here
            this.editor.shared.history.addStep();
        }
    }

That is a sixth markup insertion with none of #210's five rules on it, so under
Ingress every root-relative URL in the record was fetched from the Home
Assistant root and answered 404 -- the same escape as the two onboarding
pictures of #210, on the same field, reached a different way.

What is pinned here:

- **Nothing is stored by it, and the test says so by executing the save.** The
  strip #210 put on ``updateValue`` removes a prefix and otherwise does
  nothing, so it is a no-op over a record that was never prefixed and takes
  this rule's prefix off again over one that was. The round trip below drives
  this site's own output into that method and reads back what the record got.
- **``IN_VALUE`` and not ``IN``, executed rather than argued.** ``get value()``
  returns ``markup(newVal)`` whenever the record's value is a ``Markup``, which
  it is for every html field, and #210's ``IN`` returns a non-string as it
  came. So a rule written with ``IN`` would have been a silent no-op at the one
  site it names: the test drives that rule and shows the pictures still
  fetched from the Home Assistant root. The getter is a captured fixture of its
  own, so the claim about the value's type is Odoo's own code and not a stub.
- **The screen, and the one shape of it that produces a false pass.** The
  button exists only where ``codeview: Boolean(odoo.debug && options.codeview)``
  is true. A value whose parse yields a non-empty ``<head>`` turns
  ``sandboxedPreview`` on, the field renders through the readonly
  ``HtmlViewer`` (#237) and ``this.editor`` is undefined, so the toggle runs
  and this site is never reached. That branch is driven here, because a Live
  check run on such a field would pass while testing nothing.
- **The counts.** An unmatched ``sub_filter`` is a silent no-op, so the pattern
  is counted in bytes derived from the pinned package through Odoo's own serve
  path, kept under ``fixtures/bundles/``; and a real nginx carrying this
  location's whole literal rule set is asked what it does to the excerpt, so
  "no other rule reaches it" is measured rather than assumed.
- **The code view's textarea stays untouched**, which is a decision and not an
  omission: ``t-att-value="this.value"`` is a source view, and it should show
  the bytes the record holds.
- **Ingress only**, and no new global: the three helpers of #210 and #237 are
  enough.
"""
import json
import re
from pathlib import Path

import pytest

from test_ingress_clipboard_fallback import INGRESS_PREFIX, directive_lines
from test_ingress_media_dialog_preselect import rules_reaching, served_by_nginx
from test_ingress_readonly_html_viewer import MARKUP_CLASS
from test_ingress_router_rewrite import TEMPLATE, ingress_rule, map_block
from test_ingress_todo_description import (
    HA_ORIGIN,
    HARNESS,
    node,
    rendered_shim,
)
from test_ingress_todo_description import fixture as todo_fixture
from test_ingress_todo_description import rewritten as todo_rewritten

FIXTURES = Path(__file__).resolve().parent / "fixtures/bundles"

MARKUP_MAP = "map $upstream_http_content_type $ingress_markup_global_shim {"
IN_GLOBAL = "__WOOW_INGRESS_MARKUP_IN__"
IN_VALUE_GLOBAL = "__WOOW_INGRESS_MARKUP_IN_VALUE__"
OUT_GLOBAL = "__WOOW_INGRESS_MARKUP_OUT__"

# The one rewrite, with the fixture its pattern was measured in.
REWRITES = {
    "code view": {
        "fixture": "html_field_toggle_code_view.js",
        "source": "this.editor.editable.innerHTML=this.value;",
        "occurrences": 1,
        "global": IN_VALUE_GLOBAL,
    },
}

# The dict is the shape every contract in this family uses, and the family's
# rewrites usually come in twos and threes; this issue has one, so the one entry
# is also named on its own for the helpers that are not parametrised.
REWRITE = REWRITES["code view"]
TOGGLE_FIXTURE = REWRITE["fixture"]

# Where the method starts in the served bytes, which is where every driver slices.
TOGGLE_ANCHOR = "async toggleCodeView(){"

# The getter the site reads through, captured because the central claim of this
# issue -- that the value here is an OWL `Markup` and so needs #237's helper --
# is a claim about Odoo's code and not about a stub of it.
VALUE_GETTER = "html_field_value_getter.js"

EXCERPTS = (TOGGLE_FIXTURE, VALUE_GETTER)

# The bundles the pattern was counted in, recorded with the zero counts in
# `fixtures/bundles/README.md`.
BUNDLES = (
    "web.assets_backend",
    "web.assets_web",
    "web.assets_web_print",
    "project.webclient",
)

# A user signature, which is the screen that reaches this site with one click:
# `base/views/res_users_views.xml` sets `options="{'codeview': true}"` on
# `res.users.signature` twice, and the value is a fragment, so no `<head>` and
# no sandboxed preview. One `src` and one `href`, because the markup helper
# prefixes both and the strip has to take both off again.
STORED = (
    "<p>Mitchell Admin</p>"
    '<img src="/web/image/res.company/1/logo" alt="logo"/>'
    '<p>Sent from <a href="/odoo/contacts">Odoo</a></p>'
)
SIGNATURE_PICTURE = "/web/image/res.company/1/logo"

PREFIXED = STORED.replace('src="/', 'src="%s/' % INGRESS_PREFIX).replace(
    'href="/', 'href="%s/' % INGRESS_PREFIX
)

# A full-HTML signature: a value whose parse has a non-empty `<head>`, which is
# what `computeContainsComplexHTML` tests and what turns `sandboxedPreview` on.
# Nothing about the markup matters here; what matters is that the field then
# renders readonly and `this.editor` is undefined.
FULL_HTML = (
    "<html><head><style>p{color:#714B67}</style></head><body>"
    '<img src="%s" alt="logo"/></body></html>' % SIGNATURE_PICTURE
)

# --- the node drivers ---------------------------------------------------------

# The three module-level helpers Odoo's own `get value()` closes over, which
# both drivers below splice that getter into. `fixInvalidHTML` is the identity
# here -- what it does to invalid markup is Odoo's business, the way #210's
# render driver has it -- and the other two are what the getter branches on.
GETTER_STUBS = r"""
const fixInvalidHTML = (value) => value;
const instanceofMarkup = (value) => value instanceof Markup;
const markup = (raw) => new Markup(raw);
"""

# The toggle, driven over one record value. The editable reports what the
# browser would fetch from what it was assigned, the way #210's render driver
# does, and also whether the value arrived still wrapped as a `Markup` -- which
# `innerHTML` does not care about, but which is the property that tells `IN`
# apart from `IN_VALUE` at this site.
TOGGLE_DRIVER = r"""
__MARKUP_CLASS__
__GETTER_STUBS__
const requested = [];
const steps = [];
let assigned = null;
let assignedWasMarkup = null;
const editable = {
  set innerHTML(html) {
    assigned = String(html);
    assignedWasMarkup = html instanceof Markup;
    requested.push(...requestedBy(html, PAGE));
  },
};
class HtmlField {
  constructor(raw, asMarkup, hasEditor) {
    this.props = { name: "signature", record: { data: { signature: value(raw, asMarkup) } } };
    this.state = { showCodeView: __SHOW_CODE_VIEW__, containsComplexHTML: false };
    this.htmlUpgradeManager = { processForUpgrade: (html) => html };
    this.env = {};
    this.committed = 0;
    this.editor = hasEditor
      ? { editable, shared: { history: { addStep() { steps.push("addStep"); } } } }
      : null;
  }
  async commitChanges() { this.committed++; }
__VALUE_GETTER__
__SLICE__
}
const field = new HtmlField(__RAW__, __AS_MARKUP__, __HAS_EDITOR__);
result = field.toggleCodeView().then(() => [
  requested,
  assigned,
  assignedWasMarkup,
  steps.length,
  field.state.showCodeView,
  field.committed,
]);
"""

# The round trip, in one realm: the toggle re-inserts the record's value into
# the editable, and then the field stores what the editable holds -- which is
# what `_commitChanges` does on the next blur. `updateValue` is #210's own
# rewritten bytes, so the strip under test here is the shipped one and not a
# copy of it.
ROUND_TRIP_DRIVER = r"""
__MARKUP_CLASS__
__GETTER_STUBS__
const stored = [];
let assigned = null;
const editable = {
  set innerHTML(html) { assigned = String(html); },
};
const normalizeHTML = (value) => "N(" + value + ")";
class HtmlField {
  constructor(raw, asMarkup) {
    this.lastChangeId = 0;
    this.isDirty = true;
    this.state = { showCodeView: true, containsComplexHTML: false };
    this.htmlUpgradeManager = { processForUpgrade: (html) => html };
    this.env = {};
    this.props = {
      name: "signature",
      record: {
        data: { signature: value(raw, asMarkup) },
        update(values) { stored.push(values.signature); return Promise.resolve(); },
        model: { bus: { trigger() {} } },
      },
    };
    this.editor = { editable, shared: { history: { addStep() {} } } };
  }
  async commitChanges() {}
  clearElementToCompare() {}
__VALUE_GETTER__
__TOGGLE__
__UPDATE_VALUE__
}
const field = new HtmlField(__RAW__, true);
result = field
  .toggleCodeView()
  .then(() => field.updateValue(assigned))
  .then(() => [assigned, stored[0], field.lastValue]);
"""


# --- helpers ------------------------------------------------------------------

def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def replacement() -> str:
    """The shipped replacement for the rewrite, read out of the template."""
    found = ingress_rule(template(), REWRITE["source"], TOGGLE_FIXTURE)
    assert REWRITE["global"] in found, (
        f"the rewrite must go through {REWRITE['global']}, the helper the shim publishes"
    )
    return found


def as_served() -> str:
    """The fixture as the Ingress asset location serves it."""
    return fixture(TOGGLE_FIXTURE).replace(REWRITE["source"], replacement())


def as_served_through_the_plain_in() -> str:
    """The same site rewritten through #210's ``IN``, for a controlled test.

    This is the rule this issue did *not* ship, so the reason ``IN_VALUE``
    exists can be executed rather than asserted.
    """
    swapped = replacement().replace(IN_VALUE_GLOBAL, IN_GLOBAL)
    return fixture(TOGGLE_FIXTURE).replace(REWRITE["source"], swapped)


def method_body(text: str, anchor: str) -> str:
    """One method of an excerpt, from its anchor to the end of the excerpt.

    Each fixture is a verbatim region that *starts* at the method under test
    (`test_the_fixtures_are_verbatim_regions` holds that), so the tail is the
    method; #210's fixtures are regions with a preamble, which is why the
    anchor is passed in.
    """
    return text[text.index(anchor):].rstrip()


def toggle_program(
    text: str,
    raw: str,
    as_markup: bool = True,
    has_editor: bool = True,
    showing_code_view: bool = True,
) -> str:
    """The fixture's `toggleCodeView`, driven over one record value.

    `showing_code_view` is the state the toggle is pressed in: `True` is the
    way *off*, which is this issue's site, and `False` the way on, which
    reaches no markup.
    """
    return (
        TOGGLE_DRIVER.replace("__MARKUP_CLASS__", MARKUP_CLASS)
        .replace("__GETTER_STUBS__", GETTER_STUBS)
        .replace("__VALUE_GETTER__", fixture(VALUE_GETTER).rstrip())
        .replace("__SLICE__", method_body(text, TOGGLE_ANCHOR))
        .replace("__RAW__", json.dumps(raw))
        .replace("__AS_MARKUP__", "true" if as_markup else "false")
        .replace("__HAS_EDITOR__", "true" if has_editor else "false")
        .replace("__SHOW_CODE_VIEW__", "true" if showing_code_view else "false")
    )


def round_trip_program(toggle: str, update_value: str, raw: str) -> str:
    """The toggle's own output, driven into the save site #210 rewrote."""
    return (
        ROUND_TRIP_DRIVER.replace("__MARKUP_CLASS__", MARKUP_CLASS)
        .replace("__GETTER_STUBS__", GETTER_STUBS)
        .replace("__VALUE_GETTER__", fixture(VALUE_GETTER).rstrip())
        .replace("__TOGGLE__", method_body(toggle, TOGGLE_ANCHOR))
        .replace("__UPDATE_VALUE__", method_body(update_value, "async updateValue("))
        .replace("__RAW__", json.dumps(raw))
    )


def case(name: str, program: str, expected, shim: bool = True) -> dict:
    return {
        "name": name,
        "shim": rendered_shim(INGRESS_PREFIX) if shim else "",
        "program": program,
        "expected": expected,
    }


def toggled(
    requested=(),
    assigned=None,
    was_markup=None,
    steps=1,
    show=False,
    committed=1,
) -> list:
    """What the toggle driver reports, in its own order.

    The defaults are the *nothing happened* case -- no fetch, no assignment, no
    history step -- because a test about a site that is not reached names only
    what it expects to see.
    """
    return [list(requested), assigned, was_markup, steps, show, committed]


def under_prefix(*paths: str) -> list:
    return [HA_ORIGIN + INGRESS_PREFIX + path for path in paths]


def at_the_ha_root(*paths: str) -> list:
    return [HA_ORIGIN + path for path in paths]


# --- the rewrite --------------------------------------------------------------

@pytest.mark.parametrize("name", REWRITES)
def test_the_rewrite_matches_the_bundle_the_expected_number_of_times(name: str) -> None:
    """A pattern that does not match is a silent no-op, so measure it."""
    rewrite = REWRITES[name]
    found = fixture(rewrite["fixture"]).count(rewrite["source"])
    assert found == rewrite["occurrences"], (
        f"{name}: {rewrite['fixture']} holds {found} occurrences of {rewrite['source']!r}, "
        f"expected {rewrite['occurrences']}; re-derive the fixture and re-measure the rewrite"
    )


@pytest.mark.parametrize("name", REWRITES)
def test_every_rewrite_is_ingress_only(name: str) -> None:
    """A rule on the 8069 listener would change what the Public origin serves."""
    ingress_rule(template(), REWRITES[name]["source"], name)


def test_the_rewrite_goes_through_the_value_helper_and_nothing_else() -> None:
    """`IN` would be a silent no-op here, and an `OUT` would be a claim about
    nothing: this site renders, it does not store."""
    found = replacement()
    assert IN_VALUE_GLOBAL in found
    assert OUT_GLOBAL not in found, (
        "the code view's re-insertion stores nothing, so there is nothing to strip; the field's "
        "own writes go through #210's rules 2 and 5"
    )
    assert IN_GLOBAL + "(" not in found, (
        f"the plain {IN_GLOBAL} returns a non-string as it came, and the value at this site is "
        "an OWL Markup -- see test_the_plain_markup_helper_would_be_a_silent_no_op_here"
    )
    assert "function(h){return h}" in found, (
        "this is JavaScript and not an OWL template expression, so the fallback is the same "
        "function literal #210's five rules use"
    )


def test_the_rewrite_introduces_no_new_global() -> None:
    """Three helpers, and the last site of this family needs none of its own."""
    markup_map = map_block(template(), MARKUP_MAP)
    published = re.findall(r'mP\("(__WOOW_[A-Z_]+)"', markup_map)
    assert published == [IN_GLOBAL, IN_VALUE_GLOBAL, OUT_GLOBAL], (
        "the markup map must publish exactly #210's two helpers and #237's third; the code "
        f"view's re-insertion is an insertion of a record value like the others: found {published}"
    )


def test_the_rewrite_names_nothing_route_scoped() -> None:
    """Still the render site, not the response the field also saves through."""
    text = template()
    for forbidden in ("/web/dataset/call_kw", "res.users", "web_read"):
        offenders = [number for number, line in directive_lines(text) if forbidden in line]
        assert not offenders, (
            f"no directive may name {forbidden!r} (found on lines {offenders}): rewriting the "
            "response the HTML editor also saves through is what ADR 0004 decided against"
        )


def test_no_sub_filter_prefixes_the_code_views_own_textarea() -> None:
    """A decision, not an omission: the source view shows the record's bytes.

    ``<textarea t-ref="codeView" class="o_codeview" t-att-value="this.value"/>``
    is the code view itself. Prefixing it would make the source view lie about
    what is stored on the one render where it is right, which is the same
    choice #238 made for the legacy editor's textarea.
    """
    offenders = [
        number
        for number, line in directive_lines(template())
        if 't-att-value="this.value"' in line or "o_codeview" in line
    ]
    assert not offenders, (
        f"lines {offenders} rewrite the code view's textarea; it is a source view and must show "
        "the bytes the record holds"
    )


# --- what the browser receives ------------------------------------------------

def test_no_other_rule_of_this_location_reaches_the_excerpt() -> None:
    """So applying one rule by hand is the same as what the gateway serves."""
    own = {rewrite["source"] for rewrite in REWRITES.values()}
    for name in EXCERPTS:
        reaching = rules_reaching(fixture(name), own)
        assert reaching == {}, (
            f"{name}: no other literal rule of this location may reach this excerpt, found "
            f"{reaching}; one that did would change bytes the drivers below execute"
        )


def test_a_real_nginx_agrees_about_what_the_excerpt_becomes(tmp_path: Path) -> None:
    """The scan above, executed: the rules applied by nginx, not `str.replace`.

    Every driver below runs on `as_served`, which applies this issue's rule
    with `str.replace`. This is what says the two are the same thing, with the
    whole literal rule set of the location in the way.
    """
    answers = served_by_nginx(tmp_path, {name: fixture(name) for name in EXCERPTS})
    assert answers[("assets", TOGGLE_FIXTURE)] == as_served(), (
        "nginx and `as_served` must agree byte for byte about what this location serves; they "
        "do not, so every driver below is running on bytes the browser does not get"
    )
    assert answers[("assets", VALUE_GETTER)] == fixture(VALUE_GETTER), (
        "the getter is served unchanged: it holds no URL and no rule of this location reaches it"
    )


# --- the site itself ----------------------------------------------------------

def test_the_signature_is_fetched_from_the_home_assistant_root_without_the_rewrite() -> None:
    """The starting point: the bundle as Odoo ships it, run under Ingress."""
    run = [
        case(
            "toggle off, as Odoo ships it",
            toggle_program(fixture(TOGGLE_FIXTURE), STORED),
            toggled(at_the_ha_root(SIGNATURE_PICTURE), STORED, was_markup=True),
        )
    ]
    node(HARNESS, run)


def test_the_rewrite_renders_the_re_inserted_markup_under_the_ingress_prefix() -> None:
    """The fix: the same toggle, the picture fetched through the prefix.

    The `href` beside it is prefixed too -- the markup helper's attribute list
    is `src`/`href`/`action`/`data-src` -- which is what the save half below
    has to take off again.
    """
    node(HARNESS, [
        case(
            "toggle off, under Ingress",
            toggle_program(as_served(), STORED),
            toggled(under_prefix(SIGNATURE_PICTURE), PREFIXED, was_markup=True),
        )
    ])


def test_the_plain_markup_helper_would_be_a_silent_no_op_here() -> None:
    """Why the rule calls #237's helper, executed rather than asserted.

    `get value()` returns `markup(newVal)` when the record's value is a
    `Markup`, and every html field's is. #210's `IN` tests
    `typeof h === "string"` and returns anything else as it came -- so the rule
    this test drives would have shipped, matched its pattern, changed the
    bytes, and left the picture exactly where it was.
    """
    node(HARNESS, [
        case(
            "toggle off, rewritten through the plain IN",
            toggle_program(as_served_through_the_plain_in(), STORED),
            toggled(at_the_ha_root(SIGNATURE_PICTURE), STORED, was_markup=True),
        )
    ])


def test_a_primitive_string_value_is_prefixed_too() -> None:
    """One helper for both shapes, as `innerHTML` takes a string as markup.

    No shipped caller passes one -- `get value()` returns a `Markup` whenever
    the record's value is one -- but the helper is the same helper, and the
    `Markup` flag below is what the two cases differ in.
    """
    node(HARNESS, [
        case(
            "toggle off, a primitive string value",
            toggle_program(as_served(), STORED, as_markup=False),
            toggled(under_prefix(SIGNATURE_PICTURE), PREFIXED, was_markup=False),
        )
    ])


def test_without_the_globals_the_toggle_inserts_the_raw_value() -> None:
    """An Ingress page whose shim did not run must still render, not throw."""
    node(HARNESS, [
        case(
            "toggle off, with no Runtime shim",
            toggle_program(as_served(), STORED),
            toggled(at_the_ha_root(SIGNATURE_PICTURE), STORED, was_markup=True),
            shim=False,
        )
    ])


def test_the_toggle_is_unchanged_on_the_public_origin() -> None:
    """ADR 0003's control group gets Odoo's bytes and must keep working."""
    node(HARNESS, [
        case(
            "toggle off, public origin",
            toggle_program(fixture(TOGGLE_FIXTURE), STORED),
            toggled(at_the_ha_root(SIGNATURE_PICTURE), STORED, was_markup=True),
            shim=False,
        )
    ])


def test_toggling_the_code_view_on_touches_no_markup() -> None:
    """The other direction reaches nothing: the guard is `!showCodeView`.

    Driven because it is half of what a Live check does, and because it is the
    reason this issue is a render escape on one toggle rather than on both: the
    textarea the other direction renders is `this.value`, which no rule here
    touches.
    """
    node(HARNESS, [
        case(
            "toggle on, under Ingress",
            toggle_program(as_served(), STORED, showing_code_view=False),
            toggled(steps=0, show=True),
        )
    ])


def test_a_full_html_value_never_reaches_this_site() -> None:
    """The shape of field that produces a false pass, driven on purpose.

    A value whose parse yields a non-empty `<head>` turns `sandboxedPreview`
    on (`computeContainsComplexHTML`), the field renders through the readonly
    `HtmlViewer` -- #237's two rules, not this one -- and there is no `Wysiwyg`,
    so `this.editor` is undefined. The toggle then flips the state, assigns
    nothing and must not throw. A Live check run on such a field would pass
    while testing nothing, which is why this is executed here.
    """
    node(HARNESS, [
        case(
            "toggle off with no editor, under Ingress",
            toggle_program(as_served(), FULL_HTML, has_editor=False),
            toggled(steps=0, show=False),
        )
    ])


# --- the save half, which this change must leave exactly as it was -------------

def test_the_value_the_code_view_re_inserts_is_stored_root_relative() -> None:
    """The round trip, in one realm: this rule's output into #210's strip.

    `_commitChanges` stores what the editable holds, so the value this site
    prefixed is the value the field saves on the next blur. #210's rule 2 is
    the strip on that path, and it is driven here on its shipped bytes rather
    than re-stated: the record must get the markup it started with, and
    `lastValue` must be computed from the value that was stored.
    """
    node(HARNESS, [
        case(
            "re-insert, then save",
            round_trip_program(as_served(), todo_rewritten("save"), STORED),
            [PREFIXED, STORED, "N(%s)" % STORED],
        )
    ])


def test_the_strip_is_a_no_op_over_a_value_this_change_never_prefixed() -> None:
    """The same path with no shim: nothing is prefixed and nothing is removed.

    The strip only *removes* a prefix, so over content that was never prefixed
    it changes nothing -- which is what makes this issue a render escape and
    not a token write in either direction.
    """
    node(HARNESS, [
        case(
            "re-insert with no shim, then save",
            round_trip_program(as_served(), todo_rewritten("save"), STORED),
            [STORED, STORED, "N(%s)" % STORED],
            shim=False,
        )
    ])


def test_without_the_save_strip_the_prefix_would_reach_the_record() -> None:
    """Why the save half is a dependency and not a remark.

    Odoo's own `updateValue` beside this rule's output stores the Supervisor
    token, which is the harm ADR 0004 names. #210 is what stands between this
    rule and the database, and this is the controlled comparison that says so.
    """
    node(HARNESS, [
        case(
            "re-insert, then save through Odoo's own updateValue",
            round_trip_program(as_served(), todo_fixture("save"), STORED),
            [PREFIXED, PREFIXED, "N(%s)" % PREFIXED],
        )
    ])


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


def test_the_readme_records_every_bundle_the_pattern_was_counted_in() -> None:
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    for name in EXCERPTS:
        assert name in readme, f"fixtures/bundles/README.md must name {name}"
    for bundle in BUNDLES:
        assert bundle in readme, (
            f"fixtures/bundles/README.md must record what {bundle} carries; the tests execute "
            "the claim, the README is where a reader finds the per-bundle counts"
        )


def test_the_fixtures_are_verbatim_regions() -> None:
    """Each excerpt is bundle bytes, so it must start and end where it says."""
    toggle = fixture(TOGGLE_FIXTURE)
    assert toggle.startswith("async toggleCodeView(){await this.commitChanges();")
    assert toggle.rstrip().endswith("this.editor.shared.history.addStep();}}")
    getter = fixture(VALUE_GETTER)
    assert getter.startswith("get value(){const value=this.props.record.data[this.props.name];")
    assert getter.rstrip().endswith("return newVal;}")
    assert "if(instanceofMarkup(value)){return markup(newVal);}" in getter, (
        "the getter is captured for the one line that decides which helper the rewrite calls"
    )
    # rjsmin keeps the line break Odoo's source has before the second `return`,
    # so the getter as served spans two lines. The rewritten expression is on
    # neither of them, which is why the pattern is still one line.
    assert len(getter.rstrip().splitlines()) == 2
    assert len(toggle.rstrip().splitlines()) == 1
