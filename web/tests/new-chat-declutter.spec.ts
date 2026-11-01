import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/application-performance');

test('normal new chat sends with selected chart after a failed first creation', async ({ page }) => {
    test.setTimeout(70000);
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-newchat-normal');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await expect(page.getByRole('region', { name: 'New conversation' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Start conversation with this selection' })).toHaveCount(0);
    await expect(page.getByText('About the archive')).toHaveCount(0);
    mkdirSync(renders, { recursive: true });
    for (const view of [{ name: 'desktop', width: 1440, height: 1024 },
      { name: 'mobile', width: 390, height: 844 }, { name: 'short-mobile', width: 390, height: 560 },
      { name: 'ultrawide', width: 2560, height: 1080 }]) {
      await page.setViewportSize({ width: view.width, height: view.height });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(view.width + 1);
      await page.screenshot({ path: resolve(renders, `new-chat-normal-${view.name}.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 1440, height: 1024 });
    await page.getByRole('button', { name: '＋ Add person' }).click();
    const picker = page.getByRole('dialog', { name: 'Who’s this about?' });
    await picker.getByRole('checkbox', { name: 'Synthetic transit reader' }).check();
    await picker.getByRole('button', { name: 'Use selection' }).click();
    await expect(page.getByRole('button', { name: 'Remove Synthetic transit reader from new turn' })).toBeVisible();

    const draft = 'Synthetic selected-chart first message';
    await page.getByLabel('Message Kat').fill(draft);
    await page.route('**/api/conversations', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"synthetic unavailable"}' });
    }, { times: 1 });
    await page.getByLabel('Message Kat').press('Enter');
    await expect(page.getByLabel('Message Kat')).toHaveValue('');
    await expect(page.locator('.local-pending')).toContainText(draft);
    await expect(page.getByRole('region', { name: 'New conversation' })).toBeVisible();
    await expect(page.locator('.turn-card')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Remove Synthetic transit reader from new turn' })).toBeVisible();

    const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
    await page.getByLabel('Message Kat').press('Enter');
    await expect(page.locator('.turn-card')).toHaveCount(0); // Repeated Enter cannot start another send.
    await page.getByRole('button', { name: 'Retry this message' }).click();
    expect((await ack).status()).toBe(202);
    await expect(page.getByRole('region', { name: 'Conversation', exact: true })).toBeVisible();
    await expect(page.getByLabel('Message Kat')).toHaveValue('');
    await expect(page.getByRole('button', { name: 'Start conversation with this selection' })).toHaveCount(0);
    await expect(page.getByText('About the archive')).toHaveCount(0);
    const selected = await page.evaluate(async () => {
      const { conversations } = await fetch('/api/conversations').then(response => response.json());
      const { turns } = await fetch(`/api/conversations/${conversations[0].id}/turns?offset=0`)
        .then(response => response.json());
      return turns[0].selected_people;
    });
    expect(selected).toHaveLength(1);
    expect(selected[0].person_id).toBe('transit-person');
    expect(selected[0].chart_id).toBeTruthy();

    await page.locator('button.new-chat').click();
    await page.getByRole('button', { name: '＋ Add person' }).click();
    const nextPicker = page.getByRole('dialog', { name: 'Who’s this about?' });
    await nextPicker.getByRole('checkbox', { name: 'Synthetic transit reader' }).check();
    await nextPicker.getByRole('button', { name: 'Use selection' }).click();
    await expect(page.getByRole('button', { name: 'Remove Synthetic transit reader from new turn' })).toBeVisible();
    await page.getByLabel('Message Kat').fill('Synthetic selected-chart click send');
    await expect(page.getByRole('button', { name: 'Remove Synthetic transit reader from new turn' })).toBeVisible();
    const clickAck = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
    await page.getByRole('button', { name: 'Send message' }).click();
    expect((await clickAck).status()).toBe(202);
    await expect(page.getByLabel('Message Kat')).toHaveValue('');
    const second = await page.evaluate(async () => {
      const { conversations } = await fetch('/api/conversations').then(response => response.json());
      const { turns } = await fetch(`/api/conversations/${conversations[0].id}/turns?offset=0`)
        .then(response => response.json());
      return { count: conversations.length, selected: turns[0].selected_people };
    });
    expect(second.count).toBe(2);
    expect(second.selected[0].chart_id).toBe(selected[0].chart_id);
});
