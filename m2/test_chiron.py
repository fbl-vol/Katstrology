"""Opt-in Chiron from public Swiss main-asteroid data, not a default-body rewrite.

Published March 20 2024 00:00 New York (EDT = 04:00 UTC) Chiron 18°16' Aries:
https://cafeastrology.com/wp-content/uploads/2023/04/AsteroidsEphemeris2024.pdf
The PDF gives minute resolution; it is not a reference for extra digits or birth facts.
"""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import shutil
import unittest

from m2.natal import (CHIRON_FILE, CHIRON_SHA256, EPHE_DIRECTORY,
                       calculate_natal, checked_natal_settings)
from m2.birth_flow import BirthFlow
from m2.synastry import Synastry
from m2.test_support import DatabaseCase
from m2.transit_views import view
from m2.transits import Transits
from m2.people import DEFAULT_NATAL_SETTINGS, People
from m2.core_calc import aspect_separation


class ChironTests(unittest.TestCase):
    def test_published_chiron_anchor_and_default_chart_unchanged(self):
        instant = datetime(2024, 3, 20, 4, tzinfo=timezone.utc)
        default = calculate_natal(instant, 51.5, -0.17, DEFAULT_NATAL_SETTINGS)
        selected = calculate_natal(instant, 51.5, -0.17,
                                   {**DEFAULT_NATAL_SETTINGS, 'include_chiron': True})
        self.assertEqual([p['id'] for p in default['positions']],
                         [p['id'] for p in selected['positions'] if p['id'] != 'chiron'])
        self.assertEqual(default['ephemeris_sha256'].keys(), {'sepl_18.se1', 'semo_18.se1'})
        self.assertEqual(selected['ephemeris_sha256'][CHIRON_FILE], CHIRON_SHA256)
        chiron = next(point for point in selected['positions'] if point['id'] == 'chiron')
        self.assertAlmostEqual(chiron['longitude_degrees'], 18 + 16/60, delta=1/60)
        self.assertGreater(chiron['speed_degrees_per_day'], 0)
        self.assertEqual(chiron['sign'], 0)
        self.assertEqual(chiron['retrograde'], False)
        self.assertIn(chiron['house'], range(1, 13))
        self.assertTrue(any('chiron' in (aspect['first'], aspect['second'])
                            for aspect in selected['aspects']))
        by_id = {point['id']: point for point in
                 selected['positions'] + selected['houses']['angles']}
        for item in selected['aspects']:
            if 'chiron' in (item['first'], item['second']):
                self.assertAlmostEqual(item['orb_degrees'], aspect_separation(
                    by_id[item['first']]['longitude_degrees'],
                    by_id[item['second']]['longitude_degrees'], item['kind']))

    def test_missing_or_different_data_fails_without_moshier_substitution(self):
        instant = datetime(2024, 3, 20, 4, tzinfo=timezone.utc)
        settings = {**DEFAULT_NATAL_SETTINGS, 'include_chiron': True}
        with TemporaryDirectory() as folder:
            source = Path(folder)
            for filename in ('sepl_18.se1', 'semo_18.se1'):
                shutil.copy2(EPHE_DIRECTORY / filename, source / filename)
            with patch('m2.natal.EPHE_DIRECTORY', source):
                with self.assertRaisesRegex(ValueError, 'chiron_data_missing_or_unverified'):
                    calculate_natal(instant, 51.5, -0.17, settings)
                (source / CHIRON_FILE).write_bytes(b'unsupported numerical data')
                with self.assertRaisesRegex(ValueError, 'chiron_data_missing_or_unverified'):
                    calculate_natal(instant, 51.5, -0.17, settings)
                # Explicitly declined Chiron never silently reads the asteroid file.
                self.assertNotIn(CHIRON_FILE, calculate_natal(
                    instant, 51.5, -0.17, DEFAULT_NATAL_SETTINGS)['ephemeris_sha256'])

    def test_profile_requires_explicit_true_selection(self):
        for value in (False, None, 'true', 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                checked_natal_settings({**DEFAULT_NATAL_SETTINGS, 'include_chiron': value})


class ChironArchiveTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.person_a = self._generate('A', {**DEFAULT_NATAL_SETTINGS, 'include_chiron': True})
        self.person_b = self._generate('B', None)

    def _generate(self, suffix, settings):
        person = People(self.store).add(self.alice, f'Synthetic {suffix}')
        return BirthFlow(self.store).generate(self.alice, person['id'], {
            'request_id': f'chiron-source-{suffix}', 'birth_date': '2024-03-20',
            'birth_time': '04:06' if suffix == 'A' else '05:06',
            'time_unknown': False, 'birthplace': 'Copenhagen, Capital Region, Denmark',
            'place_id': '2618425', 'provisional': True, 'zone_override': None,
            'latitude_override': None, 'longitude_override': None, 'fold': None,
            'settings': settings,
        })['chart']

    def test_selected_chiron_survives_archive_transit_and_mixed_synastry(self):
        a, b = self.person_a, self.person_b
        self.assertIn('chiron', [point['id'] for point in a['result']['natal']['positions']])
        self.assertNotIn('chiron', [point['id'] for point in b['result']['natal']['positions']])
        instant = datetime(2025, 2, 1, tzinfo=timezone.utc)
        selected = Transits(self.store).snapshot(self.alice, a['id'], instant,
                                                 'chiron', 'chiron', 'conjunction')
        self.assertEqual(selected['status'], 'supported')
        self.assertEqual(selected['ephemeris_sha256'][CHIRON_FILE], CHIRON_SHA256)
        with self.assertRaisesRegex(ValueError, 'unselected Chiron'):
            Transits(self.store).snapshot(self.alice, b['id'], instant,
                                          'chiron', 'sun', 'conjunction')
        mixed = Synastry(self.store).compare(self.alice, a['id'], b['id'], [a['id'], b['id']])
        self.assertEqual(mixed['status'], 'supported')
        self.assertIn(CHIRON_FILE, mixed['ephemeris_a_sha256'])
        self.assertNotIn(CHIRON_FILE, mixed['ephemeris_b_sha256'])
        with self.assertRaises(KeyError):
            Transits(self.store).snapshot(self.bob, a['id'], instant,
                                          'chiron', 'sun', 'conjunction')

    def test_natal_transit_view_opt_in_does_not_change_sky_only(self):
        selected = view(self.store, self.alice, '2025-02-01', '12:00',
                        'Europe/Copenhagen', 'unspecified', 'natal_transits', self.person_a['id'])
        plain = view(self.store, self.alice, '2025-02-01', '12:00',
                     'Europe/Copenhagen', 'unspecified', 'sky')
        self.assertIn('chiron', [point['id'] for point in selected['positions']])
        self.assertNotIn('chiron', [point['id'] for point in plain['positions']])
        self.assertIn(CHIRON_FILE, selected['ephemeris_sha256'])
        self.assertNotIn(CHIRON_FILE, plain['ephemeris_sha256'])
