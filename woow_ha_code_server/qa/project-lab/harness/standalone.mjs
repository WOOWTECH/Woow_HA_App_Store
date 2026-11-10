import config from './config.cjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {spawn,spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';

const {root,makeRun,packageRoot}=config;
const output=makeRun('standalone');
const ids=Array.from({length:50},(_,i)=>'p'+String(i+1).padStart(2,'0'));
const rows=[];
const scratch=await fs.mkdtemp(path.join(output,'extracted-'));
const extractScript=String.raw`
import hashlib,io,json,pathlib,stat,sys,zipfile
archive,dest,pid,expected,file_hashes=sys.argv[1:]
file_hashes=json.loads(file_hashes)
data=pathlib.Path(archive).read_bytes()
assert hashlib.sha256(data).hexdigest()==expected,'archive hash changed before extraction'
required={'app.mjs','cases.json','test.mjs','README.txt','runtime.mjs','main.mjs','package.json','Containerfile'}
with zipfile.ZipFile(io.BytesIO(data)) as z:
    names=z.namelist()
    assert len(names)<=64 and sum(e.file_size for e in z.infolist())<=16*1024*1024,'ZIP expansion limit'
    assert len(data)<=16*1024*1024,'ZIP input limit'
    assert len(names)==len(set(names)),'duplicate ZIP members'
    assert {pid+'/'+f for f in required}<=set(names),'missing required standalone files'
    for entry in z.infolist():
        p=pathlib.PurePosixPath(entry.filename)
        assert len(p.parts)==2 and p.parts[0]==pid and p.parts[1] not in {'.','..'},'unsafe ZIP member path'
        assert not p.is_absolute() and '\\' not in entry.filename,'unsafe ZIP member path'
        assert not entry.is_dir() and stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG),'nonregular ZIP member'
        assert entry.filename==pid+'/'+p.parts[1],'noncanonical ZIP member'
        assert p.parts[1] in required,'unexpected ZIP member'
        body=z.read(entry)
        assert hashlib.sha256(body).hexdigest()==file_hashes[p.parts[1]],'member hash mismatch'
        target=pathlib.Path(dest).joinpath(*p.parts)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(body)
    print(json.dumps({'members':len(names),'sha256':expected}))
`;

async function stop(child){
  if(!child||child.exitCode!==null||child.signalCode!==null)return;
  await new Promise(resolve=>{
    const timer=setTimeout(()=>child.kill('SIGKILL'),2000);
    child.once('exit',()=>{clearTimeout(timer);resolve()});
    child.kill('SIGTERM');
  });
}
function startProject(directory){
  const child=spawn(process.execPath,[path.join(directory,'main.mjs')],{cwd:directory,env:{...process.env,PORT:'0',BIND:'127.0.0.1'},stdio:['ignore','pipe','pipe']});
  let stderr='';child.stderr.on('data',b=>{stderr=(stderr+b).slice(-2000)});
  const ready=new Promise((resolve,reject)=>{
    let data='';
    const timer=setTimeout(()=>{cleanup();reject(Error('Startup timeout'))},10000);
    const onError=error=>{cleanup();reject(error)};
    const onExit=code=>{cleanup();reject(Error(`Exited ${code}: ${stderr}`))};
    const onData=b=>{
      data+=b;
      if(data.length>65536){cleanup();reject(Error('Excessive startup output'));return;}
      if(data.includes('\n')){cleanup();try{const info=JSON.parse(data.split('\n')[0]);assert.equal(info.ready,true);assert.ok(Number.isInteger(info.port)&&info.port>0&&info.port<=65535);assert.equal(info.projects,1);resolve(info)}catch(e){reject(e)}}
    };
    function cleanup(){clearTimeout(timer);child.off('error',onError);child.off('exit',onExit);child.stdout.off('data',onData)}
    child.once('error',onError);child.once('exit',onExit);child.stdout.on('data',onData);
  });
  return {child,ready};
}
let contractError;
try{
  const manifest=JSON.parse(await fs.readFile(path.join(packageRoot(),'evidence/package-manifest.json'),'utf8'));
  assert.deepEqual(manifest.map(p=>p.id).sort(),ids,'manifest must contain exactly p01 through p50 once');
  for(const id of ids){
    const row={id,ok:false};rows.push(row);let child;
    try{
      const archive=path.join(packageRoot(),'downloads',id+'.zip');
      const data=await fs.readFile(archive);
      const sha256=createHash('sha256').update(data).digest('hex');
      const pkg=manifest.find(p=>p.id===id);
      assert.equal(sha256,pkg.sha256,'download SHA-256 does not match manifest');
      for(const name of ['app.mjs','cases.json','test.mjs','runtime.mjs']){
        const source=await fs.readFile(name==='runtime.mjs'?path.join(root,name):path.join(root,'projects',id,name));
        assert.equal(pkg.files[name],createHash('sha256').update(source).digest('hex'),id+': packaged '+name+' differs from source');
      }
      row.artifact={file:'downloads/'+id+'.zip',sha256,bytes:data.length};
      const destination=path.join(scratch,id);
      const extraction=spawnSync('python3',['-B','-c',extractScript,archive,destination,id,sha256,JSON.stringify(pkg.files)],{encoding:'utf8',timeout:10000,killSignal:'SIGKILL',maxBuffer:1024*1024});
      assert.equal(extraction.status,0,extraction.error?.message||extraction.stderr);
      row.extraction=JSON.parse(extraction.stdout);
      const project=path.join(destination,id);
      const runner=spawnSync(process.execPath,['test.mjs'],{cwd:project,encoding:'utf8',timeout:10000,killSignal:'SIGKILL',maxBuffer:2*1024*1024});
      row.testRunner={command:'node test.mjs',exitCode:runner.status,signal:runner.signal,stdout:(runner.stdout||'').slice(-2000),stderr:(runner.stderr||'').slice(-2000)};
      assert.equal(runner.status,0,runner.error?.message||runner.stderr||'extracted test.mjs failed');
      const cases=JSON.parse(await fs.readFile(path.join(project,'cases.json'),'utf8'));
      const valid=cases.filter(c=>c.error!==true&&Object.hasOwn(c,'expected')).slice(0,2),bad=cases.find(c=>c.error===true);
      assert.equal(valid.length,2);assert.ok(bad);
      const started=startProject(project);child=started.child;
      const info=await started.ready;
      row.port=info.port;
      const base='http://127.0.0.1:'+info.port;
      const request=(resource,options={})=>fetch(base+resource,{...options,signal:AbortSignal.timeout(10000)});
      const health=await request('/healthz');assert.equal(health.status,200);assert.equal((await health.json()).projects,1);
      for(const c of valid){
        const response=await request('/api/projects/'+id+'/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c.input)});
        assert.equal(response.status,200,c.name);assert.deepEqual((await response.json()).result,c.expected,c.name);
      }
      const invalid=await request('/api/projects/'+id+'/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(bad.input)});
      assert.equal(invalid.status,400);assert.ok((await invalid.json()).error?.trim());
      assert.equal((await request('/etc/passwd')).status,404);
      row.fixtureCount=cases.length;row.httpPositiveCases=valid.length;row.httpValidationStatus=400;row.ok=true;
    }catch(e){row.error=e.message.slice(0,3000)}finally{await stop(child)}
    if(Number(id.slice(1))%10===0)console.log(JSON.stringify({phase:'extracted-ZIPs',completed:rows.length,failed:rows.filter(r=>!r.ok).length}));
  }
}catch(e){contractError=e.message}finally{await fs.rm(scratch,{recursive:true,force:true})}
const report={at:new Date().toISOString(),ok:!contractError&&rows.length===50&&rows.every(r=>r.ok),source:'downloads/*.zip extracted into a clean temporary directory',independentServerProcesses:rows.filter(r=>r.port).length,projectTestRunners:rows.filter(r=>r.testRunner?.exitCode===0).length,contractError,rows};

await fs.writeFile(path.join(output,'standalone-tests.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({output,ok:report.ok,projects:rows.length,projectTestRunners:report.projectTestRunners,contractError,failures:rows.filter(r=>!r.ok)}));
if(!report.ok)process.exitCode=1;
