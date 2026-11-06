import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Page } from '@playwright/test';

export const root = resolve(import.meta.dirname, '../../..');
const digest = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');
export const source = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
const uiSourceSha256 = digest(Buffer.concat(['web/src/shared/style.css', 'web/src/main.tsx', 'web/src/features/conversation/context-chart.tsx',
  'web/src/features/conversation/turns.tsx'].map(path => readFileSync(resolve(root, path)))));
const fixtureSha256 = digest(readFileSync(resolve(root, 'web/browser_fixture.py')));
export const artifactDir = resolve(root, '.local/layout-visual',
  `${source.slice(0, 8)}-${uiSourceSha256.slice(0, 10)}-${fixtureSha256.slice(0, 8)}`);

export type Box = { x: number; y: number; width: number; height: number; right: number; bottom: number };
export type Layout = { main: Box; grid: Box; composer: Box; chart: Box | null; chartAction: Box | null;
  chartDetails: Box | null; messages: Box | null;
  columns: string; pageWidth: number; pageHeight: number; scrollY: number };
export async function layoutOf(page: Page): Promise<Layout> {
  return page.evaluate(() => {
    const box = (selector: string) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const { x, y, width, height, right, bottom } = node.getBoundingClientRect();
      return { x, y, width, height, right, bottom };
    };
    const grid = document.querySelector('.chat-reading-grid');
    return { main: box('.main')!, grid: box('.chat-reading-grid')!, composer: box('.composer-wrap')!,
      chart: box('.context-chart'), chartAction: box('.context-chart-shortcut') || box('.context-chart .context-person>button'),
      chartDetails: box('.context-chart>details[open] .context-chart-info>summary'), messages: box('.messages'),
      columns: grid ? getComputedStyle(grid).gridTemplateColumns : '',
      pageWidth: document.documentElement.scrollWidth,
      pageHeight: document.documentElement.scrollHeight, scrollY: window.scrollY };
  });
}

export async function captureActual(page: Page, scene: string, width: number, height: number, fixture: string) {
  mkdirSync(artifactDir, { recursive: true });
  await page.setViewportSize({ width, height });
  await page.evaluate(() => window.scrollTo(0, 0));
  const layout = await layoutOf(page);
  const actual = await page.screenshot({ animations: 'disabled' });
  const stem = `${scene}-${width}x${height}`;
  writeFileSync(resolve(artifactDir, `${stem}-actual.png`), actual);
  const build = process.env.KAT_BROWSER_DIST;
  writeFileSync(resolve(artifactDir, `${stem}.json`), JSON.stringify({
    scene, viewport: { width, height }, fixture, fixtureSha256, source, uiSourceSha256,
    buildHtmlSha256: build ? digest(readFileSync(resolve(build, 'index.html'))) : null,
    actualSha256: digest(actual), layout,
    privateComparison: { status: 'not_requested', referenceAvailability: 'not_checked' },
  }, null, 2));
  return layout;
}
