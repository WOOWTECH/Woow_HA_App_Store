#!/usr/bin/env python3
"""Contracts for the media dialog's preselection comparisons (issue #239).

ADR 0004's postscript named two of them as markup-and-prefix items #210 left
open, and they are the mirror of every other rule in this family: not a markup
insertion, but a comparison that expects an *unprefixed* URL and is handed a
prefixed one. Reopening the dialog on an existing image or document link is
supposed to highlight the attachment it came from; under Ingress the grid
opened with nothing selected and the user had to find the file again.

What is pinned here, and the measurement is the interesting part:

- **Only one of the two was ever broken, and the other must not be "fixed".**
  `ImageSelector.isInitialMedia` compares the element's `src` (prefixed under
  Ingress -- the shim's `setAttribute` wrapper and
  `__WOOW_INGRESS_MARKUP_IN__` both put it there) with `attachment.image_src`
  (an ORM value, never prefixed), so it never matched. That one is rewritten.
  `DocumentSelector.fetchAttachments` compares the element's `href` with
  ``` `/web/content/${attachment.id}` ``` -- and that template literal begins
  ``` `/web/ ```, which is one of the generic literal rules the Ingress asset
  location has shipped since #166. So its left operand arrives at the browser
  **already prefixed**, the comparison is prefixed-against-prefixed, and it has
  been matching all along. Stripping the `href` alone, which is what the issue
  asked for, would have broken a working screen. The tests below execute both
  halves of that: the shipped rule is derived from the template rather than
  quoted here, and a `sub_filter` that names the `href` comparison is refused.
- **The dataset branch of `isInitialMedia` is left alone for the same kind of
  reason.** `data-original-src` is not a `data-src`: the markup helper's
  attribute test is an exact name, and the `setAttribute` wrapper's list is
  `href`/`src`/`action`/`xlink:href`, so nothing in the shim prefixes it. Its
  only writer is `loadImageInfo`, which assigns the server's own `image_src`.
  Both sides of that branch are root-relative already, and the test drives the
  shim to show it rather than asserting it in prose.
- **Both dialogs, not one.** Odoo 18 ships the media dialog twice --
  `html_editor`'s, which the backend forms open, and the legacy `web_editor`'s,
  which `wysiwyg.js` and the website editor's snippet options open. The two
  files are the same code with different quote characters, so each comparison
  is rewritten once per quote style; a rule for only the editor the issue named
  would have left the mail designer's and the website editor's dialog as it
  was.
- **The counts.** An unmatched `sub_filter` is a silent no-op, so every pattern
  -- the two rewritten and the two measured-and-left-alone -- is counted in
  bytes derived from the pinned package through Odoo's own serve path, kept
  under `fixtures/bundles/`.
- **Display state only.** Nothing here is stored either way: the comparison
  decides which tile is highlighted. So there is no `OUT`-on-save half and no
  `IN`-on-render half, and the strip is used for what it is -- the one helper
  that knows what an Ingress prefix looks like.
"""
import json
import re
import socket
import subprocess
import time
from pathlib import Path

import pytest

from conftest import require_tool
from test_ingress_clipboard_fallback import INGRESS_PREFIX, directive_lines
from test_ingress_router_rewrite import TEMPLATE, ingress_assets_block, ingress_rule, map_block
from test_ingress_todo_description import (
    HARNESS,
    SHIM_CONTEXT,
    node,
    rendered_shim,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures/bundles"

MARKUP_MAP = "map $upstream_http_content_type $ingress_markup_global_shim {"
IN_GLOBAL = "__WOOW_INGRESS_MARKUP_IN__"
IN_VALUE_GLOBAL = "__WOOW_INGRESS_MARKUP_IN_VALUE__"
OUT_GLOBAL = "__WOOW_INGRESS_MARKUP_OUT__"

# A second add-on's prefix: the same shape, a different token. #234 made the
# strip remove every prefix of this shape and not only this page's, and that
# is free here -- a `src` a collaborative peer sent carries the sending page's.
FOREIGN_PREFIX = "/api/hassio_ingress/aaaabbbbccccddddeeee"

# The attachment the element was built from, and one beside it that must not be
# highlighted instead. `image_src` is `ir.attachment._compute_image_src`'s own
# shape, `/web/image/<id>-<checksum[:8]>/<quote(name)>`; the document URLs are
# `/web/content/<id>`, which is what `DocumentSelector.createElements` builds.
WANTED_ID = 7
OTHER_ID = 9
IMAGE_SRC = "/web/image/7-1a2b3c4d/logo.png"
OTHER_IMAGE_SRC = "/web/image/9-5e6f7a8b/other.png"
DOCUMENT_HREF = "/web/content/7"
OTHER_DOCUMENT_HREF = "/web/content/9"

# Each rewrite: the fixture its pattern was measured in, how many times the
# pattern occurs there, and the helper the replacement must call.
DATASET_SOURCE = (
    "if(this.props.media.dataset.originalSrc)"
    "{return this.props.media.dataset.originalSrc===attachment.image_src;}"
)

REWRITES = {
    "dataset": {
        "fixture": "media_dialog_image_preselect.js",
        "source": DATASET_SOURCE,
        "occurrences": 1,
        "global": OUT_GLOBAL,
    },
    "legacy dataset": {
        # The same bytes: this is the one line the two dialogs spell
        # identically, so one rule serves both and the fixture it was measured
        # in is the only thing that differs here.
        "fixture": "legacy_media_dialog_image_preselect.js",
        "source": DATASET_SOURCE,
        "occurrences": 1,
        "global": OUT_GLOBAL,
    },
    "image": {
        "fixture": "media_dialog_image_preselect.js",
        "source": 'return this.props.media.getAttribute("src")===attachment.image_src;',
        "occurrences": 1,
        "global": OUT_GLOBAL,
    },
    "legacy image": {
        "fixture": "legacy_media_dialog_image_preselect.js",
        "source": "return this.props.media.getAttribute('src')===attachment.image_src;",
        "occurrences": 1,
        "global": OUT_GLOBAL,
    },
}

# The comparison that was named by the issue, measured, and left alone -- in
# each dialog. It is here with its count, so that a reader who comes looking
# for a fourth and fifth rule finds the measurement instead of silence.
LEFT_ALONE = {
    "document": {
        "fixture": "media_dialog_document_preselect.js",
        "source": '===this.props.media.getAttribute("href").replace(/[?].*/,"")',
        "occurrences": 1,
    },
    "legacy document": {
        "fixture": "legacy_media_dialog_document_preselect.js",
        "source": "===this.props.media.getAttribute('href').replace(/[?].*/,'')",
        "occurrences": 1,
    },
}

MEASURED = dict(REWRITES, **LEFT_ALONE)

DOCUMENT_FIXTURES = tuple(rewrite["fixture"] for rewrite in LEFT_ALONE.values())
IMAGE_FIXTURES = (
    "media_dialog_image_preselect.js",
    "legacy_media_dialog_image_preselect.js",
)

# The one generic rule of this location that reaches a document fixture. Its
# pattern, not its replacement: the replacement is read out of the template so
# that a change to the prefix variable or to the rule's shape shows up here.
TEMPLATE_LITERAL_RULE = "`/web/"

# And the generic rule of the *HTML* location that reaches `data-original-src`.
# It is written for `src="/` and is a bare substring, so it matches inside the
# longer attribute name -- which is why the dataset branch is rewritten.
HTML_SRC_RULE = 'src="/'

# The bundles each pattern was counted in. Recorded in
# `fixtures/bundles/README.md` with the zero counts beside them; the test below
# keeps the README and this list in the same place.
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

# --- the node drivers ---------------------------------------------------------

# A media element the dialog was opened on: `dataset` for the `data-*` reads
# and `getAttribute` for the rest, which is all either comparison touches.
MEDIA_ELEMENT = r"""
function mediaElement({ attributes, dataset }) {
  return {
    dataset: dataset || {},
    getAttribute(name) {
      return name in attributes ? attributes[name] : null;
    },
  };
}
const selected = [];
class FileSelector {
  async fetchAttachments() {
    return ATTACHMENTS.map((attachment) => Object.assign({}, attachment));
  }
}
"""

# `ImageSelector.fetchAttachments`, which is the loop that calls the comparison
# and selects what it matches -- so the driver answers the question the issue
# asks ("is the attachment it came from highlighted?") and not a narrower one
# about an expression. The stubs are the module-level helpers the excerpt
# closes over; `window.location.origin` comes from the shim's own context.
IMAGE_DRIVER = r"""
__MEDIA_ELEMENT__
const ATTACHMENTS = __ATTACHMENTS__;
const getHtmlStyle = () => ({});
const getCSSVariableValue = () => "#714B67";
const weUtils = {
  getCSSVariableValue: () => "#714B67",
  isSrcCorsProtected: async () => false,
};
class ImageSelector extends FileSelector {
  constructor(media) {
    super();
    this.props = { media };
    this.MIN_ROW_HEIGHT = 128;
    this.isImageField = false;
  }
  selectInitialMedia() { return true; }
  selectAttachment(attachment) { selected.push(attachment.id); }
__SLICE__
}
result = new ImageSelector(mediaElement(__MEDIA__))
  .fetchAttachments(10, 0)
  .then(() => selected);
"""

# `DocumentSelector.fetchAttachments`, the same way: the loop, not the
# expression inside it.
DOCUMENT_DRIVER = r"""
__MEDIA_ELEMENT__
const ATTACHMENTS = __ATTACHMENTS__;
class DocumentSelector extends FileSelector {
  constructor(media) {
    super();
    this.props = { media };
  }
  selectInitialMedia() { return true; }
  selectAttachment(attachment) { selected.push(attachment.id); }
__SLICE__
}
result = new DocumentSelector(mediaElement(__MEDIA__))
  .fetchAttachments(10, 0)
  .then(() => selected);
"""

# What the shim promises about the attribute the dataset branch reads. Executed
# because it is the whole reason that branch has no rule: if either the markup
# helper or the `setAttribute` wrapper ever starts prefixing
# `data-original-src`, this is where it surfaces.
DATASET_HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { shim } = JSON.parse(process.argv[1]);
const P = "/api/hassio_ingress/token";
const ORIGIN = "http://ha.example:8123";
const PAGE = ORIGIN + P + "/odoo/action-454/5";
const IMAGE_SRC = "__IMAGE_SRC__";
__SHIM_CONTEXT__

const context = shimContext();
// Recorded *before* the shim installs its wrapper, because the wrapper calls
// the method it captured at install time and not `this.setAttribute`.
const written = {};
context.Element.prototype.setAttribute = function (name, value) { written[name] = value; };
vm.runInContext(shim, context, { filename: "ingress-runtime-shim.js" });
const markupIn = context.__WOOW_INGRESS_MARKUP_IN__;

// The record's own markup, as the editor stores it for an optimised image.
const stored =
  '<img src="' + IMAGE_SRC + '" data-original-src="' + IMAGE_SRC + '" data-original-id="7">';
assert.equal(
  markupIn(stored),
  '<img src="' + P + IMAGE_SRC + '" data-original-src="' + IMAGE_SRC + '" data-original-id="7">',
  "IN must prefix src and leave data-original-src alone: its attribute test is an exact " +
    "name, so data-original-src is not a data-src"
);

// The other way a URL reaches an attribute: the shim's setAttribute wrapper.
const node = new context.Element();
node.setAttribute("src", IMAGE_SRC);
assert.equal(written.src, P + IMAGE_SRC, "the wrapper prefixes src");
node.setAttribute("data-original-src", IMAGE_SRC);
assert.equal(
  written["data-original-src"],
  IMAGE_SRC,
  "...and leaves data-original-src as it came, which is why isInitialMedia's dataset " +
    "branch compares two unprefixed values and needs no rewrite"
);
""".replace("__SHIM_CONTEXT__", SHIM_CONTEXT).replace("__IMAGE_SRC__", IMAGE_SRC)


# --- helpers ------------------------------------------------------------------

def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def shipped_rules(text: str) -> list:
    """Every `sub_filter` pair the Ingress asset location carries, in order."""
    start, end = ingress_assets_block(text)
    rule = re.compile(
        r"sub_filter (?:'([^']*)'|\"([^\"]*)\") (?:'([^']*)'|\"([^\"]*)\");"
    )
    return [
        (
            match.group(1) if match.group(1) is not None else match.group(2),
            match.group(3) if match.group(3) is not None else match.group(4),
        )
        for match in rule.finditer(text[start:end])
    ]


def rules_reaching(text: str, own: set) -> dict:
    """Which patterns of the Ingress asset location occur in some bytes.

    `own` is the set an issue's own rewrites are written for, which of course
    reach the excerpt they were measured in; what is left is every *other*
    rule of that location. Establishing that at most one of those reaches an
    excerpt is what makes applying it by hand the same thing as what the
    browser receives, which is why the markup family's contract tests each ask
    this question -- `test_ingress_code_view_toggle.py` imports it.

    It is a containment scan and not an emulation of nginx's filter. The
    `test_a_real_nginx_agrees_about_what_*` tests are the executed version,
    over the same files and the whole rule set.
    """
    return {
        pattern: text.count(pattern)
        for pattern, _ in shipped_rules(template())
        if pattern in text and pattern not in own
    }


def generic_rules_reaching(name: str) -> dict:
    """`rules_reaching` over one of this issue's four captured excerpts."""
    return rules_reaching(
        fixture(name), {rewrite["source"] for rewrite in REWRITES.values()}
    )


def literal_rule_replacement() -> str:
    """The generic template-literal rule's replacement, out of the template."""
    return ingress_rule(template(), TEMPLATE_LITERAL_RULE, "the `/web/ literal rule")


def as_served(name: str, rewritten: bool = True) -> str:
    """The fixture as the Ingress asset location serves it.

    Every rule that reaches the excerpt is applied, because nginx applies every
    rule: this family's own three, and -- on the document excerpts -- the
    generic template-literal rule that prefixes `` `/web/content/ ``.
    """
    text = fixture(name)
    if rewritten:
        for rewrite in REWRITES.values():
            if rewrite["source"] in text:
                replacement = ingress_rule(
                    template(), rewrite["source"], rewrite["fixture"]
                )
                assert rewrite["global"] in replacement, (
                    f"{name}: the rewrite must go through {rewrite['global']}, the helper the "
                    "shim publishes"
                )
                text = text.replace(rewrite["source"], replacement)
    if TEMPLATE_LITERAL_RULE in text:
        text = text.replace(TEMPLATE_LITERAL_RULE, literal_rule_replacement())
    return text


def as_public(name: str) -> str:
    """The fixture as the Public origin serves it: no rule at all (ADR 0003)."""
    return fixture(name)


# --- the same thing, through a real nginx -------------------------------------

# A page-HTML sample in the shape Odoo's own stored arch uses: every themed
# image in `mass_mailing_themes/views/mass_mailing_themes_templates.xml`
# carries `data-original-src` beside its `src`, so this is not an invented
# attribute. `data-src` is here too, because it has a rule of its own and the
# question is which rule claims which position.
HTML_SAMPLE = (
    "<!doctype html><html><body>\n"
    '<img src="%(src)s" data-original-src="%(src)s" data-original-id="7" '
    'data-mimetype="image/png">\n'
    '<img data-src="%(other)s">\n'
    "</body></html>\n"
) % {"src": IMAGE_SRC, "other": OTHER_IMAGE_SRC}


def location_rules(text: str, bounds) -> list:
    """The simple `sub_filter` lines of one location, prefix rendered.

    A rule whose replacement splices an nginx *variable* other than the prefix
    -- the `<head>` rule, which injects the Runtime shim -- is left out: it is
    a different mechanism, tested by its own file, and it cannot be rendered
    into a probe that has no maps. Everything else goes in, so what the probe
    applies is this location's literal rule set and not a selection of it.
    """
    start, end = bounds
    lines = text[start:end].splitlines()
    return [
        line.strip().replace("$safe_ingress_path", INGRESS_PREFIX)
        for line in lines
        if line.strip().startswith("sub_filter ") and "$ingress_" not in line
    ]


def html_location_bounds(text: str) -> tuple:
    """The generic `location / {` of the Ingress (5691) server."""
    start = text.index("listen 5691;")
    opening = text.index("\n        location / {", start)
    depth = 0
    index = opening
    while True:
        index = min(
            (position for position in (text.find("{", index), text.find("}", index)) if position >= 0),
            default=-1,
        )
        assert index >= 0, "unbalanced location / block"
        depth += 1 if text[index] == "{" else -1
        index += 1
        if depth == 0:
            return opening, index


def served_by_nginx(tmp_path: Path, files: dict) -> dict:
    """Serve `files` through a real nginx and return what it answers.

    Two locations, each carrying one of the template's own literal rule sets:
    `/assets/` the Ingress asset location's, `/html/` the generic HTML
    location's. The listener is a unix socket inside `tmp_path`, which is what
    `gateway_render` does for the same reason -- probing for a free TCP port
    would race every other process on the machine.
    """
    nginx = require_tool("nginx")
    if not hasattr(socket, "AF_UNIX"):  # pragma: no cover - POSIX only
        pytest.skip("the probe serves over a unix socket")
    text = template()
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
    types { text/html html; application/javascript js; }
    default_type application/octet-stream;
    server {
        listen unix:%(sock)s;
        location /assets/ {
            alias %(root)s/;
            sub_filter_once off;
            sub_filter_types application/javascript;
            %(assets)s
        }
        location /html/ {
            alias %(root)s/;
            sub_filter_once off;
            sub_filter_types application/javascript;
            %(html)s
        }
    }
}
""" % {
        "dir": tmp_path,
        "sock": sock,
        "root": root,
        "assets": "\n            ".join(
            location_rules(text, ingress_assets_block(text))
        ),
        "html": "\n            ".join(location_rules(text, html_location_bounds(text))),
    }
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
        answers = {}
        for name in files:
            for where in ("assets", "html"):
                answers[(where, name)] = _fetch(sock, f"/{where}/{name}")
        return answers
    finally:
        server.terminate()
        server.wait(timeout=30)


def _fetch(sock: Path, path: str, attempts: int = 100) -> str:
    """One HTTP/1.0 GET over the probe's unix socket."""
    request = ("GET %s HTTP/1.0\r\nHost: probe\r\nAccept-Encoding: \r\n\r\n" % path).encode()
    for attempt in range(attempts):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.connect(str(sock))
        except OSError:
            connection.close()
            time.sleep(0.05)
            continue
        with connection:
            connection.sendall(request)
            chunks = []
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        answer = b"".join(chunks).decode()
        head, _, body = answer.partition("\r\n\r\n")
        assert " 200 " in head.splitlines()[0], head.splitlines()[0]
        return body
    raise AssertionError("the probe nginx never accepted a connection")


def image_program(text: str, media: dict) -> str:
    """The excerpt's two methods, driven over one media element."""
    body = text[text.index("isInitialMedia(attachment){"):].rstrip()
    attachments = [
        {"id": WANTED_ID, "image_src": IMAGE_SRC, "mimetype": "image/png"},
        {"id": OTHER_ID, "image_src": OTHER_IMAGE_SRC, "mimetype": "image/png"},
    ]
    return (
        IMAGE_DRIVER.replace("__MEDIA_ELEMENT__", MEDIA_ELEMENT)
        .replace("__SLICE__", body)
        .replace("__ATTACHMENTS__", json.dumps(attachments))
        .replace("__MEDIA__", json.dumps(media))
    )


def document_program(text: str, media: dict) -> str:
    """The excerpt's `fetchAttachments`, driven over one media element."""
    body = text[text.index("async fetchAttachments(...args){"):].rstrip()
    attachments = [{"id": WANTED_ID}, {"id": OTHER_ID}]
    return (
        DOCUMENT_DRIVER.replace("__MEDIA_ELEMENT__", MEDIA_ELEMENT)
        .replace("__SLICE__", body)
        .replace("__ATTACHMENTS__", json.dumps(attachments))
        .replace("__MEDIA__", json.dumps(media))
    )


def image_media(src, original_src=None) -> dict:
    dataset = {} if original_src is None else {"originalSrc": original_src}
    return {"attributes": {"src": src}, "dataset": dataset}


def document_media(href) -> dict:
    return {"attributes": {"href": href + "?unique=1a2b3c4d&download=true"}, "dataset": {}}


def run(cases: list) -> None:
    """One node process for a batch of cases, as the #210 harness does it."""
    node(HARNESS, cases)


def case(name, program, expected, shim=True) -> dict:
    return {
        "name": name,
        "shim": rendered_shim(INGRESS_PREFIX) if shim else "",
        "program": program,
        "expected": expected,
    }


# --- the patterns -------------------------------------------------------------

@pytest.mark.parametrize("name", MEASURED)
def test_every_pattern_matches_the_bundle_the_expected_number_of_times(name: str) -> None:
    """A pattern that does not match is a silent no-op, so measure it.

    The two that are *not* rewritten are measured on the same footing as the
    three that are: the reason they need no rule is a claim about these bytes,
    and it rots silently if nothing counts them.
    """
    rewrite = MEASURED[name]
    found = fixture(rewrite["fixture"]).count(rewrite["source"])
    assert found == rewrite["occurrences"], (
        f"{name}: {rewrite['fixture']} holds {found} occurrences of {rewrite['source']!r}, "
        f"expected {rewrite['occurrences']}; re-derive the fixture and re-measure"
    )


@pytest.mark.parametrize("name", REWRITES)
def test_every_rewrite_is_ingress_only(name: str) -> None:
    """A rule on the 8069 listener would change what the Public origin serves."""
    ingress_rule(template(), REWRITES[name]["source"], name)


@pytest.mark.parametrize("name", REWRITES)
def test_each_rewrite_goes_through_the_strip_and_publishes_nothing_new(name: str) -> None:
    replacement = ingress_rule(template(), REWRITES[name]["source"], name)
    assert OUT_GLOBAL in replacement, (
        f"{name}: the element side must go through {OUT_GLOBAL}, which is the only thing in "
        "this product that knows what an Ingress prefix looks like"
    )
    for other in (IN_GLOBAL + "(", IN_VALUE_GLOBAL + "("):
        assert other not in replacement, (
            f"{name}: a preselection comparison inserts no markup, so it must not call {other}"
        )
    assert "attachment.image_src;" in replacement, (
        "the ORM side of the comparison is untouched: it never carries a prefix"
    )


def test_the_rewrites_introduce_no_new_global() -> None:
    """Three helpers, and this issue needs none of its own."""
    markup_map = map_block(template(), MARKUP_MAP)
    published = re.findall(r'mP\("(__WOOW_[A-Z_]+)"', markup_map)
    assert published == [IN_GLOBAL, IN_VALUE_GLOBAL, OUT_GLOBAL], (
        "the markup map must publish exactly #210's two helpers and #237's third; the media "
        f"dialog's comparison reuses the strip, so it adds none: found {published}"
    )


def test_no_rewrite_here_names_a_route() -> None:
    """Still the bundle and not the response the dialog's data arrives on."""
    text = template()
    for forbidden in ("/web/dataset/call_kw", "ir.attachment", "search_read"):
        offenders = [number for number, line in directive_lines(text) if forbidden in line]
        assert not offenders, (
            f"no directive may name {forbidden!r} (found on lines {offenders}): the attachment "
            "list arrives on call_kw, which ADR 0004 refuses to rewrite"
        )


# --- the image comparison, which was broken -----------------------------------

def test_the_image_comparison_selects_nothing_under_ingress_without_the_rewrite() -> None:
    """The starting point: Odoo's own bytes, a prefixed element, no match."""
    cases = [
        case(
            f"{name}: Odoo's bytes, prefixed src",
            image_program(as_served(name, rewritten=False), image_media(INGRESS_PREFIX + IMAGE_SRC)),
            [],
        )
        for name in IMAGE_FIXTURES
    ]
    run(cases)


def test_the_image_comparison_highlights_its_attachment_under_ingress() -> None:
    """The fix, on both dialogs: a prefixed `src` finds its attachment."""
    cases = [
        case(
            f"{name}: rewritten, prefixed src",
            image_program(as_served(name), image_media(INGRESS_PREFIX + IMAGE_SRC)),
            [WANTED_ID],
        )
        for name in IMAGE_FIXTURES
    ]
    run(cases)


def test_the_image_comparison_still_works_on_an_unprefixed_src() -> None:
    """The strip is a no-op on a value with no prefix, which is the Public
    origin's spelling and also an element the shim never touched."""
    cases = [
        case(
            f"{name}: rewritten, unprefixed src",
            image_program(as_served(name), image_media(IMAGE_SRC)),
            [WANTED_ID],
        )
        for name in IMAGE_FIXTURES
    ]
    run(cases)


def test_the_image_comparison_handles_a_prefix_from_another_installation() -> None:
    """#234 made the strip remove every prefix of the shape, not only this
    page's -- so a `src` a collaborative peer sent matches here too."""
    cases = [
        case(
            f"{name}: rewritten, foreign prefix",
            image_program(as_served(name), image_media(FOREIGN_PREFIX + IMAGE_SRC)),
            [WANTED_ID],
        )
        for name in IMAGE_FIXTURES
    ]
    run(cases)


def test_the_image_comparison_does_not_highlight_a_different_attachment() -> None:
    """Stripping a prefix must not turn the comparison into a loose match."""
    cases = [
        case(
            f"{name}: rewritten, src of nothing in the list",
            image_program(
                as_served(name),
                image_media(INGRESS_PREFIX + "/web/image/11-99887766/elsewhere.png"),
            ),
            [],
        )
        for name in IMAGE_FIXTURES
    ] + [
        case(
            f"{name}: rewritten, src of the other attachment",
            image_program(as_served(name), image_media(INGRESS_PREFIX + OTHER_IMAGE_SRC)),
            [OTHER_ID],
        )
        for name in IMAGE_FIXTURES
    ]
    run(cases)


def test_the_image_comparison_falls_back_to_odoos_own_behaviour_with_no_globals() -> None:
    """Every rewritten expression has to survive a page where no shim ran.

    With the globals absent the fallback is the identity, so the rewritten
    bytes behave exactly as Odoo's do: an unprefixed `src` still matches and a
    prefixed one still does not. The fallback does not pretend to fix anything
    -- it promises not to throw, which is what a `sub_filter` served into a
    realm the shim never reached needs.
    """
    cases = []
    for name in IMAGE_FIXTURES:
        cases.append(
            case(
                f"{name}: no shim, unprefixed src",
                image_program(as_served(name), image_media(IMAGE_SRC)),
                [WANTED_ID],
                shim=False,
            )
        )
        cases.append(
            case(
                f"{name}: no shim, prefixed src",
                image_program(as_served(name), image_media(INGRESS_PREFIX + IMAGE_SRC)),
                [],
                shim=False,
            )
        )
    run(cases)


def test_the_image_comparison_is_unchanged_on_the_public_origin() -> None:
    """ADR 0003's control group gets Odoo's bytes and must keep working."""
    cases = [
        case(f"{name}: public origin", image_program(as_public(name), image_media(IMAGE_SRC)), [WANTED_ID])
        for name in IMAGE_FIXTURES
    ]
    run(cases)


# --- the dataset branch, which is the other half of the same method -----------

def test_the_dataset_branch_selects_nothing_on_page_markup_without_the_rewrite() -> None:
    """The starting point, and it is reached *before* the `src` branch.

    An image that has been through the image tools carries
    `data-original-src`, so this branch `return`s and the `src` rule never
    runs. On markup that reached the page as an HTML response that attribute
    carries the prefix (see the nginx probe above), and the comparison fails.
    """
    cases = [
        case(
            f"{name}: Odoo's bytes, prefixed data-original-src",
            image_program(
                as_served(name, rewritten=False),
                image_media(INGRESS_PREFIX + IMAGE_SRC, original_src=INGRESS_PREFIX + IMAGE_SRC),
            ),
            [],
        )
        for name in IMAGE_FIXTURES
    ]
    run(cases)


def test_the_dataset_branch_highlights_its_attachment_either_way() -> None:
    """Rewritten, it matches whichever spelling reached the element.

    Prefixed is the HTML-response path, root-relative the field path -- the
    same attribute, two deliveries, and the comparison must not depend on
    which one the dialog was opened over.
    """
    cases = []
    for name in IMAGE_FIXTURES:
        for label, original_src in (
            ("prefixed data-original-src", INGRESS_PREFIX + IMAGE_SRC),
            ("root-relative data-original-src", IMAGE_SRC),
            ("a prefix from another installation", FOREIGN_PREFIX + IMAGE_SRC),
        ):
            cases.append(
                case(
                    f"{name}: dataset branch, {label}",
                    image_program(
                        as_served(name),
                        image_media(INGRESS_PREFIX + IMAGE_SRC, original_src=original_src),
                    ),
                    [WANTED_ID],
                )
            )
        cases.append(
            case(
                f"{name}: dataset branch, data-original-src of another attachment",
                image_program(
                    as_served(name),
                    image_media(
                        INGRESS_PREFIX + IMAGE_SRC,
                        original_src=INGRESS_PREFIX + OTHER_IMAGE_SRC,
                    ),
                ),
                [OTHER_ID],
            )
        )
        cases.append(
            case(
                f"{name}: dataset branch, no shim",
                image_program(
                    as_served(name), image_media(INGRESS_PREFIX + IMAGE_SRC, original_src=IMAGE_SRC)
                ),
                [WANTED_ID],
                shim=False,
            )
        )
    run(cases)


def test_the_shim_is_not_what_prefixes_the_attribute_that_branch_reads() -> None:
    """So the rule above is not justified by the shim, and says so.

    The markup helper's attribute test is an exact name and the `setAttribute`
    wrapper's list is `href`/`src`/`action`/`xlink:href`, so a value the shim
    handled keeps its `data-original-src` root-relative. The prefix on that
    attribute comes from the generic HTML location instead, which
    `test_a_real_nginx_shows_what_prefixes_data_original_src` executes.
    """
    node(DATASET_HARNESS, {"shim": rendered_shim(INGRESS_PREFIX)})


# --- the document comparison, which was already right -------------------------

@pytest.mark.parametrize("name", DOCUMENT_FIXTURES)
def test_one_generic_rule_reaches_the_document_comparison(name: str) -> None:
    """And it is the generic template-literal rule, prefixing the left side.

    This is the measurement the whole decision rests on. `` `/web/ `` has been
    a rule of this location since #166, the comparison's left operand is the
    template literal `` `/web/content/${attachment.id}` ``, and no other rule
    this location carries occurs in the excerpt -- so the bytes the browser
    receives compare a prefixed literal with a prefixed `href`.
    """
    reaching = generic_rules_reaching(name)
    assert reaching == {TEMPLATE_LITERAL_RULE: 1}, (
        f"{name}: expected exactly the {TEMPLATE_LITERAL_RULE!r} rule to reach this excerpt "
        f"once, found {reaching}; if another rule now reaches it, `as_served` is no longer "
        "what the browser receives and this family's reasoning has to be redone"
    )
    assert INGRESS_PREFIX + "/web/content/" in as_served(name), (
        "the left operand of the comparison must arrive at the browser prefixed"
    )


@pytest.mark.parametrize("name", IMAGE_FIXTURES)
def test_no_generic_rule_reaches_the_image_comparison(name: str) -> None:
    """The other half of the asymmetry, pinned from its own side.

    `attachment.image_src` is an ORM value and the element's reads are DOM
    reads, so no *generic* literal rule can reach either operand -- only this
    issue's own three rules do, which is why they are excluded from the scan.
    That is the difference from the document comparison, whose left operand is
    a literal in the bundle.
    """
    reaching = generic_rules_reaching(name)
    assert reaching == {}, (
        f"{name}: no generic literal rule may reach this excerpt, found {reaching}; a rule "
        "that did would prefix one side of the comparison and the strip would then be "
        "removing a prefix the bundle put there"
    )


def test_a_real_nginx_agrees_about_what_each_excerpt_becomes(tmp_path: Path) -> None:
    """The scan above, executed: the rules applied by nginx, not by `str.replace`.

    The asymmetry this family rests on is a claim about bytes leaving the
    gateway, so it is measured by a real nginx carrying this location's own
    literal rule set over the four captured excerpts. Every driver above runs
    on `as_served`, which applies those rules with `str.replace`; this is what
    says the two are the same thing.
    """
    files = {name: fixture(name) for name in DOCUMENT_FIXTURES + IMAGE_FIXTURES}
    answers = served_by_nginx(tmp_path, files)
    for name in DOCUMENT_FIXTURES + IMAGE_FIXTURES:
        assert answers[("assets", name)] == as_served(name), (
            f"{name}: nginx and `as_served` must agree byte for byte about what this "
            "location serves; they do not, so every driver above is running on bytes the "
            "browser does not get"
        )
    for name in DOCUMENT_FIXTURES:
        assert INGRESS_PREFIX + "/web/content/" in answers[("assets", name)], (
            f"{name}: the comparison's left operand must leave the gateway prefixed"
        )
    for name in IMAGE_FIXTURES:
        # The only change to an image excerpt is this issue's own rewrites, so
        # undoing them gives the captured bytes back: no generic rule reaches
        # either operand of either branch.
        served = answers[("assets", name)]
        for rewrite in REWRITES.values():
            if rewrite["source"] in fixture(name):
                served = served.replace(
                    ingress_rule(template(), rewrite["source"], name), rewrite["source"]
                )
        assert served == fixture(name), (
            f"{name}: no generic rule of this location may change the image comparison"
        )


def test_a_real_nginx_shows_what_prefixes_data_original_src(tmp_path: Path) -> None:
    """The reason the dataset branch is rewritten, executed rather than argued.

    The generic HTML location's rule is written for `src="/` and nginx's
    `sub_filter` is a plain substring search, so it matches inside the longer
    attribute name `data-original-src="/...` -- no neighbouring rule claims
    that position first, and `data-src="/` claims only its own. Page markup
    therefore reaches the browser with a prefixed `data-original-src`, which
    `isInitialMedia`'s first branch compares with an unprefixed
    `attachment.image_src`.
    """
    answers = served_by_nginx(tmp_path, {"page.html": HTML_SAMPLE})
    served = answers[("html", "page.html")]
    assert 'data-original-src="%s%s"' % (INGRESS_PREFIX, IMAGE_SRC) in served, (
        "the generic HTML location must be shown prefixing data-original-src; if it has "
        "stopped doing so, the dataset branch's rewrite is a no-op and its comment is wrong"
    )
    assert 'src="%s%s"' % (INGRESS_PREFIX, IMAGE_SRC) in served, "and the `src` beside it"
    assert 'data-src="%s%s"' % (INGRESS_PREFIX, OTHER_IMAGE_SRC) in served, (
        "`data-src` has a rule of its own and keeps claiming its own position"
    )
    assert HTML_SAMPLE.count(INGRESS_PREFIX) == 0, "the sample itself carries no prefix"


def test_the_document_comparison_highlights_its_attachment_under_ingress() -> None:
    """As served: prefixed literal, prefixed `href`, the attachment selected."""
    cases = [
        case(
            f"{name}: as served, prefixed href",
            document_program(as_served(name), document_media(INGRESS_PREFIX + DOCUMENT_HREF)),
            [WANTED_ID],
        )
        for name in DOCUMENT_FIXTURES
    ]
    run(cases)


def test_the_document_comparison_does_not_highlight_a_different_attachment() -> None:
    cases = [
        case(
            f"{name}: as served, href of the other attachment",
            document_program(
                as_served(name), document_media(INGRESS_PREFIX + OTHER_DOCUMENT_HREF)
            ),
            [OTHER_ID],
        )
        for name in DOCUMENT_FIXTURES
    ]
    run(cases)


def test_the_document_comparison_is_unchanged_on_the_public_origin() -> None:
    cases = [
        case(
            f"{name}: public origin",
            document_program(as_public(name), document_media(DOCUMENT_HREF)),
            [WANTED_ID],
        )
        for name in DOCUMENT_FIXTURES
    ]
    run(cases)


def test_stripping_the_document_href_alone_would_break_it() -> None:
    """The fix the issue asked for, executed, so the refusal is a measurement.

    `OUT` on the `href` and nothing on the left operand leaves an unprefixed
    value compared with a prefixed literal: the dialog would stop highlighting
    the document it came from, on a screen that works today. This is why #239
    ships one rewrite and not two, and it is the one case in this family where
    doing what the issue said would have been a regression.
    """
    cases = []
    for name, rewrite in LEFT_ALONE.items():
        text = as_served(rewrite["fixture"])
        source = rewrite["source"]
        assert source in text, f"{name}: the comparison must be in the served bytes"
        # Exactly the rule the issue asked for: `OUT` around the `href` read,
        # nothing around the literal beside it.
        stripped = (
            "===(window.%s||function(v){return v})(%s)"
            % (OUT_GLOBAL, source[len("==="):])
        )
        cases.append(
            case(
                f"{name}: a one-sided strip stops matching",
                document_program(
                    text.replace(source, stripped),
                    document_media(INGRESS_PREFIX + DOCUMENT_HREF),
                ),
                [],
            )
        )
    run(cases)


def test_no_sub_filter_names_the_document_comparison() -> None:
    """So that the rule the test above refuses cannot be added by accident."""
    offenders = [
        number
        for number, line in directive_lines(template())
        if 'getAttribute("href").replace' in line or "getAttribute('href').replace" in line
    ]
    assert not offenders, (
        f"lines {offenders} rewrite the document comparison's `href`; its left operand is "
        "already prefixed by the generic `/web/ literal rule, so a one-sided strip breaks a "
        "working screen -- see test_stripping_the_document_href_alone_would_break_it"
    )


# --- the fixtures -------------------------------------------------------------

def test_the_readme_records_the_counts_for_every_pattern() -> None:
    """The fixture standard keeps the counts in the README beside the files."""
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    for rewrite in list(REWRITES.values()) + list(LEFT_ALONE.values()):
        assert rewrite["fixture"] in readme, (
            f"fixtures/bundles/README.md must name {rewrite['fixture']}"
        )
    for bundle in BUNDLES:
        assert bundle in readme, (
            f"fixtures/bundles/README.md must record what {bundle} carries; the tests execute "
            "the claim, the README is where a reader finds the per-bundle counts"
        )


def test_the_fixtures_are_verbatim_regions() -> None:
    """Each excerpt is bundle bytes, so it must start and end where it says."""
    for name in IMAGE_FIXTURES:
        text = fixture(name)
        assert text.startswith(
            "isInitialMedia(attachment){if(this.props.media.dataset.originalSrc){"
        )
        assert text.rstrip().endswith("return attachment;});}")
        assert "async fetchAttachments(limit,offset){" in text, (
            "the excerpt is both methods: the comparison and the loop that calls it"
        )
    for name in DOCUMENT_FIXTURES:
        text = fixture(name)
        assert text.startswith(
            "async fetchAttachments(...args){const attachments=await super.fetchAttachments(...args);"
        )
        assert text.rstrip().endswith("return attachments;}")


def test_the_two_dialogs_are_the_same_comparison_in_a_different_quote() -> None:
    """Which is why each comparison needs two rules and not one.

    The quote character is the whole difference at the comparison itself, and
    it is why one pattern cannot serve both files. If a future Odoo made them
    agree, one rule would match twice and the other would become a silent
    no-op, so this is held rather than left to the counts above.
    """
    pairs = (
        ("media_dialog_image_preselect.js", "legacy_media_dialog_image_preselect.js", "src"),
        (
            "media_dialog_document_preselect.js",
            "legacy_media_dialog_document_preselect.js",
            "href",
        ),
    )
    for current, legacy, attribute in pairs:
        assert fixture(current) != fixture(legacy), (
            f"{current} and {legacy} are byte-identical; one rule now covers both and the "
            "second is a no-op -- re-measure before changing the rules"
        )
        assert 'getAttribute("%s")' % attribute in fixture(current)
        assert "getAttribute('%s')" % attribute in fixture(legacy)
        assert "getAttribute('%s')" % attribute not in fixture(current)
        assert 'getAttribute("%s")' % attribute not in fixture(legacy)
