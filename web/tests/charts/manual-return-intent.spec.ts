import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/ux-followup');

// A separate owner keeps these saved calculations out of other browser scenarios.
test('return calculation defaults, missing-source recovery, rejected year and result handoff', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 560 });
  await page.route('**/api/clock?zone=UTC', route => route.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ instant_utc: '2027-06-01T09:30:00+00:00' }) }));
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced-ux');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
  const view = page.getByRole('region', { name: 'Solar return chart' });
  await expect(view.getByRole('heading', { name: 'Solar return', exact: true })).toBeFocused();
  await expect(view.getByLabel('UTC anniversary year')).toHaveValue('2027');
  await view.getByLabel('Person with a current natal').selectOption('legacy-transit-person');
  await expect(view.getByRole('button', { name: 'Calculate solar return' })).toBeDisabled();
  await expect(view.getByRole('button', { name: 'Create or review natal' })).toBeVisible();
  mkdirSync(renders, { recursive: true });
  await page.screenshot({ path: resolve(renders, 'missing-natal-short-mobile.png'), fullPage: true });
  await view.getByLabel('UTC anniversary year').fill('2028');
  await view.getByRole('button', { name: 'Create or review natal' }).click();
  await expect(page.getByRole('tab', { name: 'Charts' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.profile-editor')).toBeVisible();
  await page.getByRole('button', { name: /Return to workspace/ }).click();
  await expect(view.getByLabel('UTC anniversary year')).toHaveValue('2028');
  await expect(view.getByLabel('Person with a current natal')).toHaveValue('legacy-transit-person');
  await view.getByLabel('Person with a current natal').selectOption('transit-person');
  await expect(view.getByText('Birthplace', { exact: true })).toBeVisible();
  await view.getByLabel('UTC anniversary year').fill('2000');
  await expect(view.getByText('Choose 2001 or a later UTC anniversary year for this natal.')).toBeVisible();
  await expect(view.getByRole('button', { name: 'Calculate solar return' })).toBeDisabled();
  await view.getByLabel('UTC anniversary year').fill('2027');
  await view.getByRole('button', { name: 'Calculate solar return' }).click();
  const result = view.getByRole('heading', { name: /Solar return for Synthetic transit reader/ });
  await expect(result).toBeFocused();
  const position = await result.evaluate(element => element.getBoundingClientRect().top);
  const headerBottom = await page.locator('.main .header').evaluate(element => element.getBoundingClientRect().bottom);
  expect(position).toBeGreaterThanOrEqual(headerBottom + 8);
  expect(position).toBeLessThan(560);
  await expect(view.locator('.advanced-event')).toHaveCount(2);
  const historyLabel = view.getByRole('button', { name: /Open saved solar return/ }).first();
  await expect(historyLabel).toContainText('21 Jun 2027');
  await expect(historyLabel).toContainText('21 Jun 2028');
  await expect(historyLabel).toContainText('2 crossings');
  mkdirSync(renders, { recursive: true });
  await page.screenshot({ path: resolve(renders, 'solar-two-crossings-short-mobile.png') });
  await view.getByRole('navigation', { name: 'Choose a return crossing' })
    .getByRole('button', { name: /Return 2/ }).click();
  await expect(view.getByRole('heading', { name: /Solar return 2/ })).toBeFocused();
  await view.getByRole('button', { name: /Open saved solar return/ }).click();
  await expect(result).toBeFocused();
  await expect(view.locator('.advanced-event')).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.screenshot({ path: resolve(renders, 'solar-two-crossings-desktop.png'), fullPage: true });
});

test('creating the missing natal resumes the chosen return and uses its new birthplace', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-return-created');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
  const view = page.getByRole('region', { name: 'Solar return chart' });
  await view.getByLabel('Person with a current natal').selectOption('legacy-transit-person');
  await view.getByLabel('UTC anniversary year').fill('2026');
  await view.getByRole('button', { name: 'Create or review natal' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2001-06-21');
  await form.getByLabel('Birth time').fill('04:00');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).click();
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(page.locator('.profile-active-chart')).toBeVisible();
  await page.getByRole('button', { name: /Return to workspace/ }).click();
  await expect(view.getByLabel('Person with a current natal')).toHaveValue('legacy-transit-person');
  await expect(view.getByLabel('UTC anniversary year')).toHaveValue('2026');
  await expect(view.getByText('Birthplace', { exact: true })).toBeVisible();
  await expect(view.getByRole('button', { name: 'Calculate solar return' })).toBeEnabled();
  await view.getByRole('button', { name: 'Calculate solar return' }).click();
  await expect(view.getByRole('heading', { name: /Solar return for Legacy chart without generated natal/ })).toBeFocused();
});

test('a late application clock does not replace a focused or manually cleared return year', async ({ page }) => {
  let releaseClock: (() => void) | undefined;
  const clockHeld = new Promise<void>(resolve => { releaseClock = resolve; });
  await page.route('**/api/clock?zone=UTC', async route => {
    await clockHeld;
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ instant_utc: '2027-06-01T09:30:00+00:00' }) });
  });
  try {
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-advanced-ux');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByRole('button', { name: '＋ Create chart' }).click();
    await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
    const year = page.getByRole('region', { name: 'Solar return chart' }).getByLabel('UTC anniversary year');
    await year.focus();
    const clockResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/clock');
    releaseClock?.();
    await clockResponse;
    await page.evaluate(() => new Promise<void>(resolve =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(year).toHaveValue('');
    await year.blur();
    await expect(year).toHaveValue('2027');
    await year.fill('2026');
    await expect(year).toHaveValue('2026');
    await year.fill('');
    await expect(year).toHaveValue('');
  } finally { releaseClock?.(); }
});

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short-mobile', width: 390, height: 560 },
]) {
  test(`return year renders default, edited, delayed and recovery on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    let releaseClock: () => void = () => {};
    const held = new Promise<void>(resolve => { releaseClock = resolve; });
    await page.route('**/api/clock?zone=UTC', async route => {
      await held;
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ instant_utc: '2027-06-01T09:30:00+00:00' }) });
    });
    const destination = resolve(import.meta.dirname, '../../../.local/year-f2-renders');
    try {
      await page.goto('/');
      await page.getByLabel('Username').fill('reader-advanced-ux');
      await page.getByLabel('Password').fill('synthetic-browser-password');
      await page.getByRole('button', { name: 'Open workspace' }).click();
      if (viewport.width < 500) await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('button', { name: '＋ Create chart' }).click();
      await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
      const view = page.getByRole('region', { name: 'Solar return chart' });
      const year = view.getByLabel('UTC anniversary year');
      await year.focus();
      await expect(year).toHaveValue('');
      mkdirSync(destination, { recursive: true });
      await page.screenshot({ path: resolve(destination, `${viewport.name}-delayed.png`), fullPage: true });
      releaseClock();
      await year.blur();
      await expect(year).toHaveValue('2027');
      await page.screenshot({ path: resolve(destination, `${viewport.name}-default.png`), fullPage: true });
      await year.fill('2026');
      await view.getByLabel('Person with a current natal').selectOption('legacy-transit-person');
      await expect(view.getByRole('button', { name: 'Create or review natal' })).toBeVisible();
      await page.screenshot({ path: resolve(destination, `${viewport.name}-edited.png`), fullPage: true });
      await view.getByRole('button', { name: 'Create or review natal' }).click();
      await expect(page.locator('.profile-editor')).toBeVisible();
      await page.getByRole('button', { name: /Return to workspace/ }).click();
      await expect(year).toHaveValue('2026');
      await page.screenshot({ path: resolve(destination, `${viewport.name}-recovery.png`), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
    } finally { releaseClock(); }
  });
}

for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short-mobile', width: 390, height: 560 },
]) {
  for (const timing of ['timely', 'delayed'] as const) {
    test(`deliberately cleared return year survives natal recovery ${timing} ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      let releaseClock: () => void = () => {};
      const held = new Promise<void>(resolve => { releaseClock = resolve; });
      await page.route('**/api/clock?zone=UTC', async route => {
        if (timing === 'delayed') await held;
        await route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ instant_utc: '2027-06-01T09:30:00+00:00' }) });
      });
      const destination = resolve(import.meta.dirname, '../../../.local/year-f2-review-fixes');
      try {
        await page.goto('/');
        await page.getByLabel('Username').fill('reader-advanced-ux');
        await page.getByLabel('Password').fill('synthetic-browser-password');
        await page.getByRole('button', { name: 'Open workspace' }).click();
        if (viewport.width < 500) await page.getByRole('button', { name: 'Open navigation' }).click();
        await page.getByRole('button', { name: '＋ Create chart' }).click();
        await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
        const view = page.getByRole('region', { name: 'Solar return chart' });
        const year = view.getByLabel('UTC anniversary year');
        if (timing === 'timely') await expect(year).toHaveValue('2027');
        await year.fill('2026');
        await year.fill('');
        await expect(year).toBeFocused();
        await view.getByLabel('Person with a current natal').selectOption('legacy-transit-person');
        await expect(view.getByRole('button', { name: 'Create or review natal' })).toBeVisible();
        await expect(year).toHaveValue('');
        mkdirSync(destination, { recursive: true });
        await page.screenshot({ path: resolve(destination,
          `${viewport.name}-${timing}-cleared.png`), fullPage: true });
        await view.getByRole('button', { name: 'Create or review natal' }).click();
        await expect(page.locator('.profile-editor')).toBeVisible();
        await page.getByRole('button', { name: /Return to workspace/ }).click();
        await expect(year).toHaveValue('');
        if (timing === 'delayed') {
          const response = page.waitForResponse(reply => new URL(reply.url()).pathname === '/api/clock');
          releaseClock();
          await response;
          await page.evaluate(() => new Promise<void>(resolve =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
          await expect(year).toHaveValue('');
        }
        await page.screenshot({ path: resolve(destination,
          `${viewport.name}-${timing}-returned-empty.png`), fullPage: true });
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
      } finally { releaseClock(); }
    });
  }
}

test('untouched return year receives a late clock after natal recovery', async ({ page }) => {
  let releaseClock: () => void = () => {};
  const held = new Promise<void>(resolve => { releaseClock = resolve; });
  await page.route('**/api/clock?zone=UTC', async route => {
    await held;
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ instant_utc: '2027-06-01T09:30:00+00:00' }) });
  });
  try {
    await page.goto('/');
    await page.getByLabel('Username').fill('reader-advanced-ux');
    await page.getByLabel('Password').fill('synthetic-browser-password');
    await page.getByRole('button', { name: 'Open workspace' }).click();
    await page.getByRole('button', { name: '＋ Create chart' }).click();
    await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
    const view = page.getByRole('region', { name: 'Solar return chart' });
    const year = view.getByLabel('UTC anniversary year');
    await view.getByLabel('Person with a current natal').selectOption('legacy-transit-person');
    await view.getByRole('button', { name: 'Create or review natal' }).click();
    await page.getByRole('button', { name: /Return to workspace/ }).click();
    await expect(year).toHaveValue('');
    const response = page.waitForResponse(reply => new URL(reply.url()).pathname === '/api/clock');
    releaseClock();
    await response;
    await expect(year).toHaveValue('2027');
  } finally { releaseClock(); }
});

test('failed clock leaves the return year editable without an invented default', async ({ page }) => {
  await page.route('**/api/clock?zone=UTC', route => route.fulfill({ status: 503,
    contentType: 'application/json', body: '{"error":"unavailable"}' }));
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced-ux');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
  const view = page.getByRole('region', { name: 'Solar return chart' });
  await expect(view.getByText('Application date is unavailable. Choose a year or dates yourself.')).toBeVisible();
  const year = view.getByLabel('UTC anniversary year');
  await expect(year).toHaveValue('');
  await year.fill('2026');
  await expect(year).toHaveValue('2026');
  await year.fill('');
  await view.getByLabel('Person with a current natal').selectOption('legacy-transit-person');
  await view.getByRole('button', { name: 'Create or review natal' }).click();
  await page.getByRole('button', { name: /Return to workspace/ }).click();
  await expect(year).toHaveValue('');
  await year.fill('2026');
  await expect(year).toHaveValue('2026');
});

test('zero crossings retain the selected UTC cycle and focused result', async ({ page }) => {
  await page.route('**/api/clock?zone=UTC', route => route.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ instant_utc: '2028-02-29T08:00:00+00:00' }) }));
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced-ux');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
  const view = page.getByRole('region', { name: 'Solar return chart' });
  await expect(view.getByLabel('UTC anniversary year')).toHaveValue('2028');
  await view.getByLabel('Person with a current natal').selectOption('other-transit-person');
  await view.getByLabel('UTC anniversary year').fill('2026');
  await expect(view.getByRole('button', { name: 'Calculate solar return' })).toBeEnabled();
  const noReturn = page.waitForResponse(response => response.request().method() === 'POST' &&
    new URL(response.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Calculate solar return' }).click();
  const calculated = await (await noReturn).json();
  expect(calculated.status).toBe('no_return_in_window');
  expect(calculated.events).toEqual([]);
  await expect(view.getByRole('heading', { name: /No return crossings in this interval · 0 found/ })).toBeFocused();
  await expect(view.getByRole('status').last()).toContainText('4 Feb 2026, 09:15 to 4 Feb 2027, 09:15 UTC (end excluded)');
  await expect(view.locator('.advanced-event')).toHaveCount(0);
  await view.getByRole('button', { name: 'Back to chart choices' }).click();
  await page.getByRole('button', { name: /Lunar returns Choose a person/ }).click();
  const lunar = page.getByRole('region', { name: 'Lunar returns chart' });
  await expect(lunar.getByLabel('From (UTC, inclusive)')).toHaveValue('2028-02-29');
  await expect(lunar.getByLabel('Until (UTC, exclusive)')).toHaveValue('2028-03-30');
});

test('offline reference city changes houses, not the saved geocentric return', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced-ux');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
  const view = page.getByRole('region', { name: 'Solar return chart' });
  await view.getByLabel('Person with a current natal').selectOption('transit-person');
  await view.getByLabel('UTC anniversary year').fill('2026');
  await expect(view.getByText('Birthplace', { exact: true })).toBeVisible();
  const firstPost = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Calculate solar return' }).click();
  const birthplace = await (await firstPost).json();
  expect(birthplace.reference_place_source.kind).toBe('saved_birthplace_coordinates');
  await view.getByRole('button', { name: 'Change place' }).click();
  await view.getByLabel('Find a city or town').fill('Copenhagen');
  const city = view.getByRole('group', { name: 'Offline reference places' })
    .getByRole('button', { name: /^Copenhagen, Capital Region, Denmark/ });
  await city.click();
  await expect(view.getByText('Copenhagen, Capital Region, Denmark', { exact: true })).toBeVisible();
  const cityPost = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Calculate solar return' }).click();
  const relocated = await (await cityPost).json();
  expect(relocated.reference_place_source).toEqual({
    kind: 'offline_city_centre', label: 'Copenhagen, Capital Region, Denmark', place_id: '2618425',
  });
  expect(relocated.events.map((entry: { instant_utc: string }) => entry.instant_utc))
    .toEqual(birthplace.events.map((entry: { instant_utc: string }) => entry.instant_utc));
  expect(relocated.events[0].chart.houses.angles)
    .not.toEqual(birthplace.events[0].chart.houses.angles);
  await view.getByRole('button', { name: /Open saved solar return · .*Copenhagen, Capital Region, Denmark/ }).click();
  await expect(view.getByText(/Copenhagen, Capital Region, Denmark: 55/)).toBeVisible();
});

test('manual technique defaults come from the application UTC clock', async ({ page }) => {
  await page.route('**/api/clock?zone=UTC', route => route.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ instant_utc: '2028-12-30T23:59:00+00:00' }) }));
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced-ux');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Midheaven transit contacts/ }).click();
  const mc = page.getByRole('region', { name: 'Natal MC transit timeline' });
  await expect(mc.getByLabel('From (UTC, inclusive)')).toHaveValue('2028-12-30');
  await expect(mc.getByLabel('Until (UTC, exclusive)')).toHaveValue('2029-01-29');
  await mc.getByRole('button', { name: 'Back to chart choices' }).click();
  await page.getByRole('button', { name: /Solar-arc directions/ }).click();
  await expect(page.getByRole('region', { name: 'True solar-arc directions' })
    .getByLabel('Effective date (UTC midnight)')).toHaveValue('2028-12-30');
  await page.getByRole('button', { name: 'Back to chart choices' }).click();
  await page.getByRole('button', { name: /Lunations and eclipses/ }).click();
  const sky = page.getByRole('region', { name: 'Actual lunations and global eclipses' });
  await expect(sky.getByLabel('From', { exact: true })).toHaveValue('2028-12-30');
  await expect(sky.getByLabel('Until (not included)')).toHaveValue('2029-02-28');
});

test('an older saved-list response cannot erase a newly saved return', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced-ux');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  let releaseOldList: () => void = () => {};
  const oldListReleased = new Promise<void>(resolve => { releaseOldList = resolve; });
  let initialList = true;
  await page.route('**/api/advanced-results?person_id=other-transit-person&technique=solar_return', async route => {
    if (!initialList) { await route.continue(); return; }
    initialList = false;
    const snapshot = await route.fetch();
    await oldListReleased;
    await route.fulfill({ response: snapshot });
  });
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
  const view = page.getByRole('region', { name: 'Solar return chart' });
  await view.getByLabel('Person with a current natal').selectOption('other-transit-person');
  await view.getByLabel('UTC anniversary year').fill('2027');
  await view.getByRole('button', { name: 'Calculate solar return' }).click();
  await expect(view.getByRole('button', { name: /Open saved solar return · .*2027/ })).toBeVisible();
  const staleResponse = page.waitForResponse(response => response.request().method() === 'GET' &&
    response.url().includes('/api/advanced-results?person_id=other-transit-person&technique=solar_return'));
  releaseOldList();
  await staleResponse;
  await page.evaluate(() => new Promise<void>(resolve =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(view.getByRole('button', { name: /Open saved solar return · .*2027/ })).toBeVisible();
});

test('planetary return recovery retains body, period and reference place', async ({ page }) => {
  await page.route('**/api/clock?zone=UTC', route => route.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ instant_utc: '2027-06-01T09:30:00+00:00' }) }));
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced-ux');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Planetary returns/ }).click();
  const view = page.getByRole('region', { name: 'Planetary returns chart' });
  await view.getByLabel('Person with a current natal').selectOption('legacy-transit-person');
  await view.getByLabel('Returning planet').selectOption('mars');
  await view.getByLabel('From', { exact: true }).fill('2027-06-21');
  await view.getByLabel('Until (not included)').fill('2028-06-20');
  await view.getByRole('button', { name: 'Enter precise coordinates' }).click();
  await view.getByLabel('Latitude').fill('44');
  await view.getByLabel('Longitude').fill('-73');
  await expect(view.getByRole('button', { name: 'Find planetary return passes' })).toBeDisabled();
  await view.getByRole('button', { name: 'Create or review natal' }).click();
  await expect(page.locator('.profile-editor')).toBeVisible();
  await page.getByRole('button', { name: /Return to workspace/ }).click();
  await expect(view.getByLabel('Person with a current natal')).toHaveValue('legacy-transit-person');
  await expect(view.getByLabel('Returning planet')).toHaveValue('mars');
  await expect(view.getByLabel('From', { exact: true })).toHaveValue('2027-06-21');
  await expect(view.getByLabel('Until (not included)')).toHaveValue('2028-06-20');
  await expect(view.getByLabel('Latitude')).toHaveValue('44');
  await expect(view.getByLabel('Longitude')).toHaveValue('-73');
});

test('a source read failure can be retried without losing the selected period', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced-ux');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  let failSource = true;
  await page.route('**/api/people/transit-person', route => failSource
    ? route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"unavailable"}' })
    : route.continue());
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Lunar returns Choose a person/ }).click();
  const view = page.getByRole('region', { name: 'Lunar returns chart' });
  await view.getByLabel('From (UTC, inclusive)').fill('2027-06-01');
  await view.getByLabel('Until (UTC, exclusive)').fill('2027-07-01');
  await view.getByLabel('Person with a current natal').selectOption('transit-person');
  await expect(view.getByRole('button', { name: 'Try checking again' })).toBeVisible();
  await expect(view.getByRole('button', { name: 'Calculate lunar returns' })).toBeDisabled();
  failSource = false;
  await view.getByRole('button', { name: 'Try checking again' }).click();
  await expect(view.getByRole('button', { name: 'Calculate lunar returns' })).toBeEnabled();
  await expect(view.getByLabel('From (UTC, inclusive)')).toHaveValue('2027-06-01');
  await expect(view.getByLabel('Until (UTC, exclusive)')).toHaveValue('2027-07-01');
});

test('a definitive invalid request asks for correction, not unchanged retry', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced-ux');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.route('**/api/advanced-results', route => route.request().method() === 'POST'
    ? route.fulfill({ status: 400, contentType: 'application/json', body: '{"error":"invalid_request"}' })
    : route.continue());
  await page.getByRole('button', { name: '＋ Create chart' }).click();
  await page.getByRole('button', { name: /Solar return Choose a person/ }).click();
  const view = page.getByRole('region', { name: 'Solar return chart' });
  await view.getByLabel('Person with a current natal').selectOption('transit-person');
  await expect(view.getByRole('button', { name: 'Calculate solar return' })).toBeEnabled();
  await view.getByRole('button', { name: 'Calculate solar return' }).click();
  await expect(view.getByRole('alert')).toContainText('correct the form');
  await expect(view.getByRole('alert')).not.toContainText('Retry unchanged');
});
