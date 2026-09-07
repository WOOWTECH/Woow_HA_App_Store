// HA Ingress path-rewriting shim for the Omnigent React SPA.
// Injected by nginx sub_filter into <head> so the bundle transparently
// dials back through /api/hassio_ingress/<slug>/ instead of the naked /.
//
// Strategy (evolved after many failed attempts to patch the bundled router
// library from the outside):
//
//   1. On first script execution — BEFORE any React/module code runs —
//      call `history.replaceState()` to strip the ingress prefix from
//      the iframe's own URL. From that moment on, `window.location.
//      pathname` returns `/login`, `/settings`, `/` etc., so omnigent's
//      router sees paths it recognises and matches routes normally.
//
//   2. Patch `fetch` / `XMLHttpRequest.open` / `WebSocket` / `history.
//      pushState/replaceState` / `Location.prototype.assign/replace/href`
//      so any code that emits a bare root-absolute path (`/v1/foo`, `/
//      auth/login`, etc.) gets the ingress prefix prepended when
//      actually going over the wire or updating the URL bar.
//
// Trade-off: reloading the iframe with the stripped URL (e.g. `/login`)
// would hit HA's origin and 404. Users interact via the parent HA UI
// though, not directly with the iframe URL, so this is acceptable.
//
// LAN direct (no `window.__INGRESS_PATH__` set) bypasses the whole thing.
(function () {
  var p = window.__INGRESS_PATH__;
  if (!p) return;

  // ---- Step 1: strip the ingress prefix from the iframe URL --------------
  // Do this synchronously, before React parses `location.pathname`. If our
  // URL already lives outside the prefix (someone reloaded from elsewhere)
  // this no-ops.
  try {
    var here = location.pathname;
    if (here.indexOf(p) === 0) {
      var stripped = here.substring(p.length) || "/";
      history.replaceState(history.state, "", stripped + location.search + location.hash);
    }
  } catch (e) { /* replaceState on cross-origin iframes throws — best-effort */ }

  // Path prefixer used by every network shim below.
  function pfx(u) {
    if (typeof u === "string" && u.charAt(0) === "/" && u.indexOf(p) !== 0 && u.indexOf("//") !== 0) {
      return p + u;
    }
    return u;
  }

  // ---- Step 2: network shims ---------------------------------------------
  var f = window.fetch;
  window.fetch = function (i, init) {
    if (typeof i === "string") i = pfx(i);
    else if (i && i.url) { var u = pfx(i.url); if (u !== i.url) i = new Request(u, i); }
    return f.call(this, i, init);
  };

  var XO = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u) {
    return XO.apply(this, [m, pfx(u)].concat([].slice.call(arguments, 2)));
  };

  var HP = history.pushState, HR = history.replaceState;
  // NOTE: our step-1 replaceState above already ran with the ORIGINAL
  // replaceState. Subsequent pushState/replaceState from the SPA use
  // stripped paths (e.g. router.push("/settings")) — leave them alone,
  // do NOT re-prefix. The URL bar stays "clean" inside the iframe.

  var W = window.WebSocket;
  window.WebSocket = function (u, pr) {
    if (typeof u === "string") {
      var m = u.match(/^(wss?:\/\/[^\/]+)(\/.+)/);
      if (m && m[2].indexOf(p) !== 0) u = m[1] + p + m[2];
    }
    return pr ? new W(u, pr) : new W(u);
  };

  // window.location.assign / replace — patch to strip-then-re-navigate
  // (they'd otherwise resolve against origin without our prefix).
  var LA = Location.prototype.assign;
  Location.prototype.assign = function (u) { return LA.call(this, pfx(u)); };
  var LR = Location.prototype.replace;
  Location.prototype.replace = function (u) { return LR.call(this, pfx(u)); };
  // location.href = "/foo" — Chrome forbids overriding the built-in setter
  // (configurable: false on the instance), so this remains best-effort. The
  // sed patches in Dockerfile catch the common cases in omnigent's bundle.
  try {
    var d = Object.getOwnPropertyDescriptor(Location.prototype, "href");
    if (d && d.set) {
      Object.defineProperty(Location.prototype, "href", {
        configurable: true,
        enumerable: true,
        get: d.get,
        set: function (u) { return d.set.call(this, pfx(u)); }
      });
    }
  } catch (e) { /* Chrome guards Location.prototype.href — expected */ }
})();
