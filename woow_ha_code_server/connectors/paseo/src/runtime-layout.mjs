import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
import {setTimeout as delay} from 'node:timers/promises';
import {privateDirectory,atomicJson,RuntimeError,assertSafePath} from './state.mjs';
import {applyPidLockPatch,pidLockPatchReady,PID_LOCK_PATCH_ID,PID_LOCK_COPIES,PID_LOCK_0112} from './pid-lock-patch.mjs';
import {applyBrandIdentityPatch,brandIdentityPatchReady,BRAND_IDENTITY_PATCH_ID,BRAND_0112} from './brand-identity-patch.mjs';
import {applySmartTasksPatch,smartTasksPatchReady,validateSmartTasksSource,SMART_TASKS_PATCH_ID} from './smart-tasks-patch.mjs';
import {applyMcpRefreshPatch,mcpRefreshPatchReady,MCP_REFRESH_PATCH_ID} from './mcp-refresh-patch.mjs';
import {applyClaudeRootPatch,claudeRootPatchReady,CLAUDE_ROOT_PATCH_ID} from './claude-root-patch.mjs';
import {esbuildRuntimeReady} from './esbuild-runtime.mjs';
export const PASEO_VERSION='0.17.5';
// Managed releases before this one ran either Paseo 0.17.4 or 0.11.2; the pre-release runtimeDir layout used 0.11.2.
export const LEGACY_PASEO_VERSION='0.11.2';
// The default runtimeDir is also ../runtime. Ship build inputs separately so an
// in-place connector upgrade preserves the legacy root manifests and SDK for stop.
const template=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../runtime-manifest');
const manifest=fs.readFileSync(path.join(template,'package.json'));
const lock=fs.readFileSync(path.join(template,'package-lock.json'));
const lockedPackages=JSON.parse(lock).packages;
const lockSha256=createHash('sha256').update(lock).digest('hex');
export const RUNTIME_REVISION=PASEO_VERSION+'-r4-'+lockSha256.slice(0,12);
export const runtimeDirectory=loc=>path.join(loc.runtimeDir,'releases',RUNTIME_REVISION);
// Essential executable, SDK, configuration and supervisor entrypoints extracted
// from official npm archives whose SHA-512 matched the unchanged managed lock.
// A package.json version and a patch receipt alone cannot prove a usable install.
// daemon-client.js/messages.js are pinned to the reviewed managed-MCP patch's
// output; all other entrypoint hashes describe the original npm archive bytes.
const ENTRYPOINT_PACKAGES=Object.freeze({
 cli:{integrity:'sha512-2cxRWg04psNq82ME2eCXMv1VeSHhMsSS+EHdolL1QzVA+bSzpcGlYjYNjtpiWFYDnS4sdm3O8HFeb3w28s0w5g==',files:{
  'package.json':'f38b87a78f3429fbb76a9f292c953464f61ca064881b9f47d83f72557985c5e9',
  'bin/paseo':'2b761f40e5a6416e4aaa733f38a47d5a4639b42cc1f88fc060256d2c4ed8cf94',
  'dist/index.js':'8620d03c3e7e6776c3bfc4d22a8875f92209a563612fe7cda63dea7512f83c09',
  'dist/run.js':'49b38f3d80070a7510725dc731f7d49e15a60624e6879a2bf8a70d0f851fe73e',
  'dist/cli.js':'4380997b565ed0ab3cfa2631cd07f208c1a9b5bd16e8e00fe809c0c98fd5cd8c',
  'dist/utils/client.js':'9d36d7e84c375b0cd7e6775c138fb4ea3176855bb8f849753a83104789b6a1be',
 }},
 client:{integrity:'sha512-PQ10i1vNP71C0LULQkzyg2ZZ6BVdMWOGK8QDyoO9oKIhCnElg8levNEI29k92CWWz92O1M1+tJ0gfXarUzJr7g==',files:{
  'package.json':'e604327def5d26ce565d72ad7d7da53f0bd7f92c4a5b1a93636545e5b0b42b42',
  'dist/index.js':'4d0a97e375fe37881bd9ad53db90f51b8b3811c219c4c06dc3b8b8fdf06b63c3',
  'dist/node/index.js':'6ef4a656076563c5ffd12d6f7bac3f1f832dab9a6478534c0f3415c999fde578',
  'dist/daemon-client.js':'c7bb6b92338e80c606499767ad7d04c5a6b249f962695667e95272da1a92f942',
 }},
 server:{integrity:'sha512-OJpReFyY9etl0SQw53/ISaBNrV3gnHWMtzpnFVE5i0+Toike2fIUEMpBg2bPZofiBaL0fhcjC31DpRIFQOkrgg==',files:{
  'package.json':'37d16f7e7c216d794abbcd920ebf61bd21300e6e4ee2246bbdd6fa36ed445756',
  'dist/server/server/exports.js':'5b5e75280ce00063df150220c8af681ba7528737a3260b62b6db2a758e4ffaf7',
  'dist/server/server/config.js':'3f320570fadb47f83c50ad1a30dbb48d6901c584b706ec91aa6a2a11eaae309a',
  'dist/server/server/daemon-instance.js':'59e47c7842a4da6c507e537d3b7c474c73895c457bbef19f4ee6b3896bf7cad5',
  'dist/scripts/supervisor-entrypoint.js':'935ea7f386cb464f1aacd111901370b7c7b11ef4c9e6a1ce5fe378dee78cd3bb',
  'dist/scripts/supervisor.js':'b49fd010d7e136be254ea0aba16aa956e0cd0ae78e95c26678d9737838499db6',
  'dist/server/server/daemon-worker.js':'c010bef70008cc3b00c100abddf345dd5fff896aa9d9aa6ace6a74fe6c087bb5',
  'dist/server/server/bootstrap.js':'1888edebaa77f4188c0ff96cc966ce6df1a8d28130a6a49bd6971de5b9fb33c0',
  'dist/server/web-ui/index.html':'4c17e75ceb970dbcb25d3ae303c54a5027fe5232ebb427755a761db87c699353',
 }},
 protocol:{integrity:'sha512-d50Lrxvu+RnuyzOIE2qp22E2rxlvvzYyRfiXU5y1r7ysrD2o3EQ+yxc/p+GjyHrfIWmTRSQ+MjvpcyxJ1pjn/w==',files:{
  'package.json':'ceeca461e2da3737e917d83d8c5e267d5a8a639e32cb0980a338c8fd2924c71a',
  'dist/addresses.js':'7609da77a8960f5986ff45d29d07675caf21e0ccbcd2b0e7258c771bc321179d',
  'dist/messages.js':'f8f1f28c528c4f7b2e85d9f5b38d3d4f32a7b71288417580e9551d7e43f33f9e',
 }},
});
// Existing-daemon control compatibility only; these releases are never started.
// Frozen 0.11.2 lockfiles: 4cf9d4… shipped with later r3 and all r4 (Agent Connect
// 0.1.18-0.1.23 run 0.11.2-r4-4cf9d40940bf), 6d8dbe… with r2 and the first r3. These four are
// every release Agent Connect 0.1.4-0.1.23 shipped, newest first (0.1.1-0.1.3 ran r1: unsupported).
// r1 and r4 record their revision in state.json on non-Linux hosts; older r2/r3 daemons do not.
const LOCK_0112_HONO='4cf9d40940bf5b58301775cb8322866d3bcd605db341125d98bd5218b0dfefc0';
const LOCK_0112='6d8dbe5154790bbbb0b1281e991871b6f354919022fb55a1235162e969779526';
// The code-server package's independently built 0.11.2-r2 generation. It lives
// directly at runtimeDir (before immutable releases/) and is retained solely to
// control a daemon already running those exact bytes during migration.
const CODE_SERVER_0112_LOCK='478caab5da835fd55471ada8fcfe25b469e19e34dd0ee51b444671021d6251c2';
const CODE_SERVER_0112_PACKAGE='7e00fc186f3cdda485b6f337a70754fb50c88a5a93a4cfec6f2efe339ff4baac';
const LOCK_0174_R1='a651f42711da045b31e8a2b8993d9b82e7b7cbbef0cffcf48dfdcd5baf9d8530';
// Frozen Agent Connect 0.1.24 runtime. It has the original 0.17.4 lock plus PID and brand patches,
// and predates the Smart Tasks integration. These literals only validate its offline control path.
const PID_0174_R1=Object.freeze({original:'a4e8bc790b27c944847b7bb84694b38d0366d08d7d565409edbc63dd6462b8f7',patched:'194013b387417fb9b6d74b7a305173d8f28478ef268b7a4c073b9882af66bd1b',patchId:'1451c9714ffd86380ff04cbe0219b4a2b0d5a3cd39e152fa5e5fabc0d5403828',helperSha256:'37bdef75ee090452ce946bbf051d411352d51fda95d8121ff0c83a34680e3987'});
const BRAND_0174_R1=Object.freeze({original:'bfc79901aa7768a51b98385b6f729dac69a1098f4480a66fd3d2be1d6af06b4b',patched:'17ea88357d2f25caab81ad63d32804fe41158c1d70e8e4f549c4fc7173fe8d68',patchId:'20f860e40bfb9d654182fd996f4f1999f2b73fe2f2f924519bc344a5592e89f2',helperSha256:'036471982ccbbb5a7c3418631518025b245ac50e1c0b1a29c3824d16ba069733'});
// Agent Connect 0.1.25/0.1.26 adds this exact Tasks payload to the same lock and patches.
const TASKS_0174_R2=Object.freeze({registrySha256:'f20ea6c51acf595a72148998547ab6edc8623275f3a36f86eb2dc51415f2098e',provenanceSha256:'08a0cbe942bd3136d983e63f8c723f2b17e21f433d410bddb6faf4b5a1c802c8',patchId:'2250785f3f115705f092c3a0b45ae43386c57ef596a1c9afb65a02a38caeb485'});
// Frozen code-server r1 (before managed MCP refresh). Keep control of an already
// running r1 daemon after the r2 build bump; never select this release for start.
const LOCK_0175_R1='8664f2c3f8f58c15b8ec264fec9b69c3bc443192efd60365212e532c811f4ce2';
const BRAND_0175_R1=Object.freeze({original:'a11dd0366089d25c57c71929c3d56d47dfef3d40cc272c010c4e08bc74d9ac19',patched:'4abdd2bc4f72d5865521b0d5adfca0743b6bd3a7cb8729df42f9b0baa635c523',patchId:'54f658b3f7885b521b6d664efbbd22b5f384c1878d36e45bb988de9ce9ac916b',helperSha256:'036471982ccbbb5a7c3418631518025b245ac50e1c0b1a29c3824d16ba069733'});
// Frozen pre-root-fix code-server candidate. These hashes are control-only and
// must not follow a future MCP recipe or helper change.
const MCP_0175_R2=Object.freeze({patchId:'9d00cdb1f37426bf732e9fa4c02dc491c04f845eb1efd4b63e649f91687c3571',files:{
 'node_modules/@getpaseo/server/dist/server/server/agent/woow-managed-mcp.mjs':'6d8e117a106874132fc5d41f9c5703d5d9adedb5e0ac5833183ed5c24dda02aa',
 'node_modules/@getpaseo/server/dist/server/server/agent/agent-manager.js':'5145619c6444c10e0288b3281ef9eea943b634911bc1b779a722fa747b75ead0',
 'node_modules/@getpaseo/server/dist/server/server/session.js':'41d1e97651a01195963ae69a7189be5b218cbc9fd895305f4db50ee92a562328',
 'node_modules/@getpaseo/client/dist/daemon-client.js':'c7bb6b92338e80c606499767ad7d04c5a6b249f962695667e95272da1a92f942',
 'node_modules/@getpaseo/protocol/dist/messages.js':'f8f1f28c528c4f7b2e85d9f5b38d3d4f32a7b71288417580e9551d7e43f33f9e',
 'node_modules/@getpaseo/server/dist/server/server/agent/providers/claude/agent.js':'6f56bf2aee54221707b40ea35bcc201525190d6e88a20c0414f465c1ba088569',
}});
// Exact code-server R3 artifacts captured before the esbuild dependency update.
// This independent record includes both manifests, all essential files and all
// five patch receipts/payloads. It must never follow the current patch recipes.
const CONTROL_0175_R3=JSON.parse(fs.readFileSync(new URL('./runtime-control-0175-r3.json',import.meta.url)));
const priorReleases=[
 {version:'0.17.5',generation:'r3',sha:'8664f2c3f8f58c15b8ec264fec9b69c3bc443192efd60365212e532c811f4ce2',frozen:CONTROL_0175_R3,recordedRevision:true},
 {version:'0.17.5',generation:'r2',sha:LOCK_0175_R1,pid:PID_0174_R1,brand:BRAND_0175_R1,tasks:TASKS_0174_R2,mcp:MCP_0175_R2,recordedRevision:true},
 {version:'0.17.5',generation:'r1',sha:LOCK_0175_R1,pid:PID_0174_R1,brand:BRAND_0175_R1,tasks:TASKS_0174_R2,recordedRevision:true},
 {version:'0.17.4',generation:'r2',sha:LOCK_0174_R1,pid:PID_0174_R1,brand:BRAND_0174_R1,tasks:TASKS_0174_R2,recordedRevision:true},
 {version:'0.17.4',generation:'r1',sha:LOCK_0174_R1,pid:PID_0174_R1,brand:BRAND_0174_R1,recordedRevision:true},
 {version:LEGACY_PASEO_VERSION,generation:'r4',sha:LOCK_0112_HONO,pid:PID_LOCK_0112,brand:BRAND_0112,recordedRevision:true},
 {version:LEGACY_PASEO_VERSION,generation:'r3',sha:LOCK_0112_HONO,pid:PID_LOCK_0112},
 {version:LEGACY_PASEO_VERSION,generation:'r3',sha:LOCK_0112,pid:PID_LOCK_0112},
 {version:LEGACY_PASEO_VERSION,generation:'r2',sha:LOCK_0112},
].map(release=>Object.freeze({...release,revision:release.version+'-'+release.generation+'-'+release.sha.slice(0,12)}));
/** Revisions of the earlier releases, newest first. */
export const PRIOR_RUNTIME_REVISIONS=Object.freeze(priorReleases.map(release=>release.revision));
/** Exact legacy code-server root, for offline control only; never selected for a new start. */
export function codeServerLegacyRuntimeDirectory(loc) {
 const root=loc.runtimeDir;
 try {
  const lockFile=path.join(root,'package-lock.json'),packageFile=path.join(root,'package.json');
  assertSafePath(lockFile);assertSafePath(packageFile);
  if(createHash('sha256').update(fs.readFileSync(lockFile)).digest('hex')!==CODE_SERVER_0112_LOCK)return null;
  if(createHash('sha256').update(fs.readFileSync(packageFile)).digest('hex')!==CODE_SERVER_0112_PACKAGE)return null;
  for(const pkg of ['cli','client','server','protocol']){
   const file=path.join(root,'node_modules/@getpaseo',pkg,'package.json');assertSafePath(file);
   if(JSON.parse(fs.readFileSync(file)).version!==LEGACY_PASEO_VERSION)return null;
  }
  return root;
 }catch{return null;}
}
function verifiedPrior(loc,{revision,sha,version,pid,brand,tasks,mcp,frozen}) {
 // Never follow state-provided paths or scan arbitrary versions.
 const root=path.join(loc.runtimeDir,'releases',revision);
 try {
  const receiptFile=path.join(root,'.pi-paseo-runtime.json');assertSafePath(receiptFile);
  const receipt=JSON.parse(fs.readFileSync(receiptFile));
  if(receipt.revision!==revision||receipt.lockSha256!==sha)return null;
  if(frozen){
   if(frozen.revision!==revision||frozen.version!==version)return null;
   for(const [key,expected] of Object.entries(frozen.receipt))if(receipt[key]!==expected)return null;
   for(const [relative,expected] of Object.entries(frozen.files)){
    const file=path.join(root,relative),stat=assertSafePath(file);
    if(!stat?.isFile()||stat.size===0||createHash('sha256').update(fs.readFileSync(file)).digest('hex')!==expected)return null;
   }
   return root;
  }
  for(const pkg of ['cli','server']){
   const file=path.join(root,'node_modules/@getpaseo',pkg,'package.json');assertSafePath(file);
   if(JSON.parse(fs.readFileSync(file)).version!==version)return null;
  }
  if(pid){
   if(receipt.pidLockPatchId!==pid.patchId||!pidLockPatchReady(root,pid))return null;
  }else for(const copy of PID_LOCK_COPIES){
   const file=path.join(root,'node_modules/@getpaseo/server',copy,'pid-lock.js');assertSafePath(file);
   if(createHash('sha256').update(fs.readFileSync(file)).digest('hex')!==PID_LOCK_0112.original)return null;
  }
  if(brand&&(receipt.brandIdentityPatchId!==brand.patchId||!brandIdentityPatchReady(root,brand)))return null;
  if(tasks&&(receipt.smartTasksPatchId!==tasks.patchId||!smartTasksPatchReady(root,tasks)))return null;
  if(mcp){
   if(receipt.mcpRefreshPatchId!==mcp.patchId)return null;
   for(const [relative,expected] of Object.entries(mcp.files)){
    const file=path.join(root,relative);assertSafePath(file);
    if(createHash('sha256').update(fs.readFileSync(file)).digest('hex')!==expected)return null;
   }
  }
  return root;
 }catch{return null;} // Unsupported or unsafe releases cannot supply offline control.
}
/** The verified directory of exactly this earlier release, or null. */
export function priorRuntimeDirectory(loc,revision) {
 const release=priorReleases.find(entry=>entry.revision===revision);
 return release?verifiedPrior(loc,release):null;
}
/** The Paseo version of exactly this verified earlier release, or null. */
export function priorRuntimeVersion(loc,revision) {
 const release=priorReleases.find(entry=>entry.revision===revision);
 return release&&verifiedPrior(loc,release)?release.version:null;
}
/** The newest verified earlier release; with `unrecordedOnly`, among those that never recorded their revision. */
export function previousRuntimeDirectory(loc,{unrecordedOnly=false}={}) {
 for(const release of priorReleases){
  if(unrecordedOnly&&release.recordedRevision)continue;
  const root=verifiedPrior(loc,release);if(root)return root;
 }
 return null;
}

export function runtimeReady(loc) {
 try {
  const root=runtimeDirectory(loc);
  if(!esbuildRuntimeReady(root,lockedPackages))return false;
  for(const [name,bytes] of [['package.json',manifest],['package-lock.json',lock]]) {
   const file=path.join(root,name);if(!assertSafePath(file)?.isFile())return false;
   if(!fs.readFileSync(file).equals(bytes))return false;
  }
  for(const pkg of ['cli','client','server','protocol']) {
   const file=path.join(root,'node_modules/@getpaseo',pkg,'package.json');if(!assertSafePath(file)?.isFile())return false;
   if(JSON.parse(fs.readFileSync(file)).version!==PASEO_VERSION)return false;
  }
  for(const [pkg,{integrity,files}] of Object.entries(ENTRYPOINT_PACKAGES)) {
   const prefix='node_modules/@getpaseo/'+pkg;
   if(lockedPackages[prefix]?.version!==PASEO_VERSION||lockedPackages[prefix]?.integrity!==integrity)return false;
   for(const [name,hash] of Object.entries(files)) {
    const file=path.join(root,prefix,name),stat=assertSafePath(file);
    if(!stat?.isFile()||stat.size===0)return false;
    const bytes=fs.readFileSync(file);
    if(bytes.length===0||createHash('sha256').update(bytes).digest('hex')!==hash)return false;
   }
  }
  if(!assertSafePath(path.join(root,'.pi-paseo-runtime.json'))?.isFile())return false;
  const receipt=JSON.parse(fs.readFileSync(path.join(root,'.pi-paseo-runtime.json')));
  return receipt.revision===RUNTIME_REVISION&&receipt.lockSha256===lockSha256&&receipt.pidLockPatchId===PID_LOCK_PATCH_ID&&pidLockPatchReady(root)&&receipt.brandIdentityPatchId===BRAND_IDENTITY_PATCH_ID&&brandIdentityPatchReady(root)&&receipt.smartTasksPatchId===SMART_TASKS_PATCH_ID&&smartTasksPatchReady(root)&&receipt.mcpRefreshPatchId===MCP_REFRESH_PATCH_ID&&mcpRefreshPatchReady(root)&&receipt.claudeRootPatchId===CLAUDE_ROOT_PATCH_ID&&claudeRootPatchReady(root);
 } catch {return false;}
}
export function prepareRuntimeManifest(loc) {
 validateSmartTasksSource();
 const root=runtimeDirectory(loc);privateDirectory(root);
 const file=path.join(root,'package.json');assertSafePath(file);
 if(fs.existsSync(file)&&JSON.parse(fs.readFileSync(file)).name!=='pi-paseo-managed-runtime')throw new RuntimeError('RUNTIME_NOT_OWNED');
 for(const [name,bytes] of [['package.json',manifest],['package-lock.json',lock]]) {
  assertSafePath(path.join(root,name));fs.writeFileSync(path.join(root,name),bytes);
 }
 return root;
}
export function markRuntimeReady(loc) {const root=runtimeDirectory(loc);applyPidLockPatch(root);applyBrandIdentityPatch(root);applySmartTasksPatch(root);applyMcpRefreshPatch(root);applyClaudeRootPatch(root);atomicJson(path.join(root,'.pi-paseo-runtime.json'),{lockSha256,revision:RUNTIME_REVISION,pidLockPatchId:PID_LOCK_PATCH_ID,brandIdentityPatchId:BRAND_IDENTITY_PATCH_ID,smartTasksPatchId:SMART_TASKS_PATCH_ID,mcpRefreshPatchId:MCP_REFRESH_PATCH_ID,claudeRootPatchId:CLAUDE_ROOT_PATCH_ID});}

// ---- Pruning ----
// Every release is a full install (about 0.6-0.7 GB), and each upgrade leaves the previous one for a rollback and
// for controlling a daemon that still runs it. Pruning removes the ones nothing needs any more.
// It only ever touches a plugin-owned release: a directory directly under <runtimeDir>/releases that is named like
// a revision (<paseo version>-r<n>-<12 hex of its lockfile hash>), is a real directory (never a link) and holds a
// receipt that says the same: .pi-paseo-runtime.json with revision equal to the name and a lockSha256 that begins
// with the name's hash. Anything else under releases/ (other names, plain files, links, half-installed
// directories without a receipt, copies someone else made) and everything outside it, including the legacy
// <runtimeDir>/node_modules that earlier plugin versions installed, stays as it is.
//
// Three steps, so that the slow one never needs the caller's lock: prunePlan reads, claimReleases renames each
// release to .pruning-<revision>-<uuid> (one step: it is no longer a release), removeTombs deletes the tombs. A
// tomb that a crash left behind is a plain leftover: the next plan lists it and the next removal finishes it.
const RELEASE_NAME=/^(\d+)\.(\d+)\.(\d+)-r(\d+)-([0-9a-f]{12})$/;
const TOMB_NAME=/^\.pruning-(\d+\.\d+\.\d+-r\d+-[0-9a-f]{12})-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const RECEIPT='.pi-paseo-runtime.json';
const compareOrder=(a,b)=>{for(let i=0;i<4;i++)if(a[i]!==b[i])return a[i]-b[i];return 0;};
function ownedRelease(releases,name) {
 const match=RELEASE_NAME.exec(name);if(!match)return null;
 const root=path.join(releases,name),receiptFile=path.join(root,RECEIPT);
 let fd;
 try {
  if(!fs.lstatSync(root).isDirectory())return null; // lstat: a link to a directory is not one
  assertSafePath(receiptFile);
  const stat=fs.lstatSync(receiptFile);
  if(!stat.isFile()||stat.size>65536)return null;
  fd=fs.openSync(receiptFile,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
  const receipt=JSON.parse(fs.readFileSync(fd,'utf8'));
  if(!receipt||typeof receipt!=='object'||receipt.revision!==name)return null;
  if(typeof receipt.lockSha256!=='string'||!/^[0-9a-f]{64}$/.test(receipt.lockSha256)||receipt.lockSha256.slice(0,12)!==match[5])return null;
  return {name,order:match.slice(1,5).map(Number),receiptMtimeMs:stat.mtimeMs};
 } catch {return null;} finally {if(fd!==undefined)try{fs.closeSync(fd);}catch{}}
}
/** The plugin-owned releases under <runtimeDir>/releases, newest first: Paseo version, then revision number, then receipt time
 * (when it was installed), then name for a tie. Releases of one version and revision number differ only in their lockfile hash. */
export function ownedReleases(loc) {
 const releases=path.join(loc.runtimeDir,'releases');
 try {
  assertSafePath(releases);
  if(!fs.lstatSync(releases).isDirectory())return [];
  return fs.readdirSync(releases).map(name=>ownedRelease(releases,name)).filter(Boolean)
   .sort((a,b)=>compareOrder(b.order,a.order)||b.receiptMtimeMs-a.receiptMtimeMs||(a.name<b.name?1:-1));
 } catch {return [];}
}
/** What an earlier removal renamed away and did not finish deleting: [{name: the revision it was, tomb: its directory name}]. */
function leftoverTombs(releases) {
 try {
  return fs.readdirSync(releases).filter(entry=>TOMB_NAME.test(entry)).filter(entry=>{try{return fs.lstatSync(path.join(releases,entry)).isDirectory();}catch{return false;}})
   .map(tomb=>({name:TOMB_NAME.exec(tomb)[1],tomb}));
 } catch {return [];}
}
/** Reads only. {candidates: releases that may go, kept: releases that stay, tombs: leftovers to finish, skipped?: why nothing is planned}.
 * Stay: this release; the one newest earlier release (a rollback); every release newer than this one (a downgrade
 * is followed by an upgrade, and that is 0.7 GB to download again); every name in `keep`, which the caller fills
 * with the releases a running process still uses or needs for control. Without a valid current release nothing is planned.
 * Earlier and newer are positions in ownedReleases' order, not a comparison of version numbers: two releases of one
 * Paseo version and revision number (two lockfiles; r3 shipped with two) tie by number, and the receipt time that orders
 * them in the list decides which is newer and which is the rollback. A tie never makes a release a candidate by itself. */
export function prunePlan(loc,{keep=[]}={}) {
 const releases=path.join(loc.runtimeDir,'releases'),plan={candidates:[],kept:[],tombs:[]};
 try {assertSafePath(releases);if(!fs.lstatSync(releases).isDirectory())return {...plan,skipped:'RELEASES_NOT_A_DIRECTORY'};}
 catch(error) {return error?.code==='ENOENT'?plan:{...plan,skipped:'RELEASES_UNSAFE'};}
 const owned=ownedReleases(loc),index=owned.findIndex(release=>release.name===RUNTIME_REVISION);
 if(index<0)return {...plan,skipped:'CURRENT_RELEASE_NOT_FOUND'};
 const stay=new Set([RUNTIME_REVISION,...keep]);
 if(owned[index+1])stay.add(owned[index+1].name); // the rollback: the release right after this one, newest first
 owned.forEach((release,position)=>(stay.has(release.name)||position<index?plan.kept:plan.candidates).push(release.name));
 plan.tombs=leftoverTombs(releases);
 return plan;
}
/** Renames each named release to a tomb (one step each, no deleting). Cheap: it is the part to do under a lock.
 * {claimed: [{name, tomb}], failed: [names]}. */
export function claimReleases(loc,names) {
 const releases=path.join(loc.runtimeDir,'releases'),claimed=[],failed=[];
 for(const name of names) {
  const tomb=`.pruning-${name}-${randomUUID()}`;
  try {
   if(!ownedRelease(releases,name)||name===RUNTIME_REVISION)throw new RuntimeError('RUNTIME_NOT_OWNED');
   fs.renameSync(path.join(releases,name),path.join(releases,tomb));claimed.push({name,tomb});
  } catch {failed.push(name);}
 }
 return {claimed,failed};
}
// A release is tens of thousands of files. fs.promises.rm({recursive}) starts the delete of every entry of a directory at
// once: all of them are queued on the thread pool, so a read that something else needs (a stop's, a status's) waits behind
// them, and their callbacks keep the event loop busy in long stretches. Measured on a fast disk with 50 000 files: the
// event loop stood still for up to 250 ms and a small readFile took up to 800 ms. removeTree does one operation at a time,
// from the leaves up, pauses briefly every REMOVAL_BATCH operations (the disk is an SD card on the boards this runs on, and a
// daemon is using it), and looks at `aborted` before each operation, so a stop ends it within one.
const PAUSE_MS=2;
/** How many file operations removeTree makes between two pauses (and two turns of the event loop). */
export const REMOVAL_BATCH=64;
/** Deletes `root` and everything under it without following a link: an entry that is a link (or anything but a
 * directory) is unlinked as itself, and only real directories are entered. Resolves to true when the whole tree is gone,
 * to false when `aborted()` ended it first (what is left stays as it is: the directory is still there, with whatever it
 * had not lost yet); anything else that fails is thrown, except ENOENT (someone else already removed it).
 * `ops` is the file system (the fs.promises calls lstat, readdir, unlink and rmdir) and `pause` the wait between batches,
 * for tests. */
export async function removeTree(root,{aborted=()=>false,ops=fs.promises,pause=()=>delay(PAUSE_MS)}={}) {
 let operations=0;
 const batch=async()=>{if(++operations%REMOVAL_BATCH===0)await pause();};
 const gone=error=>error?.code==='ENOENT';
 // The root itself is looked at without following it: a link is removed as itself, whatever it points to.
 try {if(!(await ops.lstat(root)).isDirectory()){await ops.unlink(root);return true;}} catch(error) {if(gone(error))return true;throw error;}
 const stack=[{dir:root,entries:null}];
 while(stack.length) {
  if(aborted())return false;
  const top=stack[stack.length-1];
  if(top.entries===null) {
   // The type of each entry comes with the listing (the directory entry's own type, never what a link points to).
   try {top.entries=await ops.readdir(top.dir,{withFileTypes:true});} catch(error) {if(!gone(error))throw error;stack.pop();}
   await batch();continue;
  }
  const entry=top.entries.pop();
  if(!entry) {
   try {await ops.rmdir(top.dir);} catch(error) {if(!gone(error))throw error;}
   stack.pop();await batch();continue;
  }
  const target=path.join(top.dir,entry.name);
  if(entry.isDirectory()) {stack.push({dir:target,entries:null});continue;}
  try {await ops.unlink(target);} catch(error) {if(!gone(error))throw error;}
  await batch();
 }
 return true;
}
/** Deletes tombs (the slow part: it takes no lock and does not follow links). A tomb is only ever a real directory
 * whose name this code made. {removed: [names], failed: [names], aborted?: true}: with `aborted` the deletion stopped
 * early, and the tomb it was in (and every one after it) is neither removed nor failed, it is left for the next run.
 * `aborted`, `ops` and `pause` go to removeTree. */
export async function removeTombs(loc,items,{aborted=()=>false,ops,pause}={}) {
 const releases=path.join(loc.runtimeDir,'releases'),removed=[],failed=[];
 for(const {name,tomb} of items) {
  if(aborted())return {removed,failed,aborted:true};
  try {
   if(!TOMB_NAME.test(tomb))throw new RuntimeError('RUNTIME_NOT_OWNED');
   if(!fs.lstatSync(path.join(releases,tomb)).isDirectory())throw new RuntimeError('RUNTIME_NOT_OWNED');
   if(await removeTree(path.join(releases,tomb),{aborted,ops,pause})===false)return {removed,failed,aborted:true};
   removed.push(name);
  } catch(error) {(error?.code==='ENOENT'?removed:failed).push(name);} // gone already: someone else finished it
 }
 return {removed,failed};
}
/** All three steps in a row: {removed, kept, failed, skipped?, aborted?}, names only. Best effort: what cannot be removed is
 * reported in `failed`, never thrown. */
export async function pruneRuntimeReleases(loc,{keep=[],aborted,ops,pause}={}) {
 const plan=prunePlan(loc,{keep});
 if(plan.skipped)return {removed:[],kept:[],failed:[],skipped:plan.skipped};
 const claim=claimReleases(loc,plan.candidates),done=await removeTombs(loc,[...plan.tombs,...claim.claimed],{aborted,ops,pause});
 return {removed:done.removed,kept:plan.kept,failed:[...claim.failed,...done.failed],...(done.aborted?{aborted:true}:{})};
}
