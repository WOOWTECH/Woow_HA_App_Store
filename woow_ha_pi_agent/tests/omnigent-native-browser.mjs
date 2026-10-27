// Real npm-compiled Pi Web 0.12.0 + the real HA private bridge, with a local
// nginx process serving this repository's production ingress configuration.
// The model runtime is a fixture: no provider login, tokens or paid calls.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import os from 'node:os';
import { once } from 'node:events';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { createServer } from '../rootfs/usr/local/lib/pi-omnigent-ha/server.mjs';
import { createServer as createPaseoServer } from '../rootfs/usr/local/lib/pi-paseo-ha/server.mjs';
import { createPaseoBridge } from '../rootfs/usr/local/lib/pi-paseo-ha/bridge.mjs';
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
const sdk = await import(pathToFileURL(path.join(web, 'node_modules/@earendil-works/pi-coding-agent/dist/index.js')).href);
const fixturePrompt = 'Omnigent setup: enter your server URL, username and password in Settings > Omnigent. No server or account has been supplied.';
const sessionDirectory = path.join(home, '.pi/agent/sessions', `--${home.replace(/^\//, '').replaceAll('/', '-')}--`);
function savedConversation(name, message) {
  const session = sdk.SessionManager.create(home, sessionDirectory);
  session.appendSessionInfo(name);
  session.appendMessage({ role: 'user', content: message, timestamp: Date.now() });
  return { id: session.getSessionId(), file: session.getSessionFile() };
}
const omniSession = savedConversation('Omnigent setup', fixturePrompt);
const paseoSession = savedConversation('Paseo setup', 'Paseo fixture setup; do not select this automatically.');
const originalConversationBytes = Object.fromEntries(fs.readdirSync(sessionDirectory).map(name => [name, fs.readFileSync(path.join(sessionDirectory, name), 'utf8')]));
function assertConversationHistory() {
  assert.deepEqual(fs.readdirSync(sessionDirectory).sort(), Object.keys(originalConversationBytes).sort(), 'opening setup cannot create a replacement conversation');
  const additions = [];
  for (const [name, original] of Object.entries(originalConversationBytes)) {
    const actual = fs.readFileSync(path.join(sessionDirectory, name), 'utf8');
    assert.ok(actual.startsWith(original), 'original session history remains byte-for-byte intact');
    const types = actual.slice(original.length).trim().split('\n').filter(Boolean).map(line => JSON.parse(line).type);
    additions.push(...types);
    assert.ok(types.every(type => ['model_change', 'thinking_level_change', 'custom'].includes(type)), `only native runtime metadata may append: ${types}`);
  }
  return additions;
}
const stateDir = path.join(home, '.pi/agent/omnigent-plugin');
fs.mkdirSync(stateDir, { recursive: true });
const calls = [];
let lifecycle = { active: true, registered: true };
const current = { phase: 'needs-login', enabled: true, loginConfirmed: false, host: { id: 'fixture', connected: false },
  engines: { pi: { available: true, version: '1.1.0' } } };
const plugin = { locations: () => ({ stateDir }), version: '0.3.27', lifecycle: async () => lifecycle,
  onboarding: () => ({ sessionId: omniSession.id }),
  runtime: { status: async () => current,
    catalog: async () => ({ data: { engines: { pi: { models: [{ id: 'test-a', displayName: 'Test A' }, { id: 'test-b', displayName: 'Test B' }] } } } }),
    initialize: async input => { calls.push({ action: 'connect', ...input }); Object.assign(current, { loginConfirmed: true, server: input.server, host: { connected: true } }); return { ok: true }; },
    verify: async input => { calls.push({ action: 'verify', ...input }); return { ok: true }; },
    disconnect: async () => { calls.push({ action: 'disconnect' }); current.host.connected = false; current.loginConfirmed = false; return { ok: true }; } } };
const paseoRoot = process.env.PASEO_PLUGIN_ROOT;
assert.ok(paseoRoot, 'PASEO_PLUGIN_ROOT must be the checksum-verified public plugin');
const webClient = await import(pathToFileURL(path.join(paseoRoot, 'src/web-client.mjs')).href);
const clientState = { stateDir: path.join(evidence, 'paseo-state') };
await webClient.ensureWebClient(clientState);
const paseoCalls = [];
const paseoPlugin = { enabled: true, version: '0.1.12', api: {
  status: async () => ({ phase: 'ready', daemon: { running: true }, webClient: { ready: true, version: '0.13.0-woow.1' }, providers: [{ provider: 'claude', status: 'ready' }, { provider: 'codex', status: 'ready' }, { provider: 'pi', status: 'ready' }] }),
  pair: async () => { paseoCalls.push('pair'); return { url: '/paseo-web/#fixture-pairing' }; },
  web: request => webClient.serveWebClient(request, clientState),
} };
const paseo = createPaseoServer({ bridge: createPaseoBridge(async () => paseoPlugin), directory: path.join(root, 'rootfs/usr/local/share/pi-paseo-ha') });
const paseoSocket = path.join(os.tmpdir(), `ha-paseo-browser-${process.pid}.sock`);
paseo.listen(paseoSocket); await once(paseo, 'listening');
const backend = createServer({ bridge: createOmnigentBridge(async () => plugin), directory: path.join(root, 'rootfs/usr/local/share/pi-omnigent-ha') });
const omniSocket = path.join(os.tmpdir(), `ha-omni-browser-${process.pid}.sock`);
backend.listen(omniSocket); await once(backend, 'listening');
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
const escaped = [], errors = [], results = [], failedClientAssets = [], transfers = [], promptRequests = [];
// Run the actual nginx config; only bind addresses, private socket paths and
// temporary logs differ. The front proxy simulates Supervisor path stripping;
// it never rewrites application response bodies or injects browser code.
const nginxReserve = http.createServer(); nginxReserve.listen(0, '127.0.0.1'); await once(nginxReserve, 'listening');
const nginxPort = nginxReserve.address().port; await new Promise(resolve => nginxReserve.close(resolve));
const nginxConfig = nginx.replace('pid /var/run/nginx.pid;', `pid ${evidence}/nginx.pid;`)
  .replace('error_log /dev/stderr info;', `error_log ${evidence}/nginx-error.log info;`)
  .replace('access_log /dev/stdout;', `access_log ${evidence}/nginx-access.log;`)
  .replace('include /etc/nginx/mime.types;', `include ${process.env.NGINX_MIME_TYPES || '/etc/nginx/mime.types'};`)
  .replace('listen 172.30.32.1:30142', `listen 127.0.0.1:${nginxPort}`)
  .replace('allow 172.30.32.2;', 'allow 127.0.0.1;')
  .replaceAll('/data/pi-agent/omnigent-ha.sock', omniSocket).replaceAll('/data/pi-agent/paseo-ha.sock', paseoSocket)
  .replaceAll('127.0.0.1:30141', `127.0.0.1:${port}`)
  .replace('http {', `http { client_body_temp_path ${evidence}/body-temp; proxy_temp_path ${evidence}/proxy-temp; fastcgi_temp_path ${evidence}/fastcgi-temp; uwsgi_temp_path ${evidence}/uwsgi-temp; scgi_temp_path ${evidence}/scgi-temp;`);
fs.writeFileSync(path.join(evidence, 'nginx.conf'), nginxConfig);
const nginxLog = fs.openSync(path.join(evidence, 'nginx-process.log'), 'w');
const proxy = spawn(process.env.NGINX_EXECUTABLE || 'nginx', ['-p', evidence, '-c', path.join(evidence, 'nginx.conf')], { stdio: ['ignore', nginxLog, nginxLog] }); fs.closeSync(nginxLog);
const ingress = http.createServer((req, res) => {
  if (!req.url.startsWith(prefix + '/')) { escaped.push(req.url); res.writeHead(404).end(); return; }
  const url = req.url.slice(prefix.length);
  const upstream = http.request({ hostname: '127.0.0.1', port: nginxPort,
    path: req.url.slice(prefix.length), method: req.method,
    headers: { ...req.headers, 'x-ingress-path': prefix } }, response => {
      res.writeHead(response.statusCode, response.headers); response.pipe(res);
    });
  upstream.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end(); });
  req.pipe(upstream);
});
try {
  for (let attempt = 0; ; attempt++) {
    try { const response = await fetch(`http://127.0.0.1:${nginxPort}/`); if (response.ok) break; } catch {}
    if (attempt > 60 || child.exitCode !== null) throw new Error('Compiled Pi Web did not start; see pi-web.log');
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  ingress.listen(0, '127.0.0.1'); await once(ingress, 'listening');
  const base = `http://127.0.0.1:${ingress.address().port}${prefix}`;
  const pageChunks = fs.readdirSync(path.join(web, '.next/static/chunks/app')).filter(name => /^page-[a-f0-9]{16}\.js$/.test(name));
  assert.equal(pageChunks.length, 1, 'one compiled page chunk');
  const chunkResponse = await fetch(`${base}/_next/static/chunks/app/${pageChunks[0]}`);
  assert.equal(chunkResponse.status, 200, 'compiled page chunk through actual nginx ingress');
  const servedChunk = await chunkResponse.text();
  const iconExpression = servedChunk.match(/(?:let|var)\s+[\w$]+=([^;]*catppuccin[^;]*);function\s+[\w$]+\(/)?.[1];
  assert.ok(iconExpression, 'Catppuccin path in the served page chunk');
  const iconBase = new Function('window', `return ${iconExpression}`)({ __INGRESS_PATH__: prefix });
  assert.equal(iconBase, `${prefix}/icons/catppuccin`, 'nginx must not add a second ingress prefix');
  const iconResponse = await fetch(new URL(base).origin + `${iconBase}/latte/json.svg`);
  assert.equal(iconResponse.status, 200, 'Catppuccin icon survives the real nginx and Supervisor path strip');
  assert.match(iconResponse.headers.get('content-type') || '', /image\/svg\+xml/);
  results.push({ catppuccinIngressIcon: true, iconStatus: iconResponse.status });
  const observe = context => context.on('request', request => {
    if (request.method() !== 'POST') return;
    let body; try { body = request.postDataJSON(); } catch { return; }
    if (['prompt', 'steer', 'follow_up'].includes(body?.type)) promptRequests.push(body.type);
  });
  browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, headless: true, args: ['--no-sandbox'] });
  // A stale conversation from a previous image must not open on a fresh home visit.
  fs.writeFileSync(path.join(stateDir, 'onboarding.json'), JSON.stringify({ sessionId: omniSession.id }), { mode: 0o600 });
  for (const viewport of [{ width: 1365, height: 900 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]) {
    const callsBefore = calls.length;
    const context = await browser.newContext({ viewport, locale: 'en-US' });
    observe(context);
    const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/');
    // Upstream hydrates as desktop, then closes the phone drawer. Waiting on
    // its resolved state avoids clicking Settings just before it slides away.
    await page.locator('.sidebar-container:not(.sidebar-mobile-pending)').waitFor({ state: 'attached' });
    await page.waitForTimeout(1100);
    assert.notEqual(new URL(page.url()).searchParams.get('session'), omniSession.id, 'legacy setup session stays closed');
    assert.equal(await page.getByRole('link', { name: 'Omnigent', exact: true }).count(), 0, 'no floating Omnigent link on home');
    assert.equal(await page.getByRole('link', { name: 'Paseo', exact: true }).count(), 0, 'no floating Paseo link on home');
    assert.equal((await context.request.get(base + '/omnigent/onboarding')).status(), 404);
    assert.equal((await context.request.get(base + '/omnigent/launcher.js')).status(), 404);
    assertConversationHistory();

    if (viewport.width <= 640) {
      await page.locator('.sidebar-container.sidebar-closed').waitFor({ state: 'attached' });
      await page.getByRole('button', { name: 'Show sidebar', exact: true }).click();
    }
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    const dialog = page.locator('.settings-dialog-surface'); await dialog.waitFor();
    const labels = await dialog.locator('.settings-section-tab').allTextContents();
    assert.equal(labels[labels.indexOf('Omnigent') + 1], 'Paseo');
    assert.equal(labels[labels.indexOf('MCP') + 1], 'Omnigent', 'native settings must put Omnigent immediately after MCP');
    const options = await dialog.locator('.settings-mobile-section-picker option').evaluateAll(nodes => nodes.map(node => node.value));
    assert.equal(options[options.indexOf('omnigent') + 1], 'paseo');
    assert.equal(options[options.indexOf('mcp') + 1], 'omnigent', 'mobile native settings must have the same order');
    const select = async section => {
      if (await dialog.locator('.settings-mobile-section-picker').isVisible()) await dialog.locator('.settings-mobile-section-picker').selectOption(section);
      else await dialog.getByRole('button', { name: section === 'paseo' ? 'Paseo' : section === 'omnigent' ? 'Omnigent' : section === 'mcp' ? 'MCP' : 'General', exact: true }).click();
    };
    await select('paseo');
    const paseoFrame = page.frameLocator('iframe[title="Paseo"]');
    await paseoFrame.locator('#pair:enabled').waitFor();
    assert.equal(await paseoFrame.locator('#onboarding').count(), 0, 'Settings must not link to a setup conversation');
    assert.equal(await page.locator('iframe[title="Paseo"]').getAttribute('src'), prefix + '/paseo/setup?embedded=1');
    await paseoFrame.locator('#pair').click();
    await paseoFrame.locator('#pair-link:not([hidden])').waitFor();
    assert.equal(await paseoFrame.locator('#pair-link').getAttribute('href'), prefix + '/paseo-web/#fixture-pairing');
    await paseoFrame.locator('#stop').scrollIntoViewIfNeeded();
    assert.equal(await paseoFrame.locator('html').evaluate(node => node.scrollWidth > innerWidth), false);
    const [clientPage] = await Promise.all([context.waitForEvent('page'), paseoFrame.locator('#open').click()]);
    clientPage.on('pageerror', error => errors.push(error.message));
    clientPage.on('response', response => { if (response.status() >= 400 && response.url().includes('/paseo-web/')) failedClientAssets.push({ path: new URL(response.url()).pathname, status: response.status() }); });
    await clientPage.waitForLoadState('networkidle');
    assert.ok(clientPage.url().includes(prefix + '/paseo-web/'));
    // Dynamic attachment chunks can be inserted before the entry script.
    // Use the main script declared by the served HTML for router assertions.
    const entryResponse = await context.request.get(base + '/paseo-web/');
    assert.equal(entryResponse.status(), 200);
    const script = (await entryResponse.text()).match(/<script[^>]+src="([^"]+\/_expo\/static\/js\/web\/index-[^"]+\.js)"/)?.[1];
    assert.ok(script, 'served client HTML declares its main entry script');
    const scriptUrl = new URL(script, clientPage.url());
    assert.ok(scriptUrl.pathname.startsWith(prefix + '/paseo-web/'), `script escaped HA Ingress: ${scriptUrl.pathname}`);
    const scriptResponse = await context.request.get(scriptUrl.href, { headers: { 'Accept-Encoding': 'gzip' } });
    assert.equal(scriptResponse.status(), 200);
    assert.equal(scriptResponse.headers()['cache-control'], 'private, max-age=31536000, immutable');
    assert.equal(scriptResponse.headers()['content-encoding'], 'gzip');
    const decompressedBytes = (await scriptResponse.body()).length;
    const wireBytes = Number(scriptResponse.headers()['content-length']);
    assert.ok(wireBytes > 0 && wireBytes < decompressedBytes * 0.55, 'gzip must reduce actual wire bytes');
    assert.equal(scriptResponse.headers().vary, 'Accept-Encoding, X-Ingress-Path');
    const validator = scriptResponse.headers().etag;
    assert.ok(validator);
    const head = await context.request.head(scriptUrl.href, { headers: { 'Accept-Encoding': 'gzip' } });
    assert.equal(head.headers().etag, validator); assert.equal(Number(head.headers()['content-length']), wireBytes);
    assert.equal(head.headers()['content-encoding'], 'gzip'); assert.equal((await head.body()).length, 0);
    const conditional = await context.request.get(scriptUrl.href, { headers: { 'Accept-Encoding': 'gzip', 'If-None-Match': validator } });
    assert.equal(conditional.status(), 304); assert.equal((await conditional.body()).length, 0);
    const identity = await context.request.get(scriptUrl.href, { headers: { 'Accept-Encoding': 'identity' } });
    assert.ok(!identity.headers()['content-encoding']); assert.notEqual(identity.headers().etag, validator);
    assert.equal(Number(identity.headers()['content-length']), decompressedBytes);
    transfers.push({ viewport: viewport.width, identityBytes: decompressedBytes, gzipWireBytes: wireBytes, ratio: wireBytes / decompressedBytes, head: true, conditional304: true });
    assert.ok((await scriptResponse.text()).includes(prefix + '/paseo-web'), 'actual bundle router and assets receive the prefix');
    const setupResponse = await context.request.get(base + '/paseo/setup');
    assert.ok(setupResponse.headers()['content-security-policy'].includes("frame-ancestors 'self'"));
    assert.doesNotMatch(await clientPage.locator('body').innerText(), /Unmatched Route|page could not be found/);
    await clientPage.goto(base + '/paseo-web/settings');
    await clientPage.waitForLoadState('networkidle'); await clientPage.reload();
    await clientPage.waitForLoadState('networkidle');
    assert.doesNotMatch(await clientPage.locator('body').innerText(), /Unmatched Route|page could not be found/);
    await clientPage.screenshot({ path: path.join(evidence, `paseo-${viewport.width}.png`), fullPage: true });
    await clientPage.close();
    await select('omnigent');
    const frame = page.frameLocator('iframe[title="Omnigent"]');
    await frame.locator('#setup button:enabled').waitFor();
    assert.equal(await page.locator('iframe[title="Omnigent"]').getAttribute('src'), `${prefix}/omnigent?embedded=1`);
    assert.equal(await frame.locator('[name=server]').inputValue(), '');
    assert.equal(await frame.locator('[name=username]').inputValue(), '');
    assert.equal(await frame.locator('[name=password]').getAttribute('type'), 'password');
    await frame.locator('#onboarding:not([hidden])').waitFor();
    assert.equal(await frame.locator('#onboarding').getAttribute('href'), `${prefix}/?session=${omniSession.id}`);
    assert.equal(await frame.locator('#onboarding').getAttribute('target'), '_parent');
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
    assert.equal(await frame.locator('#onboarding').count(), 1);
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
    results.push({ viewport, nativeNavigation: true, fallback: true, modelSelections: 2, paseo: { pinnedStaticClient: true, ingress: true, deepLinkReload: true, mobileScroll: true } });
    await context.close();
  }
  assert.deepEqual(escaped.filter(url => url !== '/favicon.ico'), []);
  assert.deepEqual(errors, []); assert.deepEqual(failedClientAssets, []);
  assert.ok(!fs.readFileSync(path.join(evidence, 'nginx-access.log'), 'utf8').includes('fixture-pairing'), 'pair fragments never reach nginx access log');
  assert.deepEqual(promptRequests, [], 'no prompts or provider calls');
  fs.writeFileSync(path.join(evidence, 'browser-receipt.json'), JSON.stringify({ piWeb: '0.12.0', upstream: 'npm compiled artifact', proxy: 'actual nginx + simulated HA Supervisor path stripping', modelRuntime: 'fixture only', results, errors, escaped, failedClientAssets, transfers }, null, 2));
  console.log('PASS Omnigent setup link and native Settings: model selection, disconnect, Paseo and ingress work on desktop/tablet/mobile.');
} finally {
  await browser?.close(); ingress.closeAllConnections(); ingress.close(); backend.closeAllConnections(); backend.close(); paseo.closeAllConnections(); paseo.close();
  proxy.kill('SIGTERM'); if (proxy.exitCode === null) await once(proxy, 'exit');
  child.kill('SIGTERM'); if (child.exitCode === null) await once(child, 'exit');
  fs.rmSync(home, { recursive: true, force: true });
}
