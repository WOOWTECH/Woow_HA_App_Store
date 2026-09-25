// Unit test for rootfs/etc/nginx/woow/cookies.js (njs) under node.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync(new URL("../rootfs/etc/nginx/woow/cookies.js", import.meta.url), "utf8")
  .replace(/^export default .*$/m, "this.m = { request_cookie, rename_set_cookie };");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src, ctx);
const { request_cookie, rename_set_cookie } = ctx.m;

// Both entrances logged in on the same host: the browser sends the sidebar's
// (longer path) cookies first and the LAN port's bare ones after them.
const both = "woowing_hermes_session_at=SIDEBAR; ingress_session=HA; hermes_session_at=LAN; hermes_session_rt=LAN_RT";
assert.equal(request_cookie({ headersIn: { Cookie: both } }), "hermes_session_at=SIDEBAR; ingress_session=HA");

// Only the LAN port is logged in: nothing Hermes-related reaches the sidebar.
assert.equal(request_cookie({ headersIn: { Cookie: "hermes_session_at=LAN; ingress_session=HA" } }), "ingress_session=HA");

// HTTPS ingress keeps the __Secure- prefix in front.
assert.equal(
  request_cookie({ headersIn: { Cookie: "__Secure-woowing_hermes_session_rt=X; __Secure-hermes_session_rt=Y" } }),
  "__Secure-hermes_session_rt=X",
);
assert.equal(request_cookie({ headersIn: {} }), "");

const r = { headersOut: { "Set-Cookie": [
  "hermes_session_at=A; HttpOnly; Path=/api/hassio_ingress/t",
  "__Secure-hermes_session_rt=B; Secure; Path=/api/hassio_ingress/t",
  'hermes_session_provider=""; Max-Age=0; Path=/api/hassio_ingress/t',
  "other=1; Path=/",
] } };
rename_set_cookie(r);
assert.deepEqual(r.headersOut["Set-Cookie"], [
  "woowing_hermes_session_at=A; HttpOnly; Path=/api/hassio_ingress/t",
  "__Secure-woowing_hermes_session_rt=B; Secure; Path=/api/hassio_ingress/t",
  'woowing_hermes_session_provider=""; Max-Age=0; Path=/api/hassio_ingress/t',
  "other=1; Path=/",
]);
const none = { headersOut: {} };
rename_set_cookie(none);
assert.equal(none.headersOut["Set-Cookie"], undefined);
console.log("ingress cookies: ok");
