import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const prefix = '/api/hassio_ingress/abcdefghijklmnop';
const nginx = await readFile(new URL('../rootfs/etc/nginx/nginx.conf', import.meta.url), 'utf8');
const shim = await readFile(new URL('../rootfs/opt/ha-opendesign/ha-ingress.js', import.meta.url), 'utf8');

function applyDocumentRewrites(html) {
  return html
    .replaceAll('href="/', `href="${prefix}/`)
    .replaceAll('src="/', `src="${prefix}/`)
    .replaceAll('action="/', `action="${prefix}/`)
    .replaceAll('\\"/_next/', `\\"${prefix}/_next/`)
    .replace('<head>', `<head><script>window.__OD_INGRESS_PATH__="${prefix}";</script><script src="${prefix}/ha-ingress.js"></script><script src="${prefix}/ha-export-bridge.js"></script>`);
}

test('representative initial HTML rewrite matches the fixture', async () => {
  const upstream = await readFile(new URL('./fixtures/upstream-response.html', import.meta.url), 'utf8');
  const expected = await readFile(new URL('./fixtures/ingress-response.html', import.meta.url), 'utf8');
  assert.equal(applyDocumentRewrites(upstream), expected);
});

test('nginx validates the ingress prefix and preserves streaming upgrades', () => {
  assert.match(nginx, /map \$http_x_ingress_path \$safe_ingress_path/);
  assert.match(nginx, /\^\/api\/hassio_ingress\/\[A-Za-z0-9_-\]\{16,128\}\$/);
  assert.match(nginx, /proxy_pass http:\/\/127\.0\.0\.1:7456/);
  assert.match(nginx, /proxy_buffering off/);
  assert.match(nginx, /proxy_request_buffering off/);
  assert.match(nginx, /proxy_set_header Upgrade \$http_upgrade/);
  assert.match(nginx, /proxy_set_header Connection \$connection_upgrade/);
  assert.match(nginx, /proxy_set_header Accept-Encoding ""/);
  assert.match(nginx, /client_max_body_size 256M/);
  assert.match(nginx, /sub_filter_types[^;]*text\/javascript/, 'Turbopack chunks are served as text/javascript and must be rewritten');
  assert.ok(nginx.includes("sub_filter '\\\"/_next/' '\\\"$safe_ingress_path/_next/'"), 'RSC chunk references must use the ingress prefix');
  assert.ok(nginx.includes("sub_filter '\"/_next/' '\"$safe_ingress_path/_next/'"), 'Turbopack runtime asset base must use the ingress prefix');
  assert.match(nginx, /location ~ \^\/api\/projects\/\[\^\/\]\+\/export/);
  assert.match(nginx, /location = \/ha-export-bridge\.js/);
  assert.match(nginx, /ha-ingress\.js.*ha-export-bridge\.js/);
  assert.ok(nginx.indexOf("sub_filter '<head>'") > nginx.indexOf("location /"));
  assert.ok(nginx.indexOf('location ~ ^/api/projects/') < nginx.indexOf('location / {'), 'download bypass must precede the filtered shell location');
});

test('early shim covers root-relative streaming, navigation, and dynamic URLs', () => {
  for (const token of [
    'window.fetch',
    'XMLHttpRequest.prototype.open',
    'window.EventSource',
    'window.WebSocket',
    "wrapHistory('pushState')",
    "wrapHistory('replaceState')",
    'Element.prototype.setAttribute',
    'HTMLIFrameElement',
    'MutationObserver',
    "wrapWorker('Worker')",
  ]) assert.ok(shim.includes(token), `missing shim behavior: ${token}`);
  assert.ok(shim.includes("startsWith('/api/hassio_ingress/')"), 'must prevent ingress double-prefixing');
  assert.ok(shim.includes('new Request(new URL(next, input.url).href, input)'), 'Request rewriting must use an absolute replacement URL');
  assert.match(shim, /url\.protocol !== 'http:' && url\.protocol !== 'https:'/,
    'blob/data/about URLs used by browser downloads must not be ingress-rewritten');
  assert.ok(shim.includes('Service workers are disabled'), 'must not register a root-scoped service worker on HA');
});
