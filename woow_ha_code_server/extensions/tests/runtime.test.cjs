'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { createRuntime, settingsFrom, configureFields, publicStatus, validMessage, webUrl } = require('../shared/runtime.cjs');
function fakeProcess(handler) {
  const calls = [];
  function spawn(executable, args, options) {
    const child = new EventEmitter();
    child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
    child.kill = signal => { calls.push({ signal }); return true; };
    calls.push({ executable, args, options });
    let input = '';
    child.stdin.on('data', chunk => { input += chunk; });
    child.stdin.on('finish', () => handler({ child, request: JSON.parse(input) }));
    return child;
  }
  return { spawn, calls };
}
test('runtime sends top-level JSON through stdin without shell or arguments; logs no secrets', async () => {
  const diagnostics = [];
  const password = 'private-password-value';
  const fake = fakeProcess(({ child, request }) => {
    assert.equal(request.connector, 'omnigent'); assert.equal(request.action, 'connect'); assert.equal(request.password, password); assert.equal(request.fields, undefined);
    child.stderr.write(`password=${password}\n`);
    child.stdout.write(JSON.stringify({ ok: true, phase: 'online', token: 'private-token-value' }));
    child.emit('close', 0);
  });
  const run = createRuntime({ spawnProcess: fake.spawn, onEvent: entry => diagnostics.push(entry) });
  const result = await run({ connector: 'omnigent', action: 'connect', password });
  assert.equal(result.ok, true);
  assert.equal(fake.calls[0].executable, '/usr/local/bin/woow-connectors');
  assert.deepEqual(fake.calls[0].args, []); assert.equal(fake.calls[0].options.shell, false);
  assert.equal(JSON.stringify(diagnostics).includes('private-'), false);
  assert.deepEqual(diagnostics, [{ connector: 'omnigent', action: 'connect', ok: true }]);
});
test('runtime does not expose failed subprocess response or stderr', async () => {
  const fake = fakeProcess(({ child }) => { child.stdout.end(JSON.stringify({ ok: false, error: { code: 'AUTH_FAILED', message: 'private-password-value' } })); child.emit('close', 1); });
  const result = await createRuntime({ spawnProcess: fake.spawn })({ connector: 'omnigent', action: 'connect' });
  assert.equal(result.error.code, 'AUTH_FAILED'); assert.equal(JSON.stringify(result).includes('private-password'), false);
});
test('runtime rejects banners/multiple JSON objects and nonzero successful response', async () => {
  for (const [stdout, code, expected] of [['banner\n{"ok":true}',0,'INVALID_RESPONSE'], ['{"ok":true}\n{"ok":true}',0,'INVALID_RESPONSE'], ['{"ok":true}',2,'RUNTIME_EXIT']]) {
    const fake = fakeProcess(({child}) => { child.stdout.write(stdout); child.emit('close',code); });
    assert.equal((await createRuntime({spawnProcess:fake.spawn})({connector:'paseo',action:'status'})).error.code,expected);
  }
});
test('runtime bounds output and terminates timed-out calls', async () => {
  const huge = fakeProcess(({child})=>child.stdout.write('x'.repeat(2*1024*1024+1)));
  assert.equal((await createRuntime({spawnProcess:huge.spawn})({connector:'paseo',action:'status'})).error.code,'OUTPUT_LIMIT');
  assert.ok(huge.calls.some(c=>c.signal==='SIGTERM'));
  const stuck = fakeProcess(()=>{});
  assert.equal((await createRuntime({spawnProcess:stuck.spawn,timeoutMs:15})({connector:'paseo',action:'status'})).error.code,'TIMEOUT');
  assert.ok(stuck.calls.some(c=>c.signal==='SIGTERM'));
});
test('runtime overrides ignore repository settings and reject nonabsolute executable', async () => {
  const config=settingsFrom({inspect:key=>({defaultValue:key==='runtimePath'?'/usr/local/bin/woow-connectors':'',workspaceValue:'/workspace/evil.sh',workspaceFolderValue:'/workspace/evil.sh'})});
  assert.equal(config.runtimePath,'/usr/local/bin/woow-connectors');
  assert.equal((await createRuntime({executable:'evil.sh'})({connector:'paseo',action:'status'})).error.code,'INVALID_RUNTIME_PATH');
});
test('configuration rejects credentials, untrusted fields, controls and relative paths', () => {
  const valid={workspace:'/workspace',hostName:'test',server:'https://example.org'};
  assert.equal(configureFields('omnigent',valid).server,'https://example.org/');
  for(const bad of [{...valid,password:'x'},{...valid,workspace:'repo'},{...valid,server:'https://user:pass@example.org'},{...valid,server:'https://example.org/?token=x'},{...valid,hostName:'bad\nname'}]) assert.throws(()=>configureFields('omnigent',bad));
  assert.throws(()=>configureFields('paseo',{workspace:'/workspace',hostName:'test',webUrl:'https://app.paseo.sh/#token=x'}));
  assert.equal(webUrl('javascript:alert(1)'),undefined);
  assert.equal(validMessage({action:'start',command:'arbitrary'}),false);
  assert.equal(validMessage({action:'start',fields:{command:'arbitrary'}}),false);
  assert.equal(validMessage({action:'connect',fields:{password:'x'}}),false);
});
test('public status cannot mistake online for verified, strips secrets and nested credentials', () => {
  const source={ok:true,phase:'online',host:{name:'test',token:'never-visible'},token:'never-visible',pairingUrl:'https://app.paseo.sh/#private',engines:[{id:'claude',installed:true,authenticated:false,password:'never-visible'}]};
  const state=publicStatus(source,'omnigent',{server:'https://example.org/?token=never-visible',password:'never-visible'});
  assert.equal(state.phase,'online'); assert.equal(state.verification,'unverified');
  assert.equal(JSON.stringify(state).includes('never-visible'),false);
  assert.equal(state.engines[0].authenticated,'false');
  assert.equal(publicStatus({...source,verification:{status:'passed',at:'2026-11-10'}},'omnigent').verification,'passed');
});
test('real subprocess fixture exercises the installed executable JSON boundary', async () => {
  const path = require('node:path');
  const run = createRuntime({ executable: path.join(__dirname, 'fixtures/fake-backend.cjs') });
  const result = await run({ connector: 'omnigent', action: 'connect', username: 'fixture', password: 'fixture-password' });
  assert.equal(result.ok, true); assert.equal(result.phase, 'fixture-online');
  assert.equal(result.host.name, '測試工作機');
  assert.equal(publicStatus(result, 'omnigent').verification, 'unverified');
});
test('public status drops credential-bearing server URLs rather than displaying them', () => {
  const result=publicStatus({ok:true,server:'https://user:private-password@example.org/'},'omnigent');
  assert.equal(result.server,'');
});
test('Omnigent status respects runtime validation of engine receipts and rejects stale or failed evidence', () => {
  const receipts=Object.fromEntries(['claude','codex','pi'].map(engine=>[engine,{ok:true,cleanup:'stopped'}]));
  const current={ok:true,phase:'connected',verified:true,verification:receipts};
  assert.equal(publicStatus(current,'omnigent').verification,'passed');
  assert.equal(publicStatus({ok:true,data:current},'omnigent').verification,'passed');
  assert.equal(publicStatus({...current,verified:false},'omnigent').verification,'incomplete');
  assert.equal(publicStatus({...current,verified:false,verification:{ok:true}},'omnigent').verification,'incomplete');
  assert.equal(publicStatus({...current,ok:false},'omnigent').verification,'incomplete');
  assert.equal(publicStatus({ok:true,phase:'connected',verification:receipts},'omnigent').verification,'incomplete');
  assert.equal(publicStatus({ok:true,phase:'connected'},'omnigent').verification,'unverified');
});
test('Paseo daemon is not online evidence, and acceptance is separate verification evidence', () => {
  const base={ok:true,daemon:{running:true},providers:[{id:'pi',installed:true,models:[{id:'example-model'}]}]};
  const initial=publicStatus(base,'paseo');
  assert.equal(initial.phase,'daemon running; connection unverified');assert.equal(initial.verification,'unverified');assert.equal(initial.engines[0].id,'pi');assert.equal(initial.models[0].id,'example-model');
  const passed=publicStatus({...base,online:true,acceptance:{requestedPassed:true,at:'2026-11-10'}},'paseo');
  assert.equal(passed.phase,'online');assert.equal(passed.verification,'passed');
});
test('Omnigent URL validation accepts explicit HTTP private/loopback routes and rejects auth/query/fragment fields', () => {
  const base={workspace:'/workspace',hostName:'qa',server:'http://omnigent-server:8000'};
  assert.equal(configureFields('omnigent',{...base,webUrl:'http://127.0.0.1:18080'}).webUrl,'http://127.0.0.1:18080/');
  assert.equal(configureFields('omnigent',{...base,server:'http://omnigent.ns.svc.cluster.local:8000',webUrl:'https://omnigent.example.org'}).server,'http://omnigent.ns.svc.cluster.local:8000/');
  assert.equal(configureFields('omnigent',{...base,webUrl:''}).webUrl,undefined);
  for(const key of ['server','webUrl'])for(const bad of ['https://operator:fixture-private@example.org','https://example.org/?token=fixture-private','https://example.org/#fixture-private','https://example.org/?','https://example.org/#','https://exa\nmple.org',null])assert.throws(()=>configureFields('omnigent',{...base,[key]:bad}));
  const state=publicStatus({ok:true},'omnigent',{server:base.server,webUrl:'https://operator:fixture-private@example.org'});assert.equal(state.settings.webUrl,'');assert.equal(JSON.stringify(state).includes('fixture-private'),false);
});
