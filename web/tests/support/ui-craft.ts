import { expect, type Locator, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

/** Capture the real result, not a prototype; calculation and source assertions stay in each test. */
export async function captureResultHierarchy(page: Page, result: Locator, history: Locator, name: string) {
  await expect(result).toBeVisible();
  await expect(history).toBeVisible();
  const content = await result.boundingBox();
  const navigation = await history.boundingBox();
  expect(content && navigation && content.y + content.height <= navigation.y).toBe(true);

  const directory = resolve(import.meta.dirname, '../../../.local/ui-craft/renders');
  mkdirSync(directory, { recursive: true });
  const originalViewport = page.viewportSize();
  const originalSize = await page.evaluate(() => document.documentElement.style.fontSize);
  try {
    for (const size of [
      { name: 'desktop', width: 1440, height: 1024 }, { name: 'wide', width: 2560, height: 1080 },
      { name: 'mobile', width: 390, height: 844 }, { name: 'short-mobile', width: 390, height: 560 },
      { name: 'tablet', width: 768, height: 1024 }, { name: 'enlarged-reflow', width: 320, height: 640 },
    ]) {
      await page.setViewportSize(size);
      // Text enlargement plus narrow reflow, separate from browser zoom or wheel geometry.
      if (size.name === 'enlarged-reflow') await page.evaluate(() => { document.documentElement.style.fontSize = '125%'; });
      await result.locator('h2,h3').first().evaluate(node => node.scrollIntoView({ block: 'start' }));
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width + 1);
      await page.screenshot({ path: resolve(directory, `${name}-${size.name}.png`) });
    }
  } finally {
    await page.evaluate(value => { document.documentElement.style.fontSize = value; }, originalSize);
    if (originalViewport) await page.setViewportSize(originalViewport);
  }
}
