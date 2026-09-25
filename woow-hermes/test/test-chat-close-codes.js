// The chat must end the same way through the sidebar as on the LAN port.
//   KILL_TUI='<command that kills the chat process>' [HA_INGRESS_SESSION=<real HA cookie>] \
//   node test-chat-close-codes.js <base/> <password file> [screenshot dir]
// Tab A opens /chat, tab B opens /chat in the same browser (same keep-alive
// token) and takes it over: tab A must get 4409 and stay quiet. Then the
// agent process dies: tab B must get 4410 and "[session ended]".
const { chromium } = require('/home/woowtech-ai-coder/.claude/skills/playwright-skill/node_modules/playwright');
const assert = require('assert');
const fs = require('fs');

const [BASE, pwFile, shots] = process.argv.slice(2);
const PW = fs.readFileSync(pwFile, 'utf8').trim();

function closeCodes(page) {
  const codes = [];
  page.on('console', (m) => {
    const hit = /\[chat\] PTY WebSocket closed code=(\d+)/.exec(m.text());
    if (hit) codes.push(Number(hit[1]));
  });
  return codes;
}

async function openChat(page) {
  const ready = page.waitForEvent('websocket', (ws) => /\/api\/pty/.test(ws.url()), { timeout: 30000 })
    .then((ws) => new Promise((resolve) => ws.once('framereceived', resolve)));
  await page.goto(BASE + 'chat', { waitUntil: 'domcontentloaded' });
  await ready;
  await page.waitForTimeout(4000);
}

async function terminalText(page) {
  return page.evaluate(() => Array.from(document.querySelectorAll('.xterm-rows > div'))
    .map((d) => d.textContent).join('\n'));
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/home/woowtech-ai-coder/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 800 } });
  // Real HA: the HA ingress session cookie (from ha_ingress_session.py).
  if (process.env.HA_INGRESS_SESSION) {
    await ctx.addCookies([{ name: 'ingress_session', value: process.env.HA_INGRESS_SESSION,
      domain: new URL(BASE).hostname, path: '/api/hassio_ingress/' }]);
  }
  const a = await ctx.newPage();
  await a.goto(BASE, { waitUntil: 'domcontentloaded' });
  await a.fill('input[name=username]', 'admin');
  await a.fill('input[name=password]', PW);
  await a.click('button[type=submit]');
  await a.waitForURL((u) => !/\/login/.test(new URL(u).pathname), { timeout: 20000 });

  const codesA = closeCodes(a);
  await openChat(a);
  const b = await ctx.newPage();
  const codesB = closeCodes(b);
  await openChat(b);
  await a.waitForTimeout(3000);
  const textA = await terminalText(a);

  // The dashboard chat restarts itself on /exit and Ctrl+C, so end the agent
  // the way a crash would: kill the TUI process (KILL_TUI, run by the harness).
  require('child_process').execSync(process.env.KILL_TUI, { stdio: 'inherit' });
  for (let i = 0; i < 20 && !codesB.includes(4410); i++) await b.waitForTimeout(500);
  await b.waitForTimeout(1500);
  const textB = await terminalText(b);
  if (shots) {
    const tag = /hassio_ingress/.test(BASE) ? 'ingress' : 'direct';
    await a.screenshot({ path: `${shots}/${tag}-a-superseded.png` });
    await b.screenshot({ path: `${shots}/${tag}-b-exit.png` });
    fs.writeFileSync(`${shots}/${tag}-b-terminal.txt`, textB);
  }

  const result = {
    supersededTab: { codes: codesA, sessionEnded: /\[session ended/.test(textA) },
    exitedTab: { codes: codesB, sessionEnded: /\[session ended\]/.test(textB), withCode: /\[session ended \(code/.test(textB) },
  };
  console.log(JSON.stringify(result));
  await browser.close();
  assert.deepEqual(codesA, [4409], 'the tab that was taken over gets 4409');
  assert.equal(result.supersededTab.sessionEnded, false, 'and does not claim the session ended');
  assert.equal(codesB[codesB.length - 1], 4410, 'the tab whose agent exited gets 4410');
  assert.equal(result.exitedTab.withCode, false, '"[session ended]" without a raw close code');
  console.log('chat close codes: ok');
})().catch((e) => { console.error(e.message); process.exit(1); });
