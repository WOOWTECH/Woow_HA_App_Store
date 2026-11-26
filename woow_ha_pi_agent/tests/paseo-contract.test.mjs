// The frozen Agent Connect plugin that the image bundles, driven by the add-on's
// own seed, loader and Settings bridge: the archive's real status(), saveConfig()
// and pairing-link code, with no Docker, network, daemon, login or provider. It
// runs in the required test job long before the image build. Needs:
//   PASEO_PLUGIN_TGZ  the vendored archive named in cli-runtime/versions.json
//   PI_WEB_ROOT       official Pi Web 0.12.0 with its production dependencies;
//                     the image links its node_modules into the plugin, and so
//                     does this test.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { seed, loadPlugin, findPlugin } from '../rootfs/usr/local/lib/pi-paseo-ha/lifecycle.mjs';
import { chooseRuntimeDir } from '../rootfs/usr/local/lib/pi-paseo-ha/runtime-dir.mjs';
import { createPaseoBridge } from '../rootfs/usr/local/lib/pi-paseo-ha/bridge.mjs';
import { connectionTargets, pairUrl } from '../rootfs/usr/local/lib/pi-paseo-ha/ingress.mjs';

const root = path.resolve(import.meta.dirname, '..');
const pins = JSON.parse(fs.readFileSync(path.join(root, 'cli-runtime/versions.json'), 'utf8')).agentConnect;
const tarball = process.env.PASEO_PLUGIN_TGZ;
const piWeb = process.env.PI_WEB_ROOT;
assert.ok(tarball && piWeb, 'PASEO_PLUGIN_TGZ (the frozen plugin) and PI_WEB_ROOT (Pi Web with production dependencies) are required');
assert.equal(createHash('sha256').update(fs.readFileSync(tarball)).digest('hex'), pins.sha256, 'PASEO_PLUGIN_TGZ is the archive pinned in cli-runtime/versions.json');
const SNAPSHOT_KEYS = ['activeTarget', 'configurationPending', 'connectionTargets', 'enabled', 'installed', 'phase', 'providers', 'reachable', 'running', 'selectedTarget', 'settings', 'targetSelectionAvailable', 'version'];

const ENV_KEYS = ['HOME', 'PI_CODING_AGENT_DIR', 'PI_PASEO_RUNTIME_DIR'];
const originalEnv = Object.fromEntries(ENV_KEYS.map(key => [key, process.env[key]]));
/** The add-on's data layout: PI_CODING_AGENT_DIR=/data/pi-agent, HOME inside it, the plugin in /opt. */
function installation(t) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ha-paseo-contract-')));
  const agentDir = path.join(base, 'data/pi-agent'), home = path.join(agentDir, 'home');
  const bundle = path.join(base, 'opt/woow/pi-paseo-plugin'), runtimeDir = path.join(base, 'opt/woow/paseo-runtime');
  for (const directory of [home, bundle, runtimeDir]) fs.mkdirSync(directory, { recursive: true });
  const result = spawnSync('tar', ['-xzf', tarball, '--strip-components=1', '-C', bundle], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  fs.symlinkSync(path.join(piWeb, 'node_modules'), path.join(bundle, 'node_modules'));
  // The plugin reads these at call time; every test starts from the process's own values.
  const env = { HOME: home, PI_CODING_AGENT_DIR: agentDir, PI_PASEO_RUNTIME_DIR: runtimeDir };
  Object.assign(process.env, env);
  t.after(() => {
    for (const [key, value] of Object.entries(originalEnv)) { if (value === undefined) delete process.env[key]; else process.env[key] = value; }
    fs.rmSync(base, { recursive: true, force: true });
  });
  const stateDir = path.join(agentDir, 'pi-paseo');
  return { base, agentDir, home, bundle, stateDir, env,
    preferences: value => {
      fs.mkdirSync(stateDir, { recursive: true, mode: 0o700 });
      fs.writeFileSync(path.join(stateDir, 'preferences.json'), JSON.stringify(value), { mode: 0o600 });
    },
    saved: () => JSON.parse(fs.readFileSync(path.join(stateDir, 'preferences.json'), 'utf8')) };
}
/** One add-on start: seed the bundle, then load it the way the bridge and the lifecycle do. */
async function start(f) {
  assert.equal(seed({ agentDir: f.agentDir, home: f.home, bundle: f.bundle }).seeded, true);
  const plugin = await loadPlugin({ env: f.env, bundle: f.bundle });
  assert.ok(plugin, 'the seeded bundle is found by the add-on loader');
  assert.equal(plugin.enabled, true); assert.equal(plugin.version, pins.version);
  return plugin;
}

test('the real status() has no web client and a default-off agentCollaboration; the bridge reads it and projects only known fields', async t => {
  const f = installation(t);
  const plugin = await start(f);
  assert.equal(plugin.api.web, undefined, 'the host API has no web(): there is no bundled client to serve');
  for (const name of ['status', 'saveConfig', 'pair', 'lifecycle', 'listModels']) assert.equal(typeof plugin.api[name], 'function', name);
  const status = await plugin.api.status();
  assert.equal('webClient' in status, false);
  assert.equal(status.openUrl, 'https://app.paseo.sh/'); assert.equal(status.selectedTarget, 'paseo');
  assert.equal(status.settings.agentCollaboration, false); assert.equal(status.agentCollaboration, false);
  assert.deepEqual(status.connectionTargets.map(({ id, appUrl }) => [id, appUrl]), connectionTargets.map(({ id, appUrl }) => [id, appUrl]),
    'the origins this add-on fixes are the ones the plugin uses');
  const bridge = createPaseoBridge(async () => plugin);
  const read = await bridge.read();
  assert.deepEqual(Object.keys(read).sort(), SNAPSHOT_KEYS);
  assert.deepEqual(read.settings, { target: 'paseo' }); assert.equal(read.targetSelectionAvailable, true); assert.equal(read.version, pins.version);
  assert.ok(!/agentCollaboration|webClient|webReady|installationId/.test(JSON.stringify(read)));
});

test('saving a target through the bridge leaves the plugin\'s saved agentCollaboration and name alone', async t => {
  const f = installation(t);
  f.preferences({ name: 'Kitchen Pi', connection: 'relay', target: 'paseo', agentCollaboration: true });
  const plugin = await start(f);
  const bridge = createPaseoBridge(async () => plugin);
  assert.equal((await plugin.api.status()).settings.agentCollaboration, true, 'the saved choice shows in the plugin status');
  assert.deepEqual((await bridge.read()).settings, { target: 'paseo' }, 'and never in the page status');
  for (const body of [{ action: 'save', target: 'woowtech', agentCollaboration: false }, { action: 'save', agentCollaboration: false }, { action: 'save', target: 'woowtech', name: 'x' }]) {
    await assert.rejects(bridge.act(body), { code: 'INVALID_SETTINGS' }, JSON.stringify(body));
  }
  assert.deepEqual(f.saved(), { name: 'Kitchen Pi', connection: 'relay', target: 'paseo', agentCollaboration: true }, 'refused requests wrote nothing');
  const saved = await bridge.act({ action: 'save', target: 'apporo' });
  assert.equal(saved.selectedTarget, 'apporo'); assert.equal(saved.configurationPending, true);
  assert.deepEqual(f.saved(), { name: 'Kitchen Pi', connection: 'relay', target: 'apporo', agentCollaboration: true });
  assert.equal((await plugin.api.status()).settings.agentCollaboration, true);
  // The same save on a fresh install does not turn collaboration on either.
  const fresh = installation(t);
  const freshBridge = createPaseoBridge(async () => await start(fresh));
  await freshBridge.act({ action: 'save', target: 'woowtech' });
  assert.equal(Object.hasOwn(fresh.saved(), 'agentCollaboration'), false); assert.equal(fresh.saved().target, 'woowtech');
});

test('the pairing links the plugin builds for each target are exactly what the bridge accepts, and the retired client links are not', async t => {
  const f = installation(t);
  const plugin = await start(f);
  const { CONNECTION_TARGETS, targetPairUrl } = await import(pathToFileURL(path.join(f.bundle, 'src/connection-targets.mjs')).href);
  assert.deepEqual(CONNECTION_TARGETS.map(({ id, appUrl, openUrl }) => [id, appUrl, openUrl]), connectionTargets.map(({ id, appUrl }) => [id, appUrl, appUrl + '/']));
  for (const { id, appUrl, relayEndpoint } of CONNECTION_TARGETS) {
    const offer = Buffer.from(JSON.stringify({ v: 2, serverId: 'fixture-server', daemonPublicKeyB64: 'fixture-key', relay: { endpoint: relayEndpoint, useTls: true } })).toString('base64url');
    const link = targetPairUrl(`${appUrl}/#offer=${offer}`, id);
    assert.equal(link, `${appUrl}/#offer=${offer}`, `${id}: the plugin hands out the official site's own link`);
    assert.equal(pairUrl(link, id), link);
    f.preferences({ target: id });
    const bridge = createPaseoBridge(async () => ({ ...plugin, api: { ...plugin.api, pair: async () => ({ url: link, target: id }) } }));
    assert.deepEqual(await bridge.act({ action: 'pair' }), { url: link, target: id });
    for (const other of CONNECTION_TARGETS.filter(row => row.id !== id)) assert.throws(() => targetPairUrl(`${appUrl}/#offer=${offer}`, other.id), { code: /^PAIRING_/ }, `${id} offer for ${other.id}`);
    for (const retired of [`/paseo-web/welcome#offer=${offer}`, `/paseo-web/#offer=${offer}`]) {
      assert.throws(() => targetPairUrl(retired, id), { code: 'PAIRING_ORIGIN_INVALID' });
      const old = createPaseoBridge(async () => ({ ...plugin, api: { ...plugin.api, pair: async () => ({ url: retired, target: id }) } }));
      await assert.rejects(old.act({ action: 'pair' }), { code: 'PAIRING_ORIGIN_INVALID' });
    }
  }
});

test('the launcher asks the registered plugin which runtime serves it; to the real plugin the releases of earlier versions are no runtime', async t => {
  const f = installation(t);
  const plugin = await start(f);
  assert.deepEqual(await findPlugin({ env: f.env, bundle: f.bundle }), { root: plugin.root, enabled: true, version: pins.version },
    'the lookup the launcher makes finds what the lifecycle and the bridge load');
  const layout = await import(pathToFileURL(path.join(plugin.root, 'src/runtime-layout.mjs')).href);
  assert.equal(layout.RUNTIME_REVISION, pins.runtimeRevision);
  assert.equal(typeof layout.runtimeReady, 'function');
  // What an earlier add-on version can have left in a runtime saved in the home: only its own releases, or the layout of the first plugin versions.
  const saved = path.join(f.home, '.local/share/pi-paseo/runtime');
  for (const revision of layout.PRIOR_RUNTIME_REVISIONS) fs.mkdirSync(path.join(saved, 'releases', revision), { recursive: true });
  fs.mkdirSync(path.join(saved, 'node_modules/@getpaseo/cli'), { recursive: true });
  assert.equal(layout.runtimeReady({ runtimeDir: saved }), false, 'the plugin would install its release there: npm ci, about 0.7 GB');
  assert.equal(layout.runtimeReady({ runtimeDir: f.env.PI_PASEO_RUNTIME_DIR }), false, 'this fixture installs no runtime (the image smoke has the real one)');
  assert.equal(await chooseRuntimeDir({ home: f.home, bundled: f.env.PI_PASEO_RUNTIME_DIR, pluginRoot: async () => plugin.root }), saved,
    'with no ready runtime anywhere, what the plugin installs stays in the saved runtime, where it persists');
  fs.rmSync(saved, { recursive: true });
  assert.equal(await chooseRuntimeDir({ home: f.home, bundled: f.env.PI_PASEO_RUNTIME_DIR, pluginRoot: async () => plugin.root }), f.env.PI_PASEO_RUNTIME_DIR, 'a fresh home: the runtime in the image');
});

test('Smart targets refuse protected-only pairing offers while Paseo retains the client security choice', async t => {
  const f = installation(t);
  const plugin = await start(f);
  const { CONNECTION_TARGETS, targetConfiguration, targetPairUrl } = await import(pathToFileURL(path.join(plugin.root, 'src/connection-targets.mjs')).href);
  for (const { id, appUrl, relayEndpoint } of CONNECTION_TARGETS) {
    const config = { daemon: { relay: { requireProtectedSecurity: true } } };
    const selected = targetConfiguration(config, id);
    assert.equal(selected.daemon.relay.requireProtectedSecurity, id === 'paseo');
    assert.equal(config.daemon.relay.requireProtectedSecurity, true, 'the input config is not mutated');
    const offer = Buffer.from(JSON.stringify({ v: 2, serverId: 'fixture-server', daemonPublicKeyB64: 'fixture-key',
      relay: { endpoint: relayEndpoint, useTls: true }, minimumSecurityMode: 'protected' })).toString('base64url');
    const url = `${appUrl}/#offer=${offer}`;
    f.preferences({ target: id });
    const bridge = createPaseoBridge(async () => ({ ...plugin, api: { ...plugin.api,
      pair: async () => ({ url: targetPairUrl(url, id), target: id }) } }));
    if (id === 'paseo') assert.deepEqual(await bridge.act({ action: 'pair' }), { url, target: id });
    else await assert.rejects(bridge.act({ action: 'pair' }), { code: 'PAIRING_SECURITY_UNSUPPORTED' });
  }
});
