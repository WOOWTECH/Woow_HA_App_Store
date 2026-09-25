// Runs ingress-shim.js against a minimal browser stand-in and checks which URLs
// it keeps inside the ingress prefix.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const P = "/api/hassio_ingress/abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
const origin = "https://ha.example.com";
const fetched = [];
const opened = [];
const pushed = [];

class FakeXHR { open(method, url) { opened.push(url); } }
class FakeRequest { constructor(url, init) { this.url = url; this.init = init; } }

const window = {
  fetch: (input) => { fetched.push(typeof input === "string" ? input : input.url); return Promise.resolve(); },
};
const sandbox = {
  window, URL, Request: FakeRequest, XMLHttpRequest: FakeXHR, console,
  PerformanceObserver: class { observe() {} },
  location: { href: `${origin}${P}/sessions`, origin, pathname: `${P}/sessions`, search: "", hash: "" },
  history: { pushState: (s, t, u) => pushed.push(u), replaceState: () => {} },
  document: { currentScript: { src: `${origin}${P}/__woow/ingress-shim.js` } },
};
sandbox.window.XMLHttpRequest = FakeXHR;
vm.createContext(sandbox);
vm.runInContext(readFileSync(new URL("../rootfs/etc/nginx/woow/ingress-shim.js", import.meta.url), "utf8"), sandbox);
const f = sandbox.window.fetch;

f("/api/sessions/abc/export?profile=default");
f(`${P}/api/status`);
f(new URL(`${origin}/openapi.json`));
f(new FakeRequest(`${origin}/api/files`));
f("https://example.org/x");
f("relative/path");
new FakeXHR().open("GET", "/api/files");
sandbox.history.pushState({}, "", P);

assert.deepEqual(fetched, [
  `${P}/api/sessions/abc/export?profile=default`,
  `${P}/api/status`,
  `${P}/openapi.json`,
  `${P}/api/files`,
  "https://example.org/x",
  "relative/path",
]);
assert.deepEqual(opened, [`${P}/api/files`]);
assert.deepEqual(pushed, [`${P}/`]);
console.log("ingress shim: ok");
