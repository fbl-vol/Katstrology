"""Secondary phase cycle search: actual Swiss mapped geometry, brackets and replay."""

from datetime import datetime, timedelta, timezone
import json

from m2.advanced import Advanced
from m2.agent_reads import execute
from m2.birth_flow import BirthFlow
from m2.gateway import run_turn
from m2.people import People
from m2.progressed_phases import PHASES, ProgressedPhases
from m2.progressions import calendar_map
from m2.provider_model import ResponsesModel
from m2.test_agent_reads import FakeBridge, ScriptedTransport
from m2.test_support import DatabaseCase
from m2.transits import _angle, _position_at

UTC = timezone.utc


class ProgressedPhaseTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.person = People(self.store).add(self.alice, 'Synthetic phase reader')['id']
        self.chart = BirthFlow(self.store).generate(self.alice, self.person, {
            'request_id': 'phase-natal', 'birth_date': '2001-06-21', 'birth_time': '04:00',
            'time_unknown': False, 'birthplace': 'Synthetic phase city',
            'place_id': None, 'provisional': True, 'zone_override': 'UTC',
            'latitude_override': 51.5, 'longitude_override': -0.17,
            'fold': None, 'settings': None,
        })['chart']

    def test_four_symbolic_phases_are_dated_by_effective_not_mapped_time(self):
        start, end = datetime(2001, 6, 21, 4, tzinfo=UTC), datetime(2037, 6, 21, 4, tzinfo=UTC)
        result = ProgressedPhases(self.store).calculate(self.alice, self.chart['id'], start, end)
        self.assertEqual(result['status'], 'supported')
        events = result['events']
        self.assertTrue(PHASES.keys() <= {event['phase'] for event in events})
        self.assertEqual(events, sorted(events, key=lambda item: item['effective_utc']))
        self.assertTrue(any(event['cycle_index'] > 0 for event in events))
        for event in events:
            with self.subTest(event=event['phase']):
                when = datetime.fromisoformat(event['effective_utc'])
                mapped = calendar_map(start, when)[-1]
                self.assertEqual(event['mapped_ephemeris_utc'], mapped.isoformat())
                self.assertNotEqual(when, mapped)
                sun, moon = _position_at('sun', mapped)[0], _position_at('moon', mapped)[0]
                self.assertAlmostEqual(event['progressed_sun_degrees'], sun % 360)
                self.assertAlmostEqual(event['progressed_moon_degrees'], moon % 360)
                self.assertAlmostEqual(abs(_angle((moon - sun) % 360 - PHASES[event['phase']])),
                                       0, delta=.001)
                self.assertLess(event['angular_residual_degrees'], .001)
                self.assertTrue(start <= when < end)
        first = datetime.fromisoformat(events[0]['effective_utc'])
        around = ProgressedPhases(self.store).calculate(self.alice, self.chart['id'],
                                                        first - timedelta(days=2),
                                                        first + timedelta(days=2))
        self.assertEqual(len(around['events']), 1)
        self.assertEqual(around['events'][0]['phase'], events[0]['phase'])

    def test_invalid_windows_permissions_replay_and_model_read(self):
        start, end = '2024-01-01T00:00:00+00:00', '2028-01-01T00:00:00+00:00'
        params = {'start_utc': start, 'end_utc': end}
        with self.assertRaises(ValueError):
            ProgressedPhases(self.store).calculate(self.alice, self.chart['id'],
                datetime(2024, 1, 1, tzinfo=UTC), datetime(2066, 1, 1, tzinfo=UTC))
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'find_progressed_lunar_phases',
                    {'chart_id': self.chart['id'], **params}, set())
        saved = Advanced(self.store).save(self.alice, 'phase-saved', self.person,
                                          'progressed_lunar_phases', params)
        self.assertEqual(saved['status'], 'supported')
        self.assertTrue(Advanced(self.store).save(self.alice, 'phase-saved', self.person,
                        'progressed_lunar_phases', params)['reused'])
        with self.assertRaises(KeyError):
            Advanced(self.store).get(self.bob, 'phase-saved')
        self.store.create_conversation(self.alice, 'phase-conversation')
        call = {'type': 'function_call', 'id': 'fc_phase', 'call_id': 'call_phase',
                'name': 'find_progressed_lunar_phases', 'arguments': json.dumps({
                    'chart_id': self.chart['id'], **params})}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'A symbolic cycle.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        self.assertEqual(run_turn(self.store, self.alice, 'phase-conversation', 'phase-turn',
            'Read phase dates', model, lambda _: None,
            selected_people=[{'person_id': self.person, 'chart_id': self.chart['id']}],
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        projection = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual(projection['method_version'], 'progressed-moon-sun-four-phase-utc-v1')
        self.assertEqual(projection['progression_method_version'],
                         'secondary-utc-calendar-naibod-mc-v1')
        archived = next(event['payload'] for event in self.store.read_turn(
            self.alice, 'phase-conversation', 'phase-turn')['events']
            if event['kind'] == 'tool_result' and event['payload'].get('name') == 'find_progressed_lunar_phases')
        self.assertEqual(archived['result']['events'], projection['events'])
