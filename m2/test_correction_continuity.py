"""Durable revision lineage and bounded current-evidence regressions."""

from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.backup import dump_owned, restore_owned
from m2.charts import Charts
from m2.evidence import personal_context, rebuild_vectors, search_evidence
from m2.gateway import run_turn
from m2.recall import assemble_prompt, current_text, rebuild_pending, search
from m2.references import PersonalContext, References
from m2.revisions import correct, select_branch
from m2.store import Store
from m2.test_gateway import TinySource
from m2.test_support import DatabaseCase


class FixedEmbedder:
    """A deterministic local vector for indexing reachability, not relevance."""

    def document(self, _):
        return [1.0, 0.0]

    passage = document

    def query(self, _):
        return [1.0, 0.0]


class CorrectionContinuityTests(DatabaseCase):
    fixture_requires_fresh_migration = True
    def completed(self, conversation, turn, user, assistant='Synthetic answer', parent=None,
                  reference=None):
        self.store.begin(self.alice, conversation, turn, user, parent_id=parent)
        if reference:
            self.store.append(self.alice, conversation, turn, 'tool_result', {
                'results': [{'kind': 'reference_passage', 'source_id': reference,
                             'passage_id': 'passage'}]})
        sequence = self.store.append(self.alice, conversation, turn, 'assistant_chunk',
                                     {'content': assistant})
        self.store.append(self.alice, conversation, turn, 'complete', {})
        return sequence

    def test_explicit_inactive_parent_uses_selected_branch_not_active_sibling(self):
        self.store.create_conversation(self.alice, 'thread')
        self.completed('thread', 'root', 'Root request')
        self.completed('thread', 'a', 'First branch question', 'Distinct first branch', 'root')
        self.completed('thread', 'b', 'Other branch question', 'Distinct second branch', 'root')
        self.assertEqual(self.store.active_head(self.alice, 'thread'), 'b')

        model = TinySource()
        self.assertEqual(run_turn(self.store, self.alice, 'thread', 'a-child',
                                  'Continue selected branch', model, lambda _: None,
                                  parent_id='a'), 'complete')
        self.assertIn('Distinct first branch', model.prompts[0])
        self.assertNotIn('Distinct second branch', model.prompts[0])
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'a-child')['parent_id'], 'a')
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'b')['status'], 'complete')
        rebuild_pending(self.store, self.alice)
        self.assertEqual(search(self.store, self.alice, 'second')['results'], [])
        self.assertTrue(search(self.store, self.alice, 'first')['results'])

    def test_post_correction_children_current_earlier_descendants_historical(self):
        self.store.create_conversation(self.alice, 'thread')
        self.completed('thread', 'root', 'Original user text', 'Original assistant answer')
        self.completed('thread', 'old', 'Earlier question', 'Earlier claim', 'root')
        correct(self.store, self.alice, 'thread', 'revision-one', 'root',
                'correct', 'Replacement one')
        old_chain = {'thread': set(self.store.ancestry(self.alice, 'thread', 'old'))}
        self.assertIsNone(current_text(self.store, self.alice, 'thread', 'old', old_chain))

        model = TinySource()
        run_turn(self.store, self.alice, 'thread', 'new', 'Question after correction',
                 model, lambda _: None, parent_id='root')
        self.assertIn('Replacement one', model.prompts[0])
        self.assertNotIn('Original assistant answer', model.prompts[0])
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'new')['parent_revision'],
                         self.store.read_turn(self.alice, 'thread', 'root')['corrections'][-1]
                         ['sequence'])
        rebuild_pending(self.store, self.alice)
        self.assertTrue(search(self.store, self.alice, 'after')['results'])
        self.assertEqual(search(self.store, self.alice, 'Earlier')['results'], [])
        prompt, _ = assemble_prompt(self.store, self.alice, 'thread', 'new',
                                    'More context', model.tokenize)
        self.assertIn('Replacement one', prompt)
        self.assertIn('Question after correction', prompt)

        correct(self.store, self.alice, 'thread', 'revision-two', 'root',
                'correct', 'Replacement two')
        new_chain = {'thread': set(self.store.ancestry(self.alice, 'thread', 'new'))}
        self.assertIsNone(current_text(self.store, self.alice, 'thread', 'new', new_chain))
        self.completed('thread', 'latest', 'After latest revision',
                       'Fresh answer', 'root')
        rebuild_pending(self.store, self.alice)
        self.assertEqual(search(self.store, self.alice, 'Question after correction')['results'], [])
        self.assertTrue(search(self.store, self.alice, 'latest')['results'])
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'old')['status'], 'complete')

    def test_inferred_personal_entry_follows_transitive_source_validity(self):
        Charts(self.store).add_person(self.alice, 'person', 'Synthetic person')
        for conv in ('source', 'discussion', 'unrelated'):
            self.store.create_conversation(self.alice, conv)
        self.completed('source', 'claim', 'Synthetic source claim')
        refs = References(self.store)
        refs.add_source(self.alice, 'linked', 'Synthetic', 'Note', 'first',
                        'western', 'solar', 'local fixture', 'synthetic rights',
                        source=('source', 'claim'))
        refs.add_passage(self.alice, 'linked', 'passage', 'one', 'Synthetic reference claim')
        self.completed('discussion', 'quote', 'Quote reference',
                       'Synthetic interpretation', reference='linked')
        inferred_seq = self.completed('discussion', 'inference', 'Continue quote',
                                      'Synthetic inferred preference', parent='quote')
        note = PersonalContext(self.store)
        note.add(self.alice, 'person', 'inferred', 'discussion', 'inference',
                 'Synthetic inferred preference', epistemic_status='agent_inference',
                 source_event_sequence=inferred_seq)
        self.completed('unrelated', 'report',
                       'I prefer synthetic sunrise exercises.')
        note.add(self.alice, 'person', 'unrelated', 'unrelated', 'report',
                 'I prefer synthetic sunrise exercises.', source_event_sequence=0)
        self.assertEqual({row['id'] for row in personal_context(
            self.store, self.alice, 'person')['entries']}, {'inferred', 'unrelated'})

        correct(self.store, self.alice, 'source', 'withdraw', 'claim', 'withdraw')
        self.assertEqual([row['id'] for row in personal_context(
            self.store, self.alice, 'person')['entries']], ['unrelated'])
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM personal_entries')
                         .fetchone()['n'], 2)

    def test_index_pages_past_stale_rows_without_skipping_new_candidates(self):
        refs = References(self.store)
        self.store.create_conversation(self.alice, 'source')
        self.completed('source', 'old', 'Synthetic source')
        refs.add_source(self.alice, 'a-stale', 'Synthetic', 'Old', 'first',
                        'western', 'solar', 'local fixture', 'synthetic rights',
                        source=('source', 'old'))
        for index in range(120):
            refs.add_passage(self.alice, 'a-stale', f'p-{index:03}', 'one',
                             'Stale synthetic phrase')
        for source_id in ('z-current', 'zz-next'):
            refs.add_source(self.alice, source_id, 'Synthetic', 'Current', 'first',
                            'western', 'solar', 'local fixture', 'synthetic rights')
            refs.add_passage(self.alice, source_id, 'passage', 'one',
                             f'{source_id} valid semantic phrase')
        correct(self.store, self.alice, 'source', 'withdraw', 'old', 'withdraw')

        first = rebuild_vectors(self.store, self.alice, FixedEmbedder(), limit=1)
        second = rebuild_vectors(self.store, self.alice, FixedEmbedder(), limit=1)
        self.assertEqual((first['references_indexed'], second['references_indexed']), (1, 1))
        self.assertEqual({row['source_id'] for row in self.store.db.execute(
            'SELECT source_id FROM reference_vectors').fetchall()}, {'z-current', 'zz-next'})
        self.assertEqual(self.store.db.execute("SELECT count(*) AS n FROM reference_vectors "
                                               "WHERE source_id='a-stale'").fetchone()['n'], 0)
        semantic = search_evidence(self.store, self.alice, 'unmatched', FixedEmbedder(),
                                   include_history=False)
        self.assertEqual({row['source_id'] for row in semantic['results']},
                         {'z-current', 'zz-next'})

    def test_corrected_child_rebases_only_on_the_parent_revision_it_consumed(self):
        self.store.create_conversation(self.alice, 'thread')
        self.completed('thread', 'root', 'Original source')
        self.completed('thread', 'child', 'Original child', parent='root')
        correct(self.store, self.alice, 'thread', 'root-one', 'root',
                'correct', 'First root replacement')
        correct(self.store, self.alice, 'thread', 'child-one', 'child',
                'correct', 'Fresh child replacement')
        self.completed('thread', 'grandchild', 'After child correction', parent='child')
        chain = {'thread': {'root', 'child', 'grandchild'}}
        self.assertIsNotNone(current_text(self.store, self.alice, 'thread',
                                          'grandchild', chain))

        correct(self.store, self.alice, 'thread', 'root-two', 'root',
                'correct', 'Second root replacement')
        self.assertIsNone(current_text(self.store, self.alice, 'thread',
                                       'grandchild', chain))
        correct(self.store, self.alice, 'thread', 'child-two', 'child',
                'correct', 'Second child replacement')
        self.assertIsNone(current_text(self.store, self.alice, 'thread',
                                       'grandchild', chain))
        self.completed('thread', 'new-grandchild', 'After latest child', parent='child')
        self.assertIsNotNone(current_text(self.store, self.alice, 'thread', 'new-grandchild',
                                          {'thread': {'root', 'child', 'new-grandchild'}}))

    def _remove_post_seven_schema(self):
        """Rebuild a real seven-migration snapshot without later reference state."""
        with psycopg.connect(self.dsn, autocommit=True) as db:
            db.execute('DROP TABLE journal_actions, watch_actions, turn_selected_results, '
                       'journal_entries, watch_items')
            db.execute('DROP TABLE advanced_results')
            db.execute('DROP TABLE personal_entry_actions')
            db.execute('ALTER TABLE personal_entries DROP CONSTRAINT personal_entries_epistemic_status_check')
            db.execute('ALTER TABLE personal_entries ADD CONSTRAINT personal_entries_epistemic_status_check '
                       "CHECK (epistemic_status IN ('user_reported','explicitly_confirmed','agent_inference'))")
            db.execute('DROP TABLE reference_book_locations, reference_book_sources')
            db.execute('DROP TABLE reference_originals')
            db.execute('ALTER TABLE reference_sources DROP CONSTRAINT reference_sources_previous_fk, '
                       'DROP CONSTRAINT reference_sources_approval_check, '
                       'DROP CONSTRAINT reference_sources_rights_basis_check, '
                       'DROP CONSTRAINT reference_sources_one_previous_check, '
                       'DROP COLUMN supersedes_deleted_source_id, '
                       'DROP COLUMN supersedes_source_id, DROP COLUMN source_url, '
                       'DROP COLUMN language')
            db.execute("ALTER TABLE reference_sources ADD CONSTRAINT reference_sources_rights_basis_check "
                       "CHECK (rights_basis='synthetic_fixture')")
            db.execute('DROP TABLE compaction_checkpoints')
            db.execute('ALTER TABLE conversations DROP COLUMN compaction_revision')
            db.execute('ALTER TABLE corrections DROP COLUMN parent_revision')
            db.execute('ALTER TABLE turns DROP COLUMN parent_revision')
            db.execute('DROP TABLE person_active_charts')
            db.execute('DROP TABLE birth_generation_requests, web_sessions, person_drafts, '
                       'person_attachments, turn_people, conversation_people')
            db.execute('ALTER TABLE charts DROP CONSTRAINT charts_owner_person_id_unique, '
                       'DROP CONSTRAINT chart_person_identity')
            db.execute('ALTER TABLE conversations DROP COLUMN title, DROP COLUMN title_origin, '
                       'DROP COLUMN title_status, DROP COLUMN title_source_turn, '
                       'DROP COLUMN title_source_epoch, DROP COLUMN title_source_digest')
            db.execute('DELETE FROM schema_migrations WHERE version>=8')

    def test_pre_migration_dump_restores_under_revision_migration(self):
        self.store.create_conversation(self.alice, 'thread')
        self.completed('thread', 'root', 'Synthetic source')
        self.completed('thread', 'legacy', 'Legacy response', parent='root')
        self.store.close()
        self._remove_post_seven_schema()
        legacy_dump = Path(self.directory.name) / 'legacy-seven.dump'
        dump_owned(self.dsn, legacy_dump)

        target = 'kat_m2_restored_' + uuid4().hex[:12]
        target_dsn = make_conninfo(self.admin_dsn, dbname=target)
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
        restored = None
        try:
            restore_owned(target_dsn, legacy_dump)
            restored = Store(target_dsn, Path(self.directory.name) / 'restored-files',
                             self.ledger)
            alice = restored.authenticate('alice', 'synthetic-password-alice')
            self.assertIsNone(restored.read_turn(alice, 'thread', 'legacy')['parent_revision'])
            self.assertEqual(restored.db.execute('SELECT max(version) AS version FROM '
                                                  'schema_migrations').fetchone()['version'], 23)
            correct(restored, alice, 'thread', 'withdrawn', 'root', 'withdraw')
            self.assertIsNone(current_text(restored, alice, 'thread', 'legacy',
                                           {'thread': {'root', 'legacy'}}))
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
            self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)

    def test_pre_migration_lineage_without_snapshot_fails_closed_after_correction(self):
        self.store.create_conversation(self.alice, 'thread')
        self.completed('thread', 'root', 'Synthetic source')
        self.completed('thread', 'legacy', 'Legacy child', parent='root')
        self.store.close()
        self._remove_post_seven_schema()
        self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)
        alice = self.store.authenticate('alice', 'synthetic-password-alice')
        self.alice = alice
        self.assertIsNone(self.store.read_turn(alice, 'thread', 'legacy')['parent_revision'])
        correct(self.store, alice, 'thread', 'new-correction', 'root',
                'correct', 'Current replacement')
        self.assertIsNone(current_text(self.store, alice, 'thread', 'legacy',
                                       {'thread': {'root', 'legacy'}}))
        self.completed('thread', 'fresh', 'Post-migration child', parent='root')
        self.assertIsNotNone(current_text(self.store, alice, 'thread', 'fresh',
                                          {'thread': {'root', 'fresh'}}))
