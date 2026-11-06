"""Trusted per-turn time and full conversational transit chart regression paths."""

from datetime import datetime, timezone
import json

from m2.chat.agent_reads import execute
from m2.chat.gateway import run_turn
from m2.people.people import People
from tests.chat.test_agent_reads import ScriptedTransport, FakeBridge
from m2.provider.responses import ResponsesModel
from tests.chat.test_gateway import TinySource
from tests.support.database import DatabaseCase
from m2.chat.tool_evidence import MAX_MODEL_RESULT_BYTES
from m2.calculation.transit_views import view


class ClockAndChartParityTests(DatabaseCase):
    def test_turn_uses_frozen_trusted_clock_not_stale_summary_or_changed_retry_time(self):
        self.store.create_conversation(self.alice, 'clock-thread')
        old_model = TinySource()
        run_turn(self.store, self.alice, 'clock-thread', 'older',
                 'In an earlier discussion it was 2021-04-05.', old_model,
                 lambda _: None, clock=lambda: datetime(2021, 4, 5, tzinfo=timezone.utc))
        model = TinySource()
        clock = lambda: datetime(2026, 1, 1, 1, 15, 42, tzinfo=timezone.utc)
        status = run_turn(self.store, self.alice, 'clock-thread', 'now',
                          'Today, not the earlier conversation date in 2021', model,
                          lambda _: None, parent_id='older', clock=clock,
                          reporting_zone='America/Los_Angeles')
        self.assertEqual(status, 'complete')
        events = self.store.read_turn(self.alice, 'clock-thread', 'now')['events']
        anchor = events[0]['payload']['clock_anchor']
        self.assertEqual(anchor['instant_utc'], '2026-01-01T01:15:42+00:00')
        self.assertEqual(anchor['reporting']['date'], '2025-12-31')
        self.assertEqual(anchor['reporting']['zone'], 'America/Los_Angeles')
        self.assertIn('2021-04-05', model.prompts[0])
        self.assertIn('2025-12-31', model.prompts[0])
        self.assertIn('2026-01-01T01:15:42+00:00', model.prompts[0])
        self.assertEqual(run_turn(self.store, self.alice, 'clock-thread', 'now',
            'Today, not the earlier conversation date in 2021', model, lambda _: None,
            clock=lambda: (_ for _ in ()).throw(AssertionError('Replay must not re-read clock')),
            parent_id='older', reporting_zone='America/Los_Angeles'), 'complete')
        with self.assertRaisesRegex(ValueError, 'changed input'):
            run_turn(self.store, self.alice, 'clock-thread', 'now',
                     'Today, not the earlier conversation date in 2021', model,
                     lambda _: None, parent_id='older', reporting_zone='UTC')
        self.assertEqual(self.store.read_turn(self.alice, 'clock-thread', 'now')['events'][0]['payload']['clock_anchor'], anchor)

    def test_model_full_view_equals_manual_result_and_commits_before_continuation(self):
        people = People(self.store)
        people.charts.add_person(self.alice, 'chart-person', 'Synthetic person')
        birth = people.add_birth(self.alice, 'chart-person', {
            'mode': 'exact', 'zone': 'UTC', 'wall_time': '2001-06-21T04:00:00',
            'latitude': 51.5, 'longitude': -0.17})
        chart = people.create_chart(self.alice, 'chart-person', birth, 'natal-default', 1)
        args = {'date': '2024-03-20', 'time': '03:06', 'zone': 'UTC',
                'occurrence': 'unspecified', 'mode': 'natal_transits', 'chart_id': chart['id']}
        expected = view(self.store, self.alice, '2024-03-20', '03:06', 'UTC',
                        'unspecified', 'natal_transits', chart['id'])
        self.assertEqual(execute(self.store, self.alice, 'get_transit_view', args,
                                 {chart['id']}), expected)
        self.store.create_conversation(self.alice, 'thread')
        call = {'type': 'function_call', 'id': 'fc_view', 'call_id': 'call_view',
                'name': 'get_transit_view', 'arguments': json.dumps(args)}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'A calculated chart is available; degrees are the source.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        real_events = transport.response_events
        def check_archive(token, body):
            if len(transport.calls) == 2:
                events = self.store.read_turn(self.alice, 'thread', 'turn')['events']
                result = next(row['payload'] for row in events if row['kind'] == 'tool_result'
                              and row['payload'].get('name') == 'get_transit_view')
                self.assertEqual(result['result'], expected)
            yield from real_events(token, body)
        transport.response_events = check_archive
        self.assertEqual(run_turn(self.store, self.alice, 'thread', 'turn',
            'Please calculate a full transit chart for this historical instant', model,
            lambda _: None, model_provider='chatgpt_plan', model_slug='synthetic-response-model',
            selected_people=[{'person_id': 'chart-person', 'chart_id': chart['id']}]), 'complete')
        self.assertEqual(len(transport.calls), 2)
        sent = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual(sent['chart_id'], chart['id'])
        self.assertEqual(sent['same_sky_total'], expected['same_sky_total'])
        self.assertLessEqual(len(transport.calls[1]['input'][-1]['output'].encode()),
                             MAX_MODEL_RESULT_BYTES)
        self.assertEqual(sent['source_status'], expected['source_status'])
        self.assertEqual([point['id'] for point in sent['positions']],
                         [point['id'] for point in expected['positions']])
        self.assertEqual([point['id'] for point in sent['natal_positions']],
                         [point['id'] for point in expected['natal_positions']])
        self.assertEqual(sent['same_sky_shown'], len(expected['same_sky_aspects']))
        self.assertEqual(sent['transit_to_natal_shown'],
                         len(expected['transit_to_natal_aspects']))
        archived = self.store.read_turn(self.alice, 'thread', 'turn')['events']
        self.assertEqual(next(item['payload']['result'] for item in archived
                              if item['kind'] == 'tool_result' and
                              item['payload'].get('name') == 'get_transit_view'), expected)
        self.assertEqual(self.store.db.execute('''
            SELECT count(*) AS n FROM chart_evidence
            WHERE owner_id='alice' AND conversation_id='thread' AND turn_id='turn'
            AND chart_id=%s
        ''', (chart['id'],)).fetchone()['n'], 2)  # selected natal + requested full view

    def test_sky_only_and_negative_chart_access_never_cross_the_selection_fence(self):
        sky_args = {'date': '2024-11-03', 'time': '01:30:29',
                    'zone': 'America/New_York', 'occurrence': 'later',
                    'mode': 'sky', 'chart_id': None}
        sky = execute(self.store, self.alice, 'get_transit_view', sky_args, set())
        self.assertEqual(sky, view(self.store, self.alice, '2024-11-03', '01:30:29',
                                   'America/New_York', 'later', 'sky'))
        self.assertEqual(sky['natal_positions'], [])
        for invalid in ({**sky_args, 'occurrence': 'unspecified'},
                        {**sky_args, 'time': '02:30:29', 'date': '2024-03-10'},
                        {**sky_args, 'mode': 'natal_transits', 'chart_id': 'unselected'},
                        {**sky_args, 'chart_id': 'unselected'},
                        {**sky_args, 'extra': 'unauthorized'}):
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, PermissionError)):
                execute(self.store, self.alice, 'get_transit_view', invalid, set())
        person = People(self.store)
        person.charts.add_person(self.bob, 'private-person', 'Private')
        birth = person.add_birth(self.bob, 'private-person', {
            'mode': 'exact', 'zone': 'UTC', 'wall_time': '2001-06-21T04:00:00'})
        private = person.create_chart(self.bob, 'private-person', birth, 'natal-default', 1)
        with self.assertRaises(KeyError):
            execute(self.store, self.alice, 'get_transit_view', {
                **sky_args, 'mode': 'natal_transits', 'chart_id': private['id']},
                {private['id']})
