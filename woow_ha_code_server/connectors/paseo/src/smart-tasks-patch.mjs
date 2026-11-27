import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {assertSafePath,RuntimeError} from './state.mjs';

// Official npm server 0.17.5 plus the reviewed product builtin, not a whole forked daemon.
// The provenance pins every shipped byte, the Smart integration commit, and upstream 1.7.0.
export const SMART_TASKS_REGISTRY_PATH='node_modules/@getpaseo/server/dist/server/server/plugins/builtin/index.js';
export const SMART_TASKS_DIRECTORY='node_modules/@getpaseo/server/dist/server/builtin-plugins/better-paseo';
export const ORIGINAL_TASKS_REGISTRY_SHA256='f9b556bd333ab30950fb438e7da9b5f57da04e1234ad4d951c5931e19eee0092';
export const PATCHED_TASKS_REGISTRY_SHA256='f20ea6c51acf595a72148998547ab6edc8623275f3a36f86eb2dc51415f2098e';
export const SMART_TASKS_PROVENANCE_SHA256='08a0cbe942bd3136d983e63f8c723f2b17e21f433d410bddb6faf4b5a1c802c8';
const source=fileURLToPath(new URL('../runtime/better-paseo/',import.meta.url));
const sha=b=>createHash('sha256').update(b).digest('hex');
export const SMART_TASKS_PATCH_ID=sha(SMART_TASKS_PROVENANCE_SHA256+PATCHED_TASKS_REGISTRY_SHA256);

function regularBytes(file) {
  const stat=assertSafePath(file);
  if(!stat?.isFile())throw new RuntimeError('SMART_TASKS_FILE_INVALID');
  return fs.readFileSync(file);
}
export function validateSmartTasksSource(read=regularBytes) {
  const load=name=>{try{return read(path.join(source,name));}catch{throw new RuntimeError('SMART_TASKS_SOURCE_MISSING');}};
  const bytes=load('provenance.json');
  if(sha(bytes)!==SMART_TASKS_PROVENANCE_SHA256)throw new RuntimeError('SMART_TASKS_PROVENANCE_MISMATCH');
  const files=JSON.parse(bytes).files;
  const validated=[];
  for(const [name,hash] of Object.entries({...files,'provenance.json':SMART_TASKS_PROVENANCE_SHA256})){
    const contents=load(name);
    if(sha(contents)!==hash)throw new RuntimeError('SMART_TASKS_SOURCE_MISMATCH');
    validated.push({name,hash,bytes:contents});
  }
  return validated;
}
export function patchSmartTasksRegistry(bytes) {
  const hash=sha(bytes);
  if(hash===PATCHED_TASKS_REGISTRY_SHA256)return bytes;
  if(hash!==ORIGINAL_TASKS_REGISTRY_SHA256)throw new RuntimeError('SMART_TASKS_REGISTRY_MISMATCH');
  const result=Buffer.from(bytes.toString().replace('    "antigravity-provider",','    "antigravity-provider",\n    "better-paseo",'));
  if(sha(result)!==PATCHED_TASKS_REGISTRY_SHA256)throw new RuntimeError('SMART_TASKS_PATCH_MISMATCH');
  return result;
}
export function applySmartTasksPatch(root) {
  const registry=path.join(root,SMART_TASKS_REGISTRY_PATH);
  const before=regularBytes(registry),after=patchSmartTasksRegistry(before);
  // Validate every immutable source byte before any destination is created or
  // patched. A truncated package must fail without touching a serving release.
  const files=validateSmartTasksSource().map(({name,bytes})=>{
    const target=path.join(root,SMART_TASKS_DIRECTORY,name);
    assertSafePath(target);
    return {target,bytes};
  });
  // Validate the entire payload and all destinations before writing. Only a prepared,
  // inactive managed release calls this; existing daemon data and config are never touched.
  for(const {target,bytes} of files){
    fs.mkdirSync(path.dirname(target),{recursive:true});
    assertSafePath(target);
    if(!fs.existsSync(target)||!regularBytes(target).equals(bytes))fs.writeFileSync(target,bytes,{mode:0o644});
  }
  if(!before.equals(after))fs.writeFileSync(registry,after);
}
export function smartTasksPatchReady(root,release={registrySha256:PATCHED_TASKS_REGISTRY_SHA256,provenanceSha256:SMART_TASKS_PROVENANCE_SHA256}) {
  try{
    if(sha(regularBytes(path.join(root,SMART_TASKS_REGISTRY_PATH)))!==release.registrySha256)return false;
    const directory=path.join(root,SMART_TASKS_DIRECTORY);
    const provenance=regularBytes(path.join(directory,'provenance.json'));
    // A frozen, known provenance hash is the trust root, never the release's unchecked file list.
    if(sha(provenance)!==release.provenanceSha256)return false;
    return Object.entries(JSON.parse(provenance).files).every(([name,hash])=>sha(regularBytes(path.join(directory,name)))===hash);
  }catch{return false;}
}
