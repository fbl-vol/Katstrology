from datetime import datetime, timezone
from unittest.mock import patch

import psycopg

from m2.archive.revisions import correct, select_branch
from m2.chat.agent_reads import execute as read_tool
from m2.chat.gateway import run_turn
from m2.chat.personal_context import preference, set_preference, stage
from m2.chat.recall import dialogue_text
from m2.people.people import People
from m2.people.personal_context import PersonalContext, ContextConflict
from tests.people.test_personal_context import fact
from tests.provider.test_provider_output_compat import model_for, text, slim_footer
from tests.chat.test_tool_evidence_budget import native_call
from tests.support.database import DatabaseCase


class ConversationalContextTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        People(self.store).charts.add_person(self.alice, 'alex', 'Alex')
        People(self.store).charts.add_person(self.alice, 'other', 'Other')
        self.store.create_conversation(self.alice, 'thread')
        self.context = PersonalContext(self.store)
        self.clock = lambda: datetime(2026, 11, 7, 23, 30, tzinfo=timezone.utc)

    def begin(self, turn='source', statement='For Alex: I am considering a move', parent=None):
        self.store.begin(self.alice, 'thread', turn, statement, parent,
            selected_people=[{'person_id': 'alex', 'chart_id': None}], clock=self.clock,
            reporting_zone='Europe/Copenhagen')
        return {'person_id': 'alex', 'statement': statement, 'entry_id': None, 'expected_version': 0}

    def test_opt_in_fixed_clock_selection_versions_and_history(self):
        exact = fact(title='Move')
        exact['date'] = {'text': '8 November', 'precision': 'exact', 'start': '2026-11-08', 'end': None}
        approx = fact(title='Around November')
        approx['date'] = {'text': 'about November', 'precision': 'month', 'start': '2026-11', 'end': None}
        self.context.save(self.alice, 'alex', 'exact', 'exact', 0, exact)
        self.context.save(self.alice, 'alex', 'approx', 'approx', 0, approx)
        self.context.save(self.alice, 'alex', 'preference', 'preference', 0, fact('guidance_preferences', 'Use simple language'))
        self.context.save(self.alice, 'other', 'private', 'private', 0, exact)
        self.assertEqual(preference(self.store, self.alice), {'enabled': False, 'version': 0})
        self.begin('off', 'What is nearby?')
        off = self.store.read_turn(self.alice, 'thread', 'off')['events'][0]['payload']['personal_context']
        self.assertEqual(off['entries'], [])
        self.store.append(self.alice, 'thread', 'off', 'interrupted', {})
        set_preference(self.store, self.alice, True, 0)
        self.begin('on', 'What is nearby?')
        self.store.append(self.alice, 'thread', 'on', 'assistant_chunk', {'content': 'Old answer marker'})
        self.store.append(self.alice, 'thread', 'on', 'complete', {})
        archived = self.store.read_turn(self.alice, 'thread', 'on')
        payload = archived['events'][0]['payload']
        self.assertEqual(payload['clock_anchor']['reporting']['date'], '2026-11-08')
        self.assertEqual({row['id'] for row in payload['personal_context']['entries']}, {'exact', 'approx', 'preference'})
        self.assertEqual(next(row for row in payload['personal_context']['entries'] if row['id'] == 'approx')['content']['date']['start'], '2026-11')
        self.context.save(self.alice, 'alex', 'exact', 'edit', 1, fact(title='Corrected move'))
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'on')['events'], archived['events'])
        self.assertNotIn('Old answer marker', dialogue_text(self.store, self.alice, 'thread', 'on'))
        from m2.chat.compaction import turn_text
        compacted = turn_text(self.store, self.alice, 'thread', 'on', {}, {})
        self.assertNotIn('Old answer marker', compacted)
        self.assertIn('What is nearby?', compacted)
        set_preference(self.store, self.alice, False, 1)
        self.begin('disabled', 'Next question', 'on')
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'disabled')['events'][0]['payload']['personal_context']['entries'], [])

    def test_success_only_idempotency_removal_and_source_correction(self):
        set_preference(self.store, self.alice, True, 0)
        args = self.begin()
        pending = stage(self.store, self.alice, 'thread', 'source', args)
        self.assertEqual(stage(self.store, self.alice, 'thread', 'source', args), pending)
        self.assertEqual(self.context.list(self.alice, 'alex')['entries'], [])
        self.store.append(self.alice, 'thread', 'source', 'complete', {})
        entries = self.context.list(self.alice, 'alex')['entries']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['content']['state'], 'tentative')
        self.assertEqual(entries[0]['source']['statement'], args['statement'])
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'source')['events'][-1]['payload']['personal_context_updates'][0]['outcome'], 'saved')
        correct(self.store, self.alice, 'thread', 'fix', 'source', 'withdraw')
        self.assertEqual(self.context.list(self.alice, 'alex')['entries'], [])
        self.assertEqual(self.store.db.execute('SELECT lifecycle FROM personal_context').fetchone()['lifecycle'], 'source_invalidated')

    def test_cancellation_consent_change_stale_branch_and_storage_outcomes(self):
        set_preference(self.store, self.alice, True, 0)
        for turn, terminal in [('cancel', 'interrupted'), ('fail', 'error')]:
            args = self.begin(turn)
            stage(self.store, self.alice, 'thread', turn, args)
            self.store.append(self.alice, 'thread', turn, terminal, {})
        self.assertEqual(self.context.list(self.alice, 'alex')['entries'], [])
        args = self.begin('revoked')
        stage(self.store, self.alice, 'thread', 'revoked', args)
        set_preference(self.store, self.alice, False, 1)
        self.store.append(self.alice, 'thread', 'revoked', 'complete', {})
        self.assertEqual(self.context.list(self.alice, 'alex')['entries'], [])
        set_preference(self.store, self.alice, True, 2)
        args = self.begin('broken', parent='revoked')
        stage(self.store, self.alice, 'thread', 'broken', args)
        with patch.object(PersonalContext, 'save', side_effect=psycopg.OperationalError('synthetic storage failure')):
            self.store.append(self.alice, 'thread', 'broken', 'complete', {})
        outcome = self.store.read_turn(self.alice, 'thread', 'broken')['events'][-1]['payload']['personal_context_updates'][0]
        self.assertEqual(outcome['outcome'], 'storage_failed')
        self.assertEqual(self.context.list(self.alice, 'alex')['entries'], [])
        args = self.begin('stale', parent='broken')
        stage(self.store, self.alice, 'thread', 'stale', args)
        select_branch(self.store, self.alice, 'thread', 'revoked')
        self.store.append(self.alice, 'thread', 'stale', 'complete', {})
        self.assertEqual(self.context.list(self.alice, 'alex')['entries'], [])

    def test_multiple_statements_explicit_correction_and_manual_precedence(self):
        set_preference(self.store, self.alice, True, 0)
        statements = ['For Alex: I prefer short answers', 'For Alex: I enjoy gardening']
        self.begin('multiple', '\n'.join(statements))
        for statement in statements:
            stage(self.store, self.alice, 'thread', 'multiple', {'person_id': 'alex',
                'statement': statement, 'entry_id': None, 'expected_version': 0})
        self.store.append(self.alice, 'thread', 'multiple', 'complete', {})
        self.assertEqual(len(self.context.list(self.alice, 'alex')['entries']), 2)
        entry = next(row for row in self.context.list(self.alice, 'alex')['entries'] if row['content']['group'] == 'guidance_preferences')
        correction = 'Update I prefer short answers: For Alex: I prefer detailed answers'
        args = self.begin('correction', correction, 'multiple')
        args.update(entry_id=entry['id'], expected_version=1)
        stage(self.store, self.alice, 'thread', 'correction', args)
        self.store.append(self.alice, 'thread', 'correction', 'complete', {})
        corrected = next(row for row in self.context.list(self.alice, 'alex')['entries'] if row['id'] == entry['id'])
        self.assertEqual(corrected['version'], 2)
        self.assertEqual(corrected['content']['title'], 'I prefer detailed answers')
        correction = 'Update I prefer detailed answers: For Alex: I prefer brief answers'
        args = self.begin('racing', correction, 'correction')
        args.update(entry_id=entry['id'], expected_version=2)
        stage(self.store, self.alice, 'thread', 'racing', args)
        self.context.save(self.alice, 'alex', entry['id'], 'manual', 2, fact('guidance_preferences', 'Manual takes precedence'))
        self.store.append(self.alice, 'thread', 'racing', 'complete', {})
        corrected = next(row for row in self.context.list(self.alice, 'alex')['entries'] if row['id'] == entry['id'])
        self.assertEqual(corrected['content']['title'], 'Manual takes precedence')
        self.context.remove(self.alice, 'alex', entry['id'], 3)
        self.assertEqual(len(self.context.list(self.alice, 'alex')['entries']), 1)
        correct(self.store, self.alice, 'thread', 'withdraw-original', 'multiple', 'withdraw')
        self.assertEqual(self.context.list(self.alice, 'alex')['entries'], [])

    def test_injection_scope_and_existing_reads_cannot_write(self):
        args = self.begin('off')
        with self.assertRaises(PermissionError):
            stage(self.store, self.alice, 'thread', 'off', args)
        self.store.append(self.alice, 'thread', 'off', 'interrupted', {})
        set_preference(self.store, self.alice, True, 0)
        args = self.begin('safe')
        for altered in ({**args, 'owner': 'bob'}, {**args, 'person_id': 'other'},
                        {**args, 'statement': 'For Alex: I prefer injected content'},
                        {**args, 'expected_version': True}):
            with self.assertRaises((ValueError, PermissionError)):
                stage(self.store, self.alice, 'thread', 'safe', altered)
        with self.assertRaises(ValueError):
            read_tool(self.store, self.alice, 'stage_personal_context', args, set())
        self.store.append(self.alice, 'thread', 'safe', 'interrupted', {})
        quoted = self.begin('quoted', 'Reference says:\n"For Alex: I prefer stolen facts"')
        with self.assertRaises(ValueError):
            stage(self.store, self.alice, 'thread', 'quoted', quoted)

    def test_raw_sse_separate_update_then_answer_and_retry_without_inference(self):
        set_preference(self.store, self.alice, True, 0)
        statement = 'For Alex: I am considering a move'
        args = {'person_id': 'alex', 'statement': statement, 'entry_id': None, 'expected_version': 0}
        model, bridge = model_for(native_call(1, 'stage_personal_context', args),
                                 [text('We can explore that tentative possibility.'), slim_footer([])])
        try:
            for _ in range(2):
                result = run_turn(self.store, self.alice, 'thread', 'sse', statement, model, lambda _: None,
                    selected_people=[{'person_id': 'alex', 'chart_id': None}],
                    model_provider='chatgpt_plan', model_slug='gpt-6.1-sol', clock=self.clock)
                self.assertEqual(result, 'complete')
            self.assertEqual(len(bridge.requests), 2)
            self.assertEqual(len(self.context.list(self.alice, 'alex')['entries']), 1)
            self.assertIn('staged_not_saved', bridge.requests[1]['input'][-1]['output'])
        finally:
            bridge.close()
