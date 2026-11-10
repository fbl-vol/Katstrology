"""Deletion fences input identity, including uncompleted/enqueue-later input."""
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.archive.backup import backup, restore
from m2.archive.revisions import correct
from m2.chat.personal_context import set_preference
from m2.people.people import People
from m2.people.personal_context import PersonalContext
from tests.people.test_personal_context import fact
from tests.support.database import DatabaseCase


class MemorySuppressionTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        People(self.store).charts.add_person(self.alice, 'frederik', 'Frederik')
        self.store.create_conversation(self.alice, 'thread')
        set_preference(self.store, self.alice, True, 0)
        self.context = PersonalContext(self.store)
        self.context.save(self.alice, 'frederik', 'fact', 'manual', 0, fact())

    def begin(self, turn):
        # Only presence is needed at input commit; no synthetic provider is invoked.
        self.store.memory_origins[('alice', 'thread', turn)] = {}
        self.store.begin(self.alice, 'thread', turn, 'Frederik gardens.', None)
        self.store.memory_origins.pop(('alice', 'thread', turn))
        return self.store.db.execute('''SELECT id FROM memory_source_units
            WHERE owner_id='alice' AND conversation_id='thread' AND turn_id=%s''', (turn,)).fetchone()['id']

    def test_delete_fences_already_committed_input_before_enqueue(self):
        old = self.begin('pending')
        self.context.remove(self.alice, 'frederik', 'fact', 1)
        cutoff = self.store.db.execute('SELECT source_before FROM memory_source_suppressions').fetchone()['source_before']
        self.assertEqual(cutoff, old)
        self.store.append(self.alice, 'thread', 'pending', 'complete', {})
        self.assertGreater(self.begin('new'), cutoff)
        record = list(self.ledger._records())[-1]
        self.assertEqual(set(record), {'owner', 'person', 'context_entry', 'source_before'})
        self.assertEqual(record['source_before'], str(old))
        self.assertNotIn('gardens', str(record))

    def test_reconciliation_restores_barrier_and_advances_older_sequence(self):
        first = self.begin('one')
        self.store.append(self.alice, 'thread', 'one', 'interrupted', {})
        latest = self.begin('two')
        self.context.remove(self.alice, 'frederik', 'fact', 1)
        self.store.db.execute('DELETE FROM memory_source_suppressions')
        self.store.db.execute('DELETE FROM memory_source_units')
        self.store.db.execute("SELECT setval('memory_source_units_id_seq',%s)", (first,))
        self.ledger.reconcile(self.store)
        self.assertEqual(self.store.db.execute('SELECT source_before FROM memory_source_suppressions').fetchone()['source_before'], latest)
        self.store.append(self.alice, 'thread', 'two', 'interrupted', {})
        self.assertGreater(self.begin('after-restore'), latest)

    def test_old_backup_replays_new_cutoff_before_any_new_input(self):
        self.begin('one')
        self.store.append(self.alice, 'thread', 'one', 'complete', {})
        archive = Path(self.directory.name) / 'memory-snapshot'
        backup(self.store, archive)
        cutoff = self.begin('two')
        self.context.remove(self.alice, 'frederik', 'fact', 1)
        target = 'kat_person_restore_' + uuid4().hex[:12]
        dsn = make_conninfo(self.admin_dsn, dbname=target)
        with psycopg.connect(self.admin_dsn, autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
        restored = None
        try:
            restored = restore(archive, dsn, Path(self.directory.name) / 'restored', self.ledger)
            session = restored.authenticate('alice', 'synthetic-password-alice')
            self.assertEqual(PersonalContext(restored).list(session, 'frederik')['entries'], [])
            self.assertEqual(restored.db.execute('SELECT source_before FROM memory_source_suppressions').fetchone()['source_before'], cutoff)
            restored.memory_origins[('alice', 'thread', 'after-restore')] = {}
            restored.begin(session, 'thread', 'after-restore', 'Frederik enjoys painting.', 'one')
            newest = restored.db.execute('SELECT max(id) AS id FROM memory_source_units').fetchone()['id']
            self.assertGreater(newest, cutoff)
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as db:
                db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))

    def test_merged_entry_invalidates_when_a_nonprimary_conversation_source_is_withdrawn(self):
        self.begin('one')
        self.store.append(self.alice, 'thread', 'one', 'complete', {})
        self.store.create_conversation(self.alice, 'other')
        self.store.begin(self.alice, 'other', 'one', 'Frederik also paints.', None)
        self.store.append(self.alice, 'other', 'one', 'complete', {})
        earlier = {'kind': 'conversation', 'conversation_id': 'thread', 'turn_id': 'one', 'revision': 0}
        primary = {'kind': 'conversation', 'conversation_id': 'other', 'turn_id': 'one', 'revision': 0}
        self.context.save(self.alice, 'frederik', 'fact', 'merge', 1, fact(title='Combined'),
                          {**primary, 'sources': [earlier, primary]})
        self.assertEqual(len(self.context.list(self.alice, 'frederik')['entries']), 1)
        correct(self.store, self.alice, 'thread', 'withdraw', 'one', 'withdraw')
        self.assertEqual(self.context.list(self.alice, 'frederik')['entries'], [])

    def test_manual_edit_then_delete_does_not_lose_the_input_barrier(self):
        source = self.begin('one')
        self.context.save(self.alice, 'frederik', 'fact', 'edited', 1, fact(title='My manual wording'))
        self.context.remove(self.alice, 'frederik', 'fact', 2)
        barrier = self.store.db.execute('SELECT owner_id,person_id,source_before FROM memory_source_suppressions').fetchone()
        self.assertEqual(barrier, {'owner_id': 'alice', 'person_id': 'frederik', 'source_before': source})
        self.assertEqual(self.context.list(self.alice, 'frederik')['entries'], [])
