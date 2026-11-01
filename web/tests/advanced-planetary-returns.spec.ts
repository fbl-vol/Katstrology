import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/advanced-techniques');

test('named planetary returns show every pass, export provenance and replay without a message', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Planetary returns/ }).click();
  const view = page.getByRole('region', { name: 'Planetary returns chart' });
  await view.getByLabel('Person with a current natal').selectOption({ label: 'Synthetic transit reader' });
  await view.getByLabel('Returning planet').selectOption('jupiter');
  await view.getByLabel('From').fill('2012-01-01');
  await view.getByLabel('Until (not included)').fill('2012-01-01');
  await expect(view.getByText('Birthplace', { exact: true })).toBeVisible();
  await view.getByRole('button', { name: 'Find planetary return passes' }).click();
  await expect(view.getByRole('alert')).toContainText('Choose an end date after the start');
  await view.getByLabel('Until (not included)').fill('2014-01-01');
  const post = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Find planetary return passes' }).click();
  const result = await (await post).json();
  expect(result.status).toBe('supported');
  expect(result.body).toBe('jupiter');
  expect(result.method_version).toBe('planet-own-natal-longitude-all-passes-v1');
  expect(result.events.length).toBeGreaterThan(0);
  await expect(view.getByRole('region', { name: 'Planetary return results' })).toContainText('Jupiter returns');
  await expect(view.getByRole('region', { name: 'Planetary return results' })).not.toContainText('not independently verified');
  await expect(view.locator('.advanced-event')).toHaveCount(result.events.length);
  const download = page.waitForEvent('download');
  await view.getByRole('button', { name: 'Download safe SVG wheel' }).first().click();
  const svg = await readFile(await (await download).path(), 'utf8');
  expect(svg).toContain('"return_body":"jupiter"');
  expect(svg).toContain('"source_chart_id":');
  const csvDownload = page.waitForEvent('download');
  await view.getByRole('button', { name: 'Download planetary returns CSV' }).click();
  const csv = await readFile(await (await csvDownload).path(), 'utf8');
  expect(csv).toContain('jupiter,');
  expect(csv).toContain('pass_direction');
  await view.getByRole('button', { name: /Open saved planetary returns/ }).click();
  await expect(view.locator('.advanced-event')).toHaveCount(result.events.length);
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.screenshot({ path: resolve(renders, `planetary-returns-normal-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
});
