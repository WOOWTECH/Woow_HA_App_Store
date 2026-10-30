// The released Omnigent plugin that the image bundles, driven by the add-on's
// own seed, lifecycle and Settings bridge: seed → loadPlugin → lifecycle →
// status → bridge.read, with no Docker, network, server or login. Runs in the
// required test job long before the image build. Needs:
//   OMNIGENT_PLUGIN_TGZ  the release tarball named in cli-runtime/versions.json
//   PI_WEB_ROOT          official Pi Web 0.12.0 with its production
//                        dependencies; the image links its node_modules into
//                        the plugin, and so does this test.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..');
const pins = JSON.parse(fs.readFileSync(path.join(root, 'cli-runtime/versions.json'), 'utf8'));
const tarball = process.env.OMNIGENT_PLUGIN_TGZ;
const piWeb = process.env.PI_WEB_ROOT;
assert.ok(tarball && piWeb, 'OMNIGENT_PLUGIN_TGZ (the released plugin) and PI_WEB_ROOT (Pi Web with production dependencies) are required');
assert.equal(createHash('sha256').update(fs.readFileSync(tarball)).digest('hex'), pins.omnigentPlugin.sha256,
  'OMNIGENT_PLUGIN_TGZ is the release pinned in cli-runtime/versions.json');
const release = pins.omnigentPlugin.version;
const SERVER = 'https://omnigent.example.test';
const VIEW_KEYS = ['installed', 'active', 'version', 'phase', 'server', 'loginConfirmed', 'host', 'issue', 'engines'];
const ISSUE_KEYS = ['code', 'message', 'hints', 'action'];

/** The add-on's data layout: PI_CODING_AGENT_DIR=/data/pi-agent, HOME inside it, the plugin in /opt. */
function installation(t) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ha-omnigent-contract-')));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const agentDir = path.join(base, 'data/pi-agent'), home = path.join(agentDir, 'home');
  fs.mkdirSync(home, { recursive: true });
  return { base, agentDir, home, stateDir: path.join(agentDir, 'omnigent-plugin'),
    bundle: unpack(path.join(base, 'opt/woow/pi-omnigent-plugin')) };
}
/** Extract the release as the Dockerfile does; `version` marks a different build at the same path. */
function unpack(directory, version) {
  fs.rmSync(directory, { recursive: true, force: true });
  fs.mkdirSync(directory, { recursive: true });
  const result = spawnSync('tar', ['-xzf', tarball, '--strip-components=1', '-C', directory], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  fs.symlinkSync(path.join(piWeb, 'node_modules'), path.join(directory, 'node_modules'));
  if (version) {
    const file = path.join(directory, 'package.json');
    fs.writeFileSync(file, JSON.stringify({ ...JSON.parse(fs.readFileSync(file, 'utf8')), version }, null, 2) + '\n');
  }
  return directory;
}
/** One add-on start in a new process (tests/omnigent-plugin-boot.mjs). */
function start(f, extra = {}) {
  const result = spawnSync(process.execPath, [path.join(root, 'tests/omnigent-plugin-boot.mjs')], {
    encoding: 'utf8', timeout: 60_000,
    // Only node on PATH and no Omnigent CLI: dependency discovery stays offline
    // and never reaches the runner's own tools. The image smoke covers the CLIs.
    env: { PATH: path.dirname(process.execPath), HOME: f.home, PI_CODING_AGENT_DIR: f.agentDir, PI_OMNIGENT_SDK_ROOT: piWeb,
      PI_OMNIGENT_BIN: path.join(f.base, 'no-omnigent'), HA_OMNIGENT_BUNDLE: f.bundle, ...extra },
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout.trim().split('\n').at(-1));
}
/** What a completed Settings → Omnigent connection and model check leave in the plugin state (no secrets). */
function signIn(f) {
  fs.mkdirSync(f.stateDir, { recursive: true, mode: 0o700 });
  const write = (name, value) => fs.writeFileSync(path.join(f.stateDir, name), JSON.stringify(value, null, 2) + '\n', { mode: 0o600 });
  const omnigentHome = path.join(f.home, '.omnigent');
  write('state.json', { phase: 'ready', enabled: true, loginConfirmed: true, server: SERVER, issue: null });
  write('connection.json', { server: SERVER, workspace: f.home, host: { id: 'ha-contract-host', name: 'ha-contract', connected: true },
    installation: { home: f.home, configHome: omnigentHome, dataDir: omnigentHome } });
  write('verification.json', { pi: { engine: 'pi', ok: true, server: SERVER, hostId: 'ha-contract-host',
    reply: 'OMNIGENT_CONNECTION_OK', cleanup: 'stopped' } });
}
const state = f => JSON.parse(fs.readFileSync(path.join(f.stateDir, 'state.json'), 'utf8'));
const receipts = f => ['connection.json', 'verification.json'].map(name => fs.readFileSync(path.join(f.stateDir, name), 'utf8'));
const settingsFile = f => path.join(f.agentDir, 'settings.json');
function assertLoginKept(f, boot, kept) {
  assert.equal(boot.observed.reset, false, 'the lifecycle observation does not revoke the login');
  assert.equal(state(f).loginConfirmed, true);
  assert.deepEqual(receipts(f), kept, 'host proof and verification receipts are untouched');
  assert.equal(boot.view.loginConfirmed, true);
  assert.equal(boot.view.server, SERVER);
  assert.notEqual(boot.view.phase, 'needs-login');
}

test('fresh install: the image registers the released plugin and Settings reads it without a login or setup conversation', t => {
  const f = installation(t);
  const boot = start(f, { HA_CONTRACT_LOAD_EXTENSIONS: '1' });
  assert.deepEqual(boot.seeded, { seeded: true });
  assert.deepEqual(JSON.parse(fs.readFileSync(settingsFile(f), 'utf8')).packages, [f.bundle]);
  assert.equal(boot.root, f.bundle);
  assert.equal(boot.version, release);
  assert.deepEqual(boot.surface, {
    runtime: { status: 'function', catalog: 'function', initialize: 'function', verify: 'function', disconnect: 'function',
      observeLifecycle: 'function', enabled: 'function', resumeAuthorizedHost: 'function' },
    web: { loadPiSdk: 'function', packageLifecycle: 'function', watchPackageLifecycle: 'function', webLocations: 'function' },
    bootCommand: true,
  }, 'every entry point the launcher, bridge and image smoke call');
  assert.deepEqual(boot.extensions.errors, []);
  assert.ok(boot.extensions.paths.includes(path.join(f.bundle, 'extensions/index.ts')), 'the Pi SDK loads the registered extension');
  assert.equal(boot.lifecycle.active, true);
  assert.equal(boot.lifecycle.registered, true);
  assert.equal(boot.lifecycle.reason, 'native-plugin-enabled');
  assert.equal(boot.enabled, true);
  assert.deepEqual(Object.keys(boot.view), VIEW_KEYS, 'the bridge projects only the safe Settings view');
  // A status issue reaches the page as fixed fields only, never the plugin's details.
  if (boot.view.issue !== null) assert.deepEqual(Object.keys(boot.view.issue), ISSUE_KEYS);
  assert.equal(boot.view.installed, true);
  assert.equal(boot.view.active, true);
  assert.equal(boot.view.version, release);
  assert.equal(boot.view.loginConfirmed, false);
  assert.equal(boot.view.server, null);
  assert.equal(boot.view.host.connected, false);
  assert.notEqual(boot.view.phase, 'ready');
  assert.deepEqual(boot.view.engines.map(engine => engine.key), ['claude', 'codex', 'pi']);
  assert.equal(fs.existsSync(path.join(f.stateDir, 'onboarding.json')), false, 'no setup conversation state');
  assert.equal(fs.existsSync(path.join(f.agentDir, 'sessions')), false, 'no conversation is created');
  assert.equal(fs.existsSync(path.join(f.home, '.omnigent')), false, 'no Omnigent login is written');
  const again = start(f);
  assert.deepEqual(again.seeded, { seeded: false, reason: 'already-considered' }, 'a restart leaves the package list alone');
});

test('the image Omnigent CLI is the version the released plugin installs', async t => {
  const f = installation(t);
  const { DEPENDENCY_VERSIONS } = await import(pathToFileURL(path.join(f.bundle, 'src/installer.mjs')).href);
  assert.equal(DEPENDENCY_VERSIONS.omnigent, pins.omnigent.version,
    'bump cli-runtime/versions.json omnigent, its requirements lock and the reminder patch gate together with the plugin');
});

test('same-path image upgrade keeps the confirmed login, host proof and verification receipts', t => {
  const f = installation(t);
  start(f);
  signIn(f);
  const first = start(f);
  assertLoginKept(f, first, receipts(f));
  assert.equal(state(f).nativeActive, true);
  const kept = receipts(f), packages = fs.readFileSync(settingsFile(f), 'utf8');
  // An add-on update replaces /opt/woow/pi-omnigent-plugin in place; /data persists.
  unpack(f.bundle, `${release}-next`);
  const upgraded = start(f);
  assert.equal(upgraded.root, f.bundle);
  assert.equal(upgraded.version, `${release}-next`, 'the restart runs the new build');
  assert.deepEqual(upgraded.seeded, { seeded: false, reason: 'already-considered' });
  assert.equal(fs.readFileSync(settingsFile(f), 'utf8'), packages, 'the package registration is unchanged');
  assert.equal(upgraded.lifecycle.reason, 'native-plugin-enabled');
  assert.equal(upgraded.observed.changed, false);
  assertLoginKept(f, upgraded, kept);
  assert.equal(upgraded.view.version, `${release}-next`);
});

// The add-on launcher and Settings bridge always re-resolve the registered
// package. A Pi Web session that loaded the extension from the previous root
// judges registration by its own path; that plugin-side behavior is outside
// this contract and is not exercised here.
test('a plugin source switch between the image bundle and a git install keeps the login in the launcher and Settings', t => {
  const f = installation(t);
  start(f);
  signIn(f);
  start(f);
  const kept = receipts(f);
  // `pi install git:…` checks out under <agent dir>/git/<host>/<path>.
  const git = `git:github.com/WOOWTECH/pi-omnigent-plugin@v${release}`;
  const checkout = unpack(path.join(f.agentDir, 'git/github.com/WOOWTECH/pi-omnigent-plugin'), `${release}-git`);
  for (const [source, directory, version] of [[git, checkout, `${release}-git`], [f.bundle, f.bundle, release]]) {
    const settings = JSON.parse(fs.readFileSync(settingsFile(f), 'utf8'));
    fs.writeFileSync(settingsFile(f), JSON.stringify({ ...settings, packages: [source] }, null, 2) + '\n');
    const boot = start(f);
    assert.equal(boot.root, directory, `${source} is the plugin that runs`);
    assert.equal(boot.version, version);
    assert.equal(boot.lifecycle.active, true);
    assert.equal(boot.lifecycle.source, source);
    assertLoginKept(f, boot, kept);
    assert.equal(boot.view.version, version);
  }
});
