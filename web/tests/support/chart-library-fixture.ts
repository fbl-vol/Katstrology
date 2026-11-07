import { expect, type Page } from '@playwright/test';

export async function openLibrary(page: Page, waitForResults = true) {
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-advanced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  if ((page.viewportSize()?.width || 1440) < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic transit reader' }).click();
  await page.getByRole('tab', { name: 'Charts', exact: true }).click();
  if (waitForResults) await expect(page.locator('.library-card[data-technique="natal"]')).toBeVisible();
}

export async function saveLibraryExamples(page: Page) {
  const interval = { start_utc: '2024-03-01T00:00:00+00:00', end_utc: '2024-04-01T00:00:00+00:00' };
  const place = { latitude: 51.5, longitude: -1 / 6 };
  const definitions = [
    { technique: 'solar_return', parameters: { year: 2026, ...place } },
    { technique: 'lunar_return', parameters: { ...interval, ...place } },
    { technique: 'planetary_return', parameters: { ...interval, ...place, body: 'venus' } },
    { technique: 'mc_transit', parameters: { ...interval, transit_body: 'sun', aspect: 'conjunction' } },
    { technique: 'secondary_progression', parameters: { effective_utc: '2024-03-25T00:00:00+00:00' } },
    { technique: 'progressed_mc_contacts', parameters: { ...interval, branch: 'mcp', body: 'sun', aspect: 'conjunction' } },
    { technique: 'true_solar_arc', parameters: { effective_utc: '2024-03-25T00:00:00+00:00' } },
    { technique: 'progressed_lunar_phases', parameters: interval },
    { technique: 'actual_lunations_eclipses', parameters: { ...interval, natal_target: 'sun', aspect: 'conjunction' } },
    ...['synastry_overlay', 'midpoint_composite', 'uncorrected_davison'].map(technique => ({ technique,
      parameters: { person_b_id: 'other-transit-person' } })),
  ];
  const session = await (await page.request.get('/api/session')).json();
  const headers = { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin };
  const saved: { id: string; technique: string }[] = [];
  for (const definition of definitions) {
    const id = `library-example-${crypto.randomUUID()}`;
    const reply = await page.request.post('/api/advanced-results', { headers,
      data: { id, person_id: 'transit-person', ...definition } });
    expect(reply.status(), `${definition.technique}: ${await reply.text()}`).toBe(201);
    expect((await reply.json()).status).toBe('supported');
    saved.push({ id, technique: definition.technique });
  }
  return saved;
}
