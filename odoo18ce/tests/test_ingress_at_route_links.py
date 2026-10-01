#!/usr/bin/env python3
"""Contracts for the `/@` links into the web client (issue #211, U-A2).

`/@/<website path>` is Odoo 18's route from a website page into the backend,
and it is the one route whose *tail* is itself a website path rather than a
URL to fetch. Two places in the bundles build such a link, and both splice
`location.pathname` -- which under Ingress already carries the prefix -- into
that tail::

    currentUrl.pathname = `/@${currentUrl.pathname}`

The tail became ``/@<PREFIX>/shop/payment``. The Runtime shim's ``path()``
spots a prefix at position 0 and nowhere else, so it did not recognise that
one and added a second, and the "Edit this content" button on every website
page whose viewer may edit it rendered::

    href="<PREFIX>/@<PREFIX>/shop/payment"

which made the web client open ``/api/hassio_ingress/<token>/shop/payment`` as
a website path. The #163 run measured it on ``/shop/payment``; ``/shop`` shows
the same literal.

The fix is the second of the two the issue names: build the tail from the
canonical path and put the prefix on once, at the front. That value is the
right one for every consumer of these two builders, which is why the prefix
goes on here rather than being left to the shim -- ``backendEditBtnEl.href``
does go through the shim's anchor-href setter, but redirect.js's two
``window.location.replace(currentUrl.href)`` calls are writes to ``location``,
which ADR 0004 says the shim cannot wrap, and the popover hands
``browser.open`` a **URL object**, which the shim's ``window.open`` wrapper
passes through untouched because it prefixes strings only.

What is pinned here:

- **The rewrites match the bundle.** An unmatched ``sub_filter`` is a silent
  no-op, so each pattern is counted in bytes captured from the bundles the
  control group serves, kept under ``fixtures/bundles/``.
- **Ingress only.** ``ingress_rule`` refuses a rule found outside the Ingress
  asset location, which would change what the Public origin serves.
- **nginx parses what the tests model.** A ``sub_filter`` parameter may not
  carry ``${`` -- nginx reads it as a variable and there is no escape for
  ``$`` -- so the pattern stops at the backtick and the replacement re-emits
  one, turning the untouched tail into the arguments of a tagged template. A
  real nginx serves both fixtures through the template's own two rule lines
  and the bytes are compared with the substitution the rest of this file
  assumes.
- **The behaviour**, executed in node against the rendered Runtime shim: the
  reported literal reproduced before the rewrite, the single prefix after it,
  the two ``location.replace`` paths redirect.js takes, the popover's
  ``browser.open``, and the Public origin unchanged.
"""
import json
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from test_ingress_clipboard_fallback import INGRESS_PREFIX, clipboard_shim
from test_ingress_router_rewrite import TEMPLATE, ingress_rule, runtime_shim

FIXTURES = Path(__file__).resolve().parent / "fixtures/bundles"

EDIT = "website_frontend_to_backend_edit.js"
POPOVER = "website_link_popover_preview.js"

# The page the #163 run measured, and a content link of the kind the website
# editor's link popover is opened on.
PAGE = "/shop/payment"
LINK = "/shop/conference-chair-1"

# Documentation host only (RFC 2606); no real address here.
ORIGIN = "http://ha.example:8123"

# Each rewrite: the exact expression the Ingress asset location matches, and
# how many times it occurs in each fixture. A count of zero is a measurement
# too: it says the rule does not reach that site.
REWRITES = {
    "edit link builder": {
        "source": "currentUrl.pathname=`/@",
        "counts": {EDIT: 1, POPOVER: 1},
    },
    "popover backend-form guard": {
        "source": "!currentUrl.pathname.startsWith('/@/')",
        "counts": {EDIT: 0, POPOVER: 1},
    },
}


def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def replacement(rewrite: dict, prefix: str = INGRESS_PREFIX) -> str:
    """The rule's replacement, with `$safe_ingress_path` rendered as `prefix`."""
    text = ingress_rule(template(), rewrite["source"], rewrite["source"])
    return text if prefix == INGRESS_PREFIX else text.replace(INGRESS_PREFIX, prefix)


def rewritten(name: str, prefix: str = INGRESS_PREFIX) -> str:
    """The fixture as the Ingress asset location serves it.

    Every rule is applied, because nginx applies every rule: the popover
    fixture carries both patterns and the edit-link fixture carries one.
    """
    text = fixture(name)
    for rewrite in REWRITES.values():
        text = text.replace(rewrite["source"], replacement(rewrite, prefix))
    return text


def rendered_shim(prefix: str) -> str:
    text = template()
    return "\n".join(
        script.replace("$safe_ingress_path", prefix).replace("%%INGRESS_CACHE_VERSION%%", "V")
        for script in (clipboard_shim(text), runtime_shim(text))
    )


# --- the node harness ---------------------------------------------------------

# Enough of a browser for the rendered Runtime shim to install itself and for
# the two bundle excerpts to run inside it. The anchor carries a real `href`
# accessor, because the shim wraps `HTMLAnchorElement.prototype.href` and that
# wrapper is exactly what decides whether the edit button ends up prefixed
# once or twice.
HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const ORIGIN = "http://ha.example:8123";

function context(prefix, page) {
  const record = { replaced: [], opened: [], prevented: 0, keydown: null, loaded: null };
  function HTMLAnchorElement() {}
  Object.defineProperty(HTMLAnchorElement.prototype, "href", {
    configurable: true,
    get() { return this._href; },
    set(value) { this._href = String(value); },
  });
  function Element() {}
  Element.prototype.setAttribute = function () {};
  Element.prototype.setAttributeNS = function () {};
  function XMLHttpRequest() {}
  XMLHttpRequest.prototype.open = function () {};
  function History() {}
  History.prototype.pushState = function () {};
  History.prototype.replaceState = function () {};
  function WebSocket() {}
  const editButton = new HTMLAnchorElement();
  const classList = { add() {}, remove() {} };
  const context = {
    record,
    editButton,
    session: { is_website_user: false },
    document: {
      body: { innerHTML: "page" },
      documentElement: {},
      activeElement: null,
      addEventListener(name, handler) {
        if (name === "DOMContentLoaded") record.loaded = handler;
        if (name === "keydown") record.keydown = handler;
      },
      querySelector(selector) {
        if (selector === ".o_frontend_to_backend_nav") return { classList };
        if (selector === ".o_frontend_to_backend_edit_btn") return editButton;
        return null;
      },
      getElementById() { return null; },
    },
    navigator: { serviceWorker: undefined },
    location: {
      origin: ORIGIN,
      host: "ha.example:8123",
      hostname: "ha.example",
      href: ORIGIN + prefix + page,
      replace(value) { record.replaced.push(String(value)); },
    },
    sessionStorage: { getItem() { return null; }, setItem() {} },
    fetch() { return Promise.resolve(); },
    open(value) { record.opened.push(String(value)); },
    HTMLAnchorElement,
    XMLHttpRequest,
    History,
    Element,
    WebSocket,
    URL,
    CustomEvent: function () {},
    Request: function () {},
  };
  context.window = context;
  vm.createContext(context);
  return context;
}

(async () => {
  for (const testCase of JSON.parse(process.argv[1])) {
    const scope = context(testCase.prefix, testCase.page);
    if (testCase.shim) vm.runInContext(testCase.shim, scope, { filename: "shim.js" });
    // `browser` is Odoo's window wrapper: `browser.open` is `window.open`,
    // and under Ingress that is the shim's wrapper around it.
    scope.browser = { open: (...args) => scope.window.open(...args) };
    vm.runInContext(testCase.program, scope, { filename: "bundle.js" });
    // Through JSON, because the result is built inside the vm context and
    // its prototype is that context's, not this one's.
    const actual = JSON.parse(JSON.stringify(await scope.result));
    assert.deepEqual(actual, testCase.expected, testCase.name);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""

# redirect.js registers its listener on `DOMContentLoaded`; the harness keeps
# the callback and this driver runs it, then reports the address the edit
# button carries and anything the page navigated to.
EDIT_DRIVER = """
__SLICE__
result = (() => {
  record.loaded();
  return { href: editButton.href ?? null, replaced: record.replaced };
})();
"""

# The alt+A shortcut, which redirect.js registers on the same URL object.
EDIT_SHORTCUT_DRIVER = """
__SLICE__
result = (() => {
  record.loaded();
  record.keydown({ key: "a", altKey: true });
  return { href: editButton.href ?? null, replaced: record.replaced };
})();
"""

# The website editor's link popover, driven with one link.
POPOVER_DRIVER = """
const widget = { target: { href: __HREF__ }, __SLICE__ };
result = (async () => {
  await widget._onPreviewLinkClick({ preventDefault() { record.prevented += 1; } });
  return { opened: record.opened, prevented: record.prevented };
})();
"""


def node(cases: list[dict]) -> None:
    from conftest import require_tool

    result = subprocess.run(
        [require_tool("node"), "-e", HARNESS, json.dumps(cases)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def edit_case(
    name: str,
    prefix: str,
    text: str,
    expected: dict,
    driver: str = EDIT_DRIVER,
    page: str = PAGE,
) -> dict:
    return {
        "name": name,
        "prefix": prefix,
        "page": page,
        "shim": rendered_shim(prefix) if prefix else "",
        "program": driver.replace("__SLICE__", text.strip()),
        "expected": expected,
    }


def popover_case(name: str, prefix: str, text: str, href: str, expected: dict) -> dict:
    return {
        "name": name,
        "prefix": prefix,
        "page": PAGE,
        "shim": rendered_shim(prefix) if prefix else "",
        "program": (
            POPOVER_DRIVER.replace("__SLICE__", text.strip())
            .replace("__HREF__", json.dumps(href))
        ),
        "expected": expected,
    }


# --- the rules ----------------------------------------------------------------

@pytest.mark.parametrize("name", REWRITES)
def test_the_rewrite_is_ingress_only(name: str) -> None:
    """A rule on the 8069 listener would change what the Public origin serves."""
    ingress_rule(template(), REWRITES[name]["source"], name)


@pytest.mark.parametrize("name", REWRITES)
@pytest.mark.parametrize("bundle", [EDIT, POPOVER])
def test_the_rewrite_matches_the_fixture_the_expected_number_of_times(name: str, bundle: str) -> None:
    """A pattern that does not match is a silent no-op, so measure it."""
    rewrite = REWRITES[name]
    found = fixture(bundle).count(rewrite["source"])
    assert found == rewrite["counts"][bundle], (
        f"{name}: {bundle} holds {found} occurrences of {rewrite['source']!r}, "
        f"expected {rewrite['counts'][bundle]}; re-capture the fixture and re-measure the rule"
    )


@pytest.mark.parametrize("name", REWRITES)
def test_no_pattern_carries_an_nginx_variable(name: str) -> None:
    """nginx reads `$` in a quoted parameter as a variable, in the pattern too.

    That is why the builder's pattern stops at the backtick instead of
    carrying the template literal's `${...}` interpolation.
    """
    assert "$" not in REWRITES[name]["source"], (
        f"{name}: a sub_filter pattern cannot contain `$`; anchor it before the interpolation"
    )


def test_the_builder_rewrite_keeps_the_tagged_template_intact() -> None:
    """The replacement re-emits the backtick the pattern consumed.

    Without it the interpolation left behind would open a template literal
    that nothing closes, and nginx would have served a broken bundle.
    """
    assert REWRITES["edit link builder"]["source"].endswith("`/@")
    assert replacement(REWRITES["edit link builder"]).endswith("`")


def test_the_guard_rewrite_accepts_the_prefixed_spelling_beside_the_bare_one() -> None:
    """The Public surface's behaviour, kept: a backend-form link is left alone."""
    text = replacement(REWRITES["popover backend-form guard"])
    assert text.count("startsWith('/@/')") == 1
    assert text.count("startsWith('%s/@/')" % INGRESS_PREFIX) == 1


@pytest.mark.parametrize("name", REWRITES)
def test_the_readme_records_the_pattern_that_ships(name: str) -> None:
    """A shortened stand-in in the table would be a count of another pattern."""
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
    edit = fixture(EDIT)
    assert edit.startswith("document.addEventListener('DOMContentLoaded',()=>{")
    assert edit.rstrip().endswith(
        "window.frameElement.dispatchEvent(new CustomEvent('OdooFrameContentLoaded'));}});"
    )
    popover = fixture(POPOVER)
    assert popover.startswith("async _onPreviewLinkClick(ev){")
    assert popover.rstrip().endswith("browser.open(currentUrl);}}}")


# --- the edit button ----------------------------------------------------------

def test_the_edit_link_doubles_the_prefix_without_the_rewrite() -> None:
    """The starting point: the literal the #163 run recorded, reproduced."""
    doubled = INGRESS_PREFIX + "/@" + INGRESS_PREFIX + PAGE
    node([edit_case(
        "edit button, as Odoo ships it",
        INGRESS_PREFIX,
        fixture(EDIT),
        {"href": doubled, "replaced": []},
    )])


def test_the_rewrite_puts_the_prefix_on_the_link_once() -> None:
    once = INGRESS_PREFIX + "/@" + PAGE
    assert INGRESS_PREFIX not in once[len(INGRESS_PREFIX):], "the prefix must appear once"
    node([edit_case(
        "edit button, under Ingress",
        INGRESS_PREFIX,
        rewritten(EDIT),
        {"href": once, "replaced": []},
    )])


def test_the_public_origin_keeps_the_link_odoo_builds() -> None:
    """The rules are ingress-only; rendered with no prefix they change nothing.

    With no Runtime shim nothing rewrites the anchor's value, so what is
    stored is the absolute `currentUrl.href` -- which is what an anchor's
    `href` reads back as anyway. Under Ingress the shim's setter turns that
    same value into the root-relative literal the page carries.
    """
    for text in (fixture(EDIT), rewritten(EDIT, "")):
        node([edit_case(
            "edit button, no prefix", "", text,
            {"href": ORIGIN + "/@" + PAGE, "replaced": []},
        )])


def test_the_editor_redirect_leaves_for_the_prefixed_web_client() -> None:
    """`?enable_editor` replaces the whole frame, and `location` is not wrapped."""
    page = PAGE + "?enable_editor=1"
    node([edit_case(
        "enable_editor redirect",
        INGRESS_PREFIX,
        rewritten(EDIT),
        {"href": None, "replaced": [ORIGIN + INGRESS_PREFIX + "/@" + page]},
        page=page,
    )])


def test_the_alt_a_shortcut_leaves_for_the_prefixed_web_client() -> None:
    node([edit_case(
        "alt+A shortcut",
        INGRESS_PREFIX,
        rewritten(EDIT),
        {"href": INGRESS_PREFIX + "/@" + PAGE,
         "replaced": [ORIGIN + INGRESS_PREFIX + "/@" + PAGE + "?enable_editor=1"]},
        driver=EDIT_SHORTCUT_DRIVER,
    )])


# --- the link popover ---------------------------------------------------------

def test_the_popover_opens_the_prefixed_web_client() -> None:
    node([popover_case(
        "popover, under Ingress",
        INGRESS_PREFIX,
        rewritten(POPOVER),
        ORIGIN + INGRESS_PREFIX + LINK,
        {"opened": [ORIGIN + INGRESS_PREFIX + "/@" + LINK], "prevented": 1},
    )])


def test_the_popover_loses_the_prefix_altogether_without_the_rewrite() -> None:
    """The same builder on the second site, and a worse ending.

    `browser.open` is handed a **URL object**, and the shim's `window.open`
    wrapper prefixes strings only -- so the address keeps the prefix Odoo
    spliced into the `/@` tail and carries none of its own. The window opens
    at the Home Assistant root.
    """
    node([popover_case(
        "popover, as Odoo ships it",
        INGRESS_PREFIX,
        fixture(POPOVER),
        ORIGIN + INGRESS_PREFIX + LINK,
        {"opened": [ORIGIN + "/@" + INGRESS_PREFIX + LINK], "prevented": 1},
    )])


def test_a_link_already_in_backend_form_is_left_alone() -> None:
    """What the guard rewrite is for: Odoo's own check, reading a prefixed path."""
    node([popover_case(
        "popover, an already /@/ link",
        INGRESS_PREFIX,
        rewritten(POPOVER),
        ORIGIN + INGRESS_PREFIX + "/@" + LINK,
        {"opened": [], "prevented": 0},
    )])


def test_without_the_guard_rewrite_an_already_backend_link_doubles_the_route() -> None:
    """The starting point for the guard: Odoo's check never fires under Ingress."""
    text = fixture(POPOVER).replace(
        REWRITES["edit link builder"]["source"],
        replacement(REWRITES["edit link builder"]),
    )
    node([popover_case(
        "popover, builder rewritten and guard not",
        INGRESS_PREFIX,
        text,
        ORIGIN + INGRESS_PREFIX + "/@" + LINK,
        {"opened": [ORIGIN + INGRESS_PREFIX + "/@/@" + LINK], "prevented": 1},
    )])


def test_a_cross_host_link_is_left_alone() -> None:
    node([popover_case(
        "popover, a link to another host",
        INGRESS_PREFIX,
        rewritten(POPOVER),
        "https://other.example/shop/x",
        {"opened": [], "prevented": 0},
    )])


def test_a_link_to_another_origin_on_the_same_host_keeps_odoos_own_value() -> None:
    """The popover admits a link by *hostname*, which is not an origin.

    An absolute link to the add-on's own 8069 listener shares the Home
    Assistant hostname and so reaches the builder, with a path that has no
    Ingress prefix and wants none. It must come out as Odoo built it.
    """
    other = "http://ha.example:8069"
    node([popover_case(
        "popover, the same host on another port",
        INGRESS_PREFIX,
        rewritten(POPOVER),
        other + LINK,
        {"opened": [other + "/@" + LINK], "prevented": 1},
    )])


def test_the_popover_on_the_public_origin_is_unchanged() -> None:
    node([
        popover_case("popover, no prefix", "", rewritten(POPOVER, ""),
                     ORIGIN + LINK, {"opened": [ORIGIN + "/@" + LINK], "prevented": 1}),
        popover_case("popover, no prefix, already /@/", "", rewritten(POPOVER, ""),
                     ORIGIN + "/@" + LINK, {"opened": [], "prevented": 0}),
    ])


# --- nginx serves what the tests model ----------------------------------------

class _Bundle(BaseHTTPRequestHandler):
    """Serves each fixture as the asset route serves a bundle."""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        name = self.path.rsplit("/", 1)[-1]
        if name not in (EDIT, POPOVER):
            self.send_error(404)
            return
        body = fixture(name).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def rule_lines() -> list[str]:
    """The two `sub_filter` lines as the template writes them, byte for byte."""
    text = template()
    lines = []
    for rewrite in REWRITES.values():
        source = rewrite["source"]
        quoted = "'%s'" % source if "'" not in source else '"%s"' % source
        found = [
            line.strip() for line in text.splitlines()
            if line.strip().startswith("sub_filter " + quoted + " ")
        ]
        assert len(found) == 1, f"expected one rule line for {source!r}, found {found}"
        lines.append(found[0])
    return lines


def _fetch(socket: Path, name: str) -> str:
    from conftest import require_tool

    result = subprocess.run(
        [require_tool("curl"), "-s", "--unix-socket", str(socket),
         f"http://localhost/web/assets/1/{name}"],
        text=True, capture_output=True, check=True,
    )
    return result.stdout


def test_a_real_nginx_serves_the_substitution_the_tests_model() -> None:
    """The quoting traps are nginx's, so let nginx answer them.

    A pattern may not carry `${`, a parameter may not carry its own quote,
    and a `sub_filter` that fails either way is a silent no-op rather than an
    error. This renders the template's own two rule lines into a running
    nginx and compares the bytes it serves with `rewritten()`.
    """
    from conftest import require_tool

    require_tool("curl")
    nginx = require_tool("nginx")
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _Bundle)
    thread = Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="odoo-at-route-nginx-") as directory:
            root = Path(directory)
            socket = root / "ingress.sock"
            config = root / "nginx.conf"
            rules = "\n    ".join(rule_lines())
            config.write_text(
                f"""daemon off;
master_process off;
pid {root / "nginx.pid"};
error_log {root / "error.log"} notice;
events {{}}
http {{
  access_log off;
  server {{
    listen unix:{socket};
    set $safe_ingress_path {INGRESS_PREFIX};
    sub_filter_once off;
    sub_filter_types application/javascript;
    {rules}
    location / {{ proxy_pass http://127.0.0.1:{upstream.server_port}; }}
  }}
}}
""",
                encoding="utf-8",
            )
            subprocess.run(
                [nginx, "-t", "-p", str(root), "-c", str(config)],
                check=True, capture_output=True, text=True,
            )
            process = subprocess.Popen(
                [nginx, "-p", str(root), "-c", str(config)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                for _ in range(200):
                    if socket.exists():
                        break
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        raise AssertionError(f"nginx harness exited: {stdout}{stderr}")
                    time.sleep(0.02)
                else:
                    raise AssertionError("the nginx harness socket did not become ready")
                for name in (EDIT, POPOVER):
                    assert _fetch(socket, name) == rewritten(name), (
                        f"{name}: nginx served bytes the tests do not model"
                    )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    finally:
        upstream.shutdown()
        upstream.server_close()
