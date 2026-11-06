import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/person-page-redesign/renders');
test.beforeAll(() => mkdirSync(renders, { recursive: true }));

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short-mobile', width: 390, height: 560 },
]) {
  test(`quiet person overview and chart hierarchy on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-transit-desktop');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();

    await expect(page.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('button', { name: 'Start conversation' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Birth chart' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Private journal' })).toBeVisible();
    await expect(page.getByText('Historical chart files')).toHaveCount(0);
    await page.screenshot({ path: resolve(renders, `person-overview-${viewport.name}.png`), fullPage: true });
    await page.getByRole('button', { name: 'Private journal' }).click();
    await expect(page.getByLabel('Your reflection', { exact: true })).toBeVisible();

    await page.getByRole('tab', { name: 'Charts' }).click();
    const chart = page.locator('.profile-active-chart');
    await expect(chart.getByRole('group', { name: /Tropical natal wheel/ })).toBeVisible();
    await expect(chart.getByRole('tab', { name: /^Positions/ })).toBeVisible();
    await expect(chart.getByRole('button', { name: 'Download safe SVG wheel' })).toBeVisible();
    const wheel = await chart.locator('.natal-wheel-frame').boundingBox();
    const data = await chart.locator('.explorer-panel').boundingBox();
    expect(wheel).not.toBeNull(); expect(data).not.toBeNull();
    if (viewport.width > 1120) {
      expect(data!.x).toBeGreaterThan(wheel!.x + wheel!.width - 2);
      expect(data!.y).toBeLessThan(wheel!.y + wheel!.height);
    } else expect(data!.y).toBeGreaterThan(wheel!.y + wheel!.height - 2);
    await chart.getByRole('tab', { name: /^Aspects/ }).click();
    await expect(chart.getByLabel('Find in aspects')).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(renders, `person-charts-${viewport.name}.png`), fullPage: true });

    await page.getByRole('tab', { name: 'Saved' }).click();
    await page.getByRole('button', { name: 'Private journal' }).click();
    await expect(page.getByText('Private event journal', { exact: true })).toBeVisible();
    await page.screenshot({ path: resolve(renders, `person-saved-${viewport.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
    await page.getByRole('button', { name: 'Start conversation' }).click();
    await expect(page.getByLabel('Chart file for this turn')).toHaveCount(0);
  });
}
