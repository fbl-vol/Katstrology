import { test, expect, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/instant-send');

async function signIn(page: Page, owner: string) {
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
}

async function expectUnobscuredBubble(page: Page, selector: string) {
  const bounds = await page.evaluate(selector => {
    const bubble = [...document.querySelectorAll(selector)].at(-1)?.getBoundingClientRect();
    const header = document.querySelector('.header')?.getBoundingClientRect();
    const dock = document.querySelector('.composer-wrap')?.getBoundingClientRect();
    return bubble && { top: bubble.top, bottom: bubble.bottom,
      viewTop: header?.bottom || 0, viewBottom: Math.min(innerHeight, dock?.top || innerHeight) };
  }, selector);
  expect(bounds).toBeTruthy();
  expect(bounds!.top).toBeGreaterThanOrEqual(bounds!.viewTop);
  expect(bounds!.bottom).toBeLessThanOrEqual(bounds!.viewBottom);
}

async function send(page: Page, text: string, method: 'Enter' | 'Send') {
  const input = page.getByLabel('Message Kat');
  await input.fill(text);
  await input.focus();
  if (method === 'Enter') await input.press('Enter');
  else await page.getByRole('button', { name: 'Send message' }).click();
}

test('Enter paints a local message and clears only its submitted draft before create, sidebar or ACK', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await signIn(page, 'reader-instant-normal');
  let releaseCreate!: () => void;
  const createGate = new Promise<void>(resolve => { releaseCreate = resolve; });
  let releaseAck!: () => void;
  const ackGate = new Promise<void>(resolve => { releaseAck = resolve; });
  let releaseSidebar!: () => void;
  const sidebarGate = new Promise<void>(resolve => { releaseSidebar = resolve; });
  let createStarted!: () => void;
  const started = new Promise<void>(resolve => { createStarted = resolve; });
  await page.route('**/api/conversations', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    createStarted(); await createGate; await route.continue();
  });
  await page.route('**/api/conversations?offset=0', async route => {
    await sidebarGate; await route.continue();
  });
  await page.route('**/api/conversations/*/turns', async route => {
    const response = await route.fetch(); await ackGate; await route.fulfill({ response });
  });
  await page.evaluate(() => document.addEventListener('keydown', event => {
    if (event.key === 'Enter') (window as Window & { katSendStart?: number }).katSendStart = performance.now();
  }, { capture: true, once: true }));
  await send(page, 'A synthetic question to paint right away', 'Enter');
  await started;
  const painted = await page.evaluate(() => new Promise<{ elapsed: number; visible: boolean; draft: string }>(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const bubble = document.querySelector('.local-pending .user-bubble');
      const dock = document.querySelector('.composer-wrap');
      const rect = bubble?.getBoundingClientRect();
      resolve({ elapsed: performance.now() - ((window as Window & { katSendStart?: number }).katSendStart || 0),
        visible: !!rect && rect.bottom > 0 && rect.top < (dock?.getBoundingClientRect().top || innerHeight),
        draft: (document.querySelector('#message') as HTMLTextAreaElement)?.value || '' });
    }));
  }));
  writeFileSync(resolve(renders, `create-gated-normal.json`),
    JSON.stringify({ measured: painted, gate: 'create, sidebar, ACK held', source: 'isolated synthetic' }, null, 2));
  expect(painted.visible).toBe(true);
  expect(painted.draft).toBe('');
  await expect(page.getByLabel('Message Kat')).toBeFocused();
  await page.getByLabel('Message Kat').fill('A new draft, not the sent text');
  const pending = page.locator('.local-pending');
  await expect(pending).toContainText('A synthetic question to paint right away');
  await page.screenshot({ path: resolve(renders, `create-gated-normal-desktop.png`), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: resolve(renders, `create-gated-normal-mobile.png`), fullPage: true });
  await page.setViewportSize({ width: 390, height: 560 });
  await expect(pending).toBeInViewport();
  await page.screenshot({ path: resolve(renders, `create-gated-normal-short-mobile.png`), fullPage: true });
  releaseCreate();
  await expect.poll(async () => page.locator('.turn-card').count()).toBe(0);
  releaseAck(); releaseSidebar();
  await expect(pending).toHaveCount(0);
  await expect(page.locator('.user-bubble')).toContainText(['A synthetic question to paint right away']);
  await expect(page.getByLabel('Message Kat')).toHaveValue('A new draft, not the sent text');
});

test('an established long thread brings the deliberately submitted bubble above the short-mobile composer', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 390, height: 560 });
  await signIn(page, 'reader-instant-long-normal');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'Recent conversations' })
    .getByRole('button', { name: /A long synthetic conversation/ }).click();
  await expect(page.locator('.turn-card')).toHaveCount(8);
  let releaseAck!: () => void;
  const ackGate = new Promise<void>(resolve => { releaseAck = resolve; });
  await page.route('**/api/conversations/*/turns', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const response = await route.fetch(); await ackGate; await route.fulfill({ response });
  });
  await page.evaluate(() => window.scrollTo(0, 0));
  await send(page, 'Latest visible local question', 'Enter');
  await expect(page.getByLabel('Message Kat')).toHaveValue('');
  await expect(page.locator('.local-pending')).toBeInViewport();
  const geometry = await page.evaluate(() => ({
    bubble: document.querySelector('.local-pending .user-bubble')!.getBoundingClientRect().bottom,
    composer: document.querySelector('.composer-wrap')!.getBoundingClientRect().top,
  }));
  expect(geometry.bubble).toBeLessThanOrEqual(geometry.composer);
  await expectUnobscuredBubble(page, '.local-pending .user-bubble');
  await page.screenshot({ path: resolve(renders, `long-gated-normal-short-mobile.png`), fullPage: true });
  releaseAck();
  await expect(page.locator('.local-pending')).toHaveCount(0);
  await expect(page.locator('.user-bubble').last()).toContainText('Latest visible local question');
});

test('five-second conversation creation cannot delay a visible send or a new editable draft', async ({ page }) => {
  test.setTimeout(70000);
  await signIn(page, 'reader-instant-normal');
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let arrived!: () => void;
  const request = new Promise<void>(resolve => { arrived = resolve; });
  let creates = 0;
  await page.route('**/api/conversations', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    creates++; arrived(); await gate; await route.continue();
  });
  const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
  await send(page, 'A first message while creation is blocked', 'Send');
  await request;
  const bubble = page.locator('.local-pending .user-bubble');
  await expect(bubble).toBeInViewport();
  await expectUnobscuredBubble(page, '.local-pending .user-bubble');
  await expect(bubble).toHaveText('A first message while creation is blocked');
  const input = page.getByLabel('Message Kat');
  await expect(input).toHaveValue('');
  await expect(input).toBeFocused();
  await input.fill('A newer unsent draft typed during creation');
  await input.press('Enter');
  await expect(input).toHaveValue('A newer unsent draft typed during creation');
  await expect(page.getByRole('button', { name: 'Send message' })).toBeDisabled();
  await page.waitForTimeout(5100); // The real synthetic HTTP gate stays closed for five seconds.
  await expectUnobscuredBubble(page, '.local-pending .user-bubble');
  await expect(input).toHaveValue('A newer unsent draft typed during creation');
  expect(creates).toBe(1);
  release();
  expect((await ack).status()).toBe(202);
  await expect(page.locator('.turn-card')).toHaveCount(1);
  await expect(input).toHaveValue('A newer unsent draft typed during creation');
});

for (const delay of ['turn-before-admission', 'turn-ACK-after-commit', 'provider-rejection', 'sidebar-refresh'] as const) {
  test(`five-second ${delay} keeps local feedback and a newer draft independent`, async ({ page }) => {
    test.setTimeout(70000);
    await signIn(page, 'reader-instant-normal');
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let arrived!: () => void;
    const request = new Promise<void>(resolve => { arrived = resolve; });
    let attempts = 0;
    if (delay === 'sidebar-refresh') {
      await page.route('**/api/conversations?offset=0', async route => {
        arrived(); await gate; await route.continue();
      }, { times: 1 });
    } else {
      await page.route('**/api/conversations/*/turns', async route => {
        if (route.request().method() !== 'POST') { await route.continue(); return; }
        attempts++; arrived();
        if (delay === 'turn-ACK-after-commit') {
          const response = await route.fetch(); await gate; await route.fulfill({ response });
        } else {
          await gate;
          if (delay === 'provider-rejection') await route.fulfill({ status: 409, contentType: 'application/json',
            body: '{"error":"fixed_model_unavailable"}' });
          else await route.continue();
        }
      });
    }
    const ack = delay === 'sidebar-refresh' ? page.waitForResponse(response =>
      response.request().method() === 'POST' && /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname)) : null;
    await send(page, `Synthetic question held by ${delay}`, 'Enter');
    await request;
    const input = page.getByLabel('Message Kat');
    if (delay === 'sidebar-refresh') expect((await ack!).status()).toBe(202);
    else {
      await expect(page.locator('.local-pending .user-bubble')).toHaveText(`Synthetic question held by ${delay}`);
      await expectUnobscuredBubble(page, '.local-pending .user-bubble');
    }
    await expect(input).toHaveValue('');
    await expect(input).toBeFocused();
    await input.fill('Separate draft during a blocked background request');
    await expect(input).toHaveValue('Separate draft during a blocked background request');
    if (delay === 'sidebar-refresh')
      await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled(); // The answer already finished.
    else await expect(page.getByRole('button', { name: 'Send message' })).toBeDisabled();
    await page.waitForTimeout(5100);
    await expect(input).toHaveValue('Separate draft during a blocked background request');
    if (delay !== 'sidebar-refresh') {
      await expectUnobscuredBubble(page, '.local-pending .user-bubble');
      expect(attempts).toBe(1);
    }
    release();
    if (delay === 'provider-rejection') {
      await expect(page.locator('.local-pending')).toContainText('cannot use the selected model');
      await expect(page.getByRole('button', { name: 'Retry this message' })).toBeVisible();
      await expect(page.locator('.turn-card')).toHaveCount(0);
    } else {
      await expect(page.locator('.turn-card')).toHaveCount(1, { timeout: 20000 });
      await expect(page.locator('.local-pending')).toHaveCount(0);
    }
    await expect(input).toHaveValue('Separate draft during a blocked background request');
  });
}

test('a late durable ACK does not pull a reader away from earlier messages', async ({ page }) => {
  test.setTimeout(60000);
  await page.setViewportSize({ width: 390, height: 560 });
  await signIn(page, 'reader-instant-ack-reader');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'Recent conversations' })
    .getByRole('button', { name: /A long synthetic conversation/ }).click();
  await expect(page.locator('.turn-card')).toHaveCount(8);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let committed!: () => void;
  const saved = new Promise<void>(resolve => { committed = resolve; });
  await page.route('**/api/conversations/*/turns', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const response = await route.fetch(); committed(); await gate; await route.fulfill({ response });
  });
  const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
  await send(page, 'A deliberately submitted message before reading older text', 'Enter');
  await saved;
  await expectUnobscuredBubble(page, '.local-pending .user-bubble');
  const input = page.getByLabel('Message Kat');
  await input.fill('Another unsent thought');
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  release();
  expect((await ack).status()).toBe(202);
  await expect(page.locator('.local-pending')).toHaveCount(0);
  await expect(page.locator('.turn-card')).toHaveCount(9);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await expect(input).toHaveValue('Another unsent thought');
});

for (const outcome of ['complete', 'delayed failure'] as const) {
  test(`five-second post-ACK ${outcome} keeps draft, reading and navigation usable`, async ({ page }) => {
    test.setTimeout(70000);
    const long = outcome === 'complete';
    await page.setViewportSize({ width: 390, height: 560 });
    await signIn(page, long ? 'reader-instant-pending-long' : 'reader-instant-error');
    if (long) {
      await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('navigation', { name: 'Recent conversations' })
        .getByRole('button', { name: /A long synthetic conversation/ }).click();
      await expect(page.locator('.turn-card')).toHaveCount(8);
    }
    let sends = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && /\/api\/conversations\/[^/]+\/turns$/.test(new URL(request.url()).pathname)) sends++;
    });
    const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
    await send(page, `Synthetic delayed response while drafting ${outcome}`, 'Enter');
    expect((await ack).status()).toBe(202); // Actual durable commit, not local projection.
    await expect(page.locator('.turn-card .user-bubble').last()).toBeVisible();
    await expectUnobscuredBubble(page, '.turn-card .user-bubble');
    const input = page.getByLabel('Message Kat');
    await expect(input).toHaveValue('');
    await expect(input).toBeFocused();
    await input.fill('This distinct draft must survive the answer');
    await input.press('Enter');
    await expect(input).toHaveValue('This distinct draft must survive the answer');
    await expect(page.getByRole('button', { name: 'Send message' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Stop response' })).toBeVisible();
    if (long) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await expect.poll(async () => page.evaluate(() => window.scrollY)).toBe(0);
      await page.evaluate(() => window.scrollBy(0, 220));
      await expect.poll(async () => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    }
    await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Settings' }).click();
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
    await page.getByRole('button', { name: 'Back to workspace' }).click();
    await expect(input).toHaveValue('This distinct draft must survive the answer');
    await page.waitForTimeout(5100); // Provider holds response for eight seconds after commit.
    await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'open');
    await expect(input).toHaveValue('This distinct draft must survive the answer');
    expect(sends).toBe(1);
    const turn = page.locator('.turn-card').last();
    await expect(turn).toHaveAttribute('data-kat-status', outcome === 'complete' ? 'complete' : 'error',
      { timeout: 20000 });
    await expect(input).toHaveValue('This distinct draft must survive the answer');
    expect(sends).toBe(1);
    if (outcome === 'delayed failure')
      await expect(turn.getByRole('button', { name: 'Try again as a new message with current selection' })).toBeVisible();
  });
}

test('a failed conversation create retains the same message for retry without a second send', async ({ page }) => {
  await signIn(page, 'reader-instant-error');
  let calls = 0;
  await page.route('**/api/conversations', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    calls++;
    if (calls === 1) await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"unavailable"}' });
    else await route.continue();
  });
  await send(page, 'Do not lose this message on failed create', 'Send');
  await expect(page.locator('.local-pending')).toContainText('Do not lose this message on failed create');
  await expect(page.locator('.local-pending')).toContainText('not confirmed');
  await expect(page.getByLabel('Message Kat')).toHaveValue('');
  const id = await page.locator('.local-pending').getAttribute('data-kat-pending-turn-id');
  await page.getByRole('button', { name: /Retry/ }).last().click();
  await expect(page.locator(`.turn-card[data-kat-turn-id="${id}"]`)).toHaveCount(1);
  expect(calls).toBe(2);
});

test('a committed creation with lost response retries the same conversation and turn without a ghost', async ({ page }) => {
  await signIn(page, 'reader-instant-normal');
  const created: string[] = [];
  await page.route('**/api/conversations', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    created.push(route.request().postDataJSON().id);
    if (created.length === 1) { await route.fetch(); await route.abort('failed'); }
    else await route.continue();
  });
  await send(page, 'A committed conversation with a missing response', 'Enter');
  await expect(page.locator('.local-pending')).toContainText('not confirmed');
  await page.getByLabel('Message Kat').fill('Keep later unsent typing');
  await page.getByRole('button', { name: 'Retry this message' }).click();
  await expect(page.locator('.local-pending')).toHaveCount(0);
  await expect(page.locator('.turn-card')).toHaveCount(1);
  await expect(page.getByLabel('Message Kat')).toHaveValue('Keep later unsent typing');
  expect(created).toHaveLength(2);
  expect(created[0]).toBe(created[1]);
});

test('release maintenance preserves the pending identity and newer draft without automatic resend', async ({ page }) => {
  await signIn(page, 'reader-instant-normal');
  const ids: string[] = [];
  await page.route('**/api/conversations/*/turns', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    ids.push(route.request().postDataJSON().id);
    if (ids.length === 1) await route.fulfill({ status: 503, contentType: 'application/json',
      body: '{"error":"release_maintenance"}' });
    else await route.continue();
  });
  await send(page, 'Keep this message through the update', 'Send');
  await expect(page.locator('.local-pending')).toContainText('Kat is updating');
  await page.getByLabel('Message Kat').fill('A newer unsent draft');
  expect(ids).toHaveLength(1);
  await page.getByRole('button', { name: 'Retry this message' }).click();
  await expect(page.locator('.local-pending')).toHaveCount(0);
  await expect(page.getByLabel('Message Kat')).toHaveValue('A newer unsent draft');
  expect(ids).toHaveLength(2);
  expect(ids[0]).toBe(ids[1]);
  await expect(page.locator('.turn-card')).toHaveCount(1);
});

test('a rejected plan keeps the user bubble and reuses the same identity after retry', async ({ page }) => {
  await signIn(page, 'reader-instant-normal');
  const ids: string[] = [];
  await page.route('**/api/conversations/*/turns', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    ids.push(route.request().postDataJSON().id);
    if (ids.length === 1) await route.fulfill({ status: 409, contentType: 'application/json',
      body: '{"error":"fixed_model_unavailable"}' });
    else await route.continue();
  });
  await send(page, 'Keep my rejected message visible', 'Send');
  await expect(page.locator('.local-pending')).toContainText('cannot use the selected model');
  await expect(page.getByLabel('Message Kat')).toHaveValue('');
  await page.getByRole('button', { name: 'Retry this message' }).click();
  await expect(page.locator('.local-pending')).toHaveCount(0);
  await expect(page.locator('.user-bubble')).toContainText(['Keep my rejected message visible']);
  expect(ids).toHaveLength(2);
  expect(ids[1]).toBe(ids[0]);
});

test('an acknowledged write with lost HTTP response reconciles by same ID and never copies into a new draft', async ({ page }) => {
  await signIn(page, 'reader-instant-normal');
  const ids: string[] = [];
  await page.route('**/api/conversations/*/turns', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    ids.push(route.request().postDataJSON().id);
    if (ids.length === 1) { await route.fetch(); await route.abort('failed'); }
    else await route.continue();
  });
  await send(page, 'Synthetic hello. Reply in one sentence.', 'Send');
  await expect(page.locator('.local-pending')).toContainText('not confirmed');
  await page.getByLabel('Message Kat').fill('A distinct newer draft');
  await page.getByRole('button', { name: 'Retry this message' }).click();
  await expect(page.locator('.local-pending')).toHaveCount(0);
  await expect(page.getByLabel('Message Kat')).toHaveValue('A distinct newer draft');
  expect(ids).toHaveLength(2);
  expect(ids[0]).toBe(ids[1]);
  await expect(page.locator('.turn-card')).toHaveCount(1);
});

test('a new conversation can send while an abandoned archived ACK is still delayed', async ({ page }) => {
  await signIn(page, 'reader-instant-normal');
  let release!: () => void;
  const oldAck = new Promise<void>(resolve => { release = resolve; });
  let oldCommitted!: () => void;
  const committed = new Promise<void>(resolve => { oldCommitted = resolve; });
  let sends = 0;
  await page.route('**/api/conversations/*/turns', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    sends++;
    if (sends === 1) { const response = await route.fetch(); oldCommitted(); await oldAck; await route.fulfill({ response }); }
    else await route.continue();
  });
  await send(page, 'A first, committed message with a delayed ACK', 'Enter');
  await committed;
  await page.getByRole('button', { name: 'New conversation' }).first().click();
  await send(page, 'A different new conversation must still send', 'Enter');
  await expect(page.locator('.turn-card')).toHaveCount(1, { timeout: 30000 });
  await expect(page.locator('.user-bubble')).toContainText(['A different new conversation must still send']);
  release();
  await expect(page.locator('.turn-card')).toHaveCount(1);
  await expect(page.locator('.local-pending')).toHaveCount(0);
  expect(sends).toBe(2);
});

test('a different signed-in owner can send while the old owner ACK remains delayed', async ({ page }) => {
  await signIn(page, 'reader-instant-normal');
  let release!: () => void;
  const oldAck = new Promise<void>(resolve => { release = resolve; });
  let oldCommitted!: () => void;
  const committed = new Promise<void>(resolve => { oldCommitted = resolve; });
  let sends = 0;
  await page.route('**/api/conversations/*/turns', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    sends++;
    if (sends === 1) { const response = await route.fetch(); oldCommitted(); await oldAck; await route.fulfill({ response }); }
    else await route.continue();
  });
  await send(page, 'Old owner message with a delayed ACK', 'Enter');
  await committed;
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByLabel('Username')).toBeVisible();
  await signIn(page, 'reader-instant-error');
  await send(page, 'New owner message is independent', 'Enter');
  await expect(page.locator('.turn-card')).toHaveCount(1, { timeout: 30000 });
  await expect(page.locator('.user-bubble')).toContainText(['New owner message is independent']);
  release();
  await expect(page.locator('.turn-card')).toHaveCount(1);
  await expect(page.locator('.local-pending')).toHaveCount(0);
  expect(sends).toBe(2);
});

test('an archived failed response offers an explicit new attempt without replacing a later draft', async ({ page }) => {
  await signIn(page, 'reader-instant-normal');
  await send(page, 'SyntheticTransportFailureFixture', 'Send');
  const turns = page.locator('.turn-card');
  await expect(turns.first()).toHaveAttribute('data-kat-status', 'error', { timeout: 30000 });
  await expect(page.locator('.local-pending')).toHaveCount(0);
  await page.getByLabel('Message Kat').fill('Keep this different draft');
  await turns.first().getByRole('button', { name: 'Try again as a new message with current selection' }).click();
  await expect(turns).toHaveCount(2);
  await expect(turns.nth(0)).toHaveAttribute('data-kat-status', 'error');
  expect(await turns.first().getAttribute('data-kat-turn-id')).not.toBe(await turns.last().getAttribute('data-kat-turn-id'));
  await expect(page.getByLabel('Message Kat')).toHaveValue('Keep this different draft');
});

test('disconnected send remains beside the bubble with a reconnect action', async ({ page }) => {
  await signIn(page, 'reader-instant-disconnected');
  await send(page, 'Keep this question even before connecting', 'Enter');
  await expect(page.locator('.local-pending')).toContainText('Keep this question even before connecting');
  await expect(page.locator('.local-pending')).toContainText('Connect');
  await expect(page.getByLabel('Message Kat')).toHaveValue('');
  await expect(page.getByRole('button', { name: /Connect ChatGPT/ }).first()).toBeVisible();
});
