import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const password = 'synthetic-signup-password';
const views = [
  { name: 'desktop', width: 1440, height: 1024 }, { name: 'wide', width: 2560, height: 1080 },
  { name: 'mobile', width: 390, height: 844 }, { name: 'short-mobile', width: 390, height: 560 },
  { name: 'tablet', width: 768, height: 1024 },
];
const renders = resolve('..', '.local', 'lan-account-creation', 'renders');
mkdirSync(renders, { recursive: true });

async function capture(page: Page, state: string, view: string) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: resolve(renders, `${state}-${view}.png`), fullPage: true });
}
async function network(page: Page, kind = 'lan') {
  // Fixture-only transport metadata and clock; production ignores these headers.
  await page.setExtraHTTPHeaders({ 'X-Kat-Test-Signup-Network': kind,
    'X-Kat-Test-Signup-Clock': String(Date.now()) });
}
async function fill(page: Page, username: string) {
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByLabel('Confirm password', { exact: true }).fill(password);
}

for (const view of views) {
  test(`LAN creates empty account then ordinary sign-in ${view.name}`, async ({ page }) => {
    await page.setViewportSize(view); await network(page);
    let releaseCheck!: () => void;
    const check = new Promise<void>(resolve => { releaseCheck = resolve; });
    await page.route('**/api/signup', async route => {
      if (route.request().method() === 'GET') await check;
      await route.continue();
    });
    await page.goto('/');
    await expect(page.getByRole('button', { name: 'Create account', exact: true })).toBeDisabled();
    await expect(page.getByText('Checking where account creation is available…')).toBeVisible();
    await capture(page, 'checking', view.name);
    releaseCheck();
    await expect(page.getByRole('button', { name: 'Create account', exact: true })).toBeEnabled();
    await capture(page, 'available', view.name);
    await page.getByRole('button', { name: 'Create account', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Create your account.' })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.getByLabel('Username')).toBeFocused();
    await capture(page, 'form', view.name);
    const username = `signup-${view.name}-${Date.now()}`;
    await fill(page, username);
    await page.getByLabel('Confirm password').fill('different-password');
    await page.getByRole('button', { name: 'Create account', exact: true }).click();
    await expect(page.getByLabel('Confirm password')).toBeFocused();
    await expect(page.getByText('The passwords don’t match.', { exact: false })).toBeVisible();
    await capture(page, 'mismatch', view.name);
    await page.getByLabel('Confirm password').fill(password);
    await page.getByRole('button', { name: 'Show passwords' }).click();
    await expect(page.getByLabel('Password', { exact: true })).toHaveAttribute('type', 'text');
    await page.getByRole('button', { name: 'Hide passwords' }).click();
    let releasePost!: () => void;
    const post = new Promise<void>(resolve => { releasePost = resolve; });
    await page.route('**/api/signup', async route => {
      if (route.request().method() === 'POST') await post;
      await route.continue();
    });
    await page.getByRole('button', { name: 'Create account', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Creating account…' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Back to sign in' })).toBeDisabled();
    await expect(page.getByLabel('Username')).toBeDisabled();
    await capture(page, 'pending', view.name); releasePost();
    await expect(page.getByText('Your account is ready.')).toBeVisible();
    await expect(page.getByLabel('Username')).toHaveValue(username);
    await expect(page.getByLabel('Password', { exact: true })).toHaveValue('');
    await expect(page.getByLabel('Password', { exact: true })).toBeFocused();
    expect((await page.request.get('/api/session')).status()).toBe(401);
    await capture(page, 'created', view.name);
    await page.getByLabel('Password', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await expect(page.getByRole('textbox', { name: 'Message Kat', exact: true })).toBeVisible();
    expect((await (await page.request.get('/api/session')).json()).owner).toBe(username);
    expect((await (await page.request.get('/api/people')).json()).people).toEqual([]);
    expect((await (await page.request.get('/api/siwc/status')).json()).connected).toBe(false);
    expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain(password);
  });

  test(`public unknown and changed network remain closed ${view.name}`, async ({ page }) => {
    await page.setViewportSize(view); await page.goto('/');
    await expect(page.getByRole('button', { name: 'Create account', exact: true })).toBeDisabled();
    await expect(page.getByText('Account creation is only available on the home network.', { exact: false })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open workspace' })).toBeEnabled();
    await capture(page, 'public', view.name);
    await page.route('**/api/signup', route => route.abort()); await page.reload();
    await expect(page.getByText('Account creation couldn’t be checked.', { exact: false })).toBeVisible();
    await capture(page, 'unverified', view.name);
    await page.unroute('**/api/signup'); await network(page);
    await page.getByRole('button', { name: 'Check again' }).click();
    await expect(page.getByRole('button', { name: 'Create account', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Create account', exact: true }).click();
    await fill(page, `blocked-${view.name}`); await network(page, 'public');
    const denied = page.waitForResponse(response => response.url().endsWith('/api/signup') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Create account', exact: true }).click();
    expect((await denied).status()).toBe(403);
    await expect(page.getByText('Account creation isn’t available here.', { exact: false })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create account', exact: true })).toBeDisabled();
    await capture(page, 'network-changed', view.name);
    await page.getByRole('button', { name: 'Back to sign in' }).click();
    await expect(page.getByLabel('Username')).toHaveValue(`blocked-${view.name}`);
    await expect(page.getByRole('button', { name: 'Open workspace' })).toBeEnabled();
  });

  test(`lost acknowledgement recovers same account by sign-in ${view.name}`, async ({ page }) => {
    await page.setViewportSize(view); await network(page); await page.goto('/');
    await page.getByRole('button', { name: 'Create account', exact: true }).click();
    const username = `uncertain-${view.name}-${Date.now()}`;
    await fill(page, username);
    let posts = 0;
    await page.route('**/api/signup', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      posts++;
      expect((await route.fetch()).status()).toBe(201); // Real write, then lose the acknowledgement.
      await route.abort();
    });
    await page.getByRole('button', { name: 'Create account', exact: true }).click();
    await expect(page.getByText('Account creation wasn’t confirmed.', { exact: false })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create account', exact: true })).toHaveCount(0);
    await capture(page, 'uncertain', view.name);
    await page.locator('button.primary').click();
    await expect(page.getByLabel('Username')).toHaveValue(username);
    await page.getByLabel('Password', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await expect(page.getByRole('textbox', { name: 'Message Kat', exact: true })).toBeVisible();
    expect(posts).toBe(1);
  });
}

test('forged availability cannot bypass direct TCP denial; remote login survives', async ({ page }) => {
  await page.route('**/api/signup', route => route.request().method() === 'GET' ?
    route.fulfill({ json: { available: true } }) : route.continue());
  await page.goto('/'); await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await fill(page, 'forged-capability');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByText('Account creation isn’t available here.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Back to sign in' }).click();
  await page.getByLabel('Username').fill('reader-shell');
  await page.getByLabel('Password', { exact: true }).fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('textbox', { name: 'Message Kat', exact: true })).toBeVisible();
});

test('Midnight Pine adapts signup and Back retains the username', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'midnight-pine'));
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Create account', exact: true })).toBeDisabled();
  await capture(page, 'public', 'midnight-pine-mobile');
  await network(page); await page.reload();
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await capture(page, 'form', 'midnight-pine-mobile');
  await page.getByLabel('Username').fill('retained-name');
  await page.getByRole('button', { name: 'Back to sign in' }).click();
  await expect(page.getByLabel('Username')).toHaveValue('retained-name');
  await expect(page.getByRole('heading', { name: 'Welcome to Kat.' })).toBeFocused();
});

test('malformed capability and failed signup responses never invent success', async ({ page }) => {
  await page.route('**/api/signup', route => route.fulfill({ json: { available: 'true' } }));
  await page.goto('/');
  await expect(page.getByText('Account creation couldn’t be checked.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create account', exact: true })).toBeDisabled();
  await page.unroute('**/api/signup'); await network(page);
  await page.getByRole('button', { name: 'Check again' }).click();
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await fill(page, 'failed-response');
  let posts = 0;
  await page.route('**/api/signup', async route => {
    posts++;
    await route.fulfill({ status: posts === 1 ? 400 : 500, json: { error: 'unavailable' } });
  });
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByText('Check the username and passwords.', { exact: false })).toBeVisible();
  await expect(page.getByLabel('Username')).toHaveValue('failed-response');
  await expect(page.getByLabel('Password', { exact: true })).toHaveValue(password);
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByText('Account creation wasn’t confirmed.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create account', exact: true })).toHaveCount(0);
  await expect(page.getByText('Your account is ready.')).toHaveCount(0);
  expect(posts).toBe(2);
});

test('duplicate and rate-limited creation preserve username without blind retry', async ({ page }) => {
  await network(page); await page.goto('/');
  await page.getByRole('button', { name: 'Create account', exact: true }).click(); await fill(page, 'reader-shell');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByText('Account creation wasn’t confirmed.', { exact: false })).toBeVisible();
  await page.locator('button.primary').click();
  await expect(page.getByLabel('Username')).toHaveValue('reader-shell');
  await page.getByRole('button', { name: 'Create account', exact: true }).click(); await fill(page, 'reader-shell');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByText('Please wait at least ten seconds', { exact: false })).toBeVisible();
  await expect(page.getByLabel('Username')).toHaveValue('reader-shell');
});
