import { test, expect } from '@playwright/test';
import { resolve } from 'node:path';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';

const renders = resolve(import.meta.dirname, '../../.local/advanced-techniques');

test('explicit Chiron profile renders, exports and survives reload without changing old defaults', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-chiron');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic Chiron reader');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('05:06');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).first().click();
  await form.getByText('Advanced · chart settings and location').click();
  await form.getByLabel('Include Chiron').check();
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.locator('.birth-status')).toContainText('Current natal saved');
  const charts = page.getByRole('tabpanel', { name: 'Charts' });
  await expect(charts.getByRole('row', { name: /Chiron/ }).first()).toBeVisible();
  const wheel = charts.locator('.natal-wheel').first();
  await expect(wheel).toContainText('Ch');
  const downloadPromise = page.waitForEvent('download');
  await charts.getByRole('button', { name: 'Download safe SVG wheel' }).first().click();
  const download = await downloadPromise;
  const xml = await readFile(await download.path(), 'utf8');
  expect(xml).toContain('Chiron');
  expect(xml).toContain('seas_18.se1');
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(renders, `chiron-normal-${size.name}.png`), fullPage: true });
  }
  await page.reload();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic Chiron reader/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic Chiron reader' })).toBeVisible();
  await expect(page.getByRole('tabpanel', { name: 'Charts' }).getByRole('row', { name: /Chiron/ }).first()).toBeVisible();
});

test('unavailable Chiron explains the choice and returns focus to it without saving', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-chiron');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic Chiron recovery');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('05:06');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).first().click();
  await form.getByText('Advanced · chart settings and location').click();
  await form.getByLabel('Include Chiron').check();
  let rejected = false;
  await page.route('**/api/people/*/generate', route => {
    if (rejected) return route.continue();
    rejected = true;
    return route.fulfill({ status: 400, contentType: 'application/json',
      body: JSON.stringify({ error: 'chiron_data_missing_or_unverified' }) });
  });
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.getByRole('alert')).toContainText('Turn off Include Chiron');
  await expect(form.getByLabel('Include Chiron')).toBeFocused();
  await expect(page.locator('.profile-active-chart')).toHaveCount(0);
  await form.getByLabel('Include Chiron').uncheck();
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.locator('.birth-status')).toContainText('Current natal saved');
});
