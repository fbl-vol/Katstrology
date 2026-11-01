"""Owned synthetic notebook: explicit quote, immutable source, stale fences and actions."""

from m2.charts import Charts
from m2.evidence import personal_context
from m2.insights import SavedInsights
from m2.revisions import correct, select_branch
from m2.test_support import DatabaseCase


class SavedInsightTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        for session in (self.alice, self.bob):
            Charts(self.store).add_person(session, 'person', 'Synthetic reader')
            self.store.create_conversation(session, 'thread')
        self.store.begin(self.alice, 'thread', 'root', 'I keep a paper sky diary.')
        self.store.append(self.alice, 'thread', 'root', 'assistant_chunk',
                          {'content': 'A small bright '})
        self.store.append(self.alice, 'thread', 'root', 'assistant_chunk',
                          {'content': 'idea to consider, not a calculated fact.'})
        self.store.append(self.alice, 'thread', 'root', 'complete', {})
        self.insights = SavedInsights(self.store)

    def test_save_edit_remove_retains_original_and_filters_retrieval(self):
        self.assertEqual(self.insights.save(self.alice, 'person', 'insight', 'thread', 'root',
                                            'assistant', 'bright idea to consider', 'User reflection'), 'insight')
        self.assertEqual(self.insights.save(self.alice, 'person', 'insight', 'thread', 'root',
                                            'assistant', 'bright idea to consider', 'User reflection'), 'insight')
        row = self.insights.list(self.alice, 'person')['entries'][0]
        self.assertEqual(row['epistemic_status'], 'saved_assistant_passage')
        self.assertEqual(row['statement'], 'bright idea to consider')
        self.assertEqual(row['source_status'], 'current')
        self.assertEqual(row['note'], 'User reflection')
        self.insights.change(self.alice, 'person', 'insight', 'edit-one', 'edit', 'Another reflection')
        self.insights.change(self.alice, 'person', 'insight', 'edit-one', 'edit', 'Another reflection')
        self.assertEqual(self.insights.list(self.alice, 'person')['entries'][0]['note'], 'Another reflection')
        self.assertEqual(personal_context(self.store, self.alice, 'person')['entries'][0]['note'], 'Another reflection')
        with self.assertRaises(ValueError):
            self.insights.change(self.alice, 'person', 'insight', 'edit-one', 'edit', 'Different payload')
        self.insights.change(self.alice, 'person', 'insight', 'remove-one', 'remove')
        self.insights.change(self.alice, 'person', 'insight', 'remove-one', 'remove')
        with self.assertRaises(ValueError):
            self.insights.change(self.alice, 'person', 'insight', 'late-edit', 'edit', 'New text')
        self.assertEqual(self.insights.list(self.alice, 'person')['entries'], [])
        self.assertEqual(personal_context(self.store, self.alice, 'person')['entries'], [])
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'root')['events'][1]['payload']['content'],
                         'A small bright ')
        self.assertEqual(self.store.db.execute('''
            SELECT count(*) AS value FROM personal_entry_actions WHERE owner_id=%s
        ''', ('alice',)).fetchone()['value'], 3)

    def test_pages_are_bounded_and_removals_leave_no_gaps_after_refresh(self):
        for index in range(23):
            self.insights.save(self.alice, 'person', f'entry-{index:02d}', 'thread', 'root',
                               'user', 'paper sky diary', f'note {index}')
        first = self.insights.list(self.alice, 'person')
        self.assertEqual(len(first['entries']), 20)
        self.assertEqual(first['next_offset'], 20)
        second = self.insights.list(self.alice, 'person', first['next_offset'])
        self.assertEqual(len(second['entries']), 3)
        self.assertIsNone(second['next_offset'])
        self.insights.change(self.alice, 'person', first['entries'][0]['id'], 'remove', 'remove')
        refreshed = self.insights.list(self.alice, 'person')
        older = self.insights.list(self.alice, 'person', refreshed['next_offset'])
        self.assertEqual(len({entry['id'] for entry in refreshed['entries'] + older['entries']}), 22)
        self.assertEqual(personal_context(self.store, self.alice, 'person')['entries'][0]['note'],
                         refreshed['entries'][0]['note'])

    def test_owner_source_quote_branch_and_correction_fail_closed(self):
        with self.assertRaises(KeyError):
            self.insights.save(self.bob, 'person', 'foreign', 'thread', 'root', 'user',
                               'I keep a paper sky diary.', '')
        with self.assertRaises(ValueError):
            self.insights.save(self.alice, 'person', 'invented', 'thread', 'root', 'assistant',
                               'This text was invented', '')
        self.store.begin(self.alice, 'thread', 'open', 'Unfinished input', parent_id='root')
        with self.assertRaises(ValueError):
            self.insights.save(self.alice, 'person', 'unfinished', 'thread', 'open', 'user',
                               'Unfinished input', '')
        self.store.append(self.alice, 'thread', 'open', 'complete', {})
        select_branch(self.store, self.alice, 'thread', 'root')
        self.insights.save(self.alice, 'person', 'user-quote', 'thread', 'root', 'user',
                           'paper sky diary', '')
        self.store.begin(self.alice, 'thread', 'other', 'Different current branch')
        self.store.append(self.alice, 'thread', 'other', 'complete', {})
        stale = self.insights.list(self.alice, 'person')['entries'][0]
        self.assertEqual(stale['epistemic_status'], 'saved_user_passage')
        self.assertEqual(stale['source_status'], 'historical')
        self.assertEqual(personal_context(self.store, self.alice, 'person')['entries'], [])
        with self.assertRaises(ValueError):
            self.insights.save(self.alice, 'person', 'late', 'thread', 'root', 'user',
                               'paper sky diary', '')
        select_branch(self.store, self.alice, 'thread', 'root')
        self.assertEqual(self.insights.list(self.alice, 'person')['entries'][0]['source_status'], 'current')
        correct(self.store, self.alice, 'thread', 'fix', 'root', 'correct', 'Corrected sky diary')
        self.assertEqual(self.insights.list(self.alice, 'person')['entries'][0]['source_status'], 'historical')
        self.assertEqual(personal_context(self.store, self.alice, 'person')['entries'], [])
        self.assertEqual(self.insights.list(self.bob, 'person')['entries'], [])
        self.store.ledger.delete_conversation(self.store, self.alice, 'thread')
        self.assertEqual(self.insights.list(self.alice, 'person')['entries'], [])
