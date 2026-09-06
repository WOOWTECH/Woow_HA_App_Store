import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

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

function runIngressShim(initialPath) {
  const location = {
    pathname: initialPath,
    search: '',
    hash: '',
    href: `http://localhost${initialPath}`,
    host: 'localhost',
    origin: 'http://localhost',
  };
  const replaceCalls = [];
  const historyCalls = [];
  const updateLocation = (url) => {
    if (typeof url !== 'string') return;
    const next = new URL(url, 'http://localhost');
    location.pathname = next.pathname;
    location.search = next.search;
    location.hash = next.hash;
    location.href = next.href;
  };
  const history = {
    state: null,
    pushState(state, _title, url) {
      historyCalls.push({ method: 'pushState', url });
      this.state = state;
      updateLocation(url);
    },
    replaceState(state, _title, url) {
      replaceCalls.push(url);
      historyCalls.push({ method: 'replaceState', url });
      this.state = state;
      updateLocation(url);
    },
  };
  const originalSetAttributeCalls = [];
  class Element {
    constructor() { this._attrs = new Map(); }
    setAttribute(name, value) {
      originalSetAttributeCalls.push({ target: this, name, value });
      this._attrs.set(String(name).toLowerCase(), String(value));
    }
    getAttribute(name) {
      const key = String(name).toLowerCase();
      return this._attrs.has(key) ? this._attrs.get(key) : null;
    }
    hasAttribute(name) { return this._attrs.has(String(name).toLowerCase()); }
  }
  class XMLHttpRequest { open() {} }
  class CSSStyleDeclaration { setProperty() {} }
  class CSSStyleSheet { insertRule() {} }
  class MutationObserver {
    constructor() {}
    observe() {}
  }
  const iframeSetterCalls = [];
  class HTMLIFrameElement extends Element {}
  Object.defineProperty(HTMLIFrameElement.prototype, 'src', {
    configurable: true,
    enumerable: true,
    get() {
      const raw = this._attrs.get('src');
      if (raw === undefined) return '';
      // Simulate browser canonical URL resolution against page location.
      try { return new URL(raw, location.href).href; } catch { return raw; }
    },
    set(value) {
      iframeSetterCalls.push(String(value));
      this._attrs.set('src', String(value));
    },
  });
  const window = {
    __OD_INGRESS_PATH__: prefix,
    location,
    fetch() {},
    addEventListener() {},
    HTMLIFrameElement,
  };
  vm.runInNewContext(shim, {
    window,
    location,
    history,
    XMLHttpRequest,
    Element,
    CSSStyleDeclaration,
    CSSStyleSheet,
    MutationObserver,
    document: { documentElement: {} },
    navigator: {},
    URL,
    Request,
  });
  return { history, historyCalls, location, replaceCalls, Element, HTMLIFrameElement, originalSetAttributeCalls, iframeSetterCalls };
}

test('representative initial HTML rewrite matches the fixture', async () => {
  const upstream = await readFile(new URL('./fixtures/upstream-response.html', import.meta.url), 'utf8');
  const expected = await readFile(new URL('./fixtures/ingress-response.html', import.meta.url), 'utf8');
  assert.equal(applyDocumentRewrites(upstream), expected);
});

test('initial project raw and scoped preview iframe paths retain ingress transport prefix', () => {
  for (const initialPath of [
    `${prefix}/api/projects/project-123/raw/index.html`,
    `${prefix}/api/projects/project-123/preview/scope-456/index.html`,
  ]) {
    const result = runIngressShim(initialPath);
    assert.deepEqual(result.replaceCalls, [], `iframe must not transport-swap ${initialPath}`);
    assert.equal(result.location.pathname, initialPath);
  }

  const spaRoute = runIngressShim(`${prefix}/settings`);
  assert.deepEqual(spaRoute.replaceCalls, ['/settings']);
  assert.equal(spaRoute.location.pathname, '/settings');
});

test('project preview iframe history retains ingress transport prefix', () => {
  const previewPath = '/api/projects/project-123/preview/scope-456/index.html';
  const result = runIngressShim(`${prefix}${previewPath}`);

  result.history.replaceState({ page: 'editor' }, '', `${previewPath}?mode=edit`);
  assert.deepEqual(result.historyCalls.at(-1), {
    method: 'replaceState',
    url: `${prefix}${previewPath}?mode=edit`,
  });
  assert.equal(result.location.pathname, `${prefix}${previewPath}`);
  assert.equal(result.location.search, '?mode=edit');

  result.history.pushState({ panel: 'assets' }, '', '#/assets');
  assert.deepEqual(result.historyCalls.at(-1), {
    method: 'pushState',
    url: `${prefix}${previewPath}?mode=edit#/assets`,
  });
  assert.equal(result.location.pathname, `${prefix}${previewPath}`);
  assert.equal(result.location.hash, '#/assets');

  const spaRoute = runIngressShim(`${prefix}/settings`);
  spaRoute.history.pushState({}, '', '/settings/profile');
  assert.deepEqual(spaRoute.historyCalls.at(-1), {
    method: 'pushState',
    url: '/settings/profile',
  });
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
  assert.doesNotMatch(nginx, /ha-byok|byok\/profiles|127\.0\.0\.1:7457/);
  assert.match(nginx, /ha-ingress\.js.*ha-export-bridge\.js/);
  assert.ok(nginx.indexOf("sub_filter '<head>'") > nginx.indexOf("location /"));
  assert.ok(nginx.indexOf('location ~ ^/api/projects/') < nginx.indexOf('location / {'), 'download bypass must precede the filtered shell location');
});

test('repeated iframe src setAttribute with the same logical URL commits once', () => {
  // React reconciliation writes an unprefixed URL every render; the shim
  // scopes it to the ingress prefix once, then subsequent identical writes
  // must be no-ops so the preview iframe does not reload in a loop.
  const previewPath = '/api/projects/project-123/raw/index.html?v=1';
  const { Element, originalSetAttributeCalls } = runIngressShim(`${prefix}/api/projects/project-123/raw/index.html`);
  const el = new Element();
  originalSetAttributeCalls.length = 0;
  el.setAttribute('src', previewPath);
  el.setAttribute('src', previewPath);
  el.setAttribute('src', previewPath);
  assert.equal(originalSetAttributeCalls.length, 1, 'shim must skip repeated identical URL writes');
  assert.equal(el.getAttribute('src'), `${prefix}${previewPath}`);

  // Changing the URL must still commit.
  el.setAttribute('src', '/api/projects/project-123/raw/other.html');
  assert.equal(originalSetAttributeCalls.length, 2);
  // Reverting to a previously written URL must also commit (attribute differs).
  el.setAttribute('src', previewPath);
  assert.equal(originalSetAttributeCalls.length, 3);
});

test('repeated iframe.src property assignment with the same logical URL commits once', () => {
  const previewPath = '/api/projects/project-123/raw/index.html?v=2';
  const { HTMLIFrameElement, iframeSetterCalls } = runIngressShim(`${prefix}/api/projects/project-123/raw/index.html`);
  const iframe = new HTMLIFrameElement();
  iframeSetterCalls.length = 0;
  iframe.src = previewPath;
  iframe.src = previewPath;
  iframe.src = previewPath;
  assert.equal(iframeSetterCalls.length, 1, 'shim must not re-commit iframe.src for the same canonical URL');

  iframe.src = '/api/projects/project-123/raw/other.html';
  assert.equal(iframeSetterCalls.length, 2);
});

test('early shim covers root-relative streaming, navigation, and dynamic URLs', () => {
  for (const token of [
    'window.fetch',
    'XMLHttpRequest.prototype.open',
    'window.EventSource',
    'window.WebSocket',
    "wrapHistory('pushState', nativeHistoryPushState)",
    "wrapHistory('replaceState', nativeHistoryReplaceState)",
    'logicalHistoryUrl',
    "window.addEventListener('beforeunload'",
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
