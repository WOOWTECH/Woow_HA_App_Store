// Loaded by the ingress adapter only. HA Core routes ingress as
// /api/hassio_ingress/<token>/<path>: a URL that is exactly the prefix, without
// the trailing slash, is a 404 from HA before it reaches the add-on. Keep the
// slash on history updates so a reload of the panel still lands.
(function () {
  var script = document.currentScript;
  if (!script) return;
  var P = new URL(script.src).pathname.replace(/\/__woow\/ingress-shim\.js$/, "");
  if (!/^\/api\/hassio_ingress\/[A-Za-z0-9_-]{16,128}$/.test(P)) return;
  var withSlash = function (u) {
    if (u == null) return u;
    try {
      var x = new URL(u instanceof URL ? u.href : String(u), location.href);
      if (x.origin === location.origin && x.pathname === P) {
        return P + "/" + x.search + x.hash;
      }
    } catch (e) {}
    return u;
  };
  // Reloading the Home Assistant page recreates the panel's iframe at the
  // ingress root, where the app starts on Sessions, while a reload on the LAN
  // port stays on the current page. Remember the last page for this tab and go
  // back to it before the app reads the URL. A new tab starts fresh, as on the
  // LAN port; sign-in pages are never remembered.
  var routeKey = "woow-ingress-route:" + P;
  var storage = null;
  try {
    storage = window.sessionStorage;
  } catch (e) {}
  var currentRoute = function () {
    return (location.pathname.slice(P.length) || "/") + location.search + location.hash;
  };
  var pathOf = function (route) {
    return route.split(/[?#]/)[0];
  };
  var skipped = function (route) {
    return pathOf(route) === "/" || /^\/(login|auth)(\/|$)/.test(pathOf(route));
  };
  var remember = function () {
    if (!storage || location.pathname.indexOf(P + "/") !== 0) return;
    var route = currentRoute();
    if (skipped(route)) return;
    try {
      storage.setItem(routeKey, route);
    } catch (e) {}
  };
  var nativeReplaceState = history.replaceState;
  ["pushState", "replaceState"].forEach(function (name) {
    var original = history[name];
    history[name] = function (state, title, url) {
      if (arguments.length > 2) arguments[2] = withSlash(url);
      var result = original.apply(this, arguments);
      remember();
      return result;
    };
  });
  if (window.addEventListener) window.addEventListener("popstate", remember);
  var saved = null;
  try {
    saved = storage && storage.getItem(routeKey);
  } catch (e) {}
  // Only the ingress root, where HA opens the panel; the app itself sends the
  // root on to Sessions after this runs. Any other page was asked for.
  if (saved && !skipped(saved) && pathOf(currentRoute()) === "/") {
    nativeReplaceState.call(history, history.state, "", P + saved);
  } else {
    remember();
  }
  // A few upstream call sites fetch root-absolute URLs without the base path
  // (session export, Swagger "Try it out"). Keep same-origin requests inside the
  // ingress prefix; URLs already under it are left alone.
  var inPrefix = function (u) {
    try {
      var x = new URL(u, location.href);
      if (x.origin !== location.origin) return u;
      if (x.pathname === P || x.pathname.indexOf(P + "/") === 0) return u;
      if (x.pathname.charAt(0) !== "/") return u;
      return P + x.pathname + x.search + x.hash;
    } catch (e) {
      return u;
    }
  };
  var nativeFetch = window.fetch;
  window.fetch = function (input, init) {
    if (typeof input === "string") {
      input = inPrefix(input);
    } else if (input instanceof URL) {
      input = inPrefix(input.href);
    } else if (input && typeof input.url === "string") {
      var fixed = inPrefix(input.url);
      if (fixed !== input.url) input = new Request(fixed, input);
    }
    return nativeFetch.call(this, input, init);
  };
  var nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    if (typeof url === "string" || url instanceof URL) arguments[1] = inPrefix(String(url));
    return nativeOpen.apply(this, arguments);
  };
  // HA ingress forwards WebSocket messages but not the close frame: whatever
  // code Hermes closes with (4409 another tab took the chat over, 4410 the
  // agent exited, ...), the browser gets a clean 1000, which the chat reads as
  // "session ended". The add-on's relay records the real close under the
  // __wcid tag added here; on a 1000 the page did not ask for, look it up and
  // deliver that instead. No record means Hermes did not close it (HA or the
  // network did) and a failed lookup means the add-on is down: both are the
  // abnormal close the LAN port would see, so the page reconnects.
  var NativeWebSocket = window.WebSocket;
  var tag = function () {
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
  };
  var recordedClose = function (cid) {
    return nativeFetch.call(window, P + "/__woow/wsclose?id=" + encodeURIComponent(cid), {
      cache: "no-store",
      credentials: "same-origin",
    }).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (rec) {
      return rec || { code: 1006, reason: "", wasClean: false };
    }, function () {
      return { code: 1006, reason: "", wasClean: false };
    });
  };
  var IngressWebSocket = function (url, protocols) {
    var x = null;
    try {
      x = new URL(url instanceof URL ? url.href : String(url), location.href);
    } catch (e) {}
    if (!x || x.host !== location.host || x.pathname.indexOf(P + "/") !== 0) {
      return protocols === undefined ? new NativeWebSocket(url) : new NativeWebSocket(url, protocols);
    }
    var cid = tag();
    x.searchParams.set("__wcid", cid);
    var ws = protocols === undefined ? new NativeWebSocket(x.href) : new NativeWebSocket(x.href, protocols);
    var nativeAdd = ws.addEventListener;
    var nativeRemove = ws.removeEventListener;
    var nativeClose = ws.close;
    var closedByPage = false;
    var onclose = null;
    var listeners = [];
    ws.close = function () {
      closedByPage = true;
      return nativeClose.apply(ws, arguments);
    };
    Object.defineProperty(ws, "onclose", {
      configurable: true,
      get: function () { return onclose; },
      set: function (h) { onclose = h; },
    });
    ws.addEventListener = function (type, fn) {
      if (type !== "close") return nativeAdd.apply(ws, arguments);
      if (fn && listeners.indexOf(fn) < 0) listeners.push(fn);
    };
    ws.removeEventListener = function (type, fn) {
      if (type !== "close") return nativeRemove.apply(ws, arguments);
      var i = listeners.indexOf(fn);
      if (i >= 0) listeners.splice(i, 1);
    };
    var deliver = function (ev) {
      if (typeof onclose === "function") onclose.call(ws, ev);
      listeners.slice().forEach(function (fn) {
        if (typeof fn === "function") fn.call(ws, ev);
        else if (fn && typeof fn.handleEvent === "function") fn.handleEvent(ev);
      });
    };
    nativeAdd.call(ws, "close", function (ev) {
      if (ev.code !== 1000 || closedByPage) return deliver(ev);
      recordedClose(cid).then(function (rec) {
        deliver(new CloseEvent("close", { code: rec.code, reason: rec.reason || "", wasClean: !!rec.wasClean }));
      });
    });
    return ws;
  };
  if (NativeWebSocket) {
    IngressWebSocket.prototype = NativeWebSocket.prototype;
    ["CONNECTING", "OPEN", "CLOSING", "CLOSED"].forEach(function (k) {
      IngressWebSocket[k] = NativeWebSocket[k];
    });
    window.WebSocket = IngressWebSocket;
  }
  // Diagnostic only: report any request that escapes the ingress prefix.
  try {
    new PerformanceObserver(function (list) {
      list.getEntries().forEach(function (entry) {
        var u = new URL(entry.name);
        if (u.origin === location.origin && u.pathname.indexOf(P + "/") !== 0) {
          console.warn("[woow-ingress] escaped", u.pathname);
        }
      });
    }).observe({ type: "resource", buffered: true });
  } catch (e) {}
})();
