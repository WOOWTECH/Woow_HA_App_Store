// Exercise the shipped executable, including its retry loop and real manager.
// Only the native HTTP peer is a fixture; no daemon installation is requested.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';

const packageRoot=process.env.PASEO_PACKAGE_ROOT;
async function until(predicate, milliseconds=20000) {
  const deadline=Date.now()+milliseconds;
  while(Date.now()<deadline) { if(await predicate())return; await delay(50); }
  assert.fail('startup fixture did not settle');
}
test('packaged bridge survives late native bind and non-ready health before MCP CAS/restore', {timeout:30000}, async t=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'ha-paseo-startup-'));
  let child,exitPromise,healthRequests=0,earlyMcp=0,servers=[],healthy=false;
  const peer=http.createServer((req,res)=>{
    res.setHeader('Content-Type','application/json');
    if(req.url==='/api/health') {
      healthRequests++;healthy=healthRequests>=3;
      res.statusCode=healthy?200:503;res.end(JSON.stringify({ok:healthy}));return;
    }
    if(!healthy)earlyMcp++;
    if(req.url==='/api/mcp/servers'&&req.method==='GET'){res.end(JSON.stringify({servers}));return;}
    if(req.url==='/api/mcp/servers/woow-paseo'&&req.method==='PUT'){
      let text='';req.on('data',b=>text+=b);req.on('end',()=>{
        const {server,expected}=JSON.parse(text);assert.equal(expected,null);servers=[server];res.end(JSON.stringify({ok:true}));
      });return;
    }
    res.statusCode=404;res.end('{}');
  });
  t.after(async()=>{
    if(child&&child.exitCode===null){child.kill('SIGTERM');await Promise.race([exitPromise,delay(5000)]);if(child.exitCode===null)child.kill('SIGKILL');await exitPromise;}
    await new Promise(resolve=>peer.close(resolve));fs.rmSync(directory,{recursive:true,force:true});
  });
  await new Promise(resolve=>peer.listen(0,'127.0.0.1',resolve));
  const port=peer.address().port;await new Promise(resolve=>peer.close(resolve));
  const home=path.join(directory,'home'),data=path.join(directory,'data'),socket=path.join(directory,'bridge.sock');
  fs.mkdirSync(home);fs.mkdirSync(data);
  let stderr='';
  child=spawn(process.execPath,[path.join(packageRoot,'bin/serve.mjs')],{env:{PATH:process.env.PATH,HOME:home,
    OPENDESIGN_PASEO_TRANSPORT:'ha-ingress',OPENDESIGN_PASEO_SOCKET:socket,OPENDESIGN_PASEO_DATA_DIR:data,
    OPENDESIGN_PASEO_BUNDLED_PLUGIN:path.join(packageRoot,'launcher'),OPENDESIGN_PASEO_NATIVE_PORT:String(port),OPENDESIGN_PASEO_AUTO_ENABLE:'0'},stdio:['ignore','ignore','pipe']});
  child.stderr.on('data',b=>stderr+=b);
  exitPromise=new Promise(resolve=>child.once('exit',(code,signal)=>resolve({code,signal})));
  await until(()=>fs.existsSync(socket));
  await delay(1250);assert.equal(child.exitCode,null,'bridge exited before native bind');
  assert.equal(fs.existsSync(path.join(data,'paseo/host-mcp.json')),false,'MCP reconciliation started before native readiness');
  await new Promise(resolve=>peer.listen(port,'127.0.0.1',resolve));
  await until(()=>{
    try{return JSON.parse(fs.readFileSync(path.join(data,'paseo/bridge.json'))).operation?.status==='completed';}catch{return false;}
  });
  assert.ok(healthRequests>=3);assert.equal(earlyMcp,0);assert.equal(servers[0]?.id,'woow-paseo');
  assert.deepEqual(servers[0].args,[path.join(packageRoot,'bin/mcp.mjs')]);
  child.kill('SIGTERM');const exit=await exitPromise;assert.deepEqual(exit,{code:0,signal:null},stderr);
});
