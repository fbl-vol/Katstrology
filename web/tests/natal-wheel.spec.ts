import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { personIdFor, seedLegacy } from './legacy-fixture';
import { themes } from '../src/themes';

const evidence = resolve(import.meta.dirname, '../../.local/natal-wheel');
const addedPaletteIds = new Set(['peony', 'wisteria', 'apricot-silk', 'sea-pearl',
  'black-cherry', 'moonstone', 'cocoa-rose', 'midnight-orchid']);
const stage = process.env.KAT_WHEEL_CAPTURE_STAGE || 'after';
const fixtures = [
  { name: 'ordinary', date: '2024-03-20', time: '03:06', zone: 'Europe/Copenhagen',
    latitude: 55.67594, longitude: 12.56553, aspectLines: 11 },
  { name: 'dense', date: '2000-06-09', time: '13:00', zone: 'Europe/London',
    latitude: 51.5, longitude: -0.166666666666667, aspectLines: 25 },
];

test.beforeAll(() => mkdirSync(evidence, { recursive: true }));

test('eight added palettes keep natal geometry, screen PNG colors and light print output', async ({ page }) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-natal');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const name = 'Synthetic palette wheel reader';
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill(name);
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const id = await personIdFor(page, name);
  const { chartId } = await seedLegacy(page, id, { ...fixtures[0], kind: 'natal' });
  const added = themes.filter(theme => addedPaletteIds.has(theme.id));
  let geometry: (string | null)[][] | undefined;
  for (const theme of added) {
    await page.evaluate(value => localStorage.setItem('kat.appearance.theme', value), theme.id);
    await page.reload();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: new RegExp(name) }).click();
    await page.getByRole('tab', { name: 'Charts' }).click();
    await page.locator('.chart-history > summary').click();
    const chart = page.locator(`.chart-history > details[data-kat-chart-id="${chartId}"]`);
    await chart.locator(':scope > summary').click();
    const wheel = chart.getByRole('img', { name: /Tropical natal wheel/ });
    await expect(wheel).toBeVisible();
    const points = await wheel.locator('line, circle, text').evaluateAll(nodes => nodes.map(node =>
      ['x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'x', 'y'].map(key => node.getAttribute(key))));
    if (geometry) expect(points, theme.id).toEqual(geometry);
    geometry = points;
    const paper = await wheel.locator('rect').first().evaluate(node => getComputedStyle(node).fill);
    const sky = await wheel.evaluate(node => getComputedStyle(node).getPropertyValue('--wheel-sky').trim());
    expect(sky, theme.id).toBe(theme.mode === 'dark' ? '#9de0cc' : '#245b4e');
    await wheel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(evidence, `${stage}-${theme.id}-chart-desktop.png`) });
    const download = page.waitForEvent('download');
    await chart.getByRole('button', { name: 'Download PNG wheel' }).click();
    const png = await readFile(await (await download).path());
    expect(png.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
    await writeFile(resolve(evidence, `${stage}-${theme.id}-chart.png`), png);
    const exported = await page.context().newPage();
    await exported.setContent(`<img alt="Exported wheel" src="data:image/png;base64,${png.toString('base64')}">`);
    const rgb = await exported.getByRole('img', { name: 'Exported wheel' }).evaluate(element => {
      const canvas = document.createElement('canvas'); canvas.width = 960; canvas.height = 1080;
      const context = canvas.getContext('2d')!;
      context.drawImage(element as HTMLImageElement, 0, 0);
      return [...context.getImageData(80, 80, 1, 1).data].slice(0, 3);
    });
    expect(rgb, `${theme.id} screen PNG paper`).toEqual(paper.match(/\d+/g)!.slice(0, 3).map(Number));
    await exported.close();
  }
  const print = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download print-ready SVG' }).click();
  const printMarkup = await readFile(await (await print).path(), 'utf8');
  expect(printMarkup).toContain('--wheel-paper: #ffffff');
  const exported = await page.context().newPage();
  await exported.setContent(printMarkup);
  expect(await exported.locator('svg rect').first().evaluate(node => getComputedStyle(node).fill))
    .toBe('rgb(255, 255, 255)');
  await exported.locator('svg').screenshot({ path: resolve(evidence, `${stage}-midnight-orchid-print.png`) });
  await exported.close();
});

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024, owner: 'reader-natal' },
  { name: 'mobile', width: 390, height: 844, owner: 'reader-natal-mobile' },
]) {
  for (const fixture of fixtures) {
    test(`${fixture.name} natal wheel at ${viewport.name} stays inspectable in browser and exported SVG`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
      await page.goto('/');
      await page.getByLabel('Username').fill(viewport.owner);
      await page.getByLabel('Password').fill('synthetic-browser-password');
      await page.getByRole('button', { name: 'Open workspace' }).click();
      if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('button', { name: 'Add person', exact: true }).click();
      const name = `Synthetic ${fixture.name} wheel ${viewport.name}`;
      const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
      await dialog.getByLabel('Name').fill(name);
      await dialog.getByRole('button', { name: 'Create person' }).click();
      const id = await personIdFor(page, name);
      const { chartId } = await seedLegacy(page, id, { ...fixture, kind: 'natal' });
      await page.reload();
      if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: new RegExp(name) }).click();
      await page.getByRole('tab', { name: 'Charts' }).click();
      await page.locator('.chart-history > summary').click();
      const chart = page.locator(`.chart-history > details[data-kat-chart-id="${chartId}"]`);
      await chart.locator(':scope > summary').click();
      const wheel = chart.getByRole('img', { name: /Tropical natal wheel/ });
      await expect(wheel).toBeVisible();
      await expect(wheel.locator('line.wheel-aspect')).toHaveCount(fixture.aspectLines);
      await expect(wheel.locator('line.wheel-angle')).toHaveCount(2); // ASC/MC
      await expect(wheel.locator('line.wheel-cusp')).toHaveCount(10);
      await expect(wheel.locator('line.wheel-angle').first()).toHaveAttribute('stroke-width', '2');
      await expect(wheel.locator('line.wheel-aspect').first()).toHaveAttribute('stroke-width', '.75');
      await expect(wheel.locator('line.wheel-aspect').first()).toHaveAttribute('opacity', '.45');
      await expect(chart.getByRole('table', { name: /Planet and lunar node positions/ })).toBeVisible();
      await wheel.scrollIntoViewIfNeeded();
      await page.screenshot({ path: resolve(evidence, `${stage}-${fixture.name}-${viewport.name}.png`) });
      if (fixture.name === 'ordinary')
        await chart.locator('.natal-wheel-frame').screenshot({ path: resolve(evidence, `${stage}-ordinary-${viewport.name}-export-actions.png`) });
      if (viewport.name === 'mobile') {
        const scroller = chart.locator('.natal-wheel-scroll');
        await scroller.evaluate(node => { node.scrollLeft = node.scrollWidth; });
        await page.screenshot({ path: resolve(evidence, `${stage}-${fixture.name}-mobile-right.png`) });
      }
      if (fixture.name === 'ordinary' && viewport.name === 'desktop') {
        const geometry = await wheel.locator('line, circle, text').evaluateAll(nodes => nodes.map(node =>
          ['x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'x', 'y'].map(key => node.getAttribute(key))));
        const lightPaper = await wheel.locator('rect').first().evaluate(node => getComputedStyle(node).fill);
        await page.getByRole('button', { name: 'Settings' }).click();
        await page.getByRole('region', { name: 'Appearance' }).getByRole('button', { name: /Blue Hour/ }).click();
        await page.getByRole('button', { name: 'Back to workspace' }).click();
        const darkPaper = await wheel.locator('rect').first().evaluate(node => getComputedStyle(node).fill);
        expect(darkPaper).not.toBe(lightPaper);
        expect(darkPaper).toBe('rgb(38, 51, 77)');
        expect(await wheel.locator('line, circle, text').evaluateAll(nodes => nodes.map(node =>
          ['x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'x', 'y'].map(key => node.getAttribute(key))))).toEqual(geometry);
        await page.screenshot({ path: resolve(evidence, 'theme-dark-natal-desktop.png') });
      }
      const download = page.waitForEvent('download');
      await chart.getByRole('button', { name: 'Download safe SVG wheel' }).click();
      const original = await download;
      const markup = await readFile(await original.path(), 'utf8');
      expect(markup).toContain('Natal · tropical');
      expect(markup).toContain('☉');
      expect(markup).toContain('☊');
      expect(markup).toMatch(/@font-face[^<]+data:font\/woff;base64,/);
      expect(markup).toContain('var(--wheel-paper, #fffef9)'); // Standalone light fallback, even without the app stylesheet.
      expect(markup).toContain('id="kat-chart-provenance"');
      expect(markup).not.toMatch(/<script|<foreignObject|onload=|href="https?:/i);
      await writeFile(resolve(evidence, `${stage}-${fixture.name}-${viewport.name}.svg`), markup);
      const exported = await page.context().newPage();
      await exported.setViewportSize({ width: 600, height: 600 });
      await exported.setContent(markup);
      const provenance = JSON.parse(await exported.locator('svg metadata').textContent() || '{}');
      expect(provenance.chart_id).toBe(chartId);
      expect(provenance.profile_revision).toBe(1);
      const visibleWheelText = await exported.locator('svg text').allTextContents();
      expect(visibleWheelText.join(' ')).not.toMatch(/Calculated from supplied inputs|natal-default v1|natal-tropical-v1|Swiss 2\.10/);
      await exported.locator('svg').screenshot({ path: resolve(evidence, `${stage}-${fixture.name}-${viewport.name}-export.png`) });
      if (fixture.name === 'ordinary' && viewport.name === 'desktop') {
        const printReady = page.waitForEvent('download');
        await chart.getByRole('button', { name: 'Download print-ready SVG' }).click();
        const printMarkup = await readFile(await (await printReady).path(), 'utf8');
        expect(printMarkup).toContain('viewBox="0 0 480 480"');
        expect(printMarkup).toContain('id="kat-chart-provenance"');
        expect(printMarkup).toContain('--wheel-paper: #ffffff');
        expect(printMarkup).not.toMatch(/<script|<foreignObject|onload=|href="https?:/i);
        await writeFile(resolve(evidence, `${stage}-ordinary-desktop-print.svg`), printMarkup);
        await exported.setContent(printMarkup);
        expect(JSON.parse(await exported.locator('svg metadata').textContent() || '{}').chart_id).toBe(chartId);
        expect((await exported.locator('svg text').allTextContents()).join(' ')).not.toMatch(/natal-default v1|natal-tropical-v1|Swiss 2\.10|Calculated from supplied inputs/);
        expect(await exported.locator('svg rect').first().evaluate(node => getComputedStyle(node).fill))
          .toBe('rgb(255, 255, 255)');
        await exported.locator('svg').screenshot({ path: resolve(evidence, `${stage}-ordinary-desktop-print.png`) });

        const pngReady = page.waitForEvent('download');
        await chart.getByRole('button', { name: 'Download PNG wheel' }).click();
        const png = await readFile(await (await pngReady).path());
        expect(png.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
        await writeFile(resolve(evidence, `${stage}-ordinary-desktop-screen.png`), png);
        await exported.setContent(`<img alt="Downloaded chart" src="data:image/png;base64,${png.toString('base64')}">`);
        const image = exported.getByRole('img', { name: 'Downloaded chart' });
        await expect(image).toHaveJSProperty('naturalWidth', 960);
        await expect(image).toHaveJSProperty('naturalHeight', 960);
        const background = await image.evaluate(element => {
          const canvas = document.createElement('canvas'); canvas.width = 960; canvas.height = 960;
          canvas.getContext('2d')!.drawImage(element as HTMLImageElement, 0, 0);
          return [...canvas.getContext('2d')!.getImageData(80, 80, 1, 1).data];
        });
        expect(background.slice(0, 3)).toEqual([38, 51, 77]); // screen PNG uses Blue Hour, not print paper.
        await expect(chart.getByRole('alert')).toHaveCount(0);
      }
      await exported.close();
    });
  }
}
