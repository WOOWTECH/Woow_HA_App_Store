import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { validatePairUrl, safeFailure, BrowserCheckError } from './browser-support.mjs';
import { validatePlan, readPrivatePlan, waitForNewAssistant } from './browser-acceptance.mjs';
import { inspect as remoteInspect } from './inspect-command.mjs';
import { validateDownloadPlan } from './browser-downloads.mjs';

const fixturePair = (origin = 'https://app.paseo.sh', relay = 'relay.paseo.sh:443', extra = { minimumSecurityMode: 'protected' }) =>
  `${origin}/#offer=${Buffer.from(JSON.stringify({ v: 2, serverId: 'synthetic-test-server', daemonPublicKeyB64: 'synthetic-not-a-real-key', relay: { endpoint: relay, useTls: true }, ...extra })).toString('base64url')}`;
const pairUrl = fixturePair();
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
  assert.doesNotMatch(JSON.stringify(safeFailure(new Error('Navigation failed at ' + pairUrl))), /synthetic|https:|offer=/);
  assert.equal(safeFailure(new BrowserCheckError('CONTROL_NOT_FOUND')).error.code, 'CONTROL_NOT_FOUND');
});

test('a branded browser plan requires its explicit matching target and relay', () => {
  for (const [target, origin, relay] of [
    ['woowtech', 'https://smart.woowtech.io', 'relay.woowtech.io:443'],
    ['apporo', 'https://smart.apporo.ai', 'relay.apporo.ai:443'],
  ]) {
    const url = fixturePair(origin, relay, {});
    assert.equal(validatePlan({ ...plan(), target, pairUrl: url }).pairUrl, url);
    assert.equal(validatePairUrl(url, target), url);
    assert.throws(() => validatePairUrl(url), { code: 'INVALID_PAIR_URL' });
    assert.throws(() => validatePairUrl(fixturePair(origin, 'relay.paseo.sh:443', {}), target), { code: 'INVALID_PAIR_URL' });
    assert.throws(() => validatePairUrl(fixturePair(origin, relay), target), { code: 'INVALID_PAIR_URL' });
  }
  assert.throws(() => validatePlan({ ...plan(), target: 'other' }), { code: 'INVALID_BROWSER_TARGET' });
});

test('browser pairing rejects unrelated paths, queries, non-V2 and non-TLS offers', () => {
  for (const url of [
    pairUrl.replace('/#', '/unrelated#'), pairUrl.replace('/#', '/?extra=1#'),
    'https://app.paseo.sh/#test-fixture-not-a-real-pairing',
    fixturePair('https://app.paseo.sh', 'relay.paseo.sh:443', { v: 1 }),
    fixturePair('https://app.paseo.sh', 'relay.paseo.sh:443', { relay: { endpoint: 'relay.paseo.sh:443', useTls: false } }),
  ]) assert.throws(() => validatePairUrl(url), { code: 'INVALID_PAIR_URL' });
});

test('download plans bind workspace transport to the explicitly selected client', () => {
  const base = { agentId: 'synthetic-agent', assistantMarker: 'synthetic-marker', files: [{ path: 'proof.txt', label: 'Proof', sha256: '0'.repeat(64) }] };
  for (const [target, origin] of [['paseo', 'https://app.paseo.sh'], ['woowtech', 'https://smart.woowtech.io'], ['apporo', 'https://smart.apporo.ai']]) {
    const value = { ...base, target, workspaceUrl: `${origin}/h/synthetic-host/workspace/synthetic-workspace` };
    assert.doesNotThrow(() => validateDownloadPlan(value));
    assert.throws(() => validateDownloadPlan({ ...value, workspaceUrl: 'https://other.invalid/h/host/workspace/workspace' }), { code: 'INVALID_WORKSPACE_URL' });
    assert.throws(() => validateDownloadPlan({ ...value, workspaceUrl: value.workspaceUrl + '?offer=secret' }), { code: 'INVALID_WORKSPACE_URL' });
    if (target !== 'paseo') assert.throws(() => validateDownloadPlan({ ...value, target: undefined }), { code: 'INVALID_WORKSPACE_URL' });
  }
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
