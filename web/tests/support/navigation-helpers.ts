import { expect, type Page } from '@playwright/test';

/** The sole supported route to the optional manual sky/transit view. */
export async function openManualTransits(page: Page) {
  await page.getByRole('complementary', { name: 'Workspace navigation' })
    .getByRole('button', { name: '＋ Create chart' }).click();
  const hub = page.getByRole('region', { name: 'Create chart' });
  await hub.getByRole('button', { name: /^Transits/ }).click();
  await expect(page.getByRole('region', { name: 'Sky at a date' })).toBeVisible();
}

export async function leaveManualTransits(page: Page) {
  await page.getByRole('button', { name: 'Back to chart choices' }).click();
  await page.getByRole('region', { name: 'Create chart' })
    .getByRole('button', { name: 'Return to workspace' }).click();
}
