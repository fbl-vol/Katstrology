import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { captureResultHierarchy } from '../support/ui-craft';

const renders = resolve(import.meta.dirname, '../../../.local/advanced-techniques');

test('composite and uncorrected Davison keep two owner source versions and export provenance', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Composite and Davison/ }).click();
  const view = page.getByRole('region', { name: 'Relationship-derived chart' });
  await view.getByLabel('First person').selectOption({ label: 'Synthetic transit reader' });
  await view.getByLabel('Second person').selectOption({ label: 'Other synthetic reader' });
  const posted = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Calculate derived chart' }).click();
  const composite = await (await posted).json();
  expect(composite.status).toBe('supported');
  expect(composite.technique).toBe('midpoint_composite');
  expect(composite.physical_instant).toBeNull();
  expect(composite.houses).toBe('not_defined');
  await expect(view.getByRole('region', { name: 'Derived chart result' })).toContainText('no physical instant');
  await captureResultHierarchy(page, view.getByRole('region', { name: 'Derived chart result' }), view.getByRole('navigation', { name: 'Saved relationship charts' }), 'composite');
  await expect(view.getByRole('region', { name: 'Derived chart result' })).not.toContainText('not independently verified');
  await expect(view.getByRole('region', { name: 'Derived chart result' }).getByText('Chiron in this chart')).toBeVisible();
  const exported = page.waitForEvent('download');
  await view.getByText('Download chart', { exact: true }).click();
  await view.getByRole('button', { name: 'Download safe SVG wheel' }).click();
  const svg = await readFile(await (await exported).path(), 'utf8');
  expect(svg).toContain(`"chart_a_id":"${composite.chart_a_id}"`);
  expect(svg).toContain(`"chart_b_id":"${composite.chart_b_id}"`);
  await view.getByRole('button', { name: /Open saved derived chart/ }).click();
  await view.getByText(/Composite planetary positions and aspects/).click();
  await expect(view.getByRole('table', { name: /Composite planets/ }).getByRole('row')).toHaveCount(11);
  for (const size of [{ name: 'desktop', width: 1440, height: 1024 },
                       { name: 'mobile', width: 390, height: 844 }]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.screenshot({ path: resolve(renders, `composite-normal-${size.name}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1024 });
  await view.getByLabel('Technique').selectOption('uncorrected_davison');
  const davisonPosted = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Calculate derived chart' }).click();
  const davison = await (await davisonPosted).json();
  expect(davison.status).toBe('supported');
  expect(davison.technique).toBe('uncorrected_davison');
  expect(davison.derived_natal.instant_utc).toBe(davison.derived_instant_utc);
  await expect(view.getByRole('region', { name: 'Derived chart result' })).toContainText('not a spherical midpoint');
  await captureResultHierarchy(page, view.getByRole('region', { name: 'Derived chart result' }), view.getByRole('navigation', { name: 'Saved relationship charts' }), 'davison');
  const derivedExport = page.waitForEvent('download');
  await view.getByText('Download chart', { exact: true }).click();
  await view.getByRole('button', { name: 'Download safe SVG wheel' }).click();
  const derivedSvg = await readFile(await (await derivedExport).path(), 'utf8');
  expect(derivedSvg).toContain(`"chart_b_id":"${davison.chart_b_id}"`);
  expect(derivedSvg).toContain(`"derived_instant_utc":"${davison.derived_instant_utc}"`);
  await view.getByRole('button', { name: /Open saved derived chart/ }).click();
  await view.locator('.natal-detail .chart-supporting-data summary').click();
  await expect(view.getByRole('table', { name: /Uncorrected Davison positions/ }).getByRole('row').first()).toBeVisible();
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.screenshot({ path: resolve(renders, `derived-normal-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
});
