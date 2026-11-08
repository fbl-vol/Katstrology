// Native Playwright identities/outcomes only. No messages, attachments or user data.
const { createHash } = require('node:crypto');
const { writeFileSync } = require('node:fs');
const { relative } = require('node:path');
const skippedTitles = new Set(['desktop', 'mobile'].flatMap(view => [
  `long synthetic discussion compacts, refuses partial summary and keeps draft on ${view}`,
  `selected draft and consented chart file reach synthetic provider on ${view}`,
]));

module.exports = class InventoryReporter {
  onBegin(config, suite) {
    this.report = { workers: config.workers, tests: suite.allTests().map(test => ({
      id: createHash('sha256').update(test.id).digest('hex'),
      allowedSkip: relative(__dirname, test.location.file) === 'tests/provider/siwc.spec.ts'
        && skippedTitles.has(test.title),
      outcomes: [],
    })), status: 'running', errors: 0 };
    this.tests = new Map(suite.allTests().map((test, i) => [test.id, this.report.tests[i]]));
  }
  onTestEnd(test, result) { this.tests.get(test.id).outcomes.push(result.status); }
  onError() { if (this.report) this.report.errors++; }
  onEnd(result) {
    if (!this.report) throw new Error('Native test inventory absent');
    this.report.status = result.status;
    writeFileSync(process.env.KAT_BROWSER_INVENTORY_FILE, JSON.stringify(this.report));
  }
};
