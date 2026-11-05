"""Circular midpoint and arithmetic Davison anchors with two-source archive fences."""

import json
from unittest import TestCase

from m2.advanced import Advanced
from m2.agent_reads import execute
from m2.birth_flow import BirthFlow
from m2.gateway import run_turn
from m2.provider_model import ResponsesModel
from m2.test_agent_reads import FakeBridge, ScriptedTransport
from m2.people import DEFAULT_NATAL_SETTINGS, People
from m2.relationships import Relationships, circular_midpoint
from m2.test_support import DatabaseCase
from m2.tool_evidence import prepare
from m2.core_calc import aspect_separation


class CircleMidpointTests(TestCase):
    def test_wrap_coincidence_antipodes_and_exchange(self):
        self.assertEqual(circular_midpoint(350, 10), 0)
        self.assertEqual(circular_midpoint(10, 350), 0)
        self.assertEqual(circular_midpoint(42, 42), 42)
        self.assertIsNone(circular_midpoint(0, 180))
        self.assertIsNone(circular_midpoint(180, 0))
        self.assertAlmostEqual(circular_midpoint(25, 200), circular_midpoint(200, 25))


class RelationshipArchiveTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        people = People(self.store)
        self.a_id = people.add(self.alice, 'Derived A')['id']
        self.b_id = people.add(self.alice, 'Derived B')['id']
        self.first = self.chart(self.a_id, 'derived-a', '2000-01-01', '00:00', 12, 179)
        self.second = self.chart(self.b_id, 'derived-b', '2000-01-03', '00:00', -10, -179)

    def chart(self, person, request, day, hour, latitude, longitude, settings=None):
        return BirthFlow(self.store).generate(self.alice, person, {
            'request_id': request, 'birth_date': day, 'birth_time': hour,
            'time_unknown': not bool(hour), 'birthplace': 'Synthetic derived location',
            'place_id': None, 'provisional': True, 'zone_override': 'UTC',
            'latitude_override': latitude, 'longitude_override': longitude,
            'fold': None, 'settings': settings,
        })['chart']

    def test_composite_has_no_invented_instant_houses_and_is_swap_invariant(self):
        relationships = Relationships(self.store)
        a, b = self.first['id'], self.second['id']
        first = relationships.calculate(self.alice, a, b, 'midpoint_composite')
        reverse = relationships.calculate(self.alice, b, a, 'midpoint_composite')
        self.assertEqual(first['status'], 'supported')
        self.assertEqual(first['houses'], 'not_defined')
        self.assertIsNone(first['physical_instant'])
        self.assertEqual(first['angles'], 'not_defined')
        self.assertEqual([point['longitude_degrees'] for point in first['positions']],
                         [point['longitude_degrees'] for point in reverse['positions']])
        positions_a = {item['id']: item['longitude_degrees']
                       for item in self.first['result']['natal']['positions']}
        positions_b = {item['id']: item['longitude_degrees']
                       for item in self.second['result']['natal']['positions']}
        for point in first['positions']:
            if point['longitude_degrees'] is None:
                self.assertEqual(point['status'], 'ambiguous_antipodal_midpoint')
            else:
                self.assertAlmostEqual(aspect_separation(point['longitude_degrees'],
                    positions_a[point['id']], 'conjunction'),
                    aspect_separation(point['longitude_degrees'],
                    positions_b[point['id']], 'conjunction'))
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'get_midpoint_composite',
                    {'chart_a_id': a, 'chart_b_id': b}, {a})
        saved = Advanced(self.store).save(self.alice, 'composite-one', self.a_id,
                                          'midpoint_composite', {'person_b_id': self.b_id})
        self.assertEqual(saved['positions'], first['positions'])
        with self.assertRaises(KeyError):
            Advanced(self.store).get(self.bob, 'composite-one')

    def test_uncorrected_davison_algebraic_dateline_and_saved_replay(self):
        result = Relationships(self.store).calculate(self.alice,
            self.first['id'], self.second['id'], 'uncorrected_davison')
        self.assertEqual(result['status'], 'supported')
        self.assertEqual(result['derived_instant_utc'], '2000-01-02T00:00:00+00:00')
        self.assertEqual((result['derived_latitude'], result['derived_longitude']), (1, 0))
        self.assertIn('not spherical', result['geography_policy'])
        self.assertEqual(result['derived_natal']['instant_utc'], result['derived_instant_utc'])
        self.assertEqual(result['derived_natal']['houses']['status'], 'supported')
        self.assertEqual(result['derived_natal']['method_version'], 'natal-tropical-v1')
        other = Relationships(self.store).calculate(self.alice,
            self.second['id'], self.first['id'], 'uncorrected_davison')
        self.assertEqual(other['derived_natal']['positions'], result['derived_natal']['positions'])
        saved = Advanced(self.store).save(self.alice, 'davison-one', self.a_id,
                                         'uncorrected_davison', {'person_b_id': self.b_id})
        self.assertEqual(saved['derived_natal']['positions'], result['derived_natal']['positions'])
        self.assertEqual(Advanced(self.store).get(self.alice, 'davison-one')['source_status'], 'current')
        self.assertTrue(Advanced(self.store).save(self.alice, 'davison-one', self.a_id,
                            'uncorrected_davison', {'person_b_id': self.b_id})['reused'])
        self.assertEqual(len(Advanced(self.store).list(self.alice, self.a_id,
                                                      'uncorrected_davison')), 1)

    def test_model_reads_two_selected_sources_with_bounded_derived_chart(self):
        self.store.create_conversation(self.alice, 'relationship-discussion')
        call = {'type': 'function_call', 'id': 'fc_derived', 'call_id': 'call_derived',
                'name': 'get_uncorrected_davison', 'arguments': json.dumps({
                    'chart_a_id': self.first['id'], 'chart_b_id': self.second['id']})}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'A derived symbolic chart.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        self.assertEqual(run_turn(self.store, self.alice, 'relationship-discussion',
            'relationship-request', 'Read a derived chart', model, lambda _: None,
            selected_people=[{'person_id': self.a_id, 'chart_id': self.first['id']},
                             {'person_id': self.b_id, 'chart_id': self.second['id']}],
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        view = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual(view['status'], 'supported')
        self.assertEqual(view['derived_longitude'], 0)
        self.assertEqual(view['derived_natal']['aspects_shown'],
                         len(view['derived_natal']['aspects']))
        self.assertEqual(view['chart_b_id'], self.second['id'])
        archived = next(event['payload'] for event in self.store.read_turn(
            self.alice, 'relationship-discussion', 'relationship-request')['events']
            if event['kind'] == 'tool_result' and event['payload'].get('name') == 'get_uncorrected_davison')
        self.assertEqual(archived['chart_b_id'], self.second['id'])
        event = next(event for event in self.store.read_turn(self.alice,
            'relationship-discussion', 'relationship-request')['events']
            if event['kind'] == 'tool_result' and event['payload'].get('name') == 'get_uncorrected_davison')
        linked = self.store.db.execute('''SELECT chart_id FROM chart_evidence
            WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s AND event_sequence=%s
        ''', ('alice', 'relationship-discussion', 'relationship-request', event['sequence'])).fetchall()
        self.assertEqual({row['chart_id'] for row in linked}, {self.first['id'], self.second['id']})
        self.assertEqual(len(linked), 2)
        self.assertGreaterEqual(len(archived['result']['derived_natal']['aspects']),
                                len(view['derived_natal']['aspects']))

    def test_pair_link_failure_rolls_back_event_and_first_index_on_same_connection(self):
        self.store.create_conversation(self.alice, 'pair-rollback')
        self.store.begin(self.alice, 'pair-rollback', 'read', 'Synthetic pair read')
        result = Relationships(self.store).calculate(self.alice,
            self.first['id'], self.second['id'], 'midpoint_composite')
        envelope, _ = prepare('get_midpoint_composite', 'call-pair', result, 1, 0, None, {})
        self.assertEqual(envelope['chart_id'], self.first['id'])
        self.assertEqual(envelope['chart_b_id'], self.second['id'])
        with self.assertRaises(KeyError):
            self.store.append(self.alice, 'pair-rollback', 'read', 'tool_result',
                              {**envelope, 'chart_b_id': 'missing-chart'})
        self.assertEqual([event['kind'] for event in self.store.read_turn(
            self.alice, 'pair-rollback', 'read')['events']], ['user'])
        self.assertEqual(self.store.db.execute('''SELECT count(*) AS n FROM chart_evidence
            WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s
        ''', ('alice', 'pair-rollback', 'read')).fetchone()['n'], 0)
        self.assertEqual(self.store.append(self.alice, 'pair-rollback', 'read',
                         'tool_result', envelope), 1)
        self.assertEqual({row['chart_id'] for row in self.store.db.execute('''
            SELECT chart_id FROM chart_evidence WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s
        ''', ('alice', 'pair-rollback', 'read')).fetchall()}, {self.first['id'], self.second['id']})

    def test_mixed_house_conventions_do_not_pick_one_and_archived_source_is_historical(self):
        advanced = Advanced(self.store)
        advanced.save(self.alice, 'before-replacement', self.a_id,
                      'uncorrected_davison', {'person_b_id': self.b_id})
        whole = self.chart(self.b_id, 'whole-sign-b', '2000-01-03', '00:00',
                           -10, -179, {**DEFAULT_NATAL_SETTINGS, 'house_system': 'whole_sign'})
        self.assertEqual(Relationships(self.store).calculate(self.alice,
            self.first['id'], whole['id'], 'uncorrected_davison')['status'],
            'unsupported_incompatible_house_or_node_profiles')
        self.assertEqual(advanced.get(self.alice, 'before-replacement')['source_status'],
                         'historical')
        self.assertEqual(advanced.save(self.alice, 'before-replacement', self.a_id,
            'uncorrected_davison', {'person_b_id': self.b_id})['source_status'], 'historical')
