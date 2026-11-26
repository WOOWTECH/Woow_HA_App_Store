// The Paseo runtime reaches the image in two layers (patches/split-paseo-runtime.mjs).
// One layer of the whole runtime is about 236 MiB gzip with Paseo 0.17.4, against the
// 256 MiB that tests/assert-image-layer-sizes.mjs allows. Docker COPY cannot exclude a
// subdirectory, so the builder stage makes two trees (hard links) and the final stage
// copies each. These tests use a synthetic runtime shaped like the installed one.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash, randomBytes } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { HEAVY, readTree, layerOf, splitRuntime, verifySplit, mergeLayers } from '../patches/split-paseo-runtime.mjs';

const root = path.resolve(import.meta.dirname, '..');
const script = path.join(root, 'patches/split-paseo-runtime.mjs');
const DESTINATION = '/opt/woow/paseo-runtime';
const NAMES = DESTINATION.split('/').filter(Boolean);
const sha256 = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const at = (out, layer) => path.join(out, layer, ...NAMES);
const keys = map => [...map.keys()].sort();

/** Remove a tree that has read-only directories in it. */
function removeAll(directory) {
  const visit = target => {
    let stat;
    try { stat = fs.lstatSync(target); } catch { return; }
    if (stat.isDirectory()) { fs.chmodSync(target, 0o700); for (const name of fs.readdirSync(target)) visit(path.join(target, name)); }
  };
  visit(directory);
  fs.rmSync(directory, { recursive: true, force: true });
}
function scratch(t) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'sr-'));
  t.after(() => removeAll(base));
  return base;
}
const write = (file, content, mode) => {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content);
  if (mode !== undefined) fs.chmodSync(file, mode);
};
/** A distinctive mtime for every entry (microsecond fractions included), children before their directories. */
function stamp(directory, counter = { n: 0 }) {
  for (const name of fs.readdirSync(directory).sort()) {
    const target = path.join(directory, name), stat = fs.lstatSync(target);
    if (stat.isDirectory()) stamp(target, counter);
    else if (stat.isSymbolicLink()) fs.lutimesSync(target, 1_700_000_000 + ++counter.n * 3.000007, 1_700_000_000 + counter.n * 3.000007);
    else fs.utimesSync(target, 1_700_000_000 + ++counter.n * 3.000007, 1_700_000_000 + counter.n * 3.000007);
  }
  fs.utimesSync(directory, 1_700_000_000 + ++counter.n * 3.000007, 1_700_000_000 + counter.n * 3.000007);
}
/** An installed runtime: <source>/releases/<release>/node_modules with packages, a .bin directory of links and the SDK directory. */
function makeRuntime(t, { release = 'release-one', arch = 'x64', olderRelease = false } = {}) {
  const base = scratch(t);
  const source = path.join(base, 'src', 'paseo-runtime');
  const directory = path.join(source, 'releases', release);
  const modules = path.join(directory, 'node_modules');
  const sdk = path.join(modules, '@anthropic-ai');
  write(path.join(directory, 'package.json'), '{"name":"managed-runtime"}\n', 0o644);
  write(path.join(directory, 'package-lock.json'), '{}\n', 0o644);
  write(path.join(directory, '.pi-paseo-runtime.json'), '{"receipt":true}\n', 0o600);
  write(path.join(modules, '.package-lock.json'), '{}\n');
  write(path.join(modules, '@getpaseo/cli/package.json'), '{"version":"x"}\n');
  write(path.join(modules, '@getpaseo/cli/bin/paseo'), '#!/usr/bin/env node\n', 0o755);
  write(path.join(modules, '@getpaseo/server/dist/server/server/pid-lock.js'), 'export {};\n');
  write(path.join(modules, 'lodash/index.js'), 'module.exports = 1;\n');
  fs.linkSync(path.join(modules, 'lodash/index.js'), path.join(modules, 'lodash/index-copy.js'));
  write(path.join(modules, 'readonly-package/file.txt'), 'read only\n', 0o444);
  fs.mkdirSync(path.join(modules, 'empty-directory'), { mode: 0o750 });
  write(path.join(sdk, 'claude-agent-sdk/package.json'), '{"name":"@anthropic-ai/claude-agent-sdk"}\n');
  write(path.join(sdk, 'claude-agent-sdk/cli.js'), 'export {};\n');
  write(path.join(sdk, 'sdk/package.json'), '{"name":"@anthropic-ai/sdk"}\n');
  const platform = path.join(sdk, `claude-agent-sdk-linux-${arch}`);
  write(path.join(platform, 'package.json'), '{"name":"platform"}\n');
  write(path.join(platform, 'claude'), randomBytes(200 * 1024), 0o755);
  fs.linkSync(path.join(platform, 'claude'), path.join(platform, 'claude-alias'));
  fs.mkdirSync(path.join(platform, 'node_modules/.bin'), { recursive: true });
  fs.symlinkSync('../y', path.join(platform, 'node_modules/.bin/tool'));
  fs.mkdirSync(path.join(modules, '.bin'));
  fs.symlinkSync('../@getpaseo/cli/bin/paseo', path.join(modules, '.bin/paseo'));
  fs.symlinkSync('../@anthropic-ai/claude-agent-sdk/cli.js', path.join(modules, '.bin/claude'));
  fs.symlinkSync('../nowhere', path.join(modules, '.bin/dangling'));
  fs.symlinkSync(path.join(directory, 'package.json'), path.join(modules, 'absolute-link'));
  if (olderRelease) write(path.join(source, 'releases/older/node_modules/@anthropic-ai/leftover/package.json'), '{}\n');
  // Explicit modes: a directory made below a setgid directory would inherit that bit.
  const settle = target => { fs.chmodSync(target, target === path.join(modules, 'empty-directory') ? 0o750 : 0o755); for (const name of fs.readdirSync(target)) if (fs.lstatSync(path.join(target, name)).isDirectory()) settle(path.join(target, name)); };
  settle(source);
  stamp(source);
  fs.chmodSync(path.join(modules, 'readonly-package'), 0o555);
  return { base, source, release: directory, out: path.join(base, 'out'), modules, sdk, platform, heavyRel: `releases/${release}/${HEAVY}` };
}
const split = (f, extra = {}) => splitRuntime({ source: f.source, release: f.release, destination: DESTINATION, outputRoot: f.out, ...extra });
/** Everything verifySplit compares, so two listings can be compared with assert.deepEqual. */
const fingerprint = map => [...map].map(([rel, e]) => [rel, e.type, e.mode, e.uid, e.gid, String(e.size), String(e.mtimeNs), e.type === 'file' ? String(e.ino) : '', e.target]);
/** Run `action`, then put the directory's mtime back: a tamper should leave only the difference it is about. */
const keepTimes = (directory, action) => {
  const stat = fs.statSync(directory, { bigint: true });
  action();
  fs.utimesSync(directory, Number(stat.atimeNs / 1000n) / 1e6, Number(stat.mtimeNs / 1000n) / 1e6);
};

test('every file, symlink and directory is in exactly one layer, and the SDK directory alone is layer b', t => {
  const f = makeRuntime(t);
  const summary = split(f);
  const source = readTree(f.source), a = readTree(at(f.out, 'a')), b = readTree(at(f.out, 'b'));
  const inHeavy = rel => rel === f.heavyRel || rel.startsWith(`${f.heavyRel}/`);
  const leaves = map => new Set([...map].filter(([, entry]) => entry.type !== 'dir').map(([rel]) => rel));
  assert.ok([...a.keys()].every(rel => !inHeavy(rel)), 'layer a holds nothing of the SDK directory');
  assert.ok([...leaves(b)].every(inHeavy) && leaves(b).size > 5, 'layer b holds the SDK directory and nothing else');
  assert.ok([...leaves(a)].every(rel => !leaves(b).has(rel)), 'no file or symlink is in both layers');
  assert.deepEqual([...new Set([...leaves(a), ...leaves(b)])].sort(), [...leaves(source)].sort(), 'together they hold every file and symlink');
  const shared = [...a.keys()].filter(rel => b.has(rel));
  assert.deepEqual(shared.sort(), ['', 'releases', 'releases/release-one', 'releases/release-one/node_modules'], 'only the directories above the SDK directory are in both');
  assert.deepEqual(keys(source), [...new Set([...a.keys(), ...b.keys()])].sort(), 'no directory is lost and none is added');
  assert.equal(summary.layers.a.files + summary.layers.b.files, [...source.values()].filter(entry => entry.type === 'file').length);
  assert.equal(summary.layers.b.bytes, [...b.values()].reduce((sum, entry) => sum + Number(entry.size), 0));
  assert.equal(summary.heavy, f.heavyRel);
  // Above the runtime directory each layer holds the path to it and nothing else.
  for (const layer of ['a', 'b']) assert.deepEqual(fs.readdirSync(path.join(f.out, layer)), ['opt']);
});

test('the files are the installed files; modes, owners and mtimes are as installed', t => {
  const f = makeRuntime(t);
  const before = fingerprint(readTree(f.source));
  split(f);
  const source = readTree(f.source);
  for (const layer of ['a', 'b']) {
    for (const [rel, found] of readTree(at(f.out, layer))) {
      const expected = source.get(rel), where = `${layer}:${rel || '.'}`;
      assert.equal(found.type, expected.type, where); assert.equal(found.mode, expected.mode, `${where} mode`);
      assert.equal(found.uid, expected.uid, where); assert.equal(found.gid, expected.gid, where);
      if (expected.type === 'file') {
        assert.equal(found.ino, expected.ino, `${where} is the installed file`); assert.equal(found.dev, expected.dev, where);
        assert.equal(found.size, expected.size, where); assert.equal(found.mtimeNs, expected.mtimeNs, `${where} mtime`);
        assert.equal(sha256(found.abs), sha256(expected.abs), `${where} bytes`);
      } else {
        const delta = found.mtimeNs - expected.mtimeNs;
        assert.ok((delta < 0n ? -delta : delta) <= 2000n, `${where} mtime ${expected.mtimeNs} against ${found.mtimeNs}`);
      }
    }
  }
  // Spot checks of what the fixture sets, so the comparison above is not vacuous.
  assert.equal(source.get(`${f.heavyRel}/claude-agent-sdk-linux-x64/claude`).mode, 0o755);
  assert.equal(readTree(at(f.out, 'b')).get(`${f.heavyRel}/claude-agent-sdk-linux-x64/claude`).mode, 0o755);
  assert.equal(readTree(at(f.out, 'a')).get('releases/release-one/node_modules/readonly-package').mode, 0o555);
  assert.equal(readTree(at(f.out, 'a')).get('releases/release-one/.pi-paseo-runtime.json').mode, 0o600);
  assert.equal(readTree(at(f.out, 'a')).get('releases/release-one/node_modules/empty-directory').mode, 0o750);
  assert.equal(readTree(at(f.out, 'a')).get('releases/release-one/node_modules/readonly-package/file.txt').mode, 0o444);
  assert.deepEqual(fingerprint(readTree(f.source)), before, 'the installed runtime is not touched');
});

test('symlinks stay symlinks: relative, absolute, dangling and across the layers, never followed', t => {
  const f = makeRuntime(t);
  split(f);
  const a = readTree(at(f.out, 'a')), b = readTree(at(f.out, 'b'));
  const link = (map, rel) => { const entry = map.get(rel); assert.equal(entry?.type, 'symlink', rel); return entry.target; };
  assert.equal(link(a, 'releases/release-one/node_modules/.bin/paseo'), '../@getpaseo/cli/bin/paseo');
  assert.equal(link(a, 'releases/release-one/node_modules/.bin/claude'), '../@anthropic-ai/claude-agent-sdk/cli.js', 'a link in a may point into b');
  assert.equal(link(a, 'releases/release-one/node_modules/.bin/dangling'), '../nowhere');
  assert.equal(link(a, 'releases/release-one/node_modules/absolute-link'), path.join(f.release, 'package.json'));
  assert.equal(link(b, `${f.heavyRel}/claude-agent-sdk-linux-x64/node_modules/.bin/tool`), '../y', 'a dangling link inside b');
  assert.equal(fs.existsSync(path.join(at(f.out, 'a'), 'releases/release-one/node_modules/.bin/claude')), false, 'in layer a alone it dangles');
  assert.equal(fs.lstatSync(path.join(at(f.out, 'a'), 'releases/release-one/node_modules/.bin/claude')).isSymbolicLink(), true);
});

test('copying both layers over each other, as the two COPY steps do, gives the installed runtime back', t => {
  const f = makeRuntime(t);
  split(f);
  const image = path.join(f.base, 'image');
  fs.mkdirSync(image);
  for (const layer of ['a', 'b']) execFileSync('cp', ['-a', `${path.join(f.out, layer)}/.`, image]);
  const copied = readTree(path.join(image, ...NAMES)), source = readTree(f.source);
  assert.deepEqual(keys(copied), keys(source));
  for (const [rel, expected] of source) {
    const found = copied.get(rel), where = rel || '.';
    assert.equal(found.type, expected.type, where);
    assert.equal(expected.type === 'dir' ? found.mode & ~0o2000 : found.mode, expected.mode, `${where} mode (cp -a keeps a setgid bit inherited from the scratch directory)`);
    assert.equal(found.uid, expected.uid, where); assert.equal(found.gid, expected.gid, where);
    if (expected.type === 'file') {
      assert.equal(found.size, expected.size, where); assert.equal(found.mtimeNs, expected.mtimeNs, `${where} mtime`);
      assert.equal(sha256(found.abs), sha256(expected.abs), `${where} bytes`);
    } else if (expected.type === 'symlink') assert.equal(found.target, expected.target, where);
  }
  // Hard links inside one layer stay hard links; the link that crosses the layers now resolves.
  assert.equal(copied.get('releases/release-one/node_modules/lodash/index.js').ino, copied.get('releases/release-one/node_modules/lodash/index-copy.js').ino);
  const platform = `${f.heavyRel}/claude-agent-sdk-linux-x64`;
  assert.equal(copied.get(`${platform}/claude`).ino, copied.get(`${platform}/claude-alias`).ino);
  assert.equal(fs.realpathSync(path.join(image, ...NAMES, 'releases/release-one/node_modules/.bin/claude')), path.join(fs.realpathSync(image), ...NAMES, 'releases/release-one/node_modules/@anthropic-ai/claude-agent-sdk/cli.js'));
  // mergeLayers, the plugin check's view of the same thing, agrees.
  const merged = mergeLayers({ outputRoot: f.out, destination: DESTINATION, target: path.join(f.base, 'merged') });
  assert.deepEqual(keys(readTree(merged)), keys(source));
});

test('it needs no particular release or version: any release directory, any architecture, other releases beside it', t => {
  for (const options of [{ release: 'release-one' }, { release: 'another-release-2', arch: 'arm64' }, { release: 'x', olderRelease: true }]) {
    const f = makeRuntime(t, options);
    const summary = split(f);
    assert.equal(summary.release, `releases/${options.release}`);
    const b = readTree(at(f.out, 'b'));
    assert.ok(b.has(`releases/${options.release}/${HEAVY}/claude-agent-sdk-linux-${options.arch ?? 'x64'}/claude`));
    // A release other than the named one is covered, in layer a, like everything else.
    if (options.olderRelease) assert.ok(readTree(at(f.out, 'a')).has('releases/older/node_modules/@anthropic-ai/leftover/package.json'));
  }
  assert.equal(HEAVY, 'node_modules/@anthropic-ai');
  assert.equal(layerOf('releases/r/node_modules/@anthropic-ai/x', 'releases/r/node_modules/@anthropic-ai'), 'b');
  assert.equal(layerOf('releases/r/node_modules/@anthropic-ai-other', 'releases/r/node_modules/@anthropic-ai'), 'a', 'a name that merely starts alike is not the directory');
});

test('the self-check refuses output that is not an exact split', t => {
  const f = makeRuntime(t);
  split(f);
  const before = readTree(f.source);
  const check = () => verifySplit({ source: before, destination: DESTINATION, outputRoot: f.out, heavyRel: f.heavyRel });
  check();
  const a = at(f.out, 'a'), b = at(f.out, 'b');
  const cases = [
    ['a file is missing from its layer', () => keepTimes(path.join(a, 'releases/release-one/node_modules/lodash'), () => fs.rmSync(path.join(a, 'releases/release-one/node_modules/lodash/index.js'))), /in neither layer/],
    ['a directory is missing', () => keepTimes(path.join(a, 'releases/release-one/node_modules'), () => fs.rmdirSync(path.join(a, 'releases/release-one/node_modules/empty-directory'))), /in neither layer/],
    ['a file is in both layers', () => keepTimes(path.join(b, 'releases/release-one'), () => fs.linkSync(path.join(a, 'releases/release-one/package.json'), path.join(b, 'releases/release-one/package.json'))), /exactly once, found in ab/],
    ['the SDK directory is also in layer a', () => keepTimes(path.join(a, 'releases/release-one/node_modules'), () => fs.mkdirSync(path.join(a, f.heavyRel))), /exactly once, found in ab/],
    ['an extra file is in a layer', () => keepTimes(path.join(b, 'releases/release-one/node_modules'), () => write(path.join(b, 'releases/release-one/node_modules/stray.txt'), 'x')), /not in the installed runtime/],
    ['a file is a copy, not the installed file', () => keepTimes(path.join(a, 'releases/release-one'), () => { const file = path.join(a, 'releases/release-one/package.json'); const bytes = fs.readFileSync(file); fs.rmSync(file); fs.writeFileSync(file, bytes); fs.chmodSync(file, 0o644); }), /not a link to the installed file/],
    ['a directory has another mode', () => fs.chmodSync(path.join(a, 'releases/release-one/node_modules/empty-directory'), 0o700), /mode/],
    ['a symlink has another target', () => keepTimes(path.join(a, 'releases/release-one/node_modules/.bin'), () => { const link = path.join(a, 'releases/release-one/node_modules/.bin/paseo'); fs.rmSync(link); fs.symlinkSync('elsewhere', link); }), /link target/],
    ['something is beside the runtime path', () => fs.mkdirSync(path.join(f.out, 'a', 'usr')), /must hold only/],
    ['a layer is missing altogether', () => removeAll(path.join(f.out, 'b')), /must hold only/],
  ];
  for (const [name, tamper, message] of cases) {
    tamper();
    assert.throws(check, message, name);
    split(f); // idempotent: the same run puts it right again
    check();
  }
});

test('it refuses what it cannot split exactly, before writing anything', t => {
  const refuse = (f, message, extra = {}) => {
    assert.throws(() => split(f, extra), message);
    for (const layer of ['a', 'b']) assert.equal(fs.existsSync(path.join(f.out, layer)), false, `${message}: nothing was written`);
  };
  let f = makeRuntime(t); removeAll(f.sdk); refuse(f, /must be a directory inside the runtime/);
  f = makeRuntime(t); const elsewhere = path.join(f.base, 'elsewhere'); fs.renameSync(f.sdk, elsewhere); fs.symlinkSync(elsewhere, f.sdk); refuse(f, /must be a directory inside the runtime/);
  f = makeRuntime(t); fs.linkSync(path.join(f.modules, 'lodash/index.js'), path.join(f.platform, 'stolen.js')); refuse(f, /Hard links cannot be split across layers/);
  f = makeRuntime(t); execFileSync('mkfifo', [path.join(f.modules, 'pipe')]); refuse(f, /Unsupported file type/);
  f = makeRuntime(t); refuse(f, /outside the runtime/, { outputRoot: path.join(f.source, 'layers') });
  f = makeRuntime(t); refuse(f, /outside the runtime/, { outputRoot: f.base });
  f = makeRuntime(t); refuse(f, /not inside/, { release: path.join(f.base, 'other-release') });
  f = makeRuntime(t); refuse(f, /below the root/, { destination: '/' });
  f = makeRuntime(t); write(path.join(f.out, 'somebody-elses-file'), 'keep'); refuse(f, /not the output of an earlier split/);
  assert.equal(fs.readFileSync(path.join(f.out, 'somebody-elses-file'), 'utf8'), 'keep');
});

test('a split that fails its own check leaves no output behind, and leaves the runtime alone', t => {
  const f = makeRuntime(t);
  const before = fingerprint(readTree(f.source));
  assert.throws(() => split(f, { verify: () => { throw new Error('check failed'); } }), /check failed/);
  assert.deepEqual(fs.readdirSync(f.out), [], 'no layer, no marker');
  assert.deepEqual(fingerprint(readTree(f.source)), before);
  split(f); // and a later good run is not in its way
  assert.deepEqual(fs.readdirSync(f.out).sort(), ['a', 'b', 'split.json']);
});

test('running it again gives the same layers', t => {
  const f = makeRuntime(t);
  const listing = () => ['a', 'b'].map(layer => fingerprint(readTree(at(f.out, layer))));
  const first = split(f), firstListing = listing();
  const second = split(f);
  assert.deepEqual(second, first);
  assert.deepEqual(listing(), firstListing);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(f.out, 'split.json'), 'utf8')), { complete: true, ...first });
  assert.deepEqual(fs.readdirSync(f.out).sort(), ['a', 'b', 'split.json']);
});

// The command the Dockerfile runs: the release directory comes from the plugin's runtime layout.
function stubBundle(base) {
  const bundle = path.join(base, 'bundle');
  write(path.join(bundle, 'src/runtime-layout.mjs'), `import fs from 'node:fs';
import path from 'node:path';
export const runtimeDirectory = loc => path.join(loc.runtimeDir, 'releases', 'stub-revision-9');
export const runtimeReady = loc => {
  if (process.env.STUB_READY_ONLY_AT && loc.runtimeDir !== process.env.STUB_READY_ONLY_AT) return false;
  const release = runtimeDirectory(loc);
  return fs.existsSync(path.join(release, '.pi-paseo-runtime.json')) && fs.existsSync(path.join(release, 'node_modules/@getpaseo/cli/package.json'))
    && fs.existsSync(path.join(release, 'node_modules/@anthropic-ai/claude-agent-sdk-linux-x64/claude'));
};
`);
  return bundle;
}
const run = (args, env = {}) => spawnSync(process.execPath, [script, ...args], { encoding: 'utf8', env: { PATH: process.env.PATH, ...env } });

test('the command takes the release directory from the plugin layout, checks the plugin is ready before and after, and prints a summary', t => {
  const f = makeRuntime(t, { release: 'stub-revision-9' });
  const bundle = stubBundle(f.base);
  const result = run([bundle, f.source, f.out], { STUB_READY_ONLY_AT: '' });
  assert.equal(result.status, 0, result.stderr);
  const summary = JSON.parse(result.stdout);
  assert.equal(summary.release, 'releases/stub-revision-9'); assert.equal(summary.destination, f.source);
  assert.equal(summary.layers.b.files, 6);
  assert.deepEqual(fs.readdirSync(f.out).sort(), ['a', 'b', 'split.json'], 'the merged check tree is removed');
  assert.ok(readTree(path.join(f.out, 'b', f.source)).has(`releases/stub-revision-9/${HEAVY}/claude-agent-sdk-linux-x64/claude`));
});

test('the command refuses a runtime the plugin does not call ready, before or after the split', t => {
  const f = makeRuntime(t, { release: 'stub-revision-9' });
  const bundle = stubBundle(f.base);
  // Not ready to begin with.
  removeAll(path.join(f.release, '.pi-paseo-runtime.json'));
  let result = run([bundle, f.source, f.out]);
  assert.notEqual(result.status, 0); assert.match(result.stderr, /not ready/);
  assert.equal(fs.existsSync(f.out), false);
  // Ready in place, not once merged elsewhere: the layers are removed.
  write(path.join(f.release, '.pi-paseo-runtime.json'), '{}\n');
  result = run([bundle, f.source, f.out], { STUB_READY_ONLY_AT: f.source });
  assert.notEqual(result.status, 0); assert.match(result.stderr, /once both layers are merged/);
  assert.deepEqual(fs.readdirSync(f.out), []);
});

test('with the real plugin layout the release directory is the plugin\'s revision, not a name written here', t => {
  const f = makeRuntime(t);
  const bundle = path.join(f.base, 'plugin');
  fs.mkdirSync(bundle);
  const archive = fs.readdirSync(path.join(root, 'candidate-packages')).find(name => /^woowtech-pi-paseo-.*\.tgz$/.test(name));
  execFileSync('tar', ['-xzf', path.join(root, 'candidate-packages', archive), '--strip-components=1', '-C', bundle]);
  const layout = execFileSync(process.execPath, ['--input-type=module', '-e',
    `const layout = await import(${JSON.stringify(path.join(bundle, 'src/runtime-layout.mjs'))}); console.log(JSON.stringify({ revision: layout.RUNTIME_REVISION, directory: layout.runtimeDirectory({ runtimeDir: '/r' }) }));`], { encoding: 'utf8' });
  const { revision, directory } = JSON.parse(layout);
  assert.equal(directory, `/r/releases/${revision}`);
  // A runtime laid out the way that plugin lays it out splits; the plugin (no receipt here) says it is not ready, so the command stops there.
  const real = makeRuntime(t, { release: revision });
  const result = run([bundle, real.source, real.out]);
  assert.notEqual(result.status, 0); assert.match(result.stderr, /not ready/);
  const summary = split(real);
  assert.equal(summary.release, `releases/${revision}`);
});

test('the Dockerfile copies the runtime in two layers made by the split script, and the SDK directory is its own layer', () => {
  const dockerfile = fs.readFileSync(path.join(root, 'Dockerfile'), 'utf8');
  // Builder: one RUN installs the runtime and then splits it, with the directories the final stage copies from.
  const builder = dockerfile.slice(dockerfile.indexOf('FROM piweb-builder AS paseo-builder'), dockerfile.indexOf('FROM piweb-builder AS shared-runtime-builder'));
  const build = builder.indexOf('node /opt/patches/build-paseo.mjs'), splitting = builder.indexOf('node /opt/patches/split-paseo-runtime.mjs');
  assert.ok(build > 0 && splitting > build, 'the split runs after the runtime is built, in the same RUN');
  assert.equal(builder.slice(build, splitting).includes('\nRUN '), false, 'the same RUN: hard links need the files in the same layer');
  const [, plugin, runtime, outputRoot] = builder.match(/split-paseo-runtime\.mjs (\S+) (\S+) (\S+)/);
  assert.deepEqual([plugin, runtime], ['/opt/woow/pi-paseo-plugin', '/opt/woow/paseo-runtime']);
  // Final stage: exactly the plugin and the two layers come from the builder, in this order, as plain paths.
  const copies = [...dockerfile.matchAll(/^COPY --from=paseo-builder (\S+) (\S+)$/gm)].map(match => [match[1], match[2]]);
  assert.deepEqual(copies, [['/opt/woow/pi-paseo-plugin', '/opt/woow/pi-paseo-plugin'], [`${outputRoot}/a/`, '/'], [`${outputRoot}/b/`, '/']]);
  assert.ok(copies.every(([from, to]) => !/[$*?]/.test(from + to)), 'no variable or wildcard: the Store source-build check refuses substitution');
  assert.equal(dockerfile.includes('COPY --from=paseo-builder /opt/woow/paseo-runtime '), false, 'the runtime is no longer one layer');
  // The directory that is layer b is the one build-paseo.mjs inspects, and the split keeps it apart from the rest.
  assert.ok(fs.readFileSync(path.join(root, 'patches/build-paseo.mjs'), 'utf8').includes(`'${HEAVY}'`));
});
