#!/usr/bin/env python3
"""The strip removes a prefix this session never saw (issue #234).

#210 put the Ingress prefix on record markup where the HTML editor renders it
and took it off again on every value the field stores, through two string
helpers the Runtime shim publishes. ``__WOOW_INGRESS_MARKUP_OUT__`` removed
every occurrence of **one literal**: ``__INGRESS_PATH__``, the prefix the
gateway handed *this* page. That is the whole of the hole this file closes.

**Where a prefix that is not this page's comes from.** The To-do description
field carries ``'collaborative': true``, and the collaboration transport ships
*serialised nodes* -- ``attributes[name] = value`` byte for byte
(``html_editor/static/src/core/history_plugin.js:1168``) -- which the receiving
peer applies with ``node.setAttribute(key, value)`` (``:1198``, and ``:1087``
for a later attribute mutation). Under Ingress those values carry the sending
page's prefix, and the receiver's save is what writes them to
``project.task.description``.

The Supervisor token in that prefix is the add-on's, not the session's:
``ingress_entry`` is ``/api/hassio_ingress/<app.ingress_token>`` and
``ingress_token`` is one persisted value per installed app, defaulted once by
``secrets.token_urlsafe`` -- 43 characters of ``[A-Za-z0-9_-]``. The per-user
*session* is a separate 64-byte secret, and it travels as the ``ingress_session``
cookie, not in the path. (Read 2026-10-01 from ``home-assistant/supervisor`` on
``main``: ``supervisor/apps/validate.py``'s ``SCHEMA_APP_USER``,
``supervisor/apps/app.py``'s ``ingress_token``/``ingress_entry``, and
``supervisor/ingress.py``'s ``create_session``. Nothing here can test that; it is
cited so the next reader can check it.) This repository's own adapter says the same thing from
the other side: it reads the prefix from ``/addons/<slug>/info`` once and uses
it for every session (``e2e_menu_action_adapter.py:789``). So two Ingress
sessions on one add-on edit under the **same** prefix, and #210's literal strip
already covers that pair. A prefix the gateway did not hand this page arrives
when the add-on's token is not the one in the value:

- a value stored while the add-on had a different token -- an uninstall and
  reinstall, or a restored backup, mints a new one;
- a second add-on, or a second Home Assistant, reaching the same database;
- **a peer on the Public origin**, which serves no shim and no rewrite, so it
  stores what the Ingress peer sent it and cannot strip anything. ADR 0003
  keeps that surface the control group, so nothing here changes it; what the
  wider strip does is heal the record on the next Ingress save.

So the strip is now about the **shape** of a prefix and not about one value:
anything the gateway would accept as ``$safe_ingress_path`` is removed from a
value on its way to a record, whoever put it there. What is pinned here:

- **The shape is the gateway's**, derived from the template rather than
  restated: the character class, the length bounds and the literal path of
  nginx's ``$safe_ingress_path`` map are the ones the strip looks for, and a
  token longer than the map accepts is left alone rather than cut in half.
- **Both strips, and why there are two.** The literal ``__INGRESS_PATH__`` is
  the floor -- whatever the gateway handed this page is removed whatever its
  shape -- and the shape strip is the addition. #210's contract renders the
  shim with ``/api/hassio_ingress/token``, a prefix the map itself would
  refuse, and it keeps passing untouched because the literal strip still runs.
- **What the peer path produces**, executed: the receiver's ``setAttribute``
  hands the foreign value to the shim's own ``path()``, which does not
  recognise it and prefixes it again -- so the value in the editable carries
  *two* prefixes, and removing every occurrence is what covers it.
- **The save sites**, driven on the bundle bytes the Ingress location serves:
  ``HtmlField.updateValue`` stores no prefix of either kind, and
  ``_commitChanges``'s comparison still holds, so a peer value does not
  reintroduce the double write #210's comparison rewrite removed.
- **The render site is unchanged.** ``IN`` does not heal a foreign prefix: it
  stacks this page's prefix on top, as it did before, and the record comes out
  clean because the save strips both. Stated as a decision, with the cost --
  a picture a peer sent is fetched from a path that 404s until the next load.
"""
import json
import re

from test_ingress_clipboard_fallback import INGRESS_PREFIX
from test_ingress_router_rewrite import map_block
from test_ingress_todo_description import (
    MARKUP_MAP,
    SHIM_CONTEXT,
    commit_program,
    fixture,
    node,
    rendered_shim,
    rewritten,
    save_program,
    template,
)

# Documentation-only tokens, never a real one: 43 characters of the class
# `secrets.token_urlsafe()` draws from, which is the length Supervisor's
# default produces for an add-on's `ingress_token`.
FOREIGN_TOKEN = "Hs3-kQ9fR2tV7wXz_bC4dE6gJ8mN1pS5uY0aL2oZ4qT"
OWN_TOKEN = "Zq7_mB2xT5yD8hJ1kL4nP6rS9vW0cF3gN5tQ8uX1zA6"
assert len(FOREIGN_TOKEN) == len(OWN_TOKEN) == 43

GATEWAY_PATH = "/api/hassio_ingress/"
FOREIGN_PREFIX = GATEWAY_PATH + FOREIGN_TOKEN
# What the gateway hands a real page: a token of this add-on's own, which the
# `$safe_ingress_path` map accepts. #210's contract uses INGRESS_PREFIX, whose
# token the map would refuse, so both prefixes are exercised here.
OWN_PREFIX = GATEWAY_PATH + OWN_TOKEN

PICTURE = "/project_todo/static/img/todo_access.png"

# The `$safe_ingress_path` map: the one place the gateway says what an Ingress
# prefix looks like.
GATEWAY_SHAPE = re.compile(
    r'"~\^(?P<path>/api/hassio_ingress/)(?P<klass>\[[^\]]+\])(?P<bound>\{\d+,\d+\})\$"'
    r"\s+\$http_x_ingress_path;"
)
# The strip's pattern, as one JavaScript regular-expression literal. Every `/`
# inside it is escaped, so the body is "anything but `/` or `\`, or an escaped
# pair", up to the closing delimiter.
STRIP_SHAPE = re.compile(r"mS=/(?P<body>(?:[^/\\]|\\.)+)/g[,;]")
# Its trailing lookahead, which is what keeps a token longer than the gateway
# accepts out of the match instead of cutting it short.
STRIP_LOOKAHEAD = re.compile(r"(?P<shape>.*)\(\?!(?P<klass>\[[^\]]+\])\)\Z", re.S)


# One driver per case, with the prefix the payload names rendered into the shim
# *and* into the page URL, so a shape-valid prefix and the #210 prefix can both
# be driven against the same programs.
#
# This is #210's `HARNESS` with the prefix moved into the payload, and it is a
# copy rather than an import for one reason: taking the prefix from the payload
# means editing that constant, and this issue's own acceptance criteria say
# #210's contract keeps passing **untouched**. `SHIM_CONTEXT` and every driver
# are imported, so the copy is the five lines around them.
HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const payload = JSON.parse(process.argv[1]);
const P = payload.prefix;
const ORIGIN = "http://ha.example:8123";
const PAGE = ORIGIN + P + "/odoo/action-454/5";
__SHIM_CONTEXT__

(async () => {
  for (const { name, shim, program, expected } of payload.cases) {
    const context = shimContext();
    if (shim) vm.runInContext(shim, context, { filename: "ingress-runtime-shim.js" });
    vm.runInContext(program, context);
    const value = await context.result;
    assert.equal(JSON.stringify(value), JSON.stringify(expected),
      name + ": got " + JSON.stringify(value));
  }
})().catch((error) => { console.error(error); process.exit(1); });
""".replace("__SHIM_CONTEXT__", SHIM_CONTEXT)


def out_cases(prefix: str, pairs) -> None:
    """Drive the published strip over `(before, after)` pairs."""
    node(HARNESS, {
        "prefix": prefix,
        "cases": [
            {
                "name": "OUT: " + before,
                "shim": rendered_shim(prefix),
                "program": "result = __WOOW_INGRESS_MARKUP_OUT__(%s);" % _js(before),
                "expected": after,
            }
            for before, after in pairs
        ],
    })


def _js(value: str) -> str:
    return json.dumps(value)


# --- the shape, and where it comes from ---------------------------------------

def test_the_strip_looks_for_the_shape_the_gateway_validates() -> None:
    """One authority for what an Ingress prefix is, in the file that has it.

    The gateway decides which prefixes exist: a request whose
    `X-Ingress-Path` does not match the `$safe_ingress_path` map is served
    with no prefix at all. A strip that removed a *different* shape would
    either miss a prefix the gateway accepts or eat text it never would, so
    the two patterns are held together here rather than by a comment.
    """
    text = template()
    gateway = GATEWAY_SHAPE.search(text)
    assert gateway, (
        "the $safe_ingress_path map must still state the prefix shape as "
        '"~^/api/hassio_ingress/<class>{min,max}$"'
    )
    markup = map_block(text, MARKUP_MAP)
    strip = STRIP_SHAPE.search(markup)
    assert strip, "the markup helpers must carry the strip's pattern as `mS=/.../g`"

    body = strip.group("body").replace("\\/", "/")
    parts = STRIP_LOOKAHEAD.fullmatch(body)
    assert parts, (
        "the strip's pattern must end in a lookahead at the token class: without it a "
        "token longer than the gateway accepts would be matched to the bound and the "
        "rest of it left behind in the record"
    )
    assert parts.group("shape") == (
        gateway.group("path") + gateway.group("klass") + gateway.group("bound")
    ), "the strip must look for the gateway's own prefix shape, bounds included"
    assert parts.group("klass") == gateway.group("klass"), (
        "the lookahead must be the gateway's token class, so a longer token fails to "
        "match rather than being cut short"
    )


def test_the_shape_is_written_once_and_only_the_strip_reads_it() -> None:
    """`IN` must not use it: a foreign prefix is not healed on render (below)."""
    markup = map_block(template(), MARKUP_MAP)
    assert markup.count(GATEWAY_PATH.replace("/", "\\/")) == 1, (
        "the markup helpers must spell the Ingress path shape once, in the strip's pattern"
    )
    assert markup.count("mS") == 2, (
        "the shape pattern must be defined once and read once -- by mOut, and not by mIn"
    )
    assert re.search(r"mOut=function\(s\)\{[^}]*mS", markup), (
        "the strip must be the reader of the shape pattern"
    )


# --- what the strip removes ---------------------------------------------------

def test_the_strip_removes_a_prefix_this_session_never_saw() -> None:
    """The peer snapshot's own prefix, and the record it was heading for."""
    peer = '<img class="img-fluid" src="%s%s" alt="todo-access"/>' % (FOREIGN_PREFIX, PICTURE)
    clean = '<img class="img-fluid" src="%s" alt="todo-access"/>' % PICTURE
    out_cases(OWN_PREFIX, [
        (peer, clean),
        # Both prefixes, which is what the receiving peer's editable actually
        # holds (the next test drives the mechanism).
        ('<img src="%s%s%s"/>' % (OWN_PREFIX, FOREIGN_PREFIX, PICTURE),
         '<img src="%s"/>' % PICTURE),
        # This page's own prefix, which here is a shape the map accepts: the
        # literal strip and the shape strip must agree about it.
        ('<img src="%s%s"/>' % (OWN_PREFIX, PICTURE), '<img src="%s"/>' % PICTURE),
        # More than one foreign prefix in one value: every occurrence goes.
        ('<img src="%s%s"/><a href="%s/web/content/7">x</a>'
         % (FOREIGN_PREFIX, PICTURE, GATEWAY_PATH + "aB3" + "x" * 40),
         '<img src="%s"/><a href="/web/content/7">x</a>' % PICTURE),
        # An absolute URL carrying one, and prefix-shaped text a user typed:
        # the same decision #210 made for this page's prefix, for the same
        # reason -- the bytes are a Supervisor token, not content.
        ('<a href="http://ha.example:8123%s/web/content/7">x</a>' % FOREIGN_PREFIX,
         '<a href="http://ha.example:8123/web/content/7">x</a>'),
        ('<p>see %s/odoo for details</p>' % FOREIGN_PREFIX, "<p>see /odoo for details</p>"),
        # Attributes IN never touches, which the shim's own wrappers prefix.
        ('<img srcset="%s%s 1x"/>' % (FOREIGN_PREFIX, PICTURE),
         '<img srcset="%s 1x"/>' % PICTURE),
        ('<use xlink:href="%s/web/static/img/i.svg#x"/>' % FOREIGN_PREFIX,
         '<use xlink:href="/web/static/img/i.svg#x"/>'),
    ])


def test_the_strip_still_removes_the_prefix_the_gateway_handed_this_page() -> None:
    """The literal strip is the floor, and #210's contract is what needs it.

    `/api/hassio_ingress/token` is not a prefix the `$safe_ingress_path` map
    would accept -- the token is five characters and the map wants sixteen --
    so the shape strip does not see it. Removing what this page was handed
    cannot depend on its shape: the gateway is what decided it, and the value
    is in the page.
    """
    out_cases(INGRESS_PREFIX, [
        ('<img src="%s%s"/>' % (INGRESS_PREFIX, PICTURE), '<img src="%s"/>' % PICTURE),
        # And a foreign prefix is removed on such a page too.
        ('<img src="%s%s"/>' % (FOREIGN_PREFIX, PICTURE), '<img src="%s"/>' % PICTURE),
    ])


def test_only_a_prefix_the_gateway_would_accept_is_stripped() -> None:
    """Short of the shape, the URL keeps escaping rather than being corrupted.

    Every shape below fails safely: the value reaches the record as it came,
    which is a prefix escape ADR 0004 already measures, and not a URL this
    helper took bytes out of the middle of.
    """
    short = GATEWAY_PATH + "x" * 15
    longest = GATEWAY_PATH + "x" * 128
    too_long = GATEWAY_PATH + "x" * 129
    out_cases(OWN_PREFIX, [
        # The bounds the gateway states, from both sides.
        ('<img src="%s%s"/>' % (GATEWAY_PATH + "x" * 16, PICTURE),
         '<img src="%s"/>' % PICTURE),
        ('<img src="%s%s"/>' % (longest, PICTURE), '<img src="%s"/>' % PICTURE),
        ('<img src="%s%s"/>' % (short, PICTURE), '<img src="%s%s"/>' % (short, PICTURE)),
        ('<img src="%s%s"/>' % (too_long, PICTURE), '<img src="%s%s"/>' % (too_long, PICTURE)),
        # A character the class refuses ends the token, so what is left is
        # shorter than the bound and the whole thing is left alone.
        ('<img src="%s%s"/>' % (GATEWAY_PATH + "x" * 8 + "." + "x" * 8, PICTURE),
         '<img src="%s%s"/>' % (GATEWAY_PATH + "x" * 8 + "." + "x" * 8, PICTURE)),
        # Not the gateway's path, so not a prefix.
        ('<img src="/api/hassio_ingres/%s%s"/>' % (FOREIGN_TOKEN, PICTURE),
         '<img src="/api/hassio_ingres/%s%s"/>' % (FOREIGN_TOKEN, PICTURE)),
        ('<img src="%s%s"/>' % (GATEWAY_PATH, PICTURE), '<img src="%s%s"/>' % (GATEWAY_PATH, PICTURE)),
        # A record with nothing of the shape in it comes back byte for byte.
        ('<p>the add-on answers under /api/hassio_ingress/ and nowhere else</p>',
         '<p>the add-on answers under /api/hassio_ingress/ and nowhere else</p>'),
        ('<img src="%s"/>' % PICTURE, '<img src="%s"/>' % PICTURE),
    ])


def test_a_token_at_the_bound_is_taken_whole_or_not_at_all() -> None:
    """A token one character over the bound must not be cut to the bound.

    Without the lookahead the pattern would match its first 128 characters and
    leave the remainder joined to the path -- `/web/image/1` turned into
    `xxx/web/image/1`, which is neither the record's URL nor an escape anyone
    can read. Refusing the match keeps the escape, which is the measured
    behaviour and reversible.
    """
    over = GATEWAY_PATH + "x" * 129 + PICTURE
    out_cases(OWN_PREFIX, [
        ('<img src="%s"/>' % over, '<img src="%s"/>' % over),
    ])


# --- what the peer path hands the strip ---------------------------------------

def test_the_receiving_peer_stacks_this_pages_prefix_on_the_foreign_one() -> None:
    """Which is why the rule is every occurrence, not one leading prefix.

    `_unserializeNode` applies a serialised attribute with
    `node.setAttribute(key, value)`, and the shim wraps `setAttribute` for
    `src`/`href`/`action`/`xlink:href`: the value goes through the same
    `path()` the page publishes as `__WOOW_INGRESS_URL__`. It does not
    recognise a prefix that is not this page's, so it treats the whole thing
    as a root-relative path and prefixes it again.
    """
    node(HARNESS, {
        "prefix": OWN_PREFIX,
        "cases": [
            {
                "name": "path() on a foreign prefix",
                "shim": rendered_shim(OWN_PREFIX),
                "program": "result = __WOOW_INGRESS_URL__(%s);" % _js(FOREIGN_PREFIX + PICTURE),
                "expected": OWN_PREFIX + FOREIGN_PREFIX + PICTURE,
            },
            {
                # This page's own prefix is recognised and not stacked, which
                # is the behaviour that makes the two cases different.
                "name": "path() on this page's prefix",
                "shim": rendered_shim(OWN_PREFIX),
                "program": "result = __WOOW_INGRESS_URL__(%s);" % _js(OWN_PREFIX + PICTURE),
                "expected": OWN_PREFIX + PICTURE,
            },
            {
                # And two is the most it becomes. An attribute *mutation* from a
                # peer goes through the wrapper twice -- the collaboration
                # plugin's `safeSetAttribute` sets the value on a clone, lets the
                # sanitizer see it and copies it back -- and this is why that
                # does not stack a third: the value now begins with this page's
                # prefix, which `path()` recognises.
                "name": "path() on a value that already carries both",
                "shim": rendered_shim(OWN_PREFIX),
                "program": "result = __WOOW_INGRESS_URL__(%s);"
                           % _js(OWN_PREFIX + FOREIGN_PREFIX + PICTURE),
                "expected": OWN_PREFIX + FOREIGN_PREFIX + PICTURE,
            },
        ],
    })


# --- the save sites, on the bytes the Ingress location serves ------------------

PEER_EDITED = (
    '<h1>Hey</h1>'
    '<img class="img-fluid" src="%s%s%s"/>'
    '<img class="img-fluid" src="%s%s"/>'
    '<a href="https://odoo.example/docs">x</a>'
) % (OWN_PREFIX, FOREIGN_PREFIX, PICTURE, FOREIGN_PREFIX,
     "/project_todo/static/img/convert_todo.png")
PEER_SAVED = (
    '<h1>Hey</h1>'
    '<img class="img-fluid" src="%s"/>'
    '<img class="img-fluid" src="%s"/>'
    '<a href="https://odoo.example/docs">x</a>'
) % (PICTURE, "/project_todo/static/img/convert_todo.png")


def test_the_receiving_session_saves_a_foreign_token_without_the_wider_strip() -> None:
    """The hole, on the bytes Odoo ships: the token reaches `record.update`."""
    node(HARNESS, {
        "prefix": OWN_PREFIX,
        "cases": [{
            "name": "save a peer value, as Odoo ships it",
            "shim": rendered_shim(OWN_PREFIX),
            "program": save_program(fixture("save"), PEER_EDITED),
            "expected": [PEER_EDITED, "N(%s)" % PEER_EDITED],
        }],
    })


def test_the_receiving_session_stores_no_ingress_prefix_of_either_kind() -> None:
    node(HARNESS, {
        "prefix": OWN_PREFIX,
        "cases": [
            {
                "name": "save a peer value, under Ingress",
                "shim": rendered_shim(OWN_PREFIX),
                "program": save_program(rewritten("save"), PEER_EDITED),
                "expected": [PEER_SAVED, "N(%s)" % PEER_SAVED],
            },
            {
                # An Ingress page whose shim did not run must still save.
                "name": "save a peer value, with no Runtime shim",
                "shim": "",
                "program": save_program(rewritten("save"), PEER_EDITED),
                "expected": [PEER_EDITED, "N(%s)" % PEER_EDITED],
            },
        ],
    })


def test_the_urgent_comparison_still_holds_for_a_peer_value() -> None:
    """Both sides of it go through the same strip, so a peer value writes once.

    #210's comparison rewrite exists because `comparisonValue` is read off the
    clone, which keeps the prefix, while `lastValue` is the stripped value that
    was stored. A foreign prefix must not reopen that: if only one side of the
    comparison lost it, an urgent save would write the field twice.
    """
    node(HARNESS, {
        "prefix": OWN_PREFIX,
        "cases": [
            {
                "name": "commit comparison, a peer value under Ingress",
                "shim": rendered_shim(OWN_PREFIX),
                "program": commit_program(
                    rewritten("commit comparison"), PEER_EDITED, PEER_SAVED
                ),
                "expected": [PEER_EDITED],
            },
            {
                "name": "commit comparison, a peer value as Odoo ships it",
                "shim": rendered_shim(OWN_PREFIX),
                "program": commit_program(
                    fixture("commit comparison"), PEER_EDITED, PEER_SAVED
                ),
                "expected": [PEER_EDITED, PEER_EDITED],
            },
        ],
    })


# --- the render site is unchanged ---------------------------------------------

def test_the_render_site_does_not_heal_a_foreign_prefix() -> None:
    """A decision, with its cost: the picture a peer sent still 404s.

    `IN` prefixes through `path()`, so a value that already carries a foreign
    prefix comes out carrying both -- exactly what the peer transport produces
    through `setAttribute`, and unchanged by this issue. Healing it on render
    would mean rewriting somebody else's address into ours on the way *in*,
    where nothing is being stored and the value is still the record's; the
    record is made clean on the way out instead, where the token is the harm.
    What the reader is owed is the consequence: until that save and the next
    load, the picture is fetched from a path that 404s.
    """
    node(HARNESS, {
        "prefix": OWN_PREFIX,
        "cases": [
            {
                "name": "IN on a foreign prefix",
                "shim": rendered_shim(OWN_PREFIX),
                "program": "result = __WOOW_INGRESS_MARKUP_IN__(%s);"
                           % _js('<img src="%s%s"/>' % (FOREIGN_PREFIX, PICTURE)),
                "expected": '<img src="%s%s%s"/>' % (OWN_PREFIX, FOREIGN_PREFIX, PICTURE),
            },
            {
                "name": "the pair still leaves the record clean",
                "shim": rendered_shim(OWN_PREFIX),
                "program": "result = __WOOW_INGRESS_MARKUP_OUT__("
                           "__WOOW_INGRESS_MARKUP_IN__(%s));"
                           % _js('<img src="%s%s"/>' % (FOREIGN_PREFIX, PICTURE)),
                "expected": '<img src="%s"/>' % PICTURE,
            },
        ],
    })
