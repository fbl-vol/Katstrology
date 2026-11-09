"""Real synthetic natal records through the owned gateway and controlled Responses transport."""

import json
from pathlib import Path
import time

from m2.people.birth_flow import BirthFlow
from m2.calculation.advanced import Advanced
from m2.provider.local_model import DEFAULT_MODEL, model_at
from m2.chat.prompting import HOSTED, SUMMARY, identity
from m2.chat.tone_profiles import DEFAULT, archived_instructions, instructions
from m2.chat.recall import rebuild_pending
from m2.chat.gateway import run_turn
from m2.people.people import People
from m2.provider.responses import ResponsesModel
from m2.provider.model_capacity import resolve_capacity
from m2.chat.compaction import _checkpoint, _last_usage, digest, model_policy, turn_text
from m2.archive.revisions import correct, select_branch
from unittest.mock import patch
from m2.provider.siwc import ProviderBridge, ProviderFailure
from tests.support.database import DatabaseCase


class CapturedResponses:
    def __init__(self):
        self.requests = []
        self.catalog = [{'slug': 'gpt-6.1-sol'}]
        self.summary_behavior = 'normal'
        self.on_summary = None
        self.usage = True

    def models(self, _owner):
        return self.catalog

    def access(self, _owner):
        return 'synthetic-only'

    @property
    def transport(self):
        return self

    def response_events(self, _token, body):
        self.requests.append(body)
        if body['instructions'] == SUMMARY:
            if self.on_summary:
                self.on_summary()
            if self.summary_behavior == 'provider_failed':
                yield {'type': 'response.failed', 'response': {'error': {
                    'code': 'synthetic_summary_failed'}}}, 'synthetic-request'
                return
            if self.summary_behavior == 'tool_call_delta':
                yield {'type': 'response.output_item.added', 'item': {
                    'type': 'function_call', 'name': 'fictional_tool'}}, 'synthetic-request'
                return
            sources = json.loads(body['input'][0]['content'][0]['text'])
            prior = sources['previous_checkpoint'] or ''
            old_ids = prior.split('Covered turn IDs: ')[1].split('\n')[0].split(', ') if (
                'Covered turn IDs: ' in prior) else []
            new_ids = [turn_id for turn_id, _ in sources['newly_retired_eligible_turns']]
            answer = ('## Attributed user reports and preferences\nSynthetic discussion, not verified data.\n'
                      '## Prior assistant interpretations (not evidence)\nSynthetic fixture reply.\n'
                      '## Chart/person/version and other source references\nCovered turn IDs: ' +
                      ', '.join(old_ids + new_ids) + '\n'
                      '## Uncertainty, corrections and open questions\nNo fresh transits calculated.')
            if self.summary_behavior == 'empty':
                answer = ''
            if self.summary_behavior == 'oversized':
                answer = 'S' * 4097
        else:
            answer = 'Synthetic bounded reply'
        if answer:
            yield {'type': 'response.output_text.delta', 'delta': answer}, 'synthetic-request'
        if body['instructions'] == SUMMARY and self.summary_behavior == 'incomplete':
            yield {'type': 'response.incomplete', 'response': {
                'incomplete_details': {'reason': 'max_output_tokens'}}}, 'synthetic-request'
            return
        units = len(body['input'][0]['content'][0]['text'].encode()) // 3
        usage = {'input_tokens': units, 'output_tokens': 25, 'total_tokens': units + 25} if self.usage else {
            'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}
        output = [{'type': 'function_call', 'name': 'fictional_tool'}] if (
            body['instructions'] == SUMMARY and self.summary_behavior == 'tool_call') else []
        yield {'type': 'response.completed', 'response': {'usage': usage,
                                                         'output': output}}, 'synthetic-request'


class ContextOnlyCatalog(CapturedResponses):
    def models(self, _token):
        # Reachable provider row: the optional output bound is absent, not null.
        return {'models': [{'slug': 'gpt-6.1-sol', 'display_name': 'Synthetic Sol',
                            'visibility': 'list', 'context_window': 500_000,
                            'file_input_supported': True}]}

    def close(self):
        pass


class ChatBudgetTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.person = People(self.store).add(self.alice, 'Synthetic dense reader')
        self.chart = BirthFlow(self.store).generate(self.alice, self.person['id'], {
            'request_id': 'dense-chart-synthetic', 'birth_date': '2000-06-09',
            'birth_time': '13:00', 'time_unknown': False,
            'birthplace': 'Synthetic London reference (not verified coordinates)',
            'place_id': None, 'provisional': True, 'zone_override': 'Europe/London',
            'latitude_override': 51.5, 'longitude_override': -1 / 6,
            'fold': None, 'settings': None,
        })['chart']
        self.assertEqual(self.chart['result']['natal']['status'], 'complete')
        self.assertGreaterEqual(len(self.chart['result']['natal']['aspects']), 20)
        self.store.create_conversation(self.alice, 'budget-thread')
        self.bridge = CapturedResponses()
        self.model = ResponsesModel(self.bridge, 'alice', 'gpt-6.1-sol')
        self.selected = [{'person_id': self.person['id'], 'chart_id': self.chart['id']}]

    def turn(self, turn_id, text, selected=None, parent='@active', model=None,
             provider='chatgpt_plan', conv_id='budget-thread', cancelled=None, acknowledge=None):
        events = []
        status = run_turn(self.store, self.alice, conv_id, turn_id, text,
                          model or self.model, events.append, parent_id=parent,
                          selected_people=self.selected if selected is None else selected,
                          model_provider=provider, cancelled=cancelled,
                          model_slug=(model or self.model).slug if provider == 'chatgpt_plan' else None,
                          acknowledge=acknowledge)
        return status, events

    def test_synthetic_provider_sees_saturn_return_and_mc_defining_metadata(self):
        result = Advanced(self.store).save(self.alice, 'saturn-source', self.person['id'],
            'planetary_return', {'body': 'saturn',
              'start_utc': '2029-01-01T00:00:00+00:00',
              'end_utc': '2032-01-01T00:00:00+00:00',
              'latitude': 51.5, 'longitude': -1 / 6})
        self.assertEqual(result['status'], 'supported')
        self.assertTrue(result['events'])
        events = []
        status = run_turn(self.store, self.alice, 'budget-thread', 'selected-saturn',
            'What is this selected Saturn return?', self.model, events.append,
            selected_people=self.selected, model_provider='chatgpt_plan',
            model_slug=self.model.slug,
            selected_result={'result_id': 'saturn-source', 'event_index': 0})
        self.assertEqual(status, 'complete')
        tool = next(event['payload'] for event in events
                    if event['kind'] == 'tool_result' and event['payload'].get('name') == 'read_selected_result')
        self.assertEqual(tool['facts']['body'], 'saturn')
        self.assertEqual(tool['parameters']['body'], 'saturn')
        self.assertEqual(tool['reference_place']['latitude'], 51.5)
        submitted = json.dumps(self.bridge.requests[-1]['input'], ensure_ascii=False)
        self.assertIn('saturn', submitted)
        self.assertIn('planet-own-natal-longitude-all-passes-v1', submitted)
        self.assertNotIn('fictional journal entry', submitted)

        contact = Advanced(self.store).save(self.alice, 'mc-source', self.person['id'],
            'mc_transit', {'start_utc': '2024-03-01T00:00:00+00:00',
                           'end_utc': '2024-03-30T00:00:00+00:00',
                           'transit_body': 'moon', 'aspect': 'conjunction'})
        self.assertEqual(contact['status'], 'supported')
        self.assertTrue(contact['events'])
        status = run_turn(self.store, self.alice, 'budget-thread', 'selected-mc',
            'What is this selected MC contact?', self.model, lambda _: None,
            selected_people=self.selected, model_provider='chatgpt_plan',
            model_slug=self.model.slug,
            selected_result={'result_id': 'mc-source', 'event_index': 0})
        self.assertEqual(status, 'complete')
        model_input = self.bridge.requests[-1]['input'][-1]['content'][0]['text']
        for marker in ('"transit_body_id": "moon"', '"natal_body_id": "midheaven"',
                       '"aspect": "conjunction"', '"target_degrees"'):
            self.assertIn(marker, model_input)

    def test_paragraph_with_selected_dense_natal_reaches_hosted_transport(self):
        text = ('I want a thoughtful overview of the pattern in this natal chart. '
                'How might the Venus and Mercury placements colour communication and relationship themes? '
                'Please distinguish computed aspects from interpretation, connect the major tensions '
                'without predicting specific future events, and explain what would require current sky '
                'calculations or cited sources before you could make a claim about a cycle this month. ') * 2
        status, events = self.turn('paragraph', text)
        self.assertEqual(status, 'complete')
        self.assertEqual(len(self.bridge.requests), 1)
        context = next(e['payload'] for e in events if e['kind'] == 'context')
        self.assertLessEqual(context['prompt_tokens'] + context['instruction_tokens']
                             + context['reply_reserve'], context['context_limit'])
        self.assertEqual(context['count_method'], 'conservative_utf8_byte_estimate')
        self.assertEqual(context['context_limit'], 1_050_000)
        self.assertEqual(context['model_max_output_tokens'], 128_000)
        self.assertEqual(context['reply_reserve'], 16_384)
        self.assertEqual(context['capacity_source'], 'openai_api_model_docs_direct_plan_unverified')
        self.assertFalse(context['capacity_route_verified'])
        tone_text, tone_identity = instructions(DEFAULT)
        self.assertEqual({key: context[key] for key in tone_identity}, tone_identity)
        from m2.chat.agent_reads import TOOLS
        self.assertEqual(context['instruction_tokens'],
                         (len((tone_text + json.dumps(TOOLS, ensure_ascii=False, separators=(',', ':'))).encode()) + 1) // 2)
        sent = self.bridge.requests[0]
        self.assertEqual(sent['instructions'], tone_text)
        self.assertNotIn(HOSTED, sent['input'][0]['content'][0]['text'])
        self.assertIn(self.chart['id'], sent['input'][0]['content'][0]['text'])
        self.assertIn('positions=', sent['input'][0]['content'][0]['text'])
        self.assertIn('cusps=', sent['input'][0]['content'][0]['text'])
        self.assertIn(text, sent['input'][0]['content'][0]['text'])
        self.assertEqual(self.store.read_turn(self.alice, 'budget-thread', 'paragraph')
                         ['selected_people'][0]['chart_id'], self.chart['id'])

    def test_switch_during_provider_read_keeps_accepted_identity_on_continuation_and_replay(self):
        case = self

        class SwitchDuringRead(CapturedResponses):
            def response_events(self, _token, body):
                self.requests.append(body)
                if len(self.requests) == 1:
                    case.store.set_tone_preference(case.alice, 'grounded-warmth', 0)
                    yield {'type': 'response.completed', 'response': {'usage': {
                        'input_tokens': 500, 'output_tokens': 30, 'total_tokens': 530},
                        'output': [{'type': 'function_call', 'id': 'fc_1', 'call_id': 'call_1',
                                    'name': 'list_reference_sources',
                                    'arguments': '{"after":null}'}]}}, 'synthetic-first'
                else:
                    yield {'type': 'response.output_text.delta', 'delta': 'Read complete'}, 'synthetic-next'
                    yield {'type': 'response.completed', 'response': {'usage': {
                        'input_tokens': 600, 'output_tokens': 20, 'total_tokens': 620},
                        'output': []}}, 'synthetic-next'

        bridge = SwitchDuringRead()
        model = ResponsesModel(bridge, 'alice', 'gpt-6.1-sol')
        status, events = self.turn('switch-mid-read', 'Which sources are selected?', model=model)
        self.assertEqual(status, 'complete', events[-1]['payload'])
        self.assertEqual(len(bridge.requests), 2)
        first, continuation = bridge.requests
        self.assertEqual(first['instructions'], instructions(DEFAULT)[0])
        self.assertEqual(continuation['instructions'], first['instructions'])
        self.assertEqual(continuation['store'], False)
        self.assertEqual(next(e['payload'] for e in events if e['kind'] == 'context')['prompt_sha256'],
                         instructions(DEFAULT)[1]['prompt_sha256'])
        self.assertTrue(any(e['kind'] == 'tool_result' for e in events))
        replay, _ = self.turn('switch-mid-read', 'Which sources are selected?', model=model)
        self.assertEqual(replay, 'complete')
        self.assertEqual(len(bridge.requests), 2)
        next_status, next_events = self.turn('regenerated-after-switch',
                                              'Which sources are selected?', parent='@root', model=model)
        self.assertEqual(next_status, 'complete', next_events[-1]['payload'])
        self.assertEqual(bridge.requests[-1]['instructions'], instructions('grounded-warmth')[0])
        original = self.store.read_turn(self.alice, 'budget-thread', 'switch-mid-read')
        self.assertEqual(original['events'][0]['payload']['tone'], instructions(DEFAULT)[1])

    def test_revised_and_old_tones_bind_real_requests_reads_budgets_and_replay(self):
        from m2.chat.agent_reads import TOOLS
        from tests.chat.test_tone_versions import legacy_identity

        class ReadThenAnswer(CapturedResponses):
            def response_events(self, _token, body):
                self.requests.append(body)
                if len(self.requests) <= 2:
                    index = len(self.requests)
                    yield {'type': 'response.completed', 'response': {'output': [{
                        'type': 'function_call', 'id': f'fc_tone_{index}',
                        'call_id': f'call_tone_{index}', 'name': 'list_reference_sources',
                        'arguments': '{"after":null}'}]}}, f'tone-read-{index}'
                else:
                    yield {'type': 'response.output_text.delta', 'delta': 'Synthetic factual answer'}, 'tone-answer'
                    yield {'type': 'response.completed', 'response': {'output': []}}, 'tone-answer'

        prompt = 'How could I approach a creative disagreement without making a prediction?'
        for tone_id in ('thoughtful-wit', 'grounded-warmth', 'playful-cheek', 'cosmic-cabaret'):
            for version in (1, 2, 3, 4):
                with self.subTest(tone_id=tone_id, version=version):
                    revision = self.store.tone_preference(self.alice)['revision']
                    self.store.set_tone_preference(self.alice, tone_id, revision)
                    turn_id = f'{tone_id}-v{version}'
                    expected = (archived_instructions(legacy_identity(tone_id, version)) if version < 4
                                else instructions(tone_id))
                    bridge = ReadThenAnswer()
                    model = ResponsesModel(bridge, 'alice', self.model.slug)
                    if version < 4:
                        # Accept an older version, switch to current code at ACK, then
                        # reconstruct the first request and every read from its record.
                        accepting_older = patch('m2.chat.tone_profiles.instructions', return_value=expected)
                        accepting_older.start()
                        try:
                            status, events = self.turn(turn_id, prompt, parent='@root', model=model,
                                                      acknowledge=lambda _: accepting_older.stop())
                        finally:
                            accepting_older.stop()
                    else:
                        status, events = self.turn(turn_id, prompt, parent='@root', model=model)
                    self.assertEqual(status, 'complete', events)
                    self.assertEqual(instructions(tone_id)[1]['tone_version'], 4)
                    # Two requested reads require three calls, not an extra closing call.
                    self.assertEqual(len(bridge.requests), 3)
                    self.assertEqual(sum(event['kind'] == 'tool_result' and
                                         event['payload'].get('name') == 'list_reference_sources'
                                         for event in events), 2)
                    for index, request in enumerate(bridge.requests):
                        self.assertEqual(request['instructions'], expected[0])
                        for previous in range(1, index + 1):
                            self.assertIn(f'call_tone_{previous}', json.dumps(request['input']))
                    context = next(event['payload'] for event in events if event['kind'] == 'context')
                    self.assertEqual({key: context[key] for key in expected[1]}, expected[1])
                    self.assertEqual(context['instruction_tokens'],
                                     (len((expected[0] + json.dumps(TOOLS, ensure_ascii=False, separators=(',', ':'))).encode()) + 1) // 2)
                    self.assertEqual(self.store.read_turn(self.alice, 'budget-thread', turn_id)
                                     ['events'][0]['payload']['tone'], expected[1])
                    replay, _ = self.turn(turn_id, prompt, parent='@root', model=model)
                    self.assertEqual(replay, 'complete')
                    self.assertEqual(len(bridge.requests), 3)

    def test_legacy_prompt_identity_remains_archived_on_idempotent_replay(self):
        status, _ = self.turn('legacy-prompt-replay', 'Synthetic chart question.', parent='@root')
        self.assertEqual(status, 'complete')
        prior_identity = {'prompt_version': '2026-10-29.4',
                          'prompt_sha256': '6709a2f5175fb0824c1f0cd833e01d2dc614a87c6a195abfa7fc55547f7b0c9b'}
        self.store.db.execute('''
            UPDATE events SET payload=payload || %s::jsonb
            WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s AND kind='context'
        ''', (json.dumps(prior_identity), self.store.owner(self.alice),
              'budget-thread', 'legacy-prompt-replay'))
        sent_before = len(self.bridge.requests)

        replay_status, replay = self.turn('legacy-prompt-replay', 'Synthetic chart question.',
                                          parent='@root')
        self.assertEqual(replay_status, 'complete')
        self.assertEqual(len(self.bridge.requests), sent_before)
        context = next(event['payload'] for event in replay if event['kind'] == 'context')
        self.assertEqual({key: context[key] for key in prior_identity}, prior_identity)
        self.assertNotEqual(prior_identity['prompt_sha256'], identity('hosted')['prompt_sha256'])

    def test_context_only_catalog_normalization_allows_greeting_and_dense_chart(self):
        transport = ContextOnlyCatalog()
        bridge = ProviderBridge(Path(self.directory.name) / 'synthetic-plan', transport)
        bridge.credentials.save('alice', {
            'selected': 'fixture-client',
            'accounts': {'fixture-client': {
                'access_token': 'synthetic-only', 'refresh_token': 'synthetic-only',
                'expires_at': time.time() + 3600,
                'scopes': ['chatgpt.tokens.use.direct']}}})
        self.addCleanup(bridge.close)
        self.assertEqual(bridge.models('alice'), [{
            'slug': 'gpt-6.1-sol', 'display_name': 'Synthetic Sol',
            'context_window': 500_000}])
        model = ResponsesModel(bridge, 'alice', 'gpt-6.1-sol')
        model.validate()
        self.assertEqual(model.context_limit, 500_000)
        self.assertEqual(model.capacity.source, 'mixed_catalog_context_documented_output')
        self.assertEqual(model.capacity.context_source, 'provider_catalog_limits')
        self.assertEqual(model.capacity.output_source,
                         'openai_api_model_docs_direct_plan_unverified')
        self.assertFalse(model.capacity.route_verified)

        greeting, greeting_events = self.turn('partial-catalog-hi', 'hi', model=model)
        self.assertEqual(greeting, 'complete', greeting_events[-1]['payload'])
        paragraph = ('Please give a substantive overview of the selected complete natal chart. '
                     'Distinguish computed positions and aspects from interpretation; explain '
                     'the main tensions and what cannot be claimed without new calculations.')
        status, events = self.turn('partial-catalog-chart', paragraph, model=model)
        self.assertEqual(status, 'complete', events[-1]['payload'])
        self.assertEqual(len(transport.requests), 2)
        context = next(e['payload'] for e in events if e['kind'] == 'context')
        self.assertEqual(context['context_limit'], 500_000)
        self.assertEqual(context['model_max_output_tokens'], 128_000)
        self.assertEqual(context['capacity_source'], 'mixed_catalog_context_documented_output')
        self.assertFalse(context['capacity_route_verified'])
        self.assertEqual(context['context_capacity_source'], 'provider_catalog_limits')
        self.assertTrue(context['context_capacity_route_verified'])
        self.assertEqual(context['output_capacity_source'],
                         'openai_api_model_docs_direct_plan_unverified')
        self.assertFalse(context['output_capacity_route_verified'])
        self.assertLess(context['prompt_tokens'] + context['instruction_tokens'] +
                        context['reply_reserve'], 500_000)
        self.assertIn(self.chart['id'], transport.requests[1]['input'][0]['content'][0]['text'])
        self.assertIn('positions=', transport.requests[1]['input'][0]['content'][0]['text'])
        self.assertIn(paragraph, transport.requests[1]['input'][0]['content'][0]['text'])
        self.assertEqual(transport.requests[1]['instructions'], instructions(DEFAULT)[0])

    def test_greeting_followups_keep_all_eligible_history_below_threshold(self):
        status, events = self.turn('greeting', 'hi')
        self.assertEqual(status, 'complete')
        self.assertEqual(next(e['payload'] for e in events if e['kind'] == 'context')['recent_turns'], 0)
        for index in range(6):
            text = f'Synthetic follow-up {index}: ' + ('Reflect on the chart themes, not live transits. ' * 52)
            status, events = self.turn(f'follow-{index}', text)
            self.assertEqual(status, 'complete', events[-1]['payload'])
            rebuild_pending(self.store, self.alice)
        budget = next(e['payload'] for e in events if e['kind'] == 'context')
        self.assertEqual(budget['recent_turns'], 6)
        self.assertEqual(budget['summary_covered_ids'], [])
        self.assertEqual(budget['older_not_in_prompt'], 0)
        self.assertIn(self.chart['id'], self.bridge.requests[-1]['input'][0]['content'][0]['text'])
        self.assertIn('positions=', self.bridge.requests[-1]['input'][0]['content'][0]['text'])
        self.assertLessEqual(budget['prompt_tokens'] + budget['instruction_tokens']
                             + budget['reply_reserve'], budget['context_limit'])

    def test_multiple_selected_people_keep_chart_identity_without_synthetic_synastry(self):
        other = People(self.store).add(self.alice, 'Second synthetic reader')
        chart = BirthFlow(self.store).generate(self.alice, other['id'], {
            'request_id': 'second-synthetic-chart', 'birth_date': '2024-03-20',
            'birth_time': '03:06', 'time_unknown': False,
            'birthplace': 'Copenhagen, Capital Region, Denmark', 'place_id': '2618425',
            'provisional': True, 'zone_override': None, 'latitude_override': None,
            'longitude_override': None, 'fold': None, 'settings': None,
        })['chart']
        selected = self.selected + [{'person_id': other['id'], 'chart_id': chart['id']}]
        status, events = self.turn('two-charts', 'Compare the supported natal themes without claiming calculated synastry.', selected)
        self.assertEqual(status, 'complete', events[-1]['payload'])
        self.assertEqual({e['payload']['chart_id'] for e in events if e['kind'] == 'tool_result'},
                         {self.chart['id'], chart['id']})
        prompt = self.bridge.requests[0]['input'][0]['content'][0]['text']
        self.assertIn(self.chart['id'], prompt)
        self.assertIn(chart['id'], prompt)
        self.assertIn('multiple people are not a calculated synastry', prompt)
        self.assertEqual({row['person_id']: row['chart_id'] for row in self.store.read_turn(
            self.alice, 'budget-thread', 'two-charts')['selected_people']},
            {self.person['id']: self.chart['id'], other['id']: chart['id']})

    def test_oversized_hosted_input_fails_before_provider_then_new_turn_recovers(self):
        text = 'Synthetic too large for four dense charts. ' + ('X' * 4000)
        selected = list(self.selected)
        for index in range(3):
            other = People(self.store).add(self.alice, f'Additional synthetic reader {index}')
            chart = BirthFlow(self.store).generate(self.alice, other['id'], {
                'request_id': f'dense-additional-{index}', 'birth_date': '2000-06-09',
                'birth_time': '13:00', 'time_unknown': False,
                'birthplace': 'Synthetic London reference (not verified coordinates)',
                'place_id': None, 'provisional': True, 'zone_override': 'Europe/London',
                'latitude_override': 51.5, 'longitude_override': -1 / 6,
                'fold': None, 'settings': None,
            })['chart']
            selected.append({'person_id': other['id'], 'chart_id': chart['id']})
        self.bridge.catalog.append({'slug': 'synthetic-smaller-route',
                                    'context_window': 8192, 'max_output_tokens': 1024})
        small = ResponsesModel(self.bridge, 'alice', 'synthetic-smaller-route')
        status, events = self.turn('too-large', text, selected, model=small)
        self.assertEqual(status, 'error')
        self.assertEqual(events[-1]['payload']['code'], 'hosted_text_capacity_exceeded')
        self.assertEqual(events[-1]['payload']['count_method'], 'conservative_utf8_byte_estimate')
        self.assertEqual(self.bridge.requests, [])
        self.assertEqual(len([e for e in events if e['kind'] == 'tool_result']), 4)
        self.assertFalse(any(e['kind'] == 'context' for e in events))
        archived = self.store.read_turn(self.alice, 'budget-thread', 'too-large')
        self.assertEqual(archived['events'][0]['payload']['content'], text)
        replay_status, replay = self.turn('too-large', text, selected, model=small)
        self.assertEqual(replay_status, 'error')
        self.assertEqual([e['payload'] for e in replay], [e['payload'] for e in events])
        self.assertEqual(self.bridge.requests, [])
        recovered, _ = self.turn('fresh', 'A new short question about this saved chart.')
        self.assertEqual(recovered, 'complete')
        self.assertEqual(len(self.bridge.requests), 1)

    def test_small_advertised_window_compacts_twice_and_reconstructs_after_restart(self):
        self.bridge.catalog.append({'slug': 'synthetic-compact', 'context_window': 32768,
                                    'max_output_tokens': 2048})
        model = ResponsesModel(self.bridge, 'alice', 'synthetic-compact')
        for index in range(12):
            text = (f'Synthetic topic {index}: compare natal Venus/Mercury with their supported '
                    'aspects, and keep current transit claims separate. ' +
                    'This is a reported preference rather than computed sky evidence. ' * 34)
            status, events = self.turn(f'compact-{index}', text, model=model)
            self.assertEqual(status, 'complete', events[-1]['payload'])
            context = next(e['payload'] for e in events if e['kind'] == 'context')
            self.assertLessEqual(context['prompt_tokens'] + context['instruction_tokens']
                                 + context['reply_reserve'], context['context_limit'])
            sent = self.bridge.requests[-1]['input'][0]['content'][0]['text']
            self.assertIn(self.chart['id'], sent)
            self.assertEqual(sent.count('positions='), 1)
            self.assertEqual(sent.count('cusps='), 1)
        rows = self.store.db.execute('''
            SELECT id,covered_ids,first_kept_id,summary,usage,source_head
            FROM compaction_checkpoints WHERE owner_id='alice' AND conversation_id='budget-thread'
            ORDER BY id
        ''').fetchall()
        self.assertGreaterEqual(len(rows), 2)
        for prior, later in zip(rows, rows[1:]):
            self.assertEqual(later['covered_ids'][:len(prior['covered_ids'])], prior['covered_ids'])
            self.assertGreater(len(later['covered_ids']), len(prior['covered_ids']))
        self.assertIn('## Attributed user reports', rows[-1]['summary'])
        self.assertIn('compact-0', rows[-1]['summary'])
        self.assertGreater(rows[-1]['usage']['input_tokens'], 0)
        self.assertIn(rows[-1]['first_kept_id'], self.store.ancestry(
            self.alice, 'budget-thread', rows[-1]['source_head']))
        summary_requests = [body for body in self.bridge.requests if body['instructions'] == SUMMARY]
        self.assertEqual(len(summary_requests), len(rows))
        self.assertTrue(all('max_output_tokens' in body and
                            len(body['input'][0]['content']) == 1 for body in summary_requests))
        first_original = self.store.read_turn(self.alice, 'budget-thread', 'compact-0')
        self.assertEqual(first_original['events'][0]['payload']['content'].split(':')[0],
                         'Synthetic topic 0')
        self.store.close()
        from m2.archive.store import Store
        self.store = Store(self.dsn, self.store.files, self.ledger)
        self.alice = self.store.authenticate('alice', 'synthetic-password-alice')
        restored, events = self.turn('after-restart',
                                     'A new synthetic question about natal themes after restart.', model=model)
        self.assertEqual(restored, 'complete', events[-1]['payload'])
        checkpoint_id = next(e['payload'] for e in events if e['kind'] == 'context')
        self.assertGreaterEqual(checkpoint_id['compaction_checkpoint_id'], rows[-1]['id'])
        # A tighter reserved read-tool envelope may retire another old turn;
        # it must extend the durable checkpoint rather than discard its coverage.
        latest = self.store.db.execute('''
            SELECT covered_ids FROM compaction_checkpoints WHERE id=%s
        ''', (checkpoint_id['compaction_checkpoint_id'],)).fetchone()
        self.assertEqual(latest['covered_ids'][:len(rows[-1]['covered_ids'])],
                         rows[-1]['covered_ids'])

    def test_summary_failures_do_not_publish_or_rerun_archived_turns(self):
        # Leave mandatory declarations/tone/chart room; the longer history must
        # exercise summary failure, not the separate mandatory-input refusal.
        self.bridge.catalog.append({'slug': 'synthetic-compact', 'context_window': 24576,
                                    'max_output_tokens': 2048})
        compact_model = ResponsesModel(self.bridge, 'alice', 'synthetic-compact')
        for behavior in ('empty', 'oversized', 'incomplete', 'tool_call',
                         'tool_call_delta', 'provider_failed', 'cancel', 'changed'):
            with self.subTest(behavior=behavior):
                conv = f'failure-{behavior}'
                self.store.create_conversation(self.alice, conv)
                for index in range(8):
                    status, _ = self.turn(f'prefix-{index}',
                        f'Synthetic prior topic {index}: ' + 'ordinary discussion. ' * 100,
                        conv_id=conv)
                    self.assertEqual(status, 'complete')
                before = len(self.bridge.requests)
                flag = [False]
                self.bridge.summary_behavior = behavior if behavior not in ('cancel', 'changed') else 'normal'
                if behavior == 'cancel':
                    self.bridge.on_summary = lambda: flag.__setitem__(0, True)
                elif behavior == 'changed':
                    self.bridge.on_summary = lambda: self.store._changed('alice', conv)
                else:
                    self.bridge.on_summary = None
                status, events = self.turn('failed-compaction', 'Synthetic current request',
                                           model=compact_model, conv_id=conv,
                                           cancelled=lambda: flag[0])
                self.bridge.on_summary = None
                self.bridge.summary_behavior = 'normal'
                self.assertEqual(status, 'error', (behavior, events[-1]['payload']))
                self.assertEqual(events[-1]['payload']['code'], 'compaction_failed')
                self.assertEqual([e['payload']['status'] for e in events
                                  if e['kind'] == 'compaction'], ['starting', 'failed'])
                self.assertFalse(any(e['kind'] in ('context', 'assistant_chunk') for e in events))
                self.assertEqual(self.store.db.execute('''
                    SELECT count(*) AS n FROM compaction_checkpoints
                    WHERE owner_id='alice' AND conversation_id=%s
                ''', (conv,)).fetchone()['n'], 0)
                self.assertTrue(all(body['instructions'] == SUMMARY for body in
                                    self.bridge.requests[before:]))
                replay_status, replay = self.turn('failed-compaction', 'Synthetic current request',
                                                  model=compact_model, conv_id=conv)
                self.assertEqual(replay_status, 'error')
                self.assertEqual([e['payload'] for e in replay], [e['payload'] for e in events])

    def test_checkpoint_identity_branch_correction_person_and_usage_fences(self):
        self.bridge.catalog.append({'slug': 'synthetic-compact', 'context_window': 24576,
                                    'max_output_tokens': 2048})
        compact = ResponsesModel(self.bridge, 'alice', 'synthetic-compact')
        for index in range(9):
            status, _ = self.turn(f'fenced-{index}',
                                  f'Original synthetic report {index}: ' + 'reflective theme. ' * 115,
                                  model=compact)
            self.assertEqual(status, 'complete', _)
        owner, conv = 'alice', 'budget-thread'
        checkpoint = self.store.db.execute('''
            SELECT * FROM compaction_checkpoints WHERE owner_id=%s AND conversation_id=%s
            ORDER BY id DESC LIMIT 1
        ''', (owner, conv)).fetchone()
        self.assertIsNotNone(checkpoint)
        latest = self.store.active_head(self.alice, conv)
        context = next(e['payload'] for e in self.store.read_turn(
            self.alice, conv, latest)['events'] if e['kind'] == 'context')
        revision = context['compaction_revision']
        self.assertEqual(_last_usage(self.store, self.alice, conv, latest, compact,
                                     context['selected_sha256'], revision,
                                     context['compaction_checkpoint_id'], context),
                         next(e['payload']['input_tokens'] for e in self.store.read_turn(
                             self.alice, conv, latest)['events'] if e['kind'] == 'usage'))
        self.assertIsNone(_last_usage(self.store, self.alice, conv, latest, compact,
                                      digest([{'person_id': 'other'}]), revision,
                                      context['compaction_checkpoint_id']))
        changed_policy = ResponsesModel(self.bridge, 'alice', 'synthetic-compact')
        changed_policy.validate()
        changed_policy.context_limit = 272000  # Simulate newly advertised route metadata.
        self.assertIsNone(_last_usage(self.store, self.alice, conv, latest, changed_policy,
                                      context['selected_sha256'], revision,
                                      context['compaction_checkpoint_id']))
        history = [(turn_id, '') for turn_id in self.store.ancestry(self.alice, conv, latest)]
        changed_tone = instructions('cosmic-cabaret')[1]
        self.assertIsNone(_checkpoint(self.store, owner, conv, history, revision,
                                       compact, context['selected_sha256'], changed_tone))
        self.assertIsNone(_last_usage(self.store, self.alice, conv, latest, compact,
                                      context['selected_sha256'], revision,
                                      context['compaction_checkpoint_id'], changed_tone))
        with self.assertRaises(KeyError):
            self.store.ancestry(self.bob, conv, latest)
        self.assertEqual(self.store.db.execute('''
            SELECT count(*) AS n FROM compaction_checkpoints
            WHERE owner_id='bob' AND conversation_id=%s
        ''', (conv,)).fetchone()['n'], 0)
        other = People(self.store).add(self.alice, 'Unrelated synthetic reader')
        selected_other = [{'person_id': other['id'], 'chart_id': None}]
        status, events = self.turn('other-person', 'General question for the other reader.',
                                   selected=selected_other, model=self.model)
        self.assertEqual(status, 'complete', events[-1]['payload'])
        other_context = next(e['payload'] for e in events if e['kind'] == 'context')
        self.assertIsNone(other_context['compaction_checkpoint_id'])
        self.assertNotEqual(other_context['selected_sha256'], context['selected_sha256'])
        self.assertEqual(len([item for item in other_context['selected_profiles']
                              if item['person_id'] == other['id']]), 1)
        self.assertIsNone(_last_usage(self.store, self.alice, conv, 'other-person', compact,
                                      context['selected_sha256'], revision,
                                      checkpoint['id']))
        source = checkpoint['covered_ids'][0]
        self.assertTrue(correct(self.store, self.alice, conv, 'fix-old', source,
                                'correct', 'Corrected synthetic report; earlier words withdrawn.'))
        self.assertGreater(self.store._conversation(owner, conv)['compaction_revision'], revision)
        repaired, result = self.turn('after-correction', 'Only use the correction.',
                                     parent=source, model=self.model)
        self.assertEqual(repaired, 'complete', result[-1]['payload'])
        prompt = self.bridge.requests[-1]['input'][0]['content'][0]['text']
        self.assertIn('Corrected synthetic report', prompt)
        self.assertNotIn('Original synthetic report 0', prompt)
        prior_revision = self.store._conversation(owner, conv)['compaction_revision']
        select_branch(self.store, self.alice, conv, source)
        self.assertGreater(self.store._conversation(owner, conv)['compaction_revision'], prior_revision)
        self.assertGreater(self.store.db.execute('''
            SELECT count(*) AS n FROM compaction_checkpoints
            WHERE owner_id='alice' AND conversation_id=%s
        ''', (conv,)).fetchone()['n'], 0)  # Append-only historical checkpoints.

    def test_positive_provider_usage_anchors_followup_trigger_not_hard_fit(self):
        first, _ = self.turn('measured-first', 'A short synthetic natal question.')
        self.assertEqual(first, 'complete')
        status, events = self.turn('measured-followup',
                                   'Another synthetic question about saved chart aspects.')
        self.assertEqual(status, 'complete', events[-1]['payload'])
        context = next(e['payload'] for e in events if e['kind'] == 'context')
        self.assertEqual(context['projection_source'], 'provider_usage_plus_estimated_tail')
        self.assertEqual(context['count_method'], 'conservative_utf8_byte_estimate')
        self.assertLess(context['prompt_tokens'] + context['instruction_tokens']
                        + context['reply_reserve'], context['context_limit'])
        self.assertNotEqual(context['prompt_tokens'],
                            next(e['payload']['input_tokens'] for e in events if e['kind'] == 'usage'))

    def test_malformed_archived_usage_is_not_a_context_anchor(self):
        first, _ = self.turn('invalid-usage-first', 'Synthetic provider usage question.')
        self.assertEqual(first, 'complete')
        self.store.db.execute('''
            UPDATE events SET payload=jsonb_set(payload, '{input_tokens}', '"invalid"'::jsonb)
            WHERE owner_id='alice' AND conversation_id='budget-thread'
              AND turn_id='invalid-usage-first' AND kind='usage'
        ''')
        status, events = self.turn('invalid-usage-followup',
                                   'Continue with estimated context only.')
        self.assertEqual(status, 'complete', events[-1]['payload'])
        context = next(e['payload'] for e in events if e['kind'] == 'context')
        self.assertEqual(context['projection_source'], 'text_estimate')

    def test_zero_usage_falls_back_to_estimates_and_tool_pair_stays_together(self):
        self.store.begin(self.alice, 'budget-thread', 'large-tool',
                         'Synthetic past tool question', None)
        self.store.append(self.alice, 'budget-thread', 'large-tool', 'tool_call',
                          {'name': 'synthetic_lookup', 'request': 'saved evidence only'})
        self.store.append(self.alice, 'budget-thread', 'large-tool', 'tool_result',
                          {'name': 'synthetic_lookup', 'result': 'Z' * 6000})
        self.store.append(self.alice, 'budget-thread', 'large-tool', 'assistant_chunk',
                          {'content': 'Prior assistant claim is not source evidence.'})
        self.store.append(self.alice, 'budget-thread', 'large-tool', 'complete', {})
        text = turn_text(self.store, self.alice, 'budget-thread', 'large-tool',
                         {'budget-thread': {'large-tool'}}, {})
        self.assertIn('[tool_call #1 of large-tool]', text)
        self.assertIn('[tool_result #2 of large-tool]', text)
        self.assertIn('characters omitted', text)
        self.assertLess(len(text), 2600)
        self.assertIn('Z' * 6000, str(self.store.read_event(
            self.alice, 'budget-thread', 'large-tool', 2)['payload']))
        self.bridge.usage = False
        self.bridge.catalog.append({'slug': 'synthetic-compact', 'context_window': 32768,
                                    'max_output_tokens': 2048})
        model = ResponsesModel(self.bridge, 'alice', 'synthetic-compact')
        for index in range(10):
            status, events = self.turn(f'no-usage-{index}',
                 'Synthetic reflection that adds ordinary past discussion. ' * 42,
                 model=model)
            self.assertEqual(status, 'complete', events[-1]['payload'])
            self.assertFalse(any(e['kind'] == 'usage' for e in events))
        self.assertGreater(self.store.db.execute('''
            SELECT count(*) AS n FROM compaction_checkpoints
            WHERE owner_id='alice' AND conversation_id='budget-thread'
        ''').fetchone()['n'], 0)
        context = next(e['payload'] for e in events if e['kind'] == 'context')
        self.assertEqual(context['projection_source'], 'text_estimate')
        self.assertEqual(context['count_method'], 'conservative_utf8_byte_estimate')
        for body in (request for request in self.bridge.requests
                     if request['instructions'] == SUMMARY):
            source = body['input'][0]['content'][0]['text']
            if 'large-tool' in source:
                self.assertIn('[tool_call #1 of large-tool]', source)
                self.assertIn('[tool_result #2 of large-tool]', source)
                self.assertNotIn('Z' * 6000, source)
                break
        else:
            self.fail('The first tool call/result pair never reached the bounded summary source')

    def test_route_catalog_limits_are_distinct_from_docs_and_unknown_is_not_4k(self):
        for window in (500_000, 272_000):
            with self.subTest(window=window):
                advertised = resolve_capacity({'slug': 'gpt-6.1-sol',
                                               'context_window': window,
                                               'max_output_tokens': 128_000})
                self.assertEqual(advertised.context_window, window)
                self.assertEqual(advertised.source, 'provider_catalog_limits')
                self.assertTrue(advertised.route_verified)
                self.bridge.catalog = [{'slug': 'gpt-6.1-sol',
                                        'context_window': window,
                                        'max_output_tokens': 128_000}]
                status, events = self.turn(f'advertised-{window}',
                                           'Synthetic chart question with route-specific limits.',
                                           model=ResponsesModel(self.bridge, 'alice', 'gpt-6.1-sol'))
                self.assertEqual(status, 'complete', events[-1]['payload'])
                context = next(e['payload'] for e in events if e['kind'] == 'context')
                self.assertEqual(context['context_limit'], window)
                self.assertEqual(context['capacity_source'], 'provider_catalog_limits')
                self.assertTrue(context['capacity_route_verified'])
        documented = resolve_capacity({'slug': 'gpt-6.1-sol'})
        self.assertEqual(documented.context_window, 1_050_000)
        self.assertEqual(documented.source, 'openai_api_model_docs_direct_plan_unverified')
        self.assertFalse(documented.route_verified)
        context_only = resolve_capacity({'slug': 'gpt-6.1-sol', 'context_window': 500_000})
        self.assertEqual((context_only.context_window, context_only.max_output_tokens),
                         (500_000, 128_000))
        self.assertEqual(context_only.source, 'mixed_catalog_context_documented_output')
        self.assertTrue(context_only.context_route_verified)
        self.assertFalse(context_only.output_route_verified)
        output_only = resolve_capacity({'slug': 'gpt-6.1-sol', 'max_output_tokens': 32_000})
        self.assertEqual((output_only.context_window, output_only.max_output_tokens),
                         (1_050_000, 32_000))
        self.assertEqual(output_only.source, 'mixed_documented_context_catalog_output')
        self.assertFalse(output_only.context_route_verified)
        self.assertTrue(output_only.output_route_verified)
        self.bridge.catalog = [{'slug': 'gpt-6.1-sol', 'max_output_tokens': 32_000}]
        status, events = self.turn('advertised-output-only', 'hi',
                                   model=ResponsesModel(self.bridge, 'alice', 'gpt-6.1-sol'))
        self.assertEqual(status, 'complete', events[-1]['payload'])
        budget = next(e['payload'] for e in events if e['kind'] == 'context')
        self.assertEqual(budget['capacity_source'], 'mixed_documented_context_catalog_output')
        self.assertFalse(budget['context_capacity_route_verified'])
        self.assertTrue(budget['output_capacity_route_verified'])
        self.bridge.catalog = [{'slug': 'gpt-6.1-sol', 'context_window': 500_000}]
        partial = ResponsesModel(self.bridge, 'alice', 'gpt-6.1-sol')
        partial.validate()
        self.bridge.catalog = [{'slug': 'gpt-6.1-sol', 'context_window': 500_000,
                                'max_output_tokens': 128_000}]
        paired = ResponsesModel(self.bridge, 'alice', 'gpt-6.1-sol')
        paired.validate()
        self.assertNotEqual(model_policy(partial), model_policy(paired))
        self.bridge.catalog = [{'slug': 'gpt-6.1-sol', 'context_window': 8192}]
        small = ResponsesModel(self.bridge, 'alice', 'gpt-6.1-sol')
        small.validate()
        self.assertEqual(small.context_limit, 8192)
        self.assertEqual(small.reply_reserve, 2048)
        for model in ({'slug': 'gpt-6.1-sol', 'context_window': '500000'},
                      {'slug': 'gpt-6.1-sol', 'context_window': None},
                      {'slug': 'gpt-6.1-sol', 'context_window': True},
                      {'slug': 'gpt-6.1-sol', 'context_window': 2047},
                      {'slug': 'gpt-6.1-sol', 'context_window': 2_000_000},
                      {'slug': 'gpt-6.1-sol', 'max_output_tokens': None},
                      {'slug': 'gpt-6.1-sol', 'max_output_tokens': True},
                      {'slug': 'gpt-6.1-sol', 'max_output_tokens': 0},
                      {'slug': 'gpt-6.1-sol', 'max_output_tokens': 128_001},
                      {'slug': 'gpt-6.1-sol', 'context_window': 8192,
                       'max_output_tokens': 8192},
                      {'slug': 'unknown', 'context_window': False}):
            with self.subTest(model=model), self.assertRaisesRegex(
                    ProviderFailure, 'invalid_model_context_metadata'):
                resolve_capacity(model)
        for model in ({'slug': 'unknown'}, {'slug': 'unknown', 'context_window': 8192},
                      {'slug': 'unknown', 'max_output_tokens': 1024}):
            with self.subTest(model=model), self.assertRaisesRegex(
                    ProviderFailure, 'model_context_capacity_unknown'):
                resolve_capacity(model)
        sent_before_unknown = len(self.bridge.requests)
        self.bridge.catalog = [{'slug': 'unknown'}]
        unknown = ResponsesModel(self.bridge, 'alice', 'unknown')
        with self.assertRaisesRegex(ProviderFailure, 'model_context_capacity_unknown'):
            unknown.validate()
        self.assertEqual(len(self.bridge.requests), sent_before_unknown)

    def test_current_local_instructions_fit_a_short_general_turn_at_2048(self):
        local = model_at(DEFAULT_MODEL)
        try:
            class LocalCapture:
                context_limit = 2048
                tokenize = local.tokenize

                def create_completion(self, *_args, **_kwargs):
                    yield {'choices': [{'text': 'Synthetic answer.', 'finish_reason': 'stop'}]}

            self.store.create_conversation(self.alice, 'short-local-thread')
            events = []
            status = run_turn(self.store, self.alice, 'short-local-thread', 'local-short',
                              'Hi, what can a chart tell us?', LocalCapture(), events.append)
            self.assertEqual(status, 'complete', events[-1]['payload'])
            budget = next(event['payload'] for event in events if event['kind'] == 'context')
            self.assertEqual({key: budget[key] for key in identity('local')}, identity('local'))
            self.assertLessEqual(budget['prompt_tokens'] + budget['reply_reserve'], 2048)
        finally:
            local.close()

    def test_2048_local_model_keeps_a_small_selected_chart_in_context(self):
        local = model_at(DEFAULT_MODEL)
        try:
            people = People(self.store)
            people.charts.add_person(self.alice, 'solar-person', 'Synthetic solar reader')
            birth = people.add_birth(self.alice, 'solar-person', {
                'mode': 'exact', 'zone': 'UTC', 'wall_time': '2024-03-20T03:06:00'})
            chart = people.create_chart(self.alice, 'solar-person', birth, 'solar-default', 1)
            self.store.create_conversation(self.alice, 'solar-thread')

            test = self
            class LocalCapture:
                context_limit = 2048
                tokenize = local.tokenize

                def create_completion(self, prompt, **_kwargs):
                    test.assertIn('solar-person', prompt)
                    test.assertIn(chart['id'], prompt)
                    yield {'choices': [{'text': 'Synthetic answer.', 'finish_reason': 'stop'}]}

            events = []
            status = run_turn(self.store, self.alice, 'solar-thread', 'solar-turn',
                              'Explain this saved Sun position.', LocalCapture(), events.append,
                              selected_people=[{'person_id': 'solar-person', 'chart_id': chart['id']}])
            self.assertEqual(status, 'complete', events[-1]['payload'])
            budget = next(event['payload'] for event in events if event['kind'] == 'context')
            self.assertLessEqual(budget['prompt_tokens'] + budget['reply_reserve'], 2048)
            self.assertEqual({key: budget[key] for key in identity('local')}, identity('local'))
        finally:
            local.close()

    def test_actual_2048_local_model_reports_dense_chart_limit_without_inference(self):
        local = model_at(DEFAULT_MODEL)
        try:
            class LocalCapture:
                context_limit = 2048
                tokenize = local.tokenize

                def create_completion(self, *_args, **_kwargs):
                    raise AssertionError('Local inference must not run when mandatory chart cannot fit')

            events = []
            status = run_turn(self.store, self.alice, 'budget-thread', 'local-greeting',
                              'hi', LocalCapture(), events.append, selected_people=self.selected)
            self.assertEqual(status, 'error')
            self.assertEqual(events[-1]['payload']['code'], 'local_model_context_limit')
            self.assertEqual(events[-1]['payload']['context_limit'], 2048)
            self.assertEqual(events[-1]['payload']['count_method'], 'model_tokenizer')
            self.assertEqual(len([e for e in events if e['kind'] == 'tool_result']), 1)
            self.assertFalse(any(e['kind'] == 'context' for e in events))
        finally:
            local.close()
