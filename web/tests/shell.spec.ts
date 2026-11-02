import { test, expect } from '@playwright/test';
import { personIdFor, seedLegacy } from './legacy-fixture';
import { archivedTurn } from './archive-assertions';

test('local workspace login, honest empty state, protected logout', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Welcome to Kat.' })).toBeVisible();
  await page.getByLabel('Username').fill('reader-shell');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  await expect(page.getByText('No people yet.', { exact: true })).toBeVisible();
  await expect(page.locator('.model-label')).toContainText(/ChatGPT connected|Connect ChatGPT plan to send/);
  await expect(page.locator('header')).not.toContainText('gpt-6.1-sol');
  await page.getByRole('button', { name: 'Settings' }).click();
  const connection = page.getByRole('region', { name: 'Model connection' });
  await expect(connection.getByText(/Plan permission granted|connection is disabled/)).toBeVisible();
  await page.getByRole('button', { name: 'Back to workspace' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome to Kat.' })).toBeVisible();
});

test('an oversized escaped draft is not sent or cleared', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-escaped-boundary');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  const attempted: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/conversations(?:\/[^/]+\/turns)?$/.test(new URL(request.url()).pathname))
      attempted.push(request.url());
  });
  const draft = 'Q' + '\t'.repeat(64 * 1024);
  const composer = page.getByLabel('Message Kat');
  await composer.fill(draft);
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByText('This message is longer than 64 KiB. Shorten it before sending; your draft is still here.')).toBeVisible();
  await expect(composer).toHaveValue(draft);
  expect(attempted).toEqual([]);
});

test('an unreferenced synthetic legacy file can be deleted without deleting its person', async ({ page }) => {
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-handoff-file');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic file-only person/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  const person = page.locator('.profile-secondary').filter({ has: page.locator('summary', { hasText: 'Historical chart files' }) });
  await person.locator(':scope > summary').click();
  await expect(person.getByText('unreferenced.pdf')).toBeVisible();
  const response = page.waitForResponse(result => result.request().method() === 'DELETE' &&
    /\/api\/people\/[^/]+\/files\/[^/]+$/.test(new URL(result.url()).pathname));
  await person.getByRole('button', { name: 'Delete', exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(person.getByText('No chart files attached.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Synthetic file-only person' })).toBeVisible();
});

test('legacy draft and Sun-only chart remain visible without becoming the active natal', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-people');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('Name').fill('Synthetic Robin');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic Robin' })).toBeVisible();
  const personId = await personIdFor(page, 'Synthetic Robin');
  const legacy = await seedLegacy(page, personId, { kind: 'solar', unknown: true });
  await page.reload();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic Robin/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  await page.locator('.chart-history > summary').click();
  await expect(page.getByText(/Time unknown · Unverified city/)).toBeVisible();
  await expect(page.locator(`.chart-history > details[data-kat-chart-id="${legacy.chartId}"] > summary`)).toContainText('Historical chart');
  await page.reload();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic Robin/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  await expect(page.getByText('No active generated natal. Nothing is guessed from a draft, an old chart or a file.')).toBeVisible();
  await page.locator('.chart-history > summary').click();
  const chart = page.locator(`.chart-history > details[data-kat-chart-id="${legacy.chartId}"] > summary`);
  await expect(chart).toContainText('Historical chart');
  const chartId = legacy.chartId;
  await page.getByRole('tab', { name: 'Basic info' }).click();
  await page.getByRole('button', { name: 'New conversation about Synthetic Robin' }).click();
  await expect(page.locator('.person-chip')).not.toContainText('current natal');
  await page.getByLabel('Message Kat').fill(`Do not silently select historical chart ${chartId}`);
  const sent = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
  await page.getByRole('button', { name: 'Send message' }).click();
  expect((await sent).status()).toBe(202);
  expect((await archivedTurn(page, page.locator('.turn-card').last())).selected_people[0].chart_id).toBeNull();
});

test('one shared thread is listed under both selected people, never under general-only history', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-shared');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  for (const name of ['Synthetic One', 'Synthetic Two']) {
    await page.getByRole('button', { name: 'Add person', exact: true }).click();
    const form = page.getByRole('dialog', { name: 'A space for someone new.' });
    await form.getByLabel('Name').fill(name);
    await form.getByRole('button', { name: 'Create person' }).click();
    await expect(form).toBeHidden();
  }
  const recent = page.getByRole('navigation', { name: 'Recent conversations' });
  await page.locator('button.new-chat').click();
  await page.getByLabel('Message Kat').fill('Synthetic general thread');
  const generalAck = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
  await page.getByRole('button', { name: 'Send message' }).click();
  expect((await generalAck).status()).toBe(202);
  await expect(recent.getByText('General')).toBeVisible();
  await page.locator('button.new-chat').click();
  await page.getByRole('button', { name: '＋ Add person' }).click();
  const picker = page.getByRole('dialog', { name: 'Who’s this about?' });
  await picker.getByRole('checkbox', { name: 'Synthetic One' }).check();
  await picker.getByRole('checkbox', { name: 'Synthetic Two' }).check();
  await picker.getByRole('button', { name: 'Use selection' }).click();
  await expect(page.getByRole('button', { name: 'Remove Synthetic One from new turn' })).toBeVisible();
  await page.getByLabel('Message Kat').fill('Synthetic shared thread');
  const sharedAck = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
  await page.getByRole('button', { name: 'Send message' }).click();
  expect((await sharedAck).status()).toBe(202);
  await expect(recent.getByText('Synthetic One & Synthetic Two')).toBeVisible();
  await page.getByRole('button', { name: /Synthetic One/ }).first().click();
  await expect(recent.getByText('General')).toHaveCount(0);
  await expect(recent.getByText('Synthetic One & Synthetic Two')).toBeVisible();
  await page.getByRole('button', { name: /Synthetic Two/ }).first().click();
  await expect(recent.getByText('General')).toHaveCount(0);
  await expect(recent.getByText('Synthetic One & Synthetic Two')).toBeVisible();
});

test('committed hosted fixture reply, archive reload, edit and correction preserve originals', async ({ page }) => {
  test.skip(process.env.KAT_BROWSER_FAKE_PLAN !== '1', 'Requires synthetic plan fixture');
  test.setTimeout(120000);
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-shell-chat');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByLabel('Message Kat').fill('Synthetic hello. Reply in one sentence.');
  await page.getByRole('button', { name: 'Send message' }).click();
  const turns = page.locator('.turn-card');
  await expect(turns).toHaveCount(1);
  await expect(turns.first()).toHaveAttribute('data-kat-status', 'complete', { timeout: 90000 });
  await expect(turns.first().locator('.assistant-answer p')).not.toBeEmpty();
  expect((await archivedTurn(page, turns.first())).events.some(event => event.kind === 'context')).toBe(true);
  await expect(turns.first().getByText('Context & sources')).toHaveCount(0);
  await expect(turns.first().getByText('Message details')).toHaveCount(0);
  await page.reload();
  await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button', { name: /Chart conversation topics|New conversation/ }).click();
  await expect(turns.first().getByText('Synthetic hello. Reply in one sentence.')).toBeVisible();
  await turns.first().getByRole('button', { name: 'Edit input' }).click();
  await expect(page.locator('.edit-note')).toContainText('The original remains saved.');
  await expect(page.locator('.edit-note')).not.toContainText((await turns.first().getAttribute('data-kat-turn-id'))!);
  await expect(page.getByLabel('Message Kat')).toHaveValue('Synthetic hello. Reply in one sentence.');
  await page.getByLabel('Message Kat').fill('Edited synthetic hello. Reply briefly.');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(turns).toHaveCount(2);
  await expect(turns.last()).toHaveAttribute('data-kat-status', 'complete', { timeout: 90000 });
  await expect(turns.first().getByText('Synthetic hello. Reply in one sentence.')).toBeVisible();
  await turns.first().getByRole('button', { name: 'Correct or withdraw' }).click();
  await turns.first().getByLabel('Correct the record').fill('Synthetic correction note');
  await turns.first().getByRole('button', { name: 'Save correction' }).click();
  await expect(turns.first().getByText('Correction: Synthetic correction note')).toBeVisible();
  await page.getByLabel('Message Kat').fill('SyntheticTransportFailureFixture');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(turns.last()).toHaveAttribute('data-kat-status', 'error');
  await expect(page.getByLabel('Message Kat')).toHaveValue('');
  await expect(turns.last().getByRole('button', { name: 'Try again as a new message with current selection' })).toBeVisible();
});

test('person deletion is fenced by its shared conversation until the original thread is removed', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-delete');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const form = page.getByRole('dialog', { name: 'A space for someone new.' });
  await form.getByLabel('Name').fill('Synthetic To Remove');
  await form.getByRole('button', { name: 'Create person' }).click();
  await page.getByRole('tab', { name: 'Basic info' }).click();
  await page.getByRole('button', { name: 'New conversation about Synthetic To Remove' }).click();
  await page.getByLabel('Message Kat').fill('Synthetic person deletion dependency');
  const deletionAck = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
  await page.getByRole('button', { name: 'Send message' }).click();
  expect((await deletionAck).status()).toBe(202);
  await page.getByRole('button', { name: /Synthetic To Remove/ }).first().click();
  await page.getByRole('tab', { name: 'Basic info' }).click();
  await page.locator('.profile-secondary > summary').filter({ hasText: 'Remove this person' }).click();
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Delete this person' }).click();
  await expect(page.getByRole('alert')).toContainText('Delete related conversations first');
  await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
  page.once('dialog', dialog => dialog.accept());
  await page.getByText('Conversation options').click();
  await page.getByRole('button', { name: 'Delete conversation' }).click();
  await page.getByRole('button', { name: /Synthetic To Remove/ }).first().click();
  await page.getByRole('tab', { name: 'Basic info' }).click();
  await page.locator('.profile-secondary > summary').filter({ hasText: 'Remove this person' }).click();
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Delete this person' }).click();
  await expect(page.getByText('No people yet.', { exact: true })).toBeVisible();
});

test('local pending is honest before create and ACK; sidebar refresh never gates send', async ({ page }) => {
  test.setTimeout(60000);
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-local-pending');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();

  let releaseCreate!: () => void;
  let createStarted!: () => void;
  const createGate = new Promise<void>(resolve => { releaseCreate = resolve; });
  const createSeen = new Promise<void>(resolve => { createStarted = resolve; });
  let sidebarHeld = false;
  let releaseSidebar!: () => void;
  let sidebarStarted!: () => void;
  const sidebarGate = new Promise<void>(resolve => { releaseSidebar = resolve; });
  const sidebarSeen = new Promise<void>(resolve => { sidebarStarted = resolve; });
  let releaseAck!: () => void;
  let ackStarted!: () => void;
  const ackGate = new Promise<void>(resolve => { releaseAck = resolve; });
  const ackSeen = new Promise<void>(resolve => { ackStarted = resolve; });
  await page.route('**/api/conversations', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    createStarted();
    await createGate;
    const response = await route.fetch();
    sidebarHeld = true;
    await route.fulfill({ response });
  });
  await page.route('**/api/conversations?offset=0', async route => {
    if (!sidebarHeld) { await route.continue(); return; }
    sidebarStarted();
    await sidebarGate;
    await route.continue();
  });
  await page.route('**/api/conversations/*/turns', async route => {
    const response = await route.fetch();
    ackStarted();
    await ackGate;
    await route.fulfill({ response });
  });

  await page.getByLabel('Message Kat').fill('Synthetic pending question');
  await page.getByRole('button', { name: 'Send message' }).click();
  await createSeen;
  const pending = page.getByRole('status', { name: 'Message being sent' });
  await expect(pending).toContainText('Synthetic pending question');
  await expect(pending).toContainText('Sending…');
  const turnId = await pending.getAttribute('data-kat-pending-turn-id');
  expect(turnId).toMatch(/^turn-/);
  await expect(page.locator('.turn-card')).toHaveCount(0);
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.screenshot({ path: '../.local/application-performance/pending-desktop.png' });
  await page.setViewportSize({ width: 390, height: 560 });
  await expect(pending).toBeVisible();
  const mobileGeometry = await page.evaluate(() => {
    const local = document.querySelector('.local-pending')!.getBoundingClientRect();
    const composer = document.querySelector('.composer-wrap')!.getBoundingClientRect();
    return { pendingTop: local.top, pendingBottom: local.bottom, composerTop: composer.top };
  });
  expect(mobileGeometry.pendingBottom).toBeLessThanOrEqual(mobileGeometry.composerTop);
  await page.screenshot({ path: '../.local/application-performance/pending-short-mobile.png' });

  releaseCreate();
  await Promise.all([sidebarSeen, ackSeen]); // Neither request waits for the other response.
  await expect(pending).toBeVisible();
  await expect(page.locator('.turn-card')).toHaveCount(0);
  releaseAck();
  await expect(page.locator(`.turn-card[data-kat-turn-id="${turnId}"]`)).toHaveCount(1);
  await expect(pending).toHaveCount(0);
  await expect(page.locator('.turn-card .user-bubble')).toHaveText('Synthetic pending question');
  releaseSidebar();
});

test('a delayed archived ACK cannot clear a new conversation draft', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-race');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  let reportReady!: () => void;
  let release!: () => void;
  const ready = new Promise<void>(resolve => { reportReady = resolve; });
  const hold = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/conversations/*/turns', async route => {
    const archived = await route.fetch();
    reportReady();
    await hold;
    await route.fulfill({ response: archived });
  });
  await page.getByLabel('Message Kat').fill('Synthetic first input');
  await page.getByRole('button', { name: 'Send message' }).click();
  await ready;
  await page.getByRole('button', { name: 'katstrology. — New conversation' }).click();
  await page.getByLabel('Message Kat').fill('Keep this new draft');
  const response = page.waitForResponse(value => value.url().includes('/turns') && value.request().method() === 'POST');
  release();
  await response;
  await expect(page.getByLabel('Message Kat')).toHaveValue('Keep this new draft');
});

test('a new draft typed during delayed conversation creation survives its acknowledgement and error', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-create-race');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();

  let created!: () => void;
  let release!: () => void;
  const waiting = new Promise<void>(resolve => { created = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/conversations', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const response = await route.fetch(); // The server creates the actual synthetic thread.
    created();
    await held;
    await route.fulfill({ response });
  });

  await page.getByLabel('Message Kat').fill('SyntheticTransportFailureFixture');
  await page.getByRole('button', { name: 'Send message' }).click();
  await waiting;
  await page.getByLabel('Message Kat').fill('Newly typed while saving');
  await expect(page.getByRole('button', { name: 'Send message' })).toBeDisabled();
  release();

  await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'error');
  await expect(page.locator('.turn-card')).toHaveCount(1);
  await expect(page.locator('.user-bubble')).toHaveText('SyntheticTransportFailureFixture');
  await expect(page.getByLabel('Message Kat')).toHaveValue('Newly typed while saving');
});

test('mobile navigation stays over the chat and restores keyboard focus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-mobile');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  const menu = page.getByRole('button', { name: 'Open navigation' });
  await menu.click();
  await expect(menu).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('navigation', { name: 'People' })).toBeVisible();
  await page.getByRole('button', { name: 'Close navigation' }).last().click();
  await expect(menu).toBeFocused();
  await expect(menu).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('body')).toHaveJSProperty('scrollWidth', 390);
});
