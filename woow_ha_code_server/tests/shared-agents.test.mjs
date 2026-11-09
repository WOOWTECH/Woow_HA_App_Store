import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
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
