'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { retireLegacyPoller, LEGACY_POLLER_SHA256 } = require('../pi_mcp_refresh.cjs');
const crypto = require('node:crypto');
const packagePath = process.env.PI_TEST_PACKAGE;
const vendor = process.env.OMNIGENT_TEST_SITE_PACKAGES;
if (!packagePath || !vendor) throw new Error('PI_TEST_PACKAGE and OMNIGENT_TEST_SITE_PACKAGES fixture paths required');

async function fixture(t) {
  const api = await import(pathToFileURL(path.join(packagePath, 'dist/bundle/index.js')));
  assert.equal(api.VERSION, '0.99.1');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-mcp-bootstrap-'));
  fs.chmodSync(dir, 0o700);
  fs.mkdirSync(path.join(dir, 'inbox'));
  const extension = path.join(dir, 'native.js');
  const original = fs.readFileSync(path.join(vendor, 'omnigent/resources/pi_native/omnigent_pi_native_extension.js'));
  assert.equal(crypto.createHash('sha256').update(original).digest('hex'), 'dfa2d58304d3045f56658020683aafe61adb57e4775c6de5d86e10307c82a5fa');
  fs.writeFileSync(extension, original);
  const config = path.join(dir, 'config.json');
  fs.writeFileSync(config, JSON.stringify({ bridgeDir: dir, inboxDir: path.join(dir, 'inbox'),
    sessionId: 'conv_bootstrap_fixture', serverUrl: 'http://127.0.0.1:9' }));
  const oldConfig = process.env.OMNIGENT_PI_NATIVE_CONFIG;
  const oldFetch = global.fetch;
  process.env.OMNIGENT_PI_NATIVE_CONFIG = config;
  global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
  const loaded = await api.discoverAndLoadExtensions([extension], dir, dir);
  assert.deepEqual(loaded.errors, []);
  loaded.runtime.getAllTools = () => [];
  loaded.runtime.refreshTools = () => {};
  loaded.runtime.getActiveTools = () => [];
  const ctx = { isIdle: () => true, hasPendingMessages: () => false, hasUI: false,
    ui: { setStatus() {}, notify() {} },
    sessionManager: { getSessionId: () => '01234567-89ab-4cde-8f01-23456789abcd', getEntries: () => [] } };
  const timers = [];
  const originalSetInterval = global.setInterval;
  global.setInterval = (...args) => { const timer = originalSetInterval(...args); timers.push(timer); return timer; };
  try {
    for (const h of loaded.extensions[0].handlers.get('session_start') || []) await h({ type: 'session_start' }, ctx);
  } finally { global.setInterval = originalSetInterval; }
  t.after(() => {
    for (const timer of timers) clearInterval(timer);
    global.fetch = oldFetch;
    if (oldConfig === undefined) delete process.env.OMNIGENT_PI_NATIVE_CONFIG;
    else process.env.OMNIGENT_PI_NATIVE_CONFIG = oldConfig;
    fs.rmSync(dir, { recursive: true, force: true });
  });
  return { dir, loaded, api, ctx, timers };
}

test('actual original Omnigent/Jiti legacy poller retired without consuming inbox or clearing unrelated timers', async t => {
  const h = await fixture(t);
  const unrelated = setInterval(() => {}, 250);
  t.after(() => clearInterval(unrelated));
  const pending = path.join(h.dir, 'inbox', 'preserved.json');
  fs.writeFileSync(pending, JSON.stringify({ id: 'pending-original', type: 'user_message', content: 'preserve-this-input' }));
  h.loaded.runtime.invalidate(); // Exactly what Pi0.99.1 reload does before loading new extensions.
  assert.equal(retireLegacyPoller(), 1);
  assert.equal(unrelated._destroyed, false);
  assert.equal(retireLegacyPoller({ expectedMatches: 0 }), 0);
  await new Promise(resolve => setTimeout(resolve, 300));
  assert.equal(JSON.parse(fs.readFileSync(pending)).content, 'preserve-this-input');
  assert.match(LEGACY_POLLER_SHA256, /^[0-9a-f]{64}$/);
});

test('similar-looking timer callback is never retired by textual keyword alone', () => {
  const unrelated = setInterval(() => { const deliverAttempts = new Map(); void deliverAttempts; }, 250);
  try { assert.throws(() => retireLegacyPoller(), /MCP_NATIVE_UNAVAILABLE/); assert.equal(unrelated._destroyed, false); }
  finally { clearInterval(unrelated); }
});

test('zero matches refuses first bootstrap and two exact matches refuse without retiring either', async t => {
  assert.throws(() => retireLegacyPoller(), /MCP_NATIVE_UNAVAILABLE/);
  const first = await fixture(t);
  const second = await fixture(t);
  assert.equal(first.timers.length, 1);
  assert.equal(second.timers.length, 1);
  assert.throws(() => retireLegacyPoller(), /MCP_NATIVE_UNAVAILABLE/);
  assert.throws(() => retireLegacyPoller({ expectedMatches: 2 }), /MCP_NATIVE_UNAVAILABLE/);
  assert.equal(first.timers[0]._destroyed, false);
  assert.equal(second.timers[0]._destroyed, false);
});

test('first bootstrap binds exact native ID and process before retiring legacy callback', async t => {
  const h = await fixture(t);
  const id = h.ctx.sessionManager.getSessionId();
  const sessionFile = path.join(h.dir, 'original-native.jsonl');
  fs.writeFileSync(sessionFile, JSON.stringify({ type: 'session', id }) + '\n', { mode: 0o600 });
  h.ctx.sessionManager.getSessionFile = () => sessionFile;
  const handlers = new Map();
  const pi = { on: (name, handler) => handlers.set(name, handler), registerCommand() {} };
  const factory = () => api => api.on('session_start', () => {});
  const { createController } = require('../pi_mcp_refresh.cjs');
  createController(pi, { bridgeDir: h.dir, sessionId: 'conv_identity_fixture' }, factory);
  for (const values of [{ pid: process.pid + 1, nativeSessionId: id },
    { pid: process.pid, nativeSessionId: '11111111-1111-4111-8111-111111111111' }]) {
    fs.writeFileSync(path.join(h.dir, 'woow-mcp-bootstrap.json'), JSON.stringify({
      sessionId: 'conv_identity_fixture', ...values }), { mode: 0o600 });
    await assert.rejects(handlers.get('session_start')({ type: 'session_start', reason: 'reload' }, h.ctx), /MCP_NATIVE_ID_CHANGED/);
    assert.equal(h.timers[0]._destroyed, false);
  }
  h.ctx.isIdle = () => false;
  await assert.rejects(handlers.get('session_start')({ type: 'session_start', reason: 'reload' }, h.ctx), /SESSION_BUSY/);
  assert.equal(h.timers[0]._destroyed, false);
});

test('unknown Node version refuses without touching a timer', () => {
  const version = Object.getOwnPropertyDescriptor(process.versions, 'node');
  const unrelated = setInterval(() => {}, 250);
  try {
    Object.defineProperty(process.versions, 'node', { value: '24.0.0', configurable: true });
    assert.throws(() => retireLegacyPoller(), /MCP_NATIVE_UNAVAILABLE/);
    assert.equal(unrelated._destroyed, false);
  } finally {
    Object.defineProperty(process.versions, 'node', version);
    clearInterval(unrelated);
  }
});

test('patched extension loads through actual Pi Jiti, preserves queued inbox, repeat reload has no orphan', async t => {
  const h = await fixture(t);
  const { execFileSync } = require('node:child_process');
  const net = require('node:net');
  const site = path.join(h.dir, 'site');
  for (const name of ['harnesses/pi_native/bridge.py', 'resources/pi_native/omnigent_pi_native_extension.js']) {
    const target = path.join(site, 'omnigent', name);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(path.join(vendor, 'omnigent', name), target);
  }
  fs.mkdirSync(path.join(site, 'omnigent-0.16.0.dist-info'));
  fs.writeFileSync(path.join(site, 'omnigent-0.16.0.dist-info/METADATA'), 'Name: omnigent\nVersion: 0.16.0\n');
  execFileSync(process.env.OMNIGENT_TEST_PYTHON || 'python3', [path.join(__dirname, '../patch-native-resume.py'), '--site-packages', site], { stdio: 'pipe' });
  fs.copyFileSync(path.join(site, 'omnigent/resources/pi_native/omnigent_pi_native_extension.js'), path.join(h.dir, 'native.js'));
  fs.copyFileSync(path.join(site, 'omnigent/resources/pi_native/woow_pi_mcp_refresh.cjs'), path.join(h.dir, 'woow_pi_mcp_refresh.cjs'));
  const id = h.ctx.sessionManager.getSessionId();
  const sessionFile = path.join(h.dir, 'original-native.jsonl');
  const history = JSON.stringify({ type: 'session', id, version: 3 }) + '\n' + JSON.stringify({ type: 'message', id: 'old', message: { role: 'user', content: 'keep-native-history' } }) + '\n';
  fs.writeFileSync(sessionFile, history, { mode: 0o600 });
  h.ctx.sessionManager.getSessionFile = () => sessionFile;
  h.ctx.cwd = h.dir;
  h.ctx.isProjectTrusted = () => true;
  fs.writeFileSync(path.join(h.dir, 'woow-mcp-bootstrap.json'), JSON.stringify({ sessionId: 'conv_bootstrap_fixture', nativeSessionId: id, pid: process.pid }), { mode: 0o600 });
  const pending = path.join(h.dir, 'inbox', 'preserved.json');
  fs.writeFileSync(pending, JSON.stringify({ id: 'pending-original', type: 'user_message', content: 'preserve-this-input' }));
  const previousAgentDir = process.env.PI_CODING_AGENT_DIR;
  process.env.PI_CODING_AGENT_DIR = h.dir;
  let loaded;
  const deliveries = [];
  const shutdown = async () => {
    if (!loaded) return;
    for (const handler of loaded.extensions[0].handlers.get('session_shutdown') || []) await handler({ type: 'session_shutdown', reason: 'reload' }, h.ctx);
    loaded.runtime.invalidate();
    loaded = undefined;
  };
  const reload = async () => {
    loaded = await h.api.discoverAndLoadExtensions([path.join(h.dir, 'native.js')], h.dir, h.dir);
    assert.deepEqual(loaded.errors, []);
    assert.ok(loaded.extensions[0].commands.has('mcp'), 'public MCP factory was installed');
    loaded.runtime.getAllTools = () => [];
    loaded.runtime.refreshTools = () => {};
    loaded.runtime.getActiveTools = () => [];
    loaded.runtime.sendUserMessage = content => { deliveries.push(content); };
    for (const handler of loaded.extensions[0].handlers.get('session_start') || []) await handler({ type: 'session_start', reason: 'reload' }, h.ctx);
    await new Promise(resolve => setTimeout(resolve, 10));
  };
  const probe = () => new Promise((resolve, reject) => {
    const socket = net.connect(path.join(h.dir, 'woow-mcp.sock'));
    let bytes = '';
    socket.on('error', reject);
    socket.on('connect', () => socket.write(JSON.stringify({ version: 1, sessionId: 'conv_bootstrap_fixture', nativeSessionId: id,
      action: 'probe', deadlineMs: Date.now() + 2000 }) + '\n'));
    socket.on('data', data => { bytes += data; });
    socket.on('end', () => resolve(JSON.parse(bytes)));
  });
  try {
    h.loaded.runtime.invalidate();
    await reload();
    assert.equal((await probe()).legacyPollersRetired, 1);
    await new Promise(resolve => setTimeout(resolve, 350));
    assert.deepEqual(deliveries, ['preserve-this-input']);
    assert.equal(fs.existsSync(pending), false);
    assert.equal(fs.readFileSync(sessionFile, 'utf8'), history);
    await shutdown();
    // Updated helper code must load on the next native reload too, rather
    // than remaining in Node's CommonJS cache under the same filename.
    const helperPath = path.join(h.dir, 'woow_pi_mcp_refresh.cjs');
    fs.writeFileSync(helperPath, fs.readFileSync(helperPath, 'utf8').replace(
      'legacyPollersRetired };', 'legacyPollersRetired, fixtureBuild: "updated" };'));
    await reload();
    assert.equal((await probe()).legacyPollersRetired, 0);
    assert.equal((await probe()).fixtureBuild, 'updated');
    assert.equal(fs.readFileSync(sessionFile, 'utf8'), history);
  } finally {
    await shutdown();
    if (previousAgentDir === undefined) delete process.env.PI_CODING_AGENT_DIR;
    else process.env.PI_CODING_AGENT_DIR = previousAgentDir;
  }
});
