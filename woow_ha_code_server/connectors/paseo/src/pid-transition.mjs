// Copied byte-for-byte beside BOTH official pid-lock.js modules. All supported
// writers and plugin recovery lock this persistent inode; never unlink it.
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';
export const PID_TRANSITION_PROTOCOL='linux-flock-v1';
function failure(code){throw Object.assign(new Error(code),{code});}
function safePath(file){for(let p=path.resolve(file);;p=path.dirname(p)){try{if(fs.lstatSync(p).isSymbolicLink())failure('UNSAFE_SYMLINK');}catch(e){if(e.code!=='ENOENT')throw e;}if(p===path.dirname(p))break;}}
export async function withPidTransition(home,fn,{timeoutMs=10000,create=false}={}) {
 if(process.platform!=='linux')return fn(); // no automatic recovery/proof off Linux
 safePath(home);
 if(create)fs.mkdirSync(home,{recursive:true,mode:0o700});
 let directory;try{directory=fs.lstatSync(home);}catch(e){if(e.code==='ENOENT'&&!create)return fn();throw e;}
 if(!directory.isDirectory()||directory.uid!==process.getuid()||(directory.mode&0o777)!==0o700)failure('DAEMON_IDENTITY_UNSAFE');
 const file=path.join(home,'.pi-paseo-pid-transition.guard');safePath(file);
 const fd=fs.openSync(file,fs.constants.O_RDWR|fs.constants.O_CREAT|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK,0o600);
 try {
  const stat=fs.fstatSync(fd),current=fs.lstatSync(file);
  if(!stat.isFile()||stat.uid!==process.getuid()||stat.nlink!==1||(stat.mode&0o077)||stat.ino!==current.ino||stat.dev!==current.dev)failure('DAEMON_IDENTITY_UNSAFE');
  const deadline=Date.now()+timeoutMs;
  while(true){
   const lock=spawnSync('flock',['--exclusive','--nonblock','--conflict-exit-code','73','3'],{stdio:['ignore','ignore','ignore',fd],env:{PATH:process.env.PATH||'/usr/bin:/bin',LC_ALL:'C'},timeout:1000});
   if(lock.error||![0,73].includes(lock.status))failure('DAEMON_TRANSITION_FAILED');
   if(lock.status===0)break;
   if(Date.now()>=deadline)failure('DAEMON_TRANSITION_BUSY');
   await delay(10);
  }
  safePath(file);const held=fs.lstatSync(file);
  if(held.ino!==stat.ino||held.dev!==stat.dev||held.nlink!==1)failure('DAEMON_STATE_CHANGED');
  return await fn();
 }finally{fs.closeSync(fd);}
}
