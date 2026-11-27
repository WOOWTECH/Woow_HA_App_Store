import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
import {assertSafePath,RuntimeError,withLockTransition} from './state.mjs';
import {findExecutable,runProcess} from './process.mjs';
import {requireSystemTools} from './system-tools.mjs';
import {validateSmartTasksSource} from './smart-tasks-patch.mjs';
import {runtimeDirectory,runtimeReady,prepareRuntimeManifest,markRuntimeReady,RUNTIME_REVISION} from './runtime-layout.mjs';

export async function checkInstallerPrerequisites({nodeVersion=process.versions.node,env=process.env,discover=findExecutable,run=runProcess}={}) {
  const [major,minor]=nodeVersion.split('.').map(Number);
  if(!Number.isInteger(major)||!Number.isInteger(minor)||major<22||(major===22&&minor<19))throw new RuntimeError('NODE_VERSION_UNSUPPORTED');
  // Discovery only: a ready release must not invoke npm, even for --version.
  if(!discover('npm',env))throw new RuntimeError('NPM_REQUIRED');
  await requireSystemTools({env,discover,run});
  let version;
  try { version=await run(discover('flock',env),['--version'],{env,timeoutMs:5000,maxBytes:4096}); }
  catch { throw new RuntimeError('FLOCK_REQUIRED'); }
  if(!/util-linux/i.test(version))throw new RuntimeError('FLOCK_REQUIRED');
}

function runNpm(root) {
  return new Promise((resolve,reject)=>{
    const child=spawn('npm',['ci','--prefix',root,'--omit=dev','--no-audit','--no-fund'],{
      cwd:root,stdio:['ignore',2,2],shell:false,
    });
    child.once('error',()=>reject(new RuntimeError('NPM_UNAVAILABLE')));
    child.once('close',code=>code===0?resolve():reject(new RuntimeError('NPM_INSTALL_FAILED')));
  });
}

function exists(file) {
  try { fs.lstatSync(file);return true; }
  catch(error) { if(error.code==='ENOENT')return false;throw error; }
}
function ensureDirectory(dir) {
  const before=assertSafePath(dir);
  if(before&&!before.isDirectory())throw new RuntimeError('RUNTIME_PATH_INVALID');
  fs.mkdirSync(dir,{recursive:true,mode:0o700});
  assertSafePath(dir);
}
function result(loc,reused) {
  return {runtimeDir:loc.runtimeDir,releaseDir:runtimeDirectory(loc),revision:RUNTIME_REVISION,reused};
}
function reuseOrConflict(loc) {
  if(runtimeReady(loc))return result(loc,true);
  // Includes empty directories, unrecognized receipts, files and dangling links.
  if(exists(runtimeDirectory(loc)))throw new RuntimeError('RUNTIME_RELEASE_CONFLICT');
  return null;
}
async function withInstallerLock(base,fn,timeoutMs) {
  const deadline=Date.now()+timeoutMs;
  while(true) {
    // Persistent inode, OS-owned flock. A dead installer cannot strand the lock.
    const value=withLockTransition(path.join(base,'.installer.lock'),fn,{deadline});
    if(value!==null)return value;
    if(Date.now()>=deadline)throw new RuntimeError('RUNTIME_INSTALL_LOCK_TIMEOUT');
    await delay(25);
  }
}

/** Only check/runNpm/readSource are injectable; production CLI always uses the
 * real prerequisite, pinned-payload, patch and artifact verification functions.
 * The temporary runtime base lets the existing layout APIs build off to the side.
 * No daemon state/home/configuration paths participate in installation. */
export async function installRuntime(runtimeBase,{checkPrerequisites=checkInstallerPrerequisites,runNpm:install=runNpm,readSource,lockTimeoutMs=30000}={}) {
  if(typeof runtimeBase!=='string'||!path.isAbsolute(runtimeBase))throw new RuntimeError('RUNTIME_PATH_INVALID');
  const loc={runtimeDir:path.resolve(runtimeBase)};
  // Fail before mkdir, lock files, staging, or any npm invocation.
  validateSmartTasksSource(readSource);
  await checkPrerequisites();
  const ready=reuseOrConflict(loc);
  if(ready)return ready;

  ensureDirectory(loc.runtimeDir);
  const stage=fs.mkdtempSync(path.join(loc.runtimeDir,`.install-${RUNTIME_REVISION}-`));
  const identity=fs.lstatSync(stage),staged={runtimeDir:stage};
  try {
    const root=prepareRuntimeManifest(staged);
    await install(root);
    markRuntimeReady(staged);
    if(!runtimeReady(staged))throw new RuntimeError('AGENT_CONNECT_RUNTIME_VALIDATION_FAILED');
    return await withInstallerLock(loc.runtimeDir,()=>{
      const published=reuseOrConflict(loc);
      if(published)return published;
      // Reverify the actual npm output, patches, and receipt while holding the
      // publication lock. Rename stays on the runtime filesystem and is atomic.
      if(!runtimeReady(staged))throw new RuntimeError('AGENT_CONNECT_RUNTIME_VALIDATION_FAILED');
      const final=runtimeDirectory(loc);
      ensureDirectory(path.dirname(final));
      if(exists(final))throw new RuntimeError('RUNTIME_RELEASE_CONFLICT');
      assertSafePath(final);
      fs.renameSync(root,final);
      return result(loc,false);
    },lockTimeoutMs);
  } finally {
    // A crash can leave an orphan. Never scan for, reuse, or clean other stages.
    // Also refuse to delete a replacement at our own former pathname.
    if(exists(stage)) {
      const current=fs.lstatSync(stage);
      if(current.isDirectory()&&current.ino===identity.ino&&current.dev===identity.dev) {
        assertSafePath(stage);
        fs.rmSync(stage,{recursive:true,force:true});
      }
    }
  }
}

if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const target=process.argv[2];
    if(!target||!path.isAbsolute(target))throw new RuntimeError('RUNTIME_PATH_INVALID');
    process.stdout.write(JSON.stringify(await installRuntime(path.join(target,'runtime')))+'\n');
  } catch(error) {
    process.stderr.write((error instanceof RuntimeError?error.code:'RUNTIME_INSTALL_FAILED')+'\n');
    process.exitCode=1;
  }
}
