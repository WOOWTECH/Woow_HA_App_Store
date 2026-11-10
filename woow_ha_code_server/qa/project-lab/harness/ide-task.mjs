import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import config from './config.cjs';

const nonce=process.argv[2];
if(!/^[a-f0-9]{32}$/.test(nonce||''))throw Error('Supply a fresh 32-character hexadecimal nonce');
const output=config.makeRun('ide-terminal');
const runner=spawnSync(process.execPath,[fileURLToPath(new URL('./test-all.mjs',import.meta.url))],{
  cwd:config.root,env:{...process.env,QA_ROOT:config.root},encoding:'utf8',timeout:180000,killSignal:'SIGKILL',maxBuffer:4*1024*1024
});
let summary;
try{summary=JSON.parse((runner.stdout||'').trim().split('\n').at(-1))}catch{}
const ok=!runner.error&&runner.status===0&&summary?.passed===true&&summary?.projects===50&&summary?.projectTestRunners===50;
const receipt={nonce,ok,exitCode:runner.status,projects:summary?.projects,cases:summary?.cases,projectTestRunners:summary?.projectTestRunners};
// Exclusive creation: no overwritten user file or stale receipt can satisfy the UI check.
fs.writeFileSync(path.join(output,'receipt.json'),JSON.stringify(receipt,null,2),{flag:'wx'});
console.log(JSON.stringify({output,...receipt}));
process.exitCode=ok?0:1;
