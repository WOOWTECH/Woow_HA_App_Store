// Real nginx -> private Unix HTTP bridge fixture. No cluster/HA mutations.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import http from 'node:http';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
const root=path.resolve(import.meta.dirname,'..');
const packageRoot=process.env.PASEO_PACKAGE_ROOT;
assert.ok(packageRoot,'set PASEO_PACKAGE_ROOT to the verified, dependency-installed runtime');
const {createStandaloneApp}=await import(pathToFileURL(path.join(packageRoot,'host/standalone.mjs')));
const prefix='/api/hassio_ingress/'+'a'.repeat(32);
const origin='https://ha.example.test';
const headers={Host:'ha.example.test','X-Ingress-Path':prefix,'X-Remote-User-Id':'b'.repeat(32)};
const postHeaders={...headers,Origin:origin,Referer:origin+prefix+'/paseo/setup/','Sec-Fetch-Site':'same-origin','Content-Type':'application/json'};

test('nginx enforces actual Supervisor peer, sanitized context, routes, origins and persistent stop',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ha-paseo-nginx-'));
 fs.mkdirSync(path.join(dir,'nginx'),{recursive:true});
 for(const name of ['client','proxy','fastcgi','uwsgi','scgi'])fs.mkdirSync(path.join(dir,'nginx',name));
 const calls=[];const state=path.join(dir,'desired.json');
 const desired=()=>fs.existsSync(state)&&JSON.parse(fs.readFileSync(state)).desired;
 const manager={status:async()=>({phase:desired()?'running':'disabled',desiredEnabled:desired()}),
  enable:async()=>{calls.push('enable');fs.writeFileSync(state,JSON.stringify({desired:true}));},
  disable:async()=>{calls.push('disable');fs.writeFileSync(state,JSON.stringify({desired:false}));},
  restore:async()=>{calls.push('restore');},shutdown:async()=>{},cancelPending(){},cancelQueuedOperations(){}};
 const config={haIngress:true,dataDir:dir,home:dir,packageRoot,bundledPlugin:path.join(packageRoot,'launcher'),nativePort:7456,autoEnableOnStart:true};
 let runtime,server;
 const start=async()=>{
  runtime=createStandaloneApp(config,{manager,nativeRequest:async()=>({servers:[]})});
  server=runtime.app.listen(path.join(dir,'bridge.sock'));await new Promise(r=>server.once('listening',r));await runtime.bridge.start();
 };
 const stop=async()=>{await runtime.bridge.shutdown();server.closeAllConnections();await new Promise(r=>server.close(r));};
 await start();
 const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 // Only fixture peer/port/filesystem values differ from the shipped nginx config.
 const proxy=fs.readFileSync(path.join(root,'rootfs/etc/nginx/paseo-proxy.conf'),'utf8')
  .replace('allow 172.30.32.2;','allow 127.0.0.1;')
  .replace('X-OD-HA-Peer $remote_addr;','X-OD-HA-Peer 172.30.32.2;')
  .replace('/run/ha-opendesign-paseo/bridge.sock',path.join(dir,'bridge.sock'));
 fs.writeFileSync(path.join(dir,'paseo-proxy.conf'),proxy);
 const returnConfig=path.join(dir,'back-link.conf');
 fs.writeFileSync(returnConfig,'set $ha_return_path "/app/a1234def_woow_ha_opendesign";\nset $ha_return_label "← 返回 OpenDesign";\n');
 const setupConfig=fs.readFileSync(path.join(root,'rootfs/etc/nginx/paseo-setup.conf'),'utf8')
  .replace('/etc/nginx/paseo-proxy.conf',path.join(dir,'paseo-proxy.conf'))
  .replace('/run/ha-opendesign-return/back-link.conf',returnConfig);
 fs.writeFileSync(path.join(dir,'paseo-setup.conf'),setupConfig);
 const nginxConfig=fs.readFileSync(path.join(root,'rootfs/etc/nginx/nginx.conf'),'utf8')
  .replace('listen 8099 default_server;',`listen 127.0.0.1:${port} default_server;`)
  .replaceAll('/tmp/ha-opendesign-nginx',path.join(dir,'nginx'))
  .replace('/etc/nginx/mime.types',process.env.NGINX_MIME_TYPES||'/etc/nginx/mime.types')
  .replaceAll('/etc/nginx/paseo-proxy.conf',path.join(dir,'paseo-proxy.conf'))
  .replaceAll('/etc/nginx/paseo-setup.conf',path.join(dir,'paseo-setup.conf'));
 fs.writeFileSync(path.join(dir,'nginx.conf'),nginxConfig);
 const nginx=spawn(process.env.NGINX_BIN||'nginx',['-p',dir+'/', '-e','stderr','-c',path.join(dir,'nginx.conf')],{stdio:['ignore','ignore','pipe']});
 let log='';nginx.stderr.on('data',b=>log+=b);
 const send=(route,h=headers,body,localAddress='127.0.0.1')=>new Promise((resolve,reject)=>{
  const request=http.request({host:'127.0.0.1',port,localAddress,path:route,method:body?'POST':'GET',headers:{...h,...(body?{'Content-Length':Buffer.byteLength(body)}:{})}},res=>{let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,text,headers:res.headers}));});request.on('error',reject);request.end(body);
 });
 t.after(async()=>{
  nginx.kill('SIGTERM');if(nginx.exitCode===null)await new Promise(r=>nginx.once('exit',r));
  await stop();fs.rmSync(dir,{recursive:true,force:true});
 });
 for(let n=0;;n++){
  try{await send('/paseo/setup/');break;}catch(error){if(n>100||nginx.exitCode!==null)throw Error(log||error.message);await new Promise(r=>setTimeout(r,20));}
 }
 const setup=await send('/paseo/setup/');assert.equal(setup.status,200,setup.text);
 assert.ok(setup.text.includes(`src="${prefix}/paseo/assets/setup.js"`));
 assert.ok(setup.text.includes('<a href="/app/a1234def_woow_ha_opendesign" class="back-link">← 返回 OpenDesign</a>'));
 assert.ok(!setup.text.includes('← 返回外掛'));
 assert.equal(setup.headers['referrer-policy'],'same-origin');assert.match(setup.headers['cache-control'],/no-store/);
 assert.match(setup.headers['content-security-policy'],/frame-ancestors 'none'/);
 assert.equal((await send('/paseo/assets/setup.js')).text,fs.readFileSync(path.join(packageRoot,'ui/setup.js'),'utf8'));
 // A different repository prefix and missing metadata affect only the anchor,
 // not runtime bytes, CSP, assets or authenticated status/API behavior.
 for(const [target,label] of [['/app/local_woow_ha_opendesign','← 返回 OpenDesign'],['/','← 返回 Home Assistant']]){
  fs.writeFileSync(returnConfig,`set $ha_return_path "${target}";\nset $ha_return_label "${label}";\n`);
  nginx.kill('SIGHUP');
  const anchor=`<a href="${target}" class="back-link">${label}</a>`;
  for(let n=0;;n++){
   const page=await send('/paseo/setup');
   if(page.text.includes(anchor)){assert.equal(page.status,200);break;}
   assert.ok(n<100,'nginx did not apply the native return/fallback anchor');
   await new Promise(r=>setTimeout(r,20));
  }
 }
 for(const route of ['/paseo/assets/setup.js','/paseo/assets/setup.css','/api/paseo-bridge'])assert.equal((await send(route)).status,200,route);
 // A sibling container cannot forge the Supervisor peer or authenticated user.
 for(const route of ['/paseo/setup/','/api/paseo-bridge'])assert.equal((await send(route,{...postHeaders,'X-OD-HA-Peer':'172.30.32.2','X-Forwarded-For':'172.30.32.2'},undefined,'127.0.0.2')).status,403);
 for(const h of [
  {'X-Remote-User-Id':''},{'X-Ingress-Path':prefix+'/../evil'},{'X-Ingress-Path':'//evil.test'},
  {Origin:'https://evil.test','X-Forwarded-Host':'evil.test','X-Forwarded-Proto':'https'},
  {Origin:'null'},{Referer:origin+prefix+'wrong/paseo/setup/'},{'Sec-Fetch-Site':'cross-site'},
 ])assert.equal((await send('/api/paseo-bridge',{...postHeaders,...h},'{"action":"enable"}')).status,403,JSON.stringify(h));
 assert.deepEqual(calls,['enable']);
 // Valid request ignores forged forwarding rather than using it as origin authority.
 assert.equal((await send('/api/paseo-bridge',{...postHeaders,'X-Forwarded-Host':'evil.test',Forwarded:'host=evil.test'},'{"action":"status"}')).status,200);
 for(const route of ['/api/paseo-bridge/extra','/paseo/assets/%2e%2e%2fpackage.json','/paseo/%73etup'])assert.equal((await send(route)).status,403,route);
 assert.equal((await send('/api/paseo-bridge',postHeaders,'{"action":"disable"}')).status,202);
 for(let n=0;n<100&&desired();n++)await new Promise(r=>setTimeout(r,5));assert.equal(desired(),false);
 await stop();await start();
 assert.equal(calls.filter(x=>x==='enable').length,1);assert.ok(calls.includes('restore'));
 assert.equal(JSON.parse((await send('/api/paseo-bridge')).text).desiredEnabled,false);
});
