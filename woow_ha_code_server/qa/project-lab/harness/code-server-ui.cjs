'use strict';
// Optional live adapter. Only newly allocated evidence files are edited.
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const config=require('./config.cjs');
const {launch,loginIDE,checkedURL}=require('./browser-support.cjs');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const quote=value=>"'"+value.replace(/'/g,"'\\''")+"'";

async function command(page,name) {
  await page.keyboard.press('Escape');
  await page.keyboard.press('Control+Shift+P');
  const input=page.locator('.quick-input-widget');
  await input.waitFor();
  await input.locator('input').first().fill('>'+name);
  await input.locator('.monaco-list-row').filter({hasText:name}).first().click();
  await input.waitFor({state:'hidden'});
}

async function openFile(page,relative,expectedDirectory) {
  await page.keyboard.press('Control+p');
  const picker=page.locator('.quick-input-widget');
  await picker.waitFor();
  await picker.locator('input').first().fill(relative);
  const row=picker.locator('.monaco-list-row').filter({hasText:expectedDirectory}).first();
  await row.waitFor({timeout:60000});
  await row.click();
  await picker.waitFor({state:'hidden'});
  const tab=page.locator('.tabs-container .tab.active').last();
  await tab.waitFor();
  assert.ok(((await tab.getAttribute('aria-label'))||await tab.innerText()).includes(path.posix.basename(relative)));
  const editor=page.locator('.part.editor .monaco-editor:visible .view-lines').last();
  await editor.waitFor();
  await page.waitForFunction(()=>[...document.querySelectorAll('.part.editor .monaco-editor .view-lines')]
    .some(e=>e.checkVisibility()&&e.textContent.trim().length>0),null,{timeout:60000});
  const crumbs=page.locator('.breadcrumbs-control').last();
  await crumbs.filter({hasText:expectedDirectory}).waitFor({timeout:15000});
  // The basename alone cannot distinguish the fifty app.mjs files.
  assert.ok((await crumbs.innerText()).split(/\s+/).includes(expectedDirectory),
    'Editor breadcrumbs must identify the exact project/directory');
  return editor;
}

async function exercise(page,workspace,nonce) {
  const local=process.env.QA_IDE_LOCAL_WORKSPACE;
  assert.ok(local,'Set QA_IDE_LOCAL_WORKSPACE to an explicit local mount of the IDE workspace');
  const evidence=path.join(path.resolve(local),'evidence');
  await fs.mkdir(evidence,{recursive:true});
  assert.ok(!(await fs.lstat(evidence)).isSymbolicLink(),'evidence must not be a symlink');
  const fixture=await fs.mkdtemp(path.join(evidence,'ide-fixture-'));
  const dirname=path.basename(fixture),file=path.join(fixture,'notes.txt');
  const before='Portable IDE save verification.\n',marker='saved-through-editor-'+nonce;
  await fs.writeFile(file,before,{flag:'wx'});
  const editor=await openFile(page,'evidence/'+dirname+'/notes.txt',dirname);
  await editor.click();
  await page.keyboard.press('Control+End');
  await page.keyboard.type(marker+'\n');
  await page.keyboard.press('Control+s');
  const deadline=Date.now()+15000;
  let saved;
  while(Date.now()<deadline) {
    saved=await fs.readFile(file,'utf8');
    if(saved.replace(/\r\n/g,'\n')===before+marker+'\n')break;
    await delay(200);
  }
  assert.equal(saved.replace(/\r\n/g,'\n'),before+marker+'\n','New UI edit must be observed on disk');

  // A unique nonce and a newly created receipt reject stale prior test reports.
  const remoteEvidence=path.posix.join(workspace,'evidence');
  const remoteHarness=path.posix.join(workspace,'harness','ide-task.mjs');
  const line='QA_ROOT='+quote(workspace)+' QA_OUTPUT='+quote(remoteEvidence)+' node '+quote(remoteHarness)+' '+quote(nonce);
  await command(page,'Terminal: Create New Terminal');
  const terminal=page.locator('.terminal-wrapper textarea').last();
  await terminal.waitFor({timeout:20000});
  await terminal.focus();
  await page.keyboard.type(line,{delay:2});
  await page.keyboard.press('Enter');
  const receiptDeadline=Date.now()+240000;
  let receipt;
  while(Date.now()<receiptDeadline) {
    for(const name of await fs.readdir(evidence)) {
      if(!name.startsWith('project-lab-ide-terminal-'))continue;
      try {
        const candidate=JSON.parse(await fs.readFile(path.join(evidence,name,'receipt.json'),'utf8'));
        if(candidate.nonce===nonce)receipt=candidate;
      }catch{}
    }
    if(receipt)break;
    await delay(500);
  }
  assert.equal(receipt?.nonce,nonce,'Fresh integrated-terminal receipt required');
  assert.equal(receipt.ok,true);
  assert.equal(receipt.exitCode,0);
  assert.equal(receipt.projects,50);
  assert.equal(receipt.projectTestRunners,50);
  return {savedFileVerified:true,terminalInvoked:true,terminalReceiptVerified:true};
}

(async()=>{
  const output=config.makeRun('ide'),report={ok:false,files:[],exercise:process.env.QA_IDE_EXERCISE==='1'};
  let browser;
  try {
    const base=checkedURL(process.env.QA_IDE_URL),workspace=process.env.QA_IDE_WORKSPACE;
    assert.ok(workspace&&path.posix.isAbsolute(workspace),'Set QA_IDE_WORKSPACE to the explicit remote suite directory');
    browser=await launch();
    const context=await browser.newContext({viewport:{width:1500,height:1100}}),page=await context.newPage();
    page.setDefaultTimeout(20000);
    await loginIDE(page,base.href);
    base.searchParams.set('folder',workspace);
    await page.goto(base.href,{waitUntil:'domcontentloaded'});
    await page.locator('.monaco-workbench').waitFor({timeout:60000});
    // Workspace trust is configured manually; no trust or permission auto-approval.
    await page.keyboard.press('Escape');
    for(let n=1;n<=50;n++) {
      const id='p'+String(n).padStart(2,'0');
      await openFile(page,'projects/'+id+'/app.mjs',id);
      report.files.push({id,opened:true,breadcrumbsVerified:true});
    }
    if(process.env.QA_IDE_CONNECTOR_COMMAND) {
      await command(page,process.env.QA_IDE_CONNECTOR_COMMAND);
      const deadline=Date.now()+60000;
      let frame;
      while(Date.now()<deadline&&!frame) {
        for(const candidate of page.frames()) {
          if(await candidate.locator('#phase').count().catch(()=>0)){frame=candidate;break;}
        }
        if(!frame)await delay(250);
      }
      assert.ok(frame,'Connector webview must appear');
      await frame.waitForFunction(()=>document.querySelector('#engines tr')&&document.querySelector('[data-action=status]')?.disabled===false);
      assert.match(await frame.locator('#phase').innerText(),/^Connection:\s*connected$/);
      const engines=await frame.locator('#engines').innerText();
      for(const expected of (process.env.QA_IDE_EXPECT_ENGINES||'').split(',').filter(Boolean))assert.ok(engines.includes(expected));
      report.connectorVerified=true;
    }
    if(report.exercise)Object.assign(report,await exercise(page,workspace,crypto.randomBytes(16).toString('hex')));
    report.ok=report.files.length===50;
    await context.close();
  } catch(error) {
    // Browser exception messages may contain endpoints, DOM content or account data.
    report.errorType=error.name;
    process.exitCode=1;
  } finally {
    if(browser)await browser.close();
    await fs.writeFile(path.join(output,'ide.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({output,ok:report.ok,files:report.files.length,exercise:report.exercise,errorType:report.errorType}));
  }
})();
