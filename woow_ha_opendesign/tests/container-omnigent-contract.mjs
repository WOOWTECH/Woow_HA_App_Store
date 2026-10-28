// Runs inside an owned candidate container. No server login or model call.
import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';

const base = 'http://127.0.0.1:8099';
const prefix = '/api/hassio_ingress/abcdefghijklmnop';
const route = '/api/integrations/omnigent';
const expectedEngines = ['claude', 'codex', 'opencode', 'pi'];
async function request(endpoint, body, extraHeaders = {}) {
  const response = await fetch(`${base}${route}/${endpoint}`, {
    method: body ? 'POST' : 'GET',
    headers: { 'X-Ingress-Path': prefix, 'content-type': 'application/json', ...extraHeaders },
    ...(body ? { body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(60_000),
  });
  return { code: response.status, body: await response.json() };
}
async function status() {
  const result = await request('status');
  assert.equal(result.code, 200, 'native Omnigent status must be reachable through nginx');
  return result.body;
}
function fresh(value) {
  assert.equal(value.installed, true, 'pending core pin: the native Omnigent plugin must be bundled');
  assert.equal(value.installationSource, 'bundled');
  assert.equal(value.enabled, true);
  assert.equal(value.phase, 'needs-login');
  assert.equal(value.server, null, 'legacy home/backup must not supply a server');
  assert.equal(value.loginConfirmed, false, 'fresh GUI approval is required');
  assert.equal(value.host.connected, false);
  assert.deepEqual([...value.installedEngines].sort(), expectedEngines);
  assert.deepEqual(Object.keys(value.engines).sort(), expectedEngines);
}
async function action(name) {
  const result = await request('actions', { action: name });
  assert.ok([200, 202].includes(result.code), `native ${name} was refused`);
  for (let attempt = 0; attempt < 90; attempt++) {
    const current = await status();
    if (current.operation?.phase !== 'running') {
      assert.notEqual(current.operation?.phase, 'error', `native ${name} failed: ${current.operation?.issue?.code ?? 'unknown'}`);
      return current;
    }
    await delay(1000);
  }
  throw new Error(`native ${name} did not complete`);
}

if (process.argv[2] === 'fresh') {
  fresh(await status());
  const verify = await request('actions', { action: 'verify' });
  assert.equal(verify.code, 409);
  assert.equal(verify.body.error?.code, 'FRESH_LOGIN_REQUIRED');
  for (const body of [
    { action: 'setup' },
    { action: 'setup', server: 'http://invalid.example', username: 'fake', password: 'fake' },
  ]) {
    const rejected = await request('actions', body);
    assert.equal(rejected.code, 400, 'incomplete/invalid setup must never start a host');
  }
  const crossOrigin = await request('actions', { action: 'enable' }, { Origin: 'https://untrusted.invalid' });
  assert.equal(crossOrigin.code, 403);
  const crossSiteWithoutOrigin = await request('actions', { action: 'enable' }, { 'Sec-Fetch-Site': 'cross-site' });
  assert.equal(crossSiteWithoutOrigin.code, 403, 'cross-site metadata must reject a mutation even without Origin');
  const olderSameOrigin = await request('actions', { action: 'verify' }, { Origin: base });
  assert.equal(olderSameOrigin.code, 409, 'same-origin requests without Fetch Metadata must reach the native action');
  fresh(await status());
  const disabled = await action('disable');
  assert.equal(disabled.enabled, false);
  assert.equal(disabled.phase, 'disabled');
} else if (process.argv[2] === 'restored') {
  const disabled = await status();
  assert.equal(disabled.enabled, false, 'disabled choice must survive recreation and root-owned restore');
  assert.equal(disabled.phase, 'disabled');
  fresh(await action('enable'));
  const state = '/data/opendesign/integrations/omnigent';
  assert.equal((await stat(state)).mode & 0o777, 0o700);
  assert.equal((await stat(`${state}/state.json`)).mode & 0o777, 0o600);
  assert.equal((await stat(`${state}/state.json`)).uid, 1001);
  const legacy = await readFile('/data/opendesign/home/.omnigent/auth_tokens.json', 'utf8');
  const archived = await readFile('/data/opendesign/.backup/omnigent-retired/auth_tokens.json', 'utf8');
  assert.ok(legacy.includes('fake-legacy-not-for-adoption'));
  assert.ok(archived.includes('fake-archived-not-for-adoption'));
} else {
  throw new Error('Choose fresh or restored');
}
console.log(`Omnigent native daemon ${process.argv[2]} contract: OK (no authenticated host acceptance)`);
