import { test, expect } from '@playwright/test';

async function archivedChart(page: import('@playwright/test').Page, turnId: string): Promise<string | null> {
  return page.evaluate(async id => {
    const { conversations } = await fetch('/api/conversations').then(response => response.json());
    const turn = await fetch(`/api/conversations/${conversations[0].id}/turns/${id}`)
      .then(response => response.json());
    return turn.selected_people[0].chart_id;
  }, turnId);
}

test('current chart preview never replaces the archived turn chart after regeneration', async ({ page, context }) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1440, height: 1024 });
  const origin = new URL(test.info().project.use.baseURL!).origin;
  await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-clock-manual');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  const before = await page.locator('.person-chip').getAttribute('data-kat-chart-id');
  expect(before).toMatch(/^chart-[a-f0-9]+$/);
  await page.getByLabel('Message Kat').fill('One synthetic interpretation with this selected current chart.');
  await page.getByRole('button', { name: 'Send message' }).click();
  const turn = page.locator('.turn-card').last();
  await expect(turn).toHaveAttribute('data-kat-status', 'complete', { timeout: 30000 });
  const turnId = await turn.getAttribute('data-kat-turn-id');
  expect(await archivedChart(page, turnId!)).toBe(before);
  await expect(turn.locator('.turn-context')).not.toContainText(before!);
  await expect(turn.getByText('Message details')).toHaveCount(0);
  await expect(turn.getByText('Context & sources')).toHaveCount(0);
  const preview = page.getByRole('complementary', { name: 'Current natal context' });
  await expect(preview).toContainText('For your next message');
  await preview.getByRole('button', { name: /Open Synthetic transit reader’s full chart/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  await page.getByRole('button', { name: 'Edit birth details' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth time').fill('04:15');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  const saved = page.waitForResponse(response => response.request().method() === 'POST' &&
    /\/api\/people\/[^/]+\/generate$/.test(new URL(response.url()).pathname));
  await form.getByRole('button', { name: 'Generate chart' }).click();
  const response = await saved;
  expect(response.status()).toBe(201);
  const after = (await response.json()).chart.id as string;
  expect(after).not.toBe(before);
  await page.getByRole('button', { name: 'Return to conversation' }).click();
  await expect(preview).toContainText('Earlier message used a different chart');
  await expect(preview.getByText(before!, { exact: false })).toHaveCount(0);
  await expect(turn.locator('.turn-context')).toContainText('Earlier chart used for this message');
  expect(await archivedChart(page, turnId!)).toBe(before);
  await page.reload();
  await page.getByRole('navigation', { name: 'Recent conversations' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
  await expect(preview).toContainText('Earlier message used a different chart');
  await expect(turn.locator('.turn-context')).toContainText('Earlier chart used for this message');
  expect(await archivedChart(page, turnId!)).toBe(before);
  await page.setViewportSize({ width: 390, height: 560 });
  await expect(preview.locator(':scope > details > summary')).toContainText('Earlier message used a different chart');
  await expect(preview.locator(':scope > details')).not.toHaveAttribute('open');
});
