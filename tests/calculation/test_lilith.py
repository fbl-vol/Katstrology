"""Swiss lunar apogee opt-in; independent rounded model example:
https://horoscopetools.com/guides/lilith-in-capricorn/ (2017-11-09 03:58:17 UTC).
The published longitude is rounded and its UTC-to-Julian-day convention differs
slightly from swe.utc_to_jd; neither source asserts sub-arcsecond agreement.
"""

from datetime import datetime, timezone
import unittest

from m2.chat.agent_reads import project_transit_view
from m2.people.birth_flow import BirthFlow
from m2.calculation.natal import calculate_natal, checked_natal_settings
from m2.people.people import DEFAULT_NATAL_SETTINGS, People
from tests.support.database import DatabaseCase
from m2.chat.tool_answers import natal_answer
from m2.calculation.transit_views import view
from m2.calculation.transits import Transits


class LilithCalculationTests(unittest.TestCase):
    def test_independent_numeric_anchor_and_unmodified_default(self):
        instant = datetime(2017, 11, 9, 3, 58, 17, tzinfo=timezone.utc)
        base = calculate_natal(instant, 55.67, 12.56, DEFAULT_NATAL_SETTINGS)
        mean = calculate_natal(instant, 55.67, 12.56,
                               {**DEFAULT_NATAL_SETTINGS, 'include_lilith': 'mean'})
        true = calculate_natal(instant, 55.67, 12.56,
                               {**DEFAULT_NATAL_SETTINGS, 'include_lilith': 'osculating'})
        self.assertEqual(base['positions'], [point for point in mean['positions']
                                              if point['id'] != 'lilith_mean'])
        self.assertEqual(base['aspects'], [aspect for aspect in mean['aspects']
                                            if 'lilith_mean' not in (aspect['first'], aspect['second'])])
        self.assertNotIn('lilith_convention', base)
        for result, name, expected in ((mean, 'lilith_mean', 270.0000775),
                                       (true, 'lilith_osculating', 242.4181950)):
            point = next(item for item in result['positions'] if item['id'] == name)
            self.assertAlmostEqual(point['longitude_degrees'], expected, delta=0.0001)
            self.assertEqual(point['sign'], int(expected // 30))
            self.assertIn(point['house'], range(1, 13))
            self.assertEqual(result['ephemeris_sha256'], base['ephemeris_sha256'])
            self.assertEqual(result['lilith_convention'], 'mean' if name == 'lilith_mean' else 'osculating')
        self.assertGreater(abs(mean['positions'][-1]['longitude_degrees'] -
                               true['positions'][-1]['longitude_degrees']), 27)

    def test_only_explicit_declared_conventions(self):
        for value in (False, None, True, 1, 'true', 'waldemath', '1181', [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                checked_natal_settings({**DEFAULT_NATAL_SETTINGS, 'include_lilith': value})


class LilithArchiveTests(DatabaseCase):
    def _generate(self, suffix, settings):
        person = People(self.store).add(self.alice, f'Synthetic Lilith {suffix}')
        result = BirthFlow(self.store).generate(self.alice, person['id'], {
            'request_id': f'lilith-source-{suffix}', 'birth_date': '2017-11-09',
            'birth_time': '04:58', 'time_unknown': False,
            'birthplace': 'Copenhagen, Capital Region, Denmark', 'place_id': '2618425',
            'provisional': True, 'zone_override': None, 'latitude_override': None,
            'longitude_override': None, 'fold': None, 'settings': settings,
        })
        return result['chart']

    def test_immutable_selection_owner_and_transit_convention(self):
        original = self._generate('original', None)
        mean = self._generate('mean', {**DEFAULT_NATAL_SETTINGS, 'include_lilith': 'mean'})
        true = self._generate('true', {**DEFAULT_NATAL_SETTINGS, 'include_lilith': 'osculating'})
        self.assertNotIn('include_lilith', original['result']['profile']['settings'])
        self.assertNotIn('lilith_convention', original['result']['natal'])
        instant = datetime(2025, 2, 1, tzinfo=timezone.utc)
        transits = Transits(self.store)
        result = transits.snapshot(self.alice, mean['id'], instant, 'lilith_mean',
                                   'lilith_mean', 'conjunction')
        self.assertEqual(result['status'], 'supported')
        self.assertEqual(result['lilith_convention'], 'mean')
        self.assertEqual(result['profile_revision'], mean['profile_revision'])
        with self.assertRaisesRegex(ValueError, 'event scans are unsupported'):
            transits.events(self.alice, mean['id'], instant, instant.replace(day=2),
                            'lilith_mean', 'sun', 'conjunction')
        self.assertEqual(transits.events(self.alice, mean['id'], instant, instant.replace(day=2),
                                         'sun', 'lilith_mean', 'conjunction')['status'], 'supported')
        for chart, wrong in ((mean, 'lilith_osculating'), (true, 'lilith_mean'),
                             (original, 'lilith_mean')):
            with self.subTest(wrong=wrong), self.assertRaisesRegex(ValueError, 'unselected lunar apogee'):
                transits.snapshot(self.alice, chart['id'], instant, wrong, 'sun', 'conjunction')
        for chart, selected in ((mean, 'lilith_mean'), (true, 'lilith_osculating')):
            snapshot = view(self.store, self.alice, '2025-02-01', '12:00',
                            'Europe/Copenhagen', 'unspecified', 'natal_transits', chart['id'])
            self.assertIn(selected, [point['id'] for point in snapshot['positions']])
            self.assertIn(selected, [point['id'] for point in snapshot['natal_positions']])
            self.assertEqual(snapshot['lilith_convention'], chart['result']['profile']['settings']['include_lilith'])
            self.assertEqual(project_transit_view(snapshot)['lilith_convention'], snapshot['lilith_convention'])
            self.assertIn('lunar apogee', natal_answer(chart['id'], chart['result']))
        sky = view(self.store, self.alice, '2025-02-01', '12:00',
                   'Europe/Copenhagen', 'unspecified', 'sky')
        self.assertNotIn('lilith_convention', sky)
        self.assertFalse(any(point['id'].startswith('lilith_') for point in sky['positions']))
        with self.assertRaises(KeyError):
            transits.snapshot(self.bob, mean['id'], instant, 'lilith_mean', 'sun', 'conjunction')
        self.assertEqual(original['result']['natal'], transits.charts.get_chart(self.alice, original['id'])['result']['natal'])
