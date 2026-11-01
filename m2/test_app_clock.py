"""Clock-source, UTC boundary and DST fold qualification without a live clock."""

from datetime import datetime, timezone
import unittest

from m2.app_clock import snapshot
from m2.transit_views import reporting_instant


class ClockSnapshotTests(unittest.TestCase):
    def test_zone_boundary_and_explicit_utc_fallback(self):
        clock = lambda: datetime(2026, 1, 1, 1, 15, 42, tzinfo=timezone.utc)
        local = snapshot(clock, 'America/Los_Angeles')
        self.assertEqual(local['reporting']['date'], '2025-12-31')
        self.assertIn('not_verified_location', local['reporting']['zone_source'])
        self.assertEqual(snapshot(clock)['reporting']['zone'], 'UTC')
        self.assertIn('fallback', snapshot(clock)['reporting']['zone_source'])
        with self.assertRaises(ValueError):
            snapshot(clock, 'not_a_real_zone')
        with self.assertRaises(ValueError):
            snapshot(clock, 'posixrules')  # OS file is not an IANA reporting zone
        with self.assertRaises(ValueError):
            snapshot(lambda: datetime(2026, 1, 1), 'UTC')

    def test_repeated_hour_maps_back_to_original_utc_instant(self):
        for instant, occurrence in ((datetime(2024, 11, 3, 5, 30, 29, tzinfo=timezone.utc), 'earlier'),
                                    (datetime(2024, 11, 3, 6, 30, 29, tzinfo=timezone.utc), 'later')):
            anchor = snapshot(lambda: instant, 'America/New_York')
            local = anchor['reporting']
            self.assertEqual(local['occurrence'], occurrence)
            resolved, _ = reporting_instant(local['date'], local['time'], local['zone'],
                                            local['occurrence'])
            self.assertEqual(resolved.isoformat(), instant.isoformat())
