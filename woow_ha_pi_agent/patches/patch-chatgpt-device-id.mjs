#!/usr/bin/env node
import fs from 'node:fs';
export function patch(source) {
 const begin='await d.login(c,"oauth",{';
 const end='signal:j.signal}),(0,f.kn)()';
 if(source.includes('__piChatGPTDeviceId')) return source;
 for(const anchor of [begin,end])if(source.split(anchor).length!==2)throw Error('OAuth route anchor changed; inspect upstream before patching');
 const helper='async function __piChatGPTDeviceId(){const sdk=await import("@earendil-works/pi-coding-agent");const dir=sdk.getAgentDir();const settings=sdk.SettingsManager.create(dir,dir);const id=settings.getOrCreateDeviceId();if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id))throw Error("Installation deviceId must be a UUID; inspect global settings");return id;}\n';
 return helper+source.replace(begin,'const __piHostId=(c==="openai"||c==="openai-codex"||c==="openai-chatgpt")?await __piChatGPTDeviceId():undefined;'+begin).replace(end,'signal:j.signal},{getDeviceId:()=>__piHostId}),(0,f.kn)()');
}
if(process.argv[1]===new URL(import.meta.url).pathname){
 const file=process.argv[2];if(!file)throw Error('usage: patch-chatgpt-device-id.mjs <OAuth route.js>');
 fs.writeFileSync(file,patch(fs.readFileSync(file,'utf8')));console.log('OAuth installation identity patch verified');
}
