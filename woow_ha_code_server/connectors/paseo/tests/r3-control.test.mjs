import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {registerHooks} from 'node:module';
import {randomUUID} from 'node:crypto';
import {installRuntime} from '../src/runtime-installer.mjs';
import {priorRuntimeDirectory,previousRuntimeDirectory,runtimeDirectory,runtimeReady} from '../src/runtime-layout.mjs';
import {seedNpmOutput} from './fixtures/installer-0.17.5/artifact.mjs';

const record=JSON.parse(fs.readFileSync(new URL('../src/runtime-control-0175-r3.json',import.meta.url)));
const archive=JSON.parse(gunzipSync(fs.readFileSync(new URL('./fixtures/installer-0.17.5/r3-control.json.gz',import.meta.url))));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
function fixture(t) {
  const base=fs.mkdtempSync(path.join(os.tmpdir(),'paseo-r3-control-'));
  t.after(()=>fs.rmSync(base,{recursive:true,force:true}));
  const loc={runtimeDir:base},root=path.join(base,'releases',record.revision);
  for(const [relative,base64] of Object.entries(archive)) {
    const file=path.join(root,relative);fs.mkdirSync(path.dirname(file),{recursive:true});
    fs.writeFileSync(file,Buffer.from(base64,'base64'));
  }
  return {loc,root};
}
function snapshot(root) {
  return Object.keys(archive).sort().map(relative=>{
    const file=path.join(root,relative),stat=fs.statSync(file,{bigint:true});
    return {relative,ino:String(stat.ino),mtime:String(stat.mtimeNs),ctime:String(stat.ctimeNs),mode:String(stat.mode),sha256:sha(fs.readFileSync(file))};
  });
}

test('frozen R3 fixture contains its original manifests, 23 core files and all five patch receipts',()=>{
  assert.equal(record.sourceCommit,'e5622bb6b0ce7d25f1aad3f508dc4f3ad83c6a70');
  assert.equal(record.runtimeLayoutSha256,'ccd72368fd276785ef8fb0afa893b52ac122e612be3ecba54deb05259e893868');
  assert.equal(record.essentialFiles.length,23);
  assert.equal(record.files['package.json'],'8f151d594f37979d58032a88cb284a01be34b7fd7b64957ba604a3d532c71d86');
  assert.equal(record.files['package-lock.json'],'8664f2c3f8f58c15b8ec264fec9b69c3bc443192efd60365212e532c811f4ce2');
  assert.deepEqual(Object.keys(record.receipt).filter(key=>key.endsWith('PatchId')).sort(),
    ['brandIdentityPatchId','claudeRootPatchId','mcpRefreshPatchId','pidLockPatchId','smartTasksPatchId']);
  for(const relative of record.essentialFiles)assert.ok(record.files[relative],relative);
  for(const [relative,expected] of Object.entries(record.files))assert.equal(sha(Buffer.from(archive[relative],'base64')),expected,relative);
  assert.deepEqual(JSON.parse(Buffer.from(archive['.pi-paseo-runtime.json'],'base64')),record.receipt);
});

test('R4 installs beside frozen R3 without selecting or modifying it',async t=>{
  const {loc,root}=fixture(t),before=snapshot(root);
  assert.equal(priorRuntimeDirectory(loc,record.revision),root);
  assert.equal(previousRuntimeDirectory(loc),root);
  assert.notEqual(runtimeDirectory(loc),root);
  assert.equal(runtimeReady(loc),false);
  await installRuntime(loc.runtimeDir,{checkPrerequisites:async()=>{},runNpm:seedNpmOutput});
  assert.equal(runtimeReady(loc),true);
  assert.equal(priorRuntimeDirectory(loc,record.revision),root);
  assert.deepEqual(snapshot(root),before);
});

test('R3 control rejects missing, empty, changed or symlinked manifests and every pinned SDK file',t=>{
  const {loc,root}=fixture(t),outside=path.join(loc.runtimeDir,'authentic-file');
  assert.equal(priorRuntimeDirectory(loc,record.revision),root);
  for(const relative of Object.keys(record.files)) {
    const file=path.join(root,relative),bytes=fs.readFileSync(file);
    for(const kind of ['missing','empty','changed','symlink']) {
      fs.unlinkSync(file);
      if(kind==='empty')fs.writeFileSync(file,'');
      if(kind==='changed')fs.writeFileSync(file,Buffer.concat([bytes,Buffer.from('changed')]));
      if(kind==='symlink'){fs.writeFileSync(outside,bytes);fs.symlinkSync(outside,file);}
      assert.equal(priorRuntimeDirectory(loc,record.revision),null,`${kind}: ${relative}`);
      if(fs.existsSync(file))fs.unlinkSync(file);
      fs.writeFileSync(file,bytes);
      assert.equal(priorRuntimeDirectory(loc,record.revision),root,relative);
    }
  }
});

test('R3 control requires every exact receipt and rejects a receipt symlink or an unrecognized revision',t=>{
  const {loc,root}=fixture(t),file=path.join(root,'.pi-paseo-runtime.json'),bytes=fs.readFileSync(file);
  for(const key of Object.keys(record.receipt))for(const kind of ['missing','changed']) {
    const receipt={...record.receipt};if(kind==='missing')delete receipt[key];else receipt[key]='changed';
    fs.writeFileSync(file,JSON.stringify(receipt));
    assert.equal(priorRuntimeDirectory(loc,record.revision),null,`${key}: ${kind}`);
  }
  fs.writeFileSync(file,bytes);
  const outside=path.join(loc.runtimeDir,'authentic-receipt');fs.renameSync(file,outside);fs.symlinkSync(outside,file);
  assert.equal(priorRuntimeDirectory(loc,record.revision),null);
  fs.unlinkSync(file);fs.renameSync(outside,file);
  assert.equal(priorRuntimeDirectory(loc,record.revision),root);
  assert.equal(priorRuntimeDirectory(loc,'0.17.5-r3-000000000000'),null);
});

test('frozen R3 control stays valid when current SDK patch IDs and readiness recipes change',async t=>{
  const {loc,root}=fixture(t),url=new URL('../src/runtime-layout.mjs?frozen='+randomUUID(),import.meta.url).href;
  const key='__frozenR3_'+randomUUID(),modules=new Map();globalThis[key]=[];
  for(const name of ['pid-lock-patch','brand-identity-patch','smart-tasks-patch','mcp-refresh-patch','claude-root-patch']) {
    const current=await import(`../src/${name}.mjs`),changed={...current};
    for(const field of Object.keys(changed)) {
      if(field.endsWith('_PATCH_ID'))changed[field]='future-patch';
      if(field.endsWith('PatchReady'))changed[field]=()=>false;
    }
    const index=globalThis[key].push(changed)-1;
    const code=`const value=globalThis[${JSON.stringify(key)}][${index}];\n`+Object.keys(changed).map(field=>`export const ${field}=value.${field};`).join('\n');
    modules.set(`./${name}.mjs`,'data:text/javascript,'+encodeURIComponent(code));
  }
  const hooks=registerHooks({resolve(specifier,context,next){
    return context.parentURL===url&&modules.has(specifier)?{url:modules.get(specifier),shortCircuit:true}:next(specifier,context);
  }});
  try {
    const frozen=await import(url);
    assert.equal(frozen.priorRuntimeDirectory(loc,record.revision),root);
  }finally{hooks.deregister();delete globalThis[key];}
});
