import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/post-deployment-features');

test('on-demand dated transits keep natal fixed and stop or scrub without sending', async ({ page }) => {
  test.setTimeout(90000);
  const pageErrors: string[] = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  mkdirSync(renders, { recursive: true });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-motion');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic motion reader');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('04:06');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).first().click();
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.locator('.birth-status')).toContainText('Current natal saved');
  const charts = page.getByRole('tabpanel', { name: 'Charts' });
  let samples = 0, sends = 0;
  page.on('request', request => {
    if (request.url().includes('/transit-frames')) samples++;
    if (request.method() === 'POST' && /\/(turns|chat)$/.test(new URL(request.url()).pathname)) sends++;
  });
  const panel = charts.locator('.transit-motion');
  await expect(panel).toBeVisible();
  await expect(panel).not.toHaveAttribute('open', '');
  expect(samples).toBe(0);
  await panel.locator('summary').click();
  await panel.getByLabel('From (UTC)').fill('2024-04-01');
  await panel.getByLabel('To (UTC)').fill('2024-04-08');
  expect(samples).toBe(0);
  const response = page.waitForResponse(item => item.url().includes('/transit-frames') && item.status() === 200);
  await panel.getByRole('button', { name: 'Show transits' }).click();
  expect((await response).status()).toBe(200);
  await expect(panel.getByRole('img', { name: /Transiting planets around the fixed natal chart/ })).toBeVisible();
  await panel.locator('.motion-controls').scrollIntoViewIfNeeded();
  await panel.getByRole('button', { name: 'Play', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'Pause' })).toBeVisible();
  expect(pageErrors).toEqual([]);
  await panel.getByRole('button', { name: 'Pause' }).click();
  await panel.getByRole('button', { name: 'Play', exact: true }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(panel.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  expect(samples).toBe(1); expect(sends).toBe(0);
  const savedNatal = await charts.locator('.natal-tables').first().innerText();
  const slider = panel.getByRole('slider', { name: 'Transit date' });
  await slider.focus(); await page.keyboard.press('End');
  await expect(slider).toHaveAttribute('aria-valuetext', /2024-04-08 00:00 UTC/);
  expect(await charts.locator('.natal-tables').first().innerText()).toBe(savedNatal);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 },
    { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `motion-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(panel.getByRole('button', { name: 'Replay' })).toBeDisabled();
  await expect(panel.getByText('Reduced motion is on. Use the time slider to view each moment.')).toBeVisible();
  await slider.focus(); await page.keyboard.press('Home');
  await expect(slider).toHaveAttribute('aria-valuetext', /2024-04-01 00:00 UTC/);
  expect(sends).toBe(0);
});

test('empty, loading and failed transit controls retain dates without an automatic retry', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 640 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-clock-desktop');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: /Synthetic transit reader/ }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  const panel = page.locator('.transit-motion');
  let requests = 0;
  page.on('request', request => { if (request.url().includes('/transit-frames')) requests++; });
  await expect(panel).not.toHaveAttribute('open');
  expect(requests).toBe(0);
  await panel.locator('summary').click();
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath('transits-empty-short.png') });
  await panel.getByLabel('From (UTC)').fill('2026-01-01');
  await panel.getByLabel('To (UTC)').fill('2026-01-03');
  let release!: () => void;
  let arrived!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const seen = new Promise<void>(resolve => { arrived = resolve; });
  await page.route('**/api/charts/*/transit-frames?*', async route => {
    arrived(); await gate;
    await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"unavailable"}' });
  });
  await panel.getByRole('button', { name: 'Show transits' }).click();
  await seen;
  await expect(panel.getByRole('button', { name: 'Loading transits…' })).toBeDisabled();
  await page.screenshot({ path: test.info().outputPath('transits-loading-short.png') });
  release();
  await expect(panel.getByRole('alert')).toContainText('Transits could not be loaded');
  await expect(panel.getByLabel('From (UTC)')).toHaveValue('2026-01-01');
  await expect(panel.getByLabel('To (UTC)')).toHaveValue('2026-01-03');
  expect(requests).toBe(1);
  await page.screenshot({ path: test.info().outputPath('transits-error-short.png') });
});

test('conjunction scrub leaves each moving glyph visible at its linked longitude', async ({ page }) => {
  test.setTimeout(120000);
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1'
    ? route.continue() : route.abort());
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-motion-conjunction');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: 'Add person', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'A space for someone new.' });
  await dialog.getByLabel('Name').fill('Synthetic conjunction reader');
  await dialog.getByRole('button', { name: 'Create person' }).click();
  const form = page.getByRole('region', { name: 'Generate a chart' });
  await form.getByLabel('Birth date').fill('2024-03-20');
  await form.getByLabel('Birth time').fill('04:06');
  await form.getByLabel('Birthplace search').fill('Copenhagen');
  await form.getByRole('button', { name: /Copenhagen, Capital Region, Denmark/ }).first().click();
  await form.getByRole('button', { name: 'Generate chart' }).click();
  await expect(form.locator('.birth-status')).toContainText('Current natal saved');
  const panel = page.getByRole('tabpanel', { name: 'Charts' }).locator('.transit-motion');
  await panel.locator('summary').click();
  await panel.getByLabel('From (UTC)').fill('2024-04-02');
  await panel.getByLabel('To (UTC)').fill('2024-04-09');
  const response = page.waitForResponse(item => item.url().includes('/transit-frames') && item.status() === 200);
  await panel.getByRole('button', { name: 'Show transits' }).click();
  const frames = await (await response).json() as { bodies: string[]; longitudes: number[][] };
  expect(frames.longitudes).toHaveLength(673);
  const slider = panel.getByRole('slider', { name: 'Transit date' });
  // Use the native range setter so React receives a real input event at the exact Swiss sample.
  await slider.evaluate((input: HTMLInputElement) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, '648');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await expect(slider).toHaveAttribute('aria-valuetext', '2024-04-08 18:00 UTC');
  const wheel = panel.locator('svg.natal-wheel');
  const marks: Record<string, { x: number; y: number }> = {};
  for (const [body, glyph] of [['sun', '☉'], ['moon', '☽'], ['mercury', '☿']]) {
    marks[body] = await wheel.locator('text').filter({ hasText: glyph }).last().evaluate(node => {
      const circle = node.parentElement!.querySelector('circle')!;
      return { x: Number(circle.getAttribute('cx')), y: Number(circle.getAttribute('cy')) };
    });
  }
  for (const [a, b] of [['sun', 'moon'], ['sun', 'mercury'], ['moon', 'mercury']]) {
    expect(Math.hypot(marks[a].x - marks[b].x, marks[a].y - marks[b].y), `${a}/${b} label centers`).toBeGreaterThanOrEqual(24);
  }
  const allMarks = await wheel.locator('g[data-sky-body] > circle:first-of-type').evaluateAll(circles => circles.map(circle => ({
    x: Number(circle.getAttribute('cx')), y: Number(circle.getAttribute('cy')),
  })));
  expect(allMarks).toHaveLength(frames.bodies.length);
  for (let i = 0; i < allMarks.length; i++) {
    for (let j = i + 1; j < allMarks.length; j++) {
      expect(Math.hypot(allMarks[i].x - allMarks[j].x, allMarks[i].y - allMarks[j].y), `outer glyphs ${i}/${j}`).toBeGreaterThanOrEqual(24);
    }
  }
  for (const body of ['sun', 'moon', 'mercury']) {
    const root = wheel.locator(`g[data-sky-body="${body}"] line`);
    const { x, y } = await root.evaluate(line => ({ x: Number(line.getAttribute('x1')), y: Number(line.getAttribute('y1')) }));
    const degrees = frames.longitudes[648][frames.bodies.indexOf(body)];
    const radians = Math.PI - degrees * Math.PI / 180;
    expect(Math.hypot(x - 240 - 156 * Math.cos(radians), y - 240 - 156 * Math.sin(radians)), `${body} Swiss sample link`).toBeLessThan(0.1);
  }

  mkdirSync(renders, { recursive: true });
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 },
    { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, `conjunction-corrected-${size.name}.png`), fullPage: true });
    await wheel.screenshot({ path: resolve(renders, `conjunction-wheel-${size.name}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
  await slider.focus(); await page.keyboard.press('Home');
  await expect(slider).toHaveAttribute('aria-valuetext', '2024-04-02 00:00 UTC');
  await wheel.screenshot({ path: resolve(renders, 'conjunction-wheel-start.png') });
  await page.keyboard.press('End');
  await expect(slider).toHaveAttribute('aria-valuetext', '2024-04-09 00:00 UTC');
  await wheel.screenshot({ path: resolve(renders, 'conjunction-wheel-end.png') });
});
