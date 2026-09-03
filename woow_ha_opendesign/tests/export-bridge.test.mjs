import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const bridge = require('../rootfs/opt/ha-opendesign/ha-export-bridge.js');

function browserRoot(nativeFetch, options = {}) {
  const downloads = [];
  class Element {}
  const anchorParent = { appendChild() {} };
  const documentElement = options.documentElement ?? Object.assign(new Element(), {
    getAttribute: () => null,
    matches: () => false,
    querySelector: () => null,
    querySelectorAll: () => [],
  });
  const root = {
    __OD_INGRESS_PATH__: '/api/hassio_ingress/abcdefghijklmnop',
    Blob,
    Element,
    MutationObserver: class { observe() {} },
    Request,
    Response,
    URL,
    document: {
      body: anchorParent,
      documentElement,
      createElement: () => ({
        style: {},
        click() { downloads.push({ filename: this.download, href: this.href }); },
        remove() {},
      }),
      querySelectorAll: options.frames ? () => options.frames : () => [],
    },
    fetch: nativeFetch,
    location: { href: 'http://ha.local/api/hassio_ingress/abcdefghijklmnop/' },
    setTimeout(callback) { callback(); },
  };
  return { downloads, root };
}

test('PDF bridge redirects only the upstream browser POST endpoint', () => {
  assert.equal(
    bridge.redirectPdfRequest('/api/projects/project-1/export/pdf', 'POST'),
    '/api/projects/project-1/export/pdf-image',
  );
  assert.equal(
    bridge.redirectPdfRequest('/api/hassio_ingress/abcdefghijklmnop/api/projects/project-1/export/pdf', 'POST'),
    '/api/hassio_ingress/abcdefghijklmnop/api/projects/project-1/export/pdf-image',
  );
  assert.equal(bridge.redirectPdfRequest('/api/projects/project-1/export/pdf', 'GET'), null);
  assert.equal(bridge.redirectPdfRequest('/api/projects/project-1/export/pdf-image', 'POST'), null);
  assert.equal(bridge.redirectPdfRequest('/api/projects/project-1/export/pptx', 'POST'), null);
});

test('bridge learns project and HTML path from preview, raw, and export requests', () => {
  assert.deepEqual(
    bridge.extractArtifactContext('/api/projects/project-1/preview/scope-1/deck%2Findex.html'),
    { projectId: 'project-1', fileName: 'deck/index.html' },
  );
  assert.deepEqual(
    bridge.extractArtifactContext('/api/projects/project-1/raw/deck/index.html'),
    { projectId: 'project-1', fileName: 'deck/index.html' },
  );
  assert.deepEqual(
    bridge.extractArtifactContext('/api/projects/project-1/export/pdf', { body: JSON.stringify({ fileName: 'site.html' }) }),
    { projectId: 'project-1', fileName: 'site.html' },
  );
  assert.equal(bridge.extractArtifactContext('/api/health'), null);
});

test('image bridge handles only required PNG/JPEG formats', () => {
  const dialog = (value) => ({ querySelector: () => value == null ? null : { value } });
  assert.equal(bridge.imageFormatFromDialog(dialog('png')), 'png');
  assert.equal(bridge.imageFormatFromDialog(dialog('jpeg')), 'jpeg');
  assert.equal(bridge.imageFormatFromDialog(dialog('jpg')), 'jpeg');
  assert.equal(bridge.imageFormatFromDialog(dialog('webp')), null);
  assert.equal(bridge.imageFormatFromDialog(dialog(null)), null);
});

test('installed PDF wrapper downloads pdf-image bytes and returns the caller success shape', async () => {
  const calls = [];
  const { downloads, root } = browserRoot(async (input, init) => {
    calls.push({ input: String(input), init });
    return new Response(new Blob(['%PDF-smoke'], { type: 'application/pdf' }), {
      status: 200,
      headers: { 'content-disposition': 'attachment; filename="deck.pdf"' },
    });
  });
  bridge.createForRoot(root).install();
  const response = await root.fetch('/api/projects/project-1/export/pdf', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ fileName: 'deck.html', deck: true }),
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].input, '/api/projects/project-1/export/pdf-image');
  assert.deepEqual(await response.json(), { ok: true });
  assert.equal(downloads.length, 1);
  assert.equal(downloads[0].filename, 'deck.pdf');
});

test('PDF redirect preserves Request method, headers, body, credentials, and signal', async () => {
  const calls = [];
  const { root } = browserRoot(async (input, init) => {
    calls.push({ input, init });
    return new Response(new Blob(['%PDF-request'], { type: 'application/pdf' }), {
      status: 200,
      headers: { 'content-disposition': 'attachment; filename="request.pdf"' },
    });
  });
  bridge.createForRoot(root).install();
  const controller = new AbortController();
  const request = new Request('http://ha.local/api/projects/project-1/export/pdf', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-request-proof': 'preserved' },
    body: JSON.stringify({ fileName: 'request.html', deck: true }),
    credentials: 'include',
    signal: controller.signal,
  });
  const response = await root.fetch(request);
  assert.deepEqual(await response.json(), { ok: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init, undefined);
  assert.ok(calls[0].input instanceof Request);
  assert.equal(calls[0].input.url, 'http://ha.local/api/projects/project-1/export/pdf-image');
  assert.equal(calls[0].input.method, 'POST');
  assert.equal(calls[0].input.headers.get('content-type'), 'application/json');
  assert.equal(calls[0].input.headers.get('x-request-proof'), 'preserved');
  assert.equal(calls[0].input.credentials, 'include');
  assert.equal(calls[0].input.signal.aborted, false);
  controller.abort();
  assert.equal(calls[0].input.signal.aborted, true);
  assert.deepEqual(JSON.parse(await calls[0].input.text()), { fileName: 'request.html', deck: true });
});

test('installed image dialog bridge bypasses web fallback and downloads headless JPEG', async () => {
  let clickHandler;
  let cancelClicks = 0;
  const calls = [];
  const frame = { getAttribute: () => '/api/projects/project-1/raw/deck/index.html' };
  const selected = { value: 'jpeg' };
  const save = {
    disabled: false,
    addEventListener(_name, handler, capture) {
      assert.equal(capture, true);
      clickHandler = handler;
    },
  };
  const cancel = { click() { cancelClicks += 1; } };
  const { root, downloads } = browserRoot(async (input, init) => {
    calls.push({ input: String(input), init });
    return new Response(new Blob(['jpeg-bytes'], { type: 'image/jpeg' }), {
      status: 200,
      headers: { 'content-disposition': "attachment; filename*=UTF-8''deck.jpg" },
    });
  }, { frames: [frame] });
  const dialog = Object.assign(new root.Element(), {
    dataset: {},
    querySelector(selector) {
      if (selector === 'input[name="image-export-format"]:checked') return selected;
      if (selector === 'input[name="image-export-format"]') return selected;
      if (selector === '.modal-foot .viewer-action.primary') return save;
      if (selector === '.modal-foot .ghost-link.button-like') return cancel;
      return null;
    },
  });
  root.document.documentElement.querySelector = (selector) => selector === '[role="dialog"]' ? dialog : null;
  root.document.documentElement.querySelectorAll = (selector) => selector === 'iframe[src]' ? [frame] : [];
  bridge.createForRoot(root).install();
  assert.equal(typeof clickHandler, 'function');
  const stopped = [];
  await clickHandler({
    preventDefault: () => stopped.push('default'),
    stopPropagation: () => stopped.push('propagation'),
    stopImmediatePropagation: () => stopped.push('immediate'),
  });
  assert.deepEqual(stopped, ['default', 'propagation', 'immediate']);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].input, '/api/projects/project-1/export/image');
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    fileName: 'deck/index.html',
    imageFormat: 'jpeg',
  });
  assert.equal(downloads[0].filename, 'deck.jpg');
  assert.equal(cancelClicks, 1);
  assert.equal(save.disabled, false);
});

test('bridge does not install outside a validated HA ingress page', () => {
  const { root } = browserRoot(async () => new Response());
  root.__OD_INGRESS_PATH__ = '';
  bridge.createForRoot(root).install();
  assert.equal(root.__OD_HA_EXPORT_BRIDGE_INSTALLED__, undefined);
});
