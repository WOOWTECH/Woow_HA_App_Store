import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {refreshedManagedConfig} from '../src/managed-mcp-config.mjs';
import {refreshSharedMcp} from '../src/mcp-refresh.mjs';
import {patchRefreshSource, refreshRecipes} from '../src/mcp-refresh-patch.mjs';

const agent = {id:'existing-agent', provider:'codex', status:'idle', persistence:{provider:'codex',sessionId:'original-native'}};
test('refresh retains native persistence and reports no tool execution claim', async () => {
  const calls=[];
  const client={fetchAgent:async()=>({agent}),refreshAgent:async (id,requestId,options)=>{calls.push([id,requestId,options]);return {agentId:id};}};
  const result=await refreshSharedMcp(client,agent.id,async()=>({configurationHash:'a'.repeat(64)}));
  assert.deepEqual(calls,[[agent.id,undefined,{managedMcpRefresh:true}]]); assert.equal(result.refresh.historyPreserved,true);
  assert.equal(result.refresh.toolsVerified,false);
});
test('error state permits guarded recovery after a close timeout', async()=>{const before={...agent,status:'error'};let n=0;const result=await refreshSharedMcp({fetchAgent:async()=>({agent:++n===1?before:agent}),refreshAgent:async()=>({agentId:agent.id})},agent.id,async()=>({configurationHash:'b'.repeat(64)}));assert.equal(result.refresh.state,'resumed');});
test('busy, unknown, and unpersisted sessions do not synchronize or restart', async () => {
  for(const value of [{...agent,status:'running'},{...agent,status:'waiting'},{...agent,pendingPermissions:[{}]},
    {...agent,activeTurn:{id:'turn'}},{...agent,activeForegroundTurnId:'turn'},{...agent,pendingReplacement:true},{...agent,archivedAt:'2026-11-26'},
    {...agent,persistence:null},{...agent,persistence:{provider:'codex',sessionId:''}},
    {...agent,persistence:{provider:'claude',sessionId:'wrong-provider'}},{...agent,id:'another-agent'},{...agent,provider:'unknown'}]) {
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
