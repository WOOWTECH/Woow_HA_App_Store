import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { once } from 'node:events';
import { seed, startLifecycle } from '../rootfs/usr/local/lib/pi-paseo-ha/lifecycle.mjs';
import * as lifecycleModule from '../rootfs/usr/local/lib/pi-paseo-ha/lifecycle.mjs';
import { createPaseoBridge } from '../rootfs/usr/local/lib/pi-paseo-ha/bridge.mjs';
import { createServer } from '../rootfs/usr/local/lib/pi-paseo-ha/server.mjs';
import * as ingressModule from '../rootfs/usr/local/lib/pi-paseo-ha/ingress.mjs';
import { pairUrl } from '../rootfs/usr/local/lib/pi-paseo-ha/ingress.mjs';

const root = path.resolve(import.meta.dirname, '..');
const bundle = '/opt/woow/pi-paseo-plugin';
const panelDirectory = path.join(root, 'rootfs/usr/local/share/pi-paseo-ha');
function fixture(t) {
  const agentDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ha-paseo-'));
  const home = path.join(agentDir, 'home'); fs.mkdirSync(home);
  t.after(() => fs.rmSync(agentDir, { recursive: true, force: true }));
  const file = path.join(agentDir, 'settings.json');
  return { agentDir, home, bundle, file, write: data => fs.writeFileSync(file, JSON.stringify(data)), read: () => JSON.parse(fs.readFileSync(file, 'utf8')) };
}
test('first boot registers once, retains all settings, removal survives restart and image upgrades', t => {
  const f = fixture(t); f.write({ theme: 'light', packages: ['some-other-plugin'] });
  assert.equal(seed(f).seeded, true);
  assert.deepEqual(f.read(), { theme: 'light', packages: ['some-other-plugin', bundle] });
  assert.equal(seed(f).seeded, false);
  f.write({ theme: 'light', packages: [] });
  assert.equal(seed(f).seeded, false); assert.deepEqual(f.read().packages, []);
  assert.equal(fs.statSync(f.file).mode & 0o777, 0o600);
});
test('disabled, git, npm and local installations are never overwritten or duplicated', t => {
  const f = fixture(t);
  const marker = path.join(f.agentDir, 'pi-paseo/image-seed.json');
  const custom = path.join(f.agentDir, 'custom'); fs.mkdirSync(custom);
  fs.writeFileSync(path.join(custom, 'package.json'), JSON.stringify({ name: '@woowtech/pi-paseo' }));
  for (const entry of [{ source: bundle, extensions: [] }, 'git:github.com/WOOWTECH/pi-paseo-plugin@v0.3.11',
    'git:git@github.com:WOOWTECH/pi-paseo-plugin.git@v0.3.11', 'npm:@woowtech/pi-paseo@0.3.11', custom]) {
    fs.rmSync(marker, { force: true }); f.write({ packages: [entry] });
    assert.equal(seed(f).seeded, false); assert.deepEqual(f.read().packages, [entry]);
  }
});
test('previous plugin state and project package prevent reinstallation', t => {
  const f = fixture(t); fs.mkdirSync(path.join(f.agentDir, 'pi-paseo'));
  fs.writeFileSync(path.join(f.agentDir, 'pi-paseo/state.json'), '{"enabled":false}');
  assert.equal(seed(f).seeded, false); assert.equal(fs.existsSync(f.file), false);
  fs.rmSync(path.join(f.agentDir, 'pi-paseo'), { recursive: true });
  fs.mkdirSync(path.join(f.home, '.pi'));
  fs.writeFileSync(path.join(f.home, '.pi/settings.json'), JSON.stringify({ packages: [{ source: bundle, extensions: [] }] }));
  assert.equal(seed(f).seeded, false);
});
test('corrupt settings fail closed without marker or data loss', t => {
  const f = fixture(t); fs.writeFileSync(f.file, '{broken');
  assert.throws(() => seed(f)); assert.equal(fs.readFileSync(f.file, 'utf8'), '{broken');
  assert.equal(fs.existsSync(path.join(f.agentDir, 'pi-paseo/image-seed.json')), false);
});
test('explicit image opt-out and symlink settings remain untouched', t => {
  const f = fixture(t);
  assert.equal(seed({ ...f, seedEnabled: false }).reason, 'image-setup-disabled');
  assert.equal(fs.existsSync(f.file), false);
  const target = path.join(f.agentDir, 'user-settings.json'); fs.writeFileSync(target, '{"packages":[]}');
  fs.symlinkSync(target, f.file); assert.throws(() => seed(f));
  assert.equal(fs.lstatSync(f.file).isSymbolicLink(), true);
  assert.equal(fs.readFileSync(target, 'utf8'), '{"packages":[]}');
});
test('boot respects service pause; disable, re-enable, remove and reinstall reconcile once; exit does not persist stop', async () => {
  const calls = []; let current = { root: '/fixture', enabled: true, api: { lifecycle: async input => calls.push(input.action) } };
  const stop = await startLifecycle({ load: async () => current, intervalMs: 5, stop: async () => calls.push('exit') });
  const tick = () => new Promise(resolve => setTimeout(resolve, 30));
  try {
    await tick(); assert.deepEqual(calls, ['restore']);
    current = { ...current, enabled: false }; await tick(); assert.deepEqual(calls, ['restore', 'disable']);
    current = { ...current, enabled: true }; await tick(); assert.deepEqual(calls, ['restore', 'disable', 'enable']);
    const saved = current; current = null; await tick(); assert.equal(calls.at(-1), 'disable');
    current = saved; await tick(); assert.equal(calls.at(-1), 'enable');
  } finally { await stop(); }
  assert.equal(calls.at(-1), 'exit'); assert.ok(!calls.includes('stop'));
});

// --- Pairing links: the official site of the selected target, nothing else ---
const OFFER = 'eyJ2IjoyLCJzZXJ2ZXJJZCI6ImZpeHR1cmUifQ'; // base64url, the alphabet of the real offers
const origins = { paseo: 'https://app.paseo.sh', woowtech: 'https://smart.woowtech.io', apporo: 'https://smart.apporo.ai' };
const officialLink = target => `${origins[target]}/#offer=${OFFER}`;
test('each target accepts exactly https://<its origin>/#offer=<base64url> and refuses everything else', () => {
  for (const [target, origin] of Object.entries(origins)) {
    const host = new URL(origin).host;
    assert.equal(pairUrl(officialLink(target), target), officialLink(target));
    assert.equal(pairUrl(`${origin}/#offer=abc_DEF-123`, target), `${origin}/#offer=abc_DEF-123`);
    const invalid = [
      // another host, scheme, port or credentials
      `${origin}.evil.test/#offer=x`, `https://evil.${host}/#offer=x`, `https://${host}.evil.test/#offer=x`, `${origin}:444/#offer=x`, `${origin}:443/#offer=x`,
      origin.replace('https://', 'http://') + '/#offer=x', origin.replace('https://', 'HTTPS://') + '/#offer=x', origin.toUpperCase() + '/#offer=x',
      origin.replace('https://', 'https://user@') + '/#offer=x', origin.replace('https://', 'https://user:secret@') + '/#offer=x',
      `https://${host}∕evil.test/#offer=x`, `https://ａ${host.slice(1)}/#offer=x`,
      `https://${host}./#offer=x`, `https://${host.toUpperCase()}/#offer=x`, `https://${host[0].toUpperCase()}${host.slice(1)}/#offer=x`,
      `//${host}/#offer=x`, `javascript:alert(1)`, 'data:text/html,x',
      // another path, query or fragment
      `${origin}/welcome#offer=x`, `${origin}/pair#offer=x`, `${origin}//#offer=x`, `${origin}/?redirect=evil#offer=x`,
      `${origin}/#unknown=x`, `${origin}/#offer=`, `${origin}/#`, `${origin}/`, origin, `${origin}/#offer=x&next=evil`, `${origin}/#offer=x/y`,
      `${origin}/#offer=bad!`, `${origin}/#offer=a=b`, `${origin}/#offer=x%20y`, `${origin}/#offer=é`,
      // whitespace, control characters and backslashes
      `${origin}/#offer=x\n`, `${origin}/#offer=bad\nvalue`, `${origin}/#offer=bad\\value`, ` ${origin}/#offer=x`, `${origin}/#offer=x `, `${origin}/#offer=x\0`,
      // the retired bundled client, with or without the Ingress prefix
      '/paseo-web/#offer=x', '/paseo-web/welcome#offer=x', '/api/hassio_ingress/fixture01234567890123/paseo-web/welcome#offer=x', '#offer=x', '',
    ];
    for (const value of invalid) assert.throws(() => pairUrl(value, target), { code: 'PAIRING_ORIGIN_INVALID' }, JSON.stringify(value));
    for (const value of [null, undefined, 42, {}, [officialLink(target)]]) assert.throws(() => pairUrl(value, target), { code: 'PAIRING_ORIGIN_INVALID' }, String(value));
    for (const other of Object.keys(origins).filter(id => id !== target)) assert.throws(() => pairUrl(officialLink(other), target), { code: 'PAIRING_ORIGIN_INVALID' }, `${other} link for ${target}`);
  }
  assert.equal(pairUrl(officialLink('paseo')), officialLink('paseo'), 'Paseo remains the default target');
  assert.throws(() => pairUrl(officialLink('paseo'), 'custom'), { code: 'INVALID_TARGET' });
  assert.throws(() => pairUrl(officialLink('paseo'), '__proto__'), { code: 'INVALID_TARGET' });
});
test('the fixed target table has no local path: no add-on route can receive pairing material', () => {
  assert.deepEqual(ingressModule.connectionTargets.map(({ id, appUrl }) => [id, appUrl]), Object.entries(origins));
  for (const name of ['ingressResponse', 'ingressCacheUsage']) assert.equal(name in ingressModule, false, `${name} served the retired client`);
  assert.equal('prepareImage' in lifecycleModule, false);
});

// --- The bridge: status shape, forwarding and refusals ---
// Shaped like the status() of Agent Connect 0.1.23 and later: no webClient, settings.agentCollaboration (0.1.22+).
function modernStatus(overrides = {}) {
  return { installed: true, version: 'daemon-fixture', enabled: true, phase: 'ready', daemon: { running: true, reachable: true, pid: 4242 },
    providers: [{ provider: 'claude', status: 'ready', chatVerified: true, modes: [{ id: 'default', label: 'Default', secret: 'never-project-this' }], launcher: { command: 'never-project-this' } }],
    openUrl: 'https://app.paseo.sh/', setupUrl: '/paseo/setup', agentCollaboration: true,
    settings: { name: 'Private display label', target: 'paseo', agentCollaboration: true }, selectedTarget: 'paseo', activeTarget: 'paseo', configurationPending: false,
    connectionTargets: Object.entries(origins).map(([id, appUrl]) => ({ id, label: id, appUrl: 'https://untrusted.test' + appUrl.slice(7) })),
    state: { installationId: 'never-project-this' }, token: 'never-project-this', onboardingSessionId: 'legacy-id', ...overrides };
}
function fakePlugin({ status = modernStatus, pair, saveConfig = true } = {}) {
  const calls = [];
  const api = {
    status: async () => status(), pair: pair || (async () => { calls.push('pair'); return { target: 'paseo', url: officialLink('paseo') }; }),
    lifecycle: async input => calls.push(input), listModels: async () => ({ models: [{ id: 'test', secret: 'never-project-this' }] }),
  };
  if (saveConfig) api.saveConfig = async input => { calls.push(input); };
  const plugin = { enabled: true, version: 'fixture', api };
  return { calls, plugin, api, bridge: createPaseoBridge(async () => plugin) };
}
const SNAPSHOT_KEYS = ['activeTarget', 'configurationPending', 'connectionTargets', 'enabled', 'installed', 'phase', 'providers', 'running', 'selectedTarget', 'settings', 'targetSelectionAvailable', 'version'];
test('status without webClient projects exactly the known fields: no web state, no agentCollaboration, no secrets', async () => {
  const f = fakePlugin();
  const status = await f.bridge.read();
  assert.deepEqual(Object.keys(status).sort(), SNAPSHOT_KEYS);
  assert.deepEqual(status.settings, { target: 'paseo' });
  assert.equal(status.running, true); assert.equal(status.version, 'fixture'); assert.equal(status.targetSelectionAvailable, true);
  assert.deepEqual(status.providers, [{ provider: 'claude', status: 'ready', chatVerified: true, modes: [{ id: 'default', label: 'Default' }] }]);
  assert.deepEqual(status.connectionTargets.map(({ id, appUrl }) => [id, appUrl]), Object.entries(origins), 'origins come from the add-on, never from the plugin');
  const text = JSON.stringify(status);
  for (const secret of ['never-project-this', 'untrusted.test', 'Private display label', 'agentCollaboration', 'webClient', 'webReady', 'webVersion', 'paseo-web', 'onboarding']) assert.ok(!text.includes(secret), secret);
  // A status from before 0.1.22 (no agentCollaboration) and one that still carries a webClient (0.1.9-0.1.22) read the same way.
  for (const old of [modernStatus({ agentCollaboration: undefined, settings: { target: 'paseo' } }), modernStatus({ webClient: { ready: false, version: '0.13.0-woow.1' } })]) {
    const legacy = await fakePlugin({ status: () => old }).bridge.read();
    assert.deepEqual(Object.keys(legacy).sort(), SNAPSHOT_KEYS); assert.equal(legacy.running, true);
  }
});
test('bridge forwards lifecycle, refuses disabled packages and has no web client entry point', async () => {
  const f = fakePlugin();
  assert.deepEqual(await f.bridge.act({ action: 'models', provider: 'claude' }), { models: [{ id: 'test', label: 'test' }] });
  await f.bridge.act({ action: 'start' }); assert.equal(f.calls[0].action, 'enable');
  await f.bridge.act({ action: 'stop' }); assert.equal(f.calls[1].action, 'stop');
  await assert.rejects(f.bridge.act({ action: 'web' }), { code: 'INVALID_ACTION' });
  assert.equal('web' in f.bridge, false); assert.equal('web' in f.api, false, 'Agent Connect 0.1.23 has no web() in its host API');
  f.plugin.enabled = false;
  assert.equal((await f.bridge.read()).phase, 'disabled');
  await assert.rejects(f.bridge.act({ action: 'pair' }), { code: 'PLUGIN_UNAVAILABLE' });
});
test('pairing returns the official link of the saved target and refuses any other origin or the retired client path', async () => {
  for (const target of Object.keys(origins)) {
    const f = fakePlugin({ status: () => modernStatus({ settings: { target }, selectedTarget: target, activeTarget: target }), pair: async () => ({ target, url: officialLink(target) }) });
    assert.deepEqual(await f.bridge.act({ action: 'pair' }), { target, url: officialLink(target) });
    assert.deepEqual(await f.bridge.act({ action: 'pair', target }), { target, url: officialLink(target) });
    for (const url of [officialLink(Object.keys(origins).find(id => id !== target)), '/paseo-web/#offer=x', '/paseo-web/welcome#offer=x', `${origins[target]}/welcome#offer=x`, `${origins[target]}/#offer=bad!`]) {
      f.api.pair = async () => ({ target, url });
      await assert.rejects(f.bridge.act({ action: 'pair' }), { code: 'PAIRING_ORIGIN_INVALID' }, url);
    }
  }
});
test('the page can only save the target: agentCollaboration and every other field are refused and never forwarded', async () => {
  const state = modernStatus();
  const f = fakePlugin({ status: () => state });
  f.api.saveConfig = async input => { f.calls.push(input); state.settings = { ...state.settings, target: input.target }; };
  for (const body of [{ action: 'save', target: 'apporo', agentCollaboration: true }, { action: 'save', target: 'apporo', agentCollaboration: false },
    { action: 'save', agentCollaboration: true }, { action: 'save', target: 'apporo', name: 'x' }, { action: 'save', target: 'apporo', settings: { agentCollaboration: true } },
    { action: 'save', target: 'apporo', relayUrl: 'https://evil.test' }, JSON.parse('{"action":"save","target":"apporo","__proto__":{"agentCollaboration":true}}')]) {
    await assert.rejects(f.bridge.act(body), { code: 'INVALID_SETTINGS' }, JSON.stringify(body));
  }
  for (const body of [{ action: 'save', target: 'custom' }, { action: 'save', target: { toString: () => 'apporo' } }]) await assert.rejects(f.bridge.act(body), { code: 'INVALID_TARGET' });
  assert.deepEqual(f.calls, [], 'nothing reached the plugin');
  await f.bridge.act({ action: 'save', target: 'apporo' });
  assert.deepEqual(f.calls, [{ target: 'apporo' }], 'exactly the target is forwarded, so the plugin keeps its saved agentCollaboration');
  assert.equal(state.settings.agentCollaboration, true);
});
test('an older package without target support pairs through the official site only and cannot silently accept a new target', async () => {
  const old = () => ({ phase: 'ready', daemon: { running: true }, providers: [], onboardingSessionId: 'legacy-id' });
  const f = fakePlugin({ status: old, saveConfig: false });
  const state = await f.bridge.read(); assert.equal(state.selectedTarget, 'paseo'); assert.equal(state.targetSelectionAvailable, false);
  await assert.rejects(f.bridge.act({ action: 'save', target: 'woowtech' }), { code: 'TARGET_SELECTION_UNSUPPORTED' });
  assert.deepEqual(await f.bridge.act({ action: 'pair' }), { target: 'paseo', url: officialLink('paseo') });
  // What such a package returned for its own bundled client is no longer served by this add-on.
  f.api.pair = async () => ({ url: '/paseo-web/#fixture' });
  await assert.rejects(f.bridge.act({ action: 'pair' }), { code: 'PAIRING_ORIGIN_INVALID' });
});
function targetedPlugin() {
  const calls = [];
  const state = modernStatus({ settings: { target: 'paseo', name: 'Private display label', secret: 'private-field' }, configurationPending: false,
    connectionTargets: ['paseo', 'woowtech', 'apporo'].map(id => ({ id, appUrl: 'https://untrusted.test', secret: 'private-field' })), providers: [] });
  const plugin = { enabled: true, version: 'candidate', api: {
    status: async () => state,
    saveConfig: async input => { calls.push(input); state.settings.target = input.target; state.configurationPending = state.daemon.running; },
    pair: async () => { calls.push('pair'); return { target: state.settings.target, url: officialLink(state.settings.target) }; },
    lifecycle: async input => { calls.push(input.action); state.daemon.running = input.action === 'enable'; if (state.daemon.running) { state.activeTarget = state.settings.target; state.configurationPending = false; } },
  } };
  return { state, calls, plugin, bridge: createPaseoBridge(async () => plugin) };
}
test('target save is strict, retains name in the package, projects only known fields and waits for restart', async () => {
  const f = targetedPlugin();
  const status = await f.bridge.read();
  assert.deepEqual(status.settings, { target: 'paseo' }); assert.equal(status.targetSelectionAvailable, true);
  assert.ok(!JSON.stringify(status).includes('private-field')); assert.ok(!JSON.stringify(status).includes('untrusted.test'));
  for (const body of [{ action: 'save', target: 'custom' }, { action: 'save' }, { action: 'save', target: 'apporo', relayUrl: 'https://evil.test' }]) {
    await assert.rejects(f.bridge.act(body), error => ['INVALID_TARGET', 'INVALID_SETTINGS'].includes(error.code));
  }
  assert.deepEqual(f.calls, []);
  const saved = await f.bridge.act({ action: 'save', target: 'apporo' });
  assert.equal(saved.configurationPending, true); assert.equal(saved.selectedTarget, 'apporo');
  assert.equal(f.state.settings.name, 'Private display label'); assert.deepEqual(f.calls, [{ target: 'apporo' }]);
  await assert.rejects(f.bridge.act({ action: 'pair', target: 'apporo' }), { code: 'CONFIGURATION_PENDING' });
  assert.deepEqual(f.calls, [{ target: 'apporo' }]);
  await f.bridge.act({ action: 'stop' }); await f.bridge.act({ action: 'start' });
  assert.deepEqual(await f.bridge.act({ action: 'pair', target: 'apporo' }), { target: 'apporo', url: 'https://smart.apporo.ai/#offer=' + OFFER });
});
test('pair receipts bind to the saved target and reject concurrent settings changes or a foreign origin', async () => {
  const f = targetedPlugin();
  f.state.settings.target = 'woowtech'; f.state.activeTarget = 'woowtech';
  await assert.rejects(f.bridge.act({ action: 'pair', target: 'apporo' }), { code: 'CONFIGURATION_PENDING' });
  assert.deepEqual(f.calls, []);
  f.plugin.api.pair = async () => ({ target: 'apporo', url: 'https://smart.apporo.ai/#offer=private' });
  await assert.rejects(f.bridge.act({ action: 'pair' }), { code: 'CONFIGURATION_PENDING' });
  f.plugin.api.pair = async () => ({ target: 'woowtech', url: 'https://smart.apporo.ai/#offer=private' });
  await assert.rejects(f.bridge.act({ action: 'pair' }), { code: 'PAIRING_ORIGIN_INVALID' });
  f.plugin.api.pair = async () => { f.state.settings.target = 'apporo'; return { target: 'woowtech', url: 'https://smart.woowtech.io/#offer=private' }; };
  await assert.rejects(f.bridge.act({ action: 'pair' }), { code: 'CONFIGURATION_PENDING' });
});

// --- The private HTTP surface ---
async function listen(t, options) {
  const server = createServer(options);
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  return `http://127.0.0.1:${server.address().port}`;
}
test('private bridge protects the API, hands out the official pairing link and limits request bodies', async t => {
  const f = fakePlugin();
  const base = await listen(t, { bridge: f.bridge, directory: panelDirectory });
  const prefix = '/api/hassio_ingress/fixture01234567890123';
  const page = await fetch(base + '/paseo/setup', { headers: { 'X-Ingress-Path': prefix } });
  const html = await page.text();
  assert.ok(html.includes(prefix + '/paseo/app.js'));
  assert.match(html, /<a id="open" href="https:\/\/app\.paseo\.sh\/" target="_blank" rel="noopener noreferrer">/);
  assert.match(html, /<a id="pair-link" hidden target="_blank" rel="noopener noreferrer">/);
  assert.ok(!html.includes('paseo-web'), 'the page links no local web client');
  assert.match(page.headers.get('content-security-policy'), /default-src 'none'.*frame-ancestors 'self'/);
  const token = html.match(/name="paseo-token" content="([a-f0-9]+)"/)[1];
  const headers = { 'X-Paseo-Token': token, 'Content-Type': 'application/json', 'X-Ingress-Path': prefix };
  assert.equal((await fetch(base + '/api/paseo')).status, 403);
  const read = await fetch(base + '/api/paseo', { headers }); assert.equal(read.status, 200);
  assert.deepEqual(Object.keys(await read.json()).sort(), SNAPSHOT_KEYS);
  for (const extra of [{ Origin: 'https://evil.test' }, { 'Sec-Fetch-Site': 'cross-site' }, { 'Sec-Fetch-Site': 'same-site' }]) assert.equal((await fetch(base + '/api/paseo', { headers: { ...headers, ...extra } })).status, 403);
  for (const [body, status] of [['null', 400], ['{invalid', 400], ['x'.repeat(8193), 413]]) assert.equal((await fetch(base + '/api/paseo', { method: 'POST', headers, body })).status, status);
  const paired = await (await fetch(base + '/api/paseo', { method: 'POST', headers, body: '{"action":"pair"}' })).json();
  assert.deepEqual(paired, { target: 'paseo', url: officialLink('paseo') });
  assert.deepEqual(f.calls, ['pair']);
  // Only the target can be saved over HTTP; a smuggled agentCollaboration never reaches the plugin.
  for (const body of ['{"action":"save","target":"apporo","agentCollaboration":true}', '{"action":"save","target":"apporo","__proto__":{"agentCollaboration":true}}']) {
    const response = await fetch(base + '/api/paseo', { method: 'POST', headers, body });
    assert.equal(response.status, 400); assert.deepEqual(await response.json(), { error: { code: 'INVALID_SETTINGS' } });
  }
  assert.deepEqual(f.calls, ['pair']);
  await fetch(base + '/api/paseo', { method: 'POST', headers, body: '{"action":"save","target":"apporo"}' });
  assert.deepEqual(f.calls, ['pair', { target: 'apporo' }]);
});
test('the bundled client is gone: every /paseo-web route is a 404 that never reaches the plugin', async t => {
  const f = fakePlugin();
  const base = await listen(t, { bridge: f.bridge, directory: panelDirectory });
  const prefix = '/api/hassio_ingress/fixture01234567890123';
  const token = (await (await fetch(base + '/paseo/setup', { headers: { 'X-Ingress-Path': prefix } })).text()).match(/name="paseo-token" content="([a-f0-9]+)"/)[1];
  for (const headers of [{}, { 'X-Paseo-Token': token, 'X-Ingress-Path': prefix }]) {
    for (const route of ['/paseo-web', '/paseo-web/', '/paseo-web/welcome', '/paseo-web/settings', '/paseo-web/hosts/fixture', '/paseo-web/_expo/static/js/web/index-0123456789abcdef.js', '/paseo-web/assets/icon.png']) {
      for (const method of ['GET', 'HEAD', 'POST']) {
        const response = await fetch(base + route, { method, headers });
        assert.equal(response.status, 404, `${method} ${route}`);
        if (method === 'GET') assert.deepEqual(await response.json(), { error: { code: 'NOT_FOUND' } });
        else await response.arrayBuffer();
      }
    }
  }
  assert.deepEqual(f.calls, [], 'no route consulted the plugin');
});
test('the Ingress prefix is templated into the page only when it is a Supervisor Ingress path', async t => {
  // ingressPrefix() is the only thing between X-Ingress-Path and the HTML: nginx whitelists it too, this is the second line.
  const f = fakePlugin();
  const base = await listen(t, { bridge: f.bridge, directory: panelDirectory });
  const good = '/api/hassio_ingress/fixture01234567890123';
  const meta = html => html.match(/<meta name="ingress-prefix" content="([^"]*)">/)?.[1];
  const page = async value => (await fetch(base + '/paseo/setup', { headers: value === undefined ? {} : { 'X-Ingress-Path': value } })).text();
  assert.equal(meta(await page(good)), good);
  assert.equal(meta(await page()), '', 'no header, no prefix');
  for (const hostile of ['"><script>bad</script>', '/api/hassio_ingress/short', `/api/hassio_ingress/${'a'.repeat(129)}`, '//evil.test',
    'https://evil.test/api/hassio_ingress/fixture01234567890123', `${good}/../x`, `${good}?x=1`, `${good}"onload="bad`, `${good}\\`]) {
    const html = await page(hostile);
    assert.equal(meta(html), '', hostile);
    assert.ok(!html.includes('<script>bad') && !html.includes('onload="bad') && !html.includes('evil.test'), `${hostile} reached the page`);
    assert.ok(html.includes('src="/paseo/app.js"') && html.includes('href="/paseo/style.css"'), `${hostile}: the page falls back to unprefixed paths`);
  }
});
test('retired and missing static routes are 404; only listed codes reach the page, Node and system codes stay in the log', async t => {
  const logged = []; t.mock.method(console, 'error', message => { logged.push(String(message)); });
  let failure;
  const bridge = { read: async () => { throw failure; }, act: async () => { throw failure; } };
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ha-paseo-static-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  fs.copyFileSync(path.join(panelDirectory, 'index.html'), path.join(directory, 'index.html'));
  const base = await listen(t, { bridge, directory });
  for (const route of ['/paseo/launcher.js', '/paseo/app.js', '/paseo-web/', '/paseo-web/settings']) {
    const response = await fetch(base + route);
    assert.equal(response.status, 404, route); assert.deepEqual(await response.json(), { error: { code: 'NOT_FOUND' } });
  }
  const token = (await (await fetch(base + '/paseo/setup')).text()).match(/name="paseo-token" content="([a-f0-9]+)"/)[1];
  const headers = { 'X-Paseo-Token': token, 'Content-Type': 'application/json' };
  for (const [error, status, code] of [
    [Object.assign(new Error('ENOENT: no such file, open /data/pi-agent/private-file'), { code: 'ENOENT' }), 503, 'PASEO_FAILED'],
    [Object.assign(new Error('EACCES: permission denied'), { code: 'EACCES' }), 503, 'PASEO_FAILED'],
    [Object.assign(new Error('Cannot find module /opt/woow/private-module'), { code: 'ERR_MODULE_NOT_FOUND' }), 503, 'PASEO_FAILED'],
    [Object.assign(new Error('web'), { code: 'WEB_CLIENT_NOT_READY' }), 503, 'PASEO_FAILED'],
    [Object.assign(new Error('daemon'), { code: 'DAEMON_UNREACHABLE' }), 503, 'DAEMON_UNREACHABLE'],
    [Object.assign(new Error('disabled'), { code: 'PLUGIN_UNAVAILABLE' }), 409, 'PLUGIN_UNAVAILABLE'],
    [Object.assign(new Error('action'), { code: 'INVALID_ACTION' }), 400, 'INVALID_ACTION'],
  ]) {
    failure = error;
    for (const [route, init] of [['/api/paseo', { headers }], ['/api/paseo', { method: 'POST', headers, body: '{"action":"pair"}' }]]) {
      const response = await fetch(base + route, init);
      assert.equal(response.status, status, `${route} ${code}`); assert.deepEqual(await response.json(), { error: { code } });
    }
  }
  assert.ok(['ENOENT', 'EACCES', 'ERR_MODULE_NOT_FOUND', 'WEB_CLIENT_NOT_READY'].every(value => logged.some(line => line.includes(`(${value})`))), logged.join('\n'));
  assert.ok(logged.every(line => !/private-(file|module)/.test(line)), 'the add-on log keeps the code, never the message');
});

// --- nginx and the shipped files ---
/** The `location` blocks that hold no nested braces, in file order (the catch-all holds the JS shim and is checked apart). */
const nginxLocations = conf => [...conf.matchAll(/location\s+(~\*?|\^~|=)?\s*(\S+)\s*\{([^{}]*)\}/g)].map(([, modifier = '', pattern, body]) => ({ modifier, pattern, body }));
/** nginx's choice: the first matching regex location in file order, else the catch-all prefix `/`. */
const nginxPick = (locations, request) => locations.find(item => item.modifier === '~' && new RegExp(item.pattern).test(request))?.body ?? 'location /';
test('nginx answers the retired /paseo-web paths itself, and only the settings page and its API reach the Paseo bridge', () => {
  const conf = fs.readFileSync(path.join(root, 'rootfs/etc/nginx/nginx.conf'), 'utf8');
  const locations = nginxLocations(conf);
  assert.match(conf, /^\s*location \/ \{/m, 'the catch-all that serves Pi Web is still there');
  assert.equal((conf.match(/\{/g) || []).length, (conf.match(/\}/g) || []).length, 'balanced braces');
  const serverHead = conf.slice(conf.indexOf('server {'), conf.indexOf('location', conf.indexOf('server {')));
  assert.match(serverHead, /listen 172\.30\.32\.1:30142[^;]*;\s*allow 172\.30\.32\.2;\s*deny all;/, 'the Supervisor-only rules sit at server level, before every location');
  assert.equal((conf.match(/^\s*(?:allow|deny)\s/gm) || []).length, 2, 'no location adds or relaxes an allow/deny');
  const paseo = nginxPick(locations, '/paseo/setup');
  assert.match(paseo, /proxy_pass http:\/\/unix:\/data\/pi-agent\/paseo-ha\.sock;/);
  for (const request of ['/paseo', '/paseo/', '/paseo/setup', '/paseo/app.js', '/paseo/style.css', '/api/paseo']) assert.equal(nginxPick(locations, request), paseo, request);
  const retired = locations.filter(item => /paseo-web/.test(item.pattern));
  assert.equal(retired.length, 1); assert.equal(retired[0].modifier, '~');
  assert.equal(retired[0].body.replace(/\s+/g, ' ').trim(), 'return 404;', 'it only answers: nothing is proxied, nothing is relaxed');
  for (const request of ['/paseo-web', '/paseo-web/', '/paseo-web/welcome', '/paseo-web/settings', '/paseo-web/_expo/static/js/web/index-0123456789abcdef.js']) {
    assert.equal(nginxPick(locations, request), retired[0].body, `${request} is answered by nginx`);
  }
  // Near misses are neither the retired path nor the bridge; they keep their usual route.
  for (const request of ['/paseo-webx', '/paseox', '/api/paseo-web', '/api/paseox', '/']) assert.ok(![paseo, retired[0].body].includes(nginxPick(locations, request)), request);
  assert.match(nginxPick(locations, '/omnigent'), /omnigent-ha\.sock/);
});
test('nothing the image ships or builds refers to the retired bundled web client', () => {
  const walk = directory => fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? walk(path.join(directory, entry.name)) : [path.join(directory, entry.name)]);
  const files = [...walk(path.join(root, 'rootfs')), path.join(root, 'Dockerfile'), path.join(root, 'patches/build-paseo.mjs')];
  assert.ok(files.length > 20);
  for (const file of files) {
    let text = fs.readFileSync(file, 'utf8');
    // The one deliberate mention: nginx's own 404 for the retired path (and the comment that explains it).
    if (file.endsWith('nginx.conf')) text = text.replace(/^\s*#.*$/gm, '').replace(/location ~ \^\/paseo-web\(\/\|\$\) \{\s*return 404;\s*\}/, '');
    assert.doesNotMatch(text, /paseo-web|web-client|webClient|WEB_CLIENT|prepareImage|serveWebClient|ensureWebClient/, path.relative(root, file));
  }
});
