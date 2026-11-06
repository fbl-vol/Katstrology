import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/simple-ux-hub-renders');
test.beforeAll(() => mkdirSync(renders, { recursive: true }));

test('all chart choices are grouped by intent and keyboard-reachable on narrow and wide screens', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-transit-desktop');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  for (const size of [{ width: 1440, height: 1024 }, { width: 390, height: 560 },
    { width: 2560, height: 1080 }]) {
    await page.setViewportSize(size);
    if (size.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: '＋ Create chart' }).click();
    const hub = page.getByRole('region', { name: 'Create chart' });
    const groups = ['Personal charts', 'Relationships', 'Timing'];
    for (const name of groups) await expect(hub.getByRole('region', { name })).toBeVisible();
    const choices = hub.locator('.chart-hub-choice');
    await expect(choices).toHaveCount(13);
    await page.screenshot({ path: resolve(renders, `choices-grouped-top-${size.width}x${size.height}.png`) });
    await choices.first().focus();
    for (let index = 0; index < 13; index++) {
      await expect(choices.nth(index)).toBeFocused();
      if (index < 12) await page.keyboard.press('Tab');
    }
    await hub.getByRole('region', { name: 'Timing' }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `choices-grouped-bottom-${size.width}x${size.height}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
    await hub.getByRole('button', { name: 'Return to workspace' }).click();
  }
});

test('delayed comparison cannot replace a changed pair or revive a closed hub', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-transit-desktop');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByLabel('Message Kat').fill('A draft held across the comparison.');
  await page.locator('.create-chart-nav').click();
  await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: /^Synastry/ }).click();
  const pair = page.getByRole('region', { name: 'Synastry chart' });
  await pair.getByLabel('Person A').selectOption({ label: 'Synthetic transit reader' });
  await pair.getByLabel('Person B').selectOption({ label: 'Other synthetic reader' });
  let arrived!: () => void;
  let release!: () => void;
  const waiting = new Promise<void>(resolve => { arrived = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/synastry?*', async route => {
    const response = await route.fetch();
    arrived(); await held;
    await route.fulfill({ response });
  });
  await pair.getByRole('button', { name: 'Compare charts' }).click();
  await waiting;
  await pair.getByLabel('Person B').selectOption({ label: 'Legacy chart without generated natal' });
  const stale = page.waitForResponse(response => new URL(response.url()).pathname === '/api/synastry');
  release();
  await stale;
  await expect(pair.locator('.synastry-result')).toHaveCount(0);
  await pair.getByRole('button', { name: 'Back to chart choices' }).click();
  await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: 'Return to workspace' }).click();
  await expect(page.getByLabel('Message Kat')).toHaveValue('A draft held across the comparison.');
});

test('unsupported comparison keeps actionable uncertainty without showing protocol codes', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-transit-desktop');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.locator('.create-chart-nav').click();
  await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: /^Synastry/ }).click();
  const pair = page.getByRole('region', { name: 'Synastry chart' });
  await pair.getByLabel('Person A').selectOption({ label: 'Synthetic transit reader' });
  await pair.getByLabel('Person B').selectOption({ label: 'Other synthetic reader' });
  await page.route('**/api/synastry?*', route => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ status: 'unsupported_incompatible_aspect_profiles' }) }));
  await pair.getByRole('button', { name: 'Compare charts' }).click();
  await expect(pair.getByRole('status')).toContainText('matching zodiac, aspects and orb settings');
  await expect(pair.getByRole('status')).not.toContainText('unsupported_incompatible_aspect_profiles');
});

test('child route creates one ordinary generated natal without child metadata or model traffic', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-people');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  let modelRequests = 0;
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/conversations\/[^/]+\/turns$/.test(new URL(request.url()).pathname)) modelRequests++;
  });
  await page.locator('.create-chart-nav').click();
  await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: /^Child’s natal/ }).click();
  await page.getByRole('button', { name: 'Create a person' }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic family member');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  await expect(page.locator('.profile-child-note')).toContainText('same numerical natal chart');
  const editor = page.getByRole('region', { name: 'Generate a chart' });
  await editor.getByLabel('Birth date').fill('2024-03-20');
  await editor.getByLabel('Birth time').fill('03:06');
  await editor.getByLabel('Birthplace search').fill('Copenhagen');
  await editor.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  const generated = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
  await editor.getByRole('button', { name: 'Generate chart' }).click();
  const saved = await generated;
  expect(saved.status()).toBe(201);
  const result = await saved.json();
  expect(result.active_chart_id).toBe(result.chart.id);
  expect(result.chart.result.natal.method_version).toBe('natal-tropical-v1');
  await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
  expect(modelRequests).toBe(0);
  await page.reload();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic family member/ }).click();
  await expect(page.locator('.profile-child-note')).toHaveCount(0);
  await page.getByRole('tab', { name: 'Charts' }).click();
  await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
  await expect(page.locator('.chart-history > summary')).toHaveText('Earlier charts and birth details');
  await page.locator('.chart-history > summary').click();
  await expect(page.locator('.chart-history > details')).toHaveCount(1);
});

for (const viewport of [
  { name: 'desktop-light', owner: 'reader-transit-desktop', size: { width: 1440, height: 1024 }, dark: false },
  { name: 'mobile-dark', owner: 'reader-transit-mobile', size: { width: 390, height: 844 }, dark: true },
]) {
  test(`four chart choices preserve the composer and compare two active charts on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(100000);
    await page.setViewportSize(viewport.size);
    if (viewport.dark) await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'blue-hour'));
    await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
    await page.goto('/');
    await page.getByLabel('Username').fill(viewport.owner);
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByLabel('Message Kat').fill('This private draft remains unsent.');
    let modelRequests = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && /\/api\/conversations\/[^/]+\/turns$/.test(new URL(request.url()).pathname)) modelRequests++;
    });
    const createChart = async () => {
      if (viewport.dark) await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.locator('.create-chart-nav').click();
    };
    await createChart();
    const hub = page.getByRole('region', { name: 'Create chart' });
    await expect(hub.getByRole('heading', { name: 'Create chart' })).toBeFocused();
    for (const choice of ['Natal chart', 'Transits', 'Synastry', 'Child’s natal'])
      await expect(hub.getByRole('button', { name: new RegExp(`^${choice}`) })).toBeVisible();
    await page.screenshot({ path: resolve(renders, `choices-${viewport.name}.png`) });
    await hub.getByRole('button', { name: /^Natal chart/ }).click();
    await hub.getByRole('button', { name: /Synthetic transit reader/ }).click();
    await expect(page.getByRole('tab', { name: 'Charts' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('region', { name: 'Generate a chart' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Generate a chart' }).getByLabel('Birth date')).toHaveValue('2001-06-21');
    await page.getByRole('button', { name: 'Return to workspace' }).click();
    await expect(page.getByLabel('Message Kat')).toHaveValue('This private draft remains unsent.');

    await createChart();
    await hub.getByRole('button', { name: /^Child’s natal/ }).click();
    await hub.getByRole('button', { name: /Other synthetic reader/ }).click();
    await expect(page.locator('.profile-child-note')).toContainText('same numerical natal chart');
    await expect(page.getByRole('region', { name: 'Generate a chart' }).getByLabel('Birth date')).toHaveValue('1998-02-04');
    await page.getByRole('button', { name: 'Return to workspace' }).click();
    await expect(page.getByLabel('Message Kat')).toHaveValue('This private draft remains unsent.');

    await createChart();
    await hub.getByRole('button', { name: /^Transits/ }).click();
    await expect(page.getByRole('region', { name: 'Sky at a date' })).toBeVisible();
    await page.getByLabel('Date', { exact: true }).fill('2024-03-20');
    await page.getByLabel('Copenhagen time').fill('03:06');
    await page.getByRole('button', { name: 'Show calculated view' }).click();
    await expect(page.locator('.transit-section').first()).not.toHaveAttribute('open');
    await page.locator('.transit-section').first().locator('summary').click();
    await expect(page.getByRole('table', { name: /Transiting planets/ })).toBeVisible();
    await expect(page.locator('.transit-result svg text').filter({ hasText: '☉' })).toHaveCount(1);
    const transitSymbols = page.locator('.transit-result .chart-notation');
    await expect(transitSymbols).not.toHaveAttribute('open');
    await transitSymbols.locator('summary').click();
    await expect(transitSymbols.getByRole('table', { name: 'Planet and lunar node symbols on this wheel' })).toContainText('Sun');
    await page.getByRole('button', { name: 'Back to chart choices' }).click();
    await expect(hub.getByRole('heading', { name: 'Create chart' })).toBeVisible();

    await hub.getByRole('button', { name: /^Synastry/ }).click();
    const synastry = page.getByRole('region', { name: 'Synastry chart' });
    await synastry.getByLabel('Person A').selectOption({ label: 'Synthetic transit reader' });
    await synastry.getByLabel('Person B').selectOption({ label: 'Other synthetic reader' });
    const compared = page.waitForResponse(response => response.request().method() === 'GET' &&
      new URL(response.url()).pathname === '/api/synastry');
    await synastry.getByRole('button', { name: 'Compare charts' }).click();
    const reply = await compared;
    expect(reply.status()).toBe(200);
    const data = await reply.json();
    expect(data.status).toBe('supported');
    expect(data.person_a_id).not.toBe(data.person_b_id);
    await expect(synastry.getByRole('img', { name: /Two-person tropical chart/ })).toBeVisible();
    expect(await synastry.locator('svg rect').first().evaluate(node => getComputedStyle(node).fill))
      .toBe(viewport.dark ? 'rgb(38, 51, 77)' : 'rgb(255, 254, 249)');
    await expect(synastry.locator('svg text').filter({ hasText: '☉' })).toHaveCount(2);
    const pairSymbols = synastry.locator('.chart-notation');
    await expect(pairSymbols).not.toHaveAttribute('open');
    await pairSymbols.locator('summary').click();
    await expect(pairSymbols.getByRole('table', { name: 'Planet and lunar node symbols on this wheel' })).toContainText('Mercury');
    await expect(synastry.getByRole('table', { name: /A to B inter-chart/ }).getByRole('row')).toHaveCount(data.aspects.length + 1);
    await expect(synastry.locator('.synastry-result')).not.toContainText('not independently verified');
    await expect(synastry.getByText('This is not a compatibility score.')).toBeVisible();
    await expect(synastry.getByRole('region', { name: 'Directional house overlays' })).toBeVisible();
    await expect(synastry.locator('.synastry-result')).not.toContainText(data.chart_a_id);
    await expect(synastry.locator('.synastry-result')).not.toContainText(data.chart_b_id);
    if (!viewport.dark) {
      const printReady = page.waitForEvent('download');
      await synastry.getByRole('button', { name: 'Download print-ready SVG' }).click();
      const markup = await readFile(await (await printReady).path(), 'utf8');
      expect(markup).toContain(`"chart_a_id":"${data.chart_a_id}"`);
      expect(markup).toContain(`"chart_b_id":"${data.chart_b_id}"`);
      expect(markup).not.toMatch(/<text[^>]*>[^<]*chart-/);
      expect(markup).toContain('--wheel-paper: #ffffff');
      expect(markup).not.toMatch(/<script|<foreignObject|onload=|href="https?:/i);
    }
    await page.screenshot({ path: resolve(renders, `synastry-${viewport.name}.png`) });
    await synastry.getByRole('img', { name: /Two-person tropical chart/ }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `synastry-wheel-${viewport.name}.png`) });
    await synastry.getByRole('table', { name: /A to B inter-chart/ }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `synastry-aspects-${viewport.name}.png`) });
    if (viewport.dark) {
      await page.setViewportSize({ width: 390, height: 560 });
      await page.screenshot({ path: resolve(renders, 'synastry-short-mobile.png') });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
      await page.setViewportSize(viewport.size);
    }
    await synastry.getByLabel('Person B').selectOption({ label: 'Legacy chart without generated natal' });
    await synastry.getByRole('button', { name: 'Compare charts' }).click();
    await expect(synastry.getByRole('status')).toContainText('older or uploaded chart is never substituted');
    await expect(synastry.getByRole('button', { name: /Create chart for Legacy/ })).toBeVisible();
    await synastry.getByLabel('Person B').selectOption({ label: 'Synthetic transit reader' });
    await expect(synastry.getByRole('button', { name: 'Compare charts' })).toBeDisabled();
    await expect(synastry.getByRole('alert')).toContainText('two different people');
    expect(modelRequests).toBe(0);
    await synastry.getByRole('button', { name: 'Back to chart choices' }).click();
    await hub.getByRole('button', { name: 'Return to workspace' }).click();
    await expect(page.getByLabel('Message Kat')).toHaveValue('This private draft remains unsent.');
  });
}
