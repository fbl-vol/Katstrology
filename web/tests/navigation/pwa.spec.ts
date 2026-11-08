import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';

async function login(page: Page, owner = 'reader-transit-desktop') {
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByLabel('Message Kat')).toBeVisible();
}
async function menu(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
}

test('native journey restores reader, chart choices and draft without manufacturing history', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 560 });
  await login(page);
  await page.getByLabel('Message Kat').fill('Unsent native journey draft');
  let writes = 0;
  page.on('request', request => { if (request.method() !== 'GET') writes++; });
  await menu(page);
  await page.locator('.create-chart-nav').click();
  await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: /^Natal chart/ }).click();
  await page.getByRole('button', { name: /^Synthetic transit reader/ }).last().click();
  const wheel = page.locator('.profile-active-chart svg.natal-wheel').first();
  await wheel.evaluate(element => element.scrollIntoView({ block: 'center' }));
  const sun = wheel.locator('[data-wheel-entry="sun"]');
  const point = await sun.boundingBox();
  const scroll = await page.evaluate(() => scrollY);
  await page.mouse.click(point!.x + point!.width / 2, point!.y + point!.height / 2);
  const preview = page.getByRole('region', { name: 'Selected chart feature' });
  await expect(preview).toBeVisible();
  if (await preview.getByRole('combobox').count()) {
    await preview.getByRole('combobox').selectOption('sun');
    await preview.getByRole('button', { name: 'Select detail' }).click();
  }
  await preview.getByRole('button', { name: 'Read details' }).click();
  await expect(page.getByRole('heading', { name: 'Sun', exact: true })).toBeFocused();
  const length = await page.evaluate(() => history.length);
  const state = await page.evaluate(() => history.state);
  expect(Object.keys(state).sort()).toEqual(['entry', 'katNavigation']);
  expect(JSON.stringify(state)).not.toMatch(/reader|birth|csrf|Unsent|Sun/);
  await page.goBack();
  await expect(preview.getByRole('button', { name: 'Read details' })).toBeFocused();
  expect(await page.evaluate(() => scrollY)).toBeCloseTo(scroll, 0);
  await page.goForward();
  await expect(page.getByRole('heading', { name: 'Sun', exact: true })).toBeFocused();
  expect(await page.evaluate(() => history.length)).toBe(length);
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Sun', exact: true })).toHaveCount(0);
  await page.goBack();
  await expect(page.getByRole('region', { name: 'Create chart' })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: /^Natal chart/ })).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel('Message Kat')).toHaveValue('Unsent native journey draft');
  await expect(page.locator('.sidebar')).not.toHaveClass(/open/);
  expect(writes).toBe(0);
  mkdirSync('../.local/phone-first/navigation/renders', { recursive: true });
  await page.screenshot({ path: '../.local/phone-first/navigation/renders/returned-draft.png' });
});

test('native root leaves normally and old signed-out entries cannot restore another owner', async ({ page }) => {
  await page.goto('data:text/plain,synthetic previous page');
  await login(page, 'reader-shell');
  await page.goBack();
  await expect(page).toHaveURL(/^data:text\/plain/);
  await page.goForward();
  await expect(page.getByLabel('Message Kat')).toBeVisible();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByLabel('Username')).toBeVisible();
  await page.getByLabel('Username').fill('reader-people');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.locator('.account')).toContainText('reader-people');
  const length = await page.evaluate(() => history.length);
  await page.goBack();
  await expect(page.getByLabel('Message Kat')).toBeVisible();
  await expect(page.locator('.account')).toContainText('reader-people');
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => history.length)).toBe(length);
});

for (const status of [403, 404]) test(`native restoration fails closed for resource ${status}`, async ({ page }) => {
  await login(page);
  const people = await (await page.request.get('/api/people')).json();
  const person = people.people.find((item: { name: string }) => item.name === 'Synthetic transit reader');
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
  await expect(page.locator('#person-heading')).toContainText('Synthetic transit reader');
  await page.getByRole('button', { name: '＋ New conversation', exact: true }).click();
  await page.route(`**/api/people/${person.id}`, route => route.fulfill({ status, json: { error: 'unavailable' } }));
  await page.goBack();
  await expect(page.getByRole('alert')).toContainText('saved view is no longer available');
  await expect(page.locator('.person-page')).toHaveCount(0);
  await expect(page.getByLabel('Message Kat')).toBeVisible();
});

test('a delayed native restoration cannot replace a newer navigation choice', async ({ page }) => {
  await login(page);
  const people = await (await page.request.get('/api/people')).json();
  const person = people.people.find((item: { name: string }) => item.name === 'Synthetic transit reader');
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
  await expect(page.locator('#person-heading')).toContainText('Synthetic transit reader');
  await page.getByRole('button', { name: '＋ New conversation', exact: true }).click();
  let arrived!: () => void, release!: () => void;
  const waiting = new Promise<void>(resolve => { arrived = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**/api/people/${person.id}`, async route => {
    const response = await route.fetch(); arrived(); await held; await route.fulfill({ response });
  });
  await page.goBack(); await waiting;
  await expect(page.getByText('Opening saved view…')).toBeVisible();
  mkdirSync('../.local/phone-first/renders', { recursive: true });
  await page.screenshot({ path: '../.local/phone-first/renders/native-restoration-pending-desktop.png' });
  await page.locator('.create-chart-nav').click();
  await expect(page.getByRole('region', { name: 'Create chart' })).toBeVisible();
  const completed = page.waitForResponse(response => new URL(response.url()).pathname === `/api/people/${person.id}`);
  release(); await completed;
  await expect(page.getByRole('region', { name: 'Create chart' })).toBeVisible();
  await expect(page.locator('.person-page')).toHaveCount(0);
});

test('native Back and Forward retain the existing missing-natal return draft and intent', async ({ page }) => {
  await login(page, 'reader-advanced-ux');
  await page.locator('.create-chart-nav').click();
  await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
  const view = page.getByRole('region', { name: 'Solar return chart' });
  await view.getByLabel('Person with a current natal').selectOption('legacy-transit-person');
  await view.getByLabel('UTC anniversary year').fill('2028');
  await view.getByRole('button', { name: 'Create or review natal' }).click();
  await expect(page.locator('.profile-editor')).toBeVisible();
  await page.goBack();
  await expect(view.getByLabel('UTC anniversary year')).toHaveValue('2028');
  await expect(view.getByLabel('Person with a current natal')).toHaveValue('legacy-transit-person');
  await page.goForward();
  await expect(page.locator('.profile-editor')).toBeVisible();
  await page.getByRole('button', { name: /Return to workspace/ }).click();
  await expect(view.getByLabel('UTC anniversary year')).toHaveValue('2028');
  await expect(view.getByLabel('Person with a current natal')).toHaveValue('legacy-transit-person');
});

test('native restoration checks current session even when only closing a layer', async ({ page }) => {
  await login(page, 'reader-shell');
  await page.getByLabel('Message Kat').fill('Old owner unsent text');
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  const session = await (await page.request.get('/api/session')).json();
  await page.route('**/api/session', route => route.fulfill({ json: { ...session, owner: 'reader-people', csrf: 'synthetic-other-session' } }));
  await page.goBack();
  await expect(page.getByLabel('Username')).toBeVisible();
  await expect(page.getByLabel('Message Kat')).toHaveCount(0);
  await expect(page.locator('.account')).toHaveCount(0);
});

test('explicit library parent close preserves native ancestry and descendant Forward', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  const open = page.getByRole('button', { name: 'Open Natal chart', exact: true });
  await open.click();
  const reader = page.getByRole('region', { name: 'Saved chart reader' });
  const sun = reader.locator('[data-wheel-entry="sun"]');
  await sun.focus(); await sun.press('Enter');
  await expect(reader.getByRole('heading', { name: 'Sun', exact: true })).toBeFocused();
  const length = await page.evaluate(() => history.length);
  await page.getByRole('button', { name: '← Back to chart library' }).click();
  await expect(open).toBeFocused();
  expect(await page.evaluate(() => history.length)).toBe(length);
  await page.goBack();
  await expect(page.getByRole('tab', { name: 'Overview', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.goForward();
  await expect(open).toBeVisible();
  await page.goForward();
  await expect(reader.locator('svg.natal-wheel')).toBeVisible();
  await page.goForward();
  await expect(reader.getByRole('heading', { name: 'Sun', exact: true })).toBeFocused();
  expect(await page.evaluate(() => history.length)).toBe(length);
});

test('native library Forward re-resolves saved bytes and refuses a removed result', async ({ page }) => {
  await login(page);
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  await page.getByRole('button', { name: 'Open Natal chart', exact: true }).click();
  const reader = page.getByRole('region', { name: 'Saved chart reader' });
  await expect(reader.locator('svg.natal-wheel')).toBeVisible();
  const id = await reader.getAttribute('data-result-id');
  const sun = reader.locator('[data-wheel-entry="sun"]');
  await sun.focus(); await sun.press('Enter');
  await expect(reader.getByRole('heading', { name: 'Sun', exact: true })).toBeFocused();
  await page.goBack();
  await expect(sun).toBeFocused();
  await page.goBack();
  await expect(reader).toHaveCount(0);
  await page.goForward();
  await expect(reader.locator('svg.natal-wheel')).toBeVisible();
  await page.goForward();
  await expect(reader.getByRole('heading', { name: 'Sun', exact: true })).toBeFocused();
  await page.goBack(); await page.goBack();
  await expect(reader).toHaveCount(0);
  await page.route(`**/api/charts/${id}`, route => route.fulfill({ status: 404, json: { error: 'not_found' } }));
  await page.goForward();
  await expect(reader.getByRole('alert')).toContainText('could not be loaded');
  mkdirSync('../.local/phone-first/renders', { recursive: true });
  await page.screenshot({ path: '../.local/phone-first/renders/native-result-unavailable-desktop.png' });
  await expect(reader.locator('svg.natal-wheel')).toHaveCount(0);
  await expect(reader.getByText(/saved birth time/)).toHaveCount(0);
});
