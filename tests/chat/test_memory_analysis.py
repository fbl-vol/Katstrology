import copy
import json
import unittest

from m2.chat.memory_analysis import candidates


class MemoryAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.text = 'Frederik enjoys gardening.'
        self.evidence = {'turn_id': 'new', 'pending_turns': ['new'],
            'self_association': {'person_id': None, 'version': 0},
            'messages': [{'conversation_id': 'thread', 'turn_id': 'new', 'source_unit': 2,
                          'text': self.text}],
            'people': [{'id': 'frederik', 'name': 'Frederik', 'named_eligible': True,
                        'associated_self': False, 'eligible_turns': ['new'], 'entries': []}]}
        self.action = {'person_id': 'frederik', 'entry_id': None, 'expected_version': 0,
            'intent': 'add', 'group': 'interests', 'assessment': 'asserted', 'attribution': 'named',
            'identity_turn_id': 'new', 'statements': [self.span('new', self.text)],
            'state': None, 'date': None}

    @staticmethod
    def span(turn, text):
        return {'turn_id': turn, 'start': 0, 'end': len(text), 'text': text}

    def parse(self):
        return candidates(self.evidence, json.dumps({'actions': [self.action]}))

    def existing(self):
        action = self.parse()[0]
        action['source'].update(turn_id='old', source_unit=1)
        action['source']['sources'][0].update(turn_id='old', source_unit=1)
        self.evidence['people'][0]['entries'] = [{'id': 'stable', 'version': 3,
            'lifecycle': 'active', 'content': action['content'], 'source': action['source']}]

    def test_literal_fact_and_noop_duplicate_preserve_record_identity(self):
        result = self.parse()
        self.assertEqual(result[0]['content']['title'], self.text)
        self.assertEqual(result[0]['source']['sources'][0]['statement'], self.text)
        self.existing()
        self.assertEqual(self.parse(), [])
        self.assertEqual(candidates(self.evidence, '{"actions":[]}'), [])

    def test_repeated_add_or_update_target_rejects_whole_batch(self):
        with self.assertRaisesRegex(ValueError, 'One coherent action per target'):
            candidates(self.evidence, json.dumps({'actions': [self.action, self.action]}))
        self.existing()
        text = 'Frederik grows tomatoes too.'
        self.evidence['messages'][0]['text'] = text
        self.action.update(intent='merge', entry_id='stable', expected_version=3,
                           statements=[self.span('new', text)])
        with self.assertRaisesRegex(ValueError, 'One coherent action per target'):
            candidates(self.evidence, json.dumps({'actions': [self.action, self.action]}))

    def test_merge_anchor_is_pending_source_not_same_turn_id_in_another_conversation(self):
        self.existing()
        prior = self.evidence['people'][0]['entries'][0]['source']
        prior.update(conversation_id='other', turn_id='new', source_unit=99)
        prior['sources'][0].update(conversation_id='other', turn_id='new', source_unit=99)
        text = 'Frederik grows tomatoes too.'
        self.evidence['messages'][0]['text'] = text
        self.action.update(intent='merge', entry_id='stable', expected_version=3,
                           statements=[self.span('new', text)])
        source = self.parse()[0]['source']
        self.assertEqual((source['conversation_id'], source['source_unit']), ('thread', 2))
        self.assertEqual({item['source_unit'] for item in source['sources']}, {2, 99})

    def test_nonpending_history_cannot_be_promoted_by_model_assertion(self):
        self.evidence['pending_turns'] = []
        with self.assertRaisesRegex(ValueError, 'Historical evidence alone'):
            self.parse()

    def test_inactive_duplicate_is_not_reused_or_reactivated(self):
        self.existing()
        self.evidence['people'][0]['entries'][0]['lifecycle'] = 'source_invalidated'
        fresh, = self.parse()
        self.assertIsNone(fresh['entry_id'])
        self.assertEqual({source['turn_id'] for source in fresh['source']['sources']}, {'new'})
        self.action.update(entry_id='stable', expected_version=3, intent='merge')
        with self.assertRaises(ValueError):
            self.parse()

    def test_semantic_replacement_requires_version_not_a_shared_phrase(self):
        self.existing()
        changed = 'Frederik now prefers painting instead.'
        self.evidence['messages'][0]['text'] = changed
        self.action.update(entry_id='stable', expected_version=3, intent='replace',
                           statements=[self.span('new', changed)])
        result = self.parse()[0]
        self.assertEqual(result['entry_id'], 'stable')
        self.assertEqual(result['expected_version'], 3)
        self.assertEqual(result['content']['title'], changed)
        self.action['expected_version'] = 2
        with self.assertRaises(ValueError):
            self.parse()

    def test_manual_records_and_ambiguous_names_are_not_automatic_targets(self):
        self.existing()
        self.action.update(entry_id='stable', expected_version=3, intent='replace')
        self.evidence['people'][0]['entries'][0]['source'] = {'kind': 'manual'}
        with self.assertRaises(ValueError):
            self.parse()
        self.action.update(entry_id=None, expected_version=0, intent='add')
        self.evidence['people'][0]['named_eligible'] = False
        with self.assertRaises(ValueError):
            self.parse()

    def test_unambiguous_pronoun_keeps_identity_source_without_inventing_prose(self):
        prior = copy.deepcopy(self.evidence['messages'][0])
        prior.update(turn_id='prior', source_unit=1)
        text = 'He grows tomatoes too.'
        self.evidence['messages'] = [prior, {**prior, 'turn_id': 'new', 'source_unit': 2, 'text': text}]
        self.evidence['people'][0]['eligible_turns'].append('prior')
        self.action.update(attribution='reference', identity_turn_id='prior',
                           statements=[self.span('new', text)])
        result = self.parse()[0]
        self.assertEqual(result['content']['title'], text)
        self.assertEqual({source['turn_id'] for source in result['source']['sources']}, {'prior', 'new'})
        self.evidence['people'][0]['eligible_turns'].remove('prior')
        with self.assertRaises(ValueError):
            self.parse()

    def test_quotes_forged_spans_and_inferred_dates_are_rejected(self):
        self.action['statements'][0]['text'] = 'Frederik owns a yacht.'
        with self.assertRaises(ValueError):
            self.parse()
        self.action['statements'] = [self.span('new', self.text)]
        self.action['date'] = {'text': '', 'precision': 'year', 'start': '2027', 'end': None}
        with self.assertRaises(ValueError):
            self.parse()
        self.action['date'] = None
        self.evidence['messages'][0]['text'] = '"' + self.text + '"'
        self.action['statements'] = [{'turn_id': 'new', 'start': 1, 'end': 1 + len(self.text), 'text': self.text}]
        with self.assertRaises(ValueError):
            self.parse()
