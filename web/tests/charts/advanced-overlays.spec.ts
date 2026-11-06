import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/advanced-techniques');

test('directional overlays save and replay with separate recipient house tables', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Synastry/ }).click();
  const view = page.getByRole('region', { name: 'Synastry chart' });
  await view.getByLabel('Person A').selectOption({ label: 'Synthetic transit reader' });
  await view.getByLabel('Person B').selectOption({ label: 'Other synthetic reader' });
  await view.getByRole('button', { name: 'Compare charts' }).click();
  const first = view.getByRole('region', { name: 'Synthetic transit reader in Other synthetic reader houses' });
  const second = view.getByRole('region', { name: 'Other synthetic reader in Synthetic transit reader houses' });
  await expect(first.getByRole('table')).toContainText('placidus');
  await expect(first.getByRole('row')).toHaveCount(11);
  await expect(second.getByRole('row')).toHaveCount(11);
  const sent = page.waitForResponse(response => response.request().method() === 'POST' &&
    new URL(response.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Save this comparison' }).click();
  const reply = await sent;
  expect(reply.status()).toBe(201);
  const saved = await reply.json();
  expect(saved.house_overlays.a_in_b.placements).toHaveLength(10);
  await expect(view.getByRole('button', { name: /Open saved comparison/ })).toBeVisible();
  await view.getByRole('button', { name: /Open saved comparison/ }).click();
  await expect(first.getByRole('row')).toHaveCount(11);
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  const download = page.waitForEvent('download');
  await view.getByRole('button', { name: 'Download safe SVG wheel' }).click();
  const markup = await readFile(await (await download).path(), 'utf8');
  expect(markup).toContain('"house_overlays"');
  expect(markup).toContain('"recipient_house"');
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(renders, `overlay-normal-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
  await page.reload();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Synastry/ }).click();
  const reopened = page.getByRole('region', { name: 'Synastry chart' });
  await reopened.getByLabel('Person A').selectOption({ label: 'Synthetic transit reader' });
  await reopened.getByLabel('Person B').selectOption({ label: 'Other synthetic reader' });
  await reopened.getByRole('button', { name: /Open saved comparison/ }).click();
  await expect(reopened.getByRole('region', { name: 'Synthetic transit reader in Other synthetic reader houses' })
    .getByRole('row')).toHaveCount(11);
});
