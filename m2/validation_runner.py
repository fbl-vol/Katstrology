"""Unittest discovery with bounded, synthetic-only timing summaries for owned runs."""

import argparse
import json
from pathlib import Path
from time import perf_counter
import unittest


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.samples = []

    def startTest(self, test):
        self.started = perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        self.samples.append((test.id(), round(perf_counter() - self.started, 3),
                             round(getattr(test, '_fixture_setup_seconds', 0), 3)))
        super().stopTest(test)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timings', required=True, type=Path)
    parser.add_argument('selectors', nargs='*')
    args = parser.parse_args()
    loader = unittest.defaultTestLoader
    suite = (loader.loadTestsFromNames(args.selectors) if args.selectors else unittest.TestSuite([
        loader.discover('m2', pattern='test_*.py'),
        unittest.TestLoader().discover('deploy', pattern='test_*.py'),
    ]))
    result = unittest.TextTestRunner(verbosity=0, resultclass=TimedResult).run(suite)
    ranked = sorted(result.samples, key=lambda sample: sample[1], reverse=True)
    setup = sorted(result.samples, key=lambda sample: sample[2], reverse=True)
    args.timings.write_text(json.dumps({
        'sample_count': len(result.samples),
        'slowest_tests': [{'id': name, 'seconds': total} for name, total, _ in ranked[:5]],
        'slowest_fixture_setup': [{'id': name, 'seconds': seconds}
                                  for name, _, seconds in setup if seconds > 0][:5],
    }, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
