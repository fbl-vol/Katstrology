// Deterministically render the selected simplified kitten face for Android install assets.
// Run from the repository with node web/scripts/generate-install-icons.mjs; no network.
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from '@playwright/test';

const web = resolve(import.meta.dirname, '..');
const face = readFileSync(resolve(web, 'src/shared/assets/kat-face.svg'), 'utf8');
const output = resolve(web, 'public/icons');
mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.KAT_BROWSER_BIN || '/usr/bin/chromium-browser' });
try {
  for (const [size, maskable] of [[192, false], [512, false], [512, true]]) {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    // The maskable artwork is wholly inside the centre 80% safe circle. Padding
    // also keeps the ordinary icon readable at launcher sizes.
    const diameter = Math.round(size * (maskable ? 0.57 : 0.78));
    await page.setContent(`<style>html,body{margin:0;width:100%;height:100%;background:#f5f3ec}body{display:grid;place-items:center}svg{width:${diameter}px;height:${diameter}px}</style>${face}`);
    const pixels = await page.screenshot();
    writeFileSync(resolve(output, `kat-${size}${maskable ? '-maskable' : ''}.png`), pixels);
    await page.close();
  }
} finally {
  await browser.close();
}
