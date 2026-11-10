// JSON-only boundary. Runtime paths come from the deployment, never the webview.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const root = path.dirname(fileURLToPath(import.meta.url));
const actions = new Set(['status','configure','start','stop','restore','models','verify','connect','disconnect','chat','continue','switchModel','session','archive']);
const failure = (code, message) => ({ok:false,error:{code,message}});
export function environment(env=process.env) {
  const data = path.resolve(env.PI_AGENT_DATA_DIR || '/data/pi-agent');
  const state = path.join(path.resolve(env.WOOW_CONNECTOR_DATA_DIR || path.join(data,'connectors')), 'omnigent');
  const managed = ['1','true','yes','on'].includes(env.OG_HOST_ENABLED || '') || Boolean(env.OG_STATE_DIR);
  const config = managed ? env.OG_CONFIG_HOME || env.OMNIGENT_CONFIG_HOME || path.join(data,'omnigent') : path.join(state,'sdk');
  const sdkData = managed ? env.OG_DATA_DIR || env.OMNIGENT_DATA_DIR || config : config;
  const nativeHome = value => /\/(?:codex-native|claude-native)\//.test(value || '');
  const passthrough=[...new Set((env.OMNIGENT_RUNNER_ENV_PASSTHROUGH||'').split(',').filter(Boolean)
    .concat(['WOOW_OMNIGENT_SHARED_TOOLS','PI_AGENT_DATA_DIR','PI_CODING_AGENT_DIR','CODEX_HOME','CLAUDE_CONFIG_DIR','DISABLE_AUTOUPDATER']))].join(',');
  // Preserve the deployment's native homes. Never inherit a native session home
  // as the source for subsequent sessions.
  return {...env, PI_AGENT_DATA_DIR:data, PI_CODING_AGENT_DIR:data,
    CODEX_HOME:env.CODEX_HOME&&!nativeHome(env.CODEX_HOME)?env.CODEX_HOME:path.join(data,'codex'),
    CLAUDE_CONFIG_DIR:env.CLAUDE_CONFIG_DIR&&!nativeHome(env.CLAUDE_CONFIG_DIR)?env.CLAUDE_CONFIG_DIR:path.join(data,'claude'),
    // The image owns the pinned Claude installation. SDK runner env filtering
    // otherwise drops this flag, allowing a native chat to replace that CLI.
    DISABLE_AUTOUPDATER:'1',
    OMNIGENT_RUNNER_ENV_PASSTHROUGH:passthrough,
    WOOW_OMNIGENT_SHARED_TOOLS:'1', WOOW_OMNIGENT_CONNECTOR_STATE:state,
    OMNIGENT_CONFIG_HOME:config, OMNIGENT_DATA_DIR:sdkData,
    WOOW_OMNIGENT_DEPLOYMENT_MANAGED:managed?'1':'0',
    OMNIGENT_ANALYTICS:'0', OMNIGENT_DISABLE_TELEMETRY:'1', DO_NOT_TRACK:'1'};
}
function pythonPath(env) {
  const paths = [env.WOOW_OMNIGENT_PYTHON, env.OG_PYTHON,
    '/opt/omnigent/tools/omnigent/bin/python', path.join(root,'runtime/bin/python')].filter(Boolean);
  return paths.find(p=>{try {fs.accessSync(p,fs.constants.X_OK);return path.isAbsolute(p);} catch{return false;}});
}
export async function handle(request) {
  if (!request || typeof request!=='object' || Array.isArray(request) || !actions.has(request.action))
    return failure('INVALID_ACTION','不支援此 Omnigent 操作。');
  const env = environment();
  const python = pythonPath(env);
  if (!python) {
    if (request.action==='restore') return {ok:true,resumed:false,reason:'runtime-missing'};
    if (request.action==='status') return {ok:true,phase:'runtime-missing',connected:false,
      mode:env.WOOW_OMNIGENT_DEPLOYMENT_MANAGED==='1'?'deployment-managed':'connector-managed',
      runtime:{installed:false,requiredVersion:'0.16.0'},verified:false};
    return failure('RUNTIME_MISSING','Omnigent runtime 尚未安裝；請由部署安裝器安裝固定版本 0.16.0。');
  }
  env.PATH=[path.dirname(python),env.PATH].filter(Boolean).join(path.delimiter);
  // Explicit allowlist: no executable paths, state roots, env or SDK home input.
  const input = Object.fromEntries(['action','server','username','password','workspace','hostName','engine','model','timeoutSeconds','prompt','sessionId']
    .filter(k=>request[k]!==undefined).map(k=>[k,request[k]]));
  if (Buffer.byteLength(JSON.stringify(input))>65536) return failure('REQUEST_TOO_LARGE','請求過大。');
  const timeout = request.action==='verify'?240_000:request.action==='status'?30_000:150_000;
  return new Promise(resolve=>{
    const child=spawn(python,[path.join(root,'bridge.py')],{env,stdio:['pipe','pipe','pipe']});
    let output='', bytes=0, settled=false;
    const finish=result=>{if(settled)return;settled=true;clearTimeout(timer);resolve(result);};
    const timer=setTimeout(()=>{child.kill('SIGTERM');setTimeout(()=>child.kill('SIGKILL'),2000).unref();finish(failure('ADAPTER_TIMEOUT','Omnigent 操作超時，請重新查看狀態。'));},timeout);
    child.stdout.on('data',chunk=>{bytes+=chunk.length;if(bytes>2*1024*1024){child.kill('SIGTERM');finish(failure('INVALID_RESPONSE','Omnigent 回應過大。'));}else output+=chunk;});
    // Deliberately discard SDK diagnostics: errors may contain bearer headers.
    child.stderr.resume();
    child.on('error',()=>finish(failure('RUNTIME_UNAVAILABLE','無法啟動 Omnigent runtime。')));
    child.on('close',()=>{try{const result=JSON.parse(output);if(typeof result.ok!=='boolean')throw Error();finish(result);}catch{finish(failure('INVALID_RESPONSE','Omnigent runtime 未回傳有效結果。'));}});
    child.stdin.on('error',()=>{});
    child.stdin.end(JSON.stringify(input));
  });
}
