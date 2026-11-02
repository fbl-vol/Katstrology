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

for (const viewport of [{ name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 }]) {
  test(`person picker opens with current choice before its first visible frame on ${viewport.name}`, async ({ page }) => {
    await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1'
      ? route.continue() : route.abort());
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-newchat-normal');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    // Observe the actual native showModal boundary, without changing its result or delaying interaction.
    await page.evaluate(() => {
      const nativeShow = HTMLDialogElement.prototype.showModal;
      const opened: boolean[] = [];
      (window as typeof window & { pickerOpenedChecked?: boolean[] }).pickerOpenedChecked = opened;
      HTMLDialogElement.prototype.showModal = function() {
        nativeShow.call(this);
        if (this.getAttribute('aria-labelledby') === 'scope-title') {
          const person = [...this.querySelectorAll<HTMLLabelElement>('.picker-option')]
            .find(label => label.textContent?.includes('Synthetic transit reader'))!;
          opened.push(person.querySelector('input')!.checked);
        }
      };
    });
    const add = page.getByRole('button', { name: '＋ Add person' });
    const picker = page.getByRole('dialog', { name: 'Who’s this about?' });
    const checkbox = picker.getByRole('checkbox', { name: 'Synthetic transit reader' });
    const chip = page.getByRole('button', { name: 'Remove Synthetic transit reader from new turn' });
    const firstFrame = async () => page.evaluate(() => (window as typeof window & { pickerOpenedChecked?: boolean[] }).pickerOpenedChecked?.at(-1));
    mkdirSync(renders, { recursive: true });

    await add.click();
    expect(await firstFrame()).toBe(false);
    await checkbox.check();
    await picker.getByRole('button', { name: 'Use selection' }).click();
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(chip).toHaveCount(0);

    await add.click();
    expect(await firstFrame()).toBe(false); // A cleared parent must not expose the previous local check.
    await expect(checkbox).not.toBeChecked();
    await page.screenshot({ path: resolve(renders, `picker-reopened-${viewport.name}.png`) });
    await checkbox.check();
    await picker.getByRole('button', { name: 'Use selection' }).click();
    await expect(chip).toBeVisible();

    await add.click();
    expect(await firstFrame()).toBe(true);
    await checkbox.uncheck();
    await picker.getByRole('button', { name: 'Cancel' }).click();
    await expect(chip).toBeVisible(); // Cancel never applies the unsaved edit.
    await expect(add).toBeFocused();
    await page.screenshot({ path: resolve(renders, `picker-cancelled-${viewport.name}.png`) });
    await add.click();
    expect(await firstFrame()).toBe(true); // Reopening after Cancel restores the committed selection.
    await expect(checkbox).toBeChecked();
    await page.keyboard.press('Escape');
    await expect(chip).toBeVisible();
    await expect(add).toBeFocused();
  });
}
