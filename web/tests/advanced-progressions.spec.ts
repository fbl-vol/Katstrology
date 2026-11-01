import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../.local/advanced-techniques');

test('secondary progression keeps mapped date and MCp/MCr distinct in archive and SVG', async ({ page }) => {
  test.setTimeout(90000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('button', { name: /Create chart/ }).first().click();
  await page.getByRole('button', { name: /^Secondary progressions/ }).click();
  const view = page.getByRole('region', { name: 'Secondary progression chart' });
  await view.getByLabel('Person with a current natal').selectOption({ label: 'Synthetic transit reader' });
  await view.getByLabel('Effective date (UTC midnight)').fill('2026-01-01');
  const posted = page.waitForResponse(response => response.request().method() === 'POST' &&
    new URL(response.url()).pathname === '/api/advanced-results');
  await view.getByRole('button', { name: 'Calculate progression' }).click();
  const response = await posted;
  expect(response.status()).toBe(201);
  const saved = await response.json();
  expect(saved.status).toBe('supported');
  expect(saved.method_version).toBe('secondary-utc-calendar-naibod-mc-v1');
  expect(saved.effective_utc).toBe('2026-01-01T00:00:00+00:00');
  expect(saved.mapped_ephemeris_utc).not.toContain('2026');
  await expect(view.getByRole('region', { name: 'Progression result' })).toContainText('MCp');
  await expect(view.getByRole('region', { name: 'Progression result' })).toContainText('MCr');
  await page.setViewportSize({ width: 390, height: 560 });
  mkdirSync(resolve(import.meta.dirname, '../../.local/ux-followup'), { recursive: true });
  await page.screenshot({ path: resolve(import.meta.dirname, '../../.local/ux-followup/progression-collapsed-short-mobile.png'), fullPage: true });
  await page.screenshot({ path: resolve(import.meta.dirname, '../../.local/ux-followup/progression-result-viewport.png') });
  await page.setViewportSize({ width: 1440, height: 1024 });
  let disclosurePosts = 0;
  page.on('request', request => { if (request.method() === 'POST' &&
    new URL(request.url()).pathname === '/api/advanced-results') disclosurePosts++; });
  await view.getByText('Positions, natal aspects and MC contacts').focus();
  await page.keyboard.press('Enter');
  expect(disclosurePosts).toBe(0);
  await expect(view.getByRole('table', { name: /Progressed planetary positions/ }).getByRole('row')).toHaveCount(11);
  const download = page.waitForEvent('download');
  await view.getByRole('button', { name: 'Download safe SVG wheel' }).click();
  const markup = await readFile(await (await download).path(), 'utf8');
  expect(markup).toContain(`"effective_utc":"${saved.effective_utc}"`);
  expect(markup).toContain(`"mapped_ephemeris_utc":"${saved.mapped_ephemeris_utc}"`);
  await view.getByRole('button', { name: /Open saved progression/ }).click();
  await view.getByText('Positions, natal aspects and MC contacts').click();
  await expect(view.getByRole('table', { name: /Progressed planetary positions/ }).getByRole('row')).toHaveCount(11);
  await view.getByText('Search exact progressed MC dates · separate method').click();
  const timeline = page.getByRole('region', { name: 'Progressed MC exact contact timeline' });
  // Use the known-contact fixture window, not the app-clock default whose calendar position varies.
  await timeline.getByLabel('From (UTC)').fill('2025-07-01');
  await timeline.getByLabel('Until (UTC, excluded)').fill('2026-06-30');
  const firstSearch = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await timeline.getByRole('button', { name: 'Search exact dates' }).click();
  const mcp = await (await firstSearch).json();
  expect(mcp.status).toBe('supported');
  expect(mcp.branch).toBe('mcp');
  expect(mcp.body).toBe('mercury');
  expect(mcp.events.length).toBeGreaterThan(0);
  await expect(timeline.getByRole('region', { name: 'Progressed MC timeline' })).toContainText('MCp');
  const csvDownload = page.waitForEvent('download');
  await timeline.getByRole('button', { name: 'Download MC dates CSV' }).click();
  const csv = await readFile(await (await csvDownload).path(), 'utf8');
  expect(csv).toContain(`${mcp.events[0].instant_utc},mcp,mercury,square`);
  await timeline.getByRole('button', { name: /Open saved MCP Mercury/ }).click();
  await expect(timeline.getByRole('table', { name: /MCP exact dates/ }).getByRole('row')).toHaveCount(mcp.events.length + 1);
  await timeline.getByLabel('Branch').selectOption('mcr');
  const nextSearch = page.waitForResponse(reply => reply.request().method() === 'POST' &&
    new URL(reply.url()).pathname === '/api/advanced-results');
  await timeline.getByRole('button', { name: 'Search exact dates' }).click();
  const mcr = await (await nextSearch).json();
  expect(mcr.status).toBe('supported');
  expect(mcr.branch).toBe('mcr');
  expect(mcr.branch_description).not.toBe(mcp.branch_description);
  await expect(timeline.getByRole('region', { name: 'Progressed MC timeline' })).toContainText('MCr');
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  for (const size of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short-mobile', width: 390, height: 560 },
    { name: 'ultrawide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(renders, `progression-normal-${size.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
  }
});
