"""Synthetic model proposals exercise real staging, publication and next-turn reads."""
from unittest.mock import patch

import psycopg

from m2.chat.gateway import run_turn
from m2.chat.personal_context import preference, set_preference, stage
from m2.people.people import People
from m2.people.personal_context import PersonalContext, ContextConflict
from m2.people.self_association import association, set_association
from tests.chat.test_tool_evidence_budget import native_call
from tests.provider.test_provider_output_compat import model_for, text, slim_footer
from tests.support.database import DatabaseCase
from tests.support.self_association import legacy_association


def proposal(prompt, statement, group='past_moments', person_id='casey', assessment='asserted'):
    def span(value):
        start = prompt.index(value)
        return {'start': start, 'end': start + len(value), 'text': value}
    return {'person_id': person_id, 'statement': span(statement), 'identity': span(prompt),
            'context': span(prompt), 'assessment': assessment, 'attribution': 'associated_self',
            'intent': 'add', 'group': group, 'entry_id': None, 'expected_version': 0,
            'correction_cue': '', 'target_phrase': ''}


class NaturalContextTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        for person in ('casey', 'other'):
            People(self.store).charts.add_person(self.alice, person, 'Casey')
        self.store.create_conversation(self.alice, 'natural')
        self.context = PersonalContext(self.store)

    def begin(self, turn, prompt, selected='casey', parent=None):
        self.store.begin(self.alice, 'natural', turn, prompt, parent,
                         selected_people=[{'person_id': selected, 'chart_id': None}])

    def test_explicit_association_does_not_enable_consent_and_checks_owner_versions(self):
        self.assertEqual(association(self.store, self.alice), {'person_id': None, 'version': 0})
        chosen = set_association(self.store, self.alice, 'casey', 0)
        self.assertEqual(chosen, {'person_id': 'casey', 'version': 1})
        self.assertEqual(set_association(self.store, self.alice, 'casey', 0), chosen)
        self.assertFalse(preference(self.store, self.alice)['enabled'])
        with self.assertRaises(ContextConflict):
            set_association(self.store, self.alice, 'other', 0)
        with self.assertRaises(KeyError):
            set_association(self.store, self.bob, 'casey', 0)
        for replacement in ('other', None):
            with self.assertRaises(ContextConflict):
                set_association(self.store, self.alice, replacement, 1)
        self.assertEqual(association(self.store, self.alice), chosen)

    def test_natural_compound_message_through_native_model_publication_and_next_read(self):
        set_association(self.store, self.alice, 'casey', 0)
        set_preference(self.store, self.alice, True, 0)
        statements = [('Got married in May 2020', 'past_moments'),
                      ('joined ExampleWorks as a trainee in July 2021', 'past_moments'),
                      ('became full time around 2022', 'past_moments'),
                      ('I am building a small venture', 'life_now')]
        prompt = ', '.join(value for value, _ in statements) + ', what does my chart suggest?'
        rounds = [native_call(index + 1, 'stage_personal_context', proposal(prompt, value, group))
                  for index, (value, group) in enumerate(statements)]
        model, bridge = model_for(*rounds, [text('We can explore those circumstances.'), slim_footer([])])
        try:
            for _ in range(2):
                self.assertEqual(run_turn(self.store, self.alice, 'natural', 'facts', prompt,
                    model, lambda _: None, selected_people=[{'person_id': 'casey', 'chart_id': None}],
                    model_provider='chatgpt_plan', model_slug='gpt-6.1-sol'), 'complete')
            self.assertEqual(len(bridge.requests), 5)  # ordinary continuations only; retry reads archive
            rows = self.context.list(self.alice, 'casey', group='life')['entries']
            self.assertEqual({row['content']['title'] for row in rows}, {value for value, _ in statements})
            self.assertTrue(all(row['source']['evidence']['context']['text'] == prompt for row in rows))
            self.assertTrue(all(row['content']['date']['precision'] == 'unknown' for row in rows))
            self.assertEqual(self.context.list(self.alice, 'other')['entries'], [])
            terminal = self.store.read_turn(self.alice, 'natural', 'facts')['events'][-1]['payload']
            self.assertEqual([row['outcome'] for row in terminal['personal_context_updates']], ['saved'] * 4)
            self.begin('next', 'Discuss married trainee full time venture', parent='facts')
            snapshot = self.store.read_turn(self.alice, 'natural', 'next')['events'][0]['payload']['personal_context']
            self.assertEqual({row['id'] for row in snapshot['entries']}, {row['id'] for row in rows})
        finally:
            bridge.close()

    def test_identity_change_invalidates_derived_continuity_not_saved_facts_or_originals(self):
        from m2.chat.personal_context import snapshot_current
        from m2.chat.recall import dialogue_text
        set_association(self.store, self.alice, 'casey', 0)
        set_preference(self.store, self.alice, True, 0)
        prompt = 'I joined ExampleWorks.'
        self.begin('original', prompt)
        stage(self.store, self.alice, 'natural', 'original', proposal(prompt, prompt))
        self.store.append(self.alice, 'natural', 'original', 'assistant_chunk', {'content': 'Prior speaker answer marker'})
        self.store.append(self.alice, 'natural', 'original', 'complete', {})
        original = self.store.read_turn(self.alice, 'natural', 'original')['events']
        self.assertTrue(snapshot_current(self.store, self.alice, original[0]['payload']))
        legacy_association(self.store, self.alice, 'other')
        self.assertFalse(snapshot_current(self.store, self.alice, original[0]['payload']))
        self.assertEqual(self.store.read_turn(self.alice, 'natural', 'original')['events'], original)
        self.assertEqual(len(self.context.list(self.alice, 'casey', group='life')['entries']), 1)
        self.assertNotIn('Prior speaker answer marker', dialogue_text(self.store, self.alice, 'natural', 'original'))

    def test_conjunctions_without_punctuation_and_duplicate_selected_names(self):
        set_association(self.store, self.alice, 'casey', 0)
        set_preference(self.store, self.alice, True, 0)
        facts = ['I got married in May 2020', 'joined ExampleWorks in July 2021',
                 'became full time around 2022', 'I am building a small venture']
        prompt = facts[0] + ' and ' + facts[1] + ' then ' + facts[2] + ' and ' + facts[3] + ' how does my chart relate?'
        self.store.begin(self.alice, 'natural', 'connected', prompt,
                         selected_people=[{'person_id': person, 'chart_id': None} for person in ('casey', 'other')])
        for fact in facts:
            stage(self.store, self.alice, 'natural', 'connected', proposal(prompt, fact))
        self.store.append(self.alice, 'natural', 'connected', 'complete', {})
        self.assertEqual({entry['content']['title'] for entry in self.context.list(self.alice, 'casey', group='life')['entries']}, set(facts))
        self.assertEqual(self.context.list(self.alice, 'other', group='life')['entries'], [])

    def test_association_change_or_clear_discards_inflight_stage(self):
        set_association(self.store, self.alice, 'casey', 0)
        set_preference(self.store, self.alice, True, 0)
        for index, replacement in enumerate(('other', None)):
            if index:
                legacy_association(self.store, self.alice, 'casey')
            turn = f'change-{index}'
            prompt = 'I joined ExampleWorks in July 2021.'
            self.begin(turn, prompt)
            stage(self.store, self.alice, 'natural', turn, proposal(prompt, prompt))
            legacy_association(self.store, self.alice, replacement)
            self.store.append(self.alice, 'natural', turn, 'complete', {})
            terminal = self.store.read_turn(self.alice, 'natural', turn)['events'][-1]['payload']
            self.assertEqual(terminal['personal_context_updates'][0]['outcome'], 'discarded')
        self.assertEqual(self.context.list(self.alice, 'casey')['entries'], [])

    def test_changed_authority_before_proposal_and_disabled_consent_reject(self):
        set_association(self.store, self.alice, 'casey', 0)
        prompt = 'I joined ExampleWorks.'
        self.begin('off', prompt)
        with self.assertRaises(PermissionError):
            stage(self.store, self.alice, 'natural', 'off', proposal(prompt, prompt))
        self.store.append(self.alice, 'natural', 'off', 'complete', {})
        set_preference(self.store, self.alice, True, 0)
        self.begin('changed-before-stage', prompt)
        legacy_association(self.store, self.alice, 'other')
        with self.assertRaises(PermissionError):
            stage(self.store, self.alice, 'natural', 'changed-before-stage', proposal(prompt, prompt))
        self.store.append(self.alice, 'natural', 'changed-before-stage', 'complete', {})
        # Deleting an unreferenced associated person clears authority via the
        # owner-scoped foreign key and cannot retarget it to a same-name person.
        self.store.ledger.delete_person(self.store, self.alice, 'other')
        self.assertIsNone(association(self.store, self.alice)['person_id'])

    def test_eligibility_and_semantic_omissions_never_turn_into_writes(self):
        set_association(self.store, self.alice, 'casey', 0)
        set_preference(self.store, self.alice, True, 0)
        cases = [
            ('Reference says: "I joined ExampleWorks."', 'I joined ExampleWorks.', 'asserted'),
            ('I did not join ExampleWorks.', 'join ExampleWorks.', 'asserted'),
            ('If I joined ExampleWorks, what would happen?', 'I joined ExampleWorks', 'asserted'),
            ('I joined ExampleWorks. I take that back.', 'I joined ExampleWorks.', 'non_asserted'),
            ('Casey joined ExampleWorks, but I did not.', 'Casey joined ExampleWorks', 'uncertain'),
            ('Could I join ExampleWorks?', 'Could I join ExampleWorks?', 'non_asserted'),
            ('My chart suggests I must have joined ExampleWorks.', 'My chart suggests I must have joined ExampleWorks.', 'non_asserted'),
        ]
        for index, (prompt, statement, assessment) in enumerate(cases):
            turn = f'omit-{index}'
            self.begin(turn, prompt)
            with self.assertRaises(ValueError):
                stage(self.store, self.alice, 'natural', turn, proposal(prompt, statement, assessment=assessment))
            self.store.append(self.alice, 'natural', turn, 'complete', {})
        self.assertEqual(self.context.list(self.alice, 'casey', group='life')['entries'], [])
        prompt = 'I joined ExampleWorks.'
        self.begin('unselected', prompt, selected='other')
        payload = self.store.read_turn(self.alice, 'natural', 'unselected')['events'][0]['payload']
        self.assertEqual(payload['personal_context']['self_association']['person_id'], None)
        self.assertEqual(payload['personal_context']['self_association']['status'], 'unselected')
        with self.assertRaises(PermissionError):
            stage(self.store, self.alice, 'natural', 'unselected', proposal(prompt, prompt, person_id='other'))
        self.store.append(self.alice, 'natural', 'unselected', 'complete', {})
        legacy_association(self.store, self.alice, None)
        self.begin('unset', prompt)
        with self.assertRaises(PermissionError):
            stage(self.store, self.alice, 'natural', 'unset', proposal(prompt, prompt))
        self.store.append(self.alice, 'natural', 'unset', 'complete', {})

    def test_storage_failure_cancellation_and_consent_revocation_have_no_save(self):
        set_association(self.store, self.alice, 'casey', 0)
        set_preference(self.store, self.alice, True, 0)
        prompt = 'I joined ExampleWorks.'
        for terminal in ('interrupted', 'error', 'complete'):
            self.begin(terminal, prompt)
            stage(self.store, self.alice, 'natural', terminal, proposal(prompt, prompt))
            with patch.object(PersonalContext, 'save', side_effect=psycopg.OperationalError('synthetic failure')):
                self.store.append(self.alice, 'natural', terminal, terminal, {})
            outcome = self.store.read_turn(self.alice, 'natural', terminal)['events'][-1]['payload']['personal_context_updates'][0]
            self.assertEqual(outcome['outcome'], 'storage_failed' if terminal == 'complete' else 'discarded')
        self.begin('revoked', prompt)
        stage(self.store, self.alice, 'natural', 'revoked', proposal(prompt, prompt))
        set_preference(self.store, self.alice, False, 1)
        self.store.append(self.alice, 'natural', 'revoked', 'complete', {})
        self.assertEqual(self.context.list(self.alice, 'casey', group='life')['entries'], [])

    def test_schema31_to32_is_additive_and_does_not_infer_self(self):
        from hashlib import sha256
        from pathlib import Path
        from m2.release_schema import migrate
        self.store.close()
        with psycopg.connect(self.dsn) as db:
            db.execute('''DROP TABLE memory_source_suppressions, memory_source_units,
                memory_budget, memory_work, personal_context_self''')
            db.execute('DELETE FROM schema_migrations WHERE version>=32')
        # Exercise the historical candidate, not a partially rewound current schema.
        import shutil
        directory = Path(self.directory.name) / 'schema32-migrations'
        directory.mkdir()
        for original in (Path(__file__).resolve().parents[2] / 'm2/migrations').glob('*.sql'):
            if int(original.name[:3]) <= 32:
                shutil.copy2(original, directory / original.name)
        path = directory / '032_personal_context_self.sql'
        transition = {'from': 31, 'to': 32, 'migrations': {path.name: sha256(path.read_bytes()).hexdigest()},
                      'added_tables': ['personal_context_self'], 'added_columns': {}}
        self.assertEqual(migrate(self.dsn, transition, directory), {'schema': 32, 'status': 'migrated'})
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM people').fetchone(), (2,))
            self.assertEqual(db.execute('SELECT id FROM conversations').fetchall(), [('natural',)])
            self.assertEqual(db.execute('SELECT count(*) FROM personal_context_self').fetchone(), (0,))
        with self.assertRaisesRegex(ValueError, 'no replay'):
            migrate(self.dsn, transition, directory)

    def test_restoring_older_authority_cannot_resurrect_cleared_self(self):
        set_association(self.store, self.alice, 'casey', 0)
        legacy_association(self.store, self.alice, None)
        self.store.db.execute('UPDATE personal_context_self SET person_id=%s,version=1 WHERE owner_id=%s',
                              ('casey', self.store.owner(self.alice)))
        self.store.ledger.reconcile(self.store)
        self.assertEqual(association(self.store, self.alice), {'person_id': None, 'version': 2})
