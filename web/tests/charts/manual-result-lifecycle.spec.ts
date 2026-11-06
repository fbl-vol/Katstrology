import { test, expect } from '@playwright/test';

test('manual result keeps its ID after a lost ACK and fences stale history and opened originals', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced-ux');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('navigation', { name: 'People' })).toBeVisible();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Solar-arc directions/ }).click();
  const view = page.getByRole('region', { name: 'True solar-arc directions' });
  let arrived!: () => void;
  let release!: () => void;
  let delivered!: () => void;
  const historyStarted = new Promise<void>(resolve => { arrived = resolve; });
  const held = new Promise<void>(resolve => { release = resolve; });
  const historyDone = new Promise<void>(resolve => { delivered = resolve; });
  let firstHistory = true;
  await page.route('**/api/advanced-results?person_id=transit-person&technique=true_solar_arc', async route => {
    if (!firstHistory) { await route.continue(); return; }
    firstHistory = false;
    const response = await route.fetch(); arrived(); await held;
    await route.fulfill({ response }); delivered();
  });
  await view.getByLabel('Person with a current natal').selectOption({ label: 'Synthetic transit reader' });
  await historyStarted;
  await view.getByLabel('Effective date (UTC midnight)').fill('2026-01-01');
  const sent: string[] = [];
  await page.route('**/api/advanced-results', async route => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const body = route.request().postDataJSON() as { id: string };
    sent.push(body.id);
    if (sent.length === 1) { await route.fetch(); await route.abort('failed'); }
    else await route.continue();
  });
  await view.getByRole('button', { name: 'Calculate solar arc' }).click();
  await expect(view.getByRole('alert')).toContainText('Saving was not confirmed');
  await view.getByRole('button', { name: 'Calculate solar arc' }).click();
  await expect(view.getByRole('region', { name: 'Solar-arc result' })).toBeVisible();
  expect(sent).toHaveLength(2);
  expect(sent[0]).toBe(sent[1]);
  await expect(view.getByRole('button', { name: /Open saved solar arc/ })).toHaveCount(1);
  release(); await historyDone;
  await expect(view.getByRole('button', { name: /Open saved solar arc/ })).toHaveCount(1);
  const listed = (await (await page.request.get('/api/advanced-results?person_id=transit-person&technique=true_solar_arc')).json()).results;
  expect(listed.filter((row: { id: string }) => row.id === sent[0])).toHaveLength(1);

  let opened!: () => void;
  let openRelease!: () => void;
  let openDelivered!: () => void;
  const openStarted = new Promise<void>(resolve => { opened = resolve; });
  const openHeld = new Promise<void>(resolve => { openRelease = resolve; });
  const openDone = new Promise<void>(resolve => { openDelivered = resolve; });
  await page.route(`**/api/advanced-results/${sent[0]}`, async route => {
    const response = await route.fetch(); opened(); await openHeld;
    await route.fulfill({ response }); openDelivered();
  });
  await view.getByRole('button', { name: /Open saved solar arc/ }).click();
  await openStarted;
  await view.getByLabel('Person with a current natal').selectOption({ label: 'Other synthetic reader' });
  openRelease(); await openDone;
  await expect(view.getByRole('region', { name: 'Solar-arc result' })).toHaveCount(0);
  await expect(view.getByRole('button', { name: /Open saved solar arc/ })).toHaveCount(0);
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
});
