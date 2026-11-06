import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { openManualTransits, leaveManualTransits } from '../support/navigation-helpers';

test.beforeAll(() => mkdirSync(resolve(import.meta.dirname, '../../../.local/transit-view'), { recursive: true }));

async function open(page: Page, owner: string, mobile: boolean) {
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  await page.getByLabel('Message Kat').fill('A draft to keep, never send by changing the sky view.');
  if (mobile) await page.getByRole('button', { name: 'Open navigation' }).click();
  await openManualTransits(page);
  const panel = page.getByRole('region', { name: 'Sky at a date' });
  await expect(panel).toBeVisible();
  await panel.getByLabel('Date').fill('2024-03-20');
  await panel.getByLabel('Copenhagen time').fill('04:06');
  await expect(panel.getByLabel('Reporting timezone (IANA)')).toHaveCount(0);
  return panel;
}

for (const viewport of [
  { name: 'desktop', size: { width: 1440, height: 1024 }, owner: 'reader-transit-desktop' },
  { name: 'mobile', size: { width: 390, height: 844 }, owner: 'reader-transit-mobile' },
]) {
  test(`sky and active-natal transits stay bounded and read-only on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(85000);
    await page.setViewportSize(viewport.size);
    await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
    let writes = 0;
    page.on('request', request => {
      if (request.method() !== 'GET' && /\/api\/(conversations|people\/.*\/(births|charts|generate)|chatgpt)/.test(new URL(request.url()).pathname)) writes++;
    });
    const panel = await open(page, viewport.owner, viewport.name === 'mobile');
    const skyResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/transit-view');
    await panel.getByRole('button', { name: 'Show calculated view' }).click();
    expect((await (await skyResponse).json()).instant_utc).toBe('2024-03-20T03:06:00+00:00');
    await expect(panel.locator('.transit-result')).toContainText('2024-03-20 04:06 · Europe/Copenhagen');
    await expect(panel.locator('.transit-result')).not.toContainText('2024-03-20T03:06:00+00:00');
    const skySections = panel.locator('.transit-section');
    await expect(skySections).toHaveCount(2);
    await expect(skySections.first()).not.toHaveAttribute('open');
    await expect(skySections.last()).not.toHaveAttribute('open');
    await skySections.first().locator('summary').click();
    await expect(panel.getByRole('table', { name: /Transiting planets/ }).getByRole('row')).toHaveCount(11);
    await skySections.last().locator('summary').click();
    await expect(panel.getByRole('table', { name: /Same-sky aspects/ })).toBeVisible();
    await panel.locator('.transit-result').screenshot({ path: `../.local/transit-view/sky-${viewport.name}.png` });
    const originalSun = await panel.getByRole('table', { name: /Transiting planets/ }).getByRole('row', { name: /^Sun / }).innerText();
    await panel.getByLabel('Date').fill('2024-04-20');
    await expect(panel.locator('.transit-result')).toHaveCount(0);
    await panel.getByRole('button', { name: 'Show calculated view' }).click();
    await panel.locator('.transit-section').first().locator('summary').click();
    const laterSun = await panel.getByRole('table', { name: /Transiting planets/ }).getByRole('row', { name: /^Sun / }).innerText();
    expect(laterSun).not.toEqual(originalSun);
    await panel.getByLabel('Natal + transits').check();
    await expect(panel.locator('.transit-result')).toHaveCount(0);
    await panel.getByLabel('Person').selectOption('transit-person');
    const current = await (await page.request.get('/api/people/transit-person')).json();
    const chartId = current.active_chart_id as string;
    expect(chartId).toMatch(/^chart-[a-f0-9]+$/);
    await expect(panel.getByLabel('Saved natal version')).toHaveCount(0);
    const combinedResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/transit-view');
    await panel.getByRole('button', { name: 'Show calculated view' }).click();
    expect((await (await combinedResponse).json()).chart_id).toBe(chartId);
    await expect(panel.locator('.transit-result')).not.toContainText(chartId);
    const sections = panel.locator('.transit-section');
    await expect(sections).toHaveCount(4);
    for (let index = 0; index < 4; index++) await expect(sections.nth(index)).not.toHaveAttribute('open');
    await sections.nth(1).locator('summary').click();
    await expect(panel.getByRole('table', { name: /Selected natal positions/ })).toContainText('Ascendant');
    await expect(sections.nth(0)).not.toHaveAttribute('open');
    await sections.nth(3).locator('summary').click();
    await expect(panel.getByRole('table', { name: /Transit-to-natal aspects/ })).toBeVisible();
    await panel.locator('.transit-result').screenshot({ path: `../.local/transit-view/combined-${viewport.name}.png` });
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByRole('button', { name: /Appearance/ }).click();
    await page.getByRole('region', { name: 'Appearance' }).getByRole('button', { name: 'Dark', exact: true }).click();
    await page.getByRole('region', { name: 'Appearance' }).getByRole('button', { name: /Ink & Copper/ }).click();
    await page.getByRole('button', { name: 'Close settings panel' }).click();
    await page.getByRole('button', { name: 'Back to workspace' }).click();
    await expect(panel.locator('.transit-result')).not.toContainText(chartId);
    const wheelPaper = await panel.locator('.natal-wheel rect').first().evaluate(node => getComputedStyle(node).fill);
    expect(wheelPaper).toBe('rgb(48, 46, 50)'); // Ink & Copper, not a bright white chart.
    if (viewport.name === 'desktop') {
      const printReady = page.waitForEvent('download');
      await panel.getByRole('button', { name: 'Download print-ready SVG' }).click();
      const markup = await readFile(await (await printReady).path(), 'utf8');
      expect(markup).toContain(`"chart_id":"${chartId}"`);
      expect(markup).toContain('viewBox="0 0 480 480"');
      expect(markup).not.toMatch(/<text[^>]*>[^<]*chart-/);
      expect(markup).toContain('--wheel-paper: #ffffff');
      expect(markup).not.toMatch(/<script|<foreignObject|onload=|href="https?:/i);
    }
    await sections.nth(3).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/transit-view/combined-list-${viewport.name}.png` });
    await panel.getByLabel('Person').selectOption('legacy-transit-person');
    await expect(panel.locator('.transit-result')).toHaveCount(0);
    await panel.getByRole('button', { name: 'Show calculated view' }).click();
    await expect(panel.getByRole('alert')).toContainText('no active generated natal');
    await panel.getByRole('alert').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/transit-view/unsupported-${viewport.name}.png` });
    await panel.getByLabel('Sky only').check();
    await panel.getByLabel('Date').fill('2024-03-31');
    await panel.getByLabel('Copenhagen time').fill('02:30');
    await panel.getByRole('button', { name: 'Show calculated view' }).click();
    await expect(panel.getByRole('alert')).toContainText('did not occur');
    await expect(panel.getByLabel('Repeated Copenhagen hour')).toHaveCount(0);
    await expect(panel.locator('.transit-result')).toHaveCount(0);
    await page.screenshot({ path: `../.local/transit-view/error-${viewport.name}.png` });
    await leaveManualTransits(page);
    await expect(page.getByLabel('Message Kat')).toHaveValue('A draft to keep, never send by changing the sky view.');
    expect(writes).toBe(0);
  });
}

test('repeated Copenhagen hour requires an explicit occurrence and changes UTC', async ({ page }) => {
  const panel = await open(page, 'reader-transit-desktop', false);
  await panel.getByLabel('Date').fill('2024-10-27');
  await panel.getByLabel('Copenhagen time').fill('02:30');
  await panel.getByRole('button', { name: 'Show calculated view' }).click();
  await expect(panel.getByRole('alert')).toContainText('occurred twice');
  await panel.getByLabel('Repeated Copenhagen hour').selectOption('earlier');
  const earlier = page.waitForResponse(response => new URL(response.url()).pathname === '/api/transit-view');
  await panel.getByRole('button', { name: 'Show calculated view' }).click();
  expect((await (await earlier).json()).instant_utc).toBe('2024-10-27T00:30:00+00:00');
  await expect(panel.locator('.transit-result')).toContainText('earlier repeated hour');
  await panel.getByLabel('Repeated Copenhagen hour').selectOption('later');
  await expect(panel.locator('.transit-result')).toHaveCount(0);
  const later = page.waitForResponse(response => new URL(response.url()).pathname === '/api/transit-view');
  await panel.getByRole('button', { name: 'Show calculated view' }).click();
  expect((await (await later).json()).instant_utc).toBe('2024-10-27T01:30:00+00:00');
  await expect(panel.locator('.transit-result')).toContainText('later repeated hour');
});

test('changing person ignores a delayed prior calculation; keyboard submits and returns', async ({ page }) => {
  const panel = await open(page, 'reader-transit-mobile', false);
  await panel.getByLabel('Natal + transits').check();
  await panel.getByLabel('Person').selectOption('transit-person');
  let release!: () => void;
  let arrived!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const received = new Promise<void>(resolve => { arrived = resolve; });
  await page.route('**/api/transit-view?*', async route => {
    const response = await route.fetch();
    arrived(); await gate; await route.fulfill({ response });
  });
  await panel.getByRole('button', { name: 'Show calculated view' }).click();
  await arrived;
  await panel.getByLabel('Person').selectOption('other-transit-person');
  release();
  await expect(panel.locator('.transit-result')).toHaveCount(0);
  const current = await (await page.request.get('/api/people/other-transit-person')).json();
  await panel.getByRole('button', { name: 'Show calculated view' }).focus();
  const saved = page.waitForResponse(response => new URL(response.url()).pathname === '/api/transit-view');
  await page.keyboard.press('Enter');
  expect((await (await saved).json()).chart_id).toBe(current.active_chart_id);
  await expect(panel.locator('.transit-result')).not.toContainText(current.active_chart_id);
  await panel.getByRole('button', { name: 'Back to chart choices' }).focus();
  await page.keyboard.press('Enter');
  await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: 'Return to workspace' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Message Kat')).toHaveValue('A draft to keep, never send by changing the sky view.');
});

test('late earlier-date reply cannot display under changed date or mode', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  const panel = await open(page, 'reader-transit-desktop', false);
  let release!: () => void;
  let arrived!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const received = new Promise<void>(resolve => { arrived = resolve; });
  await page.route('**/api/transit-view?*', async route => {
    const response = await route.fetch();
    arrived(); await gate; await route.fulfill({ response });
  });
  await panel.getByRole('button', { name: 'Show calculated view' }).click();
  await arrived;
  await panel.getByLabel('Date').fill('2024-04-20');
  release();
  await expect(panel.locator('.transit-result')).toHaveCount(0);
  await panel.getByRole('button', { name: 'Show calculated view' }).click();
  await expect(panel.locator('.transit-result')).toContainText('2024-04-20');
  await panel.getByLabel('Natal + transits').check();
  await expect(panel.locator('.transit-result')).toHaveCount(0);
});
