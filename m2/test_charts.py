"""Actual owned PostgreSQL and independently timed synthetic solar fixture."""

from datetime import datetime, timedelta, timezone
import unittest

from m2.charts import Charts, resolve_body
from m2.test_support import DatabaseCase


UTC = timezone.utc
EQUINOX = datetime(2024, 3, 20, 3, 6, tzinfo=UTC)  # USNO minute reference
SETTINGS = {'zodiac': 'tropical', 'house_system': 'none', 'node_type': 'true',
            'aspects': ['conjunction', 'sextile']}


class ChartRecordsTests(DatabaseCase):
    def test_immutable_versions_are_owner_scoped_and_source_deletion_cascades(self):
        charts = Charts(self.store)
        for session in (self.alice, self.bob):
            charts.add_person(session, 'person', 'Synthetic person')
            charts.add_profile(session, 'profile', SETTINGS)
        self.store.create_conversation(self.alice, 'source')
        self.store.begin(self.alice, 'source', 'turn', 'Synthetic documented local time')
        self.store.append(self.alice, 'source', 'turn', 'complete', {})

        charts.add_birth(self.alice, 'person', 'birth', 'Europe/Copenhagen', 'synthetic documented time',
                         wall_time=datetime(2024, 3, 20, 4, 6), source=('source', 'turn'))
        original = charts.create_chart(self.alice, 'chart-v1', 'person', 'birth', 'profile', 1)
        longitude = original['result']['natal_sun']['sun_longitude_degrees']
        self.assertLess(min(longitude, 360 - longitude), 0.05)
        self.assertEqual(original['result']['natal_sun']['status'], 'exact_supplied_time')
        self.assertEqual(original['result']['birth']['source_turn_id'], 'turn')
        with self.assertRaises(KeyError):
            charts.get_chart(self.bob, 'chart-v1')
        with self.assertRaises(KeyError):
            charts.create_chart(self.bob, 'other', 'person', 'birth', 'profile', 1)

        revised = dict(SETTINGS, aspects=['square'])
        self.assertEqual(charts.add_profile(self.alice, 'profile', revised), 2)
        charts.create_chart(self.alice, 'chart-v2', 'person', 'birth', 'profile', 2)
        self.assertEqual(charts.get_chart(self.alice, 'chart-v1')['result'], original['result'])
        self.assertEqual(charts.get_chart(self.alice, 'chart-v2')['result']['profile']['settings'], revised)
        self.ledger.delete_conversation(self.store, self.alice, 'source')
        with self.assertRaises(KeyError):
            charts.get_chart(self.alice, 'chart-v1')
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM birth_records').fetchone()['n'], 0)

    def test_unknown_time_interval_and_dst_gap_do_not_create_false_birth_instant(self):
        charts = Charts(self.store)
        charts.add_person(self.alice, 'person', 'Synthetic unknown time')
        charts.add_profile(self.alice, 'profile', SETTINGS)
        with self.assertRaisesRegex(ValueError, 'Nonexistent'):
            charts.add_birth(self.alice, 'person', 'gap', 'Europe/Copenhagen', 'synthetic',
                             wall_time=datetime(2024, 3, 31, 2, 30))
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            charts.add_birth(self.alice, 'person', 'fold', 'Europe/Copenhagen', 'synthetic',
                             wall_time=datetime(2024, 10, 27, 2, 30))
        charts.add_birth(self.alice, 'person', 'unknown', 'UTC', 'synthetic unknown time',
                         earliest_utc=EQUINOX - timedelta(hours=12),
                         latest_utc=EQUINOX + timedelta(hours=12))
        result = charts.create_chart(self.alice, 'uncertain', 'person', 'unknown', 'profile', 1)['result']
        self.assertEqual(result['natal_sun']['status'], 'uncertain_supplied_interval')
        self.assertIsNone(result['natal_sun']['solar_interval']['stable_sign'])
        self.assertIsNone(result['natal_sun']['solar_interval']['reference_time'])
        self.assertIsNone(result['birth']['wall_time'])
        self.assertEqual(result['houses'], 'unsupported')

    def test_declared_solar_transit_event_and_unsupported_uncertainty(self):
        charts = Charts(self.store)
        charts.add_person(self.alice, 'person', 'Synthetic equinox')
        charts.add_profile(self.alice, 'profile', SETTINGS)
        charts.add_birth(self.alice, 'person', 'exact', 'UTC', 'synthetic equinox',
                         wall_time=datetime(2024, 3, 20, 3, 6))
        charts.add_birth(self.alice, 'person', 'interval', 'UTC', 'synthetic uncertain',
                         earliest_utc=EQUINOX - timedelta(hours=12),
                         latest_utc=EQUINOX + timedelta(hours=12))
        charts.create_chart(self.alice, 'exact', 'person', 'exact', 'profile', 1)
        charts.create_chart(self.alice, 'uncertain', 'person', 'interval', 'profile', 1)

        window_start = EQUINOX - timedelta(hours=6)
        window_end = EQUINOX + timedelta(hours=6)
        events = charts.find_events(self.alice, 'exact', window_start, window_end)
        self.assertEqual(events['status'], 'supported')
        self.assertEqual(events['body_id'], 'sun')
        self.assertEqual(len(events['events']), 1)
        crossing = datetime.fromisoformat(events['events'][0]['instant_utc'])
        self.assertLess(abs(crossing - EQUINOX), timedelta(minutes=3))
        self.assertEqual(charts.find_events(self.alice, 'exact', EQUINOX + timedelta(days=3),
                                            EQUINOX + timedelta(days=4))['events'], [])
        transit = charts.transit_at(self.alice, 'exact', EQUINOX)
        self.assertLess(transit['separation_from_exact_aspect_degrees'], 0.001)
        self.assertEqual(transit['in_orb'], 'unsupported_without_declared_orb_policy')
        self.assertEqual(charts.find_events(self.alice, 'uncertain', window_start, window_end)
                         ['status'], 'unsupported_uncertain_birth_time')
        self.assertEqual(charts.transit_at(self.alice, 'uncertain', EQUINOX)
                         ['status'], 'unsupported_uncertain_birth_time')
        self.assertEqual(resolve_body('Sol'), 'sun')
        with self.assertRaisesRegex(ValueError, 'Ambiguous Vulcan'):
            charts.find_events(self.alice, 'exact', window_start, window_end, body='Vulcan')
        with self.assertRaisesRegex(ValueError, 'Vulcanus'):
            resolve_body('Vulcanus')
        with self.assertRaisesRegex(ValueError, 'Unsupported aspect'):
            charts.find_events(self.alice, 'exact', window_start, window_end, aspect='trine')

    def test_unsupported_settings_and_time_ranges_fail_before_persistence(self):
        charts = Charts(self.store)
        charts.add_person(self.alice, 'person', 'Synthetic')
        with self.assertRaisesRegex(ValueError, 'Unsupported calculation profile'):
            charts.add_profile(self.alice, 'unsafe', dict(SETTINGS, house_system='placidus'))
        charts.add_profile(self.alice, 'profile', SETTINGS)
        with self.assertRaisesRegex(ValueError, 'Unsupported solar interval'):
            charts.add_birth(self.alice, 'person', 'too-wide', 'UTC', 'synthetic',
                             earliest_utc=EQUINOX - timedelta(days=2), latest_utc=EQUINOX)
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM birth_records').fetchone()['n'], 0)


if __name__ == '__main__':
    unittest.main()
