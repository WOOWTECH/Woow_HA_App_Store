#!/usr/bin/env python3
"""Contracts for the HTML editor's content round trip (issue #210).

Under Ingress the To-do form showed two broken pictures. The onboarding to-do
Odoo creates for every user copies ``project_todo``'s ``todo_user_onboarding``
template into ``project.task.description``, and that HTML carries
``<img src="/project_todo/static/img/todo_access.png">`` and one more like it.
The HTML editor field inserts the stored value as markup, the browser resolved
both root-relative URLs against the Home Assistant root, and Home Assistant
answered 404 -- ``route_escape=2``, ``http_4xx_5xx=2``, ``console_error=2``,
with the Public origin clean (#163's ``open`` run, add-on 0.4.5, `odoo_parity`).

Markup insertion is the way ADR 0004 leaves uncovered *because of this very
field*: the editor loads a value and saves the same value back, so a Runtime
shim hook on ``innerHTML`` would write the token-bearing Ingress prefix into
the database. The value arrives on ``/web/dataset/call_kw``, which the
action-help postscript names as the response it refuses to rewrite. So the fix
follows the rule the snippet-thumbnail postscript states -- rewrite where the
URL is *rendered*, leave the delivered value alone -- and adds the half that
rule did not need there: the prefix comes **off** again on every value the
field stores.

What is pinned here:

- **The two globals.** The rendered Runtime shim publishes
  ``__WOOW_INGRESS_MARKUP_IN__`` and ``__WOOW_INGRESS_MARKUP_OUT__``,
  read-only, only when the Ingress prefix is non-empty. ``IN`` prefixes
  through the shim's own ``path()``, only inside a start tag -- so an
  attribute-shaped run of text is not a candidate -- and only by walking that
  tag attribute by attribute, so an earlier value's contents are never read as
  an attribute of their own. ``OUT`` removes every occurrence of the prefix
  from a string: wider than ``IN`` on purpose, because that is what makes the
  record safe whatever ``IN`` reached and whatever the shim's own wrappers
  prefixed afterwards.
- **Where each one is called**, five sites. ``IN`` at ``Editor.attachTo``,
  before the markup is parsed, because a picture is fetched the moment it is,
  and ``IN`` again at the collaboration plugin's
  ``resetFromServerAndResyncWithPeers``, the second render site and one the
  To-do field reaches because it sets ``'collaborative': true``. ``OUT`` at
  ``HtmlField.updateValue``, the one place the field writes the record --
  which also covers the image ``savePendingImages`` re-points after the
  editor has handed its content over, and the code view's textarea -- and
  ``OUT`` on ``_commitChanges``'s ``comparisonValue``, so the urgent-save
  comparison still holds between a stripped ``lastValue`` and a clone that
  kept the prefix. And ``OUT`` on the ``src`` the image tools send to
  ``/html_editor/get_image_info``, because that route only looks up a record
  for a path beginning ``/web/image``.
- **The shim still hooks nothing.** Publishing a helper a rewritten expression
  calls is not intercepting a property; ``test_ingress_injection_hooks.py``
  keeps asserting Group B is absent, and the assertion here says the same
  thing from this side.
- **The rewrites match the bundle.** An unmatched ``sub_filter`` is a silent
  no-op, so each pattern is counted in bytes captured from the bundles the
  control group serves, kept under ``fixtures/bundles/``.
- **The round trip**, executed in node: the render site against an editable
  that reports what the browser would fetch, the save site against a record
  stand-in that reports what would be stored, and the image-tools site against
  a fake ``<img>``. Including what the round trip does *not* promise --
  ``path()`` normalises a URL the way the browser resolves one, so a value
  that is not already in normal form comes back percent-encoded or collapsed.
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

MARKUP_MAP = "map $upstream_http_content_type $ingress_markup_global_shim {"
RUNTIME_MAP = "map $upstream_http_content_type $ingress_runtime_shim {"
IN_GLOBAL = "__WOOW_INGRESS_MARKUP_IN__"
OUT_GLOBAL = "__WOOW_INGRESS_MARKUP_OUT__"

# Documentation address only (RFC 2606); no real host here.
HA_ORIGIN = "http://ha.example:8123"

# The two pictures of the onboarding to-do, as `todo_user_onboarding` writes
# them into project.task.description.
TODO_PICTURES = (
    "/project_todo/static/img/todo_access.png",
    "/project_todo/static/img/convert_todo.png",
)

# Each rewrite: the fixture it was measured in, how many times the pattern
# occurs there, and the exact expression the Ingress asset location rewrites.
REWRITES = {
    "render": {
        "fixture": "html_editor_attach_content.js",
        "source": "editable.innerHTML=fixInvalidHTML(this.config.content)",
        "occurrences": 1,
        "global": IN_GLOBAL,
    },
    "save": {
        "fixture": "html_field_update_value.js",
        "source": (
            "async updateValue(value,{changeId}={changeId:this.lastChangeId}){"
            "this.lastValue=normalizeHTML(value,this.clearElementToCompare.bind(this));"
        ),
        "occurrences": 1,
        "global": OUT_GLOBAL,
    },
    "image tools": {
        "fixture": "image_processing_relative_src.js",
        "source": "const relativeSrc=srcUrl.pathname;",
        "occurrences": 1,
        "global": OUT_GLOBAL,
    },
    "collaboration reset": {
        "fixture": "collaboration_reset_from_server.js",
        "source": "if(content){this.editable.innerHTML=content;}",
        "occurrences": 1,
        "global": IN_GLOBAL,
    },
    "commit comparison": {
        "fixture": "html_field_commit_changes.js",
        "source": "const comparisonValue=el.innerHTML;",
        "occurrences": 1,
        "global": OUT_GLOBAL,
    },
}

# Enough of a DOM for the whole Runtime shim to run, the way the clipboard and
# media-source contracts build one. Both helpers are string functions, so
# nothing below needs a DOM of its own.
SHIM_CONTEXT = r"""
function shimContext() {
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
    location: { href: PAGE, origin: ORIGIN, host: "ha.example:8123" },
    sessionStorage: { getItem() { return null; }, setItem() {} },
    fetch(input) { fetched.push(input); return Promise.resolve(); },
    open() {},
    XMLHttpRequest,
    History,
    Element,
    WebSocket,
    URL,
    Request: function () {},
    P,
    PAGE,
    ORIGIN,
    fetched,
    result: undefined,
  };
  context.window = context;
  vm.createContext(context);
  return context;
}
"""

# One driver per rewrite site, run with the rendered shim in the context so
# that what each rewritten expression calls is the helper the page gets.
HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const payload = JSON.parse(process.argv[1]);
const P = "/api/hassio_ingress/token";
const ORIGIN = "http://ha.example:8123";
const PAGE = ORIGIN + P + "/odoo/action-454/5";
__SHIM_CONTEXT__

(async () => {
  for (const { name, shim, program, expected } of payload) {
    const context = shimContext();
    if (shim) vm.runInContext(shim, context, { filename: "ingress-runtime-shim.js" });
    vm.runInContext(program, context);
    // The driver builds its result inside the vm context, so its Array is not
    // this realm's; compare the values and not the prototypes.
    const value = await context.result;
    assert.equal(JSON.stringify(value), JSON.stringify(expected),
      name + ": got " + JSON.stringify(value));
  }
})().catch((error) => { console.error(error); process.exit(1); });
""".replace("__SHIM_CONTEXT__", SHIM_CONTEXT)

# The render site. `fixInvalidHTML` is the identity here -- what it does to
# invalid markup is Odoo's business; what matters is that the prefix is on the
# string the editable is assigned, before anything can be fetched. The fake
# editable resolves every src the way a browser resolves it against the page.
RENDER_DRIVER = r"""
const fixInvalidHTML = (value) => value;
const isEmpty = () => false;
const createBaseContainer = () => ({});
const fillShrunkPhrasingParent = () => {};
const initElementForEdition = () => {};
const requested = [];
const editable = {
  ownerDocument: {},
  classList: { add() {} },
  style: {},
  setAttribute() {},
  replaceChildren() {},
  set innerHTML(value) {
    for (const match of String(value).matchAll(/src="([^"]*)"/g)) {
      requested.push(new URL(match[1], PAGE).href);
    }
  },
};
class Editor {
  constructor(content) {
    this.config = { content };
    this.isDestroyed = false;
    this.editable = null;
    this.document = null;
  }
__SLICE__
  preparePlugins() {}
  startPlugins() {}
}
new Editor(__CONTENT__).attachTo(editable);
result = requested;
"""

# The save site: the one place HtmlField writes the record. The stand-in
# reports what `record.update` was given and what `lastValue` was set to,
# because those two disagreeing is what would make the field save on every
# blur.
SAVE_DRIVER = r"""
const stored = [];
const normalizeHTML = (value) => "N(" + value + ")";
class HtmlField {
  constructor() {
    this.lastChangeId = 0;
    this.isDirty = true;
    this.props = {
      name: "description",
      record: {
        update(values) { stored.push(values.description); return Promise.resolve(); },
        model: { bus: { trigger() {} } },
      },
    };
  }
  clearElementToCompare() {}
__SLICE__
}
const field = new HtmlField();
result = field.updateValue(__VALUE__).then(() => [stored[0], field.lastValue]);
"""

# The image-tools site: the `src` handed to /html_editor/get_image_info, which
# the controller only looks a record up for when it begins `/web/image`.
IMAGE_DRIVER = r"""
const img = {
  dataset: {},
  ownerDocument: { defaultView: { location: { href: PAGE } } },
  getAttribute: () => __SRC__,
};
const src = img.getAttribute("src");
__SLICE__
result = relativeSrc;
"""

# The collaboration plugin's stale-document reset: a second render site, and
# the one the To-do field can actually reach, because it sets
# `'collaborative': true`.
COLLAB_DRIVER = r"""
const requested = [];
const stripHistoryIds = () => {};
class CollaborationOdooPlugin {
  constructor(stored) {
    this.lastCollaborationResetId = 0;
    this.isDocumentStale = true;
    this.historySyncAtLeastOnce = true;
    this.startCollaborationTime = 0;
    this.serverLastStepId = null;
    this.config = {
      collaboration: { collaborationChannel: { collaborationFieldName: "description" } },
    };
    this.stored = stored;
    this.dependencies = {
      history: { reset() {} },
      baseContainer: { createBaseContainer: () => ({}) },
    };
    this.editable = {
      replaceChildren() {},
      set innerHTML(value) {
        for (const match of String(value).matchAll(/src="([^"]*)"/g)) {
          requested.push(new URL(match[1], PAGE).href);
        }
      },
    };
  }
  getCurrentRecord() { return Promise.resolve({ description: this.stored }); }
  getLastHistoryStepId() { return "1"; }
  dispatchTo() {}
  resetCollabRequests() {}
  getPtpPeers() { return []; }
  resetFromPeer() { return Promise.resolve(); }
__SLICE__
}
result = new CollaborationOdooPlugin(__CONTENT__)
  .resetFromServerAndResyncWithPeers()
  .then(() => requested);
"""

# `_commitChanges`, for the one comparison the strip has to stay consistent
# with: `comparisonValue` is read off the clone, `lastValue` off the value that
# was stored, and the urgent path only writes again when they differ.
COMMIT_DRIVER = r"""
const stored = [];
const status = () => "mounted";
class HtmlField {
  constructor(content, lastValue) {
    this.isDirty = true;
    this.lastChangeId = 3;
    this.lastValue = lastValue;
    this.state = { showCodeView: false };
    this.editor = { getContent: () => content };
    this.content = content;
  }
  getEditorContent() { return Promise.resolve({ innerHTML: this.content }); }
  clearElementToCompare() {}
  updateValue(value) { stored.push(value); return Promise.resolve(); }
__SLICE__
}
result = new HtmlField(__CONTENT__, __LAST_VALUE__)
  ._commitChanges({ urgent: true })
  .then(() => stored);
"""

# Everything the two globals promise, executed against the rendered shim.
GLOBALS_HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { shim, emptyShim } = JSON.parse(process.argv[1]);
const P = "/api/hassio_ingress/token";
const ORIGIN = "http://ha.example:8123";
const PAGE = ORIGIN + P + "/odoo/action-454/5";
const PICTURE = "/project_todo/static/img/todo_access.png";
const SECOND = "__SECOND__";
__SHIM_CONTEXT__

function run(script) {
  const context = shimContext();
  vm.runInContext(script, context, { filename: "ingress-runtime-shim.js" });
  return context;
}

const context = run(shim);
const markupIn = context.__WOOW_INGRESS_MARKUP_IN__;
const markupOut = context.__WOOW_INGRESS_MARKUP_OUT__;
assert.equal(typeof markupIn, "function", "the shim must publish __WOOW_INGRESS_MARKUP_IN__");
assert.equal(typeof markupOut, "function", "the shim must publish __WOOW_INGRESS_MARKUP_OUT__");

// --- IN --------------------------------------------------------------------

// The onboarding to-do's own markup: both pictures, nothing else changed.
const stored = '<h1>Hey</h1><img class="img-fluid" src="' + PICTURE + '" alt="todo-access"/>';
assert.equal(
  markupIn(stored),
  '<h1>Hey</h1><img class="img-fluid" src="' + P + PICTURE + '" alt="todo-access"/>',
  "a root-relative src must come out under the prefix, with the rest of the markup untouched"
);
// Several URL attributes in one tag, all of them.
assert.equal(
  markupIn('<img src="' + PICTURE + '" data-src="' + PICTURE + '"/>'),
  '<img src="' + P + PICTURE + '" data-src="' + P + PICTURE + '"/>',
  "a second URL attribute in the same tag must be prefixed too"
);
// Single-quoted attributes are the same attributes.
assert.equal(markupIn("<img src='" + PICTURE + "'/>"), "<img src='" + P + PICTURE + "'/>");
// An uppercase tag and attribute is legal HTML and somebody can paste it into
// the code view; an unquoted value has no closing delimiter to consume and is
// not covered, so it keeps escaping rather than being corrupted; and the name
// test is exact, so `data-original-src` is not a `data-src`.
assert.equal(markupIn('<IMG SRC="' + PICTURE + '">'), '<IMG SRC="' + P + PICTURE + '">');
assert.equal(markupIn('<img Data-Src="' + PICTURE + '"/>'),
  '<img Data-Src="' + P + PICTURE + '"/>');
assert.equal(markupIn('<img src=' + PICTURE + '>'), '<img src=' + PICTURE + '>');
assert.equal(markupIn('<img data-original-src="' + PICTURE + '"/>'),
  '<img data-original-src="' + PICTURE + '"/>');

// The tag is walked attribute by attribute, so an earlier value's contents are
// never read as an attribute of their own. A pattern that searched for `src="`
// would open its value at the wrong quote and restructure the tag -- the real
// `src` would be gone, and the strip cannot undo that, because it only removes
// the prefix. This is the shape that says so.
assert.equal(
  markupIn('<img alt=' + "'" + 'a" src="/x' + "'" + ' src="' + PICTURE + '">'),
  '<img alt=' + "'" + 'a" src="/x' + "'" + ' src="' + P + PICTURE + '">'
);
// The name the walk consumes may hold a `:`, a `.` or a `_`, because an
// attribute it cannot tokenise is one whose value it would search inside --
// which is the misalignment above, reached by another spelling.
for (const name of ["xlink:title", "data-x_y", "ns:a.b", "_a", "2a", "-a", "a%b", "a~b"]) {
  assert.equal(
    markupIn('<img ' + name + '=' + "'" + 'a" src="/x' + "'" + ' src="' + PICTURE + '">'),
    '<img ' + name + '=' + "'" + 'a" src="/x' + "'" + ' src="' + P + PICTURE + '">'
  );
}
// Whitespace around the `=` is taken for the same reason, and put back as it
// came: `alt = '...'` is legal HTML, and an attribute the walk skips is an
// attribute whose value it searches inside.
for (const eq of [" = ", "\t=\t", "\n=\n", "= ", " ="]) {
  assert.equal(
    markupIn('<img alt' + eq + "'" + 'a" src="/x' + "'" + ' src' + eq + '"' + PICTURE + '">'),
    '<img alt' + eq + "'" + 'a" src="/x' + "'" + ' src' + eq + '"' + P + PICTURE + '">'
  );
}
// The URL parser reads `/\host/x` as `//host/x` for an http(s) base, so the
// second-character guard has to refuse a backslash as well as a slash --
// otherwise path() would return a same-host one as a prefixed path and the
// strip would store `/x`, moving the link to another host.
assert.equal(markupIn('<img src="/' + String.fromCharCode(92) + 'ha.example:8123/x.png"/>'),
  '<img src="/' + String.fromCharCode(92) + 'ha.example:8123/x.png"/>');
// An unquoted value is consumed as a token too, so an attribute written that
// way cannot make the walk restructure the tag either -- and what gets
// prefixed in `<img alt= href='/a src="/q"' >` is the `src` a browser also
// reads there, because it ends `alt`'s unquoted value at the whitespace.
assert.equal(
  markupIn('<img alt= href=' + "'" + '/a src="' + PICTURE + '"' + "'" + ' >'),
  '<img alt= href=' + "'" + '/a src="' + P + PICTURE + '"' + "'" + ' >'
);
// An unquoted value that is itself a URL is not prefixed: there is no
// delimiter to put back. It keeps escaping rather than being corrupted.
assert.equal(markupIn('<img src=' + PICTURE + ' alt="x">'),
  '<img src=' + PICTURE + ' alt="x">');
// An attribute may begin at a quote as well as at whitespace, because
// `<a href="/x"title="y">` is legal and minified HTML writes it. Without that,
// the walk desynchronises here and destroys the attribute after the one it
// misreads.
assert.equal(
  markupIn('<a href="' + PICTURE + '"title=' + "'" + 'say " src="/z' + "'"
    + ' class="c">t</a>'),
  '<a href="' + P + PICTURE + '"title=' + "'" + 'say " src="/z' + "'"
    + ' class="c">t</a>'
);
assert.equal(markupIn('<img src="' + PICTURE + '"alt="x">'),
  '<img src="' + P + PICTURE + '"alt="x">');
// The price of that is one more shape reached that is not really an attribute:
// a `src="..."` inside somebody's *unquoted* value, where a browser reads one
// `alt` and no `src` at all. Prefixed in the editor, and the strip takes it
// off again on the way to the record, like the other two such shapes.
assert.equal(markupIn('<img alt=a"src="' + PICTURE + '" >'),
  '<img alt=a"src="' + P + PICTURE + '" >');
// Attributes separated by a newline are still attributes.
assert.equal(
  markupIn('<img\n  src="' + PICTURE + '"\n  alt="x"/>'),
  '<img\n  src="' + P + PICTURE + '"\n  alt="x"/>'
);
// The value runs to the *matching* quote, so the other one is part of the URL
// -- an attachment called "Mary's photo.png" is a real filename.
assert.equal(
  markupIn('<img src="/web/image/12-abc/Mary' + "'" + 's photo.png"/>'),
  '<img src="' + P + '/web/image/12-abc/Mary' + "'" + 's%20photo.png"/>'
);
assert.equal(
  markupIn("<img src='/web/image/12-abc/a" + '"' + "b.png'/>"),
  "<img src='" + P + "/web/image/12-abc/a" + '%22' + "b.png'/>"
);
// Idempotent: the render site may run twice over the same content.
assert.equal(markupIn(markupIn(stored)), markupIn(stored), "no value may be prefixed twice");
assert.equal(markupIn('<a href="' + P + PICTURE + '">x</a>'),
  '<a href="' + P + PICTURE + '">x</a>', "an already prefixed value is unchanged");

// Only a value whose first byte is `/` is a candidate, which is the shape the
// nginx prefix rules match as well and the shape whose round trip is exact.
// That excludes a protocol-relative reference, where every other rule of the
// template has to be told to stop; it leaves a relative value alone, because
// prefixing it would resolve it and the resolved path is not what the record
// held; and it leaves an absolute same-origin URL alone -- Odoo writes
// root-relative URLs into record HTML, and an absolute one somebody pasted is
// unmeasured rather than fixed (see ADR 0004's postscript for this issue).
// And it is only ever looked for inside a start tag, so prose, an escaped code
// sample and an end tag keep their bytes.
for (const untouched of [
  '<a href="#anchor">x</a>',
  '<a href="https://other.example/x">x</a>',
  '<a href="//other.example/x">x</a>',
  // Same-host protocol-relative too: without the `(?!/)` this one is what
  // path() would have turned into a prefixed root-relative path, and the
  // strip would then have stored `/x`. #166 owns this shape for every rule.
  '<a href="//ha.example:8123/x">x</a>',
  '<img data-src="//www.youtube.com/embed/abc"/>',
  '<a href="' + ORIGIN + PICTURE + '">x</a>',
  '<a href="' + ORIGIN + P + PICTURE + '">x</a>',
  '<a href="todo.html">x</a>',
  '<a href="mailto:nobody@example.test">x</a>',
  '<img src="data:image/png;base64,iVBOR"/>',
  '<img src="blob:' + ORIGIN + '/9f1c"/>',
  '<img data-oe-thumbnail="' + PICTURE + '"/>',
  '<img srcset="' + PICTURE + ' 1x"/>',
  '<div style="background-image: url(' + PICTURE + ')"></div>',
  '<pre><code>&lt;img src="' + PICTURE + '"&gt;</code></pre>',
  '<p>write it as src="' + PICTURE + '" in your template</p>',
  '<p>a</p></p src="' + PICTURE + '">',
  // A start tag carrying `>` inside an attribute value is not recognised as a
  // tag, so its URL keeps escaping rather than being corrupted.
  '<img title="a > b" src="' + PICTURE + '"/>',
]) {
  assert.equal(markupIn(untouched), untouched, "must be left alone: " + untouched);
}
for (const value of [null, undefined, 7, false]) {
  assert.equal(markupIn(value), value, "a non-string is returned as it came");
}
assert.equal(markupIn("<p>no url here</p>"), "<p>no url here</p>");

// Two shapes IN does reach that are not really attributes: markup nested in
// another attribute's value, and a real start tag inside a comment. Both are
// prefixed, and OUT is what keeps them out of the record -- asserted here so
// the pair is read as one mechanism and not two.
assert.equal(
  markupIn('<div data-bs-content="<img src=' + "'" + PICTURE + "'" + '>"></div>'),
  '<div data-bs-content="<img src=' + "'" + P + PICTURE + "'" + '>"></div>'
);
assert.equal(markupIn('<!-- <img src="' + PICTURE + '"> -->'),
  '<!-- <img src="' + P + PICTURE + '"> -->');

// It is the same path() the shim's own wrappers use, not a copy of it -- and
// path() normalises, so a value that is not already in normal form comes back
// as the same address in different bytes. Said out loud, because that value is
// what the record gets on the first Ingress edit.
context.fetch(PICTURE);
assert.deepEqual(context.fetched, [P + PICTURE], "fetch must prefix through the same helper");
for (const [before, after] of [
  ["/web/image/1/my photo.png", P + "/web/image/1/my%20photo.png"],
  ["/web/image/1/%E5%9C%96.png", P + "/web/image/1/%E5%9C%96.png"],
  ["/a/../web/image/2.png", P + "/web/image/2.png"],
]) {
  assert.equal(markupIn('<img src="' + before + '"/>'), '<img src="' + after + '"/>',
    "path() normalisation: " + before);
}

// --- OUT -------------------------------------------------------------------

// Every occurrence of the prefix, wherever it is in the string: attributes IN
// prefixes, attributes only the shim's own wrappers prefix, an absolute
// same-origin URL, and text.
for (const [before, after] of [
  ['<img src="' + P + PICTURE + '"/>', '<img src="' + PICTURE + '"/>'],
  ['<form action="' + P + '/web/dataset/call_kw"></form>',
   '<form action="/web/dataset/call_kw"></form>'],
  ['<img srcset="' + P + PICTURE + ' 1x"/>', '<img srcset="' + PICTURE + ' 1x"/>'],
  ['<use xlink:href="' + P + '/web/static/img/i.svg#x"/>',
   '<use xlink:href="/web/static/img/i.svg#x"/>'],
  ['<div data-bs-content="<img src=' + "'" + P + PICTURE + "'" + '>"></div>',
   '<div data-bs-content="<img src=' + "'" + PICTURE + "'" + '>"></div>'],
  ['<a href="' + ORIGIN + P + '/web/content/7">x</a>',
   '<a href="' + ORIGIN + '/web/content/7">x</a>'],
  ['<img src="' + P + PICTURE + '"/><img src="' + P + SECOND + '"/>',
   '<img src="' + PICTURE + '"/><img src="' + SECOND + '"/>'],
  // Prefix-shaped text a user typed goes too, and that is the decision: the
  // prefix carries the Supervisor token, so an occurrence of it in a record is
  // the harm and not content worth keeping.
  ['<p>see ' + P + '/odoo for details</p>', '<p>see /odoo for details</p>'],
]) {
  assert.equal(markupOut(before), after, "must be stripped: " + before);
}
// A value with no prefix in it is returned as it came, and so is a non-string.
for (const untouched of [
  '<img src="' + PICTURE + '"/>',
  '<a href="https://other.example/x">x</a>',
  "",
  "/web/image/7",
]) {
  assert.equal(markupOut(untouched), untouched);
}
for (const value of [null, undefined, 7, false]) {
  assert.equal(markupOut(value), value, "a non-string is returned as it came");
}
// The pair round-trips what IN touches, byte for byte, for a value in normal
// form -- which is what Odoo writes into record HTML.
assert.equal(markupOut(markupIn(stored)), stored, "the record must get back what it held");
assert.equal(markupOut(markupOut(markupIn(stored))), stored, "stripping twice is stripping once");

// --- both ------------------------------------------------------------------

// Read-only: a bundle cannot replace a helper a rewritten expression calls.
// Assignment to a non-writable property is silent outside strict mode, which
// is how an asset bundle runs.
for (const [name, expected] of [
  ["__WOOW_INGRESS_MARKUP_IN__", markupIn],
  ["__WOOW_INGRESS_MARKUP_OUT__", markupOut],
]) {
  try { context[name] = function () { return "owned"; }; } catch (error) {}
  assert.equal(context[name], expected, name + " must be read-only");
  try { delete context[name]; } catch (error) {}
  assert.equal(context[name], expected, name + " must be non-configurable");
}

// With no Ingress prefix the shim returns before publishing anything.
const empty = run(emptyShim);
assert.equal(empty.__WOOW_INGRESS_MARKUP_IN__, undefined, "no prefix, no global");
assert.equal(empty.__WOOW_INGRESS_MARKUP_OUT__, undefined, "no prefix, no global");
""".replace("__SHIM_CONTEXT__", SHIM_CONTEXT).replace("__SECOND__", TODO_PICTURES[1])


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


def rendered_shim(prefix: str) -> str:
    text = template()
    return "\n".join(
        script.replace("$safe_ingress_path", prefix).replace("%%INGRESS_CACHE_VERSION%%", "V")
        for script in (clipboard_shim(text), runtime_shim(text))
    )


def node(harness: str, payload) -> None:
    from conftest import require_tool

    result = subprocess.run(
        [require_tool("node"), "-e", harness, json.dumps(payload)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def render_program(text: str, content: str) -> str:
    """The fixture's `attachTo`, driven with one stored description."""
    body = text[text.index("attachTo(editable){"):].rstrip()
    return RENDER_DRIVER.replace("__SLICE__", body).replace("__CONTENT__", json.dumps(content))


def save_program(text: str, value: str) -> str:
    """The fixture's `updateValue`, driven with one value on its way to the record."""
    body = text[text.index("async updateValue("):].rstrip()
    return SAVE_DRIVER.replace("__SLICE__", body).replace("__VALUE__", json.dumps(value))


def collab_program(text: str, content: str) -> str:
    """The fixture's `resetFromServerAndResyncWithPeers`, driven with one record."""
    body = text[text.index("async resetFromServerAndResyncWithPeers(){"):].rstrip()
    return COLLAB_DRIVER.replace("__SLICE__", body).replace("__CONTENT__", json.dumps(content))


def commit_program(text: str, content: str, last_value: str) -> str:
    """The fixture's `_commitChanges`, driven on its urgent path."""
    body = text[text.index("async _commitChanges({urgent}){"):].rstrip()
    return (
        COMMIT_DRIVER.replace("__SLICE__", body)
        .replace("__CONTENT__", json.dumps(content))
        .replace("__LAST_VALUE__", json.dumps(last_value))
    )


def image_program(text: str, src: str) -> str:
    """The fixture's `loadImageInfo` preamble, driven with one `<img>` src."""
    body = text[text.index("let docHref="):].rstrip()
    return IMAGE_DRIVER.replace("__SLICE__", body).replace("__SRC__", json.dumps(src))


# --- the globals the Runtime shim publishes -----------------------------------

def test_the_runtime_shim_publishes_the_markup_helpers() -> None:
    node(GLOBALS_HARNESS, {"shim": rendered_shim(INGRESS_PREFIX), "emptyShim": rendered_shim("")})


def test_the_helpers_prefix_through_the_shims_own_path() -> None:
    """One URL helper, published rather than copied (ADR 0004)."""
    text = template()
    assert runtime_shim(text).count("var path=function(u)") == 1, (
        "there must be exactly one URL helper"
    )
    assert "path(v)" in map_block(text, MARKUP_MAP), (
        "the markup helper must prefix through the shim's own path(), not a second helper"
    )


def test_the_helpers_are_spliced_into_the_runtime_shim_and_nowhere_else() -> None:
    text = template()
    assert "$ingress_markup_global_shim" in map_block(text, RUNTIME_MAP), (
        "the Runtime shim map must splice $ingress_markup_global_shim in by variable reference"
    )
    references = [
        number
        for number, line in directive_lines(text)
        if "$ingress_markup_global_shim" in line and not line.lstrip().startswith("map ")
    ]
    assert len(references) == 1, (
        "$ingress_markup_global_shim must be referenced only inside $ingress_runtime_shim, "
        f"found it on lines {references}"
    )


def test_the_helpers_are_string_functions_and_touch_no_dom() -> None:
    """ADR 0004's Group B stays uncovered: the shim intercepts nothing here.

    That is not only about Group B. A strip that walked the DOM would have had
    to run on the clone the editor saves, which is detached but still owned by
    the live document -- and a detached ``<img>`` loads, so writing the
    root-relative ``src`` there would have re-requested the picture from the
    Home Assistant root on every save, and a later re-insertion of that clone
    (``HtmlMailField`` does one) would have done it again.
    """
    markup_map = map_block(template(), MARKUP_MAP)
    for hook in (
        "innerHTML", "outerHTML", "insertAdjacentHTML", "defineProperty(Element",
        "setAttribute", "querySelectorAll", "childNodes", "adoptNode", "cloneNode",
    ):
        assert hook not in markup_map, (
            f"the markup helpers must not touch {hook}: a hook on markup insertion writes the "
            "Ingress prefix into the database, which is why ADR 0004 leaves Group B uncovered, "
            "and a write onto a node a live document owns can start a request. These are "
            "string functions a rewritten expression calls, nothing more."
        )


# --- the rewrites -------------------------------------------------------------

@pytest.mark.parametrize("name", REWRITES)
def test_the_rewrite_matches_the_bundle_the_expected_number_of_times(name: str) -> None:
    """A pattern that does not match is a silent no-op, so measure it."""
    rewrite = REWRITES[name]
    found = fixture(name).count(rewrite["source"])
    assert found == rewrite["occurrences"], (
        f"{name}: {rewrite['fixture']} holds {found} occurrences of {rewrite['source']!r}, "
        f"expected {rewrite['occurrences']}; re-capture the fixture and re-measure the rewrite"
    )


@pytest.mark.parametrize("name", REWRITES)
def test_every_rewrite_is_ingress_only(name: str) -> None:
    """A rule on the 8069 listener would change what the Public origin serves."""
    ingress_rule(template(), REWRITES[name]["source"], name)


def test_the_rewrites_name_nothing_route_scoped() -> None:
    """The pair is the editor's own round trip, not a rewrite of the call_kw response.

    ADR 0004 refuses to rewrite ``/web/dataset/call_kw``, which is how the HTML
    editor both loads a field and saves it. Nothing here may reach for it.
    """
    text = template()
    for forbidden in ("/web/dataset/call_kw", "project.task", "web_read"):
        offenders = [number for number, line in directive_lines(text) if forbidden in line]
        assert not offenders, (
            f"no directive may name {forbidden!r} (found on lines {offenders}): rewriting the "
            "response the HTML editor also saves through is what ADR 0004 decided against"
        )


# --- the render site ----------------------------------------------------------

STORED = (
    '<h1>Hey Administrator</h1>'
    '<img class="img-fluid d-none d-sm-block" src="%s" alt="todo-access"/>'
    '<p>Using the editor</p>'
    '<img class="img-fluid d-none d-sm-block" src="%s" alt="convert-todo"/>'
) % TODO_PICTURES


def test_the_pictures_are_fetched_from_the_home_assistant_root_without_the_rewrite() -> None:
    """The starting point: the bundle as Odoo ships it, run under Ingress."""
    node(HARNESS, [{
        "name": "render, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": render_program(fixture("render"), STORED),
        "expected": [HA_ORIGIN + picture for picture in TODO_PICTURES],
    }])


def test_the_rewrite_fetches_the_pictures_under_the_ingress_prefix() -> None:
    node(HARNESS, [{
        "name": "render, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": render_program(rewritten("render"), STORED),
        "expected": [HA_ORIGIN + INGRESS_PREFIX + picture for picture in TODO_PICTURES],
    }])


def test_without_the_globals_the_render_site_inserts_the_raw_value() -> None:
    """An Ingress page whose shim did not run must still render, not throw."""
    node(HARNESS, [{
        "name": "render, with no Runtime shim",
        "shim": "",
        "program": render_program(rewritten("render"), STORED),
        "expected": [HA_ORIGIN + picture for picture in TODO_PICTURES],
    }])


# --- the save site ------------------------------------------------------------

# What the editor hands over under Ingress: the two pictures as the render site
# left them, plus one image `savePendingImages` re-pointed after `getElContent`
# returned, which the shim's `setAttribute` wrapper prefixed.
EDITED = (
    '<img src="%(p)s%(first)s"/><img src="%(p)s%(second)s"/>'
    '<img src="%(p)s/web/image/42-abc/pasted.png"/>'
    '<a href="https://odoo.example/docs">x</a>'
) % {"p": INGRESS_PREFIX, "first": TODO_PICTURES[0], "second": TODO_PICTURES[1]}

SAVED_ROOT_RELATIVE = (
    '<img src="%s"/><img src="%s"/>'
    '<img src="/web/image/42-abc/pasted.png"/>'
    '<a href="https://odoo.example/docs">x</a>'
) % TODO_PICTURES


def test_the_editor_saves_the_ingress_prefix_without_the_rewrite() -> None:
    """The harm ADR 0004 names: the prefix, token and all, reaching the record."""
    node(HARNESS, [{
        "name": "save, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": save_program(fixture("save"), EDITED),
        "expected": [EDITED, "N(%s)" % EDITED],
    }])


def test_the_rewrite_stores_a_root_relative_value() -> None:
    """And `lastValue` is computed from the value that was stored, not the other."""
    node(HARNESS, [{
        "name": "save, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": save_program(rewritten("save"), EDITED),
        "expected": [SAVED_ROOT_RELATIVE, "N(%s)" % SAVED_ROOT_RELATIVE],
    }])


def test_without_the_globals_the_save_site_stores_the_raw_value() -> None:
    """An Ingress page whose shim did not run must still save, not throw."""
    node(HARNESS, [{
        "name": "save, with no Runtime shim",
        "shim": "",
        "program": save_program(rewritten("save"), EDITED),
        "expected": [EDITED, "N(%s)" % EDITED],
    }])


# --- the image tools ----------------------------------------------------------

CROPPED = INGRESS_PREFIX + "/web/image/42-abc/a.png"


def test_the_image_tools_ask_about_a_prefixed_path_without_the_rewrite() -> None:
    """`get_image_info` only looks a record up for a path beginning /web/image."""
    node(HARNESS, [{
        "name": "image tools, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": image_program(fixture("image tools"), CROPPED),
        "expected": CROPPED,
    }])


def test_the_rewrite_asks_about_the_root_relative_path() -> None:
    node(HARNESS, [
        {
            "name": "image tools, under Ingress",
            "shim": rendered_shim(INGRESS_PREFIX),
            "program": image_program(rewritten("image tools"), CROPPED),
            "expected": "/web/image/42-abc/a.png",
        },
        {
            # An external image has no prefix to take off, so the pathname is
            # handed on as Odoo computes it and the route's own URL search
            # still gets its chance.
            "name": "image tools, an external image",
            "shim": rendered_shim(INGRESS_PREFIX),
            "program": image_program(rewritten("image tools"), "https://other.example/a.png"),
            "expected": "/a.png",
        },
        {
            "name": "image tools, with no Runtime shim",
            "shim": "",
            "program": image_program(rewritten("image tools"), CROPPED),
            "expected": CROPPED,
        },
    ])


# --- the collaboration plugin's second render site ----------------------------

def test_the_collaboration_reset_escapes_without_the_rewrite() -> None:
    """The To-do field is collaborative, so this render site is reachable."""
    node(HARNESS, [{
        "name": "collaboration reset, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": collab_program(fixture("collaboration reset"), STORED),
        "expected": [HA_ORIGIN + picture for picture in TODO_PICTURES],
    }])


def test_the_rewrite_keeps_the_collaboration_reset_under_the_prefix() -> None:
    node(HARNESS, [
        {
            "name": "collaboration reset, under Ingress",
            "shim": rendered_shim(INGRESS_PREFIX),
            "program": collab_program(rewritten("collaboration reset"), STORED),
            "expected": [HA_ORIGIN + INGRESS_PREFIX + p for p in TODO_PICTURES],
        },
        {
            "name": "collaboration reset, with no Runtime shim",
            "shim": "",
            "program": collab_program(rewritten("collaboration reset"), STORED),
            "expected": [HA_ORIGIN + picture for picture in TODO_PICTURES],
        },
    ])


# --- the comparison the strip has to stay consistent with ---------------------

def test_the_urgent_save_writes_twice_without_the_comparison_rewrite() -> None:
    """`lastValue` is stripped, the clone is not, so the comparison never matches.

    The three tests below are one controlled comparison: the same content and
    the same ``lastValue`` every time, so the only variable is the rewrite.
    """
    node(HARNESS, [{
        "name": "commit comparison, as Odoo ships it",
        "shim": rendered_shim(INGRESS_PREFIX),
        # What the field is holding after a save: `lastValue` is the stored,
        # stripped value; the clone still carries the prefix it renders with.
        "program": commit_program(
            fixture("commit comparison"), EDITED, SAVED_ROOT_RELATIVE
        ),
        "expected": [EDITED, EDITED],
    }])


def test_the_comparison_rewrite_leaves_the_urgent_save_alone() -> None:
    """One write, because the comparison is now between two stripped values."""
    node(HARNESS, [{
        "name": "commit comparison, under Ingress",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": commit_program(
            rewritten("commit comparison"), EDITED, SAVED_ROOT_RELATIVE
        ),
        "expected": [EDITED],
    }])


def test_a_real_change_still_writes_under_the_comparison_rewrite() -> None:
    """The comparison must keep saying yes when the content actually changed."""
    node(HARNESS, [{
        "name": "commit comparison, a real change",
        "shim": rendered_shim(INGRESS_PREFIX),
        "program": commit_program(
            rewritten("commit comparison"), EDITED, "something else entirely"
        ),
        "expected": [EDITED, EDITED],
    }])


# --- the fixtures -------------------------------------------------------------

@pytest.mark.parametrize("name", REWRITES)
def test_the_readme_records_the_pattern_that_ships(name: str) -> None:
    """The counts are only about the rule if the row is the rule's own source.

    A shortened stand-in in the table would be a measurement of a different
    pattern, and the reader has no way to tell.
    """
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
    render = fixture("render")
    assert render.startswith("attachTo(editable){")
    assert render.rstrip().endswith("this.config.onEditorReady?.();}")
    save = fixture("save")
    assert save.startswith("async updateValue(value,{changeId}={changeId:this.lastChangeId}){")
    assert save.rstrip().endswith('bus.trigger("FIELD_IS_DIRTY",this.isDirty);}')
    image = fixture("image tools")
    assert image.startswith("let docHref=img.ownerDocument.defaultView.location.href;")
    assert re.search(r"const relativeSrc=srcUrl\.pathname;$", image.rstrip())
    collab = fixture("collaboration reset")
    assert collab.startswith("async resetFromServerAndResyncWithPeers(){")
    assert collab.rstrip().endswith("return true;}")
    commit = fixture("commit comparison")
    assert commit.startswith("async _commitChanges({urgent}){")
    assert commit.rstrip().endswith("await this.updateValue(content,{changeId});}}}")
