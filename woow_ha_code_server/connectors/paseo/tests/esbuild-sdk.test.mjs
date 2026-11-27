import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';

// Explicit local SDK fixture only. Never starts a daemon/provider or uses an account.
const root=process.env.WOOW_PASEO_TEST_RUNTIME;
const actual={skip:!root};
const server=relative=>pathToFileURL(path.join(root,'node_modules/@getpaseo/server/dist/server/server',relative)).href;
let esbuild;
test.after(()=>esbuild?.stop());
function fixture(t) {
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'paseo-esbuild-r4-'));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  const write=(relative,source)=>{const file=path.join(directory,relative);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,source);return file;};
  return {directory,write};
}

test('actual R4 SDK resolves the pinned wrapper and both native esbuild binaries',actual,async()=>{
  esbuild=await import(pathToFileURL(path.join(root,'node_modules/esbuild/lib/main.js')).href);
  assert.equal(esbuild.version,'0.28.2');
  const platform=`${process.platform}-${process.arch}`;
  for(const relative of ['node_modules/esbuild/bin/esbuild',`node_modules/@esbuild/${platform}/bin/esbuild`]) {
    const file=path.join(root,relative),result=spawnSync(file,['--version'],{encoding:'utf8',timeout:5000});
    assert.equal(result.status,0,result.stderr);assert.equal(result.stdout.trim(),'0.28.2');
    assert.ok(fs.readFileSync(file).includes(Buffer.from('go1.26.5')),'official 0.28.2 binary uses patched Go');
  }
});

test('actual SDK plugin compiler builds and runs server TS, client TSX/SVG and async bundles',actual,async t=>{
  const {directory,write}=fixture(t);
  write('paseo-plugin.json',JSON.stringify({id:'r4-offline-compile',name:'R4 offline compiler contract',requirements:{paseo:'>=0.17.5'}}));
  write('shared/marker.ts','export const marker: string = "R4_OFFLINE";');
  write('index.server.ts','import {join} from "node:path"; import {marker} from "./shared/marker"; export function readValue(): string {return join(marker,"server");}');
  write('client/icon.svg','<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>');
  write('index.client.tsx','import {marker} from "./shared/marker"; import svg from "./client/icon.svg"; export function readIcon() {return svg;} export async function readMarker() {return marker;} export function Demo(){return <span>{marker}</span>;}');
  const {compileDirectoryPlugin}=await import(server('plugins/compiler-build.js'));
  const result=await compileDirectoryPlugin(directory,'0.17.5');
  assert.equal(result.manifest.id,'r4-offline-compile');
  const serverExports=vm.runInNewContext(result.serverBundle)(specifier=>{assert.equal(specifier,'node:path');return path;});
  assert.equal(serverExports.readValue(),path.join('R4_OFFLINE','server'));
  const clientExports=vm.runInNewContext(result.clientBundle)(specifier=>{
    assert.equal(specifier,'react/jsx-runtime');return {jsx:(tag,props)=>({tag,...props})};
  });
  assert.equal(await clientExports.readMarker(),'R4_OFFLINE');
  assert.ok(clientExports.readIcon().startsWith('<svg'));
  assert.equal(clientExports.Demo().tag,'span');assert.equal(clientExports.Demo().children,'R4_OFFLINE');
});

test('actual plugin compiler still rejects Node and server imports in a client bundle',actual,async t=>{
  const {write}=fixture(t),entry=write('index.client.ts','import {readFileSync} from "node:fs"; export const value = readFileSync("unused");');
  const {compilePlugin}=await import(server('plugins/compiler-build.js'));
  await assert.rejects(compilePlugin({client:entry}),/Node module cannot be imported into the plugin client bundle/);
  write('server/private.ts','export const secret = "fixture-only";');
  write('index.client.ts','import {secret} from "./server/private"; export const value = secret;');
  await assert.rejects(compilePlugin({client:entry}),/server-only module cannot be imported into the plugin client bundle/);
});

test('actual OpenCode bridge private compile API rebuilds both shipped bridge artifacts',actual,async()=>{
  const url=server('agent/providers/opencode/bridge.js'),source=fs.readFileSync(new URL(url),'utf8');
  assert.equal(createHash('sha256').update(source).digest('hex'),'251f63477083cac3835790fedd3ac900372bf0c1a27d54d4153be867903b20b5');
  // Expose only the real private function in memory; installed SDK bytes stay unchanged.
  const hooks=registerHooks({load(candidate,context,next){
    const loaded=next(candidate,context);
    return candidate===url?{...loaded,source:source+'\nexport {compileOpenCodeBridgePlugin as compileForContract};\n'}:loaded;
  }});
  let compileForContract;
  try {({compileForContract}=await import(url));}finally{hooks.deregister();}
  for(const relative of ['bridge-plugin.bundle.mjs','v2/bridge-plugin.bundle.mjs']) {
    const file=new URL(relative,url),bytes=await compileForContract(file.pathname);
    assert.ok(bytes instanceof Uint8Array);assert.ok(bytes.length>100);
    const exports=await import('data:text/javascript;base64,'+Buffer.from(bytes).toString('base64'));
    assert.equal(typeof (relative.startsWith('v2/')?exports.default.setup:exports.default),'function');
  }
});
