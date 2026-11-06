import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { archivedTurn } from '../support/archive-assertions';

test.beforeAll(() => mkdirSync(resolve(import.meta.dirname, '../../../.local/one-step'), { recursive: true }));

for (const viewport of [
  { name: 'desktop', size: { width: 1440, height: 1024 }, account: 'reader-race' },
  { name: 'mobile', size: { width: 390, height: 844 }, account: 'reader-create-race' },
]) {
  test(`one form generates and discusses the current natal without version selection on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(90000);
    await page.setViewportSize(viewport.size);
    await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
    await page.goto('/');
    await page.getByLabel('Username').fill(viewport.account);
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Add person', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
    await dialog.getByLabel('Name').fill(`Synthetic one-step ${viewport.name}`);
    await dialog.getByRole('button', { name: 'Create person' }).click();
    await expect(page.getByRole('region', { name: 'Generate a chart' })).toBeVisible();
    await expect(page.locator('.chart-history > summary')).toHaveText('Earlier charts and birth details');
    await expect(page.locator('.chart-history > details')).toHaveCount(0);
    await expect(page.locator('.profile-chart-heading')).toContainText('No active generated natal');
    const form = page.getByRole('region', { name: 'Generate a chart' });
    await form.getByLabel('Birth date').fill('2024-03-20');
    await form.getByLabel('Birth time').fill('03:06');
    await form.getByLabel('Birthplace search').fill('cOPENHAGEN');
    const city = form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ });
    await expect(city).toBeVisible();
    await city.click();
    await expect(form.getByText(/GeoNames city-centre reference/)).toBeVisible();
    await expect(form.getByText('Advanced · chart settings and location')).toBeVisible();
    await page.screenshot({ path: `../.local/one-step/before-${viewport.name}.png` });
    if (viewport.name === 'mobile') {
      await page.setViewportSize({ width: 390, height: 560 });
      await form.getByRole('button', { name: 'Generate chart' }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: '../.local/one-step/action-short-mobile.png' });
      await page.setViewportSize(viewport.size);
    }
    const saved = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
    await form.getByRole('button', { name: 'Generate chart' }).click();
    const response = await saved;
    expect(response.status()).toBe(201);
    const result = await response.json();
    const chartId = result.chart.id as string;
    expect(chartId).toMatch(/^chart-[a-f0-9]+$/);
    expect(result.chart.result.natal.status).toBe('complete');
    expect(result.chart.result.birth.provenance).toBe('provisional:geonames_city_centre_2618425');
    await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
    await expect(page.locator('.profile-active-chart')).toBeVisible();
    await expect(form.locator('.birth-status')).toHaveText('Current natal saved. Details remain provisional.');
    await expect(page.locator('.profile-active-chart')).toContainText('Birth details are provisional');
    await expect(page.locator('.profile-active-chart')).toContainText('city-centre reference, not an exact birth location');
    await expect(page.locator('.profile-active-chart')).not.toContainText('not independently verified');
    await page.locator('.profile-active-chart').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/one-step/chart-handoff-${viewport.name}.png` });
    await page.locator('.profile-active-chart').getByText('All chart tables', { exact: true }).click();
    await expect(page.locator('.profile-active-chart').getByRole('table', { name: 'Planet and lunar node positions' })).toBeVisible();
    await expect(page.locator('.profile-active-chart').getByRole('group', { name: /Tropical natal wheel/ })).toBeVisible();
    await page.locator('.profile-active-chart').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/one-step/generated-${viewport.name}.png` });
    await page.getByRole('button', { name: 'Start conversation' }).click();
    await expect(page.locator('.person-chip')).toContainText('current natal');
    await page.getByLabel('Message Kat').fill(`saved chart ${chartId}`);
    const turnAck = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
    await page.getByRole('button', { name: 'Send message' }).click();
    const ack = await turnAck;
    expect(ack.status(), await ack.text()).toBe(202);
    await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'complete', { timeout: 15000 });
    expect((await archivedTurn(page, page.locator('.turn-card').last())).selected_people[0].chart_id).toBe(chartId);
    await page.reload();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: new RegExp(`Synthetic one-step ${viewport.name}`) }).click();
    await page.getByRole('tab', { name: 'Charts' }).click();
    await page.locator('.chart-history > summary').click();
    await expect(page.locator(`.chart-history > details[data-kat-chart-id="${chartId}"] > summary`)).toContainText('Current natal');
    await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
    let placeSearches = 0;
    let modelSends = 0;
    page.on('request', request => {
      if (request.url().includes('/api/places/search')) placeSearches++;
      if (/\/api\/conversations\/[^/]+\/turns$/.test(request.url()) && request.method() === 'POST') modelSends++;
    });
    await page.getByRole('button', { name: 'Edit birth details' }).click();
    const nextForm = page.getByRole('region', { name: 'Generate a chart' });
    await expect(nextForm.getByLabel('Birthplace search')).toHaveValue('Copenhagen, Capital Region, Denmark');
    await expect(nextForm.getByRole('button', { name: 'Change birthplace' })).toBeVisible();
    await nextForm.getByLabel('Birth time').fill('03:07');
    const nextSaved = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
    await nextForm.getByRole('button', { name: 'Generate chart' }).click();
    const nextResponse = await nextSaved;
    expect(nextResponse.status()).toBe(201);
    const nextResult = await nextResponse.json();
    const nextId = nextResult.chart.id as string;
    expect(nextId).not.toBe(chartId);
    expect(nextResult.place_id).toBe('2618425');
    expect(nextResult.chart.result.birth.zone).toBe(result.chart.result.birth.zone);
    expect(nextResult.chart.result.birth.latitude).toBe(result.chart.result.birth.latitude);
    expect(nextResult.chart.result.birth.longitude).toBe(result.chart.result.birth.longitude);
    expect(placeSearches).toBe(0);
    expect(modelSends).toBe(0);
    await expect(page.locator(`.chart-history > details[data-kat-chart-id="${chartId}"] > summary`)).toContainText('Historical chart');
    await expect(page.locator(`.chart-history > details[data-kat-chart-id="${nextId}"] > summary`)).toContainText('Current natal');
    await page.getByRole('button', { name: 'Start conversation' }).click();
    await expect(page.locator('.person-chip')).toContainText('current natal');
  });
}

for (const viewport of [
  { name: 'desktop', size: { width: 1440, height: 1024 }, account: 'reader-ordinary-desktop' },
  { name: 'mobile', size: { width: 390, height: 844 }, account: 'reader-ordinary-mobile' },
]) {
  test(`ordinary reliable chart copy keeps city and unknown-time warnings on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(90000);
    await page.setViewportSize(viewport.size);
    await page.goto('/');
    await page.getByLabel('Username').fill(viewport.account);
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Add person', exact: true }).click();
    await page.getByRole('dialog', { name: 'A space for someone new.' }).getByLabel('Name')
      .fill(`Synthetic ordinary copy ${viewport.name}`);
    await page.getByRole('dialog', { name: 'A space for someone new.' })
      .getByRole('button', { name: 'Create person' }).click();
    const form = page.getByRole('region', { name: 'Generate a chart' });
    await form.getByLabel('Birth date').fill('2024-03-20');
    await form.getByLabel('Birth time').fill('03:06');
    await form.getByLabel('Birthplace search').fill('Copenhagen');
    await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
    await form.getByLabel('Details are provisional').uncheck();
    await form.getByRole('button', { name: 'Generate chart' }).click();
    await expect(form.locator('.birth-status')).toHaveText('Current natal saved.');
    const chart = page.locator('.profile-active-chart');
    await expect(chart).toContainText('city-centre reference, not an exact birth location');
    await expect(chart).not.toContainText('not independently verified');
    await expect(chart.getByText('How this chart was calculated')).toBeVisible();
    await expect(chart.getByText('House membership uses ecliptic-projected longitude')).toBeHidden();
    await chart.locator('.natal-qualification').evaluate(node =>
      window.scrollTo(0, window.scrollY + node.getBoundingClientRect().top - 185));
    const renders = resolve(import.meta.dirname, '../../../.local/ux07');
    mkdirSync(renders, { recursive: true });
    await page.screenshot({ path: resolve(renders, `reliable-natal-${viewport.name}.png`) });
    await page.getByRole('button', { name: 'Edit birth details' }).click();
    const update = page.getByRole('region', { name: 'Generate a chart' });
    await update.getByRole('button', { name: 'Update the current natal' }).click();
    await update.getByLabel('Birth date').fill('2024-03-21');
    await update.getByLabel('Time unknown').check();
    await expect(update.getByRole('button', { name: 'Change birthplace' })).toBeVisible();
    await update.getByRole('button', { name: 'Generate chart' }).click();
    await expect(page.locator('.profile-active-chart')).toContainText('Unknown or uncertain birth time');
    await expect(page.locator('.profile-active-chart').getByRole('img', { name: /Tropical natal wheel/ })).toHaveCount(0);
    await page.locator('.profile-active-chart').scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `unknown-time-${viewport.name}.png`) });
  });
}

test('DST gaps reject, repeated hours require a chosen occurrence, and edits stay in the same form', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-people');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic DST correction');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2024-03-31');
  await form.getByLabel('Birth time').fill('02:30');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  const posted = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
  await form.getByRole('button', { name: 'Generate chart' }).click();
  expect((await posted).status()).toBe(400);
  await expect(form.getByRole('alert')).toContainText('did not occur');
  await expect(form.getByLabel('Birth time')).toHaveValue('02:30');
  await form.getByLabel('Birth date').fill('2024-10-27');
  const ambiguous = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
  await form.getByRole('button', { name: 'Generate chart' }).click();
  expect((await ambiguous).status()).toBe(400);
  await expect(form.getByRole('alert')).toContainText('occurred twice');
  await expect(form.locator('.birth-advanced')).toHaveAttribute('open', '');
  await form.getByLabel('Repeated birth hour').selectOption('1');
  const saved = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
  await form.getByRole('button', { name: 'Generate chart' }).click();
  expect((await saved).status()).toBe(201);
  await expect(form.locator('.birth-status')).toContainText('Current natal saved');
  await page.locator('.chart-history > summary').click();
  await expect(page.locator('.chart-history > details')).toHaveCount(1);
});

test('lost response retries the same durable generation without duplicate versions', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'midnight-orchid'));
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-natal-unknown');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic lost ACK');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('03:06');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  let count = 0;
  let chartId = '';
  let firstChartId = '';
  await page.route('**/api/people/*/generate', async route => {
    const response = await route.fetch();
    const result = await response.json();
    chartId = result.chart.id;
    count++;
    if (count === 1) {
      firstChartId = chartId;
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"unavailable"}' });
    } else {
      expect(result.reused).toBe(true);
      await route.fulfill({ response });
    }
  });
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.getByRole('alert')).toContainText('Save was not confirmed');
  await expect(form.getByRole('button', { name: 'Retry same chart request' })).toBeVisible();
  await page.screenshot({ path: resolve(import.meta.dirname, '../../../.local/one-step/midnight-orchid-error-desktop.png') });
  await form.getByRole('button', { name: 'Retry same chart request' }).click();
  await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
  await expect(form.locator('.birth-status')).toHaveText('Current natal saved. Details remain provisional.');
  expect(count).toBe(2);
  expect(chartId).toBe(firstChartId);
  await page.locator('.chart-history > summary').click();
  await expect(page.locator('.chart-history > details')).toHaveCount(1);
});

test('committed chart remains visible when archive refresh fails, then survives reload', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-natal-polar');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic refresh failure');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('03:06');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  let failed = false;
  await page.route('**/api/people/*', async route => {
    if (!failed && route.request().method() === 'GET' && /^\/api\/people\/[^/]+$/.test(new URL(route.request().url()).pathname)) {
      failed = true;
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"unavailable"}' });
    } else await route.continue();
  });
  const result = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
  await form.getByRole('button', { name: 'Generate chart' }).click();
  const saved = await result;
  expect(saved.status()).toBe(201);
  const chartId = (await saved.json()).chart.id as string;
  await expect(form.locator('.birth-status')).toContainText('The chart was saved, but the person list could not refresh');
  await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
  await expect(page.locator('.profile-active-chart')).toBeVisible();
  await expect(form.getByRole('button', { name: 'Chart saved' })).toBeDisabled();
  expect(failed).toBe(true);
  await page.reload();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic refresh failure/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  await page.locator('.chart-history > summary').click();
  await expect(page.locator(`.chart-history > details[data-kat-chart-id="${chartId}"] > summary`)).toContainText('Current natal');
});
