"""Synthetic real-PG edit/leave/return continuity, never a real provider."""
from pathlib import Path

from m2.agent_reads import execute
from m2.compaction import _history
from m2.gateway import run_turn
from m2.people import People
from m2.recall import (current_text, dialogue_text, rebuild_pending,
                       repair_stale_draft_derivatives, search)
from m2.revisions import correct
from m2.store import Store
from m2.test_gateway import TinySource
from m2.test_support import DatabaseCase, seeded_session


class WideModel(TinySource):
    context_limit = 100000


class ContinuityHotfixTests(DatabaseCase):
    def test_question_survives_profile_edit_return_and_fresh_replies(self):
        people = People(self.store)
        people.charts.add_person(self.alice, 'partner', 'Synthetic partner')
        birth = {'birth_date': '2030-02-12', 'birth_time': '09:30',
                 'birthplace': 'Synthetic town', 'time_unknown': False}
        people.add_draft(self.alice, 'partner', birth)
        self.store.create_conversation(self.alice, 'thread')
        selection = [{'person_id': 'partner', 'chart_id': None}]
        question = 'How can our relationship grow closer over the next year?'
        run_turn(self.store, self.alice, 'thread', 'question', question, WideModel(),
                 lambda _: None, selected_people=selection)
        rebuild_pending(self.store, self.alice)
        people.add_draft(self.alice, 'partner', {**birth, 'birth_date': '1983-02-12'})
        acknowledgement = WideModel()
        run_turn(self.store, self.alice, 'thread', 'updated', 'The birth year is corrected.',
                 acknowledgement, lambda _: None, parent_id='question', selected_people=selection)
        self.assertIn(question, acknowledgement.prompts[0])
        self.store.close()
        self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)
        self.alice = seeded_session(self.store, 'alice')
        head = self.store.active_head(self.alice, 'thread')
        self.assertEqual(head, 'updated')
        self.assertEqual(self.store.ancestry(self.alice, 'thread', head), ['question', 'updated'])
        history = _history(self.store, self.alice, 'thread', ['question', 'updated'])
        self.assertTrue(any(question in text for _, text in history))
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'question')['events'][0]
                         ['payload']['content'], question)
        result = execute(self.store, self.alice, 'get_conversation_messages',
                         {'conversation_id': 'thread', 'around_turn_id': 'question'}, set())
        self.assertTrue(any(question in row['text'] for row in result['turns']))
        rebuild_pending(self.store, self.alice)
        matches = search(self.store, self.alice, 'relationship')['results']
        self.assertTrue(matches)
        self.assertEqual(matches[0]['speaker'], 'historical_user')
        self.assertIsNone(current_text(self.store, self.alice, 'thread', 'question'))
        resumed = WideModel()
        run_turn(self.store, self.alice, 'thread', 'resumed', 'Continue the original question.',
                 resumed, lambda _: None, parent_id=head, selected_people=selection)
        self.assertIn(question, resumed.prompts[0])
        fresh = _history(self.store, self.alice, 'thread', ['question', 'updated', 'resumed'])
        self.assertTrue(any(turn_id == 'resumed' and 'assistant interpretation' in text
                            for turn_id, text in fresh))

    def test_explicit_bounded_repair_replaces_existing_stale_cache_without_archive_mutation(self):
        people = People(self.store)
        people.charts.add_person(self.alice, 'partner', 'Synthetic partner')
        birth = {'birth_date': '2000-02-12', 'birth_time': '09:30',
                 'birthplace': 'Synthetic town', 'time_unknown': False}
        people.add_draft(self.alice, 'partner', birth)
        self.store.create_conversation(self.alice, 'thread')
        selection = [{'person_id': 'partner', 'chart_id': None}]
        run_turn(self.store, self.alice, 'thread', 'root', 'Unmistakable old question',
                 WideModel(), lambda _: None, selected_people=selection)
        people.add_draft(self.alice, 'partner', {**birth, 'birth_date': '1983-02-12'})
        rebuild_pending(self.store, self.alice)  # Simulate an already-built pre-hotfix cache.
        self.store.db.execute('DELETE FROM search_entries WHERE conversation_id=%s', ('thread',))
        self.assertEqual(search(self.store, self.alice, 'Unmistakable')['results'], [])
        before = self.store.read_turn(self.alice, 'thread', 'root')
        page = repair_stale_draft_derivatives(self.store, self.alice, limit=1)
        self.assertEqual(page['repaired'], 1)
        self.assertIsNone(page['next_after'])
        self.assertEqual(page['pending_conversations'], 0)
        self.assertEqual(search(self.store, self.alice, 'Unmistakable')['results'][0]
                         ['speaker'], 'historical_user')
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'root'), before)
        self.assertEqual(repair_stale_draft_derivatives(self.store, self.alice,
                         after='thread')['repaired'], 0)

    def test_historical_request_does_not_resurrect_old_reply_or_invalid_branch(self):
        people = People(self.store)
        people.charts.add_person(self.alice, 'partner', 'Synthetic partner')
        birth = {'birth_date': '2000-02-12', 'birth_time': '09:30',
                 'birthplace': 'Synthetic town', 'time_unknown': False}
        people.add_draft(self.alice, 'partner', birth)
        self.store.create_conversation(self.alice, 'thread')
        selection = [{'person_id': 'partner', 'chart_id': None}]
        self.store.begin(self.alice, 'thread', 'root', 'Question and old date',
                         selected_people=selection)
        self.store.append(self.alice, 'thread', 'root', 'assistant_chunk',
                          {'content': 'Old chart interpretation must not survive'})
        self.store.append(self.alice, 'thread', 'root', 'complete', {})
        people.add_draft(self.alice, 'partner', {**birth, 'birth_date': '1983-02-12'})
        historical = dialogue_text(self.store, self.alice, 'thread', 'root')
        self.assertIn('Question and old date', historical)
        self.assertNotIn('Old chart interpretation', historical)
        self.assertNotIn('Old chart interpretation',
                         _history(self.store, self.alice, 'thread', ['root'])[0][1])
        self.store.begin(self.alice, 'thread', 'other', 'Other branch',
                         parent_id='root', selected_people=selection)
        self.store.append(self.alice, 'thread', 'other', 'complete', {})
        self.store.begin(self.alice, 'thread', 'new', 'Current branch',
                         parent_id='root', selected_people=selection)
        self.store.append(self.alice, 'thread', 'new', 'complete', {})
        self.assertIsNone(dialogue_text(self.store, self.alice, 'thread', 'other'))
        rebuild_pending(self.store, self.alice)
        self.assertEqual(search(self.store, self.alice, 'Other branch')['results'], [])
        correct(self.store, self.alice, 'thread', 'replacement', 'root',
                'correct', 'Corrected request')
        self.assertIsNone(dialogue_text(self.store, self.alice, 'thread', 'new'))
        self.assertNotIn('Question and old date', dialogue_text(
            self.store, self.alice, 'thread', 'root'))
        correct(self.store, self.alice, 'thread', 'withdrawn', 'root', 'withdraw')
        self.assertIsNone(dialogue_text(self.store, self.alice, 'thread', 'root'))
        rebuild_pending(self.store, self.alice)
        self.assertEqual(search(self.store, self.alice, 'Question')['results'], [])
