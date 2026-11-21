import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const bundle = process.env.SHARED_RUNTIME_TEST_BUNDLE;
assert.ok(bundle, 'SHARED_RUNTIME_TEST_BUNDLE must contain the verified archive and dependencies');
const native = fs.existsSync('rootfs/bin/pi-agent-shared-session.mjs');
const helpers = native
  ? ['rootfs/bin/pi-agent-share-state.mjs', 'rootfs/bin/pi-agent-shared-session.mjs']
  : [process.env.SHARED_DISTRIBUTION_HELPER || 'rootfs/usr/local/bin/pi-agent-share-state.mjs'];
const json = (file, value) => {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value));
};
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));

for (const helper of helpers) test(`${path.basename(helper)} synchronizes authoritative skills without executing extensions or installing launchers`, t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'sync-only-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const home = path.join(root, 'home'), data = path.join(root, 'data');
  const actual = helper.includes('shared-session') ? path.join(root, 'adopted') : data;
  const pkg = path.join(root, 'package'), bin = path.join(root, 'bin');
  const markers = [];
  const extension = (file, label) => {
    const marker = path.join(root, `${label}.executed`);
    markers.push(marker);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, `import fs from 'node:fs';\nfs.appendFileSync(${JSON.stringify(marker)}, 'import\\n');\nexport default function () { fs.appendFileSync(${JSON.stringify(marker)}, 'activate\\n'); }\n`);
  };
  extension(path.join(pkg, 'extension.ts'), 'package');
  extension(path.join(data, 'extensions/user.ts'), 'global');
  extension(path.join(home, '.pi/extensions/user.ts'), 'project');
  for (const name of ['visible', 'filtered']) {
    const dir = path.join(pkg, 'skills', name);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'SKILL.md'), `---\nname: ${name}\ndescription: Sync authority fixture\n---\nfixture\n`);
  }
  json(path.join(pkg, 'package.json'), { name: 'sync-only-fixture', pi: { extensions: ['./extension.ts'], skills: ['./skills'] } });
  const settings = { packages: [bundle, { source: pkg, skills: ['skills/visible'] }], theme: 'keep' };
  json(path.join(data, 'settings.json'), settings);
  json(path.join(data, 'mcp.json'), { mcpServers: { user: { command: 'unchanged-user-server' } } });
  if (actual !== data) json(path.join(actual, 'settings.json'), { packages: [], theme: 'adopted' });
  json(path.join(actual, 'auth.json'), { credential: 'fixture-only' });
  json(path.join(actual, 'models.json'), { providers: { user: { baseUrl: 'https://example.invalid' } } });
  const auth = fs.readFileSync(path.join(actual, 'auth.json')), models = fs.readFileSync(path.join(actual, 'models.json'));
  json(path.join(home, '.claude.json'), { oauthAccount: { id: 'fixture-only' }, mcpServers: { user: { command: 'keep' } } });
  fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin, 'pi-web'), '#!/bin/sh\nexit 1\n', { mode: 0o755 });
  const env = { ...process.env, HOME: home, PI_AGENT_HOME: path.join(root, 'install'),
    PI_AGENT_DATA_DIR: data, PI_CODING_AGENT_DIR: actual, PI_SHARED_HOME: home,
    PI_SHARED_DATA_DIR: data, PI_SHARED_RUNTIME_BUNDLE_DIR: bundle,
    PI_SHARED_BRIDGE: '0', PI_SHARED_INTERNAL: '0', PATH: `${bin}${path.delimiter}${process.env.PATH}` };
  const run = () => {
    const result = spawnSync(process.execPath, [path.resolve(helper)], { env, cwd: home, encoding: 'utf8', timeout: 30000 });
    assert.equal(result.status, 0, result.stderr);
    for (const marker of markers) assert.equal(fs.existsSync(marker), false, `user extension executed: ${path.basename(marker)}`);
    for (const file of [path.join(home, '.local/bin/pi-web'), path.join(data, 'shared-runtime/host.json'), path.join(data, 'shared-runtime/bootstrap.log')]) {
      assert.equal(fs.existsSync(file), false, `sync installed or bootstrapped a launcher: ${file}`);
    }
    assert.deepEqual(fs.readFileSync(path.join(actual, 'auth.json')), auth);
    assert.deepEqual(fs.readFileSync(path.join(actual, 'models.json')), models);
    assert.equal(read(path.join(data, 'mcp.json')).mcpServers.user.command, 'unchanged-user-server');
    assert.equal(read(path.join(home, '.claude.json')).mcpServers.user.command, 'keep');
  };
  for (let cycle = 0; cycle < 3; cycle++) {
    run();
    assert.deepEqual(read(path.join(data, 'settings.json')), settings);
    for (const destination of ['.claude', '.agents', '.codex']) {
      assert.equal(fs.realpathSync(path.join(home, destination, 'skills/visible')), path.join(pkg, 'skills/visible'));
      assert.equal(fs.existsSync(path.join(home, destination, 'skills/filtered')), false);
      assert.equal(fs.realpathSync(path.join(home, destination, 'skills/shared-host-memory')), path.join(bundle, 'skills/shared-host-memory'));
    }
  }
  // A generated alias must not keep a package skill enabled after its filter changes.
  settings.packages[1].skills = [];
  json(path.join(data, 'settings.json'), settings);
  run();
  for (const destination of ['.claude', '.agents', '.codex']) assert.equal(fs.existsSync(path.join(home, destination, 'skills/visible')), false);
  assert.equal(fs.existsSync(path.join(pkg, 'skills/visible/SKILL.md')), true);
});
