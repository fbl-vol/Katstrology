import { test, expect } from '@playwright/test';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '../../..');
const digest = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');
const source = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
const uiSourceSha256 = digest(Buffer.concat(['web/src/features/conversation/thinking.tsx', 'web/src/features/conversation/thinking.css',
  'web/src/features/conversation/turns.tsx', 'web/src/shared/style.css', 'web/src/shared/themes.css']
  .map(path => readFileSync(resolve(root, path)))));
const fixtureSha256 = digest(readFileSync(resolve(root, 'web/browser_fixture.py')));
const renders = resolve(root, '.local/thinking', `${source.slice(0, 8)}-${uiSourceSha256.slice(0, 10)}-${fixtureSha256.slice(0, 8)}`);
test.beforeAll(() => mkdirSync(renders, { recursive: true }));
function recordVisualEvidence() {
  const build = process.env.KAT_BROWSER_DIST;
  const screenshots = Object.fromEntries(readdirSync(renders).filter(name =>
    name.startsWith('normal-') && name.endsWith('.png'))
    .map(name => [name, digest(readFileSync(resolve(renders, name)))]));
  writeFileSync(resolve(renders, 'normal.json'), JSON.stringify({
    source, uiSourceSha256, fixtureSha256,
    privateReference: { status: 'not_requested', availability: 'not_checked' },
    buildHtmlSha256: build ? digest(readFileSync(resolve(build, 'index.html'))) : null,
    screenshots,
  }, null, 2));
}

test('normal chat thinking indicator chooses three artworks once per acknowledged wait and yields to first words', async ({ page, context }) => {
  test.setTimeout(120000);
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'aubergine'));
  const origin = new URL(test.info().project.use.baseURL!).origin;
  let heldStream: Promise<void> | null = null;
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (/\/api\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname) && heldStream) await heldStream;
    await route.continue();
  });
  await page.goto('/');
  await page.getByLabel('Username').fill('reader-thinking-normal');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  await expect(page.locator('.thinking-wait')).toHaveCount(0);

  for (const [index, expected] of ['lunar-talisman', 'celestial-sigil', 'moonlit-cauldron'].entries()) {
    const choice = (index + .2) / 3;
    await page.evaluate(value => { Math.random = () => value; }, choice);
    let releaseStream!: () => void;
    heldStream = new Promise<void>(resolve => { releaseStream = resolve; });
    try {
      await page.getByLabel('Message Kat').fill(`Synthetic wait ${index + 1}. Reply in one sentence.`);
      await page.getByRole('button', { name: 'Send message' }).click();
      const status = page.getByRole('status', { name: 'Thinking' });
      await expect(status).toBeVisible();
      await expect(status).toHaveAttribute('data-artwork', expected);
      await expect(status.locator('svg[aria-hidden="true"]')).toHaveCount(1);
      await expect(status.locator('.thinking-label')).toHaveAttribute('aria-hidden', 'true');
      await expect(status.locator('.thinking-label')).toHaveText('Thinking');
      await expect(status).toHaveCount(1);
      if (index === 0) {
        const fade = await status.locator('.thinking-label').evaluate(element => {
          const animation = element.getAnimations()[0];
          animation.pause(); animation.currentTime = 0;
          const start = { opacity: Number(getComputedStyle(element).opacity), width: element.getBoundingClientRect().width };
          animation.currentTime = 1800;
          const middle = { opacity: Number(getComputedStyle(element).opacity), width: element.getBoundingClientRect().width };
          animation.play();
          return { start, middle };
        });
        expect(fade.start.opacity).toBeGreaterThan(.99);
        expect(fade.middle.opacity).toBeLessThan(.8);
        expect(fade.middle.width).toBe(fade.start.width);
      }
      await page.screenshot({ path: resolve(renders, `normal-${expected}-aubergine-desktop.png`) });

      await page.setViewportSize({ width: 390, height: 844 });
      await page.evaluate(() => {
        document.documentElement.dataset.theme = 'rosewood';
        window.scrollTo(0, document.documentElement.scrollHeight);
      });
      const placement = await status.evaluate(element => ({
        art: element.getBoundingClientRect(),
        dock: document.querySelector('.composer-wrap')!.getBoundingClientRect(),
      }));
      expect(placement.art.y).toBeGreaterThanOrEqual(66);
      expect(placement.art.bottom).toBeLessThanOrEqual(placement.dock.y + 1);
      await page.screenshot({ path: resolve(renders, `normal-${expected}-rosewood-mobile.png`) });
      await expect(status).toHaveAttribute('data-artwork', expected);
      const motion = await status.evaluate(element => ({
        label: getComputedStyle(element.querySelector('.thinking-label')!).animationName,
        art: element.querySelector('svg')!.getAnimations({ subtree: true }).filter(item => item.playState === 'running').length,
      }));
      expect(motion.label).toBe('thinking-label-fade');
      expect(motion.art).toBeGreaterThan(0);
      const midpoint = await status.locator('.thinking-label').evaluate(element => {
        const animation = element.getAnimations()[0];
        animation.pause(); animation.currentTime = 1800;
        const opacity = Number(getComputedStyle(element).opacity);
        animation.play();
        return opacity;
      });
      expect(midpoint).toBeGreaterThanOrEqual(.88); // Rosewood's faded label still has readable contrast.
    } finally {
      releaseStream();
      heldStream = null;
    }
    await expect(page.locator('.turn-card').last()).toHaveAttribute('data-kat-status', 'complete', { timeout: 30000 });
    await expect(page.locator('.thinking-wait')).toHaveCount(0);
    await expect(page.locator('.assistant-answer').last()).toContainText('Synthetic provider captured text only');
    await page.setViewportSize({ width: 1440, height: 1024 });
    await page.evaluate(() => { document.documentElement.dataset.theme = 'aubergine'; });
  }
  recordVisualEvidence();
});

test('normal thinking indicator keeps reduced motion and survives a settings round trip', async ({ page, context }) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem('kat.appearance.theme', 'rosewood'));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const origin = new URL(test.info().project.use.baseURL!).origin;
  let heldStream: Promise<void> | null = null;
  let heldArchiveReads = 0;
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['127.0.0.1', '127.0.0.2'].includes(url.hostname)) return route.abort();
    // Returning from settings also reads the archive. Hold both delivery paths
    // while checking pending artwork, not just the EventSource transport.
    if (route.request().method() === 'GET' && /\/api\/conversations\/[^/]+\/turns(?:\/.*)?$/.test(url.pathname) && heldStream) {
      if (/\/turns$/.test(url.pathname)) heldArchiveReads++;
      await heldStream;
    }
    await route.continue();
  });
  await page.goto(origin);
  await page.getByLabel('Username').fill('reader-thinking-reduced');
  await page.getByLabel('Password').fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Open workspace' }).click();
  let releaseStream!: () => void;
  heldStream = new Promise<void>(resolve => { releaseStream = resolve; });
  try {
    await page.evaluate(() => { Math.random = () => .51; });
    await page.getByLabel('Message Kat').fill('Synthetic reduced-motion wait. Reply in one sentence.');
    await page.getByRole('button', { name: 'Send message' }).click();
    const status = page.getByRole('status', { name: 'Thinking' });
    await expect(status).toHaveAttribute('data-artwork', 'celestial-sigil');
    await expect(status).toBeVisible();
    await status.scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(renders, 'normal-reduced-rosewood-mobile.png') });
    const reduced = await status.evaluate(element => ({
      opacity: getComputedStyle(element.querySelector('.thinking-label')!).opacity,
      animations: element.getAnimations({ subtree: true }).filter(item => item.playState === 'running').length,
      thread: getComputedStyle(element.querySelector('.thinking-thread')!).strokeDashoffset,
    }));
    expect(reduced).toEqual({ opacity: '1', animations: 0, thread: '0px' });

    await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('button', { name: 'Settings' }).click();
    await expect(status).toHaveCount(0); // Unmounted artwork has no hidden animation or timer.
    await page.evaluate(() => { Math.random = () => .99; });
    await page.getByRole('button', { name: 'Back to workspace' }).click();
    await expect.poll(() => heldArchiveReads).toBeGreaterThan(0);
    await expect(status).toHaveAttribute('data-artwork', 'celestial-sigil');
    await expect(status).toBeVisible();
  } finally {
    releaseStream();
    heldStream = null;
  }
  await expect(page.locator('.turn-card')).toHaveAttribute('data-kat-status', 'complete', { timeout: 30000 });
  await expect(page.locator('.thinking-wait')).toHaveCount(0);
  await expect(page.locator('.assistant-answer')).toContainText('Synthetic provider captured text only');
  recordVisualEvidence();
});
