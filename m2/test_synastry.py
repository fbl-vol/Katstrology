"""Two-owned-version comparisons with independent circular geometry checks."""

import json
from copy import deepcopy

from m2.advanced import Advanced
from m2.agent_reads import execute
from m2.birth_flow import BirthFlow
from m2.gateway import run_turn
from m2.people import DEFAULT_NATAL_SETTINGS, People
from m2.provider_model import ResponsesModel
from m2.synastry import Synastry, pair_aspects, recipient_overlay
from m2.test_agent_reads import FakeBridge, ScriptedTransport
from m2.test_support import DatabaseCase


class SynastryTests(DatabaseCase):
    def chart(self, person_id, request_id, *, time='03:06', settings=None):
        return BirthFlow(self.store).generate(self.alice, person_id, {
            'request_id': request_id, 'birth_date': '2024-03-20',
            'birth_time': time, 'time_unknown': not bool(time),
            'birthplace': 'Copenhagen, Capital Region, Denmark', 'place_id': '2618425',
            'provisional': True, 'zone_override': None, 'latitude_override': None,
            'longitude_override': None, 'fold': None, 'settings': settings,
        })['chart']

    def setUp(self):
        super().setUp()
        people = People(self.store)
        self.a = people.add(self.alice, 'Synthetic person A')['id']
        self.b = people.add(self.alice, 'Synthetic person B')['id']
        self.chart_a = self.chart(self.a, 'chart-a')
        self.chart_b = self.chart(self.b, 'chart-b', time='05:20')
        self.selected = {self.chart_a['id'], self.chart_b['id']}

    def test_pure_geometry_wraparound_reversal_and_orb_boundary(self):
        settings = {'aspects': ['conjunction', 'trine'],
                    'orbs': {'conjunction': 2, 'trine': 3}}
        first = [{'id': 'sun', 'longitude_degrees': 359.0},
                 {'id': 'venus', 'longitude_degrees': 121.0}]
        second = [{'id': 'moon', 'longitude_degrees': 1.0}]
        pairs = pair_aspects(first, second, settings)
        self.assertEqual({(item['a_body_id'], item['b_body_id'], item['aspect'])
                          for item in pairs}, {('sun', 'moon', 'conjunction'),
                                              ('venus', 'moon', 'trine')})
        self.assertEqual([p['orb_degrees'] for p in pairs], [0.0, 2.0])
        swapped = pair_aspects(second, first, settings)
        self.assertEqual({(p['b_body_id'], p['a_body_id'], p['aspect'], p['orb_degrees'])
                          for p in swapped},
                         {(p['a_body_id'], p['b_body_id'], p['aspect'], p['orb_degrees'])
                          for p in pairs})

    def test_recipient_cusp_boundary_and_whole_sign_are_distinct(self):
        recipient = self.chart_b
        cusp = recipient['result']['natal']['houses']['cusps'][0]['longitude_degrees']
        donor = deepcopy(self.chart_a)
        positions = donor['result']['natal']['positions']
        positions[0]['longitude_degrees'] = cusp
        positions[1]['longitude_degrees'] = (cusp - .01) % 360
        projected = recipient_overlay(donor, recipient)
        self.assertEqual(projected['placements'][0]['recipient_house'], 1)
        self.assertEqual(projected['placements'][1]['recipient_house'], 12)
        whole = self.chart(self.b, 'whole-house-b', settings={
            **DEFAULT_NATAL_SETTINGS, 'house_system': 'whole_sign'})
        positions[0]['longitude_degrees'] = 0.0
        positions[1]['longitude_degrees'] = 359.999
        whole_result = recipient_overlay(donor, whole)
        asc_sign = int(whole['result']['natal']['houses']['angles'][0]['longitude_degrees'] // 30)
        self.assertEqual(whole_result['placements'][0]['recipient_house'], (0 - asc_sign) % 12 + 1)
        self.assertEqual(whole_result['placements'][1]['recipient_house'], (11 - asc_sign) % 12 + 1)
        self.assertNotEqual(projected['recipient_house_system'], whole_result['recipient_house_system'])

    def test_two_selected_chart_versions_and_unknown_or_mixed_settings(self):
        result = Synastry(self.store).compare(self.alice, self.chart_a['id'],
                                               self.chart_b['id'], self.selected)
        self.assertEqual(result['status'], 'supported')
        self.assertEqual((result['person_a_id'], result['person_b_id']), (self.a, self.b))
        self.assertEqual(result['house_overlays']['status'], 'supported')
        self.assertEqual(len(result['house_overlays']['a_in_b']['placements']), 10)
        self.assertEqual(len(result['house_overlays']['b_in_a']['placements']), 10)
        self.assertLessEqual(len(result['aspects']), 12)
        self.assertEqual(result['truncated'], result['total_aspects'] > 12)
        self.assertTrue(result['a_angles'] and result['b_angles'])
        swapped = Synastry(self.store).compare(self.alice, self.chart_b['id'],
                                               self.chart_a['id'], self.selected)
        self.assertEqual(result['total_aspects'], swapped['total_aspects'])
        self.assertEqual(result['house_overlays']['a_in_b']['placements'],
                         swapped['house_overlays']['b_in_a']['placements'])
        self.assertEqual({(row['a_body_id'], row['b_body_id'], row['aspect'], row['orb_degrees'])
                          for row in result['aspects']},
                         {(row['b_body_id'], row['a_body_id'], row['aspect'], row['orb_degrees'])
                          for row in swapped['aspects']})
        with self.assertRaises(ValueError):
            Synastry(self.store).compare(self.alice, self.chart_a['id'],
                                         self.chart_b['id'], {self.chart_a['id']})
        with self.assertRaises(KeyError):
            Synastry(self.store).compare(self.bob, self.chart_a['id'],
                                         self.chart_b['id'], self.selected)
        unknown = self.chart(self.b, 'unknown-b', time='')
        self.assertEqual(Synastry(self.store).compare(self.alice, self.chart_a['id'],
                         unknown['id'], {self.chart_a['id'], unknown['id']})['status'],
                         'unsupported_uncertain_birth_time_or_non_natal_chart')
        settings = {**DEFAULT_NATAL_SETTINGS,
                    'orbs': {**DEFAULT_NATAL_SETTINGS['orbs'], 'trine': 4}}
        altered = self.chart(self.b, 'mixed-b', settings=settings)
        self.assertEqual(Synastry(self.store).compare(self.alice, self.chart_a['id'],
                         altered['id'], {self.chart_a['id'], altered['id']})['status'],
                         'unsupported_incompatible_aspect_profiles')

    def test_partial_houses_keep_planet_pairs_but_exclude_unsupported_angles(self):
        polar = BirthFlow(self.store).generate(self.alice, self.b, {
            'request_id': 'polar-b', 'birth_date': '2024-03-20',
            'birth_time': '05:20', 'time_unknown': False,
            'birthplace': 'Synthetic polar location', 'place_id': None,
            'provisional': True, 'zone_override': 'UTC',
            'latitude_override': 89.95, 'longitude_override': 10.0,
            'fold': None, 'settings': None,
        })['chart']
        result = Synastry(self.store).compare(self.alice, self.chart_a['id'],
            polar['id'], {self.chart_a['id'], polar['id']})
        self.assertEqual(result['status'], 'supported')
        self.assertTrue(result['a_angles'])
        self.assertFalse(result['b_angles'])
        self.assertEqual(result['house_overlays']['status'], 'partial_unavailable_houses')
        self.assertEqual(result['house_overlays']['a_in_b']['status'], 'unsupported_polar_location')
        self.assertEqual(result['house_overlays']['b_in_a']['status'], 'supported')
        self.assertTrue(result['total_aspects'])
        self.assertTrue(all(p['b_body_id'] not in ('ascendant', 'midheaven')
                            for p in result['aspects']))

    def test_saved_overlay_replays_both_sources_after_a_correction(self):
        advanced = Advanced(self.store)
        params = {'person_b_id': self.b}
        saved = advanced.save(self.alice, 'overlay-request', self.a, 'synastry_overlay', params)
        self.assertEqual(saved['status'], 'supported')
        self.assertEqual(saved['house_overlays']['status'], 'supported')
        self.assertEqual(advanced.get(self.alice, 'overlay-request')['source_status'], 'current')
        with self.assertRaises(KeyError):
            advanced.get(self.bob, 'overlay-request')
        self.chart(self.b, 'replacement-b', time='07:20')
        old = advanced.get(self.alice, 'overlay-request')
        self.assertEqual(old['source_status'], 'historical')
        replay = advanced.save(self.alice, 'overlay-request', self.a, 'synastry_overlay', params)
        self.assertTrue(replay['reused'])
        self.assertEqual(replay['source_status'], 'historical')
        self.assertEqual(old['result']['house_overlays'], replay['house_overlays'])
        self.assertEqual(len(advanced.list(self.alice, self.a, 'synastry_overlay')), 1)

    def test_requested_comparison_archives_two_chart_evidence_edges(self):
        self.store.create_conversation(self.alice, 'shared')
        call = {'type': 'function_call', 'id': 'fc_pair', 'call_id': 'call_pair',
                'name': 'compare_selected_charts', 'arguments': json.dumps({
                    'chart_a_id': self.chart_a['id'], 'chart_b_id': self.chart_b['id']})}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'A symbolic reading is not geometry.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        self.assertEqual(run_turn(self.store, self.alice, 'shared', 'pair',
            'Compare our synthetic communication themes', model, lambda _: None,
            selected_people=[{'person_id': self.a, 'chart_id': self.chart_a['id']},
                             {'person_id': self.b, 'chart_id': self.chart_b['id']}],
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        reply = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual((reply['chart_a_id'], reply['chart_b_id']),
                         (self.chart_a['id'], self.chart_b['id']))
        self.assertEqual(reply['house_overlays']['status'], 'supported')
        self.assertEqual(len(reply['house_overlays']['a_in_b']['placements']), 10)
        count = self.store.db.execute('''
            SELECT count(DISTINCT chart_id) AS value FROM chart_evidence
            WHERE owner_id='alice' AND conversation_id='shared' AND turn_id='pair'
        ''').fetchone()['value']
        self.assertEqual(count, 2)
        tool_event = next(row for row in self.store.read_turn(self.alice, 'shared', 'pair')['events']
                          if row['kind'] == 'tool_result' and row['payload']['name'] ==
                          'compare_selected_charts')
        self.assertEqual(tool_event['payload']['result']['house_overlays']['status'], 'supported')
        self.assertEqual(self.store.db.execute('''
            SELECT count(*) AS value FROM chart_evidence
            WHERE owner_id='alice' AND conversation_id='shared' AND turn_id='pair'
                AND event_sequence=%s
        ''', (tool_event['sequence'],)).fetchone()['value'], 2)
