// Ingress browser check of the OpenDesign page's "MCP Server" entry (test-only; builder VM, never production).
//
// Runs in the Supervisor-peer stand-in container (172.30.32.2) of run-proof.sh, copied next to the image's
// playwright-core (/opt/ha-opendesign). A Supervisor-style proxy receives the public ingress prefix, strips it
// and forwards to the add-on's nginx :8099 with X-Ingress-Path and X-Remote-User-Id, from the Supervisor peer
// address. Chromium opens OpenDesign, clicks the injected MCP Server link and must land on the MCP admin UI
// under the same prefix, with its bootstrap API answered 200 through that prefix.
//
//   ADDON=<add-on ip> FAKE_ADMIN_ID=<hex> node /opt/ha-opendesign/mcp_link_browser.mjs
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtemp, rm } from 'node:fs/promises';
import { chromium } from 'playwright-core';

const addon = process.env.ADDON;
const user = process.env.FAKE_ADMIN_ID;
assert.ok(addon && user, 'ADDON and FAKE_ADMIN_ID are required');
const prefix = '/api/hassio_ingress/TeamHaIntegrateFakeIngressSession00000000'; // not a secret
const seen = [];

const proxy = http.createServer((request, response) => {
  if (!request.url.startsWith(`${prefix}/`)) {
    response.writeHead(404).end('missing ingress prefix');
    return;
  }
  const stripped = request.url.slice(prefix.length) || '/';
  const upstream = http.request({
    hostname: addon,
    port: 8099,
    method: request.method,
    path: stripped,
    headers: { ...request.headers, host: `${addon}:8099`, 'x-ingress-path': prefix, 'x-remote-user-id': user },
  }, (upstreamResponse) => {
    seen.push({ path: stripped, status: upstreamResponse.statusCode });
    response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
    upstreamResponse.pipe(response);
  });
  upstream.on('error', (error) => response.destroy(error));
  request.pipe(upstream);
});
await new Promise((resolve) => proxy.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${proxy.address().port}`;
const home = await mkdtemp('/tmp/mcp-link-browser-');
let browser;
try {
  browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '/usr/bin/chromium-browser',
    headless: true,
    env: { ...process.env, HOME: home, XDG_CONFIG_HOME: `${home}/c`, XDG_CACHE_HOME: `${home}/k` },
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-http2', '--disable-quic'],
  });
  const context = await browser.newContext();
  await context.addInitScript(() => {
    localStorage.setItem('open-design:config', JSON.stringify({ onboardingCompleted: true }));
  });
  const page = await context.newPage();
  await page.goto(`${base}${prefix}/`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  const link = page.getByRole('link', { name: 'Open built-in MCP server administration' });
  await link.waitFor({ timeout: 30_000 });
  assert.equal(await link.getAttribute('href'), `${prefix}/mcp-admin/`);
  assert.equal(await link.textContent(), 'MCP Server');
  assert.ok(await link.isVisible(), 'MCP Server entry must be visible on the OpenDesign page');
  const terminal = page.getByRole('link', { name: 'Open agent CLI terminal for login' });
  assert.ok(await terminal.isVisible(), 'CLI Terminal entry must stay visible next to it');
  const bootstrap = context.waitForEvent('response', {
    predicate: (response) => new URL(response.url()).pathname === `${prefix}/mcp-admin/api/bootstrap`,
    timeout: 30_000,
  });
  const [admin] = await Promise.all([context.waitForEvent('page'), link.click()]);
  await admin.waitForURL((url) => url.pathname.startsWith(`${prefix}/mcp-admin/`), { timeout: 30_000 });
  const boot = await bootstrap;
  assert.equal(boot.status(), 200, 'admin bootstrap through the ingress prefix');
  const body = await boot.json();
  assert.equal(body.product, 'opendesign');
  await admin.getByText('工具權限', { exact: true }).first().waitFor({ timeout: 30_000 });
  const title = await admin.title();
  const text = await admin.evaluate(() => document.body.innerText);
  assert.doesNotMatch(text, /管理身分已失效|你沒有管理權限/);
  console.log(JSON.stringify({
    case: 'OpenDesign page -> MCP Server link -> /mcp-admin/ through the ingress prefix',
    link_href_is_prefixed: true,
    admin_url_path: new URL(admin.url()).pathname.replace(prefix, '<ingress>'),
    admin_title: title,
    bootstrap_status: boot.status(),
    product: body.product,
    admin_requests: seen.filter(({ path }) => path.startsWith('/mcp-admin')).map(({ path, status }) => `${status} ${path}`),
  }, null, 1));
} finally {
  await browser?.close().catch(() => {});
  proxy.closeAllConnections?.();
  proxy.close();
  await rm(home, { recursive: true, force: true });
}
process.exit(0);
