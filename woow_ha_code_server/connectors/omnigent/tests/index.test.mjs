import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { environment,handle } from '../index.mjs';

test('deployment homes override a nested native session without copying credentials',()=>{
  const env=environment({PI_AGENT_DATA_DIR:'/data/tenant',WOOW_CONNECTOR_DATA_DIR:'/private/connectors',CODEX_HOME:'/other/codex-native/session/codex-home',CLAUDE_CONFIG_DIR:'/other/claude-native/session/home'});
  assert.equal(env.CODEX_HOME,'/data/tenant/codex');
  assert.equal(env.CLAUDE_CONFIG_DIR,'/data/tenant/claude');
  assert.equal(env.WOOW_OMNIGENT_CONNECTOR_STATE,'/private/connectors/omnigent');
  assert.equal(env.OMNIGENT_CONFIG_HOME,'/private/connectors/omnigent/sdk');
  assert.ok(env.OMNIGENT_RUNNER_ENV_PASSTHROUGH.includes('WOOW_OMNIGENT_SHARED_TOOLS'));
  assert.equal(env.DISABLE_AUTOUPDATER,'1');
  assert.ok(env.OMNIGENT_RUNNER_ENV_PASSTHROUGH.split(',').includes('DISABLE_AUTOUPDATER'));
});
test('explicit deployment native homes are preserved',()=>{
  const env=environment({PI_AGENT_DATA_DIR:'/data/tenant',CODEX_HOME:'/data/custom-codex',CLAUDE_CONFIG_DIR:'/data/custom-claude'});
  assert.equal(env.CODEX_HOME,'/data/custom-codex');assert.equal(env.CLAUDE_CONFIG_DIR,'/data/custom-claude');
});
test('PaaS keeps original kit state and mode',()=>{
  const env=environment({PI_AGENT_DATA_DIR:'/data/tenant',OG_HOST_ENABLED:'true',OG_CONFIG_HOME:'/data/original',OG_DATA_DIR:'/data/original-data'});
  assert.equal(env.OMNIGENT_CONFIG_HOME,'/data/original');
  assert.equal(env.OMNIGENT_DATA_DIR,'/data/original-data');
  assert.equal(env.WOOW_OMNIGENT_DEPLOYMENT_MANAGED,'1');
});
test('reject unsupported action without running a runtime',async()=>{
  assert.equal((await handle({action:'runShell',command:'echo secret'})).error.code,'INVALID_ACTION');
});
test('stdin bridge allowlists fields and discards stderr secrets',async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'woow-omni-node-'));
  const executable=path.join(dir,'fake-python');
  fs.writeFileSync(executable,`#!/usr/bin/env node
let raw='';process.stdin.on('data',c=>raw+=c);process.stdin.on('end',()=>{const v=JSON.parse(raw);process.stderr.write('SECRET_SHOULD_NOT_LEAK');process.stdout.write(JSON.stringify({ok:true,keys:Object.keys(v),hasPassword:v.password==='stdin-secret'}));});
`,{mode:0o700});
  const old=process.env.WOOW_OMNIGENT_PYTHON;
  process.env.WOOW_OMNIGENT_PYTHON=executable;
  try {
    const result=await handle({action:'connect',password:'stdin-secret',stateDir:'/foreign',configHome:'/foreign',env:{TOKEN:'secret'},omnigentBin:'/bin/sh'});
    assert.equal(result.hasPassword,true);
    assert.deepEqual(result.keys,['action','password']);
    assert.ok(!JSON.stringify(result).includes('SECRET'));
  } finally {if(old===undefined)delete process.env.WOOW_OMNIGENT_PYTHON;else process.env.WOOW_OMNIGENT_PYTHON=old;fs.rmSync(dir,{recursive:true,force:true});}
});
