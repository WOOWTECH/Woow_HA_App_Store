import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawn,spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {gunzipSync} from 'node:zlib';
import {setTimeout as delay} from 'node:timers/promises';
import {installRuntime,checkInstallerPrerequisites} from '../src/runtime-installer.mjs';
import {runtimeDirectory,runtimeReady,codeServerLegacyRuntimeDirectory,priorRuntimeDirectory,previousRuntimeDirectory,RUNTIME_REVISION,PASEO_VERSION} from '../src/runtime-layout.mjs';
import {validateSmartTasksSource,SMART_TASKS_DIRECTORY,SMART_TASKS_REGISTRY_PATH} from '../src/smart-tasks-patch.mjs';
import {BRAND_SERVER_PATH} from '../src/brand-identity-patch.mjs';
import {MCP_REFRESH_PATCH_ID,MCP_REFRESH_HELPER_PATH,mcpRefreshPatchReady,refreshRecipes} from '../src/mcp-refresh-patch.mjs';
import {CLAUDE_ROOT_PATH} from '../src/claude-root-patch.mjs';
import {copyMcpRefreshFixture} from './mcp-refresh-fixture.mjs';
import {serverIntegrity} from './fixtures/installer-0.17.5/seed.mjs';
import {seedNpmOutput,entrypointPackages,entrypointFiles} from './fixtures/installer-0.17.5/artifact.mjs';
import {seedR3Output} from './fixtures/installer-0.17.5/r3-control.mjs';
import {esbuildFiles} from '../src/esbuild-runtime.mjs';

const connector=fileURLToPath(new URL('../',import.meta.url));
const moduleUrl=new URL('../src/runtime-installer.mjs',import.meta.url).href;
const seedUrl=new URL('./fixtures/installer-0.17.5/artifact.mjs',import.meta.url).href;
const payload=validateSmartTasksSource();
const offline={checkPrerequisites:async()=>{},runNpm:seedNpmOutput};
function fixture(t) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'paseo-installer-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const base=path.join(root,'target','runtime'),loc={runtimeDir:base};
  return {root,base,loc,final:runtimeDirectory(loc)};
}
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
function snapshot(root) {
  const entries=[];
  const visit=(file,name)=>{
    const stat=fs.lstatSync(file,{bigint:true});
    entries.push({name,ino:String(stat.ino),mode:String(stat.mode),mtime:String(stat.mtimeNs),ctime:String(stat.ctimeNs),
      contents:stat.isFile()?sha(fs.readFileSync(file)):stat.isSymbolicLink()?fs.readlinkSync(file):null});
    if(stat.isDirectory())for(const child of fs.readdirSync(file).sort())visit(path.join(file,child),path.join(name,child));
  };
  visit(root,'.');return entries;
}
const stages=base=>fs.readdirSync(base).filter(name=>name.startsWith('.install-'));
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
async function waitFor(fn) {
  for(let attempt=0;attempt<500;attempt++) { if(fn())return;await delay(10); }
  assert.fail('timed out waiting for installer fixture');
}

test('installer fixtures retain official SDK inputs while R4 pins the patched esbuild dependency',()=>{
  const lock=fs.readFileSync(new URL('../runtime-manifest/package-lock.json',import.meta.url));
  assert.equal(RUNTIME_REVISION,'0.17.5-r4-2b20ef5fac0a');
  assert.equal(MCP_REFRESH_PATCH_ID,'9d00cdb1f37426bf732e9fa4c02dc491c04f845eb1efd4b63e649f91687c3571');
  assert.equal(PASEO_VERSION,'0.17.5');
  assert.equal(sha(lock).slice(0,12),'2b20ef5fac0a');
  assert.equal(JSON.parse(lock).packages['node_modules/esbuild'].version,'0.28.2');
  assert.equal(JSON.parse(fs.readFileSync(new URL('../runtime-manifest/package.json',import.meta.url))).overrides.esbuild,'0.28.2');
  assert.equal(JSON.parse(lock).packages['node_modules/@getpaseo/server'].integrity,serverIntegrity);
  for(const [pkg,{integrity}] of Object.entries(entrypointPackages))assert.equal(JSON.parse(lock).packages['node_modules/@getpaseo/'+pkg].integrity,integrity,pkg);
  assert.equal(fs.existsSync(path.join(connector,'runtime/package.json')),false);
  assert.equal(fs.existsSync(path.join(connector,'runtime/package-lock.json')),false);
});

test('the exact pre-root-fix R2 generation remains verifiable only for control',async t=>{
  const f=fixture(t);
  const revision='0.17.5-r2-8664f2c3f8f5';
  const previous=path.join(f.base,'releases',revision);
  seedR3Output(previous);
  const receiptFile=path.join(previous,'.pi-paseo-runtime.json');
  const receipt=JSON.parse(fs.readFileSync(receiptFile));receipt.revision=revision;delete receipt.claudeRootPatchId;
  fs.writeFileSync(receiptFile,JSON.stringify(receipt));
  fs.writeFileSync(path.join(previous,CLAUDE_ROOT_PATH),gunzipSync(fs.readFileSync(new URL('./fixtures/installer-0.17.5/claude-agent.js.gz',import.meta.url))));
  assert.equal(priorRuntimeDirectory(f.loc,revision),previous);
  assert.notEqual(runtimeDirectory(f.loc),previous);
  for(const relative of [CLAUDE_ROOT_PATH,refreshRecipes[0].path]){
    const file=path.join(previous,relative),before=fs.readFileSync(file);
    fs.appendFileSync(file,'tampered');assert.equal(priorRuntimeDirectory(f.loc,revision),null);
    fs.writeFileSync(file,before);assert.equal(priorRuntimeDirectory(f.loc,revision),previous);
  }
});

for(const {name} of payload)for(const failure of ['missing','tampered'])test(`${failure} pinned payload ${name} aborts before destination creation`,async t=>{
  const f=fixture(t);let npm=0,checked=0;
  await assert.rejects(installRuntime(f.base,{
    checkPrerequisites:async()=>{checked++;},runNpm:async()=>{npm++;},
    readSource:file=>{
      if(file===path.join(connector,'runtime/better-paseo',name)) {
        if(failure==='missing')throw Object.assign(new Error('missing'),{code:'ENOENT'});
        return Buffer.concat([fs.readFileSync(file),Buffer.from('tampered')]);
      }
      return fs.readFileSync(file);
    },
  }),{code:failure==='missing'?'SMART_TASKS_SOURCE_MISSING':name==='provenance.json'?'SMART_TASKS_PROVENANCE_MISMATCH':'SMART_TASKS_SOURCE_MISMATCH'});
  assert.equal(npm,0);assert.equal(checked,0);
  assert.equal(fs.existsSync(path.join(f.root,'target')),false);
});

for(const [label,settings,code] of [
  ['old Node',{nodeVersion:'22.18.0'},'NODE_VERSION_UNSUPPORTED'],
  ['missing npm',{discover:name=>name==='npm'?null:'/usr/bin/'+name},'NPM_REQUIRED'],
  ['missing flock',{discover:name=>name==='flock'?null:'/usr/bin/'+name},'FLOCK_REQUIRED'],
  ['missing procps',{discover:name=>name==='ps'?null:'/usr/bin/'+name},'PROCPS_REQUIRED'],
  ['incompatible procps',{run:async()=>'BusyBox ps'},'PROCPS_REQUIRED'],
  ['incompatible flock',{run:async command=>command.endsWith('/ps')?'procps-ng':'other flock'},'FLOCK_REQUIRED'],
])test(`${label} aborts before runtime path creation`,async t=>{
  const f=fixture(t);let npm=0;
  await assert.rejects(installRuntime(f.base,{
    checkPrerequisites:()=>checkInstallerPrerequisites({nodeVersion:'22.19.0',discover:name=>'/usr/bin/'+name,run:async command=>command.endsWith('/ps')?'procps-ng':'flock from util-linux',...settings}),
    runNpm:async()=>{npm++;},
  }),{code});
  assert.equal(npm,0);assert.equal(fs.existsSync(path.join(f.root,'target')),false);
});

test('actual artifact is patched and verified privately, then published by rename',async t=>{
  const f=fixture(t);let stagedRoot,stagedInode;
  const result=await installRuntime(f.base,{...offline,runNpm:async root=>{
    stagedRoot=root;stagedInode=fs.statSync(root).ino;
    assert.equal(fs.existsSync(f.final),false);
    const stage=path.dirname(path.dirname(root));
    assert.equal(path.dirname(stage),f.base);
    assert.equal(fs.statSync(stage).mode&0o777,0o700);
    assert.equal(fs.statSync(stage).dev,fs.statSync(f.base).dev);
    assert.equal(fs.existsSync(path.join(f.base,'.installer.lock.guard')),false);
    seedNpmOutput(root);
  }});
  assert.deepEqual(result,{runtimeDir:f.base,releaseDir:f.final,revision:RUNTIME_REVISION,reused:false});
  assert.equal(fs.statSync(f.final).ino,stagedInode);
  assert.equal(fs.existsSync(stagedRoot),false);
  assert.equal(runtimeReady(f.loc),true);
  assert.equal(stages(f.base).length,0);
  const receipt=JSON.parse(fs.readFileSync(path.join(f.final,'.pi-paseo-runtime.json')));
  assert.equal(receipt.revision,RUNTIME_REVISION);
  assert.equal(receipt.mcpRefreshPatchId,MCP_REFRESH_PATCH_ID);
  assert.equal(mcpRefreshPatchReady(f.final),true);
  for(const {path:relative,after} of refreshRecipes)assert.equal(sha(fs.readFileSync(path.join(f.final,relative))),after);
  for(const {name,bytes} of payload)assert.deepEqual(fs.readFileSync(path.join(f.final,SMART_TASKS_DIRECTORY,name)),bytes);
});

test('ready generation reuse invokes no npm and changes no contents, modes, inode or mtimes',async t=>{
  const f=fixture(t);await installRuntime(f.base,offline);
  const before=snapshot(f.base);let npm=0;
  const result=await installRuntime(f.base,{...offline,runNpm:async()=>{npm++;}});
  assert.equal(result.reused,true);assert.equal(npm,0);
  assert.deepEqual(snapshot(f.base),before);
});

test('compiler readiness accepts npm hardlinks without altering either binary',async t=>{
  const f=fixture(t);await installRuntime(f.base,offline);
  const generic=path.join(f.final,'node_modules/esbuild/bin/esbuild');
  const native=path.join(f.final,`node_modules/@esbuild/${process.platform}-${process.arch}/bin/esbuild`);
  assert.equal(fs.statSync(generic).ino,fs.statSync(native).ino);
  assert.equal(fs.statSync(generic).nlink,2);
  assert.equal(runtimeReady(f.loc),true);
  assert.equal((await installRuntime(f.base,offline)).reused,true);
});

for(const relative of Object.keys(esbuildFiles()))for(const failure of ['missing','empty','tampered','symlink'])for(const phase of ['before publication','on reuse'])test(`${failure} compiler ${relative} rejects ${phase}`,async t=>{
  const f=fixture(t);
  const damage=root=>{
    const file=path.join(root,relative);
    if(failure==='missing')fs.unlinkSync(file);
    else if(failure==='empty')fs.writeFileSync(file,'');
    else if(failure==='tampered')fs.appendFileSync(file,'tampered');
    else {
      const target=path.join(f.root,'authentic-compiler');fs.copyFileSync(file,target);
      fs.unlinkSync(file);fs.symlinkSync(target,file);
    }
  };
  if(phase==='before publication') {
    await assert.rejects(installRuntime(f.base,{...offline,runNpm:root=>{seedNpmOutput(root);damage(root);}}),{code:'AGENT_CONNECT_RUNTIME_VALIDATION_FAILED'});
    assert.equal(fs.existsSync(f.final),false);assert.deepEqual(stages(f.base),[]);
  }else {
    await installRuntime(f.base,offline);damage(f.final);const before=snapshot(f.base);
    await assert.rejects(installRuntime(f.base,{...offline,runNpm:()=>assert.fail('npm on damaged compiler')}),{code:'RUNTIME_RELEASE_CONFLICT'});
    assert.deepEqual(snapshot(f.base),before);
  }
});

test('a non-executable compiler is not ready and is never repaired in place',async t=>{
  const f=fixture(t);await installRuntime(f.base,offline);
  fs.chmodSync(path.join(f.final,'node_modules/esbuild/bin/esbuild'),0o600);
  assert.equal(runtimeReady(f.loc),false);const before=snapshot(f.base);
  await assert.rejects(installRuntime(f.base,offline),{code:'RUNTIME_RELEASE_CONFLICT'});
  assert.deepEqual(snapshot(f.base),before);
});

for(const [name,damage] of [
  ['missing receipt ID',root=>{const file=path.join(root,'.pi-paseo-runtime.json'),value=JSON.parse(fs.readFileSync(file));delete value.mcpRefreshPatchId;fs.writeFileSync(file,JSON.stringify(value));}],
  ['wrong receipt ID',root=>{const file=path.join(root,'.pi-paseo-runtime.json'),value=JSON.parse(fs.readFileSync(file));value.mcpRefreshPatchId='other';fs.writeFileSync(file,JSON.stringify(value));}],
  ['missing helper',root=>fs.unlinkSync(path.join(root,MCP_REFRESH_HELPER_PATH))],
  ['empty helper',root=>fs.writeFileSync(path.join(root,MCP_REFRESH_HELPER_PATH),'')],
  ['changed manager',root=>fs.appendFileSync(path.join(root,refreshRecipes[0].path),'changed')],
  ['changed session handler',root=>fs.appendFileSync(path.join(root,refreshRecipes[1].path),'changed')],
])test(`MCP ${name} refuses reuse without modifying the final`,async t=>{
  const f=fixture(t);await installRuntime(f.base,offline);damage(f.final);
  assert.equal(runtimeReady(f.loc),false);const before=snapshot(f.base);
  await assert.rejects(installRuntime(f.base,{...offline,runNpm:()=>assert.fail('npm on invalid MCP final')}),{code:'RUNTIME_RELEASE_CONFLICT'});
  assert.deepEqual(snapshot(f.base),before);
});

for(const recipe of refreshRecipes.slice(0,2))for(const failure of ['missing','empty','tampered'])test(`MCP ${failure} ${path.basename(recipe.path)} aborts before publication`,async t=>{
  const f=fixture(t);
  await assert.rejects(installRuntime(f.base,{...offline,runNpm:root=>{
    seedNpmOutput(root);const file=path.join(root,recipe.path);
    if(failure==='missing')fs.unlinkSync(file);else if(failure==='empty')fs.writeFileSync(file,'');else fs.appendFileSync(file,'changed');
  }}),{code:'MCP_REFRESH_SOURCE_MISMATCH'});
  assert.equal(fs.existsSync(f.final),false);assert.deepEqual(stages(f.base),[]);
});

for(const {name,relative} of entrypointFiles)for(const failure of ['missing','empty','tampered'])for(const phase of ['before publication','on reuse'])test(`${failure} essential ${name} rejects ${phase}`,async t=>{
  const f=fixture(t);
  const damage=root=>{
    const file=path.join(root,relative);
    if(failure==='missing')fs.unlinkSync(file);
    else if(failure==='empty')fs.writeFileSync(file,'');
    else fs.appendFileSync(file,'tampered');
  };
  if(phase==='before publication') {
    const code=refreshRecipes.some(recipe=>recipe.path===relative)?'MCP_REFRESH_SOURCE_MISMATCH':'AGENT_CONNECT_RUNTIME_VALIDATION_FAILED';
    await assert.rejects(installRuntime(f.base,{...offline,runNpm:root=>{seedNpmOutput(root);damage(root);}}),{code});
    assert.equal(fs.existsSync(f.final),false);assert.deepEqual(stages(f.base),[]);
  } else {
    await installRuntime(f.base,offline);damage(f.final);
    assert.equal(runtimeReady(f.loc),false);
    const before=snapshot(f.base);let npm=0;
    await assert.rejects(installRuntime(f.base,{...offline,runNpm:()=>{npm++;}}),{code:'RUNTIME_RELEASE_CONFLICT'});
    assert.equal(npm,0);assert.deepEqual(snapshot(f.base),before);
  }
});

for(const kind of ['directory','symlink'])for(const phase of ['before publication','on reuse'])test(`${kind} CLI entrypoint rejects ${phase} even with authentic target bytes`,async t=>{
  const f=fixture(t);
  const damage=root=>{
    const file=path.join(root,'node_modules/@getpaseo/cli/bin/paseo');
    if(kind==='directory'){fs.unlinkSync(file);fs.mkdirSync(file);}
    else {const target=path.join(f.root,'authentic-cli-bin');fs.copyFileSync(file,target);fs.unlinkSync(file);fs.symlinkSync(target,file);}
  };
  if(phase==='before publication') {
    await assert.rejects(installRuntime(f.base,{...offline,runNpm:root=>{seedNpmOutput(root);damage(root);}}),{code:'AGENT_CONNECT_RUNTIME_VALIDATION_FAILED'});
    assert.equal(fs.existsSync(f.final),false);assert.deepEqual(stages(f.base),[]);
  } else {
    await installRuntime(f.base,offline);damage(f.final);const before=snapshot(f.base);
    await assert.rejects(installRuntime(f.base,{...offline,runNpm:()=>assert.fail('npm on invalid final')}),{code:'RUNTIME_RELEASE_CONFLICT'});
    assert.deepEqual(snapshot(f.base),before);
  }
});

test('R4 installs alongside an exact control-only r1 without changing it',async t=>{
  const f=fixture(t),revision='0.17.5-r1-8664f2c3f8f5';
  const prior=path.join(f.base,'releases',revision);seedR3Output(prior);
  const receiptFile=path.join(prior,'.pi-paseo-runtime.json'),receipt=JSON.parse(fs.readFileSync(receiptFile));
  copyMcpRefreshFixture(prior,prior);fs.unlinkSync(path.join(prior,MCP_REFRESH_HELPER_PATH));
  receipt.revision=revision;delete receipt.mcpRefreshPatchId;delete receipt.claudeRootPatchId;fs.writeFileSync(receiptFile,JSON.stringify(receipt));
  const before=snapshot(prior);
  assert.equal(runtimeReady(f.loc),false);
  assert.equal(priorRuntimeDirectory(f.loc,revision),prior);
  assert.equal(previousRuntimeDirectory(f.loc),prior);
  await installRuntime(f.base,offline);
  assert.equal(runtimeReady(f.loc),true);assert.deepEqual(snapshot(prior),before);
  fs.appendFileSync(path.join(prior,BRAND_SERVER_PATH),'changed');
  assert.equal(priorRuntimeDirectory(f.loc,revision),null);
});

test('failed npm leaves final absent, removes only its own stage, and can retry',async t=>{
  const f=fixture(t);fs.mkdirSync(f.base,{recursive:true});
  const orphan=path.join(f.base,`.install-${RUNTIME_REVISION}-orphan`);
  fs.mkdirSync(orphan);fs.writeFileSync(path.join(orphan,'keep'),'interrupted');
  const before=snapshot(orphan);
  await assert.rejects(installRuntime(f.base,{...offline,runNpm:async root=>{
    seedNpmOutput(root);throw Object.assign(new Error('fixture npm failed'),{code:'NPM_INSTALL_FAILED'});
  }}),{code:'NPM_INSTALL_FAILED'});
  assert.equal(fs.existsSync(f.final),false);
  assert.deepEqual(stages(f.base),[path.basename(orphan)]);
  assert.equal((await installRuntime(f.base,offline)).reused,false);
  assert.equal(runtimeReady(f.loc),true);assert.deepEqual(snapshot(orphan),before);
});

test('abrupt installer exit leaves only an orphan and a fresh retry does not touch it',async t=>{
  const f=fixture(t);
  const script=`import {installRuntime} from ${JSON.stringify(moduleUrl)};import {seedNpmOutput} from ${JSON.stringify(seedUrl)};await installRuntime(process.argv[1],{checkPrerequisites:async()=>{},runNpm:async root=>{seedNpmOutput(root);process.exit(71);}});`;
  const child=spawnSync(process.execPath,['--input-type=module','-e',script,f.base],{encoding:'utf8',timeout:15000});
  assert.equal(child.status,71,child.stderr);assert.equal(fs.existsSync(f.final),false);
  assert.equal(stages(f.base).length,1);
  const orphan=path.join(f.base,stages(f.base)[0]),before=snapshot(orphan);
  await installRuntime(f.base,offline);
  assert.equal(runtimeReady(f.loc),true);assert.deepEqual(snapshot(orphan),before);
});

test('failure cleanup refuses a replacement at its own original stage pathname',async t=>{
  const f=fixture(t);let replacement,original,before;
  await assert.rejects(installRuntime(f.base,{...offline,runNpm:root=>{
    const stage=path.dirname(path.dirname(root));original=stage+'-moved';replacement=stage;
    fs.renameSync(stage,original);fs.mkdirSync(replacement);fs.writeFileSync(path.join(replacement,'keep'),'replacement owner');
    before=snapshot(replacement);throw Object.assign(new Error('fixture failure'),{code:'NPM_INSTALL_FAILED'});
  }}),{code:'NPM_INSTALL_FAILED'});
  assert.deepEqual(snapshot(replacement),before);assert.ok(fs.existsSync(original));
  assert.equal(fs.existsSync(f.final),false);
});

for(const kind of ['empty','partial','different receipt','file','dangling symlink'])test(`existing ${kind} final returns stable conflict without writes or npm`,async t=>{
  const f=fixture(t);fs.mkdirSync(path.dirname(f.final),{recursive:true});
  if(kind==='file')fs.writeFileSync(f.final,'keep');
  else if(kind==='dangling symlink')fs.symlinkSync(path.join(f.root,'missing'),f.final);
  else {
    fs.mkdirSync(f.final);
    if(kind==='partial')fs.writeFileSync(path.join(f.final,'package.json'),'{"name":"pi-paseo-managed-runtime"}');
    if(kind==='different receipt')fs.writeFileSync(path.join(f.final,'.pi-paseo-runtime.json'),'{"revision":"other"}');
  }
  const before=snapshot(f.base);let npm=0;
  await assert.rejects(installRuntime(f.base,{...offline,runNpm:async()=>{npm++;}}),{code:'RUNTIME_RELEASE_CONFLICT'});
  assert.equal(npm,0);assert.deepEqual(snapshot(f.base),before);
});

for(const [name,mutate,code] of [
  ['unknown PID writer',root=>fs.appendFileSync(path.join(root,'node_modules/@getpaseo/server/dist/server/server/pid-lock.js'),'changed'),'PID_LOCK_SOURCE_MISMATCH'],
  ['unknown server',root=>fs.appendFileSync(path.join(root,BRAND_SERVER_PATH),'changed'),'BRAND_IDENTITY_SOURCE_MISMATCH'],
  ['unknown registry',root=>fs.appendFileSync(path.join(root,SMART_TASKS_REGISTRY_PATH),'changed'),'SMART_TASKS_REGISTRY_MISMATCH'],
  ['wrong package version',root=>fs.writeFileSync(path.join(root,'node_modules/@getpaseo/server/package.json'),'{"version":"0.11.2"}'),'AGENT_CONNECT_RUNTIME_VALIDATION_FAILED'],
  ['missing SDK',root=>fs.unlinkSync(path.join(root,'node_modules/@getpaseo/client/package.json')),'AGENT_CONNECT_RUNTIME_VALIDATION_FAILED'],
  ['changed installed lock',root=>fs.appendFileSync(path.join(root,'package-lock.json'),' '),'AGENT_CONNECT_RUNTIME_VALIDATION_FAILED'],
])test(`${name} cannot produce a published receipt`,async t=>{
  const f=fixture(t);
  await assert.rejects(installRuntime(f.base,{...offline,runNpm:root=>{seedNpmOutput(root);mutate(root);}}),{code});
  assert.equal(fs.existsSync(f.final),false);assert.deepEqual(stages(f.base),[]);
});

test('a formerly ready final with a matching receipt and tampered payload is never repaired in place',async t=>{
  const f=fixture(t);await installRuntime(f.base,offline);
  fs.appendFileSync(path.join(f.final,SMART_TASKS_DIRECTORY,'assets/icon.png'),'changed');
  assert.equal(runtimeReady(f.loc),false);
  const before=snapshot(f.base);let npm=0;
  await assert.rejects(installRuntime(f.base,{...offline,runNpm:()=>{npm++;}}),{code:'RUNTIME_RELEASE_CONFLICT'});
  assert.equal(npm,0);assert.deepEqual(snapshot(f.base),before);
});

test('final appearing while npm runs is preserved and causes publication conflict',async t=>{
  const f=fixture(t);let before;
  await assert.rejects(installRuntime(f.base,{...offline,runNpm:root=>{
    seedNpmOutput(root);fs.mkdirSync(f.final,{recursive:true});
    fs.writeFileSync(path.join(f.final,'keep'),'other owner');before=snapshot(f.final);
  }}),{code:'RUNTIME_RELEASE_CONFLICT'});
  assert.deepEqual(snapshot(f.final),before);assert.deepEqual(stages(f.base),[]);
});

test('concurrent private builds publish once and the loser reuses the exact winner',async t=>{
  const f=fixture(t),both=deferred();let count=0;const roots=[];
  const runNpm=async root=>{
    seedNpmOutput(root);roots.push({root,ino:fs.statSync(root).ino});
    if(++count===2)both.resolve();await both.promise;
  };
  const results=await Promise.all([installRuntime(f.base,{...offline,runNpm}),installRuntime(f.base,{...offline,runNpm})]);
  assert.deepEqual(results.map(result=>result.reused).sort(),[false,true]);
  assert.equal(new Set(roots.map(entry=>entry.root)).size,2);
  assert.ok(roots.some(entry=>entry.ino===fs.statSync(f.final).ino));
  assert.equal(runtimeReady(f.loc),true);assert.deepEqual(stages(f.base),[]);
});

async function holdLock(t,base) {
  fs.mkdirSync(base,{recursive:true});
  const child=spawn('flock',['--exclusive',path.join(base,'.installer.lock.guard'),process.execPath,'-e',
    'process.stdout.write("locked\\n");process.stdin.resume();process.stdin.once("data",()=>process.exit(0));'],{stdio:['pipe','pipe','pipe']});
  const ended=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',resolve);});
  t.after(async()=>{child.stdin.end('release');await ended;});
  await new Promise((resolve,reject)=>{child.stdout.once('data',resolve);child.once('error',reject);child.once('exit',code=>reject(new Error('lock fixture exited '+code)));});
  return {release:async()=>{child.stdin.end('release');assert.equal(await ended,0);}};
}

for(const changed of ['receipt','payload','entrypoint','MCP patch'])test(`publication waits for an exclusive OS lock and revalidates the staged ${changed}`,async t=>{
  const f=fixture(t),held=await holdLock(t,f.base);let root;
  const operation=installRuntime(f.base,{...offline,runNpm:dir=>{root=dir;seedNpmOutput(dir);}});
  const outcome=assert.rejects(operation,{code:'AGENT_CONNECT_RUNTIME_VALIDATION_FAILED'});
  await waitFor(()=>root&&fs.existsSync(path.join(root,'.pi-paseo-runtime.json')));
  await delay(60);
  assert.equal(fs.existsSync(f.final),false);
  const stageLoc={runtimeDir:path.dirname(path.dirname(root))};
  assert.equal(runtimeReady(stageLoc),true);
  if(changed==='receipt') {
    const receipt=path.join(root,'.pi-paseo-runtime.json');
    const altered=JSON.parse(fs.readFileSync(receipt));altered.revision='other';fs.writeFileSync(receipt,JSON.stringify(altered));
  } else if(changed==='payload')fs.appendFileSync(path.join(root,SMART_TASKS_DIRECTORY,'index.client.ts'),'changed');
  else if(changed==='entrypoint')fs.writeFileSync(path.join(root,'node_modules/@getpaseo/cli/bin/paseo'),'');
  else fs.appendFileSync(path.join(root,refreshRecipes[0].path),'changed');
  await held.release();await outcome;
  assert.equal(fs.existsSync(f.final),false);assert.deepEqual(stages(f.base),[]);
});

test('installer lock contention is bounded and leaves the final absent',async t=>{
  const f=fixture(t),held=await holdLock(t,f.base);
  await assert.rejects(installRuntime(f.base,{...offline,lockTimeoutMs:50}),{code:'RUNTIME_INSTALL_LOCK_TIMEOUT'});
  assert.equal(fs.existsSync(f.final),false);assert.deepEqual(stages(f.base),[]);
  await held.release();
  await installRuntime(f.base,offline);assert.equal(runtimeReady(f.loc),true);
});

test('install and reuse preserve the exact legacy control fingerprint and SDK files',async t=>{
  const f=fixture(t);
  fs.mkdirSync(f.base,{recursive:true});
  const legacyFiles=['package.json','package-lock.json'];
  for(const name of legacyFiles)fs.writeFileSync(path.join(f.base,name),gunzipSync(fs.readFileSync(new URL('./fixtures/installer-0.17.5/legacy-'+name+'.gz',import.meta.url))));
  for(const pkg of ['cli','client','server','protocol']) {
    const name=`node_modules/@getpaseo/${pkg}/package.json`,file=path.join(f.base,name);
    fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,'{"version":"0.11.2","legacy":true}');legacyFiles.push(name);
  }
  const control='node_modules/@getpaseo/server/legacy-control.js';legacyFiles.push(control);
  fs.writeFileSync(path.join(f.base,control),'legacy control only');
  assert.equal(codeServerLegacyRuntimeDirectory(f.loc),f.base);
  const before=legacyFiles.map(name=>snapshot(path.join(f.base,name)));
  // Simulate extracting the new connector over its installed source location:
  // runtime/ is also the live legacy base, while runtime-manifest/ is separate.
  const target=path.dirname(f.base),npm=fakeNpm(f.root);
  for(const name of ['src','runtime-manifest','runtime/better-paseo','install-runtime.sh'])fs.cpSync(path.join(connector,name),path.join(target,name),{recursive:true});
  const run=()=>spawnSync('bash',[path.join(target,'install-runtime.sh'),target],{env:npm.env,encoding:'utf8',timeout:15000});
  const installed=run();assert.equal(installed.status,0,installed.stderr);
  assert.equal(JSON.parse(installed.stdout).reused,false);
  assert.equal(codeServerLegacyRuntimeDirectory(f.loc),f.base);
  const reused=run();assert.equal(reused.status,0,reused.stderr);assert.equal(JSON.parse(reused.stdout).reused,true);
  assert.equal(codeServerLegacyRuntimeDirectory(f.loc),f.base);
  assert.deepEqual(legacyFiles.map(name=>snapshot(path.join(f.base,name))),before);
  // The static fingerprint still rejects changed legacy manifests.
  fs.appendFileSync(path.join(f.base,'package-lock.json'),' ');
  assert.equal(codeServerLegacyRuntimeDirectory(f.loc),null);
});

function fakeNpm(root) {
  const bin=path.join(root,'bin'),log=path.join(root,'npm-calls');fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin,'npm'),`#!/usr/bin/env node\nimport fs from 'node:fs';import {seedNpmOutput} from ${JSON.stringify(seedUrl)};const args=process.argv.slice(2);fs.appendFileSync(${JSON.stringify(log)},JSON.stringify(args)+'\\n');if(args[0]!=='ci'||args[1]!=='--prefix')process.exit(31);seedNpmOutput(args[2]);\n`,{mode:0o700});
  return {env:{...process.env,PATH:bin+path.delimiter+process.env.PATH},log};
}

test('shell entrypoint runs production preflight, stages npm, emits JSON, and reuses without npm',t=>{
  const f=fixture(t),npm=fakeNpm(f.root);
  const run=()=>spawnSync('bash',[path.join(connector,'install-runtime.sh'),path.dirname(f.base)],{env:npm.env,encoding:'utf8',timeout:15000});
  const first=run();assert.equal(first.status,0,first.stderr);
  assert.equal(JSON.parse(first.stdout).reused,false);assert.equal(runtimeReady(f.loc),true);
  const args=JSON.parse(fs.readFileSync(npm.log,'utf8').trim());
  assert.deepEqual([args[0],args[1],...args.slice(3)],['ci','--prefix','--omit=dev','--no-audit','--no-fund']);
  assert.ok(args[2].startsWith(f.base+path.sep+'.install-'));assert.notEqual(args[2],f.final);
  const before=snapshot(f.base),calls=fs.readFileSync(npm.log);
  const second=run();assert.equal(second.status,0,second.stderr);assert.equal(JSON.parse(second.stdout).reused,true);
  assert.deepEqual(fs.readFileSync(npm.log),calls);assert.deepEqual(snapshot(f.base),before);
});

for(const [failure,victim] of [['missing','index.client.ts'],['tampered','assets/icon.png'],['tampered','server/builtin.js']])test(`shell preflight refuses ${failure} shipped ${victim} before creating target`,t=>{
  const f=fixture(t),npm=fakeNpm(f.root),copy=path.join(f.root,'source');
  fs.mkdirSync(copy);
  for(const name of ['src','runtime-manifest','runtime/better-paseo','install-runtime.sh'])fs.cpSync(path.join(connector,name),path.join(copy,name),{recursive:true});
  const file=path.join(copy,'runtime/better-paseo',victim);
  if(failure==='missing')fs.unlinkSync(file);else fs.appendFileSync(file,'tampered');
  const child=spawnSync('bash',[path.join(copy,'install-runtime.sh'),path.dirname(f.base)],{env:npm.env,encoding:'utf8',timeout:15000});
  assert.equal(child.status,1);assert.match(child.stderr,new RegExp(failure==='missing'?'SMART_TASKS_SOURCE_MISSING':'SMART_TASKS_SOURCE_MISMATCH'));
  assert.equal(fs.existsSync(path.dirname(f.base)),false);assert.equal(fs.existsSync(npm.log),false);
});
