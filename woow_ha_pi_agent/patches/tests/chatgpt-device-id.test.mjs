import test from 'node:test';
import assert from 'node:assert/strict';
import {patch} from '../patch-chatgpt-device-id.mjs';

const route='await d.login(c,"oauth",{prompt:()=>{},signal:j.signal}),(0,f.kn)()';

test('ChatGPT OAuth gets the persisted installation UUID through SDK login options',()=>{
 const fixed=patch(route);
 assert.ok(fixed.includes('(c==="openai"||c==="openai-codex"||c==="openai-chatgpt")?await __piChatGPTDeviceId():undefined'));
 assert.ok(fixed.includes('signal:j.signal},{getDeviceId:()=>__piHostId}'));
 assert.ok(fixed.includes('settings.getOrCreateDeviceId()'));
 assert.equal(patch(fixed),fixed);
});

test('unknown or duplicated upstream anchors fail closed',()=>{
 assert.throws(()=>patch('unknown upstream'));
 assert.throws(()=>patch(route+route));
});
