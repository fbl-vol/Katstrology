"""Small durable reference queue, coalescing and no paid-attempt replay."""
from pathlib import Path
import shutil
from unittest.mock import patch

import psycopg

from deploy.prepare_migration import prepare
from m2.release_schema import migrate
from m2.archive.store import Store
from m2.chat.memory_work import MemoryWork
from m2.chat.personal_context import set_preference
from m2.provider.model_capacity import CatalogAdmission, resolve_capacity
from tests.support.database import DatabaseCase


class MemoryWorkTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.store.create_conversation(self.alice, 'thread')
        self.work = MemoryWork(self.store)
        self.origin = {'session_digest': 'synthetic-session', 'admission': CatalogAdmission(
            'alice', 'gpt-6-luna', 'synthetic-binding', resolve_capacity({'slug': 'gpt-6-luna'}))}

    def complete(self, turn, parent=None):
        self.store.memory_origins[('alice', 'thread', turn)] = self.origin
        self.store.begin(self.alice, 'thread', turn, 'Frederik enjoys gardening.', parent)
        if parent is None:
            self.assertIsNone(self.work.due())
        self.store.append(self.alice, 'thread', turn, 'complete', {})
        self.store.memory_origins.pop(('alice', 'thread', turn))

    def test_no_consent_and_revoked_snapshot_are_not_queued(self):
        self.complete('off')
        self.assertIsNone(self.work.due())
        set_preference(self.store, self.alice, True, 0)
        self.store.begin(self.alice, 'thread', 'revoked', 'Frederik gardens.', 'off')
        initial = self.store.read_turn(self.alice, 'thread', 'revoked')['events'][0]['payload']
        set_preference(self.store, self.alice, False, 1)
        self.store.append(self.alice, 'thread', 'revoked', 'complete', {})
        self.work.enqueue(self.alice, 'thread', 'revoked', initial, self.origin)
        self.assertIsNone(self.work.due())

    def test_nearby_turns_coalesce_and_same_turn_is_idempotent(self):
        set_preference(self.store, self.alice, True, 0)
        self.complete('one')
        self.complete('two', 'one')
        work = self.work.due()
        self.assertEqual((work['turn_id'], work['generation']), ('two', 2))
        self.assertGreater(work['delay'], 0)
        initial = self.store.read_turn(self.alice, 'thread', 'two')['events'][0]['payload']
        self.work.enqueue(self.alice, 'thread', 'two', initial, self.origin)
        self.assertEqual(self.work.due()['generation'], 2)
        self.assertNotIn('prompt', work)
        first = self.store.db.execute("SELECT id FROM memory_source_units WHERE turn_id='one'").fetchone()['id']
        self.assertEqual(work['pending_source_unit'], first)

    def test_preclaim_deferral_rotates_owners_without_claim_or_new_generation(self):
        set_preference(self.store, self.alice, True, 0)
        self.complete('one')
        work = self.work.due()
        self.store.create_conversation(self.bob, 'other')
        set_preference(self.store, self.bob, True, 0)
        self.store.memory_origins[('bob', 'other', 'two')] = {
            'session_digest': 'synthetic-bob', 'admission': CatalogAdmission(
                'bob', 'gpt-6-luna', 'synthetic-bob-binding', self.origin['admission'].capacity)}
        self.store.begin(self.bob, 'other', 'two', 'Synthetic pending input.', None)
        self.store.append(self.bob, 'other', 'two', 'complete', {})
        self.store.db.execute("UPDATE memory_work SET queued_at=queued_at-interval '10 seconds'")
        self.assertEqual(self.work.due()['owner_id'], 'alice')
        self.work.defer(work)
        self.assertEqual(self.work.due()['owner_id'], 'bob')
        retained = self.store.db.execute("SELECT * FROM memory_work WHERE owner_id='alice'").fetchone()
        self.assertEqual((retained['generation'], retained['pending_source_unit'], retained['state']),
                         (work['generation'], work['pending_source_unit'], 'pending'))
        self.assertIsNone(retained['attempted_generation'])
        self.assertEqual(self.store.db.execute('SELECT count(*) AS count FROM memory_budget').fetchone()['count'], 0)
        self.complete('new', 'one')
        queued = self.store.db.execute("SELECT queued_at FROM memory_work WHERE owner_id='alice'").fetchone()
        self.work.defer(work)  # The obsolete generation must not delay genuinely new input.
        self.assertEqual(self.store.db.execute("SELECT queued_at FROM memory_work WHERE owner_id='alice'").fetchone(), queued)

    def test_ambiguous_attempt_is_not_retried_after_recovery(self):
        set_preference(self.store, self.alice, True, 0)
        self.complete('one')
        work = self.work.due()
        self.assertTrue(self.work.claim(work))
        self.assertFalse(self.work.claim(work))
        files = self.store.files
        self.store.close()
        self.store = Store(self.dsn, files, self.ledger)
        self.work = MemoryWork(self.store)
        self.assertIsNone(self.work.due())
        row = self.store.db.execute('SELECT state,outcome FROM memory_work').fetchone()
        self.assertEqual(row, {'state': 'idle', 'outcome': 'abandoned'})

    def test_newer_turn_survives_running_attempt_with_budget_delay(self):
        set_preference(self.store, self.alice, True, 0)
        self.complete('one')
        work = self.work.due()
        self.work.claim(work)
        self.complete('two', 'one')
        self.assertIsNone(self.work.due())
        self.work.finish(work, 'stale')
        newer = self.work.due()
        self.assertEqual(newer['turn_id'], 'two')
        self.assertGreater(newer['delay'], 290)
        self.assertEqual(newer['pending_source_unit'], work['pending_source_unit'])

    def test_newer_pending_work_survives_real_store_restart_without_replaying_attempt(self):
        set_preference(self.store, self.alice, True, 0)
        self.complete('one')
        self.work.claim(self.work.due())
        self.complete('two', 'one')
        files = self.store.files
        self.store.close()
        self.store = Store(self.dsn, files, self.ledger)
        latest = MemoryWork(self.store).due()
        self.assertEqual((latest['turn_id'], latest['state'], latest['outcome']),
                         ('two', 'pending', 'abandoned'))
        self.assertGreater(latest['delay'], 290)
        first = self.store.db.execute("SELECT id FROM memory_source_units WHERE turn_id='one'").fetchone()['id']
        self.assertGreater(latest['pending_source_unit'], first)

    def test_failed_paid_range_is_not_restored_for_newer_question(self):
        set_preference(self.store, self.alice, True, 0)
        self.complete('one')
        claimed = self.work.due()
        self.work.claim(claimed)
        self.complete('two', 'one')
        self.work.finish(claimed, 'failed')
        self.assertGreater(self.work.due()['pending_source_unit'], claimed['pending_source_unit'])

    def test_no_new_generation_never_retries_even_known_unapplied_result(self):
        set_preference(self.store, self.alice, True, 0)
        self.complete('one')
        claimed = self.work.due()
        self.work.claim(claimed)
        self.work.finish(claimed, 'stale')
        self.assertIsNone(self.work.due())
        self.complete('two', 'one')
        self.assertGreater(self.work.due()['pending_source_unit'], claimed['pending_source_unit'])

    def test_exact_nullable_lane_preserves_legacy_pending_row_without_backfill(self):
        set_preference(self.store, self.alice, True, 0)
        self.complete('one')
        self.complete('two', 'one')
        retained = self.store.db.execute(
            "SELECT to_jsonb(w)-'pending_source_unit' AS value FROM memory_work w").fetchone()['value']
        self.store.close()
        # Reconstruct schema36 only in this freshly owned disposable database,
        # retaining every legacy row/column. Never a live rollback operation.
        with psycopg.connect(self.dsn) as db:
            db.execute('ALTER TABLE memory_work DROP COLUMN pending_source_unit')
            db.execute('DELETE FROM schema_migrations WHERE version=37')
        migrations = Path(__file__).resolve().parents[2] / 'm2/migrations'
        before = Path(self.directory.name) / 'schema36'
        before.mkdir()
        for file in migrations.glob('[0-9]*.sql'):
            if int(file.name.split('_')[0]) <= 36:
                shutil.copyfile(file, before / file.name)
        lane = prepare(before, migrations)['lane']
        self.assertEqual(lane['added_columns'], {'memory_work': ['pending_source_unit']})
        self.assertEqual(migrate(self.dsn, lane, migrations), {'schema': 37, 'status': 'migrated'})
        with psycopg.connect(self.dsn) as db:
            row = db.execute("SELECT to_jsonb(w)-'pending_source_unit',pending_source_unit FROM memory_work w").fetchone()
            self.assertEqual(row, (retained, None))
        self.store = Store(self.dsn, self.store.files, self.ledger)
        self.work = MemoryWork(self.store)
        self.assertIsNone(self.work.due()['pending_source_unit'])

    def test_queue_failure_does_not_roll_back_completed_answer(self):
        set_preference(self.store, self.alice, True, 0)
        with patch.object(MemoryWork, 'enqueue', side_effect=RuntimeError('synthetic failure')):
            self.complete('one')
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'one')['status'], 'complete')
        self.assertIsNone(self.work.due())

    def test_reference_cascades_with_conversation_deletion(self):
        set_preference(self.store, self.alice, True, 0)
        self.complete('one')
        self.store.ledger.delete_conversation(self.store, self.alice, 'thread')
        self.assertIsNone(self.work.due())
