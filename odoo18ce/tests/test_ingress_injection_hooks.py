#!/usr/bin/env python3
"""Contracts for the Runtime shim's injection-way hooks (issue #169).

`U-A6` probes each way a root-relative URL can reach the browser. Seven of
them escaped to the Home Assistant root under Ingress, and the maintainer's
triage split them in two:

- **Group A, covered.** `navigator.sendBeacon`, `new EventSource`, and the SVG
  `<use>` reference set through `setAttribute("xlink:href", ...)`,
  `setAttribute("href", ...)` or `setAttributeNS(...)`. ADR 0004 makes the
  Runtime shim the Ingress URL authority for anything it can intercept, and
  each of these is one wrapper in the shim's existing pattern.
- **Group B, uncovered by decision.** HTML inserted as markup (`innerHTML`,
  `insertAdjacentHTML`, `outerHTML`), the `style` attribute and the text of a
  dynamic `<style>` element. The HTML editor and the website editor load and
  save record content through those paths, so a hook would write the Ingress
  prefix -- which carries the Ingress token -- into the database. A screen
  that hits one gets a route-scoped Literal rewrite of its own (#158, #170),
  or -- where the value round-trips through the editor, as a to-do description
  does (#210) -- a pair of rewrites that put the prefix on at the render site
  and take it off again at the save site. Both shapes call helpers the shim
  *publishes*; neither intercepts a property, which is why the assertion below
  still holds after them.

Group A is executed here, in a node ``vm`` context against a minimal DOM
stand-in, the same way the clipboard fallback is; Group B is asserted absent
from the shim text, so a later change has to reopen the decision.
"""
import json
import subprocess

from test_ingress_clipboard_fallback import INGRESS_PREFIX, template_shim
from test_ingress_router_rewrite import TEMPLATE

# Nothing in the shim may hook the ways Group B goes through. `style` is
# matched as the attribute name and as the CSS APIs a hook would need; the
# clipboard fallback's own `ta.style.position` is neither.
GROUP_B_HOOKS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "CSSStyleDeclaration",
    "cssText",
    "setProperty",
    "styleSheets",
    '"style"',
)

HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const shim = JSON.parse(process.argv[1]);
const P = "/api/hassio_ingress/token";
const ORIGIN = "http://ha.example:8123";
const XLINK = "http://www.w3.org/1999/xlink";

// A DOM stand-in with the two constructors and the element APIs the hooks
// wrap. `options` leaves either constructor out, the way a browser without
// `sendBeacon` or without `EventSource` does.
function makeContext(options) {
  options = options || {};
  const beacons = [];
  const navigator = { serviceWorker: undefined };
  if (!options.withoutSendBeacon) {
    navigator.sendBeacon = function (url, data) {
      beacons.push({ url, data, self: this });
      return true;
    };
  }
  function EventSource(url, init) {
    this.url = String(url);
    this.init = init;
    this.readyState = EventSource.CONNECTING;
  }
  EventSource.prototype.close = function () { this.readyState = EventSource.CLOSED; };
  EventSource.CONNECTING = 0;
  EventSource.OPEN = 1;
  EventSource.CLOSED = 2;
  function Element() { this.attributes = {}; this.attributesNS = {}; }
  // setAttribute() matches an existing attribute by qualified name whatever its namespace,
  // and only creates one in no namespace when there is none: that is what makes
  // setAttribute("xlink:href", ...) reach the SVG <use> reference a page rendered as markup,
  // and what makes the same call on a fresh element land somewhere SVG ignores.
  Element.prototype.setAttribute = function (name, value) {
    const existing = Object.keys(this.attributesNS).find((key) => key.split("|")[1] === name);
    if (existing) this.attributesNS[existing] = String(value);
    else this.attributes[name] = String(value);
  };
  Element.prototype.setAttributeNS = function (ns, name, value) {
    this.attributesNS[String(ns) + "|" + name] = String(value);
  };
  function XMLHttpRequest() {}
  XMLHttpRequest.prototype.open = function () {};
  function History() {}
  History.prototype.pushState = function () {};
  History.prototype.replaceState = function () {};
  function WebSocket() {}
  const context = {
    document: { body: {}, documentElement: {}, activeElement: null },
    navigator,
    location: { href: ORIGIN + P + "/odoo", origin: ORIGIN, host: "ha.example:8123" },
    sessionStorage: { getItem() { return null; }, setItem() {} },
    fetch() {},
    open() {},
    XMLHttpRequest,
    History,
    Element,
    WebSocket,
    URL,
    Request: function () {},
  };
  if (!options.withoutEventSource) context.EventSource = EventSource;
  context.window = context;
  vm.createContext(context);
  vm.runInContext(shim, context, { filename: "ingress-runtime-shim.js" });
  return { context, beacons, native: { EventSource } };
}

// navigator.sendBeacon: the URL is prefixed, the return value and `this` are the browser's.
{
  const { context, beacons } = makeContext({});
  assert.equal(context.navigator.sendBeacon("/web/parity", "payload"), true);
  assert.deepEqual([beacons[0].url, beacons[0].data], [P + "/web/parity", "payload"]);
  assert.equal(beacons[0].self, context.navigator, "sendBeacon must keep its navigator binding");
  context.navigator.sendBeacon(new URL(ORIGIN + "/web/parity"));
  assert.equal(beacons[1].url, P + "/web/parity", "a URL first argument is prefixed too");
  // Already prefixed, cross-origin and fragment-only values pass through unchanged.
  for (const value of [P + "/web/parity", "https://odoo.example/web/parity", "#frag"]) {
    context.navigator.sendBeacon(value);
    assert.equal(beacons[beacons.length - 1].url, value, value);
  }
}
// An absent sendBeacon is left absent: the shim must not invent one.
{
  const { context } = makeContext({ withoutSendBeacon: true });
  assert.equal(context.navigator.sendBeacon, undefined);
}

// new EventSource: the URL is prefixed, and the wrapper keeps the constructor's shape.
{
  const { context, native } = makeContext({});
  const source = new context.EventSource("/longpolling/poll");
  assert.equal(source.url, P + "/longpolling/poll");
  assert.ok(source instanceof context.EventSource, "instanceof must hold through the wrapper");
  assert.ok(source instanceof native.EventSource);
  assert.equal(typeof source.close, "function");
  assert.deepEqual(
    [context.EventSource.CONNECTING, context.EventSource.OPEN, context.EventSource.CLOSED],
    [0, 1, 2],
    "the readyState constants must survive the wrapper",
  );
  assert.deepEqual(new context.EventSource("/poll", { withCredentials: true }).init, { withCredentials: true });
  for (const value of [P + "/poll", "https://odoo.example/poll", "#frag"]) {
    assert.equal(new context.EventSource(value).url, value, value);
  }
}
// An absent EventSource is left absent.
{
  const { context } = makeContext({ withoutEventSource: true });
  assert.equal(context.EventSource, undefined);
}

// The SVG <use> reference, through both APIs that set it.
{
  const { context } = makeContext({});
  const node = new context.Element();
  node.setAttribute("xlink:href", "/web/image/1");
  assert.equal(node.attributes["xlink:href"], P + "/web/image/1");
  // The same call over a reference that arrived as markup: the shim prefixes it, and the DOM
  // writes it to the XLink-namespaced attribute SVG actually reads (U-A6's `svg-use` probe).
  const rendered = new context.Element();
  rendered.setAttributeNS(XLINK, "xlink:href", "#seed");
  rendered.setAttribute("xlink:href", "/web/image/9");
  assert.equal(rendered.attributesNS[XLINK + "|xlink:href"], P + "/web/image/9");
  assert.deepEqual(rendered.attributes, {}, "an existing xlink:href is updated, not shadowed");
  node.setAttribute("href", "/web/image/2");
  assert.equal(node.attributes.href, P + "/web/image/2");
  node.setAttributeNS(XLINK, "xlink:href", "/web/image/3");
  assert.equal(node.attributesNS[XLINK + "|xlink:href"], P + "/web/image/3");
  node.setAttributeNS(null, "src", "/web/image/4");
  assert.equal(node.attributesNS["null|src"], P + "/web/image/4");
  node.setAttributeNS(null, "action", "/web/image/5");
  assert.equal(node.attributesNS["null|action"], P + "/web/image/5");
  // Another attribute in the same namespace is not a URL the shim owns.
  node.setAttributeNS(XLINK, "xlink:title", "/web/image/6");
  assert.equal(node.attributesNS[XLINK + "|xlink:title"], "/web/image/6");
  // A fragment-only reference is the document's own, an already prefixed or
  // cross-origin one is already where it belongs.
  for (const [name, value] of [
    ["xlink:href", "#icon"],
    ["href", P + "/web/image/7"],
    ["href", "https://odoo.example/web/image/8"],
  ]) {
    // A fresh element each time: setAttribute() would otherwise find the attribute the
    // setAttributeNS() case left behind and write there instead.
    const plain = new context.Element();
    plain.setAttribute(name, value);
    assert.equal(plain.attributes[name], value, name + "=" + value);
    const namespaced = new context.Element();
    namespaced.setAttributeNS(XLINK, name, value);
    assert.equal(namespaced.attributesNS[XLINK + "|" + name], value, name + "=" + value);
  }
}
"""


def test_ingress_injection_hooks_prefix_through_the_apis_they_wrap() -> None:
    from conftest import require_tool

    template = TEMPLATE.read_text(encoding="utf-8")
    assert INGRESS_PREFIX == "/api/hassio_ingress/token"
    result = subprocess.run(
        [require_tool("node"), "-e", HARNESS, json.dumps(template_shim(template))],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_the_shim_hooks_nothing_group_b_goes_through() -> None:
    """Group B is uncovered by decision (#169); reopening it is a decision, not a patch."""
    shim = template_shim(TEMPLATE.read_text(encoding="utf-8"))
    for hook in GROUP_B_HOOKS:
        assert hook not in shim, (
            f"the Runtime shim must not touch {hook}: the HTML and website editors save record "
            "content through markup and style, so a prefix written there reaches the database and "
            "carries the Ingress token (#169 Group B; #158 and #170 are route-scoped rewrites "
            "instead). Reopen the decision in ADR 0004 before adding this hook."
        )
