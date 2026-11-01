// Exercise real product palettes against the isolated synthetic browser fixture.
import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { themes } from '../src/themes';

const renders = resolve(import.meta.dirname, '../../.local/clock-chart/theme-renders');
const addedPaletteIds = new Set(['peony', 'wisteria', 'apricot-silk', 'sea-pearl',
  'black-cherry', 'moonstone', 'cocoa-rose', 'midnight-orchid']);
test.beforeAll(() => mkdirSync(renders, { recursive: true }));

function contrast(foreground: string, background: string): number {
  const rgb = (hex: string) => {
    const clean = hex.trim().slice(1);
    const bytes = clean.length === 3 ? [...clean].map(ch => parseInt(ch + ch, 16)) :
      [0, 2, 4].map(i => parseInt(clean.slice(i, i + 2), 16));
    return bytes.map(value => {
      const channel = value / 255;
      return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
    });
  };
  const lum = (hex: string) => rgb(hex).reduce((value, channel, index) =>
    value + channel * [.2126, .7152, .0722][index], 0);
  const [a, b] = [lum(foreground), lum(background)].sort((x, y) => y - x);
  return (a + .05) / (b + .05);
}


test('appearance is local presentation state across draft, navigation and sign-out', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-appearance');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByLabel('Message Kat').fill('Keep this unsent draft');
  const mutations: string[] = [];
  page.on('request', request => {
    if (request.url().includes('/api/') && !['GET', 'HEAD'].includes(request.method()))
      mutations.push(`${request.method()} ${new URL(request.url()).pathname}`);
  });
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  const picker = page.getByRole('region', { name: 'Appearance' });
  await expect(picker.getByRole('button', { name: /Reading Room/ })).toHaveAttribute('aria-pressed', 'true');
  await picker.getByRole('button', { name: /Moonstone/ }).focus();
  await page.keyboard.press('Enter');
  await expect(picker.getByRole('button', { name: /Moonstone/ })).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe('dark');
  await page.getByRole('button', { name: 'Back to workspace' }).click();
  await expect(picker).toBeHidden();
  await expect(page.getByLabel('Message Kat')).toHaveValue('Keep this unsent draft');
  expect(mutations).toEqual([]);
  await page.reload();
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('moonstone');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome to Kat.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('moonstone');
});

for (const viewport of [{ name: 'desktop', size: { width: 1440, height: 1024 } },
                        { name: 'mobile', size: { width: 390, height: 844 } }]) {
  test(`all eighteen actual palettes render legibly on ${viewport.name} without an archive mutation`, async ({ page, context }) => {
    test.setTimeout(90000);
    await page.setViewportSize(viewport.size);
    await context.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ?
      route.continue() : route.abort());
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-appearance');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByLabel('Message Kat').fill('An unsent draft; appearance is presentation only.');
    const requests: string[] = [];
    page.on('request', request => {
      if (new URL(request.url()).pathname.startsWith('/api/') && !['GET', 'HEAD'].includes(request.method()))
        requests.push(`${request.method()} ${request.url()}`);
    });
    for (const theme of themes) {
      if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('button', { name: 'Settings' }).click();
      const picker = page.getByRole('region', { name: 'Appearance' });
      await expect(picker.getByRole('button')).toHaveCount(18);
      await picker.getByRole('button', { name: new RegExp(`^${theme.label}`) }).click();
      await expect(picker.getByRole('button', { name: new RegExp(`^${theme.label}`) })).toHaveAttribute('aria-pressed', 'true');
      await page.getByRole('button', { name: 'Back to workspace' }).click();
      await expect(picker).toBeHidden();
      expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe(theme.id);
      expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(theme.mode);
      const colors = await page.evaluate(() => {
        const style = getComputedStyle(document.documentElement);
        return Object.fromEntries(['paper', 'white', 'ink', 'muted', 'forest', 'sidebar-ink',
          'sidebar-muted', 'accent', 'on-accent', 'link', 'warning', 'warning-bg',
          'danger', 'danger-bg', 'surface-code', 'surface-soft', 'surface-tint',
          'sidebar-button', 'sidebar-hover', 'focus', 'sidebar-focus'].map(name =>
          [name, style.getPropertyValue(`--${name}`).trim()]));
      });
      for (const [fg, bg] of [
        ['ink', 'paper'], ['ink', 'white'], ['ink', 'surface-soft'], ['ink', 'surface-tint'],
        ['muted', 'paper'], ['muted', 'white'], ['muted', 'surface-soft'],
        ['sidebar-ink', 'forest'], ['sidebar-muted', 'forest'],
        ['sidebar-ink', 'sidebar-button'], ['sidebar-muted', 'sidebar-hover'],
        ['on-accent', 'accent'], ['link', 'paper'], ['link', 'white'],
        ['warning', 'paper'], ['warning', 'warning-bg'],
        ['danger', 'paper'], ['danger', 'danger-bg'], ['ink', 'surface-code'],
      ]) expect(contrast(colors[fg], colors[bg]), `${theme.id} ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
      for (const [fg, bg] of [['focus', 'paper'], ['focus', 'white'], ['sidebar-focus', 'forest']])
        expect(contrast(colors[fg], colors[bg]), `${theme.id} focus ${fg} on ${bg}`).toBeGreaterThanOrEqual(3);
      await expect(page.getByLabel('Message Kat')).toHaveValue('An unsent draft; appearance is presentation only.');
      await page.screenshot({ path: resolve(renders, `${theme.id}-${viewport.name}.png`) });
      expect(requests, `${theme.id} triggered an API mutation`).toEqual([]);
    }
  });
}

for (const viewport of [{ name: 'short-mobile', size: { width: 390, height: 560 } },
                        { name: 'ultrawide', size: { width: 2560, height: 1080 } }]) {
  test(`eight additions render settings and a form on ${viewport.name}`, async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize(viewport.size);
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-appearance');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await expect(page.getByLabel('Message Kat')).toBeVisible();
    for (const theme of themes.filter(theme => addedPaletteIds.has(theme.id))) {
      await page.evaluate(id => localStorage.setItem('kat.appearance.theme', id), theme.id);
      await page.reload();
      if (viewport.name === 'short-mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('button', { name: 'Settings' }).click();
      const selected = page.getByRole('region', { name: 'Appearance' }).getByRole('button',
        { name: new RegExp(`^${theme.label}`) });
      await expect(selected).toHaveAttribute('aria-pressed', 'true');
      await selected.scrollIntoViewIfNeeded();
      await page.screenshot({ path: resolve(renders, `${theme.id}-${viewport.name}-settings.png`) });
      await page.getByRole('button', { name: 'Back to workspace' }).click();
      if (viewport.name === 'short-mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('button', { name: 'Add person', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
      await dialog.getByLabel('Name').focus();
      await expect(dialog.getByLabel('Name')).toBeFocused();
      await page.screenshot({ path: resolve(renders, `${theme.id}-${viewport.name}-form.png`) });
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth), theme.id)
        .toBeLessThanOrEqual(viewport.size.width + 1);
    }
  });
}

test('Settings themes are keyboard operable and return focus on back' , async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-appearance');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  const opener = page.getByRole('button', { name: 'Settings' });
  await opener.focus();
  await page.keyboard.press('Enter');
  const picker = page.getByRole('region', { name: 'Appearance' });
  await expect(picker).toBeVisible();
  await expect(picker.getByRole('button', { name: /Reading Room/ })).toHaveAttribute('aria-pressed', 'true');
  await picker.getByRole('button', { name: /Rosewood/ }).focus();
  await page.keyboard.press('Enter');
  await expect(picker.getByRole('button', { name: /Rosewood/ })).toHaveAttribute('aria-pressed', 'true');
  await page.screenshot({ path: resolve(renders, 'picker-desktop.png') });
  await page.getByRole('button', { name: 'Back to workspace' }).click();
  await expect(picker).toBeHidden();
  await expect(opener).toBeFocused();
});

test('dark palette preserves person form and Settings connection hierarchy', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-appearance');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('region', { name: 'Appearance' }).getByRole('button', { name: /Black Cherry/ }).click();
  await page.getByRole('button', { name: 'Back to workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const personDialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await expect(personDialog).toBeVisible();
  await page.screenshot({ path: resolve(renders, 'person-dialog-dark.png') });
  await personDialog.getByLabel('Name').fill('Synthetic surface reader');
  await personDialog.getByRole('button', { name: 'Create person' }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic surface reader' })).toBeVisible();
  await page.screenshot({ path: resolve(renders, 'person-dark.png') });
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('region', { name: 'Model connection' })).toBeVisible();
  await page.screenshot({ path: resolve(renders, 'provider-disabled-dark.png') });
});

test('mobile Settings returns to workspace without hiding navigation' , async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-appearance');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  const menu = page.getByRole('button', { name: 'Open navigation' });
  await menu.click();
  await page.getByRole('button', { name: 'Settings' }).click();
  const picker = page.getByRole('region', { name: 'Appearance' });
  await expect(picker).toBeVisible();
  await page.screenshot({ path: resolve(renders, 'picker-mobile.png') });
  await page.getByRole('button', { name: 'Back to workspace' }).click();
  await expect(picker).toBeHidden();
  await expect(menu).toBeFocused();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
});

test('the CSP-pinned bootstrap applies dark mode before the React bundle can run', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'moonstone'));
  await page.route('**/assets/*.js', route => route.abort()); // Prevent React from normalizing the theme.
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
  const html = await response!.text();
  const script = html.match(/<script>([^<]+)<\/script>/)?.[1];
  expect(script).toBeTruthy();
  const digest = createHash('sha256').update(script!).digest('base64');
  expect(response!.headers()['content-security-policy']).toContain(`'sha256-${digest}'`);
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('moonstone');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe('dark');
});

test('storage access denial still leaves a usable Reading Room login', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(window, 'localStorage', {
    get() { throw new DOMException('Storage denied by this synthetic browser', 'SecurityError'); },
  }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Welcome to Kat.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('reading-room');
});

test('invalid preference returns to Reading Room before app paint', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'unexpected-palette'));
  await page.route('**/assets/*.js', route => route.abort());
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('reading-room');
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe('light');
});
