import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { personIdFor, seedLegacy } from '../support/legacy-fixture';
import { patternFixture } from '../support/exploration-fixture';
import type { Chart } from '../../src/features/charts/natal';

test.beforeEach(async ({ page }) => page.setViewportSize({ width: 1440, height: 1024 }));

async function openChart(page: Page, name: string, syntheticPatterns: boolean | 'multi' | 'exact' | 'trine' = false) {
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
    const record: Chart = saved.charts.find((c: Chart) => c.id === chartId);
    const projection = patternFixture(record, syntheticPatterns === 'multi');
    if (syntheticPatterns === 'exact') {
      record.result.natal!.positions.find(p => p.id === 'mercury')!.longitude_degrees = 142;
      record.result.natal!.aspects.find(a => a.kind === 'conjunction')!.orb_degrees = 0;
    }
    if (syntheticPatterns === 'trine') {
      projection.patterns = projection.patterns.filter(p => p.kind === 'grand_trine');
      record.result.natal!.aspects = record.result.natal!.aspects.filter(a => a.kind === 'trine' || a.kind === 'conjunction');
    }
    saved.active_chart_id = chartId;
    await page.route(`**/api/people/${personId}`, route => route.fulfill({ json: saved }));
    await page.route(`**/api/charts/${chartId}/exploration`, route => route.fulfill({ json: projection }));
  }
  await page.reload();
  if ((page.viewportSize()?.width ?? 1440) < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: new RegExp(name) }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  const chart = syntheticPatterns ? page.locator('.profile-active-chart') :
    page.locator(`.chart-history > details[data-kat-chart-id="${chartId}"]`);
  if (!syntheticPatterns) {
    await page.locator('.chart-history > summary').click();
    await chart.locator(':scope > summary').click();
  }
  return { chart, chartId, saved };
}

for (const size of [{ width: 1440, height: 1024 }, { width: 390, height: 844 }, { width: 390, height: 560 }]) {
  test(`saved natal explorer catalogue and focus ${size.width}x${size.height}`, async ({ page }) => {
    await page.setViewportSize(size);
    const { chart, chartId } = await openChart(page, `Explorer ${size.width} ${size.height}`);
    const panel = chart.getByRole('region', { name: 'Chart browser and selected detail' });
    await expect(panel.getByRole('tab', { name: 'Positions 12' })).toBeVisible();
    await expect(panel.getByRole('tab', { name: 'Houses 14' })).toBeVisible();
    await panel.getByRole('tab', { name: 'Positions 12' }).focus();
    await panel.getByRole('tab', { name: 'Positions 12' }).press('End');
    await expect(panel.getByRole('tab', { name: /^Patterns/ })).toBeFocused();
    await panel.getByRole('tab', { name: /^Patterns/ }).press('Home');
    await panel.getByLabel('Find in positions').fill('south');
    const south = panel.getByRole('button', { name: /South Node/ });
    await south.click();
    await expect(panel.getByRole('heading', { name: 'South Node' })).toBeFocused();
    await expect(chart.locator('[data-highlight-body="south_node"]')).toHaveCount(1);
    await panel.getByRole('button', { name: 'Next → position' }).click();
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
  mkdirSync('../.local/explorable-charts/renders', { recursive: true });
  await panel.evaluate(element => element.scrollIntoView({ block: 'start' }));
  await page.screenshot({ path: '../.local/explorable-charts/renders/failed-read.png' });
  await page.unroute('**/api/charts/*/exploration');
  await panel.getByRole('button', { name: 'Retry patterns' }).click();
  await expect(panel.getByRole('button', { name: 'Retry patterns' })).toHaveCount(0);
});

for (const status of ['supported', 'unavailable'] as const) {
  test(`empty pattern projection distinguishes ${status}`, async ({ page }) => {
    await page.route('**/api/charts/*/exploration', route => route.fulfill({ json: {
      chart_id: new URL(route.request().url()).pathname.split('/')[3],
      rule_version: 'natal-patterns-v1', source_status: 'current', status,
      reason: status === 'supported' ? null : 'unusable_facts', patterns: [],
    } }));
    const { chart } = await openChart(page, `Explorer ${status}`);
    const panel = chart.getByRole('region', { name: 'Chart browser and selected detail' });
    await panel.getByRole('tab', { name: /^Patterns/ }).click();
    if (status === 'supported') await expect(panel).toContainText('No supported patterns match');
    else {
      await expect(panel).toContainText('Patterns need established natal positions and aspects');
      await expect(panel.getByText('No supported patterns match', { exact: false })).toHaveCount(0);
    }
    await panel.evaluate(element => element.scrollIntoView({ block: 'start' }));
    mkdirSync('../.local/explorable-charts/renders', { recursive: true });
    await page.screenshot({ path: `../.local/explorable-charts/renders/${status}.png` });
  });
}

test('a late exploration read cannot follow navigation to a different person', async ({ page }) => {
  let release!: () => void;
  let received!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const arrived = new Promise<void>(resolve => { received = resolve; });
  let reads = 0;
  let delivered!: () => void;
  const delivery = new Promise<void>(resolve => { delivered = resolve; });
  await page.route('**/api/charts/*/exploration', async route => {
    reads++;
    const response = await route.fetch();
    const body = await response.json();
    received(); await gate;
    await route.fulfill({ status: response.status(), json: body });
    delivered();
  });
  const { chart } = await openChart(page, 'Explorer delayed source');
  await arrived;
  const panel = chart.getByRole('region', { name: 'Chart browser and selected detail' });
  await panel.getByRole('tab', { name: /^Patterns/ }).click();
  await expect(panel).toContainText('Loading patterns');
  mkdirSync('../.local/explorable-charts/renders', { recursive: true });
  await panel.evaluate(element => element.scrollIntoView({ block: 'start' }));
  await page.screenshot({ path: '../.local/explorable-charts/renders/loading-read.png' });
  await panel.getByRole('tab', { name: /^Positions/ }).click();
  await panel.getByRole('button', { name: /^Sun / }).click();
  expect(reads).toBe(1);
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Name').fill('Different empty person');
  await page.getByRole('dialog').getByRole('button', { name: 'Create person' }).click();
  await expect(page.getByRole('heading', { name: 'Different empty person' })).toBeVisible();
  release(); await delivery;
  await expect(page.getByRole('region', { name: 'Chart browser and selected detail' })).toHaveCount(0);
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Explorer delayed source/ }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  await page.locator('.chart-history > summary').click();
  await chart.locator(':scope > summary').click();
  await expect(panel.getByRole('heading', { name: 'Browse this chart' })).toBeVisible();
  await expect(panel.getByRole('tab', { name: /^Patterns \d+$/ })).toBeVisible();
});

test('contained pattern details retain every matching Grand Cross', async ({ page }) => {
  const { chart } = await openChart(page, 'Multiple parent formations', 'multi');
  const panel = chart.getByRole('region', { name: 'Chart browser and selected detail' });
  const target = chart.getByRole('button', { name: /^Explore T-square · Mars apex:/ });
  await target.focus(); await target.press('Enter');
  await expect(panel.locator('.explorer-parent .explorer-entry')).toHaveCount(2);
  await expect(panel.locator('.explorer-parent')).toContainText('Neptune');
  await expect(panel.locator('.explorer-parent')).toContainText('Pluto');
  await panel.locator('.explorer-parent .explorer-entry').last().click();
  await expect(chart.locator('[data-highlight-edge]')).toHaveCount(6);
  await expect(chart.locator('[data-highlight-body="pluto"]')).toHaveCount(1);
  await expect(chart.locator('[data-highlight-body="neptune"]')).toHaveCount(0);
});

// Find an actual exposed SVG area, then use browser mouse/touch input, not dispatchEvent.
async function patternPoint(wheel: import('@playwright/test').Locator, overlap: boolean, requireTrine = false) {
  await wheel.scrollIntoViewIfNeeded();
  return wheel.evaluate((element, { wantOverlap, requireTrine }) => {
    const svg = element as SVGSVGElement;
    const polygons = [...svg.querySelectorAll<SVGPolygonElement>('.exploration-target polygon')];
    let best: { x: number; y: number; ids: (string | null)[]; margin: number } | null = null;
    for (let y = 163; y < 317; y += 2) for (let x = 163; x < 317; x += 2) {
      const point = new DOMPoint(x, y);
      const matches = polygons.filter(p => p.isPointInFill(point));
      if (wantOverlap ? matches.length < 3 : matches.length !== 1) continue;
      if (requireTrine && !matches.some(p => p.parentElement!.getAttribute('data-wheel-entry')!.endsWith('|trine'))) continue;
      const screen = point.matrixTransform(svg.getScreenCTM()!);
      const top = document.elementFromPoint(screen.x, screen.y);
      if (top?.tagName !== 'polygon') continue;
      let margin = 0;
      for (let radius = 1; radius <= 10; radius++) {
        if ([[-radius, 0], [radius, 0], [0, -radius], [0, radius]].some(([dx, dy]) =>
          document.elementFromPoint(screen.x + dx, screen.y + dy)?.tagName !== 'polygon')) break;
        margin = radius;
      }
      if (margin > (best?.margin ?? 0)) best = { x: screen.x, y: screen.y,
        ids: matches.map(p => p.parentElement!.getAttribute('data-wheel-entry')), margin };
    }
    if (best) return best;
    throw new Error('No exposed pattern area at this viewport');
  }, { wantOverlap: overlap, requireTrine });
}

test.describe('direct natal exploration', () => {
  test.use({ hasTouch: true });
  for (const exact of [false, true]) for (const input of ['mouse', 'touch'] as const) {
    test(`conjunction hit geometry ${exact ? 'exact' : 'near'} ${input}`, async ({ page }) => {
      test.setTimeout(60_000);
      await page.setViewportSize(input === 'touch' ? { width: 390, height: 844 } : { width: 1440, height: 1024 });
      const { chart } = await openChart(page, `Conjunction ${exact} ${input}`, exact ? 'exact' : true);
      const wheel = chart.locator('svg.natal-wheel');
      const panel = chart.getByRole('region', { name: 'Chart browser and selected detail' });
      const conjunction = wheel.locator('[data-wheel-entry="conjunction:mercury:sun"]');
      const press = (p: { x: number; y: number }) => input === 'touch' ? page.touchscreen.tap(p.x, p.y) : page.mouse.click(p.x, p.y);
      // The centre is genuinely shared by three aspects; neither DOM paint order nor
      // an endpoint special case may silently choose the conjunction for the reader.
      await conjunction.focus();
      await conjunction.press('Tab');
      await conjunction.focus();
      expect(await conjunction.evaluate(element => element.matches(':focus-visible'))).toBe(true);
      await expect(conjunction.locator('[data-aspect-hit]').first()).toHaveCSS('stroke-width', '16px');
      mkdirSync('../.local/explorable-charts/renders', { recursive: true });
      await wheel.screenshot({ path: `../.local/explorable-charts/renders/conjunction-focus-${exact}-${input}.png` });
      const offsets = ['center', 'old-edge', 'outer-edge', 'arc', ...(input === 'touch' ? ['house-overlap'] : [])];
      for (const endpointIndex of [0, 1]) for (const offset of offsets) {
        // Only the Sun-side radial edge overlaps House 1; Mercury's is outside it.
        if (offset === 'house-overlap' && endpointIndex === 1) continue;
        await wheel.evaluate(element => element.scrollIntoView({ block: 'center' }));
        await conjunction.focus();
        const p = await conjunction.evaluate((element, { offset, endpointIndex }) => {
          const path = element.querySelector('path')!;
          const matrix = path.getScreenCTM()!;
          const scale = Math.hypot(matrix.a, matrix.b);
          const local = path.getPointAtLength(path.getTotalLength() * (offset === 'arc' ? .5 : endpointIndex));
          const center = new DOMPoint(240, 240).matrixTransform(matrix);
          const endpoint = local.matrixTransform(matrix);
          const radial = Math.hypot(endpoint.x - center.x, endpoint.y - center.y);
          const distance = offset === 'center' ? 0 : offset === 'arc' ? 6 : 5 * scale + (offset === 'old-edge' ? 3 : 7);
          const dx = (endpoint.x - center.x) / radial, dy = (endpoint.y - center.y) / radial;
          // The mobile radial outer edge is shared with House 1. Use the exposed
          // tangential edge here; house precedence is exercised separately.
          return { x: endpoint.x + distance * (offset === 'outer-edge' ? dy : dx),
            y: endpoint.y + distance * (offset === 'outer-edge' ? -dx : dy) };
        }, { offset, endpointIndex });
        await press(p);
        if (offset === 'center') {
          await expect(panel.getByRole('heading', { name: 'Details at this point' })).toBeFocused();
          expect((await panel.locator('[data-entry]').evaluateAll(nodes => nodes.map(n => n.getAttribute('data-entry')))).sort())
            .toEqual(['conjunction:mercury:sun', 'trine:jupiter:sun', 'trine:moon:sun']);
        }
        // Soft failure preserves evidence for all physical presses on old behavior.
        const choices = panel.getByRole('heading', { name: 'Details at this point' });
        if (await choices.isVisible()) {
          await expect.soft(panel.getByRole('button', { name: /^Sun conjunction Mercury/ }), offset).toBeVisible();
          await panel.getByRole('button', { name: /^Sun conjunction Mercury/ }).click();
        }
        const expected = offset === 'house-overlap' ? 'House 1' : 'Sun conjunction Mercury';
        await expect.soft(panel.getByRole('heading', { name: expected, exact: true }), offset).toBeFocused();
        mkdirSync('../.local/explorable-charts/renders', { recursive: true });
        await page.screenshot({ path: `../.local/explorable-charts/renders/conjunction-${exact}-${input}-${endpointIndex}-${offset}.png` });
        // Reset so a previous successful selection cannot conceal a missed press.
        await chart.getByRole('button', { name: 'Browse all', exact: true }).click();
      }
    });
  }
  for (const width of [1440, 390]) test(`unique pattern interior remains usable ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const { chart } = await openChart(page, `Exposed trine ${width}`, 'trine');
    const wheel = chart.locator('svg.natal-wheel');
    const p = await patternPoint(wheel, false);
    expect(p.margin).toBe(10);
    if (width === 390) await page.touchscreen.tap(p.x, p.y);
    else await page.mouse.click(p.x, p.y);
    await expect(chart.getByRole('heading', { name: 'Grand Trine', exact: true })).toBeFocused();
  });
  test('mobile aspect six CSS pixel offset retains direct line selection', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const { chart } = await openChart(page, 'Offset aspect touch', true);
    const wheel = chart.locator('svg.natal-wheel');
    const panel = chart.getByRole('region', { name: 'Chart browser and selected detail' });
    await wheel.evaluate(element => element.scrollIntoView({ block: 'center' }));
    await wheel.evaluate(element => element.addEventListener('click', event => {
      const e = event as MouseEvent;
      element.setAttribute('data-test-press', JSON.stringify({ x: e.clientX, y: e.clientY }));
    }, { once: true, capture: true }));
    const location = await wheel.locator('[data-wheel-entry="square:mars:venus"] path').first().evaluate(element => {
      const path = element as SVGPathElement, matrix = path.getScreenCTM()!;
      const a = path.getPointAtLength(0).matrixTransform(matrix);
      const b = path.getPointAtLength(path.getTotalLength()).matrixTransform(matrix);
      const length = Math.hypot(b.x - a.x, b.y - a.y);
      return { x: (a.x + b.x) / 2 + 6 * (b.y - a.y) / length,
        y: (a.y + b.y) / 2 - 6 * (b.x - a.x) / length };
    });
    await page.touchscreen.tap(location.x, location.y);
    const actual = JSON.parse((await wheel.getAttribute('data-test-press'))!);
    expect(Math.hypot(actual.x - location.x, actual.y - location.y)).toBeLessThan(1.5);
    await test.info().attach('six-css-pixel-press', { body: JSON.stringify({ requested: location, delivered: actual }), contentType: 'application/json' });
    await expect(panel.getByRole('heading', { name: 'Venus square Mars', exact: true })).toBeFocused();
    mkdirSync('../.local/explorable-charts/renders', { recursive: true });
    await page.screenshot({ path: '../.local/explorable-charts/renders/mobile-six-pixel-offset.png' });
  });
  for (const size of [{ width: 1440, height: 1024 }, { width: 1920, height: 1080 },
    { width: 2560, height: 1080 }, { width: 3440, height: 1440 },
    { width: 390, height: 844 }, { width: 390, height: 560 }]) {
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
      // Wider mobile line targets cover the tiny trine-only sliver in this dense
      // graph. Its exposed shared interior must still offer the trine honestly.
      const trinePoint = await patternPoint(wheel, true, true);
      expect(trinePoint.margin).toBeGreaterThanOrEqual(3);
      await test.info().attach('exposed-shared-interior', { body: JSON.stringify(trinePoint), contentType: 'application/json' });
      await press(trinePoint);
      await panel.getByRole('button', { name: /^Grand Trine / }).click();
      await expect(panel.getByRole('heading', { name: 'Grand Trine', exact: true })).toBeFocused();
      await expect(wheel.locator('[data-highlight-edge]')).toHaveCount(3);
      await expect(wheel.locator('[data-highlight-body]')).toHaveCount(3);
      mkdirSync('../.local/explorable-charts/renders', { recursive: true });
      await page.screenshot({ path: `../.local/explorable-charts/renders/trine-detail-${size.width}-${size.height}.png` });
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
      await page.screenshot({ path: `../.local/explorable-charts/renders/t-square-detail-${size.width}-${size.height}.png` });
      await panel.locator('.explorer-parent').getByRole('button').click();
      await expect(panel.getByRole('heading', { name: 'Grand Cross', exact: true })).toBeFocused();
      await expect(wheel.locator('[data-highlight-edge]')).toHaveCount(6);
      await expect(wheel.locator('[data-highlight-edge] path[stroke-dasharray]')).toHaveCount(2);
      await panel.getByRole('button', { name: 'Next → pattern' }).click();
      await expect(panel.getByRole('heading', { name: 'T-square · Mars apex', exact: true })).toBeFocused();
      await panel.getByRole('button', { name: '← Previous pattern' }).click();
      await expect(panel.getByRole('heading', { name: 'Grand Cross', exact: true })).toBeFocused();
      if (size.width === 1440) {
        const pending = page.waitForEvent('download');
        await chart.getByRole('button', { name: 'Download safe SVG wheel' }).click();
        const markup = await readFile(await (await pending).path(), 'utf8');
        expect(markup).not.toMatch(/data-wheel-entry|data-highlight-edge|exploration-marker|natal-patterns-v1/);
        expect(markup).toContain('kat-chart-provenance');
        expect(markup).toContain('Natal · tropical');
      }
      mkdirSync('../.local/explorable-charts/renders', { recursive: true });
      await wheel.evaluate(element => element.scrollIntoView({ block: 'center' }));
      await page.screenshot({ path: `../.local/explorable-charts/renders/cross-wheel-${size.width}-${size.height}.png` });
      await panel.evaluate(element => element.scrollIntoView({ block: 'start' }));
      await page.screenshot({ path: `../.local/explorable-charts/renders/cross-detail-${size.width}-${size.height}.png` });
      if (size.width === 1440) {
        await page.getByRole('button', { name: 'Settings', exact: true }).click();
        await page.getByRole('button', { name: /Appearance/ }).click();
        await page.getByRole('region', { name: 'Appearance' }).getByRole('button', { name: 'Dark', exact: true }).click();
        await page.getByRole('region', { name: 'Appearance' }).getByRole('button', { name: /Blue Hour/ }).click();
        await page.getByRole('button', { name: 'Close settings panel' }).click();
        await page.getByRole('button', { name: 'Back to workspace' }).click();
        await expect(wheel.locator('[data-highlight-edge]')).toHaveCount(6);
        await panel.evaluate(element => element.scrollIntoView({ block: 'start' }));
        await page.screenshot({ path: '../.local/explorable-charts/renders/cross-blue-hour.png' });
      }
      // Named wheel keyboard controls select directly, even when shapes overlap.
      const sun = wheel.getByRole('button', { name: /^Explore Sun:/ });
      await sun.focus(); await sun.press('Space');
      await expect(panel.getByRole('heading', { name: 'Sun', exact: true })).toBeFocused();
      const conjunction = wheel.getByRole('button', { name: /^Explore Sun conjunction Mercury:/ });
      await conjunction.focus(); await conjunction.press('Enter');
      await expect(wheel.locator('[data-highlight-edge] circle')).toHaveCount(2);
      // Actual pointer on an aspect line, not a synthetic dispatched event.
      await wheel.evaluate(element => element.scrollIntoView({ block: 'center' }));
      const line = wheel.locator('[data-wheel-entry="square:mars:venus"] path').first();
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
