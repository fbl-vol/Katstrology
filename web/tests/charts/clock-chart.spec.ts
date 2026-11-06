import { test, expect, type BrowserContext, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { layoutOf } from '../support/layout-artifacts';
import { archivedTurn } from '../support/archive-assertions';
import { openManualTransits, leaveManualTransits } from '../support/navigation-helpers';

test.beforeAll(() => mkdirSync(resolve(import.meta.dirname, '../../../.local/clock-chart/renders'), { recursive: true }));

async function connect(page: Page, context: BrowserContext, owner: string, mobile: boolean) {
  const base = new URL(test.info().project.use.baseURL!);
  const provider = `http://127.0.0.2:${Number(base.port) + 1}`;
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin === base.origin || url.origin === provider) return route.continue();
    return route.abort();
  });
  await page.goto('/');
  await page.getByLabel('Username').fill(owner);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  if (mobile) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Settings' }).click();
  await page.getByRole('button', { name: /ChatGPT.*Manage/ }).click();
  await page.getByRole('region', { name: 'Model connection' })
    .getByRole('button', { name: 'Reconnect ChatGPT account', exact: true }).click();
  await page.waitForURL(`${provider}/authorize?*`);
  await page.getByRole('link', { name: 'Complete synthetic sign-in' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  await expect(page.locator('.model-label')).toHaveText('ChatGPT connected');
}

async function selectPerson(page: Page, mobile: boolean) {
  if (mobile) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' })
    .getByRole('button', { name: /Synthetic transit reader/ }).click();
  const person = await (await page.request.get('/api/people/transit-person')).json();
  const chartId = person.active_chart_id as string;
  expect(chartId).toMatch(/^chart-[a-f0-9]+$/);
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.locator('.person-chip')).toContainText('current natal');
  return chartId;
}

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024, owner: 'reader-clock-retained-desktop' },
  { name: 'mobile', width: 390, height: 844, owner: 'reader-clock-retained-mobile' },
]) {
  test(`normal chat reopens archived chart and keeps draft on ${viewport.name}`, async ({ page, context }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await connect(page, context, viewport.owner, viewport.name === 'mobile');
    await selectPerson(page, viewport.name === 'mobile');
    const contextChart = page.getByRole('complementary', { name: 'Current natal context' });
    await expect(contextChart).toContainText('For your next message');
    await expect(contextChart.locator('.context-chart-info')).toHaveCount(0);
    if (viewport.name === 'mobile') await expect(contextChart.locator(':scope > details')).not.toHaveAttribute('open');
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.getByRole('button', { name: /Appearance/ }).click();
    await page.getByRole('region', { name: 'Appearance' }).getByRole('button', { name: 'Dark', exact: true }).click();
    await page.getByRole('region', { name: 'Appearance' }).getByRole('button', { name: /Blue Hour/ }).click();
    await page.getByRole('button', { name: 'Close settings panel' }).click();
    const back = page.getByRole('button', { name: 'Back to workspace' });
    // Hold only this navigation's deferred restoration until the reader has
    // chosen the composer. The callback must not steal that newer focus.
    const deferredFocus = await back.evaluateHandle(button => {
      const callbacks: FrameRequestCallback[] = [];
      button.addEventListener('click', () => {
        const original = window.requestAnimationFrame;
        window.requestAnimationFrame = callback => {
          window.requestAnimationFrame = original;
          callbacks.push(callback);
          return 0;
        };
      }, { capture: true, once: true });
      return callbacks;
    });
    await back.click();
    const composer = page.getByLabel('Message Kat');
    await composer.fill('Synthetic full transit chart fixture: please calculate today’s natal transits.');
    await composer.press('Shift+Enter');
    await expect(composer).toHaveValue('Synthetic full transit chart fixture: please calculate today’s natal transits.\n');
    await composer.focus();
    expect(await deferredFocus.evaluate(callbacks => callbacks.length)).toBe(1);
    await deferredFocus.evaluate(callbacks => callbacks.splice(0).forEach(callback => callback(performance.now())));
    await deferredFocus.dispose();
    await expect(composer).toBeFocused();
    await composer.pressSequentially('Keep the uncertainty visible.', { delay: 25 });
    await expect(composer).toHaveValue('Synthetic full transit chart fixture: please calculate today’s natal transits.\nKeep the uncertainty visible.');
    await composer.press('Enter');
    const card = page.locator('.turn-card .chat-transit-card');
    await expect(card).toContainText('Open Synthetic transit reader · calculated natal + transits chart', { timeout: 30000 });
    await card.locator(':scope > summary').click();
    const sections = card.locator('.transit-section');
    await expect(sections).toHaveCount(4);
    for (let index = 0; index < 4; index++) await expect(sections.nth(index)).not.toHaveAttribute('open');
    await sections.nth(1).locator('summary').click();
    await expect(card.getByRole('table', { name: /Selected natal positions/ })).toContainText('Ascendant');
    await expect(sections.nth(0)).not.toHaveAttribute('open');
    await page.getByLabel('Message Kat').fill('This draft stays unsent through a manual view.');
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await openManualTransits(page);
    await leaveManualTransits(page);
    await expect(page.getByLabel('Message Kat')).toHaveValue('This draft stays unsent through a manual view.');
    await card.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/clock-chart/renders/normal-${viewport.name}.png` });
    await page.reload();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button',
      { name: /Synthetic transit reader/ }).click();
    await expect(page.locator('.chat-transit-card')).toContainText('Open Synthetic transit reader · calculated natal + transits chart');
    await expect(contextChart).toContainText('For your next message');
    await expect(contextChart.locator('.context-chart-info')).toHaveCount(0);
  });
}

test('normal chat keeps a centred chart rail, composer and draft across ultrawide-to-mobile resize', async ({ page, context }) => {
  await page.setViewportSize({ width: 2560, height: 1080 });
  await connect(page, context, 'reader-clock-retained-desktop', false);
  await selectPerson(page, false);
  const card = page.getByRole('complementary', { name: 'Current natal context' });
  await expect(card.getByRole('img', { name: /Tropical natal wheel/ })).toBeVisible();
  const wide = await layoutOf(page);
  expect(Math.abs(wide.grid.x - wide.composer.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(wide.grid.width - wide.composer.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(wide.grid.x - wide.main.x - (wide.main.right - wide.grid.right))).toBeLessThanOrEqual(1);
  expect(wide.grid.width).toBeLessThanOrEqual(1125);
  await page.getByLabel('Message Kat').fill('An unsent normal draft during resize.');
  await page.setViewportSize({ width: 390, height: 560 });
  await expect(card.locator(':scope > details')).not.toHaveAttribute('open');
  await expect(page.getByLabel('Message Kat')).toHaveValue('An unsent normal draft during resize.');
  const short = await layoutOf(page);
  expect(Math.abs(short.grid.x - short.composer.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(short.grid.width - short.composer.width)).toBeLessThanOrEqual(1);
  expect(short.pageWidth).toBeLessThanOrEqual(390);
});

test('Now / Today fills Copenhagen controls without sending or attaching a turn', async ({ page, context }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const base = new URL(test.info().project.use.baseURL!);
  await context.route('**/*', route => new URL(route.request().url()).origin === base.origin ? route.continue() : route.abort());
  let sends = 0;
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/conversations\//.test(new URL(request.url()).pathname)) sends++;
  });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-clock-manual');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByLabel('Message Kat').fill('An unsent draft is not a transit view.');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await openManualTransits(page);
  const panel = page.getByRole('region', { name: 'Sky at a date' });
  await expect(panel.getByLabel('Reporting timezone (IANA)')).toHaveCount(0);
  await panel.getByRole('button', { name: 'Use Now / Today' }).click();
  await expect(panel.getByLabel('Date')).toHaveValue('2026-01-01');
  await expect(panel.getByLabel('Copenhagen time')).toHaveValue('02:15:42');
  await expect(panel.locator('.transit-result')).toHaveCount(0);
  await panel.getByRole('button', { name: 'Show calculated view' }).click();
  await expect(panel.locator('.transit-result')).toContainText('2026-01-01 02:15:42 · Europe/Copenhagen');
  await expect(panel.locator('.transit-result')).not.toContainText('2026-01-01T01:15:42+00:00');
  await panel.getByLabel('Copenhagen time').fill('03:16:00');
  await expect(panel.locator('.transit-result')).toHaveCount(0);
  await leaveManualTransits(page);
  await expect(page.getByLabel('Message Kat')).toHaveValue('An unsent draft is not a transit view.');
  expect(sends).toBe(0);
  await page.screenshot({ path: '../.local/clock-chart/renders/now-manual-mobile.png' });
});

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024, owner: 'reader-clock-desktop' },
  { name: 'mobile', width: 390, height: 844, owner: 'reader-clock-mobile' },
]) {
  test(`fresh application time and in-conversation chart survive reload on ${viewport.name}`, async ({ page, context }) => {
    test.setTimeout(90000);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await connect(page, context, viewport.owner, viewport.name === 'mobile');
    const chartId = await selectPerson(page, viewport.name === 'mobile');
    await page.getByLabel('Message Kat').fill('Synthetic full transit chart fixture: please calculate today’s natal transits with my current chart.');
    await page.getByRole('button', { name: 'Send message' }).click();
    const turn = page.locator('.turn-card').last();
    await expect(turn).toHaveAttribute('data-kat-status', 'complete', { timeout: 30000 });
    const savedTurn = await archivedTurn(page, turn);
    const clock = savedTurn.events.find(event => event.kind === 'user')?.payload.clock_anchor as
      { instant_utc: string; reporting: { date: string; time: string; zone: string } };
    expect(clock.instant_utc).toBe('2026-01-01T01:15:42+00:00');
    expect(clock.reporting.zone).toBe('Europe/Copenhagen');
    await expect(turn).not.toContainText(clock.instant_utc);
    await expect(turn.locator('.assistant-answer')).toContainText('chart is calculated and attached');
    const card = turn.locator('.chat-transit-card');
    await expect(card).toContainText('Open Synthetic transit reader · calculated natal + transits chart · 2026-01-01 02:15:42');
    await card.locator(':scope > summary').click();
    await expect(card.getByRole('img', { name: /Natal and transiting tropical/ })).toBeVisible();
    await expect(card).not.toContainText(chartId);
    expect(savedTurn.selected_people[0].chart_id).toBe(chartId);
    if (viewport.name === 'desktop') {
      const printReady = page.waitForEvent('download');
      await card.getByRole('button', { name: 'Download print-ready SVG' }).click();
      const markup = await readFile(await (await printReady).path(), 'utf8');
      expect(markup).toContain(`"chart_id":"${chartId}"`);
      expect(markup).toContain('viewBox="0 0 480 480"');
      expect(markup).not.toMatch(/<text[^>]*>[^<]*chart-/);
      expect(markup).not.toContain('Calculated from supplied inputs');
    }
    const sections = card.locator('.transit-section');
    await expect(sections).toHaveCount(4);
    for (let index = 0; index < 4; index++) await expect(sections.nth(index)).not.toHaveAttribute('open');
    await sections.nth(0).locator('summary').click();
    await expect(card.getByRole('table', { name: /Transiting planets/ }).getByRole('row')).toHaveCount(11);
    await sections.nth(1).locator('summary').click();
    await expect(card.getByRole('table', { name: /Selected natal positions/ })).toContainText('Ascendant');
    await sections.nth(3).locator('summary').click();
    await expect(card.getByRole('table', { name: /Transit-to-natal aspects/ })).toBeVisible();
    await card.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../.local/clock-chart/renders/conversation-${viewport.name}.png` });
    const archived = savedTurn.events.find(event => event.kind === 'tool_result' &&
      event.payload.name === 'get_transit_view')?.payload.result as { status: string;
        positions: unknown[]; reporting: { date: string } };
    expect(archived.status).toBe('supported');
    expect(archived.positions).toHaveLength(10);
    expect(archived.reporting.date).toBe('2026-01-01');
    await page.getByRole('button', { name: 'Remove Synthetic transit reader from new turn' }).click();
    await expect(page.locator('.person-chip')).toHaveCount(0);
    await expect(card.locator(':scope > summary')).toContainText('Synthetic transit reader');
    await expect(card.getByRole('heading', { name: 'Synthetic transit reader · natal + transits' })).toBeVisible();
    await page.reload();
    if (viewport.name === 'mobile') await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button',
      { name: /Synthetic transit reader/ }).click();
    await expect(page.locator('.turn-card .chat-transit-card')).toContainText('Open Synthetic transit reader · calculated natal + transits chart');
    await page.locator('.chat-transit-card > summary').click();
    await expect(page.locator('.chat-transit-card .transit-section')).toHaveCount(4);
    await expect(page.locator('.chat-transit-card .transit-section').nth(1)).not.toHaveAttribute('open');
    await page.locator('.chat-transit-card .transit-section').nth(1).locator('summary').click();
    await expect(page.locator('.chat-transit-card').getByRole('table', { name: /Selected natal positions/ })).toContainText('Ascendant');
  });
}
