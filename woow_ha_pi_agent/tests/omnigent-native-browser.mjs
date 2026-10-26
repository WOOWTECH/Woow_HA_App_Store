// Real npm-compiled Pi Web 0.12.0 + the real HA private bridge, with a local
// Ingress proxy applying this repository's nginx sub_filter rules verbatim.
// The model runtime is a fixture: no provider login, tokens or paid calls.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { once } from 'node:events';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { createServer } from '../rootfs/usr/local/lib/pi-omnigent-ha/server.mjs';
import { createOmnigentBridge } from '../rootfs/usr/local/lib/pi-omnigent-ha/bridge.mjs';

const root = path.resolve(import.meta.dirname, '..');
const web = process.env.PI_WEB_ROOT;
const evidence = process.env.EVIDENCE_DIR;
assert.ok(web && evidence, 'PI_WEB_ROOT and EVIDENCE_DIR must be isolated test directories');
assert.equal(JSON.parse(fs.readFileSync(path.join(web, 'package.json'))).version, '0.12.0');
fs.mkdirSync(evidence, { recursive: true });
const home = fs.mkdtempSync(path.join(evidence, 'browser-home-'));
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const prefix = '/api/hassio_ingress/nativefixture0123456789';
const nginx = fs.readFileSync(path.join(root, 'rootfs/etc/nginx/nginx.conf'), 'utf8');
const rewrites = [...nginx.matchAll(/sub_filter\s+'([^']*)'\s+'([^']*)';/g)].map(([, from, to]) => [from, to.replaceAll('$safe_ingress_path', prefix)]);
assert.ok(rewrites.length > 10, 'load real Ingress rewrite rules');
const calls = [];
const current = { phase: 'needs-login', loginConfirmed: false, host: { id: 'fixture', connected: false },
  engines: { pi: { available: true, version: '1.1.0' } } };
const plugin = { version: '0.3.11', lifecycle: async () => ({ active: true }), onboarding: () => ({ sessionId: 'fixture-session' }),
  runtime: { status: async () => current,
    catalog: async () => ({ data: { engines: { pi: { models: [{ id: 'test-a', displayName: 'Test A' }, { id: 'test-b', displayName: 'Test B' }] } } } }),
    initialize: async input => { calls.push({ action: 'connect', ...input }); Object.assign(current, { loginConfirmed: true, server: input.server, host: { connected: true } }); return { ok: true }; },
    verify: async input => { calls.push({ action: 'verify', ...input }); return { ok: true }; },
    disconnect: async () => { calls.push({ action: 'disconnect' }); current.host.connected = false; current.loginConfirmed = false; return { ok: true }; } } };
const backend = createServer({ bridge: createOmnigentBridge(async () => plugin), directory: path.join(root, 'rootfs/usr/local/share/pi-omnigent-ha') });
backend.listen(0, '127.0.0.1'); await once(backend, 'listening');
const reserve = http.createServer(); reserve.listen(0, '127.0.0.1'); await once(reserve, 'listening');
const port = reserve.address().port; await new Promise(resolve => reserve.close(resolve));
const log = fs.openSync(path.join(evidence, 'pi-web.log'), 'w');
const child = spawn(process.execPath, [path.join(web, 'node_modules/next/dist/bin/next'), 'start', '-H', '127.0.0.1', '-p', String(port)], {
  cwd: web, stdio: ['ignore', log, log],
  env: { PATH: process.env.PATH, HOME: home, NODE_ENV: 'production', NEXT_TELEMETRY_DISABLED: '1',
    PI_CODING_AGENT_DIR: path.join(home, '.pi/agent'), PI_WEB_HOSTNAME: '127.0.0.1', PI_SKIP_VERSION_CHECK: '1', PI_TELEMETRY: '0' },
});
fs.closeSync(log);
let browser;
const escaped = [], errors = [], results = [];
const ingress = http.createServer((req, res) => {
  if (!req.url.startsWith(prefix + '/')) { escaped.push(req.url); res.writeHead(404).end(); return; }
  const url = req.url.slice(prefix.length);
  const privateRoute = /^\/(omnigent(?:[/?]|$)|api\/omnigent(?:[?]|$))/.test(url);
  const headers = { ...req.headers, 'x-ingress-path': prefix, 'accept-encoding': 'identity' };
  if (!privateRoute) { headers.host = 'localhost'; delete headers.origin; }
  const upstream = http.request({ hostname: '127.0.0.1', port: privateRoute ? backend.address().port : port,
    path: url, method: req.method, headers }, response => {
    const responseHeaders = { ...response.headers }; delete responseHeaders['content-length']; delete responseHeaders['transfer-encoding'];
    const rewrite = !privateRoute && /text\/html|text\/css|javascript/.test(response.headers['content-type'] || '');
    res.writeHead(response.statusCode, responseHeaders);
    if (!rewrite) { response.pipe(res); return; }
    const chunks = []; response.on('data', chunk => chunks.push(chunk));
    response.on('end', () => { let body = Buffer.concat(chunks).toString(); for (const [from, to] of rewrites) body = body.replaceAll(from, to); res.end(body); });
  });
  upstream.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end(); });
  req.pipe(upstream);
});
try {
  for (let attempt = 0; ; attempt++) {
    try { const response = await fetch(`http://127.0.0.1:${port}/`); if (response.ok) break; } catch {}
    if (attempt > 60 || child.exitCode !== null) throw new Error('Compiled Pi Web did not start; see pi-web.log');
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  ingress.listen(0, '127.0.0.1'); await once(ingress, 'listening');
  const base = `http://127.0.0.1:${ingress.address().port}${prefix}`;
  browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox'] });
  for (const viewport of [{ width: 1365, height: 900 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]) {
    const callsBefore = calls.length;
    const context = await browser.newContext({ viewport, locale: 'en-US' });
    const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/');
    // Upstream hydrates as desktop, then closes the phone drawer. Waiting on
    // its resolved state avoids clicking Settings just before it slides away.
    await page.locator('.sidebar-container:not(.sidebar-mobile-pending)').waitFor({ state: 'attached' });
    if (viewport.width <= 640) {
      await page.locator('.sidebar-container.sidebar-closed').waitFor({ state: 'attached' });
      await page.getByRole('button', { name: 'Show sidebar', exact: true }).click();
    }
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    const dialog = page.locator('.settings-dialog-surface'); await dialog.waitFor();
    const labels = await dialog.locator('.settings-section-tab').allTextContents();
    assert.equal(labels[labels.indexOf('MCP') + 1], 'Omnigent', 'native settings must put Omnigent immediately after MCP');
    const options = await dialog.locator('.settings-mobile-section-picker option').evaluateAll(nodes => nodes.map(node => node.value));
    assert.equal(options[options.indexOf('mcp') + 1], 'omnigent', 'mobile native settings must have the same order');
    const select = async section => {
      if (await dialog.locator('.settings-mobile-section-picker').isVisible()) await dialog.locator('.settings-mobile-section-picker').selectOption(section);
      else await dialog.getByRole('button', { name: section === 'omnigent' ? 'Omnigent' : section === 'mcp' ? 'MCP' : 'General', exact: true }).click();
    };
    await select('omnigent');
    const frame = page.frameLocator('iframe[title="Omnigent"]');
    await frame.locator('#setup button:enabled').waitFor();
    assert.equal(await page.locator('iframe[title="Omnigent"]').getAttribute('src'), `${prefix}/omnigent?embedded=1`);
    assert.equal(await frame.locator('[name=server]').inputValue(), '');
    assert.equal(await frame.locator('[name=username]').inputValue(), '');
    assert.equal(await frame.locator('[name=password]').getAttribute('type'), 'password');
    assert.equal(calls.length, callsBefore, 'opening settings must not trigger model calls');
    await page.screenshot({ path: path.join(evidence, `native-top-${viewport.width}.png`), fullPage: true });
    await frame.locator('[name=password]').fill('discard-this-fixture');
    await select('mcp');
    assert.equal(await page.locator('iframe[title="Omnigent"]').count(), 0, 'leaving the panel unmounts its password form');
    await select('omnigent');
    await frame.locator('#setup button:enabled').waitFor();
    assert.equal(await frame.locator('[name=password]').inputValue(), '');
    await frame.locator('[name=server]').fill('https://example.test');
    await frame.locator('[name=username]').fill('fixture');
    await frame.locator('[name=password]').fill('fixture-password-only');
    await frame.locator('#setup button').click();
    await frame.locator('#setup button:enabled').waitFor();
    assert.equal(calls.at(-1).verify, false);
    assert.equal(await frame.locator('[name=password]').inputValue(), '');
    assert.equal(await frame.locator('#onboarding').getAttribute('href'), `${prefix}/?session=fixture-session`);
    assert.equal(await frame.locator('#onboarding').getAttribute('target'), '_parent');
    await frame.locator('#engine').selectOption('pi');
    for (const model of ['test-a', 'test-b']) {
      await frame.locator('#model').selectOption(model); await frame.locator('#verify button').click();
      await frame.locator('#verify button:enabled').waitFor();
      assert.deepEqual(calls.at(-1), { action: 'verify', engine: 'pi', model });
    }
    const overflow = await frame.locator('html').evaluate(node => node.scrollWidth > innerWidth);
    assert.equal(overflow, false, 'embedded form fits the viewport');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(evidence, `native-${viewport.width}.png`), fullPage: true });
    page.once('dialog', item => item.accept()); await frame.locator('#disconnect').click();
    await frame.locator('#setup button:enabled').waitFor(); assert.equal(calls.at(-1).action, 'disconnect');
    await frame.locator('[name=username]').focus(); await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await page.frameLocator('iframe[title="Omnigent"]').locator('#setup button:enabled').waitFor();
    assert.equal(await page.locator('.settings-section-tab[aria-current=page]').textContent(), 'Omnigent', 'last section survives closing settings');
    await page.goto(base + '/omnigent');
    await page.locator('#setup button:enabled').waitFor();
    assert.equal(await page.locator('#back').getAttribute('href'), prefix + '/');
    assert.equal(await page.locator('#back').getAttribute('target'), null, 'standalone fallback stays standalone');
    results.push({ viewport, nativeNavigation: true, fallback: true, modelSelections: 2 });
    await context.close();
  }
  assert.deepEqual(escaped.filter(url => url !== '/favicon.ico'), []);
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(evidence, 'browser-receipt.json'), JSON.stringify({ piWeb: '0.12.0', upstream: 'npm compiled artifact', proxy: 'local nginx-rule fixture', modelRuntime: 'fixture only', results, errors, escaped }, null, 2));
  console.log('PASS compiled Pi Web 0.12 desktop/tablet/mobile: MCP adjacency, embedded bridge, fresh credentials, model selection, disconnect, Escape, remount, Ingress fallback.');
} finally {
  await browser?.close(); ingress.closeAllConnections(); ingress.close(); backend.closeAllConnections(); backend.close();
  child.kill('SIGTERM'); if (child.exitCode === null) await once(child, 'exit');
  fs.rmSync(home, { recursive: true, force: true });
}
