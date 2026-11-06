import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { test } from 'node:test';

function launchOptions(environment = {}) {
  // Load the actual config in a fresh non-hosted process. No fixture or browser
  // is started, and no system executable is supplied or required.
  const output = execFileSync(process.execPath, ['--experimental-strip-types',
    '--input-type=module', '-e',
    "import('./playwright.config.ts').then(({default:c}) => console.log(JSON.stringify(c.use.launchOptions)))"],
  { cwd: new URL('../', import.meta.url), env: environment, encoding: 'utf8' });
  return JSON.parse(output);
}

test('local and hosted defaults delegate browser selection to Playwright', () => {
  assert.equal(launchOptions().executablePath, undefined);
  assert.equal(launchOptions({ GITHUB_ACTIONS: 'true', RUNNER_ENVIRONMENT: 'github-hosted' }).executablePath, undefined);
});

test('explicit executable does not change synthetic external-host denial', () => {
  const options = launchOptions({ KAT_BROWSER_BIN: '/synthetic/explicit-browser', KAT_BROWSER_FAKE_PLAN: '1' });
  assert.equal(options.executablePath, '/synthetic/explicit-browser');
  assert.deepEqual(options.args, ['--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE 127.0.0.2']);
});
