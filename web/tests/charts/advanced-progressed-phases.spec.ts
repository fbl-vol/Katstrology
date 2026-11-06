import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/advanced-techniques');

test('progressed lunar cycle keeps effective and mapped times separate with saved phase chart', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Progressed lunar phases/ }).click();
  const view = page.getByRole('region', { name: 'Progressed lunar phase cycles' });
  await view.getByLabel('Person with a current natal').selectOption({ label: 'Synthetic transit reader' });
  await view.getByLabel('From (effective UTC)').fill('2001-06-22');
  await view.getByLabel('Until (UTC, excluded)').fill('2037-06-21');
  const posted = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Find progressed phases' }).click();
  const saved = await (await posted).json();
  expect(saved.status).toBe('supported');
  expect(saved.method_version).toBe('progressed-moon-sun-four-phase-utc-v1');
  expect(new Set(saved.events.map((item: { phase: string }) => item.phase)).size).toBe(4);
  expect(saved.events[0].effective_utc).not.toBe(saved.events[0].mapped_ephemeris_utc);
  await expect(view.getByRole('table', { name: /Progressed lunar phase dates/ }).getByRole('row')).toHaveCount(saved.events.length + 1);
  const chart = view.getByRole('region', { name: 'Selected symbolic phase chart' });
  await expect(chart).toContainText('mapped');
  await expect(view).not.toContainText('not independently verified');
  await expect(view).toContainText('not an actual New or Full Moon');
  await expect(chart).toContainText('Moon–Sun separation 0.00000°');
  const download = page.waitForEvent('download');
  await chart.getByRole('button', { name: 'Download safe SVG wheel' }).click();
  const markup = await readFile(await (await download).path(), 'utf8');
  expect(markup).toContain(`"effective_utc":"${saved.events[0].effective_utc}"`);
  expect(markup).toContain(`"mapped_ephemeris_utc":"${saved.events[0].mapped_ephemeris_utc}"`);
  const csvDownload = page.waitForEvent('download');
  await view.getByRole('button', { name: 'Download progressed phase dates CSV' }).click();
  const csv = await readFile(await (await csvDownload).path(), 'utf8');
  expect(csv).toContain(saved.events[0].effective_utc);
  await view.getByRole('button', { name: /Open saved phases/ }).click();
  await expect(view.getByRole('table', { name: /Progressed lunar phase dates/ }).getByRole('row')).toHaveCount(saved.events.length + 1);
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.screenshot({ path: resolve(renders, `phase-normal-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
});
