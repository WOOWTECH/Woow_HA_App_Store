'use strict';
// Optional assertions for an operator-owned, already authenticated API/page.
// No login lookup, session creation, prompt submission, approval or model mutation.
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const crypto=require('node:crypto');

async function assertConversation({api,page,sessionId,expectedHost,expectedModel,marker}) {
  assert.ok(sessionId&&expectedHost&&expectedModel&&marker,'Explicit expectations are required');
  const sid=encodeURIComponent(sessionId);
  const session=await api('GET','/v1/sessions/'+sid);
  assert.equal(session.host_id,expectedHost);
  assert.equal(session.llm_model,expectedModel);
  const items=await api('GET','/v1/sessions/'+sid+'/items?limit=100&order=desc');
  assert.ok(items.data.some(item=>item.type==='message'&&item.role==='assistant'&&
    (item.content||[]).some(part=>(part.text||'').includes(marker))),'Assistant marker must be present in API history');
  const bubble=page.locator('[data-testid="message-bubble"][data-role="assistant"]')
    .filter({has:page.getByTestId('assistant-text-section').filter({hasText:marker})});
  await bubble.first().waitFor({timeout:45000});
  return bubble.first();
}

async function assertEffectiveModel({api,sessionId,expectedModel}) {
  const deadline=Date.now()+60000;
  while(Date.now()<deadline) {
    const session=await api('GET','/v1/sessions/'+encodeURIComponent(sessionId));
    if(session.model_override===expectedModel&&session.llm_model===expectedModel)return;
    await new Promise(resolve=>setTimeout(resolve,500));
  }
  throw Error('Requested model did not become effective');
}

async function assertAssistantDownload({context,page,link,expectedURL,expectedSha256}) {
  assert.match(expectedSha256,/^[a-f0-9]{64}$/);
  assert.equal(await link.getAttribute('href'),expectedURL);
  const listeners=new Map();
  let timer,resolveDownload,rejectDownload;
  const pending=new Promise((resolve,reject)=>{resolveDownload=resolve;rejectDownload=reject;});
  pending.catch(()=>{});
  const watch=p=>{const listener=d=>resolveDownload(d);listeners.set(p,listener);p.on('download',listener);};
  watch(page);
  context.on('page',watch);
  timer=setTimeout(()=>rejectDownload(Error('Assistant link produced no download')),60000);
  try {
    await link.click();
    const download=await pending;
    assert.equal(await download.failure(),null);
    try {
      const bytes=await fs.readFile(await download.path());
      assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),expectedSha256);
    }finally{await download.delete();}
  }finally{
    clearTimeout(timer);
    context.off('page',watch);
    for(const [p,listener] of listeners)p.off('download',listener);
  }
}
module.exports={assertConversation,assertEffectiveModel,assertAssistantDownload};
