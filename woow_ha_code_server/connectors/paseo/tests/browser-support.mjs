import { pathToFileURL } from 'node:url';

export class BrowserCheckError extends Error {
  constructor(code) { super(code); this.code = code; }
}

export async function launchBrowser() {
  const location = process.env.WOOW_PLAYWRIGHT_MODULE
    ? pathToFileURL(process.env.WOOW_PLAYWRIGHT_MODULE).href
    : new URL('../../../../browser-tools/node_modules/playwright-core/index.mjs', import.meta.url).href;
  const { chromium } = await import(location);
  return chromium.launch({ headless: true, executablePath: process.env.WOOW_CHROME_PATH || '/usr/bin/google-chrome', args: ['--no-sandbox'] });
}

export async function freshPage(browser) {
  // Intentionally no persistent profile, storageState, HAR, tracing or screenshots:
  // those artifacts would contain pairing material and per-browser private keys.
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'en-US' });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  return { context, page };
}

export async function probeOfficial(page) {
  let response;
  try { response = await page.goto('https://app.paseo.sh/', { waitUntil: 'domcontentloaded', timeout: 45000 }); }
  catch { throw new BrowserCheckError('OFFICIAL_WEB_NAVIGATION_FAILED'); }
  await page.getByText('Welcome to Paseo', { exact: true }).waitFor({ timeout: 30000 });
  const result = await page.evaluate(() => {
    const body = document.body.innerText;
    return { title: document.title, version: body.match(/\bv\d+\.\d+\.\d+\b/)?.[0] || null, welcomeVisible: body.includes('Welcome to Paseo'), pastePairingAvailable: body.includes('Paste pairing link') };
  });
  return { url: 'https://app.paseo.sh/', httpStatus: response?.status() || null, ...result };
}

export function validatePairUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new BrowserCheckError('INVALID_PAIR_URL'); }
  if (url.origin !== 'https://app.paseo.sh' || url.username || url.password || !url.hash || url.search) throw new BrowserCheckError('INVALID_PAIR_URL');
  return url.href;
}

export async function pairBrowser(page, pairUrl) {
  const url = validatePairUrl(pairUrl);
  try { await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 }); }
  catch { throw new BrowserCheckError('PAIRING_NAVIGATION_FAILED'); }
  await page.getByText('Connect to this host?', { exact: true }).waitFor({ timeout: 30000 });
  // Pairing is an explicit user-authorized test of this supplied daemon only.
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await page.getByText('Connect to this host?', { exact: true }).waitFor({ state: 'hidden', timeout: 30000 });
  await page.getByTestId('wide-shell').waitFor({ timeout: 45000 });
  const setup = page.getByTestId('onboarding-modal');
  try { await setup.waitFor({ timeout: 5000 }); } catch { /* returning paired browser may not show onboarding */ }
  if (await setup.isVisible()) {
    await setup.getByRole('button', { name: 'Skip setup', exact: true }).click();
    await setup.waitFor({ state: 'hidden', timeout: 10000 });
  }
  return { pairingConfirmedInBrowser: true };
}

export async function openProjectInBrowser(page, workspace) {
  await page.getByTestId('sidebar-add-project').click();
  await page.getByTestId('add-project-flow-method-directory-search').click();
  await page.getByTestId('add-project-flow-input').fill(workspace);
  await page.getByTestId(`add-project-flow-path-${encodeURIComponent(workspace)}`).click({ timeout: 45000 });
  await page.waitForURL(url => url.pathname === '/new' && url.searchParams.get('dir') === workspace, { timeout: 30000 });
  await page.getByRole('textbox', { name: 'Message agent...' }).first().waitFor();
  return page.url();
}

export function safeFailure(error) {
  return { ok: false, error: { code: error instanceof BrowserCheckError ? error.code : 'BROWSER_CHECK_FAILED' } };
}
