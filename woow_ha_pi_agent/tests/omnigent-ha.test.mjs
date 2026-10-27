import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { seed } from '../rootfs/usr/local/lib/pi-omnigent-ha/lifecycle.mjs';
import { createOmnigentBridge } from '../rootfs/usr/local/lib/pi-omnigent-ha/bridge.mjs';
import { createServer } from '../rootfs/usr/local/lib/pi-omnigent-ha/server.mjs';

const root = path.resolve(import.meta.dirname, '..');
const bundle = '/opt/woow/pi-omnigent-plugin';
function fixture(t) {
  const agentDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ha-omnigent-'));
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
  const marker = path.join(f.agentDir, 'omnigent-plugin/image-seed.json');
  const custom = path.join(f.agentDir, 'custom'); fs.mkdirSync(custom);
  fs.writeFileSync(path.join(custom, 'package.json'), JSON.stringify({ name: '@woowtech/pi-omnigent-plugin' }));
  for (const entry of [{ source: bundle, extensions: [] }, 'git:github.com/WOOWTECH/pi-omnigent-plugin@v0.3.11',
    'git:git@github.com:WOOWTECH/pi-omnigent-plugin.git@v0.3.11', 'npm:@woowtech/pi-omnigent-plugin@0.3.11', custom]) {
    fs.rmSync(marker, { force: true }); f.write({ packages: [entry] });
    assert.equal(seed(f).seeded, false); assert.deepEqual(f.read().packages, [entry]);
  }
});
test('previous plugin state and project package prevent reinstallation', t => {
  const f = fixture(t); fs.mkdirSync(path.join(f.agentDir, 'omnigent-plugin'));
  fs.writeFileSync(path.join(f.agentDir, 'omnigent-plugin/state.json'), '{"enabled":false}');
  assert.equal(seed(f).seeded, false); assert.equal(fs.existsSync(f.file), false);
  fs.rmSync(path.join(f.agentDir, 'omnigent-plugin'), { recursive: true });
  fs.mkdirSync(path.join(f.home, '.pi'));
  fs.writeFileSync(path.join(f.home, '.pi/settings.json'), JSON.stringify({ packages: [{ source: bundle, extensions: [] }] }));
  assert.equal(seed(f).seeded, false);
});
test('corrupt settings fail closed without marker or data loss', t => {
  const f = fixture(t); fs.writeFileSync(f.file, '{broken');
  assert.throws(() => seed(f)); assert.equal(fs.readFileSync(f.file, 'utf8'), '{broken');
  assert.equal(fs.existsSync(path.join(f.agentDir, 'omnigent-plugin/image-seed.json')), false);
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
function fakePlugin() {
  const calls = [];
  const current = { phase: 'needs-login', loginConfirmed: false, server: undefined, host: { id: 'fixture-host', connected: false },
    engines: { pi: { available: true, version: '1.1.0', configured: true } }, verification: {}, secret: 'must-not-leak' };
  const plugin = { version: '0.3.11', lifecycle: async () => ({ active: true }), onboarding: () => ({ sessionId: 'test-session' }),
    runtime: { status: async () => current, catalog: async () => ({ data: { engines: { pi: { ready: true, models: [{ id: 'fixture-model', displayName: 'Fixture' }] } } } }),
      initialize: async input => { calls.push(input); Object.assign(current, { server: input.server, loginConfirmed: true, host: { id: 'fixture-host', connected: true } }); return { ok: true, password: input.password }; },
      verify: async input => { calls.push(input); return { ok: false, phase: 'needs-verification', verification: { pi: { ok: true, reply: 'OMNIGENT_CONNECTION_OK', cleanup: 'stopped', model: input.model } } }; },
      disconnect: async () => { calls.push('disconnect'); return { ok: true }; } } };
  return { plugin, current, calls, bridge: createOmnigentBridge(async () => plugin) };
}
test('fresh credentials go directly to runtime, never DTO or automatic chat verification', async () => {
  const f = fakePlugin(); const view = await f.bridge.act({ action: 'connect', server: 'https://example.test', username: 'test', password: 'private-fixture' });
  assert.deepEqual(f.calls, [{ server: 'https://example.test', username: 'test', password: 'private-fixture', verify: false }]);
  assert.equal(view.operation.ok, true); assert.equal(JSON.stringify(view).includes('private-fixture'), false);
  assert.equal(JSON.stringify(view).includes('must-not-leak'), false); assert.equal(view.engines[2].models[0].id, 'fixture-model');
  assert.equal(view.onboardingUrl, '/?session=test-session');
});
test('model-specific verification is successful even when another engine still needs setup', async () => {
  const f = fakePlugin(); const view = await f.bridge.act({ action: 'verify', engine: 'pi', model: 'fixture-model' });
  assert.deepEqual(f.calls, [{ engine: 'pi', model: 'fixture-model' }]); assert.equal(view.operation.ok, true);
});
test('invalid fields, disabled packages and unconfirmed disconnect cannot mutate runtime', async () => {
  const f = fakePlugin();
  for (const body of [{ action: 'connect', server: 'https://user:pass@example.test', username: 'test', password: 'secret' },
    { action: 'connect', server: 'https://example.test' }, { action: 'verify', engine: 'missing' }, { action: 'verify', model: 'x' }, { action: 'disconnect' }]) await assert.rejects(f.bridge.act(body));
  assert.deepEqual(f.calls, []); f.plugin.lifecycle = async () => ({ active: false });
  await assert.rejects(f.bridge.act({ action: 'disconnect', confirm: true }));
  assert.equal((await f.bridge.read()).active, false);
});
test('private HTTP bridge checks token, body, error redaction and HA prefix for every operation', async t => {
  const f = fakePlugin();
  const server = createServer({ bridge: f.bridge, directory: path.join(root, 'rootfs/usr/local/share/pi-omnigent-ha') });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const prefix = '/api/hassio_ingress/fixture01234567890123';
  f.plugin.lifecycle = async () => ({ active: true, registered: true });
  f.current.enabled = true;
  assert.equal((await fetch(base + '/omnigent/onboarding')).status, 404);
  assert.equal((await fetch(base + '/omnigent/launcher.js')).status, 404);
  assert.deepEqual(f.calls, [], 'removed navigation routes do not initialize or verify');
  const html = await (await fetch(base + '/omnigent', { headers: { 'X-Ingress-Path': prefix } })).text();
  assert.ok(html.includes(`${prefix}/omnigent/app.js`)); assert.ok(!html.includes('__CSRF_TOKEN__'));
  const token = html.match(/name="omnigent-token" content="([a-f0-9]+)"/)[1];
  const headers = { 'X-Omnigent-Token': token, 'Content-Type': 'application/json' };
  assert.equal((await fetch(base + '/api/omnigent')).status, 403);
  assert.equal((await fetch(base + '/api/omnigent', { headers })).status, 200);
  assert.equal((await fetch(base + '/api/omnigent', { headers: { ...headers, 'Sec-Fetch-Site': 'cross-site' } })).status, 403);
  assert.equal((await fetch(base + '/api/omnigent', { headers: { ...headers, 'Sec-Fetch-Site': 'same-site' } })).status, 403);
  assert.equal((await fetch(base + '/api/omnigent', { headers: { ...headers, Origin: 'https://evil.example' } })).status, 403);
  assert.equal((await fetch(base + '/api/omnigent', { headers: { ...headers, Origin: base, 'Sec-Fetch-Site': 'same-origin' } })).status, 200);
  for (const [body, status, contentType] of [['{secret', 400, 'application/json'], ['null', 400, 'application/json'], ['{}', 415, 'text/plain'], ['x'.repeat(8193), 413, 'application/json']]) {
    const response = await fetch(base + '/api/omnigent', { method: 'POST', headers: { ...headers, 'Content-Type': contentType }, body });
    assert.equal(response.status, status); assert.ok(!(await response.text()).includes('secret'));
  }
  const response = await fetch(base + '/api/omnigent', { method: 'POST', headers, body: JSON.stringify({ action: 'connect', server: 'https://example.test', username: '測試帳號', password: 'private-fixture' }) });
  assert.equal(response.status, 200); assert.equal((await response.json()).operation.ok, true);
  assert.equal(f.calls[0].username, '測試帳號');
  assert.equal((await fetch(base + '/omnigent/../../etc/passwd')).status, 404);
  const badHeader = await (await fetch(base + '/omnigent', { headers: { 'X-Ingress-Path': '"><script>bad</script>' } })).text();
  assert.ok(!badHeader.includes('bad</script>'));
});
test('Pi wrapper preserves per-session provider directory across legacy env scripts', t => {
  const f = fixture(t); const cli = path.join(f.agentDir, 'cli.js');
  fs.writeFileSync(cli, 'console.log(process.env.PI_CODING_AGENT_DIR)');
  const envScript = path.join(f.agentDir, 'env.sh'); fs.writeFileSync(envScript, 'export PI_CODING_AGENT_DIR=/container-default\n');
  const source = fs.readFileSync(path.join(root, 'rootfs/usr/local/bin/pi'), 'utf8')
    .replace('/usr/lib/node_modules/@agegr/pi-web/node_modules/@earendil-works/pi-coding-agent/dist/cli.js', cli)
    .replaceAll('/usr/local/bin/pi-agent-env.sh', envScript);
  const wrapper = path.join(f.agentDir, 'pi'); fs.writeFileSync(wrapper, source);
  for (const value of [undefined, '/session/private-provider', '']) {
    const env = { ...process.env }; delete env.PI_CODING_AGENT_DIR;
    if (value !== undefined) env.PI_CODING_AGENT_DIR = value;
    const result = spawnSync('bash', [wrapper, '--version'], { env, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr); assert.equal(result.stdout.trim(), value === undefined ? '/container-default' : value);
  }
});
