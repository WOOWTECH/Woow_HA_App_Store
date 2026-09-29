#!/usr/bin/env python3
"""Contracts for the Runtime shim's media-source hooks (issue #159).

Odoo's event barcode client action -- the Event Registration Desk -- builds its
sounds with ``new Audio(url("/barcodes/static/src/audio/error.<ext>"))``.
``url()`` makes an absolute same-origin URL, and the Runtime shim wrapped
nothing for media: not the ``Audio`` constructor, not
``HTMLMediaElement.prototype.src``, not ``HTMLSourceElement.prototype.src``. So
under Ingress the request reached the Home Assistant root and answered 404 --
a **Prefix escape**, and a scanner silent on a failed scan. The ``/mail/`` sound
on the next line survived only because ``/mail/`` is a Shipped rewrite.

ADR 0004 makes the Runtime shim the Ingress URL authority for anything it can
intercept, and ``new Audio(...)`` can be intercepted, so the maintainer's triage
put the fix in the shim rather than in the Rewrite scan: one shim change covers
every media prefix at once, where a Generated rewrite covers one at a time.

The wrappers live in the ``$ingress_injection_hooks_shim`` map, the tail of the
prefix script's closure (#169), because that script is ~200 bytes short of
nginx's 4096-byte parameter buffer. They are executed here, in a node ``vm``
context against a minimal DOM stand-in, the same way the injection-way hooks
and the clipboard fallback are, so the contract covers the shim as the page
gets it rather than an excerpt.
"""
import json
import subprocess

from test_ingress_clipboard_fallback import INGRESS_PREFIX, template_shim
from test_ingress_router_rewrite import TEMPLATE

HARNESS = r"""
const assert = require("node:assert/strict");
const vm = require("node:vm");
const shim = JSON.parse(process.argv[1]);
const P = "/api/hassio_ingress/token";
const ORIGIN = "http://ha.example:8123";
const ERROR_SOUND = "/barcodes/static/src/audio/error.ogg";

// A DOM stand-in with the media interfaces the shim wraps. `options` leaves one
// of them out, the way a browser without that constructor does.
function makeContext(options) {
  options = options || {};
  // How many times a `src` property setter ran. The browser's Audio(src)
  // factory reflects its argument into the *content attribute* and not through
  // this setter, so a constructor call must leave the count at zero: that is
  // what makes the constructor wrapper necessary, and what shows the two
  // wrappers cannot prefix the same value twice.
  const setterCalls = [];

  function HTMLMediaElement() { this.attributes = {}; }
  Object.defineProperty(HTMLMediaElement.prototype, "src", {
    get: function () {
      return this.attributes.src === undefined ? "" : this.attributes.src;
    },
    set: function (value) {
      setterCalls.push(value);
      this.attributes.src = String(value);
    },
    configurable: true,
  });

  function HTMLAudioElement() { HTMLMediaElement.call(this); }
  HTMLAudioElement.prototype = Object.create(HTMLMediaElement.prototype);
  HTMLAudioElement.prototype.constructor = HTMLAudioElement;

  function HTMLVideoElement() { HTMLMediaElement.call(this); }
  HTMLVideoElement.prototype = Object.create(HTMLMediaElement.prototype);
  HTMLVideoElement.prototype.constructor = HTMLVideoElement;

  function HTMLSourceElement() { this.attributes = {}; }
  Object.defineProperty(HTMLSourceElement.prototype, "src", {
    get: function () {
      return this.attributes.src === undefined ? "" : this.attributes.src;
    },
    set: function (value) {
      setterCalls.push(value);
      this.attributes.src = String(value);
    },
    configurable: true,
  });

  // The `Audio(src)` factory function, as the spec defines it: it creates an
  // `audio` element and, when `src` is given, sets the src content attribute
  // directly -- not through the JS property setter, and not through
  // `Element.prototype.setAttribute`, so none of the shim's other wrappers see
  // it.
  function Audio(src) {
    const element = new HTMLAudioElement();
    if (src !== undefined) element.attributes.src = String(src);
    return element;
  }
  Audio.prototype = HTMLAudioElement.prototype;

  function Element() {}
  Element.prototype.setAttribute = function () {};
  Element.prototype.setAttributeNS = function () {};
  function XMLHttpRequest() {}
  XMLHttpRequest.prototype.open = function () {};
  function History() {}
  History.prototype.pushState = function () {};
  History.prototype.replaceState = function () {};
  function WebSocket() {}
  const context = {
    document: { body: {}, documentElement: {}, activeElement: null },
    navigator: { serviceWorker: undefined },
    location: { href: ORIGIN + P + "/odoo/action-609", origin: ORIGIN, host: "ha.example:8123" },
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
  if (!options.withoutAudio) context.Audio = Audio;
  if (!options.withoutMediaElement) {
    context.HTMLMediaElement = HTMLMediaElement;
    context.HTMLAudioElement = HTMLAudioElement;
    context.HTMLVideoElement = HTMLVideoElement;
  }
  if (!options.withoutSourceElement) context.HTMLSourceElement = HTMLSourceElement;
  context.window = context;
  vm.createContext(context);
  vm.runInContext(shim, context, { filename: "ingress-runtime-shim.js" });
  return { context, setterCalls, native: { Audio, HTMLAudioElement, HTMLMediaElement } };
}

// new Audio(src): the Registration Desk's own call, built the way url() builds it.
{
  const { context, setterCalls, native } = makeContext({});
  const sound = new context.Audio(context.location.origin + ERROR_SOUND);
  assert.equal(sound.src, P + ERROR_SOUND, "the error sound must carry the Ingress prefix");
  assert.ok(sound.src.endsWith(P + ERROR_SOUND));
  assert.deepEqual(setterCalls, [], "the factory reflects src into the content attribute, not the setter");
  // The wrapper keeps the prototype, the way the Worker wrapper does, so both
  // instanceof checks still hold.
  assert.ok(sound instanceof context.HTMLAudioElement, "instanceof HTMLAudioElement must hold");
  assert.ok(sound instanceof native.HTMLAudioElement);
  assert.ok(sound instanceof context.HTMLMediaElement);
  assert.ok(sound instanceof context.Audio, "new Audio() instanceof Audio must hold");
  assert.ok(new context.Audio() instanceof context.Audio);
  assert.equal(context.Audio.prototype, native.Audio.prototype);
  // No argument: unchanged, and no src attribute is invented.
  const silent = new context.Audio();
  assert.equal(silent.src, "");
  assert.equal("src" in silent.attributes, false, "new Audio() must not gain an src");
  // path()'s own rules, unchanged: already prefixed, cross-origin, blob:, data:
  // and fragment-only values pass through.
  for (const value of [
    P + ERROR_SOUND,
    ORIGIN + P + ERROR_SOUND,
    "https://odoo.example" + ERROR_SOUND,
    "blob:http://ha.example:8123/9f1c",
    "data:audio/ogg;base64,T2dnUw==",
    "#sound",
  ]) {
    assert.equal(new context.Audio(value).src, value === ORIGIN + P + ERROR_SOUND ? P + ERROR_SOUND : value, value);
  }
  // A `URL` object is prefixed too, the way fetch() and sendBeacon() take one.
  assert.equal(new context.Audio(new URL(ORIGIN + ERROR_SOUND)).src, P + ERROR_SOUND);
  assert.equal(
    new context.Audio(new URL("https://odoo.example" + ERROR_SOUND)).src,
    "https://odoo.example" + ERROR_SOUND,
  );
  // Anything else is handed to the browser as it came, as path() does.
  assert.equal(new context.Audio(null).src, "null");
}
// An absent Audio is left absent: the shim must not invent one.
{
  const { context } = makeContext({ withoutAudio: true });
  assert.equal(context.Audio, undefined);
}

// HTMLMediaElement.prototype.src, through <audio> and <video>, and the getter
// the prop() helper keeps.
{
  const { context, setterCalls } = makeContext({});
  for (const Constructor of [context.HTMLAudioElement, context.HTMLVideoElement]) {
    const element = new Constructor();
    element.src = ERROR_SOUND;
    assert.equal(element.src, P + ERROR_SOUND, Constructor.name);
    assert.equal(element.attributes.src, P + ERROR_SOUND, "the native setter must still run");
    // Setting it again over the prefixed value does not prefix twice.
    element.src = element.src;
    assert.equal(element.src, P + ERROR_SOUND, "an already prefixed src must not be prefixed twice");
    for (const value of [
      "https://odoo.example" + ERROR_SOUND,
      "blob:http://ha.example:8123/9f1c",
      "data:audio/ogg;base64,T2dnUw==",
      "#sound",
    ]) {
      element.src = value;
      assert.equal(element.src, value, value);
    }
  }
  assert.ok(setterCalls.length > 0, "the wrapper must delegate to the native setter");
}
// An absent HTMLMediaElement is skipped, not thrown on: prop() returns early.
{
  const { context } = makeContext({ withoutMediaElement: true });
  assert.equal(context.HTMLMediaElement, undefined);
  assert.equal(typeof context.fetch, "function");
  assert.notEqual(context.fetch.toString(), "fetch() {}", "the rest of the shim must still have run");
}

// HTMLSourceElement.prototype.src: the <source> children of a <video>.
{
  const { context } = makeContext({});
  const source = new context.HTMLSourceElement();
  source.src = ERROR_SOUND;
  assert.equal(source.src, P + ERROR_SOUND);
  source.src = P + ERROR_SOUND;
  assert.equal(source.src, P + ERROR_SOUND);
  source.src = "https://odoo.example" + ERROR_SOUND;
  assert.equal(source.src, "https://odoo.example" + ERROR_SOUND);
}
// An absent HTMLSourceElement is skipped the same way.
{
  const { context } = makeContext({ withoutSourceElement: true });
  assert.equal(context.HTMLSourceElement, undefined);
  assert.equal(typeof context.open, "function");
}
"""


def test_media_sources_prefix_through_the_apis_the_shim_wraps() -> None:
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


def test_media_hooks_reuse_the_shims_own_helpers() -> None:
    """One URL helper and one property-setter helper, not a second of either (#159)."""
    shim = template_shim(TEMPLATE.read_text(encoding="utf-8"))
    assert 'prop(window.HTMLMediaElement&&HTMLMediaElement.prototype,"src")' in shim
    assert 'prop(window.HTMLSourceElement&&HTMLSourceElement.prototype,"src")' in shim
    assert "window.Audio.prototype=AU.prototype" in shim, (
        "the Audio wrapper must keep the prototype, as the Worker wrapper does, so "
        "instanceof HTMLAudioElement still holds"
    )
    assert shim.count("var path=function(u)") == 1, "the media hooks must reuse path(), not add a helper"
    assert shim.count("var prop=function(proto,n)") == 1, "the media hooks must reuse prop()"
    # Out of scope by decision (#159): nothing reported them escaping. `srcset` is
    # in the shim for HTMLImageElement, so `<source>`'s is checked by prototype.
    for absent in ('"poster"', '"srcObject"', "HTMLTrackElement", "HTMLObjectElement", "HTMLEmbedElement"):
        assert absent not in shim, f"{absent} is out of scope for #159; add it when a test shows the escape"
    assert 'HTMLSourceElement.prototype,"srcset"' not in shim, (
        "HTMLSourceElement.srcset is the responsive <picture> candidate list, not a media "
        "source, and has not been reported escaping; it is out of scope for #159 by decision"
    )
