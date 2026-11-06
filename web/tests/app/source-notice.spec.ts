import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

test('source, license and warranty notice are available before and after local sign-in', async ({ page }) => {
  const renders = resolve(import.meta.dirname, '../../../.local/first-publication');
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 390, height: 560 });
  await page.goto('/');
  const notice = page.locator('.login-card .source-notice');
  await expect(notice).toContainText('without warranty');
  await expect(notice.getByRole('link', { name: 'Read the license' }))
    .toHaveAttribute('href', 'https://www.gnu.org/licenses/agpl-3.0.html');
  await expect(notice.getByRole('link', { name: 'Source and build instructions' }))
    .toHaveAttribute('href', 'https://github.com/fbl-vol/Katstrology');
  await expect(notice.getByRole('link', { name: 'Source and build instructions' }))
    .toHaveAttribute('rel', 'noopener noreferrer');
  const licenseLink = await notice.getByRole('link', { name: 'Read the license' }).boundingBox();
  expect(licenseLink && licenseLink.y + licenseLink.height).toBeLessThanOrEqual(560);
  await page.screenshot({ path: resolve(renders, 'license-login-mobile.png') });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.screenshot({ path: resolve(renders, 'license-login-desktop.png') });
  await page.setViewportSize({ width: 390, height: 560 });

  await page.getByLabel('Username').fill('reader-shell');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: 'About Kat & source' }).click();
  const about = page.getByRole('region', { name: 'About and source' });
  await expect(about).toContainText('AGPLv3 only, without warranty');
  await expect(about.getByRole('link', { name: 'Source and build instructions' })).toBeVisible();
  await expect(about.getByRole('link', { name: 'Read the license' })).toBeVisible();
  await about.scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'license-settings-mobile.png') });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.screenshot({ path: resolve(renders, 'license-settings-desktop.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440);
});
