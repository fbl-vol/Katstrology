"""Own-body Swiss return anchors, retrograde passes, reference-place invariance and archive."""

from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

from m2.calculation.advanced import Advanced
from m2.chat.agent_reads import execute
from m2.people.birth_flow import BirthFlow
from m2.chat.gateway import run_turn
from m2.people.people import People
from m2.people.places import selected as selected_place
from m2.calculation.planetary_returns import MAX_DAYS, PlanetaryReturns
from m2.provider.responses import ResponsesModel
from tests.chat.test_agent_reads import FakeBridge, ScriptedTransport
from tests.support.database import DatabaseCase
from m2.calculation.transits import _angle, _position_at

UTC = timezone.utc


class PlanetaryReturnTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.person = People(self.store).add(self.alice, 'Synthetic planetary reader')['id']
        self.chart = BirthFlow(self.store).generate(self.alice, self.person, {
            'request_id': 'planet-2024', 'birth_date': '2024-04-05', 'birth_time': '12:00',
            'time_unknown': False, 'birthplace': 'Synthetic London',
            'place_id': None, 'provisional': True, 'zone_override': 'UTC',
            'latitude_override': 51.5, 'longitude_override': -0.17,
            'fold': None, 'settings': None,
        })['chart']

    def test_venus_retrograde_three_passes_and_reference_place_independence(self):
        start, end = datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 6, 1, tzinfo=UTC)
        returns = PlanetaryReturns(self.store)
        first = returns.calculate(self.alice, self.chart['id'], 'venus', start, end, 51.5, -0.17)
        other = returns.calculate(self.alice, self.chart['id'], 'venus', start, end, -33.86, 151.21)
        self.assertEqual(first['status'], 'supported')
        self.assertEqual(len(first['events']), 3)
        self.assertEqual([item['pass_direction'] for item in first['events']],
                         ['direct', 'retrograde', 'direct'])
        self.assertEqual([item['instant_utc'] for item in first['events']],
                         [item['instant_utc'] for item in other['events']])
        self.assertNotEqual(first['events'][0]['chart']['houses']['angles'],
                            other['events'][0]['chart']['houses']['angles'])
        natal = next(point['longitude_degrees'] for point in self.chart['result']['natal']['positions']
                     if point['id'] == 'venus')
        for event in first['events']:
            instant = datetime.fromisoformat(event['instant_utc'])
            self.assertAlmostEqual(_angle(_position_at('venus', instant)[0] - natal),
                                   0, delta=.00003)
            self.assertLess(event['angular_residual_degrees'], .00003)
            before = _angle(_position_at('venus', instant - timedelta(days=1))[0] - natal)
            after = _angle(_position_at('venus', instant + timedelta(days=1))[0] - natal)
            self.assertLess(before * after, 0, 'independent day samples bracket the pass')
            self.assertEqual(before < after, event['pass_direction'] == 'direct')
            self.assertTrue(start <= instant < end)
            self.assertEqual(event['chart']['aspects_truncated'],
                             len(event['chart']['aspects']) < event['chart']['aspects_total'])

    def test_five_year_venus_passes_equal_adjacent_half_open_windows(self):
        start = datetime(2024, 4, 5, 12, tzinfo=UTC)
        midpoint = start + timedelta(days=915)
        end = start + timedelta(days=1830)
        finder = PlanetaryReturns(self.store)
        def passes(begin, finish):
            result = finder.calculate(self.alice, self.chart['id'], 'venus',
                                      begin, finish, 51.5, -0.17)
            self.assertEqual(result['status'], 'supported')
            return [(event['instant_utc'], event['pass_direction']) for event in result['events']]
        whole = passes(start, end)
        self.assertGreater(len(whole), 4)
        self.assertIn('retrograde', [direction for _, direction in whole])
        self.assertEqual(whole, passes(start, midpoint) + passes(midpoint, end))

    def test_all_named_bodies_and_exact_birth_boundary(self):
        born = datetime(2024, 4, 5, 12, tzinfo=UTC)
        finder = PlanetaryReturns(self.store)
        for body in MAX_DAYS:
            with self.subTest(body=body):
                result = finder.calculate(self.alice, self.chart['id'], body,
                    born, born + timedelta(days=1), 51.5, -0.17)
                self.assertEqual(result['status'], 'supported')
                self.assertEqual(result['events'][0]['instant_utc'], born.isoformat())
                self.assertEqual(result['events'][0]['angular_residual_degrees'], 0)
        for body, start, end in (
            ('mars', datetime(2025, 12, 1, tzinfo=UTC), datetime(2027, 12, 1, tzinfo=UTC)),
            ('jupiter', datetime(2035, 1, 1, tzinfo=UTC), datetime(2038, 1, 1, tzinfo=UTC)),
            ('saturn', datetime(2050, 1, 1, tzinfo=UTC), datetime(2057, 1, 1, tzinfo=UTC))):
            with self.subTest(later_body=body):
                later = finder.calculate(self.alice, self.chart['id'], body, start, end,
                                         51.5, -0.17)
                self.assertTrue(later['events'])
                for event in later['events']:
                    self.assertLess(event['angular_residual_degrees'], .00003)
        with self.assertRaisesRegex(ValueError, 'positive'):
            finder.calculate(self.alice, self.chart['id'], 'jupiter', born,
                             born + timedelta(days=MAX_DAYS['jupiter'] + 1), 51.5, -0.17)
        with self.assertRaises(ValueError):
            finder.calculate(self.alice, self.chart['id'], 'chiron', born,
                             born + timedelta(days=10), 51.5, -0.17)
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'get_planetary_returns', {
                'chart_id': self.chart['id'], 'body': 'venus',
                'start_utc': born.isoformat(),
                'end_utc': (born + timedelta(days=1)).isoformat(),
                'latitude': 51.5, 'longitude': -0.17}, set())

    def test_near_station_tangency_is_not_reported_as_a_complete_search(self):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        target = next(point['longitude_degrees'] for point in self.chart['result']['natal']['positions']
                      if point['id'] == 'venus')
        def near_tangent(_body, instant):
            days = (instant - start).total_seconds() / 86400 - .5
            return target + .00005 + .001 * days * days, .002 * days
        with patch('m2.calculation.planetary_returns._position_at', near_tangent):
            result = PlanetaryReturns(self.store).calculate(self.alice, self.chart['id'],
                'venus', start, start + timedelta(days=1), 51.5, -0.17)
        self.assertEqual(result['status'], 'partial_near_station_contact')
        self.assertNotIn('events', result)

    def test_selected_offline_reference_persists_for_planetary_return(self):
        city = selected_place('2618425')
        params = {'body': 'venus', 'start_utc': '2024-04-05T12:00:00+00:00',
                  'end_utc': '2024-04-06T12:00:00+00:00',
                  'latitude': city['latitude'], 'longitude': city['longitude'],
                  'reference_place_id': city['id']}
        saved = Advanced(self.store).save(self.alice, 'planet-city', self.person,
                                          'planetary_return', params)
        self.assertEqual(saved['status'], 'supported')
        self.assertEqual(saved['reference_place_source']['label'],
                         'Copenhagen, Capital Region, Denmark')
        self.assertEqual(Advanced(self.store).get(self.alice, 'planet-city')['result']['events'],
                         saved['events'])
        self.assertEqual(Advanced(self.store).save(self.alice, 'planet-city', self.person,
                        'planetary_return', params)['reference_place_source'],
                         saved['reference_place_source'])

    def test_saved_replay_and_model_projection_preserve_all_passes(self):
        params = {'body': 'venus', 'start_utc': '2025-01-01T00:00:00+00:00',
                  'end_utc': '2025-06-01T00:00:00+00:00',
                  'latitude': 51.5, 'longitude': -0.17}
        saved = Advanced(self.store).save(self.alice, 'venus-passes', self.person,
                                         'planetary_return', params)
        self.assertEqual(saved['status'], 'supported')
        self.assertTrue(Advanced(self.store).save(self.alice, 'venus-passes', self.person,
                        'planetary_return', params)['reused'])
        with self.assertRaises(KeyError):
            Advanced(self.store).get(self.bob, 'venus-passes')
        self.store.create_conversation(self.alice, 'return-conversation')
        call = {'type': 'function_call', 'id': 'fc_venus', 'call_id': 'call_venus',
                'name': 'get_planetary_returns', 'arguments': json.dumps({
                    'chart_id': self.chart['id'], **params})}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'Three passes.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        self.assertEqual(run_turn(self.store, self.alice, 'return-conversation', 'venus-turn',
            'Read Venus returns', model, lambda _: None,
            selected_people=[{'person_id': self.person, 'chart_id': self.chart['id']}],
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        projection = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual(projection['events_total'], 3)
        self.assertEqual([event['pass_direction'] for event in projection['events']],
                         ['direct', 'retrograde', 'direct'])
        archived = next(event['payload'] for event in self.store.read_turn(
            self.alice, 'return-conversation', 'venus-turn')['events']
            if event['kind'] == 'tool_result' and event['payload'].get('name') == 'get_planetary_returns')
        self.assertEqual(len(archived['result']['events']), 3)
        self.assertEqual(archived['result']['events'][1]['chart']['houses']['status'], 'supported')
