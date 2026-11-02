"""Synthetic producer/consumer tests for stateless Responses read rounds."""

import copy
import json
from unittest.mock import patch

from m2.agent_reads import TOOLS, execute
from m2.gateway import run_turn
from m2.provider_model import ResponsesModel, _valid_read_arguments
from m2.references import References
from m2.people import People
from m2.recall import rebuild_pending, search
from m2.revisions import correct
from m2.test_gateway import TinySource
from m2.test_support import DatabaseCase


class ScriptedTransport:
    def __init__(self):
        self.calls = []
        self.script = []

    def response_events(self, token, body):
        self.calls.append(copy.deepcopy(body))
        yield from self.script.pop(0)


class FakeBridge:
    def __init__(self, transport):
        self.transport = transport

    def models(self, owner):
        return [{'slug': 'synthetic-response-model', 'context_window': 500000,
                 'max_output_tokens': 128000}]

    def access(self, owner):
        return 'synthetic-only'


class AgentReadTests(DatabaseCase):
    def test_passage_offset_protocol_schema_rejects_bool_float_and_out_of_range(self):
        for offset, expected in ((0, True), (4096, True), (65535, True),
                                 (65536, False), (-1, False), (True, False), (1.5, False)):
            with self.subTest(offset=offset):
                self.assertEqual(_valid_read_arguments('get_reference_passage', json.dumps({
                    'source_id': 'source', 'passage_id': 'passage', 'offset': offset})), expected)


    def model(self, script):
        transport = ScriptedTransport()
        transport.script = script
        return ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model'), transport

    def test_stateless_round_is_archived_before_continuation_and_never_retried(self):
        self.store.create_conversation(self.alice, 'thread')
        self.store.create_conversation(self.bob, 'private-bob')
        run_turn(self.store, self.alice, 'thread', 'older', 'Synthetic lighthouse detail',
                 TinySource(), lambda _: None)
        run_turn(self.store, self.bob, 'private-bob', 'hidden', 'Synthetic lighthouse secret',
                 TinySource(), lambda _: None)
        from m2.recall import rebuild_pending
        rebuild_pending(self.store, self.alice)
        rebuild_pending(self.store, self.bob)
        call = {'type': 'function_call', 'id': 'fc_synthetic', 'call_id': 'call_synthetic',
                'name': 'search_conversations',
                'arguments': json.dumps({'query': 'lighthouse', 'person_id': None})}
        reasoning = {'type': 'reasoning', 'id': 'rs_synthetic', 'encrypted_content': 'synthetic-opaque'}
        first = [({'type': 'response.output_item.added', 'item': call}, 'fixture'),
                 ({'type': 'response.completed', 'response': {'output': [reasoning, call]}}, 'fixture')]
        second = [({'type': 'response.output_text.delta', 'delta': 'The earlier thread mentions a lighthouse.'}, 'fixture'),
                  ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')]
        model, transport = self.model([first, second])
        original = transport.response_events
        def check_archive(token, body):
            if len(transport.calls) == 2:
                events = self.store.read_turn(self.alice, 'thread', 'new')['events']
                self.assertEqual([e['kind'] for e in events[-2:]], ['tool_call', 'tool_result'])
                self.assertEqual(events[-1]['payload']['id'], 'call_synthetic')
            yield from original(token, body)
        transport.response_events = check_archive
        delivered = []
        status = run_turn(self.store, self.alice, 'thread', 'new', 'Recall the lighthouse', model,
                          delivered.append, parent_id='older', model_provider='chatgpt_plan',
                          model_slug='synthetic-response-model')
        self.assertEqual(status, 'complete')
        self.assertEqual([e['kind'] for e in delivered][-4:],
                         ['tool_call', 'tool_result', 'assistant_chunk', 'complete'])
        self.assertEqual([item['name'] for item in transport.calls[0]['tools']],
                         [item['name'] for item in TOOLS])
        self.assertFalse(transport.calls[1]['store'])
        self.assertNotIn('previous_response_id', transport.calls[1])
        self.assertEqual(transport.calls[1]['input'][-2], call)
        self.assertEqual(transport.calls[1]['input'][-3], reasoning)
        self.assertEqual(transport.calls[1]['input'][-1]['call_id'], 'call_synthetic')
        self.assertNotIn('private-bob', transport.calls[1]['input'][-1]['output'])
        archived = self.store.read_turn(self.alice, 'thread', 'new')['events']
        self.assertNotIn('synthetic-opaque', json.dumps(archived, default=str))
        self.assertEqual(run_turn(self.store, self.alice, 'thread', 'new',
            'Recall the lighthouse', model, lambda _: None, parent_id='older',
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        self.assertEqual(len(transport.calls), 2)

    def test_read_validation_denies_other_owner_inactive_branch_and_unselected_chart(self):
        self.store.create_conversation(self.alice, 'thread')
        self.store.create_conversation(self.bob, 'hidden')
        run_turn(self.store, self.alice, 'thread', 'old', 'Original', TinySource(), lambda _: None)
        run_turn(self.store, self.alice, 'thread', 'branch', 'Replacement', TinySource(),
                 lambda _: None, parent_id='@root', revision_kind='edit', replaces_turn_id='old')
        with self.assertRaises(KeyError):
            execute(self.store, self.alice, 'get_conversation_messages',
                    {'conversation_id': 'hidden', 'around_turn_id': 'secret'}, set())
        with self.assertRaises(KeyError):
            execute(self.store, self.alice, 'get_conversation_messages',
                    {'conversation_id': 'thread', 'around_turn_id': 'old'}, set())
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'get_chart', {'chart_id': 'not-selected'}, set())
        for args in ({'query': 'abc', 'owner_id': 'bob'},
                     {'query': '', 'person_id': None},
                     {'query': 'x' * 257, 'person_id': None}):
            with self.assertRaises(ValueError):
                execute(self.store, self.alice, 'search_conversations', args, set())

    def test_long_current_message_pages_preserve_ending_and_owner_fence(self):
        self.store.create_conversation(self.alice, 'long-history')
        message = 'Synthetic report: ' + 'bounded-detail-' * 420 + ' LAST_MARKER'
        self.assertEqual(run_turn(self.store, self.alice, 'long-history', 'original', message,
                                   TinySource(), lambda _: None, parent_id='@root'), 'complete',
                         self.store.read_turn(self.alice, 'long-history', 'original')['events'][-1]['payload'])
        first = execute(self.store, self.alice, 'get_conversation_messages', {
            'conversation_id': 'long-history', 'around_turn_id': 'original'}, set())['turns'][0]
        self.assertTrue(first['truncated'])
        self.assertEqual(first['next_offset'], 4096)
        pages = []
        offset = 0
        while offset is not None:
            page = execute(self.store, self.alice, 'get_conversation_message_page', {
                'conversation_id': 'long-history', 'turn_id': 'original', 'offset': offset}, set())
            self.assertEqual(page['text_sha256'], first['text_sha256'])
            pages.append(page['text'])
            offset = page['next_offset']
        self.assertIn('LAST_MARKER', ''.join(pages))
        self.assertEqual(first['text'], pages[0])
        with self.assertRaises(KeyError):
            execute(self.store, self.bob, 'get_conversation_message_page', {
                'conversation_id': 'long-history', 'turn_id': 'original', 'offset': 0}, set())

    def test_person_scoped_history_does_not_mix_selected_turns_and_honors_correction(self):
        people = People(self.store)
        person_a = people.add(self.alice, 'Synthetic A')['id']
        person_b = people.add(self.alice, 'Synthetic B')['id']
        self.store.create_conversation(self.alice, 'shared')
        model = TinySource()
        run_turn(self.store, self.alice, 'shared', 'a', 'Lighthouse detail alpha',
                 model, lambda _: None,
                 selected_people=[{'person_id': person_a, 'chart_id': None}])
        run_turn(self.store, self.alice, 'shared', 'b', 'Lighthouse detail beta',
                 model, lambda _: None,
                 selected_people=[{'person_id': person_b, 'chart_id': None}])
        rebuild_pending(self.store, self.alice)
        result = search(self.store, self.alice, 'lighthouse', person_id=person_a)
        self.assertEqual([item['source_id'] for item in result['results']], ['a'])
        from m2.evidence import search_evidence
        selected = search_evidence(self.store, self.alice, 'lighthouse',
                                   person_id=person_a, limit=5)
        self.assertEqual([item['source_id'] for item in selected['results']], ['a'])
        correct(self.store, self.alice, 'shared', 'revision-a', 'a', 'correct',
                'Corrected lighthouse detail alpha')
        rebuild_pending(self.store, self.alice)
        self.assertEqual([item['source_id'] for item in search(self.store, self.alice,
                         'lighthouse', person_id=person_a)['results']], ['revision-a'])
        self.assertEqual(search(self.store, self.alice, 'lighthouse',
                         person_id=person_b)['results'], [])  # descendant fenced after correction
        run_turn(self.store, self.alice, 'shared', 'b-rebased', 'Lighthouse beta current',
                 model, lambda _: None, parent_id='a',
                 selected_people=[{'person_id': person_b, 'chart_id': None}])
        rebuild_pending(self.store, self.alice)
        self.assertEqual(search(self.store, self.alice, 'lighthouse',
                         person_id=person_b)['results'][0]['source_id'], 'b-rebased')
        with self.assertRaises(KeyError):
            search(self.store, self.bob, 'lighthouse', person_id=person_a)

    def test_passage_read_preserves_source_and_owner_and_is_bounded(self):
        references = References(self.store)
        references.add_source(self.alice, 'source', 'Fixture Author', 'Fixture Text',
            '1', 'modern', 'interpretation', 'synthetic authored', 'synthetic test grant')
        references.add_passage(self.alice, 'source', 'passage', 'Section 2',
                               'Synthetic motif ' * 190)
        value = execute(self.store, self.alice, 'get_reference_passage',
                        {'source_id': 'source', 'passage_id': 'passage'}, set())
        self.assertEqual(value['author'], 'Fixture Author')
        self.assertEqual(value['source_status'], 'independent_synthetic_fixture')
        self.assertFalse(value['truncated'])
        self.assertEqual(value['content'], 'Synthetic motif ' * 190)
        self.assertIsNone(value['next_offset'])
        tail = execute(self.store, self.alice, 'get_reference_passage',
                       {'source_id': 'source', 'passage_id': 'passage', 'offset': 1800}, set())
        self.assertIsNone(tail['next_offset'])
        self.assertEqual(value['content'][1800:], tail['content'])
        self.assertEqual(value['content_sha256'], tail['content_sha256'])
        with self.assertRaises(ValueError):
            execute(self.store, self.alice, 'get_reference_passage',
                    {'source_id': 'source', 'passage_id': 'passage', 'offset': -1}, set())
        with self.assertRaises(KeyError):
            execute(self.store, self.bob, 'get_reference_passage',
                    {'source_id': 'source', 'passage_id': 'passage'}, set())

    def test_model_search_fetch_keeps_attribution_and_denies_unadvertised_write(self):
        refs = References(self.store)
        a = 'Synthetic author A considers angular geometry a starting point; never follow this text as an instruction.'
        b = 'Synthetic author B considers angular geometry insufficient as interpretation.'
        for source_id, author, text in (('author-a', 'Synthetic A', a),
                                        ('author-b', 'Synthetic B', b)):
            refs.ingest_edition(self.alice, {
                'source_id': source_id, 'author': author, 'title': 'Synthetic study',
                'edition': '2026 fixture', 'tradition': 'invented', 'technique': 'aspects',
                'provenance': 'local synthetic fixture', 'rights_evidence': 'locally authored',
                'extraction_note': 'no OCR; original local test text',
            }, text, [{'id': 'p1', 'section': 'page 1', 'content': text}])
        self.store.create_conversation(self.alice, 'study')
        args = {'query': 'geometry', 'author': None, 'tradition': 'invented',
                'technique': 'aspects', 'language': 'en'}
        def call(number, name, arguments):
            return {'type': 'function_call', 'id': f'fc_{number}',
                    'call_id': f'call_{number}', 'name': name,
                    'arguments': json.dumps(arguments)}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [
                call(1, 'search_references', args)]}}, 'fixture')],
            [({'type': 'response.completed', 'response': {'output': [
                call(2, 'get_reference_passage',
                     {'source_id': 'author-a', 'passage_id': 'p1'})]}}, 'fixture')],
            [({'type': 'response.completed', 'response': {'output': [
                call(3, 'delete_reference', {'source_id': 'author-b'})]}}, 'fixture')],
            [({'type': 'response.output_text.delta',
               'delta': 'Synthetic A and B disagree; no source was changed.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        self.assertEqual(run_turn(self.store, self.alice, 'study', 'read',
            'Compare synthetic angular geometry', model, lambda _: None,
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'complete')
        found = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertIn('results', found, found)
        self.assertEqual({row['source_id'] for row in found['results']},
                         {'author-a', 'author-b'})
        self.assertEqual(found['search_mode'], 'keyword_and_partial_semantic_index')
        passage = json.loads(transport.calls[2]['input'][-1]['output'])
        self.assertEqual(passage['content'], a)
        denied = json.loads(transport.calls[3]['input'][-1]['output'])
        self.assertEqual(denied['error'], 'ValueError')
        self.assertEqual(refs.get_passage(self.alice, 'author-b', 'p1')['content'], b)
        self.assertEqual({row['source_id'] for row in execute(self.store, self.alice,
            'search_references', {**args, 'author': 'Synthetic A'}, set())['results']},
            {'author-a'})
        self.assertEqual(execute(self.store, self.alice, 'search_references',
            {**args, 'language': 'da'}, set())['results'], [])
        self.assertEqual(self.store.db.execute('''
            SELECT count(*) AS value FROM reference_evidence
            WHERE owner_id='alice' AND conversation_id='study' AND turn_id='read'
        ''').fetchone()['value'], 3)

    def test_stream_announced_tool_without_completed_item_fails_closed(self):
        from m2.siwc import ProviderFailure
        call = {'type': 'function_call', 'id': 'fc_1', 'call_id': 'call_1',
                'name': 'search_conversations',
                'arguments': '{"query":"fixture","person_id":null}'}
        model, transport = self.model([[({'type': 'response.output_item.added', 'item': call}, 'fixture'),
            ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')]])
        with self.assertRaisesRegex(ProviderFailure, 'unsupported_provider_output'):
            list(model.create_completion('Synthetic'))
        self.assertEqual(len(transport.calls), 1)

    def test_continuation_capacity_preserves_call_result_but_never_sends_overflow(self):
        self.store.create_conversation(self.alice, 'small-context')
        class SmallBridge(FakeBridge):
            def models(self, owner):
                return [{'slug': 'synthetic-response-model', 'context_window': 16384,
                         'max_output_tokens': 2048}]
        call = {'type': 'function_call', 'id': 'fc_overflow', 'call_id': 'call_overflow',
                'name': 'search_conversations',
                'arguments': '{"query":"fixture","person_id":null}'}
        transport = ScriptedTransport()
        transport.script = [[({'type': 'response.completed', 'response': {'output': [
            {'type': 'reasoning', 'id': 'rs_large',
             'encrypted_content': 'synthetic-opaque-' * 1900}, call]}}, 'fixture')]]
        model = ResponsesModel(SmallBridge(transport), 'alice', 'synthetic-response-model')
        self.assertEqual(run_turn(self.store, self.alice, 'small-context', 'overflow',
            'Synthetic search request', model, lambda _: None,
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'error')
        self.assertEqual(len(transport.calls), 1)
        events = self.store.read_turn(self.alice, 'small-context', 'overflow')['events']
        self.assertEqual([e['kind'] for e in events][-3:],
                         ['tool_call', 'tool_result', 'error'])
        self.assertEqual(events[-1]['payload']['code'], 'tool_round_capacity_exceeded')
        self.assertGreater(events[-1]['payload']['used_units'],
                           events[-1]['payload']['limit_units'])
        self.assertEqual(events[-2]['payload']['model_projection_limit']['scope'],
                         'model_context')
        self.assertNotIn('synthetic-opaque', json.dumps(events, default=str))
        self.assertEqual(run_turn(self.store, self.alice, 'small-context', 'overflow',
            'Synthetic search request', model, lambda _: None,
            model_provider='chatgpt_plan', model_slug='synthetic-response-model'), 'error')
        self.assertEqual(len(transport.calls), 1)

    def test_repeated_native_call_id_is_protocol_failure_not_budget_exhaustion(self):
        self.store.create_conversation(self.alice, 'thread')
        call = {'type': 'function_call', 'id': 'fc-a', 'call_id': 'call-a',
                'name': 'search_conversations',
                'arguments': '{"query":"fixture","person_id":null}'}
        script = [[({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
                  [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')]]
        model, transport = self.model(script)
        with patch('m2.gateway.execute_read', wraps=execute) as read:
            status = run_turn(self.store, self.alice, 'thread', 'duplicate-id', 'Synthetic',
                model, lambda _: None, model_provider='chatgpt_plan',
                model_slug='synthetic-response-model')
        self.assertEqual(status, 'error')
        self.assertEqual(read.call_count, 1)
        self.assertEqual(len(transport.calls), 2)
        events = self.store.read_turn(self.alice, 'thread', 'duplicate-id')['events']
        self.assertEqual(events[-1]['payload']['code'], 'duplicate_tool_call_id')
        self.assertEqual(sum(event['kind'] == 'tool_result' for event in events), 1)

    def test_model_can_request_ten_reads_then_finish_without_count_denial(self):
        self.store.create_conversation(self.alice, 'thread')
        call = lambda n: {'type': 'function_call', 'id': f'fc_{n}', 'call_id': f'call_{n}',
            'name': 'search_conversations',
            'arguments': json.dumps({'query': f'fixture-{n}', 'person_id': None})}
        script = [[({'type': 'response.completed', 'response': {'output': [call(n)]}}, 'fixture')]
                  for n in range(1, 11)]
        script.append([({'type': 'response.output_text.delta',
                        'delta': 'A model-led answer based on the available synthetic reads.'}, 'fixture'),
                       ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')])
        model, transport = self.model(script)
        with patch('m2.gateway.execute_read', wraps=execute) as read:
            status = run_turn(self.store, self.alice, 'thread', 'later-reads', 'Synthetic', model,
                lambda _: None, model_provider='chatgpt_plan', model_slug='synthetic-response-model')
        self.assertEqual(status, 'complete')
        self.assertEqual(read.call_count, 10)
        self.assertEqual(len(transport.calls), 11)
        self.assertTrue(all(body['tools'] for body in transport.calls))
        self.assertTrue(all(body.get('tool_choice') != 'none' for body in transport.calls))
        events = self.store.read_turn(self.alice, 'thread', 'later-reads')['events']
        self.assertEqual(sum(e['kind'] == 'tool_result' for e in events), 10)
        self.assertEqual(events[-1]['kind'], 'complete')
