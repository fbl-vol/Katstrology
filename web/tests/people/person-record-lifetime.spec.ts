import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/total-review-fixes');

async function profile(page: import('@playwright/test').Page, owner = 'reader-review-records') {
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByRole('tab', { name: 'Saved' }).click();
}

test('private journal fences a late initial read and retains drafts only for this person and session', async ({ page }) => {
  mkdirSync(renders, { recursive: true });
  await profile(page);
  let arrive!: () => void;
  let release!: () => void;
  let delivered!: () => void;
  const arrived = new Promise<void>(resolve => { arrive = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  const done = new Promise<void>(resolve => { delivered = resolve; });
  let first = true;
  await page.route('**/api/people/transit-person/journal?offset=0', async route => {
    if (!first) { await route.continue(); return; }
    first = false;
    const response = await route.fetch();
    arrive(); await held;
    await route.fulfill({ response });
    delivered();
  });
  const records = page.getByRole('region', { name: 'Saved timing and private reflections' });
  await page.getByRole('button', { name: 'Private journal' }).click();
  await arrived;
  await expect(records.getByText('Opening private reflections…')).toBeVisible();
  await expect(records.getByText('No private reflections saved.')).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 560 });
  await records.getByText('Opening private reflections…').scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'journal-loading-short.png') });
  await records.getByLabel('Your reflection', { exact: true }).fill('A private synthetic entry');
  await records.getByRole('button', { name: 'Save private reflection' }).click();
  await expect(records.locator('li').filter({ hasText: 'A private synthetic entry' })).toBeVisible();
  release(); await done;
  await expect(records.locator('li').filter({ hasText: 'A private synthetic entry' })).toBeVisible();
  await expect(records.getByText('No private reflections saved.')).toHaveCount(0);
  const entry = await records.locator('li').filter({ hasText: 'A private synthetic entry' }).boundingBox();
  const addForm = records.getByRole('form', { name: 'Add private reflection' });
  const formBox = await addForm.boundingBox();
  expect(entry && formBox && entry.y + entry.height <= formBox.y).toBe(true);
  await records.getByRole('button', { name: 'Add reflection', exact: true }).click();
  await expect(addForm.getByLabel('Your reflection')).toBeFocused();
  await addForm.getByLabel('Your reflection').fill('An unsaved private draft');
  await records.getByRole('button', { name: 'Edit text' }).click();
  await records.getByRole('form', { name: 'Edit private reflection' }).getByLabel('Your reflection').fill('An unsaved edit');
  await page.getByRole('tab', { name: 'Charts' }).click();
  await page.getByRole('tab', { name: 'Saved' }).click();
  await page.getByRole('tab', { name: 'Saved' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Overview' })).toBeFocused();
  await page.keyboard.press('ArrowLeft');
  await expect(page.getByRole('tab', { name: 'Saved' })).toBeFocused();
  await expect(addForm.getByLabel('Your reflection')).toHaveValue('An unsaved private draft');
  await expect(records.getByRole('form', { name: 'Edit private reflection' }).getByLabel('Your reflection')).toHaveValue('An unsaved edit');
  for (const viewport of [
    { name: 'desktop', width: 1440, height: 1024 }, { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 }, { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    await page.screenshot({ path: resolve(renders, `journal-${viewport.name}.png`), fullPage: true });
    if (viewport.name === 'short') {
      await records.getByRole('form', { name: 'Edit private reflection' }).getByRole('button', { name: 'Save edit' }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: resolve(renders, 'journal-short-viewport.png') });
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
  }
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Other synthetic reader' }).click();
  await page.getByRole('tab', { name: 'Saved' }).click();
  await page.getByRole('button', { name: 'Private journal' }).click();
  await expect(page.getByLabel('Your reflection', { exact: true })).toHaveValue('');
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByRole('tab', { name: 'Saved' }).click();
  await page.getByRole('button', { name: 'Private journal' }).click();
  await expect(page.getByLabel('Your reflection', { exact: true })).toHaveValue('');
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByLabel('Username').fill('reader-review-records');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByRole('tab', { name: 'Saved' }).click();
  await page.getByRole('button', { name: 'Private journal' }).click();
  await expect(page.getByLabel('Your reflection', { exact: true })).toHaveValue('');
  expect((await (await page.request.get('/api/people/transit-person/journal?offset=0')).json()).entries).toHaveLength(1);
});

test('a failed initial journal read is not described as an empty journal', async ({ page }) => {
  await profile(page, 'reader-review-page');
  let failed = false;
  await page.route('**/api/people/transit-person/journal?offset=0', async route => {
    if (!failed) { failed = true; await route.fulfill({ status: 503, body: '{}', contentType: 'application/json' }); }
    else await route.continue();
  });
  const records = page.getByRole('region', { name: 'Saved timing and private reflections' });
  await page.getByRole('button', { name: 'Private journal' }).click();
  await expect(records.getByText('Private reflections could not be refreshed.', { exact: false })).toBeVisible();
  await expect(records.getByText('No private reflections saved.')).toHaveCount(0);
  await page.getByText('Private event journal', { exact: true }).click();
  await page.getByText('Private event journal', { exact: true }).click();
  await expect(records.getByText('No private reflections saved.')).toBeVisible();
});

test('watchlist ignores a read started before saving and retains an unsaved reminder edit across tabs', async ({ page }) => {
  await profile(page, 'reader-review-records');
  const session = await (await page.request.get('/api/session')).json();
  const resultId = `watch-source-${crypto.randomUUID()}`;
  const result = await page.request.post('/api/advanced-results', {
    headers: { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin },
    data: { id: resultId, person_id: 'transit-person', technique: 'solar_return',
      parameters: { year: 2026, latitude: 55.68, longitude: 12.57 } },
  });
  expect(result.status()).toBe(201);
  await page.getByRole('tab', { name: 'Overview' }).click();
  await page.getByText('Saved timing', { exact: true }).click();
  const timing = page.getByRole('region', { name: 'Where am I now' });
  await timing.getByLabel('From (UTC)').fill('2026-01-01');
  await timing.getByLabel('Explore').selectOption('year');
  await timing.getByRole('button', { name: 'Show saved timing' }).click();
  await expect(timing.locator(`[data-result-id="${resultId}"]`).first()).toBeVisible();
  let arrive!: () => void;
  let release!: () => void;
  let delivered!: () => void;
  const arrived = new Promise<void>(resolve => { arrive = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  const done = new Promise<void>(resolve => { delivered = resolve; });
  let first = true;
  await page.route('**/api/people/transit-person/watchlist?offset=0', async route => {
    if (!first) { await route.continue(); return; }
    first = false;
    const response = await route.fetch(); arrive(); await held;
    await route.fulfill({ response }); delivered();
  });
  await page.getByRole('tab', { name: 'Saved' }).click();
  const records = page.getByRole('region', { name: 'Saved timing and private reflections' });
  await page.getByRole('button', { name: 'Saved for later' }).click();
  await arrived;
  await expect(records.getByText('Opening saved items…')).toBeVisible();
  await page.getByRole('tab', { name: 'Overview' }).click();
  await timing.locator(`[data-result-id="${resultId}"]`).first().getByRole('button', { name: 'Save for later' }).click();
  await page.getByRole('tab', { name: 'Saved' }).click();
  await expect(records.getByText('Reminder off.')).toBeVisible();
  release(); await done;
  await expect(records.getByText('Reminder off.')).toBeVisible();
  await expect(records.getByText('No saved items yet.', { exact: false })).toHaveCount(0);
  await records.getByRole('button', { name: 'Edit note or reminder' }).click();
  const form = records.getByRole('form', { name: 'Edit saved item' });
  await form.getByLabel('Private note (optional)').fill('Unsaved reminder note');
  await page.getByRole('tab', { name: 'Charts' }).click();
  await page.getByRole('tab', { name: 'Saved' }).click();
  await expect(form.locator('textarea')).toHaveValue('Unsaved reminder note');
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
});

test('watchlist pagination started before an edit cannot append a stale page', async ({ page }) => {
  test.setTimeout(60_000);
  await profile(page, 'reader-review-page');
  const session = await (await page.request.get('/api/session')).json();
  const headers = { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin };
  const resultId = `paged-source-${crypto.randomUUID()}`;
  expect((await page.request.post('/api/advanced-results', { headers,
    data: { id: resultId, person_id: 'transit-person', technique: 'solar_return',
      parameters: { year: 2026, latitude: 55.68, longitude: 12.57 } },
  })).status()).toBe(201);
  for (let i = 0; i < 21; i++) {
    expect((await page.request.post('/api/people/transit-person/watchlist', { headers,
      data: { id: `page-item-${i}-${resultId}`, result_id: resultId, event_index: 0,
        note: `Synthetic item ${i}`, reminder: null },
    })).status()).toBe(201);
  }
  const records = page.getByRole('region', { name: 'Saved timing and private reflections' });
  await page.getByRole('button', { name: 'Saved for later' }).click();
  await expect(records.getByRole('button', { name: 'Load more saved items' })).toBeVisible();
  await expect(records.locator('ul > li')).toHaveCount(20);
  let arrive!: () => void;
  let release!: () => void;
  let delivered!: () => void;
  const arrived = new Promise<void>(resolve => { arrive = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  const done = new Promise<void>(resolve => { delivered = resolve; });
  await page.route('**/api/people/transit-person/watchlist?offset=20', async route => {
    const response = await route.fetch(); arrive(); await held;
    await route.fulfill({ response }); delivered();
  });
  await records.getByRole('button', { name: 'Load more saved items' }).click();
  await arrived;
  await records.getByRole('button', { name: 'Edit note or reminder' }).first().click();
  const form = records.getByRole('form', { name: 'Edit saved item' });
  await form.getByLabel('Private note (optional)').fill('Edited before stale page');
  await form.getByRole('button', { name: 'Save item' }).click();
  await expect(form).toBeHidden();
  await expect(records.locator('ul > li').first()).toContainText('Edited before stale page');
  release(); await done;
  await page.unroute('**/api/people/transit-person/watchlist?offset=20');
  await expect(records.locator('ul > li')).toHaveCount(20);
  await expect(records.getByRole('button', { name: 'Load more saved items' })).toBeVisible();
  await records.getByRole('button', { name: 'Load more saved items' }).click();
  await expect(records.locator('ul > li')).toHaveCount(21);
});

test('watchlist read failure is not an empty list and retried read restores actual items', async ({ page }) => {
  await profile(page, 'reader-review-records');
  const session = await (await page.request.get('/api/session')).json();
  const headers = { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin };
  const resultId = `watch-retry-source-${crypto.randomUUID()}`;
  const result = await page.request.post('/api/advanced-results', { headers,
    data: { id: resultId, person_id: 'transit-person', technique: 'solar_return',
      parameters: { year: 2026, latitude: 55.68, longitude: 12.57 } },
  });
  expect(result.status()).toBe(201);
  const saved = await page.request.post('/api/people/transit-person/watchlist', { headers,
    data: { id: `watch-retry-${crypto.randomUUID()}`, result_id: resultId, event_index: 0,
      note: 'A persisted synthetic item', reminder: null },
  });
  expect(saved.status()).toBe(201);
  let failed = false;
  await page.route('**/api/people/transit-person/watchlist?offset=0', async route => {
    if (!failed) { failed = true; await route.fulfill({ status: 503, body: '{}', contentType: 'application/json' }); }
    else await route.continue();
  });
  const records = page.getByRole('region', { name: 'Saved timing and private reflections' });
  await page.getByRole('button', { name: 'Saved for later' }).click();
  await expect(records.getByText('Saved items could not be refreshed.', { exact: false })).toBeVisible();
  await expect(records.getByText('No saved items yet.', { exact: false })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 560 });
  await page.screenshot({ path: resolve(renders, 'watchlist-error-short.png'), fullPage: true });
  await page.getByText('Saved for later · in-app reminders').click();
  await page.getByText('Saved for later · in-app reminders').click();
  await expect(records.getByText('A persisted synthetic item')).toBeVisible();
});

test('post-mutation watchlist paging cannot replace a committed first-page refresh', async ({ page }) => {
  test.setTimeout(90_000);
  await profile(page, 'reader-review-pagination');
  const session = await (await page.request.get('/api/session')).json();
  const headers = { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin };
  const resultId = `review-paged-${crypto.randomUUID()}`;
  expect((await page.request.post('/api/advanced-results', { headers,
    data: { id: resultId, person_id: 'transit-person', technique: 'solar_return',
      parameters: { year: 2026, latitude: 55.68, longitude: 12.57 } },
  })).status()).toBe(201);
  for (let i = 0; i < 21; i++) {
    expect((await page.request.post('/api/people/transit-person/watchlist', { headers,
      data: { id: `after-item-${i}-${resultId}`, result_id: resultId, event_index: 0,
        note: `Original saved note ${i}`, reminder: null },
    })).status()).toBe(201);
  }
  const records = page.getByRole('region', { name: 'Saved timing and private reflections' });
  await page.getByRole('button', { name: 'Saved for later' }).click();
  await expect(records.locator('ul > li')).toHaveCount(20);
  await expect(records.getByRole('button', { name: 'Load more saved items' })).toBeVisible();

  let arrive!: () => void;
  let release!: () => void;
  let delivered!: () => void;
  const arrived = new Promise<void>(resolve => { arrive = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  const done = new Promise<void>(resolve => { delivered = resolve; });
  const basePath = '**/api/people/transit-person/watchlist?offset=0';
  await page.route(basePath, async route => {
    const response = await route.fetch(); arrive(); await held;
    await route.fulfill({ response }); delivered();
  });
  await records.getByRole('button', { name: 'Edit note or reminder' }).first().click();
  const form = records.getByRole('form', { name: 'Edit saved item' });
  await form.getByLabel('Private note (optional)').fill('Committed saved note');
  await form.getByRole('button', { name: 'Save item' }).click();
  await arrived;
  await expect(records.getByText('Opening saved items…')).toBeVisible();
  await expect(form.getByRole('button', { name: 'Saving…' })).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 560 });
  await records.getByText('Opening saved items…').scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'post-watch-pending-short.png') });
  await form.getByRole('button', { name: 'Saving…' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'post-watch-disabled-short.png') });
  const stalePage = records.getByRole('button', { name: 'Load more saved items' });
  if (await stalePage.count()) {
    await stalePage.evaluate(button => (button as HTMLButtonElement).click());
    if (await stalePage.isEnabled()) await expect(records.locator('ul > li')).toHaveCount(21);
  }
  release(); await done;
  await page.unroute(basePath);
  await expect(records.getByText('Committed saved note')).toBeVisible();
  await expect(form).toHaveCount(0);
  await expect(records.locator('ul > li')).toHaveCount(20);
  expect((await (await page.request.get('/api/people/transit-person/watchlist?offset=0')).json())
    .items.some((item: { note: string }) => item.note === 'Committed saved note')).toBe(true);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 }, { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 }, { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize(size);
    await records.getByText('Committed saved note').scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `post-watch-${size.name}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
  await expect(records.getByRole('button', { name: 'Load more saved items' })).toBeEnabled();
  await records.getByRole('button', { name: 'Load more saved items' }).focus();
  await expect(records.getByRole('button', { name: 'Load more saved items' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(records.locator('ul > li')).toHaveCount(21);
});

test('post-mutation journal paging cannot replace a committed first-page refresh', async ({ page }) => {
  test.setTimeout(90_000);
  await profile(page, 'reader-review-journal');
  const session = await (await page.request.get('/api/session')).json();
  const headers = { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin };
  for (let i = 0; i < 21; i++) {
    expect((await page.request.post('/api/people/transit-person/journal', { headers,
      data: { id: `after-journal-${i}-${crypto.randomUUID()}`, kind: 'date', local_date: '2026-11-01',
        wall_time: null, zone: null, fold: null, linked_result_id: null, text: `Original reflection ${i}` },
    })).status()).toBe(201);
  }
  const records = page.getByRole('region', { name: 'Saved timing and private reflections' });
  await page.getByRole('button', { name: 'Private journal' }).click();
  await expect(records.locator('ul > li')).toHaveCount(20);
  await expect(records.getByRole('button', { name: 'Load more reflections' })).toBeVisible();

  let arrive!: () => void;
  let release!: () => void;
  let delivered!: () => void;
  const arrived = new Promise<void>(resolve => { arrive = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  const done = new Promise<void>(resolve => { delivered = resolve; });
  const basePath = '**/api/people/transit-person/journal?offset=0';
  await page.route(basePath, async route => {
    const response = await route.fetch(); arrive(); await held;
    await route.fulfill({ response }); delivered();
  });
  await records.getByRole('button', { name: 'Edit text' }).first().click();
  const form = records.getByRole('form', { name: 'Edit private reflection' });
  await form.getByLabel('Your reflection').fill('Committed private reflection');
  await form.getByRole('button', { name: 'Save edit' }).click();
  await arrived;
  await expect(records.getByText('Opening private reflections…')).toBeVisible();
  await expect(form.getByRole('button', { name: 'Saving…' })).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 560 });
  await records.getByText('Opening private reflections…').scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'post-journal-pending-short.png') });
  await form.getByRole('button', { name: 'Saving…' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'post-journal-disabled-short.png') });
  const stalePage = records.getByRole('button', { name: 'Load more reflections' });
  if (await stalePage.count()) {
    await stalePage.evaluate(button => (button as HTMLButtonElement).click());
    if (await stalePage.isEnabled()) await expect(records.locator('ul > li')).toHaveCount(21);
  }
  release(); await done;
  await page.unroute(basePath);
  await expect(records.getByText('Committed private reflection')).toBeVisible();
  await expect(form).toHaveCount(0);
  await expect(records.locator('ul > li')).toHaveCount(20);
  expect((await (await page.request.get('/api/people/transit-person/journal?offset=0')).json())
    .entries.some((item: { text: string }) => item.text === 'Committed private reflection')).toBe(true);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 }, { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 }, { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize(size);
    await records.getByText('Committed private reflection').scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `post-journal-${size.name}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
  let failed = false;
  await page.route(basePath, async route => {
    if (!failed) { failed = true; await route.fulfill({ status: 503, body: '{}', contentType: 'application/json' }); }
    else await route.continue();
  });
  await records.getByRole('button', { name: 'Edit text' }).first().click();
  await records.getByRole('form', { name: 'Edit private reflection' }).getByLabel('Your reflection').fill('Committed after failed refresh');
  await records.getByRole('form', { name: 'Edit private reflection' }).getByRole('button', { name: 'Save edit' }).click();
  await expect(records.getByText('Private reflections could not be refreshed.', { exact: false })).toBeVisible();
  await expect(records.getByRole('button', { name: 'Load more reflections' })).toHaveCount(0);
  await expect(records.getByText('Committed private reflection')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 560 });
  await records.getByText('Private reflections could not be refreshed.', { exact: false }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'post-journal-failed-refresh-short.png') });
  await page.getByText('Private event journal', { exact: true }).click();
  await page.getByText('Private event journal', { exact: true }).click();
  await expect(records.getByText('Committed after failed refresh')).toBeVisible();
  await expect(records.getByRole('button', { name: 'Load more reflections' })).toBeEnabled();
  await records.getByRole('button', { name: 'Load more reflections' }).focus();
  await expect(records.getByRole('button', { name: 'Load more reflections' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(records.locator('ul > li')).toHaveCount(21);
});
