import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const repo=process.cwd();
const helper=process.env.SHARED_DISTRIBUTION_HELPER || path.join(repo,process.env.NATIVE_DISTRIBUTION==='1'?'rootfs/bin/pi-agent-share-state.mjs':'rootfs/usr/local/bin/pi-agent-share-state.mjs');
const bundle=process.env.SHARED_RUNTIME_TEST_BUNDLE;
assert.ok(bundle,'SHARED_RUNTIME_TEST_BUNDLE points to the unpacked verified package with installed dependencies');
for(const choice of ['fresh','disabled','removed'])test(`${choice} package choice through shipped distribution helper`,t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'dist-launch-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const data=path.join(root,'data'),home=path.join(root,'real-home');fs.mkdirSync(data,{recursive:true});fs.mkdirSync(home);
 const write=(p,v)=>{fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,JSON.stringify(v));};
 write(path.join(data,'mcp.json'),{mcpServers:{}});
 write(path.join(home,'.claude.json'),{oauthAccount:{id:'keep'},mcpServers:{user:{command:'fixture'}}});
 if(choice==='disabled')write(path.join(data,'settings.json'),{packages:[{source:bundle,extensions:[]}]});
 if(choice==='removed'){write(path.join(data,'settings.json'),{packages:['user']});write(path.join(data,'shared-runtime/distribution-seed.json'),{schema:1});}
 const env={...process.env,HOME:home,PI_AGENT_HOME:path.join(root,'install'),PI_AGENT_DATA_DIR:data,PI_CODING_AGENT_DIR:data,PI_SHARED_DATA_DIR:data,PI_SHARED_HOME:home,PI_SHARED_RUNTIME_BUNDLE_DIR:bundle};
 const result=spawnSync(process.execPath,[helper],{env,cwd:home,encoding:'utf8',timeout:30000});
 assert.equal(result.status,0,result.stderr);
 const settings=JSON.parse(fs.readFileSync(path.join(data,'settings.json'),'utf8'));
 const memory=JSON.parse(fs.readFileSync(path.join(data,'mcp.json'),'utf8')).mcpServers.pi_shared_memory;
 if(choice==='fresh'){assert.ok(settings.packages.includes(bundle));assert.equal(memory.env.PI_SHARED_DATA_DIR,data);assert.equal(memory.env.PI_SHARED_HOME,home);}
 else {assert.equal(memory,undefined);assert.match(result.stdout,new RegExp(choice));}
 assert.equal(JSON.parse(fs.readFileSync(path.join(home,'.claude.json'),'utf8')).oauthAccount.id,'keep');
});
