import { expect, test, type Page } from '@playwright/test';

async function signIn(page: Page, owner: string) {
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
}

test('normal Reading Room loads bounded saved pages before allowing another send from the current head', async ({ page }) => {
  await signIn(page, 'reader-paged-normal');
  await page.getByRole('navigation', { name: 'Recent conversations' })
    .getByRole('button', { name: /A paged synthetic conversation/ }).click();
  await expect(page.locator('.turn-card')).toHaveCount(20);
  await expect(page.getByRole('status')).toContainText('current saved message is on another page');
  await page.getByLabel('Message Kat').fill('Must not send from incomplete history');
  await expect(page.getByRole('button', { name: 'Send message' })).toBeDisabled();
  await page.getByRole('button', { name: 'Load more saved messages' }).click();
  await expect(page.locator('.turn-card')).toHaveCount(21);
  await expect(page.getByRole('status')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled();
  await expect(page.locator('.turn-card').last()).toContainText('Synthetic archived page 20');
});

test('normal Reading Room never restores a prior thread after a late saved-turn lookup', async ({ page }) => {
  await signIn(page, 'reader-paged-normal');
  let requested!: () => void;
  let release!: () => void;
  const waiting = new Promise<void>(resolve => { requested = resolve; });
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/conversations/*/turns/*', async route => {
    if (route.request().method() !== 'GET' || route.request().url().includes('/events')) {
      await route.continue(); return;
    }
    const response = await route.fetch(); requested(); await gate;
    await route.fulfill({ response });
  });
  await page.getByRole('navigation', { name: 'Recent conversations' })
    .getByRole('button', { name: /A paged synthetic conversation/ }).click();
  await waiting;
  await page.getByRole('button', { name: 'New conversation' }).first().click();
  await page.getByLabel('Message Kat').fill('A new unrelated draft');
  release();
  await expect(page.locator('.header-title')).toHaveText('New conversation');
  await expect(page.getByLabel('Message Kat')).toHaveValue('A new unrelated draft');
  await expect(page.locator('.turn-card')).toHaveCount(0);
});

test('normal Reading Room shows committed prefix and interruption after cancellation and reload', async ({ page }) => {
  await signIn(page, 'reader-instant-normal');
  await page.getByLabel('Message Kat').fill('Synthetic slow cancel');
  await page.getByRole('button', { name: 'Send message' }).click();
  const turn = page.locator('.turn-card');
  await expect(turn.locator('.assistant-answer')).toContainText('Synthetic committed prefix', { timeout: 15000 });
  await page.getByRole('button', { name: 'Stop response' }).click();
  await expect(turn).toHaveAttribute('data-kat-status', 'interrupted', { timeout: 15000 });
  await expect(turn.locator('.turn-warning')).toContainText('committed prefix is preserved');
  await page.reload();
  await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry > button').first().click();
  await expect(turn).toHaveAttribute('data-kat-status', 'interrupted');
  await expect(turn.locator('.assistant-answer')).toContainText('Synthetic committed prefix');
});

test('normal Reading Room leaves submitted HTML literal and does not fetch remote media', async ({ page }) => {
  let external = 0;
  await page.route('**/*', route => {
    const host = new URL(route.request().url()).hostname;
    if (host === '127.0.0.1' || host === '127.0.0.2') return route.continue();
    external++;
    return route.abort();
  });
  await signIn(page, 'reader-instant-error');
  const literal = '<img src="https://example.org/never-fetch" onerror="alert(1)">';
  await page.getByLabel('Message Kat').fill(`Synthetic literal ${literal}`);
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.locator('.turn-card .user-bubble')).toContainText(literal);
  await expect(page.locator('.turn-card img')).toHaveCount(0);
  await expect(page.locator('.turn-card')).toHaveAttribute('data-kat-status', 'complete');
  expect(external).toBe(0);
});
