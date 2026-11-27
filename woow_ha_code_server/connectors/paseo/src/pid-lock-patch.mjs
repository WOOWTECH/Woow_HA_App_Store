import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {assertSafePath,RuntimeError} from './state.mjs';
// Frozen @getpaseo/server 0.17.5 writer; both official copies are unchanged from 0.17.4.
export const ORIGINAL_PID_LOCK_SHA256='a4e8bc790b27c944847b7bb84694b38d0366d08d7d565409edbc63dd6462b8f7';
export const PATCHED_PID_LOCK_SHA256='194013b387417fb9b6d74b7a305173d8f28478ef268b7a4c073b9882af66bd1b';
const helper=fs.readFileSync(new URL('./pid-transition.mjs',import.meta.url));
const sha=b=>createHash('sha256').update(b).digest('hex');
export const PID_LOCK_PATCH_ID=sha(Buffer.concat([helper,Buffer.from(PATCHED_PID_LOCK_SHA256)]));
const CURRENT=Object.freeze({original:ORIGINAL_PID_LOCK_SHA256,patched:PATCHED_PID_LOCK_SHA256,helperSha256:sha(helper)});
// Frozen @getpaseo/server 0.11.2 writer as Agent Connect 0.1.4-0.1.23 left it in runtime
// generations r2 (original) and r3/r4 (patched by this same transformation, receipt patch ID
// and helper bytes below). Literal values: they only verify those releases for control of a
// daemon they already run, and must not follow later edits to the writer or its helper.
export const PID_LOCK_0112=Object.freeze({
 original:'1a4bd330996ed25047b2dbc3b77b6407a49365ef5b2db9fbffdf4d988d237483',
 patched:'a12564718dde7ac54f530ef3fedafdb762d8ee3055961b8e9919d58f34536264',
 patchId:'9cb53ae98869412f55f4f5987cf1244d46641a3d492a70219893891c671578c0',
 helperSha256:'37bdef75ee090452ce946bbf051d411352d51fda95d8121ff0c83a34680e3987',
});
export const PID_LOCK_COPIES=['dist/server/server','dist/src/server'];
export function patchPidLockSource(source,release=CURRENT) {
 if(sha(source)===release.patched)return source;
 if(sha(source)!==release.original)throw new RuntimeError('PID_LOCK_SOURCE_MISMATCH');
 let output='import {withPidTransition,PID_TRANSITION_PROTOCOL} from "./pi-paseo-pid-transition.mjs";\n'+source;
 output=output.replace('    bootId: z.string().optional(),','    bootId: z.string().optional(),\n    piPaseoProtocol: z.literal("linux-flock-v1").optional(),');
 output=output.replace('        heartbeat: true,','        heartbeat: true,\n        piPaseoProtocol: PID_TRANSITION_PROTOCOL,');
 const signatures={acquirePidLock:'paseoHome, listen, options',refreshPidLock:'paseoHome, options',updatePidLock:'paseoHome, patch, options',releasePidLock:'paseoHome, options'};
 for(const [name,args] of Object.entries(signatures)) {
  output=output.replace('export async function '+name+'(', 'async function '+name+'Unguarded(');
  output+=`\nexport async function ${name}(${args}) {\n    return withPidTransition(paseoHome, () => ${name}Unguarded(${args}), ${name==='acquirePidLock'?'{create: true}':'{}'});\n}\n`;
 }
 if(sha(output)!==release.patched)throw new RuntimeError('PID_LOCK_PATCH_MISMATCH');
 return output;
}
export function applyPidLockPatch(root) {
 const server=path.join(root,'node_modules/@getpaseo/server');
 // Validate every input before mutating either copy. Installation is serialized
 // by the plugin runtime lock; this revision is never patched while running.
 const staged=PID_LOCK_COPIES.map(relative=>{
  const file=path.join(server,relative,'pid-lock.js');assertSafePath(file);
  return{file,source:patchPidLockSource(fs.readFileSync(file,'utf8'))};
 });
 for(const {file,source} of staged){
  const target=path.join(path.dirname(file),'pi-paseo-pid-transition.mjs');assertSafePath(target);
  if(!fs.existsSync(target)||!fs.readFileSync(target).equals(helper))fs.writeFileSync(target,helper,{mode:0o644});
  if(fs.readFileSync(file,'utf8')!==source)fs.writeFileSync(file,source);
 }
}
/** Both official copies carry the given release's patched writer beside its guard helper. */
export function pidLockPatchReady(root,release=CURRENT) {
 try{return PID_LOCK_COPIES.every(relative=>{
  const dir=path.join(root,'node_modules/@getpaseo/server',relative);
  const file=path.join(dir,'pid-lock.js'),guard=path.join(dir,'pi-paseo-pid-transition.mjs');assertSafePath(file);assertSafePath(guard);
  return sha(fs.readFileSync(file))===release.patched&&sha(fs.readFileSync(guard))===release.helperSha256;
 });}catch{return false;}
}
