from pathlib import Path
from unittest.mock import patch
import os
import select
import subprocess
import sys
import psycopg
import swisseph as swe

from m2.gateway import run_turn
from m2.recall import rebuild_pending, search
from m2.test_support import DatabaseCase
from m2.store import Store


class TinySource:
    def __init__(self):
        self.invocations = 0
        self.prompts = []

    def tokenize(self, text, **kwargs):
        return text.split()

    def create_completion(self, prompt, **kwargs):
        self.invocations += 1
        self.prompts.append(prompt)
        yield {'choices': [{'text': 'Synthetic reply', 'finish_reason': None}]}
        yield {'choices': [{'text': '', 'finish_reason': 'stop'}]}


class GatewayTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        swe.set_ephe_path(str((Path(__file__).resolve().parents[1] / '.local/ephe').resolve()))

    def test_tool_and_output_committed_before_inference_and_delivery(self):
        self.store.create_conversation(self.alice, 'thread')
        class CheckedSource(TinySource):
            def create_completion(inner, prompt, **kwargs):
                with psycopg.connect(self.dsn) as other:
                    rows = other.execute('''
                        SELECT kind FROM events WHERE owner_id='alice' AND conversation_id='thread'
                        AND turn_id='turn' ORDER BY sequence
                    ''').fetchall()
                self.assertEqual([r[0] for r in rows], ['user', 'tool_call', 'tool_result', 'context'])
                yield from super().create_completion(prompt, **kwargs)

        model = CheckedSource()
        delivered = []
        def deliver(event):
            with psycopg.connect(self.dsn) as other:
                saved = other.execute('''
                    SELECT kind FROM events WHERE owner_id='alice' AND conversation_id='thread'
                    AND turn_id='turn' AND sequence=%s
                ''', (event['sequence'],)).fetchone()
            self.assertEqual(saved[0], event['kind'])
            delivered.append(event)

        acknowledgements = []
        def acknowledge(value):
            with psycopg.connect(self.dsn) as reader:
                self.assertEqual(reader.execute('''
                    SELECT kind FROM events WHERE owner_id='alice' AND conversation_id='thread'
                    AND turn_id='turn' AND sequence=0
                ''').fetchone()[0], 'user')
            acknowledgements.append(value)

        status = run_turn(self.store, self.alice, 'thread', 'turn',
                          'solar longitude at 2024-03-20T03:06:00+00:00', model, deliver,
                          acknowledge=acknowledge)
        self.assertEqual(acknowledgements[0]['acknowledged'], True)
        self.assertEqual(status, 'complete')
        self.assertEqual(model.invocations, 1)
        self.assertEqual([e['kind'] for e in delivered],
                         ['tool_call', 'tool_result', 'context', 'assistant_chunk', 'complete'])
        self.assertAlmostEqual(delivered[1]['payload']['longitude_degrees'], 359.9997223853829, places=5)
        before = self.store.read_turn(self.alice, 'thread', 'turn')['events']
        with patch('m2.gateway.solar_longitude', side_effect=AssertionError('tool was rerun')):
            run_turn(self.store, self.alice, 'thread', 'turn',
                     'solar longitude at 2024-03-20T03:06:00+00:00', model, lambda _: None)
        self.assertEqual(model.invocations, 1)
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'turn')['events'], before)
        self.assertEqual(rebuild_pending(self.store, self.alice), 1)
        self.assertEqual(search(self.store, self.alice, 'solar')['results'][0]['source_id'], 'turn')

    def test_postgresql_stream_write_refusal_never_delivers_unsaved_chunk(self):
        self.store.create_conversation(self.alice, 'thread')
        class TwoChunks(TinySource):
            def create_completion(inner, prompt, **kwargs):
                inner.invocations += 1
                yield {'choices': [{'text': 'saved', 'finish_reason': None}]}
                yield {'choices': [{'text': 'unsaved', 'finish_reason': None}]}
                yield {'choices': [{'text': '', 'finish_reason': 'stop'}]}
        model = TwoChunks()
        delivered = []
        def deliver(event):
            delivered.append(event)
            if event['kind'] == 'assistant_chunk':
                self.store.db.execute('SET default_transaction_read_only = on')
        try:
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                run_turn(self.store, self.alice, 'thread', 'midstream', 'Synthetic',
                         model, deliver)
        finally:
            self.store.db.execute('SET default_transaction_read_only = off')
        self.assertEqual([event['kind'] for event in delivered], ['context', 'assistant_chunk'])
        self.assertEqual([e['payload'].get('content') for e in self.store.read_turn(
            self.alice, 'thread', 'midstream')['events'] if e['kind'] == 'assistant_chunk'],
                         ['saved'])
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'midstream')['status'], 'open')
        self.assertEqual(self.store.recover_open(), 1)
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'midstream')['status'], 'interrupted')
        run_turn(self.store, self.alice, 'thread', 'midstream', 'Synthetic', model,
                 lambda _: None)
        self.assertEqual(model.invocations, 1)

    def test_actual_process_kill_recovery_preserves_delivered_prefix(self):
        self.store.create_conversation(self.alice, 'crash-thread')
        self.store.close()  # transfer exclusive database ownership to the child
        child_script = '''
import os, time
from m2.deletion import Tombstones
from m2.gateway import run_turn
from m2.store import Store
class Model:
    def tokenize(self, text, **kwargs): return text.split()
    def create_completion(self, prompt, **kwargs):
        yield {'choices':[{'text':'Durable prefix','finish_reason':None}]}
        time.sleep(60)
        yield {'choices':[{'text':'','finish_reason':'stop'}]}
with Store(os.environ['KAT_FIXTURE_DSN'], os.environ['KAT_FIXTURE_FILES'],
           Tombstones(os.environ['KAT_FIXTURE_LEDGER'])) as store:
    session=store.authenticate('alice','synthetic-password-alice')
    run_turn(store,session,'crash-thread','killed','Synthetic',Model(),
             lambda event: print(event['kind'],flush=True) if event['kind']=='assistant_chunk' else None)
'''
        env = dict(os.environ, KAT_FIXTURE_DSN=self.dsn,
                   KAT_FIXTURE_FILES=str(Path(self.directory.name) / 'files'),
                   KAT_FIXTURE_LEDGER=str(self.ledger.path))
        child = subprocess.Popen([sys.executable, '-c', child_script],
                                 cwd=Path(__file__).resolve().parents[1], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([child.stdout], [], [], 15)[0],
                            'Owned child did not deliver the prefix')
            self.assertEqual(child.stdout.readline().strip(), 'assistant_chunk')
            child.kill()
            child.wait(timeout=5)
            self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)
            self.assertEqual(self.store.recover_open(), 1)
            self.alice = self.store.authenticate('alice', 'synthetic-password-alice')
            turn = self.store.read_turn(self.alice, 'crash-thread', 'killed')
            self.assertEqual(turn['status'], 'interrupted')
            self.assertEqual([e['kind'] for e in turn['events'][-2:]],
                             ['assistant_chunk', 'interrupted'])
            model = TinySource()
            run_turn(self.store, self.alice, 'crash-thread', 'killed', 'Synthetic', model,
                     lambda _: None, parent_id='@root')
            self.assertEqual(model.invocations, 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()
            if self.store.db.closed:
                self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)

    def test_long_stored_retry_is_paginated_without_truncating_original_events(self):
        self.store.create_conversation(self.alice, 'long')
        self.store.begin(self.alice, 'long', 'many', 'Synthetic')
        for index in range(260):
            self.store.append(self.alice, 'long', 'many', 'assistant_chunk',
                              {'content': f'part-{index}'})
        self.store.append(self.alice, 'long', 'many', 'complete', {})
        self.assertEqual(len(self.store.read_turn(self.alice, 'long', 'many')['events']), 256)
        self.assertEqual(self.store.read_turn(self.alice, 'long', 'many')['next_event_offset'], 256)
        delivered = []
        model = TinySource()
        run_turn(self.store, self.alice, 'long', 'many', 'Synthetic', model, delivered.append,
                 parent_id='@root')
        self.assertEqual(len(delivered), 261)
        self.assertEqual(delivered[-1]['kind'], 'complete')
        self.assertEqual(model.invocations, 0)
        from m2.recall import rebuild_pending
        self.assertEqual(rebuild_pending(self.store, self.alice), 1)
        from m2.recall import current_text
        text = current_text(self.store, self.alice, 'long', 'many')
        self.assertIn('part-259', text)
        from m2.compaction import turn_text
        self.assertIn('part-259', turn_text(self.store, self.alice, 'long', 'many', {'long': {'many'}}, {}))
        self.store.close()
        self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)
        self.alice = self.store.authenticate('alice', 'synthetic-password-alice')
        self.assertIn('part-259', current_text(self.store, self.alice, 'long', 'many'))
        self.assertEqual(self.store.read_turn(self.alice, 'long', 'many')['event_count'], 262)

    def test_large_single_output_delta_archives_contiguous_utf8_chunks(self):
        class LargeDelta(TinySource):
            def create_completion(self, prompt, **kwargs):
                self.invocations += 1
                yield {'choices': [{'text': 'ø' * 12000, 'finish_reason': None}]}
                yield {'choices': [{'text': '', 'finish_reason': 'stop'}]}
        self.store.create_conversation(self.alice, 'large-output')
        model = LargeDelta()
        self.assertEqual(run_turn(self.store, self.alice, 'large-output', 'answer', 'Synthetic',
                                  model, lambda _: None, parent_id='@root'), 'complete')
        chunks = [event['payload']['content'] for event in self.store.read_turn(
            self.alice, 'large-output', 'answer')['events'] if event['kind'] == 'assistant_chunk']
        self.assertEqual(''.join(chunks), 'ø' * 12000)
        self.assertTrue(all(len(chunk.encode('utf-8')) <= 8192 for chunk in chunks))

    def test_cancel_restart_storage_refusal_and_no_reexecution(self):
        self.store.create_conversation(self.alice, 'thread')
        model = TinySource()
        events = []
        run_turn(self.store, self.alice, 'thread', 'cancel', 'Synthetic', model,
                 events.append, cancel_after=1)
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'cancel')['status'], 'interrupted')
        self.assertEqual(model.invocations, 1)
        self.store.begin(self.alice, 'thread', 'crash', 'Synthetic crash')
        self.store.append(self.alice, 'thread', 'crash', 'assistant_chunk', {'content': 'durable prefix'})
        self.store.close()
        self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)
        self.assertEqual(self.store.recover_open(), 1)
        self.alice = self.store.authenticate('alice', 'synthetic-password-alice')
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'crash')['status'], 'interrupted')
        run_turn(self.store, self.alice, 'thread', 'crash', 'Synthetic crash', model, lambda _: None,
                 parent_id='@root')
        self.assertEqual(model.invocations, 1)

        self.store.db.execute('SET default_transaction_read_only = on')
        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            run_turn(self.store, self.alice, 'thread', 'refused', 'Synthetic', model, lambda _: None)
        self.store.db.execute('SET default_transaction_read_only = off')
        self.assertEqual(model.invocations, 1)
        with self.assertRaises(KeyError):
            self.store.read_turn(self.alice, 'thread', 'refused')


if __name__ == '__main__':
    import unittest
    unittest.main()
