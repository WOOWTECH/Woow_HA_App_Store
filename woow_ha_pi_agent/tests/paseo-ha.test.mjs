import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { seed, startLifecycle } from '../rootfs/usr/local/lib/pi-paseo-ha/lifecycle.mjs';
import { createPaseoBridge } from '../rootfs/usr/local/lib/pi-paseo-ha/bridge.mjs';
import { createServer } from '../rootfs/usr/local/lib/pi-paseo-ha/server.mjs';
import { gunzipSync } from 'node:zlib';
import { ingressResponse, pairUrl, ingressCacheUsage } from '../rootfs/usr/local/lib/pi-paseo-ha/ingress.mjs';

const root = path.resolve(import.meta.dirname, '..');
const bundle = '/opt/woow/pi-paseo-plugin';
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

test('Ingress pair links cannot leak to an external origin or accept executable input', () => {
  const prefix = '/api/hassio_ingress/fixture01234567890123';
  assert.equal(pairUrl('/paseo-web/#fixture', prefix), prefix + '/paseo-web/#fixture');
  for (const value of ['https://evil.test/#secret', '//evil.test', '/paseo-web/pair#x', '/paseo-web/#bad\nvalue', '/paseo-web/#bad\\value']) assert.throws(() => pairUrl(value, prefix));
  assert.equal(pairUrl('/paseo-web/#fixture', '"><script>'), '/paseo-web/#fixture');
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
test('the compiled router base and dynamic assets follow each Ingress session, never cached across prefixes', async () => {
  const source = 'const base="/paseo-web";const chunk="/paseo-web/_expo/static/index.js";';
  for (const prefix of ['/api/hassio_ingress/fixture01234567890123', '/api/hassio_ingress/different012345678901']) {
    const response = await ingressResponse(new Response(source, { headers: { 'Content-Type': 'text/javascript', 'Content-Length': '12', 'Cache-Control': 'immutable' } }), prefix);
    const text = await response.text();
    assert.ok(text.includes('base="' + prefix + '/paseo-web"')); assert.ok(text.includes(prefix + '/paseo-web/_expo'));
    assert.equal(Number(response.headers.get('content-length')), Buffer.byteLength(text)); assert.equal(response.headers.get('cache-control'), 'private, no-store');
    assert.ok(response.headers.get('vary').includes('X-Ingress-Path'));
  }
});
test('hashed assets gzip after prefix rewrite, validate GET/HEAD/304 per representation and bound cache', async () => {
  const pathname = '/paseo-web/_expo/static/js/web/index-0123456789abcdef.js';
  const source = 'const base="/paseo-web";'.repeat(3000);
  const response = () => new Response(source, { headers: { 'Content-Type': 'text/javascript' } });
  const prefix = '/api/hassio_ingress/compression0123456789';
  const options = { pathname, acceptEncoding: 'gzip, deflate, br' };
  const compressed = await ingressResponse(response(), prefix, 'GET', options);
  const bytes = Buffer.from(await compressed.arrayBuffer());
  assert.equal(compressed.headers.get('content-encoding'), 'gzip');
  assert.equal(Number(compressed.headers.get('content-length')), bytes.length);
  assert.ok(bytes.length < source.length / 10);
  assert.equal(gunzipSync(bytes).toString(), source.replaceAll('/paseo-web', prefix + '/paseo-web'));
  assert.equal(compressed.headers.get('cache-control'), 'private, max-age=31536000, immutable');
  const head = await ingressResponse(response(), prefix, 'HEAD', options);
  assert.equal(head.headers.get('etag'), compressed.headers.get('etag'));
  assert.equal(head.headers.get('content-length'), compressed.headers.get('content-length'));
  assert.equal(head.headers.get('vary'), 'Accept-Encoding, X-Ingress-Path'); assert.equal(await head.text(), '');
  const conditional = await ingressResponse(response(), prefix, 'GET', { ...options, ifNoneMatch: head.headers.get('etag') });
  assert.equal(conditional.status, 304); assert.equal(await conditional.text(), ''); assert.equal(conditional.headers.get('content-length'), null);
  const plain = await ingressResponse(response(), prefix, 'GET', { ...options, acceptEncoding: 'gzip;q=0, *;q=1' });
  assert.equal(plain.headers.get('content-encoding'), null); assert.notEqual(plain.headers.get('etag'), head.headers.get('etag'));
  assert.equal(Number(plain.headers.get('content-length')), Buffer.byteLength(await plain.text()));
  for (let i = 0; i < 12; i++) {
    const otherPrefix = `/api/hassio_ingress/cachefixture0123456789${i}`;
    const item = await ingressResponse(response(), otherPrefix, 'GET', options);
    assert.ok(gunzipSync(Buffer.from(await item.arrayBuffer())).toString().includes(otherPrefix));
  }
  const usage = ingressCacheUsage(); assert.ok(usage.entries <= usage.maxEntries); assert.ok(usage.bytes <= usage.maxBytes);
  const html = await ingressResponse(new Response('<html>/paseo-web</html>', { headers: { 'Content-Type': 'text/html' } }), prefix, 'GET', options);
  assert.equal(html.headers.get('cache-control'), 'private, no-store'); assert.equal(html.headers.get('etag'), null);
});
function fakePlugin() {
  const calls = [];
  const plugin = { enabled: true, version: '0.1.13', api: {
    status: async () => ({ phase: 'ready', daemon: { running: true }, webClient: { ready: true, version: '0.13.0-woow.1' }, providers: [{ provider: 'claude', status: 'ready' }], onboardingSessionId: 'legacy-id', token: 'never-project-this' }),
    pair: async () => { calls.push('pair'); return { url: '/paseo-web/#fixture' }; },
    lifecycle: async input => calls.push(input), listModels: async () => ({ models: [{ id: 'test', secret: 'never-project-this' }] }),
    web: async () => new Response('<script src="/paseo-web/main.js"></script>', { headers: { 'Content-Type': 'text/html' } }),
  } };
  return { calls, plugin, bridge: createPaseoBridge(async () => plugin) };
}
test('bridge projects safe fields, forwards lifecycle and refuses disabled packages', async () => {
  const f = fakePlugin();
  assert.ok(!JSON.stringify(await f.bridge.read()).includes('never-project-this'));
  assert.equal('onboardingUrl' in await f.bridge.read(), false);
  assert.deepEqual(await f.bridge.act({ action: 'models', provider: 'claude' }), { models: [{ id: 'test', label: 'test' }] });
  await f.bridge.act({ action: 'start' }); assert.equal(f.calls[0].action, 'enable');
  await f.bridge.act({ action: 'stop' }); assert.equal(f.calls[1].action, 'stop');
  f.plugin.enabled = false;
  await assert.rejects(f.bridge.act({ action: 'pair' }), { code: 'PLUGIN_UNAVAILABLE' });
  assert.equal((await f.bridge.web(new Request('http://localhost/paseo-web'))).status, 409);
});
test('private bridge protects API, rewrites web and pairing under HA prefix, and limits request bodies', async t => {
  const f = fakePlugin();
  const server = createServer({ bridge: f.bridge, directory: path.join(root, 'rootfs/usr/local/share/pi-paseo-ha') });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const prefix = '/api/hassio_ingress/fixture01234567890123';
  const html = await (await fetch(base + '/paseo/setup', { headers: { 'X-Ingress-Path': prefix } })).text();
  assert.ok(html.includes(prefix + '/paseo/app.js'));
  const token = html.match(/name="paseo-token" content="([a-f0-9]+)"/)[1];
  const headers = { 'X-Paseo-Token': token, 'Content-Type': 'application/json', 'X-Ingress-Path': prefix };
  assert.equal((await fetch(base + '/api/paseo')).status, 403);
  assert.equal((await fetch(base + '/api/paseo', { headers })).status, 200);
  for (const extra of [{ Origin: 'https://evil.test' }, { 'Sec-Fetch-Site': 'cross-site' }, { 'Sec-Fetch-Site': 'same-site' }]) assert.equal((await fetch(base + '/api/paseo', { headers: { ...headers, ...extra } })).status, 403);
  for (const [body, status] of [['null', 400], ['{invalid', 400], ['x'.repeat(8193), 413]]) assert.equal((await fetch(base + '/api/paseo', { method: 'POST', headers, body })).status, status);
  const paired = await (await fetch(base + '/api/paseo', { method: 'POST', headers, body: '{"action":"pair"}' })).json();
  assert.equal(paired.url, prefix + '/paseo-web/#fixture');
  assert.deepEqual(f.calls, ['pair']);
  const web = await fetch(base + '/paseo-web/hosts/fixture', { headers });
  assert.ok((await web.text()).includes(prefix + '/paseo-web/main.js'));
  assert.equal((await fetch(base + '/paseo-web/', { method: 'POST', headers })).status, 405);
  const head = await fetch(base + '/paseo-web/', { method: 'HEAD', headers });
  assert.equal(head.status, 200); assert.equal(await head.text(), '');
});
