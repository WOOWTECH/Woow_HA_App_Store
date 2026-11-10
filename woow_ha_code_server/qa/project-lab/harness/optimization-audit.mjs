import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import config from './config.cjs';

const output=config.makeRun('optimization');
const {start}=await import(pathToFileURL(config.runtime).href);
const server=await start({root:config.root,port:0,host:'127.0.0.1'});
const original=fs.stat;
const files=[];
let error;
try {
  // Start-up legitimately builds the catalog. Count only this real HTTP request.
  fs.stat=async (...args)=>{
    if(path.basename(String(args[0]))==='app.mjs') files.push(path.resolve(String(args[0])));
    return original(...args);
  };
  const response=await fetch(`http://127.0.0.1:${server.address().port}/api/projects/p33/run`,{
    method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({value:2,from:'kWh',to:'J'}),signal:AbortSignal.timeout(10000)
  });
  assert.equal(response.status,200);
  assert.equal((await response.json()).result.result,7200000);
  assert.deepEqual(files,[path.join(config.root,'projects/p33/app.mjs')],
    'One run request must stat exactly its requested application once');
} catch(e) {error=e.message;process.exitCode=1;}
finally {
  fs.stat=original;
  server.closeAllConnections();
  await new Promise(resolve=>server.close(resolve));
}
const report={ok:!error,requestCount:1,appStatCalls:files.length,error};
await fs.writeFile(path.join(output,'optimization.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({output,...report}));
