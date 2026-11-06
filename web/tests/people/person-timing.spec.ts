import { test, expect } from '@playwright/test';
import { mkdirSync, copyFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/remaining-usability');

test('bundled wheel fonts obey isolated CSP in page and export', async ({ page }) => {
  mkdirSync(renders, { recursive: true });
  await page.addInitScript(() => {
    (window as unknown as { katViolations: string[] }).katViolations = [];
    document.addEventListener('securitypolicyviolation', event => {
      (window as unknown as { katViolations: string[] }).katViolations.push(
        `${event.violatedDirective}: ${event.blockedURI}`);
    });
  });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByRole('tab', { name: 'Charts' }).click();
  await expect(page.locator('.natal-wheel').first()).toBeVisible();
  const observation = await page.evaluate(async () => {
    let loaded = -1;
    try { loaded = (await document.fonts.load('16px KatAstro', '☽')).length; } catch { /* capture the CSP failure */ }
    return { loaded, violations: (window as unknown as { katViolations: string[] }).katViolations };
  });
  expect(observation.loaded).toBeGreaterThan(0);
  expect(observation.violations).toEqual([]);
  const actions = page.locator('.profile-active-chart');
  for (const [label, filename] of [
    ['Download safe SVG wheel', 'font-chart.svg'],
    ['Download print-ready SVG', 'font-chart-print.svg'],
    ['Download PNG wheel', 'font-chart.png'],
  ]) {
    const download = page.waitForEvent('download');
    await actions.getByRole('button', { name: label }).click();
    copyFileSync(await (await download).path(), resolve(renders, filename));
  }
  expect(readFileSync(resolve(renders, 'font-chart.svg'), 'utf8')).toMatch(/@font-face[^<]+data:font\/woff;base64,/);
  expect(readFileSync(resolve(renders, 'font-chart-print.svg'), 'utf8')).toContain('kat-chart-provenance');
  expect(readFileSync(resolve(renders, 'font-chart.png')).subarray(0, 8)).toEqual(
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  expect(await page.evaluate(() => (window as unknown as { katViolations: string[] }).katViolations)).toEqual([]);
});

test('saved cross-technique dates sort chronologically and open their actual calculations', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('navigation', { name: 'People' })).toBeVisible();
  const session = await (await page.request.get('/api/session')).json();
  const definitions = [
    { id: 'timing-arc-producer', technique: 'true_solar_arc',
      parameters: { effective_utc: '2024-03-25T00:00:00+00:00' } },
    { id: 'timing-progression-producer', technique: 'secondary_progression',
      parameters: { effective_utc: '2024-04-05T00:00:00+00:00' } },
    { id: 'timing-sky-producer', technique: 'actual_lunations_eclipses',
      parameters: { start_utc: '2024-03-01T00:00:00+00:00',
        end_utc: '2024-06-01T00:00:00+00:00', natal_target: 'sun', aspect: 'conjunction' } },
  ];
  for (const item of definitions) {
    const reply = await page.request.post('/api/advanced-results', {
      headers: { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin },
      data: { person_id: 'transit-person', ...item },
    });
    expect(reply.status(), `${item.technique}: ${JSON.stringify(await reply.json())}`).toBe(201);
  }
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByText('Saved timing', { exact: true }).click();
  const timing = page.getByRole('region', { name: 'Where am I now' });
  await timing.getByLabel('From (UTC)').fill('2024-01-01');
  await timing.getByLabel('Explore').selectOption('year');
  await timing.getByRole('button', { name: 'Show saved timing' }).click();
  await expect(timing.locator('[data-result-id="timing-arc-producer"]')).toBeVisible();
  await expect(timing.locator('[data-result-id="timing-progression-producer"]')).toBeVisible();
  const maximum = timing.getByText('global maximum', { exact: false }).first();
  await expect(maximum).toBeVisible();
  await expect(timing.getByText('linked syzygy', { exact: false }).first()).toBeVisible();
  const dates = await timing.locator('.timing-results > li > strong').allTextContents();
  expect(dates.length).toBeGreaterThan(3);
  expect(dates).toEqual([...dates].sort((a, b) => Date.parse(a) - Date.parse(b)));
  await timing.locator('[data-result-id="timing-arc-producer"]').first()
    .getByRole('button', { name: 'Open saved result' }).click();
  await expect(timing.getByText('True forward solar arc', { exact: false }).last()).toBeVisible();
  await expect(timing.locator('.timing-opened .natal-wheel')).toBeVisible();
  for (const [button, file] of [['Download safe SVG wheel', 'corrected-arc.svg'],
    ['Download PNG wheel', 'corrected-arc.png']]) {
    const downloaded = page.waitForEvent('download');
    await timing.locator('.timing-opened').getByRole('button', { name: button }).click();
    copyFileSync(await (await downloaded).path(), resolve(renders, file));
  }
  expect(readFileSync(resolve(renders, 'corrected-arc.svg'), 'utf8')).toContain('timing-arc-producer');
  expect(readFileSync(resolve(renders, 'corrected-arc.png')).subarray(0, 8)).toEqual(
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  await timing.locator('[data-result-id="timing-progression-producer"]').first()
    .getByRole('button', { name: 'Open saved result' }).click();
  await expect(timing.getByText('Secondary progression for age', { exact: false })).toBeVisible();
  let reached!: () => void;
  let resume!: () => void;
  const intercepted = new Promise<void>(resolve => { reached = resolve; });
  const held = new Promise<void>(resolve => { resume = resolve; });
  await page.route('**/api/advanced-results/timing-arc-producer', async route => {
    reached(); await held; await route.continue();
  });
  await timing.locator('[data-result-id="timing-arc-producer"]').first()
    .getByRole('button', { name: 'Open saved result' }).click();
  await intercepted;
  await timing.locator('[data-result-id="timing-progression-producer"]').first()
    .getByRole('button', { name: 'Open saved result' }).click();
  await expect(timing.getByText('Secondary progression for age', { exact: false })).toBeVisible();
  const oldResponse = page.waitForResponse(response => response.url().endsWith('/api/advanced-results/timing-arc-producer'));
  resume(); await oldResponse;
  await expect(timing.locator('[data-result-id="timing-arc-producer"] .timing-opened')).toHaveCount(0);
  const sky = timing.locator('[data-result-id="timing-sky-producer"]').first();
  await sky.getByRole('button', { name: 'Open saved result' }).click();
  await expect(sky.getByText('Geocentric lunations and physically distinct', { exact: false })).toBeVisible();
  await expect(sky.getByRole('table', { name: /global eclipse maximum/ })).toBeVisible();
  for (const viewport of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 },
    { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    await page.screenshot({ path: resolve(renders, `corrected-${viewport.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
  }
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
});

test('opened progressed MC contact names its branch without inventing a planetary return or showing method slugs', async ({ page }) => {
  mkdirSync(renders, { recursive: true });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('navigation', { name: 'People' })).toBeVisible();
  const session = await (await page.request.get('/api/session')).json();
  const origin = new URL(page.url()).origin;
  const parameters = { branch: 'mcp', body: 'mercury', aspect: 'square',
    start_utc: '2025-07-01T00:00:00+00:00', end_utc: '2026-06-30T00:00:00+00:00' };
  const id = `final-mcp-${crypto.randomUUID()}`;
  const undatedId = `final-undated-${crypto.randomUUID()}`;
  async function save(resultId: string, interval: typeof parameters) {
    const response = await page.request.post('/api/advanced-results', {
      headers: { Origin: origin, 'X-Kat-CSRF': session.csrf },
      data: { id: resultId, person_id: 'transit-person', technique: 'progressed_mc_contacts', parameters: interval },
    });
    expect(response.status()).toBe(201);
    return response.json();
  }
  const contact = await save(id, parameters);
  expect(contact.status).toBe('supported');
  expect(contact.method_version).toBe('secondary-utc-calendar-naibod-mc-v1');
  expect(contact.events.length).toBeGreaterThan(0);
  expect(contact.branch_description).toContain('MCp progressed astronomical MC to fixed natal planet');
  const empty = await save(undatedId, { ...parameters, end_utc: '2025-07-02T00:00:00+00:00' });
  expect(empty.status).toBe('supported');
  expect(empty.events).toHaveLength(0);

  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByText('Saved timing', { exact: true }).click();
  const timing = page.getByRole('region', { name: 'Where am I now' });
  await timing.getByLabel('From (UTC)').fill('2025-07-01');
  await timing.getByLabel('Explore').selectOption('year');
  await timing.getByRole('button', { name: 'Show saved timing' }).click();
  const row = timing.locator(`[data-result-id="${id}"]`).first();
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: 'Open saved result' }).click();
  const opened = row.getByRole('region', { name: 'Opened saved calculation' });
  await expect(opened).toContainText('MCp progressed astronomical MC to fixed natal planet · Mercury square');
  await expect(opened.getByRole('table', { name: /progressed mc contacts points/ })).toBeVisible();
  await expect(opened).not.toContainText('Mercury returns to its saved natal longitude');
  await expect(opened).not.toContainText(contact.method_version);
  const undated = timing.getByText('Saved calculations without dated points', { exact: false });
  await undated.click();
  await expect(timing.locator(`[data-result-id="${undatedId}"]`)).toBeVisible();
  await expect(timing.locator(`[data-result-id="${undatedId}"]`)).not.toContainText(empty.method_version);
  // The API still serves the unmodified source/version for reproducibility and export.
  const original = await (await page.request.get(`/api/advanced-results/${id}`)).json();
  expect(original.result.method_version).toBe(contact.method_version);
  for (const viewport of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 },
    { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    await page.screenshot({ path: resolve(renders, `final-renderer-${viewport.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
  }
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
});

test('earlier natal identity is separate from source eligibility in saved timing', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByText('Saved timing', { exact: true }).click();
  const timing = page.getByRole('region', { name: 'Where am I now' });
  await timing.getByLabel('Source natal').selectOption({ label: 'Earlier natal 2' });
  await timing.getByRole('button', { name: 'Show saved timing' }).click();
  await expect(timing.getByRole('status')).toContainText('Earlier natal');
  await expect(timing.getByRole('status')).not.toContainText('Current natal');
  await timing.getByLabel('Source natal').selectOption({ label: 'Current natal' });
  await timing.getByRole('button', { name: 'Show saved timing' }).click();
  await expect(timing.getByRole('status')).toContainText('Current natal');
});

test('saved timing keeps the exact result selected for an editable draft', async ({ page }) => {
  mkdirSync(renders, { recursive: true });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('navigation', { name: 'People' })).toBeVisible();
  const session = await (await page.request.get('/api/session')).json();
  const result = await page.request.post('/api/advanced-results', {
    headers: { 'X-Kat-CSRF': session.csrf,
      Origin: new URL(page.url()).origin },
    data: { id: `timing-${crypto.randomUUID()}`, person_id: 'transit-person',
      technique: 'solar_return', parameters: { year: 2026, latitude: 55.68, longitude: 12.57 } },
  });
  expect(result.status(), JSON.stringify({ reply: await result.json(), sessionOwner: session.owner, origin: new URL(page.url()).origin })).toBe(201);
  const saved = await result.json();
  await page.getByLabel('Message Kat').fill('My existing unsent thought');
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByText('Saved timing', { exact: true }).click();
  const timing = page.getByRole('region', { name: 'Where am I now' });
  await timing.getByLabel('From (UTC)').fill('2026-01-01');
  await timing.getByLabel('Explore').selectOption('year');
  await timing.getByRole('button', { name: 'Show saved timing' }).click();
  await expect(timing).toContainText('Gaps are not a no-event finding.');
  await expect(timing).toContainText('Solar return');
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  for (const viewport of [
    { name: 'desktop', width: 1440, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'short', width: 390, height: 560 },
    { name: 'wide', width: 2560, height: 1080 },
  ]) {
    await page.setViewportSize(viewport);
    await page.screenshot({ path: resolve(renders, `timing-${viewport.name}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
  }
  const createdRow = timing.locator(`[data-result-id="${saved.id}"]`);
  await createdRow.getByRole('button', { name: 'Open saved result' }).click();
  await expect(timing.locator('.natal-wheel')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 560 });
  await page.screenshot({ path: resolve(renders, 'timing-open-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
  await createdRow.getByRole('button', { name: 'Save for later' }).first().click();
  await expect(timing).toContainText('Saved for later. A due reminder is off');
  await page.getByRole('tab', { name: 'Saved' }).click();
  await page.getByRole('button', { name: 'Saved for later' }).click();
  await expect(page.getByText('Reminder off.')).toBeVisible();
  await page.getByRole('button', { name: 'Edit note or reminder' }).click();
  const watchForm = page.getByRole('form', { name: 'Edit saved item' });
  await watchForm.getByLabel('Private note (optional)').fill('Saved synthetic date');
  await watchForm.getByLabel('Remind me in Kat when open').check();
  await watchForm.getByLabel('Local reminder time').fill('2026-10-25T02:30');
  await watchForm.getByLabel('Timezone (IANA)').fill('Europe/Copenhagen');
  await watchForm.getByRole('button', { name: 'Save item' }).click();
  await expect(watchForm.getByLabel('Repeated clock hour')).toBeVisible();
  await page.screenshot({ path: resolve(renders, 'corrected-reminder-edit-short.png'), fullPage: true });
  await expect(watchForm.getByLabel('Private note (optional)')).toHaveValue('Saved synthetic date');
  await watchForm.getByLabel('Repeated clock hour').selectOption('1');
  await watchForm.getByRole('button', { name: 'Save item' }).click();
  await expect(watchForm).toHaveCount(0);
  await expect(page.getByText('Saved synthetic date')).toBeVisible();
  await page.getByRole('button', { name: 'Edit note or reminder' }).click();
  await expect(watchForm.getByLabel('Remind me in Kat when open')).toBeChecked();
  await watchForm.getByLabel('Remind me in Kat when open').uncheck();
  await watchForm.getByRole('button', { name: 'Cancel' }).click();
  await page.getByRole('button', { name: 'Edit note or reminder' }).click();
  await expect(watchForm.getByLabel('Remind me in Kat when open')).toBeChecked();
  await watchForm.getByLabel('Private note (optional)').fill('Note-only update keeps due reminder');
  await watchForm.getByRole('button', { name: 'Save item' }).click();
  await expect(page.getByText('Note-only update keeps due reminder')).toBeVisible();
  await page.getByRole('button', { name: 'Private journal' }).click();
  await page.getByLabel('Date', { exact: true }).last().fill('2026-06-22');
  await page.getByLabel('Link a saved item (optional)').selectOption(saved.id);
  await page.getByLabel('Your reflection').fill('A deliberate synthetic life note');
  await page.getByRole('button', { name: 'Save private reflection' }).click();
  await expect(page.getByText('A deliberate synthetic life note')).toBeVisible();
  await page.getByRole('button', { name: 'Edit text' }).click();
  const journalEdit = page.getByRole('form', { name: 'Edit private reflection' });
  await journalEdit.getByLabel('Your reflection').fill('A cancelled private note');
  await journalEdit.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByText('A cancelled private note')).toHaveCount(0);
  await page.getByRole('button', { name: 'Edit text' }).click();
  await journalEdit.getByLabel('Your reflection').fill('A revised private synthetic life note');
  await page.screenshot({ path: resolve(renders, 'corrected-journal-edit-short.png'), fullPage: true });
  await journalEdit.getByRole('button', { name: 'Save edit' }).click();
  await expect(page.getByText('A revised private synthetic life note')).toBeVisible();
  await page.getByRole('tab', { name: 'Overview' }).click();
  const glossary = page.getByText('What do these chart terms mean?');
  await glossary.focus(); await page.keyboard.press('Enter');
  await expect(page.getByText('A calculated angle tied to the local meridian', { exact: false })).toBeVisible();
  expect((await (await page.request.get('/api/conversations')).json()).conversations).toHaveLength(0);
  await createdRow.getByRole('button', { name: 'Discuss this point' }).first().click();
  await expect(page.getByLabel('Message Kat')).toHaveValue('My existing unsent thought');
  await expect(page.getByText('saved result, not recalculated')).toBeVisible();
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.locator('.turn-card')).toHaveCount(1);
  const thread = (await (await page.request.get('/api/conversations')).json()).conversations[0];
  const turns = (await (await page.request.get(`/api/conversations/${thread.id}/turns`)).json()).turns;
  expect(turns[0].events[0].payload.selected_result).toEqual({ result_id: saved.id, event_index: 0 });
  expect(JSON.stringify(turns)).not.toContain('A revised private synthetic life note');
  await expect.poll(async () => {
    const turnsPage = (await (await page.request.get(`/api/conversations/${thread.id}/turns`)).json()).turns;
    return turnsPage[0].events.some((event: { kind: string; payload: { name?: string } }) =>
      event.kind === 'tool_result' && event.payload.name === 'read_selected_result');
  }).toBe(true);
});
