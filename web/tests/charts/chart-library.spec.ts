import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { openLibrary, saveLibraryExamples } from '../support/chart-library-fixture';
const expectedTitles: Record<string, string> = {
  solar_return: 'Solar return', lunar_return: 'Lunar returns', planetary_return: 'Planetary returns',
  mc_transit: 'Midheaven transit contacts', secondary_progression: 'Secondary progressions',
  progressed_mc_contacts: 'Progressed Midheaven contacts', true_solar_arc: 'Solar-arc directions',
  progressed_lunar_phases: 'Progressed lunar phases', actual_lunations_eclipses: 'Lunations and eclipses',
  synastry_overlay: 'Synastry', midpoint_composite: 'Midpoint composite', uncorrected_davison: 'Uncorrected Davison',
};

const renders = resolve(import.meta.dirname, '../../../.local/chart-library-release2-fixes/renders');

test('chart library opens every persisted technique with its original reader and no writes', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 1024 });
  await openLibrary(page);
  const examples = await saveLibraryExamples(page);
  await page.reload();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  const library = page.locator('.chart-library');
  await expect(library.locator('.library-card')).toHaveCount(13);
  const posts: string[] = [];
  page.on('request', request => { if (request.url().includes('/api/') && request.method() !== 'GET') posts.push(request.url()); });
  await library.getByRole('button', { name: 'Gallery', exact: true }).click();
  mkdirSync(renders, { recursive: true });
  for (const size of [{ width: 1440, height: 1024 }, { width: 1920, height: 1080 },
    { width: 2560, height: 1080 }, { width: 3440, height: 1440 }, { width: 390, height: 844 }, { width: 390, height: 560 }]) {
    await page.setViewportSize(size);
    for (const layout of ['List', 'Gallery']) {
      await library.getByRole('button', { name: layout, exact: true }).click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await page.screenshot({ path: resolve(renders, `all-types-${layout.toLowerCase()}-${size.width}-${size.height}.png`), fullPage: true });
    }
  }
  for (const example of examples) {
    const title = expectedTitles[example.technique];
    await expect(library.locator(`[data-technique="${example.technique}"]`)).toHaveAttribute('data-result-id', example.id);
    const original = page.waitForResponse(response => response.url().endsWith(`/api/advanced-results/${example.id}`));
    await library.getByRole('button', { name: `Open ${title}`, exact: true }).click();
    expect((await original).status()).toBe(200);
    if (['synastry_overlay', 'midpoint_composite', 'uncorrected_davison'].includes(example.technique)) {
      await expect(library.getByRole('heading', { name: /Other synthetic reader/, level: 2 })).toBeVisible();
      const download = page.waitForEvent('download');
      await library.getByRole('button', { name: 'Download safe SVG wheel', exact: true }).click();
      expect((await download).suggestedFilename()).toMatch(/\.svg$/);
      await expect(library.getByRole('button', { name: /Calculate|Compare charts|Save this comparison/ })).toHaveCount(0);
    } else {
      await expect(library.getByRole('region', { name: 'Opened saved calculation' })).toBeVisible();
      await expect(library.getByRole('button', { name: 'Discuss this saved result', exact: true })).toBeVisible();
    }
    await library.getByRole('button', { name: 'Back to chart library' }).click();
  }
  await page.evaluate(() => localStorage.setItem('kat.appearance.theme', 'blue-hour'));
  await page.reload();
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  await expect(library.locator('.library-card')).toHaveCount(13);
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'blue-hour');
  await page.screenshot({ path: resolve(renders, 'all-types-gallery-blue-hour-390-560.png'), fullPage: true });
  expect(posts).toEqual([]);
});

test('chart library pages all saved versions and labels body variants beyond the latest listing page', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 1024 });
  await openLibrary(page);
  const session = await (await page.request.get('/api/session')).json();
  const headers = { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin };
  const created = await page.request.post('/api/people', { headers, data: { name: 'Synthetic paged library' } });
  expect(created.status()).toBe(201);
  const personId: string = (await created.json()).id;
  const natal = await page.request.post(`/api/people/${personId}/generate`, { headers, data: {
    request_id: `library-source-${crypto.randomUUID()}`, birth_date: '2001-06-21', birth_time: '04:00',
    time_unknown: false, birthplace: 'Copenhagen, Capital Region, Denmark', place_id: '2618425',
    provisional: true, zone_override: null, latitude_override: null, longitude_override: null, fold: null, settings: null,
  } });
  expect(natal.status()).toBe(201);
  const ids: string[] = [];
  for (let index = 0; index < 24; index++) {
    const id = `library-history-${crypto.randomUUID()}`;
    ids.push(id);
    const reply = await page.request.post('/api/advanced-results', { headers, data: {
      id, person_id: personId, technique: 'true_solar_arc', parameters: { effective_utc: '2024-03-25T00:00:00+00:00' },
    } });
    expect(reply.status()).toBe(201);
  }
  for (const body of ['venus', 'saturn']) {
    const reply = await page.request.post('/api/advanced-results', { headers, data: {
      id: `library-body-${crypto.randomUUID()}`, person_id: personId, technique: 'planetary_return', parameters: {
        body, start_utc: '2024-03-01T00:00:00+00:00', end_utc: '2024-04-01T00:00:00+00:00', latitude: 51.5, longitude: -1 / 6,
      },
    } });
    expect(reply.status()).toBe(201);
  }
  await page.reload();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic paged library' }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  const library = page.locator('.chart-library');
  await expect(library.locator('[data-technique="planetary_return"]')).toContainText('Saturn');
  await expect(library.locator('[data-technique="planetary_return"]')).toContainText('2 variants');
  mkdirSync(renders, { recursive: true });
  for (const size of [{ width: 1440, height: 1024 }, { width: 390, height: 560 }]) {
    await page.setViewportSize(size);
    await page.screenshot({ path: resolve(renders, `body-variants-${size.width}-${size.height}.png`), fullPage: true });
  }
  await library.getByRole('button', { name: /Solar-arc directions history/ }).click();
  const historyRows = library.locator('.library-history li');
  await expect(historyRows).toHaveCount(20);
  await expect(historyRows.first()).toHaveAttribute('data-result-id', ids.at(-1)!);
  await expect(historyRows.first()).toContainText(`Version ${ids.at(-1)}`);
  await page.screenshot({ path: resolve(renders, 'history-first-page-390-560.png') });
  await page.route(`**/api/people/${personId}/chart-library/true_solar_arc?before=*`, route =>
    route.fulfill({ status: 503, json: { error: 'synthetic_page_failure' } }), { times: 1 });
  await library.getByRole('button', { name: 'Load older results' }).click();
  await expect(library.getByRole('alert')).toContainText('Already listed versions are still available');
  await expect(historyRows).toHaveCount(20);
  await library.getByRole('button', { name: 'Retry history' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'history-page-failure-390-560.png') });
  await library.getByRole('button', { name: 'Retry history' }).click();
  await expect(historyRows).not.toHaveCount(20);
  while (await library.getByRole('button', { name: 'Load older results' }).count()) {
    await library.getByRole('button', { name: 'Load older results' }).click();
    await expect(library.getByText('Loading saved history…', { exact: true })).toHaveCount(0);
  }
  const all = await historyRows.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-result-id')));
  expect(new Set(all).size).toBe(all.length);
  expect(ids.every(id => all.includes(id))).toBe(true);
  for (const size of [{ width: 1440, height: 1024 }, { width: 390, height: 560 }]) {
    await page.setViewportSize(size);
    await historyRows.last().scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: resolve(renders, `history-final-page-${size.width}-${size.height}.png`) });
  }
});

test.describe('chart library touch and local preference', () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 560 } });
  test('chart library remembers Gallery and shows a truthful empty first-chart path', async ({ page }) => {
    await openLibrary(page);
    await page.getByRole('button', { name: 'Gallery', exact: true }).tap();
    await page.reload();
    await page.getByRole('button', { name: 'Open navigation' }).tap();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).tap();
    await page.getByRole('tab', { name: 'Charts', exact: true }).tap();
    await expect(page.getByRole('button', { name: 'Gallery', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: 'Open Natal chart', exact: true }).tap();
    await expect(page.locator('.profile-active-chart .natal-wheel')).toBeVisible();
    await page.getByRole('button', { name: 'Back to chart library' }).tap();
    await page.getByRole('button', { name: 'Open navigation' }).tap();
    await page.getByRole('button', { name: 'Add person', exact: true }).tap();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Name').fill('Synthetic empty library');
    await dialog.getByRole('button', { name: 'Create person' }).tap();
    await page.getByRole('button', { name: 'Close editor', exact: true }).tap();
    await expect(page.getByRole('heading', { name: 'No saved charts yet' })).toBeVisible();
    await expect(page.locator('.library-card')).toHaveCount(0);
    mkdirSync(renders, { recursive: true });
    await page.screenshot({ path: resolve(renders, 'empty-390-560.png'), fullPage: true });
    await page.getByRole('button', { name: 'Create first chart', exact: true }).tap();
    await expect(page.getByRole('region', { name: 'Generate a chart' })).toBeVisible();
  });
});

test('chart library recovers from loading and failed reads without inventing empty results', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 560 });
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let requests = 0;
  await page.route('**/api/people/transit-person/chart-library', async route => {
    requests++;
    if (requests === 1) { await gate; await route.fulfill({ status: 503, json: { error: 'synthetic_failure' } }); }
    else await route.continue();
  });
  await openLibrary(page, false);
  await expect(page.getByRole('status').filter({ hasText: 'Loading saved chart library' })).toBeVisible();
  mkdirSync(renders, { recursive: true });
  await page.screenshot({ path: resolve(renders, 'loading-390-560.png'), fullPage: true });
  await page.getByRole('button', { name: 'Gallery', exact: true }).click();
  expect(requests).toBe(1);
  release();
  await expect(page.getByRole('alert')).toContainText('The saved chart library could not be loaded');
  await expect(page.getByText('No saved charts yet', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: resolve(renders, 'failure-390-560.png'), fullPage: true });
  await page.getByRole('button', { name: 'Retry chart library' }).click();
  await expect(page.locator('.library-card[data-technique="natal"]')).toBeVisible();
  expect(requests).toBe(2);
  await expect(page.locator('.library-collection')).toHaveAttribute('data-view', 'gallery');
  await page.route('**/api/charts/*', async route => {
    if (/\/exploration$/.test(new URL(route.request().url()).pathname)) await route.continue();
    else await route.fulfill({ status: 503, json: { error: 'synthetic_read_failure' } });
  });
  await page.getByRole('button', { name: 'Open Natal chart', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('This saved result could not be loaded');
  await page.unroute('**/api/charts/*');
  await page.getByRole('button', { name: 'Retry saved result' }).click();
  await expect(page.locator('.profile-active-chart .natal-wheel')).toBeVisible();
});

test('chart library keeps saved identities across List and Gallery without requests or calculations', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('navigation', { name: 'People' })).toBeVisible();
  const session = await (await page.request.get('/api/session')).json();
  const id = `library-arc-${crypto.randomUUID()}`;
  const response = await page.request.post('/api/advanced-results', {
    headers: { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin },
    data: { id, person_id: 'transit-person', technique: 'true_solar_arc',
      parameters: { effective_utc: '2024-03-25T00:00:00+00:00' } },
  });
  expect(response.status()).toBe(201);
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  const library = page.locator('.chart-library');
  const cards = library.locator('.library-card');
  await expect(cards.locator('button', { hasText: 'Open chart' }).first()).toBeVisible();
  await expect(library.getByRole('button', { name: 'List', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const identities = await cards.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-result-id')));
  expect(identities).toContain(id);
  const calls: string[] = [];
  page.on('request', request => { if (request.url().includes('/api/')) calls.push(request.method() + ' ' + request.url()); });
  await library.getByRole('button', { name: 'Gallery', exact: true }).focus();
  await page.keyboard.press('Space');
  await expect(library.locator('.library-collection')).toHaveAttribute('data-view', 'gallery');
  expect(await cards.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-result-id')))).toEqual(identities);
  await library.getByRole('button', { name: 'List', exact: true }).click();
  expect(calls).toEqual([]);
  mkdirSync(renders, { recursive: true });
  for (const size of [{ width: 1440, height: 1024 }, { width: 1920, height: 1080 },
    { width: 2560, height: 1080 }, { width: 3440, height: 1440 }, { width: 390, height: 844 }, { width: 390, height: 560 }]) {
    await page.setViewportSize(size);
    for (const layout of ['List', 'Gallery']) {
      await library.getByRole('button', { name: layout, exact: true }).click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await page.screenshot({ path: resolve(renders, `${layout.toLowerCase()}-${size.width}-${size.height}.png`), fullPage: true });
    }
  }
  await library.getByRole('button', { name: 'Open Solar-arc directions', exact: true }).click();
  await expect(library.locator('.library-reader')).toHaveAttribute('data-result-id', id);
  await expect(library.getByRole('button', { name: 'Discuss this saved result', exact: true })).toBeVisible();
  await library.getByRole('button', { name: 'Back to chart library' }).click();
  await expect(library.getByRole('button', { name: 'Open Solar-arc directions', exact: true })).toBeFocused();
  await expect(library.getByRole('button', { name: 'Gallery', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await library.getByRole('button', { name: /Solar-arc directions history/ }).click();
  await expect(library.locator('.library-history [data-result-id]').first()).toHaveAttribute('data-result-id', id);
  expect(calls.filter(call => call.startsWith('POST'))).toEqual([]);
});
