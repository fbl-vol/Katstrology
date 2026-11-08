import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { personIdFor, seedLegacy } from '../support/legacy-fixture';
import { archivedTurn } from '../support/archive-assertions';

test.beforeAll(() => mkdirSync(resolve(import.meta.dirname, '../../../.local/birth-save'), { recursive: true }));

async function openPerson(page: import('@playwright/test').Page, name: string, owner: string, mobile = false) {
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  if (mobile) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill(name);
  await dialog.getByRole('button', { name: 'Create person' }).click();
  await expect(page.getByRole('heading', { name })).toBeVisible();
  return page.getByRole('region', { name: 'Generate a chart' });
}

async function chooseCity(form: import('@playwright/test').Locator, city: string, result: RegExp) {
  await form.getByLabel('Birthplace search').fill(city);
  await form.getByRole('button', { name: result }).first().click();
}

for (const viewport of [
  { name: 'desktop', size: { width: 1440, height: 1024 }, owner: 'reader-people' },
  { name: 'mobile', size: { width: 390, height: 844 }, owner: 'reader-mobile' },
]) {
  test(`historical timezone correction and saved one-step chart on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(90000);
    await page.setViewportSize(viewport.size);
    await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
    const name = `Synthetic timezone ${viewport.name}`;
    const form = await openPerson(page, name, viewport.owner, viewport.name === 'mobile');
    await form.getByLabel('Birth date').fill('2024-03-20');
    await form.getByLabel('Birth time').fill('03:06');
    await chooseCity(form, 'Copenhagen', /Copenhagen, Capital Region, Denmark/);
    await form.getByText('Advanced · chart settings and location').click();
    const zone = form.getByLabel('IANA timezone override');
    await zone.fill('europe/copenhagen');
    await expect(form.getByRole('button', { name: 'Use Europe/Copenhagen' })).toBeVisible();
    let posts = 0;
    page.on('request', request => { if (request.method() === 'POST' && /\/api\/people\/[^/]+\/generate$/.test(new URL(request.url()).pathname)) posts++; });
    await form.getByRole('button', { name: 'Generate chart' }).click();
    await expect(form.getByRole('alert')).toContainText('exact timezone spelling Europe/Copenhagen');
    await expect(zone).toBeFocused();
    expect(posts).toBe(0);
    await page.screenshot({ path: `../.local/birth-save/correction-${viewport.name}.png` });
    await form.getByRole('button', { name: 'Use Europe/Copenhagen' }).click();
    await expect(zone).toHaveValue('Europe/Copenhagen');
    let release!: () => void;
    let arrived!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const received = new Promise<void>(resolve => { arrived = resolve; });
    let chartId = '';
    await page.route('**/api/people/*/generate', async route => {
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      chartId = (await response.json()).chart.id;
      arrived(); await gate; await route.fulfill({ response });
    });
    await form.getByRole('button', { name: 'Generate chart' }).click();
    await received;
    await expect(form.getByRole('button', { name: 'Generating chart…' })).toBeDisabled();
    await expect(form.locator('.birth-status')).toContainText('Generating and saving');
    await page.screenshot({ path: `../.local/birth-save/pending-${viewport.name}.png` });
    release();
    expect(chartId).toMatch(/^chart-[a-f0-9]+$/);
    await expect(form.locator('.birth-status')).toContainText('Current natal saved');
    await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
    expect(posts).toBe(1);
    await expect(form.getByRole('button', { name: 'Chart saved' })).toBeDisabled();
    await form.locator('.birth-status').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/birth-save/saved-${viewport.name}.png` });
    await page.reload();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: new RegExp(name) }).click();
    await page.getByRole('tab', { name: 'Charts' }).click();
    await page.locator('.chart-history > summary').click();
    await expect(page.locator(`.chart-history > details[data-kat-chart-id="${chartId}"] > summary`)).toContainText('Current natal');
  });
}

for (const viewport of [
  { name: 'desktop', size: { width: 1440, height: 1024 }, owner: 'reader-natal' },
  { name: 'mobile', size: { width: 390, height: 844 }, owner: 'reader-natal-mobile' },
]) {
  test(`one-step natal, safe SVG and selected context persist on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize(viewport.size);
    const name = `Synthetic chart reader ${viewport.name}`;
    const form = await openPerson(page, name, viewport.owner, viewport.name === 'mobile');
    await form.getByLabel('Birth date').fill('1948-11-14');
    await form.getByLabel('Birth time').fill('21:14');
    await chooseCity(form, 'London', /London, England, United Kingdom/);
    await form.getByText('Advanced · chart settings and location').click();
    await form.getByLabel('Latitude override').fill('51.5');
    await form.getByLabel('Longitude override').fill('-0.166666666666667');
    const saved = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
    await form.getByRole('button', { name: 'Generate chart' }).click();
    const response = await saved;
    expect(response.status()).toBe(201);
    const chartId = (await response.json()).chart.id as string;
    const chart = page.locator('.profile-active-chart');
    await expect(chart.getByRole('group', { name: /Tropical natal wheel/ })).toBeVisible();
    await chart.getByText('All chart tables', { exact: true }).click();
    await expect(chart.getByRole('table', { name: /Planet and lunar node positions/ }).getByRole('row', { name: /Sun 22°25′ Scorpio/ })).toBeVisible();
    await chart.getByRole('tab', { name: /^Houses/ }).click();
    await expect(chart.getByRole('table', { name: /Angles and placidus house cusps/ }).getByRole('row', { name: /Ascendant 5°23′ Leo/ })).toBeVisible();
    await chart.getByRole('tab', { name: /^Aspects/ }).click();
    await expect(chart.getByRole('table', { name: /Major aspects/ }).getByRole('row', { name: /Jupiter opposition Uranus/ })).toBeVisible();
    await expect(chart.getByText(/ecliptic-projected longitude/)).toBeHidden();
    await chart.getByText('How this chart was calculated').click();
    await expect(chart.getByText(/ecliptic-projected longitude/)).toBeVisible();
    await page.screenshot({ path: `../.local/acceptance/natal-${viewport.name}.png`, fullPage: true });
    const downloadPromise = page.waitForEvent('download');
    await chart.getByText('Download chart', { exact: true }).click();
    await chart.getByRole('button', { name: 'Download safe SVG wheel' }).click();
    const download = await downloadPromise;
    const markup = await readFile(await download.path(), 'utf8');
    expect(markup).toContain('Natal · tropical');
    expect(markup).toContain('"method_version":"natal-tropical-v1"');
    expect(markup).not.toMatch(/<text[^>]*>[^<]*natal-tropical-v1/);
    expect(markup).not.toMatch(/<script|<foreignObject|onload=|href="https?:/i);
    expect(download.suggestedFilename()).toMatch(/^kat-chart-[a-f0-9]+\.svg$/);
    await page.getByRole('button', { name: 'Start conversation' }).click();
    await expect(page.locator('.person-chip')).toContainText('current natal');
    await page.getByLabel('Message Kat').fill(`saved chart ${chartId}`);
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.locator('.assistant-answer')).toContainText('Synthetic provider captured text only', { timeout: 15000 });
    const card = page.locator('.turn-card').last();
    await expect(card).toHaveAttribute('data-kat-status', 'complete', { timeout: 30000 });
    const savedTurn = await archivedTurn(page, card);
    expect(savedTurn.selected_people[0].chart_id).toBe(chartId);
    const natalRead = savedTurn.events.find(event => event.kind === 'tool_result' && event.payload.name === 'get_chart');
    expect(JSON.stringify(natalRead?.payload.result)).toContain('jupiter');
    await expect(card.getByText('Context & sources')).toHaveCount(0);
    await card.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/acceptance/labels-natal-${viewport.name}.png` });
    await page.reload();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: new RegExp(name) }).click();
    await page.getByRole('tab', { name: 'Charts' }).click();
    await page.locator('.chart-history > summary').click();
    const history = page.locator(`.chart-history > details[data-kat-chart-id="${chartId}"]`);
    await history.locator(':scope > summary').click();
    await history.getByText('All chart tables', { exact: true }).click();
    await expect(history.getByRole('table', { name: /Planet and lunar node positions/ })).toBeVisible();
  });
}

test('polar Placidus remains unsupported and explicit whole-sign/mean-node revisions persist', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  mkdirSync('../.local/explorable-charts/renders', { recursive: true });
  const form = await openPerson(page, 'Synthetic polar chart', 'reader-natal-polar');
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('03:06');
  await form.getByLabel('Birthplace search').fill('Synthetic polar location');
  await form.getByText('Advanced · chart settings and location').click();
  await form.getByLabel('IANA timezone override').fill('UTC');
  await form.getByLabel('Latitude override').fill('70');
  await form.getByLabel('Longitude override').fill('20');
  await form.getByRole('button', { name: 'Generate chart' }).click();
  const partial = page.locator('.profile-active-chart');
  await expect(partial.getByText(/No substitute system or ascendant was invented/)).toBeVisible();
  await expect(partial.locator('svg.natal-wheel')).toHaveCount(0);
  await expect(partial.getByText(/Choose a symbol, house number/)).toHaveCount(0);
  await partial.getByRole('tab', { name: /^Patterns/ }).click();
  await expect(partial.getByRole('tab', { name: /^Patterns \d+$/ })).toBeVisible();
  await expect(partial.getByText(/Patterns need established/)).toHaveCount(0);
  await partial.locator('.explorer-panel').evaluate(element => element.scrollIntoView({ block: 'start' }));
  await page.screenshot({ path: '../.local/explorable-charts/renders/partial-houses.png' });
  await form.getByRole('button', { name: 'Update the current natal' }).click();
  await form.getByLabel('House system').selectOption('whole_sign');
  await form.getByLabel('North node').selectOption('mean');
  await form.getByRole('button', { name: 'Generate chart' }).click();
  const whole = page.locator('.profile-active-chart');
  await expect(whole.getByRole('group', { name: /Tropical natal wheel/ })).toBeVisible();
  await expect(whole.getByText(/whole_sign houses · mean north node/)).toBeVisible();
  const personId = await personIdFor(page, 'Synthetic polar chart');
  const record = await (await page.request.get(`/api/people/${personId}`)).json();
  const facts = record.charts.find((c: { id: string }) => c.id === record.active_chart_id).result.natal;
  const mc = facts.houses.angles.find((p: { id: string }) => p.id === 'midheaven').longitude_degrees;
  expect(mc).not.toBe(facts.houses.cusps[9].longitude_degrees);
  await whole.getByRole('tab', { name: /^Houses/ }).click();
  await whole.locator('[data-entry="midheaven"]').click();
  await expect(whole.getByRole('region', { name: 'Chart browser and selected detail' })).toContainText(`${mc.toFixed(4)}°`);
  await expect(whole.locator('[data-highlight-body="midheaven"]')).toHaveCount(1);
  await page.screenshot({ path: '../.local/explorable-charts/renders/whole-sign-angle.png' });
  await form.getByRole('button', { name: 'Update the current natal' }).click();
  await form.getByRole('spinbutton', { name: 'square' }).fill('0.1');
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await page.locator('.profile-active-chart').getByRole('tab', { name: /^Aspects/ }).click();
  await page.locator('.profile-active-chart').getByText('All chart tables', { exact: true }).click();
  await expect(page.locator('.profile-active-chart').getByRole('table', { name: /Major aspects/ })).toBeVisible();
  await page.locator('.chart-history > summary').click();
  await expect(page.locator('.chart-history > details')).toHaveCount(3);
});

test('legacy partial chart and new unknown-time chart never invent a wheel', async ({ page }) => {
  const form = await openPerson(page, 'Synthetic uncertain reader', 'reader-natal-unknown');
  const id = await personIdFor(page, 'Synthetic uncertain reader');
  const { chartId: legacyId } = await seedLegacy(page, id, { kind: 'natal' });
  await page.reload();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic uncertain reader/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  await page.locator('.chart-history > summary').click();
  const legacy = page.locator(`.chart-history > details[data-kat-chart-id="${legacyId}"]`);
  await legacy.locator(':scope > summary').click();
  await expect(legacy.getByText(/Houses and angles unavailable \(unsupported missing coordinates\)/)).toBeVisible();
  await expect(legacy.getByRole('img', { name: /Tropical natal wheel/ })).toHaveCount(0);
  await legacy.getByText('All chart tables', { exact: true }).click();
  await expect(legacy.getByRole('table', { name: /Planet and lunar node positions/ })).toBeVisible();
  await page.getByRole('button', { name: 'Create first chart' }).first().click();
  const birth = page.getByRole('region', { name: 'Generate a chart' });
  await birth.getByLabel('Birth date').fill('2024-10-27');
  await birth.getByLabel('Time unknown').check();
  await chooseCity(birth, 'Copenhagen', /Copenhagen, Capital Region, Denmark/);
  await birth.getByRole('button', { name: 'Generate chart' }).click();
  const unknown = page.locator('.profile-active-chart');
  await expect(unknown.getByText(/no full natal positions, houses, angles or aspects were calculated/)).toBeVisible();
  await expect(unknown.getByRole('table')).toHaveCount(0);
  mkdirSync('../.local/explorable-charts/renders', { recursive: true });
  await unknown.screenshot({ path: '../.local/explorable-charts/renders/unknown-time.png' });
  await expect(unknown.getByRole('img', { name: /Tropical natal wheel/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Start conversation' }).click();
  const contextChart = page.getByRole('complementary', { name: 'Current natal context' });
  await expect(contextChart).toContainText('Complete natal wheel unavailable');
  await expect(contextChart.getByRole('img', { name: /Tropical natal wheel/ })).toHaveCount(0);
  const desktop = page.viewportSize()!;
  await page.setViewportSize({ width: 390, height: 560 });
  await expect(contextChart.locator(':scope > details > summary')).toContainText('Complete natal wheel unavailable');
  await expect(contextChart.locator(':scope > details')).not.toHaveAttribute('open');
  await page.setViewportSize(desktop);
  await page.getByLabel('Message Kat').fill('unknown-time chart');
  await page.getByRole('button', { name: 'Send message' }).click();
  const card = page.locator('.turn-card').last();
  await expect(card).toHaveAttribute('data-kat-status', 'complete', { timeout: 30000 });
  const savedTurn = await archivedTurn(page, card);
  const natalRead = savedTurn.events.find(event => event.kind === 'tool_result' && event.payload.name === 'get_chart');
  expect(JSON.stringify(natalRead?.payload.result)).toContain('unsupported_uncertain_birth_time');
  await expect(card.getByText('Context & sources')).toHaveCount(0);
});
