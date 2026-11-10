import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { BrowserCheckError, launchBrowser, freshPage, pairBrowser, safeFailure } from './browser-support.mjs';

const fail = code => { throw new BrowserCheckError(code); };

// A popup may emit its download before a second waitForEvent can be installed.
// Register all listeners before the ordinary user click; remove them on either outcome.
async function clickDownload(context, control) {
  const pages = new Set(context.pages());
  let timer, resolveDownload, rejectDownload;
  const result = new Promise((resolve, reject) => { resolveDownload = resolve; rejectDownload = reject; });
  const attach = page => { pages.add(page); page.on('download', resolveDownload); };
  for (const page of pages) page.on('download', resolveDownload);
  context.on('page', attach);
  timer = setTimeout(() => rejectDownload(new BrowserCheckError('FILE_DOWNLOAD_EVENT_TIMEOUT')), 60000);
  // Avoid an unhandled rejection if the click itself fails first.
  result.catch(() => {});
  try {
    await control.click();
    const download = await result;
    if (await download.failure()) fail('FILE_DOWNLOAD_FAILED');
    return download;
  } finally {
    clearTimeout(timer);
    context.off('page', attach);
    for (const page of pages) page.off('download', resolveDownload);
  }
}

function validatePlan(plan) {
  const url = new URL(plan.workspaceUrl);
  if (url.origin !== 'https://app.paseo.sh' || url.username || url.password || url.search || url.hash || !/^\/h\/[^/]+\/workspace\/[^/]+$/.test(url.pathname)) fail('INVALID_WORKSPACE_URL');
  if (!/^[A-Za-z0-9_-]+$/.test(plan.agentId) || !plan.assistantMarker || !Array.isArray(plan.files) || !plan.files.length) fail('INVALID_DOWNLOAD_PLAN');
  for (const file of plan.files) {
    if (typeof file.path !== 'string' || !file.path || file.path.startsWith('/') || /[\\\0?#:]/.test(file.path) || file.path.split('/').some(p => !p || p === '.' || p === '..') || !file.label || !/^[a-f0-9]{64}$/.test(file.sha256)) fail('INVALID_DOWNLOAD_FILE');
  }
}

export async function verifyDownloads(page, context, plan, progress = () => {}) {
  validatePlan(plan);
  const rows = [];
  await page.goto(plan.workspaceUrl, { waitUntil: 'domcontentloaded' });
  for (const file of plan.files) {
    const row = { path: file.path, expectedSha256: file.sha256, ok: false };
    rows.push(row);
    const stage = value => { row.stage = value; progress({ rows }); };
    stage('open-conversation');
    await page.keyboard.press('Escape');
    // Restore the chat width after the previous file's Explorer action.
    if (await page.getByTestId('workspace-explorer-sidebar').isVisible()) await page.getByTestId('workspace-explorer-toggle').click();
    await page.getByTestId(`workspace-tab-agent_${plan.agentId}`).click();
    stage('find-assistant-link');
    const assistant = page.getByTestId('assistant-message').filter({ hasText: plan.assistantMarker }).last();
    await assistant.waitFor();
    const link = assistant.getByRole('link', { name: file.label, exact: true });
    if (await link.getAttribute('href') !== file.path) fail('ASSISTANT_LINK_IS_NOT_WORKSPACE_RELATIVE');
    stage('open-workspace-file');
    await link.click();
    try { await page.getByTestId(`workspace-tab-file_${file.path}`).waitFor({ timeout: 15000 }); }
    catch {
      row.visibleFileTabs = await page.locator('[data-testid^="workspace-tab-file_"]').evaluateAll(nodes => nodes.filter(node => node.checkVisibility()).map(node => node.dataset.testid));
      progress({ rows });
      fail('ASSISTANT_FILE_TAB_NOT_OPENED');
    }
    // Paseo keeps inactive file panes mounted after opening another file.
    await page.getByTestId('workspace-file-pane').filter({ visible: true }).first().waitFor();
    row.assistantFileLinkClicked = true;

    stage('open-file-menu');
    const explorer = page.getByTestId('workspace-explorer-sidebar');
    if (!await explorer.isVisible()) await page.getByTestId('workspace-explorer-toggle').click();
    await explorer.getByTestId('workspace-tab-files').click();
    const components = file.path.split('/');
    for (let i = 0; i < components.length - 1; i++) {
      if (!await explorer.getByText(components[i + 1], { exact: true }).isVisible()) await explorer.getByText(components[i], { exact: true }).click();
    }
    await explorer.getByText(components.at(-1), { exact: true }).click({ button: 'right' });
    stage('download');
    const download = await clickDownload(context, page.getByRole('menuitem', { name: 'Download', exact: true }));
    const localFile = await download.path();
    const bytes = fs.readFileSync(localFile);
    row.sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
    row.bytes = bytes.length;
    row.suggestedFilename = download.suggestedFilename();
    // Keep only transport metadata. Never persist the transient download URL.
    const url = new URL(download.url());
    row.urlScheme = url.protocol;
    row.urlHasQuery = !!url.search;
    if (row.sha256 !== file.sha256) fail('FILE_DOWNLOAD_HASH_MISMATCH');
    if (url.protocol !== 'blob:' || url.search) fail('EXPECTED_PAIRED_BROWSER_BLOB_DOWNLOAD');
    if (plan.downloadDirectory) {
      fs.mkdirSync(plan.downloadDirectory, { recursive: true });
      await download.saveAs(path.join(plan.downloadDirectory, `${rows.length}-${path.basename(file.path)}`));
    }
    row.ordinaryDownloadClicked = true;
    row.ok = true;
    stage('complete');
  }
  return rows;
}

export async function verifyUnpairedIsolation(browser, workspaceUrl) {
  const { context, page } = await freshPage(browser);
  try {
    await page.goto(workspaceUrl, { waitUntil: 'domcontentloaded' });
    await page.getByText('Welcome to Paseo', { exact: true }).waitFor();
    const result = {
      welcomeVisible: true,
      assistantMessages: await page.getByTestId('assistant-message').count(),
      filePanes: await page.getByTestId('workspace-file-pane').count(),
      downloadActions: await page.getByRole('menuitem', { name: 'Download', exact: true }).count(),
    };
    if (result.assistantMessages || result.filePanes || result.downloadActions) fail('UNPAIRED_WORKSPACE_ACCESS');
    return result;
  } finally { await context.close(); }
}

async function main() {
  const plan = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  validatePlan(plan);
  const report = { ok: false, rows: [], noHeaderInjection: true, noSshForward: true };
  const save = () => { if (plan.reportFile) fs.writeFileSync(plan.reportFile, JSON.stringify(report, null, 2) + '\n'); };
  let browser, context;
  try {
    browser = await launchBrowser();
    const fresh = await freshPage(browser); context = fresh.context;
    const pair = JSON.parse(fs.readFileSync(plan.privatePairFile, 'utf8'));
    await pairBrowser(fresh.page, pair.pairUrl);
    report.paired = true;
    report.rows = await verifyDownloads(fresh.page, context, plan, result => { Object.assign(report, result); save(); });
    report.unpairedIsolation = await verifyUnpairedIsolation(browser, plan.workspaceUrl);
    report.ok = true;
  } catch (error) {
    Object.assign(report, safeFailure(error));
    process.exitCode = 1;
  } finally {
    await context?.close().catch(() => {});
    await browser?.close().catch(() => {});
    report.browserClosed = true;
    save();
    console.log(JSON.stringify(report));
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(() => { console.error('DOWNLOAD_ACCEPTANCE_SETUP_FAILED'); process.exitCode = 1; });
}
