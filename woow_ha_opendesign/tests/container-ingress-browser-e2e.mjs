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
  if (request.url.startsWith(`${prefix}/terminal/`)) {
    const stripped = request.url.slice(prefix.length) || '/';
    const upstreamRequest = http.request({
      hostname: '127.0.0.1',
      port: upstreamPort,
      method: 'GET',
      path: stripped,
      headers: {
        ...request.headers,
        host: `127.0.0.1:${upstreamPort}`,
        'x-ingress-path': prefix,
      },
    });
    upstreamRequest.on('upgrade', (upstreamResponse, upstreamSocket, upstreamHead) => {
      const headers = [];
      for (let i = 0; i < upstreamResponse.rawHeaders.length; i += 2) {
        headers.push(`${upstreamResponse.rawHeaders[i]}: ${upstreamResponse.rawHeaders[i + 1]}`);
      }
      socket.write(`HTTP/1.1 ${upstreamResponse.statusCode} ${upstreamResponse.statusMessage}\r\n${headers.join('\r\n')}\r\n\r\n`);
      if (upstreamHead.length) socket.write(upstreamHead);
      upstreamSocket.pipe(socket);
      socket.pipe(upstreamSocket);
      upstreamSocket.on('error', () => socket.destroy());
      socket.on('error', () => upstreamSocket.destroy());
    });
    upstreamRequest.on('response', (upstreamResponse) => {
      socket.end(`HTTP/1.1 ${upstreamResponse.statusCode} ${upstreamResponse.statusMessage}\r\n\r\n`);
      upstreamResponse.resume();
    });
    upstreamRequest.on('error', (error) => {
      console.error(`Supervisor-style terminal WebSocket upstream failure: ${error.message}`);
      socket.destroy(error);
    });
    upstreamRequest.end();
    return;
  }
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
  const terminalLink = page.getByRole('link', { name: 'Open agent CLI terminal for login' });
  await terminalLink.waitFor({ timeout: 15_000 });
  assert.equal(await terminalLink.getAttribute('href'), `${prefix}/terminal/`);
  assert.equal(await terminalLink.getAttribute('target'), '_blank');
  // The built-in MCP server's administration entry sits next to it. This
  // proxy's source is not the Supervisor peer, so only the link is checked
  // here; mcp-runtime/tests/e2e/mcp_link_browser.mjs follows it from there.
  const mcpLink = page.getByRole('link', { name: 'Open built-in MCP server administration' });
  await mcpLink.waitFor({ timeout: 15_000 });
  assert.ok(await mcpLink.isVisible(), 'MCP Server entry must be visible');
  assert.equal(await mcpLink.getAttribute('href'), `${prefix}/mcp-admin/`);
  assert.equal(await mcpLink.getAttribute('target'), '_blank');
  const terminalSocketPromise = new Promise((resolve) => {
    context.on('page', (newPage) => {
      newPage.on('websocket', (socket) => {
        if (socket.url().endsWith('/terminal/ws')) resolve(socket);
      });
    });
  });
  const [terminalPage] = await Promise.all([
    context.waitForEvent('page'),
    terminalLink.click(),
  ]);
  await terminalPage.waitForURL((url) => url.pathname === `${prefix}/terminal/`, { timeout: 15_000 });
  assert.equal(new URL(terminalPage.url()).pathname, `${prefix}/terminal/`);
  let terminalSocketTimeout;
  const terminalSocket = await Promise.race([
    terminalSocketPromise,
    new Promise((_, reject) => {
      terminalSocketTimeout = setTimeout(() => reject(new Error('CLI terminal WebSocket did not connect through ingress')), 15_000);
    }),
  ]);
  clearTimeout(terminalSocketTimeout);
  const terminalInput = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('CLI terminal did not accept keyboard input')), 8_000);
    terminalSocket.on('framesent', ({ payload }) => {
      if (payload && payload.length) {
        clearTimeout(timeout);
        resolve();
      }
    });
  });
  await terminalPage.bringToFront();
  await terminalPage.keyboard.type("printf 'TTYD_INGRESS_OK\\n'");
  await terminalPage.keyboard.press('Enter');
  await terminalInput;
  await terminalPage.close();
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
  // 0.2.1 removed Omnigent: without the woow-omnigent plugin the core's native
  // integration must not open its setup project or connection dialog.
  const onboarding = await page.waitForURL((url) => url.pathname.startsWith('/projects/'), { timeout: 15_000 })
    .then(() => true, () => false);
  assert.equal(onboarding, false, 'no Omnigent setup project may open on first load');
  assert.equal(await page.getByText('Connect Omnigent', { exact: true }).count(), 0, 'no Omnigent connection dialog');
  const omnigentText = await page.evaluate(() => (document.body.innerText.match(/[^\n]*omnigent[^\n]*/gi) ?? []).slice(0, 10));
  console.log(`Omnigent text on the home page: ${JSON.stringify(omnigentText)}`);
  assert.equal(new URL(page.url()).pathname, '/', 'ingress transport prefix must be hidden from OpenDesign route logic');
  // OpenDesign 0.24.1: with the sidebar collapsed the nav-rail buttons sit
  // under the main pane, expanding it re-renders (detaches) them, and two
  // buttons are named Settings. Expand first, let the layout settle, click the
  // rail test id, and retry a click that a concurrent re-render swallowed.
  const navigate = async (locator, pathname) => {
    for (let attempt = 1; ; attempt += 1) {
      try {
        const expand = page.getByRole('button', { name: 'Expand sidebar' }).first();
        if (await expand.isVisible().catch(() => false)) {
          await expand.click({ timeout: 5_000 });
          await page.waitForTimeout(500);
        }
        await locator().click({ timeout: 10_000 });
        await page.waitForURL((url) => url.pathname === pathname, { timeout: 10_000 });
        return;
      } catch (error) {
        if (attempt >= 3) throw error;
      }
    }
  };
  await navigate(() => page.getByTestId('entry-settings-button'), '/settings');
  await page.waitForFunction(() => (
    document.body.innerText.includes('Models & providers')
    && document.body.innerText.includes('API providers')
  ));

  await navigate(() => page.getByRole('button', { name: 'Back to home', exact: true }), '/');
  await navigate(() => page.getByTestId('entry-nav-design-systems'), '/design-systems');
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
