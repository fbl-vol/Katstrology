import { test, expect } from '@playwright/test';
import { createHash } from 'node:crypto';
import { readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const web = resolve(import.meta.dirname, '../..');
const renders = resolve(web, '../.local/pwa');
const sha = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');

const icons = [
  { src: '/icons/kat-192.png', size: 192, purpose: 'any' },
  { src: '/icons/kat-512.png', size: 512, purpose: 'any' },
  { src: '/icons/kat-512-maskable.png', size: 512, purpose: 'maskable' },
];

test('normal installed-app assets are immutable build copies with scoped online-only identity', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute('href', '/manifest.webmanifest');
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#f5f3ec');
  const response = await page.request.get('/manifest.webmanifest');
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toContain('application/manifest+json');
  expect(response.headers()['cache-control']).toContain('no-store');
  const bytes = await response.body();
  expect(sha(bytes)).toBe(sha(readFileSync(resolve(web, 'public/manifest.webmanifest'))));
  const manifest = JSON.parse(bytes.toString());
  expect(manifest).toMatchObject({ id: '/', name: 'Katstrology', short_name: 'Kat',
    start_url: '/', scope: '/', display: 'standalone',
    theme_color: '#f5f3ec', background_color: '#f5f3ec' });
  expect(manifest).not.toHaveProperty('serviceworker');
  expect(manifest.icons).toEqual(icons.map(({ src, size, purpose }) => ({
    src, sizes: `${size}x${size}`, type: 'image/png', purpose,
  })));
  const origin = new URL(page.url());
  for (const { src, size } of icons) {
    expect(new URL(src, origin).origin).toBe(origin.origin);
    const icon = await page.request.get(src);
    expect(icon.status()).toBe(200);
    expect(icon.headers()['content-type']).toContain('image/png');
    expect(icon.headers()['cache-control']).toContain('no-store');
    const pixels = await icon.body();
    expect(pixels.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
    expect([pixels.readUInt32BE(16), pixels.readUInt32BE(20)]).toEqual([size, size]);
    expect(sha(pixels)).toBe(sha(readFileSync(resolve(web, 'public' + src))));
    expect((await page.request.get(src, { headers: { Host: 'wrong.invalid' } })).status()).toBe(403);
  }
  expect((await page.request.get('/manifest.webmanifest', { headers: { Host: 'wrong.invalid' } })).status()).toBe(403);
  const mask = await page.evaluate(async () => {
    const blob = await (await fetch('/icons/kat-512-maskable.png')).blob();
    const bitmap = await createImageBitmap(blob);
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 512;
    const context = canvas.getContext('2d')!;
    context.drawImage(bitmap, 0, 0);
    const data = context.getImageData(0, 0, 512, 512).data;
    let outside = 0;
    let artwork = 0;
    for (let y = 0; y < 512; y++) for (let x = 0; x < 512; x++) {
      const i = (y * 512 + x) * 4;
      const background = data[i] === 245 && data[i + 1] === 243 && data[i + 2] === 236;
      if (!background) {
        artwork++;
        if (Math.hypot(x + 0.5 - 256, y + 0.5 - 256) >= 0.4 * 512) outside++;
      }
    }
    return { outside, artwork };
  });
  expect(mask.outside).toBe(0);
  expect(mask.artwork).toBeGreaterThan(1000);
  expect((await page.request.get('/api/session')).status()).toBe(401);
  expect(await page.evaluate(() => navigator.serviceWorker?.getRegistrations().then(list => list.length) ?? 0)).toBe(0);
});

test('normal synthetic standalone-media branch retains login, draft and logout on mobile and desktop', async ({ page }) => {
  mkdirSync(renders, { recursive: true });
  // Chromium's CDP media override does not emulate display-mode here. This
  // branch probe is not a WebAPK install, system window or device acceptance.
  await page.addInitScript(() => {
    const original = window.matchMedia.bind(window);
    window.matchMedia = (query: string) => query === '(display-mode: standalone)'
      ? { ...original(query), matches: true } as MediaQueryList
      : original(query);
  });
  for (const { name, width, height } of [
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'desktop', width: 1440, height: 1024 },
  ]) {
    await page.setViewportSize({ width, height });
    await page.goto('/');
    expect(await page.evaluate(() => matchMedia('(display-mode: standalone)').matches)).toBe(true);
    await expect(page.getByLabel('Username')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
    await page.screenshot({ path: resolve(renders, `login-${name}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel('Username').fill('reader-transit-desktop');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByLabel('Message Kat')).toBeVisible();
  await page.getByLabel('Message Kat').fill('Synthetic unsubmitted installed-mode draft');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('complementary', { name: 'Workspace navigation' }).getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
  await page.getByRole('button', { name: 'Back to workspace' }).click();
  await expect(page.getByLabel('Message Kat')).toHaveValue('Synthetic unsubmitted installed-mode draft');
  await page.screenshot({ path: resolve(renders, 'standalone-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('complementary', { name: 'Workspace navigation' }).getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByLabel('Username')).toBeVisible();
  expect((await page.request.get('/api/session')).status()).toBe(401);
});
