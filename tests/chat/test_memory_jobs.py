"""Real runtime/Store and dedicated blocked background provider, entirely synthetic."""
import asyncio
import json
from threading import Event, current_thread
from time import monotonic, sleep

from m2.chat.memory_analysis import INSTRUCTIONS
from tests.http_boundary.test_web_chat import ChatHttpFixture


class MemoryJobsFixture(ChatHttpFixture):
    def setUp(self):
        super().setUp()
        self.post('/api/personal-context-preference', {'enabled': True, 'expected_version': 0})
        self.person = self.post('/api/people', {'name': 'Frederik'}).json()['id']
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic memory', 'people': []})
        self.entered, self.release = Event(), Event()
        self.background_thread = None
        self.background_calls = 0
        self.action_transform = lambda action, evidence: action
        original = self.transport.response_events

        def response(token, body, *, bounded=False):
            if body.get('instructions') != INSTRUCTIONS:
                yield from original(token, body, bounded=bounded)
                return
            self.background_calls += 1
            self.background_thread = current_thread().name
            self.assertTrue(bounded)
            self.assertEqual(body['model'], 'gpt-6-luna')
            self.assertFalse(body['store'])
            self.assertTrue(body['stream'])
            self.assertNotIn('tools', body)
            evidence = json.loads(body['input'][0]['content'][0]['text'])
            message = evidence['messages'][-1]
            text = message['text']
            action = {'person_id': self.person, 'entry_id': None, 'expected_version': 0,
                'intent': 'add', 'group': 'interests', 'assessment': 'asserted', 'attribution': 'named',
                'identity_turn_id': message['turn_id'], 'statements': [{'turn_id': message['turn_id'],
                    'start': 0, 'end': len(text), 'text': text}], 'state': None, 'date': None}
            action = self.action_transform(action, evidence)
            yield {'type': 'response.output_text.delta', 'delta': json.dumps({'actions': [action]})}, 'synthetic-memory'
            self.entered.set()
            if not self.release.wait(15):
                raise RuntimeError('Synthetic memory watchdog')
            yield {'type': 'response.completed'}, 'synthetic-memory'
        self.transport.response_events = response

    def tearDown(self):
        self.release.set()
        super().tearDown()

    def start_memory(self, turn='source', text='Frederik enjoys gardening.', before_analysis=None):
        before = self.background_calls
        self.entered.clear()
        self.release.clear()
        response = self.post('/api/conversations/thread/turns', self.message(turn, text))
        self.assertEqual(response.status_code, 202, response.text)
        events = self.events(turn)
        self.assertEqual(events[-1]['kind'], 'complete')
        self.assertEqual(self.background_calls, before)
        if before_analysis is not None:
            before_analysis()
        runtime = self.app.state.runtime

        async def due():
            async with asyncio.timeout(5):
                while not runtime.chat.jobs[('alice', 'thread', turn)].finished:
                    await asyncio.sleep(0.001)
            await runtime.execute(lambda: runtime.store.db.execute(
                "UPDATE memory_work SET queued_at=clock_timestamp()-interval '5 seconds'"))
            await runtime.execute(lambda: runtime.store.db.execute(
                "UPDATE memory_budget SET next_attempt_at=clock_timestamp()-interval '5 minutes'"))
            runtime.memory.notify(0)
        self.client.portal.call(due)
        self.assertTrue(self.entered.wait(5))
        self.assertTrue(self.background_thread.startswith('kat-memory'))
        return events

    def finish_memory(self):
        self.release.set()
        runtime = self.app.state.runtime
        deadline = monotonic() + 5
        while monotonic() < deadline:
            row = self.client.portal.call(runtime.call, lambda store, _: store.db.execute(
                "SELECT state,outcome FROM memory_work WHERE owner_id='alice' AND conversation_id='thread'").fetchone())
            if row['state'] == 'idle':
                return row['outcome']
            sleep(0.005)
        self.fail('Background attempt did not settle')

    def entries(self):
        response = self.client.get(f'/api/people/{self.person}/context')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['entries']


class MemoryJobsTests(MemoryJobsFixture):
    def test_completed_unselected_person_memory_is_quiet_and_owner_scoped(self):
        original = self.start_memory()
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.finish_memory(), 'saved')
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['content']['title'], 'Frederik enjoys gardening.')
        self.assertEqual(self.events('source'), original)
        foreground = next(call[2] for call in self.responses())
        self.assertNotIn('stage_personal_context', [tool.get('name') for tool in foreground['tools']])
        self.assertNotIn('offer Personal context settings to explicitly associate self', json.dumps(foreground['input']))
        self.assertEqual(original[0]['payload']['personal_context']['collection_mode'], 'background_v1')
        self.assertEqual(self.client.get('/api/personal-context-self').json()['person_id'], None)
        self.login('bob', 'synthetic-password-bob')
        self.assertEqual(self.client.get(f'/api/people/{self.person}/context').status_code, 404)

    def test_blocked_real_background_slot_does_not_block_next_ack_stream_store_or_stop(self):
        self.start_memory()
        self.assertFalse(self.release.is_set())
        foreground_entered, foreground_release = Event(), Event()
        original = self.transport.response_events

        def foreground(token, body, *, bounded=False):
            if body.get('instructions') != INSTRUCTIONS and 'A blocked foreground' in json.dumps(body['input']):
                for text in ('Foreground', ' stays live'):
                    yield {'type': 'response.output_text.delta', 'delta': text}, 'synthetic-foreground'
                foreground_entered.set()
                if not foreground_release.wait(15):
                    raise RuntimeError('Synthetic foreground watchdog')
                yield {'type': 'response.completed'}, 'synthetic-foreground'
            else:
                yield from original(token, body, bounded=bounded)
        self.transport.response_events = foreground
        try:
            response = self.post('/api/conversations/thread/turns', self.message('next', 'A blocked foreground question.'))
            self.assertEqual(response.status_code, 202, response.text)
            self.assertTrue(foreground_entered.wait(5))
            deadline = monotonic() + 5
            streamed = ''
            while monotonic() < deadline:
                events = self.client.get('/api/conversations/thread/turns/next').json()['events']
                streamed = ''.join(event['payload']['content'] for event in events if event['kind'] == 'assistant_chunk')
                if streamed == 'Foreground stays live':
                    break
                sleep(0.005)
            self.assertEqual(streamed, 'Foreground stays live')
            self.assertEqual(self.client.get('/api/people').status_code, 200)
            self.assertEqual(self.client.get('/api/conversations/thread').status_code, 200)
            stopped = self.post('/api/conversations/thread/turns/next/cancel')
            self.assertEqual(stopped.json()['status'], 'cancellation_requested')
            self.assertFalse(foreground_release.is_set())
            self.assertFalse(self.release.is_set())
        finally:
            foreground_release.set()
        self.assertEqual(self.events('next')[-1]['kind'], 'interrupted')
        self.transport.response_events = original
        self.assertEqual(self.post('/api/conversations/thread/turns', self.message('after-stop')).status_code, 202)
        self.assertEqual(self.events('after-stop')[-1]['kind'], 'complete')
        self.assertFalse(self.release.is_set())
        self.release.set()
        # The newer completed turn changes the snapshot; old work cannot publish.
        runtime = self.app.state.runtime
        async def settled():
            async with asyncio.timeout(5):
                while runtime.memory.task is not None:
                    await asyncio.sleep(0.005)
        self.client.portal.call(settled)
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.background_calls, 1)

    def test_complementary_turns_merge_stably_and_repetition_does_not_churn(self):
        self.start_memory()
        self.assertEqual(self.finish_memory(), 'saved')
        original = self.entries()[0]

        def merge(action, evidence):
            old = evidence['people'][0]['entries'][0]
            return {**action, 'intent': 'merge', 'entry_id': old['id'], 'expected_version': old['version']}
        self.action_transform = merge
        self.start_memory('complement', 'Frederik grows tomatoes too.')
        self.assertEqual(self.finish_memory(), 'saved')
        merged = self.entries()
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]['id'], merged[0]['version']), (original['id'], 2))
        self.assertEqual(merged[0]['content']['notes'],
                         'Frederik enjoys gardening.\nFrederik grows tomatoes too.')
        self.assertEqual({item['turn_id'] for item in merged[0]['source']['sources']}, {'source', 'complement'})
        self.start_memory('repeat', 'Frederik grows tomatoes too.')
        self.assertEqual(self.finish_memory(), 'unchanged')
        self.assertEqual(self.entries()[0]['version'], 2)

    def test_manual_context_written_during_analysis_wins(self):
        from tests.people.test_personal_context import fact
        self.start_memory()
        response = self.post(f'/api/people/{self.person}/context', {'id': 'manual',
            'operation_id': 'manual-create', 'expected_version': 0,
            'content': fact('interests', 'My own wording')})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.finish_memory(), 'stale')
        self.assertEqual([entry['id'] for entry in self.entries()], ['manual'])
        self.assertEqual(self.entries()[0]['content']['title'], 'My own wording')

    def test_source_correction_during_analysis_cannot_publish_old_fact(self):
        self.start_memory()
        response = self.post('/api/conversations/thread/corrections', {'id': 'correct-source',
            'source_turn': 'source', 'action': 'correct', 'replacement': 'That was a fictional example.'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.finish_memory(), 'stale')
        self.assertEqual(self.entries(), [])

    def test_release_drain_tracks_blocked_worker_without_reopening_or_publishing(self):
        self.start_memory()
        runtime = self.app.state.runtime
        async def drain():
            return await runtime.admission.drain('b' * 32, timeout=0.05)
        status = self.client.portal.call(drain)
        self.assertEqual(status['phase'], 'fenced')
        self.assertFalse(self.release.is_set())
        self.assertTrue(runtime.admission.pending)
        self.assertEqual(self.finish_memory(), 'superseded_after_request')
        self.assertEqual(runtime.admission.phase, 'fenced')
        self.client.portal.call(runtime.admission.resume, 'b' * 32)
        self.assertEqual(self.entries(), [])

    def test_account_disconnect_during_analysis_rejects_old_output(self):
        self.start_memory()
        self.app.state.runtime.siwc.credentials.save('alice', {'selected': None, 'accounts': {}})
        self.assertEqual(self.finish_memory(), 'failed')
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.background_calls, 1)

    def test_revocation_during_analysis_prevents_apply(self):
        self.start_memory()
        response = self.post('/api/personal-context-preference', {'enabled': False, 'expected_version': 1})
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.finish_memory(), ('stale', 'failed'))
        self.assertEqual(self.entries(), [])
