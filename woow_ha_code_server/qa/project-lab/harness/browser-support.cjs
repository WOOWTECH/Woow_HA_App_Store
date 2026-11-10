'use strict';
const path=require('node:path');
function checkedURL(value) {
  const url=new URL(value);
  if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.hash||url.search)throw Error('Supply an HTTP(S) base URL without credentials, query or fragment');
  if(!url.pathname.endsWith('/'))url.pathname+='/';
  return url;
}
async function launch() {
  const moduleName=process.env.PLAYWRIGHT_MODULE||'playwright-core';
  const {chromium}=require(moduleName);
  const options={headless:process.env.QA_HEADED!=='1'};
  if(process.env.CHROME_EXECUTABLE)options.executablePath=path.resolve(process.env.CHROME_EXECUTABLE);
  // Sandbox stays enabled unless the operator explicitly opts out in their environment.
  options.chromiumSandbox=process.env.QA_BROWSER_NO_SANDBOX!=='1';
  if(process.env.QA_BROWSER_NO_SANDBOX==='1')options.args=['--no-sandbox'];
  return chromium.launch(options);
}
async function loginIDE(page,value) {
  await page.goto(checkedURL(value).href,{waitUntil:'domcontentloaded'});
  if(await page.locator('input[name=password]').count()) {
    const password=process.env.QA_IDE_PASSWORD;
    if(!password)throw Error('This IDE requires explicit QA_IDE_PASSWORD');
    await page.locator('input[name=password]').fill(password);
    await page.locator('input[type=submit]').click();
  }
}
async function waitForHealth(context,base) {
  const deadline=Date.now()+60000;
  while(Date.now()<deadline) {
    try {
      const response=await context.request.get(new URL('healthz',base).href,{timeout:3000,maxRedirects:0});
      try {
        if(response.ok()) {
          const body=await response.json();
          if(body.ok===true&&body.projects===50)return;
        }
      }finally{await response.dispose();}
    }catch{}
    await new Promise(resolve=>setTimeout(resolve,250));
  }
  throw Error('Preview did not become healthy with 50 projects within 60 seconds');
}
module.exports={checkedURL,launch,loginIDE,waitForHealth};
