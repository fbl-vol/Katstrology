import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/context-hierarchy-a1/renders');
for (const viewport of [
  { name: 'desktop', width: 1440, height: 1024 }, { name: 'mobile', width: 390, height: 844 },
  { name: 'short-dark', width: 390, height: 560 }, { name: 'reflow', width: 320, height: 560 },
]) test(`saved self canonical label survives reopen reload and recovery ${viewport.name}`, async ({ page }) => {
  await page.setViewportSize(viewport);
  if (viewport.name === 'short-dark') await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'midnight-pine'));
  await page.goto('/');
  await page.getByLabel('Username').fill(`reader-hierarchy-${viewport.name}`);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  const session = await (await page.request.get('/api/session')).json();
  const headers = { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin };
  const ids: string[] = [];
  for (const occupation of ['Teacher', 'Artist']) {
    const response = await page.request.post('/api/people', { headers, data: { name: 'Casey saved-self' } });
    expect(response.status()).toBe(201);
    const id = (await response.json()).id;
    ids.push(id);
    expect((await page.request.post(`/api/people/${id}/personal-profile`, { headers, data: {
      operation_id: crypto.randomUUID(), change: { kind: 'details', expected_version: 0,
        details: { pronouns: '', home: '', occupation, about: '' } },
    } })).ok()).toBe(true);
  }
  const authority = async () => (await (await page.request.get('/api/personal-context-self')).json());
  const consentBefore = await (await page.request.get('/api/personal-context-preference')).json();
  expect(consentBefore.enabled).toBe(false);
  const self = page.getByRole('region', { name: 'Who is me?' });
  const saved = self.locator('p').filter({ hasText: 'Saved association:' });
  const openPanel = () => page.getByRole('button', { name: /Personal context Choose whether/ }).click();
  async function openSettings() {
    if (viewport.name === 'reflow') await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
    if (viewport.width < 701) await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await openPanel();
  }
  async function capture(state: string) {
    await saved.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width + 1);
    expect(await page.locator('dialog[open]').evaluateAll(nodes => nodes.every(node => node.scrollWidth <= node.clientWidth + 1))).toBe(true);
    mkdirSync(renders, { recursive: true });
    await page.screenshot({ path: resolve(renders, `${state}-${viewport.name}.png`) });
  }
  await openSettings();
  await self.getByRole('button', { name: 'Choose who is me' }).click();
  await self.getByLabel('Search owned people').fill('Casey saved-self');
  const picker = self.getByRole('combobox', { name: 'Person', exact: true });
  const teacher = 'Casey saved-self · Teacher (profile 1)';
  const artist = 'Casey saved-self · Artist (profile 2)';
  await expect(picker.locator(`option[value="${ids[0]}"]`)).toHaveText(teacher);
  await expect(picker.locator(`option[value="${ids[1]}"]`)).toHaveText(artist);
  await picker.selectOption(ids[0]);
  await self.getByRole('button', { name: 'Use this person as me' }).click();
  await expect(saved).toHaveText(`Saved association: ${teacher}`);
  const initial = await authority();
  expect(initial).toEqual({ person_id: ids[0], version: 1 });
  await capture('initial');

  await page.getByRole('button', { name: 'Close settings panel' }).click();
  await openPanel();
  await expect(self.getByRole('button', { name: 'Change who is me' })).toBeEnabled();
  await capture('reopened'); // Preserve the actual faulty frame if the next assertion fails.
  await expect(saved).toHaveText(`Saved association: ${teacher}`);
  expect(await authority()).toEqual(initial);
  await page.reload();
  await openSettings();
  await expect(saved).toHaveText(`Saved association: ${teacher}`);
  expect(await authority()).toEqual(initial);
  await capture('reloaded');

  // A failed label read must not offer a new write; recovery reuses saved authority.
  await page.getByRole('button', { name: 'Close settings panel' }).click();
  await page.route(`**/api/people/${ids[0]}`, route => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  await openPanel();
  await expect(self.getByRole('alert')).toContainText('could not be checked');
  await expect(self.getByRole('button', { name: 'Choose who is me' })).toHaveCount(0);
  expect(await authority()).toEqual(initial);
  await page.unroute(`**/api/people/${ids[0]}`);
  await self.getByRole('button', { name: 'Refresh association' }).click();
  await expect(saved).toHaveText(`Saved association: ${teacher}`);
  await capture('read-recovered');

  // Simulate a committed change whose acknowledgement cannot be trusted.
  await self.getByRole('button', { name: 'Change who is me' }).click();
  await picker.selectOption(ids[1]);
  await page.route('**/api/personal-context-self', async route => {
    if (route.request().method() === 'POST') {
      expect((await route.fetch()).ok()).toBe(true);
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
    } else await route.continue();
  });
  await self.getByRole('button', { name: 'Use this person as me' }).click();
  await expect(self.getByRole('alert')).toContainText('change was not confirmed');
  await expect(self.getByRole('button', { name: 'Use this person as me' })).toBeDisabled();
  await page.unroute('**/api/personal-context-self');
  await self.getByRole('button', { name: 'Refresh association' }).click();
  await expect(saved).toHaveText(`Saved association: ${artist}`);
  expect(await authority()).toEqual({ person_id: ids[1], version: 2 });
  await capture('change-recovered');

  // A legacy/missing label remains safely identifiable by name plus opaque ID.
  await page.getByRole('button', { name: 'Close settings panel' }).click();
  await page.route(`**/api/people/${ids[1]}`, async route => {
    const response = await route.fetch();
    const body = await response.json();
    delete body.picker_label;
    await route.fulfill({ response, json: body });
  });
  await openPanel();
  await expect(saved).toHaveText(`Saved association: Casey saved-self · ${ids[1]}`);
  await capture('fallback');
  await page.unroute(`**/api/people/${ids[1]}`);
  await self.getByRole('button', { name: 'Clear self association' }).click();
  await expect(self.getByText('No self association saved.')).toBeVisible();
  expect(await authority()).toEqual({ person_id: null, version: 3 });
  expect(await (await page.request.get('/api/personal-context-preference')).json()).toEqual(consentBefore);
});
