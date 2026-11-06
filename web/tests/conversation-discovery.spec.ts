import { test, expect, type Page } from '@playwright/test';

async function signIn(page: Page) {
  await page.getByLabel('Username').fill('reader-shell');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByLabel('Message Kat')).toBeVisible();
}

function result(title: string) {
  return { id: title, title, created_at: '2026-01-01T12:00:00Z', active_head: null, people: [] };
}

for (const delayed of ['search', 'page'] as const) {
  test(`conversation discovery ignores a stale ${delayed} after a newer search`, async ({ page }) => {
    let release!: () => void;
    const held = new Promise<void>(resolve => { release = resolve; });
    let started!: () => void;
    const requested = new Promise<void>(resolve => { started = resolve; });
    await page.route('**/api/conversations?*', async route => {
      if (new URL(route.request().url()).searchParams.get('offset') === '20') {
        started(); await held;
        await route.fulfill({ json: { conversations: [result('Old page')], next_offset: null, search_pending: 0 } });
      } else await route.fulfill({ json: { conversations: [result('Initial history')], next_offset: 20, search_pending: 0 } });
    });
    await page.route('**/api/conversations/search', async route => {
      const query = route.request().postDataJSON().query;
      if (query === 'old') { started(); await held; }
      await route.fulfill({ json: { conversations: [result(query === 'old' ? 'Old search' : 'Current match')],
        next_offset: null, search_pending: 0 } });
    });
    await page.goto('/'); await signIn(page);
    await expect(page.getByText('Initial history', { exact: true })).toBeVisible();
    if (delayed === 'page') await page.getByRole('button', { name: 'Load older conversations' }).click();
    else {
      await page.getByLabel('Search conversations').fill('old');
      await page.getByRole('button', { name: 'Search', exact: true }).click();
    }
    await requested;
    await page.getByLabel('Search conversations').fill('current');
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    await expect(page.locator('.recent-title')).toHaveText(['Current match']);
    const staleResponse = page.waitForResponse(response => delayed === 'page' ?
      response.url().includes('offset=20') : response.request().postData()?.includes('old') === true);
    release(); await staleResponse;
    await expect(page.locator('.recent-title')).toHaveText(['Current match']);
    await expect(page.getByRole('button', { name: 'Load older conversations' })).toHaveCount(0);
  });
}

test('conversation discovery discards an old session search after sign-out and sign-in', async ({ page }) => {
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let started!: () => void;
  const requested = new Promise<void>(resolve => { started = resolve; });
  await page.route('**/api/conversations/search', async route => {
    started(); await held;
    await route.fulfill({ json: { conversations: [result('Old session result')], next_offset: 20, search_pending: 0 } });
  });
  await page.goto('/'); await signIn(page);
  await page.getByLabel('Search conversations').fill('old');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await requested;
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome to Kat.' })).toBeVisible();
  await signIn(page);
  const response = page.waitForResponse('**/api/conversations/search');
  release(); await response;
  await expect(page.getByText('Old session result', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Search conversations')).toHaveValue('');
});
