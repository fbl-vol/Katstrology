import { test, expect } from '@playwright/test';

test('plain Enter sends once; Shift+Enter and composition preserve the draft', async ({ page }) => {
  test.skip(process.env.KAT_BROWSER_FAKE_PLAN !== '1', 'Requires synthetic plan fixture');
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-chat');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  const input = page.getByLabel('Message Kat');
  await input.fill('A question');
  await input.press('Shift+Enter');
  await input.type('with a second line');
  await expect(input).toHaveValue('A question\nwith a second line');
  let sends = 0;
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/conversations\/[^/]+\/turns$/.test(new URL(request.url()).pathname)) sends++;
  });
  await input.evaluate(element => element.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter', bubbles: true, cancelable: true, isComposing: true,
  })));
  await expect(input).toHaveValue('A question\nwith a second line');
  await input.evaluate(element => element.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter', bubbles: true, cancelable: true, repeat: true,
  })));
  await expect(input).toHaveValue('A question\nwith a second line');
  expect(sends).toBe(0);
  const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
  await input.press('Enter');
  expect((await ack).status()).toBe(202);
  await expect(page.locator('.user-bubble')).toContainText('A question\nwith a second line');
  await expect(input).toHaveValue('');
  await input.press('Enter');
  expect(sends).toBe(1);
  await expect(page.getByRole('navigation', { name: 'Recent conversations' }))
    .toContainText('Chart conversation topics', { timeout: 15000 });
});

test('downloadable chart and comparison wheel expose a full text legend', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-transit-desktop');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  await page.locator('.chart-history > summary').click();
  const chart = page.locator('.chart-history > details').filter({ hasText: 'Current natal' });
  await chart.locator(':scope > summary').click();
  await expect(chart.getByRole('group', { name: /Tropical natal wheel/ })).toBeVisible();
  await expect(chart.getByRole('group', { name: /Tropical natal wheel/ }).locator('desc'))
    .toContainText('☊ North Node');
  const key = chart.locator('.chart-notation');
  await expect(key).not.toHaveAttribute('open');
  await key.locator('summary').click();
  await expect(key.getByRole('table', { name: 'Planet and lunar node symbols on this wheel' })).toContainText('North Node');
  await expect(key).toContainText('MC = Midheaven');
  await expect(key).toContainText('Numbered rays mark house cusps');
});
