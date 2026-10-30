// cli-runtime/versions.json is the single source of the bundled Omnigent
// plugin, Omnigent CLI, Claude Code and Codex versions. The package locks, the
// hash-locked Omnigent requirements and the reminder patch's validated version
// must agree with it, and the Dockerfile, CI and image smoke must read it
// rather than repeat it.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const pins = JSON.parse(read('cli-runtime/versions.json'));
const SEMVER = /^\d+\.\d+\.\d+$/;
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const mentions = (text, literal) => new RegExp(`(?<![\\w.])${escape(literal)}(?![\\w.])`).test(text);

test('versions.json pins exact versions and an immutable plugin release', () => {
  for (const name of ['omnigentPlugin', 'omnigent', 'claude', 'codex']) assert.match(pins[name]?.version ?? '', SEMVER, `${name}.version`);
  const { version, url, sha256 } = pins.omnigentPlugin;
  assert.equal(url, `https://github.com/WOOWTECH/pi-omnigent-plugin/releases/download/v${version}/woowtech-pi-omnigent-plugin-${version}.tgz`);
  assert.match(sha256, /^[0-9a-f]{64}$/);
});

test('the Claude Code and Codex package locks install the pinned versions', () => {
  for (const [name, pkg] of [['claude', '@anthropic-ai/claude-code'], ['codex', '@openai/codex']]) {
    const manifest = JSON.parse(read(`cli-runtime/${name}/package.json`));
    const lock = JSON.parse(read(`cli-runtime/${name}/package-lock.json`));
    assert.equal(manifest.dependencies[pkg], pins[name].version, `cli-runtime/${name}/package.json`);
    assert.equal(lock.packages[''].dependencies[pkg], pins[name].version, `cli-runtime/${name}/package-lock.json root`);
    assert.equal(lock.packages[`node_modules/${pkg}`].version, pins[name].version, `cli-runtime/${name}/package-lock.json ${pkg}`);
  }
});

test('the hash-locked Omnigent requirements and the reminder patch gate use the pinned CLI', () => {
  const version = escape(pins.omnigent.version);
  assert.match(read('cli-runtime/omnigent/requirements.in'), new RegExp(`^omnigent==${version}$`, 'm'));
  assert.match(read('cli-runtime/omnigent/requirements.lock'), new RegExp(`^omnigent==${version} \\\\$`, 'm'));
  assert.match(read('patches/omnigent-reminder-patch/omnigent-reminder-patch.py'), new RegExp(`^EXPECTED_VERSION = "${version}"$`, 'm'),
    'revalidate the reminder patch anchors before moving the Omnigent CLI');
});

test('the Dockerfile, CI and image checks read the pins instead of repeating them', () => {
  const literals = [pins.omnigentPlugin.version, pins.omnigentPlugin.sha256, pins.omnigent.version, pins.claude.version, pins.codex.version];
  for (const file of ['Dockerfile', '.github/workflows/build.yml', 'tests/omnigent-image-smoke.mjs', 'tests/cli-image-layers.mjs']) {
    const text = read(file);
    for (const literal of literals) assert.equal(mentions(text, literal), false, `${file} repeats ${literal}; read cli-runtime/versions.json`);
  }
  const dockerfile = read('Dockerfile');
  assert.match(dockerfile, /^COPY cli-runtime\/versions\.json \/tmp\/versions\.json$/m, 'the pins stage reads versions.json');
  assert.match(dockerfile, /^COPY cli-runtime\/versions\.json \/usr\/local\/share\/woow-ha-pi-agent\/versions\.json$/m,
    'the image smoke reads the pins the image was built from');
});
