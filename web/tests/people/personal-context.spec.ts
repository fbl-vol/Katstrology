import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/personal-context/renders');
const viewports = [
  { name: 'desktop', width: 1440, height: 1024 }, { name: 'wide', width: 2560, height: 1080 },
  { name: 'mobile', width: 390, height: 844 }, { name: 'short-mobile', width: 390, height: 560 },
  { name: 'tablet', width: 768, height: 1024 },
];
for (const viewport of viewports) test(`personal context complete manual workflow ${viewport.name}`, async ({ page }) => {
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize(viewport);
  async function capture(state: string, fullPage = false) {
    if (fullPage) await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(renders, `${state}-${viewport.name}.png`), fullPage });
  }
  await page.goto('/');
  await page.getByLabel('Username').fill(`reader-context-${viewport.name}`);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  const session = await (await page.request.get('/api/session')).json();
  const headers = { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin };
  const make = async (name: string) => {
    const response = await page.request.post('/api/people', { headers, data: { name } });
    expect(response.status()).toBe(201); return (await response.json()).id as string;
  };
  const person = await make('Synthetic context reader');
  const other = await make('Synthetic linked person');
  await page.reload();
  if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic context reader' }).click();
  const contextTab = page.getByRole('tab', { name: 'Context', exact: true });
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let firstRead = true;
  let failRead = false;
  await page.route(`**/api/people/${person}/context/search`, async route => {
    if (firstRead) { firstRead = false; await held; }
    if (failRead) { failRead = false; await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }); }
    else await route.continue();
  });
  await page.getByRole('tab', { name: 'Overview' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(contextTab).toBeFocused();
  const pane = page.getByRole('tabpanel', { name: 'Context', exact: true });
  await expect(pane.getByText('Opening context…')).toBeVisible();
  await capture('loading', true);
  release();
  await expect(pane.getByText('Nothing here yet. Add what matters to you.')).toHaveCount(2);
  await capture('empty', true);
  await page.getByRole('tab', { name: 'Overview' }).click(); failRead = true; await contextTab.click();
  await expect(pane.getByRole('alert')).toContainText('Context could not be refreshed');
  await expect(pane.getByText('Nothing here yet. Add what matters to you.')).toHaveCount(0);
  await capture('unavailable', true);
  await pane.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(pane.getByText('Nothing here yet. Add what matters to you.')).toHaveCount(2);
  await pane.getByRole('region', { name: 'Life & plans' }).getByRole('button', { name: 'Add', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Add context', exact: true });
  await expect(dialog.getByLabel('Title', { exact: true })).toBeFocused();
  await dialog.getByLabel('Title', { exact: true }).fill('A possible move');
  await dialog.getByLabel('Supporting details').fill('Only a possibility; no exact date yet');
  await dialog.getByLabel('Date in your words').fill('Maybe next summer');
  await page.screenshot({ path: resolve(renders, `add-${viewport.name}.png`) });
  let failSave = true;
  await page.route(`**/api/people/${person}/context`, async route => {
    if (route.request().method() === 'POST' && failSave) {
      failSave = false; await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
    } else await route.continue();
  });
  await dialog.getByRole('button', { name: 'Save entry' }).click();
  await expect(dialog.getByRole('alert')).toContainText('Save was not confirmed');
  await expect(dialog.getByLabel('Title', { exact: true })).toHaveValue('A possible move');
  await dialog.getByRole('button', { name: 'Save entry' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, `save-failure-${viewport.name}.png`) });
  await dialog.getByRole('button', { name: 'Save entry' }).click();
  await expect(dialog).not.toBeVisible();
  await expect(pane.getByRole('button', { name: /A possible move/ })).toBeVisible();
  await pane.getByRole('region', { name: 'Interests & learning' }).getByRole('button', { name: 'Add', exact: true }).click();
  await dialog.getByRole('combobox', { name: 'Group', exact: true }).selectOption('guidance_preferences');
  await dialog.getByLabel('Title', { exact: true }).fill('Short explanations');
  await dialog.getByRole('button', { name: 'Save entry' }).click();
  await expect(pane.getByRole('button', { name: /Short explanations/ })).toBeVisible();
  await capture('ordinary', true);
  for (let index = 0; index < 25; index++) {
    const response = await page.request.post(`/api/people/${person}/context`, { headers, data: {
      id: `synthetic-${index}`, operation_id: `synthetic-${index}`, expected_version: 0,
      content: { group: 'coming_up', title: `Synthetic plan ${index}`, notes: 'Fictional details', state: 'tentative',
        date: { text: 'Sometime next year', precision: 'unknown', start: null, end: null } },
    } }); expect(response.status()).toBe(200);
  }
  await page.getByRole('tab', { name: 'Overview' }).click(); await contextTab.click();
  await expect(pane.getByRole('button', { name: 'View all (26, 24 more)' })).toBeVisible();
  await capture('large', true);
  await pane.getByRole('button', { name: 'View all (26, 24 more)' }).click();
  await expect(pane.getByRole('button', { name: 'More entries' })).toBeVisible();
  await pane.getByRole('button', { name: 'More entries' }).click();
  await expect(pane.locator('.context-row')).toHaveCount(26);
  await pane.locator('.context-row').last().scrollIntoViewIfNeeded();
  await capture('expanded-bottom');
  await pane.getByLabel('Search context').fill('possible move');
  await expect(pane.locator('.context-row')).toHaveCount(1);
  await capture('search', true);
  await pane.getByRole('button', { name: /A possible move/ }).click();
  const edit = page.getByRole('dialog', { name: 'Edit entry', exact: true });
  await edit.getByLabel('Title', { exact: true }).fill('A revised possible move');
  await page.screenshot({ path: resolve(renders, `edit-${viewport.name}.png`) });
  await edit.getByRole('button', { name: 'Save entry' }).click();
  await expect(pane.getByRole('button', { name: /A revised possible move/ })).toBeVisible();
  await page.getByRole('tab', { name: 'Overview' }).click();
  await page.getByRole('region', { name: 'Personal details and linked people' }).getByRole('button', { name: 'Edit', exact: true }).click();
  const details = page.getByRole('dialog', { name: 'Edit personal details', exact: true });
  await details.getByLabel('Occupation', { exact: true }).fill('Synthetic teacher');
  await details.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(details).not.toBeVisible();
  await expect(page.getByText('Synthetic teacher', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Link person', exact: true }).click();
  const link = page.getByRole('dialog', { name: 'Link person', exact: true });
  await link.getByRole('combobox', { name: 'Person', exact: true }).selectOption(other);
  await link.getByLabel('Their relationship').fill('Friend');
  await page.screenshot({ path: resolve(renders, `link-${viewport.name}.png`) });
  await link.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(link).not.toBeVisible();
  await page.getByRole('button', { name: /Synthetic linked person Friend/ }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic linked person', exact: true })).toBeVisible();
  if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic context reader' }).click();
  await contextTab.click();
  await expect(pane.getByLabel('Search context')).toHaveValue('possible move');
  await expect(pane.getByRole('button', { name: /A revised possible move/ })).toBeVisible();
  await pane.getByRole('button', { name: /A revised possible move/ }).click();
  page.once('dialog', dialog => dialog.accept());
  await edit.getByRole('button', { name: 'Remove', exact: true }).click();
  await expect(edit).not.toBeVisible();
  await expect(pane.getByText('No matching entries.')).toBeVisible();
  await page.getByRole('tab', { name: 'Overview' }).click();
  await page.getByRole('button', { name: 'Edit relationship with Synthetic linked person' }).click();
  await link.getByRole('button', { name: 'Unlink', exact: true }).click();
  await expect(link).not.toBeVisible();
  expect((await page.request.get(`/api/people/${other}`)).status()).toBe(200);
  await contextTab.click();
  const result = await (await page.request.get(`/api/people/${person}/context`)).json();
  expect(result.counts).toEqual({ coming_up: 25, guidance_preferences: 1 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
  await page.reload();
  if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic context reader' }).click();
  await contextTab.click();
  await expect(pane.getByRole('button', { name: 'View all (25, 23 more)' })).toBeVisible();
  expect((await (await page.request.get('/api/personal-context-preference')).json()).enabled).toBe(false);
  if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: /Personal context Choose whether/ }).click();
  const consent = page.getByRole('checkbox', { name: 'Use and collect personal context automatically' });
  await expect(consent).not.toBeChecked();
  await consent.check(); await expect(consent).toBeChecked();
  await expect(consent).toBeEnabled(); await consent.uncheck(); await expect(consent).not.toBeChecked();
  await expect(consent).toBeEnabled();
  await page.screenshot({ path: resolve(renders, `consent-${viewport.name}.png`) });
});
