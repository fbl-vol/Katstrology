import { expect, test, type Route } from '@playwright/test';

test('a normal archived reply loads all 17 remaining events without another send', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-complete-normal');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByLabel('Message Kat').fill('Synthetic multi-page reply fixture');
    await page.getByRole('button', { name: 'Send message' }).click();
    const reply = page.locator('.turn-card .assistant-answer').first();
    await expect(reply).toContainText('[segment-45]', { timeout: 30000 });
    await page.reload();

    let pages = 0;
    await page.route('**/turns/*?offset=32', async route => {
      pages++;
      if (pages === 1) {
        await route.fulfill({ status: 503, contentType: 'application/json',
          body: JSON.stringify({ error: 'synthetic_page_failure' }) });
      } else {
        await route.continue();
      }
    });
    await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
    const card = page.locator('.turn-card').first();
    await expect(card.getByRole('alert')).toContainText('saved reply is incomplete');
    const visibleReply = page.locator('.turn-card .assistant-answer').first();
    await expect(visibleReply).not.toContainText('[segment-45]');
    await expect(page.getByRole('button', { name: /Load remaining archived events/ })).toHaveCount(0);
    await card.getByRole('button', { name: 'Retry loading saved reply' }).click();
    await expect(visibleReply).toContainText('[segment-45]', { timeout: 30000 });
    await expect(card.getByRole('alert')).toHaveCount(0);
    expect(pages).toBe(2);
    const archived = await page.evaluate(async () => {
      const id = (await fetch('/api/conversations').then(response => response.json())).conversations[0]?.id;
      const turnId = document.querySelector('[data-kat-turn-id]')?.getAttribute('data-kat-turn-id');
      if (!id || !turnId) throw new Error('Synthetic archived turn missing');
      const page = await fetch(`/api/conversations/${id}/turns/${turnId}?offset=32`).then(response => response.json());
      return { count: page.events.length, terminal: page.events.at(-1)?.kind };
    });
    expect(archived).toEqual({ count: 17, terminal: 'complete' });
    const text = await visibleReply.innerText();
    for (let index = 0; index < 46; index++)
      expect(text.split(`[segment-${String(index).padStart(2, '0')}]`).length - 1).toBe(1);

    await page.reload();
    let unblock!: () => void;
    let requested!: () => void;
    const gate = new Promise<void>(resolve => { unblock = resolve; });
    const reached = new Promise<void>(resolve => { requested = resolve; });
    const slowPage = async (route: Route) => {
      requested();
      await gate;
      try { await route.continue(); } catch { /* Navigation may abort the old request. */ }
    };
    await page.route('**/turns/*?offset=32', slowPage);
    try {
      await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
      await reached;
      await page.locator('button.new-chat').click();
    } finally {
      unblock();
    }
    await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
    await page.unroute('**/turns/*?offset=32', slowPage);
    await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
    await expect(page.locator('.turn-card .assistant-answer').first())
      .toContainText('[segment-45]', { timeout: 30000 });

    await page.reload();
    let openGate!: () => void;
    let onRequest!: () => void;
    const waiting = new Promise<void>(resolve => { openGate = resolve; });
    const requestedPage = new Promise<void>(resolve => { onRequest = resolve; });
    const pendingPage = async (route: Route) => {
      onRequest();
      await waiting;
      try { await route.continue(); } catch { /* An old view may abort its fetch. */ }
    };
    await page.route('**/turns/*?offset=32', pendingPage);
    try {
      await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
      await requestedPage;
      await page.getByRole('button', { name: /Create chart/ }).first().click();
    } finally {
      openGate();
    }
    await expect(page.getByRole('region', { name: 'Create chart' })).toBeVisible();
    await page.getByRole('button', { name: 'Return to workspace' }).click();
    await page.unroute('**/turns/*?offset=32', pendingPage);
    await expect(page.locator('.turn-card .assistant-answer').first())
      .toContainText('[segment-45]', { timeout: 30000 });

    await page.reload();
    let releaseAccount!: () => void;
    let accountRequest!: () => void;
    const accountGate = new Promise<void>(resolve => { releaseAccount = resolve; });
    const accountReached = new Promise<void>(resolve => { accountRequest = resolve; });
    const oldPage = async (route: Route) => {
      accountRequest();
      await accountGate;
      try { await route.continue(); } catch { /* The signed-out request may be aborted. */ }
    };
    await page.route('**/turns/*?offset=32', oldPage);
    try {
      await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
      await accountReached;
      await page.getByRole('button', { name: 'Sign out' }).click();
    } finally {
      releaseAccount();
    }
    await page.unroute('**/turns/*?offset=32', oldPage);
    await page.getByLabel('Username').fill('reader-complete-alt');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await expect(page.locator('.turn-card')).toHaveCount(0);
    await expect(page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry')).toHaveCount(0);
  });

test('a normal three-page reply reaches its exact final event', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-complete-three-normal');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByLabel('Message Kat').fill('Synthetic three-page reply fixture');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.locator('.turn-card .assistant-answer').first())
      .toContainText('[segment-109]', { timeout: 30000 });
    await page.reload();
    const offsets: number[] = [];
    await page.route('**/turns/*?offset=*', async route => {
      const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
      offsets.push(offset);
      await route.continue();
    });
    await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
    const card = page.locator('.turn-card').first();
    await expect(page.locator('.turn-card .assistant-answer').first())
      .toContainText('[segment-109]', { timeout: 30000 });
    expect(offsets).toEqual([32, 96]);
    await expect(card.getByRole('status')).toHaveCount(0);
    await expect(card.getByRole('alert')).toHaveCount(0);
    const all = await page.evaluate(async () => {
      const id = (await fetch('/api/conversations').then(response => response.json())).conversations[0]?.id;
      const turnId = document.querySelector('[data-kat-turn-id]')?.getAttribute('data-kat-turn-id');
      return fetch(`/api/conversations/${id}/turns/${turnId}?offset=96`).then(response => response.json());
    });
    expect(all.events).toHaveLength(17);
    expect(all.events.at(-1).kind).toBe('complete');
  });

test('a 270-event reply retains its ending after archive paging and reload', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-complete-270-normal');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByLabel('Message Kat').fill('Synthetic 270-event reply fixture');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.locator('.turn-card .assistant-answer').first())
      .toContainText('[segment-269]', { timeout: 60000 });
    await page.reload();
    const offsets: number[] = [];
    await page.route('**/turns/*?offset=*', async route => {
      offsets.push(Number(new URL(route.request().url()).searchParams.get('offset')));
      await route.continue();
    });
    await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
    await expect(page.locator('.turn-card .assistant-answer').first())
      .toContainText('[segment-269]', { timeout: 60000 });
    expect(offsets).toEqual([32, 96, 160, 224]);
    await expect(page.locator('.turn-card').first().getByRole('alert')).toHaveCount(0);
  });

test('a normal long archived reply remains document-scrollable on mobile', async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-complete-mobile-normal');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByLabel('Message Kat').fill('Synthetic multi-page reply fixture');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.locator('.turn-card .assistant-answer').first())
      .toContainText('[segment-45]', { timeout: 30000 });
    await page.reload();
    await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
    const reply = page.locator('.turn-card .assistant-answer').first();
    await expect(reply).toContainText('[segment-45]', { timeout: 30000 });
    const scroll = await page.evaluate(() => ({ document: document.documentElement.scrollHeight,
      viewport: window.innerHeight }));
    expect(scroll.document).toBeGreaterThan(scroll.viewport);
    await reply.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/application-performance/complete-reply-normal-mobile.png` });
    await expect(page.getByRole('button', { name: /Load remaining archived events|Show more/ })).toHaveCount(0);
  });

test('a normal late chart survives archived event pagination', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-complete-sky-normal');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByLabel('Message Kat').fill('Synthetic multi-page sky chart fixture');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.locator('.turn-card .chat-transit-card')).toHaveCount(1, { timeout: 30000 });
    await page.reload();
    await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
    const card = page.locator('.turn-card').first();
    await expect(card.locator('.chat-transit-card')).toHaveCount(1, { timeout: 30000 });
    await expect(page.locator('.turn-card .assistant-answer').first())
      .toContainText('Late calculated sky chart follows.');
    await card.locator('.chat-transit-card > summary').click();
    await expect(card.locator('.chat-transit-card').getByRole('img', { name: /tropical/ })).toBeVisible();
    await expect(card.getByRole('button', { name: /Load remaining archived events/ })).toHaveCount(0);
});
