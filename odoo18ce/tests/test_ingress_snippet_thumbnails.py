#!/usr/bin/env python3
"""Contracts for the website editor's snippet thumbnails (issue #170, U-D2).

Under Ingress, Website > Edit opened the Blocks panel and every one of its 36
tiles asked the Home Assistant root for its picture: 36 **Prefix escapes** and
36 console 404s per editor open, blank tiles, with the Public origin clean
(check ``check:U-D2|shared|generic``, run ``WOOW-PARITY-20260925T043539Z``).

The tile is rendered by an OWL template,

    <div class="oe_snippet_thumbnail_img"
         t-attf-style="background-image: url({{snippet.thumbnailSrc}});"/>

and a ``url(`` inside a ``style`` attribute is one of the ways ADR 0004's
2026-09-28 postscript leaves *uncovered by decision* (#169, Group B): the HTML
editor and the website editor save record content back through those same
paths, so a shim hook would write the token-bearing Ingress prefix into the
database. A screen that hits an uncovered way gets a Literal rewrite of its
own, and this is the second of them, after the action help (#158).

Where that rewrite goes is the part worth pinning. The value **round-trips to
the database**: the editor's "Save block" hands ``thumbnailSrc`` -- the raw
``data-oe-thumbnail`` of the snippet catalogue response -- to
``ir.ui.view.save_snippet`` as ``thumbnail_url``, which writes it into the new
snippet view's arch as ``t-thumbnail``. So the catalogue response is *not*
rewritten; the **render site** is, which is the template text itself. Odoo 18
inlines OWL templates into the bundle as ``registerTemplate(...)`` template
literals, appended unminified after the JavaScript, so that exact text is
served through the Ingress asset location where the ADR 0006 exact-expression
rewrites already live.

What is pinned here:

- **The rewrite matches the bundle.** An unmatched ``sub_filter`` is a silent
  no-op, so the pattern is measured against bytes captured from the bundle the
  control group actually serves, under ``fixtures/bundles/``.
- **The rewritten expression behaves.** node evaluates the interpolation
  expression itself, before and after the rewrite -- an OWL template is not
  something node can render, which is the fallback this issue allows -- so a
  rule that changes nothing fails rather than passing quietly.
- **The rewritten template is still a template.** The attribute has to survive
  in both skins it wears at once: an XML attribute delimited by double quotes,
  inside a JavaScript template literal. Python parses the rewritten
  ``registerTemplate`` payload as XML, and the attribute is checked for the
  four characters that would end one skin or the other.
- **Ingress only, and nowhere near the round trip.** ``ingress_rule`` refuses a
  rule found outside the Ingress asset location, and no directive anywhere in
  the template may touch ``data-oe-thumbnail``, ``render_public_asset`` or
  ``save_snippet`` -- so changing that decision means reopening this test.
"""
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from test_ingress_router_rewrite import TEMPLATE, ingress_rule

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures/bundles/website_editor_snippet_thumbnail.js"
)

PREFIX = "/api/hassio_ingress/token"
# The exact template text the Ingress asset location rewrites.
SOURCE = "url({{snippet.thumbnailSrc}})"
# A thumbnail as the snippet catalogue delivers it, and the one value that is
# not a path at all: a snippet whose view carries no `t-thumbnail` arrives as
# the literal `oe-thumbnail`, and has to come out of the rewrite untouched.
ROOT_RELATIVE = "/website/static/src/img/snippets_thumbs/s_cover.svg"
NOT_A_PATH = "oe-thumbnail"

HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");

for (const { name, expression, thumbnailSrc, expected } of JSON.parse(process.argv[1])) {
  // `null` stands for a snippet that carries no thumbnailSrc at all: JSON has
  // no undefined, and that case is the reason the expression is total.
  const snippet = thumbnailSrc === null ? {} : { thumbnailSrc };
  const context = vm.createContext({ snippet, result: undefined });
  vm.runInContext("result = (" + expression + ")", context);
  assert.equal(context.result, expected === null ? undefined : expected, name);
}
"""


def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def replacement() -> str:
    """The rewrite as nginx serves it, with a validated ingress prefix in place."""
    rewritten = ingress_rule(template(), SOURCE, "snippet thumbnail")
    assert rewritten != SOURCE, "a rewrite that changes nothing is a no-op"
    assert PREFIX in rewritten, "the rewrite must put the ingress prefix in front of the path"
    return rewritten


def expression(text: str) -> str:
    """The OWL interpolation expression inside `url({{ ... }})`."""
    assert text.startswith("url({{") and text.endswith("}})"), text
    return text[len("url({{") : -len("}})")]


def rewritten_fixture() -> str:
    """The captured bundle excerpt as the Ingress asset location serves it."""
    return fixture().replace(SOURCE, replacement())


def thumbnail_attribute(bundle: str) -> str:
    """The tile's `t-attf-style`, read out of the bundle's registerTemplate payload."""
    literals = bundle.split("`")
    # registerTemplate("<name>", `<source path>`, `<template>`);
    assert len(literals) == 5, "the excerpt is one registerTemplate call and its two literals"
    root = ET.fromstring(literals[3])
    tiles = [
        element for element in root.iter()
        if "oe_snippet_thumbnail_img" in (element.get("class") or "").split()
    ]
    assert len(tiles) == 1, f"expected one thumbnail tile, found {len(tiles)}"
    style = tiles[0].get("t-attf-style")
    assert style, "the thumbnail tile has no t-attf-style"
    return style


def url_call(style: str) -> str:
    """The `url(...)` of a `background-image` attribute value."""
    assert style.startswith("background-image: ") and style.endswith(";"), style
    return style[len("background-image: ") : -1]


def run(cases: list[dict]) -> None:
    from conftest import require_tool

    result = subprocess.run(
        [require_tool("node"), "-e", HARNESS, json.dumps(cases)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_the_rewrite_is_ingress_only() -> None:
    """A rule on the 8069 listener would change what the Public origin serves."""
    assert replacement().startswith("url({{")
    public = template().replace(
        "listen 8069 default_server;",
        "listen 8069 default_server;\n        sub_filter '%s' 'url(x)';" % SOURCE,
        1,
    )
    with pytest.raises(AssertionError, match="public listener"):
        ingress_rule(public, SOURCE, "snippet thumbnail")


def test_the_source_pattern_occurs_once_in_the_captured_bundle() -> None:
    """A pattern that does not match is a silent no-op, so measure it."""
    text = fixture()
    assert text.count(SOURCE) == 1, (
        f"the captured bundle holds {text.count(SOURCE)} occurrences of {SOURCE!r}; "
        "re-capture the fixture and re-measure the rewrite"
    )
    # And it is the tile's own attribute, not some other `url(` in the panel.
    assert url_call(thumbnail_attribute(text)) == SOURCE


def test_the_tile_keeps_the_root_relative_path_without_the_rewrite() -> None:
    """The starting point: the template as Odoo ships it, read out of the bundle.

    A root-relative path in a `style` attribute resolves against the page
    origin, which under Ingress is the Home Assistant root -- the 36 escapes.
    """
    run([{
        "name": "shipped template, root-relative thumbnail",
        "expression": expression(url_call(thumbnail_attribute(fixture()))),
        "thumbnailSrc": ROOT_RELATIVE,
        "expected": ROOT_RELATIVE,
    }])


def test_the_rewrite_prefixes_a_root_relative_thumbnail() -> None:
    run([{
        "name": "rewritten template, root-relative thumbnail",
        "expression": expression(url_call(thumbnail_attribute(rewritten_fixture()))),
        "thumbnailSrc": ROOT_RELATIVE,
        "expected": PREFIX + ROOT_RELATIVE,
    }])


@pytest.mark.parametrize(
    "label, value",
    [
        # A snippet view with no `t-thumbnail` arrives as this literal.
        ("no thumbnail", NOT_A_PATH),
        # Nothing else here is a root-relative path either: leave all of it be.
        ("absolute URL", "https://cdn.example.test/thumb.svg"),
        ("relative path", "website/static/src/img/snippets_thumbs/s_cover.svg"),
        ("data URL", "data:image/svg+xml;base64,AAAA"),
        ("empty", ""),
        # `+''` keeps the expression total: a value that is not a string has to
        # render as it does today rather than throw inside the tile, which would
        # take the whole Blocks panel down with it.
        ("absent", None),
    ],
)
def test_the_rewrite_leaves_everything_that_is_not_a_root_relative_path(label: str, value) -> None:
    run([{
        "name": f"rewritten template, {label}",
        "expression": expression(replacement()),
        "thumbnailSrc": value,
        "expected": value,
    }])


def test_a_protocol_relative_thumbnail_is_prefixed_and_breaks() -> None:
    """The one limit inherited from every other prefix rule, pinned rather than fixed.

    `//host/path` starts with `/` and is prefixed like a path, which breaks it.
    The five HTML attribute rules on the Ingress `location /` have exactly the
    same limit; #166 fixes it for every such rule at once or not at all, so
    this rule does not grow a guard of its own. Nothing can reach it here in
    practice: `thumbnailSrc` is a view's `t-thumbnail`, which Odoo ships as
    `/<module>/static/...`, and a custom block saves back whatever the
    catalogue delivered.
    """
    run([{
        "name": "rewritten template, protocol-relative",
        "expression": expression(replacement()),
        "thumbnailSrc": "//cdn.example.test/thumb.svg",
        "expected": PREFIX + "//cdn.example.test/thumb.svg",
    }])


def test_without_an_ingress_prefix_the_value_is_unchanged() -> None:
    """No `X-Ingress-Path`, or one the map rejects: today's behaviour exactly."""
    bare = replacement().replace(PREFIX, "")
    run([{
        "name": "rewritten template, empty safe_ingress_path",
        "expression": expression(bare),
        "thumbnailSrc": ROOT_RELATIVE,
        "expected": ROOT_RELATIVE,
    }])


def test_the_rewritten_template_is_still_well_formed_xml() -> None:
    """OWL parses the template as XML, so the attribute has to survive as one."""
    # Both calls parse; a failure here is the rewrite's and not the capture's.
    assert url_call(thumbnail_attribute(fixture())) == SOURCE
    assert url_call(thumbnail_attribute(rewritten_fixture())) == replacement()


def test_the_rewritten_attribute_ends_neither_of_its_two_skins() -> None:
    """A double quote ends the XML attribute; a backtick, a backslash or `${`
    ends or reopens the JavaScript template literal the bundle inlines it in."""
    style = thumbnail_attribute(rewritten_fixture())
    for forbidden in ['"', "`", "\\", "${"]:
        assert forbidden not in style, f"the rewritten attribute carries {forbidden!r}"
    assert len(rewritten_fixture().split("`")) == 5, (
        "the rewrite opened or closed a template literal"
    )


def test_the_rewritten_expression_is_valid_owl_interpolation() -> None:
    """`t-attf` splits the attribute on `{{` and `}}`, so the expression holds neither."""
    inner = expression(replacement())
    assert "{{" not in inner and "}}" not in inner
    assert inner.count("(") == inner.count(")")


def test_no_directive_touches_the_round_trip_sites() -> None:
    """The decision itself: a rewrite on delivery would reach the database.

    `save_snippet` writes `thumbnailSrc` into a snippet view's arch, so a rule
    over `data-oe-thumbnail` in the `render_public_asset` response would store
    the Ingress prefix -- Supervisor token included -- for every custom block
    saved under Ingress, and break that block on the Public origin. Changing
    that means changing this test first.
    """
    directives = [
        line for line in template().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for forbidden in ["oe-thumbnail", "render_public_asset", "save_snippet"]:
        offenders = [line.strip() for line in directives if forbidden in line]
        assert not offenders, f"{forbidden} is rewritten by: {offenders}"


def test_the_prefix_is_added_once() -> None:
    """Three reasons there is no double prefix, and the one that is positional.

    The rule is a plain prefix: it does not look for a prefix that is already
    there, and it does not need to. `sub_filter` never reads back what it
    wrote, so the `$safe_ingress_path` this emits is not rescanned; the generic
    `url(` rules match a different byte and so cannot consume this text or be
    consumed by it; and the shim's `path()` never sees the value, a `style`
    attribute being a way it does not wrap.

    What is left is the value itself, and it can never arrive prefixed: it
    comes from the snippet catalogue response, which is deliberately not
    rewritten (`test_no_directive_touches_the_round_trip_sites`). The last case
    below says what would happen if it ever did, so that a change of mind about
    the catalogue shows up here rather than on a user's screen.
    """
    rendered = template()
    for generic in ["sub_filter 'url(/'", "sub_filter \"url('/\"", "sub_filter 'url(\"/'"]:
        assert generic in rendered, generic
    emitted = replacement()
    for generic_source in ["url(/", "url('/", 'url("/']:
        assert generic_source not in emitted, generic_source
    run([{
        "name": "a value that already carried the prefix would be prefixed again",
        "expression": expression(emitted),
        "thumbnailSrc": PREFIX + ROOT_RELATIVE,
        "expected": PREFIX + PREFIX + ROOT_RELATIVE,
    }])
