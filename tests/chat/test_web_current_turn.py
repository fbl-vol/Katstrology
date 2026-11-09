"""Trusted current execution versus historical web sources, through the real gateway."""
import json
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import patch

from m2.chat.gateway import run_turn, turn_steps
from m2.provider.steps import ProviderStep, next_provider
from m2.provider.siwc import ProviderFailure
from tests.provider.test_provider_output_compat import model_for
from tests.support.database import DatabaseCase
from tests.chat.test_tool_evidence_budget import native_call
from tests.chat.test_web_evidence import ANSWER
from m2.chat.web_evidence import read_content


class CurrentWebTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.store.create_conversation(self.alice, 'web-thread')

    def page(self):
        url = 'https://news.example/story'
        return {'status': 'ok', 'content': ''.join(
                    f'Paragraph {index}: distinct public background. ' for index in range(300))
                    + 'UNIQUE LATER PASSAGE.',
                'source_id': uuid4().hex * 2, 'requested_url': url, 'final_url': url,
                'retrieved_at': datetime.now(timezone.utc).isoformat(), 'title': 'Synthetic long article',
                'source_truncated': False, 'provider': 'public_http',
                'content_kind': 'untrusted_public_page_text'}

    def run_model(self, model, turn='current'):
        return run_turn(self.store, self.alice, 'web-thread', turn,
                        'Read https://news.example/story and find the later passage.', model,
                        lambda _: None, model_provider='chatgpt_plan', model_slug=model.slug)

    def test_fetch_discover_find_and_page_before_completion_use_only_returned_handles(self):
        page = self.page()
        model, bridge = model_for(ANSWER)
        self.addCleanup(bridge.close)
        outputs, handles = [], {}
        cursor = None

        def respond(token, body):
            nonlocal cursor
            last = body['input'][-1]
            if last.get('type') != 'function_call_output':
                events = native_call(1, 'fetch_web_page', {'urls': [page['requested_url']]})
            else:
                output = json.loads(last['output'])
                outputs.append(output)
                if len(outputs) == 1:
                    handles.update(conversation_id=output['conversation_id'], turn_id=output['turn_id'],
                                   source_id=output['pages'][0]['source_id'])
                    cursor = output['pages'][0]['next_offset']
                    args = {'conversation_id': '', 'turn_id': '', 'source_id': '', 'offset': 0, 'find': None}
                    events = native_call(2, 'read_web_content', args)
                elif len(outputs) == 2:
                    events = native_call(3, 'read_web_content', {**handles, 'offset': 0, 'find': 'UNIQUE LATER'})
                elif len(outputs) == 3:
                    events = native_call(4, 'read_web_content', {**handles, 'offset': cursor, 'find': None})
                else:
                    events = ANSWER
                archived = self.store.read_turn(self.alice, handles['conversation_id'], handles['turn_id'])
                self.assertEqual(archived['status'], 'open')
                self.assertIsNone(self.store.active_head(self.alice, handles['conversation_id']))
                self.assertEqual(archived['events'][-1]['kind'], 'tool_result')
                self.assertEqual(archived['events'][-1]['payload']['id'], last['call_id'])
            for event in events:
                yield event, 'synthetic-same-turn'

        bridge.transport.response_events = respond
        with patch('m2.chat.web_evidence.fetch_page', return_value=page) as fetch:
            self.assertEqual(self.run_model(model), 'complete')
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(outputs[2].get('content'), 'UNIQUE LATER PASSAGE.', outputs[2])
        self.assertEqual(outputs[1]['source_id'], handles['source_id'])
        self.assertEqual(outputs[1]['turn_id'], handles['turn_id'])
        self.assertEqual(outputs[1]['sources'][0]['url'], page['final_url'])
        self.assertTrue(outputs[1]['text_omitted'])
        self.assertGreater(cursor, 0)
        self.assertEqual(outputs[3]['offset'], cursor)
        self.assertGreater(len(outputs[3]['content']), 100)
        self.assertEqual(outputs[3]['content'], page['content'][cursor:cursor + len(outputs[3]['content'])])
        archived = self.store.read_turn(self.alice, 'web-thread', 'current')['events']
        calls = [event['payload'] for event in archived if event['kind'] == 'tool_call']
        self.assertEqual(calls[1]['arguments']['conversation_id'], '')
        self.assertEqual(calls[1]['arguments']['turn_id'], '')
        self.assertEqual([call['id'] for call in calls], ['call-1', 'call-2', 'call-3', 'call-4'])
        self.assertTrue(all(event['payload']['model_projection_bytes'] <= 3072
                            for event in archived if event['kind'] == 'tool_result'))

    def test_same_turn_access_still_checks_parent_correction_and_active_branch(self):
        from m2.archive.revisions import correct, select_branch
        from tests.chat.test_gateway import TinySource

        for change in ('correction', 'branch'):
            with self.subTest(change=change):
                conv = 'web-' + change
                self.store.create_conversation(self.alice, conv)
                for root in ('parent', 'other-root'):
                    run_turn(self.store, self.alice, conv, root, 'Synthetic root', TinySource(),
                             lambda _: None, parent_id='@root')
                select_branch(self.store, self.alice, conv, 'parent')
                page = self.page()
                model, bridge = model_for(ANSWER)
                self.addCleanup(bridge.close)
                outputs = []
                def respond(token, body):
                    last = body['input'][-1]
                    if last.get('type') != 'function_call_output':
                        events = native_call(1, 'fetch_web_page', {'urls': [page['requested_url']]})
                    else:
                        output = json.loads(last['output'])
                        outputs.append(output)
                        if len(outputs) == 1:
                            if change == 'correction':
                                correct(self.store, self.alice, conv, 'changed-parent', 'parent',
                                        'correct', 'Replaced synthetic report')
                            else:
                                select_branch(self.store, self.alice, conv, 'other-root')
                            events = native_call(2, 'read_web_content', {
                                'conversation_id': output['conversation_id'], 'turn_id': output['turn_id'],
                                'source_id': output['pages'][0]['source_id'], 'offset': 0, 'find': 'UNIQUE LATER'})
                        else:
                            events = ANSWER
                    for event in events:
                        yield event, 'synthetic-parent-change'
                bridge.transport.response_events = respond
                with patch('m2.chat.web_evidence.fetch_page', return_value=page) as fetch:
                    status = run_turn(self.store, self.alice, conv, 'current', 'Read ' + page['requested_url'],
                                      model, lambda _: None, model_provider='chatgpt_plan', model_slug=model.slug)
                    self.assertEqual(status, 'complete')
                    self.assertEqual(fetch.call_count, 1)
                self.assertEqual(outputs[1]['reason'], 'source_not_current')
                self.assertNotIn('content', outputs[1])

    def suspend_fetched_turn(self, conversation, turn, session=None):
        """Pause actual gateway execution after its fetch result commits, before continuation."""
        session = session or self.alice
        page = self.page()
        model, bridge = model_for(native_call(1, 'fetch_web_page', {'urls': [page['requested_url']]}), ANSWER)
        self.addCleanup(bridge.close)
        steps = turn_steps(self.store, session, conversation, turn, 'Read ' + page['requested_url'],
                           model, lambda _: None, model_provider='chatgpt_plan', model_slug=model.slug,
                           defer_provider=True)
        self.addCleanup(steps.close)
        initial = next(steps)
        work = steps.send(next_provider(initial.stream))
        with patch('m2.chat.web_evidence.fetch_page', return_value=page):
            continuation = steps.send(next_provider(work.stream))
        self.assertIsInstance(continuation, ProviderStep)
        archived = self.store.read_turn(session, conversation, turn)
        self.assertEqual(archived['status'], 'open')
        result = archived['events'][-1]['payload']['result']
        return {'conversation_id': result['conversation_id'], 'turn_id': result['turn_id'],
                'source_id': result['pages'][0]['source_id'], 'offset': 0, 'find': 'UNIQUE LATER'}

    def test_model_cannot_select_another_open_turn_or_forge_execution_context(self):
        other_open = self.suspend_fetched_turn('web-thread', 'other-open')
        self.store.create_conversation(self.alice, 'other-thread')
        # Same turn ID in another owned conversation must not match execution scope.
        collision = self.suspend_fetched_turn('other-thread', 'current')
        self.store.create_conversation(self.bob, 'foreign-thread')
        foreign = self.suspend_fetched_turn('foreign-thread', 'current', self.bob)
        self.assertEqual(read_content(self.store, self.alice, other_open)['reason'], 'source_not_current')
        self.assertEqual(read_content(self.store, self.alice, collision)['reason'], 'source_not_current')
        attempts = [other_open, collision, foreign, {**other_open, 'turn_id': 'current'}]
        model, bridge = model_for(*(native_call(index + 1, 'read_web_content', args)
                                    for index, args in enumerate(attempts)), ANSWER)
        self.addCleanup(bridge.close)
        with patch('m2.chat.web_evidence.fetch_page', side_effect=AssertionError('Unexpected external fetch')):
            self.assertEqual(self.run_model(model), 'complete')
        results = [event['payload']['result'] for event in
                   self.store.read_turn(self.alice, 'web-thread', 'current')['events']
                   if event['kind'] == 'tool_result']
        self.assertEqual([result.get('reason') for result in results[:2]],
                         ['source_not_current', 'source_not_current'])
        self.assertEqual(results[2]['error'], 'KeyError')
        self.assertEqual(results[3]['error'], 'KeyError')  # No matching committed result in this turn.
        self.assertNotIn('UNIQUE LATER PASSAGE.', json.dumps(results))

        forged, transport = model_for(native_call(10, 'read_web_content', {
            **other_open, 'current_turn': ['web-thread', 'other-open']}), ANSWER)
        self.addCleanup(transport.close)
        with self.assertRaisesRegex(ProviderFailure, 'invalid_provider_tool_call'):
            self.run_model(forged, 'forged')
        self.assertFalse(any(event['kind'] == 'tool_result' for event in
                             self.store.read_turn(self.alice, 'web-thread', 'forged')['events']))
