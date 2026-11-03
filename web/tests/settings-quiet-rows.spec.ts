import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/settings-quiet-rows');
test.beforeAll(() => mkdirSync(renders, { recursive: true }));

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short-mobile', width: 390, height: 640 },
  { name: 'wide', width: 2560, height: 1080 },
]) {
  test(`Quiet rows keeps every palette reachable and restores focus on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-appearance');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByLabel('Message Kat').fill('Unsent settings draft');
    const sends: string[] = [];
    page.on('request', request => {
      if (request.method() !== 'GET' && /\/api\/conversations/.test(request.url())) sends.push(request.url());
    });
    if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Settings' }).click();
    const appearance = page.getByRole('button', { name: /Appearance/ });
    await expect(appearance).toContainText('Reading Room');
    await expect(page.getByRole('button', { name: /ChatGPT.*Manage/ })).toBeVisible();
    await expect(page.getByRole('button', { name: 'About Kat & source' })).toBeVisible();
    await expect(page.getByText("Kat's tone")).toHaveCount(0); // No unfinished preference UI.
    await page.screenshot({ path: resolve(renders, `overview-${viewport.name}.png`) });

    await appearance.click();
    const picker = page.getByRole('dialog', { name: 'Choose a palette' });
    await expect(picker.locator('.appearance-option')).toHaveCount(9);
    await picker.getByRole('button', { name: 'Dark', exact: true }).click();
    await expect(picker.locator('.appearance-option')).toHaveCount(9);
    const last = picker.getByRole('button', { name: /Midnight Orchid/ });
    await last.scrollIntoViewIfNeeded();
    await last.focus();
    await expect(last).toBeFocused();
    await expect(last).toBeInViewport();
    await page.screenshot({ path: resolve(renders, `picker-${viewport.name}.png`) });
    await last.press('Enter');
    await expect(last).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('meta[name="theme-color"]')).not.toHaveAttribute('content', '#f5f3ec');
    await picker.getByRole('button', { name: 'Close settings panel' }).click();
    await expect(appearance).toBeFocused();
    await expect(appearance).toContainText('Midnight Orchid');

    await page.getByRole('button', { name: 'About Kat & source' }).click();
    await expect(page.getByRole('link', { name: 'Read the license' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: 'About Kat & source' })).toBeFocused();
    await page.getByRole('button', { name: 'Back to workspace' }).click();
    await expect(page.getByLabel('Message Kat')).toHaveValue('Unsent settings draft');
    expect(sends).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
  });
}

test('ChatGPT Manage shows real account status, keeps selection available and confirms disconnect', async ({ page }) => {
  let disconnects = 0;
  await page.route('**/api/siwc/disconnect', route => { disconnects++; return route.abort(); });
  await page.route('**/api/siwc/status', route => route.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ available: true, connected: true,
      registration: 'offline', phase: 'ready', selected: 'synthetic-a', accounts: [
        { client_id: 'synthetic-a', email: 'first@example.invalid', plan_enabled: true, selected: true },
        { client_id: 'synthetic-b', email: 'second@example.invalid', plan_enabled: false, selected: false },
      ] }),
  }));
  await page.setViewportSize({ width: 390, height: 640 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-review-fixes');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('button', { name: /ChatGPT.*Manage/ })).toContainText('Account saved · checked when used');
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  const connection = page.getByRole('region', { name: 'Model connection' });
  await expect(connection.getByLabel('Saved account')).toHaveCount(1);
  await expect(connection.getByLabel('Saved account').locator('option')).toHaveCount(2);
  await expect(connection.getByText('Model availability is checked when chat is used.')).toBeVisible();
  await page.screenshot({ path: resolve(renders, 'connection-multi-account-short-mobile.png') });
  page.once('dialog', dialog => dialog.dismiss());
  await connection.getByRole('button', { name: 'Disconnect ChatGPT plan' }).click();
  expect(disconnects).toBe(0);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: /ChatGPT.*Manage/ })).toBeFocused();
});
