// Run during image build against the actual pi-web SDK and OAuth provider.
// Stops at the authorization URL; never exchanges a code or logs in an account.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {patch} from '../patch-chatgpt-device-id.mjs';

const piWebRoot=process.env.PI_WEB_ROOT;
if(!piWebRoot) throw Error('PI_WEB_ROOT must point at the installed pi-web package');
const nodeModules=process.env.PI_NODE_MODULES||path.join(piWebRoot,'node_modules');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'pi-device-id-'));
try {
 const module=path.join(dir,'identity.mjs');
 const source=patch('await d.login(c,"oauth",{signal:j.signal}),(0,f.kn)()');
 fs.writeFileSync(module,source.slice(0,source.indexOf('\n'))+'\nconsole.log(await __piChatGPTDeviceId());');
 fs.symlinkSync(nodeModules,path.join(dir,'node_modules'),'dir');
 const env={...process.env,PI_CODING_AGENT_DIR:path.join(dir,'agent')};
 const run=()=>{const r=spawnSync(process.execPath,[module],{env,encoding:'utf8'});if(r.status!==0)throw Error(r.stderr);return r.stdout.trim();};
 const a=run(),b=run();
 if(a!==b||!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(a)) throw Error('device identity must be a durable UUID');
 console.log('PASS: the real SDK persists one installation UUID across process restarts');

 const provider=path.join(nodeModules,'@earendil-works/pi-ai/dist/auth/oauth/openai-chatgpt.js');
 const {openaiChatGPTOAuth}=await import(pathToFileURL(provider).href);
 const missingController=new AbortController();let missing=false;
 try { await openaiChatGPTOAuth.login({signal:missingController.signal,notify(){},prompt:async()=>''}); }
 catch(e) { missing=e.message.includes('requires a device ID'); }
 if(!missing) throw Error('expected original missing-device error');
 const controller=new AbortController(),id='12345678-1234-4234-8234-123456789abc';let authorization=false;
 try {
  await openaiChatGPTOAuth.login({signal:controller.signal,notify(event){
   if(event.type==='auth_url') { const url=new URL(event.url); authorization=url.searchParams.get('ext_agent_host_id')==='urn:uuid:'+id; controller.abort(); }
  },prompt:async()=>{throw Error('test stops before account approval');}},{getDeviceId:()=>id});
 } catch {}
 if(!authorization) throw Error('actual OAuth provider did not reach authorization with the supplied UUID');
 console.log('PASS: actual OAuth fails without callback and reaches authorization with callback');
} finally { fs.rmSync(dir,{recursive:true,force:true}); }
