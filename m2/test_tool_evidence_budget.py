"""Actual synthetic Responses HTTP/SSE, read services and PostgreSQL evidence budgets."""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.backup import backup, restore
from m2.agent_reads import execute as execute_read
from m2.birth_flow import BirthFlow
from m2.gateway import run_turn
from m2.people import People
from m2.provider_model import ResponsesModel
from m2.references import References
from m2.store import MAX_EVENT_BYTES, MAX_TOOL_RESULT_BYTES
from m2.tool_evidence import MAX_MODEL_EVIDENCE_BYTES, encoded, prepare, project
from m2.test_provider_output_compat import model_for, added, slim_footer, text
from m2.test_support import DatabaseCase


def native_call(index, name, arguments):
    if name == 'get_reference_passage':
        arguments = {**arguments, 'offset': arguments.get('offset', 0)}
    item = {'type': 'function_call', 'id': f'fc-{index}', 'call_id': f'call-{index}',
            'name': name, 'arguments': json.dumps(arguments)}
    return [added({**item, 'arguments': ''}),
            {'type': 'response.function_call_arguments.done', 'output_index': 0,
             'item_id': item['id'], 'arguments': item['arguments']},
            added(item, 'response.output_item.done'), slim_footer([])]


class ToolEvidenceBudgetTests(DatabaseCase):
    fixture_requires_fresh_migration = True
    def setUp(self):
        super().setUp()
        person = People(self.store).add(self.alice, 'Synthetic dense reader')
        chart = BirthFlow(self.store).generate(self.alice, person['id'], {
            'request_id': 'budget-chart', 'birth_date': '2000-06-09', 'birth_time': '13:00',
            'time_unknown': False, 'birthplace': 'Synthetic London reference',
            'place_id': None, 'provisional': True, 'zone_override': 'Europe/London',
            'latitude_override': 51.5, 'longitude_override': -1 / 6, 'fold': None,
            'settings': None})['chart']
        self.chart_id = chart['id']
        self.person_id = person['id']
        self.assertGreaterEqual(len(chart['result']['natal']['aspects']), 20)
        self.store.create_conversation(self.alice, 'budget-thread')

        refs = References(self.store)
        refs.add_source(self.alice, 'source-danish', 'Synthetic Danish author',
                        'Belysning af planeternes forhold', 'Fixture edition 2026',
                        'synthetic', 'interpretation', 'locally authored', 'synthetic rights')
        passage = ('Syntetisk læsning af relationer, timing og usikkerhed; '
                   'ingen påstand er selvstændigt bevist. ') * 35
        refs.add_passage(self.alice, 'source-danish', 'passage-danish', 'Afsnit 2', passage)

    def create_history_windows(self):
        self.store.create_conversation(self.alice, 'history-window')
        parent = None
        for index in range(9):
            turn_id = f'history-{index}'
            self.store.begin(self.alice, 'history-window', turn_id, '🪐' * 1000, parent)
            self.store.append(self.alice, 'history-window', turn_id, 'assistant_chunk',
                              {'content': 'Synthetic attributed response.'})
            self.store.append(self.alice, 'history-window', turn_id, 'complete', {})
            parent = turn_id

    def test_three_native_reads_commit_before_continuation_and_finish(self):
        chart = self.chart_id
        model, bridge = model_for(
            native_call(1, 'get_chart', {'chart_id': chart}),
            native_call(2, 'get_transit_view', {'date': '2026-01-01', 'time': '12:00',
                'zone': 'Europe/Copenhagen', 'occurrence': 'unspecified',
                'mode': 'natal_transits', 'chart_id': chart}),
            native_call(3, 'get_reference_passage', {
                'source_id': 'source-danish', 'passage_id': 'passage-danish'}),
            [text('Synthetic final synthesis: chart, transits and attributed Danish passage.'),
             slim_footer([])])
        try:
            status = run_turn(self.store, self.alice, 'budget-thread', 'three-reads',
                'Discuss this selected complete natal chart, today’s transits and a cited passage.',
                model, lambda _: None, model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                selected_people=[{'person_id': self.person_id, 'chart_id': chart}])
            archive = self.store.read_turn(self.alice, 'budget-thread', 'three-reads')
            self.assertEqual(status, 'complete', archive['events'][-1]['payload'].get('code'))
            self.assertEqual([e['payload']['id'] for e in archive['events']
                if e['kind'] == 'tool_result' and e['payload'].get('id') in
                {'call-1', 'call-2', 'call-3'}], ['call-1', 'call-2', 'call-3'])
            self.assertEqual(len(bridge.requests), 4)
            self.assertEqual([json.loads(bridge.requests[i]['input'][-1]['output']).get('chart_id')
                              for i in (1, 2)], [chart, chart])
            self.assertIn('læ', bridge.requests[3]['input'][-1]['output'])
            self.assertLess(len(str(archive['events'][-3]['payload']).encode()), MAX_TOOL_RESULT_BYTES)
            self.assertEqual(archive['events'][-1]['kind'], 'complete')
            self.assertEqual(run_turn(self.store, self.alice, 'budget-thread', 'three-reads',
                'Discuss this selected complete natal chart, today’s transits and a cited passage.',
                model, lambda _: None, model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                selected_people=[{'person_id': self.person_id, 'chart_id': chart}]), 'complete')
            self.assertEqual(len(bridge.requests), 4)
        finally:
            bridge.close()

    def test_eight_model_directed_reads_keep_native_association_and_finish(self):
        reads = [
            ('get_transit_view', {'date': '2026-01-01', 'time': '12:00',
                'zone': 'Europe/Copenhagen', 'occurrence': 'unspecified',
                'mode': 'natal_transits', 'chart_id': self.chart_id}),
            ('get_reference_passage', {'source_id': 'source-danish',
                'passage_id': 'passage-danish'}),
            ('search_references', {'query': 'Syntetisk', 'author': None,
                'tradition': None, 'technique': None, 'language': None}),
            *(('search_conversations', {'query': f'Synthetic {i}', 'person_id': None})
              for i in range(4, 9)),
        ]
        model, bridge = model_for(*(native_call(i, name, args) for i, (name, args) in
                                    enumerate(reads, start=1)),
            [text('Calculated sky and attributed passage support a tentative pattern; '
                  'other cycles were not checked.'), slim_footer([])])
        try:
            status = run_turn(self.store, self.alice, 'budget-thread', 'model-directed',
                'Give a careful sky overview and distinguish sourced text from calculation.',
                model, lambda _: None, model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                selected_people=[{'person_id': self.person_id, 'chart_id': self.chart_id}])
            archive = self.store.read_turn(self.alice, 'budget-thread', 'model-directed')
            self.assertEqual(status, 'complete', archive['events'][-1]['payload'])
            self.assertEqual(len(bridge.requests), 9)
            self.assertTrue(all(request['tools'] for request in bridge.requests))
            self.assertTrue(all(request.get('tool_choice') != 'none' for request in bridge.requests))
            final = bridge.requests[-1]
            self.assertEqual([row['call_id'] for row in final['input']
                              if row.get('type') == 'function_call_output'],
                             [f'call-{i}' for i in range(1, 9)])
            self.assertEqual([row['call_id'] for row in final['input']
                              if row.get('type') == 'function_call'],
                             [f'call-{i}' for i in range(1, 9)])
            self.assertEqual(len([e for e in archive['events'] if e['kind'] == 'tool_result']), 9)
            self.assertIn('other cycles were not checked', ''.join(e['payload']['content'] for e in
                archive['events'] if e['kind'] == 'assistant_chunk'))
            self.assertFalse(any(e['kind'] == 'context' and 'read_finalization' in e['payload']
                for e in archive['events']))
            self.assertEqual(run_turn(self.store, self.alice, 'budget-thread', 'model-directed',
                'Give a careful sky overview and distinguish sourced text from calculation.',
                model, lambda _: None, model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                selected_people=[{'person_id': self.person_id, 'chart_id': self.chart_id}]), 'complete')
            self.assertEqual(len(bridge.requests), 9)
        finally:
            bridge.close()

    def test_maximal_multibyte_passage_preserves_attribution_and_archive(self):
        source = References(self.store)
        large = '🪐' * 128
        source.add_source(self.alice, 'source-large', large, large, large, large,
                          large, 'synthetic original', 'synthetic rights', language='da')
        original = ('🪐' * 1000) + ' synthetic'
        source.add_passage(self.alice, 'source-large', 'passage-large', large[:64], original)
        model, bridge = model_for(
            native_call(1, 'get_reference_passage', {
                'source_id': 'source-large', 'passage_id': 'passage-large'}),
            [text('Synthetic attribution preserved with a bounded excerpt.'), slim_footer([])])
        try:
            status = run_turn(self.store, self.alice, 'budget-thread', 'large-passage',
                'Inspect the synthetic passage without claiming it is exhaustive.', model,
                lambda _: None, model_provider='chatgpt_plan', model_slug='gpt-6.1-sol')
            self.assertEqual(status, 'complete')
            events = self.store.read_turn(self.alice, 'budget-thread', 'large-passage')['events']
            result = next(e['payload']['result'] for e in events if e['kind'] == 'tool_result')
            projected = json.loads(bridge.requests[1]['input'][-1]['output'])
            self.assertEqual(result['content'], original)
            self.assertEqual(projected['content'], result['content'])
            self.assertEqual(projected['author'], result['author'])
            self.assertEqual(projected['approval'], result['approval'])
            self.assertEqual(projected['source_status'], result['source_status'])
            self.assertLessEqual(len(bridge.requests[1]['input'][-1]['output'].encode()), 256 * 1024)
            self.assertLess(len(str(events[-3]['payload']).encode()), MAX_TOOL_RESULT_BYTES)
        finally:
            bridge.close()

    def test_model_shortened_passage_has_contiguous_next_offset_not_silent_gap(self):
        read = execute_read(self.store, self.alice, 'get_reference_passage', {
            'source_id': 'source-danish', 'passage_id': 'passage-danish', 'offset': 0}, set())
        projected, reduced = project('get_reference_passage', read, len(encoded(read)) - 400)
        self.assertTrue(reduced)
        self.assertLess(len(projected['content']), len(read['content']))
        self.assertEqual(projected['next_offset'], len(projected['content']))
        continuation = execute_read(self.store, self.alice, 'get_reference_passage', {
            'source_id': 'source-danish', 'passage_id': 'passage-danish',
            'offset': projected['next_offset']}, set())
        self.assertEqual(projected['content'] + continuation['content'],
                         self.store.db.execute('''
                             SELECT content FROM reference_passages
                             WHERE owner_id='alice' AND source_id='source-danish'
                         ''').fetchone()['content'][:projected['next_offset'] + 4096])
        self.assertEqual(projected['content_sha256'], continuation['content_sha256'])

    def test_four_calculated_reads_above_old_aggregate_allowance_finish_in_native_order(self):
        calls = [native_call(i, 'get_chart', {'chart_id': self.chart_id}) for i in range(1, 5)]
        model, bridge = model_for(*calls, [text('Four calculated reads inspected.'), slim_footer([])])
        try:
            with patch('m2.gateway.execute_read', return_value={
                    'chart_id': self.chart_id, 'content': 'X' * 13_000}):
                status = run_turn(self.store, self.alice, 'budget-thread', 'larger-evidence',
                    'Inspect four distinct synthetic calculated results.', model, lambda _: None,
                    model_provider='chatgpt_plan', model_slug='gpt-6.1-sol')
            self.assertEqual(status, 'complete')
            saved = self.store.read_turn(self.alice, 'budget-thread', 'larger-evidence')['events']
            results = [event['payload'] for event in saved if event['kind'] == 'tool_result']
            self.assertEqual([row['id'] for row in results], [f'call-{i}' for i in range(1, 5)])
            self.assertGreater(sum(row['model_projection_bytes'] for row in results), 32 * 1024)
            self.assertTrue(all(row['model_projection_status'] == 'full' for row in results))
            self.assertEqual([row['call_id'] for row in bridge.requests[-1]['input']
                              if row.get('type') == 'function_call_output'],
                             [f'call-{i}' for i in range(1, 5)])
            self.assertEqual(len(bridge.requests), 5)
        finally:
            bridge.close()

    def test_two_selected_people_and_year_transit_reads_reach_fake_responses_without_old_refusal(self):
        other = People(self.store).add(self.alice, 'Second synthetic reader')
        second = BirthFlow(self.store).generate(self.alice, other['id'], {
            'request_id': 'second-budget-chart', 'birth_date': '1995-02-11',
            'birth_time': '09:00', 'time_unknown': False,
            'birthplace': 'Synthetic Copenhagen reference', 'place_id': None,
            'provisional': True, 'zone_override': 'Europe/Copenhagen',
            'latitude_override': 55.68, 'longitude_override': 12.57,
            'fold': None, 'settings': None})['chart']
        second_id = second['id']
        reads = [
            ('get_chart', {'chart_id': self.chart_id}),
            ('compare_selected_charts', {'chart_a_id': self.chart_id, 'chart_b_id': second_id}),
            ('find_transit_events', {'chart_id': self.chart_id,
                'start_utc': '2024-01-01T00:00:00+00:00',
                'end_utc': '2025-01-01T00:00:00+00:00',
                'transit_body': 'moon', 'natal_body': 'sun', 'aspect': 'square'}),
            ('get_lunar_returns', {'chart_id': self.chart_id,
                'start_utc': '2024-01-01T00:00:00+00:00',
                'end_utc': '2025-01-01T00:00:00+00:00',
                'latitude': 55.68, 'longitude': 12.57}),
            ('get_transit_view', {'date': '2025-01-01', 'time': '12:00',
                'zone': 'Europe/Copenhagen', 'occurrence': 'unspecified',
                'mode': 'natal_transits', 'chart_id': second_id}),
        ]
        model, bridge = model_for(*(native_call(i, name, args) for i, (name, args) in
                                    enumerate(reads, start=1)),
            [text('The two synthetic people have separate chart versions and year-level events.'),
             slim_footer([])])
        try:
            status = run_turn(self.store, self.alice, 'budget-thread', 'year-relationship',
                'Compare both selected charts and a year of transit and lunar-return calculations.',
                model, lambda _: None, model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                selected_people=[{'person_id': self.person_id, 'chart_id': self.chart_id},
                                 {'person_id': other['id'], 'chart_id': second_id}])
            events = self.store.read_turn(self.alice, 'budget-thread', 'year-relationship')['events']
            self.assertEqual(status, 'complete', events[-1]['payload'])
            results = [event['payload'] for event in events if event['kind'] == 'tool_result'
                       and event['payload'].get('id', '').startswith('call-')]
            self.assertEqual([row['id'] for row in results], [f'call-{i}' for i in range(1, 6)])
            self.assertGreater(sum(row['model_projection_bytes'] for row in results), 32 * 1024)
            self.assertTrue(all(row['model_projection_status'] != 'limit' for row in results))
            self.assertGreater(len(results[2]['result']['events']), 20)
            self.assertGreater(len(results[3]['result']['events']), 10)
            self.assertEqual(results[1]['result']['chart_b_id'], second_id)
            self.assertEqual([row['call_id'] for row in bridge.requests[-1]['input']
                              if row.get('type') == 'function_call_output'],
                             [f'call-{i}' for i in range(1, 6)])
            self.assertEqual(len(bridge.requests), 6)
            self.assertEqual(run_turn(self.store, self.alice, 'budget-thread', 'year-relationship',
                'Compare both selected charts and a year of transit and lunar-return calculations.',
                model, lambda _: None, model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                selected_people=[{'person_id': self.person_id, 'chart_id': self.chart_id},
                                 {'person_id': other['id'], 'chart_id': second_id}]), 'complete')
            self.assertEqual(len(bridge.requests), 6)
        finally:
            bridge.close()

    def test_excessive_read_returns_structured_limit_not_success_shaped_evidence(self):
        for size, scope in ((300_000, 'per_call'), (1_100_000, 'archive')):
            with self.subTest(scope=scope):
                model, bridge = model_for(
                    native_call(1, 'get_chart', {'chart_id': self.chart_id}),
                    [text('The requested bounded read is unavailable, not an empty chart.'),
                     slim_footer([])])
                try:
                    with patch('m2.gateway.execute_read', return_value={
                            'chart_id': self.chart_id, 'content': 'X' * size}):
                        status = run_turn(self.store, self.alice, 'budget-thread',
                            f'oversized-{size}', 'Read synthetic excess', model,
                            lambda _: None, model_provider='chatgpt_plan',
                            model_slug='gpt-6.1-sol', selected_people=[])
                    self.assertEqual(status, 'complete')
                    events = self.store.read_turn(self.alice, 'budget-thread', f'oversized-{size}')['events']
                    result = next(e['payload'] for e in events if e['kind'] == 'tool_result')
                    self.assertEqual(result['model_projection_limit']['scope'], scope)
                    self.assertEqual(result['model_projection_status'], 'limit')
                    self.assertGreater(result['model_projection_limit']['used_bytes'],
                                       result['model_projection_limit']['limit_bytes'])
                    provider_result = json.loads(bridge.requests[1]['input'][-1]['output'])
                    self.assertEqual(provider_result['error'], 'bounded_tool_result_unavailable')
                    self.assertFalse(provider_result['complete'])
                    self.assertNotIn('X' * 20, json.dumps(provider_result))
                    if scope == 'archive':
                        self.assertNotIn('X' * 20, json.dumps(result))
                    self.assertEqual(events[-1]['kind'], 'complete')
                    self.assertEqual(len(bridge.requests), 2)
                    self.assertTrue(bridge.requests[1]['tools'])
                    self.assertNotEqual(bridge.requests[1].get('tool_choice'), 'none')
                    self.assertFalse(any(e['kind'] == 'context' and 'read_finalization' in e['payload']
                        for e in events))
                finally:
                    bridge.close()

    def test_exhausted_aggregate_byte_guard_archives_result_and_stops_cleanly(self):
        model, bridge = model_for(*(native_call(i, 'get_chart', {'chart_id': self.chart_id})
                                    for i in range(1, 41)))
        try:
            with patch('m2.gateway.execute_read', return_value={
                    'chart_id': self.chart_id, 'content': 'X' * 15_400}):
                status = run_turn(self.store, self.alice, 'budget-thread', 'byte-ceiling',
                    'Inspect synthetic full results until byte capacity is reached',
                    model, lambda _: None, model_provider='chatgpt_plan',
                    model_slug='gpt-6.1-sol')
            self.assertEqual(status, 'error')
            events = self.store.read_turn(self.alice, 'budget-thread', 'byte-ceiling',
                                          event_limit=100)['events']
            self.assertEqual(events[-1]['payload']['code'], 'tool_round_capacity_exceeded')
            self.assertGreater(events[-1]['payload']['read_count'], 3)
            self.assertEqual(len(bridge.requests), events[-1]['payload']['read_count'])
            final_result = events[-2]['payload']
            self.assertEqual(final_result['model_projection_status'], 'limit')
            self.assertEqual(final_result['model_projection_limit']['scope'], 'model_context')
            self.assertEqual(len(final_result['result']['content']), 15_400)
            self.assertNotIn('complete', [event['kind'] for event in events])
        finally:
            bridge.close()

    def test_upper_bound_source_search_keeps_exact_result_through_backup_restore(self):
        refs = References(self.store)
        source_text = 'Syntheticneedle ' + ('🪐' * 280)
        for index in range(4):
            source_id = f'large-source-{index}'
            refs.add_source(self.alice, source_id, 'A' * 512, 'T' * 512,
                'E' * 512, 'R' * 512, 'M' * 512, 'P' * 512, 'synthetic rights',
                language='da', source_url='https://example.org/' + 'r' * 480)
            refs.add_passage(self.alice, source_id, 'entry', 'section', source_text)
        arguments = {'query': 'Syntheticneedle', 'author': None, 'tradition': None,
                     'technique': None, 'language': 'da'}
        model, bridge = model_for(native_call(1, 'search_references', arguments),
            [text('Four attributed synthetic search results, not exhaustive.'), slim_footer([])])
        try:
            status = run_turn(self.store, self.alice, 'budget-thread', 'source-search',
                'Search attributed sources', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug='gpt-6.1-sol')
            self.assertEqual(status, 'complete')
            event = next(e['payload'] for e in self.store.read_turn(
                self.alice, 'budget-thread', 'source-search')['events'] if e['kind'] == 'tool_result')
            self.assertEqual(len(event['result']['results']), 4)
            self.assertGreater(len(str(event).encode()), MAX_EVENT_BYTES)
            self.assertLess(len(str(event).encode()), MAX_TOOL_RESULT_BYTES)
            self.assertEqual(len(json.loads(bridge.requests[1]['input'][-1]['output'])['results']), 4)
            self.assertEqual(self.store.db.execute('''SELECT count(*) AS n FROM reference_evidence
                WHERE owner_id='alice' AND conversation_id='budget-thread' AND turn_id='source-search'
            ''').fetchone()['n'], 4)

            snapshot = Path(self.directory.name) / 'source-snapshot'
            backup(self.store, snapshot)
            target = 'kat_m2_restored_' + uuid4().hex[:12]
            dsn = make_conninfo(self.admin_dsn, dbname=target)
            with psycopg.connect(self.admin_dsn, autocommit=True) as db:
                db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
            recovered = None
            try:
                recovered = restore(snapshot, dsn, Path(self.directory.name) / 'recovered', self.ledger)
                user = recovered.authenticate('alice', 'synthetic-password-alice')
                saved = next(e['payload'] for e in recovered.read_turn(user,
                    'budget-thread', 'source-search')['events'] if e['kind'] == 'tool_result')
                self.assertEqual(saved['result'], event['result'])
                self.assertEqual(recovered.db.execute('''SELECT count(*) AS n FROM reference_evidence
                    WHERE owner_id='alice' AND conversation_id='budget-thread'
                    AND turn_id='source-search' ''').fetchone()['n'], 4)
            finally:
                if recovered:
                    recovered.close()
                with psycopg.connect(self.admin_dsn, autocommit=True) as db:
                    db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
        finally:
            bridge.close()

    def test_three_multibyte_history_windows_preserve_full_model_projection(self):
        self.create_history_windows()
        script = [native_call(index + 1, 'get_conversation_messages', {
            'conversation_id': 'history-window', 'around_turn_id': f'history-{center}'})
            for index, center in enumerate((1, 4, 7))]
        model, bridge = model_for(*script,
            [text('The third history window was shortened for the model; it is not exhaustive.'),
             slim_footer([])])
        try:
            status = run_turn(self.store, self.alice, 'budget-thread', 'aggregate',
                'Compare three separate current-branch history windows.', model,
                lambda _: None, model_provider='chatgpt_plan', model_slug='gpt-6.1-sol')
            self.assertEqual(status, 'complete')
            results = [e['payload'] for e in self.store.read_turn(
                self.alice, 'budget-thread', 'aggregate')['events'] if e['kind'] == 'tool_result']
            self.assertEqual(len(results), 3)
            self.assertEqual([r['model_projection_status'] for r in results],
                             ['full', 'full', 'full'])
            self.assertEqual(len(results[-1]['result']['turns']), 4)  # five-turn window at chain edge
            projected = json.loads(bridge.requests[-1]['input'][-1]['output'])
            self.assertEqual(len(projected['turns']), 4)
            self.assertFalse(any(row.get('model_text_shortened') for row in projected['turns']))
            self.assertEqual(results[-1]['result']['turns'][0]['text'],
                             projected['turns'][0]['text'])
            self.assertLess(sum(row['model_projection_bytes'] for row in results), 2 * 1024 * 1024)
            self.assertEqual(len(bridge.requests), 4)
        finally:
            bridge.close()

    def test_cumulative_guard_returns_incomplete_result_without_losing_chart(self):
        # Defensive state: two earlier reads already used almost all of this finite
        # operation's evidence allowance. This is not the normal three-read fixture.
        result = execute_read(self.store, self.alice, 'get_chart',
                              {'chart_id': self.chart_id}, {self.chart_id})
        archive, provider_text = prepare('get_chart', 'call-3', result, 3,
            MAX_MODEL_EVIDENCE_BYTES - 600, None, {})
        self.assertEqual(archive['model_projection_limit']['scope'], 'cumulative')
        self.assertEqual(archive['model_projection_limit']['read_count'], 3)
        self.assertEqual(archive['result']['chart_id'], self.chart_id)
        self.assertFalse(json.loads(provider_text)['complete'])
        self.store.begin(self.alice, 'budget-thread', 'budgeted-result', 'Synthetic question')
        self.store.append(self.alice, 'budget-thread', 'budgeted-result', 'tool_result', archive)
        self.assertEqual(self.store.read_turn(self.alice, 'budget-thread',
            'budgeted-result')['events'][-1]['payload']['result'], result)

    def test_cancellation_after_second_durable_read_never_starts_third_request(self):
        model, bridge = model_for(
            native_call(1, 'get_chart', {'chart_id': self.chart_id}),
            native_call(2, 'get_reference_passage', {
                'source_id': 'source-danish', 'passage_id': 'passage-danish'}))
        cancelled = False
        def delivered(event):
            nonlocal cancelled
            if event['kind'] == 'tool_result' and event['payload'].get('id') == 'call-2':
                cancelled = True
        try:
            status = run_turn(self.store, self.alice, 'budget-thread', 'cancelled-reads',
                'Read selected chart and synthetic passage', model, delivered,
                cancelled=lambda: cancelled, model_provider='chatgpt_plan',
                model_slug='gpt-6.1-sol', selected_people=[{
                    'person_id': self.person_id, 'chart_id': self.chart_id}])
            self.assertEqual(status, 'interrupted')
            events = self.store.read_turn(self.alice, 'budget-thread', 'cancelled-reads')['events']
            self.assertEqual([event['payload']['id'] for event in events
                if event['kind'] == 'tool_result' and event['payload'].get('id') in
                ('call-1', 'call-2')], ['call-1', 'call-2'])
            self.assertEqual(events[-1]['kind'], 'interrupted')
            self.assertEqual(len(bridge.requests), 2)
            self.assertEqual(run_turn(self.store, self.alice, 'budget-thread', 'cancelled-reads',
                'Read selected chart and synthetic passage', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug='gpt-6.1-sol', selected_people=[{
                    'person_id': self.person_id, 'chart_id': self.chart_id}]), 'interrupted')
            self.assertEqual(len(bridge.requests), 2)
        finally:
            bridge.close()

    def test_later_round_cancellation_preserves_results_and_skips_next_request(self):
        script = [native_call(i, 'search_conversations', {
            'query': f'synthetic-{i}', 'person_id': None}) for i in range(1, 9)]
        model, bridge = model_for(*script)
        cancelled = False
        def delivered(event):
            nonlocal cancelled
            if event['kind'] == 'tool_result' and event['payload'].get('id') == 'call-8':
                cancelled = True
        try:
            status = run_turn(self.store, self.alice, 'budget-thread', 'cancel-later',
                'Search synthetic conversation', model, delivered,
                cancelled=lambda: cancelled, model_provider='chatgpt_plan',
                model_slug='gpt-6.1-sol')
            self.assertEqual(status, 'interrupted')
            self.assertEqual(len(bridge.requests), 8)
            events = self.store.read_turn(self.alice, 'budget-thread', 'cancel-later')['events']
            self.assertEqual(sum(e['kind'] == 'tool_result' for e in events), 8)
            self.assertEqual(events[-1]['kind'], 'interrupted')
            self.assertEqual(run_turn(self.store, self.alice, 'budget-thread', 'cancel-later',
                'Search synthetic conversation', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug='gpt-6.1-sol'), 'interrupted')
            self.assertEqual(len(bridge.requests), 8)
        finally:
            bridge.close()

    def test_whitespace_only_model_answer_after_reads_is_not_complete(self):
        model, bridge = model_for(native_call(1, 'get_chart', {'chart_id': self.chart_id}),
                                  [text(' '), slim_footer([])])
        try:
            with patch('m2.gateway.execute_read', return_value={
                    'chart_id': self.chart_id, 'content': 'X' * 20_000}):
                status = run_turn(self.store, self.alice, 'budget-thread', 'empty-final',
                    'Read synthetic oversized result', model, lambda _: None,
                    model_provider='chatgpt_plan', model_slug='gpt-6.1-sol')
            self.assertEqual(status, 'error')
            self.assertEqual(len(bridge.requests), 2)
            self.assertTrue(bridge.requests[-1]['tools'])
            events = self.store.read_turn(self.alice, 'budget-thread', 'empty-final')['events']
            self.assertEqual(events[-1]['payload']['code'], 'empty_model_answer')
            self.assertNotIn('complete', [event['kind'] for event in events])
        finally:
            bridge.close()

    def test_status_prefix_cannot_count_as_answer_after_empty_continuation(self):
        model, bridge = model_for(
            [text('Checking the synthetic source.'), *native_call(1, 'search_conversations', {
                'query': 'synthetic', 'person_id': None})],
            [text(' '), slim_footer([])])
        try:
            status = run_turn(self.store, self.alice, 'budget-thread', 'prefix-only',
                'Search the synthetic conversation', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug='gpt-6.1-sol')
            self.assertEqual(status, 'error')
            events = self.store.read_turn(self.alice, 'budget-thread', 'prefix-only')['events']
            self.assertIn('Checking', ''.join(e['payload']['content'] for e in events
                if e['kind'] == 'assistant_chunk'))
            self.assertEqual(events[-1]['payload']['code'], 'empty_model_answer')
            self.assertNotIn('complete', [event['kind'] for event in events])
            self.assertEqual(len(bridge.requests), 2)
        finally:
            bridge.close()

    def test_later_round_archive_fault_does_not_send_next_request(self):
        script = [native_call(i, 'search_conversations', {
            'query': f'synthetic-{i}', 'person_id': None}) for i in range(1, 8)]
        model, bridge = model_for(*script)
        append = self.store.append
        def refuse_seventh_result(session, conversation, turn, kind, payload):
            if kind == 'tool_result' and payload.get('id') == 'call-7':
                raise OSError('synthetic archive write refusal')
            return append(session, conversation, turn, kind, payload)
        try:
            with patch.object(self.store, 'append', side_effect=refuse_seventh_result):
                with self.assertRaisesRegex(OSError, 'synthetic archive write refusal'):
                    run_turn(self.store, self.alice, 'budget-thread', 'archive-refused',
                        'Search synthetic conversation', model, lambda _: None,
                        model_provider='chatgpt_plan', model_slug='gpt-6.1-sol')
            self.assertEqual(len(bridge.requests), 7)
            events = self.store.read_turn(self.alice, 'budget-thread', 'archive-refused')['events']
            self.assertEqual(sum(e['kind'] == 'tool_result' for e in events), 6)
            self.assertEqual(sum(e['kind'] == 'tool_call' for e in events), 7)
            self.assertNotIn('complete', [event['kind'] for event in events])
            self.assertEqual(self.store.recover_open(), 1)
            self.assertEqual(run_turn(self.store, self.alice, 'budget-thread', 'archive-refused',
                'Search synthetic conversation', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug='gpt-6.1-sol'), 'interrupted')
            self.assertEqual(len(bridge.requests), 7)
        finally:
            bridge.close()

    def test_non_tool_events_keep_original_archive_ceiling(self):
        self.store.begin(self.alice, 'budget-thread', 'oversized-chunk', 'Synthetic question')
        with self.assertRaisesRegex(ValueError, 'oversized event'):
            self.store.append(self.alice, 'budget-thread', 'oversized-chunk',
                              'assistant_chunk', {'content': 'X' * (MAX_EVENT_BYTES + 10)})


class AbsentEvidenceTests(DatabaseCase):
    def test_no_approved_source_returns_explicit_absence_and_answer(self):
        self.store.create_conversation(self.alice, 'empty-corpus')
        model, bridge = model_for(native_call(1, 'search_references', {
            'query': 'unseen', 'author': None, 'tradition': None,
            'technique': None, 'language': None}),
            [text('No approved source matches; this does not prove the claim.'), slim_footer([])])
        try:
            self.assertEqual(run_turn(self.store, self.alice, 'empty-corpus', 'read',
                'Look for a cited source', model, lambda _: None,
                model_provider='chatgpt_plan', model_slug='gpt-6.1-sol'), 'complete')
            model_result = json.loads(bridge.requests[1]['input'][-1]['output'])
            self.assertEqual(model_result['results'], [])
            self.assertEqual(model_result['evidence_status'], 'not_found')
            archive = self.store.read_turn(self.alice, 'empty-corpus', 'read')
            self.assertEqual(archive['events'][-1]['kind'], 'complete')
        finally:
            bridge.close()
