import { test, expect, type Page } from '@playwright/test';

async function openThread(page: Page, owner: string, people: string[]) {
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  const status = await page.evaluate(async people => {
    const { csrf } = await fetch('/api/session').then(response => response.json());
    return (await fetch('/api/conversations', { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Kat-CSRF': csrf },
      body: JSON.stringify({ id: `menu-${crypto.randomUUID()}`, title: 'New conversation', people }),
    })).status;
  }, people);
  expect(status).toBe(201);
  await page.reload();
  if (page.viewportSize()!.width <= 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
  await expect(page.getByRole('region', { name: 'Conversation', exact: true })).toBeVisible();
}

async function contained(page: Page) {
  const geometry = await page.locator('.conversation-menu .conversation-controls').evaluate(element => {
    const rect = element.getBoundingClientRect();
    const last = element.querySelector('button:last-child')!.getBoundingClientRect();
    return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
      lastTop: last.top, lastBottom: last.bottom, viewport: innerWidth, height: innerHeight,
      lastFocused: document.activeElement === element.querySelector('button:last-child') };
  });
  expect(geometry.left).toBeGreaterThanOrEqual(0);
  expect(geometry.right).toBeLessThanOrEqual(geometry.viewport);
  expect(geometry.top, JSON.stringify(geometry)).toBeGreaterThanOrEqual(0);
  expect(geometry.bottom).toBeLessThanOrEqual(geometry.height);
  if (geometry.lastFocused) {
    expect(geometry.lastTop).toBeGreaterThanOrEqual(geometry.top);
    expect(geometry.lastBottom).toBeLessThanOrEqual(geometry.bottom);
  }
}

test('conversation actions fit general and person contexts and dismiss without changing the draft', async ({ page }) => {
  test.setTimeout(90000);
  for (const people of [[], ['transit-person']]) {
    await page.setViewportSize({ width: 390, height: 844 });
    await openThread(page, `reader-layout-${people.length ? 'mobile' : 'desktop'}`, people);
    const menu = page.locator('.conversation-menu');
    const opener = menu.locator('summary');
    const draft = page.getByLabel('Message Kat');
    await draft.fill('Retained unsent menu draft');
    await expect(draft).toHaveValue('Retained unsent menu draft');
    for (const size of [{ width: 390, height: 844 }, { width: 390, height: 640 },
      { width: 844, height: 390 }, { width: 1440, height: 1024 }, { width: 2560, height: 1080 }]) {
      await page.setViewportSize(size);
      if (size.height === 390) { await opener.focus(); await opener.press('Enter'); }
      else await opener.click();
      await expect(menu).toHaveAttribute('data-placement', /^(above|below)$/);
      await contained(page);
      await expect(menu.getByRole('button', { name: 'Rename' })).toBeVisible();
      await expect(menu.getByRole('button', { name: 'Export original JSONL' })).toBeVisible();
      await expect(menu.getByRole('button', { name: 'Delete conversation' })).toBeVisible();
      await opener.focus();
      await page.keyboard.press('Tab');
      await page.keyboard.press('Tab');
      await page.keyboard.press('Tab');
      await expect(menu.getByRole('button', { name: 'Delete conversation' })).toBeFocused();
      await contained(page);
      await page.screenshot({ path: test.info().outputPath(`menu-${people.length}-${size.width}x${size.height}-last.png`) });
      await page.keyboard.press('Escape');
      await expect(menu).not.toHaveAttribute('open');
      await expect(opener).toBeFocused();
      if (size.height === 390) {
        await opener.press('Enter');
        await page.mouse.click(400, 70);
      } else {
        await opener.click();
        await draft.click();
        await expect(draft).toBeFocused();
      }
      await expect(menu).not.toHaveAttribute('open');
      await expect(draft).toHaveValue('Retained unsent menu draft');
    }
    await opener.click();
    page.once('dialog', dialog => dialog.dismiss());
    await menu.getByRole('button', { name: 'Rename' }).click();
    await expect(menu).not.toHaveAttribute('open');
    await opener.click();
    const exportDownload = page.waitForEvent('download');
    await menu.getByRole('button', { name: 'Export original JSONL' }).click();
    await exportDownload;
    await expect(menu).not.toHaveAttribute('open');
    await opener.click();
    page.once('dialog', dialog => dialog.dismiss());
    await menu.getByRole('button', { name: 'Delete conversation' }).click();
    await expect(menu).not.toHaveAttribute('open');
    await expect(page.getByRole('region', { name: 'Conversation', exact: true })).toBeVisible();
    await expect(draft).toHaveValue('Retained unsent menu draft');
    await page.getByRole('button', { name: 'Sign out' }).click();
    await expect(page.getByRole('heading', { name: 'Welcome to Kat.' })).toBeVisible();
  }
});
