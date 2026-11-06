import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/chat-scroll-renders');

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short-mobile', width: 390, height: 560 },
]) for (const theme of ['reading-room', 'blue-hour']) {
  test(`${viewport.name} ${theme}: one page scrollbar and uncapped draft`, async ({ page, context }) => {
    test.setTimeout(60000);
    mkdirSync(renders, { recursive: true });
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await context.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ?
      route.continue() : route.abort());
    await page.addInitScript(themeId => localStorage.setItem('kat.appearance.theme', themeId), theme);
    await page.goto('/');
    await page.getByLabel('Username').fill(`reader-chat-scroll-${viewport.name}-${theme}`);
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    const input = page.getByLabel('Message Kat');
    await input.fill('Synthetic draft scroll setup');
    const setupAck = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
    await page.getByRole('button', { name: 'Send message' }).click();
    expect((await setupAck).status()).toBe(202);
    await expect(page.getByRole('region', { name: 'Conversation', exact: true })).toBeVisible();
    await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'complete');
    const draft = ('A longer thought with two sentences and a careful question.\n').repeat(65);
    await input.fill(draft);
    await expect(input).toHaveValue(draft);
    const layout = await page.evaluate(() => {
      const input = document.querySelector<HTMLTextAreaElement>('#message')!;
      const dock = input.closest<HTMLElement>('.composer-wrap')!;
      const messages = dock.closest('.conversation')!.querySelector<HTMLElement>('.messages')!;
      return {
        inputHeight: input.clientHeight, contentHeight: input.scrollHeight, inputOverflow: getComputedStyle(input).overflowY,
        dockFlow: dock.classList.contains('composer-in-flow'), dockHeight: dock.offsetHeight,
        dockOverflow: getComputedStyle(dock).overflowY,
        messageOverflow: getComputedStyle(messages).overflowY,
        readerOverflow: getComputedStyle(dock.closest('.reader-content')!).overflowY,
        pageHeight: document.documentElement.scrollHeight, pageWidth: document.documentElement.scrollWidth,
      };
    });
    expect(layout.contentHeight).toBeLessThanOrEqual(layout.inputHeight + 1);
    expect(layout.inputOverflow).toBe('hidden');
    expect(layout.dockOverflow).toBe('visible');
    expect(layout.messageOverflow).toBe('visible');
    expect(layout.readerOverflow).toBe('visible');
    expect(layout.pageWidth).toBeLessThanOrEqual(viewport.width);
    expect(layout.pageHeight).toBeGreaterThan(viewport.height);
    expect(layout.dockFlow).toBe(layout.dockHeight > viewport.height - 120);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await page.screenshot({ path: resolve(renders, `${viewport.name}-${theme}-long.png`) });
    await page.mouse.move(viewport.width / 2, viewport.height / 2);
    const beforeWheel = await page.evaluate(() => window.scrollY);
    await page.mouse.wheel(0, -280);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeLessThan(beforeWheel);
    await input.fill('A short question');
    await expect(input).toHaveValue('A short question');
    await expect(page.locator('.composer-wrap')).not.toHaveClass(/composer-in-flow/);
    await page.screenshot({ path: resolve(renders, `${viewport.name}-${theme}-compact.png`) });
    // The synthetic fake-plan fixture is the only network destination; never call the live provider.
    if (process.env.KAT_BROWSER_FAKE_PLAN === '1') {
      const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
        /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
      await input.press('Enter');
      expect((await ack).status()).toBe(202);
      await expect(page.locator('.user-bubble').last()).toContainText('A short question');
      await expect(input).toHaveValue('');
      await input.fill('Unsent second question');
      await input.evaluate(element => element.blur()); // Reading earlier turns after leaving the composer.
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.locator('.conversation-toolbar').scrollIntoViewIfNeeded();
      const before = await page.evaluate(() => window.scrollY);
      await page.locator('.conversation-toolbar').click();
      expect(await page.evaluate(() => window.scrollY)).toBe(before);
      await expect(input).toHaveValue('Unsent second question');
    }
  });
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1024 },
                        { name: 'mobile', width: 390, height: 844 }]) {
  test(`${viewport.name}: long archived turn scrolls the document, survives reload and keeps a new draft`, async ({ page, context }) => {
    test.skip(process.env.KAT_BROWSER_FAKE_PLAN !== '1', 'Requires the isolated fake-plan fixture');
    mkdirSync(renders, { recursive: true });
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await context.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ?
      route.continue() : route.abort());
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-chat');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    const message = 'Synthetic archive line to read on the page.\n'.repeat(45);
    await page.getByLabel('Message Kat').fill(message);
    const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
    await page.getByRole('button', { name: 'Send message' }).click();
    expect((await ack).status()).toBe(202);
    await expect(page.locator('.turn-card').first().locator('.user-bubble')).toHaveText(message);
    await page.getByLabel('Message Kat').fill('Draft while reading archived reply');
    const layout = await page.evaluate(() => ({ page: document.documentElement.scrollHeight,
      messages: document.querySelector<HTMLElement>('.messages')!.scrollTop,
      overflow: getComputedStyle(document.querySelector('.messages')!).overflowY }));
    expect(layout.page).toBeGreaterThan(viewport.height);
    expect(layout.messages).toBe(0);
    expect(layout.overflow).toBe('visible');
    await page.locator('.user-bubble').first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `thread-${viewport.name}.png`) });
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await expect(page.getByLabel('Message Kat')).toHaveValue('Draft while reading archived reply');
    await page.reload();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry').getByRole('button').first().click();
    await expect(page.locator('.turn-card').first().locator('.user-bubble')).toHaveText(message);
  });
}
