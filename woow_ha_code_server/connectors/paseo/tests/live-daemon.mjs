// Explicit integration test against a prebuilt runtime. Uses a fresh temporary
// home and no provider credentials, opens only loopback, and cleans up its daemon.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import assert from 'node:assert/strict';
import { handle } from '../index.mjs';
import { readState, updateState } from '../src/state.mjs';

if (!process.env.WOOW_PASEO_RUNTIME_DIR) throw new Error('Set WOOW_PASEO_RUNTIME_DIR to a prebuilt pinned runtime.');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'woow-paseo-live-'));
Object.assign(process.env, {
  HOME: path.join(root, 'home'),
  PI_AGENT_DATA_DIR: path.join(root, 'agents'),
  PI_CODING_AGENT_DIR: path.join(root, 'agents'),
  CLAUDE_CONFIG_DIR: path.join(root, 'agents/claude'),
  CODEX_HOME: path.join(root, 'agents/codex'),
  WOOW_CONNECTOR_DATA_DIR: path.join(root, 'connectors'),
  WOOW_PASEO_PORT: '28669',
  PATH: '/usr/bin:/bin',
});
for (const name of Object.keys(process.env)) if (/TOKEN|PASSWORD|SECRET|API_KEY/.test(name)) delete process.env[name];
for (const directory of [process.env.HOME, process.env.PI_AGENT_DATA_DIR, process.env.CLAUDE_CONFIG_DIR, process.env.CODEX_HOME]) fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
try {
  const fresh = await handle({ action: 'status' });
  assert.equal(fresh.installed, true);
  assert.equal(fresh.phase, 'not_configured');
  assert.equal((await handle({ action: 'restore' })).restored, false);
  const starts = await Promise.all([handle({ action: 'start' }), handle({ action: 'start' })]);
  assert.equal(starts[0].ok, true, JSON.stringify(starts[0]));
  assert.equal(starts[1].ok, true, JSON.stringify(starts[1]));
  assert.equal(starts[0].daemon.reachable, true);
  assert.equal(starts[0].daemon.pid, starts[1].daemon.pid);
  assert.equal(starts[0].chatVerified, false);
  const before = readState().updatedAt;
  const restored = await handle({ action: 'restore' });
  assert.equal(restored.ok, true, JSON.stringify(restored));
  assert.equal(restored.daemon.pid, starts[0].daemon.pid);
  assert.equal(readState().updatedAt, before, 'healthy periodic restore should not rewrite config or state');
  const pair = await handle({ action: 'pair' });
  assert.equal(pair.ok, true, JSON.stringify({ ok: pair.ok, error: pair.error }));
  assert.equal(new URL(pair.url).hostname, 'app.paseo.sh');
  assert.equal(fs.existsSync(path.join(root, 'connectors/paseo/pairing.private.json')), false);
  const status = await handle({ action: 'status' });
  assert.equal(JSON.stringify(status).includes(pair.url), false);
  assert.equal((await handle({ action: 'stop' })).daemon.running, false);
  assert.equal((await handle({ action: 'restore' })).restored, false);
  updateState({ desiredEnabled: true });
  assert.equal((await handle({ action: 'restore' })).daemon.reachable, true);
  process.stdout.write(JSON.stringify({ passed: true, daemonVersion: '0.11.2', concurrentSingleDaemon: true, pairingProduced: true, statePrivate: true, healthyRestoreReadOnly: true, stoppedRestoreRespected: true, enabledRestoreWorks: true, realModelVerified: false }) + '\n');
} finally {
  const stopped = await handle({ action: 'stop' });
  if (!stopped.ok || stopped.daemon.running) throw new Error('LIVE_DAEMON_CLEANUP_FAILED: ' + JSON.stringify(stopped.error || {}));
  fs.rmSync(root, { recursive: true, force: true });
}
