import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';

async function login(page: Page, owner: string) {
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByLabel('Message Kat')).toBeVisible();
}
async function visibility(page: Page, value: 'hidden' | 'visible') {
  await page.evaluate(value => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value });
    document.dispatchEvent(new Event('visibilitychange'));
  }, value);
}

test('live page resume preserves older reading, loaded pages and unsent text; reload is explicitly different', async ({ page }) => {
  await login(page, 'reader-paged-normal');
  await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button', { name: /A paged synthetic conversation/ }).click();
  await page.getByRole('button', { name: 'Load more saved messages' }).click();
  await expect(page.locator('.turn-card')).toHaveCount(21);
  await page.getByLabel('Message Kat').fill('An unsent live-page draft, not persisted');
  await page.getByLabel('Message Kat').blur();
  await page.locator('.turn-card').nth(2).evaluate(element => element.scrollIntoView({ block: 'center' }));
  const position = await page.evaluate(() => scrollY);
  let writes = 0;
  page.on('request', request => { if (request.method() === 'POST') writes++; });
  await visibility(page, 'hidden');
  const refreshed = page.waitForResponse(response => response.url().includes('/turns?offset=20'));
  await visibility(page, 'visible'); await refreshed;
  await expect(page.locator('.turn-card')).toHaveCount(21);
  await expect(page.getByLabel('Message Kat')).toHaveValue('An unsent live-page draft, not persisted');
  expect(await page.evaluate(() => scrollY)).toBeCloseTo(position, 0);
  await page.evaluate(() => window.visualViewport!.dispatchEvent(new Event('resize')));
  expect(await page.evaluate(() => scrollY)).toBeCloseTo(position, 0);
  expect(writes).toBe(0);
  await page.reload();
  await expect(page.getByLabel('Message Kat')).toHaveValue('');
  await expect(page.locator('.turn-card')).toHaveCount(0);
  expect(await page.evaluate(() => Object.keys(localStorage).some(key => /draft|conversation|birth/i.test(key)))).toBe(false);
});

test('visual viewport keyboard geometry keeps Send reachable without a second scrolling editor', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 560 });
  await login(page, 'reader-mobile');
  await page.getByLabel('Message Kat').fill('An unsent keyboard draft');
  await page.getByLabel('Message Kat').evaluate((element: HTMLTextAreaElement) => element.setSelectionRange(3, 3));
  await page.evaluate(() => {
    Object.defineProperty(visualViewport, 'height', { configurable: true, value: 360 });
    Object.defineProperty(visualViewport, 'offsetTop', { configurable: true, value: 0 });
    visualViewport!.dispatchEvent(new Event('resize'));
  });
  await expect(page.locator('.composer-wrap')).toHaveCSS('bottom', '200px');
  const send = await page.getByRole('button', { name: 'Send message' }).boundingBox();
  expect(send!.y).toBeGreaterThanOrEqual(0);
  expect(send!.y + send!.height).toBeLessThanOrEqual(360);
  await expect(page.getByLabel('Message Kat')).toHaveCSS('overflow-y', 'hidden');
  expect(await page.getByLabel('Message Kat').evaluate((element: HTMLTextAreaElement) => element.selectionStart)).toBe(3);
  mkdirSync('../.local/phone-first/continuity/renders', { recursive: true });
  await page.screenshot({ path: '../.local/phone-first/continuity/renders/visual-viewport-inset.png' });
  await page.evaluate(() => {
    Reflect.deleteProperty(visualViewport!, 'height'); Reflect.deleteProperty(visualViewport!, 'offsetTop');
    visualViewport!.dispatchEvent(new Event('resize'));
  });
  await expect(page.locator('.composer-wrap')).toHaveCSS('bottom', '0px');
  await expect(page.getByLabel('Message Kat')).toHaveValue('An unsent keyboard draft');
});

test('resume never retries an uncertain acknowledged send or overwrites the next draft', async ({ page }) => {
  await login(page, 'reader-instant-normal');
  const ids: string[] = [];
  await page.route('**/api/conversations/*/turns', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    ids.push(route.request().postDataJSON().id);
    if (ids.length === 1) { await route.fetch(); await route.abort('failed'); }
    else await route.continue();
  });
  await page.getByLabel('Message Kat').fill('Synthetic hello. Reply in one sentence.');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.locator('.local-pending')).toContainText('not confirmed');
  await page.getByLabel('Message Kat').fill('A distinct newer unsent draft');
  await visibility(page, 'hidden');
  const session = page.waitForResponse('**/api/session');
  await visibility(page, 'visible'); await session;
  await expect(page.locator('.local-pending')).toContainText('not confirmed');
  expect(ids).toHaveLength(1);
  await expect(page.getByLabel('Message Kat')).toHaveValue('A distinct newer unsent draft');
  await page.getByRole('button', { name: 'Retry this message' }).click();
  await expect(page.locator('.local-pending')).toHaveCount(0);
  expect(ids).toHaveLength(2); expect(ids[1]).toBe(ids[0]);
  await expect(page.locator('.turn-card')).toHaveCount(1);
});

test('resume reads an interrupted reply after a lost stream without new inference', async ({ page }) => {
  await page.addInitScript(() => {
    const Native = EventSource;
    const sources: EventSource[] = [];
    Object.assign(window, { syntheticSources: sources });
    window.EventSource = class extends Native { constructor(url: string | URL, options?: EventSourceInit) { super(url, options); sources.push(this); } };
  });
  await login(page, 'reader-instant-normal');
  await page.getByLabel('Message Kat').fill('Synthetic slow cancel');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.locator('.assistant-answer')).toContainText('Synthetic committed prefix', { timeout: 15000 });
  await page.evaluate(() => (window as unknown as { syntheticSources: EventSource[] }).syntheticSources.forEach(source => source.close()));
  const cancelled = page.waitForResponse('**/cancel');
  await page.getByRole('button', { name: 'Stop response' }).click(); await cancelled;
  let writes = 0;
  page.on('request', request => { if (request.method() === 'POST') writes++; });
  await visibility(page, 'hidden');
  await visibility(page, 'visible');
  await expect(page.locator('.turn-card')).toHaveAttribute('data-kat-status', 'interrupted', { timeout: 15000 });
  await expect(page.locator('.assistant-answer')).toContainText('Synthetic committed prefix');
  await expect(page.locator('.turn-warning')).toContainText('committed prefix is preserved');
  expect(writes).toBe(0);
});

test('resume clears mounted private state after session expiry instead of reviving it', async ({ page }) => {
  await login(page, 'reader-shell');
  await page.getByLabel('Message Kat').fill('Old session private draft');
  await page.route('**/api/session', route => route.fulfill({ status: 401, json: { error: 'unauthorized' } }));
  await visibility(page, 'hidden'); await visibility(page, 'visible');
  await expect(page.getByLabel('Username')).toBeVisible();
  await expect(page.getByLabel('Message Kat')).toHaveCount(0);
  await expect(page.locator('.account')).toHaveCount(0);
});
