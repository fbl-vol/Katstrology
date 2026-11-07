import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { openLibrary } from '../support/chart-library-fixture';

const renders = resolve(import.meta.dirname, '../../../.local/chart-library-release2-fixes/renders');
const hub = (page: Page) => page.getByRole('region', { name: 'Create chart', exact: true });

async function freshLibrary(page: Page, name: string, natal = true) {
  await openLibrary(page);
  const session = await (await page.request.get('/api/session')).json();
  const headers = { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin };
  const created = await page.request.post('/api/people', { headers, data: { name } });
  expect(created.status()).toBe(201);
  const id: string = (await created.json()).id;
  if (natal) {
    const generated = await page.request.post(`/api/people/${id}/generate`, { headers, data: {
      request_id: crypto.randomUUID(), birth_date: '2001-06-21', birth_time: '04:00',
      time_unknown: false, birthplace: 'Copenhagen, Capital Region, Denmark', place_id: '2618425',
      provisional: true, zone_override: null, latitude_override: null, longitude_override: null, fold: null, settings: null,
    } });
    expect(generated.status()).toBe(201);
  }
  await page.reload();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  await expect(page.locator('.library-card')).toHaveCount(natal ? 1 : 0);
  return id;
}

test('chart library corrections carry contextual creation and reset global and switched-person intent', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  await openLibrary(page);
  await expect(page.getByRole('button', { name: 'Start conversation', exact: true })).not.toHaveClass(/primary/);
  const create = page.locator('.chart-library').getByRole('button', { name: 'Create chart', exact: true });
  await expect(create).toHaveClass(/primary/);
  const createBackground = await create.evaluate(button => getComputedStyle(button).backgroundColor);
  const discuss = page.getByRole('button', { name: 'Start conversation', exact: true });
  expect(await discuss.evaluate(button => getComputedStyle(button).backgroundColor)).not.toBe(createBackground);
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  expect(await discuss.evaluate(button => getComputedStyle(button).backgroundColor)).toBe(createBackground);
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  await create.click();
  for (const title of ['Solar return', 'Lunar returns', 'Planetary returns', 'Midheaven transit contacts',
    'Secondary progressions', 'Solar-arc directions', 'Progressed lunar phases', 'Lunations and eclipses']) {
    await hub(page).getByRole('button', { name: new RegExp(`^${title}`) }).click();
    await expect(page.getByLabel('Person with a current natal')).toHaveValue('transit-person');
    if (title === 'Solar-arc directions') {
      mkdirSync(renders, { recursive: true });
      for (const size of [{ width: 1440, height: 1024 }, { width: 1920, height: 1080 },
        { width: 2560, height: 1080 }, { width: 3440, height: 1440 }, { width: 390, height: 844 }, { width: 390, height: 560 }]) {
        await page.setViewportSize(size);
        await page.screenshot({ path: resolve(renders, `contextual-solar-arc-${size.width}-${size.height}.png`), fullPage: true });
      }
      await page.setViewportSize({ width: 1440, height: 1024 });
    }
    await page.getByRole('button', { name: 'Back to chart choices', exact: true }).click();
  }
  await hub(page).getByRole('button', { name: /^Transits / }).click();
  await page.getByRole('radio', { name: 'Natal + transits', exact: true }).check();
  await expect(page.getByRole('combobox', { name: 'Person', exact: true })).toHaveValue('transit-person');
  await page.getByRole('button', { name: 'Back to chart choices' }).click();
  await hub(page).getByRole('button', { name: /^Synastry/ }).click();
  await expect(page.getByRole('combobox', { name: 'Person A', exact: true })).toHaveValue('transit-person');
  await expect(page.getByRole('combobox', { name: 'Person B', exact: true })).toHaveValue('');
  await expect(page.getByRole('button', { name: 'Compare charts', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Back to chart choices' }).click();
  await hub(page).getByRole('button', { name: /^Composite and Davison/ }).click();
  await expect(page.getByRole('combobox', { name: 'First person', exact: true })).toHaveValue('transit-person');
  await expect(page.getByRole('combobox', { name: 'Second person', exact: true })).toHaveValue('');
  await page.getByRole('button', { name: 'Back to chart choices' }).click();
  await hub(page).getByRole('button', { name: /^Natal chart/ }).click();
  await expect(page.getByRole('region', { name: 'Generate a chart' })).toBeVisible();
  await expect(page.locator('.header-title')).toHaveText('Synthetic transit reader');
  await page.getByRole('button', { name: '← Return to workspace', exact: true }).click();
  await expect(page.locator('.chart-library')).toBeVisible();
  await page.getByRole('button', { name: '＋ Create chart', exact: true }).click();
  await hub(page).getByRole('button', { name: /^Solar-arc directions/ }).click();
  await expect(page.getByLabel('Person with a current natal')).toHaveValue('');
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Other synthetic reader' }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  await page.locator('.chart-library').getByRole('button', { name: 'Create chart', exact: true }).click();
  await hub(page).getByRole('button', { name: /^Solar-arc directions/ }).click();
  await expect(page.getByLabel('Person with a current natal')).toHaveValue('other-transit-person');
});

test('chart library corrections route missing natal to the same birth editor and preserve corrected source', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  const id = await freshLibrary(page, 'Synthetic missing source', false);
  await page.locator('.chart-library').getByRole('button', { name: 'Create chart', exact: true }).click();
  await hub(page).getByRole('button', { name: /^Solar-arc directions/ }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic missing source needs a current natal' })).toBeVisible();
  mkdirSync(renders, { recursive: true });
  for (const size of [{ width: 1440, height: 1024 }, { width: 390, height: 560 }]) {
    await page.setViewportSize(size);
    await page.screenshot({ path: resolve(renders, `missing-natal-${size.width}-${size.height}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.getByRole('button', { name: 'Create natal for Synthetic missing source' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2001-06-21');
  await form.getByLabel('Birth time').fill('04:00');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  const generated = page.waitForResponse(response => /\/generate$/.test(response.url()), { timeout: 8000 });
  await form.getByRole('button', { name: 'Generate chart', exact: true }).click();
  const firstResponse = await generated;
  expect(firstResponse.url()).toContain(`/api/people/${id}/generate`);
  expect(firstResponse.status()).toBe(201);
  await expect(form.getByRole('status').filter({ hasText: 'Current natal saved.' })).toBeVisible();
  await page.getByRole('button', { name: '← Return to workspace', exact: true }).click();
  await expect(page.getByLabel('Person with a current natal')).toHaveValue(id);
  await page.getByRole('button', { name: 'Back to chart choices' }).click();
  await hub(page).getByRole('button', { name: 'Return to workspace' }).click();
  await expect(page.locator('.library-card[data-technique="natal"]')).toBeVisible();
  await page.locator('.chart-library').getByRole('button', { name: 'Create chart', exact: true }).click();
  await hub(page).getByRole('button', { name: /^Natal chart/ }).click();
  await form.getByRole('button', { name: 'Update the current natal', exact: true }).click();
  await expect(form.getByLabel('Birth time')).toHaveValue('04:00');
  await form.getByLabel('Birth time').fill('04:02');
  const corrected = page.waitForResponse(response => /\/generate$/.test(response.url()), { timeout: 8000 });
  await form.getByRole('button', { name: 'Generate chart', exact: true }).click();
  const correctedResponse = await corrected;
  expect(correctedResponse.url()).toContain(`/api/people/${id}/generate`);
  expect(correctedResponse.status()).toBe(201);
  const currentId = (await correctedResponse.json()).chart.id;
  await expect(form.getByRole('status').filter({ hasText: 'Current natal saved.' })).toBeVisible();
  await page.getByRole('button', { name: '← Return to workspace', exact: true }).click();
  await expect(page.locator('.library-card[data-technique="natal"]')).toHaveAttribute('data-result-id', currentId);
  await expect(page.locator('.library-card[data-technique="natal"]')).toContainText('History · 2 saved');
});

for (const layout of ['List', 'Gallery']) {
  test(`chart library corrections refresh real first-type and existing-type saves on normal return in ${layout}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1024 });
    const id = await freshLibrary(page, `Synthetic save return ${layout}`);
    const library = page.locator('.chart-library');
    await library.getByRole('button', { name: layout, exact: true }).click();
    for (let save = 1; save <= 2; save++) {
      await library.getByRole('button', { name: 'Create chart', exact: true }).click();
      await hub(page).getByRole('button', { name: /^Solar-arc directions/ }).click();
      await expect(page.getByLabel('Person with a current natal')).toHaveValue(id);
      await page.getByLabel('Effective date (UTC midnight)').fill(save === 1 ? '2024-03-25' : '2025-03-25');
      const saved = page.waitForResponse(response => response.url().endsWith('/api/advanced-results') && response.request().method() === 'POST');
      await page.getByRole('button', { name: 'Calculate solar arc', exact: true }).click();
      const response = await saved;
      expect(response.status()).toBe(201);
      const result = await response.json();
      await page.getByRole('button', { name: 'Back to chart choices' }).click();
      await hub(page).getByRole('button', { name: 'Return to workspace' }).click();
      const card = library.locator('[data-technique="true_solar_arc"]');
      await expect(card).toHaveAttribute('data-result-id', result.id);
      await expect(card).toContainText(`History · ${save} saved`);
      await expect(library.locator('.library-card')).toHaveCount(2);
      await expect(library.locator('.library-collection')).toHaveAttribute('data-view', layout.toLowerCase());
      await card.getByRole('button', { name: 'Open Solar-arc directions', exact: true }).click();
      await expect(library.locator('.library-reader')).toHaveAttribute('data-result-id', result.id);
      await library.getByRole('button', { name: 'Back to chart library' }).click();
      await card.getByRole('button', { name: /Solar-arc directions history/ }).click();
      await expect(library.locator('.library-history li')).toHaveCount(save);
      await library.getByRole('button', { name: 'Back to chart library' }).click();
    }
  });
}

for (const layout of ['List', 'Gallery']) {
test(`chart library corrections retain usable ${layout} through refresh failure and isolate late person responses`, async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  const id = await freshLibrary(page, `Synthetic retained library ${layout}`);
  const library = page.locator('.chart-library');
  await library.getByRole('button', { name: layout, exact: true }).click();
  const session = await (await page.request.get('/api/session')).json();
  const generated = await page.request.post(`/api/people/${id}/generate`, {
    headers: { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin }, data: {
      request_id: crypto.randomUUID(), birth_date: '2001-06-21', birth_time: '04:01',
      time_unknown: false, birthplace: 'Copenhagen, Capital Region, Denmark', place_id: '2618425',
      provisional: true, zone_override: null, latitude_override: null, longitude_override: null, fold: null, settings: null,
    },
  });
  expect(generated.status()).toBe(201);
  const newNatal: string = (await generated.json()).chart.id;
  const originalId = await library.locator('.library-card').getAttribute('data-result-id');
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let requests = 0;
  await page.route(`**/api/people/${id}/chart-library`, async route => {
    requests++;
    if (requests === 1) { await gate; await route.fulfill({ status: 503, json: { error: 'synthetic_refresh_failure' } }); }
    else await route.continue();
  });
  await library.getByRole('button', { name: 'Create chart', exact: true }).click();
  await hub(page).getByRole('button', { name: 'Return to workspace' }).click();
  await expect(library.getByRole('button', { name: 'Create chart', exact: true })).toBeFocused();
  await expect(library.getByRole('status')).toContainText('Updating saved chart library');
  await expect(library.locator('.library-card')).toHaveAttribute('data-result-id', originalId!);
  await library.getByRole('button', { name: layout === 'List' ? 'Gallery' : 'List', exact: true }).click();
  await library.getByRole('button', { name: layout, exact: true }).click();
  expect(requests).toBe(1);
  mkdirSync(renders, { recursive: true });
  await page.screenshot({ path: resolve(renders, `retained-${layout}-refresh-1440-1024.png`), fullPage: true });
  await library.getByRole('button', { name: 'Open Natal chart', exact: true }).click();
  await expect(library.locator('.profile-active-chart .natal-wheel')).toBeVisible();
  release();
  await library.getByRole('button', { name: 'Back to chart library' }).click();
  await expect(library.getByRole('alert')).toContainText('Previously loaded charts remain available');
  await expect(library.locator('.library-label')).toHaveText('Previously loaded natal');
  await expect(library.locator('.library-card')).toHaveAttribute('data-result-id', originalId!);
  for (const size of [{ width: 1440, height: 1024 }, { width: 390, height: 560 }, { width: 3440, height: 1440 }]) {
    await page.setViewportSize(size);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(renders, `retained-${layout}-failure-${size.width}-${size.height}.png`), fullPage: true });
  }
  await library.getByRole('button', { name: /Natal chart history/ }).click();
  await expect(library.locator('.library-history li')).toHaveCount(2);
  await library.getByRole('button', { name: 'Back to chart library' }).click();
  await library.getByRole('button', { name: 'Retry chart library' }).click();
  await expect(library.getByRole('alert')).toHaveCount(0);
  await expect(library.getByRole('status')).toHaveCount(0);
  expect(requests).toBe(2);
  await expect(library.locator('.library-card')).toHaveAttribute('data-result-id', newNatal);
  await expect(library.locator('.library-label')).toHaveText('Current natal');

  let late!: () => void;
  const lateGate = new Promise<void>(resolve => { late = resolve; });
  await page.unroute(`**/api/people/${id}/chart-library`);
  await page.route(`**/api/people/${id}/chart-library`, async route => {
    const response = await route.fetch();
    await lateGate;
    await route.fulfill({ response });
  });
  await library.getByRole('button', { name: 'Create chart', exact: true }).click();
  await hub(page).getByRole('button', { name: 'Return to workspace' }).click();
  await expect(library.getByRole('status')).toContainText('Updating saved chart library');
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Other synthetic reader' }).click();
  await expect(page.locator(`[data-result-id="${newNatal}"]`)).toHaveCount(0);
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  await expect(library.locator('[data-technique="natal"]')).toBeVisible();
  const lateResponse = page.waitForResponse(response => response.url().endsWith(`/api/people/${id}/chart-library`));
  late();
  await lateResponse;
  await expect(library.locator(`[data-result-id="${newNatal}"]`)).toHaveCount(0);
  await expect(page.locator('.header-title')).toHaveText('Other synthetic reader');
});
}
