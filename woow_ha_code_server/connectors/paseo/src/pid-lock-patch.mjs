import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {assertSafePath,RuntimeError} from './state.mjs';
export const ORIGINAL_PID_LOCK_SHA256='1a4bd330996ed25047b2dbc3b77b6407a49365ef5b2db9fbffdf4d988d237483';
export const PATCHED_PID_LOCK_SHA256='a12564718dde7ac54f530ef3fedafdb762d8ee3055961b8e9919d58f34536264';
const helper=fs.readFileSync(new URL('./pid-transition.mjs',import.meta.url));
const sha=b=>createHash('sha256').update(b).digest('hex');
export const PID_LOCK_PATCH_ID=sha(Buffer.concat([helper,Buffer.from(PATCHED_PID_LOCK_SHA256)]));
export const PID_LOCK_COPIES=['dist/server/server','dist/src/server'];
export function patchPidLockSource(source) {
 if(sha(source)===PATCHED_PID_LOCK_SHA256)return source;
 if(sha(source)!==ORIGINAL_PID_LOCK_SHA256)throw new RuntimeError('PID_LOCK_SOURCE_MISMATCH');
 let output='import {withPidTransition,PID_TRANSITION_PROTOCOL} from "./pi-paseo-pid-transition.mjs";\n'+source;
 output=output.replace('    bootId: z.string().optional(),','    bootId: z.string().optional(),\n    piPaseoProtocol: z.literal("linux-flock-v1").optional(),');
 output=output.replace('        heartbeat: true,','        heartbeat: true,\n        piPaseoProtocol: PID_TRANSITION_PROTOCOL,');
 const signatures={acquirePidLock:'paseoHome, listen, options',refreshPidLock:'paseoHome, options',updatePidLock:'paseoHome, patch, options',releasePidLock:'paseoHome, options'};
 for(const [name,args] of Object.entries(signatures)) {
  output=output.replace('export async function '+name+'(', 'async function '+name+'Unguarded(');
  output+=`\nexport async function ${name}(${args}) {\n    return withPidTransition(paseoHome, () => ${name}Unguarded(${args}), ${name==='acquirePidLock'?'{create: true}':'{}'});\n}\n`;
 }
 if(sha(output)!==PATCHED_PID_LOCK_SHA256)throw new RuntimeError('PID_LOCK_PATCH_MISMATCH');
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
export function pidLockPatchReady(root) {
 try{return PID_LOCK_COPIES.every(relative=>{
  const dir=path.join(root,'node_modules/@getpaseo/server',relative);
  const file=path.join(dir,'pid-lock.js'),guard=path.join(dir,'pi-paseo-pid-transition.mjs');assertSafePath(file);assertSafePath(guard);
  return sha(fs.readFileSync(file))===PATCHED_PID_LOCK_SHA256&&sha(fs.readFileSync(guard))===sha(helper);
 });}catch{return false;}
}
