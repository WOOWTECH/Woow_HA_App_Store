#!/usr/bin/env python3
"""Contracts for the ORM *search patterns* in the media dialogs (issue #271).

The class, and it is the finding rather than the one literal: **a generic
literal rewrite reaches ORM domain literals, not only URLs.** The Ingress asset
location has prefixed `"/web/`-opening string literals since #166 because
almost every one of them is an address. `nginx`'s `sub_filter` is a byte-level
substring search with no idea what a literal is *for*, so it also prefixed
`'/web/assets/%'` -- the `=like` operand `DocumentSelector.attachmentsDomain`
excludes generated asset bundles with, naming the reason in its own comment.

The exclusion then reads `NOT (url =like '<prefix>/web/assets/%')`, which
matches no stored `url` -- every generated bundle attachment is
`/web/assets/...` in the database -- so the `'|' ['url','=',null]` beside it let
every bundle through. #266 measured the result on Release 0.4.10: the Documents
tab listed **30** tiles under Ingress (the page limit, filled with
`mass_mailing.assets_wysiwyg.min.js` and its siblings) against **1** on the
Public origin, with the served getter 383 bytes against 320 -- exactly one
prefix insertion. Nothing is stored: the domain travels in a request body, and
that run's `stored_verdict` was `CLEAN` on both surfaces. It is a wrong list in
a picker, which is why the parity plan registers it as `G-09` at `minor`.

What is pinned here:

- **Six pattern literals, measured, not four.** The issue named four. Counting
  the served bytes of every `*/static/src/**/*.js` file in the pinned package
  found that quote style is per *site* and not per file, so the four are six
  occurrences-as-bytes -- and that a third selector carries three of them:
  `FileDocumentsSelector`, `html_editor`'s compatibility shim for the `/file`
  command, whose own header says it is no longer used. Every count is in
  `fixtures/bundles/README.md` beside the fixtures.
- **Two of the six were reached by a shipped rule, and which two is the
  measurement.** The double- and single-quoted `/web/assets/%` of the two
  document selectors. `/html_editor/shape/%`, `/web_editor/shape/%` and
  `/%/static/%` are reached by nothing -- `/web_editor/` survives because the
  rule needs `/web/` and it has `_` where the rule has `/` -- so they ship no
  counter-rule, and they are held here anyway so that a future generic rule
  which starts claiming one turns this file red instead of silently changing a
  picker.
- **The fix is an explicit counter-rule per site, not a narrower generic
  rule** (ADR 0004's 2026-10-02 postscript). Each is its own pattern spelled as
  its own replacement: the job is to claim those bytes before a generic rule
  can. `sub_filter` tracks one match attempt at a time, so the pattern starting
  at the earlier byte wins; #158 pins the other half, that two patterns
  starting at the *same* byte go by written order. The rules sit ahead of the
  generic ones so the fix holds under either half, and both halves are executed
  below by a real nginx rather than argued.
- **Identity, so the Live reading stays legible.** The check's probe asks
  `domain.includes("/web/assets/")`, so the reading that shows this fixed is
  "the literal is there and carries no prefix". A split spelling
  (`"/web"+"/assets/%"`) would survive the same way and make that field read
  `false`, which is a worse answer to the same question.
- **Nothing about URL rewriting changes.** The last test serves a sample
  carrying a pattern literal *and* a real URL literal through the same rules
  and requires the URL to keep its prefix.

The ordering the fix leans on is a property of `ngx_http_sub_filter_module` and
not of the config, so it is worth saying which nginx measured it. The add-on
ships Debian bookworm's `1.22.1`, which is also what the development container
has; CI installs Ubuntu's `nginx-core`, a different build and usually a later
version, and runs the same tests -- so the claim is checked on two nginxes
rather than one, and a release that resolved overlapping patterns differently
would turn one of them red. What the Build tier adds is not a third serve:
`in_image/gateway_config_loads.py` loads the rendered config with the image's
own nginx, which proves the rules parse there and nothing about how they
resolve. That is the limit of the guarantee, and what makes it tolerable is the
failure mode -- a wrong picker list, not a silent escape -- together with
`media-document-mailing`, which reads the served getter off the real host on
every run.
"""
import json
import re
import socket
import subprocess
from pathlib import Path

import pytest

from conftest import require_tool
from test_ingress_clipboard_fallback import INGRESS_PREFIX, directive_lines
from test_ingress_media_dialog_preselect import (
    FIXTURES,
    _fetch,
    fixture,
    location_rules,
    served_by_nginx,
    shipped_rules,
    template,
)
from test_ingress_router_rewrite import TEMPLATE, ingress_assets_block

# --- the six literals, as bytes -----------------------------------------------

# name -> (the served bytes, whether a counter-rule is shipped for it)
LITERALS = {
    "web assets, double": ('["url","=like","/web/assets/%"]', True),
    "web assets, single": ("['url','=like','/web/assets/%']", True),
    "html_editor shape": ('["url","=ilike","/html_editor/shape/%"]', False),
    "web_editor shape": ('["url","=ilike","/web_editor/shape/%"]', False),
    "any static, double": ('["url","=like","/%/static/%"]', False),
    "any static, single": ("['url','=like','/%/static/%']", False),
}

COUNTERED = tuple(name for name, (_, countered) in LITERALS.items() if countered)
LEFT_ALONE = tuple(name for name, (_, countered) in LITERALS.items() if not countered)

# Each captured `attachmentsDomain` getter, and which literals it carries how
# many times. The quote styles are the point: the legacy `web_editor` image
# selector writes its two shape literals *double*-quoted while writing
# `/%/static/%` single-quoted, so "one literal per dialog" is the wrong unit.
FIXTURE_LITERALS = {
    "media_dialog_document_domain.js": {"web assets, double": 1},
    "legacy_media_dialog_document_domain.js": {"web assets, single": 1},
    "media_dialog_image_domain.js": {
        "html_editor shape": 1,
        "web_editor shape": 1,
        "any static, double": 1,
    },
    "legacy_media_dialog_image_domain.js": {
        "html_editor shape": 1,
        "web_editor shape": 1,
        "any static, single": 1,
    },
    # The third selector, found by the measurement and not by the issue. Its
    # three literals are byte-identical to the image selectors', so the rows
    # above already stand for them; it is captured because it is the reason a
    # bundle carries three occurrences of a shape literal and not two, and
    # because it inherits the document getter's `/web/assets/%` through
    # `super.attachmentsDomain` rather than spelling one of its own.
    "file_documents_selector_domain.js": {
        "html_editor shape": 1,
        "web_editor shape": 1,
        "any static, double": 1,
    },
}

DOCUMENT_FIXTURES = (
    "media_dialog_document_domain.js",
    "legacy_media_dialog_document_domain.js",
)
IMAGE_FIXTURES = (
    "media_dialog_image_domain.js",
    "legacy_media_dialog_image_domain.js",
    "file_documents_selector_domain.js",
)
ALL_FIXTURES = DOCUMENT_FIXTURES + IMAGE_FIXTURES

# The generic rules that reached the two document literals before the fix. The
# patterns only: what each does is read out of the template.
GENERIC_WEB_RULES = ('"/web/', "'/web/")

# The bundles the counts were taken in, recorded in `fixtures/bundles/README.md`
# with the zero counts beside them.
BUNDLES = (
    "web.assets_backend",
    "web.assets_web",
    "web.assets_web_print",
    "web.assets_frontend",
    "web.assets_frontend_lazy",
    "html_editor.assets_media_dialog",
    "web_editor.assets_media_dialog",
    "project.webclient",
)

# A stored `url` of each kind the exclusion is about. `ir.attachment` rows for
# generated bundles carry `/web/assets/<version>/<name>` (see
# `_get_asset_template_url`); a document a user uploaded carries no `url` at
# all, which is the `['url', '=', null]` branch the exclusion `|`s with.
BUNDLE_URL = "/web/assets/1/ab12cd34/mass_mailing.assets_wysiwyg.min.js"
SHAPE_URL = "/html_editor/shape/geometric/geo_shuriken.svg"
MODULE_STATIC_URL = "/website/static/src/img/snippets_demo/s_banner.jpg"


def attachments() -> list:
    """The rows the Documents tab is choosing between, as the ORM returns them."""
    return [
        {
            "id": 7, "name": "contract.pdf", "url": None, "type": "binary",
            "public": False, "res_model": "mailing.mailing", "res_id": 5,
            "mimetype": "application/pdf", "description": False,
        },
        {
            "id": 101, "name": "mass_mailing.assets_wysiwyg.min.js",
            "url": BUNDLE_URL, "type": "binary", "public": True,
            "res_model": "ir.ui.view", "res_id": 0,
            "mimetype": "text/javascript", "description": False,
        },
        {
            "id": 102, "name": "web_editor.wysiwyg_iframe_editor_assets.min.css",
            "url": "/web/assets/2/ef56ab78/web_editor.wysiwyg_iframe_editor_assets.min.css",
            "type": "binary", "public": True, "res_model": "ir.ui.view", "res_id": 0,
            "mimetype": "text/css", "description": False,
        },
    ]


WANTED_ID = 7
BUNDLE_IDS = (101, 102)


# --- a model of the ORM, narrow on purpose ------------------------------------

def normalize_domain(domain: list) -> list:
    """Odoo's own `normalize_domain`, so the model reads a domain as Odoo does.

    Ported from `osv/expression.py` in the pinned package: a domain is a list
    of leaves with an *implicit* `&`, and the operators are prefix. The getters
    here `unshift` an `'&'` in front of a `'|'` and then `push` four more
    leaves, so reading the list naively gets a different answer from the
    server's -- which would make every count below meaningless.
    """
    result = []
    expected = 1
    arity = {"!": 1, "&": 2, "|": 2}
    for token in domain:
        if expected == 0:
            result[0:0] = ["&"]
            expected = 1
        if isinstance(token, (list, tuple)):
            expected -= 1
        else:
            expected += arity.get(token, 0) - 1
        result.append(token)
    assert expected == 0, f"domain {domain} is syntactically not correct"
    return result


def like_to_re(operand: str, *, bare: bool, insensitive: bool) -> re.Pattern:
    """SQL `LIKE` as a regex: `%` is any run, `_` is one character.

    `bare` is the `=like`/`=ilike` family, whose operand is the whole pattern;
    the plain `like`/`ilike` family wraps it in `%...%`, which is why the
    exclusion is written `=like` and not `like`.
    """
    pattern = "".join(
        ".*" if char == "%" else "." if char == "_" else re.escape(char)
        for char in operand
    )
    if not bare:
        pattern = ".*" + pattern + ".*"
    return re.compile("^" + pattern + "$", re.DOTALL | (re.I if insensitive else 0))


NEGATIVE = ("!=", "not like", "not ilike", "not in")
WILDCARD = ("like", "ilike", "not like", "not ilike")
EMPTY = (None, False, "")


def leaf(condition, record) -> bool:
    """One domain leaf, as `models._condition_to_sql` would ask Postgres it.

    Two of its rules decide every count in this file and neither is what a
    reader would write from scratch, so both are spelled out here:

    - **A negative operator with a truthy operand also passes on NULL.** The
      generator adds `OR <field> IS NULL` exactly when
      `bool(value) == (operator in NEGATIVE_TERM_OPERATORS)`, so
      `['description', 'not like', 'CSS font face for']` is *true* of a row
      with no description -- which is every row here. Read naively (Postgres's
      own `NULL NOT LIKE x` is NULL, so false) the document getter would list
      nothing at all and the measurement would be of the model and not of the
      gateway.
    - **A positive `=like` with a truthy operand does not.** No `IS NULL` is
      added, so a row with no `url` fails `url =like '/web/assets/%'` -- which
      is why the exclusion needs the `'|' ['url', '=', null]` beside it, and
      why a prefixed exclusion lets everything through rather than nothing.
    """
    field, operator, operand = condition
    value = record.get(field)
    nulls_pass = operator in NEGATIVE and bool(operand)
    if operator == "=":
        # A char field compared with False is compared with '' as well.
        if operand in EMPTY:
            return value in EMPTY
        return value == operand
    if operator == "!=":
        if value in EMPTY:
            return nulls_pass or operand not in EMPTY
        return value != operand
    if operator in ("in", "not in"):
        if value in EMPTY and nulls_pass:
            return True
        return (value in operand) if operator == "in" else (value not in operand)
    if operator in ("=like", "=ilike") + WILDCARD:
        if operator in WILDCARD and not operand:
            # `like ''` is dropped entirely: TRUE for a positive operator and
            # FALSE for a negative one, whatever the row holds. This is the
            # search box with nothing typed in it.
            return operator not in NEGATIVE
        if value in EMPTY:
            return nulls_pass
        matched = bool(
            like_to_re(
                operand,
                bare=operator.startswith("="),
                insensitive="ilike" in operator,
            ).match(value)
        )
        return not matched if operator.startswith("not ") else matched
    raise AssertionError(f"the model does not implement {operator!r}")


def matches(domain: list, record) -> bool:
    tokens = list(normalize_domain(domain))

    def read() -> bool:
        token = tokens.pop(0)
        if token == "!":
            return not read()
        if token in ("&", "|"):
            left, right = read(), read()
            return (left and right) if token == "&" else (left or right)
        return leaf(token, record)

    answer = read()
    assert not tokens, f"trailing tokens in {domain}"
    return answer


def listed(domain: list) -> list:
    """Which attachment ids the Documents tab would show for this domain."""
    return [row["id"] for row in attachments() if matches(domain, row)]


# --- the getters, executed ----------------------------------------------------

# The base getter is `FileSelector.attachmentsDomain`, a stand-in written to the
# shape the pinned package has -- it is scaffolding, not the thing measured. The
# captured region is spliced in as the subclass's own getter, which is what
# `super` then reaches past.
DOMAIN_DRIVER = r"""
const IMAGE_MIMETYPES = ["image/jpg", "image/jpeg", "image/png", "image/svg+xml"];
class FileSelector {
  constructor() {
    this.props = { resModel: "mailing.mailing", resId: 5, useMediaLibrary: false,
                   media: { dataset: {} } };
    this.state = { needle: "" };
    this.env = { debug: false };
  }
  get attachmentsDomain() {
    const domain = ["&", ["res_model", "=", this.props.resModel],
                         ["res_id", "=", this.props.resId || 0]];
    domain.unshift("|", ["public", "=", true]);
    domain.push(["name", "ilike", this.state.needle]);
    return domain;
  }
}
class Selector extends FileSelector {
__SLICE__
}
result = new Selector().attachmentsDomain;
"""

# The family's node harness, with the one difference this file needs: the
# question here is *what domain the getter produced*, so each case's value comes
# back as JSON instead of being compared with an expectation inside node. No
# shim is rendered into the context -- an `attachmentsDomain` getter touches no
# global the shim publishes, and that is part of the point: this divergence is
# the gateway's alone.
DOMAIN_HARNESS = r"""
const vm = require("node:vm");
const payload = JSON.parse(process.argv[1]);
const out = [];
for (const { program } of payload) {
  const context = { result: undefined };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(program, context);
  out.push(context.result);
}
process.stdout.write(JSON.stringify(out));
"""


def program(text: str) -> str:
    """One captured getter, spliced into the driver."""
    region = text[text.index("get attachmentsDomain(){"):].rstrip()
    return DOMAIN_DRIVER.replace("__SLICE__", region)


def domains(texts: list) -> list:
    """Run each getter in node and return the domains they built."""
    result = subprocess.run(
        [require_tool("node"), "-e", DOMAIN_HARNESS,
         json.dumps([{"program": program(text)} for text in texts])],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


# --- the rules ----------------------------------------------------------------

def counter_rules() -> list:
    """The `sub_filter` pairs whose pattern is a pattern literal of this family."""
    return [
        (pattern, replacement)
        for pattern, replacement in shipped_rules(template())
        if pattern.startswith(("[\"url\"", "['url'"))
    ]


def rules_before(pattern: str) -> list:
    """Every rule of the Ingress asset location written ahead of `pattern`."""
    rules = shipped_rules(template())
    index = [number for number, (shipped, _) in enumerate(rules) if shipped == pattern]
    assert len(index) == 1, f"{pattern!r} must be shipped exactly once, found {len(index)}"
    return [shipped for shipped, _ in rules[: index[0]]]


def without_counter_rules(lines: list) -> list:
    """The location's rule set with this issue's own rules taken back out."""
    patterns = {pattern for pattern, _ in counter_rules()}
    kept = [
        line for line in lines
        if not any("sub_filter '%s'" % p in line or 'sub_filter "%s"' % p in line
                   for p in patterns)
    ]
    assert len(kept) == len(lines) - len(patterns), (
        "the before-the-fix rule set must drop exactly this issue's own rules"
    )
    return kept


def test_each_countered_literal_ships_one_identity_rule() -> None:
    """Identity: the whole job is to claim the bytes, not to change them."""
    shipped = dict(counter_rules())
    expected = {LITERALS[name][0] for name in COUNTERED}
    assert set(shipped) == expected, (
        f"expected a counter-rule for exactly {sorted(expected)}, found {sorted(shipped)}"
    )
    for pattern, replacement in shipped.items():
        assert replacement == pattern, (
            f"{pattern!r} must be replaced by itself: a replacement that changed the bytes "
            "would also change what the Live probe's `includes(\"/web/assets/\")` reads"
        )
        assert "$" not in pattern, (
            "nginx reads `$` in a parameter as a variable and there is no escape for it"
        )


def test_no_counter_rule_is_shipped_for_a_literal_no_rule_reaches() -> None:
    """A rule nobody could see is worse than no rule: it reads as cover."""
    shipped = {pattern for pattern, _ in counter_rules()}
    for name in LEFT_ALONE:
        source, _ = LITERALS[name]
        assert source not in shipped, (
            f"{name}: no generic rule reaches this literal, so a counter-rule for it is a "
            "no-op that a reader would mistake for protection -- the real-nginx test below "
            "is what keeps it honest"
        )


def test_the_counter_rules_sit_ahead_of_the_generic_literal_rules() -> None:
    """So the fix holds under both halves of the ordering rule.

    A pattern starting at an earlier byte wins on its own, which is why this
    works at all; but two patterns starting at the *same* byte are resolved by
    written order (#158), and keeping these first means nothing about the fix
    depends on which half of that rule is doing the work.
    """
    for pattern, _ in counter_rules():
        earlier = rules_before(pattern)
        for generic in GENERIC_WEB_RULES:
            assert generic not in earlier, (
                f"{pattern!r} must be written before the generic {generic!r} rule"
            )


def test_the_counter_rules_are_ingress_only() -> None:
    """A rule on the 8069 listener would change what the Public origin serves."""
    text = template()
    start, end = ingress_assets_block(text)
    for pattern, _ in counter_rules():
        occurrences = [
            number for number, line in directive_lines(text)
            if "sub_filter" in line and pattern in line
        ]
        assert len(occurrences) == 1, (
            f"{pattern!r} must be shipped once, found it on lines {occurrences}"
        )
        inside = text[start:end].count(pattern)
        assert inside == 2, (
            f"{pattern!r} must occur twice inside the Ingress asset location -- once as the "
            f"pattern and once as the replacement -- found {inside}"
        )
        assert text.count(pattern) == inside, (
            f"{pattern!r} must appear nowhere else in the template (ADR 0003: a rule outside "
            "this location could reach the Public listener)"
        )


# --- the literals, counted ----------------------------------------------------

@pytest.mark.parametrize("name", FIXTURE_LITERALS)
def test_each_fixture_carries_the_literals_it_was_measured_for(name: str) -> None:
    """An unmatched `sub_filter` is a silent no-op, so count the bytes."""
    text = fixture(name)
    found = {
        label: text.count(source)
        for label, (source, _) in LITERALS.items()
        if text.count(source)
    }
    assert found == FIXTURE_LITERALS[name], (
        f"{name}: carries {found}, expected {FIXTURE_LITERALS[name]}; re-derive the fixture "
        "from the pinned package and re-measure before touching a rule"
    )


@pytest.mark.parametrize("name", LITERALS)
def test_every_literal_is_carried_by_some_fixture(name: str) -> None:
    """So a literal cannot be named in the rules and measured nowhere."""
    carried = [
        label for label, literals in FIXTURE_LITERALS.items() if name in literals
    ]
    assert carried, f"{name}: no captured getter carries this literal"


@pytest.mark.parametrize("name", COUNTERED)
def test_the_generic_rule_that_reached_each_countered_literal(name: str) -> None:
    """The measurement the decision rests on, as a containment scan.

    Exactly one generic rule of this location occurs inside each of the two
    `/web/assets/%` literals, and it is the `/web/` literal rule of its own
    quote style. The real-nginx tests below are the executed version.
    """
    source, _ = LITERALS[name]
    counter = {pattern for pattern, _ in counter_rules()}
    reaching = {
        pattern: source.count(pattern)
        for pattern, _ in shipped_rules(template())
        if pattern in source and pattern not in counter
    }
    assert len(reaching) == 1 and set(reaching) <= set(GENERIC_WEB_RULES), (
        f"{name}: expected exactly one generic `/web/` rule to reach this literal, "
        f"found {reaching}"
    )


@pytest.mark.parametrize("name", LEFT_ALONE)
def test_no_shipped_rule_reaches_the_other_literals(name: str) -> None:
    """`/web_editor/` survives because the rule needs `/web/`, not `/web`."""
    source, _ = LITERALS[name]
    counter = {pattern for pattern, _ in counter_rules()}
    reaching = {
        pattern: source.count(pattern)
        for pattern, _ in shipped_rules(template())
        if pattern in source and pattern not in counter
    }
    assert reaching == {}, (
        f"{name}: no rule of this location may reach this literal, found {reaching}; one "
        "that did would silently change which attachments a picker lists, so give it a "
        "counter-rule of its own and move this name into COUNTERED"
    )


# --- the same thing, through a real nginx -------------------------------------

def test_a_real_nginx_leaves_every_pattern_literal_unprefixed(tmp_path: Path) -> None:
    """The claim is about bytes leaving the gateway, so measure it there.

    All five captured getters, through a real nginx carrying this location's
    own literal rule set -- the counter-rules and every generic rule beside
    them. Each of the six literals must come out exactly as Odoo wrote it.
    """
    answers = served_by_nginx(tmp_path, {name: fixture(name) for name in ALL_FIXTURES})
    for name in ALL_FIXTURES:
        served = answers[("assets", name)]
        assert served == fixture(name), (
            f"{name}: an `attachmentsDomain` getter is all search patterns and no address, "
            "so this location must serve it unchanged"
        )
        assert INGRESS_PREFIX not in served, f"{name}: no prefix may reach this getter"
        for label, count in FIXTURE_LITERALS[name].items():
            source, _ = LITERALS[label]
            assert served.count(source) == count, (
                f"{name}: {label} must leave the gateway as it arrived"
            )


def test_without_the_counter_rules_a_real_nginx_prefixes_the_exclusion(
    tmp_path: Path,
) -> None:
    """The bug, executed: the state #266 measured on Release 0.4.10.

    The same bytes through the same location with this issue's own rules taken
    back out. The two document literals gain a prefix and the other four do
    not, which is both halves of the measurement at once -- the generic rules
    reach exactly the two the fix is for.
    """
    nginx = require_tool("nginx")
    text = template()
    rules = without_counter_rules(location_rules(text, ingress_assets_block(text)))
    served = _serve_with(tmp_path, nginx, rules,
                         {name: fixture(name) for name in ALL_FIXTURES})
    for name in DOCUMENT_FIXTURES:
        for label in FIXTURE_LITERALS[name]:
            source, _ = LITERALS[label]
            prefixed = source.replace("/web/assets/", INGRESS_PREFIX + "/web/assets/")
            assert served[name].count(prefixed) == 1, (
                f"{name}: without the counter-rule the generic `/web/` rule must be shown "
                "prefixing this search pattern; if it no longer does, the fix is covering "
                "nothing and the counter-rules should go"
            )
    for name in IMAGE_FIXTURES:
        assert served[name] == fixture(name), (
            f"{name}: these three literals are reached by no rule, with or without the fix"
        )


# A sample with a search pattern and a real URL literal side by side, in the
# spelling the bundles use for each: the exclusion out of
# `DocumentSelector.attachmentsDomain`, and the `` `/web/content/${id}` `` of
# the `fetchAttachments` beside it, which #239 measured as a URL that must keep
# its prefix.
MIXED_SAMPLE = (
    'domain.unshift("&","|",["url","=",null],"!",["url","=like","/web/assets/%"]);\n'
    "if(`/web/content/${attachment.id}`===href){select(attachment);}\n"
    'loadBundle("/web/assets/debug/web.assets_backend.min.js");\n'
)


def test_the_counter_rules_change_nothing_about_a_url_literal(tmp_path: Path) -> None:
    """The scope claim, executed: only a *search pattern* stops being prefixed.

    `sub_filter` never rescans what it wrote and each counter-rule claims only
    its own bytes, so a real URL literal in the same response -- including one
    that is itself `/web/assets/...`, which is what `loadBundle` asks for --
    keeps the prefix the location exists to put there.
    """
    answers = served_by_nginx(tmp_path, {"mixed.js": MIXED_SAMPLE})
    served = answers[("assets", "mixed.js")]
    assert '["url","=like","/web/assets/%"]' in served, "the search pattern is untouched"
    assert "`%s/web/content/" % INGRESS_PREFIX in served, (
        "the template literal the document comparison compares against must keep its "
        "prefix -- #239 rests on that operand arriving prefixed"
    )
    assert 'loadBundle("%s/web/assets/debug/' % INGRESS_PREFIX in served, (
        "a real `/web/assets/` *address* must still be prefixed; the counter-rule claims "
        "the ORM array and nothing else"
    )
    assert served.count(INGRESS_PREFIX) == 2, (
        f"exactly the two addresses may gain a prefix, got {served.count(INGRESS_PREFIX)}"
    )


def _serve_with(tmp_path: Path, nginx: str, rules: list, files: dict) -> dict:
    """Serve `files` through one nginx carrying exactly `rules`.

    `served_by_nginx` renders the template's own two locations, which is what
    almost every test here wants. This one needs a rule set the template does
    *not* ship -- the one from before the fix -- so it builds its own, and
    `_fetch` is shared rather than written again.
    """
    if not hasattr(socket, "AF_UNIX"):  # pragma: no cover - POSIX only
        pytest.skip("the probe serves over a unix socket")
    root = tmp_path / "www"
    root.mkdir()
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")
    sock = tmp_path / "probe.sock"
    config = """daemon off;
pid %(dir)s/nginx.pid;
error_log %(dir)s/error.log info;
worker_processes 1;
events { worker_connections 64; }
http {
    access_log off;
    client_body_temp_path %(dir)s/body;
    proxy_temp_path %(dir)s/proxy;
    fastcgi_temp_path %(dir)s/fastcgi;
    uwsgi_temp_path %(dir)s/uwsgi;
    scgi_temp_path %(dir)s/scgi;
    types { application/javascript js; }
    default_type application/octet-stream;
    server {
        listen unix:%(sock)s;
        location /assets/ {
            alias %(root)s/;
            sub_filter_once off;
            sub_filter_types application/javascript;
            %(rules)s
        }
    }
}
""" % {"dir": tmp_path, "sock": sock, "root": root,
       "rules": "\n            ".join(rules)}
    path = tmp_path / "nginx.conf"
    path.write_text(config, encoding="utf-8")
    check = subprocess.run(
        [nginx, "-t", "-p", str(tmp_path), "-c", str(path)],
        text=True, capture_output=True, check=False,
    )
    assert check.returncode == 0, check.stderr
    server = subprocess.Popen(
        [nginx, "-p", str(tmp_path), "-c", str(path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        return {name: _fetch(sock, "/assets/" + name) for name in files}
    finally:
        server.terminate()
        server.wait(timeout=30)


# --- what the dialog then lists -----------------------------------------------

def test_the_served_document_getter_excludes_every_generated_bundle() -> None:
    """The question the issue asks, executed on the bytes the gateway serves.

    The getter is run, the domain it built is read against three stored
    `ir.attachment` rows, and the answer must be the user's own document alone
    -- on both dialogs.
    """
    built = domains([fixture(name) for name in DOCUMENT_FIXTURES])
    for name, domain in zip(DOCUMENT_FIXTURES, built):
        assert listed(domain) == [WANTED_ID], (
            f"{name}: the Documents tab must list the document and not the bundles, "
            f"got {listed(domain)}"
        )


def test_the_prefixed_document_getter_excludes_nothing() -> None:
    """And the same getter as it was served before the fix, which is the bug.

    `NOT (url =like '<prefix>/web/assets/%')` is true of every row, so the
    exclusion stops excluding and the `|` beside it lets the bundles through --
    30 tiles where there is one document.
    """
    before = [
        fixture(name).replace("/web/assets/", INGRESS_PREFIX + "/web/assets/")
        for name in DOCUMENT_FIXTURES
    ]
    for name, domain in zip(DOCUMENT_FIXTURES, domains(before)):
        assert listed(domain) == [WANTED_ID, *BUNDLE_IDS], (
            f"{name}: a prefixed exclusion must be shown listing the bundles too; if it no "
            f"longer does, the mechanism in this file's docstring is wrong -- got "
            f"{listed(domain)}"
        )


def test_the_exclusions_null_branch_is_why_a_prefix_lets_everything_through() -> None:
    """Not the `=like` leaf alone: the `|` is half the mechanism.

    `'|' ['url', '=', null]` is there for the documents a user uploaded, which
    have no `url`. Once the `=like` half matches nothing, the `|` is what turns
    "exclude the bundles" into "exclude nothing", so the model is held against
    both halves rather than only the one the prefix lands on.
    """
    exclusion = ["|", ["url", "=", None], "!", ["url", "=like", "/web/assets/%"]]
    rows = {row["id"]: row for row in attachments()}
    assert matches(exclusion, rows[WANTED_ID]), "a document with no url passes the `|`"
    for identifier in BUNDLE_IDS:
        assert not matches(exclusion, rows[identifier]), "a bundle is excluded"
    prefixed = ["|", ["url", "=", None], "!",
                ["url", "=like", INGRESS_PREFIX + "/web/assets/%"]]
    for row in attachments():
        assert matches(prefixed, row), (
            "prefixed, the `=like` matches no stored url, so the negation is true of every "
            "row and the clause excludes nothing"
        )


def test_the_model_reads_a_domain_the_way_odoo_normalizes_one() -> None:
    """The model is only worth anything if it agrees with Odoo's own reading.

    The getters `unshift` an `'&'` in front of a `'|'` and then `push` four
    more leaves, so the list is *not* a balanced prefix expression -- Odoo's
    `normalize_domain` inserts the missing `'&'`s. A model that read the list
    naively would answer a different question, so the normalisation is held on
    the shape this family actually produces.
    """
    assert normalize_domain([["a", "=", 1]]) == [["a", "=", 1]]
    assert normalize_domain([["a", "=", 1], ["b", "=", 2]]) == (
        ["&", ["a", "=", 1], ["b", "=", 2]]
    )
    # The shape the getters build: a `|` that covers two of four leaves, so two
    # `&`s have to be inserted in front of it and not one.
    assert normalize_domain(
        ["|", ["a", "=", 1], ["b", "=", 2], ["c", "=", 3], ["d", "=", 4]]
    ) == ["&", "&", "|", ["a", "=", 1], ["b", "=", 2], ["c", "=", 3], ["d", "=", 4]]
    # `=like` is anchored and `like` is not, which is why the exclusion can be
    # written as a prefix match at all.
    row = {"url": MODULE_STATIC_URL}
    assert not leaf(["url", "=like", "static"], row)
    assert leaf(["url", "like", "static"], row)
    assert leaf(["url", "=like", "/website/static/%"], row)
    # A NULL url fails a positive `=like` and *passes* a negative `not like`,
    # which is `_condition_to_sql`'s `OR <field> IS NULL` rule and the one the
    # document getter's four pushed leaves depend on.
    assert not leaf(["url", "=like", "%"], {"url": None})
    assert leaf(["url", "not like", "x"], {"url": None})
    assert leaf(["description", "not like", "CSS font face for"], {"description": False})
    assert leaf(["name", "!=", "googleFontMetadata"], {"name": None})
    assert leaf(["mimetype", "not in", ["image/png"]], {"mimetype": None})
    # An empty needle drops out of the domain rather than matching nothing.
    assert leaf(["name", "ilike", ""], {"name": "anything"})
    assert leaf(["name", "ilike", ""], {"name": None})


def test_the_image_getters_build_the_same_domain_either_way() -> None:
    """Their three literals are reached by no rule, so there is nothing to fix.

    Executed rather than left to the counts: the two image getters and the
    `FileDocumentsSelector` one are run, and each excludes the shaped and
    module-static URLs exactly as it does on the Public origin.
    """
    built = domains([fixture(name) for name in IMAGE_FIXTURES])
    rows = [
        {"id": 1, "url": SHAPE_URL, "type": "url", "name": "geo_shuriken.svg",
         "public": True, "res_model": "ir.ui.view", "res_id": 0,
         "mimetype": "image/svg+xml", "description": False, "original_id": False},
        {"id": 2, "url": MODULE_STATIC_URL, "type": "url", "name": "s_banner.jpg",
         "public": True, "res_model": "ir.ui.view", "res_id": 0,
         "mimetype": "image/jpeg", "description": False, "original_id": False},
        {"id": 3, "url": None, "type": "binary", "name": "logo.png",
         "public": True, "res_model": "mailing.mailing", "res_id": 5,
         "mimetype": "image/png", "description": False, "original_id": False},
    ]
    for name, domain in zip(IMAGE_FIXTURES, built):
        selected = [row["id"] for row in rows if matches(domain, row)]
        assert selected == [3], (
            f"{name}: a shaped or module-static url must stay out of the grid, got "
            f"{selected}"
        )


def test_the_public_origin_is_served_odoos_own_bytes() -> None:
    """ADR 0003: the control group gets no rule, and nothing here changes that."""
    text = template()
    public = text[: text.index("listen 5691;")]
    for name, _ in counter_rules():
        assert name not in public, (
            f"{name!r} must not appear on the Public listener's side of the template"
        )


# --- the fixtures -------------------------------------------------------------

def test_the_fixtures_are_verbatim_regions() -> None:
    """Each is served bundle bytes, so it must start and end where it says."""
    for name in ALL_FIXTURES:
        text = fixture(name)
        assert text.startswith("get attachmentsDomain(){"), name
        assert text.rstrip().endswith("return domain;}"), name
    # The two document getters are the same code in a different quote, which is
    # why the fix is two rules and not one. If a future Odoo made them agree,
    # one rule would match twice and the other would be a silent no-op.
    current, legacy = DOCUMENT_FIXTURES
    assert fixture(current) != fixture(legacy), (
        f"{current} and {legacy} are byte-identical; re-measure before changing the rules"
    )
    # 320 bytes is the number #266 read off the Public origin for this getter
    # (`served_domain_length`), and 383 is the same getter with one prefix in
    # it. The fixture being that length is what says the capture is the served
    # getter and not a region around it.
    for name in DOCUMENT_FIXTURES:
        assert len(fixture(name).rstrip("\n")) == 320, (
            f"{name}: #266 measured this getter at 320 bytes on the Public origin; a "
            "capture of a different length is a capture of something else"
        )


def test_the_readme_records_the_counts_for_every_fixture() -> None:
    """The fixture standard keeps the per-bundle counts beside the files."""
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    for name in ALL_FIXTURES:
        assert name in readme, f"fixtures/bundles/README.md must name {name}"
    for bundle in BUNDLES:
        assert bundle in readme, (
            f"fixtures/bundles/README.md must record what {bundle} carries"
        )
    for name, (source, _) in LITERALS.items():
        assert source in readme, (
            f"{name}: the README must record the literal as the bytes it was counted as "
            f"({source!r}) -- the quote style is the unit here"
        )


def test_the_template_is_the_one_in_the_image() -> None:
    """A guard the whole file rests on: the rules read above are the shipped ones."""
    assert TEMPLATE.name == "nginx.conf.template", TEMPLATE
    assert TEMPLATE.is_file(), TEMPLATE
