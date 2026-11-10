import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/context-background-visibility/renders');
for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
]) test(`Context background visibility ${viewport.name}`, async ({ page }) => {
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize(viewport);
  await page.goto('/');
  await page.getByLabel('Username').fill(`reader-memory-${viewport.name}`);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  // The fixture already contains an original-source automatic record. Hide only
  // initial collection reads to model an open pane predating publication. Actual
  // worker→save is covered independently by test_memory_transport, not faked here.
  let available = false;
  let reads = 0;
  await page.route('**/api/people/frederik/context/search', async route => {
    reads++;
    if (!available) {
      await route.fulfill({ json: { entries: [], counts: {}, next_offset: null } });
    } else await route.continue();
  });
  if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Frederik$/ }).click();
  await page.getByRole('tab', { name: 'Context', exact: true }).click();
  await expect(page.getByText('Nothing here yet. Add what matters to you.')).toHaveCount(2);
  const initialReads = reads;
  available = true;
  const saved = await (await page.request.get('/api/people/frederik/context')).json();
  expect(saved.entries).toHaveLength(1);
  expect(saved.entries[0].source.kind).toBe('conversation');
  expect(saved.entries[0].content.title).toBe('Frederik enjoys gardening.');
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  expect(reads).toBe(initialReads); // Bounded observation, not a real-time refresh claim.
  await expect(page.getByRole('button', { name: /Frederik enjoys gardening/ })).toHaveCount(0);
  await page.screenshot({ path: resolve(renders, `open-pane-stale-${viewport.name}.png`) });
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  await page.getByRole('tab', { name: 'Context', exact: true }).click();
  const entry = page.getByRole('button', { name: /Frederik enjoys gardening/ });
  await expect(entry).toBeVisible();
  expect(reads).toBeGreaterThan(initialReads);
  await entry.scrollIntoViewIfNeeded();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: resolve(renders, `reopened-${viewport.name}.png`) });
  await entry.click();
  const editor = page.getByRole('dialog', { name: 'Edit entry', exact: true });
  await expect(editor.getByLabel('Title', { exact: true })).toHaveValue('Frederik enjoys gardening.');
  await editor.getByText('Source', { exact: true }).click();
  await expect(editor).toContainText('From a conversation.');
  await expect(editor.locator('blockquote')).toHaveText('Frederik enjoys gardening.');
  await page.screenshot({ path: resolve(renders, `original-source-${viewport.name}.png`) });
});
