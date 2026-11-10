"""Small durable reference queue, coalescing and no paid-attempt replay."""
from unittest.mock import patch

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
        self.store.begin(self.alice, 'thread', turn, 'Frederik enjoys gardening.', parent)
        self.store.memory_origins[('alice', 'thread', turn)] = self.origin
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

    def test_ambiguous_attempt_is_not_retried_after_recovery(self):
        set_preference(self.store, self.alice, True, 0)
        self.complete('one')
        work = self.work.due()
        self.assertTrue(self.work.claim(work))
        self.assertFalse(self.work.claim(work))
        self.work.recover_interrupted()
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
