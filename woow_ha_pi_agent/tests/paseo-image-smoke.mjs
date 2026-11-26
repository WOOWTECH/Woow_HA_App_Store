// Runs in the built image with network disabled. These are real package, SDK
// and CLI imports; no provider login or paid chat is performed. The expected
// versions are the pins the image was built from (cli-runtime/versions.json).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { verifyNativeRuntime } from './paseo-native-runtime.mjs';
const pins = JSON.parse(fs.readFileSync('/usr/local/share/woow-ha-pi-agent/versions.json', 'utf8')).agentConnect;
const agentDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ha-paseo-image-'));
try {
  process.env.HOME = path.join(agentDir, 'home'); fs.mkdirSync(process.env.HOME);
  process.env.PI_CODING_AGENT_DIR = agentDir;
  process.env.PI_PASEO_RUNTIME_DIR = '/opt/woow/paseo-runtime';
  const lifecycle = await import('/usr/local/lib/pi-paseo-ha/lifecycle.mjs');
  assert.equal(lifecycle.seed().seeded, true);
  const plugin = await lifecycle.loadPlugin();
  assert.equal(plugin.version, pins.version); assert.equal(plugin.enabled, true);
  assert.equal(plugin.hooks, undefined, 'image bridge must not offer conversation creation');
  const sessionsDir = path.join(agentDir, 'sessions');
  const sessions = fs.existsSync(sessionsDir) ? fs.readdirSync(sessionsDir, { recursive: true }).filter(file => file.endsWith('.jsonl')) : [];
  assert.equal(sessions.length, 0, 'image registration must not create a conversation');
  const { locations } = await import('/opt/woow/pi-paseo-plugin/src/state.mjs');
  const layout = await import('/opt/woow/pi-paseo-plugin/src/runtime-layout.mjs');
  assert.equal(layout.runtimeReady(locations()), true);
  // The runtime arrives as two image layers; the one that holds the Claude SDK's platform package must be there too.
  const sdkScope = path.join(layout.runtimeDirectory(locations()), 'node_modules/@anthropic-ai');
  assert.equal(fs.existsSync(path.join(sdkScope, `claude-agent-sdk-linux-${process.arch}`)), true, 'the layer with the Claude SDK platform package is part of the image');
  assert.equal(fs.existsSync(path.join(sdkScope, `claude-agent-sdk-linux-${process.arch}-musl`)), false, 'no musl copy');
  // The launcher's runtime choice with this plugin and this image's runtime. A runtime saved in the home directory by an earlier
  // version holds earlier releases only, and the plugin would download its own (about 0.7 GB) at the first start of this image.
  // The launcher gives it the ready runtime in the image instead, as it does on a fresh home.
  const { chooseRuntimeDir, BUNDLED_RUNTIME } = await import('/usr/local/lib/pi-paseo-ha/runtime-dir.mjs');
  assert.equal(BUNDLED_RUNTIME, process.env.PI_PASEO_RUNTIME_DIR);
  const choice = () => chooseRuntimeDir({ home: process.env.HOME, pluginRoot: async () => plugin.root });
  assert.equal(await choice(), BUNDLED_RUNTIME, 'a fresh home gets the runtime in the image');
  const savedRuntime = path.join(process.env.HOME, '.local/share/pi-paseo/runtime');
  fs.mkdirSync(path.join(savedRuntime, 'releases', layout.PRIOR_RUNTIME_REVISIONS[0]), { recursive: true });
  assert.equal(layout.runtimeReady({ runtimeDir: savedRuntime }), false, 'an earlier release is no runtime for this plugin');
  assert.equal(await choice(), BUNDLED_RUNTIME, 'a saved runtime with earlier releases only does not hide the image\'s: no download at the first start');
  fs.rmSync(savedRuntime, { recursive: true });
  const native = await verifyNativeRuntime({ bundle: '/opt/woow/pi-paseo-plugin', runtimeDir: process.env.PI_PASEO_RUNTIME_DIR });
  const cli = path.join(layout.runtimeDirectory(locations()), 'node_modules/@getpaseo/cli/bin/paseo');
  assert.equal(execFileSync(process.execPath, [cli, '--version'], { encoding: 'utf8' }).trim(), pins.paseoVersion);
  // No bundled web client: nothing in the image, nothing in the plugin, nothing in its status.
  assert.equal(fs.existsSync('/opt/woow/paseo-web'), false); assert.equal(fs.existsSync('/opt/woow/pi-paseo-plugin/src/web-client.mjs'), false);
  assert.equal(plugin.api.web, undefined, 'the plugin API serves no web client');
  const status = await plugin.api.status();
  assert.equal('webClient' in status, false); assert.equal(status.openUrl, 'https://app.paseo.sh/'); assert.equal(status.settings.target, 'paseo');
  assert.equal(status.settings.agentCollaboration, false, 'agent collaboration stays off unless someone turns it on');
  const sdk = JSON.parse(fs.readFileSync('/usr/local/lib/node_modules/@agegr/pi-web/package.json'));
  assert.equal(sdk.version, '0.12.0');
  const settings = path.join(agentDir, 'settings.json'); fs.writeFileSync(settings, '{"packages":[]}');
  assert.equal(lifecycle.seed().seeded, false); assert.equal(await lifecycle.loadPlugin(), null);
  console.log(`PASS offline HA image: Agent Connect ${pins.version}, Paseo CLI ${pins.paseoVersion} (${pins.runtimeRevision}), both native writers, no bundled web client, Pi Web 0.12 SDK, settings-only registration/removal.`, JSON.stringify(native));
} finally { fs.rmSync(agentDir, { recursive: true, force: true }); }
