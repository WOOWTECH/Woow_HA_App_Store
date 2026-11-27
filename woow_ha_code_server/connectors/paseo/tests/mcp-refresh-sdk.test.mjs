import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {applyMcpRefreshPatch, mcpRefreshPatchReady, patchRefreshSource, refreshRecipes,
  MCP_REFRESH_PATCH_ID, MCP_REFRESH_HELPER_PATH, MCP_REFRESH_HELPER_SHA256} from '../src/mcp-refresh-patch.mjs';
import {copyMcpRefreshFixture} from './mcp-refresh-fixture.mjs';

// CI installs a generation with install-runtime.sh and supplies that exact root.
// A developer may alternatively npm ci in runtime-manifest; never use legacy runtime/.
const sdkRoot = path.resolve(process.env.WOOW_PASEO_TEST_RUNTIME || fileURLToPath(new URL('../runtime-manifest/', import.meta.url)));
const available = fs.existsSync(path.join(sdkRoot, refreshRecipes[0].path));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const id = '17d31a6c-4bd1-4ff1-af25-7a714ab47311';
const handle = {provider:'codex', sessionId:'original-native-session'};
const guarded = {managedMcpRefresh:true, requireIdle:true, requirePersistence:true, rehydrateFromDisk:true};
const logger = {trace(){}, info(){}, warn(){}, error(){}};

function preparedCopy(destination) {
  const modules = path.join(destination, 'node_modules');
  fs.mkdirSync(path.join(modules, '@getpaseo'), {recursive:true});
  for (const name of fs.readdirSync(path.join(sdkRoot, 'node_modules'))) {
    if (name === '@getpaseo') {
      for (const pkg of fs.readdirSync(path.join(sdkRoot, 'node_modules', name))) {
        const source = path.join(sdkRoot, 'node_modules', name, pkg);
        const target = path.join(modules, name, pkg);
        if (['server','client','protocol'].includes(pkg)) fs.cpSync(source, target, {recursive:true});
        else fs.symlinkSync(source, target, 'dir');
      }
    } else fs.symlinkSync(path.join(sdkRoot, 'node_modules', name), path.join(modules, name), 'dir');
  }
  copyMcpRefreshFixture(sdkRoot,destination);
  for (const recipe of refreshRecipes) {
    const file = path.join(destination, recipe.path);
    const source = fs.readFileSync(file, 'utf8');
    fs.writeFileSync(file.replace(/\.js$/, '-upstream.js'), source);
  }
  fs.rmSync(path.join(destination, MCP_REFRESH_HELPER_PATH), {force:true});
}

function managerHarness(AgentManager, {busy=false, persistence=handle, close, resumeError=false, onPrepare}={}) {
  const calls=[], prepared=[], registrations=[];
  const session={capabilities:{supportsMcpServers:true}, close:async()=>{calls.push('close');await close?.();}};
  const existing={id, provider:'codex', persistence, lifecycle:busy?'running':'idle', pendingPermissions:new Map(),
    config:{provider:'codex',cwd:'/workspace',model:'keep-model',modeId:'default',mcpServers:{old:{type:'stdio',command:'stale'},private_only:{type:'stdio',command:'keep'}}},
    session, labels:{user:'ordinary'}, metadata:{preserve:true}, historyPrimed:true, launchEnv:{KEEP:'value'}};
  const manager=Object.create(AgentManager.prototype);
  Object.assign(manager,{
    agents:new Map([[id,existing]]), lifecycleMutationTails:new Map(), collectingRuntimes:new Set(), historySessions:new WeakSet(),
    pendingCancellations:new Map(), reloadedSessionCloses:new WeakMap(), rescueTimeouts:{reloadSessionCloseMs:15},
    trackAgentRegistrationOperation:operation=>operation, assertAcceptingAgentRegistrations(){},
    cancelAgentRunBefore:async()=>{calls.push('interrupt');existing.lifecycle='idle';},
    requireClient:()=>({createSession:async()=>{calls.push('create');return {capabilities:{}};},resumeSession:async(saved,config)=>{
      assert.strictEqual(saved,persistence);calls.push('resume');if(resumeError)throw Error('resume failed');return {capabilities:{},close:async()=>{}};
    }}),
    prepareSessionConfig:async config=>{calls.push('prepare');prepared.push(config);await onPrepare?.(manager);return {storedConfig:config,launchConfig:config,paseoToolPolicy:{}};},
    paseoToolPolicies:new Map(), buildLaunchContext:async()=>({}), resolveInitialPersistedTitle:async()=>null,
    resolveProviderLaunchConfig:config=>config, launchOptionsFor:()=>({}),
    drainSessionEvents:async()=>{calls.push('drain');}, cancelRunningProviderSubagents(){}, clearProviderBackgroundWork(){},
    prepareAgentForClosure:agent=>agent, persistSnapshot:async()=>{calls.push('persist');}, requireExternalMcpSupport:async()=>{},
    registerSession:(replacement,config,agentId,options)=>{
      assert.equal(agentId,id);calls.push('register');registrations.push(options);
      existing.session=replacement;existing.config=config;existing.lifecycle='idle';return existing;
    },
    timelineStore:new Map(), providerSubagents:{deleteParent:()=>[]}, dispatch(){},
    logger, emitState(){}, raiseErrorAttention(){}, emitClosedAgent(){}, detachPluginTools(){}, closeUnregisteredSession:async()=>{},
    runs:{hasRun:()=>false,createPendingRun:()=>{calls.push('prompt');return {};}}
  });
  return {manager,existing,session,calls,prepared,registrations};
}

function sessionHarness(Session, {loaded=true, failReload, reload}={}) {
  const calls=[], messages=[];
  const snapshot={id,provider:'codex',persistence:handle};
  const record={...snapshot,cwd:'/workspace',createdAt:'2026-11-26T00:00:00Z',updatedAt:'2026-11-26T00:00:00Z',config:{cwd:'/workspace'}};
  const session=Object.create(Session.prototype);
  const manager={getAgent:()=>loaded?snapshot:null,
    unarchiveSnapshot:async()=>{calls.push(['unarchive']);return snapshot;}, notifyAgentState:()=>calls.push(['notify']),
    reloadAgentSession:async(agentId,overrides,options)=>{calls.push(['reload',options]);if(failReload)throw Error(failReload);return reload?reload(agentId,overrides,options):snapshot;},
    resumeAgentFromPersistence:async(saved,_config,agentId)=>{assert.equal(agentId,id);assert.equal(saved.sessionId,handle.sessionId);calls.push(['cold-load']);loaded=true;return snapshot;},
    getRegisteredProviderIds:()=>['codex'], hydrateTimelineFromProvider:async()=>calls.push(['hydrate']), getTimeline:()=>[],
    waitForAgentClose:async()=>{}, createAgentFromRecord:()=>assert.fail('new native conversation')};
  Object.assign(session,{agentManager:manager, agentStorage:{get:async()=>{calls.push(['read']);return record;}},
    providerSnapshotManager:{listRegisteredProviderIds:()=>['codex']}, sessionLogger:logger,
    restoreOwningWorkspaceForLegacyAgentRefresh:async()=>calls.push(['restore-workspace']),
    interruptAgentIfRunning:async()=>calls.push(['interrupt']), agentUpdates:{forwardLiveAgent:async()=>calls.push(['forward'])},
    emit:message=>messages.push(message)});
  return {session,calls,messages};
}

test('real pinned 0.17.5 SDK managed refresh in isolated prepared copies', {skip:!process.env.WOOW_PASEO_TEST_RUNTIME&&!available}, async t=>{
  assert.ok(available, 'WOOW_PASEO_TEST_RUNTIME must point to the installed generation root');
  const originalHashes=refreshRecipes.map(recipe=>sha(fs.readFileSync(path.join(sdkRoot,recipe.path))));
  const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'paseo-mcp-0175-'));
  t.after(()=>{
    assert.deepEqual(refreshRecipes.map(recipe=>sha(fs.readFileSync(path.join(sdkRoot,recipe.path)))),originalHashes,'installed SDK changed');
    fs.rmSync(tmp,{recursive:true,force:true});
  });
  const copy=path.join(tmp,'prepared');preparedCopy(copy);
  assert.equal(mcpRefreshPatchReady(copy),false);
  applyMcpRefreshPatch(copy);
  assert.equal(mcpRefreshPatchReady(copy),true);
  const sdkImport=relative=>import(pathToFileURL(path.join(copy,'node_modules/@getpaseo',relative)).href);
  const [{AgentManager},{Session},{DaemonClient},protocol,{AgentManager:UpstreamManager},{Session:UpstreamSession}]=await Promise.all([
    sdkImport('server/dist/server/server/agent/agent-manager.js'),sdkImport('server/dist/server/server/session.js'),
    sdkImport('client/dist/daemon-client.js'),sdkImport('protocol/dist/messages.js'),
    sdkImport('server/dist/server/server/agent/agent-manager-upstream.js'),sdkImport('server/dist/server/server/session-upstream.js')]);
  const data=path.join(tmp,'data');fs.mkdirSync(path.join(data,'shared'),{recursive:true});fs.mkdirSync(path.join(data,'claude'));
  const managedFile=path.join(data,'shared/managed.json');const nativeFile=path.join(data,'claude/.claude.json');
  fs.writeFileSync(managedFile,JSON.stringify({managedServers:['old','new']}));
  fs.writeFileSync(nativeFile,JSON.stringify({mcpServers:{new:{type:'stdio',command:'fresh'}}}));
  const priorData=process.env.PI_AGENT_DATA_DIR, priorClaude=process.env.CLAUDE_CONFIG_DIR;
  process.env.PI_AGENT_DATA_DIR=data;process.env.CLAUDE_CONFIG_DIR=path.join(data,'claude');
  t.after(()=>{if(priorData===undefined)delete process.env.PI_AGENT_DATA_DIR;else process.env.PI_AGENT_DATA_DIR=priorData;if(priorClaude===undefined)delete process.env.CLAUDE_CONFIG_DIR;else process.env.CLAUDE_CONFIG_DIR=priorClaude;});

  await t.test('all four before/after hashes, helper bytes and receipt ID are pinned; patch is idempotent',()=>{
    assert.equal(refreshRecipes.length,4);assert.match(MCP_REFRESH_PATCH_ID,/^[a-f0-9]{64}$/);
    assert.equal(sha(fs.readFileSync(new URL('../src/managed-mcp-config.mjs',import.meta.url))),MCP_REFRESH_HELPER_SHA256);
    for(const recipe of refreshRecipes){
      const upstream=fs.readFileSync(path.join(copy,recipe.path.replace(/\.js$/,'-upstream.js')),'utf8');
      assert.equal(sha(upstream),recipe.before);assert.equal(sha(patchRefreshSource(upstream,recipe)),recipe.after);
      assert.equal(sha(fs.readFileSync(path.join(copy,recipe.path))),recipe.after);
    }
    const installerFixture=path.join(tmp,'installer-fixture');
    copyMcpRefreshFixture(copy,installerFixture);
    for(const recipe of refreshRecipes)assert.equal(sha(fs.readFileSync(path.join(installerFixture,recipe.path))),recipe.before);
    applyMcpRefreshPatch(copy);assert.equal(mcpRefreshPatchReady(copy),true);
  });
  await t.test('unknown source or helper corruption fails readiness; validate all SDK sources before writing',()=>{
    const recipe=refreshRecipes.at(-1),file=path.join(copy,recipe.path),bytes=fs.readFileSync(file);
    fs.appendFileSync(file,'\n// corrupt');assert.equal(mcpRefreshPatchReady(copy),false);
    fs.rmSync(path.join(copy,MCP_REFRESH_HELPER_PATH));
    assert.throws(()=>applyMcpRefreshPatch(copy),{code:'MCP_REFRESH_SOURCE_MISMATCH'});
    assert.equal(fs.existsSync(path.join(copy,MCP_REFRESH_HELPER_PATH)),false);
    fs.writeFileSync(file,bytes);applyMcpRefreshPatch(copy);
    fs.appendFileSync(path.join(copy,MCP_REFRESH_HELPER_PATH),'\n// corrupt');assert.equal(mcpRefreshPatchReady(copy),false);
    applyMcpRefreshPatch(copy);assert.equal(mcpRefreshPatchReady(copy),true);
  });
  await t.test('protocol and client carry the flag only for managed requests',async()=>{
    const base={type:'refresh_agent_request',agentId:id,requestId:'request'};
    assert.deepEqual(protocol.RefreshAgentRequestMessageSchema.parse(base),base);
    assert.equal(protocol.SessionInboundMessageSchema.parse({...base,managedMcpRefresh:true}).managedMcpRefresh,true);
    assert.equal(protocol.RefreshAgentRequestMessageSchema.safeParse({...base,managedMcpRefresh:false}).success,false);
    const client=Object.create(DaemonClient.prototype);const sent=[];
    client.createRequestId=value=>value||'request';client.sendRequest=async request=>{sent.push(request.message);return {agentId:id};};
    await client.refreshAgent(id);await client.refreshAgent(id,'explicit',{managedMcpRefresh:true});
    assert.deepEqual(sent,[base,{...base,requestId:'explicit',managedMcpRefresh:true}]);
  });
  await t.test('normal Web loaded and cold reload paths match the upstream session exactly',async()=>{
    for(const loaded of [true,false]){
      const before=sessionHarness(UpstreamSession,{loaded}),after=sessionHarness(Session,{loaded});
      const request={type:'refresh_agent_request',agentId:id,requestId:'request'};
      await before.session.handleRefreshAgentRequest(request);await after.session.handleRefreshAgentRequest(request);
      assert.deepEqual(after.calls,before.calls);assert.deepEqual(after.messages,before.messages);
      assert.ok(after.calls.some(([action])=>action==='restore-workspace'));assert.ok(after.calls.some(([action])=>action==='unarchive'));
      assert.ok(after.calls.some(([action])=>action===(loaded?'interrupt':'cold-load')));
      assert.equal(after.messages.at(-1)?.payload?.status,'agent_refreshed');
    }
  });
  await t.test('normal manager reload keeps upstream interruption and configuration behavior',async()=>{
    const before=managerHarness(UpstreamManager,{busy:true}),after=managerHarness(AgentManager,{busy:true});
    await before.manager.reloadAgentSession(id,undefined,{rehydrateFromDisk:true});
    await after.manager.reloadAgentSession(id,undefined,{rehydrateFromDisk:true});
    assert.deepEqual(after.calls,before.calls);assert.deepEqual(after.prepared,before.prepared);
    assert.equal(after.prepared[0].mcpServers.old.command,'stale');assert.equal(after.prepared[0].mcpServers.new,undefined);
    assert.ok(after.calls.includes('interrupt'));
  });
  await t.test('managed session never restores, unarchives or interrupts; cold sessions are refused',async()=>{
    const warm=sessionHarness(Session);
    await warm.session.handleRefreshAgentRequest({type:'refresh_agent_request',agentId:id,requestId:'request',managedMcpRefresh:true});
    assert.deepEqual(warm.calls,[['reload',guarded],['hydrate'],['forward']]);
    assert.equal(warm.messages.at(-1).payload.status,'agent_refreshed');
    const cold=sessionHarness(Session,{loaded:false});
    await cold.session.handleRefreshAgentRequest({type:'refresh_agent_request',agentId:id,requestId:'request',managedMcpRefresh:true});
    assert.deepEqual(cold.calls,[]);assert.equal(cold.messages[0].type,'rpc_error');assert.equal(cold.messages[0].payload.error,'MCP_NATIVE_UNAVAILABLE');
  });
  await t.test('ordinary user agents resume exactly their persistence with refreshed config and labels intact',async()=>{
    const h=managerHarness(AgentManager);
    await h.manager.reloadAgentSession(id,undefined,guarded);
    assert.deepEqual(h.calls,['prepare','close','drain','persist','resume','register']);
    assert.equal(h.existing.persistence.sessionId,handle.sessionId);assert.notStrictEqual(h.existing.session,h.session);
    assert.equal(h.prepared[0].mcpServers.old,undefined);assert.equal(h.prepared[0].mcpServers.new.command,'fresh');
    assert.equal(h.prepared[0].mcpServers.private_only.command,'keep');assert.equal(h.prepared[0].model,'keep-model');
    assert.deepEqual(h.registrations[0].labels,{user:'ordinary'});assert.deepEqual(h.registrations[0].metadata,{preserve:true});
    assert.equal(h.registrations[0].historyPrimed,false);assert.equal(h.manager.woowMcpRefreshes.size,0);
  });
  await t.test('busy turns, permissions, replacement and missing/malformed persistence fail before config or close',async()=>{
    for(const mutate of [h=>{h.existing.lifecycle='running';},h=>{h.existing.activeForegroundTurnId='turn';},
      h=>h.existing.pendingPermissions.set('permission',{}),h=>{h.existing.pendingReplacement=true;},h=>h.manager.pendingCancellations.set(id,Promise.resolve())]){
      const h=managerHarness(AgentManager);mutate(h);
      await assert.rejects(h.manager.reloadAgentSession(id,undefined,guarded),/SESSION_BUSY/);assert.deepEqual(h.calls,[]);
      assert.equal(h.manager.woowMcpRefreshes.size,0);
    }
    for(const persistence of [null,{provider:'codex',sessionId:''},{provider:'claude',sessionId:'other'}]){
      const h=managerHarness(AgentManager,{persistence});await assert.rejects(h.manager.reloadAgentSession(id,undefined,guarded),/MCP_RESUME_UNAVAILABLE/);assert.deepEqual(h.calls,[]);
    }
  });
  await t.test('managed refresh refuses unloaded, collected and history-only runtimes',async()=>{
    for(const mutate of [h=>h.manager.agents.clear(),h=>{h.existing.session=null;},h=>h.manager.collectingRuntimes.add(id),h=>h.manager.historySessions.add(h.session)]){
      const h=managerHarness(AgentManager);mutate(h);
      await assert.rejects(h.manager.reloadAgentSession(id,undefined,guarded),/MCP_NATIVE_UNAVAILABLE/);assert.deepEqual(h.calls,[]);
    }
  });
  await t.test('turn racing the client check is rejected inside the lifecycle lane',async()=>{
    const h=managerHarness(AgentManager);const refresh=h.manager.reloadAgentSession(id,undefined,guarded);
    h.manager.streamAgent(id,'racing prompt');
    h.existing.activeForegroundTurnId='racing-turn';
    await assert.rejects(refresh,/SESSION_BUSY/);assert.deepEqual(h.calls,['prompt']);
  });
  await t.test('stream guard runs before runtime collection or history loading while refresh awaits preparation',async()=>{
    const h=managerHarness(AgentManager,{onPrepare:async manager=>{
      manager.collectingRuntimes.add(id);manager.historySessions.add(h.session);
      manager.streamAfterRuntimeCollection=()=>assert.fail('collection bypassed refresh guard');
      manager.streamAfterHistoryLoad=()=>assert.fail('history bypassed refresh guard');
      assert.throws(()=>manager.streamAgent(id,'race'),/SESSION_BUSY/);
      manager.collectingRuntimes.delete(id);manager.historySessions.delete(h.session);
    }});
    await h.manager.reloadAgentSession(id,undefined,guarded);assert.equal(h.manager.woowMcpRefreshes.size,0);
  });
  await t.test('a turn or permission becoming active during asynchronous preparation cannot be closed',async()=>{
    for(const change of [h=>{h.existing.lifecycle='running';},h=>h.existing.pendingPermissions.set('raced-permission',{})]){
      const h=managerHarness(AgentManager,{onPrepare:async()=>change(h)});
      await assert.rejects(h.manager.reloadAgentSession(id,undefined,guarded),/SESSION_BUSY/);
      assert.deepEqual(h.calls,['prepare']);assert.strictEqual(h.existing.session,h.session);
      assert.equal(h.manager.woowMcpRefreshes.size,0);
    }
  });
  await t.test('invalid managed definitions fail before closing the native writer',async()=>{
    const h=managerHarness(AgentManager);const saved=fs.readFileSync(nativeFile);fs.writeFileSync(nativeFile,'private-config-not-json');
    try {await assert.rejects(h.manager.reloadAgentSession(id,undefined,guarded),/^Error: MCP_CONFIG_INVALID$/);assert.deepEqual(h.calls,[]);}
    finally {fs.writeFileSync(nativeFile,saved);}
  });
  await t.test('close timeout and queued refreshes share one close; retired handles cannot stream even after late close',async()=>{
    let release;const closing=new Promise(resolve=>{release=resolve;});
    const h=managerHarness(AgentManager,{close:()=>closing});
    const first=h.manager.reloadAgentSession(id,undefined,guarded),queued=h.manager.reloadAgentSession(id,undefined,guarded);
    await Promise.all([assert.rejects(first,/Timed out closing/),assert.rejects(queued,/Timed out closing/)]);
    assert.equal(h.calls.filter(call=>call==='close').length,1);assert.equal(h.calls.includes('resume'),false);assert.equal(h.existing.lifecycle,'error');
    assert.throws(()=>h.manager.streamAgent(id,'after timeout'),/MCP_NATIVE_UNAVAILABLE/);
    h.manager.collectingRuntimes.add(id);h.manager.historySessions.add(h.session);
    assert.throws(()=>h.manager.streamAgent(id,'collecting retired writer'),/MCP_NATIVE_UNAVAILABLE/);
    release();await closing;await new Promise(resolve=>setImmediate(resolve));
    h.manager.collectingRuntimes.delete(id);h.manager.historySessions.delete(h.session);
    assert.throws(()=>h.manager.streamAgent(id,'closed but not resumed'),/MCP_NATIVE_UNAVAILABLE/);
    await h.manager.reloadAgentSession(id,undefined,guarded);
    assert.equal(h.calls.filter(call=>call==='close').length,1);assert.equal(h.calls.filter(call=>call==='resume').length,1);
    assert.notStrictEqual(h.existing.session,h.session);assert.equal(h.existing.persistence.sessionId,handle.sessionId);
    h.manager.streamAgent(id,'after explicit resume');assert.equal(h.calls.at(-1),'prompt');
  });
  await t.test('close or resume failure never starts a second writer and always releases the refresh guard',async()=>{
    for(const options of [{close:async()=>{throw Error('close failed');}},{resumeError:true}]){
      const h=managerHarness(AgentManager,options);
      await assert.rejects(h.manager.reloadAgentSession(id,undefined,guarded),/failed/);assert.equal(h.manager.woowMcpRefreshes.size,0);
      assert.equal(h.calls.includes('create'),false);assert.equal(h.calls.filter(call=>call==='resume').length,options.resumeError?1:0);
      assert.throws(()=>h.manager.streamAgent(id,'failed retired writer'),/MCP_NATIVE_UNAVAILABLE/);
    }
  });
});
