import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/simple-ux-profile-renders');
test.beforeAll(() => mkdirSync(renders, { recursive: true }));

async function login(page: import('@playwright/test').Page, owner: string) {
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
}

for (const viewport of [
  { name: 'desktop', size: { width: 1440, height: 1024 }, owner: 'reader-transit-desktop' },
  { name: 'mobile', size: { width: 390, height: 844 }, owner: 'reader-transit-mobile' },
]) {
  test(`saved profile leads with a summary and retains a hidden chart editor on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport.size);
    await login(page, viewport.owner);
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
    await expect(page.getByRole('heading', { name: 'Synthetic transit reader' })).toBeVisible();
    const overview = page.getByRole('tab', { name: 'Overview' });
    const charts = page.getByRole('tab', { name: 'Charts' });
    await expect(overview).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tabpanel', { name: 'Overview' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Generate a chart' })).toBeHidden();
    await page.screenshot({ path: resolve(renders, `saved-basic-${viewport.name}.png`) });
    await overview.focus(); await overview.press('ArrowRight');
    await expect(charts).toBeFocused();
    await expect(charts).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('group', { name: /Tropical natal wheel/ })).toBeVisible();
    await page.screenshot({ path: resolve(renders, `saved-chart-${viewport.name}.png`) });
    if (viewport.name === 'desktop') {
      await page.evaluate(() => localStorage.setItem('kat.appearance.theme', 'blue-hour'));
      await page.reload();
      await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
      await page.getByRole('tab', { name: 'Charts' }).click();
      await page.screenshot({ path: resolve(renders, 'saved-chart-dark-desktop.png') });
    }
    await page.getByRole('button', { name: 'Edit birth details' }).click();
    const editor = page.getByRole('region', { name: 'Generate a chart' });
    await expect(editor).toBeVisible();
    await expect(page.locator('.profile-editor')).toBeFocused();
    await editor.getByLabel('Birth date').fill('2001-04-05');
    await page.getByRole('button', { name: 'Close editor' }).click();
    await expect(editor).toBeHidden();
    await page.getByRole('button', { name: 'Edit birth details' }).click();
    await expect(editor.getByLabel('Birth date')).toHaveValue('2001-04-05');
    await overview.click(); await charts.click();
    await expect(editor.getByLabel('Birth date')).toHaveValue('2001-04-05');
    if (viewport.name === 'mobile') {
      await page.setViewportSize({ width: 390, height: 560 });
      await page.screenshot({ path: resolve(renders, 'saved-editor-short-mobile.png') });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
    }
  });
}

test('first chart empty state, unknown birth time and local generation are truthful', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'blue-hour'));
  await login(page, 'reader-people');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic unknown time');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  await expect(page.getByRole('tab', { name: 'Charts' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.profile-chart-heading')).toContainText('No active generated natal');
  await page.locator('.profile-header').scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'empty-chart-dark-mobile.png') });
  await page.locator('.profile-editor').scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'first-editor-dark-mobile.png') });
  const editor = page.getByRole('region', { name: 'Generate a chart' });
  await editor.getByLabel('Birth date').fill('2024-03-20');
  await editor.getByLabel('Time unknown').check();
  await editor.getByLabel('Birthplace search').fill('Copenhagen');
  await editor.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  let modelRequests = 0;
  page.on('request', request => { if (/\/api\/conversations\/[^/]+\/turns$/.test(new URL(request.url()).pathname)) modelRequests++; });
  const posted = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
  await editor.getByRole('button', { name: 'Generate chart' }).click();
  const response = await posted;
  expect(response.status()).toBe(201);
  const result = await response.json();
  await expect(page.locator('.profile-chart-empty')).toBeHidden();
  await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
  await expect(page.locator('.profile-active-chart')).toContainText('Unknown or uncertain birth time: no full natal positions');
  expect(modelRequests).toBe(0);
  await page.getByRole('tab', { name: 'Overview' }).click();
  await expect(page.getByRole('button', { name: /Birth chart/ })).toContainText('Limited chart · birth time unknown');
  await page.screenshot({ path: resolve(renders, 'saved-unknown-dark-mobile.png') });
});
