import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const port = Number(process.env.KAT_BROWSER_TEST_PORT || '8765');
const syntheticSiwc = process.env.KAT_BROWSER_SIWC === '1';
const fakePlan = process.env.KAT_BROWSER_FAKE_PLAN === '1';
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid isolated test port');
export default defineConfig({
  testDir: './tests',
  testMatch: process.env.KAT_BROWSER_CLOCK_CHART === '1' ? '**/clock-chart.spec.ts' :
    syntheticSiwc ? '**/siwc.spec.ts' :
    '**/{chart-library-fixes,chart-library,exploration,appearance,shell,conversation-discovery,conversation-menu,birthplace-recovery,natal,one-step,natal-wheel,transit-view,composer-notation,profile,chart-hub,chat-scroll,context-chart,context-archive,layout-visual,thinking,conversation-browsing,insights,theme-contract,single-page-scroll,complete-reply,new-chat-declutter,diagnostic-cleanup,brand-home,sidebar-navigation,advanced-returns,manual-return-intent,chiron,advanced-overlays,advanced-mc-transits,advanced-progressions,advanced-relationships,advanced-solar-arc,advanced-progressed-phases,advanced-lunations,advanced-planetary-returns,instant-send,retained-chat,source-notice,personal-context,existing-link-label,person-timing,person-record-lifetime,person-redesign,person-review-fixes,manual-result-lifecycle,production-settings,settings-quiet-rows,lilith,transit-motion,pwa}.spec.ts',
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    ...devices['Desktop Chrome'],
    launchOptions: {
      // Use Playwright's installed browser on both local and hosted runners.
      executablePath: process.env.KAT_BROWSER_BIN || undefined,
      args: syntheticSiwc || fakePlan ? ['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE 127.0.0.2'] : [],
    },
  },
  webServer: {
    command: '.venv-swiss/bin/python -m web.browser_fixture',
    cwd: root,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: false,
    timeout: 40_000,
  },
});
