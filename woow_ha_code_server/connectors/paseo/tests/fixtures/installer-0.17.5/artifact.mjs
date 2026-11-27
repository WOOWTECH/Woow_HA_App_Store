import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {seedNpmOutput as seedPatchInputs} from './seed.mjs';
import {copyMcpRefreshFixture} from '../../mcp-refresh-fixture.mjs';
import {CLAUDE_ROOT_PATH,ORIGINAL_CLAUDE_SHA256} from '../../../src/claude-root-patch.mjs';
import {esbuildFiles} from '../../../src/esbuild-runtime.mjs';

// These files were extracted from local official npm tarballs only after each
// archive's SHA-512 matched runtime-manifest/package-lock.json. No dummy modules.
export const entrypointPackages=JSON.parse(gunzipSync(fs.readFileSync(new URL('./entrypoints.json.gz',import.meta.url)))).packages;
export const entrypointFiles=Object.entries(entrypointPackages).flatMap(([pkg,{files}])=>Object.entries(files).map(([name,{sha256,base64}])=>{
  const bytes=Buffer.from(base64,'base64');
  assert.ok(bytes.length>0);
  assert.equal(createHash('sha256').update(bytes).digest('hex'),sha256);
  return {name:`${pkg}/${name}`,relative:`node_modules/@getpaseo/${pkg}/${name}`,bytes,sha256};
}));
const mcpInputs=JSON.parse(gunzipSync(fs.readFileSync(new URL('./mcp-inputs.json.gz',import.meta.url))));
assert.equal(mcpInputs.integrity,entrypointPackages.server.integrity);
export function seedNpmOutput(root) {
  // Keep native executables out of the source/consumer fixture bundle. Offline
  // installer tests use the explicitly prepared, hash-verified R4 SDK; copy its
  // binary before hardlinking only the two disposable destination paths.
  const compilerRoot=process.env.WOOW_PASEO_TEST_RUNTIME;
  assert.ok(compilerRoot,'WOOW_PASEO_TEST_RUNTIME must point at the prepared R4 SDK');
  for(const [relative,expected] of Object.entries(esbuildFiles())) {
    const source=path.join(compilerRoot,relative),bytes=fs.readFileSync(source);
    assert.equal(createHash('sha256').update(bytes).digest('hex'),expected,relative);
    const target=path.join(root,relative);fs.mkdirSync(path.dirname(target),{recursive:true});
    if(relative.startsWith('node_modules/@esbuild/'))fs.linkSync(path.join(root,'node_modules/esbuild/bin/esbuild'),target);
    else fs.copyFileSync(source,target);
  }
  seedPatchInputs(root);
  for(const {relative,bytes} of entrypointFiles) {
    const file=path.join(root,relative);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,bytes);
  }
  for(const [relative,{base64,sha256}] of Object.entries(mcpInputs.files)) {
    const bytes=Buffer.from(base64,'base64');assert.equal(createHash('sha256').update(bytes).digest('hex'),sha256);
    const file=path.join(root,relative);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,bytes);
  }
  // The connected worker's helper validates all four original SDK inputs. Use
  // the actual frozen SDK when supplied, or these verified archive extracts.
  copyMcpRefreshFixture(process.env.WOOW_PASEO_TEST_RUNTIME||root,root);
  const claude=gunzipSync(fs.readFileSync(new URL('./claude-agent.js.gz',import.meta.url)));
  assert.equal(createHash('sha256').update(claude).digest('hex'),ORIGINAL_CLAUDE_SHA256);
  const file=path.join(root,CLAUDE_ROOT_PATH);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,claude);
}
