import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
import * as state from '../src/state.mjs';
import * as layout from '../src/runtime-layout.mjs';

// Exercise the complete runtime module through its public APIs. Only the OS,
// provider launchers and daemon SDK boundary are simulated; no provider runs.
async function fixture(t, options = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'agent-connect-spec-'));
  const settings = {HOME:path.join(root,'home'), PI_AGENT_DATA_DIR:path.join(root,'data'),
    PI_CODING_AGENT_DIR:path.join(root,'pi'), WOOW_CONNECTOR_DATA_DIR:path.join(root,'connectors'),
    WOOW_PASEO_RUNTIME_DIR:path.join(root,'runtime')};
  const before = Object.fromEntries(Object.keys(settings).map(key => [key, process.env[key]]));
  Object.assign(process.env, settings);
  const loc = state.locations(), runtimeRoot = layout.runtimeDirectory(loc);
  state.privateDirectory(loc.paseoHome);
  state.updateState({installationId:'spec-installation', desiredEnabled:true, phase:'running', ...options.state});
  state.atomicJson(path.join(loc.paseoHome,'.pi-paseo-owner.json'), {installationId:'spec-installation', home:loc.paseoHome});
  const packageFile = path.join(runtimeRoot,'node_modules/@getpaseo/cli/package.json');
  state.atomicJson(packageFile,{version:layout.PASEO_VERSION});
  const webFile = path.join(runtimeRoot,'node_modules/@getpaseo/server/dist/server/web-ui/index.html');
  fs.mkdirSync(path.dirname(webFile),{recursive:true}); fs.writeFileSync(webFile,'fixture');
  if (options.config) state.atomicJson(path.join(loc.paseoHome,'config.json'),options.config);
  const pid = 424242, instance = {pid,startedAt:'2026-11-26T00:00:00Z',uid:process.getuid(),heartbeat:true,listen:'127.0.0.1:6769'};
  const f = {loc,events:[], instance:options.running === false ? null : instance,
    revision:layout.RUNTIME_REVISION, reachable:true, supervisors:[], agents:[], ...options};
  const procFs = {...fs,
    readdirSync(file,...args) {return file === '/proc' ? f.supervisors.map(String) : fs.readdirSync(file,...args);},
    statSync(file,...args) {return /^\/proc\/\d+$/.test(String(file)) ? {uid:process.getuid()} : fs.statSync(file,...args);},
    realpathSync(file,...args) {return file === `/proc/${pid}/exe` ? fs.realpathSync(process.execPath) : fs.realpathSync(file,...args);},
    readFileSync(file,...args) {
      if (file === '/proc/sys/kernel/random/boot_id') return '12345678-1234-1234-1234-123456789abc\n';
      if (file === `/proc/${pid}/stat`) return `${pid} (Paseo Supervisor) ${Array(19).fill('0').join(' ')} 12345`;
      if (file === `/proc/${pid}/cmdline`) return 'Paseo Supervisor\0';
      if (file === `/proc/${pid}/environ`) {
        if (f.procError) throw Object.assign(new Error(),{code:f.procError});
        return `PASEO_HOME=${f.supervisorHome || loc.paseoHome}\0PI_PASEO_RUNTIME_REVISION=${f.revision}\0PI_PASEO_CONNECTION_PROFILE_VERSION=1\0`;
      }
      return fs.readFileSync(file,...args);
    }
  };
  const providers = ['claude','codex','pi'].map(provider => ({provider,available:true,modes:[]}));
  let turn = 0, marker;
  f.client = {
    close:async()=>{},
    getDaemonStatus:async()=>{
      f.events.push('status');
      if (!f.reachable) throw new state.RuntimeError('DAEMON_REQUEST_TIMEOUT');
      return {pid:pid+1,providers,relay:{enabled:true,connected:true}};
    },
    reloadDaemonConfig:async()=>{
      f.events.push('reload');
      if (f.reloadError) throw new state.RuntimeError(f.reloadError);
      f.reachable = f.recoverOnReload === true || f.reachable;
      return f.reloadReceipt || {appliedPaths:[],restartRequiredPaths:[],overrideControlledPaths:[]};
    },
    listProviderModels:async()=>({models:[{id:'test-model',isDefault:true}]}),
    getProvidersSnapshot:async()=>({entries:providers}),
    fetchWorkspaces:async()=>({entries:[{id:'test-workspace',workspaceDirectory:path.join(loc.stateDir,'acceptance-workspace')}],pageInfo:{hasMore:false}}),
    createAgent:async options=>{
      const agent = {id:'spec-agent-id',...options}; f.agents.push(agent);
      marker = options.initialPrompt.match(/Remember (\w+)/)[1]; turn = 0; return agent;
    },
    waitForFinish:async()=>({status:'idle'}),
    fetchAgentTimeline:async()=>({entries:[{turnId:String(turn),seqStart:turn,seqEnd:turn,item:{type:'assistant_message',text:marker}}]}),
    sendAgentMessage:async()=>{turn++;},
    archiveAgent:async()=>({archivedAt:'2026-11-26T00:00:01Z'})
  };
  const key = `__runtime_spec_${randomUUID()}`, values = [];
  globalThis[key] = values;
  function moduleUrl(exports) {
    const index = values.push(exports)-1;
    const code = `const value = globalThis[${JSON.stringify(key)}][${index}];\n` + Object.keys(exports).map(name =>
      name === 'default' ? 'export default value.default;' : `export const ${name} = value.${name};`).join('\n');
    return `data:text/javascript,${encodeURIComponent(code)}`;
  }
  const runtimeUrl = new URL(`../src/runtime.mjs?spec=${randomUUID()}`,import.meta.url).href;
  const identityUrl = new URL(`../src/daemon-identity.mjs?spec=${randomUUID()}`,import.meta.url).href;
  const mocked = new Map([
    ['node:fs',moduleUrl({default:procFs})],
    ['node:net',moduleUrl({default:{createServer:()=>({once(){},listen(_port,_host,fn){fn();},close(fn){fn();}})}})],
    ['./state.mjs',moduleUrl({...state,processIdentity:pidValue=>pidValue === pid ? 'fixture-birth' : state.processIdentity(pidValue)})],
    ['./process.mjs',moduleUrl({findExecutable:()=>null,runProcess:async(_exe,args)=>{
      if (args.includes('--version')) {f.events.push('version'); return layout.PASEO_VERSION;}
      assert.ok(args.includes('start'),'only a simulated daemon start may execute');
      f.events.push('spawn'); f.instance = instance; f.supervisorHome = loc.paseoHome;
      if (f.startError) throw new state.RuntimeError(f.startError);
      return '{}';
    }})],
    ['./runtime-layout.mjs',moduleUrl({...layout,runtimeReady:()=>f.installed !== false,
      previousRuntimeDirectory:()=>null,codeServerLegacyRuntimeDirectory:()=>null,prunePlan:()=>({skipped:true})})],
    ['./provider-launchers.mjs',moduleUrl({providerEnvironment:()=>({...settings,CLAUDE_CONFIG_DIR:path.join(root,'claude'),CODEX_HOME:path.join(root,'codex')}),
      resolveProviderLaunchers:async()=>Object.fromEntries(providers.map(({provider})=>[provider,{startup:'ready'}])),
      configureProviders:()=>f.desiredProviders || {}})],
    ['./host-checks.mjs',moduleUrl({checkProcessTable:async()=>({checked:false})})]
  ]);
  const sdk = new Map();
  function sdkModule(relative,exports) {sdk.set(pathToFileURL(path.join(runtimeRoot,'node_modules/@getpaseo',relative)).href,moduleUrl(exports));}
  sdkModule('server/dist/server/server/daemon-instance.js',{
    readDaemonInstance:async()=>f.instance,
    stopDaemonInstance:async(_home,stopOptions)=>{
      f.events.push('stop'); assert.equal(stopOptions.force,false);
      if (f.stopError) throw new state.RuntimeError(f.stopError);
      f.instance = null;
    }
  });
  sdkModule('server/dist/server/server/config.js',{
    readPersistedConfig:home=>JSON.parse(fs.readFileSync(path.join(home,'config.json'),'utf8')),
    savePersistedConfig:(home,config)=>{f.events.push('write-config'); state.atomicJson(path.join(home,'config.json'),config);}
  });
  sdkModule('cli/dist/utils/client.js',{connectToDaemon:async()=>f.client});
  const hooks = registerHooks({resolve(specifier,context,nextResolve) {
    if ((context.parentURL === runtimeUrl || context.parentURL === identityUrl) && mocked.has(specifier)) return {url:mocked.get(specifier),shortCircuit:true};
    if (context.parentURL === runtimeUrl && sdk.has(specifier)) return {url:sdk.get(specifier),shortCircuit:true};
    return nextResolve(specifier,context);
  }});
  t.after(()=>{
    hooks.deregister(); delete globalThis[key];
    for (const [name,value] of Object.entries(before)) value === undefined ? delete process.env[name] : process.env[name] = value;
    fs.rmSync(root,{recursive:true,force:true});
  });
  const identity = await import(identityUrl);
  mocked.set('./daemon-identity.mjs',moduleUrl({...identity,observeOwnedInstance:async()=>null,rememberOwnedInstance:async()=>{}}));
  f.runtime = await import(runtimeUrl);
  f.readState = state.readState;
  f.updateState = state.updateState;
  f.pid = pid;
  return f;
}

test('activation rejects an unpublished same-home supervisor before writing config or spawning', async t => {
  const f = await fixture(t,{running:false,supervisors:[424242]});
  await assert.rejects(f.runtime.activate(),{code:'DAEMON_ALREADY_RUNNING'});
  assert.equal(f.events.includes('write-config'),false);
  assert.equal(f.events.includes('spawn'),false);
});

test('acceptance requires a confirmed archive receipt after both replies', async t => {
  const f = await fixture(t);
  f.client.archiveAgent = async()=>({});
  const result = await f.runtime.acceptance({providers:['claude']});
  assert.equal(result.requestedPassed,false);
  assert.equal(result.providers[0].passed,false);
  assert.equal(result.providers[0].code,'ACCEPTANCE_CLEANUP_FAILED');
  assert.equal(result.providers[0].firstReply,true);
  assert.equal(result.providers[0].followup,true);
});

test('failed cleanup keeps its base error precedence when a turn also fails', async t => {
  const f = await fixture(t);
  f.client.waitForFinish = async()=>({status:'permission'});
  f.client.archiveAgent = async()=>({});
  const result = await f.runtime.acceptance({providers:['claude']});
  assert.equal(result.requestedPassed,false);
  assert.equal(result.providers[0].passed,false);
  assert.equal(result.providers[0].code,'ACCEPTANCE_CLEANUP_FAILED');
});

test('a transport timeout while archive is pending cannot pass acceptance', async t => {
  const f = await fixture(t);
  let entered;
  const archiving = new Promise(resolve=>{entered=resolve;});
  f.client.archiveAgent = async()=>{entered(); await new Promise(()=>{});};
  t.mock.timers.enable({apis:['setTimeout']});
  const pending = f.runtime.acceptance({providers:['claude'],timeoutMs:10000});
  await archiving;
  t.mock.timers.tick(50000);
  const result = await pending;
  assert.equal(result.requestedPassed,false);
  assert.equal(result.providers[0].passed,false);
  assert.equal(result.providers[0].code,'DAEMON_REQUEST_TIMEOUT');
  assert.notEqual(result.providers[0].cleanup?.archived,true);
});

test('new acceptance agents retain this installation ownership label', async t => {
  const f = await fixture(t);
  const result = await f.runtime.acceptance({providers:['claude']});
  assert.equal(result.requestedPassed,true);
  assert.equal(f.agents.length,1);
  assert.doesNotThrow(()=>f.runtime.requireOwnedAgent(f.agents[0]));
  assert.equal(f.agents[0].labels['woow-code-server-acceptance'],f.readState().installationId);
  assert.throws(()=>f.runtime.requireOwnedAgent({...f.agents[0],labels:{'woow-code-server-acceptance':'other-installation'}}),{code:'AGENT_NOT_OWNED'});
});

test('restore cannot report success for a running but unreachable daemon', async t => {
  const f = await fixture(t,{reachable:false});
  await assert.rejects(f.runtime.restore(),{code:'DAEMON_UNREACHABLE'});
  assert.equal(f.events.includes('stop'),false);
  assert.equal(f.events.includes('spawn'),false);
});

test('restore retries live configuration for an unreachable daemon and verifies recovery', async t => {
  const f = await fixture(t,{reachable:false,recoverOnReload:true});
  const result = await f.runtime.restore();
  assert.equal(result.restored,true);
  assert.equal(result.daemon.reachable,true);
  assert.equal(f.events.includes('reload'),true);
  assert.equal(f.events.includes('stop'),false);
  assert.equal(f.events.includes('spawn'),false);
});

test('restore cannot claim an unreachable restart-required daemon was restored', async t => {
  const f = await fixture(t,{reachable:false,state:{configurationPending:true}});
  await assert.rejects(f.runtime.restore(),{code:'DAEMON_UNREACHABLE'});
  assert.equal(f.readState().configurationPending,true);
  assert.equal(f.readState().phase,'restart_required');
  assert.equal(f.events.includes('reload'),false);
  assert.equal(f.events.includes('stop'),false);
  assert.equal(f.events.includes('spawn'),false);
});

test('healthy restore remains read-only and keeps verification receipts', async t => {
  const f = await fixture(t,{state:{acceptance:{passed:true,providers:[]},modelSwitches:[{confirmed:true}]}});
  const file = path.join(f.loc.stateDir,'state.json'), before = fs.readFileSync(file);
  const result = await f.runtime.restore();
  assert.equal(result.restored,true);
  assert.equal(result.chatVerified,true);
  assert.deepEqual(fs.readFileSync(file),before);
  assert.deepEqual(f.events,['status']);
});

function verifiedState() {
  return {acceptance:{passed:true,providers:['claude','codex','pi'].map(provider=>({provider,passed:true,cleanup:{archived:true}}))},
    modelSwitches:[{confirmed:true,replyVerified:true,model:'old-model'}]};
}

test('confirmed stop invalidates chat and model-switch verification receipts', async t => {
  const f = await fixture(t,{state:verifiedState()});
  const result = await f.runtime.deactivate();
  assert.equal(result.enabled,false);
  assert.equal(result.daemon.running,false);
  assert.equal(result.chatVerified,false);
  assert.equal(result.state.acceptance,null);
  assert.deepEqual(result.state.modelSwitches,[]);
  const diagnosed = await f.runtime.diagnose();
  assert.equal(diagnosed.providers.some(row=>row.authentication === 'chat_verified'),false);
});

test('stop with an already absent daemon also invalidates verification receipts', async t => {
  const f = await fixture(t,{running:false,state:verifiedState()});
  const result = await f.runtime.deactivate();
  assert.equal(result.chatVerified,false);
  assert.deepEqual(result.state.modelSwitches,[]);
});

test('a new R2 daemon cannot inherit model verification from the previous runtime', async t => {
  const f = await fixture(t,{running:false,state:{...verifiedState(),daemonRuntimeRevision:'0.11.2-r2-old'}});
  const result = await f.runtime.activate();
  assert.equal(result.daemon.reachable,true);
  assert.equal(result.state.daemonRuntimeRevision,layout.RUNTIME_REVISION);
  assert.equal(result.chatVerified,false);
  assert.equal(result.state.acceptance,null);
  assert.deepEqual(result.state.modelSwitches,[]);
});

test('an uncertain new start clears old verification before the daemon launch', async t => {
  const f = await fixture(t,{running:false,state:verifiedState(),startError:'COMMAND_TIMEOUT'});
  await assert.rejects(f.runtime.activate(),{code:'COMMAND_TIMEOUT'});
  const result = await f.runtime.status();
  assert.equal(result.daemon.running,true);
  assert.equal(result.chatVerified,false);
  assert.equal(result.state.acceptance,null);
  assert.deepEqual(result.state.modelSwitches,[]);
});

for (const version of ['21.9.0','22.0.0','22.18.9','22.19.0','22.23.3','23.0.0']) {
  test(`activation enforces the Node 22.19 minimum for ${version}`, async t => {
    const f = await fixture(t,{running:false});
    t.mock.property(process.versions,'node',version);
    if (['21.9.0','22.0.0','22.18.9'].includes(version)) {
      await assert.rejects(f.runtime.activate(),{code:'NODE_VERSION_UNSUPPORTED'});
      assert.equal(f.events.includes('version'),false);
      assert.equal(f.events.includes('spawn'),false);
    } else {
      const result = await f.runtime.activate();
      assert.equal(result.daemon.reachable,true);
      assert.equal(f.events.includes('spawn'),true);
    }
  });
}

test('activation fails closed when a same-UID supervisor cannot be inspected', async t => {
  const f = await fixture(t,{running:false,supervisors:[424242],procError:'EACCES'});
  await assert.rejects(f.runtime.activate(),{code:'DAEMON_IDENTITY_UNVERIFIABLE'});
  assert.equal(f.events.includes('write-config'),false);
  assert.equal(f.events.includes('spawn'),false);
});

test('a supervisor belonging to another home does not prevent this home from starting', async t => {
  const f = await fixture(t,{running:false,supervisors:[424242],supervisorHome:'/other-home'});
  const result = await f.runtime.activate();
  assert.equal(result.daemon.reachable,true);
  assert.equal(f.events.includes('spawn'),true);
});

test('legacy acceptance rows without cleanup proof cannot make the full result pass', async t => {
  const f = await fixture(t,{state:{acceptance:{providers:[{provider:'codex',passed:true},{provider:'pi',passed:true}]}}});
  const result = await f.runtime.acceptance({providers:['claude']});
  assert.equal(result.requestedPassed,true);
  assert.equal(result.passed,false);
});

test('a failed stop preserves live verification and reports its failure', async t => {
  const f = await fixture(t,{state:verifiedState(),stopError:'STOP_NOT_CONFIRMED'});
  await assert.rejects(f.runtime.deactivate(),{code:'STOP_NOT_CONFIRMED'});
  const result = await f.runtime.status();
  assert.equal(result.enabled,false);
  assert.equal(result.daemon.running,true);
  assert.equal(result.chatVerified,true);
  assert.equal(result.state.modelSwitches.length,1);
});

test('a successful no-op reload confirms a previous uncertain provider reload', async t => {
  const f = await fixture(t,{state:verifiedState(),desiredProviders:{claude:{enabled:true}},reloadError:'DAEMON_REQUEST_TIMEOUT'});
  await assert.rejects(f.runtime.activate(),{code:'RESTART_REQUIRED'});
  assert.deepEqual(f.readState().providerReloadPending,{pid:f.pid,startedAt:f.instance.startedAt});
  f.reloadError = null;
  const result = await f.runtime.activate();
  assert.equal(result.daemon.reachable,true);
  assert.equal(result.state.providerReloadPending,null);
  assert.equal(result.chatVerified,true);
  assert.equal(result.state.modelSwitches.length,1);
  assert.equal(f.events.filter(event=>event === 'reload').length,2);
  assert.equal(f.events.includes('spawn'),false);
  assert.equal(f.events.includes('stop'),false);
});

test('acceptance preserves the base rejection of empty and duplicate provider lists', async t => {
  const f = await fixture(t);
  const before = fs.readFileSync(path.join(f.loc.stateDir,'state.json'));
  for (const providers of [[],['claude','claude'],['claude','codex','pi','claude']]) {
    await assert.rejects(f.runtime.acceptance({providers}),{code:'INVALID_PROVIDER'});
  }
  assert.equal(f.agents.length,0);
  assert.deepEqual(fs.readFileSync(path.join(f.loc.stateDir,'state.json')),before);
});

test('owned homes keep the base missing-runtime status diagnostic without writes', async t => {
  const f = await fixture(t,{installed:false,running:false});
  const file = path.join(f.loc.stateDir,'state.json'), before = fs.readFileSync(file);
  const result = await f.runtime.status();
  assert.equal(result.installed,false);
  assert.equal(result.daemon.owned,true);
  assert.equal(result.diagnosticCode,'RUNTIME_MISSING');
  assert.deepEqual(fs.readFileSync(file),before);
  assert.deepEqual(f.events,[]);
});
