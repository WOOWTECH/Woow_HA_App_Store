import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { seed } from '../rootfs/usr/local/lib/pi-omnigent-ha/lifecycle.mjs';
import { createOmnigentBridge } from '../rootfs/usr/local/lib/pi-omnigent-ha/bridge.mjs';
import { createServer } from '../rootfs/usr/local/lib/pi-omnigent-ha/server.mjs';
import { bootSummary, logSafe, startBootWorker } from '../rootfs/usr/local/lib/pi-omnigent-ha/worker.mjs';

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
  const plugin = { version: '0.3.11', lifecycle: async () => ({ active: true }),
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
  assert.equal('onboardingUrl' in view, false);
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
test('Settings bridge and UI never reference a setup conversation', () => {
  const files = ['rootfs/usr/local/lib/pi-omnigent-ha/bridge.mjs', 'rootfs/usr/local/lib/pi-omnigent-ha/lifecycle.mjs',
    'rootfs/usr/local/share/pi-omnigent-ha/app.js', 'rootfs/usr/local/share/pi-omnigent-ha/index.html'];
  for (const file of files) {
    assert.doesNotMatch(fs.readFileSync(path.join(root, file), 'utf8'), /onboarding|設定對話/i, `${file} must not reference a setup conversation`);
  }
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
// Plugin issue contract (0.3.30+): status().issue keeps {code, message, details?}
// and adds hints {en, zh-TW, zh-CN} and an action. Older plugins send code/message only.
const resetHints = {
  en: 'This host identity is already used by another Omnigent account. Run omnigent host reset-id --yes in the terminal, then connect again.',
  'zh-TW': '這個主機身分已被另一個 Omnigent 帳號使用。請在終端機執行 omnigent host reset-id --yes，再重新連線。',
  'zh-CN': '此主机身份已被另一个 Omnigent 账号使用。请在终端执行 omnigent host reset-id --yes，然后重新连接。',
};
test('the status issue reaches the page with only its code, message, hints and action', async () => {
  const f = fakePlugin();
  Object.assign(f.current, { phase: 'error', issue: { code: 'NEEDS_RESET_ID', message: '此 host ID 屬於另一個 Omnigent 帳號。\u0007',
    details: ['/data/pi-agent/home/.omnigent/private-detail'], hints: { ...resetHints, 'zh-TW': `${resetHints['zh-TW']}\n`, fr: 'not a contract locale' },
    action: 'reset-host-id', token: 'must-not-leak' } });
  const view = await f.bridge.read();
  assert.deepEqual(view.issue, { code: 'NEEDS_RESET_ID', message: '此 host ID 屬於另一個 Omnigent 帳號。', hints: resetHints, action: 'reset-host-id' });
  assert.equal(JSON.stringify(view).includes('private-detail'), false);
  assert.equal(JSON.stringify(view).includes('must-not-leak'), false);
  f.current.issue = { code: 'CONNECTION_IDENTITY_MISMATCH' };
  assert.deepEqual((await f.bridge.read()).issue, { code: 'CONNECTION_IDENTITY_MISMATCH', message: null, hints: null, action: null });
  f.current.issue = { code: 'NEEDS_LOGIN', hints: { en: 42, 'zh-TW': ' ' }, action: 'reboot' };
  assert.deepEqual((await f.bridge.read()).issue, { code: 'NEEDS_LOGIN', message: null, hints: null, action: null });
  for (const code of ['needs_login', '1NEEDS', '_NEEDS', 'N'.repeat(65), 'NEEDS LOGIN', 42, undefined]) {
    f.current.issue = { code, message: 'not shown', hints: resetHints, action: 'relogin' };
    assert.equal((await f.bridge.read()).issue, null, `issue code ${code} is outside the contract`);
  }
  delete f.current.issue;
  assert.equal((await f.bridge.read()).issue, null);
  f.plugin.lifecycle = async () => ({ active: false });
  assert.equal((await f.bridge.read()).issue, null);
});
test('resume reconnects only the recorded login and reports why it did not', async () => {
  const f = fakePlugin(); const seen = [];
  let outcome = { ok: true, resumed: true, server: 'https://example.test', host: { id: 'fixture-host', connected: true } };
  f.plugin.runtime.resumeAuthorizedHost = async options => { seen.push({ keys: Object.keys(options).sort(), lifecycle: await options.lifecycle() }); return outcome; };
  let view = await f.bridge.act({ action: 'resume', server: 'https://other.test', username: 'test', password: 'private-fixture' });
  assert.deepEqual(view.operation, { ok: true, code: null });
  assert.deepEqual(seen, [{ keys: ['lifecycle'], lifecycle: { active: true } }], 'only the native lifecycle is passed, never login input');
  assert.equal(JSON.stringify(view).includes('private-fixture'), false);
  for (const [result, code] of [
    [{ ok: true, resumed: false, reason: 'fresh-login-required' }, 'FRESH_LOGIN_REQUIRED'],
    [{ ok: true, resumed: false, reason: 'inactive' }, 'PLUGIN_UNAVAILABLE'],
    [{ ok: true, resumed: false, reason: 'a-future-reason' }, 'RESUME_SKIPPED'],
    [{ ok: false, resumed: false, error: { code: 'CONNECTION_IDENTITY_MISMATCH' } }, 'CONNECTION_IDENTITY_MISMATCH'],
    [{ ok: false, busy: true, phase: 'busy', error: { code: 'OPERATION_BUSY', message: '另一個 Omnigent 操作正在執行，請稍後重試。' } }, 'OPERATION_BUSY'],
  ]) {
    outcome = result;
    assert.deepEqual((await f.bridge.act({ action: 'resume' })).operation, { ok: false, code });
  }
  // A failed resume is recorded as the status issue, so its hints return with the view.
  outcome = { ok: false, resumed: false, error: { code: 'HOST_CONNECT_TIMEOUT' } };
  f.current.issue = { code: 'HOST_CONNECT_TIMEOUT', message: '原 host 尚未回線；請查看插件狀態。', action: 'retry',
    hints: { en: 'The host is not online yet. Try again.', 'zh-TW': '主機尚未上線，請稍後再試。', 'zh-CN': '主机尚未上线，请稍后再试。' } };
  view = await f.bridge.act({ action: 'resume' });
  assert.equal(view.operation.code, 'HOST_CONNECT_TIMEOUT'); assert.equal(view.issue.action, 'retry');
  delete f.plugin.runtime.resumeAuthorizedHost;
  assert.deepEqual((await f.bridge.act({ action: 'resume' })).operation, { ok: false, code: 'RESUME_UNSUPPORTED' });
  assert.deepEqual(f.calls, [], 'resume never logs in, verifies or disconnects');
  f.plugin.runtime.resumeAuthorizedHost = async () => { seen.push('disabled'); return outcome; };
  f.plugin.lifecycle = async () => ({ active: false });
  await assert.rejects(f.bridge.act({ action: 'resume' }), { code: 'PLUGIN_UNAVAILABLE' });
  assert.equal(seen.includes('disabled'), false);
});
test('only the bridge\'s own error codes reach the page; Node and system codes stay in the add-on log', async t => {
  const logged = []; t.mock.method(console, 'error', message => { logged.push(String(message)); });
  let failure;
  const bridge = { read: async () => { throw failure; }, act: async () => { throw failure; } };
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ha-omnigent-static-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  fs.copyFileSync(path.join(root, 'rootfs/usr/local/share/pi-omnigent-ha/index.html'), path.join(directory, 'index.html'));
  const server = createServer({ bridge, directory });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const token = (await (await fetch(base + '/omnigent')).text()).match(/name="omnigent-token" content="([a-f0-9]+)"/)[1];
  const headers = { 'X-Omnigent-Token': token, 'Content-Type': 'application/json' };
  for (const [error, status, code] of [
    [Object.assign(new Error('ENOENT: no such file, open /data/pi-agent/private-file'), { code: 'ENOENT' }), 503, 'OMNIGENT_FAILED'],
    [Object.assign(new Error('Cannot find module /opt/woow/private-module'), { code: 'ERR_MODULE_NOT_FOUND' }), 503, 'OMNIGENT_FAILED'],
    [Object.assign(new Error('Linux util-linux flock is required.'), { code: 'LOCK_UNAVAILABLE' }), 503, 'OMNIGENT_FAILED'],
    [new TypeError('private detail'), 503, 'OMNIGENT_FAILED'],
    [Object.assign(new Error('Plugin unavailable'), { code: 'PLUGIN_UNAVAILABLE' }), 409, 'PLUGIN_UNAVAILABLE'],
    [Object.assign(new Error('Unsupported action'), { code: 'INVALID_ACTION' }), 400, 'INVALID_ACTION'],
  ]) {
    failure = error;
    for (const init of [{ headers }, { method: 'POST', headers, body: '{"action":"resume"}' }]) {
      const response = await fetch(base + '/api/omnigent', init);
      assert.equal(response.status, status); assert.deepEqual(await response.json(), { error: { code } });
    }
  }
  assert.ok(['ENOENT', 'ERR_MODULE_NOT_FOUND', 'LOCK_UNAVAILABLE', 'TypeError'].every(value => logged.some(line => line.includes(`(${value})`))), logged.join('\n'));
  assert.ok(logged.every(line => !/private-(file|module)|private detail/.test(line)), 'the add-on log keeps the code, never the message');
  // A route whose file is missing is a 404, not a 503 naming the errno.
  const missing = await fetch(base + '/omnigent/app.js');
  assert.equal(missing.status, 404); assert.deepEqual(await missing.json(), { error: { code: 'NOT_FOUND' } });
});
test('pi-omnigent reaches the plugin CLI only for reviewed commands and refuses its Pi Web 0.10 setup', t => {
  const f = fixture(t);
  const cli = path.join(f.agentDir, 'cli.mjs'), ran = path.join(f.agentDir, 'ran');
  fs.writeFileSync(cli, `import fs from 'node:fs'; fs.writeFileSync(${JSON.stringify(ran)}, ''); console.log(JSON.stringify(process.argv.slice(2)));\n`);
  const source = fs.readFileSync(path.join(root, 'rootfs/usr/local/bin/pi-omnigent'), 'utf8');
  assert.match(source, /^#!\/bin\/sh\n/);
  assert.equal(fs.statSync(path.join(root, 'rootfs/usr/local/bin/pi-omnigent')).mode & 0o111, 0o111, 'executable in the repository');
  const wrapper = path.join(f.agentDir, 'pi-omnigent');
  fs.writeFileSync(wrapper, source.replace('/opt/woow/pi-omnigent-plugin/bin/cli.mjs', cli), { mode: 0o755 });
  const env = { PATH: `${path.dirname(process.execPath)}:/usr/bin:/bin` };
  const run = args => { fs.rmSync(ran, { force: true }); return spawnSync(wrapper, args, { env, encoding: 'utf8' }); };
  for (const args of [[], ['status'], ['verify', '--engine', 'pi', '--model', 'model with spaces'], ['cleanup-ui', '--dry-run'], ['boot'], ['disconnect']]) {
    const result = run(args);
    assert.equal(result.status, 0, result.stderr); assert.deepEqual(JSON.parse(result.stdout), args);
  }
  for (const [command, reason] of [['install-ui', /Pi Web 0\.10/], ['activate', /launcher/], ['install-host', /launcher/],
    ['launch-web', /second Pi Web/], ['onboarding', /not available/], ['--help', /not available/], ['', /not available/]]) {
    const result = run([command, '--prebuilt-root', '/tmp']);
    assert.equal(result.status, 2, command); assert.equal(fs.existsSync(ran), false, `${command} must not reach the plugin CLI`);
    assert.match(result.stderr, reason); assert.match(result.stderr, /not available/); assert.match(result.stderr, /status, catalog, verify/);
    assert.equal(result.stdout, '');
  }
  const dockerfile = fs.readFileSync(path.join(root, 'Dockerfile'), 'utf8');
  assert.doesNotMatch(dockerfile, /ln -s \/opt\/woow\/pi-omnigent-plugin\/bin\/cli\.mjs/, 'the plugin CLI is reached only through the wrapper');
  assert.match(dockerfile, /chmod \+x[^&]*\/usr\/local\/bin\/pi-omnigent \\/);
  assert.match(dockerfile, /sh -n \/usr\/local\/bin\/pi-omnigent \\/);
});
test('boot summaries copy only fixed vocabulary from the worker result', () => {
  assert.equal(bootSummary('not json'), null);
  assert.equal(bootSummary('[]'), null);
  assert.equal(bootSummary(JSON.stringify({ phase: 'disabled' })), 'phase=disabled');
  assert.equal(bootSummary(JSON.stringify({ phase: 'error', error: 'Operation failed (LOCK_UNAVAILABLE).' })), 'phase=error error=LOCK_UNAVAILABLE');
  assert.equal(bootSummary(JSON.stringify({ phase: 'error', error: '操作未完成；請檢查插件狀態與登入／模型設定。' })), 'phase=error');
  assert.equal(bootSummary(JSON.stringify({ initialization: { phase: 'ready', checked: true }, startup: { status: 'ready' },
    resumption: { ok: true, resumed: true, server: 'https://omnigent.example', host: { id: 'private-host-id', connected: true } } })), 'startup=ready initialization=ready resumed=yes');
  assert.equal(bootSummary(JSON.stringify({ initialization: { phase: 'inactive' }, startup: { status: 'inactive', reason: 'package-removed-or-unregistered' } })),
    'startup=inactive reason=package-removed-or-unregistered initialization=inactive');
  assert.equal(bootSummary(JSON.stringify({ initialization: { phase: 'needs-login' }, startup: { status: 'settings-required' },
    resumption: { ok: true, resumed: false, reason: 'fresh-login-required' } })), 'startup=settings-required initialization=needs-login resumed=no resume-reason=fresh-login-required');
  assert.equal(bootSummary(JSON.stringify({ startup: { status: 'Ready <script>' }, initialization: { phase: 'x'.repeat(65), reason: 'Omnigent initialization needs attention in Settings.' } })), null);
  assert.equal(logSafe('password: "private-value", ok'), 'password: "[redacted]", ok');
  assert.equal(logSafe('GET https://user:private@omnigent.example/v1'), 'GET https://[redacted]@omnigent.example/v1');
  assert.equal(logSafe('\u001b[33mwarning\u001b[0m\tdone'), 'warning done');
  assert.equal(logSafe('word '.repeat(100)).length, 301);
  assert.equal(logSafe(`sha ${'a1'.repeat(32)} kept short`), 'sha [redacted] kept short');
});
test('the boot worker reaches the add-on log as a summary and redacted, capped stderr', async t => {
  const f = fixture(t);
  const pluginRoot = path.join(f.agentDir, 'plugin'); fs.mkdirSync(path.join(pluginRoot, 'bin'), { recursive: true });
  const receipt = { checkedAt: '2026-10-29T12:00:00.000Z',
    initialization: { ok: true, phase: 'needs-verification', dependencies: { changed: false, installed: [], warnings: ['/data/pi-agent/home/private-path'] } },
    resumption: { ok: false, resumed: false, error: { code: 'HOST_CONNECT_TIMEOUT', message: 'private adapter message' } },
    startup: { status: 'settings-required' }, server: 'https://user:private-password@omnigent.example', host: { id: 'private-host-id' } };
  const lines = ['Authorization: Bearer private-bearer-token-123', 'token=private-token-value',
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwcml2YXRlIn0.cHJpdmF0ZS1zaWduYXR1cmU', 'retry https://user:private-pass@omnigent.example/v1',
    '\u001b[31mcolored warning\u001b[0m', ...Array.from({ length: 30 }, (_, index) => `line ${index}`)];
  fs.writeFileSync(path.join(pluginRoot, 'bin/cli.mjs'), `if (process.argv[2] !== 'boot') process.exit(9);
process.stderr.write(${JSON.stringify(lines.join('\n'))} + '\\npartial line without newline');
process.stdout.write(JSON.stringify(${JSON.stringify(receipt)}, null, 2) + '\\n');\n`);
  const out = [], err = [], spawned = [];
  const spawnImpl = (command, args, options) => { spawned.push({ command, args, options }); return spawn(command, args, options); };
  const worker = startBootWorker(pluginRoot, { env: { PATH: process.env.PATH }, spawnImpl, log: line => out.push(line), warn: line => err.push(line) });
  await once(worker, 'close');
  assert.deepEqual(spawned.map(item => [item.command, item.args]), [[process.execPath, [path.join(pluginRoot, 'bin/cli.mjs'), 'boot']]]);
  assert.equal(spawned[0].options.detached, true, 'its own process group, so stopping Pi Web also stops unfinished work');
  assert.deepEqual(spawned[0].options.stdio, ['ignore', 'pipe', 'pipe']);
  const log = [...out, ...err].join('\n');
  assert.deepEqual(out, ['Omnigent host worker finished (exit 0): startup=settings-required initialization=needs-verification resumed=no resume-error=HOST_CONNECT_TIMEOUT'], log);
  for (const secret of ['private-bearer-token-123', 'private-token-value', 'eyJzdWIiOiJwcml2YXRlIn0', 'private-pass', 'private-password',
    'private adapter', 'private-path', 'private-host-id', '\u001b']) assert.equal(log.includes(secret), false, `${JSON.stringify(secret)} must not reach the add-on log`);
  assert.ok(err.includes('[omnigent] colored warning'), log);
  assert.ok(err.includes('[omnigent] 16 more worker log lines not shown.'), log);
  assert.equal(err.length, 21);
});
test('the launcher keeps worker output and the write-only Pi Web URL is gone', () => {
  const launch = fs.readFileSync(path.join(root, 'rootfs/usr/local/lib/pi-omnigent-ha/launch.mjs'), 'utf8');
  assert.match(launch, /startBootWorker\(/); assert.doesNotMatch(launch, /stdio: 'ignore'/);
  for (const file of ['rootfs/etc/s6-overlay/s6-rc.d/pi-web/run', 'tests/omnigent-image-smoke.mjs']) {
    assert.doesNotMatch(fs.readFileSync(path.join(root, file), 'utf8'), /PI_OMNIGENT_PI_WEB_URL/, `${file}: the plugin never reads it`);
  }
});
