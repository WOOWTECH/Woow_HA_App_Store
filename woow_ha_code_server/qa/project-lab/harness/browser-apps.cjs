const fs=require('fs'),path=require('path'),assert=require('assert/strict'),crypto=require('crypto');
const config=require('./config.cjs');
const {root,packageRoot,makeRun}=config,output=makeRun('browser');
const {launch,loginIDE,checkedURL,waitForHealth}=require('./browser-support.cjs');
const base=checkedURL(process.argv[2]||'http://127.0.0.1:18750/').href,label=process.argv[3]||'apps';
assert.match(label,/^[a-zA-Z0-9_-]+$/,'label must be a safe filename');
const firstAndLast=items=>items.length>1?[items[0],items.at(-1)]:items;
const isRunRequest=(request,id)=>request.method()==='POST'&&new URL(request.url()).pathname.endsWith('/api/projects/'+id+'/run');
async function runFresh(page){
  const before=await page.locator('#status').getAttribute('data-run')||'';
  await page.locator('#run').click();
  await page.waitForFunction(previous=>{
    const s=document.querySelector('#status');
    return s.dataset.run&&s.dataset.run!==previous&&s.dataset.completedRun===s.dataset.run&&['true','false'].includes(s.dataset.ok);
  },before,{timeout:20000});
}
(async()=>{
  const report={at:new Date().toISOString(),label,rows:[],ok:false};let browser;
  try{
    browser=await launch();
    const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:1000}}),page=await context.newPage();
    page.setDefaultTimeout(20000);
    if(process.env.QA_IDE_URL)await loginIDE(page,process.env.QA_IDE_URL);
    await waitForHealth(context,base);
    await page.goto(base);
    assert.equal(await page.locator('.card').count(),50);
    await page.locator('#search').fill('p33');assert.equal(await page.locator('.card:visible').count(),1);await page.locator('#search').fill('');
    const manifest=JSON.parse(fs.readFileSync(path.join(packageRoot(),'evidence/package-manifest.json')));
    assert.deepEqual(manifest.map(p=>p.id).sort(),Array.from({length:50},(_,i)=>'p'+String(i+1).padStart(2,'0')));
    for(const pkg of manifest){
      const id=pkg.id,row={id};report.rows.push(row);
      try{
        await page.goto(new URL('app?id='+id,base).href);
        await page.waitForFunction(()=>document.querySelector('#input')?.value);
        const cases=JSON.parse(fs.readFileSync(path.join(root,'projects',id,'cases.json')));
        const positives=cases.filter(c=>c.error!==true&&Object.hasOwn(c,'expected')),negatives=cases.filter(c=>c.error===true);
        assert.ok(positives.length>=2&&negatives.length>=1,'contract requires two positive and one negative fixture');
        const valid=firstAndLast(positives),invalid=firstAndLast(negatives);
        row.functionalCaseNames=[];
        for(const c of valid){
          await page.locator('#input').fill(JSON.stringify(c.input));await runFresh(page);
          assert.equal(await page.locator('#status').getAttribute('data-ok'),'true',c.name);
          assert.deepEqual(JSON.parse(await page.locator('#output').getAttribute('data-result')),c.expected,c.name);
          row.functionalCaseNames.push(c.name);
        }
        row.functionalCases=valid.length;
        await page.locator('#save').click();const saved=await page.locator('#input').inputValue();
        await page.reload();await page.waitForFunction(()=>document.querySelector('#input')?.value);
        assert.equal(await page.locator('#input').inputValue(),saved);row.persisted=true;
        row.validationCases=[];
        for(const c of invalid){
          await page.locator('#input').fill(JSON.stringify(c.input));
          const [response]=await Promise.all([
            page.waitForResponse(response=>isRunRequest(response.request(),id),{timeout:20000}),
            runFresh(page)
          ]);
          assert.equal(response.status(),400,c.name+': expected a fresh validation response');
          assert.deepEqual(response.request().postDataJSON(),c.input);
          const rejected=await response.json();assert.ok(typeof rejected.error==='string'&&rejected.error.trim());
          assert.equal(await page.locator('#status').getAttribute('data-ok'),'false');
          assert.equal(await page.locator('#status').getAttribute('data-error-kind'),'request');
          assert.equal(await page.locator('#status').innerText(),rejected.error);
          assert.equal(await page.locator('#output').getAttribute('data-result'),null);
          row.validationCases.push({name:c.name,httpStatus:response.status(),message:rejected.error});
        }
        row.invalidRejected=true;
        await page.locator('#input').fill('{invalid');
        const expectedParseError=await page.evaluate(()=>{try{JSON.parse(document.querySelector('#input').value)}catch(e){return e.message}});
        assert.ok(expectedParseError);
        let apiRequests=0;
        const countRequest=request=>{if(isRunRequest(request,id))apiRequests++};
        page.on('request',countRequest);
        try{
          await runFresh(page);
          // Allow the browser's request events to settle before asserting no API call.
          await page.waitForTimeout(100);
          assert.equal(apiRequests,0,'malformed JSON must not reach the API');
          assert.equal(await page.locator('#status').getAttribute('data-ok'),'false');
          assert.equal(await page.locator('#status').getAttribute('data-error-kind'),'parse');
          assert.equal(await page.locator('#status').innerText(),expectedParseError);
          assert.equal(await page.locator('#output').getAttribute('data-result'),null);
          assert.equal(await page.locator('#output').innerText(),'');
        }finally{page.off('request',countRequest)}
        row.malformedJsonRejected=true;row.malformedJsonApiRequests=apiRequests;
        await page.locator('#reset').click();await runFresh(page);
        assert.equal(await page.locator('#status').getAttribute('data-ok'),'true');
        const result=JSON.parse(await page.locator('#output').getAttribute('data-result'));
        const exported=page.waitForEvent('download');await page.locator('#export').click();const d=await exported;
        const file=path.join(output,label+'-'+id+'-result.json');await d.saveAs(file);
        assert.deepEqual(JSON.parse(fs.readFileSync(file)),result);row.resultDownloaded=true;
        const downloading=page.waitForEvent('download');await page.locator('#source').click();const zip=await downloading;
        const dest=path.join(output,label+'-'+id+'.zip');await zip.saveAs(dest);
        assert.equal(crypto.createHash('sha256').update(fs.readFileSync(dest)).digest('hex'),pkg.sha256);
        row.sourceDownloadSha256=pkg.sha256;row.ok=true;
      }catch(e){row.ok=false;row.error=e.message.slice(0,1000)}

      if(Number(id.slice(1))%10===0)console.log(JSON.stringify({label,completed:report.rows.length,failed:report.rows.filter(x=>!x.ok).length}));
    }
    await page.setViewportSize({width:390,height:844});await page.goto(new URL('app?id=p33',base).href);
    await page.waitForFunction(()=>document.querySelector('#input')?.value);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    report.mobile=true;report.ok=report.rows.length===50&&report.rows.every(x=>x.ok);await context.close();
  }catch(e){report.error=e.message.slice(0,1400)}
  finally{
    if(browser)await browser.close();
    fs.writeFileSync(path.join(output,label+'-browser.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({output,label,ok:report.ok,projects:report.rows.length,error:report.error}));
    if(!report.ok)process.exitCode=1;
  }
})();
