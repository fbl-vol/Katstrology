"""Synthetic-only sampled transit motion: geometry, cost, owner and time bounds."""

from datetime import date, datetime, timedelta, timezone
from time import perf_counter
import unittest

from m2.birth_flow import BirthFlow
from m2.natal import BODY_IDS, _ephemeris
from m2.people import People
from m2.test_support import DatabaseCase
from m2.transit_animation import frames
from m2.transits import _position_at


def angular_error(a, b):
    return abs((a - b + 180) % 360 - 180)


class MotionGeometryTests(unittest.TestCase):
    def test_sample_interval_near_mercury_station_and_zodiac_wrap(self):
        # The spring 2024 Mercury station and zodiac wrap exercise reversal and seam.
        _ephemeris()
        start = datetime(2024, 4, 1, tzinfo=timezone.utc)
        worst = 0.0
        reversals = False
        wraps = False
        elapsed = perf_counter()
        for body in BODY_IDS:
            for index in range(7 * 24 * 4):
                left_time = start + timedelta(minutes=15 * index)
                left, speed = _position_at(body, left_time)
                right, next_speed = _position_at(body, left_time + timedelta(minutes=15))
                middle, _ = _position_at(body, left_time + timedelta(minutes=7, seconds=30))
                delta = (right - left + 180) % 360 - 180
                worst = max(worst, angular_error((left + delta / 2) % 360, middle))
                wraps |= abs(right - left) > 180
                if body == 'mercury':
                    reversals |= speed * next_speed < 0
        elapsed = perf_counter() - elapsed
        self.assertTrue(reversals)
        self.assertTrue(wraps)
        self.assertLess(worst, 0.0001)  # <0.36 arcseconds at unsampled midpoints
        self.assertLess(elapsed, 2.0)  # generous local CPU guard, not production profiling


class MotionArchiveTests(DatabaseCase):
    def test_owner_source_range_and_current_natal(self):
        person = People(self.store).add(self.alice, 'Synthetic motion reader')
        chart = BirthFlow(self.store).generate(self.alice, person['id'], {
            'request_id': 'motion-source', 'birth_date': '2024-03-20', 'birth_time': '04:06',
            'time_unknown': False, 'birthplace': 'Copenhagen, Capital Region, Denmark',
            'place_id': '2618425', 'provisional': True, 'zone_override': None,
            'latitude_override': None, 'longitude_override': None, 'fold': None,
            'settings': None,
        })['chart']
        start, end = date(2024, 4, 1), date(2024, 4, 8)
        motion = frames(self.store, self.alice, chart['id'], start, end)
        self.assertEqual(motion['status'], 'supported')
        self.assertEqual(motion['profile_revision'], chart['profile_revision'])
        self.assertEqual(motion['ephemeris_sha256'], chart['result']['natal']['ephemeris_sha256'])
        self.assertEqual(tuple(motion['bodies']), tuple(BODY_IDS))
        self.assertEqual(len(motion['longitudes']), 7 * 24 * 4 + 1)
        self.assertTrue(all(len(sample) == len(BODY_IDS) for sample in motion['longitudes']))
        with self.assertRaises(KeyError):
            frames(self.store, self.bob, chart['id'], start, end)
        unknown = People(self.store).add(self.alice, 'Synthetic unknown-time motion reader')
        unknown_chart = BirthFlow(self.store).generate(self.alice, unknown['id'], {
            'request_id': 'motion-unknown-source', 'birth_date': '2024-03-20',
            'birth_time': '', 'time_unknown': True,
            'birthplace': 'Copenhagen, Capital Region, Denmark', 'place_id': '2618425',
            'provisional': True, 'zone_override': None, 'latitude_override': None,
            'longitude_override': None, 'fold': None, 'settings': None,
        })['chart']
        self.assertEqual(frames(self.store, self.alice, unknown_chart['id'], start, end)['status'],
                         'unsupported_uncertain_birth_time_or_non_natal_chart')
        for left, right in ((date(2024, 4, 1), date(2024, 4, 1)),
                            (date(2024, 4, 1), date(2024, 4, 9)),
                            (date(2099, 12, 31), date(2100, 1, 1))):
            with self.assertRaises(ValueError):
                frames(self.store, self.alice, chart['id'], left, right)
