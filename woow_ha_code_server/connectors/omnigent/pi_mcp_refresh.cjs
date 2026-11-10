'use strict';
// In-process MCP reload using Pi 0.99.1's public createMcpExtension factory.
// No terminal input, new session, transcript rewrite, abort, or provider changes.
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const crypto = require('node:crypto');
const timers = require('node:timers');

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const HASH = /^[a-f0-9]{64}$/;
const fail = code => Object.assign(new Error(code), { code });
const known = new Set(['SESSION_BUSY', 'MCP_NATIVE_ID_CHANGED', 'MCP_PERSISTENCE_MISSING',
  'MCP_NATIVE_UNAVAILABLE', 'MCP_CONFIG_INVALID', 'MCP_PREPARE_FAILED',
  'MCP_REQUEST_EXPIRED', 'MCP_REFRESH_FAILED', 'MCP_INVALID_REQUEST']);
const codeOf = error => known.has(error?.code) ? error.code : 'MCP_REFRESH_FAILED';

// Omnigent 0.16 forgot to dispose its inbox interval on extension reload. Node
// offers no public timer enumerator. This bounded Node22-only bootstrap shim
// discovers via the timer list and disposes ONLY the exact pinned legacy callback.
// No inspector, process attach, global timer reset, native input or inbox edits.
const LEGACY_POLLER_SHA256 = '4efe03b5e290823384b6867e4619dcfce0b741687e7ab9ee9933123db7549772';
function retireLegacyPoller({ expectedMatches = 1 } = {}) {
  if (process.versions.node.split('.')[0] !== '22' || ![0, 1].includes(expectedMatches))
    throw fail('MCP_NATIVE_UNAVAILABLE');
  const sentinel = timers.setInterval(() => {}, 250);
  sentinel.unref();
  const found = [];
  try {
    let item = sentinel._idleNext;
    let count = 0;
    while (item && item !== sentinel && count++ < 4096) {
      if (item.constructor?.name === 'Timeout' && item._repeat === 250
        && typeof item._onTimeout === 'function') {
        const digest = crypto.createHash('sha256').update(Function.prototype.toString.call(item._onTimeout)).digest('hex');
        if (digest === LEGACY_POLLER_SHA256) found.push(item);
      }
      item = item._idleNext;
    }
    if (item !== sentinel || found.length !== expectedMatches) throw fail('MCP_NATIVE_UNAVAILABLE');
    for (const timer of found) timers.clearInterval(timer);
    return found.length;
  } finally { timers.clearInterval(sentinel); }
}

function createController(pi, config, createMcpExtension, options = {}) {
  let current;
  let context;
  let refreshing = false;
  let epoch = 0;
  let stopped = false;
  let pendingInput = false;
  let server;
  let socketIdentity;
  let legacyPollersRetired = 0;
  const bootstrapKey = Symbol.for('woow.pi.mcp.bootstrap.v1');
  const bootstrapStates = globalThis[bootstrapKey] ??= new Map();
  const socketPath = path.join(config.bridgeDir, 'woow-mcp.sock');
  const factoryOptions = options.factoryOptions || {};

  function runtime() {
    const state = { mode: 'staged', definitions: new Map(), handlers: new Map(),
      commands: new Map(), additions: new Set(), notices: false };
    const api = Object.create(pi);
    api.on = (event, handler) => {
      if (!state.handlers.has(event)) state.handlers.set(event, []);
      state.handlers.get(event).push(handler);
    };
    api.registerCommand = (name, command) => state.commands.set(name, command);
    api.registerTool = definition => {
      if (state.mode === 'retired') return;
      state.definitions.set(definition.name, definition);
      if (state.mode === 'live') pi.registerTool(definition);
    };
    api.getActiveTools = () => [...new Set([...pi.getActiveTools(), ...state.additions])];
    api.setActiveTools = names => {
      if (state.mode === 'retired') return;
      if (state.mode === 'live') pi.setActiveTools(names);
      else for (const name of names) if (!pi.getActiveTools().includes(name)) state.additions.add(name);
    };
    api.getAllTools = () => {
      const all = new Map(pi.getAllTools().map(tool => [tool.name, tool]));
      for (const [name, definition] of state.definitions) all.set(name, definition);
      return [...all.values()];
    };
    createMcpExtension({ ...factoryOptions, startupWaitMs: options.startupWaitMs ?? 10000 })(api);
    state.emit = async (event, ctx) => {
      for (const handler of state.handlers.get(event.type) || []) await handler(event, ctx);
    };
    state.close = async () => {
      state.mode = 'retired';
      await state.emit({ type: 'session_shutdown', reason: 'reload' }, context);
    };
    return state;
  }

  function identity(request) {
    if (!context || stopped || typeof context.isIdle !== 'function') throw fail('MCP_NATIVE_UNAVAILABLE');
    if (!context.isIdle() || context.hasPendingMessages?.() || pendingInput) throw fail('SESSION_BUSY');
    const id = context.sessionManager?.getSessionId?.();
    if (!UUID.test(id || '') || id !== request.nativeSessionId) throw fail('MCP_NATIVE_ID_CHANGED');
    const file = context.sessionManager?.getSessionFile?.();
    // Only inspect the header: never copy, synthesize or expose native messages.
    let fd;
    try {
      if (!file || fs.lstatSync(file).isSymbolicLink()) throw new Error();
      fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
      const stat = fs.fstatSync(fd);
      if (!stat.isFile() || stat.size === 0 || stat.uid !== process.getuid()) throw new Error();
      const prefix = Buffer.alloc(16384);
      const size = fs.readSync(fd, prefix, 0, prefix.length, 0);
      const line = prefix.subarray(0, size).toString('utf8').split('\n')[0];
      const header = JSON.parse(line);
      if (header.type !== 'session' || header.id !== id) throw new Error();
    } catch { throw fail('MCP_PERSISTENCE_MISSING'); }
    finally { if (fd !== undefined) fs.closeSync(fd); }
    return { id, file };
  }

  function validate(request) {
    if (!request || request.version !== 1 || request.sessionId !== config.sessionId
      || !UUID.test(request.nativeSessionId || '')
      || !['probe', 'refresh'].includes(request.action)
      || (request.action === 'refresh' && !HASH.test(request.configurationHash || '')))
      throw fail('MCP_INVALID_REQUEST');
    if (!Number.isSafeInteger(request.deadlineMs) || request.deadlineMs <= Date.now()
      || request.deadlineMs > Date.now() + 60000) throw fail('MCP_REQUEST_EXPIRED');
  }

  async function request(request, alive = () => true) {
    let staged;
    try {
      validate(request);
      if (refreshing) throw fail('SESSION_BUSY');
      const initial = identity(request);
      if (request.action === 'probe') return { state: 'ready', nativeSessionId: initial.id, legacyPollersRetired };
      refreshing = true;
      const generation = epoch;
      staged = runtime();
      const prepareContext = Object.create(context);
      // Actual ExtensionRunner contexts expose ui via a getter without a
      // setter. Shadow it explicitly rather than assigning through that getter.
      const prepareUI = Object.create(context.ui || {});
      Object.defineProperty(prepareContext, 'ui', { value: prepareUI });
      // Built-in connection errors may contain credentials or server output.
      // Keep only a boolean; never forward these messages to UI/logs/results.
      Object.defineProperty(prepareUI, 'notify', { value: () => { staged.notices = true; } });
      await staged.emit({ type: 'session_start', reason: 'reload' }, prepareContext);
      await staged.emit({ type: 'before_agent_start' }, prepareContext);
      if (staged.notices) throw fail('MCP_PREPARE_FAILED');
      if (!alive() || request.deadlineMs <= Date.now()) throw fail('MCP_REQUEST_EXPIRED');
      if (epoch !== generation) throw fail('SESSION_BUSY');
      const final = identity(request);
      if (final.file !== initial.file) throw fail('MCP_NATIVE_ID_CHANGED');
      // No await from the authoritative idle check through publication. Native
      // input can run during preparation with the old tools. An active turn
      // refuses publication; its connections are never closed.
      const previous = current;
      const activeBefore = pi.getActiveTools();
      previous.mode = 'retired';
      staged.mode = 'live';
      try {
        for (const [name, definition] of previous.definitions) {
          if (!staged.definitions.has(name)) pi.registerTool({ ...definition, exposure: 'hidden' });
        }
        for (const definition of staged.definitions.values()) pi.registerTool(definition);
        pi.setActiveTools([...new Set([...pi.getActiveTools(), ...staged.additions])]);
      } catch {
        staged.mode = 'retired';
        previous.mode = 'live';
        for (const [name, definition] of staged.definitions) {
          if (!previous.definitions.has(name)) pi.registerTool({ ...definition, exposure: 'hidden' });
        }
        for (const definition of previous.definitions.values()) pi.registerTool(definition);
        pi.setActiveTools(activeBefore);
        throw fail('MCP_REFRESH_FAILED');
      }
      current = staged;
      staged = undefined;
      // Old callbacks are fenced by mode='retired'. New turns see new tools;
      // retiring old MCP transports cannot cancel a native/model turn.
      // Publication already succeeded. Cleanup failures cannot imply rollback.
      void previous.close().catch(() => {});
      return { state: 'applied', method: 'native-mcp-reload', historyPreserved: true,
        nativeSessionId: final.id, configurationHash: request.configurationHash,
        inventoryVerified: true, toolsVerified: false,
        toolCount: [...current.definitions.values()].filter(d => d.exposure !== 'hidden').length };
    } catch (error) {
      if (staged) { try { await staged.close(); } catch {} }
      return { state: 'refused', code: codeOf(error) };
    } finally {
      // A concurrent refused request must not clear another request's guard.
      if (request === activeRequest) { refreshing = false; activeRequest = undefined; }
    }
  }
  let activeRequest;
  const invoke = (payload, alive) => {
    if (refreshing) return Promise.resolve({ state: 'refused', code: 'SESSION_BUSY' });
    activeRequest = payload;
    return request(payload, alive);
  };

  async function listen() {
    if (options.noSocket || server) return;
    const dir = fs.lstatSync(config.bridgeDir);
    if (!dir.isDirectory() || dir.isSymbolicLink() || dir.uid !== process.getuid()
      || (dir.mode & 0o077)) return;
    server = net.createServer(socket => {
      let data = '';
      socket.setTimeout(45000, () => socket.destroy());
      socket.on('error', () => {});
      socket.on('data', chunk => {
        data += chunk.toString('utf8');
        if (data.length > 4096) return socket.destroy();
        if (!data.includes('\n')) return;
        socket.removeAllListeners('data');
        let payload;
        try { payload = JSON.parse(data.trim()); }
        catch { return socket.end(JSON.stringify({ state: 'refused', code: 'MCP_INVALID_REQUEST' }) + '\n'); }
        void invoke(payload, () => !socket.destroyed).then(result => {
          if (!socket.destroyed) socket.end(JSON.stringify(result) + '\n');
        });
      });
    });
    server.on('error', () => {});
    // Never unlink an existing socket: it may belong to another live process.
    server.listen(socketPath, () => {
      fs.chmodSync(socketPath, 0o600);
      socketIdentity = fs.lstatSync(socketPath);
    });
  }

  current = runtime();
  current.mode = 'live';
  // Pi performs asynchronous auth/compaction preparation before it marks the
  // agent run active. Track that admission window too. A failed prompt can
  // conservatively block refresh until a subsequent successful turn settles.
  pi.on('input', () => { epoch++; pendingInput = true; return { action: 'continue' }; });
  pi.on('agent_start', () => { epoch++; pendingInput = true; });
  pi.on('agent_settled', () => { pendingInput = false; });
  for (const event of current.handlers.keys()) {
    pi.on(event, async (payload, ctx) => {
      if (event === 'session_start') {
        context = ctx; stopped = false; epoch++;
        if (!options.noSocket) {
          // Reload bootstrap is coordinator-owned and must already be idle.
          if (ctx.isIdle?.() !== true || ctx.hasPendingMessages?.()) throw fail('SESSION_BUSY');
          const id = ctx.sessionManager?.getSessionId?.();
          const previous = bootstrapStates.get(config.sessionId);
          const knownPatchedReload = previous?.shutdown === true && previous.id === id && previous.pid === process.pid;
          const fresh = payload.reason === 'startup';
          if (!fresh && !knownPatchedReload) {
            // First reload requires a coordinator-created owner-only identity
            // receipt. It contains no prompts, credentials or history content.
            const receiptPath = path.join(config.bridgeDir, 'woow-mcp-bootstrap.json');
            const stat = fs.lstatSync(receiptPath);
            if (!stat.isFile() || stat.isSymbolicLink() || stat.uid !== process.getuid() || (stat.mode & 0o077))
              throw fail('MCP_NATIVE_UNAVAILABLE');
            const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
            if (receipt.sessionId !== config.sessionId || receipt.nativeSessionId !== id || receipt.pid !== process.pid)
              throw fail('MCP_NATIVE_ID_CHANGED');
            identity({ nativeSessionId: id });
          }
          legacyPollersRetired += retireLegacyPoller({ expectedMatches: fresh || knownPatchedReload ? 0 : 1 });
          bootstrapStates.set(config.sessionId, { id, pid: process.pid, shutdown: false });
        }
        await listen();
      }
      if (event === 'mcp_servers_change') epoch++;
      if (event === 'before_agent_start') { epoch++; pendingInput = true; }
      if (event === 'session_shutdown') {
        stopped = true;
        epoch++;
        if (server) server.close();
        const bootstrap = bootstrapStates.get(config.sessionId);
        if (bootstrap) bootstrap.shutdown = true;
        try {
          const stat = fs.lstatSync(socketPath);
          if (socketIdentity && stat.ino === socketIdentity.ino && stat.dev === socketIdentity.dev) fs.unlinkSync(socketPath);
        } catch {}
      }
      await current.emit(payload, ctx);
    });
  }
  for (const [name, command] of current.commands) {
    pi.registerCommand(name, { ...command, handler: async (...args) => {
      if (refreshing) return args[1]?.ui?.notify('SESSION_BUSY', 'warning');
      return current.commands.get(name).handler(...args);
    } });
  }
  return { request: invoke, socketPath };
}

module.exports = { createController, install: createController, retireLegacyPoller, LEGACY_POLLER_SHA256 };
