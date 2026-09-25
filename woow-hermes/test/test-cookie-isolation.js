// The LAN port and the HA sidebar must keep separate Hermes sessions even when
// they share a host (cookies are not scoped by port).
//   node test-cookie-isolation.js <direct base/> <ingress base/> <password file> [cookie header for the ingress host]
const { chromium } = require('/home/woowtech-ai-coder/.claude/skills/playwright-skill/node_modules/playwright');
const assert = require('assert');
const fs = require('fs');

const [D, I, pwFile, haCookie] = process.argv.slice(2);
const PW = fs.readFileSync(pwFile, 'utf8').trim();

async function login(page, base) {
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.fill('input[name=username]', 'admin');
  await page.fill('input[name=password]', PW);
  await page.click('button[type=submit]');
  await page.waitForURL(u => !/\/login/.test(new URL(u).pathname), { timeout: 20000 });
}

async function loggedIn(page, base) {
  await page.goto(base + 'sessions', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  return !/\/login/.test(new URL(page.url()).pathname);
}

async function logout(page, base) {
  const r = await page.evaluate(async (b) => (await fetch(b + 'auth/logout', { method: 'POST' })).status, base);
  assert.ok(r < 400, `logout returned ${r}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/home/woowtech-ai-coder/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome' });
  const ctx = await browser.newContext();
  if (haCookie) {
    const u = new URL(I);
    await ctx.addCookies([{ name: 'ingress_session', value: haCookie, domain: u.hostname, path: '/api/hassio_ingress/' }]);
  }
  const d = await ctx.newPage();
  const i = await ctx.newPage();
  const results = {};

  await login(d, D);
  results.sidebarNeedsOwnLogin = !(await loggedIn(i, I));
  assert.ok(results.sidebarNeedsOwnLogin, 'a LAN-port login must not log the sidebar in');

  await login(i, I);
  results.bothLoggedIn = (await loggedIn(d, D)) && (await loggedIn(i, I));
  assert.ok(results.bothLoggedIn);

  await logout(i, I);
  results.sidebarLogoutSticks = !(await loggedIn(i, I));
  results.lanUnaffectedBySidebarLogout = await loggedIn(d, D);
  assert.ok(results.sidebarLogoutSticks, 'sidebar logout must log the sidebar out');
  assert.ok(results.lanUnaffectedBySidebarLogout, 'sidebar logout must not touch the LAN session');

  await login(i, I);
  await logout(d, D);
  results.sidebarUnaffectedByLanLogout = await loggedIn(i, I);
  assert.ok(results.sidebarUnaffectedByLanLogout, 'LAN logout must not touch the sidebar session');

  const names = (await ctx.cookies()).map(c => `${c.name}@${c.path}`).filter(n => /hermes/.test(n));
  results.cookieNames = names;
  console.log(JSON.stringify(results, null, 1));
  console.log('cookie isolation: ok');
  await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });
