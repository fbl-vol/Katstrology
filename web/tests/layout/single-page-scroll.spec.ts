import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { openManualTransits, leaveManualTransits } from '../support/navigation-helpers';

const renders = resolve(import.meta.dirname, '../../../.local/single-page-scroll');

type ScrollRange = { selector: string; range: number; scrollTop: number };

async function verticalRanges(page: Page, selectors: string[]): Promise<ScrollRange[]> {
  return page.evaluate(names => names.flatMap(selector =>
    [...document.querySelectorAll<HTMLElement>(selector)].map(element => {
      const before = element.scrollTop;
      element.scrollTop = before + 3;
      const scrollTop = element.scrollTop - before;
      element.scrollTop = before;
      return { selector, range: element.scrollHeight - element.clientHeight, scrollTop };
    })), selectors);
}

async function wheelMovesDocument(page: Page, selector: string) {
  const target = page.locator(selector).first();
  await page.evaluate(() => window.scrollTo(0, 0));
  await target.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => window.scrollY);
  const rect = await target.boundingBox();
  expect(rect).not.toBeNull();
  await page.mouse.move(rect!.x + Math.min(25, rect!.width / 2), rect!.y + Math.min(25, rect!.height / 2));
  await page.mouse.wheel(0, 260);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(before);
}

for (const size of [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'wide', width: 1920, height: 1080 },
  { name: 'ultrawide', width: 2560, height: 1080 },
  { name: 'wide-tall', width: 3440, height: 1440 },
  { name: 'short-desktop', width: 1440, height: 650 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short-mobile', width: 390, height: 560 },
]) {
  test(`synastry has one document-owned vertical scroll on ${size.name}`, async ({ page, context }) => {
    test.setTimeout(60000);
    mkdirSync(renders, { recursive: true });
    await page.setViewportSize({ width: size.width, height: size.height });
    await context.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ?
      route.continue() : route.abort());
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-transit-desktop');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByLabel('Message Kat').fill('Unsent draft stays while inspecting two charts.');
    if (size.width < 700) {
      await page.getByRole('button', { name: 'Open navigation' }).click();
      await expect(page.locator('.sidebar.open')).toBeVisible();
    }
    await page.locator('.create-chart-nav').click();
    const hubRanges = await verticalRanges(page, ['.main', '.settings-visible', '.chart-hub']);
    expect(hubRanges.filter(item => item.scrollTop !== 0), JSON.stringify(hubRanges)).toEqual([]);
    await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: /^Synastry/ }).click();
    const pair = page.getByRole('region', { name: 'Synastry chart' });
    await pair.getByLabel('Person A').selectOption({ label: 'Synthetic transit reader' });
    await pair.getByLabel('Person B').selectOption({ label: 'Other synthetic reader' });
    await pair.getByRole('button', { name: 'Compare charts' }).click();
    await expect(pair.getByRole('table', { name: /A to B inter-chart/ })).toBeVisible();
    await pair.locator('.chart-notation > summary').click();
    await page.evaluate(() => window.scrollTo(0, 0));

    const ranges = await verticalRanges(page, ['.main', '.reader-content', '.synastry-page', '.natal-wheel-scroll', '.transit-tables']);
    expect(ranges.filter(item => item.scrollTop !== 0), JSON.stringify(ranges)).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeGreaterThan(size.height);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
    await wheelMovesDocument(page, '.synastry-result .natal-wheel-scroll');
    await wheelMovesDocument(page, '.synastry-result .transit-tables');
    await pair.getByRole('heading', { name: 'Synastry' }).focus();
    await page.keyboard.press('PageDown');
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await pair.getByRole('button', { name: 'Start conversation about these people' }).scrollIntoViewIfNeeded();
    await expect(pair.getByRole('button', { name: 'Start conversation about these people' })).toBeVisible();
    await page.screenshot({ path: resolve(renders, `synastry-${size.name}.png`) });
    await pair.getByRole('button', { name: 'Back to chart choices' }).click();
    await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: 'Return to workspace' }).click();
    await expect(page.getByLabel('Message Kat')).toHaveValue('Unsent draft stays while inspecting two charts.');
  });
}

for (const size of [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short-mobile', width: 390, height: 560 },
]) {
  test(`expanded transit wrappers move the page without losing horizontal access on ${size.name}`, async ({ page, context }) => {
    test.setTimeout(60000);
    mkdirSync(renders, { recursive: true });
    await page.setViewportSize({ width: size.width, height: size.height });
    await context.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ?
      route.continue() : route.abort());
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-transit-desktop');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByLabel('Message Kat').fill('Leave this draft alone.');
    if (size.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
    await openManualTransits(page);
    const panel = page.getByRole('region', { name: 'Sky at a date' });
    await panel.getByLabel('Date').fill('2024-03-20');
    await panel.getByLabel('Copenhagen time').fill('04:06');
    await panel.getByLabel('Natal + transits').check();
    await panel.getByLabel('Person').selectOption('transit-person');
    await panel.getByRole('button', { name: 'Show calculated view' }).click();
    await expect(panel.locator('.transit-section')).toHaveCount(4);
    for (const section of await panel.locator('.transit-section').all()) await section.locator('summary').click();
    await expect(panel.getByRole('table', { name: /Transit-to-natal aspects/ })).toBeVisible();
    const selectors = ['.main', '.settings-visible', '.transit-page', '.natal-wheel-scroll', '.transit-tables'];
    const ranges = await verticalRanges(page, selectors);
    expect(ranges.filter(item => item.scrollTop !== 0), JSON.stringify(ranges)).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
    await wheelMovesDocument(page, '.transit-result .natal-wheel-scroll');
    await wheelMovesDocument(page, '.transit-result .transit-tables');
    if (size.width < 700) {
      const wrappers = panel.locator('.natal-wheel-scroll, .transit-tables');
      for (const wrapper of await wrappers.all()) {
        const horizontal = await wrapper.evaluate(element => {
          element.scrollLeft = element.scrollWidth;
          const last = element.querySelector('table tr > :last-child, svg')!;
          return { remaining: element.scrollWidth - element.clientWidth, left: element.scrollLeft,
            lastRight: last.getBoundingClientRect().right, frameRight: element.getBoundingClientRect().right };
        });
        expect(horizontal.remaining).toBeGreaterThan(0);
        expect(horizontal.left).toBeGreaterThan(0);
        expect(horizontal.lastRight).toBeLessThanOrEqual(horizontal.frameRight + 1);
      }
      await expect(panel.locator('.transit-section').last().locator(':scope > .transit-scroll-hint')).toBeVisible();
      for (const wrapper of await wrappers.all()) await wrapper.evaluate(element => { element.scrollLeft = 0; });
    }
    await panel.locator('.transit-section').last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `transit-${size.name}.png`) });
    await leaveManualTransits(page);
    await expect(page.getByLabel('Message Kat')).toHaveValue('Leave this draft alone.');
  });
}

for (const size of [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'short-mobile', width: 390, height: 560 },
]) {
  test(`person history, notebook and settings keep document scroll on ${size.name}`, async ({ page, context }) => {
    test.setTimeout(60000);
    mkdirSync(renders, { recursive: true });
    await page.setViewportSize({ width: size.width, height: size.height });
    await context.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ?
      route.continue() : route.abort());
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-transit-desktop');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    if (size.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
    await page.getByRole('tab', { name: 'Charts' }).click();
    await page.getByRole('button', { name: 'Open Natal chart', exact: true }).click();
    await page.locator('.chart-history > summary').click();
    await page.locator('.chart-history > details > summary').first().click();
    const profileRanges = await verticalRanges(page, ['.main', '.reader-content', '.person-page', '.natal-wheel-scroll', '.natal-tables']);
    expect(profileRanges.filter(item => item.scrollTop !== 0), JSON.stringify(profileRanges)).toEqual([]);
    await wheelMovesDocument(page, '.profile-active-chart .natal-wheel-scroll');
    await page.screenshot({ path: resolve(renders, `person-history-${size.name}.png`) });

    await page.getByRole('tab', { name: 'Saved' }).click();
    await expect(page.locator('.insight-notebook')).toBeVisible();
    const notebookRanges = await verticalRanges(page, ['.main', '.reader-content', '.person-page']);
    expect(notebookRanges.filter(item => item.scrollTop !== 0), JSON.stringify(notebookRanges)).toEqual([]);
    if (size.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await expect(page.getByRole('button', { name: /Appearance/ })).toBeVisible();
    const settingsRanges = await verticalRanges(page, ['.main', '.settings-page']);
    expect(settingsRanges.filter(item => item.scrollTop !== 0), JSON.stringify(settingsRanges)).toEqual([]);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.mouse.move(size.width / 2, size.height / 2);
    await page.mouse.wheel(0, 280);
    if (await page.evaluate(() => document.documentElement.scrollHeight > innerHeight))
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    else expect(await page.evaluate(() => window.scrollY)).toBe(0);
    await page.screenshot({ path: resolve(renders, `settings-${size.name}.png`) });
    await page.getByRole('button', { name: 'Back to workspace' }).click();
    await expect(page.getByRole('tab', { name: 'Saved' })).toHaveAttribute('aria-selected', 'true');
  });
}
