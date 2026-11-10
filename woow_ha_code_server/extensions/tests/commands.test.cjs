'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createExtension } = require('../shared/extension.cjs');
const { html } = require('../shared/ui.cjs');
function harness(connector, responses={}) {
  const commands=new Map(), calls=[], logs=[], updates=[], notices=[], opened=[], posted=[], inputOptions=[], editorCommands=[];
  const values={runtimePath:'/usr/local/bin/woow-connectors',workspace:'/workspace',hostName:'test',server:'https://omnigent.example.org',webUrl:connector==='paseo'?'https://app.paseo.sh':''};
  const inputs=[], picks=[], pickOptions=[];
  let receive;
  const disposable={dispose(){}};
  const panel={webview:{html:'',postMessage:message=>posted.push(message),onDidReceiveMessage:fn=>{receive=fn;return disposable;}},reveal(){},onDidDispose(){return disposable;},dispose(){}};
  const vscode={
    ConfigurationTarget:{Global:1},ViewColumn:{One:1},UIKind:{Desktop:1,Web:2},Uri:{parse:value=>value},
    EventEmitter:class {event=()=>{};fire(){}dispose(){}},
    workspace:{isTrusted:true,getConfiguration:()=>({inspect:key=>({defaultValue:values[key]}),update:async(key,value)=>{updates.push([key,value]);values[key]=value;}}),onDidChangeConfiguration:()=>disposable},
    env:{openExternal:async url=>{opened.push(url);return true;}},
    commands:{registerCommand:(id,fn)=>{commands.set(id,fn);return disposable;},executeCommand:async(...args)=>{editorCommands.push(args);}},
    window:{createOutputChannel:()=>({appendLine:line=>logs.push(line),dispose(){}}),registerTreeDataProvider:()=>disposable,createWebviewPanel:()=>panel,showInputBox:async options=>{inputOptions.push(options);return inputs.shift();},showQuickPick:async(items,options)=>{pickOptions.push({items,options});return picks.shift();},showInformationMessage:async text=>notices.push(text),showErrorMessage:async text=>notices.push(text)},
  };
  const ext=createExtension(connector,{vscode,createRuntime:options=>async request=>{calls.push(request);const response=responses[request.action]??{ok:true,phase:'online'};options.onEvent({connector,action:request.action,ok:response.ok});return response;}});
  const api=ext.activate({subscriptions:[]});
  return {ext,api,vscode,commands,calls,logs,updates,notices,opened,posted,inputs,picks,pickOptions,inputOptions,panel,values,editorCommands,receive:message=>receive(message)};
}
test('native settings opens container machine settings in remote and browser hosts without changing configuration', async () => {
  for (const connector of ['paseo','omnigent']) {
    for (const [environment, expected] of [
      [{remoteName:'code-server',uiKind:1},'workbench.action.openRemoteSettings'],
      [{uiKind:2},'workbench.action.openRemoteSettings'],
      [{uiKind:1},'workbench.action.openSettings'],
    ]) {
      const h=harness(connector);Object.assign(h.vscode.env,environment);
      await h.commands.get(`woow.${connector}.settings`)();
      assert.deepEqual(h.editorCommands,[[expected,{query:`@ext:woowtech.${connector}`}]]);
      assert.equal(h.calls.length,0);assert.equal(h.updates.length,0);
    }
  }
});
test('activation and window deactivation do not start or stop backend processes', () => {
  for(const name of ['paseo','omnigent']) {const h=harness(name);assert.equal(h.calls.length,0);assert.ok(h.commands.has(`woow.${name}.configure`));h.ext.deactivate();assert.equal(h.calls.length,0);}
});
test('native commands dispatch explicit connector actions; configure fields remain top-level', async () => {
  const h=harness('paseo');
  await h.commands.get('woow.paseo.start')();
  assert.deepEqual(h.calls[0],{connector:'paseo',action:'start'});
  await h.api.perform('configure',{workspace:'/workspace/team',hostName:'my host',webUrl:'https://app.paseo.sh'});
  assert.deepEqual(h.calls.find(c=>c.action==='configure'),{connector:'paseo',action:'configure',workspace:'/workspace/team',hostName:'my host'});
  assert.equal(h.updates.some(([key])=>key==='workspace'),true);
});
test('Omnigent sign-in prompts masked password and never persists or renders it', async () => {
  const h=harness('omnigent');h.inputs.push('operator','private-password-value');
  await h.commands.get('woow.omnigent.connect')();
  const request=h.calls.find(c=>c.action==='connect');
  assert.equal(request.password,'private-password-value');assert.equal(request.username,'operator');assert.equal(h.inputOptions[1].password,true);
  assert.equal(JSON.stringify([h.logs,h.updates,h.notices,h.posted,h.api.getPublicState()]).includes('private-password-value'),false);
});
test('cancelled sign-in performs no connect and untrusted workspace cannot start', async () => {
  const h=harness('omnigent');h.inputs.push(undefined);
  await h.commands.get('woow.omnigent.connect')();assert.equal(h.calls.some(c=>c.action==='connect'),false);
  h.vscode.workspace.isTrusted=false;await h.commands.get('woow.omnigent.start')();assert.equal(h.calls.some(c=>c.action==='start'),false);
});
test('pair opens private URL only on explicit action without rendering or logging', async () => {
  const privateUrl='https://app.paseo.sh/#private-pairing-credential';
  const h=harness('paseo',{pair:{ok:true,pairingUrl:privateUrl}});
  h.commands.get('woow.paseo.open')();assert.equal(h.opened.length,0);
  await h.commands.get('woow.paseo.pair')();assert.deepEqual(h.opened,[privateUrl]);
  assert.equal(JSON.stringify([h.logs,h.posted,h.updates,h.api.getPublicState()]).includes('private-pairing'),false);
  const bad=harness('paseo',{pair:{ok:true,url:'https://unrelated.example/#private'}});
  await bad.commands.get('woow.paseo.pair')();assert.equal(bad.opened.length,0);
});
test('verify passes selected engine and model; success requires explicit verification evidence', async () => {
  const h=harness('paseo',{models:{ok:true,models:[{agent:'codex',id:'test-model',name:'Test model'}]},verify:{ok:true}});
  h.picks.push({label:'Codex',engine:'codex'},{model:'test-model'});
  await h.commands.get('woow.paseo.verify')();
  assert.deepEqual(h.calls.find(c=>c.action==='verify'),{connector:'paseo',action:'verify',engine:'codex',model:'test-model'});
  assert.equal(h.notices.some(n=>n.includes('has not reported a verified reply')),true);
  assert.equal(h.api.getPublicState().verification,'unverified');
});
test('Paseo Verify offers only models from the selected provider inventory', async () => {
  const h=harness('paseo',{models:{ok:true,providers:[
    {provider:'claude',models:[{id:'claude-sonnet-5-5',label:'Sonnet 5.5'}]},
    {provider:'codex',models:[{id:'gpt-6.1-sol',label:'GPT-6.1-Sol'}]},
    {provider:'pi',models:[{id:'openai-codex/gpt-6.1-sol'}]},
  ]},verify:{ok:true,requestedPassed:true}});
  h.picks.push({label:'Claude Code',engine:'claude'},{model:'claude-sonnet-5-5'});
  await h.commands.get('woow.paseo.verify')();
  assert.deepEqual(h.pickOptions[1].items.map(item=>item.model),['claude-sonnet-5-5']);
  assert.deepEqual(h.calls.find(call=>call.action==='verify'),{connector:'paseo',action:'verify',engine:'claude',model:'claude-sonnet-5-5'});
});
test('webview rejects unsupported messages and connector-mismatched actions', async () => {
  const h=harness('paseo');h.commands.get('woow.paseo.open')();
  h.receive({action:'exec',command:'bash'});h.receive({action:'connect'});h.receive({action:'start',fields:{connector:'omnigent'}});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(h.calls.length,0);
  const markup=html('omnigent');assert.ok(markup.includes("default-src 'none'"));assert.ok(markup.includes("form-action 'none'"));
  assert.equal(markup.includes('innerHTML'),false);assert.equal(markup.includes('setState'),false);assert.equal(markup.includes('type="password"'),false);
});
test('native status command reports connection and separate unverified state without webview', async () => {
  const h=harness('paseo');await h.commands.get('woow.paseo.status')();
  assert.ok(h.notices.some(message=>message.includes('connection online; conversation unverified')));
});
test('activity-bar container IDs meet the live VS Code contribution schema', () => {
  for (const connector of ['paseo','omnigent']) {
    const manifest=require(`../${connector}/package.json`);
    const id=manifest.contributes.viewsContainers.activitybar[0].id;
    assert.match(id,/^[a-zA-Z0-9_-]+$/);
    assert.ok(manifest.contributes.views[id].some(view=>view.id===`woow.${connector}.statusView`));
  }
});
test('Omnigent routes login to internal server and browser opening to separate Web URL without forwarding auth', async () => {
  const h=harness('omnigent');
  await h.api.perform('configure',{workspace:'/workspace/team',hostName:'qa',server:'http://omnigent-server:8000',webUrl:'http://127.0.0.1:18080'});
  assert.deepEqual(h.calls.find(c=>c.action==='configure'),{connector:'omnigent',action:'configure',workspace:'/workspace/team',hostName:'qa',server:'http://omnigent-server:8000/'});
  h.inputs.push('operator','fixture-password-private');await h.commands.get('woow.omnigent.connect')();
  const connect=h.calls.find(c=>c.action==='connect');assert.equal(connect.server,'http://omnigent-server:8000/');assert.equal(connect.webUrl,undefined);assert.equal(connect.password,'fixture-password-private');
  await h.commands.get('woow.omnigent.openWeb')();assert.deepEqual(h.opened,['http://127.0.0.1:18080/']);
  assert.equal(JSON.stringify([h.opened,h.logs,h.posted,h.updates,h.api.getPublicState()]).includes('fixture-password-private'),false);
  assert.equal(h.api.getPublicState().settings.webUrl,'http://127.0.0.1:18080/');
});
test('clearing optional Omnigent Web URL restores server fallback without changing the backend destination', async () => {
  const h=harness('omnigent');
  await h.api.perform('configure',{workspace:'/workspace',hostName:'qa',server:'http://omnigent.ns.svc.cluster.local:8000',webUrl:'https://omnigent.example.org'});
  await h.api.perform('configure',{workspace:'/workspace',hostName:'qa',server:'http://omnigent.ns.svc.cluster.local:8000',webUrl:''});
  await h.commands.get('woow.omnigent.openWeb')();assert.deepEqual(h.opened,['http://omnigent.ns.svc.cluster.local:8000/']);
  assert.ok(h.updates.some(([key,value])=>key==='webUrl'&&value===undefined));
});
test('native Omnigent configuration asks for a separate optional browser URL and cancellation does not save partial settings', async () => {
  const h=harness('omnigent');h.inputs.push('/workspace','qa','http://omnigent-server:8000','https://omnigent.example.org');
  await h.commands.get('woow.omnigent.configure')();
  assert.equal(h.inputOptions.at(-1).title,'Omnigent: browser Web URL (optional)');assert.ok(h.updates.some(([key,value])=>key==='webUrl'&&value==='https://omnigent.example.org/'));
  const cancel=harness('omnigent');cancel.inputs.push('/workspace','qa','http://omnigent-server:8000',undefined);
  await cancel.commands.get('woow.omnigent.configure')();assert.equal(cancel.calls.some(c=>c.action==='configure'),false);assert.equal(cancel.updates.length,0);
});
test('normal Open Web rejects sensitive URL components even when inserted directly in machine settings', async () => {
  for(const connector of ['paseo','omnigent']) for(const bad of ['https://operator:fixture-private@example.org','https://example.org/?token=fixture-private','https://example.org/#fixture-private','https://example.org/?','https://example.org/#','javascript:alert(1)','https://exa\nmple.org']) {
    const h=harness(connector);h.values.webUrl=bad;
    const result=await h.commands.get(`woow.${connector}.openWeb`)();assert.equal(result.ok,false);assert.equal(h.opened.length,0);
    assert.equal(JSON.stringify([h.logs,h.notices,h.posted,h.api.getPublicState()]).includes('fixture-private'),false);
  }
});
test('Omnigent form and machine settings expose backend and browser URLs separately', () => {
  const markup=html('omnigent');assert.ok(markup.includes('name="server"'));assert.ok(markup.includes('name="webUrl"'));assert.ok(markup.includes('Browser Web URL (optional)'));
  const property=require('../omnigent/package.json').contributes.configuration.properties['woow.omnigent.webUrl'];assert.equal(property.scope,'machine');assert.equal(property.default,'');
});

test('explicit MCP refresh stays on chosen conversation and describes queued native reload', async () => {
  const h=harness('omnigent',{refreshMcp:{ok:true,refresh:{state:'queued',toolsVerified:false}}});
  h.inputs.push('existing-session');
  await h.commands.get('woow.omnigent.refreshMcp')();
  assert.deepEqual(h.calls[0],{connector:'omnigent',action:'refreshMcp',sessionId:'existing-session'});
  assert.ok(h.notices.some(text=>text.includes('next turn boundary')));
  assert.ok(h.notices.every(text=>!text.includes('verification passed')));
  assert.ok(html('omnigent').includes('data-action="refreshMcp"'));
});
test('busy MCP refresh is visible and cancellation makes no runtime request', async () => {
  const h=harness('paseo',{refreshMcp:{ok:false,error:{code:'SESSION_BUSY'}}});
  h.inputs.push('existing-agent');await h.commands.get('woow.paseo.refreshMcp')();
  assert.ok(h.notices.some(text=>text.includes('Nothing was interrupted')));
  const cancelled=harness('paseo');await cancelled.commands.get('woow.paseo.refreshMcp')();
  assert.equal(cancelled.calls.length,0);
});

test('in-process inventory refresh does not claim a restart or tool execution', async()=>{
 const h=harness('omnigent',{refreshMcp:{ok:true,refresh:{state:'applied',inventoryVerified:true,toolsVerified:false}}});h.inputs.push('existing-pi-session');await h.commands.get('woow.omnigent.refreshMcp')();assert.ok(h.notices.some(x=>x.includes('inventory updated')));assert.ok(h.notices.every(x=>!x.includes('resumed')));assert.ok(h.notices.some(x=>x.includes('not yet verified')));
});

test('Claude reload receipt and uncertain submission have distinct honest notices', async()=>{
 const done=harness('omnigent',{refreshMcp:{ok:true,refresh:{state:'reloaded',reloadVerified:true,inventoryVerified:false,toolsVerified:false}}});
 done.inputs.push('existing-claude-session');await done.commands.get('woow.omnigent.refreshMcp')();
 assert.ok(done.notices.some(x=>x.includes('native reload completed')));
 assert.ok(done.notices.some(x=>x.includes('inventory and execution are not yet verified')));
 assert.ok(done.notices.every(x=>!x.includes('resumed')));
 const pending=harness('omnigent',{refreshMcp:{ok:false,error:{code:'MCP_RELOAD_SUBMISSION_UNKNOWN'}}});
 pending.inputs.push('existing-claude-session');await pending.commands.get('woow.omnigent.refreshMcp')();
 assert.ok(pending.notices.some(x=>x.includes('submission is uncertain')));
 assert.ok(pending.notices.some(x=>x.includes('not resent')));
 assert.equal(pending.calls.filter(x=>x.action==='refreshMcp').length,1);
});
