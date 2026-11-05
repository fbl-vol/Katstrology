"""Regression contracts for shared calculation primitives and chart qualification."""
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from m2.calculation.chart_source import NatalChartSource
from m2.calculation.ephemeris import position_at
from m2.calculation.time import julian_ut, instant_from_julian_ut, signed_angle
from m2.transits import _angle, _position_at


class SharedCalculationTests(TestCase):
    def test_legacy_consumers_use_the_same_real_sky_and_angle_contract(self):
        self.assertIs(_position_at, position_at)
        self.assertIs(_angle, signed_angle)
        instant = datetime(2024, 3, 20, 4, 6, 12, tzinfo=timezone.utc)
        self.assertLess(abs(instant_from_julian_ut(julian_ut(instant)) - instant),
                        timedelta(milliseconds=2))
        with self.assertRaisesRegex(ValueError, 'Timezone-aware'):
            julian_ut(instant.replace(tzinfo=None))

    def test_chart_source_checks_owner_first_and_rejects_engine_or_data_drift(self):
        chart = {'source_status': 'current', 'engine_version': 'wrong',
                 'result': {'natal': {'status': 'complete', 'ephemeris_sha256': {'file': 'hash'}},
                            'profile': {'settings': {'include_chiron': True}}}}
        session, chart_id = object(), 'selected-chart'
        with patch('m2.calculation.chart_source.Charts') as charts, \
                patch('m2.calculation.chart_source.ephemeris', return_value={'file': 'hash'}) as ephe:
            charts.return_value.get_chart.return_value = chart
            source = NatalChartSource(object())
            chart['source_status'] = 'stale'
            self.assertEqual(source.selected_natal(session, chart_id)[2],
                             'unsupported_stale_birth_source')
            ephe.assert_not_called()
            chart['source_status'] = 'current'
            with self.assertRaisesRegex(ValueError, 'engine/data versions differ'):
                source.selected_natal(session, chart_id)
            charts.return_value.get_chart.assert_called_with(session, chart_id)
            ephe.assert_not_called()  # short circuit before source calculation
