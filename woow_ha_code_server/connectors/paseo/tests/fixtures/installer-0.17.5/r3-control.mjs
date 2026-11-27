import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';

export const r3Control=JSON.parse(fs.readFileSync(new URL('../../../src/runtime-control-0175-r3.json',import.meta.url)));
const archive=JSON.parse(gunzipSync(fs.readFileSync(new URL('./r3-control.json.gz',import.meta.url))));
export function seedR3Output(root) {
  for(const [relative,base64] of Object.entries(archive)) {
    const bytes=Buffer.from(base64,'base64');
    if(relative==='.pi-paseo-runtime.json')assert.deepEqual(JSON.parse(bytes),r3Control.receipt);
    else assert.equal(createHash('sha256').update(bytes).digest('hex'),r3Control.files[relative],relative);
    const file=path.join(root,relative);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,bytes);
  }
}
