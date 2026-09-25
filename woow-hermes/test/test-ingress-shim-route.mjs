// Reloading the Home Assistant page recreates the panel's iframe at the
// ingress root, while a reload on the LAN port stays on the current page. The
// shim remembers the last page per tab and puts it back before the app starts.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const P = "/api/hassio_ingress/abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
const origin = "https://ha.example.com";
const shim = readFileSync(new URL("../rootfs/etc/nginx/woow/ingress-shim.js", import.meta.url), "utf8");

// sessionStorage survives a reload of the same tab.
function tab() {
  const store = new Map();
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
}

function load(storage, path) {
  const replaced = [];
  const listeners = {};
  const location = { href: origin + path, origin, host: "ha.example.com" };
  Object.defineProperty(location, "pathname", { get: () => new URL(location.href).pathname });
  Object.defineProperty(location, "search", { get: () => new URL(location.href).search });
  Object.defineProperty(location, "hash", { get: () => new URL(location.href).hash });
  const history = {
    pushState(s, t, u) { location.href = new URL(u, location.href).href; },
    replaceState(s, t, u) { replaced.push(u); location.href = new URL(u, location.href).href; },
  };
  const window = {
    fetch: () => Promise.resolve({ ok: true }),
    sessionStorage: storage,
    addEventListener: (type, fn) => { listeners[type] = fn; },
  };
  const sandbox = {
    window, URL, console, location, history, sessionStorage: storage,
    Request: class { constructor(u) { this.url = u; } },
    XMLHttpRequest: class { open() {} },
    PerformanceObserver: class { observe() {} },
    document: { currentScript: { src: `${origin}${P}/__woow/ingress-shim.js` } },
  };
  vm.createContext(sandbox);
  vm.runInContext(shim, sandbox);
  return { history: sandbox.history, location, replaced, listeners };
}

const t = tab();

// First visit at the root: nothing to restore.
let page = load(t, `${P}/`);
assert.deepEqual(page.replaced, []);

// The user moves around in the app; the last page is remembered.
page.history.pushState({}, "", `${P}/sessions`);
page.history.pushState({}, "", `${P}/skills?tab=installed#top`);

// F5 on the HA page: the iframe starts again at the ingress root, and the
// shim goes back to the last page before the app reads the URL.
page = load(t, `${P}/`);
assert.deepEqual(page.replaced, [`${P}/skills?tab=installed#top`]);
assert.equal(page.location.pathname, `${P}/skills`);

// Only the ingress root is the panel's start page. A full load of any other
// page, Sessions included (a bookmark, a typed URL), is left alone.
page.history.pushState({}, "", `${P}/cron`);
page = load(t, `${P}/sessions`);
assert.deepEqual(page.replaced, []);
page = load(t, `${P}/`);
assert.deepEqual(page.replaced, [`${P}/sessions`]);
page.history.pushState({}, "", `${P}/cron`);

// Back and forward are remembered as well.
page.location.href = `${origin}${P}/models`;
page.listeners.popstate();
page = load(t, `${P}/`);
assert.deepEqual(page.replaced, [`${P}/models`]);

// A reload that is already on a real page stays there, and becomes the last page.
page = load(t, `${P}/files`);
assert.deepEqual(page.replaced, []);
page = load(t, `${P}/`);
assert.deepEqual(page.replaced, [`${P}/files`]);

// Sign-in pages are never remembered or restored over.
page.history.pushState({}, "", `${P}/login?next=%2F`);
page = load(t, `${P}/`);
assert.deepEqual(page.replaced, [`${P}/files`]);
page = load(t, `${P}/login`);
assert.deepEqual(page.replaced, [], "the login page is left alone");

// A new tab starts at the start page, as on the LAN port.
page = load(tab(), `${P}/`);
assert.deepEqual(page.replaced, []);

console.log("ingress shim route: ok");
