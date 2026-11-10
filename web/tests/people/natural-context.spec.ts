import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/natural-context-capture/renders');
for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024 }, { name: 'mobile', width: 390, height: 844 },
  { name: 'short-mobile', width: 390, height: 560 }, { name: 'reflow', width: 320, height: 560 },
]) test(`natural context explicit self and durable outcomes ${viewport.name}`, async ({ page }) => {
  test.setTimeout(90_000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize(viewport);
  await page.goto('/');
  await page.getByLabel('Username').fill(`reader-capture-${viewport.name}`);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  if (viewport.name === 'reflow') {
    await page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%', 'important'));
    await expect(page.locator('html')).toHaveCSS('font-size', '32px');
  }
  async function capture(state: string) {
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await expect.poll(() => page.locator('dialog[open]').evaluateAll(dialogs => dialogs.every(dialog => dialog.scrollWidth <= dialog.clientWidth + 1))).toBe(true);
    await page.screenshot({ path: resolve(renders, `${state}-${viewport.name}.png`) });
  }
  async function navigation() {
    if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  }
  await navigation();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/personal-context-self', async route => {
    if (route.request().method() === 'GET') await held;
    await route.continue();
  });
  await page.getByRole('button', { name: /Personal context Choose whether/ }).click();
  const self = page.getByRole('region', { name: 'Who is me?' });
  await expect(self.getByRole('status')).toBeVisible();
  await capture('association-loading');
  release();
  await expect(self.getByText('Saved association:', { exact: false })).toBeVisible();
  const consent = page.getByRole('checkbox', { name: 'Use and collect personal context automatically' });
  await expect(consent).not.toBeChecked();
  const denied = await page.request.post('/api/personal-context-self', { data: { person_id: 'casey', expected_version: 2 } });
  expect(denied.status()).toBe(403);
  expect((await (await page.request.get('/api/personal-context-self')).json()).person_id).toBe('casey');
  await capture('consent-off');
  // This seeded historical account retains its existing choice; first-choice and
  // uncertain acknowledgement recovery are exercised in self-label.spec.ts.
  await expect(consent).not.toBeChecked();
  await consent.check();
  await expect(consent).toBeChecked();
  expect((await (await page.request.get('/api/personal-context-self')).json()).person_id).toBe('casey');
  await capture('association-saved');
  await expect(self.getByRole('button', { name: /Change who is me|Clear self association|Choose who is me/ })).toHaveCount(0);
  await expect(self).toContainText('choice cannot be switched');
  expect((await (await page.request.get('/api/personal-context-self')).json()).person_id).toBe('casey');
  await expect(consent).toBeChecked();
  await capture('association-one-time');
  await page.getByRole('button', { name: 'Close settings panel' }).click();
  await page.getByRole('button', { name: 'Back to workspace' }).click();
  for (const state of ['omitted', 'rejected', 'failure', 'conflict', 'discarded', 'saved']) {
    await navigation();
    await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button', { name: new RegExp(`Context ${state}`) }).click();
    const disclosure = page.locator(`[data-kat-turn-id="${state}"] details`).filter({ has: page.locator('summary', { hasText: 'Personal context ·' }) });
    const summary = disclosure.locator('summary');
    await summary.scrollIntoViewIfNeeded();
    const summaryBox = await summary.boundingBox();
    const dock = await page.locator('.composer-wrap').boundingBox();
    const header = await page.locator('.header').boundingBox();
    if (summaryBox && dock && (summaryBox.y < (header?.height ?? 78) || summaryBox.y + summaryBox.height > dock.y)) {
      await page.mouse.move(viewport.width - 20, 100);
      await page.mouse.wheel(0, summaryBox.y - ((header?.height ?? 78) + 16));
    }
    // Explicit user scrolling must expose the summary below the header as well
    // as above the composer; a shorter reply footer can put it behind either.
    await expect.poll(() => summary.evaluate(node => {
      const r = node.getBoundingClientRect();
      return node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
    })).toBe(true);
    await capture(`outcome-${state}-before-open`);
    await summary.click({ timeout: 10_000 });
    if (state === 'saved') await expect(disclosure.locator('summary')).toContainText('1 saved');
    if (state === 'omitted') await expect(disclosure).toContainText('No personal-context update was proposed');
    if (state === 'rejected') await expect(disclosure).toContainText('1 proposal was rejected');
    if (state === 'failure') await expect(disclosure).toContainText('storage failed');
    if (state === 'conflict') await expect(disclosure).toContainText('entry or source changed');
    if (state === 'discarded') await expect(disclosure.locator('li')).toHaveText('discarded');
    await capture(`outcome-${state}`);
    await disclosure.getByRole('button', { name: 'Inspect Context · Casey' }).scrollIntoViewIfNeeded();
    const inspect = disclosure.getByRole('button', { name: 'Inspect Context · Casey' });
    const actionBox = await inspect.boundingBox();
    const composerBox = await page.locator('.composer-wrap').boundingBox();
    if (actionBox && composerBox && actionBox.y + actionBox.height > composerBox.y) {
      // An explicit user scroll, not a claim that opening the disclosure scrolls.
      await page.mouse.move(viewport.width - 20, 100);
      await page.mouse.wheel(0, actionBox.y + actionBox.height - composerBox.y + 24);
    }
    await expect.poll(async () => {
      const action = await inspect.boundingBox();
      const composer = await page.locator('.composer-wrap').boundingBox();
      return !!action && !!composer && action.y >= 0 && action.y + action.height <= composer.y;
    }).toBe(true);
    await capture(`outcome-${state}-inspect-action`);
  }
  await page.getByLabel('Message Kat').fill('A retained synthetic draft');
  await page.getByRole('button', { name: 'Inspect Context · Casey' }).click();
  await expect(page.getByRole('tab', { name: 'Context', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('button', { name: /I joined ExampleWorks in July 2021/ })).toBeVisible();
  await capture('inspect-context');
  await page.goBack();
  await expect(page.getByLabel('Message Kat')).toHaveValue('A retained synthetic draft');
  const stored = await (await page.request.get('/api/people/casey/context?group=past_moments')).json();
  expect(stored.entries).toHaveLength(1);
  expect(stored.entries[0].source.evidence.context.text).toBe('I joined ExampleWorks in July 2021.');
});
