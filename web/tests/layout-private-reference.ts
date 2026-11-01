// Only imported for KAT_LAYOUT_PRIVATE_REFERENCE=1; public validation never reads these inputs.
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Page } from '@playwright/test';
import { artifactDir, root } from './layout-artifacts';

export const referenceFile = resolve(root, 'mockups/theme-study/aubergine.html');
const referenceSha256 = 'b9b2d6abff219ff5443db05cda551e03dde00f150d73cb42bc65410d506526e3';
const baseline = '54b2db4003b93f633ab738c225f127347cd3f696';
const digest = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');
let savedBaselineCss: string | undefined;

export function verifyPrivateReference() {
  if (!existsSync(referenceFile)) throw new Error('Private layout comparison unavailable: approved mockup is absent. Public actual-app checks run without it.');
  if (digest(readFileSync(referenceFile)) !== referenceSha256) throw new Error('Approved private layout reference changed; comparison cannot use a new baseline silently');
  for (const path of ['web/src/style.css', 'web/src/themes.css']) {
    try { execFileSync('git', ['cat-file', '-e', `${baseline}:${path}`], { cwd: root, stdio: 'ignore' }); }
    catch { throw new Error('Private layout comparison unavailable: historical baseline CSS is absent. Public actual-app checks run without it.'); }
  }
}

function baselineCss() {
  return savedBaselineCss ??= ['web/src/style.css', 'web/src/themes.css'].map(path =>
    execFileSync('git', ['show', `${baseline}:${path}`], { cwd: root, encoding: 'utf8' })).join('\n');
}

export async function withBaselineCss<T>(page: Page, capture: () => Promise<T>): Promise<T> {
  // The application CSP disallows inline styles. Serve the historical stylesheet on this synthetic page only.
  const href = new URL('/synthetic-layout-baseline.css', page.url()).href;
  await page.route(href, route => route.fulfill({ status: 200, contentType: 'text/css', body: baselineCss() }));
  try {
    await page.evaluate(href => new Promise<void>((resolve, reject) => {
      for (const link of document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')) link.disabled = true;
      const link = document.createElement('link'); link.id = 'synthetic-layout-baseline';
      link.rel = 'stylesheet'; link.href = href; link.onload = () => resolve(); link.onerror = () => reject(new Error('Baseline CSS failed'));
      document.head.append(link);
    }), href);
    return await capture();
  } finally {
    await page.evaluate(() => {
      document.querySelector('#synthetic-layout-baseline')?.remove();
      for (const link of document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')) link.disabled = false;
    });
    await page.waitForFunction(() => [...document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')]
      .every(link => !link.disabled && !!link.sheet));
    await page.unroute(href);
  }
}

async function compose(page: Page, first: Buffer, second: Buffer, width: number, height: number, stem: string) {
  const images = await page.evaluate(async ({ first, second, width, height }) => {
    const load = (base64: string) => new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image(); image.onload = () => resolve(image); image.onerror = reject;
      image.src = `data:image/png;base64,${base64}`;
    });
    const [left, right] = await Promise.all([load(first), load(second)]);
    const canvas = document.createElement('canvas');
    canvas.width = width * 2; canvas.height = height;
    let ctx = canvas.getContext('2d')!;
    ctx.drawImage(left, 0, 0); ctx.drawImage(right, width, 0);
    const sideBySide = canvas.toDataURL('image/png');
    canvas.width = width; ctx = canvas.getContext('2d')!;
    ctx.drawImage(left, 0, 0); ctx.globalAlpha = .5; ctx.drawImage(right, 0, 0); ctx.globalAlpha = 1;
    const overlay = canvas.toDataURL('image/png');
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(left, 0, 0);
    const a = ctx.getImageData(0, 0, width, height);
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(right, 0, 0);
    const b = ctx.getImageData(0, 0, width, height);
    for (let i = 0; i < a.data.length; i += 4) {
      for (let channel = 0; channel < 3; channel++) a.data[i + channel] = Math.min(255, Math.abs(a.data[i + channel] - b.data[i + channel]) * 3);
      a.data[i + 3] = 255;
    }
    ctx.putImageData(a, 0, 0);
    return { sideBySide, overlay, diff: canvas.toDataURL('image/png') };
  }, { first: first.toString('base64'), second: second.toString('base64'), width, height });
  for (const [kind, data] of Object.entries(images)) writeFileSync(resolve(artifactDir, `${stem}-${kind}.png`),
    Buffer.from(data.split(',')[1], 'base64'));
}

export async function captureBeforeAfter(page: Page, scene: string, width: number, height: number) {
  const stem = `${scene}-${width}x${height}`;
  await compose(page, readFileSync(resolve(artifactDir, `before-${stem}-actual.png`)),
    readFileSync(resolve(artifactDir, `${stem}-actual.png`)), width, height, `before-after-${stem}`);
}

export async function compareReference(app: Page, reference: Page, scene: string, width: number, height: number) {
  const bar = width <= 760 ? 44 : 48;
  await reference.setViewportSize({ width, height: height + bar });
  const refBox = await reference.evaluate(() => {
    const bar = document.querySelector('.study-bar')!.getBoundingClientRect().height;
    const grid = document.querySelector('.reading-grid')!.getBoundingClientRect();
    const composer = document.querySelector('.composer')!.getBoundingClientRect();
    const chart = document.querySelector('.chart-card')!.getBoundingClientRect();
    return { bar, grid: { x: grid.x, width: grid.width }, composer: { x: composer.x, width: composer.width },
      chart: { x: chart.x, width: chart.width } };
  });
  if (Math.abs(refBox.bar - bar) > 1) throw new Error('Reference study-bar height changed');
  const stem = `${scene}-${width}x${height}`;
  const actual = readFileSync(resolve(artifactDir, `${stem}-actual.png`));
  const expected = await reference.screenshot({ clip: { x: 0, y: bar, width, height }, animations: 'disabled' });
  writeFileSync(resolve(artifactDir, `${stem}-reference.png`), expected);
  await compose(app, actual, expected, width, height, stem);
  const manifestPath = resolve(artifactDir, `${stem}.json`);
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  writeFileSync(manifestPath, JSON.stringify({ ...manifest,
    privateComparison: { status: 'captured', reference: 'mockups/theme-study/aubergine.html', referenceSha256,
      studyBarRemoved: bar, referenceImageSha256: digest(expected), referenceLayout: refBox,
      baselineCss: scene.startsWith('before-') ? { source: baseline, sha256: digest(Buffer.from(baselineCss())),
        method: 'Only CSS was swapped on the synthetic page, not a historical build.' } : null,
      note: 'Structural anchors only; fictional populated content makes pixel diff diagnostic, not an acceptance threshold.' },
  }, null, 2));
  return refBox;
}
