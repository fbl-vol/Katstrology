"""Selected total-review regressions on the owned synthetic PostgreSQL fixture."""

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.backup import backup, restore
from m2.charts import Charts
from m2.deletion import Tombstones
from m2.evidence import search_evidence
from m2.recall import rebuild_pending, search, assemble_prompt
from m2.references import References
from m2.revisions import correct
from m2.test_gateway import TinySource
from m2.test_support import DatabaseCase
from m2.provenance import source_turn_current


class SelectedReviewFixes(DatabaseCase):
    fixture_requires_fresh_migration = True
    def completed(self, conv, turn, text, parent=None, reference=None):
        self.store.begin(self.alice, conv, turn, text, parent_id=parent)
        if reference:
            self.store.append(self.alice, conv, turn, 'tool_result', {
                'results': [{'kind': 'reference_passage', 'source_id': reference,
                             'passage_id': 'p'}]})
        self.store.append(self.alice, conv, turn, 'assistant_chunk',
                          {'content': 'Synthetic repeated claim'})
        self.store.append(self.alice, conv, turn, 'complete', {})

    def source(self, source_id, linked=None):
        refs = References(self.store)
        refs.add_source(self.alice, source_id, 'Synthetic author', 'Synthetic note',
                        'first', 'western', 'solar', 'local fixture', 'synthetic rights',
                        source=linked)
        refs.add_passage(self.alice, source_id, 'p', 'one',
                         'A rareword synthetic claim for local tests.')
        return refs

    def test_truncated_post_backup_journal_fails_closed_before_restore(self):
        self.store.create_conversation(self.alice, 'deleted')
        self.completed('deleted', 'old', 'synthetic input')
        snapshot = Path(self.directory.name) / 'snapshot'
        backup(self.store, snapshot)
        prefix = self.ledger.path.read_bytes()
        self.ledger.delete_conversation(self.store, self.alice, 'deleted')
        self.ledger.path.write_bytes(prefix)  # the tip remains at the newer deletion

        with self.assertRaisesRegex(RuntimeError, 'tip disagrees'):
            Tombstones(self.ledger.path)
        with self.assertRaisesRegex(RuntimeError, 'tip disagrees'):
            restore(snapshot, self.dsn, Path(self.directory.name) / 'unsafe', self.ledger)
        self.assertFalse((Path(self.directory.name) / 'unsafe').exists())

    def test_failed_tip_update_blocks_live_reads_and_startup(self):
        self.store.create_conversation(self.alice, 'doomed')
        self.completed('doomed', 'turn', 'Synthetic source')
        with patch.object(self.ledger, '_write_tip', side_effect=OSError('local write failed')):
            with self.assertRaises(OSError):
                self.ledger.delete_conversation(self.store, self.alice, 'doomed')
        with self.assertRaisesRegex(RuntimeError, 'reconciliation required'):
            self.store.read_turn(self.alice, 'doomed', 'turn')
        with self.assertRaisesRegex(RuntimeError, 'tip disagrees'):
            Tombstones(self.ledger.path)

    def test_deleted_person_and_reference_ids_cannot_be_recreated(self):
        charts = Charts(self.store)
        charts.add_person(self.alice, 'person', 'Synthetic Alice')
        charts.add_person(self.bob, 'person', 'Synthetic Bob')
        self.source('source')
        refs = References(self.store)
        refs.add_source(self.bob, 'source', 'Bob', 'Note', 'first', 'western', 'solar',
                        'local fixture', 'synthetic rights')
        self.ledger.delete_person(self.store, self.alice, 'person')
        self.ledger.delete_reference(self.store, self.alice, 'source')
        with self.assertRaisesRegex(ValueError, 'cannot be reused'):
            charts.add_person(self.alice, 'person', 'Replacement')
        with self.assertRaisesRegex(ValueError, 'cannot be reused'):
            self.source('source')

        self.store.close()
        self.store = self.store.__class__(self.dsn, Path(self.directory.name) / 'files',
                                           Tombstones(self.ledger.path))
        alice = self.store.authenticate('alice', 'synthetic-password-alice')
        bob = self.store.authenticate('bob', 'synthetic-password-bob')
        with self.assertRaisesRegex(ValueError, 'cannot be reused'):
            Charts(self.store).add_person(alice, 'person', 'Replacement')
        with self.assertRaisesRegex(ValueError, 'cannot be reused'):
            References(self.store).add_source(alice, 'source', 'A', 'B', 'first',
                                                'western', 'solar', 'local fixture', 'synthetic')
        self.assertEqual(self.store.db.execute("SELECT name FROM people WHERE owner_id='bob' "
                                               "AND id='person'").fetchone()['name'],
                         'Synthetic Bob')
        self.assertEqual(self.store.db.execute("SELECT title FROM reference_sources WHERE "
                                               "owner_id='bob' AND id='source'")
                         .fetchone()['title'], 'Note')

    def test_correction_fences_transitive_sources_and_repeating_followup(self):
        for conv in ('a', 'b', 'c'):
            self.store.create_conversation(self.alice, conv)
        self.completed('a', 'original', 'Synthetic source')
        self.source('ref-a', ('a', 'original'))
        self.completed('b', 'quote', 'Quote first reference', reference='ref-a')
        self.completed('b', 'followup', 'Follow up', parent='quote')
        refs = self.source('ref-b', ('b', 'quote'))
        self.completed('c', 'claim', 'Use second reference', reference='ref-b')
        rebuild_pending(self.store, self.alice)
        self.assertEqual(refs.get_passage(self.alice, 'ref-b', 'p')['source_status'], 'active')
        self.assertTrue(search(self.store, self.alice, 'repeated')['results'])

        correct(self.store, self.alice, 'a', 'withdraw', 'original', 'withdraw')
        self.assertEqual(refs.get_passage(self.alice, 'ref-b', 'p')['source_status'],
                         'superseded')
        self.assertFalse(source_turn_current(self.store, self.alice, 'b', 'followup'))
        self.assertEqual(search(self.store, self.alice, 'repeated')['results'], [])
        rebuild_pending(self.store, self.alice)
        self.assertEqual(search(self.store, self.alice, 'repeated')['results'], [])
        self.assertEqual(search_evidence(self.store, self.alice, 'rareword')['results'], [])
        prompt, _ = assemble_prompt(self.store, self.alice, 'b', 'followup',
                                    'New synthetic question', TinySource().tokenize)
        self.assertNotIn('Synthetic repeated claim', prompt)
        self.assertEqual(self.store.read_turn(self.alice, 'c', 'claim')['status'], 'complete')

    def test_cycle_group_deletion_blocks_external_dependents_and_replays(self):
        for conv in ('a', 'b', 'outside'):
            self.store.create_conversation(self.alice, conv)
        self.completed('a', 'start', 'First synthetic source')
        self.source('ref-a', ('a', 'start'))
        self.completed('b', 'start', 'Second synthetic source')
        self.completed('b', 'quote', 'Quote A', parent='start', reference='ref-a')
        self.source('ref-b', ('b', 'quote'))
        self.completed('a', 'quote', 'Quote B', parent='start', reference='ref-b')
        self.completed('outside', 'quote', 'Other dependent', reference='ref-a')
        snapshot = Path(self.directory.name) / 'cycle-snapshot'
        backup(self.store, snapshot)

        for conv in ('a', 'b'):
            with self.assertRaisesRegex(ValueError, 'dependent conversations'):
                self.ledger.delete_conversation(self.store, self.alice, conv)
        with self.assertRaisesRegex(ValueError, 'dependent conversations'):
            self.ledger.delete_conversations(self.store, self.alice, ['a', 'b'])
        self.ledger.delete_conversation(self.store, self.alice, 'outside')
        self.ledger.delete_conversations(self.store, self.alice, ['a', 'b'])
        for conv in ('a', 'b', 'outside'):
            with self.assertRaises(KeyError):
                self.store._conversation('alice', conv)
        for conv in ('a', 'b'):
            with self.assertRaisesRegex(ValueError, 'cannot be reused'):
                self.store.create_conversation(self.alice, conv)

        target = 'kat_m2_restored_' + uuid4().hex[:12]
        dsn = make_conninfo(self.admin_dsn, dbname=target)
        with psycopg.connect(self.admin_dsn, autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
        restored = None
        try:
            restored = restore(snapshot, dsn, Path(self.directory.name) / 'restored', self.ledger)
            alice = restored.authenticate('alice', 'synthetic-password-alice')
            self.assertEqual(restored.list_conversations(alice), [])
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as db:
                db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))

    def test_stale_keyword_candidates_do_not_hide_older_current_passage(self):
        refs = self.source('current')
        self.store.create_conversation(self.alice, 'source-thread')
        self.completed('source-thread', 'source', 'Synthetic source')
        refs.add_source(self.alice, 'stale', 'Synthetic author', 'Superseded note',
                        'first', 'western', 'solar', 'local fixture', 'synthetic rights',
                        source=('source-thread', 'source'))
        for index in range(121):
            refs.add_passage(self.alice, 'stale', f'old-{index:03}', 'one',
                             'A rareword synthetic claim now withdrawn.')
        correct(self.store, self.alice, 'source-thread', 'withdraw', 'source', 'withdraw')

        result = search_evidence(self.store, self.alice, 'rareword')
        self.assertEqual(result['evidence_status'], 'keyword_matches')
        self.assertEqual([(row['source_id'], row['passage_id']) for row in result['results']],
                         [('current', 'p')])
        self.assertFalse(result['reference_scan_truncated'])

        for index in range(121, 1201):
            refs.add_passage(self.alice, 'stale', f'old-{index:04}', 'one',
                             'A rareword synthetic claim now withdrawn.')
        bounded = search_evidence(self.store, self.alice, 'rareword')
        self.assertEqual(bounded['results'], [])
        self.assertEqual(bounded['evidence_status'], 'incomplete_candidate_scan')
        self.assertTrue(bounded['reference_scan_truncated'])
