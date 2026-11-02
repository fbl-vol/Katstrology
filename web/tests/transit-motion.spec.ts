import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/post-deployment-features');

test('on-demand dated transits keep natal fixed and stop or scrub without sending', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-motion');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic motion reader');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('04:06');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).first().click();
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.locator('.birth-status')).toContainText('Current natal saved');
  const charts = page.getByRole('tabpanel', { name: 'Charts' });
  let samples = 0, sends = 0;
  page.on('request', request => {
    if (request.url().includes('/transit-frames')) samples++;
    if (request.method() === 'POST' && /\/(turns|chat)$/.test(new URL(request.url()).pathname)) sends++;
  });
  const panel = charts.locator('.transit-motion');
  await expect(panel).toBeVisible();
  await expect(panel).not.toHaveAttribute('open', '');
  expect(samples).toBe(0);
  await panel.locator('summary').click();
  await panel.getByLabel('From (UTC)').fill('2024-04-01');
  await panel.getByLabel('To (UTC)').fill('2024-04-08');
  expect(samples).toBe(0);
  const response = page.waitForResponse(item => item.url().includes('/transit-frames') && item.status() === 200);
  await panel.getByRole('button', { name: 'Load dated samples' }).click();
  expect((await response).status()).toBe(200);
  await expect(panel.getByRole('img', { name: /Sampled transiting planets around the fixed natal chart/ })).toBeVisible();
  await panel.getByRole('button', { name: 'Play', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'Pause' })).toBeVisible();
  await panel.getByRole('button', { name: 'Pause' }).click();
  await panel.getByRole('button', { name: 'Play', exact: true }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(panel.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  expect(samples).toBe(1); expect(sends).toBe(0);
  const savedNatal = await charts.locator('.natal-tables').first().innerText();
  const slider = panel.getByRole('slider', { name: 'Scrub dated samples' });
  await slider.focus(); await page.keyboard.press('End');
  await expect(slider).toHaveAttribute('aria-valuetext', /2024-04-08 00:00 UTC/);
  expect(await charts.locator('.natal-tables').first().innerText()).toBe(savedNatal);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 },
    { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `motion-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(panel.getByRole('button', { name: 'Replay' })).toBeDisabled();
  await expect(panel.getByText('Reduced motion: autoplay and Play are disabled.')).toBeVisible();
  await slider.focus(); await page.keyboard.press('Home');
  await expect(slider).toHaveAttribute('aria-valuetext', /2024-04-01 00:00 UTC/);
  expect(sends).toBe(0);
});
