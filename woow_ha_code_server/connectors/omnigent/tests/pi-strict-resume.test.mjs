import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { installStrictOpen, verifyHistory, ownerPath, launch } from '../pi_strict_launcher.mjs';

const packageDir = process.env.PI_TEST_PACKAGE;
if (!packageDir) throw Error('PI_TEST_PACKAGE required');
const bundle = pathToFileURL(path.join(packageDir, 'dist/bundle/index.js')).href;
const api = await import(bundle);
assert.equal(api.VERSION, '0.99.1');
function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-cold-'));
  const children = [];
  const trackChild = child => {
    const closed = new Promise(resolve => child.once('close', resolve));
    children.push({ child, closed });
    return closed;
  };
  t.after(async () => {
    for (const { child, closed } of children) {
      if (child.exitCode === null && child.signalCode === null) child.kill();
      const deadline = setTimeout(() => child.kill('SIGKILL'), 3000);
      try { await closed; } finally { clearTimeout(deadline); }
    }
    // No child can still create native config/cache files after close.
    fs.rmSync(dir, { recursive: true, force: true });
  });
  const id = '01234567-89ab-4cde-8f01-23456789abcd';
  const rows = [
    { type: 'session', version: 3, id, cwd: dir, timestamp: '2026-11-10T00:00:00.000Z' },
    { type: 'model_change', id: 'model1', parentId: null, provider: 'openai', modelId: 'gpt-4o' },
    { type: 'message', id: 'user1', parentId: 'model1', message: { role: 'user', content: [{ type: 'text', text: 'original-private-fixture' }], timestamp: 1 } },
    { type: 'message', id: 'assistant1', parentId: 'user1', message: { role: 'assistant', content: [{ type: 'text', text: 'preserved-answer' }], api: 'openai-completions', provider: 'openai', model: 'gpt-4o', usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: 'stop', timestamp: 2 } },
  ];
  const file = path.join(dir, 'original_' + id + '.jsonl');
  const bytes = Buffer.from(rows.map(r => JSON.stringify(r)).join('\n') + '\n');
  fs.writeFileSync(file, bytes, { mode: 0o600 });
  const ticket = { nativeFile: file, nativeSessionId: id, nativeBytes: bytes.length,
    nativeSHA256: crypto.createHash('sha256').update(bytes).digest('hex'), entryCount: rows.length, cwd: dir };
  return { dir, file, bytes, rows, ticket, trackChild };
}

test('actual pinned SessionManager preserves original ID, tree, model and every byte', t => {
  const f = fixture(t), guard = installStrictOpen(api, f.ticket);
  try {
    const manager = api.SessionManager.open(f.file, f.dir);
    assert.equal(guard.opened(), true);
    assert.equal(manager.getSessionId(), f.ticket.nativeSessionId);
    assert.deepEqual(manager.getEntries(), f.rows.slice(1));
    assert.equal(manager.getLeafId(), 'assistant1');
    assert.deepEqual(fs.readFileSync(f.file), f.bytes);
  } finally { guard.restore(); }
});

test('missing, empty, changed, malformed, wrong ID/version and symlink histories refuse without fallback', t => {
  const f = fixture(t);
  for (const data of [Buffer.alloc(0), Buffer.from('{}\n'), Buffer.from(f.bytes.toString().replace('"version":3', '"version":2')), Buffer.from(f.bytes.toString().replace('original-private-fixture', 'changed'))]) {
    fs.writeFileSync(f.file, data);
    const guard = installStrictOpen(api, f.ticket);
    try { assert.throws(() => api.SessionManager.open(f.file, f.dir)); assert.equal(guard.opened(), false); assert.deepEqual(fs.readFileSync(f.file), data); }
    finally { guard.restore(); }
  }
  fs.unlinkSync(f.file);
  assert.throws(() => verifyHistory(f.ticket));
  assert.equal(fs.existsSync(f.file), false);
  const other = path.join(f.dir, 'other'); fs.writeFileSync(other, f.bytes); fs.symlinkSync(other, f.file);
  assert.throws(() => ownerPath(f.file), /UNSAFE_PATH/);
  fs.unlinkSync(f.file); fs.writeFileSync(f.file, f.bytes, { mode: 0o600 });
  assert.throws(() => verifyHistory({ ...f.ticket, nativeSessionId: 'wrong' }), /INVALID_HISTORY/);
  assert.throws(() => installStrictOpen({ ...api, VERSION: '0.100.0' }, f.ticket), /VERSION_UNSUPPORTED/);
});

test('native fresh and migration fallback are blocked inside synchronous open, including a disappearance race', t => {
  const f = fixture(t), actual = api.SessionManager.open;
  for (const operation of ['newSession', '_rewriteFile', 'disappear']) {
    api.SessionManager.open = function(...args) {
      if (operation === 'disappear') { fs.unlinkSync(f.file); return actual.apply(this, args); }
      return api.SessionManager.prototype[operation]();
    };
    const guard = installStrictOpen(api, f.ticket);
    try { assert.throws(() => api.SessionManager.open(f.file, f.dir), /FORBIDDEN/); assert.equal(guard.opened(), false); }
    finally { guard.restore(); api.SessionManager.open = actual; }
    if (operation === 'disappear') { assert.equal(fs.existsSync(f.file), false); fs.writeFileSync(f.file, f.bytes, { mode: 0o600 }); }
    else assert.deepEqual(fs.readFileSync(f.file), f.bytes);
  }
});

test('actual public main RPC uses the same guarded SessionManager and exposes original messages without model call', async t => {
  const f = fixture(t);
  const script = path.join(f.dir, 'main.mjs');
  fs.writeFileSync(script, `import * as api from ${JSON.stringify(bundle)};
import { installStrictOpen } from ${JSON.stringify(new URL('../pi_strict_launcher.mjs', import.meta.url).href)};
const guard=installStrictOpen(api, ${JSON.stringify(f.ticket)});
const timer=setInterval(()=>{if(guard.opened()){process.stderr.write('STRICT_OPENED\\n');clearInterval(timer)}},10);
await api.main(['--mode','rpc','--session',${JSON.stringify(f.file)},'--session-dir',${JSON.stringify(f.dir)},'--no-extensions','--no-skills','--no-prompt-templates','--no-themes','--approve']);`);
  const child = spawn(process.execPath, [script], { cwd: f.dir,
    env: { PATH: process.env.PATH, HOME: f.dir, PI_CODING_AGENT_DIR: path.join(f.dir, 'agent') }, stdio: ['pipe', 'pipe', 'pipe'] });
  const closed = f.trackChild(child);
  let stdout = '', stderr = '';
  child.stdout.on('data', c => { stdout += c; }); child.stderr.on('data', c => { stderr += c; });
  child.stdin.write(JSON.stringify({ type: 'get_state', id: 'state' }) + '\n');
  child.stdin.write(JSON.stringify({ type: 'get_messages', id: 'messages' }) + '\n');
  const until = Date.now() + 15000;
  while (Date.now() < until && !stdout.includes('"id":"messages"')) await new Promise(r => setTimeout(r, 30));
  const lines = stdout.split('\n').flatMap(line => { try { return [JSON.parse(line)]; } catch { return []; } });
  const state = lines.find(x => x.id === 'state'), messages = lines.find(x => x.id === 'messages');
  assert.equal(state?.success, true, 'native RPC must return state');
  assert.equal(state.data.sessionId, f.ticket.nativeSessionId);
  assert.equal(state.data.isStreaming, false);
  assert.equal(messages?.success, true);
  assert.match(JSON.stringify(messages.data), /original-private-fixture/);
  assert.match(JSON.stringify(messages.data), /preserved-answer/);
  assert.match(stderr, /STRICT_OPENED/);
  assert.equal(fs.readFileSync(f.file).subarray(0, f.bytes.length).equals(f.bytes), true);
  child.kill();
  await closed;
});

test('expired preparation and duplicate startup claims fail closed before native startup', async t => {
  const f = fixture(t), bridge = path.join(f.dir, 'bridge'); fs.mkdirSync(bridge, { mode: 0o700 });
  fs.mkdirSync(path.join(bridge, 'inbox')); fs.mkdirSync(path.join(bridge, 'sessions'));
  const file = path.join(bridge, 'sessions', path.basename(f.file)); fs.copyFileSync(f.file, file);
  const config = JSON.stringify({ sessionId: 'test' }); fs.writeFileSync(path.join(bridge, 'config.json'), config, { mode: 0o600 });
  const ticket = { ...f.ticket, nativeFile: file, bridgeDir: bridge, sessionId: 'test', version: 1, expiresAt: 0,
    configSHA256: crypto.createHash('sha256').update(config).digest('hex') };
  const ticketFile = path.join(bridge, 'ticket.json'); fs.writeFileSync(ticketFile, JSON.stringify(ticket), { mode: 0o600 });
  await assert.rejects(launch(ticketFile), /TICKET_EXPIRED/);
  ticket.expiresAt = Date.now() + 10000; fs.writeFileSync(ticketFile, JSON.stringify(ticket), { mode: 0o600 });
  fs.mkdirSync(path.join(bridge, 'woow-pi-cold-active'));
  await assert.rejects(launch(ticketFile), /SESSION_BUSY/);
  assert.deepEqual(fs.readFileSync(file), f.bytes);
});
