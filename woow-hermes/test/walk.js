// Hermes dashboard page walk: direct vs emulated HA ingress.
// usage: node walk.js <label> <baseUrl-with-trailing-slash> <outdir> [password-file]
const { chromium } = require('/home/woowtech-ai-coder/.claude/skills/playwright-skill/node_modules/playwright');
const fs = require('fs');
const path = require('path');

const [label, base, outdir, pwFile] = process.argv.slice(2);
const PW = fs.readFileSync(pwFile || path.join(__dirname, '.pw'), 'utf8').trim();
const baseUrl = new URL(base);
const prefix = baseUrl.pathname.replace(/\/$/, ''); // "" for direct
const ROUTES = ['/', '/chat', '/sessions', '/files', '/analytics', '/models', '/logs', '/cron', '/skills',
  '/plugins', '/mcp', '/channels', '/webhooks', '/pairing', '/profiles', '/config', '/env', '/system', '/docs'];

const log = [];      // every request/response
const wsLog = [];    // websockets
const consoleLog = [];
let currentPage = 'boot';

function classify(u) {
  try {
    const x = new URL(u);
    if (x.origin !== baseUrl.origin) return 'external';
    if (prefix && !x.pathname.startsWith(prefix + '/') && x.pathname !== prefix + '/') return 'ESCAPED';
    return 'ok';
  } catch { return 'other'; }
}

(async () => {
  fs.mkdirSync(outdir, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME || '/home/woowtech-ai-coder/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();

  page.on('request', r => {
    log.push({ page: currentPage, t: 'req', method: r.method(), url: r.url(), type: r.resourceType(), cls: classify(r.url()) });
  });
  page.on('response', async r => {
    const req = r.request();
    const hdr = r.headers();
    log.push({ page: currentPage, t: 'res', method: req.method(), url: r.url(), type: req.resourceType(), status: r.status(),
      cls: classify(r.url()), location: hdr['location'] || undefined, setCookie: hdr['set-cookie'] || undefined,
      probe: hdr['x-probe'] || undefined, ctype: hdr['content-type'] });
  });
  page.on('requestfailed', r => {
    log.push({ page: currentPage, t: 'fail', method: r.method(), url: r.url(), type: r.resourceType(), err: r.failure() && r.failure().errorText, cls: classify(r.url()) });
  });
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') consoleLog.push({ page: currentPage, type: m.type(), text: m.text().slice(0, 400) }); });
  page.on('pageerror', e => consoleLog.push({ page: currentPage, type: 'pageerror', text: String(e).slice(0, 400) }));
  page.on('websocket', ws => {
    const rec = { page: currentPage, url: ws.url(), cls: classify(ws.url().replace(/^ws/, 'http')), rx: 0, tx: 0, rxBytes: 0, closed: false, error: null, firstRx: null };
    wsLog.push(rec);
    ws.on('framereceived', f => { rec.rx++; const s = typeof f.payload === 'string' ? f.payload : f.payload.toString('utf8'); rec.rxBytes += s.length; if (!rec.firstRx) rec.firstRx = s.slice(0, 160); });
    ws.on('framesent', () => rec.tx++);
    ws.on('close', () => rec.closed = true);
    ws.on('socketerror', e => rec.error = String(e));
  });

  // ---- login
  currentPage = 'login';
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  const loginUrl = page.url();
  let loginOk = false;
  try {
    await page.fill('input[name=username]', 'admin', { timeout: 5000 });
    await page.fill('input[name=password]', PW);
    await page.screenshot({ path: path.join(outdir, '00-login.png') });
    await page.click('button[type=submit]');
    await page.waitForTimeout(4000);
    loginOk = !/\/login(\?|$)/.test(new URL(page.url()).pathname + new URL(page.url()).search) && classify(page.url()) !== 'ESCAPED';
  } catch (e) { consoleLog.push({ page: 'login', type: 'probe', text: 'login form interaction failed: ' + e.message }); }
  const afterLogin = page.url();
  const afterLoginText = (await page.textContent('body').catch(() => '')).slice(0, 200);
  const cookies = await ctx.cookies();
  await page.screenshot({ path: path.join(outdir, '01-after-login.png') });

  // If the UI login escaped, fall back to an API login so the rest of the walk still runs
  // (records the failure but still measures pages).
  let fallbackLogin = false;
  if (!loginOk) {
    currentPage = 'login-fallback';
    const r = await page.request.post(new URL('auth/password-login', base).href, {
      data: { provider: 'basic', username: 'admin', password: PW, next: '' } }).catch(e => ({ status: () => 'ERR ' + e.message }));
    fallbackLogin = r.status();
  }

  // ---- discover nav links (includes plugin tabs)
  currentPage = 'discover';
  await page.goto(new URL('chat', base).href, { waitUntil: 'domcontentloaded' }).catch(() => {});
  await page.waitForTimeout(3000);
  const navHrefs = await page.$$eval('a[href]', as => [...new Set(as.map(a => a.getAttribute('href')))]).catch(() => []);
  const navAbs = await page.$$eval('a[href]', as => [...new Set(as.map(a => a.href))]).catch(() => []);
  const pluginRoutes = navHrefs.filter(h => h && h.startsWith(prefix + '/') || (h && !prefix && h.startsWith('/')))
    .map(h => h.slice(prefix.length)).filter(h => !ROUTES.includes(h) && !h.startsWith('/docs/') && !h.includes('#') && h.length < 60);

  const routes = [...ROUTES, ...new Set(pluginRoutes)];
  const pages = [];
  let i = 2;
  for (const r of routes) {
    currentPage = r;
    const target = new URL(r.replace(/^\//, ''), base).href;
    let status = null;
    // The walk compares a fresh open of each page. In the sidebar the ingress
    // root restores the tab's last page (a reload of the HA panel), which
    // test-reload-route.js covers; start the root from a clean tab state.
    if (r === '/') await page.evaluate(() => { try { sessionStorage.clear(); } catch (e) {} }).catch(() => {});
    try {
      const resp = await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 20000 });
      status = resp && resp.status();
    } catch (e) { status = 'ERR ' + e.message.slice(0, 80); }
    await page.waitForTimeout(r === '/chat' ? 9000 : 3500);
    const finalUrl = page.url();
    const bodyText = ((await page.textContent('body').catch(() => '')) || '').replace(/\s+/g, ' ').slice(0, 160);
    const shot = String(i++).padStart(2, '0') + '-' + (r.replace(/\//g, '_') || '_root') + '.png';
    await page.screenshot({ path: path.join(outdir, shot) }).catch(() => {});
    pages.push({ route: r, status, finalUrl, finalCls: classify(finalUrl), bodyText, shot });
  }

  // ---- raw <a href> check: any same-origin link escaping the prefix?
  const escapingLinks = navAbs.filter(u => classify(u) === 'ESCAPED');

  // ---- logout via the real SPA button (api.logout -> POST ${BASE}/auth/logout -> location.assign)
  currentPage = 'logout';
  let logoutUrl = null;
  try {
    await page.goto(new URL('sessions', base).href, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    await page.click('button[aria-label="Log out"]', { timeout: 5000 });
    await page.waitForTimeout(3000);
    logoutUrl = { finalUrl: page.url(), cls: classify(page.url()), body: ((await page.textContent('body').catch(()=>''))||'').replace(/\s+/g,' ').slice(0,80) };
    await page.screenshot({ path: path.join(outdir, '99-after-logout.png') });
  } catch (e) { logoutUrl = 'ERR ' + e.message.slice(0, 120); }

  await browser.close();

  const res = log.filter(x => x.t === 'res');
  const summary = {
    label, base, prefix, loginUrl, loginOk, afterLogin, afterLoginText, fallbackLogin,
    cookies: cookies.map(c => ({ name: c.name, path: c.path, secure: c.secure, sameSite: c.sameSite, httpOnly: c.httpOnly })),
    counts: {
      requests: log.filter(x => x.t === 'req').length,
      responses: res.length,
      non2xx3xx: res.filter(x => x.status >= 400).length,
      escaped: log.filter(x => x.t === 'req' && x.cls === 'ESCAPED').length,
      failed: log.filter(x => x.t === 'fail').length,
      websockets: wsLog.length,
      eventsource: log.filter(x => x.t === 'req' && x.type === 'eventsource').length,
    },
    errors: res.filter(x => x.status >= 400).map(x => `${x.page} ${x.status} ${x.method} ${x.url}${x.probe ? ' [' + x.probe + ']' : ''}`),
    escapedReqs: [...new Set(log.filter(x => x.t === 'req' && x.cls === 'ESCAPED').map(x => `${x.page} ${x.method} ${x.type} ${x.url}`))],
    failedReqs: log.filter(x => x.t === 'fail').map(x => `${x.page} ${x.method} ${x.type} ${x.url} ${x.err}`),
    redirects: res.filter(x => x.location).map(x => `${x.page} ${x.status} ${x.url} -> ${x.location}`),
    websockets: wsLog,
    pages, escapingLinks, logout: logoutUrl,
    console: consoleLog.slice(0, 80),
  };
  fs.writeFileSync(path.join(outdir, 'requests.jsonl'), log.map(x => JSON.stringify(x)).join('\n'));
  fs.writeFileSync(path.join(outdir, 'summary.json'), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify({ label, loginOk, afterLogin, fallbackLogin, counts: summary.counts, escapingLinks: escapingLinks.length }, null, 1));
})();
