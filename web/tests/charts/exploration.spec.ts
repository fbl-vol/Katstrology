import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { personIdFor, seedLegacy } from '../support/legacy-fixture';

async function openChart(page: Page, name: string) {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-natal');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  if ((page.viewportSize()?.width ?? 1440) < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Name').fill(name);
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const personId = await personIdFor(page, name);
  const { chartId } = await seedLegacy(page, personId, { date: '1948-11-14', time: '21:14',
    zone: 'Europe/London', latitude: 51.5, longitude: -1 / 6, kind: 'natal' });
  const saved = await (await page.request.get(`/api/people/${personId}`)).json();
  await page.reload();
  if ((page.viewportSize()?.width ?? 1440) < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: new RegExp(name) }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  await page.locator('.chart-history > summary').click();
  const chart = page.locator(`.chart-history > details[data-kat-chart-id="${chartId}"]`);
  await chart.locator(':scope > summary').click();
  return { chart, chartId, saved };
}

for (const size of [{ width: 1440, height: 1024 }, { width: 390, height: 844 }, { width: 390, height: 560 }]) {
  test(`saved natal explorer catalogue and focus ${size.width}x${size.height}`, async ({ page }) => {
    await page.setViewportSize(size);
    const { chart, chartId } = await openChart(page, `Explorer ${size.width} ${size.height}`);
    const panel = chart.getByRole('region', { name: 'Chart browser and selected detail' });
    await expect(panel.getByRole('tab', { name: 'Positions 12' })).toBeVisible();
    await expect(panel.getByRole('tab', { name: 'Houses 14' })).toBeVisible();
    await panel.getByLabel('Find in positions').fill('south');
    const south = panel.getByRole('button', { name: /South Node/ });
    await south.click();
    await expect(panel.getByRole('heading', { name: 'South Node' })).toBeFocused();
    await expect(chart.locator('[data-highlight-body="south_node"]')).toHaveCount(1);
    await panel.getByRole('button', { name: 'Next → positions' }).click();
    await expect(panel.getByRole('heading', { name: 'Sun', exact: true })).toBeFocused();
    await panel.getByRole('button', { name: '← All positions' }).click();
    await expect(panel.getByLabel('Find in positions')).toHaveValue('south');
    await panel.getByRole('tab', { name: 'Houses 14' }).click();
    await panel.getByRole('button', { name: /^House 12 / }).click();
    await expect(panel).toContainText('actual cusp boundaries');
    await expect(chart.locator('.exploration-highlight > path')).toHaveCount(1);
    await panel.getByRole('button', { name: '← All houses' }).click();
    await expect(panel.getByRole('button', { name: /^House 12 / })).toBeFocused();
    await panel.getByRole('tab', { name: /^Patterns/ }).click();
    const projection = await (await page.request.get(`/api/charts/${chartId}/exploration`)).json();
    await expect(panel.getByRole('tab', { name: `Patterns ${projection.patterns.length}` })).toBeVisible();
    await panel.getByLabel('Find in patterns').fill('does not exist');
    await expect(panel).toContainText('No matching details');
    await panel.getByRole('button', { name: 'Clear search' }).click();
    mkdirSync('../.local/explorable-charts/renders', { recursive: true });
    await chart.locator('.natal-explorer').screenshot({ path: `../.local/explorable-charts/renders/catalogue-${size.width}-${size.height}.png` });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test('pattern read failure and retry leave individual exploration available', async ({ page }) => {
  await page.route('**/api/charts/*/exploration', route => route.fulfill({ status: 503, json: { error: 'synthetic' } }));
  const { chart } = await openChart(page, 'Explorer retry');
  const panel = chart.getByRole('region', { name: 'Chart browser and selected detail' });
  await panel.getByRole('button', { name: /^Sun / }).click();
  await expect(panel.getByRole('heading', { name: 'Sun', exact: true })).toBeVisible();
  await panel.getByRole('button', { name: '← All positions' }).click();
  await panel.getByRole('tab', { name: /^Patterns/ }).click();
  await expect(panel).toContainText('Patterns could not be loaded');
  await page.unroute('**/api/charts/*/exploration');
  await panel.getByRole('button', { name: 'Retry patterns' }).click();
  await expect(panel.getByRole('button', { name: 'Retry patterns' })).toHaveCount(0);
});
