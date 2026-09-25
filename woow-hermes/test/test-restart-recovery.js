// An add-on restart must look the same in the sidebar as on the LAN port:
// the open chat and live feeds reconnect by themselves and nobody is logged out.
//   RESTART_CMD='<command that restarts the add-on>' \
//   node test-restart-recovery.js <out dir> <password file> <label>=<base/>[,<ingress_session>] ...
// Each base gets its own browser context with /chat and /sessions open. After
// RESTART_CMD, every page must still be logged in, and the chat must reopen its
// sockets without a reload instead of claiming the session ended.
const { chromium } = require('/home/woowtech-ai-coder/.claude/skills/playwright-skill/node_modules/playwright');
const { spawn } = require('child_process');
const assert = require('assert');
const fs = require('fs');

const [OUT, pwFile, ...targets] = process.argv.slice(2);
const PW = fs.readFileSync(pwFile, 'utf8').trim();
const t0 = Date.now();
const now = () => Date.now() - t0;

function watch(page, key, state) {
  const s = (state[key] = { closes: [], opens: [], ended: false, url: null });
  page.on('console', (m) => {
    const hit = /\[chat\] PTY WebSocket closed code=(\d+)/.exec(m.text());
    if (hit) s.closes.push({ t: now(), code: Number(hit[1]) });
  });
  page.on('websocket', (ws) => {
    // Ingress paths are /api/hassio_ingress/<token>/api/...: match the tail.
    const hit = /\/api\/(pty|events|ws)$/.exec(new URL(ws.url()).pathname);
    if (hit) s.opens.push({ t: now(), path: `/api/${hit[1]}` });
  });
  return s;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: '/home/woowtech-ai-coder/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome' });
  const state = {};
  const pages = {};
  for (const target of targets) {
    const [label, rest] = target.split('=');
    const [base, session] = rest.split(',');
    const ctx = await browser.newContext({ viewport: { width: 1200, height: 800 } });
    if (session) {
      await ctx.addCookies([{ name: 'ingress_session', value: session, domain: new URL(base).hostname, path: '/api/hassio_ingress/' }]);
    }
    const login = await ctx.newPage();
    await login.goto(base, { waitUntil: 'domcontentloaded' });
    await login.fill('input[name=username]', 'admin');
    await login.fill('input[name=password]', PW);
    await login.click('button[type=submit]');
    await login.waitForURL((u) => !/\/login/.test(new URL(u).pathname), { timeout: 30000 });
    await login.close();
    for (const route of ['chat', 'sessions']) {
      const page = await ctx.newPage();
      const key = `${label}:${route}`;
      watch(page, key, state);
      await page.goto(base + route, { waitUntil: 'domcontentloaded' });
      pages[key] = { page, base };
    }
  }
  await new Promise((r) => setTimeout(r, 15000));
  const tRestart = now();
  for (const s of Object.values(state)) s.opensBefore = s.opens.length;

  const restart = spawn('sh', ['-c', process.env.RESTART_CMD], { stdio: 'inherit' });
  await new Promise((r) => restart.on('exit', r));
  // Wait until every page that had sockets has reopened them, up to 3 minutes.
  const hadSockets = (s) => s.opensBefore > 0;
  for (let i = 0; i < 180; i++) {
    if (Object.values(state).filter(hadSockets).every((s) => s.opens.length > s.opensBefore)) break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  await new Promise((r) => setTimeout(r, 10000));

  const result = {};
  for (const [key, { page }] of Object.entries(pages)) {
    const s = state[key];
    const text = await page.evaluate(() => document.body.innerText).catch(() => '');
    const reopened = s.opens.slice(s.opensBefore);
    result[key] = {
      hadSockets: hadSockets(s),
      closeCodes: s.closes.filter((c) => c.t >= tRestart).map((c) => c.code),
      reconnectedAfterMs: reopened.length ? reopened[0].t - tRestart : null,
      reopened: [...new Set(reopened.map((o) => o.path))],
      sessionEnded: /\[session ended/.test(text),
      loggedIn: !/\/login/.test(new URL(page.url()).pathname),
    };
    await page.screenshot({ path: `${OUT}/${key.replace(':', '-')}.png` }).catch(() => {});
  }
  fs.writeFileSync(`${OUT}/restart-recovery.json`, JSON.stringify(result, null, 1));
  console.log(JSON.stringify(result, null, 1));
  await browser.close();

  for (const [key, r] of Object.entries(result)) {
    assert.ok(r.loggedIn, `${key}: still logged in after the restart`);
    if (r.hadSockets) assert.ok(r.reconnectedAfterMs !== null, `${key}: sockets reopened without a reload`);
    if (key.endsWith(':chat')) {
      assert.equal(r.sessionEnded, false, `${key}: chat does not claim the session ended`);
      // Hermes says 1012 (restarting) when it gets to close first, and the
      // page sees 1006 when it does not; both make the chat reconnect.
      assert.ok(r.closeCodes.every((c) => c === 1012 || c === 1006), `${key}: unexpected close ${r.closeCodes}`);
    }
  }
  console.log('restart recovery: ok');
})().catch((e) => { console.error(e.message); process.exit(1); });
