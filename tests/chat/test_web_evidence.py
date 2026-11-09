"""Owned PostgreSQL + synthetic Responses web continuation and recovery contracts."""

from datetime import datetime, timezone, timedelta
import json
from unittest.mock import patch
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.archive.backup import backup, restore
from m2.provider.siwc import ProviderFailure

from m2.chat.gateway import run_turn, turn_steps
from m2.provider.steps import ProviderStep, next_provider
from tests.support.database import DatabaseCase
from tests.provider.test_provider_output_compat import model_for, completed, text, slim_footer
from tests.chat.test_tool_evidence_budget import native_call
from tests.provider.test_web_capabilities import ARGS
from m2.chat.tool_evidence import prepare, MAX_MODEL_EVIDENCE_BYTES
from m2.chat.web_evidence import read_content, WEB_MODEL_BYTES


SEARCH_OUTPUT = [{'type': 'web_search_call', 'id': 'search-one', 'status': 'completed',
    'action': {'sources': [{'url': 'https://news.example/story', 'title': 'Public report'}]}},
    {'type': 'message', 'id': 'summary-one', 'content': [{'type': 'output_text',
        'text': 'Reporting differs; the date is unknown.', 'annotations': []}]}]
ANSWER = [text('Supported symbolic interpretation, not proof of causation.'), slim_footer([])]


class WebEvidenceTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.store.create_conversation(self.alice, 'public-thread')

    def test_search_separates_private_prompt_and_archives_before_continuation(self):
        model, bridge = model_for(native_call(1, 'web_search', ARGS),
                                  [completed(SEARCH_OUTPUT)], ANSWER)
        original = bridge.transport.response_events
        def observe(token, body):
            if len(bridge.requests) == 2:
                events = self.store.read_turn(self.alice, 'public-thread', 'one')['events']
                self.assertEqual(events[-1]['kind'], 'tool_result')
                self.assertEqual(events[-1]['payload']['id'], 'call-1')
            yield from original(token, body)
        bridge.transport.response_events = observe
        try:
            self.assertEqual(run_turn(self.store, self.alice, 'public-thread', 'one',
                'PRIVATE SYNTHETIC CHART CONTEXT; public news please', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug=model.slug), 'complete')
            self.assertNotIn('PRIVATE', json.dumps(bridge.requests[1]))
            self.assertEqual(json.loads(bridge.requests[1]['input']), ARGS)
            self.assertEqual(bridge.requests[2]['input'][-1]['call_id'], 'call-1')
            original_count = len(bridge.requests)
            self.store.recover_open()
            self.assertEqual(run_turn(self.store, self.alice, 'public-thread', 'one',
                'PRIVATE SYNTHETIC CHART CONTEXT; public news please', model, lambda _: None,
                model_provider='chatgpt_plan',
                model_slug=model.slug), 'complete')
            self.assertEqual(len(bridge.requests), original_count)
        finally:
            bridge.close()

    def test_page_deep_read_owner_expiry_and_historical_content(self):
        content = 'Opening. ' + 'public background ' * 700 + 'Later passage matters.'
        page = {'status': 'ok', 'content': content, 'source_id': 'a' * 64,
                'requested_url': 'https://news.example/story', 'final_url': 'https://news.example/story',
                'retrieved_at': '2026-11-09T12:00:00+00:00', 'title': 'Synthetic story',
                'source_truncated': False}
        model, bridge = model_for(native_call(1, 'fetch_web_page', {'urls': [page['requested_url']]}), ANSWER)
        try:
            with patch('m2.chat.web_evidence.fetch_page', return_value=page) as fetch:
                self.assertEqual(run_turn(self.store, self.alice, 'public-thread', 'one',
                    'Read https://news.example/story', model, lambda _: None,
                    model_provider='chatgpt_plan', model_slug=model.slug), 'complete')
                self.assertEqual(fetch.call_count, 1)
            args = {'conversation_id': 'public-thread', 'turn_id': 'one', 'source_id': 'a' * 64,
                    'offset': 0, 'find': 'Later passage'}
            passage = read_content(self.store, self.alice, args)
            self.assertEqual(passage['content'], 'Later passage matters.')
            self.assertEqual(passage['offset'], content.index('Later passage'))
            with self.assertRaises((PermissionError, KeyError)):
                read_content(self.store, self.bob, args)
            future = datetime.now(timezone.utc) + timedelta(days=8)
            with patch('m2.chat.web_evidence.datetime') as clock:
                clock.now.return_value = future
                self.assertEqual(read_content(self.store, self.alice, args)['status'], 'expired')
            events = self.store.read_turn(self.alice, 'public-thread', 'one')['events']
            archived = next(e['payload'] for e in events if e['kind'] == 'tool_result')
            self.assertEqual(archived['result']['pages'][0]['content'], content)
            self.assertLessEqual(archived['model_projection_bytes'], 3072)
            snapshot = Path(self.directory.name) / 'web-snapshot'
            backup(self.store, snapshot)
            target = 'kat_m2_restored_' + uuid4().hex[:12]
            dsn = make_conninfo(self.admin_dsn, dbname=target)
            with psycopg.connect(self.admin_dsn, autocommit=True) as db:
                db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
            recovered = None
            try:
                recovered = restore(snapshot, dsn, Path(self.directory.name) / 'restored', self.ledger)
                user = recovered.authenticate('alice', 'synthetic-password-alice')
                self.assertEqual(read_content(recovered, user, args)['content'], 'Later passage matters.')
            finally:
                if recovered:
                    recovered.close()
                with psycopg.connect(self.admin_dsn, autocommit=True) as db:
                    db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
            # Use the actual deletion journal, not a cache-specific cleanup path.
            self.ledger.delete_conversation(self.store, self.alice, 'public-thread')
            with self.assertRaises((PermissionError, KeyError)):
                read_content(self.store, self.alice, args)
        finally:
            bridge.close()

    def test_followup_discovers_long_article_without_refetch_even_after_compaction(self):
        from tests.chat.test_chat_budget import CapturedResponses
        from m2.provider.responses import ResponsesModel
        from m2.chat.prompting import SUMMARY
        from m2.archive.revisions import correct, select_branch

        for compacted in (False, True):
            with self.subTest(compacted=compacted):
                conv = 'compacted-web' if compacted else 'recent-web'
                self.store.create_conversation(self.alice, conv)
                source_id, url = uuid4().hex * 2, 'https://news.example/story'
                page = {'status': 'ok', 'content': 'Public background. ' * 600 + 'Later passage matters.',
                        'source_id': source_id, 'requested_url': url, 'final_url': url,
                        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'title': 'Synthetic story',
                        'source_truncated': False, 'content_kind': 'untrusted_public_page_text'}
                first, transport = model_for(native_call(1, 'fetch_web_page', {'urls': [url]}), ANSWER)
                self.addCleanup(transport.close)
                bridge = CapturedResponses()
                bridge.catalog = [{'slug': 'gpt-6.1-sol', 'context_window': 24576 if compacted else 100000,
                                   'max_output_tokens': 2048}]
                model = ResponsesModel(bridge, 'alice', 'gpt-6.1-sol')
                def turn(turn_id, prompt, selected_model=model):
                    return run_turn(self.store, self.alice, conv, turn_id, prompt, selected_model,
                                    lambda _: None, model_provider='chatgpt_plan', model_slug=selected_model.slug)
                with patch('m2.chat.web_evidence.fetch_page', return_value=page) as fetch:
                    self.assertEqual(turn('article', 'Read ' + url, first), 'complete')
                    if compacted:
                        for index in range(8):
                            self.assertEqual(turn(f'context-{index}', 'Public reflection. ' * 200), 'complete',
                                self.store.read_turn(self.alice, conv, f'context-{index}')['events'][-1])
                        rows = self.store.db.execute('SELECT covered_ids FROM compaction_checkpoints '
                            'WHERE owner_id=%s AND conversation_id=%s', ('alice', conv)).fetchall()
                        self.assertTrue(any('article' in row['covered_ids'] for row in rows))
                    original, observed = bridge.response_events, []
                    def followup(token, body):
                        if body['instructions'] == SUMMARY:
                            yield from original(token, body)
                            return
                        bridge.requests.append(body)
                        last = body['input'][-1]
                        if last.get('type') != 'function_call_output':
                            # The tool contract, not an ID injected by this test, supplies the fallback.
                            args = {'conversation_id': '', 'turn_id': '', 'source_id': '', 'offset': 0, 'find': None}
                            events = native_call(2, 'read_web_content', args)
                        else:
                            result = json.loads(last['output'])
                            observed.append(result)
                            if 'content' not in result:
                                args = {key: result[key] for key in ('conversation_id', 'turn_id', 'source_id')}
                                events = native_call(3, 'read_web_content', {**args, 'offset': 0, 'find': 'Later passage'})
                            else:
                                events = ANSWER
                        for event in events:
                            yield event, 'synthetic-followup'
                    bridge.response_events = followup
                    self.assertEqual(turn('followup', 'Find the later passage in the article already read, without refetching.'), 'complete')
                    self.assertEqual(observed[0]['conversation_id'], conv)
                    self.assertEqual(observed[0]['source_id'], source_id)
                    self.assertEqual(observed[0]['sources'][0]['url'], url)
                    self.assertEqual(observed[0]['content_kind'], 'untrusted_public_page_text')
                    self.assertEqual(observed[1]['content'], 'Later passage matters.')
                    self.assertEqual(fetch.call_count, 1)

                discover = {'conversation_id': conv, 'turn_id': '', 'source_id': '', 'offset': 0, 'find': None}
                direct = {**discover, 'turn_id': 'article', 'source_id': source_id, 'find': 'Later passage'}
                with self.assertRaises((KeyError, PermissionError)):
                    read_content(self.store, self.bob, discover)
                with self.assertRaises((KeyError, PermissionError)):
                    read_content(self.store, self.bob, direct)
                with patch('m2.chat.web_evidence.datetime') as clock:
                    clock.now.return_value = datetime.now(timezone.utc) + timedelta(days=8)
                    self.assertEqual(read_content(self.store, self.alice, discover)['status'], 'no_sources')
                    self.assertEqual(read_content(self.store, self.alice, direct)['status'], 'expired')
                correct(self.store, self.alice, conv, 'replace-article', 'article', 'correct', 'Replaced report')
                self.assertEqual(read_content(self.store, self.alice, discover)['status'], 'no_sources')
                self.assertEqual(read_content(self.store, self.alice, direct)['reason'], 'source_not_current')
                correct(self.store, self.alice, conv, 'withdraw-article', 'article', 'withdraw', None)
                self.assertEqual(read_content(self.store, self.alice, discover)['status'], 'no_sources')
                select_branch(self.store, self.alice, conv, None)
                self.assertEqual(read_content(self.store, self.alice, direct)['reason'], 'source_not_current')

    def test_external_work_is_cooperative_and_cancelled_result_never_continues(self):
        model, bridge = model_for(native_call(1, 'web_search', ARGS), [completed(SEARCH_OUTPUT)], ANSWER)
        stopped = False
        steps = turn_steps(self.store, self.alice, 'public-thread', 'one', 'Public news', model,
                           lambda _: None, model_provider='chatgpt_plan', model_slug=model.slug,
                           defer_provider=True,
                           cancelled=lambda: stopped)
        try:
            first = next(steps)
            self.assertIsInstance(first, ProviderStep)
            work = steps.send(next_provider(first.stream))
            self.assertIsInstance(work, ProviderStep)
            self.assertEqual(len(bridge.requests), 1)  # No external work on Store advance.
            self.assertEqual(self.store.read_turn(self.alice, 'public-thread', 'one')['events'][-1]['kind'], 'tool_call')
            response = next_provider(work.stream)
            stopped = True
            with self.assertRaises(StopIteration) as done:
                steps.send(response)
            self.assertEqual(done.exception.value, 'interrupted')
            self.assertEqual(len(bridge.requests), 2)
            self.store.recover_open()
            run_turn(self.store, self.alice, 'public-thread', 'one', 'Public news', model,
                     lambda _: None, model_provider='chatgpt_plan', model_slug=model.slug)
            self.assertEqual(len(bridge.requests), 2)
        finally:
            steps.close()
            bridge.close()

    def test_ambiguous_search_failure_still_allows_supported_answer_without_retry(self):
        model, bridge = model_for(native_call(1, 'web_search', ARGS), [], ANSWER)
        try:
            self.assertEqual(run_turn(self.store, self.alice, 'public-thread', 'one',
                'Use supported astrology if news fails', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug=model.slug), 'complete')
            result = json.loads(bridge.requests[2]['input'][-1]['output'])
            self.assertEqual(result['reason'], 'search_not_completed')
            self.assertEqual(len(bridge.requests), 3)
        finally:
            bridge.close()

    def test_ordinary_astrology_answer_does_not_force_public_search(self):
        model, bridge = model_for(ANSWER)
        try:
            self.assertEqual(run_turn(self.store, self.alice, 'public-thread', 'ordinary',
                'Explain what an orb means', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug=model.slug), 'complete')
            self.assertEqual(len(bridge.requests), 1)
            self.assertNotIn('tool_choice', bridge.requests[0])
            events = self.store.read_turn(self.alice, 'public-thread', 'ordinary')['events']
            self.assertFalse(any(event['kind'] == 'tool_call' for event in events))
        finally:
            bridge.close()

    def test_mixed_reporting_and_real_sky_calculation_remain_distinct(self):
        sky = {'date': '2026-11-09', 'time': '12:00', 'zone': 'UTC',
               'occurrence': 'unspecified', 'mode': 'sky', 'chart_id': None}
        model, bridge = model_for(native_call(1, 'web_search', ARGS),
            [completed(SEARCH_OUTPUT)], native_call(2, 'get_transit_view', sky), ANSWER)
        try:
            self.assertEqual(run_turn(self.store, self.alice, 'public-thread', 'mixed',
                'News and computed sky, separately', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug=model.slug), 'complete')
            events = self.store.read_turn(self.alice, 'public-thread', 'mixed')['events']
            results = [e['payload'] for e in events if e['kind'] == 'tool_result']
            self.assertEqual([r['name'] for r in results], ['web_search', 'get_transit_view'])
            geometry = results[1]['result']
            self.assertEqual(geometry['status'], 'supported')
            self.assertGreater(len(geometry['positions']), 8)
            self.assertIn('ephemeris_sha256', geometry)
            self.assertNotEqual(results[1]['model_projection_status'], 'limit')
            self.assertIsNone(results[0]['result']['sources'][0]['publication_date'])
        finally:
            bridge.close()

    def test_account_change_after_search_refuses_old_account_evidence(self):
        model, bridge = model_for(native_call(1, 'web_search', ARGS), [completed(SEARCH_OUTPUT)])
        changed = False
        def verify():
            if changed:
                raise ProviderFailure('selected_account_changed')
        model.verify_binding = verify
        steps = turn_steps(self.store, self.alice, 'public-thread', 'one', 'Public news', model,
                           lambda _: None, model_provider='chatgpt_plan', model_slug=model.slug,
                           defer_provider=True)
        try:
            first = next(steps)
            work = steps.send(next_provider(first.stream))
            response = next_provider(work.stream)
            changed = True
            with self.assertRaisesRegex(ProviderFailure, 'selected_account_changed'):
                steps.send(response)
            events = self.store.read_turn(self.alice, 'public-thread', 'one')['events']
            self.assertEqual(events[-1]['kind'], 'tool_call')
            self.assertEqual(len(bridge.requests), 2)
        finally:
            steps.close()
            bridge.close()

    def test_restart_after_external_attempt_never_reexecutes(self):
        model, bridge = model_for(native_call(1, 'web_search', ARGS), [completed(SEARCH_OUTPUT)])
        steps = turn_steps(self.store, self.alice, 'public-thread', 'one', 'Public news', model,
                           lambda _: None, model_provider='chatgpt_plan', model_slug=model.slug,
                           defer_provider=True)
        try:
            first = next(steps)
            work = steps.send(next_provider(first.stream))
            next_provider(work.stream)  # Request completed, result not yet committed.
            steps.close()
            self.store.recover_open()
            self.assertEqual(run_turn(self.store, self.alice, 'public-thread', 'one',
                'Public news', model, lambda _: None, model_provider='chatgpt_plan',
                model_slug=model.slug), 'interrupted')
            self.assertEqual(len(bridge.requests), 2)
        finally:
            steps.close()
            bridge.close()

    def test_web_allowance_preserves_chart_room_and_labels_projection_limits(self):
        used = 0
        result = {'status': 'ok', 'content': 'hostile webpage text ' * 1000,
                  'source_id': 'b' * 64, 'source_truncated': False}
        for index in range(3):
            archived, output = prepare('web_search', f'call-{index}', result, index + 1,
                                       used, None, {}, used)
            self.assertIsNotNone(output)
            used += len(output.encode())
            self.assertLessEqual(used, WEB_MODEL_BYTES)
            self.assertEqual(archived['result']['content'], result['content'])
        _, chart = prepare('get_chart', 'chart', {'positions': 'x' * 15000}, 4, used, None, {})
        self.assertIn('positions', json.loads(chart))
        self.assertLess(used + len(chart.encode()), MAX_MODEL_EVIDENCE_BYTES)
        archived, output = prepare('web_search', 'exhausted', result, 5,
                                  WEB_MODEL_BYTES, None, {}, WEB_MODEL_BYTES)
        self.assertIsNone(output)
        self.assertEqual(archived['model_projection_limit']['scope'], 'web_allowance')
        self.assertEqual(archived['model_projection_limit']['limit_bytes'], WEB_MODEL_BYTES)

    def test_projected_paging_cursor_never_skips_omitted_multibyte_text(self):
        from m2.chat.web_evidence import project_web
        result = {'content': '🪐' * 1800, 'offset': 200, 'next_offset': 2000,
                  'retained_characters': 5000, 'source_id': 'c' * 64}
        projected = project_web(result, 1000)
        self.assertLess(len(projected['content']), 1800)
        self.assertEqual(projected['next_offset'], 200 + len(projected['content']))
        self.assertEqual(projected['retained_characters'], 5000)
        self.assertEqual(result['next_offset'], 2000)  # Archive not mutated.
