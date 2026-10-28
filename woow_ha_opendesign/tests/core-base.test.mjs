import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const [dockerfile, smoke, workflow, launcher, build] = await Promise.all([
  readFile(new URL('Dockerfile', root), 'utf8'),
  readFile(new URL('tests/container-smoke.sh', root), 'utf8'),
  readFile(new URL('.github/workflows/build.yml', root), 'utf8'),
  readFile(new URL('rootfs/usr/local/bin/ha-opendesign', root), 'utf8'),
  readFile(new URL('build.yaml', root), 'utf8'),
]);
const coreImage = 'ghcr.io/woowtech/open-design-core:20261027.1127@sha256:c8cd57f07adaef23b8dddbb22a8b75f97bdf8ca42c8bfbec1b284dc60ee5a4cf';

test('the add-on derives from the WoowTech core image, never upstream OpenDesign', () => {
  assert.match(dockerfile, new RegExp(`^ARG BUILD_FROM=${coreImage.replace(/[.]/g, '\\.')}$`, 'm'));
  assert.match(dockerfile, /^FROM \$\{BUILD_FROM\}$/m);
  for (const text of [dockerfile, workflow, build]) assert.doesNotMatch(text, /nexu-io\/od/);
  assert.ok(workflow.split('\n').includes(`  CORE_IMAGE: ${coreImage}`), 'CI must pin the same core digest as the Dockerfile');
  assert.match(workflow, /BUILD_FROM=\$\{\{ env\.CORE_IMAGE \}\}/);
});

test('agent CLIs come from the core and are asserted, not installed, by the add-on', () => {
  assert.doesNotMatch(dockerfile, /npm install (?:--global|-g)/);
  assert.doesNotMatch(dockerfile, /runtime\/opencode|ha-opendesign\/opencode|runtime\/pi|ha-pi-wrapper|ha-byok-(?:store|profiles)/);
  for (const [arg, version] of [
    ['CORE_CLAUDE_CODE_VERSION', '2.1.296'],
    ['CORE_CODEX_VERSION', '0.162.1'],
    ['CORE_PI_VERSION', '1.1.0'],
    ['CORE_OPENCODE_VERSION', '1.18.33'],
  ]) {
    assert.match(dockerfile, new RegExp(`^ARG ${arg}=${version.replace(/[.]/g, '\\.')}$`, 'm'));
    assert.ok(dockerfile.includes(`\${${arg}}`), `${arg} must be asserted`);
  }
  assert.match(dockerfile, /su-exec open-design:open-design sh -ceu/);
  assert.match(smoke, /test "\$\(opencode --version\)" = 1\.18\.33/);
  assert.match(smoke, /test "\$\(command -v opencode\)" = \/usr\/local\/bin\/opencode/);
  assert.match(smoke, /claude --version \| grep -Fq 2\.1\.296/);
  assert.match(smoke, /codex --version \| grep -Fq 0\.162\.1/);
  assert.match(smoke, /pi --version \| grep -Fq 1\.1\.0/);
  assert.match(workflow, /Verify bundled agent CLIs as UID 1001/);
  assert.match(workflow, /--platform \$\{\{ matrix\.platform \}\}/);
});

test('HA overrides the core PaaS runtime defaults', () => {
  for (const env of ['OD_PORT=7456', 'OD_BIND_HOST=127.0.0.1', 'OD_DATA_DIR=/data/opendesign', 'HOME=/data/opendesign/home']) {
    assert.ok(dockerfile.includes(env), `Dockerfile must set ${env}`);
  }
  assert.doesNotMatch(dockerfile, /OMNIGENT_(?:CONFIG_HOME|DATA_DIR)=/, 'private host state must be derived by the native service');
  assert.match(dockerfile, /^ENTRYPOINT \["\/sbin\/tini", "--", "\/usr\/local\/bin\/ha-opendesign"\]$/m);
  assert.match(dockerfile, /^CMD \[\]$/m, 'the core CMD (daemon on 7457) must be cleared');
  assert.doesNotMatch(dockerfile, /^ENTRYPOINT .*omnigent-host-entry/m, 'the PaaS entry stub must not be the HA entrypoint');
  assert.doesNotMatch(dockerfile, /^EXPOSE/m);
  assert.match(launcher, /export OD_PORT=7456/);
});

test('core skills and plugin catalog are verified at build and in the running container', () => {
  assert.match(dockerfile, /test -f \/app\/skills\/woowtech-brand\/SKILL\.md/);
  assert.match(dockerfile, /test ! -e \/app\/skills\/brainstorming/);
  assert.match(smoke, /"woowtech-brand" in catalog\["skills"\]/);
  assert.match(smoke, /"brainstorming" not in catalog\["skills"\]/);
});

test('image license labels name OpenDesign (Apache-2.0) and the add-on code (MIT)', async () => {
  const license = await readFile(new URL('LICENSE', root), 'utf8');
  assert.match(license, /^MIT License/);
  assert.match(dockerfile, /org\.opencontainers\.image\.licenses="Apache-2\.0 AND MIT"/);
  assert.match(build, /org\.opencontainers\.image\.licenses: Apache-2\.0 AND MIT/);
});

test('HA OpenDesign is amd64 only', () => {
  assert.match(build, /^build_from:\n  amd64: \S+\n(?!  aarch64)/m);
  assert.doesNotMatch(workflow, /aarch64|linux\/arm64/);
});
