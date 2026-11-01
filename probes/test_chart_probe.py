import copy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest

from chart_probe import compare, difference_degrees


ROOT = Path(__file__).resolve().parents[1]


def chart_reference_path(root, environment):
    supplied = environment.get('KAT_CHART_REFERENCE')
    path = Path(supplied) if supplied is not None else root / '.local/chart-reference.json'
    if not path.is_file():
        if supplied is not None:
            raise FileNotFoundError('Configured private chart reference is missing')
        raise unittest.SkipTest('Optional private chart oracle is not supplied')
    return path


class ChartProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = chart_reference_path(ROOT, os.environ)
        cls.reference = json.loads(path.read_text())
        cls.ephemeris = ROOT / '.local/ephe'

    def test_supplied_image_and_utc_reference(self):
        result = compare(self.reference, self.ephemeris)
        self.assertEqual(len(result['comparisons']), 18)
        self.assertTrue(all(row['within_tolerance'] for row in result['comparisons']))
        self.assertLess(abs(result['sidereal_delta_seconds']), 1)

    def test_wrong_node_reference_is_detected(self):
        reference = copy.deepcopy(self.reference)
        reference['body_reference_dms']['True Node'][0] += 30
        result = compare(reference, self.ephemeris)
        node = next(row for row in result['comparisons'] if row['name'] == 'True Node')
        self.assertFalse(node['within_tolerance'])

    def test_wrong_utc_is_not_silently_used(self):
        shifted_utc = datetime.fromisoformat(self.reference['expected_utc']) + timedelta(hours=1)
        reference = dict(self.reference, expected_utc=shifted_utc.isoformat())
        with self.assertRaisesRegex(ValueError, 'Time-zone conversion'):
            compare(reference, self.ephemeris)

    def test_missing_ephemeris_does_not_silently_use_moshier(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, 'fallback'):
                compare(self.reference, Path(directory))


class GeometryTests(unittest.TestCase):
    def test_wraparound_difference_is_short_arc(self):
        self.assertAlmostEqual(difference_degrees(0.1, 359.9), 0.2)

    def test_missing_private_oracle_skips_but_bad_explicit_path_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(unittest.SkipTest, 'Optional private chart'):
                chart_reference_path(root, {})
            with self.assertRaisesRegex(FileNotFoundError, 'Configured private chart'):
                chart_reference_path(root, {'KAT_CHART_REFERENCE': str(root / 'missing.json')})


if __name__ == '__main__':
    unittest.main()
