import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {sync,render} from '../rootfs/opt/woow-agent-tools/agent-sync.mjs';
function fixture(t) {
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'woow-agents-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const data=root+'/data',home=root+'/home';fs.mkdirSync(home);
 const put=(p,d)=>{fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,typeof d==='string'?d:JSON.stringify(d));};
 const env={PI_AGENT_DATA_DIR:data,CLAUDE_CONFIG_DIR:data+'/claude',CODEX_HOME:data+'/codex',HOME:home};
 return {root,data,home,put,env};
}
test('upgrading merges actual skill files, retains originals/auth and is idempotent',t=>{
 const {data,home,put,env}=fixture(t);
 put(data+'/skills/pi-skill/SKILL.md','pi');put(data+'/claude/skills/synced/claude-skill/SKILL.md','claude');
 put(data+'/codex/skills/codex-skill/SKILL.md','codex');put(data+'/codex/auth.json','secret-do-not-touch');
 put(data+'/claude/.claude.json',{oauthAccount:{accountUuid:'preserve'},mcpServers:{fixture:{command:'node',args:['/fixture.cjs']}}});
 put(data+'/codex/config.toml','model = "existing-model"\n[profiles.work]\napproval_policy = "on-request"\n');
 sync(env);
 for(const p of [data+'/claude/skills',data+'/codex/skills',home+'/.agents/skills',data+'/home/.agents/skills'])assert.equal(fs.realpathSync(p),data+'/skills');
 assert.equal(fs.readFileSync(data+'/skills/synced/claude-skill/SKILL.md','utf8'),'claude');
 assert.equal(fs.readFileSync(data+'/codex/auth.json','utf8'),'secret-do-not-touch');
 assert.deepEqual(JSON.parse(fs.readFileSync(data+'/claude/.claude.json')).oauthAccount,{accountUuid:'preserve'});
 assert.match(fs.readFileSync(data+'/codex/config.toml','utf8'),/existing-model/);
 const files=['shared/mcp.json','mcp.json','claude/.claude.json','codex/config.toml','shared/managed.json'];
 const before=files.map(p=>[fs.readFileSync(data+'/'+p,'utf8'),fs.statSync(data+'/'+p).mtimeMs]);sync(env);
 assert.deepEqual(files.map(p=>[fs.readFileSync(data+'/'+p,'utf8'),fs.statSync(data+'/'+p).mtimeMs]),before);
});
test('removing a managed server removes it from all clients without resurrecting stale config',t=>{
 const {data,put,env}=fixture(t);put(data+'/shared/mcp.json',{mcpServers:{demo:{command:'true'}}});sync(env);
 put(data+'/shared/mcp.json',{mcpServers:{}});sync(env);
 assert.deepEqual(JSON.parse(fs.readFileSync(data+'/mcp.json')).mcpServers,{});
 assert.deepEqual(JSON.parse(fs.readFileSync(data+'/claude/.claude.json')).mcpServers,{});
 assert.doesNotMatch(fs.readFileSync(data+'/codex/config.toml','utf8'),/demo/);
 assert.deepEqual(JSON.parse(fs.readFileSync(data+'/shared/managed.json')),{servers:[],managedServers:['demo']});
});
test('conflicting skills fail before replacing source dirs',t=>{
 const {data,put,env}=fixture(t);put(data+'/skills/same/SKILL.md','first');put(data+'/claude/skills/same/SKILL.md','second');
 assert.throws(()=>sync(env),/Skills conflict/);
 assert.equal(fs.readFileSync(data+'/skills/same/SKILL.md','utf8'),'first');
 assert.equal(fs.readFileSync(data+'/claude/skills/same/SKILL.md','utf8'),'second');
 assert.equal(fs.lstatSync(data+'/claude/skills').isSymbolicLink(),false);
});
test('invalid registry fails before touching existing client settings',t=>{
 const {data,put,env}=fixture(t);put(data+'/claude/.claude.json',{oauthAccount:{id:'safe'}});
 put(data+'/shared/mcp.json',{mcpServers:{bad:{command:'true',url:'https://example.com'}}});
 assert.throws(()=>sync(env),/exactly one/);
 assert.deepEqual(JSON.parse(fs.readFileSync(data+'/claude/.claude.json')),{oauthAccount:{id:'safe'}});
});
test('native OAuth and tool restrictions are never silently dropped during import',t=>{
 const {data,put,env}=fixture(t);
 const initial='[mcp_servers.private]\nurl = "https://example.com/mcp"\ndisabled_tools = ["delete"]\n';
 put(data+'/codex/config.toml',initial);
 assert.throws(()=>sync(env),/disabled_tools/);
 assert.equal(fs.readFileSync(data+'/codex/config.toml','utf8'),initial);
 assert.equal(fs.existsSync(data+'/shared/mcp.json'),false);
});
test('legacy SSE and hidden Pi servers fail without changing the source',t=>{
 const {data,put,env}=fixture(t);
 put(data+'/mcp.json',{mcpServers:{hidden:{command:'true',exposure:'hidden'}}});
 assert.throws(()=>sync(env),/hidden MCP/);
 put(data+'/mcp.json',{mcpServers:{legacy:{type:'sse',url:'https://example.com/sse'}}});
 assert.throws(()=>sync(env),/unsupported MCP transport/);
 assert.equal(JSON.parse(fs.readFileSync(data+'/mcp.json')).mcpServers.legacy.type,'sse');
});
test('MCP transports, disabled entries, and explicit environment references translate across clients',()=>{
 process.env.WOOW_TEST_HEADER='test-value';
 const r=render({web:{url:'https://example.com/mcp',headers:{Authorization:'Bearer ${WOOW_TEST_HEADER}'},timeout:25},off:{command:'true',enabled:false}});
 assert.equal(r.pi.web.headers.Authorization,'Bearer ${WOOW_TEST_HEADER}');
 assert.equal(r.claude.web.headers.Authorization,'Bearer test-value');assert.equal(r.codex.web.http_headers.Authorization,'Bearer test-value');
 assert.equal(r.codex.web.tool_timeout_sec,25);assert.equal(r.claude.off,undefined);assert.equal(r.codex.off.enabled,false);
 assert.throws(()=>render({bad:{url:'https://example.com',type:'sse'}}),/transport/);
 delete process.env.WOOW_TEST_HEADER;
});
test('equivalent native and canonical HTTP types do not create a false import conflict',t=>{
 const {data,put,env}=fixture(t),entry={type:'http',url:'https://example.com/mcp'};
 put(data+'/shared/mcp.json',{mcpServers:{same:entry}});
 put(data+'/claude/.claude.json',{mcpServers:{same:entry}});
 sync(env);
 assert.equal(JSON.parse(fs.readFileSync(data+'/mcp.json')).mcpServers.same.url,entry.url);
});
test('disabled servers do not require credentials until enabled',()=>{
 const r=render({pending:{url:'https://example.com/mcp',enabled:false,headers:{Authorization:'Bearer ${WOOW_UNSET_TEST_KEY}'}}});
 assert.equal(r.codex.pending.enabled,false);assert.equal(r.claude.pending,undefined);
});
test('incompatible transport fields are rejected before clients can interpret them differently',()=>{
 assert.throws(()=>render({bad:{type:'http',command:'true'}}),/transport does not match/);
 assert.throws(()=>render({bad:{url:'https://example.com',env:{KEY:'value'}}}),/cannot be mixed/);
 assert.throws(()=>render({bad:{command:'true',enabled:'false'}}),/boolean/);
});

// A separate native writer using Claude's proper-lockfile protocol: mkdir the
// exact <config>.lock, read only after acquisition, atomic rename, then rmdir.
// No production hooks or shared JS mutex can make this process respect sync.
function nativeWrite(config, changes) {
 const result=spawnSync(process.execPath,['--input-type=module','-e',`
  import fs from 'node:fs';
  const [config,changes]=process.argv.slice(1),lock=config+'.lock';
  try { fs.mkdirSync(lock,{mode:0o700}); }
  catch(error) { if(error.code==='EEXIST') process.exit(73); throw error; }
  try {
   const current=JSON.parse(fs.readFileSync(config,'utf8'));
   const temporary=config+'.native-'+process.pid;
   fs.writeFileSync(temporary,JSON.stringify({...current,...JSON.parse(changes)}),{mode:0o600});
   fs.renameSync(temporary,config);
  } finally { fs.rmdirSync(lock); }
 `,config,JSON.stringify(changes)],{encoding:'utf8',timeout:5000});
 assert.equal(result.error,undefined);
 assert.equal(result.stderr,'');
 return result.status;
}

function duringSkillCopy(t, action) {
 const original=fs.cpSync;
 let calls=0;
 t.mock.method(fs,'cpSync',function(...args) {
  if(calls++===0) action();
  return original.apply(this,args);
 });
 return ()=>assert.ok(calls>0,'native writer interleaved after config read during actual skill migration');
}

test('native preference writes during skill migration survive shared sync',t=>{
 const {data,put,env}=fixture(t),config=data+'/claude/.claude.json';
 put(config,{mcpServers:{},oauthAccount:{id:'preserved'},projects:{'/work':{disabledMcpServers:[]}}});
 put(data+'/claude/skills/incoming/SKILL.md','migrate');
 put(data+'/shared/mcp.json',{mcpServers:{demo:{command:'true'}}});
 const preferences={projects:{'/work':{disabledMcpServers:['user-disabled'],hasTrustDialogAccepted:true}},theme:'native-new'};
 const interleaved=duringSkillCopy(t,()=>{
  assert.ok(fs.existsSync(data+'/shared/.sync-lock'));
  assert.equal(fs.existsSync(config+'.lock'),false,'native lock is not held through skill copying');
  assert.equal(nativeWrite(config,preferences),0);
 });
 sync(env);interleaved();
 const saved=JSON.parse(fs.readFileSync(config));
 assert.deepEqual(saved.projects,preferences.projects);
 assert.equal(saved.theme,preferences.theme);
 assert.deepEqual(saved.oauthAccount,{id:'preserved'});
 assert.equal(saved.mcpServers.demo.command,'true');
 assert.equal(fs.existsSync(config+'.lock'),false);
});

test('concurrent native MCP edits are preserved and require a new import pass',t=>{
 const {data,put,env}=fixture(t),config=data+'/claude/.claude.json';
 put(config,{mcpServers:{}});
 put(data+'/claude/skills/incoming/SKILL.md','migrate');
 put(data+'/shared/mcp.json',{mcpServers:{demo:{command:'true'}}});
 const originalRegistry=fs.readFileSync(data+'/shared/mcp.json','utf8');
 const nativeServers={private:{command:'native-only'}};
 const interleaved=duringSkillCopy(t,()=>assert.equal(nativeWrite(config,{mcpServers:nativeServers}),0));
 assert.throws(()=>sync(env),/MCP definitions changed during sync/);interleaved();
 assert.deepEqual(JSON.parse(fs.readFileSync(config)).mcpServers,nativeServers);
 assert.equal(fs.readFileSync(data+'/shared/mcp.json','utf8'),originalRegistry);
 for(const name of ['mcp.json','codex/config.toml','shared/managed.json','shared/.sync-lock','claude/.claude.json.lock'])
  assert.equal(fs.existsSync(data+'/'+name),false,name);
 sync(env);
 assert.equal(JSON.parse(fs.readFileSync(config)).mcpServers.private.command,'native-only');
 assert.equal(JSON.parse(fs.readFileSync(config)).mcpServers.demo.command,'true');
});

test('an existing native lock is never stolen and prevents client publication',t=>{
 const {data,put,env}=fixture(t),config=data+'/claude/.claude.json',lock=config+'.lock';
 put(config,{mcpServers:{},projects:{'/work':{disabledMcpServers:['mine']}}});
 put(data+'/shared/mcp.json',{mcpServers:{demo:{command:'true'}}});
 const original=fs.readFileSync(config,'utf8'),registry=fs.readFileSync(data+'/shared/mcp.json','utf8');
 fs.mkdirSync(lock,{mode:0o700});const inode=fs.statSync(lock).ino;
 assert.throws(()=>sync(env),/Claude config is being updated/);
 assert.equal(fs.statSync(lock).ino,inode);
 assert.equal(fs.readFileSync(config,'utf8'),original);
 assert.equal(fs.readFileSync(data+'/shared/mcp.json','utf8'),registry);
 for(const name of ['mcp.json','codex/config.toml','shared/managed.json','shared/.sync-lock'])
  assert.equal(fs.existsSync(data+'/'+name),false,name);
});

test('a separate native writer cannot enter while sync publishes Claude config',t=>{
 const {data,put,env}=fixture(t),config=data+'/claude/.claude.json';
 put(config,{mcpServers:{},projects:{'/work':{disabledMcpServers:['mine']}}});
 put(data+'/shared/mcp.json',{mcpServers:{demo:{command:'true'}}});
 const original=fs.renameSync;let attempts=0;
 t.mock.method(fs,'renameSync',function(from,to) {
  if(to===config) {
   attempts++;
   assert.ok(fs.existsSync(data+'/shared/.sync-lock'));
   assert.equal(nativeWrite(config,{theme:'must-wait'}),73);
  }
  return original.call(this,from,to);
 });
 sync(env);assert.equal(attempts,1);
 assert.equal(nativeWrite(config,{theme:'after-sync'}),0);
 const saved=JSON.parse(fs.readFileSync(config));
 assert.equal(saved.theme,'after-sync');
 assert.equal(saved.mcpServers.demo.command,'true');
 assert.deepEqual(saved.projects['/work'].disabledMcpServers,['mine']);
});

test('failed Claude publication preserves its old bytes and releases both owned locks',t=>{
 const {data,put,env}=fixture(t),config=data+'/claude/.claude.json';
 put(config,{mcpServers:{},projects:{'/work':{disabledMcpServers:['mine']}}});
 put(data+'/shared/mcp.json',{mcpServers:{demo:{command:'true'}}});
 const before=fs.readFileSync(config,'utf8'),registry=fs.readFileSync(data+'/shared/mcp.json','utf8');
 const original=fs.renameSync;
 const mocked=t.mock.method(fs,'renameSync',function(from,to) {
  if(to===config) throw Object.assign(new Error('fixture publication failure'),{code:'EIO'});
  return original.call(this,from,to);
 });
 assert.throws(()=>sync(env),/fixture publication failure/);
 assert.equal(fs.readFileSync(config,'utf8'),before);
 assert.equal(fs.readFileSync(data+'/shared/mcp.json','utf8'),registry);
 assert.equal(fs.existsSync(config+'.lock'),false);
 assert.equal(fs.existsSync(data+'/shared/.sync-lock'),false);
 mocked.mock.restore();
 sync(env);
 assert.deepEqual(JSON.parse(fs.readFileSync(config)).projects['/work'].disabledMcpServers,['mine']);
});
