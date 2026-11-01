import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/advanced-techniques');

test('manual natal MC contacts save a dated timeline and CSV without a message', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Midheaven transit contacts/ }).click();
  const view = page.getByRole('region', { name: 'Natal MC transit timeline' });
  await view.getByLabel('Person with a current natal').selectOption({ label: 'Synthetic transit reader' });
  await view.getByLabel('From (UTC, inclusive)').fill('2026-02-10');
  await view.getByLabel('Until (UTC, exclusive)').fill('2026-02-25');
  const posted = page.waitForResponse(response => response.request().method() === 'POST' &&
    new URL(response.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Calculate MC contacts' }).click();
  const reply = await posted;
  expect(reply.status()).toBe(201);
  const result = await reply.json();
  expect(result.status).toBe('supported');
  expect(result.method_version).toBe('natal-mc-transit-ecliptic-v1');
  expect(result.window_end_inclusive).toBe(false);
  expect(result.events.length).toBeGreaterThanOrEqual(1);
  await expect(view.getByRole('region', { name: 'MC contact results' })).toContainText('astronomical natal MC');
  await expect(view.getByRole('region', { name: 'MC contact results' })).not.toContainText('not independently verified');
  const download = page.waitForEvent('download');
  await view.getByRole('button', { name: 'Download CSV timeline' }).click();
  expect(await readFile(await (await download).path(), 'utf8')).toContain('UTC instant,Transiting body,Aspect');
  await view.getByRole('button', { name: /Open saved timeline/ }).click();
  await expect(view.getByRole('table', { name: /Transiting Sun to saved natal MC/ })
    .getByRole('row')).toHaveCount(result.events.length + 1);
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(renders, `mc-normal-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
});
