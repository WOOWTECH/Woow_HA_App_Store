import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { handle } from '../index.mjs';
import { launchBrowser, freshPage, probeOfficial, pairBrowser, openProjectInBrowser, BrowserCheckError, safeFailure } from './browser-support.mjs';

let browser, root;
try {
  browser = await launchBrowser();
  const { page } = await freshPage(browser);
  const official = await probeOfficial(page);
  if (!process.env.WOOW_PASEO_RUNTIME_DIR) {
    process.stdout.write(JSON.stringify({ ok: true, official, daemonPairingTested: false, realModelsTested: false }) + '\n');
  } else {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'woow-paseo-browser-'));
    Object.assign(process.env, {
      HOME: path.join(root, 'home'), PI_AGENT_DATA_DIR: path.join(root, 'agents'),
      PI_CODING_AGENT_DIR: path.join(root, 'agents'), CLAUDE_CONFIG_DIR: path.join(root, 'agents/claude'),
      CODEX_HOME: path.join(root, 'agents/codex'), WOOW_CONNECTOR_DATA_DIR: path.join(root, 'connectors'),
      WOOW_PASEO_PORT: '28669', PATH: '/usr/bin:/bin',
    });
    for (const key of Object.keys(process.env)) if (/TOKEN|PASSWORD|SECRET|API_KEY/.test(key)) delete process.env[key];
    for (const directory of [process.env.HOME, process.env.PI_AGENT_DATA_DIR, process.env.CLAUDE_CONFIG_DIR, process.env.CODEX_HOME]) fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    const started = await handle({ action: 'start' });
    if (!started.ok) throw new BrowserCheckError(started.error.code);
    const pair = await handle({ action: 'pair' });
    if (!pair.ok) throw new BrowserCheckError(pair.error.code);
    const paired = await pairBrowser(page, pair.url);
    await openProjectInBrowser(page, process.env.HOME);
    const summary = await page.evaluate(() => ({
      path: location.pathname,
      buttons: [...document.querySelectorAll('[role="button"],button')].map(el => ({ name: el.getAttribute('aria-label') || el.textContent?.trim(), testId: el.getAttribute('data-testid') })).filter(row => row.name && row.name.length < 120 && !/[#=]|https?:|[A-Za-z0-9_+/=-]{40,}/.test(row.name)).slice(0, 35),
      testIds: [...document.querySelectorAll('[data-testid]')].map(el => el.getAttribute('data-testid')).filter(id => /^[A-Za-z][A-Za-z0-9_-]{0,70}$/.test(id)).slice(0, 60),
      openProjectVisible: /Open (?:a )?(?:project|folder)/i.test(document.body.innerText),
      notConnectedVisible: /No hosts connected|Connect your computer to get started/.test(document.body.innerText),
    }));
    process.stdout.write(JSON.stringify({ ok: true, official, ...paired, ...summary, remoteDirectoryOpenedThroughBrowser: true, realModelsTested: false }) + '\n');
  }
} catch (error) {
  process.stdout.write(JSON.stringify(safeFailure(error)) + '\n');
  process.exitCode = 1;
} finally {
  await browser?.close();
  if (root) {
    const stopped = await handle({ action: 'stop' });
    if (stopped.ok) fs.rmSync(root, { recursive: true, force: true });
    else { process.stderr.write('OWNED_DAEMON_CLEANUP_FAILED\n'); process.exitCode = 1; }
  }
}
