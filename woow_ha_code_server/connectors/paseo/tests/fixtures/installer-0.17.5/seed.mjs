import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {PID_LOCK_COPIES,ORIGINAL_PID_LOCK_SHA256} from '../../../src/pid-lock-patch.mjs';
import {BRAND_SERVER_PATH,ORIGINAL_BRAND_SERVER_SHA256} from '../../../src/brand-identity-patch.mjs';
import {SMART_TASKS_REGISTRY_PATH,ORIGINAL_TASKS_REGISTRY_SHA256} from '../../../src/smart-tasks-patch.mjs';

// Exact unpatched @getpaseo/server 0.17.5 inputs from the reviewed upstream
// fixtures, matching the managed lock's npm tarball. Only npm is simulated;
// production patchers, payload hashes, receipt creation and readiness all run.
export const serverIntegrity='sha512-OJpReFyY9etl0SQw53/ISaBNrV3gnHWMtzpnFVE5i0+Toike2fIUEMpBg2bPZofiBaL0fhcjC31DpRIFQOkrgg==';
const read=name=>fs.readFileSync(new URL(name,import.meta.url));
const checked=(bytes,hash)=>{
  assert.equal(createHash('sha256').update(bytes).digest('hex'),hash);
  return bytes;
};
const pid=checked(read('pid-lock.js'),ORIGINAL_PID_LOCK_SHA256);
const brand=checked(gunzipSync(read('websocket-server.js.gz')),ORIGINAL_BRAND_SERVER_SHA256);
const registry=checked(read('builtin-index.js'),ORIGINAL_TASKS_REGISTRY_SHA256);
function write(root,name,bytes) {
  const file=path.join(root,name);
  fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,bytes);
}
export function seedNpmOutput(root) {
  for(const pkg of ['cli','client','server','protocol'])write(root,`node_modules/@getpaseo/${pkg}/package.json`,JSON.stringify({name:`@getpaseo/${pkg}`,version:'0.17.5',type:'module'}));
  for(const copy of PID_LOCK_COPIES)write(root,`node_modules/@getpaseo/server/${copy}/pid-lock.js`,pid);
  write(root,BRAND_SERVER_PATH,brand);
  write(root,SMART_TASKS_REGISTRY_PATH,registry);
}
