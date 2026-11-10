#!/usr/bin/env node
// One deployment-private skills tree and MCP registry; never copies model credentials.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { parse, stringify } from 'smol-toml';
import { fileURLToPath } from 'node:url';

const json = p => fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : {};
const same = (a,b) => JSON.stringify(sort(a)) === JSON.stringify(sort(b));
function sort(v) { return Array.isArray(v) ? v.map(sort) : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map(k=>[k,sort(v[k])])) : v; }
function write(p, body) {
  if (fs.existsSync(p) && fs.readFileSync(p,'utf8') === body) return;
  fs.mkdirSync(path.dirname(p), {recursive:true,mode:0o700});
  if (fs.existsSync(p) && !fs.existsSync(p+'.before-shared-agents')) fs.copyFileSync(p,p+'.before-shared-agents');
  if (fs.existsSync(p+'.before-shared-agents')) fs.chmodSync(p+'.before-shared-agents',0o600);
  const tmp = `${p}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, body, {mode:0o600}); fs.renameSync(tmp,p);
}
const writeJSON = (p,d) => write(p,JSON.stringify(d,null,2)+'\n');
function withClaudeConfigLock(config, run) {
  // Claude's proper-lockfile writer uses mkdir(<config>.lock). Match that
  // protocol, never steal a native lock, and keep this section synchronous and
  // short: skill migration and rendering must finish before acquiring it.
  // All shared writers take shared/.sync-lock BEFORE this native lock.
  const lock = config+'.lock';
  try { fs.mkdirSync(lock,{mode:0o700}); }
  catch (error) {
    if (error.code === 'EEXIST') throw new Error('Claude config is being updated (.claude.json.lock); retry after it finishes.');
    throw error;
  }
  const owned = fs.lstatSync(lock);
  try { return run(); }
  finally {
    let current;
    try { current = fs.lstatSync(lock); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (current?.dev === owned.dev && current?.ino === owned.ino) fs.rmdirSync(lock);
  }
}

// Refuse a collision before moving anything; retain the original tree for rollback.
function mergePlan(source, target, copies=[]) {
  if (!fs.existsSync(source)) return copies;
  if (fs.existsSync(target) && fs.realpathSync(source) === fs.realpathSync(target)) return copies;
  for (const name of fs.readdirSync(source)) {
    const s=path.join(source,name), t=path.join(target,name), st=fs.lstatSync(s);
    if (!fs.existsSync(t) && !fs.lstatSync(t,{throwIfNoEntry:false})) copies.push([s,t]);
    else if (st.isDirectory() && fs.lstatSync(t).isDirectory()) mergePlan(s,t,copies);
    else {
      const equal=st.isSymbolicLink() ? fs.lstatSync(t).isSymbolicLink() && fs.readlinkSync(s)===fs.readlinkSync(t) : !fs.lstatSync(t).isSymbolicLink() && fs.statSync(t).isFile() && fs.readFileSync(s).equals(fs.readFileSync(t));
      if (!equal) throw new Error(`Skills conflict at ${t}; original files are retained. Resolve the conflict before syncing.`);
    }
  }
  return copies;
}
function link(source,target) {
  fs.mkdirSync(path.dirname(source),{recursive:true,mode:0o700});
  if (fs.existsSync(source) && fs.realpathSync(source) === fs.realpathSync(target)) return;
  if (fs.lstatSync(source,{throwIfNoEntry:false})) {
    if (fs.lstatSync(source).isSymbolicLink()) fs.unlinkSync(source);
    else fs.renameSync(source,`${source}.before-shared-agents-${Date.now()}`);
  }
  fs.symlinkSync(target,source,'dir');
}

function normalize(s) {
  const r={};
  for (const k of ['command','args','env','cwd','url','headers','enabled','timeout','type']) if(s[k]!==undefined) r[k]=s[k];
  if (s.http_headers) r.headers={...(r.headers||{}),...s.http_headers};
  for (const [k,v] of Object.entries(s.env_http_headers||{})) (r.headers??={})[k]=`\${${v}}`;
  if (s.bearer_token_env_var) (r.headers??={}).Authorization=`Bearer \${${s.bearer_token_env_var}}`;
  if (s.tool_timeout_sec) r.timeout=s.tool_timeout_sec;
  return r;
}
function importServer(name,s) {
  // Never discard a native client's OAuth or tool restrictions while importing.
  const allowed=['command','args','env','cwd','url','headers','enabled','timeout','type',
    'http_headers','env_http_headers','bearer_token_env_var','tool_timeout_sec','exposure'];
  for(const key of Object.keys(s)) if(!allowed.includes(key))
    throw new Error(`Cannot share native MCP field ${name}.${key}; retain it in client-specific project configuration or supply a common server definition`);
  if(s.exposure==='hidden') throw new Error(`Cannot expose hidden MCP server ${name} to other clients`);
  const r=normalize(s);
  // Native transport labels are equivalent only after validation.
  if(r.type && !['stdio','http','streamable-http'].includes(r.type))
    throw new Error(`${name}: unsupported MCP transport`);
  if(r.type && (r.type==='stdio')!==Boolean(r.command))
    throw new Error(`${name}: transport does not match command or URL`);
  delete r.type;
  return r;
}
function expand(v) {
  if(typeof v!=='string') throw new Error('MCP environment/header values must be strings');
  if(v.startsWith('!')) throw new Error('Shell substitutions are not supported in the shared MCP registry');
  return v.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g,(_,k)=>{
    if(process.env[k]===undefined) throw new Error(`Missing MCP environment variable ${k}`);
    return process.env[k];
  });
}
export function render(servers) {
  const pi={},claude={},codex={};
  for(const [name,input] of Object.entries(servers)) {
    if(!/^[a-zA-Z0-9_-]+$/.test(name)) throw new Error(`Invalid shared MCP name: ${name}`);
    const allowed=['command','args','env','cwd','url','headers','enabled','timeout','type'];
    for(const k of Object.keys(input)) if(!allowed.includes(k)) throw new Error(`Unsupported shared MCP field ${name}.${k}`);
    const s=normalize(input);
    if(Boolean(s.command)===Boolean(s.url)) throw new Error(`${name} needs exactly one command or URL`);
    if(input.type && !['stdio','http','streamable-http'].includes(input.type)) throw new Error(`${name}: unsupported MCP transport`);
    if(input.type && (input.type==='stdio')!==Boolean(s.command)) throw new Error(`${name}: transport does not match command or URL`);
    if(s.enabled!==undefined && typeof s.enabled!=='boolean') throw new Error(`${name}.enabled must be a boolean`);
    if(s.command && typeof s.command!=='string') throw new Error(`${name}.command must be an executable string`);
    if(s.args && (!Array.isArray(s.args)||s.args.some(x=>typeof x!=='string'))) throw new Error(`${name}.args must be an array of strings`);
    if(s.headers && !s.url || s.url && (s.env || s.args)) throw new Error(`${name}: HTTP headers and stdio environment/arguments cannot be mixed`);
    if(s.url && !/^https?:\/\//.test(s.url)) throw new Error(`${name} needs a streamable HTTP URL`);
    if(s.cwd) throw new Error(`${name}: use a stdio wrapper for cwd so all clients behave identically`);
    const enabled=s.enabled!==false;
    const {type,...piConfig}=s;
    pi[name]={...piConfig,exposure:'direct'};
    if(enabled) {
      claude[name]={type:s.url?'http':'stdio',...(s.url?{url:s.url}:{command:s.command,args:s.args||[]})};
      for(const k of ['env','headers']) if(s[k]) claude[name][k]=Object.fromEntries(Object.entries(s[k]).map(([k,v])=>[k,expand(v)]));
    }
    codex[name]={enabled,...(s.url?{url:s.url}:{command:s.command,args:s.args||[]})};
    if(s.env) codex[name].env=Object.fromEntries(Object.entries(s.env).map(([k,v])=>[k,enabled?expand(v):v]));
    if(s.headers) codex[name].http_headers=Object.fromEntries(Object.entries(s.headers).map(([k,v])=>[k,enabled?expand(v):v]));
    if(s.timeout) codex[name].tool_timeout_sec=s.timeout;
  }
  return {pi,claude,codex};
}

export function sync(env=process.env) {
  const data=env.PI_AGENT_DATA_DIR||'/data/pi-agent';
  const claudeDir=env.CLAUDE_CONFIG_DIR||`${data}/claude`, codexDir=env.CODEX_HOME||`${data}/codex`;
  const shared=`${data}/shared`, skills=`${data}/skills`;
  for(const dir of [data,shared,skills,claudeDir,codexDir]) fs.mkdirSync(dir,{recursive:true,mode:0o700});
  const lock=`${shared}/.sync-lock`;
  try {fs.mkdirSync(lock,{mode:0o700});} catch {throw new Error('Another agent sync is running (shared/.sync-lock); retry after it finishes.');}
  try {
    const registryPath=`${shared}/mcp.json`, statePath=`${shared}/managed.json`;
    const piPath=`${data}/mcp.json`, claudePath=`${claudeDir}/.claude.json`, codexPath=`${codexDir}/config.toml`;
    const pi=json(piPath), claude=json(claudePath);
    const codex=fs.existsSync(codexPath)?parse(fs.readFileSync(codexPath,'utf8')):{};
    const managed=json(statePath);
    const previous=managed.servers||[], registry=json(registryPath);
    const servers=registry.mcpServers??{};
    // Import local, explicitly configured servers once. Account-only Claude cloud
    // connectors and each client's OAuth tokens are deliberately outside this registry.
    for(const entries of [pi.mcpServers,claude.mcpServers,codex.mcp_servers]) {
      for(const [name,entry] of Object.entries(entries||{})) {
        if(previous.includes(name)) continue;
        const normalized=importServer(name,entry);
        if(servers[name] && !same(importServer(name,servers[name]),normalized)) throw new Error(`MCP conflict for ${name}; choose one definition in shared/mcp.json first`);
        servers[name]??=normalized;
      }
    }
    const rendered=render(servers); // Validate every server before changing client files.
    const bridges=[`${claudeDir}/skills`,`${codexDir}/skills`,`${data}/home/.agents/skills`,`${data}/home/.pi/agent/skills`];
    if(env.HOME && env.WOOW_SKIP_LOGIN_HOME!=='1') bridges.push(`${env.HOME}/.agents/skills`);
    const plans=bridges.map(source=>[source,mergePlan(source,skills)]);
    // Detect conflicting incoming skills from two clients before any migration.
    const destinations=new Map();
    for(const [,copies] of plans) for(const [s,t] of copies) {
      if(destinations.has(t) && destinations.get(t)!==s) mergePlan(path.dirname(s),path.dirname(destinations.get(t)));
      destinations.set(t,s);
    }
    for(const [,copies] of plans) for(const [s,t] of copies) {fs.mkdirSync(path.dirname(t),{recursive:true});fs.cpSync(s,t,{recursive:true,force:false,errorOnExist:false,verbatimSymlinks:true});}
    for(const source of bridges) link(source,skills);
    const replace=(old,fresh)=>({...Object.fromEntries(Object.entries(old||{}).filter(([k])=>!previous.includes(k)&&!Object.hasOwn(servers,k))),...fresh});
    pi.mcpServers=replace(pi.mcpServers,rendered.pi);
    codex.mcp_servers=replace(codex.mcp_servers,rendered.codex);
    withClaudeConfigLock(claudePath,()=>{
      // A native writer may have saved preferences since import planning. Read
      // its latest document under its lock; never publish the earlier snapshot.
      // Changed MCP definitions need a new import/validation pass instead.
      const current=json(claudePath);
      if (!same(current.mcpServers,claude.mcpServers)) throw new Error('Claude MCP definitions changed during sync; retry to import the current configuration.');
      current.mcpServers=replace(current.mcpServers,rendered.claude);
      writeJSON(claudePath,current);
    });
    writeJSON(registryPath,{...registry,mcpServers:servers});
    writeJSON(piPath,pi);
    // Preserve the user's entire original TOML in a private rollback copy. Parsing
    // and serialization preserve values, including unrelated models and profiles.
    if(!same(fs.existsSync(codexPath)?parse(fs.readFileSync(codexPath,'utf8')):{},codex)) write(codexPath,stringify(codex));
    writeJSON(statePath,{servers:Object.keys(servers).sort(), managedServers:[...new Set([...(managed.managedServers||previous),...Object.keys(servers)])].sort()});
    const digest=crypto.createHash('sha256').update(JSON.stringify(sort(servers))).digest('hex');
    console.log(JSON.stringify({sharedSkills:skills,sharedMcp:registryPath,servers:Object.keys(servers).sort(),configurationHash:digest}));
  } finally {fs.rmdirSync(lock);}
}
if(process.argv[1] && fileURLToPath(import.meta.url)===fs.realpathSync(process.argv[1])) {
  try {sync();} catch(e) {console.error(`woow-agent-sync: ${e.message}`);process.exitCode=1;}
}
