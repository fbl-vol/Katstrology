import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/conversation-browsing');
test.beforeAll(() => mkdirSync(renders, { recursive: true }));

for (const view of [
  { name: 'mobile', owner: 'reader-browse-mobile', size: { width: 390, height: 844 } },
  { name: 'ultrawide', owner: 'reader-browse-wide', size: { width: 2560, height: 1080 } },
]) {
  test(`bounded conversation browsing keeps the draft and date groups on ${view.name}`, async ({ page }) => {
    test.setTimeout(85000);
    await page.setViewportSize(view.size);
    await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
    await page.goto('/');
    await page.getByLabel('Username').fill(view.owner);
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
    const session = await page.request.get('/api/session');
    expect(session.status()).toBe(200);
    const workspace = await session.json();
    expect(workspace.csrf).toBeTruthy();
    const navigation = page.getByRole('navigation', { name: 'Recent conversations' });
    await expect(page.locator('.recent').getByText('No conversations yet.')).toHaveCount(1);

    for (let index = 0; index < 25; index++) {
      const status = await page.evaluate(async ({ index, csrf }) => {
        const response = await fetch('/api/conversations', {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Kat-CSRF': csrf },
          body: JSON.stringify({ id: `browse-${String(index).padStart(2, '0')}`,
            title: `Synthetic browsing topic ${index}`, people: [] }),
        });
        return { status: response.status, result: await response.json() };
      }, { index, csrf: workspace.csrf });
      expect(status.status, JSON.stringify(status.result)).toBe(201);
    }
    const olderMonth = new Date(Date.UTC(2024, 2, 18)).toISOString();
    const oldestMonth = new Date(Date.UTC(2023, 10, 18)).toISOString();
    await page.route('**/api/conversations?offset=*', async route => {
      const response = await route.fetch();
      const list = await response.json();
      const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
      list.conversations.forEach((row: { created_at: string; preview?: string }, index: number) => {
        if (offset === 0 && index >= 15) row.created_at = olderMonth;
        if (offset === 20) row.created_at = oldestMonth;
        if (index === 0 && offset === 0) row.preview = 'Bounded current excerpt for this synthetic discussion';
      });
      await route.fulfill({ response, json: list });
    });
    await page.reload();
    await page.getByLabel('Message Kat').fill('An unsent browsing draft');
    if (view.name === 'mobile') {
      await page.getByRole('button', { name: 'Open navigation' }).click();
      await expect(page.locator('.sidebar')).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)');
    }
    await expect(navigation.getByRole('button', { name: /Synthetic browsing topic/ })).toHaveCount(20);
    await expect(navigation.locator('.recent-month')).toHaveCount(2);
    await expect(navigation.getByText('You: Bounded current excerpt for this synthetic discussion')).toBeVisible();
    await page.screenshot({ path: resolve(renders, `${view.name}-page-one.png`) });
    await navigation.locator('.recent-month').last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `${view.name}-older-month.png`) });
    await navigation.getByRole('button', { name: 'Load older conversations' }).click();
    await expect(navigation.getByRole('button', { name: /Synthetic browsing topic/ })).toHaveCount(25);
    await expect(navigation.locator('.recent-month')).toHaveCount(3);
    await navigation.getByLabel('Search conversations').fill('No matching title or indexed text');
    await navigation.getByRole('button', { name: 'Search', exact: true }).click();
    await expect(navigation.getByText('No matches in current indexed conversations.')).toBeVisible();
    await page.screenshot({ path: resolve(renders, `${view.name}-no-match.png`) });
    await navigation.getByLabel('Search conversations').fill('');
    await navigation.getByRole('button', { name: 'Search', exact: true }).click();
    await navigation.getByRole('button', { name: /Synthetic browsing topic 24/ }).click();
    await expect(page.getByRole('region', { name: 'Conversation' })).toBeVisible();
    await expect(page.getByLabel('Message Kat')).toHaveValue('An unsent browsing draft');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(view.size.width + 1);
  });
}
