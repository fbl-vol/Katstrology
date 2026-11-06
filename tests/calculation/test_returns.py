"""Owned synthetic returns; independent equinox anchor and orbital/geometry invariants."""

from datetime import datetime, timedelta, timezone
import json

from m2.people.birth_flow import BirthFlow
from m2.calculation.advanced import Advanced
from m2.chat.agent_reads import execute
from m2.chat.gateway import run_turn
from m2.provider.responses import ResponsesModel
from tests.chat.test_agent_reads import FakeBridge, ScriptedTransport
from m2.people.people import People
from m2.people.places import selected as selected_place
from m2.calculation.returns import Returns
from tests.support.database import DatabaseCase

UTC = timezone.utc


class ReturnTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        person = People(self.store).add(self.alice, 'Synthetic return reader')
        self.chart = BirthFlow(self.store).generate(self.alice, person['id'], {
            'request_id': 'return-source', 'birth_date': '2024-03-20', 'birth_time': '04:06',
            'time_unknown': False, 'birthplace': 'Copenhagen, Capital Region, Denmark', 'place_id': '2618425',
            'provisional': True, 'zone_override': None, 'latitude_override': None,
            'longitude_override': None, 'fold': None, 'settings': None,
        })['chart']
        self.returns = Returns(self.store)

    def test_solar_equinox_year_and_relocated_houses_keep_geocentric_root(self):
        chart_id = self.chart['id']
        copenhagen = self.returns.calculate(self.alice, chart_id, 'solar_return', year=2025,
                                             latitude=55.68, longitude=12.57)
        sydney = self.returns.calculate(self.alice, chart_id, 'solar_return', year=2025,
                                        latitude=-33.87, longitude=151.21)
        self.assertEqual(copenhagen['status'], 'supported')
        self.assertEqual(len(copenhagen['events']), 1)
        event = copenhagen['events'][0]
        # Independently published USNO March 2025 equinox 09:01 UTC, minute precision.
        # https://aa.usno.navy.mil/calculated/seasons?year=2025&tz=0
        self.assertLess(abs(datetime.fromisoformat(event['instant_utc']) -
                            datetime(2025, 3, 20, 9, 1, tzinfo=UTC)), timedelta(minutes=8))
        self.assertEqual(event['instant_utc'], sydney['events'][0]['instant_utc'])
        self.assertNotEqual(event['chart']['houses']['angles'], sydney['events'][0]['chart']['houses']['angles'])
        self.assertLess(event['angular_residual_degrees'], .0002)
        self.assertEqual(copenhagen['ephemeris_sha256'], self.chart['result']['natal']['ephemeris_sha256'])

    def test_lunar_window_contains_multiple_crossings_without_month_assumption(self):
        start = datetime(2024, 3, 20, 2, 6, tzinfo=UTC)
        result = self.returns.calculate(self.alice, self.chart['id'], 'lunar_return',
            start=start, end=start + timedelta(days=56), latitude=55.68, longitude=12.57)
        self.assertEqual(result['status'], 'supported')
        self.assertEqual(len(result['events']), 3)
        first, second, third = [datetime.fromisoformat(item['instant_utc']) for item in result['events']]
        # Moon's sidereal revolution is about 27.3 days; phases are not this cycle.
        for distance in (second - first, third - second):
            self.assertGreater(distance.days, 26)
            self.assertLess(distance.days, 29)
        self.assertLess(abs(first - datetime.fromisoformat(
            self.chart['result']['natal_sun']['instant_utc'])), timedelta(seconds=1))

    def test_two_year_lunar_returns_include_every_crossing_and_chart(self):
        start = datetime.fromisoformat(self.chart['result']['natal_sun']['instant_utc'])
        result = self.returns.calculate(self.alice, self.chart['id'], 'lunar_return',
            start=start, end=start + timedelta(days=732), latitude=55.68, longitude=12.57)
        self.assertEqual(result['status'], 'supported')
        self.assertGreater(len(result['events']), 24)
        self.assertLessEqual(len(result['events']), 32)
        self.assertTrue(all(event['chart']['positions'] for event in result['events']))
        instants = [datetime.fromisoformat(item['instant_utc']) for item in result['events']]
        self.assertEqual(instants, sorted(instants))
        self.assertTrue(all(timedelta(days=26) < later - earlier < timedelta(days=29)
                            for earlier, later in zip(instants, instants[1:])))

    def test_exact_start_crossing_belongs_to_current_cycle(self):
        birth = datetime.fromisoformat(self.chart['result']['natal_sun']['instant_utc'])
        lunar = self.returns.calculate(self.alice, self.chart['id'], 'lunar_return',
            start=birth, end=birth + timedelta(days=1), latitude=55.68, longitude=12.57)
        solar = self.returns.calculate(self.alice, self.chart['id'], 'solar_return',
            year=2024, latitude=55.68, longitude=12.57)
        self.assertEqual(len(lunar['events']), 1)
        self.assertEqual(len(solar['events']), 1)
        self.assertLess(abs(datetime.fromisoformat(lunar['events'][0]['instant_utc']) - birth),
                        timedelta(seconds=1))
        self.assertLess(abs(datetime.fromisoformat(solar['events'][0]['instant_utc']) - birth),
                        timedelta(seconds=1))

    def test_persisted_return_replays_without_inference_and_tool_requires_selection(self):
        advanced = Advanced(self.store)
        parameters = {'year': 2025, 'latitude': 55.68, 'longitude': 12.57}
        result = advanced.save(self.alice, 'return-2025', self.chart['person_id'],
                               'solar_return', parameters)
        self.assertFalse(result['reused'])
        self.assertEqual(advanced.save(self.alice, 'return-2025', self.chart['person_id'],
            'solar_return', parameters)['events'], result['events'])
        self.assertEqual(advanced.get(self.alice, 'return-2025')['result']['events'], result['events'])
        with self.assertRaises(KeyError):
            advanced.get(self.bob, 'return-2025')
        args = {'chart_id': self.chart['id'], **parameters}
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'get_solar_return', args, set())
        self.assertEqual(execute(self.store, self.alice, 'get_solar_return', args,
            {self.chart['id']})['events'], result['events'])
        with self.assertRaisesRegex(ValueError, 'another request'):
            advanced.save(self.alice, 'return-2025', self.chart['person_id'],
                          'solar_return', {**parameters, 'year': 2026})
        BirthFlow(self.store).generate(self.alice, self.chart['person_id'], {
            'request_id': 'replacement-source', 'birth_date': '2024-03-21', 'birth_time': '04:06',
            'time_unknown': False, 'birthplace': 'Copenhagen, Capital Region, Denmark',
            'place_id': '2618425', 'provisional': True, 'zone_override': None,
            'latitude_override': None, 'longitude_override': None, 'fold': None, 'settings': None,
        })
        archived = advanced.get(self.alice, 'return-2025')
        self.assertEqual(archived['source_status'], 'historical')
        self.assertEqual(archived['result']['events'][0]['instant_utc'], result['events'][0]['instant_utc'])
        replay = advanced.save(self.alice, 'return-2025', self.chart['person_id'],
                               'solar_return', parameters)
        self.assertTrue(replay['reused'])
        self.assertEqual(replay['source_status'], 'historical')
        self.assertEqual(replay['events'][0]['instant_utc'], result['events'][0]['instant_utc'])
        listed = advanced.list(self.alice, self.chart['person_id'], 'solar_return')
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['window_utc'], result['window_utc'])
        self.assertEqual(listed[0]['event_count'], len(result['events']))
        self.assertEqual(listed[0]['reference_place'], result['reference_place'])
        self.assertEqual(listed[0]['reference_place_source'], result['reference_place_source'])
        with self.assertRaises(KeyError):
            advanced.list(self.bob, self.chart['person_id'], 'solar_return')

    def test_reference_city_id_matches_catalog_and_replays_without_changing_root(self):
        advanced = Advanced(self.store)
        place = selected_place('2618425')
        coordinates = {'latitude': place['latitude'], 'longitude': place['longitude']}
        birth = self.chart['result']['birth']
        self.assertEqual((birth['latitude'], birth['longitude']),
                         (place['latitude'], place['longitude']))
        saved = advanced.save(self.alice, 'saved-birth-coordinates', self.chart['person_id'],
            'solar_return', {'year': 2025, **coordinates})
        city = advanced.save(self.alice, 'selected-city', self.chart['person_id'],
            'solar_return', {'year': 2025, **coordinates, 'reference_place_id': place['id']})
        self.assertEqual(saved['events'], city['events'])
        self.assertEqual(saved['reference_place_source']['kind'], 'saved_birthplace_coordinates')
        self.assertEqual(city['reference_place_source'], {
            'kind': 'offline_city_centre', 'label': 'Copenhagen, Capital Region, Denmark',
            'place_id': place['id']})
        self.assertEqual(advanced.get(self.alice, 'selected-city')['result']['reference_place_source'],
                         city['reference_place_source'])
        history = {entry['id']: entry for entry in
                   advanced.list(self.alice, self.chart['person_id'], 'solar_return')}
        self.assertEqual(history['selected-city']['reference_place_source'], city['reference_place_source'])
        self.assertEqual(history['saved-birth-coordinates']['reference_place_source'],
                         saved['reference_place_source'])
        with self.assertRaisesRegex(ValueError, 'Selected city coordinates'):
            advanced.save(self.alice, 'false-city', self.chart['person_id'],
                'solar_return', {'year': 2025, 'latitude': 0, 'longitude': 0,
                                 'reference_place_id': place['id']})
        with self.assertRaises(KeyError):
            advanced.get(self.alice, 'false-city')
        with self.assertRaises(KeyError):
            advanced.get(self.bob, 'selected-city')

    def test_model_requested_return_is_archived_and_not_truncated_by_projection(self):
        self.store.create_conversation(self.alice, 'return-discussion')
        call = {'type': 'function_call', 'id': 'fc_return', 'call_id': 'call_return',
                'name': 'get_solar_return', 'arguments': json.dumps({
                    'chart_id': self.chart['id'], 'year': 2025,
                    'latitude': 55.68, 'longitude': 12.57})}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'Synthetic return answer.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        result = run_turn(self.store, self.alice, 'return-discussion', 'return-request',
            'Read the selected solar return', model, lambda _: None,
            selected_people=[{'person_id': self.chart['person_id'], 'chart_id': self.chart['id']}],
            model_provider='chatgpt_plan', model_slug='synthetic-response-model')
        self.assertEqual(result, 'complete')
        projected = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual(projected['technique'], 'solar_return')
        self.assertTrue(projected['events'][0]['positions'])
        archived = next(event['payload'] for event in self.store.read_turn(
            self.alice, 'return-discussion', 'return-request')['events']
            if event['kind'] == 'tool_result' and event['payload'].get('name') == 'get_solar_return')
        self.assertIn('events', archived['result'], str(archived['result']))
        self.assertEqual(archived['result']['events'][0]['chart']['positions'][0]['id'], 'sun')
        self.assertEqual(archived['model_projection_status'], 'bounded')

    def test_owner_uncertainty_and_interval_bounds(self):
        with self.assertRaises(KeyError):
            self.returns.calculate(self.bob, self.chart['id'], 'solar_return',
                                   year=2025, latitude=55, longitude=12)
        with self.assertRaisesRegex(ValueError, '732 days'):
            self.returns.calculate(self.alice, self.chart['id'], 'lunar_return',
                start=datetime(2025, 1, 1, tzinfo=UTC), end=datetime(2027, 1, 4, tzinfo=UTC),
                latitude=55, longitude=12)
        with self.assertRaisesRegex(ValueError, 'reference latitude'):
            self.returns.calculate(self.alice, self.chart['id'], 'solar_return', year=2025)
