import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { archivedTurn } from '../support/archive-assertions';
import { openManualTransits, leaveManualTransits } from '../support/navigation-helpers';

function origins() {
  const baseURL = test.info().project.use.baseURL;
  if (!baseURL) throw new Error('An isolated browser baseURL is required');
  const origin = new URL(baseURL).origin;
  const port = Number(new URL(baseURL).port);
  return { origin, provider: `http://127.0.0.2:${port === 65535 ? port - 1 : port + 1}`,
    hostile: `http://127.0.0.1:${port > 65533 ? port - 2 : port + 2}` };
}

async function syntheticNavigation(context: BrowserContext, origin: string, provider: string, hostile: string) {
  // Install before opening the app. Only the two loopback sites may be reached;
  // the synthetic provider is a separate disposable HTTP server on 127.0.0.2.
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin === origin || url.origin === provider) { await route.continue(); return; }
    if (url.origin === hostile && url.pathname === '/') {
      await route.fulfill({ status: 200, contentType: 'text/html', body:
        `<form method="post" action="${origin}/auth/chatgpt/start"><input name="csrf" value="invalid"><input name="client_id" value=""><button>Submit hostile form</button></form>` });
      return;
    }
    await route.abort();
  });
}

async function openSyntheticSignIn(page: Page, owner: string) {
  const { origin, provider } = origins();
  const home = await page.goto('/');
  const csp = home!.headers()['content-security-policy'];
  expect(csp).toContain(`form-action 'self' ${provider}`);
  expect(csp).not.toContain('https://auth.openai.com');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  if ((page.viewportSize()?.width || 900) < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  const connection = page.getByRole('region', { name: 'Model connection' });
  // A previous scenario may have connected this synthetic owner; the same flow reconnects it.
  const connect = connection.getByRole('button', { name: /^(Connect ChatGPT plan|Reconnect ChatGPT account)$/ });
  await expect(connect).toBeVisible();
  const started = page.waitForResponse(response =>
    response.url() === `${origin}/auth/chatgpt/start` && response.request().method() === 'POST');
  await connect.click();
  const start = await started;
  expect(start.request().headers()['origin']).toBe(origin);
  expect(start.status()).toBe(303);
  expect(start.headers()['referrer-policy']).toBe('no-referrer');
  const destination = new URL(start.headers()['location']);
  expect(destination.origin).toBe(provider);
  expect(destination.pathname).toBe('/authorize');
  expect(destination.searchParams.get('state')).toBeTruthy();
  expect(destination.searchParams.get('code_challenge')).toBeTruthy();
  await page.waitForURL(`${provider}/authorize?*`);
}

async function returnFromProvider(page: Page, action: string, outcome: string) {
  const { origin } = origins();
  const callback = page.waitForResponse(response => response.url().startsWith(`${origin}/auth/chatgpt/callback?`));
  const landing = page.waitForResponse(response => response.url().startsWith(`${origin}/?connection=`));
  // The app clears the one-time URL marker promptly after landing; register
  // the navigation observer before clicking, rather than waiting after load.
  const homeNavigation = page.waitForURL(`${origin}/?connection=${outcome}`, { waitUntil: 'commit' });
  await page.getByRole('link', { name: action }).click();
  const returned = await callback;
  const home = await landing;
  expect(returned.status()).toBe(303);
  expect(returned.headers()['referrer-policy']).toBe('no-referrer');
  expect((await home.request().allHeaders())['sec-fetch-site']).toBe('cross-site');
  expect(home.status()).toBe(200);
  await homeNavigation;
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  return returned.url();
}

test('signed synthetic callback lands in the existing workspace; cross-site mutations still fail', async ({ page, context }) => {
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  await openSyntheticSignIn(page, 'reader-siwc');
  const callbackUrl = await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  const connected = page.getByRole('region', { name: 'Model connection' });
  await expect(connected.getByText(/Connected · Selected account: synthetic@example.invalid/)).toBeVisible();
  await expect(connected.getByRole('button', { name: 'Reconnect ChatGPT account' })).toHaveClass(/quiet-action/);
  await expect(connected.getByRole('button', { name: 'Connect ChatGPT plan', exact: true })).toHaveCount(0);
  await expect(page.locator('.model-label')).toHaveText('ChatGPT connected');
  mkdirSync(resolve(import.meta.dirname, '../../../.local/ux-followup'), { recursive: true });
  await page.screenshot({ path: resolve(import.meta.dirname, '../../../.local/ux-followup/provider-connected-desktop.png') });
  await page.setViewportSize({ width: 390, height: 560 });
  await page.screenshot({ path: resolve(import.meta.dirname, '../../../.local/ux-followup/provider-connected-short-mobile.png') });
  await page.goto(callbackUrl); // one-time state was consumed
  await page.waitForURL(`${origin}/?connection=failed`);

  await page.goto(`${hostile}/`);
  const hostileResponse = page.waitForResponse(response => response.url() === `${origin}/auth/chatgpt/start`);
  await page.getByRole('button', { name: 'Submit hostile form' }).click();
  const denied = await hostileResponse;
  expect(denied.request().headers()['origin']).toBe(hostile);
  expect(denied.status()).toBe(403);
  expect(await denied.json()).toEqual({ error: 'local_origin_required' });

  const opaque = await context.newPage();
  await opaque.setContent(`<form method="post" action="${origin}/auth/chatgpt/start"><input name="csrf" value="invalid"><input name="client_id" value=""><button>Submit opaque form</button></form>`);
  const opaqueResponse = opaque.waitForResponse(response => response.url() === `${origin}/auth/chatgpt/start`);
  await opaque.getByRole('button', { name: 'Submit opaque form' }).click();
  const deniedOpaque = await opaqueResponse;
  expect(deniedOpaque.request().headers()['origin']).toBe('null');
  expect(deniedOpaque.status()).toBe(403);
  expect(await deniedOpaque.json()).toEqual({ error: 'local_origin_required' });
  await opaque.close();
});

test('identity-only callback lands, but never enables plan mode', async ({ page, context }) => {
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  await openSyntheticSignIn(page, 'reader-siwc-identity');
  await returnFromProvider(page, 'Complete synthetic sign-in', 'identity_only');
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  const identity = page.getByRole('region', { name: 'Model connection' });
  await expect(identity.getByText(/Identity only; plan use not permitted/)).toBeVisible();
  await expect(identity.getByRole('button', { name: 'Connect ChatGPT plan', exact: true })).toHaveClass(/primary/);
  await expect(page.locator('header').getByText('Connect ChatGPT plan to send')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: resolve(import.meta.dirname, '../../../.local/ux-followup/provider-identity-mobile.png') });
});

test('unconfirmed connection status is not presented as disabled or connected', async ({ page }) => {
  await page.route('**/api/siwc/status', route => route.fulfill({ status: 503,
    contentType: 'application/json', body: '{"error":"temporarily_unavailable"}' }));
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-siwc');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.locator('.model-label')).toHaveText('ChatGPT connection unavailable');
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  const connection = page.getByRole('region', { name: 'Model connection' });
  await expect(connection.getByText(/Connection status is unavailable/)).toBeVisible();
  await expect(connection.getByText(/Connection status could not be confirmed/)).toBeVisible();
  await expect(connection.getByRole('button', { name: 'Reconnect ChatGPT account' })).toHaveCount(0);
});

test('disconnected Settings offers Connect without starting authentication', async ({ page, context }) => {
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  let authStarts = 0;
  page.on('request', request => { if (request.url().endsWith('/auth/chatgpt/start')) authStarts++; });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-siwc-failure');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  const connection = page.getByRole('region', { name: 'Model connection' });
  await expect(connection.getByRole('button', { name: 'Connect ChatGPT plan', exact: true })).toHaveClass(/primary/);
  await expect(connection.getByRole('button', { name: 'Reconnect ChatGPT account' })).toHaveCount(0);
  expect(authStarts).toBe(0);
  await page.setViewportSize({ width: 390, height: 560 });
  await page.screenshot({ path: resolve(import.meta.dirname, '../../../.local/ux-followup/provider-disconnected-short-mobile.png') });
});

test('wrong state and a forged success marker cannot authenticate a provider account', async ({ page, context }) => {
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  await openSyntheticSignIn(page, 'reader-siwc-failure');
  await returnFromProvider(page, 'Submit wrong state', 'failed');
  await page.goto(`${origin}/?connection=connected`); // display hint is not authority
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  await expect(page.getByRole('region', { name: 'Model connection' }).getByText(/Selected account:/)).toHaveCount(0);
  await expect(page.locator('header').getByText('Connect ChatGPT plan to send')).toBeVisible();
});

test.beforeAll(() => {
  mkdirSync(resolve(import.meta.dirname, '../../../.local/budget-ui'), { recursive: true });
  mkdirSync(resolve(import.meta.dirname, '../../../.local/remaining-ui'), { recursive: true });
});

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024, owner: 'reader-grounded-desktop' },
  { name: 'mobile', width: 390, height: 844, owner: 'reader-grounded-mobile' },
  { name: 'short-mobile', width: 390, height: 560, owner: 'reader-grounded-short-mobile' },
  { name: 'wide', width: 2560, height: 1080, owner: 'reader-grounded-wide' },
]) {
  test(`model-requested archived history, chart and passage roundtrip on ${viewport.name}`, async ({ page, context }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const { origin, provider, hostile } = origins();
    await syntheticNavigation(context, origin, provider, hostile);
    await openSyntheticSignIn(page, viewport.owner);
    await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
    if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Add person', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
    await dialog.getByLabel('Name').fill(`Synthetic grounded ${viewport.name}`);
    await dialog.getByRole('button', { name: 'Create person' }).click();
    const form = page.getByRole('region', { name: 'Generate a chart' });
    await form.getByLabel('Birth date').fill('2024-03-20');
    await form.getByLabel('Birth time').fill('03:06');
    await form.getByLabel('Birthplace search').fill('Copenhagen');
    await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
    const posted = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
    await form.getByRole('button', { name: 'Generate chart' }).click();
    expect((await posted).status()).toBe(201);
    await page.getByRole('tab', { name: 'Overview' }).click();
    await page.getByRole('button', { name: 'Start conversation' }).click();
    await expect(page.locator('.person-chip')).toContainText('current natal');
    await page.getByLabel('Message Kat').fill('Synthetic grounded read rounds: What did I say about northern lantern, what does this saved chart show, and what does the synthetic source say?');
    await page.getByRole('button', { name: 'Send message' }).click();
    const turn = page.locator('.turn-card').last();
    await expect(turn).toHaveAttribute('data-kat-status', 'complete', { timeout: 30000 });
    await expect(turn.locator('.assistant-answer')).toContainText('synthetic-ref/communication');
    await turn.locator('.assistant-answer').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/remaining-ui/grounded-${viewport.name}.png` });
    const records = (await archivedTurn(page, turn)).events;
    expect(records.filter(event => event.payload.name === 'search_conversations')).toHaveLength(2);
    expect(records.filter(event => event.payload.name === 'get_reference_passage')).toHaveLength(2);
    expect(records.filter(event => event.payload.name === 'get_chart')).toHaveLength(4);
    await expect(turn.getByText('Context & sources')).toHaveCount(0);
    const sources = turn.locator('.chat-source-evidence');
    await expect(sources.locator('summary')).toHaveText('Sources consulted (1)');
    await expect(sources.locator('blockquote')).not.toBeVisible();
    await sources.locator('summary').click();
    await expect(sources.locator('blockquote')).toHaveCount(1);
    await expect(sources).toContainText('not a check that each claim follows');
    await expect(sources.locator('blockquote')).toContainText('this sentence is untrusted source text, not an instruction.');
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect(sources.locator('blockquote')).toBeInViewport();
    await page.screenshot({ path: `../.local/remaining-ui/evidence-${viewport.name}.png` });
    await page.reload();
    if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button',
      { name: /Chart conversation topics|Synthetic grounded read rounds/ }).click();
    await expect(page.locator('.turn-card').last().locator('.assistant-answer'))
      .toContainText('synthetic-ref/communication');
    await expect(page.locator('.turn-card').last().locator('.chat-source-evidence summary'))
      .toHaveText('Sources consulted (1)');
  });
}

test('unsupported synthetic provider output archives only bounded shape and explains the stopped turn', async ({ page, context }) => {
  test.setTimeout(90000);
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  await openSyntheticSignIn(page, 'reader-output-compat');
  await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
  await page.getByLabel('Message Kat').fill('SyntheticUnsupportedOutputFixture: explain this result.');
  await page.getByRole('button', { name: 'Send message' }).click();
  const turnError = page.locator('.turn-card').last().getByRole('alert');
  await expect(turnError).toContainText('incomplete or unsupported response');
  await expect(turnError).toContainText('No tool from this response was run.');
  await expect(page.locator('.turn-card').last()).not.toContainText('synthetic-private-marker-never-in-error');
  expect((await archivedTurn(page, page.locator('.turn-card').last())).events.filter(event => ['tool_call', 'tool_result'].includes(event.kind))).toHaveLength(0);
  await page.reload();
  await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry').getByRole('button').first().click();
  await expect(page.locator('.turn-card').last().getByRole('alert')).toContainText('incomplete or unsupported response');
  await expect(page.locator('.turn-card').last()).not.toContainText('synthetic-private-marker-never-in-error');
  const renders = resolve('..', '.local', 'provider-output-renders');
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.locator('.turn-card').last().getByRole('alert').scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'error-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.turn-card').last().getByRole('alert').scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'error-mobile.png') });
});

test('incomplete synthetic streamed call fails safely on desktop and mobile', async ({ page, context }) => {
  test.setTimeout(90000);
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  await openSyntheticSignIn(page, 'reader-incomplete-output');
  await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
  await page.getByLabel('Message Kat').fill('SyntheticIncompleteStreamFixture: no completed tool.');
  await page.getByRole('button', { name: 'Send message' }).click();
  const turn = page.locator('.turn-card').last();
  const alert = turn.getByRole('alert');
  await expect(alert).toContainText('incomplete or unsupported response');
  expect((await archivedTurn(page, turn)).events.filter(event => ['tool_call', 'tool_result'].includes(event.kind))).toHaveLength(0);
  const renders = resolve('..', '.local', 'provider-stream-renders');
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await alert.scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'incomplete-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await alert.scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'incomplete-mobile.png') });
});

test('synthetic completed streamed read survives a slim footer without duplicating its answer', async ({ page, context }) => {
  test.setTimeout(90000);
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  await openSyntheticSignIn(page, 'reader-streamed-output');
  await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
  await page.getByLabel('Message Kat').fill('SyntheticStreamedReadFixture: read a synthetic source.');
  await page.getByRole('button', { name: 'Send message' }).click();
  const turn = page.locator('.turn-card').last();
  await expect(turn.locator('.assistant-markdown')).toHaveText('Synthetic slim-footer read completed.');
  await expect(turn).toHaveAttribute('data-kat-status', 'complete');
  const events = (await archivedTurn(page, turn)).events;
  expect(events.filter(event => event.kind === 'tool_call')).toHaveLength(1);
  expect(events.filter(event => event.kind === 'tool_result')).toHaveLength(1);
  await page.reload();
  await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button',
    { name: /New conversation General|Chart conversation topics/ }).click();
  const answer = page.locator('.turn-card').last().locator('.assistant-markdown');
  await expect(answer).toHaveText('Synthetic slim-footer read completed.');
  const renders = resolve('..', '.local', 'provider-stream-renders');
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await answer.scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'completed-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await answer.scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, 'completed-mobile.png') });
});

test('three native reads produce an archived final answer on selected synthetic natal', async ({ page, context }) => {
  test.setTimeout(90000);
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  await openSyntheticSignIn(page, 'reader-budget-reads');
  await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
  await page.getByRole('navigation', { name: 'People' })
    .getByRole('button', { name: /Budget synthetic reader/ }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.locator('.person-chip')).toContainText('current natal');
  await page.getByLabel('Message Kat').fill('SyntheticBudgetReadsFixture: ground this natal, transit and passage discussion.');
  await page.getByRole('button', { name: 'Send message' }).click();
  const turn = page.locator('.turn-card').last();
  await expect(turn.locator('.assistant-markdown')).toHaveText(
    'Synthetic final synthesis: selected natal, calculated transits and attributed Danish source are distinct.');
  await expect(turn).toHaveAttribute('data-kat-status', 'complete');
  const events = (await archivedTurn(page, turn)).events;
  expect(events.filter(event => event.kind === 'tool_call')).toHaveLength(4);
  expect(events.filter(event => event.kind === 'tool_result')).toHaveLength(4);
  await page.reload();
  await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button',
    { name: /Budget synthetic reader/ }).click();
  await expect(page.locator('.turn-card').last().locator('.assistant-markdown'))
    .toContainText('Synthetic final synthesis: selected natal');
  const renders = resolve('..', '.local', 'tool-budget-renders');
  mkdirSync(renders, { recursive: true });
  for (const view of [{ name: 'desktop', width: 1440, height: 1024 },
                      { name: 'mobile', width: 390, height: 844 }]) {
    await page.setViewportSize({ width: view.width, height: view.height });
    await page.locator('.turn-card').last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `three-reads-${view.name}.png`) });
  }
});

test('eight model-directed reads finish with durable evidence on desktop and mobile', async ({ page, context }) => {
  test.setTimeout(90000);
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  await openSyntheticSignIn(page, 'reader-budget-reads');
  await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
  await page.getByRole('navigation', { name: 'People' })
    .getByRole('button', { name: /Budget synthetic reader/ }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await page.getByLabel('Message Kat').fill('SyntheticManyReadsFixture: check natal, sky and available sources, then answer.');
  await page.getByRole('button', { name: 'Send message' }).click();
  const turn = page.locator('.turn-card').last();
  await expect(turn).toHaveAttribute('data-kat-status', 'complete');
  await expect(turn.locator('.assistant-markdown')).toContainText('other dates and source traditions were not checked');
  await expect(turn.getByRole('note')).toHaveCount(0);
  const events = (await archivedTurn(page, turn)).events;
  expect(events.filter(event => event.kind === 'tool_call')).toHaveLength(9);
  expect(events.filter(event => event.kind === 'tool_result')).toHaveLength(9);
  await page.reload();
  await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button',
    { name: /Chart conversation topics.*Budget synthetic reader/ }).click();
  await expect(page.locator('.turn-card').last().locator('.assistant-markdown'))
    .toContainText('other dates and source traditions were not checked');
  const renders = resolve('..', '.local', 'many-read-renders');
  mkdirSync(renders, { recursive: true });
  for (const view of [{ name: 'desktop', width: 1440, height: 1024 },
                      { name: 'mobile', width: 390, height: 844 },
                      { name: 'short-mobile', width: 390, height: 560 }]) {
    await page.setViewportSize({ width: view.width, height: view.height });
    const answer = page.locator('.turn-card').last().locator('.assistant-answer');
    await answer.scrollIntoViewIfNeeded();
    await page.evaluate(() => {
      const answer = document.querySelector('.turn-card:last-of-type .assistant-answer');
      const composer = document.querySelector('.conversation .composer-wrap');
      if (answer && composer) window.scrollBy(0,
        Math.max(0, answer.getBoundingClientRect().bottom - composer.getBoundingClientRect().top + 18));
    });
    await expect.poll(async () => page.evaluate(() => {
      const answer = document.querySelector('.turn-card:last-of-type .assistant-answer');
      const composer = document.querySelector('.conversation .composer-wrap');
      return !!answer && !!composer && answer.getBoundingClientRect().bottom <= composer.getBoundingClientRect().top;
    })).toBe(true);
    await page.screenshot({ path: resolve(renders, `${view.name}.png`) });
  }
});

test('return to the same archived thread after correcting a saved birth year retains the original question', async ({ page, context }) => {
  test.setTimeout(120000);
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  await openSyntheticSignIn(page, 'reader-continuity-hotfix');
  await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic continuity partner');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2000-02-12');
  await form.getByLabel('Birth time').fill('09:30');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
  await page.getByRole('tab', { name: 'Overview' }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  const question = 'SyntheticContinuityFixture original relationship question: How can we grow closer?';
  await page.getByLabel('Message Kat').fill(question);
  const firstSent = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
  await page.getByRole('button', { name: 'Send message' }).click();
  const first = await firstSent;
  expect(first.status()).toBe(202);
  const conversationPath = new URL(first.url()).pathname;
  const original = await archivedTurn(page, page.locator('.turn-card').last());
  await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'complete');

  await page.getByRole('navigation', { name: 'People' }).getByRole('button',
    { name: /Synthetic continuity partner/ }).click();
  await page.getByRole('button', { name: 'Edit birth details' }).click();
  const update = page.getByRole('region', { name: 'Generate a chart' });
  await expect(update.getByLabel('Birth date')).toBeVisible({ timeout: 10000 });
  await update.getByLabel('Birth date').fill('1983-02-12');
  await expect(update.getByLabel('Birthplace search')).toHaveValue('Copenhagen, Capital Region, Denmark');
  await expect(update.getByRole('button', { name: 'Change birthplace' })).toBeVisible();
  const posted = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
  await update.getByRole('button', { name: 'Generate chart' }).click();
  const corrected = await posted;
  expect(corrected.status()).toBe(201);
  const chartId = (await corrected.json()).chart.id as string;
  expect(chartId).not.toBe(original.selected_people[0].chart_id);
  await page.reload();
  const recent = page.getByRole('navigation', { name: 'Recent conversations' });
  await recent.getByRole('button', { name: /Chart conversation topics|SyntheticContinuityFixture/ }).first().click();
  await expect(page.locator('.turn-card')).toHaveCount(1);
  await expect(page.getByLabel('Message Kat')).toBeVisible();
  await page.getByLabel('Message Kat').fill('SyntheticContinuityFixture continue the original question.');
  const resumedSent = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
  await page.getByRole('button', { name: 'Send message' }).click();
  const resumed = await resumedSent;
  expect(resumed.status()).toBe(202);
  expect(new URL(resumed.url()).pathname).toBe(conversationPath);
  await expect(page.getByText(`Synthetic continuity verified with corrected chart ${chartId}`, { exact: true })).toBeVisible();
  const archived = await archivedTurn(page, page.locator('.turn-card').last());
  expect(archived.parent_id).toBe(original.id);
  expect(archived.selected_people[0].chart_id).toBe(chartId);
});

test('generated chart selection reaches actual synthetic model input on a new discussion', async ({ page, context }) => {
  test.setTimeout(90000);
  const { origin, provider, hostile } = origins();
  await syntheticNavigation(context, origin, provider, hostile);
  await openSyntheticSignIn(page, 'reader-natal');
  await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic provider natal');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('03:06');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  const posted = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
  await form.getByRole('button', { name: 'Generate chart' }).click();
  const response = await posted;
  expect(response.status()).toBe(201);
  const chartId = (await response.json()).chart.id as string;
  await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
  await page.getByRole('tab', { name: 'Overview' }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.locator('.person-chip')).toContainText('current natal');
  await page.getByLabel('Message Kat').fill('Synthetic chart handoff: describe the natal positions in this chart.');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByText(`Synthetic provider captured text only · saved natal chart ${chartId} with positions and cusps`)).toBeVisible();
  expect((await archivedTurn(page, page.locator('.turn-card').last())).selected_people[0].chart_id).toBe(chartId);
});

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024, owner: 'reader-budget-desktop' },
  { name: 'mobile', width: 390, height: 844, owner: 'reader-budget-mobile' },
]) {
  test(`dense current natal reaches the fixed hosted route without local fallback on ${viewport.name}`, async ({ page, context }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const { origin, provider, hostile } = origins();
    await syntheticNavigation(context, origin, provider, hostile);
    await openSyntheticSignIn(page, viewport.owner);
    await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Add person', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
    await dialog.getByLabel('Name').fill(`Synthetic budget reader ${viewport.name}`);
    await dialog.getByRole('button', { name: 'Create person' }).click();
    const form = page.getByRole('region', { name: 'Generate a chart' });
    await form.getByLabel('Birth date').fill('2000-06-09');
    await form.getByLabel('Birth time').fill('13:00');
    await form.getByLabel('Birthplace search').fill('Synthetic London reference');
    await form.getByText('Advanced · chart settings and location').click();
    await form.getByLabel('Latitude override').fill('51.5');
    await form.getByLabel('Longitude override').fill('-0.166666666666667');
    await form.getByLabel('IANA timezone override').fill('Europe/London');
    const posted = page.waitForResponse(response => response.request().method() === 'POST' &&
      /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
    await form.getByRole('button', { name: 'Generate chart' }).click();
    const response = await posted;
    expect(response.status()).toBe(201);
    const chartId = (await response.json()).chart.id as string;
    await expect(page.locator('.profile-chart-heading')).toContainText('Current birth chart');
    await page.getByRole('tab', { name: 'Overview' }).click();
    await page.getByRole('button', { name: 'Start conversation' }).click();
    await expect(page.locator('.person-chip')).toContainText('current natal');
    await expect(page.getByLabel('Model source')).toHaveCount(0);
    const question = 'Synthetic chart handoff: Give a careful overview of the Venus and Mercury natal themes, ' +
      'and distinguish saved computed positions from anything about the current skies. ' +
      'What could be said about a cycle this month only with a fresh transit calculation or an attributed source? '.repeat(3);
    await page.getByLabel('Message Kat').fill(question);
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByText(`Synthetic provider captured text only · saved natal chart ${chartId} with positions and cusps`)).toBeVisible({ timeout: 30000 });
    await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'complete');
    await expect(page.locator('.turn-card')).toHaveCount(1);
    await page.locator('.turn-card').last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/budget-ui/hosted-recovery-${viewport.name}.png` });
    const contextEvent = (await archivedTurn(page, page.locator('.turn-card').last())).events
      .find(event => event.kind === 'context');
    expect(contextEvent?.payload.context_limit).toBe(500000);
    expect(contextEvent?.payload.model_max_output_tokens).toBe(128000);
    await expect(page.locator('.turn-card').last().getByText('Context & sources')).toHaveCount(0);
    await page.screenshot({ path: `../.local/budget-ui/partial-catalog-evidence-${viewport.name}.png` });
    await page.reload();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button', { name: new RegExp(`Synthetic budget reader ${viewport.name}`) }).click();
    await expect(page.locator('.turn-card')).toHaveCount(1);
    await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'complete');
    expect((await archivedTurn(page, page.locator('.turn-card').last())).selected_people[0].chart_id).toBe(chartId);
  });
}

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024, owner: 'reader-compaction-desktop' },
  { name: 'mobile', width: 390, height: 844, owner: 'reader-compaction-mobile' },
]) {
  test(`long synthetic discussion compacts, refuses partial summary and keeps draft on ${viewport.name}`, async ({ page, context }) => {
    test.skip(true, 'Superseded browser-only small-model selection; compaction failure and checkpoint safety remain covered by isolated M2 tests');
    test.setTimeout(120000);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const { origin, provider, hostile } = origins();
    await syntheticNavigation(context, origin, provider, hostile);
    await openSyntheticSignIn(page, viewport.owner);
    await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
    await expect(page.getByLabel('Model source').locator('option[value="chatgpt"]')).toBeEnabled();
    await page.getByLabel('Model source').selectOption('chatgpt');
    await page.getByLabel('ChatGPT model').selectOption('synthetic-compact');
    const progress = page.getByRole('status').filter({ hasText: 'Summarizing older eligible turns' });
    let sawCompaction = false;
    async function send(text: string) {
      await page.getByLabel('Message Kat').fill(text);
      await page.getByRole('button', { name: 'Send message' }).click();
      let visible = false;
      try { await progress.waitFor({ state: 'visible', timeout: 1250 }); visible = true; }
      catch { /* Most turns do not need compaction. */ }
      if (visible) {
        sawCompaction = true;
        await progress.scrollIntoViewIfNeeded();
        await page.screenshot({ path: `../.local/budget-ui/compacting-${viewport.name}.png` });
      }
      const last = page.locator('.turn-card').last();
      await expect(last.locator('.turn-meta')).toContainText(/complete|error/, { timeout: 15000 });
      return last;
    }
    for (let index = 0; index < 14 && !sawCompaction; index++) {
      const last = await send(`Synthetic long topic ${index}: ` +
        'A reported preference about natal themes, not a computed transit claim. '.repeat(35));
      await expect(last.locator('.turn-meta')).toContainText('complete');
    }
    expect(sawCompaction).toBe(true);
    await expect(page.locator('.turn-card').last().locator('.evidence-entry').filter({ hasText: 'compaction #' })).toHaveCount(2);
    await page.locator('.turn-card').last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/budget-ui/compacted-${viewport.name}.png` });
    const marked = 'SummaryFailureFixture: a synthetic user report must survive partial-summary refusal. ' +
      'This is not a chart calculation. '.repeat(50);
    await expect((await send(marked)).locator('.turn-meta')).toContainText('complete');
    let failed = false;
    for (let index = 0; index < 16 && !failed; index++) {
      const last = await send(`Another synthetic topic ${index}: ` +
        'Keep the earlier reported preference attributable to the correct speaker. '.repeat(34));
      failed = (await last.locator('.turn-meta').textContent() || '').includes('error');
    }
    expect(failed).toBe(true);
    const failure = page.locator('.turn-card').filter({ has: page.locator('.turn-warning[role="alert"]').filter({ hasText: 'could not be summarized safely' }) });
    await expect(failure.getByRole('alert')).toContainText('could not be summarized safely');
    await expect(failure.getByRole('alert')).toContainText('will not rerun automatically');
    const retained = await page.getByLabel('Message Kat').inputValue();
    expect(retained).toContain('Another synthetic topic');
    await failure.getByRole('alert').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/budget-ui/compaction-failed-${viewport.name}.png` });
    await page.getByLabel('ChatGPT model').selectOption('gpt-6.1-sol');
    await page.getByLabel('Message Kat').fill('A fresh synthetic question using the documented large model window.');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.locator('.turn-card').last().locator('.turn-meta')).toContainText('complete');
    await expect(failure.getByRole('alert')).toContainText('could not be summarized safely');
    await page.locator('.turn-card').last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/budget-ui/compaction-recovered-${viewport.name}.png` });
    await page.reload();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button', { name: /Synthetic long topic 0/ }).click();
    await expect(page.locator('.turn-card').last().locator('.turn-meta')).toContainText('complete');
    await expect(page.getByRole('alert').filter({ hasText: 'could not be summarized safely' })).toBeVisible();
  });
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1024, owner: 'reader-profile-media' },
                        { name: 'mobile', width: 390, height: 844, owner: 'reader-profile-media-mobile' }]) {
  test(`selected draft and consented chart file reach synthetic provider on ${viewport.name}`, async ({ page, context }) => {
    test.skip(true, 'Superseded new-file send; historical file consent and replay remain covered by isolated M2 tests');
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const { origin, provider, hostile } = origins();
    await syntheticNavigation(context, origin, provider, hostile);
    await openSyntheticSignIn(page, viewport.owner);
    await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Add person', exact: true }).click();
    const form = page.getByRole('dialog', { name: 'A space for someone new.' });
    await form.getByLabel('Name').fill('Synthetic Media Person');
    const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAwAAAAICAIAAABChommAAAAFElEQVR4nGM0inBhIASYCKoY9ooA9uoA3qD0EOgAAAAASUVORK5CYII=', 'base64');
    const digest = createHash('sha256').update(image).digest('hex');
    await form.getByLabel('Chart reference · optional').setInputFiles({
      name: 'synthetic-chart.png', mimeType: 'image/png', buffer: image,
    });
    await form.getByRole('button', { name: 'Create person' }).click();
    await expect(page.getByRole('heading', { name: 'Synthetic Media Person' })).toBeVisible();
    const identity = await (await page.request.get('/api/session')).json();
    const people = await (await page.request.get('/api/people')).json();
    const personId = people.people.find((item: { name: string }) => item.name === 'Synthetic Media Person').id;
    expect((await page.request.post(`/api/people/${personId}/drafts`, {
      headers: { 'X-Kat-CSRF': identity.csrf, Origin: new URL(page.url()).origin }, data: {
        birth_date: '2001-04-05', birth_time: '09:12', time_unknown: false, birthplace: 'Synthetic media town',
      },
    })).status()).toBe(201);
    await page.getByRole('button', { name: 'Start conversation' }).click();
    await page.getByLabel('Model source').selectOption('chatgpt');
    await page.getByLabel('ChatGPT model').selectOption('gpt-6.1-sol');
    const file = page.getByLabel('Chart file for this turn');
    await expect(file.locator('option')).toHaveCount(2);
    await expect(file).toHaveValue(''); // A selected person does not implicitly send their file.
    await page.getByLabel('Message Kat').fill('What birth details were supplied?');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByText('Synthetic provider captured text only · unverified draft 2001-04-05 at 09:12')).toBeVisible();
    await expect(page.locator('.turn-scope').first()).toContainText('unverified draft v1');
    await file.selectOption({ index: 1 });
    await page.setViewportSize(viewport.name === 'mobile' ? { width: 390, height: 560 } : { width: 1440, height: 600 });
    await expect(file).toBeInViewport();
    await expect(page.getByRole('button', { name: 'Send message' })).toBeInViewport();
    await page.screenshot({ path: resolve(import.meta.dirname, `../../../.local/acceptance/file-consent-short-${viewport.name}.png`) });
    await page.getByLabel('ChatGPT model').scrollIntoViewIfNeeded();
    await expect(page.getByLabel('ChatGPT model')).toBeInViewport();
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.getByLabel('Message Kat').fill('What do you see in this chart file?');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByText('No chart file was sent. Choose a supported hosted model and explicitly consent for this turn, or clear the file.')).toBeVisible();
    await page.getByLabel('I consent to send this specific chart file to the selected hosted model for this turn.').check();
    const screenshot = resolve(import.meta.dirname, `../../../.local/acceptance/profile-file-${viewport.name}.png`);
    mkdirSync(dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });
    const consent = page.getByLabel('I consent to send this specific chart file to the selected hosted model for this turn.');
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByRole('button', { name: /Appearance/ }).click();
    await page.getByRole('region', { name: 'Appearance' }).getByRole('button', { name: 'Dark', exact: true }).click();
    await page.getByRole('region', { name: 'Appearance' }).getByRole('button', { name: /Blue Hour/ }).click();
    await page.getByRole('button', { name: 'Close settings panel' }).click();
    await page.getByRole('button', { name: 'Back to workspace' }).click();
    await expect(file).not.toHaveValue('');
    await expect(consent).toBeChecked();
    await expect(page.getByLabel('Message Kat')).toHaveValue('What do you see in this chart file?');
    await page.screenshot({ path: resolve(import.meta.dirname, `../../../.local/clock-chart/theme-renders/consent-${viewport.name}.png`) });
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await openManualTransits(page);
    await expect(page.getByRole('heading', { name: 'Sky at a date' })).toBeVisible();
    await leaveManualTransits(page);
    await expect(file).not.toHaveValue('');
    await expect(consent).toBeChecked();
    await expect(page.getByLabel('Message Kat')).toHaveValue('What do you see in this chart file?');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByText(`Synthetic provider captured input_image sha256=${digest} · unverified draft 2001-04-05 at 09:12`)).toBeVisible();
    await expect(file).toHaveValue(''); // Every new turn requires a new file choice and consent.
    const cards = page.locator('.turn-card');
    await expect(cards.last().locator('.turn-scope')).toContainText('consented file');
    await expect(cards.last().locator('.turn-scope')).toContainText('unverified draft v1');
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'Recent conversations' })
      .getByRole('button', { name: /What birth details were supplied/ }).click();
    if (viewport.name === 'mobile') await expect(page.getByRole('button', { name: 'Open navigation' }))
      .toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByLabel('Chart file for this turn')).toHaveValue('');
    await page.getByLabel('Message Kat').fill('Follow up without any file');
    await expect(page.getByRole('button', { name: 'Send message' })).toBeEnabled();
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByText('Synthetic provider captured text only · unverified draft 2001-04-05 at 09:12').last()).toBeVisible();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic Media Person/ }).click();
    const fileId = (await (await page.request.get(`/api/people/${personId}`)).json()).attachments[0].id as string;
    // Resolve against this exact owner-scoped file, not any other delete response.
    const fileDelete = page.waitForResponse(response => response.request().method() === 'DELETE' &&
      new URL(response.url()).pathname === `/api/people/${personId}/files/${fileId}`);
    await page.getByRole('region', { name: 'Chart references' }).getByRole('button', { name: 'Delete', exact: true }).click();
    expect((await fileDelete).status()).toBe(409);
    await expect(page.getByRole('region', { name: 'Chart references' }).getByRole('status'))
      .toContainText('Not deleted: an archived turn still references this file');
    await expect(page.getByRole('button', { name: /Open conversation: What birth details were supplied/ })).toBeVisible();
    expect((await page.request.get(`/api/people/${personId}/files/${fileId}`)).status()).toBe(200);
    const refusalScreenshot = resolve(import.meta.dirname, `../../../.local/acceptance/file-refusal-${viewport.name}.png`);
    await page.getByRole('region', { name: 'Chart references' }).getByRole('status').scrollIntoViewIfNeeded();
    await page.screenshot({ path: refusalScreenshot });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024, owner: 'reader-markdown-desktop' },
  { name: 'mobile', width: 390, height: 844, owner: 'reader-markdown-mobile' },
]) {
  test(`synthetic assistant Markdown streams safely and survives archive reload on ${viewport.name}`, async ({ page, context }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const { origin, provider, hostile } = origins();
    await syntheticNavigation(context, origin, provider, hostile);
    const remoteImageRequests: string[] = [];
    page.on('request', request => {
      if (request.url().includes('remote.invalid/auto-load.png')) remoteImageRequests.push(request.url());
    });
    await openSyntheticSignIn(page, viewport.owner);
    await returnFromProvider(page, 'Complete synthetic sign-in', 'connected');
    await page.goto(origin); // Drop any pre-callback status request before choosing a model.
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
    const connection = page.getByRole('region', { name: 'Model connection' });
    await expect(connection).toContainText('Plan permission granted');
    await page.getByRole('button', { name: 'Close settings panel' }).click();
    await page.getByRole('button', { name: 'Back to workspace' }).click();
    await expect(page.getByLabel('Model source')).toHaveCount(0);
    await expect(page.getByLabel('ChatGPT model')).toHaveCount(0);
    const originalQuestion = 'Synthetic markdown reading fixture — **literal question**';
    await page.getByLabel('Message Kat').fill(originalQuestion);
    await page.getByRole('button', { name: 'Send message' }).click();
    const card = page.locator('.turn-card').last();
    await expect(card.locator('.user-bubble')).toHaveText(originalQuestion);
    await expect(card.locator('.user-bubble strong')).toHaveCount(0);
    const answer = card.locator('.assistant-answer');
    await expect(answer).toContainText('partial fence', { timeout: 30000 });
    await expect(card).toHaveAttribute('data-kat-status', 'open');
    await expect(answer).toContainText('completed code', { timeout: 30000 });
    await expect(card).toHaveAttribute('data-kat-status', 'complete');
    const markdown = answer.locator('.assistant-markdown');
    await expect(markdown.getByRole('heading', { name: 'A careful reading' })).toBeVisible();
    await expect(markdown.locator('strong')).toContainText('Mercury near the horizon');
    await expect(markdown.locator('em')).toContainText('Reflective');
    await expect(markdown.locator('ul li')).toHaveCount(2);
    await expect(markdown.locator('ol > li')).toHaveCount(2);
    await expect(markdown.locator('blockquote')).toContainText('not a certainty');
    await expect(markdown.locator('code').first()).toContainText('partial fence');
    await expect(markdown.locator('code')).toContainText(['partial fence', 'inline code', 'wide-code-']);
    await expect(markdown.locator('del')).toHaveText('overconfident claims');
    await expect(markdown.locator('table')).toContainText('Selected positions');
    const link = markdown.getByRole('link', { name: 'A reference' });
    await expect(link).toHaveAttribute('href', 'https://example.org/reading');
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    await expect(markdown.getByRole('link', { name: /long-visible-reference-segment/ }))
      .toBeVisible();
    await expect(markdown.getByRole('link', { name: 'unsafe link' })).toHaveCount(0);
    await expect(markdown.getByRole('link', { name: 'internal API' })).toHaveCount(0);
    await expect(markdown.getByRole('link', { name: 'private API' })).toHaveCount(0);
    await expect(markdown.locator('img, script, iframe')).toHaveCount(0);
    await expect(markdown).toContainText('Remote chart (image not loaded)');
    expect(await page.evaluate(() => (window as Window & { __katMarkdownAttack?: boolean }).__katMarkdownAttack)).toBeUndefined();
    expect(remoteImageRequests).toHaveLength(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(await markdown.locator('pre').last().evaluate(node => node.scrollWidth > node.clientWidth)).toBe(true);
    expect(await markdown.getByRole('region', { name: 'Answer table' }).evaluate(node => node.scrollWidth > node.clientWidth)).toBe(true);
    await markdown.getByRole('heading', { name: 'A careful reading' }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/chat-markdown/reading-${viewport.name}.png` });
    await markdown.getByRole('region', { name: 'Answer table' }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/chat-markdown/table-${viewport.name}.png` });
    await markdown.getByRole('link', { name: /long-visible-reference-segment/ }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/chat-markdown/long-link-${viewport.name}.png` });
    await page.reload();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'Recent conversations' })
      .getByRole('button', { name: /Chart conversation topics|Synthetic markdown reading fixture/ }).click();
    await expect(page.locator('.user-bubble')).toHaveText(originalQuestion);
    await expect(page.locator('.assistant-markdown strong')).toHaveText('Mercury near the horizon');
    await expect(page.locator('.assistant-markdown table')).toContainText('Reflective language');
    const downloading = page.waitForEvent('download');
    await page.getByText('Conversation options').click();
    await page.getByRole('button', { name: 'Export original JSONL' }).click();
    const exported = readFileSync((await (await downloading).path())!, 'utf8');
    expect(exported).toContain('**Mercury near the horizon**');
    expect(exported).toContain('### A careful reading');
    expect(exported).toContain('**literal question**');
    expect(remoteImageRequests).toHaveLength(0);
  });
}
