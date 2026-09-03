import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const smoke = await readFile(new URL('./container-smoke.sh', import.meta.url), 'utf8');

test('browser smoke runs beside the container playwright-core dependency', () => {
  const browserSmokePath = '/opt/ha-opendesign/container-ingress-browser-e2e.mjs';
  assert.ok(
    smoke.includes(`docker cp tests/container-ingress-browser-e2e.mjs "$container:${browserSmokePath}"`),
    'browser smoke must be copied beneath the runtime package root for ESM dependency resolution',
  );
  assert.ok(
    smoke.includes(`docker exec "$container" node ${browserSmokePath}`),
    'browser smoke must run from the path beneath the runtime package root',
  );
  assert.ok(
    !smoke.includes('node /tmp/container-ingress-browser-e2e.mjs'),
    'running the browser smoke from /tmp cannot resolve the runtime playwright-core dependency',
  );
});
