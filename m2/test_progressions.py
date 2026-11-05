"""Independent calendar anchors, geometry and archived secondary progression branches."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from m2.advanced import Advanced
from m2.agent_reads import execute
from m2.birth_flow import BirthFlow
from m2.gateway import run_turn
from m2.provider_model import ResponsesModel
from m2.test_agent_reads import FakeBridge, ScriptedTransport
from m2.people import People
from m2.progressions import Progressions, _astronomical_mc, calendar_map, interpolate_mc
from m2.returns import _jd
from m2.test_support import DatabaseCase
from m2.transits import _position_at
from m2.core_calc import aspect_separation

UTC = timezone.utc


class CalendarProgressionTests(unittest.TestCase):
    def test_fractional_anniversary_leap_and_february_29_boundary(self):
        born = datetime(2000, 2, 29, 12, tzinfo=UTC)
        age, fraction, left, right, mapped = calendar_map(born, datetime(2001, 2, 28, 12, tzinfo=UTC))
        self.assertEqual((age, fraction, left, right), (
            1, 0, datetime(2001, 2, 28, 12, tzinfo=UTC),
            datetime(2002, 2, 28, 12, tzinfo=UTC)))
        self.assertEqual(mapped, born + timedelta(days=1))
        _, fraction, left, right, mapped = calendar_map(
            born, datetime(2003, 8, 29, 12, tzinfo=UTC))
        self.assertEqual((left, right), (
            datetime(2003, 2, 28, 12, tzinfo=UTC),
            datetime(2004, 2, 29, 12, tzinfo=UTC)))
        self.assertAlmostEqual(fraction, 182/366)
        self.assertEqual(mapped, born + timedelta(days=3 + fraction))
        with self.assertRaisesRegex(ValueError, 'before birth'):
            calendar_map(born, born - timedelta(seconds=1))

    def test_circular_mc_interpolation_wraps_without_returning_360(self):
        self.assertAlmostEqual(interpolate_mc(359, 1, .5), 0)
        self.assertAlmostEqual(interpolate_mc(1, 359, .5), 0)
        self.assertAlmostEqual(interpolate_mc(359, 1, .75), .5)
        self.assertAlmostEqual(interpolate_mc(120, 121, .4), 120.4)


class ProgressionArchiveTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.person_id = People(self.store).add(self.alice, 'Synthetic progressed reader')['id']
        self.chart = self._chart('birth-progressed', '2024-03-20', '04:06', 51.5)

    def _chart(self, request, day, hour, latitude):
        return BirthFlow(self.store).generate(self.alice, self.person_id, {
            'request_id': request, 'birth_date': day, 'birth_time': hour,
            'time_unknown': not bool(hour), 'birthplace': 'Synthetic progressed birthplace',
            'place_id': None, 'provisional': True, 'zone_override': 'UTC',
            'latitude_override': latitude, 'longitude_override': -0.17,
            'fold': None, 'settings': None,
        })['chart']

    def test_mapped_sun_planets_and_two_mc_branches_are_not_transits(self):
        effective = datetime(2025, 3, 20, 4, 6, tzinfo=UTC)
        result = Progressions(self.store).calculate(self.alice, self.chart['id'], effective)
        self.assertEqual(result['status'], 'supported')
        self.assertEqual(result['age_completed_years'], 1)
        self.assertEqual(result['anniversary_fraction'], 0)
        self.assertEqual(result['mapped_ephemeris_utc'], '2024-03-21T04:06:00+00:00')
        sun = next(point for point in result['positions'] if point['id'] == 'sun')
        self.assertAlmostEqual(sun['longitude_degrees'], 1.0, delta=.2)
        self.assertGreater(abs(sun['longitude_degrees'] - _position_at('sun', effective)[0]), .1)
        self.assertNotIn('speed_degrees_per_day', sun)
        self.assertIsNone(sun['house'])
        natal_mc = result['natal_mc_degrees']
        self.assertEqual(result['mc_status'], 'supported')
        self.assertAlmostEqual(result['mcp_degrees'], _astronomical_mc(
            datetime(2024, 3, 21, 4, 6, tzinfo=UTC), 51.5, -0.17))
        self.assertNotEqual(result['mcp_degrees'], natal_mc)
        for contact in result['mcr_contacts']:
            point = next(point for point in result['positions'] if point['id'] == contact['first'])
            self.assertAlmostEqual(contact['orb_degrees'],
                aspect_separation(point['longitude_degrees'], natal_mc, contact['kind']), delta=1e-6)
        for contact in result['mcp_contacts']:
            natal_point = next(point for point in self.chart['result']['natal']['positions']
                               if point['id'] == contact['second'])
            self.assertAlmostEqual(contact['orb_degrees'], aspect_separation(
                result['mcp_degrees'], natal_point['longitude_degrees'], contact['kind']), delta=1e-6)

    def test_mc_branches_scan_bounded_effective_dates_without_sky_substitution(self):
        progression = Progressions(self.store)
        start = datetime(2025, 3, 20, 4, 6, tzinfo=UTC)
        end = start + timedelta(days=366)
        for branch in ('mcp', 'mcr'):
            with self.subTest(branch=branch):
                found = progression.mc_events(self.alice, self.chart['id'], start, end,
                                              branch, 'sun', 'conjunction')
                self.assertEqual(found['status'], 'supported')
                self.assertEqual(found['branch'], branch)
                self.assertFalse(found['window_end_inclusive'])
                self.assertEqual(found['natal_mc_degrees'], next(point['longitude_degrees']
                    for point in self.chart['result']['natal']['houses']['angles']
                    if point['id'] == 'midheaven'))
                self.assertTrue(all(start <= datetime.fromisoformat(item['instant_utc']) < end
                                    for item in found['events']))
        with self.assertRaisesRegex(ValueError, 'at most 732'):
            progression.mc_events(self.alice, self.chart['id'], start,
                                  end + timedelta(days=366, seconds=1), 'mcp', 'sun', 'conjunction')
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'find_progressed_mc_contacts', {
                'chart_id': self.chart['id'], 'start_utc': start.isoformat(),
                'end_utc': end.isoformat(), 'branch': 'mcp',
                'body': 'sun', 'aspect': 'conjunction'}, set())

    def test_stationary_near_contact_is_partial_not_saved_as_complete(self):
        start = datetime(2025, 3, 20, 4, 6, tzinfo=UTC)
        natal_mc = next(point['longitude_degrees'] for point in self.chart['result']['natal']['houses']['angles']
                        if point['id'] == 'midheaven')
        station_jd = _jd(datetime(2024, 3, 21, 4, 7, tzinfo=UTC))

        def grazing_position(_body, jd):
            delta = jd - station_jd
            return natal_mc + .000002 * delta * delta, 0, 0, .000004 * delta

        with patch('m2.progressions._position', side_effect=grazing_position):
            found = Progressions(self.store).mc_events(self.alice, self.chart['id'],
                start, start + timedelta(days=1), 'mcr', 'sun', 'conjunction')
            unsaved = Advanced(self.store).save(self.alice, 'near-station', self.person_id,
                'progressed_mc_contacts', {'start_utc': start.isoformat(),
                    'end_utc': (start + timedelta(days=1)).isoformat(),
                    'branch': 'mcr', 'body': 'sun', 'aspect': 'conjunction'})
        self.assertEqual(found['status'], 'partial_near_station_contact')
        self.assertEqual(unsaved['status'], 'partial_near_station_contact')
        self.assertFalse(Advanced(self.store).list(self.alice, self.person_id,
                                                   'progressed_mc_contacts'))

    def test_fixture_mc_exact_event_matches_snapshot_geometry_and_saved_replay(self):
        chart = self._chart('timeline-fixture', '2001-06-21', '04:00', 51.5)
        start, end = datetime(2025, 7, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC)
        result = Progressions(self.store).mc_events(self.alice, chart['id'], start, end,
                                                 'mcp', 'mercury', 'square')
        self.assertEqual(result['status'], 'supported')
        self.assertTrue(result['events'])
        instant = datetime.fromisoformat(result['events'][0]['instant_utc'])
        snapshot = Progressions(self.store).calculate(self.alice, chart['id'], instant)
        natal_mercury = next(point['longitude_degrees'] for point in chart['result']['natal']['positions']
                             if point['id'] == 'mercury')
        self.assertAlmostEqual(aspect_separation(snapshot['mcp_degrees'], natal_mercury,
                                                 'square'), 0, delta=.001)
        parameters = {'start_utc': start.isoformat(), 'end_utc': end.isoformat(),
                      'branch': 'mcp', 'body': 'mercury', 'aspect': 'square'}
        saved = Advanced(self.store).save(self.alice, 'mcp-source', self.person_id,
                                         'progressed_mc_contacts', parameters)
        self.assertEqual(saved['events'], result['events'])
        self.assertEqual(Advanced(self.store).get(self.alice, 'mcp-source')['result']['events'],
                         result['events'])
        with self.assertRaises(KeyError):
            Advanced(self.store).get(self.bob, 'mcp-source')

    def test_progressed_mc_exact_start_belongs_only_to_first_half_open_window(self):
        progression = Progressions(self.store)
        chart = deepcopy(self.chart)
        natal = chart['result']['natal']
        mc = next(item['longitude_degrees'] for item in natal['houses']['angles']
                  if item['id'] == 'midheaven')
        next(item for item in natal['positions'] if item['id'] == 'sun')['longitude_degrees'] = mc
        born = datetime.fromisoformat(chart['result']['natal_sun']['instant_utc'])
        with patch.object(progression.chart_source, 'selected_natal', return_value=(chart, natal, None)):
            first = progression.mc_events(self.alice, chart['id'], born,
                born + timedelta(days=1), 'mcp', 'sun', 'conjunction')
            later = progression.mc_events(self.alice, chart['id'], born + timedelta(seconds=1),
                born + timedelta(days=1), 'mcp', 'sun', 'conjunction')
        self.assertEqual(first['events'][0]['instant_utc'], born.isoformat())
        self.assertFalse(later['events'])

    def test_model_read_preserves_branch_distinction_and_archives_full_result(self):
        self.store.create_conversation(self.alice, 'progressed-discussion')
        call = {'type': 'function_call', 'id': 'fc_progression', 'call_id': 'call_progression',
                'name': 'get_secondary_progression', 'arguments': json.dumps({
                    'chart_id': self.chart['id'], 'effective_utc': '2025-03-20T04:06:00+00:00'})}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'Symbolic comparison.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        self.assertEqual(run_turn(self.store, self.alice, 'progressed-discussion', 'progressed-request',
            'Read this synthetic progression', model, lambda _: None,
            selected_people=[{'person_id': self.person_id, 'chart_id': self.chart['id']}],
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        projection = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual(projection['method_version'], 'secondary-utc-calendar-naibod-mc-v1')
        self.assertIn('MCp', projection['mc_branch_policy'])
        self.assertIn('MCr', projection['mc_branch_policy'])
        self.assertTrue(projection['positions'])
        self.assertEqual(len(projection['natal_aspects']), projection['natal_aspects_total'])
        archived = next(event['payload'] for event in self.store.read_turn(
            self.alice, 'progressed-discussion', 'progressed-request')['events']
            if event['kind'] == 'tool_result' and event['payload'].get('name') == 'get_secondary_progression')
        self.assertEqual(archived['result']['mapped_ephemeris_utc'],
                         projection['mapped_ephemeris_utc'])
        self.assertEqual(len(archived['result']['positions']), 10)
        self.assertGreaterEqual(len(archived['result']['natal_aspects']),
                                len(projection['natal_aspects']))

    def test_qualifications_owner_replay_and_polar_partial(self):
        params = {'effective_utc': '2025-03-20T04:06:00+00:00'}
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'get_secondary_progression',
                    {'chart_id': self.chart['id'], **params}, set())
        selected = execute(self.store, self.alice, 'get_secondary_progression',
                           {'chart_id': self.chart['id'], **params}, {self.chart['id']})
        self.assertEqual(selected['status'], 'supported')
        saved = Advanced(self.store).save(self.alice, 'progressed-result', self.person_id,
                                          'secondary_progression', params)
        self.assertEqual(saved['mapped_ephemeris_utc'], selected['mapped_ephemeris_utc'])
        with self.assertRaises(KeyError):
            Advanced(self.store).get(self.bob, 'progressed-result')
        polar = self._chart('polar-progressed', '2024-03-20', '04:06', 89.95)
        partial = Progressions(self.store).calculate(self.alice, polar['id'],
            datetime.fromisoformat(params['effective_utc']))
        self.assertEqual(partial['status'], 'supported')
        self.assertEqual(partial['mc_status'], 'unsupported_polar_location')
        self.assertIsNone(partial['mcp_degrees'])
        self.assertTrue(partial['positions'])
        self.assertFalse(partial['mcr_contacts'])
        self.assertEqual(Advanced(self.store).get(self.alice, 'progressed-result')['source_status'], 'historical')
        self.assertTrue(Advanced(self.store).save(self.alice, 'progressed-result', self.person_id,
                                              'secondary_progression', params)['reused'])
        self.assertEqual(len(Advanced(self.store).list(self.alice, self.person_id,
                                                       'secondary_progression')), 1)
