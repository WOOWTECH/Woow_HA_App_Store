// Runs in the built image with network disabled. These are real package, SDK,
// CLI and static-client imports; no provider login or paid chat is performed.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
const agentDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ha-paseo-image-'));
try {
  process.env.HOME = path.join(agentDir, 'home'); fs.mkdirSync(process.env.HOME);
  process.env.PI_CODING_AGENT_DIR = agentDir;
  process.env.PI_PASEO_RUNTIME_DIR = '/opt/woow/paseo-runtime';
  const lifecycle = await import('/usr/local/lib/pi-paseo-ha/lifecycle.mjs');
  await lifecycle.prepareImage(); assert.equal(lifecycle.seed().seeded, true);
  const plugin = await lifecycle.loadPlugin();
  assert.equal(plugin.version, '0.1.9'); assert.equal(plugin.enabled, true);
  const { ensureOnboarding } = await import('/opt/woow/pi-paseo-plugin/src/onboarding.mjs');
  const first = await ensureOnboarding(plugin.hooks.createOnboarding);
  const second = await ensureOnboarding(plugin.hooks.createOnboarding);
  assert.ok(first.sessionId); assert.equal(first.sessionId, second.sessionId);
  const sessions = fs.readdirSync(path.join(agentDir, 'sessions'), { recursive: true }).filter(file => file.endsWith('.jsonl'));
  assert.equal(sessions.length, 1, 'onboarding persists once without a model account');
  const { locations } = await import('/opt/woow/pi-paseo-plugin/src/state.mjs');
  const layout = await import('/opt/woow/pi-paseo-plugin/src/runtime-layout.mjs');
  assert.equal(layout.runtimeReady(locations()), true);
  const cli = path.join(layout.runtimeDirectory(locations()), 'node_modules/@getpaseo/cli/bin/paseo');
  assert.equal(execFileSync(process.execPath, [cli, '--version'], { encoding: 'utf8' }).trim(), '0.11.2');
  const response = await plugin.api.web(new Request('http://localhost/paseo-web/'));
  assert.equal(response.status, 200); assert.match(await response.text(), /\/paseo-web\/_expo/);
  const sdk = JSON.parse(fs.readFileSync('/usr/local/lib/node_modules/@agegr/pi-web/package.json'));
  assert.equal(sdk.version, '0.12.0');
  const settings = path.join(agentDir, 'settings.json'); fs.writeFileSync(settings, '{"packages":[]}');
  assert.equal(lifecycle.seed().seeded, false); assert.equal(await lifecycle.loadPlugin(), null);
  console.log('PASS offline HA image: Paseo 0.1.9, CLI 0.11.2, fixed web, Pi Web 0.12 SDK, registration/removal.');
} finally { fs.rmSync(agentDir, { recursive: true, force: true }); }
