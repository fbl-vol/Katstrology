import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/information-hierarchy/renders');
const sizes = [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short-dark', width: 390, height: 560 },
  { name: 'reflow', width: 320, height: 560 },
];
for (const size of sizes) test(`information hierarchy chart depth and dated return ${size.name}`, async ({ page }) => {
  await page.setViewportSize(size);
  if (size.name === 'short-dark') await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'midnight-pine'));
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-clock-desktop');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  if (size.width < 701) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  const chartRead = page.waitForResponse(response => /\/api\/charts\/[^/]+$/.test(new URL(response.url()).pathname));
  await page.getByRole('button', { name: 'Open Natal chart', exact: true }).click();
  const chart = await (await chartRead).json();
  if (size.name === 'reflow') await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
  const reader = page.getByRole('region', { name: 'Saved chart reader' });
  await expect(reader.getByText('Birth details are provisional; treat these positions as tentative.')).toBeVisible();
  mkdirSync(renders, { recursive: true });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(renders, `chart-${size.name}.png`), fullPage: true });

  const tables = reader.locator('.chart-exact-data');
  await tables.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(tables.locator('table').first().locator('tbody tr')).toHaveCount(chart.result.natal.positions.length);
  await expect(tables.locator('table').nth(1).locator('tbody tr')).toHaveCount(14);
  await expect(tables.locator('table').nth(2).locator('tbody tr')).toHaveCount(chart.result.natal.aspects.length);
  await tables.scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, `tables-${size.name}.png`) });
  await tables.locator('summary').click();
  const timing = reader.getByRole('region', { name: 'Explore timing' });
  let sampleRequests = 0;
  page.on('request', request => { if (request.url().includes('/transit-frames')) sampleRequests++; });
  await timing.getByText('Animate transits', { exact: false }).click();
  await expect(timing).toContainText('1–7 UTC days');
  await expect(timing).toContainText('no aspect events or sky houses');
  await expect(timing.getByLabel('From (UTC)')).toBeVisible();
  expect(sampleRequests).toBe(0);
  await timing.evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 90));
  await page.screenshot({ path: resolve(renders, `timing-${size.name}.png`) });
  await timing.locator('form').evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 90));
  await page.screenshot({ path: resolve(renders, `animation-input-${size.name}.png`) });
  await timing.getByRole('button', { name: 'Sky at a date', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Sky at a date' })).toBeVisible();
  await page.getByRole('button', { name: 'Return to person' }).click();
  await expect(reader.getByRole('heading', { name: 'Current birth chart' })).toBeVisible();
  await expect(timing.getByRole('button', { name: 'Sky at a date', exact: true })).toBeFocused();
  await page.goForward();
  await expect(page.getByRole('heading', { name: 'Sky at a date' })).toBeVisible();
  await page.goBack();
  await expect(reader.getByRole('heading', { name: 'Current birth chart' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
});

for (const size of sizes) test(`information hierarchy content and reply actions ${size.name}`, async ({ page }) => {
  await page.setViewportSize(size);
  if (size.name === 'short-dark') await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'midnight-pine'));
  await page.goto('/');
  await page.getByLabel('Username').fill(`reader-hierarchy-${size.name}`);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  if (size.width < 701) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Casey');
  await page.getByRole('button', { name: 'Create person', exact: true }).click();
  await page.getByRole('tab', { name: 'Context', exact: true }).click();
  const pane = page.getByRole('tabpanel', { name: 'Context', exact: true });
  await expect(page.getByRole('button', { name: 'Start conversation', exact: true })).not.toHaveClass(/primary/);
  for (const [collection, title, notes] of [
    ['Life & plans', 'Settling into ExampleWorks', 'I want to give myself time to find a rhythm.'],
    ['Interests & learning', 'Concrete examples', 'I prefer examples alongside unfamiliar terms.'],
  ]) {
    await pane.getByRole('region', { name: collection, exact: true }).getByRole('button', { name: 'Add', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Add context', exact: true });
    await dialog.getByLabel('Title', { exact: true }).fill(title);
    await dialog.getByLabel('Supporting details').fill(notes);
    await dialog.getByRole('button', { name: 'Save entry' }).click();
    await expect(pane.getByRole('button', { name: new RegExp(title) })).toBeVisible();
  }
  if (size.name === 'reflow') await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
  mkdirSync(renders, { recursive: true });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(renders, `context-${size.name}.png`), fullPage: true });
  for (const add of await pane.getByRole('button', { name: 'Add', exact: true }).all()) {
    expect(await add.evaluate(node => {
      const range = document.createRange();
      range.selectNodeContents(node);
      return range.getClientRects().length;
    })).toBe(1);
  }
  await pane.getByRole('searchbox', { name: 'Search Life & plans' }).fill('no match');
  await expect(pane.getByText('No matching entries.')).toBeVisible();
  await expect(pane.getByRole('button', { name: /Concrete examples/ })).toBeVisible();
  await pane.getByRole('searchbox', { name: 'Search Life & plans' }).fill('');
  await pane.getByRole('button', { name: /Settling into ExampleWorks/ }).click();
  const edit = page.getByRole('dialog', { name: 'Edit entry', exact: true });
  await edit.getByText('Source', { exact: true }).click();
  await expect(edit.getByText('Entered directly by you.')).toBeVisible();
  page.once('dialog', async dialog => {
    expect(dialog.message()).toContain('information already sent to a provider remain');
    await dialog.dismiss();
  });
  await edit.getByRole('button', { name: 'Remove', exact: true }).click();
  await expect(edit.getByLabel('Title', { exact: true })).toHaveValue('Settling into ExampleWorks');
  await edit.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Start conversation', exact: true }).click();
  await page.getByLabel('Message Kat').fill('I am finding a rhythm at ExampleWorks. Where could I begin?');
  await page.getByRole('button', { name: 'Send message' }).click();
  const turn = page.locator('.turn-card').last();
  await expect(turn).toHaveAttribute('data-kat-status', 'complete');
  await expect(turn.locator('.assistant-answer')).toContainText('it is a rhythm you can actually live with.');
  await expect(turn.locator('.assistant-answer h3')).toHaveText('Start with one dependable thing');
  await expect(turn.getByRole('button', { name: 'Edit input' })).not.toBeVisible();
  await page.getByLabel('Message Kat').fill('Keep this draft while I inspect the reply.');
  await turn.locator('.assistant-answer').evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 100));
  await page.screenshot({ path: resolve(renders, `reading-${size.name}.png`) });
  await turn.locator('.assistant-answer p').last().evaluate(node => {
    const composer = document.querySelector('.composer')!.getBoundingClientRect();
    window.scrollBy(0, node.getBoundingClientRect().bottom - composer.top + 24);
  });
  await page.screenshot({ path: resolve(renders, `reading-end-${size.name}.png`) });
  await turn.getByText('Reply actions', { exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(turn.getByRole('button', { name: 'Edit input' })).toBeVisible();
  await expect(turn.getByRole('button', { name: 'Correct or withdraw' })).toBeVisible();
  await turn.locator('.reply-maintenance .turn-actions').evaluate(node => window.scrollTo(0, scrollY + node.getBoundingClientRect().top - 100));
  await expect(turn.getByRole('button', { name: 'Edit input' })).toBeInViewport();
  await expect(turn.getByRole('button', { name: 'Correct or withdraw' })).toBeInViewport();
  await page.screenshot({ path: resolve(renders, `reply-actions-${size.name}.png`) });
  await turn.getByText('Reply actions', { exact: true }).click();
  await expect(page.getByLabel('Message Kat')).toHaveValue('Keep this draft while I inspect the reply.');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
});
