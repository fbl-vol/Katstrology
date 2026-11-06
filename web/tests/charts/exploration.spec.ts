import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { personIdFor, seedLegacy } from '../support/legacy-fixture';
import { patternFixture } from '../support/exploration-fixture';
import type { Chart } from '../../src/features/charts/natal';

async function openChart(page: Page, name: string, syntheticPatterns = false) {
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
  if (syntheticPatterns) {
    const record = saved.charts.find((c: Chart) => c.id === chartId);
    const projection = patternFixture(record);
    await page.route(`**/api/people/${personId}`, route => route.fulfill({ json: saved }));
    await page.route(`**/api/charts/${chartId}/exploration`, route => route.fulfill({ json: projection }));
  }
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

test('a late exploration read cannot follow navigation to a different person', async ({ page }) => {
  let release!: () => void;
  let received!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const arrived = new Promise<void>(resolve => { received = resolve; });
  let reads = 0;
  await page.route('**/api/charts/*/exploration', async route => {
    reads++;
    const response = await route.fetch(); received(); await gate; await route.fulfill({ response });
  });
  const { chart } = await openChart(page, 'Explorer delayed source');
  await arrived;
  const panel = chart.getByRole('region', { name: 'Chart browser and selected detail' });
  await panel.getByRole('tab', { name: /^Patterns/ }).click();
  await expect(panel).toContainText('Loading patterns');
  await panel.getByRole('tab', { name: /^Positions/ }).click();
  await panel.getByRole('button', { name: /^Sun / }).click();
  expect(reads).toBe(1);
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Name').fill('Different empty person');
  await page.getByRole('dialog').getByRole('button', { name: 'Create person' }).click();
  await expect(page.getByRole('heading', { name: 'Different empty person' })).toBeVisible();
  release();
  await expect(page.getByRole('region', { name: 'Chart browser and selected detail' })).toHaveCount(0);
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Explorer delayed source/ }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  await page.locator('.chart-history > summary').click();
  await chart.locator(':scope > summary').click();
  await expect(panel.getByRole('heading', { name: 'Browse this chart' })).toBeVisible();
});

// Find an actual exposed SVG area, then use browser mouse/touch input, not dispatchEvent.
async function patternPoint(wheel: import('@playwright/test').Locator, overlap: boolean) {
  await wheel.scrollIntoViewIfNeeded();
  return wheel.evaluate((element, wantOverlap) => {
    const svg = element as SVGSVGElement;
    const polygons = [...svg.querySelectorAll<SVGPolygonElement>('.exploration-target polygon')];
    for (let y = 163; y < 317; y += 1) for (let x = 163; x < 317; x += 1) {
      const point = new DOMPoint(x, y);
      const matches = polygons.filter(p => p.isPointInFill(point));
      if (wantOverlap ? matches.length < 3 : matches.length !== 1) continue;
      const screen = point.matrixTransform(svg.getScreenCTM()!);
      const top = document.elementFromPoint(screen.x, screen.y);
      if (top?.tagName !== 'polygon' || [[-1, 0], [1, 0], [0, -1], [0, 1]].some(([dx, dy]) =>
        document.elementFromPoint(screen.x + dx, screen.y + dy)?.tagName !== 'polygon')) continue;
      return { x: screen.x, y: screen.y, ids: matches.map(p => p.parentElement!.getAttribute('data-wheel-entry')) };
    }
    throw new Error('No exposed pattern area at this viewport');
  }, overlap);
}

test.describe('direct natal exploration', () => {
  test.use({ hasTouch: true });
  for (const size of [{ width: 1440, height: 1024 }, { width: 390, height: 844 }, { width: 390, height: 560 }]) {
    test(`patterns, overlap, cancellation and input ${size.width}x${size.height}`, async ({ page }) => {
      await page.setViewportSize(size);
      const { chart } = await openChart(page, `Spatial ${size.width} ${size.height}`, true);
      const wheel = chart.getByRole('group', { name: /Tropical natal wheel/ });
      const panel = chart.getByRole('region', { name: 'Chart browser and selected detail' });
      const press = (p: { x: number; y: number }) => size.width < 700 ? page.touchscreen.tap(p.x, p.y) : page.mouse.click(p.x, p.y);
      await expect(wheel.locator('.exploration-target polygon')).toHaveCount(6);
      // Cancellation without a previous selection restores the directory.
      await press(await patternPoint(wheel, true));
      await panel.getByRole('button', { name: 'Back without choosing' }).click();
      await expect(panel.getByRole('heading', { name: 'Browse this chart' })).toBeVisible();
      await expect(wheel.locator('[data-highlight-edge]')).toHaveCount(0);
      // Unique interior and complete highlighted edges.
      await press(await patternPoint(wheel, false));
      await expect(panel.getByRole('heading', { name: 'Grand Trine', exact: true })).toBeFocused();
      await expect(wheel.locator('[data-highlight-edge]')).toHaveCount(3);
      await expect(wheel.locator('[data-highlight-body]')).toHaveCount(3);
      const overlap = await patternPoint(wheel, true);
      await press(overlap);
      await expect(panel.getByRole('heading', { name: 'Patterns at this point' })).toBeFocused();
      await expect(wheel.locator('.exploration-marker')).toHaveCount(1);
      mkdirSync('../.local/explorable-charts/renders', { recursive: true });
      await panel.screenshot({ path: `../.local/explorable-charts/renders/overlap-${size.width}-${size.height}.png` });
      const actual = await panel.locator('[data-entry]').evaluateAll(nodes => nodes.map(n => n.getAttribute('data-entry')));
      expect(actual.sort()).toEqual(overlap.ids.sort());
      await panel.getByRole('button', { name: 'Back without choosing' }).click();
      await expect(panel.getByRole('heading', { name: 'Grand Trine', exact: true })).toBeVisible();
      await expect(wheel.locator('[data-highlight-edge]')).toHaveCount(3);
      await press(await patternPoint(wheel, true));
      const contained = panel.locator('.explorer-contained');
      await contained.locator('summary').click();
      await contained.getByRole('button').first().click();
      await expect(panel.getByRole('heading', { name: /T-square/ })).toBeFocused();
      await expect(wheel.locator('[data-highlight-edge]')).toHaveCount(3);
      await panel.locator('.explorer-parent').getByRole('button').click();
      await expect(panel.getByRole('heading', { name: 'Grand Cross', exact: true })).toBeFocused();
      await expect(wheel.locator('[data-highlight-edge]')).toHaveCount(6);
      await expect(wheel.locator('[data-highlight-edge] path[stroke-dasharray]')).toHaveCount(2);
      mkdirSync('../.local/explorable-charts/renders', { recursive: true });
      await chart.locator('.natal-explorer').screenshot({ path: `../.local/explorable-charts/renders/cross-${size.width}-${size.height}.png` });
      // Named wheel keyboard controls select directly, even when shapes overlap.
      const sun = wheel.getByRole('button', { name: /^Explore Sun:/ });
      await sun.focus(); await sun.press('Space');
      await expect(panel.getByRole('heading', { name: 'Sun', exact: true })).toBeFocused();
      const conjunction = wheel.getByRole('button', { name: /^Explore Sun conjunction Mercury:/ });
      await conjunction.focus(); await conjunction.press('Enter');
      await expect(wheel.locator('[data-highlight-edge] circle')).toHaveCount(2);
      // Actual pointer on an aspect line, not a synthetic dispatched event.
      await wheel.evaluate(element => element.scrollIntoView({ block: 'center' }));
      const line = wheel.locator('[data-wheel-entry="square:mars:venus"] path');
      const center = await line.evaluate(element => {
        const path = element as SVGPathElement;
        const p = path.getPointAtLength(path.getTotalLength() / 2).matrixTransform(path.getScreenCTM()!);
        return { x: p.x, y: p.y };
      });
      await press(center);
      if (await panel.getByRole('heading', { name: 'Details at this point' }).isVisible())
        await panel.getByRole('button', { name: /^Venus square Mars/ }).click();
      await expect(panel.getByRole('heading', { name: 'Venus square Mars', exact: true })).toBeVisible();
      // Actual pointer target on a glyph and a house number.
      for (const target of [wheel.getByRole('button', { name: /^Explore Jupiter:/ }), wheel.getByRole('button', { name: /^Explore House 12:/ })]) {
        await wheel.evaluate(element => element.scrollIntoView({ block: 'center' }));
        const box = await target.boundingBox();
        await press({ x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 });
        await expect(panel.getByRole('heading', { name: /^(Jupiter|House 12)$/ })).toBeVisible();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }
});
