// Bounded checkpoints survive a runner interruption before native JSON onEnd.
// Never retain titles, test IDs, errors, stdout, attachments or arbitrary paths.
const { writeFileSync, renameSync } = require('node:fs');
const { relative, resolve } = require('node:path');
const { freemem, totalmem, loadavg } = require('node:os');

function location(test) {
  const value = test.location;
  const file = relative(__dirname, resolve(value.file));
  return /^tests\/[A-Za-z0-9_/.-]{1,240}\.ts$/.test(file) && !file.split('/').includes('..')
    ? { file, line: value.line } : null;
}

module.exports = class ValidationReporter {
  constructor() {
    this.path = process.env.KAT_BROWSER_PROGRESS_FILE;
    this.active = new Map();
    this.report = { status: 'initializing', total: 0, started: 0, finished: 0,
      global_errors: 0, outcomes: { passed: 0, failed: 0, timedOut: 0, skipped: 0, interrupted: 0 } };
    this.save();
  }
  save() {
    if (!this.path) return;
    const snapshot = { ...this.report, active: [...this.active.values()].slice(0, 8),
      active_omitted: Math.max(0, this.active.size - 8),
      resources: { node_rss: process.memoryUsage().rss, free_memory: freemem(),
        total_memory: totalmem(), load1: loadavg()[0] } };
    writeFileSync(this.path + '.tmp', JSON.stringify(snapshot));
    renameSync(this.path + '.tmp', this.path);
  }
  onBegin(_config, suite) {
    this.report.status = 'running';
    this.report.total = suite.allTests().length;
    this.save();
  }
  onTestBegin(test) {
    const point = location(test);
    this.active.set(test.id, point);
    this.report.started++;
    this.report.last_started_test = point;
    this.save();
  }
  onTestEnd(test, result) {
    this.active.delete(test.id);
    this.report.finished++;
    this.report.last_finished_test = location(test);
    this.report.outcomes[result.status]++;
    this.save();
  }
  onError() {
    this.report.global_errors++;
    this.save();
  }
  onEnd(result) {
    this.report.status = result.status;
    this.save();
  }
};
