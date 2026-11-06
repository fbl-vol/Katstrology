import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/application-performance');

test('ordinary account and chart history use human labels without losing chart identity', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Sign in to your local workspace. Your ChatGPT connection is separate.')).toBeVisible();
    await page.getByLabel('Username').fill('reader-transit-desktop');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await expect(page.locator('.account')).toContainText('Local workspace');
    await expect(page.locator('header')).not.toContainText('gpt-6.1-sol');
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
    await page.getByRole('tab', { name: 'Charts' }).click();
    const history = page.locator('.chart-history');
    await history.locator(':scope > summary').click();
    const summary = await history.innerText();
    expect(summary).toContain('2001-06-21');
    expect(summary).not.toMatch(/chart-[a-f0-9]+|birth-[a-f0-9]+|profile v\d+/);
    await expect(history.locator(':scope > details[data-kat-chart-id]').first()).toHaveAttribute('data-kat-chart-id', /^chart-/);
});

test('normal provider explanation is accessible without hiding consent or errors', async ({ page }) => {
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-shell');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
    const connection = page.getByRole('region', { name: 'Model connection' });
    const help = connection.getByRole('button', { name: 'About ChatGPT plan connection' });
    const explanation = connection.getByRole('note');
    await expect(explanation).toHaveCount(0);
    await help.hover();
    await expect(explanation).toContainText('Plan use requires a separate permission');
    await page.mouse.move(0, 0);
    await expect(explanation).toHaveCount(0);
    await help.focus();
    await expect(explanation).toBeVisible();
    await help.press('Escape');
    await expect(explanation).toHaveCount(0);
    await help.click();
    await expect(explanation).toBeVisible();
    await explanation.getByRole('button', { name: 'Close explanation' }).click();
    await expect(explanation).toHaveCount(0);
    mkdirSync(renders, { recursive: true });
    for (const view of [{ width: 390, height: 560 }, { width: 2560, height: 1080 }]) {
      await page.setViewportSize(view);
      await help.click();
      await expect(explanation).toBeVisible();
      const bounds = await explanation.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(view.width);
      await page.screenshot({ path: resolve(renders, `provider-help-normal-${view.width}.png`), fullPage: true });
      await explanation.getByRole('button', { name: 'Close explanation' }).click();
      await expect(explanation).toHaveCount(0);
    }
    await expect(connection.getByRole('button', { name: 'Connect ChatGPT plan' })
      .or(connection.getByText(/connection is disabled/))).toBeVisible();
});
