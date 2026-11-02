import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/application-performance');
const brand = { name: 'kat. — New conversation' };

async function sidebarButton(page: Page, name: string | RegExp, mobile: boolean) {
  if (mobile) await page.getByRole('button', { name: 'Open navigation' }).click();
  const section = name instanceof RegExp ? page.getByRole('navigation', { name: 'People' }) :
    page.getByRole('complementary', { name: 'Workspace navigation' });
  await section.getByRole('button', { name }).click();
}

async function brandHome(page: Page, mobile: boolean) {
  const menu = page.getByRole('button', { name: 'Open navigation' });
  if (mobile) await menu.click();
  const home = page.getByRole('button', brand);
  await expect(home).toBeVisible();
  const bounds = await home.boundingBox();
  expect(bounds!.height).toBeGreaterThanOrEqual(44);
  await home.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('region', { name: 'New conversation' })).toBeVisible();
  await expect(page.locator('.header-title')).toHaveText('New conversation');
  await expect(page.getByLabel('Message Kat')).toHaveValue('');
  await expect(page.getByRole('button', { name: 'Remove Synthetic transit reader from new turn' })).toHaveCount(0);
  if (mobile) {
    await expect(menu).toBeFocused();
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
  }
}

test('normal brand reuses New conversation from saved thread and every route', async ({ page }) => {
    test.setTimeout(100000);
    mkdirSync(renders, { recursive: true });
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-transit-desktop');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await expect(page.getByRole('region', { name: 'New conversation' })).toBeVisible();
    expect(decodeURIComponent((await page.locator('.brand img').getAttribute('src'))!)).toContain('Crescent-tail kitten primary logo');
    expect(decodeURIComponent((await page.locator('link[rel="icon"]').getAttribute('href'))!)).toMatch(/kat-face|Simplified kitten face/);
    let creates = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/conversations') creates++;
    });

    await sidebarButton(page, /Synthetic transit reader/, false);
    await page.getByRole('button', { name: 'New conversation about Synthetic transit reader' }).click();
    await page.getByLabel('Message Kat').fill('Synthetic brand-home archived input');
    const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
    await page.getByRole('button', { name: 'Send message' }).click();
    expect((await ack).status()).toBe(202);
    await expect(page.getByRole('region', { name: 'Conversation', exact: true })).toBeVisible();
    await brandHome(page, false);
    expect(creates).toBe(1); // Clicking the brand does not create or resend a conversation.
    const saved = await (await page.request.get('/api/conversations')).json();
    const turns = await (await page.request.get(`/api/conversations/${saved.conversations[0].id}/turns`)).json();
    expect(turns.turns[0].events[0].payload.content).toBe('Synthetic brand-home archived input');
    await expect(page.getByRole('navigation', { name: 'Recent conversations' })).not.toContainText('No messages yet');
    await page.evaluate(() => { (window as Window & { brandDocument?: string }).brandDocument = 'original'; });

    for (const view of [
      { name: 'desktop', width: 1440, height: 1024 },
      { name: 'mobile', width: 390, height: 844 },
      { name: 'short-mobile', width: 390, height: 560 },
      { name: 'ultrawide', width: 2560, height: 1080 },
    ]) {
      await page.setViewportSize({ width: view.width, height: view.height });
      const mobile = view.width < 700;
      await sidebarButton(page, 'Settings', mobile);
      await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
      await expect(page.locator('.reading-kitten svg')).toHaveAttribute('data-motion', 'off');
      await brandHome(page, mobile);

      await sidebarButton(page, '＋ Create chart', mobile);
      await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: /^Transits/ }).click();
      await expect(page.getByRole('region', { name: 'Sky at a date' })).toBeVisible();
      await brandHome(page, mobile);

      await sidebarButton(page, '＋ Create chart', mobile);
      await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: /^Synastry/ }).click();
      await expect(page.getByRole('region', { name: 'Synastry chart' })).toBeVisible();
      await brandHome(page, mobile);

      await sidebarButton(page, /Synthetic transit reader/, mobile);
      await expect(page.getByRole('heading', { name: 'Synthetic transit reader' })).toBeVisible();
      await brandHome(page, mobile);
      const kitten = page.locator('.welcome .reading-kitten svg');
      await expect(kitten).toBeVisible();
      await expect(kitten).toHaveAttribute('data-motion', 'on');
      for (const [part, name] of [['.eye', 'kat-blink'], ['.tail', 'kat-tail'], ['.star', 'kat-star']]) {
        expect(await kitten.locator(part).first().evaluate(node => getComputedStyle(node).animationName)).toBe(name);
      }
      expect(await kitten.locator('.iris').first().evaluate(node => getComputedStyle(node).fill)).toBe('rgb(230, 193, 120)');
      await page.emulateMedia({ reducedMotion: 'reduce' });
      for (const part of ['.eye', '.tail', '.star']) {
        expect(await kitten.locator(part).first().evaluate(node => getComputedStyle(node).animationName)).toBe('none');
      }
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      expect(creates).toBe(1);
      expect(await page.evaluate(() => (window as Window & { brandDocument?: string }).brandDocument)).toBe('original');
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(view.width + 1);
      await page.screenshot({ path: resolve(renders, `brand-home-normal-${view.name}.png`), fullPage: true });
    }
});
