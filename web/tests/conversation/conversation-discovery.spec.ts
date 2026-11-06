import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

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

test('a delayed generated title cannot replace a newer sidebar search', async ({ page }) => {
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let started!: () => void;
  const requested = new Promise<void>(resolve => { started = resolve; });
  let titleReads = 0;
  await page.route(/\/api\/conversations\/[^/?]+$/, async route => {
    if (route.request().method() !== 'GET') { await route.continue(); return; }
    const response = await route.fetch();
    const thread = await response.json();
    if (++titleReads === 1) {
      await route.fulfill({ json: { ...thread, title_status: 'pending' } });
    } else {
      started(); await held;
      await route.fulfill({ json: { ...thread, title: 'Generated after search', title_status: 'generated' } });
    }
  });
  await page.route('**/api/conversations/search', route => route.fulfill({ json: {
    conversations: [result('Current search result')], next_offset: null, search_pending: 0,
  } }));
  await page.goto('/'); await signIn(page);
  await page.getByLabel('Message Kat').fill('Synthetic title refresh question');
  await page.getByRole('button', { name: 'Send message' }).click();
  await requested;
  await page.getByLabel('Search conversations').fill('current');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.locator('.recent-title')).toHaveText(['Current search result']);
  release();
  await expect(page.locator('.header-title')).toHaveText('Generated after search');
  await expect(page.locator('.recent-title')).toHaveText(['Current search result']);
});

for (const heldStage of ['create', 'ACK', 'retry'] as const) {
  for (const browse of ['search', 'page'] as const) {
    test(`background discovery preserves intervening ${browse} after held ${heldStage}`, async ({ page }) => {
      let release!: () => void;
      const held = new Promise<void>(resolve => { release = resolve; });
      let arrived!: () => void;
      const started = new Promise<void>(resolve => { arrived = resolve; });
      const holdPage = heldStage === 'ACK' && browse === 'page';
      let releasePage!: () => void;
      const pageHeld = new Promise<void>(resolve => { releasePage = resolve; });
      let pageArrived!: () => void;
      const pageStarted = new Promise<void>(resolve => { pageArrived = resolve; });
      const turnIds: string[] = [];
      const laterReads: { query: string; offset: number }[] = [];
      let watchRefresh = false;
      await page.route('**/api/conversations', async route => {
        if (route.request().method() !== 'POST' || heldStage !== 'create') {
          await route.continue(); return;
        }
        const response = await route.fetch();
        arrived(); await held; await route.fulfill({ response });
      });
      await page.route('**/api/conversations/*/turns', async route => {
        if (route.request().method() !== 'POST') { await route.continue(); return; }
        turnIds.push(route.request().postDataJSON().id);
        const response = await route.fetch(); // Real durable admission, not a fake ACK.
        if (heldStage === 'retry' && turnIds.length === 1) { await route.abort('failed'); return; }
        if (heldStage !== 'create') { arrived(); await held; }
        await route.fulfill({ response });
      });
      await page.route('**/api/conversations?*', async route => {
        if (watchRefresh) laterReads.push({ query: '', offset: Number(new URL(route.request().url()).searchParams.get('offset')) });
        await route.continue();
      });
      await page.route('**/api/conversations/search', async route => {
        const { query, offset } = route.request().postDataJSON();
        if (watchRefresh) laterReads.push({ query, offset });
        if (offset && holdPage) { pageArrived(); await pageHeld; }
        await route.fulfill({ json: { conversations: [result(offset ? 'Older deliberate match' : 'Current deliberate match')],
          next_offset: offset ? null : 20, search_pending: 0 } });
      });
      await page.goto('/'); await signIn(page);
      await page.getByLabel('Message Kat').fill('Synthetic delayed response while drafting complete');
      await page.getByRole('button', { name: 'Send message' }).click();
      if (heldStage === 'retry') await page.getByRole('button', { name: 'Retry this message' }).click();
      await started;
      const pendingId = await page.locator('.local-pending').getAttribute('data-kat-pending-turn-id');
      await page.getByLabel('Message Kat').fill('New draft stays separate');
      await page.getByLabel('Search conversations').fill('deliberate');
      await page.getByRole('button', { name: 'Search', exact: true }).click();
      await expect(page.locator('.recent-title')).toHaveText(['Current deliberate match']);
      if (browse === 'page') {
        await page.getByRole('button', { name: 'Load older conversations' }).click();
        if (holdPage) await pageStarted;
        else await expect(page.locator('.recent-title')).toHaveText(['Current deliberate match', 'Older deliberate match']);
      }
      // Unsubmitted text is not the committed query that a background refresh should use.
      await page.getByLabel('Search conversations').fill('not submitted');
      watchRefresh = true;
      release();
      await expect(page.locator('.local-pending')).toHaveCount(0);
      await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'complete', { timeout: 30000 });
      expect(turnIds).toEqual(heldStage === 'retry' ? [pendingId, pendingId] : [pendingId]);
      expect(laterReads.filter(read => read.query !== 'deliberate')).toEqual([]);
      if (browse === 'page') expect(laterReads).toEqual([]); // Background work must not collapse loaded pages.
      releasePage(); // An in-flight page remains current through ACK and terminal refresh.
      await expect(page.locator('.recent-title')).toHaveText(browse === 'page' ?
        ['Current deliberate match', 'Older deliberate match'] : ['Current deliberate match']);
      await expect(page.getByLabel('Search conversations')).toHaveValue('not submitted');
      await expect(page.getByLabel('Message Kat')).toHaveValue('New draft stays separate');
      if (heldStage === 'ACK' && browse === 'page') {
        const renders = resolve(import.meta.dirname, '../../../.local/structure-fix1-renders');
        mkdirSync(renders, { recursive: true });
        for (const view of [{ width: 1440, height: 1024 }, { width: 390, height: 844 }, { width: 390, height: 560 }]) {
          await page.setViewportSize(view);
          if (view.width === 390) await page.getByRole('button', { name: 'Open navigation' }).click();
          await page.getByLabel('Search conversations').scrollIntoViewIfNeeded();
          if (view.height === 560) await page.locator('.recent-title').last().scrollIntoViewIfNeeded();
          await page.screenshot({ path: resolve(renders, `preserved-page-${view.width}x${view.height}.png`) });
          if (view.width === 390) await page.keyboard.press('Escape');
          await expect(page.getByLabel('Message Kat')).toHaveValue('New draft stays separate');
        }
      }
    });
  }
}
