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
const PLUGIN_VERSION = /^\d+\.\d+\.\d+(?:-rc\.\d+)?$/;
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const mentions = (text, literal) => new RegExp(`(?<![\\w.])${escape(literal)}(?![\\w.])`).test(text);

const tar = (...args) => {
  const result = spawnSync('tar', args, { maxBuffer: 64 * 1024 * 1024 });
  assert.equal(result.status, 0, `tar ${args.join(' ')}: ${result.stderr}`);
  return result.stdout;
};
test('versions.json pins exact versions and the hash-checked frozen plugin archives', () => {
  for (const name of ['omnigentPlugin', 'agentConnect']) assert.match(pins[name]?.version ?? '', PLUGIN_VERSION, `${name}.version`);
  for (const name of ['omnigent', 'claude', 'codex']) assert.match(pins[name]?.version ?? '', SEMVER, `${name}.version`);
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
    if (pins[name].combinedPatchSha256) assert.equal(candidate?.combinedPatchSha256, pins[name].combinedPatchSha256, `${name}: combined patch manifest`);
    if (pins[name].adapterSha256) assert.equal(candidate?.adapterSha256, pins[name].adapterSha256, `${name}: adapter manifest`);
  }
  assert.equal(manifest.find(row => row.file === path.basename(pins.agentConnect.archive)).runtimeRevision, pins.agentConnect.runtimeRevision, 'manifest.json');
});

test('the paired plugin archives are the verified GitHub release assets', () => {
  assert.equal(pins.agentConnect.version, '0.1.27');
  assert.equal(pins.agentConnect.sourceCommit, '053a39a7b72e83787a419b97206adc34f45e35bb');
  assert.equal(pins.agentConnect.archiveBuildCommit, '053a39a7b72e83787a419b97206adc34f45e35bb');
  assert.equal(pins.agentConnect.sourceCommit, pins.agentConnect.archiveBuildCommit);
  assert.equal(pins.agentConnect.sha256, 'aecf3bdff1505d3745ddc694f1e50fead50a0fc19b3fa2c82205174917143b6f');
  assert.equal(pins.agentConnect.adapterSha256, '22d3a604d0c3ddc9305afe07f9f68524bec906fddb16636c08ac2783b4442a6c');
  assert.equal(pins.omnigentPlugin.version, '0.3.42');
  assert.equal(pins.omnigentPlugin.sourceCommit, '7b56ad586711e6a707c6c3f36ff5dc5fef2790a4');
  assert.equal(pins.omnigentPlugin.sha256, '7ffa8983e3bb2d9790f3122fd53db3e7adca4e24aed33f37aa4cc86bbeea5bb5');
  assert.equal(pins.omnigentPlugin.combinedPatchSha256, '8d55d6824307023eed5ead7fa89080650d3981fae1746378db9a400fab8a9632');
  const manifest = JSON.parse(read('candidate-packages/manifest.json')).artifacts;
  const releases = {
    'woowtech-pi-paseo-0.1.27.tgz': 'https://github.com/WOOWTECH/pi-paseo-plugin/releases/download/v0.1.27/woowtech-pi-paseo-0.1.27.tgz',
    'woowtech-pi-omnigent-plugin-0.3.42.tgz': 'https://github.com/WOOWTECH/pi-omnigent-plugin/releases/download/v0.3.42/woowtech-pi-omnigent-plugin-0.3.42.tgz',
  };
  for (const pin of [pins.agentConnect, pins.omnigentPlugin]) {
    const row = manifest.find(item => item.file === path.basename(pin.archive));
    assert.equal(row?.status, 'verified GitHub release asset');
    assert.equal(row?.releaseUrl, releases[row.file], 'the release asset URL of these exact bytes');
  }
  assert.equal(pins.agentConnect.paseoVersion, '0.17.5');
  assert.equal(pins.agentConnect.runtimeRevision, '0.17.5-r4-8664f2c3f8f5');
});

test('the pinned Omnigent archive contains the exact candidate package identity', () => {
  const pin = pins.omnigentPlugin;
  const pkg = JSON.parse(tar('-xzOf', path.join(root, pin.archive), 'package/package.json'));
  assert.equal(pkg.name, '@woowtech/pi-omnigent-plugin');
  assert.equal(pkg.version, pin.version);
  const patch = tar('-xzOf', path.join(root, pin.archive), 'package/integrations/pi-web/combined.adapter.patch');
  assert.equal(createHash('sha256').update(patch).digest('hex'), pin.combinedPatchSha256);
  const metadata = JSON.parse(tar('-xzOf', path.join(root, pin.archive), 'package/integrations/pi-web/combined.adapter-meta.json'));
  assert.equal(metadata.patchSha256, pin.combinedPatchSha256);
  assert.equal(metadata.paseo.packageName, '@woowtech/pi-paseo');
  assert.equal(metadata.paseo.packageVersion, pins.agentConnect.version);
  const paseoAdapter = tar('-xzOf', path.join(root, pins.agentConnect.archive), 'package/host/adapter.patch');
  assert.equal(metadata.paseo.adapterPatchSha256, pins.agentConnect.adapterSha256);
  assert.equal(createHash('sha256').update(paseoAdapter).digest('hex'), metadata.paseo.adapterPatchSha256);
  assert.equal(metadata.omnigent.packageName, pkg.name);
  assert.equal(metadata.omnigent.packageVersion, pin.version);
  const omnigentAdapter = tar('-xzOf', path.join(root, pin.archive), 'package/integrations/pi-web/adapter.patch');
  assert.equal(metadata.omnigent.adapterPatchSha256, createHash('sha256').update(omnigentAdapter).digest('hex'));
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

test('Agent Connect 0.1.27 carries the exact adapter and peer-matched r4/a7 payload', () => {
  const pin = pins.agentConnect;
  const adapterMeta = JSON.parse(tar('-xzOf', path.join(root, pin.archive), 'package/host/adapter-meta.json'));
  const adapter = tar('-xzOf', path.join(root, pin.archive), 'package/host/adapter.patch');
  assert.equal(createHash('sha256').update(adapter).digest('hex'), pin.adapterSha256);
  assert.equal(adapterMeta.patchSha256, pin.adapterSha256);
  assert.equal(pin.runtimeRevision, '0.17.5-r4-8664f2c3f8f5');
  const provenance = JSON.parse(tar('-xzOf', path.join(root, pin.archive), 'package/runtime/better-paseo/provenance.json'));
  assert.equal(provenance.smartCommit, 'a7bfd65a3f39076cf664e28687818c24952e261c');
  for (const [file, hash] of Object.entries({
    'index.client.ts': '68f27211b8fc364ae7b3e58e4b7c6026bdca989cfd2251f27e830d450ad4c922',
    'index.server.ts': 'e2dcac63d3a3c2816b9e3c639e6abb2f71a5a50872af989dd6b83a7299bdcccd',
    'server/builtin.js': '7baa01803bcf477181169db05e537ecdc3075b295655ba5b2eee5e9a4db98109',
    'builtin-build.json': 'da1f9e36773dae2c69024e6dd337ce23835b00c11044a703dd8e632e83be5fc6',
    'THIRD_PARTY_NOTICES.txt': '1d89a0c7fddb8b83545bb727b9c1bb9bac35f1bbc173bc01081bb591ffc2f1e6',
  })) assert.equal(provenance.files[file], hash, file);
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
  assert.ok(dockerfile.includes("plugin_semver='^[0-9]+[.][0-9]+[.][0-9]+(-rc[.][0-9]+)?$'"),
    'plugin pins accept an explicit rc.N prerelease while CLI pins remain stable-only');
  assert.ok(dockerfile.includes("^candidate-packages/woowtech-pi-omnigent-plugin-[0-9]+[.][0-9]+[.][0-9]+(-rc[.][0-9]+)?[.]tgz$"),
    'the checksum-pinned candidate archive filename accepts the exact rc.N suffix');
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

test('the image smoke exercises real sessions JSON over gzip HTTP with owned synthetic fixtures', () => {
  const smoke = read('tests/omnigent-image-smoke.mjs');
  const acceptance = read('tests/sessions-http-json-acceptance.mjs');
  const dockerfile = read('Dockerfile');
  assert.match(smoke, /verifySessionsHttpJson\(/);
  assert.match(dockerfile, /^COPY tests\/sessions-http-json-acceptance\.mjs \/tmp\/sessions-http-json-acceptance\.mjs$/m);
  assert.match(acceptance, /accept-encoding': 'gzip'/);
  assert.match(acceptance, /gunzipSync\(response\.body, \{ maxOutputLength: MAX_JSON_BYTES \}\)/);
  assert.match(acceptance, /JSON\.parse\(decoded\.toString\('utf8'\)\)/);
  assert.match(acceptance, /await fetchResponse\.json\(\)/, 'the standard client JSON path parses transparently decompressed gzip');
  assert.match(acceptance, /MAX_WIRE_BYTES = 1024 \* 1024/);
  assert.match(acceptance, /assert\.equal\(target\.hostname, '127\.0\.0\.1'/);
  assert.match(acceptance, /result\.on\('aborted'/);
  assert.match(acceptance, /result\.on\('error'/);
  assert.match(acceptance, /minimumSessions = 24/);
});


test('Pi Web is rebuilt from exact 0.12.0 source with a hash-locked Next 16.4.6 security gate', () => {
  const pin = JSON.parse(read('patches/pi-web-source/build-pins.json'));
  const patch = read(pin.patch);
  assert.equal(pin.sourceRef, 'v0.12.0');
  assert.equal(pin.sourceCommit, '894e1a28dbeeb7b457c7712e495d975fe9927b89');
  assert.equal(createHash('sha256').update(patch).digest('hex'), pin.patchSha256);
  assert.equal(pin.nextVersion, '16.4.6');
  assert.equal(pin.eslintConfigNextVersion, '16.4.6');
  assert.equal(pin.auditLevel, 'high');
  assert.match(patch, /"next": "16\.4\.6"/);
  assert.match(patch, /"eslint-config-next": "16\.4\.6"/);
  assert.match(patch, /"undici": "8\.12\.2"/);
  assert.match(read('Dockerfile'), /test \"\$PI_WEB_SOURCE_COMMIT\" = \"\$PINNED_SOURCE_COMMIT\"/);
  assert.match(read('Dockerfile'), /refs\/tags\/\$PINNED_SOURCE_REF/);
  assert.match(read('Dockerfile'), /rev-parse \"refs\/tags\/\$PINNED_SOURCE_REF\^\{commit\}\"/);
  assert.match(read('Dockerfile'), /git -C \"\$ROOT\" checkout --detach \"\$PINNED_SOURCE_COMMIT\"/);
  assert.ok(read('Dockerfile').includes('rm -rf \"$ROOT/.git\" \"$ROOT/.next/cache\" \"$ROOT/node_modules/.cache\"'));
  assert.ok(read('Dockerfile').includes('test ! -e \"$ROOT/.git\" && test ! -e \"$ROOT/.next/cache\"'));
  assert.match(read('Dockerfile'), /npm ci --include=dev/);
  assert.match(read('Dockerfile'), /npm audit --audit-level=high/);
  assert.match(read('Dockerfile'), /NEXT_TELEMETRY_DISABLED=1 npm run build/);
  assert.match(read('Dockerfile'), /node_modules\/next\/package\.json/);
  const workflow = read('.github/workflows/build.yml');
  assert.match(workflow, /Build pinned Pi Web source and validate native settings/);
  assert.match(workflow, /npm ci --include=dev/);
  assert.match(workflow, /npm audit --audit-level=high/);
  assert.match(workflow, /NEXT_TELEMETRY_DISABLED=1 npm run build/);
  assert.match(workflow, /PI_WEB_ROOT=\"\$pi_web_root\" node --test/);
  assert.doesNotMatch(workflow, /npm pack @agegr\/pi-web@0\.12\.0/);
});
