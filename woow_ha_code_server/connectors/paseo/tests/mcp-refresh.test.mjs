import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {refreshedManagedConfig} from '../src/managed-mcp-config.mjs';
import {pathToFileURL} from 'node:url';
import {refreshSharedMcp} from '../src/mcp-refresh.mjs';
import {patchRefreshSource, refreshRecipes} from '../src/mcp-refresh-patch.mjs';

const agent = {id:'existing-agent', provider:'codex', status:'idle', persistence:{provider:'codex',sessionId:'original-native'}};
test('refresh retains native persistence and reports no tool execution claim', async () => {
  const calls=[];
  const client={fetchAgent:async()=>({agent}),refreshAgent:async id=>{calls.push(id);return {agentId:id};}};
  const result=await refreshSharedMcp(client,agent.id,async()=>({configurationHash:'a'.repeat(64)}));
  assert.deepEqual(calls,[agent.id]); assert.equal(result.refresh.historyPreserved,true);
  assert.equal(result.refresh.toolsVerified,false);
});
test('error state permits guarded recovery after a close timeout', async()=>{const before={...agent,status:'error'};let n=0;const result=await refreshSharedMcp({fetchAgent:async()=>({agent:++n===1?before:agent}),refreshAgent:async()=>({agentId:agent.id})},agent.id,async()=>({configurationHash:'b'.repeat(64)}));assert.equal(result.refresh.state,'resumed');});
test('busy, unknown, and unpersisted sessions do not synchronize or restart', async () => {
  for(const value of [{...agent,status:'running'},{...agent,status:'waiting'},{...agent,persistence:null},{...agent,provider:'unknown'}]) {
    await assert.rejects(refreshSharedMcp({fetchAgent:async()=>({agent:value}),refreshAgent:()=>assert.fail('restart')},agent.id,()=>assert.fail('sync')));
  }
});
test('sync failure and rejected runtime refresh cannot be reported as success', async () => {
  await assert.rejects(refreshSharedMcp({fetchAgent:async()=>({agent}),refreshAgent:()=>assert.fail('restart')},agent.id,async()=>{throw Error('sync');}),/sync/);
  await assert.rejects(refreshSharedMcp({fetchAgent:async()=>({agent}),refreshAgent:async()=>{throw Error('SESSION_BUSY');}},agent.id,async()=>({})),{code:'SESSION_BUSY'});
});
test('changed native persistence is rejected even if the visible conversation ID stayed the same', async () => {
  let reads=0;
  await assert.rejects(refreshSharedMcp({fetchAgent:async()=>({agent:++reads===1?agent:{...agent,persistence:{sessionId:'new-native'}}}),refreshAgent:async()=>({agentId:agent.id})},agent.id,async()=>({})),{code:'MCP_REFRESH_UNCONFIRMED'});
});
test('patch refuses an unrecognized upstream build',()=>assert.throws(()=>patchRefreshSource('unknown',refreshRecipes[0]),{code:'MCP_REFRESH_SOURCE_MISMATCH'}));

// This integration exercises the actual pinned AgentManager lifecycle method,
// not a second implementation of the reload ordering. npm ci runtime/ first.
const root=path.resolve(new URL('../runtime',import.meta.url).pathname);
const recipe=refreshRecipes[0], original=path.join(root,recipe.path);
test('pinned manager guards active turns and resumes the exact saved handle', {skip:!fs.existsSync(original)}, async t => {
  const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'paseo-refresh-'));
  fs.mkdirSync(path.join(tmp,'shared'));fs.mkdirSync(path.join(tmp,'claude'));
  fs.writeFileSync(path.join(tmp,'shared/managed.json'),JSON.stringify({managedServers:['old','new']}));
  fs.writeFileSync(path.join(tmp,'claude/.claude.json'),JSON.stringify({mcpServers:{new:{type:'stdio',command:'new-executable'}}}));
  const priorData=process.env.PI_AGENT_DATA_DIR, priorClaude=process.env.CLAUDE_CONFIG_DIR;
  process.env.PI_AGENT_DATA_DIR=tmp;process.env.CLAUDE_CONFIG_DIR=path.join(tmp,'claude');
  t.after(()=>{if(priorData===undefined) delete process.env.PI_AGENT_DATA_DIR;else process.env.PI_AGENT_DATA_DIR=priorData;if(priorClaude===undefined)delete process.env.CLAUDE_CONFIG_DIR;else process.env.CLAUDE_CONFIG_DIR=priorClaude;fs.rmSync(tmp,{recursive:true});});
  const helper=path.join(path.dirname(original),'woow-managed-mcp.mjs');
  const priorHelper=fs.existsSync(helper)?{bytes:fs.readFileSync(helper),mode:fs.statSync(helper).mode}:null;
  fs.copyFileSync(new URL('../src/managed-mcp-config.mjs',import.meta.url),helper);t.after(()=>{if(priorHelper){fs.writeFileSync(helper,priorHelper.bytes);fs.chmodSync(helper,priorHelper.mode);}else fs.unlinkSync(helper);});
  const copy=path.join(path.dirname(original),`woow-mcp-test-${process.pid}.js`);
  fs.writeFileSync(copy,patchRefreshSource(fs.readFileSync(original,'utf8'),recipe));
  t.after(()=>fs.unlinkSync(copy));
  const {AgentManager}=await import(pathToFileURL(copy));
  function harness({busy=false,handle=agent.persistence,closeError=false,resumeError=false}={}) {
    const calls=[],existing={id:agent.id,provider:'codex',persistence:handle,config:{provider:'codex',cwd:'/workspace',modeId:'default',mcpServers:{old:{type:'stdio',command:'stale-executable'},private_only:{type:'stdio',command:'keep'}}},session:{capabilities:{supportsMcpServers:true}},labels:{keep:'label'},historyPrimed:true};
    const manager=Object.create(AgentManager.prototype);
    Object.assign(manager,{
      trackAgentRegistrationOperation:operation=>operation,lifecycleMutationTails:new Map(),
      assertAcceptingAgentRegistrations(){},requireSessionAgent:()=>existing,hasInFlightRun:()=>busy,
      cancelAgentRunBefore:()=>assert.fail('active turn cancelled'),
      requireClient:()=>({createSession:()=>assert.fail('new native chat'),resumeSession:async (saved,config)=>{assert.strictEqual(saved,handle);assert(!('old' in config.mcpServers));assert.equal(config.mcpServers.new.command,'new-executable');assert.equal(config.mcpServers.private_only.command,'keep');calls.push('resume');if(resumeError)throw Error('resume failed');return {capabilities:{}};}}),
      prepareSessionConfig:async config=>({storedConfig:config,launchConfig:config,paseoToolPolicy:{}}),
      paseoToolPolicies:new Map(),buildLaunchContext:async()=>({}),resolveProviderLaunchConfig:config=>config,
      closeReloadedSession:async()=>{assert.throws(()=>manager.streamAgent(agent.id,'racing prompt'),/SESSION_BUSY/);calls.push('close');if(closeError)throw Error('close failed');},drainSessionEvents:async()=>{},cancelRunningProviderSubagents(){},
      prepareAgentForClosure:()=>existing,persistSnapshot:async()=>{},requireExternalMcpSupport:async()=>{},
      registerSession:(_s,_c,id,options)=>{assert.equal(id,agent.id);assert.equal(options.historyPrimed,false);assert.equal(options.labels.keep,'label');existing.session=_s;existing.persistence=handle;existing.lifecycle='idle';return existing;},
      timelineStore:new Map(),providerSubagents:{deleteParent:()=>[]},
      agents:new Map([[agent.id,existing]]),emitState(){},emitClosedAgent(){},closeUnregisteredSession:async()=>{},
    });
    return {manager,calls,existing};
  }
  for(const [options,error] of [[{busy:true},'SESSION_BUSY'],[{handle:null},'MCP_RESUME_UNAVAILABLE']]) {
    const {manager,calls}=harness(options);
    await assert.rejects(manager.reloadAgentSession(agent.id,undefined,{requireIdle:true,requirePersistence:true,rehydrateFromDisk:true}),new RegExp(error)); assert.deepEqual(calls,[]);assert.equal(manager.woowMcpRefreshes.size,0);
  }
  // Real close timeout and real lifecycle queue: a request deadline does not
  // release ownership of the old native writer. Late close alone is insufficient.
  const pending=harness();let releaseClose,closeCalls=0,promptAccepted=false;
  const closing=new Promise(resolve=>{releaseClose=resolve;});
  const oldSession=pending.existing.session;
  oldSession.close=()=>{closeCalls++;return closing;};
  delete pending.manager.closeReloadedSession;
  pending.manager.reloadedSessionCloses=new WeakMap();
  pending.manager.rescueTimeouts={reloadSessionCloseMs:10};
  pending.manager.logger={trace(){},warn(){}};
  pending.manager.runs={hasRun:()=>false,createPendingRun:()=>{promptAccepted=true;return {};}};
  const options={requireIdle:true,requirePersistence:true,rehydrateFromDisk:true};
  const first=pending.manager.reloadAgentSession(agent.id,undefined,options);
  const queued=pending.manager.reloadAgentSession(agent.id,undefined,options);
  await Promise.all([assert.rejects(first,/Timed out closing/),assert.rejects(queued,/Timed out closing/)]);
  assert.equal(closeCalls,1);assert.equal(pending.existing.lifecycle,'error');
  assert.throws(()=>pending.manager.streamAgent(agent.id,'after timeout'),/MCP_NATIVE_UNAVAILABLE/);
  releaseClose();await closing;await new Promise(resolve=>setImmediate(resolve));
  assert.throws(()=>pending.manager.streamAgent(agent.id,'closed but not resumed'),/MCP_NATIVE_UNAVAILABLE/);
  assert.equal(promptAccepted,false);
  await pending.manager.reloadAgentSession(agent.id,undefined,options);
  assert.notStrictEqual(pending.existing.session,oldSession);
  assert.equal(pending.existing.persistence.sessionId,'original-native');
  assert.deepEqual(pending.calls,['resume']);assert.equal(closeCalls,1);
  pending.manager.streamAgent(agent.id,'after explicit resume');assert.equal(promptAccepted,true);
  const good=harness();await good.manager.reloadAgentSession(agent.id,undefined,{requireIdle:true,requirePersistence:true,rehydrateFromDisk:true});assert.deepEqual(good.calls,['close','resume']);
  for(const options of [{closeError:true},{resumeError:true}]) {
    const failed=harness(options);await assert.rejects(failed.manager.reloadAgentSession(agent.id,undefined,{requireIdle:true,requirePersistence:true,rehydrateFromDisk:true}),/failed/);assert.equal(failed.manager.woowMcpRefreshes.size,0);
  }
});

test('managed removals and changes override stale config; Pi reloads native files without ACP injection', t => {
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'paseo-config-'));t.after(()=>fs.rmSync(tmp,{recursive:true}));
 fs.mkdirSync(path.join(tmp,'shared'));fs.mkdirSync(path.join(tmp,'claude'));
 fs.writeFileSync(path.join(tmp,'shared/managed.json'),JSON.stringify({managedServers:['old','new']}));
 fs.writeFileSync(path.join(tmp,'claude/.claude.json'),JSON.stringify({mcpServers:{new:{type:'stdio',command:'fresh'}}}));
 const env={PI_AGENT_DATA_DIR:tmp};
 const config={provider:'claude',model:'keep-model',mcpServers:{old:{command:'stale'},new:{command:'stale'},private_only:{command:'keep'}}};
 const actual=refreshedManagedConfig(config,env);assert.equal(actual.model,'keep-model');assert.equal(actual.mcpServers.new.command,'fresh');assert.equal(actual.mcpServers.private_only.command,'keep');assert(!('old' in actual.mcpServers));
 const pi=refreshedManagedConfig({...config,provider:'pi'},env);assert.deepEqual(Object.keys(pi.mcpServers),['private_only']);
 fs.writeFileSync(path.join(tmp,'claude/.claude.json'),'{invalid');assert.throws(()=>refreshedManagedConfig(config,env));
});
