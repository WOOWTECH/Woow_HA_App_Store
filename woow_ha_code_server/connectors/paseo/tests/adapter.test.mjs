import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { handle, allowedActions, normalizeRequest } from '../index.mjs';
import { locations, readState, updateState, withRuntimeLock, processIdentity } from '../src/state.mjs';
import { configureProviders, resolveProviderLaunchers, providerEnvironment } from '../src/provider-launchers.mjs';
import { chatResult, latestAssistantCursor } from '../src/chat-result.mjs';
import { applyVerifiedModel, statusPhase } from '../src/runtime.mjs';
import { runProcess } from '../src/process.mjs';
import { requireSystemTools } from '../src/system-tools.mjs';
import { patchClaudeRootSource } from '../src/claude-root-patch.mjs';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'woow-paseo-test-'));
  const settings = { WOOW_CONNECTOR_DATA_DIR: path.join(root, 'connectors'), WOOW_PASEO_RUNTIME_DIR: path.join(root, 'missing-runtime'), PI_AGENT_DATA_DIR: path.join(root, 'agents') };
  const before = Object.fromEntries(Object.keys(settings).map(key => [key, process.env[key]]));
  Object.assign(process.env, settings);
  t.after(() => {
    for (const [key, value] of Object.entries(before)) value === undefined ? delete process.env[key] : process.env[key] = value;
    fs.rmSync(root, { recursive: true, force: true });
  });
  return root;
}

test('installed runtime without configuration is not reported as uninstalled', () => {
  assert.equal(statusPhase({}, true, false), 'not_configured');
  assert.equal(statusPhase({ settings: { cwd: '/workspace' } }, true, false), 'not_started');
  assert.equal(statusPhase({}, false, false), 'not_installed');
  assert.equal(statusPhase({ phase: 'running' }, true, false), 'stopped');
  assert.equal(statusPhase({ phase: 'disabled' }, true, false), 'disabled');
});

test('Linux provider probes require procps ps before starting a daemon', async () => {
  const common = { platform: 'linux', discover: name => '/usr/bin/' + name };
  await assert.rejects(requireSystemTools({ ...common, discover: name => name === 'ps' ? null : '/usr/bin/' + name }), { code: 'PROCPS_REQUIRED' });
  await assert.rejects(requireSystemTools({ ...common, run: async () => 'BusyBox ps' }), { code: 'PROCPS_REQUIRED' });
  await requireSystemTools({ ...common, run: async () => 'ps from procps-ng 4.0.2' });
});

test('Claude root compatibility patch rejects unknown upstream source', () => {
  assert.throws(() => patchClaudeRootSource('allowDangerouslySkipPermissions: true,'), { code: 'CLAUDE_ROOT_SOURCE_MISMATCH' });
});

test('fresh status and periodic restore neither write state nor start/install runtime', async t => {
  const root = fixture(t);
  assert.equal(allowedActions.includes('restore'), true);
  const status = await handle({ action: 'status' });
  assert.equal(status.ok, true);
  assert.equal(status.online, false);
  assert.equal(status.chatVerified, false);
  assert.equal(status.installed, false);
  assert.equal(status.state, undefined);
  assert.equal((await handle({ action: 'restore' })).restored, false);
  assert.deepEqual(fs.readdirSync(root), []);
});

test('configuration does not enable connection, and explicit stop survives restore', async t => {
  const root = fixture(t);
  const configured = await handle({ action: 'configure', workspace: root, hostName: 'QA code-server', port: 27669 });
  assert.equal(configured.ok, true);
  assert.equal(configured.enabled, false);
  assert.equal(configured.settings.cwd, root);
  assert.equal(configured.settings.displayName, 'QA code-server');
  assert.equal((await handle({ action: 'restore' })).restored, false);
  updateState({ desiredEnabled: true });
  const stopped = await handle({ action: 'stop' });
  assert.equal(stopped.enabled, false);
  assert.equal((await handle({ action: 'restore' })).restored, false);
  assert.equal(readState().desiredEnabled, false);
  assert.equal(fs.statSync(path.join(locations().stateDir, 'state.json')).mode & 0o777, 0o600);
});

test('missing runtime, invalid fields, and unknown actions produce stable private errors', async t => {
  fixture(t);
  for (const [request, code] of [
    [{ action: 'start' }, 'RUNTIME_MISSING'],
    [{ action: 'configure', port: 80 }, 'INVALID_PORT'],
    [{ action: 'configure', displayName: 'bad\nsecret' }, 'INVALID_DISPLAY_NAME'],
    [{ action: 'chat', timeoutMs: '600000' }, 'INVALID_TIMEOUT'],
    [{ action: 'verify', providers: ['pi', 'pi'] }, 'INVALID_PROVIDER'],
    [{ action: 'execute-shell', password: 'SHOULD_NOT_LEAK' }, 'INVALID_ACTION'],
  ]) {
    const result = await handle(request);
    assert.equal(result.ok, false);
    assert.equal(result.error.code, code);
    assert.doesNotMatch(JSON.stringify(result), /SHOULD_NOT_LEAK|bad\nsecret/);
  }
});

test('all providers reuse the deployment homes and missing providers never trigger installation', async () => {
  const loc = { home: '/home/runtime', dataDir: '/deployment/agents', agentDir: '/deployment/pi' };
  const env = { PATH: '/bin', CODEX_HOME: '/private/codex', CLAUDE_CONFIG_DIR: '/private/claude', PI_CODING_AGENT_DIR: '/private/pi', PI_AGENT_DATA_DIR: '/private/shared' };
  const runs = [];
  const launchers = await resolveProviderLaunchers(loc, { env, discover: name => name === 'pi' ? '/usr/bin/pi' : null, run: async (command, args, options) => {
    runs.push({ command, args, options }); return '0.99.1';
  } });
  assert.deepEqual(runs.map(row => row.args), [['--version']]);
  assert.equal(launchers.claude.startup, 'missing');
  const config = configureProviders({ opencode: { enabled: true }, pi: { env: { TOKEN: 'old-private-token' } } }, launchers, loc, env);
  assert.equal(config.opencode, undefined);
  assert.equal(config.pi.env.TOKEN, undefined);
  for (const provider of ['claude', 'codex', 'pi']) {
    for (const key of ['CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'PI_CODING_AGENT_DIR', 'PI_AGENT_DATA_DIR']) assert.equal(config[provider].env[key], env[key]);
  }
  assert.equal(providerEnvironment(loc, {}).CODEX_HOME, '/deployment/agents/codex');
});

test('Claude updater is disabled in discovery and explicit SDK child configuration', async () => {
  const loc = { home: '/home/runtime', dataDir: '/deployment/agents', agentDir: '/deployment/pi' };
  const env = { DISABLE_AUTOUPDATER: '0', CLAUDE_CONFIG_DIR: '/private/claude' };
  const launches = [];
  const launchers = await resolveProviderLaunchers(loc, { env, discover: provider => provider === 'claude' ? '/usr/bin/claude' : null, run: async (_command, _args, options) => { launches.push(options.env); return '2.1.285'; } });
  assert.equal(launches[0].DISABLE_AUTOUPDATER, '1');
  const configured = configureProviders({}, launchers, loc, env);
  assert.equal(configured.claude.env.DISABLE_AUTOUPDATER, '1');
  assert.equal(configured.claude.env.CLAUDE_CONFIG_DIR, '/private/claude');
  assert.equal(configured.claude.command[0], '/usr/bin/claude');
});

test('verify does not report ok when a selected provider cannot answer', async t => {
  fixture(t);
  const result = await handle({ action: 'verify', provider: 'pi', timeoutMs: 1000 });
  assert.equal(result.ok, false);
  assert.equal(result.requestedPassed, false);
  assert.equal(result.passed, false);
  assert.equal(result.error.code, 'MODEL_VERIFICATION_FAILED');
  assert.equal(result.providers[0].code, 'RUNTIME_MISSING');
});

test('extension engine/model selection maps to exactly the requested provider and model', async t => {
  fixture(t);
  const request = normalizeRequest({ action: 'verify', engine: 'pi', model: 'provider/selected-model' });
  assert.equal(request.provider, 'pi');
  assert.deepEqual(request.models, { pi: 'provider/selected-model' });
  assert.equal(normalizeRequest({ action: 'models', engine: 'claude-code' }).provider, 'claude');
  assert.throws(() => normalizeRequest({ action: 'verify', engine: 'pi', provider: 'codex' }), { code: 'PROVIDER_SELECTION_CONFLICT' });
  assert.throws(() => normalizeRequest({ action: 'verify', engine: 'pi', model: 'requested', models: { pi: 'different' } }), { code: 'MODEL_SELECTION_CONFLICT' });
  const result = await handle({ action: 'verify', engine: 'pi', model: 'provider/selected-model', timeoutMs: 1000 });
  assert.deepEqual(result.providers.map(row => row.provider), ['pi']);
  assert.equal(result.ok, false);
});

const message = (seq, type, text) => ({ seqStart: seq, seqEnd: seq, turnId: `turn-${seq}`, timestamp: String(seq), item: { type, text } });
const client = entries => ({ waitForFinish: async () => ({ status: 'idle' }), fetchAgentTimeline: async () => ({ entries }) });

test('user echo and a previous assistant reply cannot satisfy chat verification', async () => {
  const prior = [message(1, 'assistant_message', 'old marker')];
  const result = await chatResult(client([...prior, message(2, 'user_message', 'new marker')]), 'id', 'pi', 'model', 1000, latestAssistantCursor(prior));
  assert.equal(result.status, 'error');
  assert.equal(result.reply, '');
  const success = await chatResult(client([message(3, 'assistant_message', 'new marker')]), 'id', 'pi', 'model', 1000, latestAssistantCursor(prior));
  assert.equal(success.status, 'completed');
});

test('quota and auth text are classified as failure, not successful assistant replies', async () => {
  for (const [text, code] of [["You've hit your weekly limit", 'PROVIDER_QUOTA_EXHAUSTED'], ['Please log in', 'PROVIDER_AUTH_REQUIRED']]) {
    const result = await chatResult(client([message(1, 'assistant_message', text)]), 'id', 'claude', 'model', 1000);
    assert.equal(result.status, 'error'); assert.equal(result.code, code);
  }
});

test('model selection requires the live model and cannot confirm an echoed config', async () => {
  const fake = { setAgentModel: async () => {}, fetchAgent: async () => ({ agent: { model: 'requested', config: { model: 'requested' }, runtimeInfo: { model: 'old' } } }) };
  await assert.rejects(applyVerifiedModel(fake, 'id', 'requested', { waitMs: 0 }), { code: 'MODEL_SELECTION_UNCONFIRMED' });
  fake.fetchAgent = async () => ({ agent: { runtimeInfo: { model: 'requested' } } });
  assert.equal((await applyVerifiedModel(fake, 'id', 'requested')).runtimeInfo.model, 'requested');
});

test('runtime mutations serialize, and lock identity includes kernel boot identity', async t => {
  fixture(t);
  assert.match(processIdentity(process.pid), /^[a-f0-9-]{36}:\d+$/);
  const order = [];
  await Promise.all([withRuntimeLock(async () => { order.push('start'); await new Promise(resolve => setTimeout(resolve, 80)); order.push('finish'); }), withRuntimeLock(async () => { order.push('next'); })]);
  assert.deepEqual(order, ['start', 'finish', 'next']);
});

test('subprocess timeouts and failures do not expose child output', async () => {
  await assert.rejects(runProcess(process.execPath, ['-e', 'console.error("secret-value");setTimeout(()=>{},10000)'], { timeoutMs: 50 }), error => error.code === 'COMMAND_TIMEOUT' && !error.message.includes('secret-value'));
  await assert.rejects(runProcess(process.execPath, ['-e', 'console.error("secret-value");process.exit(1)']), error => error.code === 'COMMAND_FAILED' && !error.message.includes('secret-value'));
});
