import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/automatic-memory/renders');
for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short-mobile', width: 390, height: 560 },
  { name: 'reflow', width: 320, height: 560 },
]) test(`automatic memory quiet consent and Context controls ${viewport.name}`, async ({ page }) => {
  test.setTimeout(90_000);
  page.setDefaultTimeout(10_000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize(viewport);
  await page.goto('/');
  await page.getByLabel('Username').fill(`reader-memory-${viewport.name}`);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  if (viewport.name === 'reflow') {
    await page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%', 'important'));
  }
  async function navigation() {
    if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  }
  async function capture(state: string) {
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await expect.poll(() => page.locator('dialog[open]').evaluateAll(nodes => nodes.every(node => node.scrollWidth <= node.clientWidth + 1))).toBe(true);
    await page.screenshot({ path: resolve(renders, `${state}-${viewport.name}.png`) });
  }
  await navigation();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let fail = true;
  let posts = 0;
  await page.route('**/api/personal-context-preference', async route => {
    if (route.request().method() === 'GET') await held;
    if (route.request().method() === 'POST') {
      posts++;
      if (fail) {
        fail = false;
        await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
        return;
      }
    }
    await route.continue();
  });
  await page.getByRole('button', { name: /Personal context Choose whether/ }).click();
  const settings = page.getByRole('region', { name: 'Personal context settings' });
  await expect(settings.getByText('Loading choice…')).toBeVisible();
  await capture('loading');
  release();
  const consent = settings.getByRole('checkbox', { name: 'Use and collect personal context automatically' });
  await expect(consent).not.toBeChecked();
  const consentLabel = settings.locator('.personal-context-consent');
  await expect.poll(() => consentLabel.evaluate(node => node.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
  if (viewport.name === 'reflow') await expect(consentLabel).toHaveCSS('font-size', '28px');
  await expect(settings).toContainText('including people you add later');
  await expect(settings).toContainText('your connected provider for processing after a reply');
  await expect(settings).not.toContainText('unselected people');
  await expect(settings).not.toContainText('keep that person selected');
  await consent.scrollIntoViewIfNeeded();
  await capture('consent-off');
  await consent.focus();
  await page.keyboard.press('Space');
  await expect(settings.getByRole('alert')).toContainText('not confirmed');
  await expect(consent).not.toBeChecked();
  await expect(consent).toBeDisabled();
  await settings.getByRole('alert').scrollIntoViewIfNeeded();
  await capture('failure');
  await settings.getByRole('button', { name: 'Refresh choice' }).click();
  await expect(consent).toBeEnabled();
  await consent.check();
  await expect(consent).toBeEnabled();
  await expect(consent).toBeChecked();
  expect(posts).toBe(2);
  expect((await (await page.request.get('/api/personal-context-self')).json()).person_id).toBeNull();
  await consent.scrollIntoViewIfNeeded();
  await capture('consent-on');
  await page.getByRole('button', { name: 'Close settings panel' }).click();
  await page.getByRole('button', { name: 'Back to workspace' }).click();
  await navigation();
  await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button', { name: /Garden conversation/ }).click();
  const turn = page.locator('[data-kat-turn-id="remembered"]');
  await expect(turn).toContainText('Gardening can be a rewarding creative practice.');
  await expect(turn).not.toContainText('Personal context ·');
  await expect(turn).not.toContainText('no confirmed saves');
  await expect(turn).not.toContainText('gpt-6-luna');
  await page.getByLabel('Message Kat').fill('A retained draft while I inspect Context');
  await capture('quiet-reply');
  await navigation();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Frederik$/ }).click();
  await page.getByRole('tab', { name: 'Context', exact: true }).click();
  const entry = page.getByRole('button', { name: /Frederik enjoys gardening/ });
  await expect(entry).toBeVisible();
  await entry.scrollIntoViewIfNeeded();
  await capture('context');
  await entry.click();
  const editor = page.getByRole('dialog', { name: 'Edit entry', exact: true });
  await expect(editor.getByLabel('Title', { exact: true })).toBeFocused();
  await editor.getByLabel('Title', { exact: true }).fill('Frederik enjoys growing herbs');
  await capture('manual-edit');
  await editor.getByRole('button', { name: 'Save entry' }).click();
  await expect(editor).not.toBeVisible();
  await page.getByRole('button', { name: /Frederik enjoys growing herbs/ }).click();
  page.once('dialog', async dialog => {
    expect(dialog.message()).toContain('Earlier conversation inputs will no longer supply automatic updates for this person');
    expect(dialog.message()).toContain('Other saved entries');
    await dialog.accept();
  });
  await editor.getByRole('button', { name: 'Remove', exact: true }).click();
  await expect(editor).not.toBeVisible();
  expect((await (await page.request.get('/api/people/frederik/context')).json()).entries).toHaveLength(0);
  await page.goBack();
  await expect(page.getByRole('tab', { name: 'Overview', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.goBack();
  await expect(page.getByLabel('Message Kat')).toHaveValue('A retained draft while I inspect Context');
});
