import assert from 'node:assert/strict';

// Use the real bundled plugin link and setup form through the Supervisor-style
// ingress proxy. Only invalid credentials are submitted, so no remote service
// or historical login can turn this packaging smoke into an external session.
export async function checkOmnigentSetup(pluginsPage, prefix) {
  const link = pluginsPage.getByTestId('plugins-card-open-woow-omnigent');
  await link.waitFor({ timeout: 30_000 });
  assert.equal(await link.getAttribute('href'), `${prefix}/settings/omnigent`);
  assert.equal(await link.getAttribute('target'), '_blank');
  const [page] = await Promise.all([pluginsPage.waitForEvent('popup'), link.click()]);
  try {
    const section = page.getByTestId('omnigent-integration-section');
    await section.waitFor({ timeout: 30_000 });
    assert.equal(new URL(page.url()).pathname, `${prefix}/settings/omnigent`);
    const reloaded = await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
    assert.equal(reloaded.status(), 200, 'plugin settings reload must stay inside HA Ingress');
    await section.waitFor({ timeout: 30_000 });
    await section.getByRole('button', { name: 'Configure', exact: true }).click();
    const dialog = page.getByTestId('omnigent-setup-dialog');
    await dialog.waitFor({ timeout: 30_000 });
    const fields = Object.fromEntries(['server', 'username', 'password'].map(name => [name, dialog.locator(`input[name="${name}"]`)]));
    await fields.server.waitFor({ state: 'visible' });
    await page.waitForFunction(() => !document.querySelector('[data-testid="omnigent-setup-dialog"] input[name="server"]')?.disabled);
    for (const field of Object.values(fields)) {
      assert.equal(await field.inputValue(), '', 'fresh setup must ask for every credential');
      assert.notEqual(await field.getAttribute('required'), null);
    }
    assert.equal(await fields.password.getAttribute('type'), 'password');
    await fields.server.fill('http://invalid.example'); // HTTPS is required by the real daemon.
    await fields.username.fill('ha-smoke-fake-user');
    await fields.password.fill('ha-smoke-fake-password');
    const responsePromise = page.waitForResponse(response => response.request().method() === 'POST'
      && response.url().includes('/api/integrations/omnigent/actions')
      && response.request().postDataJSON()?.action === 'setup');
    await dialog.locator('button[type="submit"]').click();
    const response = await responsePromise;
    assert.ok(new URL(response.url()).pathname.startsWith(`${prefix}/api/`), 'GUI mutation must use ingress prefix');
    assert.equal(response.status(), 400);
    assert.equal((await response.json()).error?.code, 'INVALID_SERVER');
    for (const field of Object.values(fields)) assert.equal(await field.inputValue(), '', 'rejected login must clear all fields');
    const stored = await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]));
    assert.ok(!stored.includes('ha-smoke-fake-password') && !stored.includes('ha-smoke-fake-user'), 'login credentials must not enter browser storage');
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });
  } finally { await page.close(); }
}
