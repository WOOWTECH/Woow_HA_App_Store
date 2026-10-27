// Run with a preinstalled Playwright package and browser (no downloads here).
// PLAYWRIGHT_MODULE=/absolute/path/index.mjs CHROMIUM_EXECUTABLE=/path/chrome node tests/omnigent-browser.mjs
import assert from 'node:assert/strict';
import http from 'node:http';
import path from 'node:path';
import { once } from 'node:events';
import { pathToFileURL } from 'node:url';
import { createServer } from '../rootfs/usr/local/lib/pi-omnigent-ha/server.mjs';
import { createOmnigentBridge } from '../rootfs/usr/local/lib/pi-omnigent-ha/bridge.mjs';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const prefix = '/api/hassio_ingress/browserfixture0123456789';
const calls = [];
const current = { phase: 'needs-login', host: { id: 'fixture', connected: false }, loginConfirmed: false,
  engines: { pi: { available: true, version: '1.1.0' }, codex: { available: true, version: '0.162.1' } } };
const plugin = { version: '0.3.11', lifecycle: async () => ({ active: true }), onboarding: () => ({ sessionId: 'fixture-session' }),
  runtime: { status: async () => current,
    catalog: async () => ({ data: { engines: { pi: { models: [{ id: 'test-model-a', displayName: 'Test model A' }, { id: 'test-model-b', displayName: 'Test model B' }] } } } }),
    initialize: async input => { calls.push({ action: 'connect', ...input }); Object.assign(current, { loginConfirmed: true, server: input.server, host: { id: 'fixture', connected: true } }); return { ok: true }; },
    verify: async input => { calls.push({ action: 'verify', ...input }); return { ok: false, phase: 'needs-verification', verification: { pi: { ok: true, reply: 'OMNIGENT_CONNECTION_OK', cleanup: 'stopped', model: input.model } } }; },
    disconnect: async () => { calls.push({ action: 'disconnect' }); current.loginConfirmed = false; current.host.connected = false; return { ok: true }; } } };
const backend = createServer({ bridge: createOmnigentBridge(async () => plugin), directory: path.resolve(import.meta.dirname, '../rootfs/usr/local/share/pi-omnigent-ha') });
backend.listen(0, '127.0.0.1'); await once(backend, 'listening');
let escaped = [];
const ingress = http.createServer((req, res) => {
  if (!req.url.startsWith(prefix + '/')) { escaped.push(req.url); res.writeHead(404); res.end(); return; }
  const upstream = http.request({ hostname: '127.0.0.1', port: backend.address().port, path: req.url.slice(prefix.length), method: req.method,
    headers: { ...req.headers, 'x-ingress-path': prefix } }, response => { res.writeHead(response.statusCode, response.headers); response.pipe(res); });
  req.pipe(upstream);
});
ingress.listen(0, '127.0.0.1'); await once(ingress, 'listening');
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox'] });
try {
  for (const viewport of [{ width: 1365, height: 900 }, { width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${ingress.address().port}${prefix}/omnigent`);
    await page.locator('#setup button').waitFor();
    await page.waitForFunction(() => !document.querySelector('#setup button').disabled);
    assert.equal(await page.locator('[name=server]').inputValue(), '');
    assert.equal(await page.locator('[name=username]').inputValue(), '');
    assert.equal(await page.locator('[name=password]').getAttribute('type'), 'password');
    await page.locator('[name=server]').fill('https://example.test');
    await page.locator('[name=username]').fill('測試');
    await page.locator('[name=password]').fill('fixture-password-only');
    await page.locator('#setup button').click();
    await page.waitForFunction(() => document.querySelector('#notice').textContent.includes('Server 登入完成'));
    assert.equal(await page.locator('[name=password]').inputValue(), '');
    await page.locator('#onboarding:not([hidden])').waitFor();
    assert.equal(await page.locator('#onboarding').getAttribute('href'), `${prefix}/?session=fixture-session`);
    await page.locator('#engine').selectOption('pi');
    for (const model of ['test-model-a', 'test-model-b']) {
      await page.locator('#model').selectOption(model);
      await page.locator('#verify button').click();
      await page.waitForFunction(() => !document.querySelector('#verify button').disabled);
      assert.deepEqual(calls.at(-1), { action: 'verify', engine: 'pi', model });
      assert.ok(!(await page.locator('#notice').innerText()).includes('操作尚未完成'));
    }
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.locator('#disconnect').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('#disconnect').isVisible(), true);
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#disconnect').click();
    await page.waitForFunction(() => document.querySelector('#connection').textContent.includes('主機離線'));
    assert.deepEqual(calls.at(-1), { action: 'disconnect' });
    assert.deepEqual(errors, []);
    await page.close();
  }
  assert.deepEqual(escaped.filter(url => url !== '/favicon.ico'), []);
  assert.equal(calls.filter(call => call.action === 'connect').every(call => call.verify === false), true);
  console.log('Desktop/mobile HA ingress form passed: fresh fields, masked/cleared password, two model switches, confirmed disconnect, no escaped API/asset routes.');
} finally { await browser.close(); backend.closeAllConnections(); backend.close(); ingress.closeAllConnections(); ingress.close(); }
