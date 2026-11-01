"""Synthetic raw HTTP/SSE to Responses parser and owner-scoped archive boundaries."""

import json
from datetime import datetime
import unittest

import httpx

from m2.charts import Charts
from m2.gateway import run_turn
from m2.provider_model import ResponsesModel, _valid_read_arguments
from m2.siwc import OpenAITransport, ProviderFailure, RESPONSES
from m2.test_support import DatabaseCase


PRIVATE = 'synthetic-private-marker-never-in-error'
CALL = {'type': 'function_call', 'id': 'fc-native-1', 'call_id': 'call-native-1',
        'name': 'get_chart', 'arguments': '{"chart_id":"chart-synthetic"}'}


def added(item, kind='response.output_item.added', index=0):
    return {'type': kind, 'output_index': index, 'item': item}


def completed(output):
    return {'type': 'response.completed', 'response': {'status': 'completed', 'output': output,
            'usage': {'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 110}}}


def slim_footer(output=None):
    response = {'status': 'completed'}
    if output is not None:
        response['output'] = output
    return {'type': 'response.completed', 'response': response}


def streamed_call(delta=None):
    return [added({'type': 'function_call', 'id': CALL['id'],
                   'call_id': CALL['call_id'], 'name': CALL['name'], 'arguments': ''}),
            {'type': 'response.function_call_arguments.delta', 'output_index': 0,
             'item_id': CALL['id'], 'delta': CALL['arguments'] if delta is None else delta},
            {'type': 'response.function_call_arguments.done', 'output_index': 0,
             'item_id': CALL['id'], 'arguments': CALL['arguments']},
            added(CALL, 'response.output_item.done')]


def text(value):
    return {'type': 'response.output_text.delta', 'delta': value}


class FixtureBridge:
    def __init__(self, exchanges):
        self.exchanges = exchanges
        self.requests = []
        self.transport = OpenAITransport()
        self.transport.client.close()
        self.transport.client = httpx.Client(transport=httpx.MockTransport(self._http),
                                              trust_env=False, follow_redirects=False)

    def _http(self, request):
        assert str(request.url) == RESPONSES
        assert request.headers['authorization'] == 'Bearer synthetic-access'
        body = json.loads(request.content)
        self.requests.append(body)
        events = self.exchanges.pop(0)
        data = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events)
        return httpx.Response(200, headers={'content-type': 'text/event-stream',
                'x-request-id': 'req-synthetic'}, content=(data + 'data: [DONE]\n\n').encode())

    def access(self, owner):
        assert owner == 'alice'
        return 'synthetic-access'

    def models(self, owner):
        assert owner == 'alice'
        return [{'slug': 'gpt-6.1-sol', 'context_window': 100000,
                 'max_output_tokens': 10000}]

    def close(self):
        self.transport.close()


def model_for(*exchanges):
    bridge = FixtureBridge(list(exchanges))
    return ResponsesModel(bridge, 'alice', 'gpt-6.1-sol'), bridge


class OutputParserTests(unittest.TestCase):
    def test_slim_footer_replays_completed_reasoning_message_and_tool_without_repeating_text(self):
        reasoning = {'type': 'reasoning', 'id': 'rs-private',
                     'encrypted_content': PRIVATE, 'summary': []}
        message = {'type': 'message', 'id': 'msg-one', 'role': 'assistant',
                   'status': 'completed', 'phase': 'commentary',
                   'content': [{'type': 'output_text', 'text': 'Checking chart.'}]}
        events = [added({'type': 'reasoning', 'id': reasoning['id']}, index=0),
                  added(reasoning, 'response.output_item.done', index=0),
                  added({'type': 'message', 'id': message['id'], 'content': []}, index=1),
                  {'type': 'response.output_text.delta', 'output_index': 1,
                   'item_id': message['id'], 'delta': 'Checking chart.'},
                  added(message, 'response.output_item.done', index=1)]
        events.extend({**item, 'output_index': 2} for item in streamed_call())
        for footer in (slim_footer([]), completed([
                {'type': 'reasoning', 'id': reasoning['id'], 'summary': []}, message, CALL])):
            with self.subTest(footer=footer):
                model, bridge = model_for(events + [footer],
                                          [text('Completed.'), slim_footer([])])
                try:
                    first = list(model.create_completion('Question'))
                    self.assertEqual(first[0]['choices'][0]['text'], 'Checking chart.')
                    self.assertEqual(len([part for part in first if 'tool_call' in part]), 1)
                    followup = list(model.continue_completion([{'type': 'function_call_output',
                        'call_id': CALL['call_id'], 'output': '{}'}]))
                    self.assertEqual([part['choices'][0]['text'] for part in followup],
                                     ['Completed.', ''])
                    self.assertEqual(bridge.requests[1]['input'][1:4], [reasoning, message, CALL])
                    self.assertEqual(bridge.requests[1]['input'][4]['call_id'], CALL['call_id'])
                    self.assertEqual(len(bridge.requests), 2)
                finally:
                    bridge.close()

    def test_completed_stream_call_survives_omitted_and_empty_final_output(self):
        for footer in (slim_footer(), slim_footer([]), completed([CALL])):
            with self.subTest(footer=footer):
                model, bridge = model_for(streamed_call(delta='{"chart_id":') + [footer],
                    [text('Synthetic answer'), slim_footer()])
                try:
                    events = list(model.create_completion('Question'))
                    self.assertEqual(events[0]['tool_call'], {'call_id': CALL['call_id'],
                                     'name': CALL['name'], 'arguments': CALL['arguments']})
                    self.assertEqual(list(model.continue_completion([{
                        'type': 'function_call_output', 'call_id': CALL['call_id'],
                        'output': '{}'}]))[0]['choices'][0]['text'], 'Synthetic answer')
                    self.assertEqual(bridge.requests[1]['input'][1], CALL)
                    self.assertEqual(len(bridge.requests), 2)
                finally:
                    bridge.close()

    def test_numeric_return_calls_accept_both_completed_footer_shapes(self):
        examples = {
            'get_solar_return': {'chart_id': 'chart-synthetic', 'year': 2026,
                                 'latitude': 55.68, 'longitude': -12},
            'get_lunar_returns': {'chart_id': 'chart-synthetic',
                                  'start_utc': '2026-01-01T00:00:00Z',
                                  'end_utc': '2026-02-01T00:00:00Z',
                                  'latitude': 0, 'longitude': 12.5},
            'get_planetary_returns': {'chart_id': 'chart-synthetic', 'body': 'saturn',
                                      'start_utc': '2026-01-01T00:00:00Z',
                                      'end_utc': '2026-02-01T00:00:00Z',
                                      'latitude': 40.7, 'longitude': -73.9},
        }
        for name, arguments in examples.items():
            call = {**CALL, 'name': name, 'arguments': json.dumps(arguments)}
            for footer in (slim_footer([]), completed([call])):
                with self.subTest(name=name, footer=footer['response']['output']):
                    model, bridge = model_for([added(call, 'response.output_item.done'), footer])
                    try:
                        self.assertEqual(list(model.create_completion('Return'))[0]['tool_call'],
                                         {'call_id': call['call_id'], 'name': name,
                                          'arguments': call['arguments']})
                    finally:
                        bridge.close()
            for invalid in (True, None, '55.68', float('nan'), float('inf')):
                with self.subTest(name=name, invalid=invalid):
                    changed = {**arguments, 'latitude': invalid}
                    self.assertFalse(_valid_read_arguments(name, json.dumps(changed)))
            self.assertFalse(_valid_read_arguments(name, json.dumps({**arguments, 'owner': 'bob'})))

    def test_arguments_done_supplies_missing_item_done_arguments_without_guessing(self):
        events = streamed_call()
        events[-1] = added({key: value for key, value in CALL.items()
                            if key != 'arguments'}, 'response.output_item.done')
        model, bridge = model_for(events + [slim_footer([])])
        try:
            self.assertEqual(list(model.create_completion('Question'))[0]['tool_call'],
                             {'call_id': CALL['call_id'], 'name': CALL['name'],
                              'arguments': CALL['arguments']})
        finally:
            bridge.close()

    def test_partial_announcement_matches_native_item_and_call_ids_through_continuation(self):
        partial = {key: CALL[key] for key in ('type', 'id', 'name')}
        model, bridge = model_for(
            [added(partial), {'type': 'response.function_call_arguments.delta',
                              'output_index': 0, 'item_id': CALL['id'], 'delta': CALL['arguments']},
             added(CALL, 'response.output_item.done'), completed([CALL])],
            [text('Final answer.'), completed([{'type': 'message', 'content': [
                {'type': 'output_text', 'text': 'Final answer.'}]}])])
        try:
            result = list(model.create_completion('Question'))
            self.assertEqual(result, [{'tool_call': {'call_id': CALL['call_id'],
                                 'name': 'get_chart', 'arguments': CALL['arguments']}}])
            continuation = list(model.continue_completion([{'type': 'function_call_output',
                              'call_id': CALL['call_id'], 'output': '{}'}]))
            self.assertEqual(continuation[-1]['choices'][0]['finish_reason'], 'stop')
            self.assertEqual(continuation[0]['choices'][0]['text'], 'Final answer.')
            self.assertEqual(bridge.requests[0]['parallel_tool_calls'], False)
            self.assertEqual(bridge.requests[1]['input'][1], CALL)
            self.assertEqual(bridge.requests[1]['input'][2]['call_id'], CALL['call_id'])
            self.assertEqual(len(bridge.requests), 2)
        finally:
            bridge.close()

    def test_no_text_deltas_but_completed_message_text_is_delivered_once(self):
        message = {'type': 'message', 'id': 'msg-synthetic', 'role': 'assistant',
                   'content': [{'type': 'output_text', 'text': 'Only completed text.'}]}
        model, bridge = model_for([added(message, 'response.output_item.done'), slim_footer([])])
        try:
            self.assertEqual([part['choices'][0]['text'] for part in
                model.create_completion('Question')], ['Only completed text.', ''])
        finally:
            bridge.close()

    def test_final_only_function_call_is_still_supported(self):
        model, bridge = model_for([completed([CALL])])
        try:
            self.assertEqual(list(model.create_completion('Question'))[0]['tool_call']['call_id'],
                             CALL['call_id'])
        finally:
            bridge.close()

    def test_rejections_are_distinct_bounded_and_never_execute_a_call(self):
        cases = [
            ('multiple_calls', [completed([CALL, {**CALL, 'id': 'fc-native-2',
                 'call_id': 'call-native-2'}])]),
            ('identifier_mismatch', [added(CALL), completed([{**CALL, 'id': 'fc-other'}])]),
            ('identifier_mismatch', [added(CALL),
                 added({**CALL, 'call_id': 'call-other'}, 'response.output_item.done'),
                 completed([CALL])]),
            ('identifier_mismatch', [added(CALL),
                 added({**CALL, 'arguments': '{"x":1}'}, 'response.output_item.done'),
                 completed([CALL])]),
            ('unsupported_item', [completed([{'type': PRIVATE, 'payload': PRIVATE}])]),
            ('unsupported_content_part', [completed([{'type': 'message', 'content':
                [{'type': 'refusal', 'refusal': PRIVATE}]}])]),
            ('unsupported_content_part', [completed([{'type': 'message',
                'content': {'type': PRIVATE}}])]),
        ]
        for category, events in cases:
            with self.subTest(category=category, events=events):
                model, bridge = model_for(events)
                try:
                    with self.assertRaises(ProviderFailure) as failure:
                        list(model.create_completion(PRIVATE))
                    public = failure.exception.public()
                    self.assertEqual(public['reason'], 'unsupported_provider_output')
                    self.assertEqual(public['request_id'], 'req-synthetic')
                    self.assertEqual(public['diagnostic']['category'], category)
                    self.assertLessEqual(public['diagnostic']['output_items'], 8)
                    self.assertNotIn(PRIVATE, json.dumps(public))
                    self.assertEqual(len(bridge.requests), 1)
                finally:
                    bridge.close()

    def test_slim_footer_does_not_promote_partial_conflicting_or_unsupported_items(self):
        half = [streamed_call()[0], streamed_call()[1], streamed_call()[2]]
        cases = [
            ('incomplete_item', half + [slim_footer()]),
            ('incomplete_item', [streamed_call()[0], slim_footer([])]),
            ('incomplete_item', [added({'type': 'message', 'id': 'msg-partial'}),
                text('Partial visible text'), slim_footer([])]),
            ('identifier_mismatch', [added(CALL, 'response.output_item.done', index=9),
                                     slim_footer([])]),
            ('identifier_mismatch', [streamed_call()[0],
                added({**CALL, 'id': 'fc-different'}, 'response.output_item.done'), slim_footer([])]),
            ('identifier_mismatch', [streamed_call()[0],
                added({**CALL, 'call_id': 'call-different'}, 'response.output_item.done'), slim_footer([])]),
            ('identifier_mismatch', [streamed_call()[0], streamed_call()[1],
                streamed_call()[2], added({**CALL, 'arguments': '{"other":1}'},
                                       'response.output_item.done'), slim_footer([])]),
            ('identifier_mismatch', streamed_call() +
                [completed([{**CALL, 'arguments': '{"other":1}'}])]),
            ('identifier_mismatch', [added({'type': 'reasoning', 'id': CALL['id']}, index=1),
                added({'type': 'reasoning', 'id': CALL['id']},
                      'response.output_item.done', index=1)] + streamed_call() + [slim_footer([])]),
            ('multiple_calls', streamed_call() + [added({**CALL, 'id': 'fc-other',
                'call_id': 'call-other'}, 'response.output_item.done', index=1), slim_footer([])]),
            ('unsupported_item', [added({'type': PRIVATE, 'id': 'item-unknown'}),
                added({'type': PRIVATE, 'id': 'item-unknown'},
                      'response.output_item.done'), slim_footer([])]),
        ]
        for category, events in cases:
            with self.subTest(category=category, events=events):
                model, bridge = model_for(events)
                try:
                    with self.assertRaises(ProviderFailure) as failure:
                        list(model.create_completion('Synthetic input'))
                    public = failure.exception.public()
                    self.assertEqual(public['reason'], 'unsupported_provider_output')
                    self.assertEqual(public['diagnostic']['category'], category)
                    self.assertEqual(public['diagnostic']['footer_output_present'],
                                     'output' in events[-1]['response'])
                    self.assertNotIn(PRIVATE, json.dumps(public))
                    self.assertEqual(len(bridge.requests), 1)
                finally:
                    bridge.close()

    def test_reconstructed_tool_requires_advertised_name_and_json_schema(self):
        for override in ({'name': 'delete_archive'}, {'arguments': '{not-json'},
                         {'arguments': '{}'},
                         {'arguments': '{"chart_id":42}'},
                         {'arguments': '{"chart_id":"chart-synthetic","owner":"bob"}'}):
            with self.subTest(override=override):
                changed = {**CALL, **override}
                model, bridge = model_for([added(changed, 'response.output_item.done'),
                                           slim_footer([])])
                try:
                    with self.assertRaisesRegex(ProviderFailure, 'invalid_provider_tool_call'):
                        list(model.create_completion('Question'))
                    self.assertEqual(len(bridge.requests), 1)
                finally:
                    bridge.close()

    def test_terminal_failure_eof_or_empty_unknown_stream_never_executes_call(self):
        for terminal, reason in [(slim_footer([]), 'invalid_provider_output'),
                                 ({'type': 'response.failed'}, 'response_failed'),
                                 ({'type': 'response.incomplete'}, 'response_incomplete'),
                                 ({'type': 'response.completed', 'response': {'status': 'incomplete'}},
                                  'provider_incomplete'),
                                 (None, 'provider_stream_ended_without_completion')]:
            with self.subTest(reason=reason):
                events = ([] if reason == 'invalid_provider_output' else streamed_call())
                if terminal is not None:
                    events.append(terminal)
                model, bridge = model_for(events)
                try:
                    with self.assertRaisesRegex(ProviderFailure, reason):
                        list(model.create_completion('Synthetic input'))
                    self.assertEqual(len(bridge.requests), 1)
                finally:
                    bridge.close()

    def test_cancelling_after_committed_prefix_does_not_release_completed_tool(self):
        model, bridge = model_for([text('Synthetic prefix ' * 20),
                                   *streamed_call(), slim_footer([])])
        try:
            stream = model.create_completion('Question')
            self.assertIn('Synthetic prefix', next(stream)['choices'][0]['text'])
            stream.close()
            self.assertEqual(len(bridge.requests), 1)
        finally:
            bridge.close()

    def test_diagnostic_constructor_drops_unbounded_or_untrusted_metadata(self):
        self.assertNotIn('diagnostic', ProviderFailure('unsupported_provider_output',
            diagnostic={'phase': 'completed_output', 'category': PRIVATE,
                        'payload': PRIVATE}).public())


class OutputArchiveTests(DatabaseCase):
    def test_http_sse_tool_prefix_continuation_and_replay_are_archived_once(self):
        self.store.create_conversation(self.alice, 'provider-output')
        charts = Charts(self.store)
        charts.add_person(self.alice, 'person-synthetic', 'Synthetic profile')
        charts.add_profile(self.alice, 'profile-synthetic', {'zodiac': 'tropical',
            'house_system': 'none', 'node_type': 'true', 'aspects': ['conjunction']})
        charts.add_birth(self.alice, 'person-synthetic', 'birth-synthetic', 'UTC',
                         'synthetic supplied time', wall_time=datetime(2024, 3, 20, 3, 6))
        charts.create_chart(self.alice, 'chart-synthetic', 'person-synthetic',
                            'birth-synthetic', 'profile-synthetic', 1)
        prefix = 'Committed prefix ' * 20  # exceeds the parser's incremental flush threshold
        reasoning = {'type': 'reasoning', 'id': 'rs-synthetic',
                     'encrypted_content': PRIVATE, 'summary': []}
        message = {'type': 'message', 'id': 'msg-synthetic', 'role': 'assistant',
                   'content': [{'type': 'output_text', 'text': prefix}]}
        first = [added({'type': 'reasoning', 'id': reasoning['id']}, index=0),
                 added(reasoning, 'response.output_item.done', index=0),
                 added({'type': 'message', 'id': message['id']}, index=1),
                 {**text(prefix), 'output_index': 1, 'item_id': message['id']},
                 added(message, 'response.output_item.done', index=1)]
        first.extend({**event, 'output_index': 2} for event in streamed_call())
        model, bridge = model_for(
            first + [slim_footer([])],
            [text('Synthetic final.'), completed([{'type': 'message', 'content': [
                {'type': 'output_text', 'text': 'Synthetic final.'}]}])])
        delivered = []
        try:
            status = run_turn(self.store, self.alice, 'provider-output', 'turn',
                              'Read a selected chart', model, delivered.append,
                              model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                              selected_people=[{'person_id': 'person-synthetic',
                                                'chart_id': 'chart-synthetic'}],
                              interpret_commands=False)
            self.assertEqual(status, 'complete')
            archived = self.store.read_turn(self.alice, 'provider-output', 'turn')
            kinds = [event['kind'] for event in archived['events']]
            call_index = next(index for index, event in enumerate(archived['events'])
                if event['kind'] == 'tool_call' and
                event['payload'].get('origin') == 'model_requested')
            self.assertLess(kinds.index('assistant_chunk'), call_index)
            self.assertEqual(kinds[call_index + 1], 'tool_result')
            self.assertEqual(''.join(event['payload']['content'] for event in archived['events']
                    if event['kind'] == 'assistant_chunk'), prefix + 'Synthetic final.')
            self.assertEqual([event['payload']['id'] for event in archived['events'][call_index:]
                    if event['kind'] in ('tool_call', 'tool_result')],
                    [CALL['call_id'], CALL['call_id']])
            self.assertEqual([event['kind'] for event in delivered], kinds[1:])
            self.assertEqual(bridge.requests[1]['input'][1:4], [reasoning, message, CALL])
            self.assertEqual(bridge.requests[1]['input'][4]['call_id'], CALL['call_id'])
            self.assertNotIn(PRIVATE, json.dumps(archived['events'], default=str))
            result = json.loads(bridge.requests[1]['input'][4]['output'])
            self.assertEqual(result['chart_id'], 'chart-synthetic')
            self.assertEqual(result['source_status'], 'current')
            self.assertEqual(archived['selected_people'][0]['chart_id'], 'chart-synthetic')
            self.assertEqual(run_turn(self.store, self.alice, 'provider-output', 'turn',
                    'Read a selected chart', model, lambda _: None,
                    selected_people=[{'person_id': 'person-synthetic',
                                      'chart_id': 'chart-synthetic'}],
                    model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                    interpret_commands=False), 'complete')
            self.assertEqual(len(bridge.requests), 2)
        finally:
            bridge.close()

    def test_rejected_output_leaves_archived_prefix_but_no_tool_effect(self):
        self.store.create_conversation(self.alice, 'provider-output')
        prefix = 'Already committed ' * 20
        model, bridge = model_for([text(prefix), completed([CALL, {**CALL, 'id': 'fc-other',
                                       'call_id': 'call-other'}])])
        try:
            with self.assertRaises(ProviderFailure) as failure:
                run_turn(self.store, self.alice, 'provider-output', 'turn',
                         'Read a selected chart', model, lambda _: None,
                         model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                         interpret_commands=False)
            self.assertEqual(failure.exception.public()['diagnostic']['category'], 'multiple_calls')
            kinds = [event['kind'] for event in
                     self.store.read_turn(self.alice, 'provider-output', 'turn')['events']]
            self.assertIn('assistant_chunk', kinds)
            self.assertNotIn('tool_call', kinds)
            self.assertNotIn('tool_result', kinds)
            self.assertEqual(len(bridge.requests), 1)
        finally:
            bridge.close()
