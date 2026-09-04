import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import http from 'node:http';
import { chromium } from 'playwright-core';

const prefix = '/api/hassio_ingress/abcdefghijklmnop';
const upstreamPort = Number(process.env.OD_INGRESS_PORT || 8099);
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '/usr/bin/chromium-browser';
const publicRequests = [];
const forwardedRequests = [];
const proxySockets = new Set();

const proxy = http.createServer((request, response) => {
  publicRequests.push(request.url);
  if (!request.url.startsWith(`${prefix}/`) && request.url !== prefix) {
    response.writeHead(404).end('missing ingress prefix');
    return;
  }
  const stripped = request.url.slice(prefix.length) || '/';
  if (stripped === '/__ha_probe/fetch') {
    response.writeHead(200, { 'content-type': 'application/json' }).end('{"transport":"fetch"}');
    return;
  }
  if (stripped === '/__ha_probe/xhr') {
    response.writeHead(200, { 'content-type': 'text/plain' }).end('xhr');
    return;
  }
  if (stripped === '/__ha_probe/events') {
    response.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
    response.end('data: ingress-sse\n\n');
    return;
  }
  // Keep the UI-bridge browser and the real renderer Chromium serial on small
  // CI runners. These deterministic binary stubs validate the browser bridge,
  // path stripping, headers and blob-anchor behavior; container-smoke.sh calls
  // the real image/PDF/PPTX endpoints immediately after this browser exits.
  if (request.method === 'POST' && stripped.endsWith('/export/pdf-image')) {
    forwardedRequests.push({ path: stripped, requestProof: request.headers['x-request-proof'] });
    request.resume();
    response.writeHead(200, {
      'content-type': 'application/pdf',
      'content-disposition': 'attachment; filename="browser-smoke.pdf"',
    });
    response.end('%PDF-1.4\n%%EOF\n');
    return;
  }
  if (request.method === 'POST' && stripped.endsWith('/export/image')) {
    forwardedRequests.push({ path: stripped, requestProof: request.headers['x-request-proof'] });
    request.resume();
    response.writeHead(200, {
      'content-type': 'image/png',
      'content-disposition': 'attachment; filename="browser-smoke.png"',
    });
    response.end(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'));
    return;
  }

  const upstream = http.request({
    hostname: '127.0.0.1',
    port: upstreamPort,
    method: request.method,
    path: stripped,
    headers: {
      ...request.headers,
      host: `127.0.0.1:${upstreamPort}`,
      'x-ingress-path': prefix,
    },
  }, (upstreamResponse) => {
    response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
    upstreamResponse.pipe(response);
  });
  forwardedRequests.push({
    path: stripped,
    requestProof: upstream.getHeader('x-request-proof'),
  });
  upstream.on('error', (error) => {
    console.error(`Supervisor-style proxy upstream failure for ${stripped}: ${error.message}`);
    response.destroy(error);
  });
  request.pipe(upstream);
});

proxy.on('connection', (socket) => {
  proxySockets.add(socket);
  socket.once('close', () => proxySockets.delete(socket));
});

proxy.on('upgrade', (request, socket) => {
  publicRequests.push(request.url);
  if (request.url !== `${prefix}/__ha_probe/ws`) {
    socket.destroy();
    return;
  }
  const accept = createHash('sha1')
    .update(`${request.headers['sec-websocket-key']}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
    .digest('base64');
  socket.write([
    'HTTP/1.1 101 Switching Protocols',
    'Upgrade: websocket',
    'Connection: Upgrade',
    `Sec-WebSocket-Accept: ${accept}`,
    '',
    '',
  ].join('\r\n'));
  socket.write(Buffer.from([0x81, 0x0a, ...Buffer.from('ingress-ws')]));
  setTimeout(() => socket.end(Buffer.from([0x88, 0x00])), 25);
});

await new Promise((resolve, reject) => {
  proxy.once('error', reject);
  proxy.listen(0, '127.0.0.1', resolve);
});
const proxyPort = proxy.address().port;
let browser;
let chromiumHome;
try {
  chromiumHome = await mkdtemp('/tmp/ha-opendesign-ci-browser-');
  const configHome = `${chromiumHome}/config`;
  const cacheHome = `${chromiumHome}/cache`;
  await Promise.all([mkdir(configHome), mkdir(cacheHome)]);
  browser = await chromium.launch({
    executablePath,
    headless: true,
    env: { ...process.env, HOME: chromiumHome, XDG_CONFIG_HOME: configHome, XDG_CACHE_HOME: cacheHome },
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-http2', '--disable-quic'],
  });
  const context = await browser.newContext({ acceptDownloads: true });
  await context.addInitScript(() => {
    localStorage.setItem('open-design:config', JSON.stringify({ onboardingCompleted: true }));
  });
  const page = await context.newPage();
  page.on('requestfailed', (request) => console.error(`browser request failed: ${request.method()} ${request.url()} ${request.failure()?.errorText || ''}`));
  page.on('pageerror', (error) => console.error(`browser page error: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') console.error(`browser console error: ${message.text()}`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) console.error(`browser HTTP ${response.status()}: ${response.url()}`);
  });
  await page.goto(`http://127.0.0.1:${proxyPort}${prefix}/`, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await page.waitForFunction(() => window.__OD_HA_EXPORT_BRIDGE_INSTALLED__ === true, null, { timeout: 15_000 });
  try {
    await page.waitForFunction(
      () => !document.body.textContent.includes('Loading OpenDesign…'),
      null,
      { timeout: 30_000 },
    );
  } catch (error) {
    const diagnostics = await page.evaluate(() => ({
      body: document.body.textContent.slice(0, 500),
      scripts: Array.from(document.scripts).map((script) => script.src || script.textContent.slice(0, 120)),
      resources: performance.getEntriesByType('resource').map((entry) => ({ name: entry.name, duration: entry.duration, transferSize: entry.transferSize })),
      globals: Object.keys(window).filter((key) => /next|turbo|react/i.test(key)).sort(),
      nextFlightLength: window.__next_f?.length,
      pathname: window.location.pathname,
    }));
    console.error(`OpenDesign bootstrap diagnostics: ${JSON.stringify(diagnostics)}`);
    throw error;
  }
  assert.equal(new URL(page.url()).pathname, '/', 'ingress transport prefix must be hidden from OpenDesign route logic');
  const expandSidebar = page.getByRole('button', { name: 'Expand sidebar' });
  if (await expandSidebar.count()) await expandSidebar.click();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.waitForURL((url) => url.pathname === '/settings');
  await page.waitForFunction(() => (
    document.body.innerText.includes('Models & providers')
    && document.body.innerText.includes('API providers')
  ));

  await page.getByText('Back to home', { exact: true }).click();
  await page.waitForURL((url) => url.pathname === '/');
  const expandAfterSettings = page.getByRole('button', { name: 'Expand sidebar' });
  if (await expandAfterSettings.count()) await expandAfterSettings.click();
  await page.getByRole('button', { name: 'Design systems', exact: true }).first().click();
  await page.waitForURL((url) => url.pathname === '/design-systems');
  await page.getByRole('heading', { name: 'Design systems', exact: true }).waitFor();
  // GitHub-hosted headless Chromium does not reliably emit Playwright download
  // events for programmatically clicked blob: anchors. Observe the exact anchor
  // click in-page instead; direct endpoint checks below still verify PDF/image
  // bytes, and the HAOS host acceptance run exercises real download events.
  await page.evaluate(() => {
    window.__OD_TEST_DOWNLOAD_CLICKS__ = [];
    HTMLAnchorElement.prototype.click = function testDownloadClick() {
      window.__OD_TEST_DOWNLOAD_CLICKS__.push({ download: this.download, href: this.href });
    };
  });

  const probes = await page.evaluate(async () => {
    const fetched = await fetch('/__ha_probe/fetch').then((response) => response.json());
    const xhr = await new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open('GET', '/__ha_probe/xhr');
      request.onload = () => resolve(request.responseText);
      request.onerror = reject;
      request.send();
    });
    const sse = await new Promise((resolve, reject) => {
      const source = new EventSource('/__ha_probe/events');
      source.onmessage = (event) => { source.close(); resolve(event.data); };
      source.onerror = reject;
    });
    const websocket = await new Promise((resolve, reject) => {
      const socket = new WebSocket(`ws://${location.host}/__ha_probe/ws`);
      socket.onmessage = (event) => { socket.close(); resolve(event.data); };
      socket.onerror = reject;
    });
    return { fetched, xhr, sse, websocket };
  });
  assert.deepEqual(probes, {
    fetched: { transport: 'fetch' },
    xhr: 'xhr',
    sse: 'ingress-sse',
    websocket: 'ingress-ws',
  });

  const pdfResponse = await page.evaluate(async () => {
    // This matches OpenDesign 0.21.1's actual exportProjectAsPdf call shape.
    // Request-object preservation is covered separately by the unit test.
    const response = await fetch('/api/projects/ha-smoke/export/pdf', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-request-proof': 'browser-request' },
      body: JSON.stringify({ fileName: 'deck.html', deck: true, title: 'Ingress browser' }),
      credentials: 'same-origin',
    });
    return response.json();
  });
  assert.deepEqual(pdfResponse, { ok: true });
  await page.waitForFunction(() => window.__OD_TEST_DOWNLOAD_CLICKS__.length >= 1);

  await page.evaluate(async () => {
    const frame = document.createElement('iframe');
    frame.src = '/api/projects/ha-smoke/raw/deck.html';
    frame.hidden = true;
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog');
    dialog.innerHTML = `
      <input name="image-export-format" type="radio" value="png" checked>
      <div class="modal-foot">
        <button class="viewer-action primary" type="button">Save</button>
        <button class="ghost-link button-like" type="button">Cancel</button>
      </div>`;
    document.body.append(frame, dialog);
    await new Promise((resolve) => setTimeout(resolve, 100));
    dialog.querySelector('.viewer-action.primary').click();
  });
  await page.waitForFunction(() => window.__OD_TEST_DOWNLOAD_CLICKS__.length >= 2, null, { timeout: 120_000 });
  const downloadClicks = await page.evaluate(() => window.__OD_TEST_DOWNLOAD_CLICKS__);
  assert.equal(downloadClicks.length, 2);
  assert.match(downloadClicks[0].download, /\.pdf$/i);
  assert.match(downloadClicks[1].download, /\.png$/i);
  assert.ok(downloadClicks.every(({ href }) => href.startsWith('blob:')));

  for (const probePath of ['fetch', 'xhr', 'events', 'ws']) {
    assert.ok(publicRequests.includes(`${prefix}/__ha_probe/${probePath}`), `${probePath} did not traverse the public HA prefix`);
  }
  assert.ok(publicRequests.some((value) => value.startsWith(`${prefix}/api/projects/ha-smoke/export/pdf-image`)));
  assert.ok(forwardedRequests.some(({ path: requestPath, requestProof }) => (
    requestPath.startsWith('/api/projects/ha-smoke/export/pdf-image')
      && requestProof === 'browser-request'
  )), 'PDF Request headers must survive the Supervisor-style path-stripping proxy');
  assert.ok(publicRequests.some((value) => value.startsWith(`${prefix}/api/projects/ha-smoke/export/image`)));
  console.log('container browser ingress e2e: built UI injection, path stripping, fetch/XHR/SSE/WebSocket, PDF Request headers, and image action passed');
} finally {
  proxy.closeAllConnections?.();
  proxy.closeIdleConnections?.();
  for (const socket of proxySockets) socket.destroy();
  await Promise.race([
    browser?.close().catch(() => {}),
    new Promise((resolve) => setTimeout(resolve, 10_000)),
  ]);
  for (const socket of proxySockets) socket.destroy();
  await Promise.race([
    new Promise((resolve) => proxy.close(resolve)),
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
  if (chromiumHome) await rm(chromiumHome, { recursive: true, force: true });
}

// This is a standalone smoke-test process. If the assertions above completed,
// do not let third-party app timers or Chromium helpers keep CI alive forever.
process.exit(0);
