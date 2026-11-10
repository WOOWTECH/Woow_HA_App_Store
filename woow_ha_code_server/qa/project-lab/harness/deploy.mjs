// Manual foreground preview. Ctrl+C stops only this process's server.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import config from './config.cjs';
import {snapshot} from './snapshot.mjs';

const port=Number(process.env.PORT??18750),host=process.env.BIND||'127.0.0.1';
if(!Number.isInteger(port)||port<0||port>65535)throw Error('PORT must be 0..65535');
const output=config.makeRun('preview'),root=path.join(output,'preview');
await snapshot(config.root,root,{runtime:config.runtime,packages:process.env.QA_PACKAGES?config.packageRoot():undefined});
const {start}=await import(pathToFileURL(path.join(root,'runtime.mjs')).href);
const server=await start({root,host,port});
const receipt={ready:true,host,port:server.address().port,output,foreground:true};
await fs.writeFile(path.join(root,'evidence','preview.json'),JSON.stringify(receipt,null,2));
console.log(JSON.stringify(receipt));
let stopping=false;
const stop=()=>{
  if(stopping)return;
  stopping=true;
  server.closeAllConnections();
  server.close(()=>{process.exitCode=0;});
};
process.once('SIGINT',stop);process.once('SIGTERM',stop);
