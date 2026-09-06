import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const [harness, smoke] = await Promise.all([
  readFile(new URL('tests/container-opencode-byok-e2e.mjs', root), 'utf8'),
  readFile(new URL('tests/container-smoke.sh', root), 'utf8'),
]);

test('native byok-opencode container harness uses a streaming mock and browser request shape', () => {
  assert.match(harness, /const FAKE_API_KEY = 'od-byok-test-key-not-a-secret'/);
  assert.match(harness, /agentId: 'byok-opencode'/);
  assert.match(harness, /\$\{daemonUrl\}\/api\/runs/);
  assert.match(harness, /\/api\/runs\/\$\{encodeURIComponent\(created\.runId\)\}\/events/);
  assert.match(harness, /sessionMode: 'chat'/);
  assert.match(harness, /byokProvider: \{/);
  assert.match(harness, /protocol: 'openai'/);
  assert.match(harness, /apiKey: FAKE_API_KEY/);
  assert.match(harness, /baseUrl: `http:\/\/127\.0\.0\.1:\$\{address\.port\}\/v1`/);
  assert.match(harness, /request\.url === '\/v1\/chat\/completions'/);
  assert.match(harness, /parsedBody\?\.stream === true/);
  assert.match(harness, /content-type': 'text\/event-stream; charset=utf-8'/);
  assert.match(harness, /data: \[DONE\]/);
  assert.match(harness, /runOutput\.includes\(COMPLETION\)/);
  assert.match(harness, /const completionRequests = requests\.filter/);
  assert.match(harness, /completionRequests\.length >= 1/);
  assert.match(harness, /request\.model === MODEL/);
  assert.match(harness, /request\.authorization === `Bearer \$\{FAKE_API_KEY\}`/);
});

test('container smoke executes native BYOK coverage and rejects log and /data leakage', () => {
  assert.match(smoke, /docker cp tests\/container-opencode-byok-e2e\.mjs "\$container:\/tmp\/container-opencode-byok-e2e\.mjs"/);
  assert.match(smoke, /docker exec "\$container" node \/tmp\/container-opencode-byok-e2e\.mjs/);
  assert.match(smoke, /docker logs "\$container" 2>&1 \| grep -Fq -- "\$BYOK_FAKE_KEY"/);
  assert.match(smoke, /grep -R -I -F -q -- "\$1" \/data/);
  assert.match(smoke, /fake BYOK key leaked to \/data persisted artifacts/);
});
