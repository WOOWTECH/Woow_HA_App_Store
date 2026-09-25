// A reload keeps the current page, on the LAN port and in the sidebar.
//   node test-reload-route.js direct <base/> <password file>
//   node test-reload-route.js root <ingress base/> <password file> [ingress_session]
//   node test-reload-route.js panel <panel URL> <ingress base/> <password file> [ingress_session]
// "panel" loads the dashboard in an iframe the way the HA panel does, moves to
// Skills inside it, reloads the whole panel page (F5 in Home Assistant) and
// checks the iframe comes back on Skills.
const { chromium } = require('/home/woowtech-ai-coder/.claude/skills/playwright-skill/node_modules/playwright');
const assert = require('assert');
const fs = require('fs');

const [mode, ...args] = process.argv.slice(2);

async function signIn(frame, pw) {
  await frame.waitForSelector('input[name=username]', { timeout: 30000 });
  await frame.fill('input[name=username]', 'admin');
  await frame.fill('input[name=password]', pw);
  await frame.click('button[type=submit]');
}

async function goToSkills(frame) {
  await frame.click('a[href$="/skills"]', { timeout: 30000 });
  await frame.waitForFunction(() => location.pathname.endsWith('/skills'), null, { timeout: 15000 });
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/home/woowtech-ai-coder/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 800 } });
  const page = await ctx.newPage();
  let after;
  if (mode === 'direct' || mode === 'root') {
    const [base, pwFile, session] = args;
    if (session) {
      await ctx.addCookies([{ name: 'ingress_session', value: session, domain: new URL(base).hostname, path: '/api/hassio_ingress/' }]);
    }
    await page.goto(base, { waitUntil: 'domcontentloaded' });
    await signIn(page, fs.readFileSync(pwFile, 'utf8').trim());
    await page.waitForURL((u) => !/\/login/.test(new URL(u).pathname), { timeout: 30000 });
    await goToSkills(page);
    // "root": what the HA panel does on a reload, in the same tab.
    if (mode === 'root') await page.goto(base, { waitUntil: 'domcontentloaded' });
    else await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(4000);
    after = new URL(page.url()).pathname;
  } else {
    const [panel, base, pwFile, session] = args;
    if (session) {
      await ctx.addCookies([{ name: 'ingress_session', value: session, domain: new URL(base).hostname, path: '/api/hassio_ingress/' }]);
    }
    const panelUrl = `${panel}?src=${encodeURIComponent(base)}`;
    const frameOf = () => page.frames().find((f) => f.url().startsWith(base));
    await page.goto(panelUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelector('iframe'), null, { timeout: 15000 });
    for (let i = 0; i < 30 && !frameOf(); i++) await page.waitForTimeout(500);
    await signIn(frameOf(), fs.readFileSync(pwFile, 'utf8').trim());
    await frameOf().waitForFunction(() => !/\/login/.test(location.pathname), null, { timeout: 30000 });
    await goToSkills(frameOf());
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(6000);
    after = new URL(frameOf().url()).pathname;
  }
  await browser.close();
  console.log(JSON.stringify({ mode, afterReload: after.replace(/\/api\/hassio_ingress\/[^/]+/, '<ingress>') }));
  assert.ok(after.endsWith('/skills'), `after a reload the page is ${after}, not Skills`);
  console.log('reload keeps the page: ok');
})().catch((e) => { console.error(e.message); process.exit(1); });
