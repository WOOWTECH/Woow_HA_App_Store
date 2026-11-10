import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { validatePairUrl, safeFailure, BrowserCheckError } from './browser-support.mjs';
import { validatePlan, readPrivatePlan, waitForNewAssistant } from './browser-acceptance.mjs';
import { inspect as remoteInspect } from './inspect-command.mjs';

const pairUrl = 'https://app.paseo.sh/#test-fixture-not-a-real-pairing';
const plan = () => ({ pairUrl, workspace: '/workspace', allowModelCalls: true, providers: ['claude', 'codex', 'pi'].map(id => ({ id, models: [{ id: 'model-one', label: 'Model one' }, { id: 'model-two', label: 'Model two' }] })) });

test('pair-only mode cannot implicitly enable models and full mode requires explicit authorization', () => {
  assert.equal(validatePlan({ pairUrl, workspace: '/workspace', mode: 'pair' }).allowModelCalls, undefined);
  const value = plan(); delete value.allowModelCalls;
  assert.throws(() => validatePlan(value), { code: 'MODEL_CALLS_NOT_AUTHORIZED' });
  assert.equal(validatePlan(plan()).providers.length, 3);
});

test('browser plan requires all three engines and two distinct models per engine', () => {
  const missing = plan(); missing.providers.pop();
  assert.throws(() => validatePlan(missing), { code: 'THREE_PROVIDERS_REQUIRED' });
  const repeated = plan(); repeated.providers[0].models[1].id = 'model-one';
  assert.throws(() => validatePlan(repeated), { code: 'TWO_DISTINCT_MODELS_REQUIRED' });
});

test('shared proof requires an explicit deployment prefix and boolean opt-in', () => {
  assert.throws(() => validatePlan({ ...plan(), sharedProof: 'true' }), { code: 'INVALID_SHARED_PROOF_PLAN' });
  assert.throws(() => validatePlan({ ...plan(), sharedProof: true }), { code: 'INVALID_SHARED_PROOF_PREFIX' });
  assert.equal(validatePlan({ ...plan(), sharedProof: true, proofRunPrefix: 'paseo-podman' }).sharedProof, true);
});

test('targeted retries retain the three-engine plan and reject unknown or duplicate engines', () => {
  assert.deepEqual(validatePlan({ ...plan(), runProviders: ['claude'] }).runProviders, ['claude']);
  assert.throws(() => validatePlan({ ...plan(), runProviders: ['other'] }), { code: 'INVALID_PROVIDER_RETRY' });
  assert.throws(() => validatePlan({ ...plan(), runProviders: ['pi', 'pi'] }), { code: 'INVALID_PROVIDER_RETRY' });
});

test('pair URL rejects origin changes and userinfo without disclosing its fragment', () => {
  assert.equal(validatePairUrl(pairUrl), pairUrl);
  assert.throws(() => validatePairUrl('https://other.invalid/#sensitive-fragment'), { code: 'INVALID_PAIR_URL' });
  assert.throws(() => validatePairUrl('https://user:secret@app.paseo.sh/#sensitive-fragment'), { code: 'INVALID_PAIR_URL' });
  assert.doesNotMatch(JSON.stringify(safeFailure(new Error('Navigation failed at ' + pairUrl))), /test-fixture|https:/);
  assert.equal(safeFailure(new BrowserCheckError('CONTROL_NOT_FOUND')).error.code, 'CONTROL_NOT_FOUND');
});

test('pairing plan must be private and outside the checkout', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'woow-paseo-browser-plan-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'plan.json');
  fs.writeFileSync(file, JSON.stringify(plan()), { mode: 0o600 });
  assert.equal(readPrivatePlan(file).providers.length, 3);
  fs.chmodSync(file, 0o644);
  assert.throws(() => readPrivatePlan(file), { code: 'UNSAFE_PLAN_FILE' });
});

test('a visible marker in an old assistant node never counts as a new browser reply', async () => {
  const assistant = { count: async () => 1, last: () => ({ innerText: async () => 'marker' }), filter() { return this; } };
  const page = { getByTestId: () => assistant, waitForTimeout: async () => {} };
  await assert.rejects(waitForNewAssistant(page, 1, 'marker', 2), { code: 'NEW_ASSISTANT_REPLY_NOT_VERIFIED' });
});

test('remote read-only inspector forwards JSON stdin and suppresses raw stderr', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'woow-paseo-inspector-test-'));
  const file = path.join(dir, 'command.json');
  const previous = process.env.WOOW_PASEO_INSPECT_COMMAND_FILE;
  process.env.WOOW_PASEO_INSPECT_COMMAND_FILE = file;
  t.after(() => {
    previous === undefined ? delete process.env.WOOW_PASEO_INSPECT_COMMAND_FILE : process.env.WOOW_PASEO_INSPECT_COMMAND_FILE = previous;
    fs.rmSync(dir, { recursive: true, force: true });
  });
  fs.writeFileSync(file, JSON.stringify([process.execPath, '-e', 'let input="";process.stdin.on("data",c=>input+=c);process.stdin.on("end",()=>process.stdout.write(JSON.stringify({ok:true,agentId:JSON.parse(input).agentId})))']), { mode: 0o600 });
  assert.deepEqual(await remoteInspect({ agentId: 'test-agent-123' }), { ok: true, agentId: 'test-agent-123' });
  fs.writeFileSync(file, JSON.stringify([process.execPath, '-e', 'console.error("fake-sensitive-output");process.exit(2)']));
  const failed = await remoteInspect({ agentId: 'test-agent-123' });
  assert.equal(failed.ok, false);
  assert.doesNotMatch(JSON.stringify(failed), /fake-sensitive-output/);
});
