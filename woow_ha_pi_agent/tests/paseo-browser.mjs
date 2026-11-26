// The Agent Connect page in a real browser behind a front proxy that strips the
// HA Ingress prefix the way Supervisor does. The plugin is a fixture (the 0.1.23
// generation: target switching, no web client, no web()): no daemon, login or
// model call, and the official sites are answered locally, so nothing leaves
// this machine. Run with a preinstalled Playwright package and browser:
//   PLAYWRIGHT_MODULE=/absolute/path/index.mjs CHROMIUM_EXECUTABLE=/path/chrome node tests/paseo-browser.mjs
import assert from 'node:assert/strict';
import http from 'node:http';
import path from 'node:path';
import { once } from 'node:events';
import { pathToFileURL } from 'node:url';
import { createServer } from '../rootfs/usr/local/lib/pi-paseo-ha/server.mjs';
import { createPaseoBridge } from '../rootfs/usr/local/lib/pi-paseo-ha/bridge.mjs';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const prefix = '/api/hassio_ingress/paseobrowserfixture0123';
const offer = 'eyJ2IjoyLCJzZXJ2ZXJJZCI6ImZpeHR1cmUifQ';
const origins = { paseo: 'https://app.paseo.sh', woowtech: 'https://smart.woowtech.io', apporo: 'https://smart.apporo.ai' };
const labels = { paseo: 'Paseo', woowtech: 'Woowtech Smart', apporo: 'Apporo Smart' };
const state = { phase: 'ready', daemon: { running: true }, settings: { target: 'paseo', agentCollaboration: false }, agentCollaboration: false,
  activeTarget: 'paseo', configurationPending: false, connectionTargets: Object.keys(origins).map(id => ({ id })),
  providers: [{ provider: 'claude', status: 'ready' }, { provider: 'codex', status: 'ready' }, { provider: 'pi', status: 'ready' }] };
const calls = [];
const plugin = { enabled: true, version: 'fixture', api: {
  status: async () => state,
  saveConfig: async input => { calls.push({ saveConfig: input }); state.settings.target = input.target; state.configurationPending = state.daemon.running; },
  pair: async () => { calls.push('pair'); return { target: state.settings.target, url: `${origins[state.settings.target]}/#offer=${offer}` }; },
  lifecycle: async input => {
    calls.push(input.action); state.daemon.running = input.action === 'enable';
    if (state.daemon.running) { state.activeTarget = state.settings.target; state.configurationPending = false; }
  },
} };
const backend = createServer({ bridge: createPaseoBridge(async () => plugin), directory: path.resolve(import.meta.dirname, '../rootfs/usr/local/share/pi-paseo-ha') });
backend.listen(0, '127.0.0.1'); await once(backend, 'listening');
const escaped = [];
const ingress = http.createServer((req, res) => {
  if (!req.url.startsWith(prefix + '/')) { escaped.push(req.url); res.writeHead(404); res.end(); return; }
  const upstream = http.request({ hostname: '127.0.0.1', port: backend.address().port, path: req.url.slice(prefix.length), method: req.method,
    headers: { ...req.headers, 'x-ingress-path': prefix } }, response => { res.writeHead(response.statusCode, response.headers); response.pipe(res); });
  req.pipe(upstream);
});
ingress.listen(0, '127.0.0.1'); await once(ingress, 'listening');
const base = `http://127.0.0.1:${ingress.address().port}${prefix}`;
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox'] });
try {
  for (const viewport of [{ width: 1365, height: 900 }, { width: 390, height: 844 }]) {
    Object.assign(state, { daemon: { running: true }, activeTarget: 'paseo', configurationPending: false }); state.settings.target = 'paseo'; calls.length = 0;
    const context = await browser.newContext({ viewport });
    const official = [];
    // The official sites are answered here: the test never reaches the network.
    await context.route(/^https:\/\/(app\.paseo\.sh|smart\.woowtech\.io|smart\.apporo\.ai)\//, route => {
      official.push(route.request().url()); return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>official site fixture</title>' });
    });
    const page = await context.newPage();
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${base}/paseo/setup`);
    await page.locator('#notice').filter({ hasNotText: '讀取中' }).waitFor();
    await page.locator('#pair:enabled').waitFor();
    assert.deepEqual(await page.locator('#target option').evaluateAll(nodes => nodes.map(node => node.value)), ['paseo', 'woowtech', 'apporo']);
    assert.equal(await page.locator('#target').inputValue(), 'paseo');
    // Paseo: the official site, in a new tab, with no local web client anywhere on the page.
    assert.equal(await page.locator('#open').getAttribute('href'), 'https://app.paseo.sh/');
    assert.equal(await page.locator('#open').getAttribute('target'), '_blank'); assert.match(await page.locator('#open').getAttribute('rel'), /noopener/);
    assert.equal((await page.content()).includes('paseo-web'), false);
    const openTab = async locator => {
      const [tab] = await Promise.all([context.waitForEvent('page'), locator.click()]);
      await tab.waitForLoadState('domcontentloaded'); const url = tab.url(); await tab.close(); return url;
    };
    assert.equal(await openTab(page.locator('#open')), 'https://app.paseo.sh/');
    await page.locator('#pair').click();
    await page.locator('#pair-link:not([hidden])').waitFor();
    assert.equal(await page.locator('#pair-link').getAttribute('href'), `https://app.paseo.sh/#offer=${offer}`);
    assert.equal(await page.locator('#pair-link').textContent(), '開啟並配對 Paseo');
    assert.equal(await openTab(page.locator('#pair-link')), `https://app.paseo.sh/#offer=${offer}`);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'no horizontal scrolling');
    // Switching target: nothing opens or pairs until the save is applied by a restart.
    await page.locator('#target').selectOption('apporo');
    assert.equal(await page.locator('#pair-link').isHidden(), true); assert.equal(await page.locator('#pair').isDisabled(), true);
    await page.locator('#save').click();
    await page.locator('#target-notice').filter({ hasText: '停止並重新啟動' }).waitFor();
    assert.equal(await page.locator('#pair').isDisabled(), true);
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#stop').click(); await page.locator('#start:enabled').waitFor(); await page.locator('#start').click();
    await page.locator('#pair:enabled').waitFor();
    assert.equal(await page.locator('#open').getAttribute('href'), 'https://smart.apporo.ai/');
    assert.equal(await page.locator('#open').textContent(), `開啟 ${labels.apporo} 對話介面`);
    await page.locator('#pair').click();
    await page.locator('#pair-link:not([hidden])').waitFor();
    assert.equal(await page.locator('#pair-link').getAttribute('href'), `https://smart.apporo.ai/#offer=${offer}`);
    assert.deepEqual(calls, ['pair', { saveConfig: { target: 'apporo' } }, 'stop', 'enable', 'pair']);
    assert.deepEqual(official.map(url => url.split('#')[0]).filter(url => !url.endsWith('/favicon.ico')), ['https://app.paseo.sh/', 'https://app.paseo.sh/'], 'only the two opened tabs reached an official site');
    // The retired bundled client is not served by this page's server.
    for (const retired of ['/paseo-web/', '/paseo-web/welcome', '/paseo-web/settings']) assert.equal((await context.request.get(base + retired)).status(), 404, retired);
    assert.deepEqual(errors, []);
    await context.close();
  }
  assert.deepEqual(escaped, []);
  console.log('PASS Agent Connect page: official-site links in new tabs, exact pairing links per target, target switch after restart, retired /paseo-web 404, desktop and mobile.');
} finally { await browser.close(); ingress.closeAllConnections(); ingress.close(); backend.closeAllConnections(); backend.close(); }
