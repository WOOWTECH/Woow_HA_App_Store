import config from './config.cjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import assert from 'node:assert/strict';

const {root,makeRun,packageRoot}=config;
const output=process.argv[2]==='--project'?null:makeRun('test-all');
const ids=Array.from({length:50},(_,i)=>'p'+String(i+1).padStart(2,'0'));
const marker='WOOW_PROJECT_TEST_RESULT ';

async function inspectProject(id){
  const row={id,passed:0,failed:0,tests:[],runner:null};
  const directory=path.join(root,'projects',id);
  try{
    const {meta,run}=await import(pathToFileURL(path.join(directory,'app.mjs')).href);
    assert.equal(meta.id,id);
    assert.equal(typeof run,'function');
    assert.ok(meta.example&&typeof meta.example==='object'&&!Array.isArray(meta.example),'object example required');
    const cases=JSON.parse(await fs.readFile(path.join(directory,'cases.json'),'utf8'));
    assert.ok(Array.isArray(cases)&&cases.length>=4,'at least four fixtures required');
    assert.ok(cases.every(c=>c&&typeof c==='object'&&!Array.isArray(c)),'fixture objects required');
    assert.ok(cases.filter(c=>c.error!==true&&Object.hasOwn(c,'expected')).length>=2,'at least two known-success fixtures required');
    assert.ok(cases.some(c=>c.error===true),'at least one explicit rejection required');
    for(const c of cases){
      try{
        assert.ok(Object.hasOwn(c,'input'),'fixture input is required');
        assert.ok(c.error===undefined||typeof c.error==='boolean','fixture error must be boolean');
        if(c.error===true){
          assert.throws(()=>run(c.input),e=>e instanceof Error&&e.message.trim().length>0&&(!c.errorMessage||e.message.includes(c.errorMessage))&&(!c.errorPattern||new RegExp(c.errorPattern,'i').test(e.message)));
        }else{
          assert.ok(Object.hasOwn(c,'expected'),'success fixture requires expected output');
          const actual=run(c.input);
          assert.deepEqual(actual,c.expected);
          assert.deepEqual(JSON.parse(JSON.stringify(actual)),actual,'result must be JSON serializable');
        }
        row.passed++;row.tests.push({name:c.name,ok:true});
      }catch(e){row.failed++;row.tests.push({name:c.name,ok:false,error:e.message});}
    }
  }catch(e){row.failed++;row.tests.push({name:'contract',ok:false,error:e.message});}
  const runner=spawnSync(process.execPath,['test.mjs'],{cwd:directory,encoding:'utf8',timeout:10000,killSignal:'SIGKILL',maxBuffer:2*1024*1024});
  row.runner={command:'node test.mjs',exitCode:runner.status,signal:runner.signal,error:runner.error?.message,stdout:(runner.stdout||'').slice(-2000),stderr:(runner.stderr||'').slice(-2000)};
  if(runner.status!==0||runner.error){row.failed++;row.tests.push({name:'project test.mjs runner',ok:false,error:runner.error?.message||`exit=${runner.status}, signal=${runner.signal}`});}
  return row;
}

if(process.argv[2]==='--project'){
  const id=process.argv[3];
  assert.ok(ids.includes(id),'unknown project ID');
  const row=await inspectProject(id);
  console.log(marker+JSON.stringify(row));
  if(row.failed)process.exitCode=1;
}else{
  const rows=[];let contractError;
  try{
    const actual=(await fs.readdir(path.join(root,'projects'))).filter(x=>/^p\d{2}$/.test(x)).sort();
    assert.deepEqual(actual,ids,'must contain exactly p01 through p50');
    for(const id of ids){
      // The entire fixture evaluator is bounded too, including module loading/run().
      const child=spawnSync(process.execPath,[fileURLToPath(import.meta.url),'--project',id],{cwd:root,env:{...process.env,QA_ROOT:root},encoding:'utf8',timeout:20000,killSignal:'SIGKILL',maxBuffer:4*1024*1024});
      const line=(child.stdout||'').split('\n').findLast(x=>x.startsWith(marker));
      if(line&&!child.error){
        const row=JSON.parse(line.slice(marker.length));
        if(child.status!==0&&row.failed===0){row.failed++;row.tests.push({name:'isolated worker',ok:false,error:`exit=${child.status}`});}
        rows.push(row);
      }else rows.push({id,passed:0,failed:1,tests:[{name:'isolated worker',ok:false,error:child.error?.message||(child.stderr||'').slice(-2000)||`exit=${child.status}`}],runner:null});
    }
  }catch(e){contractError=e.message;}
  const report={at:new Date().toISOString(),projects:rows.length,cases:rows.reduce((n,r)=>n+r.tests.filter(t=>!['contract','project test.mjs runner','isolated worker'].includes(t.name)).length,0),projectTestRunners:rows.filter(r=>r.runner?.exitCode===0&&!r.runner.error).length,passed:!contractError&&rows.length===50&&rows.every(r=>r.failed===0),contractError,rows};

  await fs.writeFile(path.join(output,'unit-tests.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({output,projects:report.projects,cases:report.cases,projectTestRunners:report.projectTestRunners,passed:report.passed,contractError,failures:rows.filter(r=>r.failed)}));
  if(!report.passed)process.exitCode=1;
}
