// Runs only inside the disposable container-smoke fixture, not a live HA host.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import http from 'node:http';
import {execFileSync} from 'node:child_process';
import {assertListeners,parseListeners,readProcessTcpListeners} from './listener-contract.mjs';
import {setTimeout as delay} from 'node:timers/promises';
const mode=process.argv[2];assert.ok(['prepare','restored','restored-enabled'].includes(mode));
const runtimeDir='/data/opendesign/paseo/packages/runtime';
const prefix='/api/hassio_ingress/'+'a'.repeat(32);
const socketPath='/run/ha-opendesign-paseo/bridge.sock';
const checkpoint='/data/opendesign/paseo-smoke.json';
const request=(body)=>new Promise((resolve,reject)=>{
 const req=http.request({socketPath,path:'/api/paseo-bridge',method:body?'POST':'GET',headers:{
  Host:'ha.fixture.test','X-OD-HA-Peer':'172.30.32.2','X-Remote-User-Id':'b'.repeat(32),'X-Ingress-Path':prefix,
  ...(body?{Origin:'https://ha.fixture.test',Referer:`https://ha.fixture.test${prefix}/paseo/setup/`,'Sec-Fetch-Site':'same-origin','Content-Type':'application/json'}:{}),
 }},res=>{let text='';res.on('data',b=>text+=b);res.on('end',()=>{try{resolve({status:res.statusCode,body:JSON.parse(text)});}catch{reject(Error('non-JSON bridge response'));}});});req.on('error',reject);req.setTimeout(15000,()=>req.destroy(Error('bridge timeout')));req.end(body?JSON.stringify(body):undefined);
});
async function until(predicate){
 for(let n=0;n<420;n++){
  try{const res=await request();if(res.status===200&&predicate(res.body))return res.body;}catch{}
  await delay(1000);
 }
 throw Error('Paseo lifecycle did not settle within 420 seconds');
}
const json=file=>JSON.parse(fs.readFileSync(file,'utf8'));
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const protectedFiles=[
 '/data/opendesign/home/.claude/ha-restore-fixture',
 '/data/opendesign/home/.codex/ha-restore-fixture',
 '/data/opendesign/home/.pi/agent/ha-restore-fixture',
 '/data/opendesign/shared/workspaces/ha-restore-fixture',
 '/data/opendesign/paseo/daemon/ha-restore-fixture',
];
function checkPreserved(expected,dto){
 assert.equal(dto.onboarding.projectId,expected.projectId);
 assert.equal(dto.onboarding.conversationId,expected.conversationId);
 assert.equal(json('/data/opendesign/paseo/state.json').installationId,expected.installationId);
 assert.equal(hash('/data/opendesign/paseo/daemon/.pi-paseo-owner.json'),expected.ownerHash);
 for(const [file,digest] of Object.entries(expected.files))assert.equal(hash(file),digest,file);
}
async function checkRebuilt(){
 const {runtimeReady,runtimeDirectory}=await import('/opt/opendesign-paseo/vendor/pi-paseo/src/runtime-layout.mjs');
 assert.equal(runtimeReady({runtimeDir}),true);
 const root=runtimeDirectory({runtimeDir});
 assert.equal(hash(path.join(root,'package-lock.json')),hash('/opt/opendesign-paseo/vendor/pi-paseo/runtime/package-lock.json'));
 assert.equal(json(path.join(root,'node_modules/@getpaseo/cli/package.json')).version,'0.11.2');
 assert.ok(fs.existsSync(path.join(root,'node_modules/@getpaseo/server/dist/server/web-ui/index.html')));
 await checkListeners(true);
}
const native=async(method,route,body)=>{
 const res=await fetch('http://127.0.0.1:7456'+route,{method,headers:{'Content-Type':'application/json','Sec-Fetch-Site':'same-origin'},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(15000)});
 return {status:res.status,body:await res.json()};
};
async function checkListeners(running) {
 const json=path=>JSON.parse(fs.readFileSync(path,'utf8'));
 let workerListeners;
 if(running){
  // Inspect private lifecycle status locally; worker PIDs never enter the public DTO.
  const {runtimeContext}=await import('/opt/opendesign-paseo/src/runtime-context.mjs');
  const {env}=runtimeContext({dataDir:'/data/opendesign',home:'/data/opendesign/home',env:{PATH:process.env.PATH}});
  const processInfo=JSON.parse(execFileSync(process.execPath,['--input-type=module','-e',`
   import {status} from '/opt/opendesign-paseo/vendor/pi-paseo/src/runtime.mjs';
   const {daemon}=await status();
   console.log(JSON.stringify({owned:daemon.owned,reachable:daemon.reachable,workerPid:daemon.workerPid}));
  `],{env,encoding:'utf8',timeout:20000}));
  assert.equal(processInfo.owned,true);assert.equal(processInfo.reachable,true);
  assert.ok(Number.isInteger(processInfo.workerPid)&&processInfo.workerPid>1);
  assert.equal(fs.statSync(`/proc/${processInfo.workerPid}`).uid,1001);
  workerListeners=readProcessTcpListeners(processInfo.workerPid);
 }
 const state=running?json('/data/opendesign/paseo/state.json'):undefined;
 assertListeners(parseListeners(execFileSync('netstat',['-ltn'],{encoding:'utf8'})), {
  running,workerListeners,state, ...(running?{config:json('/data/opendesign/paseo/daemon/config.json')}:{})
 });
 if(running){
  const auxiliary=workerListeners.find(address=>address!==`127.0.0.1:${state.port}`);
  for(const authorization of [undefined,'Bearer invalid-smoke-token']){
   const res=await fetch(`http://${auxiliary}/_internal/opencode/tools`,{
    headers:authorization?{authorization}:{},signal:AbortSignal.timeout(5000),redirect:'error'
   });
   assert.equal(res.status,401,'internal OpenCode bridge must require its private bearer token');
   assert.deepEqual(await res.json(),{error:'Unauthorized'});
  }
  console.log('Paseo listeners: recorded daemon + one kernel-owned OpenCode bridge; missing/invalid token rejected');
 }
}
if(mode==='prepare'){
 const dto=await until(s=>s.desiredEnabled&&s.daemon?.reachable&&s.onboarding?.initialized);
 assert.equal(dto.daemon.owned,true);await checkListeners(true);
 const socket=fs.statSync(socketPath);assert.equal(socket.uid,1001);assert.equal(socket.gid,1002);assert.equal(socket.mode&0o777,0o660);
 const listed=await native('GET','/api/mcp/servers');assert.equal(listed.status,200);
 const entry=listed.body.servers.find(row=>row.id==='woow-paseo');assert.ok(entry);assert.deepEqual(entry.args,['/opt/opendesign-paseo/bin/mcp.mjs']);
 // A stale expected value must not overwrite the bridge's MCP registration.
 assert.equal((await native('PUT','/api/mcp/servers/woow-paseo',{server:entry,expected:null})).status,409);
 assert.deepEqual((await native('GET','/api/mcp/servers')).body.servers,listed.body.servers);
 for(const file of protectedFiles)fs.writeFileSync(file,'ha-restore-not-a-secret',{mode:0o600,flag:'wx'});
 fs.writeFileSync(checkpoint,JSON.stringify({projectId:dto.onboarding.projectId,conversationId:dto.onboarding.conversationId,
  installationId:json('/data/opendesign/paseo/state.json').installationId,
  ownerHash:hash('/data/opendesign/paseo/daemon/.pi-paseo-owner.json'),
  files:Object.fromEntries(protectedFiles.map(file=>[file,hash(file)])),
 }),{mode:0o600});
 assert.equal((await request({action:'disable'})).status,202);
 await until(s=>s.desiredEnabled===false&&!s.daemon?.running&&s.operation?.status!=='running');
 await checkListeners(false);
 console.log('Paseo smoke: native onboarding/CAS, managed start/stop, socket ownership passed');
}else if(mode==='restored'){
 const expected=JSON.parse(fs.readFileSync(checkpoint));
 const dto=await until(s=>s.pluginInstalled&&s.desiredEnabled===false);
 assert.equal(dto.daemon?.running,false);checkPreserved(expected,dto);
 // A saved installedVersion must not substitute for the excluded files.
 assert.equal(json('/data/opendesign/paseo/state.json').installedVersion,'0.11.2');
 assert.equal(fs.existsSync(runtimeDir),false);
 const projects=await native('GET','/api/projects');assert.equal(projects.status,200);
 assert.equal(projects.body.projects.filter(p=>p.metadata?.woowPaseoInstallation).length,1);
 await checkListeners(false);
 assert.equal((await request({action:'enable'})).status,202);
 const enabled=await until(s=>s.desiredEnabled&&s.daemon?.reachable&&s.operation?.status!=='running');
 checkPreserved(expected,enabled);await checkRebuilt();
 console.log('Paseo smoke: excluded runtime stays absent while disabled; GUI enable rebuilds exact lock and preserves state');
}else{
 // No enable request: restored enabled intent must trigger package recovery.
 const dto=await until(s=>s.desiredEnabled&&s.daemon?.reachable&&s.onboarding?.initialized);
 checkPreserved(json(checkpoint),dto);await checkRebuilt();
 assert.equal((await native('GET','/api/projects')).body.projects.filter(p=>p.metadata?.woowPaseoInstallation).length,1);
 assert.equal((await request({action:'disable'})).status,202);
 await until(s=>!s.desiredEnabled&&!s.daemon?.running&&s.operation?.status!=='running');
 await checkListeners(false);
 console.log('Paseo smoke: enabled restore automatically rebuilds exact runtime; identities and protected files retained');
}
