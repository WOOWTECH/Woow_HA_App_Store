import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const [dockerfile, smoke, workflow, provenance] = await Promise.all([
  readFile(new URL('Dockerfile', root), 'utf8'),
  readFile(new URL('tests/container-smoke.sh', root), 'utf8'),
  readFile(new URL('.github/workflows/build.yml', root), 'utf8'),
  readFile(new URL('runtime/opencode/README.md', root), 'utf8'),
]);

test('native OpenCode and preinstalled agent CLIs are pinned and checked on PATH', () => {
  assert.match(dockerfile, /npm ci --omit=dev --prefix \/opt\/ha-opendesign\/opencode/);
  assert.match(dockerfile, /PATH=\/usr\/local\/bin:\/opt\/ha-opendesign\/opencode\/node_modules\/\.bin:\$\{PATH\}/);
  assert.match(dockerfile, /su-exec open-design:open-design opencode --version\)" = "1\.18\.29"/);
  assert.match(dockerfile, /@anthropic-ai\/claude-code@2\.1\.296/);
  assert.match(dockerfile, /@openai\/codex@0\.162\.1/);
  assert.match(dockerfile, /@earendil-works\/pi-coding-agent@1\.1\.0/);
  assert.doesNotMatch(dockerfile, /runtime\/pi|ha-pi-wrapper|ha-byok-(?:store|profiles)/);
  assert.match(smoke, /test "\$\(opencode --version\)" = 1\.18\.29/);
  assert.match(smoke, /claude --version \| grep -Fq 2\.1\.296/);
  assert.match(smoke, /codex --version \| grep -Fq 0\.162\.1/);
  assert.match(smoke, /pi --version \| grep -Fq 1\.1\.0/);
  assert.match(workflow, /Verify bundled agent CLIs as UID 1001/);
  assert.match(workflow, /--platform \$\{\{ matrix\.platform \}\}/);
  assert.match(provenance, /github\.com\/anomalyco\/opencode/);
  assert.match(provenance, /MIT licensed/);
});
