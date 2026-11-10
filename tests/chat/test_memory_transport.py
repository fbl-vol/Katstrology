"""Owned HTTP/runtime/Store memory through the real HTTP/SSE transport, never a provider.

MockTransport is below serialization and OpenAITransport's status/SSE handling.
It substitutes the endpoint, not the memory analyzer, parser, scheduler or apply.
"""
import asyncio
import json
from threading import current_thread

import httpx

from m2.chat.memory_analysis import INSTRUCTIONS
from m2.provider.siwc import OpenAITransport
from tests.chat.test_memory_jobs import MemoryJobsFixture


class MemoryTransportTests(MemoryJobsFixture):
    def setUp(self):
        super().setUp()
        self.reject_background = False
        self.omit_actions = False
        self.fact_turn = 'source'
        self.wire_bodies = []
        self.sentences = ['Frederik married in May 2020.']
        wire = OpenAITransport()
        wire.client.close()
        wire.client = httpx.Client(transport=httpx.MockTransport(self.endpoint),
                                   timeout=20, trust_env=False, follow_redirects=False)
        self.addCleanup(wire.close)
        self.transport.response_events = wire.response_events

    def endpoint(self, request):
        # An unexpected URL cannot escape to the network through MockTransport.
        self.assertEqual(str(request.url), 'https://api.openai.com/v1/responses')
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.headers['authorization'], 'Bearer synthetic-access')
        body = json.loads(request.content)
        self.wire_bodies.append(body)
        self.assertEqual(body['model'], 'gpt-6-luna')
        self.assertIs(body['store'], False)
        self.assertIs(body['stream'], True)
        text = 'Understood.'
        if body['instructions'] == INSTRUCTIONS:
            self.background_calls += 1
            self.background_thread = current_thread().name
            self.entered.set()
            required = {'model', 'instructions', 'input', 'store', 'stream', 'max_output_tokens'}
            if set(body) != required or body['max_output_tokens'] != 4096 or self.reject_background:
                return httpx.Response(400, json={'error': {'code': 'synthetic_contract_rejection'}})
            evidence = json.loads(body['input'][0]['content'][0]['text'])
            message = next(item for item in evidence['messages'] if item['turn_id'] == self.fact_turn)
            actions = []
            for sentence in self.sentences:
                start = message['text'].index(sentence)
                actions.append({'person_id': self.person, 'entry_id': None, 'expected_version': 0,
                    'intent': 'add', 'group': 'past_moments', 'assessment': 'asserted',
                    'attribution': 'named', 'identity_turn_id': self.fact_turn,
                    'statements': [{'turn_id': self.fact_turn, 'start': start,
                                    'end': start + len(sentence), 'text': sentence}],
                    'state': 'completed', 'date': None})
            text = json.dumps({'actions': [] if self.omit_actions else actions})
        events = [{'type': 'response.output_text.delta', 'delta': text},
                  {'type': 'response.completed'}]
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              content=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))

    def complete_turn(self, turn, text):
        response = self.post('/api/conversations/thread/turns', self.message(turn, text))
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.events(turn)[-1]['kind'], 'complete')

    def queue_turns(self, *turns):
        memory = self.app.state.runtime.memory
        self.client.portal.call(memory.foreground_enter)
        try:
            for turn, text in turns:
                self.complete_turn(turn, text)
        finally:
            self.client.portal.call(memory.foreground_leave)

    def run_due(self):
        runtime = self.app.state.runtime
        async def run():
            async with asyncio.timeout(5):
                while any(not job.finished for job in runtime.chat.jobs.values()):
                    await asyncio.sleep(0.001)
                runtime.memory._cancel_timer()
                await runtime.execute(lambda: runtime.store.db.execute(
                    "UPDATE memory_work SET queued_at=clock_timestamp()-interval '5 seconds'"))
                await runtime.memory._run()
        self.client.portal.call(run)

    def work_state(self):
        runtime = self.app.state.runtime
        return self.client.portal.call(runtime.call, lambda store, _: store.db.execute(
            "SELECT state,outcome,attempted_generation,queued_at FROM memory_work "
            "WHERE owner_id='alice' AND conversation_id='thread'").fetchone())

    def test_two_distinct_milestones_in_same_group_are_saved_atomically(self):
        self.sentences.append('Frederik joined ExampleWorks in July 2021.')
        self.start_memory(text=' '.join(self.sentences))
        self.assertEqual(self.finish_memory(), 'saved')
        self.assertEqual({entry['content']['title'] for entry in self.entries()}, set(self.sentences))
        self.assertEqual(self.background_calls, 1)

    def test_question_coalescing_does_not_erase_unprocessed_milestone(self):
        self.queue_turns(('source', self.sentences[0]), ('question', 'What should I consider?'))
        self.run_due()
        self.assertEqual(self.work_state()['outcome'], 'saved')
        self.assertEqual([entry['content']['title'] for entry in self.entries()], self.sentences)
        self.assertEqual(self.entries()[0]['source']['turn_id'], 'source')

    def test_preclaim_credential_contention_defers_without_consuming_work(self):
        runtime = self.app.state.runtime
        self.queue_turns(('source', self.sentences[0]))
        queued = self.work_state()['queued_at']
        with runtime.siwc._owner_lock('alice'):
            self.run_due()
            self.assertEqual(self.background_calls, 0)
            self.assertEqual(self.work_state()['state'], 'pending')
            self.assertIsNone(self.work_state()['attempted_generation'])
            self.assertGreater(self.work_state()['queued_at'], queued)
        self.run_due()
        self.assertEqual(self.work_state()['outcome'], 'saved')
        self.assertEqual([entry['content']['title'] for entry in self.entries()], self.sentences)
        self.assertEqual(self.background_calls, 1)

    def test_pending_milestone_survives_question_and_owner_cooldown(self):
        self.start_memory(text=self.sentences[0])
        self.assertEqual(self.finish_memory(), 'saved')
        self.fact_turn = 'later-fact'
        self.sentences = ['Frederik joined ExampleWorks in July 2021.']
        self.queue_turns((self.fact_turn, self.sentences[0]), ('question', 'What should I consider?'))
        self.run_due()
        self.assertEqual(self.work_state()['state'], 'pending')
        self.assertEqual(self.background_calls, 1)  # Cooldown still enforced.
        runtime = self.app.state.runtime
        self.client.portal.call(runtime.call, lambda store, _: store.db.execute(
            "UPDATE memory_budget SET next_attempt_at=clock_timestamp()-interval '1 second'"))
        self.run_due()
        self.assertEqual(self.work_state()['outcome'], 'saved')
        self.assertEqual(self.background_calls, 2)
        self.assertEqual({entry['content']['title'] for entry in self.entries()}, {
            'Frederik married in May 2020.', 'Frederik joined ExampleWorks in July 2021.'})

    def test_later_retraction_reaches_model_and_consumed_fact_cannot_reappear(self):
        # Semantic selection is supplied, not proved: server must expose the
        # complete qualifier, then fence this consumed range from later questions.
        self.omit_actions = True
        qualifier = 'Actually, that marriage was a fictional example, not Frederik.'
        self.queue_turns(('source', self.sentences[0]), ('retraction', qualifier))
        self.run_due()
        self.assertEqual(self.work_state()['outcome'], 'unchanged')
        self.assertEqual(self.entries(), [])
        body = next(body for body in self.wire_bodies if body['instructions'] == INSTRUCTIONS)
        evidence = json.loads(body['input'][0]['content'][0]['text'])
        self.assertEqual(evidence['messages'][-1]['text'], qualifier)
        self.omit_actions = False  # A bad later proposal must not revive consumed evidence.
        self.queue_turns(('question', 'What should I consider?'))
        runtime = self.app.state.runtime
        self.client.portal.call(runtime.call, lambda store, _: store.db.execute(
            "UPDATE memory_budget SET next_attempt_at=clock_timestamp()-interval '1 second'"))
        self.run_due()
        self.assertEqual(self.work_state()['outcome'], 'failed')
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.background_calls, 2)

    def test_milestone_reaches_correct_context_through_strict_responses_wire(self):
        original = self.start_memory(text=self.sentences[0])
        self.assertEqual(self.finish_memory(), 'saved')
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['content']['group'], 'past_moments')
        self.assertEqual(entries[0]['content']['title'], 'Frederik married in May 2020.')
        self.assertEqual(entries[0]['content']['date']['precision'], 'unknown')
        self.assertEqual(entries[0]['source']['turn_id'], 'source')
        self.assertEqual(self.background_calls, 1)
        self.assertEqual(self.events('source'), original)
        body = next(body for body in self.wire_bodies if body['instructions'] == INSTRUCTIONS)
        self.assertEqual(body['max_output_tokens'], 4096)
        self.assertNotIn('tools', body)
        self.login('bob', 'synthetic-password-bob')
        self.assertEqual(self.client.get(f'/api/people/{self.person}/context').status_code, 404)

    def test_strict_endpoint_rejection_is_terminal_without_unbounded_or_paid_fallback(self):
        self.reject_background = True
        self.start_memory(text=self.sentences[0])
        self.assertEqual(self.finish_memory(), 'failed')
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.background_calls, 1)
        body = next(body for body in self.wire_bodies if body['instructions'] == INSTRUCTIONS)
        self.assertEqual(body['max_output_tokens'], 4096)
