// Regression test for the HA Ingress URL shim in rootfs/etc/nginx/nginx.conf.
//
// WHY THIS EXISTS
//
// Under HA Ingress the app is served at /api/hassio_ingress/<token>/, but
// pi-web emits absolute paths (/api/..., /_next/..., /favicon...). The shim
// monkey-patches fetch / EventSource / XMLHttpRequest so those paths get the
// ingress prefix prepended before they leave the browser. A route the shim
// fails to match does not error — it escapes the iframe and lands on HA Core,
// which answers with its own 404 or login page. The symptom is "one panel in
// the UI is permanently broken", which is expensive to trace back to here.
//
// pi-web is pinned in the Dockerfile precisely because upstream can add routes
// without warning. When bumping PI_WEB_VERSION, add that release's new routes
// to ROUTES below and run:
//
//     node tests/shim-routes.mjs
//
// The shim source is not duplicated here — it is extracted from nginx.conf at
// run time, so this test cannot drift from what is actually served.
//
// Verified against pi-web 0.9.0: 19/19.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const NGINX_CONF = join(HERE, "..", "rootfs", "etc", "nginx", "nginx.conf");
const PREFIX = "/api/hassio_ingress/abcdefghijklmnop1234";

function extractShim() {
  const conf = readFileSync(NGINX_CONF, "utf8");
  const m = conf.match(/sub_filter '<\/head>' '(<script>[\s\S]*?<\/script>)<\/head>';/);
  if (!m) throw new Error(`could not find the </head> shim in ${NGINX_CONF}`);
  return m[1].replace(/^<script>/, "").replace(/<\/script>$/, "");
}

const calls = { fetch: [], eventsource: [], xhr: [] };
const g = globalThis;
g.location = { origin: "http://homeassistant.local:8123" };
g.window = g;
g.fetch = (u) => { calls.fetch.push(String(u)); return Promise.resolve(); };
function ES(u){ calls.eventsource.push(String(u)); }
g.EventSource = ES;
g.XMLHttpRequest = function(){}; 
g.XMLHttpRequest.prototype.open = function(m,u){ calls.xhr.push(String(u)); };
g.Request = class {
  constructor(u, init) {
    if (init && typeof init === "object") { const { url, ...rest } = init; Object.assign(this, rest); }
    this.url = String(u && u.url !== undefined ? u.url : u);
  }
  toString() { return this.url; }
};
g.URL = URL;
g.history = { pushState(){}, replaceState(){} };
g.Element = { prototype: { setAttribute(){} } };
g.HTMLLinkElement = undefined; g.HTMLScriptElement = undefined; g.HTMLImageElement = undefined;
// A serviceWorker container that mimics Home Assistant's: HA registers its own
// worker at scope "/" on the SAME origin the ingress iframe lives on, so every
// one of these accessors would otherwise hand pi-web *HA's* worker.
const haWorker = { scope: "/", pushManager: { subscribe: async () => ({ endpoint: "ha" }) } };
const swContainer = {
  register: async () => haWorker,
  getRegistration: async () => haWorker,
  getRegistrations: async () => [haWorker],
  ready: Promise.resolve(haWorker),
  controller: haWorker,
};
Object.defineProperty(g, "navigator", { value: { serviceWorker: swContainer }, configurable: true, writable: true });

// nginx substitutes $safe_ingress_path at serve time; do the same here.
const js = extractShim().replace(
  'window.__INGRESS_PATH__="$safe_ingress_path"',
  `window.__INGRESS_PATH__=${JSON.stringify(PREFIX)}`,
);
new Function(js)();

// Routes pi-web 0.9.0 actually calls from the browser, incl. everything new.
const ROUTES = [
  ["/api/home",                          true,  "0.8.4 baseline"],
  ["/api/sessions",                      true,  "0.8.4 baseline"],
  ["/api/models-config",                 true,  "0.8.4 baseline"],
  ["/api/terminal",                      true,  "0.9.0 NEW — terminal create"],
  ["/api/terminal/abc123/events",        true,  "0.9.0 NEW — terminal SSE"],
  ["/api/subagents/profiles",            true,  "0.9.0 NEW"],
  ["/api/sessions/search",               true,  "0.9.0 NEW"],
  ["/api/tools/settings",                true,  "0.9.0 NEW"],
  ["/api/push/subscribe",                true,  "0.9.0 NEW — web-push"],
  ["/api/app-update",                    true,  "0.9.0 NEW"],
  ["/_next/static/chunks/main.js",       true,  "asset"],
  ["/favicon.ico",                       true,  "asset"],
  ["/manifest.webmanifest",              true,  "asset"],
  ["/icons/icon-192.png",                true,  "asset"],
  ["/?_rsc=1a2b3",                       true,  "RSC prefetch"],
  [`${PREFIX}/api/home`,                 false, "already prefixed — must NOT double-prefix"],
  ["https://api.openai.com/v1/models",   false, "absolute external — must not touch"],
];

let pass = 0, fail = 0;
console.log("=== fetch() ===");
for (const [url, shouldPrefix, note] of ROUTES) {
  calls.fetch.length = 0;
  g.fetch(url);
  const got = calls.fetch[0];
  const expected = shouldPrefix ? PREFIX + url : url;
  const ok = got === expected;
  ok ? pass++ : fail++;
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${url}`);
  if (!ok) console.log(`        expected ${expected}\n        got      ${got}   (${note})`);
}

console.log("\n=== EventSource() — this is how 0.9.0 streams terminal output ===");
for (const url of ["/api/terminal/abc123/events", "/api/sessions/x/events"]) {
  calls.eventsource.length = 0;
  new g.EventSource(url);
  const got = calls.eventsource[0];
  const ok = got === PREFIX + url;
  ok ? pass++ : fail++;
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${url} -> ${got}`);
}

console.log("\n=== XMLHttpRequest ===");
calls.xhr.length = 0;
const x = new g.XMLHttpRequest(); g.XMLHttpRequest.prototype.open.call(x, "POST", "/api/terminal");
console.log(`  (open called with) ${calls.xhr[0] ?? "<none>"}`);

console.log("\n=== trailing slash on the ingress prefix (the v0.14.1 404) ===");
// Next.js App Router builds its RSC prefetch URL from the canonical pathname with
// the trailing slash normalised OFF, producing "<prefix>?_rsc=...". HA Core routes
// /api/hassio_ingress/{token}/{path} and does not match without that slash, so Core
// 404s the prefetch; Next then hard-navigates to the same slash-less URL and the
// whole page becomes "404: Not Found" about a second after it rendered correctly.
// The shim used to pass these through untouched because of its "already prefixed,
// leave alone" early-out. Reproduced live against the box, then fixed here.
const slashCases = [
  [PREFIX,                       PREFIX + "/",                  "bare prefix, no slash"],
  [PREFIX + "?_rsc=QLBdCDjfp",   PREFIX + "/?_rsc=QLBdCDjfp",   "RSC prefetch (the actual failing request)"],
  [PREFIX + "#frag",             PREFIX + "/#frag",             "prefix + fragment"],
  [PREFIX + "/",                 PREFIX + "/",                  "already correct, must not double"],
  [PREFIX + "/api/home",         PREFIX + "/api/home",          "normal prefixed path untouched"],
];
for (const [input, expected, note] of slashCases) {
  calls.fetch.length = 0;
  g.fetch(input);
  const got = calls.fetch[0];
  const ok = got === expected;
  ok ? pass++ : fail++;
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${note}`);
  if (!ok) console.log(`        in  ${input}\n        exp ${expected}\n        got ${got}`);
}

console.log("\n=== fetch argument shapes (the v0.14.2 miss) ===");
// v0.14.2 applied FS() only when fetch was called with a STRING. Next.js's RSC
// fetch builds `new URL(href, location.origin)` and hands fetch a URL OBJECT,
// so the one request that actually breaks the page went unrepaired and the
// deployed fix changed nothing. Every argument shape must be covered.
const shapeCases = [
  ["string", () => PREFIX + "?_rsc=QLBdCDjfp"],
  ["URL object", () => new URL(location.origin + PREFIX + "?_rsc=QLBdCDjfp")],
  ["Request object", () => new g.Request(PREFIX + "?_rsc=QLBdCDjfp")],
];
for (const [name, make] of shapeCases) {
  calls.fetch.length = 0;
  g.fetch(make());
  const got = String(calls.fetch[0] ?? "");
  // Accept either the absolute or the origin-relative form; what matters is
  // that the slash after the ingress token is present.
  const ok = got.includes(PREFIX + "/?_rsc=");
  ok ? pass++ : fail++;
  console.log(`  ${ok ? "PASS" : "FAIL"}  fetch(${name}) keeps the slash`);
  if (!ok) console.log(`        got ${got}`);
}

console.log("\n=== service worker neutralisation ===");
// Regression guard for the v0.14.1 fix. pi-web 0.9.0 added push code that calls
// navigator.serviceWorker.getRegistration(); the v0.14.0 shim only replaced
// register(), so that call returned Home Assistant's own service worker and
// pi-web subscribed its VAPID key to it. Every accessor that can hand out a
// real registration must be neutralised, not just register().
const swChecks = [
  ["register() resolves a stub, not HA's worker", async () => {
    const r = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    return !!r && r !== haWorker && !r.pushManager;
  }],
  ["getRegistration() resolves undefined", async () => {
    return (await navigator.serviceWorker.getRegistration()) === undefined;
  }],
  ["getRegistrations() resolves empty", async () => {
    const r = await navigator.serviceWorker.getRegistrations();
    return Array.isArray(r) && r.length === 0;
  }],
  ["controller is null", async () => navigator.serviceWorker.controller === null],
  ["ready does not resolve to HA's worker", async () => {
    const raced = await Promise.race([
      navigator.serviceWorker.ready.then(() => "resolved"),
      new Promise((res) => setTimeout(() => res("pending"), 50)),
    ]);
    return raced === "pending";
  }],
];
for (const [name, fn] of swChecks) {
  const ok = await fn();
  ok ? pass++ : fail++;
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}`);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
