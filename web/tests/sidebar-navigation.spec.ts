import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/application-performance');

async function navigation(page: Page, mobile: boolean) {
  if (mobile && await page.locator('.mobile-menu').getAttribute('aria-expanded') === 'false')
    await page.getByRole('button', { name: 'Open navigation' }).click();
  return page.getByRole('complementary', { name: 'Workspace navigation' });
}

async function allConversations(page: Page, mobile: boolean, draft = '', screenshotPath?: string) {
  const sidebar = await navigation(page, mobile);
  const recent = sidebar.getByRole('navigation', { name: 'Recent conversations' });
  const all = recent.getByRole('button', { name: 'All conversations' });
  await expect(page.getByRole('button', { name: 'All conversations' })).toHaveCount(1);
  if (mobile) await expect.poll(async () => (await sidebar.boundingBox())?.x).toBeGreaterThanOrEqual(-1);
  const allBox = await all.boundingBox();
  const searchBox = await recent.getByRole('textbox', { name: 'Search conversations' }).boundingBox();
  expect(allBox!.y).toBeLessThan(searchBox!.y);
  if (screenshotPath) {
    await page.screenshot({ path: screenshotPath });
    if (mobile) {
      await sidebar.getByRole('button', { name: 'Sign out' }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: screenshotPath.replace(/\.png$/, '-footer.png') });
    }
  }
  await all.click();
  if (mobile) {
    await expect(page.locator('.mobile-menu')).toHaveAttribute('aria-expanded', 'true');
    await expect(recent.getByRole('heading', { name: 'RECENT CONVERSATIONS' })).toBeFocused();
    await expect(recent.locator('.recent-entry').first()).toBeVisible();
    if (screenshotPath) await page.screenshot({ path: screenshotPath.replace(/\.png$/, '-history-visible.png') });
  }
  await expect(page.locator('section.home[aria-label="New conversation"]')).toBeVisible();
  if (!mobile) await expect(page.getByLabel('Message Kat')).toHaveValue(draft);
  const history = page.locator('.sidebar nav[aria-label="Recent conversations"]');
  await expect(history.locator('.side-filter').filter({ hasText: 'For Synthetic transit reader' })).toHaveCount(0);
  await expect(history.locator('#thread-search')).toHaveValue('');
  await expect(history.locator('.recent-entry')).toHaveCount(2);
  if (mobile) {
    await sidebar.getByRole('button', { name: 'Close navigation' }).click();
    await expect(page.getByRole('button', { name: 'Open navigation' })).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByRole('button', { name: 'Open navigation' })).toBeFocused();
    await expect(page.getByLabel('Message Kat')).toHaveValue(draft);
  }
}

async function send(page: Page, text: string) {
  await page.getByLabel('Message Kat').fill(text);
  const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
  await page.getByRole('button', { name: 'Send message' }).click();
  expect((await ack).status()).toBe(202);
  await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'complete', { timeout: 30000 });
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1024 },
                        { name: 'mobile', width: 390, height: 844 }]) {
  for (const source of ['chart hub', 'advanced return', 'transits', 'settings'] as const) {
    test(`People navigation reveals the profile from ${source} on ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/');
      await page.getByLabel('Username').fill('reader-transit-desktop');
      await page.getByLabel('Password').fill('synthetic-browser-password');
      await page.getByRole('button', { name: 'Open workspace' }).click();
      await page.getByLabel('Message Kat').fill('An unsent question stays available after profile browsing.');
      if (source === 'settings') {
        const sidebar = await navigation(page, viewport.width < 700);
        await sidebar.getByRole('button', { name: 'Settings' }).click();
        await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
      } else {
        const sidebar = await navigation(page, viewport.width < 700);
        await sidebar.locator('.create-chart-nav').click();
        if (source !== 'chart hub') {
          await page.getByRole('region', { name: 'Create chart' }).getByRole('button',
            { name: source === 'transits' ? /^Transits/ : /^Solar return/ }).click();
          await expect(page.getByRole('region', { name: source === 'transits' ? 'Sky at a date' : 'Solar return chart' })).toBeVisible();
        }
      }
      const sidebar = await navigation(page, viewport.width < 700);
      await sidebar.getByRole('navigation', { name: 'People' })
        .getByRole('button', { name: /Synthetic transit reader/ }).click();
      await expect(page.getByRole('heading', { name: 'Synthetic transit reader' })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Synthetic transit reader' })).toBeFocused();
      await expect(page.locator('.chart-hub, .advanced-view, .transit-page')).toHaveCount(0);
      if (source === 'chart hub') {
        mkdirSync(renders, { recursive: true });
        await page.screenshot({ path: resolve(renders, `ux-profile-from-hub-${viewport.name}.png`) });
      }
      await navigation(page, viewport.width < 700);
      await page.getByRole('navigation', { name: 'Recent conversations' })
        .getByRole('button', { name: 'All conversations' }).click();
      if (viewport.width < 700) await sidebar.getByRole('button', { name: 'Close navigation' }).click();
      await expect(page.getByLabel('Message Kat')).toHaveValue('An unsent question stays available after profile browsing.');
    });
  }
}

for (const mobile of [false, true]) {
  test(`new-person dialog focuses Name and restores keyboard navigation on ${mobile ? 'mobile' : 'desktop'}`, async ({ page }) => {
    await page.setViewportSize({ width: mobile ? 390 : 1440, height: mobile ? 560 : 1024 });
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-people');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    const sidebar = await navigation(page, mobile);
    await sidebar.getByRole('button', { name: 'Add person' }).click();
    const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
    await expect(dialog.getByLabel('Name')).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    if (mobile) await expect(page.getByRole('button', { name: 'Open navigation' })).toBeFocused();
    else await expect(sidebar.getByRole('button', { name: 'Add person' })).toBeFocused();
  });
}

test('normal All conversations exits every route and restores unfiltered history', async ({ page }) => {
    test.setTimeout(105000);
    mkdirSync(renders, { recursive: true });
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-transit-mobile');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    const footer = page.locator('.sidebar .side-bottom');
    await expect(footer.getByRole('button', { name: 'Settings' })).toHaveCount(1);
    await expect(footer.getByRole('button', { name: 'Sign out' })).toHaveCount(1);
    await expect(footer.getByRole('button', { name: 'All conversations' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Sky at a date · optional' })).toHaveCount(0);
    await send(page, 'Synthetic unfiltered sidebar story');
    await page.locator('button.new-chat').click();
    await page.getByRole('button', { name: '＋ Add person' }).click();
    const picker = page.getByRole('dialog', { name: 'Who’s this about?' });
    await picker.getByRole('checkbox', { name: 'Synthetic transit reader' }).check();
    await picker.getByRole('button', { name: 'Use selection' }).click();
    await expect(page.getByRole('button', { name: 'Remove Synthetic transit reader from new turn' })).toBeVisible();
    await send(page, 'Synthetic person sidebar story');

    for (const view of [
      { name: 'desktop', width: 1440, height: 1024 },
      { name: 'mobile', width: 390, height: 844 },
      { name: 'short-mobile', width: 390, height: 560 },
      { name: 'ultrawide', width: 2560, height: 1080 },
    ]) {
      await page.setViewportSize({ width: view.width, height: view.height });
      const mobile = view.width < 700;
      let sidebar = await navigation(page, mobile);
      await sidebar.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
      await expect(page.getByRole('heading', { name: 'Synthetic transit reader' })).toBeVisible();
      await expect(page.locator('.sidebar nav[aria-label="Recent conversations"]')).toContainText('For Synthetic transit reader');
      await allConversations(page, mobile, '', resolve(renders, `sidebar-open-normal-${view.name}.png`));

      const recent = page.getByRole('navigation', { name: 'Recent conversations' });
      if (mobile) await page.getByRole('button', { name: 'Open navigation' }).click();
      await recent.getByRole('textbox', { name: 'Search conversations' }).fill('unlikely-result');
      await recent.getByRole('button', { name: 'Search' }).click();
      await expect(recent.locator('.recent-entry')).toHaveCount(0);
      await recent.getByRole('button', { name: 'All conversations' }).click();
      await expect(page.locator('.sidebar .recent-entry')).toHaveCount(2);

      sidebar = await navigation(page, mobile);
      await sidebar.getByRole('button', { name: 'Settings' }).click();
      await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
      await allConversations(page, mobile);

      sidebar = await navigation(page, mobile);
      await sidebar.getByRole('button', { name: '＋ Create chart' }).click();
      await expect(page.getByRole('region', { name: 'Create chart' })).toBeVisible();
      await allConversations(page, mobile);

      sidebar = await navigation(page, mobile);
      await sidebar.getByRole('button', { name: '＋ Create chart' }).click();
      await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: /^Transits/ }).click();
      await expect(page.getByRole('region', { name: 'Sky at a date' })).toBeVisible();
      await allConversations(page, mobile);

      sidebar = await navigation(page, mobile);
      await sidebar.getByRole('navigation', { name: 'Recent conversations' })
        .locator('.recent-entry button').filter({ hasText: 'Synthetic transit reader' }).click();
      await expect(page.getByRole('region', { name: 'Conversation', exact: true })).toBeVisible();
      await page.getByLabel('Message Kat').fill('Draft kept when viewing all history');
      await allConversations(page, mobile, 'Draft kept when viewing all history');
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(view.width + 1);
      await page.screenshot({ path: resolve(renders, `sidebar-normal-${view.name}.png`), fullPage: true });
      await page.getByLabel('Message Kat').fill('');
    }
  });

test('normal All conversations fences a delayed ACK and reopens only the committed original', async ({ page }) => {
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-clock-manual');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await expect(page.getByRole('region', { name: 'New conversation' })).toBeVisible();
    const beforeResponse = await page.request.get('/api/conversations');
    expect(beforeResponse.ok()).toBe(true);
    const before = await beforeResponse.json();
    let release!: () => void;
    let arrived!: () => void;
    const held = new Promise<void>(resolve => { release = resolve; });
    const seen = new Promise<void>(resolve => { arrived = resolve; });
    await page.route('**/api/conversations/*/turns', async route => {
      const response = await route.fetch();
      arrived(); await held;
      await route.fulfill({ response });
    });
    await page.getByLabel('Message Kat').fill('Original delayed sidebar input');
    const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
    await page.getByRole('button', { name: 'Send message' }).click();
    await seen;
    await page.getByRole('navigation', { name: 'Recent conversations' })
      .getByRole('button', { name: 'All conversations' }).click();
    await page.getByLabel('Message Kat').fill('A different draft to keep');
    release();
    expect((await ack).status()).toBe(202);
    await expect(page.getByRole('region', { name: 'New conversation' })).toBeVisible();
    await expect(page.getByLabel('Message Kat')).toHaveValue('A different draft to keep');
    await expect(page.locator('.turn-card')).toHaveCount(0);
    await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
    await expect(page.locator('.turn-card .user-bubble'))
      .toContainText('Original delayed sidebar input');
    await expect(page.getByLabel('Message Kat')).toHaveValue('A different draft to keep');
    const saved = await (await page.request.get('/api/conversations')).json();
    expect(saved.conversations).toHaveLength(before.conversations.length + 1);
});
