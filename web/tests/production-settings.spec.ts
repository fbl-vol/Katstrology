import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

test('offline personal connection offers no unsupported browser signup', async ({ page }) => {
  const folder = resolve(import.meta.dirname, '../../.local/fresh-production');
  mkdirSync(folder, { recursive: true });
  await page.route('**/api/siwc/status', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ available: true, connected: false, accounts: [],
      selected: null, registration: 'offline' }),
  }));
  let starts = 0;
  page.on('request', request => { if (request.url().includes('/auth/chatgpt/start')) starts++; });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-review-fixes');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  const connection = page.getByRole('region', { name: 'Model connection' });
  await expect(connection.getByText(/Connect the account offline/)).toBeVisible();
  await expect(connection.getByRole('button', { name: /Connect ChatGPT plan|Reconnect ChatGPT account/ })).toHaveCount(0);
  await expect(page.locator('.model-label')).toHaveText('Chat not connected');
  expect(starts).toBe(0);
  await page.screenshot({ path: resolve(folder, 'offline-desktop.png') });
  await page.setViewportSize({ width: 390, height: 560 });
  await expect(connection.getByText(/Connect the account offline/)).toBeVisible();
  await page.screenshot({ path: resolve(folder, 'offline-short-mobile.png') });
});
