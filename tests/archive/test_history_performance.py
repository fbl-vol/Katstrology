"""Bounded history pages and scheduled, epoch-fenced derived search."""

import asyncio
from unittest.mock import patch

from m2.chat.chat_jobs import ChatJobs
from m2.archive.conversations import Conversations
from m2.chat.recall import search
from m2.archive.revisions import correct, select_branch
from tests.support.database import DatabaseCase


class CountingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.queries = 0

    def execute(self, *args, **kwargs):
        self.queries += 1
        return self.connection.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class HistoryPerformanceTests(DatabaseCase):
    def complete(self, turn_id, parent=None):
        self.store.begin(self.alice, 'thread', turn_id, f'Input {turn_id}', parent)
        self.store.append(self.alice, 'thread', turn_id, 'assistant_chunk', {'content': f'Reply {turn_id}'})
        self.store.append(self.alice, 'thread', turn_id, 'complete', {})

    def test_batched_page_preserves_branch_scope_corrections_and_event_cursor(self):
        self.store.create_conversation(self.alice, 'thread')
        parent = None
        for number in range(24):
            turn_id = f't{number:02}'
            self.complete(turn_id, parent)
            parent = turn_id
        # The first page must still identify the active branch after switching to a sibling.
        self.complete('branch', 't03')
        # Append-only events cannot follow a terminal event; use a separate open turn
        # with a long recorded read round before completing it.
        self.store.begin(self.alice, 'thread', 'long', 'Long input', 'branch')
        for number in range(36):
            self.store.append(self.alice, 'thread', 'long', 'context', {'part': number})
        self.store.append(self.alice, 'thread', 'long', 'complete', {})
        correct(self.store, self.alice, 'thread', 'correction', 't12', 'correct', 'Adjusted input')
        meter = CountingConnection(self.store.db)
        self.store.db = meter
        try:
            first = Conversations(self.store).turns(self.alice, 'thread')
            self.assertLessEqual(meter.queries, 8)
            meter.queries = 0
            for turn in first['turns']:
                self.store.read_turn(self.alice, 'thread', turn['id'], event_limit=32)
            self.assertGreaterEqual(meter.queries, 100)  # Comparable 20-turn shape, not a latency claim.
            meter.queries = 0
            second = Conversations(self.store).turns(self.alice, 'thread', offset=20)
            self.assertLessEqual(meter.queries, 8)
        finally:
            self.store.db = meter.connection
        self.assertEqual(len(first['turns']), 20)
        self.assertEqual(first['next_offset'], 20)
        self.assertEqual(len(second['turns']), 6)
        self.assertIsNone(second['next_offset'])
        self.assertFalse(first['turns'][4]['on_active_branch'])
        self.assertEqual(first['turns'][12]['corrections'][0]['replacement'], 'Adjusted input')
        self.assertTrue(second['turns'][-1]['on_active_branch'])
        long = second['turns'][-1]
        saved = self.store.read_turn(self.alice, 'thread', 'long', event_limit=32)
        for field in ('event_count', 'events', 'selected_people', 'corrections', 'next_event_offset'):
            self.assertEqual(long[field], saved[field])
        self.assertEqual(long['next_event_offset'], 32)
        self.assertEqual(long['event_count'], 38)

    def test_ancestry_uses_constant_queries_and_rejects_corrupt_or_overdeep_chains(self):
        self.store.create_conversation(self.alice, 'thread')
        parent = None
        for number in range(24):
            turn_id = f't{number:02}'
            self.complete(turn_id, parent)
            parent = turn_id
        meter = CountingConnection(self.store.db)
        self.store.db = meter
        try:
            self.assertEqual(self.store.ancestry(self.alice, 'thread', parent),
                             [f't{number:02}' for number in range(24)])
            self.assertLessEqual(meter.queries, 2)
            with patch('m2.archive.store.MAX_ANCESTORS', 12):
                with self.assertRaisesRegex(ValueError, 'depth or cycle'):
                    self.store.ancestry(self.alice, 'thread', parent)
            self.store.db.execute('''
                UPDATE turns SET parent_id='t23' WHERE owner_id=%s
                  AND conversation_id='thread' AND id='t00'
            ''', (self.alice.owner_id,))
            with self.assertRaisesRegex(ValueError, 'depth or cycle'):
                self.store.ancestry(self.alice, 'thread', parent)
            self.store.db.execute('''
                UPDATE turns SET parent_id=NULL WHERE owner_id=%s
                  AND conversation_id='thread' AND id='t00'
            ''', (self.alice.owner_id,))
            self.store.db.execute('''
                UPDATE turns SET status='interrupted' WHERE owner_id=%s
                  AND conversation_id='thread' AND id='t00'
            ''', (self.alice.owner_id,))
            with self.assertRaisesRegex(ValueError, 'Incomplete or absent'):
                self.store.ancestry(self.alice, 'thread', parent)
        finally:
            self.store.db = meter.connection

    def test_scheduled_rebuild_reports_pending_and_uses_current_epoch(self):
        self.store.create_conversation(self.alice, 'thread')
        self.complete('first')

        class Runtime:
            spawn = staticmethod(asyncio.create_task)

            def __init__(self, store):
                self.store = store

            async def execute(self, operation):
                return operation()

        async def scenario():
            jobs = ChatJobs(Runtime(self.store))
            jobs._schedule_rebuild(self.alice, 'thread')
            pending = search(self.store, self.alice, 'Input')
            self.assertEqual(pending['pending_conversations'], 1)
            jobs._schedule_rebuild(self.alice, 'thread')
            self.assertEqual(len(jobs.rebuilds), 1)
            # A newer committed head before the task runs must be indexed, not
            # a stale snapshot of the queued epoch.
            self.complete('second', 'first')
            await next(iter(jobs.rebuilds.values()))
            current = search(self.store, self.alice, 'Input')
            self.assertEqual(current['pending_conversations'], 0)
            self.assertEqual({row['source_id'] for row in current['results']}, {'first', 'second'})
            correct(self.store, self.alice, 'thread', 'fix-first', 'first', 'correct', 'Corrected source')
            self.assertEqual(search(self.store, self.alice, 'Input')['results'], [])
            jobs._schedule_rebuild(self.alice, 'thread')
            await jobs.rebuilds[self.alice.owner_id, 'thread']
            corrected = search(self.store, self.alice, 'Corrected')
            self.assertEqual([row['source_id'] for row in corrected['results']], ['fix-first'])
            select_branch(self.store, self.alice, 'thread', 'first')
            self.assertEqual(search(self.store, self.alice, 'Corrected')['results'], [])
            jobs._schedule_rebuild(self.alice, 'thread')
            await jobs.rebuilds[self.alice.owner_id, 'thread']
            correct(self.store, self.alice, 'thread', 'withdraw-first', 'first', 'withdraw')
            jobs._schedule_rebuild(self.alice, 'thread')
            await jobs.rebuilds[self.alice.owner_id, 'thread']
            self.assertEqual(search(self.store, self.alice, 'Corrected')['results'], [])
            self.assertEqual(search(self.store, self.alice, 'Corrected')['pending_conversations'], 0)

        asyncio.run(scenario())
