import { test, expect, type Page } from '@playwright/test';
import { pathToFileURL } from 'node:url';
import { captureActual, layoutOf, type Layout } from '../support/layout-artifacts';

const views = [
  { label: 'desktop', width: 1440, height: 1024 },
  { label: 'wide', width: 1920, height: 1080 },
  { label: 'ultrawide', width: 2560, height: 1080 },
  { label: 'large-ultrawide', width: 3440, height: 1440 },
  { label: 'mobile', width: 390, height: 844 },
  { label: 'short-mobile', width: 390, height: 560 },
];
const near = (value: number, expected: number, tolerance = 1) => expect(Math.abs(value - expected)).toBeLessThanOrEqual(tolerance);
function visibleChartControls(layout: Layout, height: number) {
  const { chart, chartAction, chartDetails, composer } = layout;
  expect(chart).not.toBeNull();
  expect(chartAction).not.toBeNull();
  // Independent of horizontal alignment or pixel diffs: controls must not sit under the dock.
  expect(chart!.bottom).toBeLessThanOrEqual(composer.y + 1);
  expect(chartAction!.bottom).toBeLessThanOrEqual(composer.y + 1);
  expect(chartAction!.bottom).toBeLessThanOrEqual(height);
  if (chartDetails && chartDetails.width > 0) expect(chartDetails.bottom).toBeLessThanOrEqual(composer.y + 1);
}

function aligned(layout: Layout, width: number, chart: boolean) {
  const { grid, main, composer } = layout;
  near(grid.x, composer.x);
  near(grid.width, composer.width);
  near(grid.x - main.x, main.right - grid.right);
  expect(grid.width).toBeLessThanOrEqual(chart ? 1125 : 801);
  expect(layout.pageWidth).toBeLessThanOrEqual(width + 1);
  if (chart && width > 1000) {
    expect(layout.chart).not.toBeNull();
    near(layout.chart!.right, grid.right);
    expect(layout.chart!.width).toBeGreaterThanOrEqual(255);
    expect(layout.chart!.width).toBeLessThanOrEqual(301);
    expect(layout.chart!.x - grid.x).toBeGreaterThan(500);
  } else if (!chart) {
    expect(layout.chart).toBeNull();
    expect(layout.columns).not.toContain('300px');
  }
}

async function openSyntheticEmptyThread(page: Page, id: string, people: string[]) {
  // Exercise the archived empty-thread layout without reinstating a redundant UI creation action.
  const status = await page.evaluate(async ({ id, people }) => {
    const { csrf } = await fetch('/api/session').then(response => response.json());
    return (await fetch('/api/conversations', { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Kat-CSRF': csrf },
      body: JSON.stringify({ id, title: 'New conversation', people }),
    })).status;
  }, { id, people });
  expect(status).toBe(201);
  await page.reload();
  if (page.viewportSize()!.width <= 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'Recent conversations' }).locator('.recent-entry button').first().click();
  await expect(page.getByRole('region', { name: 'Conversation', exact: true })).toBeVisible();
}

for (const view of views) {
  test(`pinned synthetic reading layout on ${view.label}`, async ({ page, context, browser }) => {
    test.setTimeout(180000);
    const owner = `reader-layout-${view.label}`;
    await page.setViewportSize({ width: view.width, height: view.height });
    await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'aubergine'));
    const origin = new URL(test.info().project.use.baseURL!).origin;
    await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    // Comparison inputs are private and absent from a public root. Never inspect them by default.
    const privateComparison = process.env.KAT_LAYOUT_PRIVATE_REFERENCE === '1'
      ? await import('../support/layout-private-reference') : null;
    privateComparison?.verifyPrivateReference();
    const referenceContext = privateComparison
      ? await browser.newContext({ viewport: { width: view.width, height: view.height + 48 } }) : null;
    const reference = referenceContext ? await referenceContext.newPage() : null;
    if (reference && privateComparison) {
      await referenceContext!.route('**/*', route => route.request().url() === pathToFileURL(privateComparison.referenceFile).href
        ? route.continue() : route.abort());
    }
    const capture = async (scene: string, fixture: string) => {
      const layout = await captureActual(page, scene, view.width, view.height, fixture);
      const expected = reference && privateComparison
        ? await privateComparison.compareReference(page, reference, scene, view.width, view.height) : null;
      return { layout, reference: expected };
    };
    try {
      if (reference && privateComparison) await reference.goto(pathToFileURL(privateComparison.referenceFile).href);
      await page.goto('/');
      await page.getByLabel('Username').fill(owner);
      await page.getByLabel('Password').fill('synthetic-browser-password');
      await page.getByRole('button', { name: 'Open workspace' }).click();
      await expect(page.getByRole('region', { name: 'New conversation' })).toBeVisible();
      await expect(page.locator('.chat-reading-grid')).toBeVisible();
      await expect(page.getByRole('complementary', { name: 'Current natal context' })).toHaveCount(0);
      if (privateComparison && view.width >= 2560) {
        const before = await privateComparison.withBaselineCss(page, () => capture('before-general',
          `${owner} · pre-layout CSS · general new conversation`));
        expect(Math.abs(before.layout.grid.x - before.layout.composer.x)).toBeGreaterThan(50);
      }
      const general = await capture('general', `${owner} · general new conversation`);
      aligned(general.layout, view.width, false);
      if (privateComparison && view.width >= 2560) await privateComparison.captureBeforeAfter(page, 'general', view.width, view.height);
      await openSyntheticEmptyThread(page, `layout-general-${view.label}`, []);
      const generalThread = await capture('general-thread', `${owner} · empty general conversation without chart`);
      aligned(generalThread.layout, view.width, false);
      if (view.width <= 700) await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.locator('.side-main-actions .new-chat').click();
      if (view.width <= 700) await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
      await page.getByRole('button', { name: 'Start conversation' }).click();
      const card = page.getByRole('complementary', { name: 'Current natal context' });
      await expect(card).toContainText('For your next message');
      if (view.width <= 1000) {
        await expect(card.locator(':scope > details')).not.toHaveAttribute('open');
        await expect(card.getByRole('button', { name: /full chart/ })).toBeVisible();
      } else await expect(card.getByRole('img', { name: /Tropical natal wheel/ })).toBeVisible();
      if (privateComparison && view.width >= 2560) {
        const before = await privateComparison.withBaselineCss(page, () => capture('before-chart',
          `${owner} · pre-layout CSS · seeded generated natal`));
        expect(Math.abs(before.layout.grid.x - before.layout.composer.x)).toBeGreaterThan(50);
      }
      const chart = await capture('chart', `${owner} · seeded generated natal`);
      aligned(chart.layout, view.width, true);
      visibleChartControls(chart.layout, view.height);
      if (privateComparison && view.width >= 2560) await privateComparison.captureBeforeAfter(page, 'chart', view.width, view.height);
      if (chart.reference) {
        near(chart.layout.grid.x, chart.reference.grid.x, 12);
        near(chart.layout.grid.width, chart.reference.grid.width, 12);
        if (view.width > 1000) near(chart.layout.chart!.x, chart.reference.chart.x, 12);
      }
      await openSyntheticEmptyThread(page, `layout-chart-${view.label}`, ['transit-person']);
      const draft = page.getByLabel('Message Kat');
      const input = 'Synthetic archive line for checking long reading layout.\n'.repeat(45);
      await draft.fill(input);
      const ack = page.waitForResponse(response => response.request().method() === 'POST' &&
        /\/api\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname));
      await page.getByRole('button', { name: 'Send message' }).click();
      expect((await ack).status()).toBe(202);
      await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'complete', { timeout: 30000 });
      await draft.fill('Unsent synthetic draft survives resizing.');
      const long = await capture('long', `${owner} · committed long synthetic turn + unsent draft`);
      aligned(long.layout, view.width, true);
      visibleChartControls(long.layout, view.height);
      if (view.width <= 1000) {
        expect(long.layout.messages!.y).toBeGreaterThanOrEqual(long.layout.chart!.bottom);
        expect(long.layout.messages!.y).toBeGreaterThanOrEqual(long.layout.chartAction!.bottom);
      }
      expect(long.layout.pageHeight).toBeGreaterThan(view.height);
      const readingScroll = await page.evaluate(() => ({
        document: document.scrollingElement === document.documentElement,
        messages: getComputedStyle(document.querySelector('.messages')!).overflowY,
        composer: getComputedStyle(document.querySelector('.composer-wrap')!).overflowY,
      }));
      expect(readingScroll).toEqual({ document: true, messages: 'visible', composer: 'visible' });
      if (view.width > 1000) {
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight - innerHeight));
        const scrolled = await layoutOf(page);
        expect(scrolled.scrollY).toBeGreaterThan(0);
        expect(scrolled.chart!.y).toBeGreaterThanOrEqual(78);
        expect(scrolled.chart!.bottom).toBeLessThanOrEqual(scrolled.composer.y + 1);
        expect(scrolled.chartAction!.bottom).toBeLessThanOrEqual(scrolled.composer.y + 1);
      }
      if (view.label === 'large-ultrawide' || view.label === 'short-mobile') {
        const growingDraft = 'An unsent synthetic line for composer growth.\n'.repeat(65);
        await draft.fill(growingDraft);
        const growth = await page.evaluate(() => {
          const input = document.querySelector<HTMLTextAreaElement>('#message')!;
          const dock = input.closest<HTMLElement>('.composer-wrap')!;
          return { content: input.scrollHeight, visible: input.clientHeight,
            overflow: getComputedStyle(input).overflowY,
            inFlow: dock.classList.contains('composer-in-flow'), height: dock.offsetHeight };
        });
        expect(growth.content).toBeLessThanOrEqual(growth.visible + 1);
        expect(growth.overflow).toBe('hidden');
        expect(growth.inFlow).toBe(growth.height > view.height - 120);
        visibleChartControls(await layoutOf(page), view.height);
        await draft.fill('Unsent synthetic draft survives resizing.');
      }
      if (view.label === 'large-ultrawide') {
        for (const size of [{ width: 1440, height: 768 }, { width: 960, height: 900 },
          { width: 390, height: 560 }, { width: 3440, height: 1440 }]) {
          await page.setViewportSize(size);
          await page.evaluate(() => window.scrollTo(0, 0));
          await expect(draft).toHaveValue('Unsent synthetic draft survives resizing.');
          const resized = await layoutOf(page);
          aligned(resized, size.width, true);
          if (size.width > 1000) visibleChartControls(resized, size.height);
          if (size.width <= 1000) await expect(card.locator(':scope > details')).not.toHaveAttribute('open');
        }
      }
    } finally {
      await referenceContext?.close();
    }
  });
}
