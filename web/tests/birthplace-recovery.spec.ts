import { test, expect, type Page } from '@playwright/test';
import { personIdFor } from './legacy-fixture';

async function newPerson(page: Page, account: string, name: string) {
  await page.goto('/');
  await page.getByLabel('Username').fill(account);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  if (page.viewportSize()!.width <= 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill(name);
  await dialog.getByRole('button', { name: 'Create person' }).click();
  await expect(page.getByRole('region', { name: 'Generate a chart' })).toBeVisible();
  return page.getByRole('region', { name: 'Generate a chart' });
}

async function reopen(page: Page, name: string) {
  await page.reload();
  if (page.viewportSize()!.width <= 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: new RegExp(name) }).click();
  await page.getByRole('button', { name: 'Edit current chart' }).click();
  return page.getByRole('region', { name: 'Generate a chart' });
}

test('ten city results keep each wrapped label inside its own hit target in both palettes', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 640 });
  const form = await newPerson(page, 'reader-appearance', 'Synthetic place list');
  for (const theme of ['reading-room', 'blue-hour']) {
    await page.evaluate(theme => localStorage.setItem('kat.appearance.theme', theme), theme);
    await page.reload();
    if (page.viewportSize()!.width <= 700) await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic place list/ }).click();
    await page.getByRole('button', { name: 'Create first chart' }).click();
    for (const size of [{ width: 390, height: 640 }, { width: 1440, height: 1024 }]) {
      await page.setViewportSize(size);
      await form.getByLabel('Birthplace search').fill('San');
      const results = form.locator('.place-results button');
      await expect(results).toHaveCount(10);
      const geometry = await results.evaluateAll(buttons => buttons.map(button => {
        const hit = button.getBoundingClientRect();
        const label = button.querySelector('small')!.getBoundingClientRect();
        return { top: hit.top, bottom: hit.bottom, labelBottom: label.bottom, height: hit.height };
      }));
      for (let i = 0; i < geometry.length; i++) {
        expect(geometry[i].height).toBeGreaterThanOrEqual(40);
        expect(geometry[i].labelBottom).toBeLessThanOrEqual(geometry[i].bottom);
        if (i) expect(geometry[i].top).toBeGreaterThanOrEqual(geometry[i - 1].bottom);
      }
      await results.last().focus();
      await expect(results.last()).toBeFocused();
      await page.screenshot({ path: test.info().outputPath(`places-${theme}-${size.width}-last.png`) });
      await results.first().click();
      await expect(form.getByRole('button', { name: 'Change birthplace' })).toBeVisible();
      await form.getByRole('button', { name: 'Change birthplace' }).click();
    }
  }
});

test('saved catalogue location can change explicitly; saved manual inputs survive an ordinary edit', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 640 });
  const name = 'Synthetic saved overrides';
  let form = await newPerson(page, 'reader-advanced-ux', name);
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('03:06');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  await form.locator('.birth-advanced > summary').click();
  await form.getByLabel('Latitude override').fill('55.6');
  await form.getByLabel('Longitude override').fill('12.5');
  await form.getByLabel('IANA timezone override').fill('Europe/Stockholm');
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.locator('.birth-status')).toContainText('Current natal saved');
  form = await reopen(page, name);
  await expect(form.getByRole('button', { name: 'Change birthplace' })).toBeVisible();
  await form.locator('.birth-advanced > summary').click();
  await expect(form.getByLabel('Latitude override')).toHaveValue('55.6');
  await expect(form.getByLabel('Longitude override')).toHaveValue('12.5');
  await expect(form.getByLabel('IANA timezone override')).toHaveValue('Europe/Stockholm');
  await page.screenshot({ path: test.info().outputPath('saved-overrides-short.png') });
  await form.getByLabel('Birth time').fill('03:07');
  const changed = page.waitForResponse(response => response.request().method() === 'POST' && /\/generate$/.test(response.url()));
  await form.getByRole('button', { name: 'Generate chart' }).click();
  const result = await (await changed).json();
  expect(result.chart.result.birth).toMatchObject({ latitude: 55.6, longitude: 12.5, zone: 'Europe/Stockholm',
    provenance: 'provisional:user_supplied_coordinates_place_2618425' });
  form = await reopen(page, name);
  await form.getByRole('button', { name: 'Change birthplace' }).click();
  await expect(form.getByLabel('Latitude override')).toHaveValue('');
  await expect(form.getByLabel('IANA timezone override')).toHaveValue('');
  await form.getByLabel('Birthplace search').fill('Berlin');
  await form.getByRole('button', { name: /Berlin, State of Berlin, Germany/ }).first().click();
  await page.screenshot({ path: test.info().outputPath('changed-place-short.png') });
  const other = page.waitForResponse(response => response.request().method() === 'POST' && /\/generate$/.test(response.url()));
  await form.getByRole('button', { name: 'Generate chart' }).click();
  const newResult = await (await other).json();
  expect(newResult.place_id).not.toBe('2618425');
  expect(newResult.chart.result.birth.zone).toBe('Europe/Berlin');
  expect(newResult.chart.id).not.toBe(result.chart.id);
});

test('manual-only edit, unmatched draft and unavailable lookup retain a deliberate recovery', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 640 });
  const name = 'Synthetic manual recovery';
  let form = await newPerson(page, 'reader-return-created', name);
  const personId = await personIdFor(page, name);
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('03:06');
  await form.getByLabel('Birthplace search').fill('Synthetic farm near Berlin');
  await form.locator('.birth-advanced > summary').click();
  await form.getByLabel('Latitude override').fill('50.1');
  await form.getByLabel('Longitude override').fill('10.2');
  await form.getByLabel('IANA timezone override').fill('Europe/Berlin');
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.locator('.birth-status')).toContainText('Current natal saved');
  form = await reopen(page, name);
  await expect(form.getByText(/Saved manual location/)).toContainText('50.1, 10.2 · Europe/Berlin');
  await expect(form.getByLabel('Latitude override')).toHaveValue('50.1');
  await page.screenshot({ path: test.info().outputPath('manual-short.png') });
  const revision = await page.evaluate(async personId => {
    const { csrf } = await fetch('/api/session').then(response => response.json());
    const response = await fetch(`/api/people/${personId}/drafts`, { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Kat-CSRF': csrf },
      body: JSON.stringify({ birth_date: '2024-03-20', birth_time: '03:06', time_unknown: false,
        birthplace: 'Copenhagen, Capital Region, Denmark' }) });
    return response.status;
  }, personId);
  expect(revision).toBe(201);
  await page.route('**/api/places/search', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  form = await reopen(page, name);
  await expect(form.getByText(/Saved birthplace: Copenhagen, Capital Region, Denmark/)).toBeVisible();
  await expect(form.getByLabel('Birthplace search')).toHaveValue('Copenhagen');
  await expect(form.getByRole('button', { name: 'Change birthplace' })).toHaveCount(0);
  await expect(form.getByText(/Local city search is unavailable/)).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('unmatched-unavailable-short.png') });
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.locator('#birthplace-error')).toBeVisible();
  await expect(form.getByLabel('Birthplace search')).toHaveAttribute('aria-invalid', 'true');
  await expect(form.getByLabel('Birthplace search')).toBeFocused();
  await page.screenshot({ path: test.info().outputPath('unmatched-error-short.png') });
  await expect(form.getByLabel('Birthplace search')).toHaveValue('Copenhagen');
});
