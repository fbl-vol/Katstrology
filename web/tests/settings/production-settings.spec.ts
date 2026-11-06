import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const folder = resolve(import.meta.dirname, '../../../.local/chatgpt-connect');
type Phase = 'not_connected' | 'refresh_required' | 'ready' | 'reauthorization_required' | 'identity_only';

async function isolatedSession(page: Page, context: BrowserContext, status: () => {
  available: boolean; phase: Phase; account: boolean;
}) {
  // Register the deny rule before any browser navigation; no real provider page.
  const baseURL = test.info().project.use.baseURL;
  if (!baseURL) throw new Error('Owned isolated browser origin required');
  const origin = new URL(baseURL).origin;
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin === origin) return route.continue();
    return route.abort();
  });
  await page.route('**/api/siwc/status', route => {
    const current = status();
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      available: current.available, connected: current.account &&
        (current.phase === 'refresh_required' || current.phase === 'ready'),
      phase: current.phase, accounts: current.account ? [{ client_id: 'oaiapp_synthetic',
        email: 'example@invalid.test', plan_enabled: current.phase !== 'identity_only' &&
          current.phase !== 'reauthorization_required', selected: true }] : [],
      selected: current.account ? 'oaiapp_synthetic' : null, registration: 'offline',
    }) });
  });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-review-fixes');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  return page.getByRole('region', { name: 'Model connection' });
}

test('offline connection explains the loopback handoff, never disguises Manage usage as Connect', async ({ page, context }) => {
  mkdirSync(folder, { recursive: true });
  const state = { available: true, phase: 'not_connected' as Phase, account: false };
  let starts = 0;
  page.on('request', request => { if (request.url().includes('/auth/chatgpt/start')) starts++; });
  const connection = await isolatedSession(page, context, () => state);
  await expect(connection.getByText(/Connect the account offline/)).toBeVisible();
  await expect(connection).toContainText('Your Kat login and ChatGPT permission are separate');
  await expect(connection.getByText('127.0.0.1 callback, not this website', { exact: false })).toBeHidden();
  await connection.getByText('Show offline setup steps').click();
  await expect(connection).toContainText('127.0.0.1 callback, not this website');
  await expect(connection.getByRole('link', { name: 'Manage usage in ChatGPT settings' })).toHaveCount(0);
  await expect(connection.getByRole('button', { name: /Connect ChatGPT plan|Reconnect ChatGPT account/ })).toHaveCount(0);
  expect(starts).toBe(0);
  const help = connection.getByRole('button', { name: 'About ChatGPT plan connection' });
  await help.focus();
  await expect(connection.getByRole('note')).toBeVisible();
  await help.press('Escape');
  await expect(help).toHaveAttribute('aria-expanded', 'false');
  await page.screenshot({ path: resolve(folder, 'setup-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: resolve(folder, 'setup-mobile.png') });
  await page.setViewportSize({ width: 390, height: 560 });
  await page.screenshot({ path: resolve(folder, 'setup-short-mobile.png') });
  await connection.getByText(/No ChatGPT credentials are entered/).scrollIntoViewIfNeeded();
  await expect(connection.getByText(/No ChatGPT credentials are entered/)).toBeVisible();
  await page.screenshot({ path: resolve(folder, 'setup-short-mobile-end.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(starts).toBe(0);
});

test('transferred grant, renewal and unavailable states keep recovery honest', async ({ page, context }) => {
  mkdirSync(folder, { recursive: true });
  const state = { available: true, phase: 'refresh_required' as Phase, account: true };
  let starts = 0;
  page.on('request', request => { if (request.url().includes('/auth/chatgpt/start')) starts++; });
  let catalogChecks = 0;
  let terminalFailure = false;
  await page.route('**/api/siwc/models', route => {
    catalogChecks++;
    state.phase = terminalFailure ? 'reauthorization_required' : 'ready';
    return route.fulfill({ status: terminalFailure ? 503 : 200, contentType: 'application/json',
      body: JSON.stringify(terminalFailure ? { error: 'unavailable' } :
        { chat_available: true, models: [] }) });
  });
  const connection = await isolatedSession(page, context, () => state);
  await expect(connection).toContainText('still needs to refresh its token');
  await expect(connection).toContainText('saved permission alone does not confirm plan eligibility');
  await expect(connection.getByRole('link', { name: 'Manage usage in ChatGPT settings' })).toBeVisible();
  await expect(connection).toContainText('usage and access only, not connection setup');
  await expect(page.locator('.model-label')).toHaveText('ChatGPT account saved');
  await page.screenshot({ path: resolve(folder, 'saved-desktop.png') });
  const check = connection.getByRole('button', { name: 'Check chat connection' });
  await check.focus();
  await check.press('Enter');
  await expect(connection.getByRole('status')).toContainText('chat model is available');
  expect(catalogChecks).toBe(1);
  await expect(connection).toContainText('set up privately on this server');
  terminalFailure = true;
  await connection.getByRole('button', { name: 'Check chat connection' }).click();
  await expect(connection.getByRole('status')).toContainText('chat model could not be checked');
  await expect(connection).toContainText('authorization needs renewing');
  expect(catalogChecks).toBe(2);
  await page.screenshot({ path: resolve(folder, 'refresh-failed-desktop.png') });
  await page.reload();
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  await expect(page.getByRole('region', { name: 'Model connection' }))
    .toContainText('authorization needs renewing');
  await page.screenshot({ path: resolve(folder, 'recovery-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: resolve(folder, 'recovery-mobile.png') });
  await page.setViewportSize({ width: 390, height: 560 });
  await page.screenshot({ path: resolve(folder, 'recovery-short-mobile.png') });
  await expect(page.getByRole('region', { name: 'Model connection' }))
    .not.toContainText('Identity only; plan use not permitted');
  state.phase = 'identity_only';
  await page.reload();
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  await expect(page.getByRole('region', { name: 'Model connection' })).toContainText('without plan permission');
  state.available = false;
  await page.reload();
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  await expect(page.getByRole('region', { name: 'Model connection' }))
    .toContainText('server connection is disabled');
  await page.screenshot({ path: resolve(folder, 'unavailable-short-mobile.png') });
  expect(starts).toBe(0);
});
