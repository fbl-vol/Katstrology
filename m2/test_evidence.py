"""Retrieval relevance and authority limits on synthetic owned content."""

import psycopg

from m2.charts import Charts
from m2.evidence import LocalEmbedder, personal_context, rebuild_vectors, search_evidence
from m2.recall import rebuild_pending
from m2.references import PersonalContext, References
from m2.test_support import DatabaseCase


class EvidenceTests(DatabaseCase):
    def test_bounded_hybrid_reference_history_and_source_attribution(self):
        refs = References(self.store)
        refs.add_source(self.alice, 'primer', 'Synthetic A', 'Solar note', 'test edition',
                        'western', 'solar', 'synthetic local fixture', 'authored locally')
        refs.add_passage(self.alice, 'primer', 'solar', 'p1',
                         'At the March equinox the Sun crosses the tropical zero Aries point.')
        refs.add_passage(self.alice, 'primer', 'moon', 'p2',
                         'Synthetic note: the Moon changes longitude quickly.')
        self.store.create_conversation(self.alice, 'thread')
        self.store.begin(self.alice, 'thread', 'spoken', 'We discussed an equinox yesterday.')
        self.store.append(self.alice, 'thread', 'spoken', 'assistant_chunk',
                          {'content': 'An equinox does not prove a personal prediction.'})
        self.store.append(self.alice, 'thread', 'spoken', 'complete', {})
        rebuild_pending(self.store, self.alice)

        keyword = search_evidence(self.store, self.alice, 'equinox', limit=3)
        self.assertTrue(any(r['kind'] == 'reference_passage' for r in keyword['results']))
        self.assertTrue(any(r['kind'] == 'conversation' for r in keyword['results']))
        self.assertFalse(keyword['semantic_available'])
        self.assertEqual(keyword['results'][0]['source_kind'], 'source_not_verified_interpretation')
        embedder = LocalEmbedder()  # cached offline ONNX, never sends source text to a provider
        self.assertEqual(rebuild_vectors(self.store, self.alice, embedder)['references_indexed'], 2)
        semantic = search_evidence(self.store, self.alice, 'equinox', embedder, limit=3,
                                   tradition='western', technique='solar')
        self.assertEqual(semantic['results'][0]['passage_id'], 'solar')
        self.assertEqual(semantic['results'][0]['approval'], 'not_kat_selected')
        self.assertTrue(semantic['semantic_available'])
        self.assertEqual(semantic['pending_conversations'], 0)
        Charts(self.store).add_person(self.alice, 'reader', 'Synthetic reader')
        scoped = search_evidence(self.store, self.alice, 'equinox', embedder,
                                 person_id='reader')
        self.assertFalse(scoped['history_excluded_for_person_filter'])
        self.assertTrue(all(row['kind'] == 'reference_passage' for row in scoped['results']))
        with self.assertRaises(KeyError):
            search_evidence(self.store, self.bob, 'equinox', embedder, person_id='reader')
        with self.assertRaises(KeyError):
            refs.get_passage(self.bob, 'primer', 'solar')
        self.assertEqual(search_evidence(self.store, self.bob, 'equinox', embedder)['results'], [])
        self.store.create_conversation(self.bob, 'thread')
        self.store.begin(self.bob, 'thread', 'attempt', 'Synthetic wrong-owner citation')
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.store.append(self.bob, 'thread', 'attempt', 'tool_result', {
                'results': [{'kind': 'reference_passage', 'source_id': 'primer',
                             'passage_id': 'solar'}]})
        self.assertEqual(self.store.read_turn(self.bob, 'thread', 'attempt')['event_count'], 1)

    def test_personal_context_requires_person_active_branch_and_current_source(self):
        charts = Charts(self.store)
        for session in (self.alice, self.bob):
            charts.add_person(session, 'person', 'Synthetic person')
        self.store.create_conversation(self.alice, 'thread')
        self.store.begin(self.alice, 'thread', 'root', 'I prefer observing in the evening.')
        self.store.append(self.alice, 'thread', 'root', 'complete', {})
        notes = PersonalContext(self.store)
        notes.add(self.alice, 'person', 'preference', 'thread', 'root',
                  'I prefer observing in the evening.')
        self.assertEqual(personal_context(self.store, self.alice, 'person')['entries'][0]
                         ['epistemic_status'], 'user_reported')
        self.assertEqual(personal_context(self.store, self.bob, 'person')['entries'], [])
        self.store.begin(self.alice, 'thread', 'confirmation',
                         'confirm: I prefer observing in the evening.', parent_id='root')
        self.store.append(self.alice, 'thread', 'confirmation', 'complete', {})
        notes.add(self.alice, 'person', 'confirmed', 'thread', 'root',
                  'I prefer observing in the evening.', 'explicitly_confirmed',
                  confirmation_turn_id='confirmation')

        from m2.revisions import correct, select_branch
        correct(self.store, self.alice, 'thread', 'confirm-withdrawn', 'confirmation', 'withdraw')
        self.assertEqual([row['id'] for row in personal_context(
            self.store, self.alice, 'person')['entries']], ['preference'])
        correct(self.store, self.alice, 'thread', 'corr', 'root', 'withdraw')
        self.assertEqual(personal_context(self.store, self.alice, 'person')['entries'], [])
        self.assertEqual(self.store.db.execute("SELECT count(*) AS n FROM personal_entries "
                         "WHERE owner_id='alice'").fetchone()['n'], 2)
        select_branch(self.store, self.alice, 'thread', None)
        self.assertEqual(personal_context(self.store, self.alice, 'person')['entries'], [])
