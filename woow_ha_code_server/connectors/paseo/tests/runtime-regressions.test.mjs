import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import * as runtime from '../src/runtime.mjs';
import {locations, readState, updateState, withRuntimeLock} from '../src/state.mjs';

function fixture(t, extra = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-connect-regression-'));
  const settings = {HOME: path.join(root, 'home'), PI_AGENT_DATA_DIR: undefined,
    PI_CODING_AGENT_DIR: path.join(root, 'custom-pi'), WOOW_CONNECTOR_DATA_DIR: path.join(root, 'connectors'),
    WOOW_PASEO_RUNTIME_DIR: path.join(root, 'missing-runtime'), ...extra};
  const before = Object.fromEntries(Object.keys(settings).map(key => [key, process.env[key]]));
  for (const [key, value] of Object.entries(settings)) value === undefined ? delete process.env[key] : process.env[key] = value;
  t.after(() => {
    for (const [key, value] of Object.entries(before)) value === undefined ? delete process.env[key] : process.env[key] = value;
    fs.rmSync(root, {recursive:true,force:true});
  });
  return root;
}

test('provider launch environment keeps deployment homes and strips host login passwords', t => {
  fixture(t, {PASSWORD:'qa-host-password', SUDO_PASSWORD:'qa-sudo-password', HASHED_PASSWORD:'qa-hash',
    PI_WEB_PASSWORD:'qa-web-password', PASEO_PASSWORD:'qa-paseo-password', CLAUDE_CONFIG_DIR:'/custom/claude', CODEX_HOME:'/custom/codex'});
  assert.equal(typeof runtime.inheritedEnv, 'function', 'existing environment export remains available');
  const env = runtime.inheritedEnv();
  for (const key of ['PASSWORD','SUDO_PASSWORD','HASHED_PASSWORD','PI_WEB_PASSWORD','PASEO_PASSWORD']) assert.equal(env[key], undefined, key);
  assert.equal(env.PI_AGENT_DATA_DIR, '/data/pi-agent');
  assert.equal(env.PI_CODING_AGENT_DIR, locations().agentDir);
  assert.equal(env.CLAUDE_CONFIG_DIR, '/custom/claude');
  assert.equal(env.CODEX_HOME, '/custom/codex');
  assert.equal(env.DISABLE_AUTOUPDATER, '1');
});

test('a restore queued before manual stop cannot enable the connection after acquiring its lock', async t => {
  fixture(t);
  updateState({desiredEnabled:true, phase:'running'});
  let entered, release;
  const acquired = new Promise(resolve => entered = resolve);
  const gate = new Promise(resolve => release = resolve);
  const holding = withRuntimeLock(async () => {entered(); await gate;});
  await acquired;
  const pending = runtime.restore();
  // restore() has passed its initial enabled check and is now waiting on our lock.
  await new Promise(resolve => setImmediate(resolve));
  updateState({desiredEnabled:false, phase:'disabled'});
  const stopped = fs.readFileSync(path.join(locations().stateDir, 'state.json'));
  release();
  await holding;
  const result = await pending;
  assert.equal(result.restored, false);
  assert.equal(readState().desiredEnabled, false);
  assert.equal(readState().phase, 'disabled');
  assert.deepEqual(fs.readFileSync(path.join(locations().stateDir, 'state.json')), stopped);
});

test('read-only browser inspector can import the preserved withClient API', async () => {
  assert.equal(typeof runtime.withClient, 'function');
  const inspector = await import('./inspect-local.mjs');
  assert.deepEqual(await inspector.inspect({agentId:'invalid'}), {ok:false,code:'INVALID_AGENT_ID'});
});

test('client access rejects an unowned home before loading or connecting a transport', async t => {
  const root = fixture(t);
  let called = false;
  await assert.rejects(runtime.withClient(() => {called = true;}, 1000, {root:path.join(root,'untrusted-control'),version:'0.17.5'}), {code:'DAEMON_NOT_OWNED'});
  assert.equal(called, false);
  assert.equal(fs.existsSync(path.join(root, 'untrusted-control')), false);
});

test('invalid workspace settings cannot partially switch the connection target', async t => {
  const root = fixture(t);
  await runtime.configure({workspace:root,target:'paseo',hostName:'QA'});
  const before = fs.readFileSync(path.join(locations().stateDir,'preferences.json'));
  const state = fs.readFileSync(path.join(locations().stateDir,'state.json'));
  await assert.rejects(runtime.configure({workspace:path.join(root,'missing'),target:'apporo'}), {code:'INVALID_WORKSPACE'});
  await assert.rejects(runtime.configure({workspace:root,target:'woowtech',hostName:'x'.repeat(101)}), {code:'INVALID_DISPLAY_NAME'});
  await assert.rejects(runtime.configure({workspace:root,target:'apporo',port:80}), {code:'INVALID_PORT'});
  assert.deepEqual(fs.readFileSync(path.join(locations().stateDir,'preferences.json')),before);
  assert.deepEqual(fs.readFileSync(path.join(locations().stateDir,'state.json')),state);
});
