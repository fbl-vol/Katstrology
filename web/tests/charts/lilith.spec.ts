import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/post-deployment-features');

test('opt-in mean lunar apogee survives archive and export; default and sky-only omit it', async ({ page }) => {
  test.setTimeout(100000);
  mkdirSync(renders, { recursive: true });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-lilith');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic apogee reader');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2017-11-09');
  await form.getByLabel('Birth time').fill('04:58');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).first().click();
  await form.getByText('Advanced · chart settings and location').click();
  const selector = form.getByLabel('Black Moon Lilith (lunar apogee)');
  await expect(selector).toHaveValue('off');
  await selector.selectOption('mean');
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.locator('.birth-status')).toContainText('Current natal saved');
  const charts = page.getByRole('tabpanel', { name: 'Charts' });
  const selected = (await (await page.request.get('/api/people')).json()).people
    .find((person: { name: string }) => person.name === 'Synthetic apogee reader');
  expect(selected?.active_chart_id).toBeTruthy();
  const query = 'date=2025-02-01&time=12%3A00&zone=Europe%2FCopenhagen&occurrence=unspecified';
  const sky = await (await page.request.get(`/api/transit-view?${query}&mode=sky`)).json();
  expect(sky.positions.some((item: { id: string }) => item.id.startsWith('lilith_'))).toBe(false);
  const combined = await (await page.request.get(`/api/transit-view?${query}&mode=natal_transits&person_id=${selected.id}`)).json();
  expect(combined.lilith_convention).toBe('mean');
  expect(combined.positions.some((item: { id: string }) => item.id === 'lilith_mean')).toBe(true);
  await charts.getByText('All chart tables', { exact: true }).first().click();
  await expect(charts.getByRole('row', { name: /Black Moon Lilith \(mean lunar apogee\)/ }).first()).toBeVisible();
  await expect(charts.getByText('Swiss mean lunar apogee').first()).toBeVisible();
  const downloadPromise = page.waitForEvent('download');
  await charts.getByRole('button', { name: 'Download safe SVG wheel' }).first().click();
  const xml = await readFile(await (await downloadPromise).path(), 'utf8');
  expect(xml).toContain('lilith_mean');
  expect(xml).toContain('include_lilith');
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 },
    { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.screenshot({ path: resolve(renders, `mean-${size.name}.png`), fullPage: true });
  }
  await page.reload();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic apogee reader/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  await page.getByRole('tabpanel', { name: 'Charts' }).getByText('All chart tables', { exact: true }).first().click();
  await expect(page.getByRole('tabpanel', { name: 'Charts' }).getByRole('row', { name: /Black Moon Lilith \(mean lunar apogee\)/ }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Edit birth details' }).click();
  await form.getByText('Advanced · chart settings and location').click();
  await form.getByLabel('Black Moon Lilith (lunar apogee)').selectOption('osculating', { timeout: 8000 });
  await expect(form.getByRole('button', { name: 'Change birthplace' })).toBeVisible();
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.locator('.birth-status')).toContainText('Current natal saved');
  await expect(charts.getByRole('row', { name: /Black Moon Lilith \(true \/ osculating lunar apogee\)/ }).first()).toBeVisible();
  await expect(charts.getByText('Swiss osculating lunar apogee', { exact: false }).first()).toBeVisible();
  const history = await (await page.request.get(`/api/people/${selected.id}`)).json();
  const historical = history.charts.find((item: { id: string }) => item.id === selected.active_chart_id);
  expect(historical.result.profile.settings.include_lilith).toBe('mean');
  expect(historical.result.natal.positions.some((item: { id: string }) => item.id === 'lilith_mean')).toBe(true);
  for (const size of [{ name: 'desktop', width: 1440, height: 1024 },
    { name: 'short', width: 390, height: 560 }]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.screenshot({ path: resolve(renders, `osculating-${size.name}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('region', { name: 'Create chart' }).getByRole('button', { name: /^Transits/ }).click();
  const transit = page.getByRole('region', { name: 'Sky at a date' });
  await transit.getByRole('radio', { name: 'Natal + transits' }).check();
  await transit.getByLabel('Date').fill('2025-02-01');
  await transit.getByLabel('Copenhagen time').fill('12:00');
  await transit.getByLabel('Person').selectOption(selected.id);
  await transit.getByRole('button', { name: 'Show calculated view' }).click();
  await expect(transit.getByText('Black Moon Lilith: true / osculating lunar apogee', { exact: false })).toBeVisible();
  await page.screenshot({ path: resolve(renders, 'osculating-transits-desktop.png'), fullPage: true });
});
