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

test('native OpenCode runtime is locked, on PATH, and verified without Pi', () => {
  assert.match(dockerfile, /npm ci --omit=dev --prefix \/opt\/ha-opendesign\/opencode/);
  assert.match(dockerfile, /PATH=\/opt\/ha-opendesign\/opencode\/node_modules\/\.bin:\$\{PATH\}/);
  assert.match(dockerfile, /su-exec open-design:open-design opencode --version\)" = "1\.18\.29"/);
  assert.doesNotMatch(dockerfile, /runtime\/pi|ha-pi-wrapper|ha-byok-(?:store|profiles)/);
  assert.match(smoke, /test "\$\(opencode --version\)" = 1\.18\.29/);
  assert.match(smoke, /! command -v pi/);
  assert.match(workflow, /Verify locked OpenCode runtime as UID 1001/);
  assert.match(workflow, /--platform \$\{\{ matrix\.platform \}\}/);
  assert.match(provenance, /github\.com\/anomalyco\/opencode/);
  assert.match(provenance, /MIT licensed/);
});
