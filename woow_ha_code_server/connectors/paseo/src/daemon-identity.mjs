// Recovery authority comes from a previously verified process incarnation, never
// from a PID/name/hostname alone. This module never sends a process signal.
import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {assertSafePath,atomicJson,processIdentity,readState,RuntimeError} from './state.mjs';
import {withPidTransition,PID_TRANSITION_PROTOCOL} from './pid-transition.mjs';
import {runtimeReady} from './runtime-layout.mjs';
const fail=code=>{throw new RuntimeError(code);};
const sameInode=(a,b)=>a?.dev===b?.dev&&a?.ino===b?.ino;
const sameBirth=(a,b)=>!!a&&!!b&&a.bootId===b.bootId&&a.startTicks===b.startTicks;
const proofPath=loc=>path.join(loc.stateDir,'daemon-instance.private.json');
const pidPath=loc=>path.join(loc.paseoHome,'paseo.pid');
const sameLock=(a,b)=>a?.pid===b?.pid&&a?.startedAt===b?.startedAt&&a?.bootId===b?.bootId&&a?.uid===b?.uid&&a?.piPaseoProtocol===b?.piPaseoProtocol;

function privateDir(dir) {
 const s=assertSafePath(dir);
 if(!s?.isDirectory()||s.uid!==process.getuid()||(s.mode&0o777)!==0o700)fail('DAEMON_IDENTITY_UNSAFE');
}
function safeJson(file,{proof=false}={}) {
 const before=assertSafePath(file);
 if(!before?.isFile()||before.uid!==process.getuid()||before.nlink!==1||(before.mode&(proof?0o077:0o022))||before.size>65536)fail('DAEMON_IDENTITY_UNSAFE');
 const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
 try {
  const opened=fs.fstatSync(fd);
  if(!sameInode(before,opened)||!opened.isFile()||opened.nlink!==1)fail('DAEMON_STATE_CHANGED');
  const buffer=Buffer.alloc(65537),length=fs.readSync(fd,buffer,0,buffer.length,0);
  if(length>65536)fail('DAEMON_IDENTITY_UNSAFE');
  const text=buffer.subarray(0,length).toString('utf8');
  const after=fs.fstatSync(fd),current=assertSafePath(file);
  if(!sameInode(opened,current)||opened.size!==after.size||opened.mtimeMs!==after.mtimeMs||opened.ctimeMs!==after.ctimeMs)fail('DAEMON_STATE_CHANGED');
  let value;try{value=JSON.parse(text);}catch{fail('DAEMON_IDENTITY_UNSAFE');}
  return{file,stat:after,text,value};
 }finally{fs.closeSync(fd);}
}
function ownedHome(loc) {
 privateDir(loc.stateDir);privateDir(loc.paseoHome);
 const marker=safeJson(path.join(loc.paseoHome,'.pi-paseo-owner.json'),{proof:true}).value;
 const installationId=readState().installationId;
 if(!installationId||marker.installationId!==installationId||marker.home!==loc.paseoHome)fail('DAEMON_NOT_OWNED');
 return installationId;
}
function requireRuntimeLock(loc) {
 const file=path.join(loc.stateDir,'runtime.lock');
 if(!assertSafePath(file))fail('DAEMON_RECOVERY_NOT_LOCKED');
 const lock=safeJson(file,{proof:true}).value;
 if(lock.pid!==process.pid||!lock.token||lock.identity!==processIdentity(process.pid))fail('DAEMON_RECOVERY_NOT_LOCKED');
}
function pidRecord(loc,instance) {
 const record=safeJson(pidPath(loc));const p=record.value;
 if(!Number.isInteger(p.pid)||p.pid<=1||typeof p.startedAt!=='string'||!p.startedAt||p.uid!==process.getuid()||p.heartbeat!==true||p.piPaseoProtocol!==PID_TRANSITION_PROTOCOL||!sameLock(p,instance))fail('DAEMON_NOT_OWNED');
 return record;
}
function unchanged(record) {
 const now=safeJson(record.file);
 if(!sameInode(now.stat,record.stat)||now.text!==record.text)fail('DAEMON_STATE_CHANGED');
 return now;
}
function birthShape(p) {
 return p&&typeof p.bootId==='string'&&/^[a-f0-9-]{36}$/i.test(p.bootId)&&typeof p.startTicks==='string'&&/^\d+$/.test(p.startTicks)&&Number.isInteger(p.uid);
}
export function readLinuxBirth(pid) {
 if(process.platform!=='linux'||!Number.isInteger(pid)||pid<1)fail('DAEMON_IDENTITY_UNVERIFIABLE');
 try {
  const dir=`/proc/${pid}`,stat=fs.readFileSync(dir+'/stat','utf8');
  const startTicks=stat.slice(stat.lastIndexOf(')')+2).split(' ')[19];
  const birth={bootId:fs.readFileSync('/proc/sys/kernel/random/boot_id','utf8').trim(),startTicks,uid:fs.statSync(dir).uid};
  if(!birthShape(birth))fail('DAEMON_IDENTITY_UNVERIFIABLE');
  return birth;
 }catch(error){
  if(error.code==='ENOENT'||error.code==='ESRCH'){
   try{process.kill(pid,0);}catch(e){if(e.code==='ESRCH')return null;}
  }
  fail('DAEMON_IDENTITY_UNVERIFIABLE');
 }
}
export function assertNoHomeSupervisor(loc) {
 // Include other runtime revisions and a supervisor that has not published its
 // PID file yet. Failure to inspect a same-UID candidate is not proof of absence.
 for(const name of fs.readdirSync('/proc')) {
  if(!/^\d+$/.test(name))continue;
  const pid=Number(name),dir='/proc/'+name;
  try {
   if(fs.statSync(dir).uid!==process.getuid())continue;
   const before=readLinuxBirth(pid);if(!before)continue;
   const args=fs.readFileSync(dir+'/cmdline','utf8').split('\0');
   if(args[0]!=='Paseo Supervisor'&&!args.some(a=>a.endsWith('/dist/scripts/supervisor-entrypoint.js')))continue;
   const env=fs.readFileSync(dir+'/environ','utf8').split('\0');
   const after=readLinuxBirth(pid);
   if(!sameBirth(before,after))fail('DAEMON_STATE_CHANGED');
   if(env.includes(`PASEO_HOME=${loc.paseoHome}`))fail('DAEMON_ALREADY_RUNNING');
  }catch(error){
   if(error.code==='ENOENT'||error.code==='ESRCH')continue;
   if(error instanceof RuntimeError)throw error;
   fail('DAEMON_IDENTITY_UNVERIFIABLE');
  }
 }
}

export function createDaemonIdentity({readBirth=readLinuxBirth,assertNoSupervisor=assertNoHomeSupervisor}={}) {
 function observe(loc,instance,verifyOwnership) {
  if(process.platform!=='linux')return;
  const installationId=ownedHome(loc);requireRuntimeLock(loc);
  if(!runtimeReady(loc))fail('DAEMON_TRANSITION_UNVERIFIED');
  const record=pidRecord(loc,instance),before=readBirth(instance.pid);
  if(!birthShape(before)||before.uid!==process.getuid())fail('DAEMON_IDENTITY_UNVERIFIABLE');
  verifyOwnership(instance); // synchronous final argv/executable/home check
  if(!sameBirth(before,readBirth(instance.pid)))fail('DAEMON_STATE_CHANGED');
  unchanged(record);
  return {schema:1,installationId,home:loc.paseoHome,lock:{pid:instance.pid,startedAt:instance.startedAt,bootId:instance.bootId,uid:instance.uid,piPaseoProtocol:instance.piPaseoProtocol},process:before,pidFile:{dev:record.stat.dev,ino:record.stat.ino}};
 }
 async function observeOwnedInstance(loc,instance,verifyOwnership) {
  if(process.platform!=='linux')return null;
  return withPidTransition(loc.paseoHome,()=>observe(loc,instance,verifyOwnership));
 }
 async function rememberOwnedInstance(loc,instance,verifyOwnership,expected) {
  if(process.platform!=='linux')return;
  return withPidTransition(loc.paseoHome,()=>{
  const receipt=observe(loc,instance,verifyOwnership);
  if(!expected||!sameBirth(receipt.process,expected.process)||!sameLock(receipt.lock,expected.lock)||!sameInode(receipt.pidFile,expected.pidFile))fail('DAEMON_STATE_CHANGED');
  // Never replace an untrusted existing proof path through atomicJson/chmod.
  if(assertSafePath(proofPath(loc)))safeJson(proofPath(loc),{proof:true});
  atomicJson(proofPath(loc),receipt);
  });
 }
 async function recoverStaleInstance(loc,instance) {
  if(process.platform!=='linux')fail('DAEMON_NOT_OWNED');
  return withPidTransition(loc.paseoHome,()=>{
  const installationId=ownedHome(loc);requireRuntimeLock(loc);
  if(!runtimeReady(loc))fail('DAEMON_TRANSITION_UNVERIFIED');
  let receipt;
  if(!assertSafePath(proofPath(loc)))fail('DAEMON_NOT_OWNED'); // legacy: no birth proof, no reclamation
  receipt=safeJson(proofPath(loc),{proof:true});
  const proof=receipt.value,record=pidRecord(loc,instance);
  if(proof.schema!==1||proof.installationId!==installationId||proof.home!==loc.paseoHome||!sameLock(proof.lock,record.value)||!sameInode(proof.pidFile,record.stat)||!birthShape(proof.process)||proof.process.uid!==process.getuid()||(proof.lock.bootId&&proof.lock.bootId!==proof.process.bootId))fail('DAEMON_NOT_OWNED');
  const current=readBirth(instance.pid);
  if(current&&!birthShape(current))fail('DAEMON_IDENTITY_UNVERIFIABLE');
  if(sameBirth(proof.process,current))fail('DAEMON_NOT_OWNED');
  assertNoSupervisor(loc);
  unchanged(record);unchanged(receipt);
  const confirmed=readBirth(instance.pid);
  if((current===null)!==(confirmed===null)||(current&&!sameBirth(current,confirmed)))fail('DAEMON_STATE_CHANGED');
  ownedHome(loc);requireRuntimeLock(loc);
  unchanged(record);
  const quarantine=path.join(loc.paseoHome,`.paseo.pid.stale-${randomUUID()}`);
  fs.renameSync(record.file,quarantine);
  const restore=()=>{
   // link is a no-clobber restore. Never overwrite a concurrently published PID
   // file, and keep quarantine evidence when restoration cannot be completed.
   try{fs.linkSync(quarantine,record.file);}catch{return;}
   fs.unlinkSync(quarantine); // only our unique quarantine link; data remains at original path
  };
  try {
   const moved=safeJson(quarantine);
   if(!sameInode(moved.stat,record.stat)||moved.text!==record.text)fail('DAEMON_STATE_CHANGED');
   if(assertSafePath(record.file))fail('DAEMON_STATE_CHANGED');
   assertNoSupervisor(loc);
   // A new writer/owner wins. Never start another daemon in that case.
   if(assertSafePath(record.file))fail('DAEMON_STATE_CHANGED');
  }catch(error){restore();throw error;}
  return{quarantine};
  });
 }
 return{observeOwnedInstance,rememberOwnedInstance,recoverStaleInstance};
}
export const {observeOwnedInstance,rememberOwnedInstance,recoverStaleInstance}=createDaemonIdentity();
