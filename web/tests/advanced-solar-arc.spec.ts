import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/advanced-techniques');

test('true solar arc is not MCp or fixed one degree per year and replays saved wheel', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Solar-arc directions/ }).click();
  const view = page.getByRole('region', { name: 'True solar-arc directions' });
  await view.getByLabel('Person with a current natal').selectOption({ label: 'Synthetic transit reader' });
  await view.getByLabel('Effective date (UTC midnight)').fill('2026-01-01');
  const posted = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Calculate solar arc' }).click();
  const saved = await (await posted).json();
  expect(saved.status).toBe('supported');
  expect(saved.method_version).toBe('true-progressed-sun-forward-solar-arc-v1');
  expect(saved.arc_degrees).not.toBeCloseTo(24, 2);
  expect(saved.arc_degrees).toBeGreaterThan(0);
  expect(saved.positions).toHaveLength(12);
  await expect(view.getByRole('region', { name: 'Solar-arc result' })).toContainText('not a simultaneous sky');
  await view.getByText(/Directed positions and natal aspects/).click();
  await expect(view.getByRole('table', { name: /Solar-arc directions/ }).getByRole('row')).toHaveCount(13);
  const download = page.waitForEvent('download');
  await view.getByRole('button', { name: 'Download safe SVG wheel' }).click();
  const markup = await readFile(await (await download).path(), 'utf8');
  expect(markup).toContain(`"arc_degrees":${saved.arc_degrees}`);
  expect(markup).toContain(`"mapped_ephemeris_utc":"${saved.mapped_ephemeris_utc}"`);
  await view.getByRole('button', { name: /Open saved solar arc/ }).click();
  await view.getByText(/Directed positions and natal aspects/).click();
  await expect(view.getByRole('table', { name: /Solar-arc directions/ }).getByRole('row')).toHaveCount(13);
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.screenshot({ path: resolve(renders, `solar-arc-normal-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
});
