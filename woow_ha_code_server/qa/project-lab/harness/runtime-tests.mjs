import config from './config.cjs';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import {setTimeout as delay} from 'node:timers/promises';
import {fileURLToPath} from 'node:url';
import {pathToFileURL} from 'node:url';
const {start}=await import(pathToFileURL(config.runtime).href);

const {root,makeRun,packageRoot}=config;
const output=makeRun('runtime-tests');
const server=await start({root,port:0,host:'127.0.0.1'}),base='http://127.0.0.1:'+server.address().port,rows=[];
const observed=new Map();
// Observe actual IncomingMessage data events without starting its flow early.
server.prependListener('request',req=>{
  const tag=req.headers['x-utf8-probe'];
  if(!tag)return;
  const chunks=[];observed.set(tag,chunks);
  const emit=req.emit;
  req.emit=function(event,...args){if(event==='data')chunks.push(Buffer.from(args[0]));return Reflect.apply(emit,this,[event,...args])};
});
async function splitRequest(body,cut,tag){
  let request;
  const response=new Promise((resolve,reject)=>{
    request=http.request(base+'/api/projects/p31/run',{method:'POST',headers:{'content-type':'application/json','x-utf8-probe':tag,'transfer-encoding':'chunked'},agent:false},res=>{
      const chunks=[];res.on('data',b=>chunks.push(b));res.on('error',reject);res.on('end',()=>{try{resolve({status:res.statusCode,body:JSON.parse(Buffer.concat(chunks).toString('utf8'))})}catch(e){reject(e)}});
    });
    request.on('error',reject);request.setTimeout(5000,()=>request.destroy(Error('UTF-8 request timeout')));
  });
  // Prevent an unhandled rejection while awaiting the first server-side chunk.
  response.catch(()=>{});
  try{
    request.setNoDelay(true);request.flushHeaders();request.write(body.subarray(0,cut));
    const deadline=Date.now()+3000;
    while((observed.get(tag)||[]).reduce((n,b)=>n+b.length,0)<cut){
      if(Date.now()>deadline)throw Error('First HTTP chunk was not observed');
      await delay(5);
    }
    request.end(body.subarray(cut));
    const result=await response;
    const chunks=observed.get(tag);
    assert.ok(chunks.length>=2,'must receive separate real HTTP data chunks');
    assert.equal(chunks[0].length,cut,'first HTTP chunk must end at the requested split');
    assert.deepEqual(Buffer.concat(chunks),body,'server must receive exact original bytes');
    return {...result,chunkLengths:chunks.map(b=>b.length)};
  }finally{request.destroy()}
}
let error;
try{
  for(const [name,resource,options,status] of [
    ['unknown route','/etc/passwd',{},404],['unknown project','/api/projects/p99/run',{method:'POST',headers:{'content-type':'application/json'},body:'{}'},404],
    ['wrong content type','/api/projects/p01/run',{method:'POST',body:'{}'},415],['invalid JSON','/api/projects/p01/run',{method:'POST',headers:{'content-type':'application/json'},body:'bad'},400],
    ['null input','/api/projects/p01/run',{method:'POST',headers:{'content-type':'application/json'},body:'null'},400],['large input','/api/projects/p01/run',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({value:'x'.repeat(140000)})},413],
    ['unexpected download','/downloads/private.json',{},404],['unexpected HTTP method','/api/catalog',{method:'DELETE'},404]
  ]){
    const response=await fetch(base+resource,{...options,signal:AbortSignal.timeout(10000)});
    assert.equal(response.status,status,name);await response.arrayBuffer();rows.push({name,status,ok:true});
  }
  const catalog=await(await fetch(base+'/api/catalog',{signal:AbortSignal.timeout(10000)})).json();
  assert.deepEqual(catalog.projects.map(p=>p.id).sort(),Array.from({length:50},(_,i)=>'p'+String(i+1).padStart(2,'0')));
  rows.push({name:'exactly fifty applications',ok:true});
  const answer='東京🙂';
  const input={cards:[{id:'city',prompt:'Repeat the text',answers:[answer]}],responses:{city:answer}};
  const body=Buffer.from(JSON.stringify(input)),startByte=body.lastIndexOf(Buffer.from(answer));
  for(let offset=1;offset<Buffer.byteLength(answer);offset++){
    const result=await splitRequest(body,startByte+offset,'split-'+offset);
    assert.equal(result.status,200);assert.equal(result.body.result.correct,1);assert.equal(result.body.result.results[0].response,answer);
    rows.push({name:'UTF-8 actual HTTP byte split '+offset,status:result.status,chunkLengths:result.chunkLengths,ok:true});
  }
  const oversized=JSON.stringify({text:'東'.repeat(44000)});
  assert.ok(oversized.length<131072&&Buffer.byteLength(oversized)>131072);
  const response=await fetch(base+'/api/projects/p35/run',{method:'POST',headers:{'content-type':'application/json'},body:oversized,signal:AbortSignal.timeout(10000)});
  assert.equal(response.status,413);await response.arrayBuffer();rows.push({name:'UTF-8 size limit counts bytes, not characters',status:413,ok:true});
}catch(e){error=e.stack||e.message;process.exitCode=1}
finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve))}

await fs.writeFile(output+'/runtime-tests.json',JSON.stringify({at:new Date().toISOString(),ok:!error,rows,error},null,2));
console.log(JSON.stringify({output,ok:!error,checks:rows.length,error}));
