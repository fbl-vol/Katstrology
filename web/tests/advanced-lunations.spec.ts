import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/advanced-techniques');

test('actual lunation and global eclipse have distinct UTC instants and no local visibility claim', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Lunations and eclipses/ }).click();
  const view = page.getByRole('region', { name: 'Actual lunations and global eclipses' });
  await view.getByLabel('Person with a current natal').selectOption({ label: 'Synthetic transit reader' });
  await view.getByLabel('From').fill('2024-03-01');
  await view.getByLabel('Until (not included)').fill('2024-03-01');
  await view.getByRole('button', { name: 'Find lunations and eclipses' }).click();
  await expect(view.getByRole('alert')).toContainText('Choose an end date after the start');
  await view.getByLabel('Until (not included)').fill('2024-05-01');
  const posted = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Find lunations and eclipses' }).click();
  const saved = await (await posted).json();
  expect(saved.status).toBe('supported');
  expect(saved.method_version).toBe('actual-geocentric-lunations-global-eclipses-v1');
  expect(saved.eclipses.some((item: { family: string; eclipse_type: string }) =>
    item.family === 'solar' && item.eclipse_type === 'total')).toBe(true);
  expect(saved.eclipses.some((item: { family: string; eclipse_type: string }) =>
    item.family === 'lunar' && item.eclipse_type === 'penumbral')).toBe(true);
  await expect(view.getByRole('region', { name: 'Actual lunations result' })).toContainText('not necessarily visible');
  await expect(view.getByRole('region', { name: 'Actual lunations result' })).not.toContainText('not independently verified');
  await view.getByRole('button', { name: 'View global eclipse' }).first().click();
  const chart = view.getByRole('region', { name: 'Selected actual-sky chart' });
  await expect(chart).toContainText('Global lunar eclipse maximum');
  const download = page.waitForEvent('download');
  await chart.getByRole('button', { name: 'Download safe SVG wheel' }).click();
  const svg = await readFile(await (await download).path(), 'utf8');
  expect(svg).toContain('"global_visibility":"not_calculated_for_location"');
  expect(svg).toContain('"linked_syzygy_utc":');
  const csvDownload = page.waitForEvent('download');
  await view.getByRole('button', { name: 'Download lunations and eclipses CSV' }).click();
  const csv = await readFile(await (await csvDownload).path(), 'utf8');
  expect(csv).toContain('solar_global_eclipse,total');
  expect(csv).toContain('lunar_global_eclipse,penumbral');
  await view.getByRole('button', { name: /Open saved sky search/ }).click();
  await expect(view.getByRole('table', { name: /Swiss global solar and lunar eclipse maxima/ }).getByRole('row')).toHaveCount(saved.eclipses.length + 1);
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.screenshot({ path: resolve(renders, `lunations-normal-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
});
