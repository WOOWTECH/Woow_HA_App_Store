// HA ingress delivers every WebSocket close to the browser as a clean 1000.
// The shim tags each ingress WebSocket, and on an unexplained 1000 asks the
// add-on's relay (/__woow/wsclose) how Hermes really closed it.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const P = "/api/hassio_ingress/abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
const origin = "https://ha.example.com";

class FakeCloseEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.code = init.code ?? 0;
    this.reason = init.reason ?? "";
    this.wasClean = init.wasClean ?? false;
  }
}

// Minimal stand-in for the browser WebSocket: onclose lives on the prototype,
// and the native dispatch calls it plus every close listener.
const sockets = [];
class FakeWebSocket {
  constructor(url, protocols) {
    this.url = url;
    this.protocols = protocols;
    this._listeners = [];
    this._h = null;
    this.closedByPage = false;
    sockets.push(this);
  }
  get onclose() { return this._h; }
  set onclose(h) { this._h = h; }
  addEventListener(type, fn) { if (type === "close") this._listeners.push(fn); }
  removeEventListener(type, fn) { this._listeners = this._listeners.filter((f) => f !== fn); }
  close() { this.closedByPage = true; }
  // What the network does: fire a close event.
  _serverClose(code, reason = "", wasClean = true) {
    const ev = new FakeCloseEvent("close", { code, reason, wasClean });
    if (typeof this._h === "function") this._h.call(this, ev);
    this._listeners.slice().forEach((fn) => fn.call(this, ev));
  }
}
FakeWebSocket.OPEN = 1;

const records = new Map();
const lookups = [];
let fetchMode = "ok";
const fakeFetch = (input) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.includes("/__woow/wsclose")) {
    lookups.push(url);
    if (fetchMode === "down") return Promise.reject(new TypeError("network"));
    const id = new URL(url, origin).searchParams.get("id");
    const rec = records.get(id);
    return Promise.resolve(rec
      ? { ok: true, status: 200, json: () => Promise.resolve(rec) }
      : { ok: false, status: 404, json: () => Promise.reject(new Error("404")) });
  }
  return Promise.resolve({ ok: true, status: 200 });
};

const window = { fetch: fakeFetch, WebSocket: FakeWebSocket };
const sandbox = {
  window, URL, console, setTimeout, clearTimeout,
  WebSocket: FakeWebSocket, CloseEvent: FakeCloseEvent,
  Request: class { constructor(u) { this.url = u; } },
  XMLHttpRequest: class { open() {} },
  PerformanceObserver: class { observe() {} },
  location: { href: `${origin}${P}/chat`, origin, host: "ha.example.com", pathname: `${P}/chat`, search: "", hash: "" },
  history: { pushState() {}, replaceState() {} },
  document: { currentScript: { src: `${origin}${P}/__woow/ingress-shim.js` } },
};
vm.createContext(sandbox);
vm.runInContext(readFileSync(new URL("../rootfs/etc/nginx/woow/ingress-shim.js", import.meta.url), "utf8"), sandbox);
const WS = sandbox.window.WebSocket;
const tick = () => new Promise((r) => setTimeout(r, 20));

function cidOf(ws) {
  return new URL(ws.url).searchParams.get("__wcid");
}

// 1. Ingress sockets are tagged; foreign ones are left alone.
const pty = new WS(`wss://ha.example.com${P}/api/pty?ticket=t&attach=k`);
assert.ok(cidOf(pty), "ingress socket gets a __wcid");
assert.equal(new URL(pty.url).searchParams.get("ticket"), "t", "existing query kept");
const foreign = new WS("wss://other.example.org/socket");
assert.equal(foreign.url, "wss://other.example.org/socket");

// 2. Hermes closed with 4409, HA delivered 1000: the page sees 4409, through
//    both onclose and addEventListener.
records.set(cidOf(pty), { code: 4409, reason: "superseded", wasClean: true });
const seen = [];
pty.onclose = (ev) => seen.push(["onclose", ev.code, ev.reason, ev.wasClean]);
pty.addEventListener("close", (ev) => seen.push(["listener", ev.code]));
pty._serverClose(1000);
await tick();
assert.deepEqual(seen, [["onclose", 4409, "superseded", true], ["listener", 4409]]);

// 3. No record (HA or the network ended it, not Hermes): an abnormal close, so
//    the page reconnects as it does after a network drop on the LAN port.
const events = new WS(`wss://ha.example.com${P}/api/events?ticket=u`);
let got;
events.onclose = (ev) => { got = [ev.code, ev.wasClean]; };
events._serverClose(1000);
await tick();
assert.deepEqual(got, [1006, false]);

// 4. The add-on is down (lookup fails): also an abnormal close.
fetchMode = "down";
const ws4 = new WS(`wss://ha.example.com${P}/api/ws`);
ws4.onclose = (ev) => { got = [ev.code, ev.wasClean]; };
ws4._serverClose(1000);
await tick();
assert.deepEqual(got, [1006, false]);
fetchMode = "ok";

// 5. The page closed it itself, or the code already survived: delivered as is,
//    without a lookup.
const before = lookups.length;
const ws5 = new WS(`wss://ha.example.com${P}/api/pty?attach=z`);
ws5.onclose = (ev) => { got = [ev.code]; };
ws5.close();
ws5._serverClose(1000);
await tick();
assert.deepEqual(got, [1000]);
const ws6 = new WS(`wss://ha.example.com${P}/api/pty?attach=y`);
ws6.onclose = (ev) => { got = [ev.code]; };
ws6._serverClose(4401, "auth");
await tick();
assert.deepEqual(got, [4401]);
assert.equal(lookups.length, before, "no lookup for page-initiated or explicit codes");

// 6. A removed listener is not called.
const ws7 = new WS(`wss://ha.example.com${P}/api/pty?attach=x`);
records.set(cidOf(ws7), { code: 4410, reason: "", wasClean: true });
let calls = 0;
const fn = () => { calls++; };
ws7.addEventListener("close", fn);
ws7.removeEventListener("close", fn);
ws7._serverClose(1000);
await tick();
assert.equal(calls, 0);

assert.equal(WS.OPEN, 1, "constants kept");
console.log("ingress shim websockets: ok");
