'use strict';
// PI_TEST_PACKAGE points at an isolated npm install of Pi 0.99.1.
// Uses its actual bundled createMcpExtension and actual pi-mcp JSON-RPC client.
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { createController } = require('../pi_mcp_refresh.cjs');
const packagePath = process.env.PI_TEST_PACKAGE;
if (!packagePath) throw new Error('Set PI_TEST_PACKAGE to an isolated @earendil-works/pi-coding-agent@0.99.1 installation');
assert.equal(JSON.parse(fs.readFileSync(path.join(packagePath, 'package.json'))).version, '0.99.1');
const nativeId = '01234567-89ab-4cde-8f01-23456789abcd';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate) {
  for (let n = 0; n < 400; n++) { if (predicate()) return; await delay(5); }
  throw new Error('FIXTURE_TIMEOUT');
}

async function harness(t, { socket = false, timeout = 1000 } = {}) {
  const { createMcpExtension, ExtensionRunner, VERSION } = await import(pathToFileURL(path.join(packagePath, 'dist/bundle/index.js')));
  assert.equal(VERSION, '0.99.1');
  const { createInMemoryTransportPair } = await import(pathToFileURL(path.join(packagePath,
    'node_modules/@earendil-works/pi-mcp/dist/testing/index.js')));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-mcp-reload-'));
  fs.chmodSync(dir, 0o700);
  const file = path.join(dir, 'original.jsonl');
  const history = JSON.stringify({ type: 'session', version: 3, id: nativeId }) + '\n'
    + JSON.stringify({ type: 'message', id: 'old', message: { role: 'user', content: 'original-history-nonce' } }) + '\n';
  fs.writeFileSync(file, history, { mode: 0o600 });
  const handlers = new Map(), commands = new Map(), definitions = new Map();
  let active = ['local_tool'];
  const state = { idle: true, pending: false, id: nativeId, file, fail: false, gate: null,
    entries: [{ name: 'old', nonce: 'before', tools: ['echo'] }], transports: [], notifications: [] };
  definitions.set('local_tool', { name: 'local_tool', exposure: 'direct' });
  const pi = {
    on(name, handler) { if (!handlers.has(name)) handlers.set(name, []); handlers.get(name).push(handler); },
    registerCommand(name, value) { commands.set(name, value); },
    registerTool(def) {
      definitions.set(def.name, def);
      if (def.exposure === 'hidden') active = active.filter(name => name !== def.name);
      else if (def.exposure === 'direct' && !active.includes(def.name)) active.push(def.name);
    },
    getAllTools: () => [...definitions.values()],
    getActiveTools: () => [...active],
    setActiveTools(names) { active = names.filter(name => definitions.get(name)?.exposure !== 'hidden'); },
    getMcpServers: () => [],
  };
  const ui = { notify: message => state.notifications.push(message) };
  // Use the actual native context implementation, including its lazy getter-only
  // ui property. A plain-object fixture misses that real runtime constraint.
  const runner = new ExtensionRunner([], {}, dir,
    { getSessionId: () => state.id, getSessionFile: () => state.file }, {});
  runner.uiContext = ui;
  runner.isIdleFn = () => state.idle;
  runner.hasPendingMessagesFn = () => state.pending;
  runner.abortFn = () => assert.fail('Never abort');
  const ctx = runner.createContext();
  ctx.newSession = () => assert.fail('Never create a fresh session');
  const emit = async type => { for (const fn of handlers.get(type) || []) await fn({ type, reason: 'startup' }, ctx); };
  const controller = createController(pi, { bridgeDir: dir, sessionId: 'conv_test' }, createMcpExtension, {
    noSocket: !socket, startupWaitMs: timeout,
    factoryOptions: {
      credentials: {},
      logPath: path.join(dir, 'private-mcp.log'),
      loadConfig: () => ({ servers: state.entries.map(entry => ({ name: entry.name, scope: 'global', source: 'fixture',
        config: { command: 'in-memory-only', exposure: 'direct', nonce: entry.nonce, tools: entry.tools } })), errors: [] }),
      createTransport(entry) {
        const pair = createInMemoryTransportPair();
        const record = { ...pair, name: entry.name, nonce: entry.config.nonce, calls: [] };
        state.transports.push(record);
        void pair.server.start();
        pair.server.onMessage(async message => {
          if (message.id === undefined) return;
          const send = result => pair.server.send({ jsonrpc: '2.0', id: message.id, result }).catch(() => {});
          if (message.method === 'initialize') {
            if (state.gate) await state.gate;
            if (state.fail) {
              await pair.server.send({ jsonrpc: '2.0', id: message.id, error: { code: -32603, message: 'secret-not-for-output' } });
            } else await send({ protocolVersion: message.params.protocolVersion, capabilities: { tools: {} },
              serverInfo: { name: 'fixture', version: '1' } });
          } else if (message.method === 'tools/list') {
            await send({ tools: entry.config.tools.map(name => ({ name, description: 'nonce fixture', inputSchema: { type: 'object' } })) });
          } else if (message.method === 'tools/call') {
            record.calls.push(message.params.name);
            await send({ content: [{ type: 'text', text: entry.config.nonce }] });
          } else await send({});
        });
        return pair.client;
      },
    },
  });
  await emit('session_start');
  await until(() => definitions.has('mcp__old__echo'));
  const request = (overrides = {}) => controller.request({ version: 1, sessionId: 'conv_test', nativeSessionId: nativeId,
    action: 'refresh', configurationHash: 'a'.repeat(64), deadlineMs: Date.now() + 15000, ...overrides });
  const call = async name => {
    const tool = definitions.get(name);
    assert.ok(tool && tool.exposure !== 'hidden', 'tool is callable');
    const result = await tool.execute('fixture-call', {}, undefined, undefined, ctx);
    return result.content[0].text;
  };
  t.after(async () => {
    state.gate = null;
    await emit('session_shutdown');
    for (const transport of state.transports) await transport.client.close();
    fs.rmSync(dir, { recursive: true, force: true });
  });
  return { state, definitions, pi, ctx, emit, request, call, file, history, controller, dir };
}

test('actual Pi factory replaces configuration and tools while keeping native identity/history', async t => {
  const h = await harness(t);
  assert.equal(await h.call('mcp__old__echo'), 'before');
  const original = h.state.transports[0];
  h.state.entries = [{ name: 'old', nonce: 'after', tools: ['echo', 'added'] },
    { name: 'new', nonce: 'new-server-nonce', tools: ['probe'] }];
  const result = await h.request();
  assert.equal(result.state, 'applied');
  assert.equal(result.nativeSessionId, nativeId);
  assert.equal(result.inventoryVerified, true);
  assert.equal(result.toolsVerified, false);
  assert.equal(await h.call('mcp__old__echo'), 'after');
  assert.equal(await h.call('mcp__new__probe'), 'new-server-nonce');
  assert.equal(original.client.closed, true);
  h.state.entries = [{ name: 'new', nonce: 'third-nonce', tools: ['probe'] }];
  assert.equal((await h.request()).state, 'applied');
  for (const name of ['mcp__old__echo', 'mcp__old__added']) {
    assert.equal(h.definitions.get(name).exposure, 'hidden');
    assert.ok(!h.pi.getActiveTools().includes(name));
  }
  assert.equal(await h.call('mcp__new__probe'), 'third-nonce');
  assert.equal(h.state.id, nativeId);
  assert.equal(fs.readFileSync(h.file, 'utf8'), h.history);
  assert.ok(h.pi.getActiveTools().includes('local_tool'));
});

test('busy, pending input, missing persistence and wrong identity refuse before connecting', async t => {
  const h = await harness(t);
  h.state.idle = false;
  assert.equal((await h.request()).code, 'SESSION_BUSY');
  h.state.idle = true; h.state.pending = true;
  assert.equal((await h.request()).code, 'SESSION_BUSY');
  h.state.pending = false;
  await h.emit('input');
  assert.equal((await h.request()).code, 'SESSION_BUSY');
  await h.emit('agent_settled');
  assert.equal((await h.request({ nativeSessionId: '11111111-1111-4111-8111-111111111111' })).code, 'MCP_NATIVE_ID_CHANGED');
  fs.unlinkSync(h.file);
  assert.equal((await h.request()).code, 'MCP_PERSISTENCE_MISSING');
  assert.equal(h.state.transports.length, 1);
  assert.equal(h.state.transports[0].client.closed, false);
});

test('failed preparation keeps original connections and callable tools, sanitizes errors', async t => {
  const h = await harness(t);
  h.state.entries = [{ name: 'new', nonce: 'new', tools: ['echo'] }];
  h.state.fail = true;
  const result = await h.request();
  assert.equal(result.code, 'MCP_PREPARE_FAILED');
  assert.ok(!JSON.stringify(result).includes('secret'));
  assert.equal(await h.call('mcp__old__echo'), 'before');
  assert.equal(h.state.transports[0].client.closed, false);
  assert.equal(h.definitions.has('mcp__new__echo'), false);
  assert.equal(fs.readFileSync(h.file, 'utf8'), h.history);
});

test('idle is rechecked at commit, concurrent requests cannot clear guard, turns keep old connections', async t => {
  const h = await harness(t);
  let release;
  h.state.gate = new Promise(resolve => { release = resolve; });
  h.state.entries = [{ name: 'new', nonce: 'new', tools: ['echo'] }];
  const first = h.request();
  await until(() => h.state.transports.length === 2);
  assert.equal((await h.request()).code, 'SESSION_BUSY');
  assert.equal((await h.request()).code, 'SESSION_BUSY');
  assert.equal(await h.call('mcp__old__echo'), 'before');
  h.state.idle = false;
  release();
  assert.equal((await first).code, 'SESSION_BUSY');
  assert.equal(h.state.transports[0].client.closed, false);
  assert.equal(h.state.transports[1].client.closed, true);
  h.state.idle = true; h.state.gate = null;
  assert.equal((await h.request()).state, 'applied');
});

test('prompt admission during staging refuses even if Pi idle signal has not changed', async t => {
  const h = await harness(t);
  let release;
  h.state.gate = new Promise(resolve => { release = resolve; });
  const pending = h.request();
  await until(() => h.state.transports.length === 2);
  await h.emit('input');
  release();
  assert.equal((await pending).code, 'SESSION_BUSY');
  assert.equal(h.state.transports[0].client.closed, false);
});

test('empty configuration withdraws all old MCP tools without changing unrelated tools', async t => {
  const h = await harness(t);
  h.state.entries = [];
  assert.equal((await h.request()).state, 'applied');
  assert.equal(h.definitions.get('mcp__old__echo').exposure, 'hidden');
  assert.deepEqual(h.pi.getActiveTools(), ['local_tool']);
});

test('private Unix socket speaks the same identity-checked protocol', async t => {
  const h = await harness(t, { socket: true });
  await until(() => fs.existsSync(h.controller.socketPath));
  assert.equal(fs.statSync(h.controller.socketPath).mode & 0o777, 0o600);
  const net = require('node:net');
  const result = await new Promise((resolve, reject) => {
    const socket = net.connect(h.controller.socketPath);
    socket.on('error', reject);
    let data = '';
    socket.on('connect', () => socket.write(JSON.stringify({ version: 1, sessionId: 'conv_test',
      nativeSessionId: nativeId, action: 'probe', deadlineMs: Date.now() + 2000 }) + '\n'));
    socket.on('data', chunk => { data += chunk; });
    socket.on('end', () => resolve(JSON.parse(data)));
  });
  assert.deepEqual(result, { state: 'ready', nativeSessionId: nativeId, legacyPollersRetired: 0 });
});

test('retired callbacks cannot restore removed tools after publication', async t => {
  const h = await harness(t);
  const old = h.state.transports[0];
  h.state.entries = [{ name: 'new', nonce: 'new', tools: ['echo'] }];
  assert.equal((await h.request()).state, 'applied');
  await old.server.send({ jsonrpc: '2.0', method: 'notifications/tools/list_changed' }).catch(() => {});
  await delay(10);
  assert.equal(h.definitions.get('mcp__old__echo').exposure, 'hidden');
  assert.ok(!h.pi.getActiveTools().includes('mcp__old__echo'));
  assert.equal(await h.call('mcp__new__echo'), 'new');
});

test('native identity or persistence changed during preparation never commits', async t => {
  for (const mutate of [h => { h.state.id = '11111111-1111-4111-8111-111111111111'; }, h => fs.unlinkSync(h.file)]) {
    const h = await harness(t);
    let release;
    h.state.gate = new Promise(resolve => { release = resolve; });
    h.state.entries = [{ name: 'new', nonce: 'new', tools: ['echo'] }];
    const pending = h.request();
    await until(() => h.state.transports.length === 2);
    mutate(h);
    release();
    assert.ok(['MCP_NATIVE_ID_CHANGED', 'MCP_PERSISTENCE_MISSING'].includes((await pending).code));
    assert.equal(h.state.transports[0].client.closed, false);
    assert.equal(h.definitions.has('mcp__new__echo'), false);
  }
});

test('preparation timeout or client expiry keeps old toolset and never publishes late callbacks', async t => {
  const h = await harness(t, { timeout: 20 });
  let release;
  h.state.gate = new Promise(resolve => { release = resolve; });
  h.state.entries = [{ name: 'new', nonce: 'new', tools: ['echo'] }];
  const result = await h.request();
  assert.equal(result.code, 'MCP_PREPARE_FAILED');
  release();
  await delay(25);
  assert.equal(h.definitions.has('mcp__new__echo'), false);
  assert.equal(await h.call('mcp__old__echo'), 'before');
  assert.equal((await h.request({ deadlineMs: Date.now() - 1 })).code, 'MCP_REQUEST_EXPIRED');
});

test('post-publication transport close failure does not falsely claim rollback', async t => {
  const h = await harness(t);
  const old = h.state.transports[0].client;
  const close = old.close.bind(old);
  old.close = async () => { throw new Error('private-cleanup-failure'); };
  h.state.entries = [{ name: 'new', nonce: 'after-cleanup-error', tools: ['echo'] }];
  const result = await h.request();
  assert.equal(result.state, 'applied');
  assert.equal(await h.call('mcp__new__echo'), 'after-cleanup-error');
  assert.equal(h.definitions.get('mcp__old__echo').exposure, 'hidden');
  assert.ok(!JSON.stringify(result).includes('private'));
  old.close = close;
});
