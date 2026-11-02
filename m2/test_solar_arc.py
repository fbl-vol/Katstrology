"""Independent solar displacement anchors, source eligibility and archived directions."""

from datetime import datetime, timezone
import json
import unittest

from m2.advanced import Advanced
from m2.agent_reads import execute
from m2.birth_flow import BirthFlow
from m2.gateway import run_turn
from m2.people import People
from m2.provider_model import ResponsesModel
from m2.solar_arc import SolarArc
from m2.test_agent_reads import FakeBridge, ScriptedTransport
from m2.test_support import DatabaseCase
from m2.transits import _position_at
from m2.progressions import calendar_map

UTC = timezone.utc


class SolarArcTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.person = People(self.store).add(self.alice, 'Synthetic arc reader')['id']
        self.chart = self.chart_at('2000-06-09', '13:00', 'arc-reader')

    def chart_at(self, day, hour, request):
        return BirthFlow(self.store).generate(self.alice, self.person, {
            'request_id': request, 'birth_date': day, 'birth_time': hour,
            'time_unknown': not bool(hour), 'birthplace': 'Synthetic arc location',
            'place_id': None, 'provisional': True, 'zone_override': 'UTC',
            'latitude_override': 51.5, 'longitude_override': -0.17,
            'fold': None, 'settings': None,
        })['chart']

    def test_zero_age_and_17_year_true_arc_from_direct_sun_sample(self):
        arc = SolarArc(self.store)
        birth = datetime(2000, 6, 9, 13, tzinfo=UTC)
        zero = arc.calculate(self.alice, self.chart['id'], birth)
        self.assertEqual(zero['arc_degrees'], 0)
        for point in zero['positions']:
            self.assertEqual(point['longitude_degrees'], point['source_longitude_degrees'])
        effective = datetime(2017, 8, 12, 10, 20, tzinfo=UTC)
        result = arc.calculate(self.alice, self.chart['id'], effective)
        mapped = calendar_map(birth, effective)[-1]
        progressed_sun = _position_at('sun', mapped)[0]
        natal_sun = next(point['longitude_degrees'] for point in self.chart['result']['natal']['positions']
                         if point['id'] == 'sun')
        self.assertAlmostEqual(result['progressed_sun_degrees'], progressed_sun)
        self.assertAlmostEqual(result['arc_degrees'], (progressed_sun - natal_sun) % 360)
        self.assertNotAlmostEqual(result['arc_degrees'], 17, places=3)
        self.assertEqual(result['axis_status'], 'supported')
        self.assertTrue({'ascendant', 'midheaven'} <= {point['id'] for point in result['positions']})
        for point in result['positions']:
            self.assertAlmostEqual(point['longitude_degrees'],
                (point['source_longitude_degrees'] + result['arc_degrees']) % 360)
            self.assertNotIn('retrograde', point)
            self.assertNotIn('speed_degrees_per_day', point)
        self.assertEqual(result['physical_sky'], 'not_defined')

    def test_long_forward_arc_and_polar_axes_never_invented(self):
        early = self.chart_at('1900-02-01', '04:00', 'early-arc')
        result = SolarArc(self.store).calculate(self.alice, early['id'],
                                                datetime(2098, 6, 1, tzinfo=UTC))
        self.assertGreater(result['arc_degrees'], 180)
        self.assertLess(result['arc_degrees'], 360)
        polar = BirthFlow(self.store).generate(self.alice, self.person, {
            'request_id': 'polar-arc', 'birth_date': '2000-06-09', 'birth_time': '13:00',
            'time_unknown': False, 'birthplace': 'Synthetic polar arc',
            'place_id': None, 'provisional': True, 'zone_override': 'UTC',
            'latitude_override': 89.95, 'longitude_override': 10,
            'fold': None, 'settings': None,
        })['chart']
        partial = SolarArc(self.store).calculate(self.alice, polar['id'],
                                                 datetime(2017, 6, 9, 13, tzinfo=UTC))
        self.assertEqual(partial['status'], 'supported')
        self.assertEqual(partial['axis_status'], 'unsupported_polar_location')
        self.assertFalse({'ascendant', 'midheaven'} & {item['id'] for item in partial['positions']})

    def test_owner_replay_and_model_projection(self):
        params = {'effective_utc': '2017-08-12T10:20:00+00:00'}
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'get_true_solar_arc',
                    {'chart_id': self.chart['id'], **params}, set())
        saved = Advanced(self.store).save(self.alice, 'arc-saved', self.person,
                                          'true_solar_arc', params)
        self.assertEqual(saved['status'], 'supported')
        with self.assertRaises(KeyError):
            Advanced(self.store).get(self.bob, 'arc-saved')
        self.assertTrue(Advanced(self.store).save(self.alice, 'arc-saved', self.person,
                       'true_solar_arc', params)['reused'])
        self.store.create_conversation(self.alice, 'arc-conversation')
        call = {'type': 'function_call', 'id': 'fc_arc', 'call_id': 'call_arc',
                'name': 'get_true_solar_arc', 'arguments': json.dumps({
                    'chart_id': self.chart['id'], **params})}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'A symbolic direction.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        self.assertEqual(run_turn(self.store, self.alice, 'arc-conversation', 'arc-turn',
            'Read solar arc', model, lambda _: None,
            selected_people=[{'person_id': self.person, 'chart_id': self.chart['id']}],
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        projected = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual(projected['method_version'], 'true-progressed-sun-forward-solar-arc-v1')
        self.assertEqual(len(projected['directed_natal_aspects']), projected['directed_natal_aspects_total'])
        self.assertIn('mapped_ephemeris_utc', projected)
        archived = next(event['payload'] for event in self.store.read_turn(
            self.alice, 'arc-conversation', 'arc-turn')['events']
            if event['kind'] == 'tool_result' and event['payload'].get('name') == 'get_true_solar_arc')
        self.assertEqual(archived['result']['arc_degrees'], projected['arc_degrees'])
        self.assertGreaterEqual(len(archived['result']['directed_natal_aspects']),
                                len(projected['directed_natal_aspects']))
