"""Shared histories are one record; each archived turn retains its own versions."""

from m2.charts import Charts
from m2.conversations import Conversations
from m2.people import People
from m2.gateway import run_turn
from m2.test_gateway import TinySource
from m2.recall import current_text
from m2.revisions import correct, select_branch
from m2.test_support import DatabaseCase


class ConversationScopeTests(DatabaseCase):
    fixture_requires_fresh_migration = True
    def test_selected_draft_inputs_reach_model_without_verified_birth_or_solar_chart(self):
        people = People(self.store)
        people.charts.add_person(self.alice, 'one', 'Synthetic One')
        details = {'birth_date': '2001-04-05', 'birth_time': '09:12',
                   'birthplace': 'Unverified town', 'time_unknown': False}
        people.add_draft(self.alice, 'one', details)
        self.store.create_conversation(self.alice, 'draft-thread')
        model = TinySource()
        run_turn(self.store, self.alice, 'draft-thread', 'first',
                 'What did I supply?', model, lambda _: None,
                 selected_people=[{'person_id': 'one', 'chart_id': None}])
        self.assertIn('2001-04-05', model.prompts[0])
        self.assertIn('09:12', model.prompts[0])
        self.assertIn('Unverified town', model.prompts[0])
        self.assertIn('UNVERIFIED', model.prompts[0])
        self.assertEqual(self.store.read_turn(self.alice, 'draft-thread', 'first')
                         ['selected_people'][0]['draft_revision'], 1)

    def test_selected_chart_is_committed_as_attributed_tool_evidence_before_inference(self):
        people = People(self.store)
        people.charts.add_person(self.alice, 'one', 'Synthetic One')
        birth = people.add_birth(self.alice, 'one', {'mode': 'exact', 'zone': 'UTC',
                                                   'wall_time': '2024-03-20T03:06:00'})
        chart = people.create_chart(self.alice, 'one', birth, 'solar-default', 1)
        self.store.create_conversation(self.alice, 'chart-thread')
        model = TinySource()
        delivered = []
        run_turn(self.store, self.alice, 'chart-thread', 'first',
                 'Synthetic question about the saved chart', model, delivered.append,
                 selected_people=[{'person_id': 'one', 'chart_id': chart['id']}])
        recorded = self.store.read_turn(self.alice, 'chart-thread', 'first')['events']
        self.assertEqual([event['kind'] for event in recorded],
                         ['user', 'tool_call', 'tool_result', 'context', 'assistant_chunk', 'complete'])
        self.assertEqual(recorded[2]['payload']['chart_id'], chart['id'])
        self.assertEqual(recorded[2]['payload']['source_status'], 'current')
        self.assertIn('Synthetic One', model.prompts[0])
        self.assertIn('selected_birth_record', model.prompts[0])
        self.assertIn('user_supplied_browser_inputs', model.prompts[0])
        self.assertIn('not a calculated synastry', model.prompts[0])
        self.assertEqual([event['kind'] for event in delivered],
                         [event['kind'] for event in recorded[1:]])

    def test_cumulative_membership_and_per_turn_versions_survive_corrections(self):
        people = People(self.store)
        people.charts.add_person(self.alice, 'one', 'First synthetic person')
        people.charts.add_person(self.alice, 'two', 'Second synthetic person')
        first_draft = {'birth_date': '2024-03-20', 'birth_time': '03:06',
                       'birthplace': 'Unverified place', 'time_unknown': False}
        self.assertEqual(people.add_draft(self.alice, 'one', first_draft), 1)
        birth = people.add_birth(self.alice, 'one', {'mode': 'exact', 'zone': 'UTC',
                                                   'wall_time': '2024-03-20T03:06:00'})
        chart1 = people.create_chart(self.alice, 'one', birth, 'solar-default', 1)
        threads = Conversations(self.store)
        threads.create(self.alice, 'shared', 'Shared synthetic question', ['one'])
        threads.create(self.alice, 'general', 'General synthetic question', [])
        self.assertEqual([c['id'] for c in threads.list(self.alice, 'one')['conversations']],
                         ['shared'])
        self.assertEqual(threads.get(self.alice, 'general')['people'], [])
        self.assertTrue(self.store.begin(self.alice, 'shared', 'first', 'First synthetic input',
                                         selected_people=[{'person_id': 'one', 'chart_id': chart1['id'] }]))
        self.store.append(self.alice, 'shared', 'first', 'complete', {})
        self.assertEqual(self.store.read_turn(self.alice, 'shared', 'first')['selected_people'][0]
                         ['draft_revision'], 1)

        self.assertEqual(people.add_draft(self.alice, 'one', {**first_draft,
                                                             'birthplace': 'New unverified label'}), 2)
        revision = people.add_profile(self.alice, 'solar-default',
                                      {'zodiac': 'tropical', 'house_system': 'none',
                                       'node_type': 'true', 'aspects': ['opposition']})
        chart2 = people.create_chart(self.alice, 'one', birth, 'solar-default', revision)
        selected = [{'person_id': 'one', 'chart_id': chart2['id']},
                    {'person_id': 'two', 'chart_id': None}]
        self.assertTrue(self.store.begin(self.alice, 'shared', 'second', 'Follow-up synthetic input',
                                         parent_id='first', selected_people=selected))
        self.store.append(self.alice, 'shared', 'second', 'complete', {})
        first = self.store.read_turn(self.alice, 'shared', 'first')['selected_people']
        second = self.store.read_turn(self.alice, 'shared', 'second')['selected_people']
        self.assertEqual(first[0]['chart_id'], chart1['id'])
        self.assertEqual(first[0]['profile_revision'], 1)
        self.assertEqual(first[0]['draft_revision'], 1)
        self.assertEqual(second[0]['chart_id'], chart2['id'])
        self.assertEqual(second[0]['profile_revision'], 2)
        self.assertEqual(second[0]['draft_revision'], 2)
        self.assertEqual({row['person_id'] for row in second}, {'one', 'two'})
        self.assertEqual([c['id'] for c in threads.list(self.alice, 'two')['conversations']],
                         ['shared'])
        with self.assertRaises(ValueError):
            self.store.begin(self.alice, 'shared', 'second', 'Follow-up synthetic input',
                             parent_id='first', selected_people=[])
        with self.assertRaises(ValueError):
            self.store.ledger.delete_person(self.store, self.alice, 'two')

        correct(self.store, self.alice, 'shared', 'revision-one', 'first',
                'correct', 'Replacement after first input')
        self.assertIsNone(current_text(self.store, self.alice, 'shared', 'second',
                                       {'shared': {'first', 'second'}}))
        self.assertTrue(self.store.begin(self.alice, 'shared', 'fresh', 'New synthetic reply',
                                         parent_id='first', selected_people=[
                                             {'person_id': 'two', 'chart_id': None}]))
        self.store.append(self.alice, 'shared', 'fresh', 'complete', {})
        select_branch(self.store, self.alice, 'shared', 'fresh')
        self.assertIsNotNone(current_text(self.store, self.alice, 'shared', 'fresh',
                                          {'shared': {'first', 'fresh'}}))
        self.assertEqual(threads.turns(self.alice, 'shared')['turns'][1]['on_active_branch'], False)
        self.assertEqual(threads.turns(self.alice, 'shared')['turns'][2]['on_active_branch'], True)
