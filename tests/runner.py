"""Unittest discovery with bounded, synthetic-only diagnostics for owned runs."""

import argparse
import json
from pathlib import Path
import re
from time import perf_counter
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAX_FAILURES = 20


def symbol(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]{0,239}', value) else 'unknown'


def test_name(test):
    # Never use subtest parameters, descriptions, custom id() or exception text.
    if isinstance(test, unittest.TestCase):
        cls = type(test)
        return '.'.join((symbol(cls.__module__), symbol(cls.__qualname__),
                         symbol(test._testMethodName)))
    # unittest represents class/module fixture failures without a TestCase.
    description = getattr(test, 'description', '')
    match = re.fullmatch(r'(setUpClass|tearDownClass|setUpModule|tearDownModule) '
                         r'\(([A-Za-z_][A-Za-z0-9_.]{0,239})\)', description)
    return '.'.join(reversed(match.groups())) if match else 'unknown_fixture'


def failure_detail(test, outcome, err):
    frames = []
    if err:
        traceback = err[2]
        while traceback:
            filename = Path(traceback.tb_frame.f_code.co_filename)
            try:
                relative = filename.resolve().relative_to(ROOT).as_posix()
            except ValueError:
                relative = ''
            # Only code locations, not source lines, locals, external/private paths
            # or exception messages. Keep the innermost eight source frames.
            if re.fullmatch(r'(?:m2|deploy|tests)/[A-Za-z0-9_/.-]{1,240}\.py', relative):
                frames.append({'file': relative, 'line': traceback.tb_lineno})
            traceback = traceback.tb_next
    return {'test': test_name(test), 'outcome': outcome,
            'exception_type': symbol(err[0].__name__) if err else None,
            'frames': frames[-8:]}


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, report_path=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.samples = []
        self.failure_details = []
        self.failure_total = 0
        self.last_started_test = None
        self.report_path = report_path

    def startTest(self, test):
        self.started = perf_counter()
        self.last_started_test = test_name(test)
        super().startTest(test)
        self.write_report('running')

    def stopTest(self, test):
        self.samples.append((test_name(test), round(perf_counter() - self.started, 3),
                             round(getattr(test, '_fixture_setup_seconds', 0), 3)))
        super().stopTest(test)

    def record_failure(self, test, outcome, err=None):
        self.failure_total += 1
        if len(self.failure_details) < MAX_FAILURES:
            self.failure_details.append(failure_detail(test, outcome, err))
        self.write_report('running')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record_failure(test, 'failure', err)

    def addError(self, test, err):
        super().addError(test, err)
        self.record_failure(test, 'error', err)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err:
            outcome = 'failure' if issubclass(err[0], test.failureException) else 'error'
            self.record_failure(test, outcome, err)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.record_failure(test, 'unexpected_success')

    def write_report(self, status):
        if self.report_path is None:
            return
        ranked = sorted(self.samples, key=lambda sample: sample[1], reverse=True)
        setup = sorted(self.samples, key=lambda sample: sample[2], reverse=True)
        report = {
            'status': status, 'tests_run': self.testsRun,
            'failure_count': self.failure_total,
            'failures': self.failure_details,
            'failures_omitted': self.failure_total - len(self.failure_details),
            'last_started_test': self.last_started_test,
            'sample_count': len(self.samples),
            'slowest_tests': [{'id': name, 'seconds': total} for name, total, _ in ranked[:5]],
            'slowest_fixture_setup': [{'id': name, 'seconds': seconds}
                                     for name, _, seconds in setup if seconds > 0][:5],
        }
        # An abruptly terminated child leaves the previous complete checkpoint.
        temporary = self.report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, sort_keys=True))
        temporary.replace(self.report_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timings', required=True, type=Path)
    parser.add_argument('selectors', nargs='*')
    args = parser.parse_args()
    loader = unittest.defaultTestLoader
    suite = (loader.loadTestsFromNames(args.selectors) if args.selectors else unittest.TestSuite([
        loader.discover('tests', pattern='test_*.py', top_level_dir='.'),
        unittest.TestLoader().discover('.agents/skills/tests', pattern='test_*.py'),
    ]))
    result = unittest.TextTestRunner(verbosity=0, resultclass=lambda *a, **kw:
        TimedResult(*a, report_path=args.timings, **kw)).run(suite)
    result.write_report('passed' if result.wasSuccessful() else 'failed')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
