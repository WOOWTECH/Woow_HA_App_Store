import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import config from './config.cjs';

const ids=Array.from({length:50},(_,i)=>'p'+String(i+1).padStart(2,'0'));
const actual=(await fs.readdir(path.join(config.root,'projects'))).filter(x=>/^p\d+$/.test(x)).sort();
assert.deepEqual(actual,ids,'exactly p01..p50 required; missing or extra IDs fail');
const runtime=await fs.readFile(path.join(config.root,'runtime.mjs'));
for(const id of ids) {
  const dir=path.join(config.root,'projects',id),st=await fs.lstat(dir);
  assert.ok(st.isDirectory()&&!st.isSymbolicLink(),'regular project directories required');
  for(const name of ['runtime.mjs','app.mjs','cases.json','test.mjs','README.txt','main.mjs','package.json','Containerfile']) {
    const stat=await fs.lstat(path.join(dir,name));
    assert.ok(stat.isFile()&&!stat.isSymbolicLink(),id+': regular source files required');
  }
  assert.deepEqual(await fs.readFile(path.join(dir,'runtime.mjs')),runtime,id+': runtime differs from top-level runtime');
}
console.log(JSON.stringify({ok:true,projects:50,identicalRuntimes:50,runtimeSha256:createHash('sha256').update(runtime).digest('hex')}));
