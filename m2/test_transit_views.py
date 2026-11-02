"""Independent anchor and isolated owner-scoped sky/natal view regressions."""

from datetime import datetime, timedelta, timezone
from time import perf_counter

from m2.people import People
from m2.revisions import correct
from m2.test_support import DatabaseCase
from m2.transit_views import reporting_instant, view
from m2.transits import _position_at


class TransitViewTests(DatabaseCase):
    def test_month_animation_requires_recalculation_not_endpoint_interpolation(self):
        # Mercury's April 2024 retrograde loop makes endpoint tweening factually wrong.
        start = datetime(2024, 3, 20, tzinfo=timezone.utc)
        end = start + timedelta(days=30)
        beginning = _position_at('mercury', start)[0]
        finish = _position_at('mercury', end)[0]
        middle = _position_at('mercury', start + timedelta(days=15))[0]
        linear_middle = beginning + ((finish - beginning + 180) % 360 - 180) / 2
        error = abs((middle - linear_middle + 180) % 360 - 180)
        self.assertGreater(error, 1.0)
        began = perf_counter()
        for day in range(31):
            instant = start + timedelta(days=day)
            for body in ('sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
                         'uranus', 'neptune', 'pluto'):
                _position_at(body, instant)
        print(f'month sampled sky: 31 dates x 10 bodies, {perf_counter() - began:.3f}s; '
              f'endpoint interpolation Mercury error {error:.3f} degrees')

    def test_wall_clock_zone_dst_gap_overlap_and_utc_instant(self):
        instant, report = reporting_instant('2024-03-20', '04:06', 'Europe/Paris')
        self.assertEqual(instant, datetime(2024, 3, 20, 3, 6, tzinfo=timezone.utc))
        self.assertEqual(report['offset'], '+0100')
        with self.assertRaisesRegex(ValueError, 'nonexistent_local_time'):
            reporting_instant('2024-03-31', '02:30', 'Europe/Paris')
        with self.assertRaisesRegex(ValueError, 'choose_dst_occurrence'):
            reporting_instant('2024-10-27', '02:30', 'Europe/Paris')
        early, _ = reporting_instant('2024-10-27', '02:30', 'Europe/Paris', 'earlier')
        late, _ = reporting_instant('2024-10-27', '02:30', 'Europe/Paris', 'later')
        self.assertEqual((late - early).total_seconds(), 3600)
        with self.assertRaisesRegex(ValueError, 'occurrence_not_applicable'):
            reporting_instant('2024-03-20', '04:06', 'Europe/Paris', 'later')
        for invalid in [('2024-03-20', '', 'UTC'), ('2024-03-20', '04:06', 'unknown-zone'),
                        ('2024-02-30', '04:06', 'UTC'), ('2099-12-31', '25:06', 'UTC'),
                        ('2100-01-01', '04:06', 'UTC')]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                reporting_instant(*invalid)

    def test_sky_only_independent_equinox_anchor_changes_with_date_and_no_house(self):
        # Independent published 2024 March equinox ~03:06 UTC (USNO); Sun ~0° Aries.
        sky = view(self.store, self.alice, '2024-03-20', '03:06', 'UTC', 'unspecified', 'sky')
        self.assertEqual(sky['status'], 'supported')
        self.assertEqual(sky['birth_time_status'], 'not_applicable')
        self.assertEqual(sky['natal_positions'], [])
        self.assertEqual(len(sky['positions']), 10)
        sun = next(item for item in sky['positions'] if item['id'] == 'sun')
        self.assertLess(min(sun['longitude_degrees'], 360 - sun['longitude_degrees']), .12)
        self.assertEqual(sun['retrograde'], sun['speed_degrees_per_day'] < 0)
        later = view(self.store, self.alice, '2024-04-20', '03:06', 'UTC', 'unspecified', 'sky')
        later_sun = next(item for item in later['positions'] if item['id'] == 'sun')
        self.assertGreater((later_sun['longitude_degrees'] - sun['longitude_degrees']) % 360, 28)
        self.assertLess((later_sun['longitude_degrees'] - sun['longitude_degrees']) % 360, 32)
        self.assertTrue(all(row['first'] != row['second'] for row in sky['same_sky_aspects']))
        self.assertLessEqual(len(sky['same_sky_aspects']), 12)
        self.assertEqual(sky['orb_policy']['square'], 6)

    def test_corrected_birth_source_cannot_back_a_current_natal_overlay(self):
        self.store.create_conversation(self.alice, 'birth-source')
        self.store.begin(self.alice, 'birth-source', 'supplied', 'Synthetic exact birth input')
        self.store.append(self.alice, 'birth-source', 'supplied', 'complete', {})
        people = People(self.store)
        people.charts.add_person(self.alice, 'source-person', 'Source-linked')
        people.charts.add_birth(self.alice, 'source-person', 'source-birth', 'UTC',
            'user supplied', wall_time=datetime(2001, 6, 21, 4, 0),
            source=('birth-source', 'supplied'))
        chart = people.create_chart(self.alice, 'source-person', 'source-birth',
                                    'natal-default', 1)
        self.assertEqual(view(self.store, self.alice, '2024-03-20', '03:06', 'UTC',
            'unspecified', 'natal_transits', chart['id'])['status'], 'supported')
        correct(self.store, self.alice, 'birth-source', 'correction', 'supplied',
                'correct', 'This time was not verified.')
        stale = view(self.store, self.alice, '2024-03-20', '03:06', 'UTC',
                     'unspecified', 'natal_transits', chart['id'])
        self.assertEqual(stale['status'], 'unsupported_stale_birth_source')
        self.assertNotIn('positions', stale)

    def test_selected_natal_pairing_identity_unknown_time_and_owner_fence(self):
        people = People(self.store)
        people.charts.add_person(self.alice, 'one', 'One')
        people.charts.add_person(self.bob, 'other', 'Other')
        birth = people.add_birth(self.alice, 'one', {'mode': 'exact', 'zone': 'UTC',
                                                   'wall_time': '2001-06-21T04:00:00',
                                                   'latitude': 51.5, 'longitude': -0.17})
        chart = people.create_chart(self.alice, 'one', birth, 'natal-default', 1)
        result = view(self.store, self.alice, '2024-03-20', '03:06', 'UTC',
                      'unspecified', 'natal_transits', chart['id'])
        self.assertEqual(result['chart_id'], chart['id'])
        self.assertEqual(result['profile_revision'], chart['profile_revision'])
        self.assertTrue(result['transit_to_natal_total'])
        self.assertTrue(result['same_sky_total'])
        self.assertEqual(len(result['transit_to_natal_aspects']), result['transit_to_natal_total'])
        self.assertTrue(all(row['a_body_id'] in {item['id'] for item in result['positions']}
                            and row['b_body_id'] in {item['id'] for item in result['natal_positions']}
                            for row in result['transit_to_natal_aspects']))
        self.assertFalse(any(item['id'] == 'south_node' for item in result['natal_positions']))
        self.assertEqual(result['natal_house_status'], 'supported')
        birth_instant = view(self.store, self.alice, '2001-06-21', '04:00', 'UTC',
                             'unspecified', 'natal_transits', chart['id'])
        conjunction = next(row for row in birth_instant['transit_to_natal_aspects']
                           if row['a_body_id'] == row['b_body_id'] == 'sun'
                           and row['aspect'] == 'conjunction')
        self.assertLess(conjunction['orb_degrees'], .00001)
        with self.assertRaises(KeyError):
            view(self.store, self.bob, '2024-03-20', '03:06', 'UTC',
                 'unspecified', 'natal_transits', chart['id'])
        with self.assertRaises(ValueError):
            view(self.store, self.alice, '2024-03-20', '03:06', 'UTC',
                 'unspecified', 'sky', chart['id'])
        uncertain = people.add_birth(self.alice, 'one', {'mode': 'interval', 'zone': 'UTC',
            'earliest_utc': '2001-06-21T04:00:00+00:00',
            'latest_utc': '2001-06-21T16:00:00+00:00'})
        unknown = people.create_chart(self.alice, 'one', uncertain, 'natal-default', 1)
        limited = view(self.store, self.alice, '2024-03-20', '03:06', 'UTC',
                       'unspecified', 'natal_transits', unknown['id'])
        self.assertEqual(limited['status'], 'unsupported_uncertain_birth_time_or_non_natal_chart')
        self.assertNotIn('positions', limited)
