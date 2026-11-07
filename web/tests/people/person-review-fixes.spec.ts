import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { archivedTurn } from '../support/archive-assertions';

const renders = resolve(import.meta.dirname, '../../../.local/person-page-redesign/review-fixes');
test.beforeAll(() => mkdirSync(renders, { recursive: true }));
const viewports = [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short-mobile', width: 390, height: 640 },
] as const;

async function openPerson(page: Page, owner: string, mobile: boolean) {
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  if (mobile) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic transit reader' })).toBeVisible();
}

async function person(page: Page) {
  const response = await page.request.get('/api/people/transit-person');
  expect(response.ok()).toBe(true);
  return response.json();
}

async function post(page: Page, path: string, data: unknown) {
  const session = await (await page.request.get('/api/session')).json();
  const response = await page.request.post(path, {
    headers: { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin }, data,
  });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function reopenPerson(page: Page, mobile: boolean) {
  await page.reload();
  if (mobile) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
}

for (const viewport of viewports) {
  test(`saved exact chart is distinct from newer exact and unknown drafts on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize(viewport);
    const mobile = viewport.width < 700;
    await openPerson(page, `reader-layout-${viewport.name}`, mobile);
    const original = await person(page);
    const chartId = original.active_chart_id;
    expect(original.active_chart_draft_revision).toBe(original.drafts[0].revision);
    expect(original.charts.find((chart: { id: string }) => chart.id === chartId).result.natal.status).toBe('complete');

    for (const [label, time, unknown] of [['later-exact', '04:15', false], ['later-unknown', '', true]] as const) {
      await post(page, '/api/people/transit-person/drafts', {
        birth_date: '2001-06-21', birth_time: time, time_unknown: unknown, birthplace: 'Synthetic London',
      });
      await reopenPerson(page, mobile);
      const current = await person(page);
      expect(current.active_chart_id).toBe(chartId);
      expect(current.active_chart_draft_revision).toBe(original.active_chart_draft_revision);
      expect(current.charts.find((chart: { id: string }) => chart.id === chartId).source_status).toBe('current');
      await expect(page.locator('.profile-summary')).toContainText(unknown ? 'Birth time unknown' : '04:15');
      await expect(page.locator('.profile-draft-notice')).toContainText('Latest details are not in the current chart.');
      await expect(page.locator('.profile-draft-notice')).toContainText('saved birth time of 04:00');
      await expect(page.getByRole('button', { name: 'Birth chart' })).toContainText('Your current natal, placements and aspects');
      await page.screenshot({ path: resolve(renders, `${viewport.name}-${label}-overview.png`) });
      await page.getByRole('tab', { name: 'Charts' }).click();
      await page.getByRole('button', { name: 'Open Natal chart', exact: true }).click();
      await expect(page.locator('.profile-chart-heading')).toContainText('saved birth time 04:00');
      await expect(page.locator('.profile-active-chart').getByRole('group', { name: /Tropical natal wheel/ })).toBeVisible();
      await page.screenshot({ path: resolve(renders, `${viewport.name}-${label}-charts.png`) });
    }
    if (viewport.name === 'desktop') {
      await page.getByRole('button', { name: 'Start conversation' }).click();
      await expect(page.locator('.person-chip')).toContainText('current natal');
      await page.getByLabel('Message Kat').fill('Which saved chart is selected?');
      const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
        /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
      await page.getByRole('button', { name: 'Send message' }).click();
      expect((await ack).status()).toBe(202);
      await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'complete', { timeout: 15000 });
      expect((await archivedTurn(page, page.locator('.turn-card').last())).selected_people[0].chart_id).toBe(chartId);
    }
  });
}

test('unknown-time saved chart remains limited when latest draft supplies an exact time', async ({ page }) => {
  await page.setViewportSize(viewports[2]);
  await openPerson(page, 'reader-review-fixes', true);
  const generated = await post(page, '/api/people/transit-person/generate', {
    request_id: `inverse-${crypto.randomUUID()}`, birth_date: '2001-06-21', birth_time: '', time_unknown: true,
    birthplace: 'Synthetic Auckland', place_id: null, provisional: true, zone_override: 'Pacific/Auckland',
    latitude_override: -36.8485, longitude_override: 174.7633, fold: null, settings: null,
  });
  expect(generated.chart.result.natal.status).toBe('unsupported_uncertain_birth_time');
  await post(page, '/api/people/transit-person/drafts', {
    birth_date: '2001-06-21', birth_time: '04:15', time_unknown: false, birthplace: 'Synthetic Auckland',
  });
  await reopenPerson(page, true);
  const current = await person(page);
  expect(current.active_chart_id).toBe(generated.chart.id);
  expect(current.active_chart_draft_revision).toBe(generated.draft_revision);
  await expect(page.locator('.profile-summary')).toContainText('04:15');
  await expect(page.locator('.profile-draft-notice')).toContainText('unknown birth time on 2001-06-21');
  await expect(page.getByRole('button', { name: 'Birth chart' })).toContainText('Limited chart · birth time unknown');
  await page.screenshot({ path: resolve(renders, 'short-mobile-inverse-overview.png') });
  await page.getByRole('tab', { name: 'Charts' }).click();
  await page.getByRole('button', { name: 'Open Natal chart', exact: true }).click();
  await expect(page.locator('.profile-chart-heading')).toContainText('birth time unknown');
  await expect(page.locator('.profile-chart-heading')).toContainText('2001-06-20 – 2001-06-21 · UTC interval');
  await expect(page.locator('.profile-active-chart').getByRole('img', { name: /Tropical natal wheel/ })).toHaveCount(0);
  await page.screenshot({ path: resolve(renders, 'short-mobile-inverse-charts.png') });
});

test('a still-mounted chart uses refreshed latest draft while retaining its generated identity', async ({ page }) => {
  await page.setViewportSize(viewports[0]);
  await openPerson(page, 'reader-review-page', false);
  await page.getByRole('button', { name: 'Edit birth details' }).click();
  const editor = page.getByRole('region', { name: 'Generate a chart' });
  await editor.getByLabel('Birth time').fill('04:05');
  const saved = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
  await editor.getByRole('button', { name: 'Generate chart' }).click();
  const generated = await saved;
  expect(generated.status()).toBe(201);
  const chartId = (await generated.json()).chart.id;
  await expect(page.locator('.profile-chart-heading')).toContainText('saved birth time 04:05');
  await post(page, '/api/people/transit-person/drafts', {
    birth_date: '2001-06-21', birth_time: '04:15', time_unknown: false, birthplace: 'Synthetic London',
  });
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await expect(page.locator('.profile-summary')).toContainText('04:15');
  await expect(page.locator('.profile-draft-notice')).toContainText('saved birth time of 04:05');
  expect((await person(page)).active_chart_id).toBe(chartId);
});

for (const viewport of viewports) {
  test(`empty Saved sections open directly on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const owner = viewport.name === 'desktop' ? 'reader-layout-wide' :
      viewport.name === 'mobile' ? 'reader-layout-ultrawide' : 'reader-layout-large-ultrawide';
    await openPerson(page, owner, viewport.width < 700);
    await page.getByRole('tab', { name: 'Saved' }).click();
    const saved = page.getByRole('tabpanel', { name: 'Saved' });
    await saved.getByRole('button', { name: 'Saved for later' }).click();
    await expect(saved.getByText('No saved items yet.', { exact: false })).toBeVisible();
    await page.screenshot({ path: resolve(renders, `${viewport.name}-later-empty.png`) });
    await saved.getByRole('button', { name: 'Private journal' }).click();
    await expect(saved.getByText('No private reflections saved.')).toBeVisible();
    await expect(saved.getByLabel('Your reflection', { exact: true })).toBeVisible();
    await page.screenshot({ path: resolve(renders, `${viewport.name}-journal-empty.png`) });
  });

  test(`Saved selectors open content, retain drafts and retry failed reads on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize(viewport);
    await openPerson(page, `reader-layout-${viewport.name}`, viewport.width < 700);
    const resultId = `saved-review-${crypto.randomUUID()}`;
    await post(page, '/api/advanced-results', { id: resultId, person_id: 'transit-person',
      technique: 'solar_return', parameters: { year: 2026, latitude: 55.68, longitude: 12.57 } });
    await post(page, '/api/people/transit-person/watchlist', {
      id: `watch-review-${crypto.randomUUID()}`, result_id: resultId, event_index: 0,
      note: 'Synthetic saved result', reminder: null,
    });
    await post(page, '/api/people/transit-person/journal', {
      id: `journal-review-${crypto.randomUUID()}`, kind: 'date', local_date: '2026-11-01',
      wall_time: null, zone: null, fold: null, linked_result_id: null, text: 'Synthetic private reflection',
    });
    const reads = { later: 0, journal: 0 };
    for (const [kind, path] of [['later', 'watchlist'], ['journal', 'journal']] as const) {
      await page.route(`**/api/people/transit-person/${path}?offset=0`, async route => {
        reads[kind]++;
        if (reads[kind] === 1) await route.fulfill({ status: 503, body: '{}', contentType: 'application/json' });
        else await route.continue();
      });
    }
    await page.getByRole('tab', { name: 'Saved' }).click();
    const saved = page.getByRole('tabpanel', { name: 'Saved' });
    await expect(saved.getByRole('button', { name: 'Insights' })).toHaveAttribute('aria-pressed', 'true');
    await page.screenshot({ path: resolve(renders, `${viewport.name}-insights-empty.png`) });
    await saved.getByRole('button', { name: 'Saved for later' }).click();
    await expect(saved.getByText('Saved items could not be refreshed.', { exact: false })).toBeVisible();
    await expect(saved.getByText('No saved items yet.', { exact: false })).toHaveCount(0);
    await page.screenshot({ path: resolve(renders, `${viewport.name}-later-error.png`) });
    await saved.getByRole('alert').getByRole('button', { name: 'Try again' }).click();
    await expect(saved.getByText('Synthetic saved result')).toBeVisible();
    expect(reads.later).toBe(2);
    await saved.getByRole('button', { name: 'Edit note or reminder' }).click();
    await saved.getByRole('form', { name: 'Edit saved item' }).getByLabel('Private note (optional)').fill('Unsent reminder note');
    await page.screenshot({ path: resolve(renders, `${viewport.name}-later-ready.png`) });

    const journalButton = saved.getByRole('button', { name: 'Private journal' });
    await journalButton.focus(); await journalButton.press('Enter');
    await expect(journalButton).toHaveAttribute('aria-pressed', 'true');
    await expect(saved.getByText('Private reflections could not be refreshed.', { exact: false })).toBeVisible();
    await expect(saved.getByLabel('Your reflection', { exact: true })).toBeVisible();
    await page.screenshot({ path: resolve(renders, `${viewport.name}-journal-error.png`) });
    await saved.getByRole('alert').getByRole('button', { name: 'Try again' }).click();
    await expect(saved.getByText('Synthetic private reflection')).toBeVisible();
    expect(reads.journal).toBe(2);
    await saved.getByLabel('Your reflection', { exact: true }).fill('Unsent private draft');
    await page.screenshot({ path: resolve(renders, `${viewport.name}-journal-ready.png`) });

    const laterButton = saved.getByRole('button', { name: 'Saved for later' });
    await laterButton.focus(); await laterButton.press('Enter');
    await expect(saved.getByRole('form', { name: 'Edit saved item' }).getByLabel('Private note (optional)')).toHaveValue('Unsent reminder note');
    await expect(saved.getByText('Synthetic saved result')).toBeVisible();
    expect(reads.later).toBe(2);
    await journalButton.click();
    const reflection = saved.locator('.person-records > details').nth(1).locator('form.journal-form').first().locator('textarea');
    await expect(reflection).toBeVisible();
    await expect(reflection).toHaveValue('Unsent private draft');
    expect(reads.journal).toBe(2);
    await laterButton.click();
    await expect(saved.getByText('Synthetic saved result')).toBeVisible();
    expect(reads.later).toBe(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
  });
}

async function saveTimingForLater(page: Page, resultId: string) {
  await page.getByRole('tab', { name: 'Overview' }).click();
  await page.getByText('Saved timing', { exact: true }).click();
  const timing = page.getByRole('region', { name: 'Where am I now' });
  await timing.getByLabel('From (UTC)').fill('2026-01-01');
  await timing.getByLabel('Explore').selectOption('year');
  await timing.getByRole('button', { name: 'Show saved timing' }).click();
  const result = timing.locator(`[data-result-id="${resultId}"]`).first();
  await expect(result).toBeVisible();
  await result.getByRole('button', { name: 'Save for later' }).click();
  await expect(timing).toContainText('Saved for later. A due reminder is off');
}

for (const viewport of viewports) {
  test(`journal link choices refresh after Save for later while Later stays closed on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize(viewport);
    const owner = viewport.name === 'desktop' ? 'reader-layout-wide' :
      viewport.name === 'mobile' ? 'reader-layout-ultrawide' : 'reader-layout-large-ultrawide';
    await openPerson(page, owner, viewport.width < 700);
    const resultId = `journal-freshness-${crypto.randomUUID()}`;
    await post(page, '/api/advanced-results', { id: resultId, person_id: 'transit-person',
      technique: 'solar_return', parameters: { year: 2026, latitude: 55.68, longitude: 12.57 } });
    let reads = 0;
    page.on('request', request => {
      if (request.method() === 'GET' && request.url().includes('/people/transit-person/watchlist?offset=0')) reads++;
    });
    const initialRead = page.waitForResponse(response => response.url().includes('/people/transit-person/watchlist?offset=0'));
    await page.getByRole('button', { name: 'Private journal' }).click();
    await initialRead;
    const link = page.getByLabel('Link a saved item (optional)');
    await expect(page.getByText('No private reflections saved.')).toBeVisible();
    await expect(link.locator('option')).toHaveCount(1);
    await page.getByLabel('Your reflection', { exact: true }).fill('Unsent journal note');
    await page.getByText('Private event journal', { exact: true }).click();
    await saveTimingForLater(page, resultId);
    expect(reads).toBe(1); // Later stayed closed; the mutation must not force a hidden read.
    await page.getByRole('button', { name: 'Private journal' }).click();
    await expect(link.locator(`option[value="${resultId}"]`)).toHaveCount(1);
    await expect(link).toBeVisible();
    await expect(page.getByRole('tabpanel', { name: 'Saved' }).locator('form.journal-form').first().locator('textarea'))
      .toHaveValue('Unsent journal note');
    expect(reads).toBe(2);
    await link.selectOption(resultId);
    await expect(link).toHaveValue(resultId);
    await link.scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `${viewport.name}-journal-new-link.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
  });
}

test('an in-flight old Journal link read cannot replace a saved calculation', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize(viewports[0]);
  await openPerson(page, 'reader-layout-wide', false);
  const resultId = `journal-pending-${crypto.randomUUID()}`;
  await post(page, '/api/advanced-results', { id: resultId, person_id: 'transit-person',
    technique: 'solar_return', parameters: { year: 2026, latitude: 55.68, longitude: 12.57 } });
  let arrive!: () => void;
  let release!: () => void;
  const arrived = new Promise<void>(resolve => { arrive = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  let delivered!: () => void;
  const done = new Promise<void>(resolve => { delivered = resolve; });
  let reads = 0;
  await page.route('**/api/people/transit-person/watchlist?offset=0', async route => {
    reads++;
    if (reads === 1) {
      const response = await route.fetch();
      arrive(); await held; await route.fulfill({ response }); delivered();
    } else await route.continue();
  });
  try {
    const oldResponse = page.waitForResponse(response => response.url().includes('/people/transit-person/watchlist?offset=0'));
    await page.getByRole('button', { name: 'Private journal' }).click();
    await arrived;
    await expect(page.getByText('No private reflections saved.')).toBeVisible();
    await saveTimingForLater(page, resultId);
    const link = page.getByLabel('Link a saved item (optional)');
    await page.getByRole('tab', { name: 'Saved' }).click();
    await expect(link.locator(`option[value="${resultId}"]`)).toHaveCount(1);
    expect(reads).toBe(2);
    release(); await done;
    await (await oldResponse).finished();
    await expect(link.locator(`option[value="${resultId}"]`)).toHaveCount(1);
  } finally { release(); }
});
