import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '../..');
const clean = execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim() === '';
const source = clean ? execFileSync('git', ['rev-parse', '--short', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim() : 'work-in-progress';
const renders = resolve(root, '.local/ui-after', source);
test.beforeAll(() => mkdirSync(renders, { recursive: true }));

for (const viewport of [
  { name: 'desktop', size: { width: 1440, height: 1024 }, owner: 'reader-transit-desktop' },
  { name: 'mobile', size: { width: 390, height: 844 }, owner: 'reader-transit-mobile' },
  { name: 'short-mobile', size: { width: 390, height: 560 }, owner: 'reader-transit-mobile' },
]) for (const theme of ['reading-room', 'blue-hour']) {
  test(`contextual chart follows current selection on ${viewport.name} ${theme}`, async ({ page, context }) => {
    test.setTimeout(90000);
    await page.setViewportSize(viewport.size);
    await page.addInitScript(value => localStorage.setItem('kat.appearance.theme', value), theme);
    const origin = new URL(test.info().project.use.baseURL!).origin;
    await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    await page.goto('/');
    await page.getByLabel('Username').fill(viewport.owner);
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    const chart = page.getByRole('complementary', { name: 'Current natal context' });
    await expect(chart).toHaveCount(0);
    await page.screenshot({ path: resolve(renders, `${viewport.name}-${theme}-no-chart.png`) });
    await page.getByLabel('Message Kat').fill('Keep this synthetic draft unsent.');
    let sends = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && /\/api\/conversations\/[^/]+\/turns$/.test(new URL(request.url()).pathname)) sends++;
    });
    const mobile = viewport.size.width < 700;
    if (mobile) await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
    await page.getByRole('button', { name: 'New conversation about Synthetic transit reader' }).click();
    await expect(page.getByLabel('Message Kat')).toHaveValue(''); // Explicit new-chat action clears the old draft.
    await page.getByLabel('Message Kat').fill('This draft stays while I inspect the chart.');
    await expect(chart).toContainText('Synthetic transit reader’s natal chart');
    await expect(chart).toContainText('For your next message');
    const chartId = await page.locator('.person-chip').getAttribute('data-kat-chart-id');
    expect(chartId).toMatch(/^chart-[a-f0-9]+$/);
    await expect(chart.getByText('Chart details', { exact: true })).toHaveCount(0);
    const disclosure = chart.locator(':scope > details');
    if (viewport.size.width > 1000) {
      await expect(disclosure).toHaveAttribute('open');
      await expect(chart.getByRole('img', { name: /Tropical natal wheel/ })).toBeVisible();
      await expect(chart.getByRole('table', { name: /Selected placements/ })).toContainText('Sun');
    } else {
      await expect(disclosure).not.toHaveAttribute('open');
      await expect(chart.getByRole('img', { name: /Tropical natal wheel/ })).toBeHidden();
      await disclosure.locator(':scope > summary').focus();
      await page.keyboard.press('Enter');
      await expect(disclosure).toHaveAttribute('open');
      await expect(chart.getByRole('img', { name: /Tropical natal wheel/ })).toBeVisible();
    }
    await expect(chart.getByText(chartId!, { exact: false })).toHaveCount(0);
    const symbols = chart.locator('.chart-notation > summary');
    await symbols.focus();
    await page.keyboard.press('Enter');
    await expect(chart.getByRole('table', { name: /Planet and lunar node symbols/ })).toContainText('North Node');
    await page.screenshot({ path: resolve(renders, `${viewport.name}-${theme}-symbols.png`), fullPage: true });
    await page.keyboard.press('Enter');
    if (mobile) {
      await disclosure.locator(':scope > summary').focus();
      await page.keyboard.press('Enter');
      await expect(disclosure).not.toHaveAttribute('open');
    }
    await page.screenshot({ path: resolve(renders, `${viewport.name}-${theme}-one-chart.png`), fullPage: true });
    await chart.getByRole('button', { name: /Open Synthetic transit reader’s full chart/ }).click();
    await expect(page.getByRole('tab', { name: 'Charts' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('.profile-active-chart')).toContainText('Calculated natal chart');
    await expect(page.locator('.profile-active-chart').getByText(chartId!, { exact: false })).toHaveCount(0);
    await page.getByRole('button', { name: 'Return to workspace' }).click();
    await expect(page.getByLabel('Message Kat')).toHaveValue('This draft stays while I inspect the chart.');
    await page.getByRole('button', { name: '＋ Add person' }).click();
    const picker = page.getByRole('dialog', { name: 'Who’s this about?' });
    await picker.getByRole('checkbox', { name: /Other synthetic reader/ }).check();
    await picker.getByRole('button', { name: 'Use selection' }).click();
    await expect(chart).toContainText('Separate charts · no comparison');
    await expect(chart).toContainText('Other synthetic reader');
    await expect(chart.locator('.context-chart-info')).toHaveCount(0);
    await expect(chart.getByRole('img', { name: /Tropical natal wheel/ })).toHaveCount(0);
    await chart.scrollIntoViewIfNeeded();
    if (mobile) {
      await expect(chart.locator(':scope > details > summary')).toBeInViewport();
      const placement = await page.evaluate(() => ({
        cardBottom: document.querySelector('.context-chart')!.getBoundingClientRect().bottom,
        composerTop: document.querySelector('.composer-wrap')!.getBoundingClientRect().top,
      }));
      expect(placement.cardBottom).toBeLessThan(placement.composerTop);
    }
    await page.screenshot({ path: resolve(renders, `${viewport.name}-${theme}-two-people.png`), fullPage: true });
    await page.getByRole('button', { name: '＋ Add person' }).click();
    const unavailable = page.getByRole('dialog', { name: 'Who’s this about?' });
    await unavailable.getByRole('checkbox', { name: /Synthetic transit reader/ }).uncheck();
    await unavailable.getByRole('checkbox', { name: /Other synthetic reader/ }).uncheck();
    await unavailable.getByRole('checkbox', { name: /Legacy chart without generated natal/ }).check();
    await unavailable.getByRole('button', { name: 'Use selection' }).click();
    await expect(chart.locator(':scope > details > summary')).toContainText('No current generated natal');
    await expect(chart.getByRole('img', { name: /Tropical natal wheel/ })).toHaveCount(0);
    await page.screenshot({ path: resolve(renders, `${viewport.name}-${theme}-missing-natal.png`), fullPage: true });
    expect(sends).toBe(0);
    const bars = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, client: document.documentElement.clientWidth,
      nested: [...document.querySelectorAll('.messages,.conversation,.reader-content')].filter(node => getComputedStyle(node).overflowY === 'auto')
        .filter(node => node.scrollHeight > node.clientHeight + 1).length }));
    expect(bars.document).toBeLessThanOrEqual(bars.client + 1);
    expect(bars.nested).toBe(0);
  });
}
