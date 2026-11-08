import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const renders = resolve(import.meta.dirname, '../../../.local/existing-link-label/renders');
const viewports = [
  { name: 'desktop', width: 1440, height: 1024 }, { name: 'wide', width: 2560, height: 1080 },
  { name: 'mobile', width: 390, height: 844 }, { name: 'short-mobile', width: 390, height: 560 },
  { name: 'tablet', width: 768, height: 1024 },
];
for (const viewport of viewports) test(`existing off-page link descriptor ${viewport.name}`, async ({ page }) => {
  test.setTimeout(90_000);
  mkdirSync(renders, { recursive: true });
  await page.setViewportSize(viewport);
  await page.goto('/');
  await page.getByLabel('Username').fill(`reader-link-label-${viewport.name}`);
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.getByRole('heading', { name: 'What’s on your mind?' })).toBeVisible();
  const session = await (await page.request.get('/api/session')).json();
  const headers = { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin };
  const make = async (name: string) => {
    const response = await page.request.post('/api/people', { headers, data: { name } });
    expect(response.status()).toBe(201);
    return (await response.json()).id as string;
  };
  const change = async (id: string, value: unknown) => {
    const response = await page.request.post(`/api/people/${id}/personal-profile`, {
      headers, data: { operation_id: crypto.randomUUID(), change: value },
    });
    expect(response.ok()).toBe(true);
  };
  const duplicates: string[] = [];
  for (let index = 0; index < 54; index++) duplicates.push(await make('Synthetic duplicate'));
  // API IDs are random. Deliberately choose the last key so the real initial
  // keyset page cannot accidentally include the pre-existing selected link.
  const target = [...duplicates].sort().at(-1)!;
  const ordinal = duplicates.indexOf(target) + 1;
  await change(target, { kind: 'details', expected_version: 0,
    details: { pronouns: '', home: 'Northport', occupation: 'Teacher', about: '' } });
  const parent = await make('Synthetic linked reader');
  await change(parent, { kind: 'link', expected_version: 0, id: 'existing-link',
    other_person_id: target, label: 'Friend', dates: 'Since school' });
  const first = await (await page.request.post('/api/people/picker', {
    headers, data: { query: '', after: null },
  })).json();
  expect(first.people).toHaveLength(50);
  expect(first.total).toBe(55);
  expect(first.people.some((person: { id: string }) => person.id === target)).toBe(false);
  await page.reload();
  if (viewport.width < 700) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'People' }).getByRole('button', { name: 'Synthetic linked reader' }).click();
  await page.getByRole('button', { name: 'Edit relationship with Synthetic duplicate', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Link person', exact: true });
  const selection = dialog.getByRole('combobox', { name: 'Person', exact: true });
  const label = `Synthetic duplicate · Teacher, Northport (profile ${ordinal})`;
  await expect(dialog.getByLabel('Search owned people')).toHaveValue('');
  await expect(selection).toHaveValue(target);
  await expect(selection.locator('option:checked')).toHaveText(label);
  await expect(dialog.getByRole('button', { name: 'More people', exact: true })).toBeEnabled();
  await expect(selection.locator('option:checked')).toHaveText(label);
  expect(await dialog.innerText()).not.toContain(target);
  await page.screenshot({ path: resolve(renders, `edit-open-${viewport.name}.png`) });

  await dialog.getByLabel('Their relationship').fill('Close friend');
  await dialog.getByLabel('Dates (optional)').fill('Since university');
  let fail = true;
  await page.route('**/api/people/picker', async route => {
    if (fail) { fail = false; await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }); }
    else await route.continue();
  });
  await dialog.getByLabel('Search owned people').fill('no match');
  await expect(dialog.getByRole('alert')).toContainText('Your selection and relationship draft are retained');
  await expect(selection).toHaveValue(target);
  await expect(selection.locator('option:checked')).toHaveText(label);
  await expect(dialog.getByLabel('Their relationship')).toHaveValue('Close friend');
  await expect(dialog.getByLabel('Dates (optional)')).toHaveValue('Since university');
  expect(await dialog.innerText()).not.toContain(target);
  await page.screenshot({ path: resolve(renders, `edit-failure-${viewport.name}.png`) });
  await dialog.getByRole('button', { name: 'Retry people search' }).click();
  await expect(dialog.getByText('Finding owned people…')).not.toBeVisible();
  await expect(selection.locator('option:checked')).toHaveText(label);
  await dialog.getByRole('button', { name: 'Save', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(renders, `edit-save-${viewport.name}.png`) });
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  const saved = await (await page.request.get(`/api/people/${parent}/personal-profile`)).json();
  expect(saved.links).toHaveLength(1);
  expect(saved.links[0]).toMatchObject({ other_person_id: target, picker_label: label,
    label: 'Close friend', dates: 'Since university', version: 2 });
  await page.getByRole('button', { name: 'Edit relationship with Synthetic duplicate', exact: true }).click();
  await expect(selection.locator('option:checked')).toHaveText(label);
  await dialog.getByRole('button', { name: 'Unlink', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect((await (await page.request.get(`/api/people/${parent}/personal-profile`)).json()).links).toEqual([]);
  expect((await page.request.get(`/api/people/${target}`)).status()).toBe(200);
});
