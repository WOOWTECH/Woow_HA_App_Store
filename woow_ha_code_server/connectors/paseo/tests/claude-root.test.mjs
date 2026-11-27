import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import {gunzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import {patchClaudeRootSource,applyClaudeRootPatch,claudeRootPatchReady,CLAUDE_ROOT_PATH,ORIGINAL_CLAUDE_SHA256} from '../src/claude-root-patch.mjs';

const original=gunzipSync(fs.readFileSync(new URL('./fixtures/installer-0.17.5/claude-agent.js.gz',import.meta.url))).toString();
assert.equal(createHash('sha256').update(original).digest('hex'),ORIGINAL_CLAUDE_SHA256);
function sdkOptions(source,uid,overrides={}) {
  const start=source.indexOf('    async buildOptions(permissionMode) {');
  const end=source.indexOf('\n    async buildSettingsOptions(',start);
  assert.ok(start>0&&end>start);
  const method=source.slice(start,end).replace('async buildOptions(', 'async function buildOptions(');
  const build=vm.runInNewContext('('+method+')',{
    process:{env:{PATH:'/usr/bin'},...(uid===undefined?{}:{getuid:()=>uid})},
    applyClaudeToolPolicy:options=>options,resolvePathEnvKey:()=> 'PATH',CLAUDE_SETTING_SOURCES:['user','project','local'],
  });
  return build.call({config:{cwd:'/workspace',providerOptions:overrides},defaults:{},harnessEnvironment:{HOME:'/private/qa'},
    resolveThinkingConfig:()=>({}),buildAppendedSystemPrompt:()=>'',buildSettingsOptions:async()=>({}),
    resolveBinary:async()=>'/usr/local/bin/claude',logger:{debug:()=>{}},buildSubagentEffortHooks:()=>({}),
  },'default');
}

test('real 0.17.5 SDK normal root launch no longer requests the forbidden bypass capability',async()=>{
  assert.equal((await sdkOptions(original,0)).allowDangerouslySkipPermissions,true,'upstream reproduces the root launch regression');
  const source=patchClaudeRootSource(original);
  for(const options of [{},{allowDangerouslySkipPermissions:true}]){
    const actual=await sdkOptions(source,0,options);
    assert.equal(actual.permissionMode,'default');
    assert.equal(actual.allowDangerouslySkipPermissions,false);
    assert.equal(actual.cwd,'/workspace');
    assert.equal(actual.env.HOME,'/private/qa');
  }
  assert.equal((await sdkOptions(source,1000)).allowDangerouslySkipPermissions,true);
  assert.equal((await sdkOptions(source,undefined)).allowDangerouslySkipPermissions,true);
  assert.equal((await sdkOptions(source,1000,{allowDangerouslySkipPermissions:false})).allowDangerouslySkipPermissions,false);
});

test('root compatibility patch is exact, idempotent and part of artifact readiness',t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'paseo-claude-root-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const file=path.join(root,CLAUDE_ROOT_PATH);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,original);
  assert.equal(claudeRootPatchReady(root),false);
  applyClaudeRootPatch(root);
  assert.equal(claudeRootPatchReady(root),true);
  const bytes=fs.readFileSync(file);applyClaudeRootPatch(root);assert.deepEqual(fs.readFileSync(file),bytes);
  fs.appendFileSync(file,'\n// tampered');assert.equal(claudeRootPatchReady(root),false);
  assert.throws(()=>applyClaudeRootPatch(root),{code:'CLAUDE_ROOT_SOURCE_MISMATCH'});
});
