import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/advanced-techniques');

test('normal return workflows save trusted charts without sending a message', async ({ page }) => {
  mkdirSync(renders, { recursive: true });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
  const view = page.getByRole('region', { name: 'Solar return chart' });
  await view.getByLabel('Person with a current natal').selectOption('transit-person');
  await expect(view.getByText('Birthplace', { exact: true })).toBeVisible();
  await view.getByLabel('UTC anniversary year').fill('2026');
  const created = page.waitForResponse(response => response.url().endsWith('/api/advanced-results') &&
    response.request().method() === 'POST');
  await view.getByRole('button', { name: 'Calculate solar return' }).click();
  const record = await (await created).json();
  await expect(view.locator('.advanced-event')).toHaveCount(1);
  await expect(view.locator('.natal-wheel')).toContainText('Solar return · tropical');
  await expect(view).not.toContainText('not independently verified');
  const saved = await (await page.request.get(`/api/advanced-results/${record.id}`)).json();
  expect(saved.result.events[0].instant_utc).toBe(record.events[0].instant_utc);
  expect(saved.result.events[0].chart.positions.map((item: { longitude_degrees: number }) =>
    item.longitude_degrees)).toEqual(record.events[0].chart.positions.map(
    (item: { longitude_degrees: number }) => item.longitude_degrees));
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  await view.getByRole('button', { name: /Open saved solar return/ }).click();
  await expect(view.locator('.natal-wheel')).toContainText('Solar return · tropical');
  const download = page.waitForEvent('download');
  await view.getByText('Download chart', { exact: true }).click();
  await view.getByRole('button', { name: 'Download safe SVG wheel' }).click();
  const svg = await readFile(await (await download).path(), 'utf8');
  expect(svg).toContain('kat-chart-provenance');
  expect(svg).toContain('solar-return-utc-anniversary-v1');
  await expect(page.locator('.turn-card')).toHaveCount(0);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(renders, `return-normal-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
  await view.getByRole('button', { name: 'Back to chart choices' }).click();
  await page.getByRole('button', { name: /Lunar returns Choose a person/ }).click();
  const lunar = page.getByRole('region', { name: 'Lunar returns chart' });
  await lunar.getByLabel('Person with a current natal').selectOption('transit-person');
  await lunar.getByLabel('From (UTC, inclusive)').fill('2026-06-21');
  await lunar.getByLabel('Until (UTC, exclusive)').fill('2026-08-20');
  await lunar.getByRole('button', { name: 'Calculate lunar returns' }).click();
  await expect.poll(async () => lunar.locator('.advanced-event').count()).toBeGreaterThanOrEqual(2);
  await lunar.getByRole('button', { name: 'Discuss this crossing' }).first().click();
  await expect(page.locator('.compose-context')).toContainText('saved result, not recalculated');
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
});
