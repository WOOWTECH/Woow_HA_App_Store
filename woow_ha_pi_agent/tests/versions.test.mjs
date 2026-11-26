// cli-runtime/versions.json is the single source of the bundled Omnigent
// plugin, Agent Connect, Omnigent CLI, Claude Code and Codex versions. The
// package locks, the hash-locked Omnigent requirements, the reminder patch's
// validated version and the vendored archives' record must agree with it, and
// the Dockerfile, CI and image smoke must read it rather than repeat it.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';

const root = path.resolve(import.meta.dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const pins = JSON.parse(read('cli-runtime/versions.json'));
const SEMVER = /^\d+\.\d+\.\d+$/;
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const mentions = (text, literal) => new RegExp(`(?<![\\w.])${escape(literal)}(?![\\w.])`).test(text);

const tar = (...args) => {
  const result = spawnSync('tar', args, { maxBuffer: 64 * 1024 * 1024 });
  assert.equal(result.status, 0, `tar ${args.join(' ')}: ${result.stderr}`);
  return result.stdout;
};
test('versions.json pins exact versions and the hash-checked frozen plugin archives', () => {
  for (const name of ['omnigentPlugin', 'agentConnect', 'omnigent', 'claude', 'codex']) assert.match(pins[name]?.version ?? '', SEMVER, `${name}.version`);
  const manifest = JSON.parse(read('candidate-packages/manifest.json')).artifacts;
  for (const [name, packageName] of [['omnigentPlugin', 'woowtech-pi-omnigent-plugin'], ['agentConnect', 'woowtech-pi-paseo']]) {
    const { version, archive, sha256, sourceCommit } = pins[name];
    assert.equal(archive, `candidate-packages/${packageName}-${version}.tgz`, name);
    assert.match(sha256, /^[0-9a-f]{64}$/, name);
    assert.match(sourceCommit, /^[0-9a-f]{40}$/, name);
    assert.equal(createHash('sha256').update(fs.readFileSync(path.join(root, archive))).digest('hex'), sha256, name);
    const candidate = manifest.find(row => row.file === path.basename(archive));
    assert.equal(candidate?.sha256, sha256, `${name}: manifest.json`);
    assert.equal(candidate?.sourceCommit, sourceCommit, `${name}: manifest.json`);
  }
  assert.equal(manifest.find(row => row.file === path.basename(pins.agentConnect.archive)).runtimeRevision, pins.agentConnect.runtimeRevision, 'manifest.json');
});

test('the Agent Connect archive is the pinned release: no bundled web client, runtime revision derived from its lockfile', () => {
  const { version, archive, paseoVersion, runtimeRevision } = pins.agentConnect;
  assert.deepEqual(fs.readdirSync(path.join(root, 'candidate-packages')).filter(name => /^woowtech-pi-paseo-.*\.tgz$/.test(name)), [path.basename(archive)],
    'exactly one Agent Connect archive: the Dockerfile COPY matches it by pattern');
  const pkg = JSON.parse(tar('-xzOf', path.join(root, archive), 'package/package.json'));
  assert.equal(pkg.name, '@woowtech/pi-paseo'); assert.equal(pkg.version, version);
  const members = tar('-tzf', path.join(root, archive)).toString().split('\n').filter(Boolean);
  assert.deepEqual(members.filter(member => /web-client/.test(member)), [], 'the bundled web client is gone since 0.1.23');
  for (const member of ['package/src/host-api.mjs', 'package/src/runtime-layout.mjs', 'package/runtime/package-lock.json']) assert.ok(members.includes(member), member);
  // The plugin names its runtime '<paseo version>-r<generation>-<first 12 of the lockfile sha256>'.
  const lock = createHash('sha256').update(tar('-xzOf', path.join(root, archive), 'package/runtime/package-lock.json')).digest('hex');
  assert.match(paseoVersion, SEMVER);
  assert.equal(runtimeRevision.replace(/-r\d+-/, '-r-'), `${paseoVersion}-r-${lock.slice(0, 12)}`);
  const runtime = JSON.parse(tar('-xzOf', path.join(root, archive), 'package/runtime/package.json'));
  assert.equal(runtime.dependencies['@getpaseo/cli'], paseoVersion, 'the daemon the runtime installs');
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
  const { omnigentPlugin, agentConnect } = pins;
  const literals = [omnigentPlugin.version, omnigentPlugin.sha256, pins.omnigent.version, pins.claude.version, pins.codex.version,
    agentConnect.version, agentConnect.sha256, agentConnect.sourceCommit, agentConnect.paseoVersion, agentConnect.runtimeRevision];
  for (const file of ['Dockerfile', '.github/workflows/build.yml', 'tests/omnigent-image-smoke.mjs', 'tests/cli-image-layers.mjs',
    'tests/paseo-image-smoke.mjs', 'tests/paseo-native-runtime.mjs', 'patches/build-paseo.mjs', 'patches/split-paseo-runtime.mjs']) {
    const text = read(file);
    for (const literal of literals) assert.equal(mentions(text, literal), false, `${file} repeats ${literal}; read cli-runtime/versions.json`);
  }
  const dockerfile = read('Dockerfile');
  assert.match(dockerfile, /^COPY cli-runtime\/versions\.json \/tmp\/versions\.json$/m, 'the pins stage reads versions.json');
  assert.match(dockerfile, /^COPY cli-runtime\/versions\.json \/usr\/local\/share\/woow-ha-pi-agent\/versions\.json$/m,
    'the image smoke reads the pins the image was built from');
  // Agent Connect: the pins stage splits the pins; the builder takes the one vendored archive by pattern.
  for (const [pin, key] of [['version', 'version'], ['sha256', 'sha256'], ['runtime-revision', 'runtimeRevision']]) {
    assert.match(dockerfile, new RegExp(`^\\s*pin agent-connect/${pin} \\.agentConnect\\.${key} `, 'm'), `the pins stage reads agentConnect.${key}`);
  }
  assert.match(dockerfile, /^COPY --from=pins \/pins\/agent-connect\/ \/tmp\/pins\/agent-connect\/$/m);
  assert.match(dockerfile, /^COPY candidate-packages\/woowtech-pi-paseo-\*\.tgz \/tmp\/paseo\.tgz$/m, 'one archive, matched by pattern, so a new release needs no Dockerfile edit');
  assert.match(dockerfile, /PI_PASEO_EXPECTED_VERSION="\$\(< \/tmp\/pins\/agent-connect\/version\)"/);
  assert.match(dockerfile, /PI_PASEO_EXPECTED_RUNTIME_REVISION="\$\(< \/tmp\/pins\/agent-connect\/runtime-revision\)"/);
});
