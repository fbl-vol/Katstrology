import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/advanced-techniques');

test('unknown-time natal gives actionable unsaved solar-arc error without a model turn', async ({ page }) => {
  mkdirSync(renders, { recursive: true });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-review-fixes');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('navigation', { name: 'People' })).toBeVisible();
  const session = await (await page.request.get('/api/session')).json();
  const generated = await page.request.post('/api/people/transit-person/generate', {
    headers: { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin },
    data: { request_id: `unknown-source-${crypto.randomUUID()}`, birth_date: '2001-06-21',
      birth_time: '', time_unknown: true, birthplace: 'Synthetic unknown-time London',
      place_id: null, provisional: true, zone_override: 'UTC', latitude_override: 51.5,
      longitude_override: -0.17, fold: null, settings: null },
  });
  expect(generated.status(), await generated.text()).toBe(201);
  await page.reload();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Solar-arc directions/ }).click();
  const view = page.getByRole('region', { name: 'True solar-arc directions' });
  await view.getByLabel('Person with a current natal').selectOption({ label: 'Synthetic transit reader' });
  await view.getByLabel('Effective date (UTC midnight)').fill('2026-01-01');
  const posted = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Calculate solar arc' }).click();
  const unsupported = await (await posted).json();
  expect(unsupported.status).toBe('unsupported_uncertain_birth_time_or_non_natal_chart');
  await expect(view.getByRole('alert')).toContainText('supply an exact birth time');
  await expect(view.getByRole('alert')).not.toContainText(unsupported.status);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 }, { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 }, { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize(size);
    await page.screenshot({ path: resolve(renders, `unsupported-solar-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
  expect((await (await page.request.get('/api/advanced-results?person_id=transit-person&technique=true_solar_arc')).json()).results).toHaveLength(0);
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  await page.route('**/api/advanced-results', route => route.fulfill({
    status: 201, contentType: 'application/json', body: JSON.stringify({ status: 'synthetic_new_status' }),
  }));
  await view.getByRole('button', { name: 'Calculate solar arc' }).click();
  await expect(view.getByRole('alert')).toContainText('not available for the selected charts');
  await expect(view.getByRole('alert')).not.toContainText('synthetic_new_status');
  await page.unroute('**/api/advanced-results');
  await view.getByRole('button', { name: 'Back to chart choices' }).click();
  await page.getByRole('button', { name: /^Progressed lunar phases/ }).click();
  const phases = page.getByRole('region', { name: 'Progressed lunar phase cycles' });
  await phases.getByLabel('Person with a current natal').selectOption({ label: 'Synthetic transit reader' });
  await phases.getByLabel('From (effective UTC)').fill('2001-06-22');
  await phases.getByLabel('Until (UTC, excluded)').fill('2037-06-21');
  const phaseReply = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await phases.getByRole('button', { name: 'Find progressed phases' }).click();
  const phaseStatus = (await (await phaseReply).json()).status;
  expect(phaseStatus).toBe('unsupported_uncertain_birth_time_or_non_natal_chart');
  await expect(phases.getByRole('alert')).toContainText('supply an exact birth time');
  await expect(phases.getByRole('alert')).not.toContainText(phaseStatus);
  await page.setViewportSize({ width: 390, height: 560 });
  await page.screenshot({ path: resolve(renders, 'unsupported-phases-short.png'), fullPage: true });
  expect((await (await page.request.get('/api/advanced-results?person_id=transit-person&technique=progressed_lunar_phases')).json()).results).toHaveLength(0);
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
});

test('true solar arc is not MCp or fixed one degree per year and replays saved wheel', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Solar-arc directions/ }).click();
  const view = page.getByRole('region', { name: 'True solar-arc directions' });
  await view.getByLabel('Person with a current natal').selectOption({ label: 'Synthetic transit reader' });
  await view.getByLabel('Effective date (UTC midnight)').fill('2026-01-01');
  const posted = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Calculate solar arc' }).click();
  const saved = await (await posted).json();
  expect(saved.status).toBe('supported');
  expect(saved.method_version).toBe('true-progressed-sun-forward-solar-arc-v1');
  expect(saved.arc_degrees).not.toBeCloseTo(24, 2);
  expect(saved.arc_degrees).toBeGreaterThan(0);
  expect(saved.positions).toHaveLength(12);
  await expect(view.getByRole('region', { name: 'Solar-arc result' })).toContainText('not a simultaneous sky');
  await view.getByText(/Directed positions and natal aspects/).click();
  await expect(view.getByRole('table', { name: /Solar-arc directions/ }).getByRole('row')).toHaveCount(13);
  const download = page.waitForEvent('download');
  await view.getByRole('button', { name: 'Download safe SVG wheel' }).click();
  const markup = await readFile(await (await download).path(), 'utf8');
  expect(markup).toContain(`"arc_degrees":${saved.arc_degrees}`);
  expect(markup).toContain(`"mapped_ephemeris_utc":"${saved.mapped_ephemeris_utc}"`);
  await view.getByRole('button', { name: /Open saved solar arc/ }).click();
  await view.getByText(/Directed positions and natal aspects/).click();
  await expect(view.getByRole('table', { name: /Solar-arc directions/ }).getByRole('row')).toHaveCount(13);
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.screenshot({ path: resolve(renders, `solar-arc-normal-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
});
