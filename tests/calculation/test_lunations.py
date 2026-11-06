"""Global Swiss eclipse flags versus independent NASA UTC minute anchors and syzygies."""

from datetime import datetime, timedelta, timezone
import json

from m2.calculation.advanced import Advanced
from m2.chat.agent_reads import execute
from m2.people.birth_flow import BirthFlow
from m2.chat.gateway import run_turn
from m2.calculation.lunations import Lunations
from m2.people.people import People
from m2.provider.responses import ResponsesModel
from tests.chat.test_agent_reads import FakeBridge, ScriptedTransport
from tests.support.database import DatabaseCase
from m2.calculation.transits import _position_at

UTC = timezone.utc


class LunationTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.person = People(self.store).add(self.alice, 'Synthetic eclipse reader')['id']
        self.chart = BirthFlow(self.store).generate(self.alice, self.person, {
            'request_id': 'eclipse-natal', 'birth_date': '2001-06-21', 'birth_time': '04:00',
            'time_unknown': False, 'birthplace': 'Synthetic London',
            'place_id': None, 'provisional': True, 'zone_override': 'UTC',
            'latitude_override': 51.5, 'longitude_override': -0.17,
            'fold': None, 'settings': None,
        })['chart']

    def test_nasa_global_eclipses_distinct_from_actual_syzygies_and_local_visibility(self):
        start, end = datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 5, 1, tzinfo=UTC)
        result = Lunations(self.store).calculate(self.alice, self.chart['id'], start, end,
                                                  'sun', 'conjunction')
        self.assertEqual(result['status'], 'supported')
        self.assertGreaterEqual(len(result['lunations']), 4)
        solar = next(item for item in result['eclipses'] if item['family'] == 'solar')
        lunar = next(item for item in result['eclipses'] if item['family'] == 'lunar')
        self.assertEqual(solar['eclipse_type'], 'total')
        self.assertEqual(lunar['eclipse_type'], 'penumbral')
        # NASA OH2024 catalog gives Apr 8 18:17 UT (solar) and Mar 25 07:13 UT
        # (penumbral lunar); minute-level independent source, not exact Swiss equivalence.
        self.assertLess(abs(datetime.fromisoformat(solar['maximum_utc']) -
            datetime(2024, 4, 8, 18, 17, tzinfo=UTC)), timedelta(minutes=10))
        self.assertLess(abs(datetime.fromisoformat(lunar['maximum_utc']) -
            datetime(2024, 3, 25, 7, 13, tzinfo=UTC)), timedelta(minutes=10))
        for event in result['eclipses']:
            self.assertEqual(event['visibility'], 'global_only_not_calculated_for_location')
            self.assertNotEqual(event['linked_syzygy_utc'], event['maximum_utc'])
            match = next(item for item in result['lunations']
                         if item['instant_utc'] == event['linked_syzygy_utc'])
            self.assertEqual(match['phase'], 'new' if event['family'] == 'solar' else 'full')
            maximum = datetime.fromisoformat(event['maximum_utc'])
            self.assertAlmostEqual(event['sun_degrees_at_maximum'], _position_at('sun', maximum)[0] % 360)
            self.assertAlmostEqual(event['moon_degrees_at_maximum'], _position_at('moon', maximum)[0] % 360)
            self.assertEqual(len(event['contacts_at_maximum']), 2)
        for phase in result['lunations']:
            self.assertLess(phase['angular_residual_degrees'], .01)
            self.assertEqual(len(phase['contacts']), 2)
            self.assertTrue(start <= datetime.fromisoformat(phase['instant_utc']) < end)
        self.assertNotEqual(result['technique'], 'progressed_lunar_phases')

    def test_two_year_sky_window_preserves_multiple_global_eclipses_and_syzygies(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=732)
        result = Lunations(self.store).calculate(self.alice, self.chart['id'], start, end,
                                                  'sun', 'conjunction')
        self.assertEqual(result['status'], 'supported')
        self.assertGreater(len(result['lunations']), 40)
        self.assertGreaterEqual(len(result['eclipses']), 6)
        self.assertTrue(all(row['linked_syzygy_utc'] in
                            {event['instant_utc'] for event in result['lunations']}
                            for row in result['eclipses']))

    def test_partial_lunar_september_event_and_half_open_search(self):
        start = datetime(2024, 9, 1, tzinfo=UTC)
        end = datetime(2024, 10, 15, tzinfo=UTC)
        found = Lunations(self.store).calculate(self.alice, self.chart['id'], start, end,
                                                  'midheaven', 'square')
        lunar = next(item for item in found['eclipses'] if item['family'] == 'lunar')
        self.assertEqual(lunar['eclipse_type'], 'partial')
        self.assertLess(abs(datetime.fromisoformat(lunar['maximum_utc']) -
            datetime(2024, 9, 18, 2, 44, tzinfo=UTC)), timedelta(minutes=10))
        self.assertTrue(all(item['natal_target'] == 'midheaven'
                            for event in found['lunations'] for item in event['contacts']))
        with self.assertRaises(ValueError):
            Lunations(self.store).calculate(self.alice, self.chart['id'],
                                             start, start + timedelta(days=733), 'sun', 'conjunction')
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'find_actual_lunations_eclipses',
                {'chart_id': self.chart['id'], 'start_utc': start.isoformat(),
                 'end_utc': end.isoformat(), 'natal_target': 'sun', 'aspect': 'conjunction'}, set())

    def test_global_maximum_half_open_boundary_and_unavailable_polar_angle(self):
        full = Lunations(self.store).calculate(self.alice, self.chart['id'],
            datetime(2024, 4, 1, tzinfo=UTC), datetime(2024, 4, 20, tzinfo=UTC),
            'sun', 'conjunction')
        maximum = datetime.fromisoformat(full['eclipses'][0]['maximum_utc'])
        earlier = Lunations(self.store).calculate(self.alice, self.chart['id'],
            maximum - timedelta(days=1), maximum, 'sun', 'conjunction')
        later = Lunations(self.store).calculate(self.alice, self.chart['id'],
            maximum, maximum + timedelta(days=1), 'sun', 'conjunction')
        self.assertFalse(earlier['eclipses'])
        self.assertEqual(len(later['eclipses']), 1)
        polar = BirthFlow(self.store).generate(self.alice, self.person, {
            'request_id': 'polar-eclipse', 'birth_date': '2001-06-21', 'birth_time': '04:00',
            'time_unknown': False, 'birthplace': 'Synthetic pole',
            'place_id': None, 'provisional': True, 'zone_override': 'UTC',
            'latitude_override': 89.95, 'longitude_override': 10,
            'fold': None, 'settings': None,
        })['chart']
        self.assertEqual(Lunations(self.store).calculate(self.alice, polar['id'],
            datetime(2024, 4, 1, tzinfo=UTC), datetime(2024, 4, 20, tzinfo=UTC),
            'midheaven', 'conjunction')['status'], 'unsupported_natal_angle')

    def test_archive_and_model_keep_explicit_maximum_not_merged_with_syzygy(self):
        params = {'start_utc': '2024-03-01T00:00:00+00:00',
                  'end_utc': '2024-05-01T00:00:00+00:00',
                  'natal_target': 'sun', 'aspect': 'conjunction'}
        saved = Advanced(self.store).save(self.alice, 'sky-2024', self.person,
                                         'actual_lunations_eclipses', params)
        self.assertEqual(saved['status'], 'supported')
        self.assertTrue(Advanced(self.store).save(self.alice, 'sky-2024', self.person,
                        'actual_lunations_eclipses', params)['reused'])
        with self.assertRaises(KeyError):
            Advanced(self.store).get(self.bob, 'sky-2024')
        self.store.create_conversation(self.alice, 'sky-conversation')
        call = {'type': 'function_call', 'id': 'fc_eclipse', 'call_id': 'call_eclipse',
                'name': 'find_actual_lunations_eclipses', 'arguments': json.dumps({
                    'chart_id': self.chart['id'], **params})}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'Global, not local.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        self.assertEqual(run_turn(self.store, self.alice, 'sky-conversation', 'sky-turn',
            'Read eclipse dates', model, lambda _: None,
            selected_people=[{'person_id': self.person, 'chart_id': self.chart['id']}],
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        projection = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual(projection['eclipse_policy'], saved['eclipse_policy'])
        self.assertNotEqual(projection['eclipses'][0]['maximum_utc'],
                            projection['eclipses'][0]['linked_syzygy_utc'])
        archived = next(event['payload'] for event in self.store.read_turn(
            self.alice, 'sky-conversation', 'sky-turn')['events']
            if event['kind'] == 'tool_result' and event['payload'].get('name') == 'find_actual_lunations_eclipses')
        self.assertEqual(archived['result']['eclipses'], projection['eclipses'])
