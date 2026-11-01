import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

test('offline personal connection offers no unsupported browser signup', async ({ page }) => {
  const folder = resolve(import.meta.dirname, '../../.local/fresh-production');
  mkdirSync(folder, { recursive: true });
  let mode: 'pending' | 'connected' | 'unavailable' = 'pending';
  await page.route('**/api/siwc/status', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ available: mode !== 'unavailable', connected: mode === 'connected',
      accounts: mode === 'connected' ? [{ client_id: 'synthetic-registration',
        email: 'example@invalid.test', plan_enabled: true, selected: true }] : [],
      selected: mode === 'connected' ? 'synthetic-registration' : null,
      registration: 'offline' }),
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
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: resolve(folder, 'offline-mobile.png') });
  await page.setViewportSize({ width: 390, height: 560 });
  await expect(connection.getByText(/Connect the account offline/)).toBeVisible();
  await page.screenshot({ path: resolve(folder, 'offline-short-mobile.png') });
  await page.setViewportSize({ width: 2560, height: 1080 });
  await page.screenshot({ path: resolve(folder, 'offline-wide.png') });

  mode = 'connected';
  await page.reload();
  await page.getByRole('button', { name: 'Settings' }).click();
  const enrolled = page.getByRole('region', { name: 'Model connection' });
  await expect(enrolled.getByText(/set up privately on this server/)).toBeVisible();
  await expect(enrolled).toContainText('Saved plan permission; checked when chat is used');
  await expect(page.locator('.model-label')).toHaveText('ChatGPT account saved');
  await expect(enrolled.getByRole('button', { name: /Reconnect ChatGPT account/ })).toHaveCount(0);
  await page.screenshot({ path: resolve(folder, 'offline-enrolled-wide.png') });
  await page.setViewportSize({ width: 390, height: 560 });
  await page.screenshot({ path: resolve(folder, 'offline-enrolled-short.png') });

  mode = 'unavailable';
  await page.reload();
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('region', { name: 'Model connection' })
    .getByText(/needs an offline ChatGPT registration/)).toBeVisible();
  await page.screenshot({ path: resolve(folder, 'offline-unavailable-short.png') });
});
