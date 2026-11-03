"""Synthetic, independently labelled retrieval risks for an owned book-sized corpus."""

import json
from time import perf_counter

import numpy as np

from m2.evidence import LocalEmbedder, rebuild_vectors, search_evidence
from m2.references import References
from m2.test_support import DatabaseCase


class RagRetrievalTests(DatabaseCase):
    def test_older_interpretive_source_competes_with_newer_keyword_distractors(self):
        refs = References(self.store)
        refs.add_source(self.alice, 'older', 'Synthetic Astronomer', 'Interpretive note',
                        'synthetic edition', 'western', 'mercury', 'synthetic exercise',
                        'synthetic rights')
        refs.add_passage(self.alice, 'older', 'meaning', 'core',
                         'Mercury retrograde interpretation in a natal chart invites review '
                         'of conversations, timing and habitual assumptions.')
        refs.add_source(self.alice, 'newer', 'Synthetic Supplier', 'Product catalog',
                        'synthetic edition', 'western', 'mercury', 'synthetic exercise',
                        'synthetic rights')
        for index in range(617):
            refs.add_passage(self.alice, 'newer', f'catalog-{index:03}', f'item-{index:03}',
                             'Mercury Retrograde Interpretation is a catalog product title '
                             'for stationery labels and invoice processing, not astrology.')

        embedder = LocalEmbedder()
        started = perf_counter()
        total = 0
        while True:
            indexed = rebuild_vectors(self.store, self.alice, embedder, limit=10)
            total += indexed['references_indexed']
            if indexed['references_indexed'] == 0:
                break
        self.assertEqual(total, 618)
        self.assertEqual(self.store.db.execute('''SELECT count(*) AS n FROM reference_vectors
            WHERE owner_id=%s''', ('alice',)).fetchone()['n'], 618)
        index_ms = round((perf_counter() - started) * 1000)
        query = 'Mercury retrograde interpretation'
        started = perf_counter()
        found = search_evidence(self.store, self.alice, query, embedder,
                                limit=8, include_history=False)
        print('RAG_CORPUS_METRICS=' + json.dumps({
            'eligible_passages': 618, 'newer_keyword_distractors': 617,
            'old_source_rank': next((i + 1 for i, row in enumerate(found['results'])
                                     if row['passage_id'] == 'meaning'), None),
            'index_ms': index_ms, 'query_ms': round((perf_counter() - started) * 1000),
            'scan_truncated': found['reference_scan_truncated']}, sort_keys=True), flush=True)
        self.assertIn('meaning', [row['passage_id'] for row in found['results']])
        self.assertFalse(found['semantic_candidates_truncated'])
        self.assertFalse(found['semantic_index_incomplete'])
        self.assertEqual(found['evidence_status'], 'keyword_matches')

    def test_different_passage_tails_have_distinct_durable_vectors(self):
        refs = References(self.store)
        refs.add_source(self.alice, 'tails', 'Synthetic Source', 'Tail distinctions',
                        'synthetic edition', 'western', 'timing', 'synthetic exercise',
                        'synthetic rights')
        prefix = ('Synthetic context describes an open question without choosing a method. ' * 31)
        self.assertGreater(len(prefix), 2048)
        self.assertLess(len(prefix) + 100, 4096)
        refs.add_passage(self.alice, 'tails', 'one', 'section', prefix +
                         'The late qualification requires a verified birth time for this chart.')
        refs.add_passage(self.alice, 'tails', 'two', 'section', prefix +
                         'The late qualification says the birth time is unknown for this chart.')
        self.assertEqual(rebuild_vectors(self.store, self.alice, LocalEmbedder())['references_indexed'], 2)
        rows = self.store.db.execute('''SELECT passage_id,embedding,model_id FROM reference_vectors
            WHERE owner_id=%s ORDER BY passage_id''', ('alice',)).fetchall()
        self.assertNotEqual(rows[0]['embedding'], rows[1]['embedding'])
        self.assertEqual(rows[0]['model_id'], rows[1]['model_id'])

    def test_labelled_english_danish_retrieval_modes(self):
        refs = References(self.store)
        refs.add_source(self.alice, 'parallel', 'Synthetic Author', 'Bilingual notes',
                        'synthetic edition', 'western', 'general', 'synthetic exercise',
                        'synthetic rights')
        passages = {
            'en-season': 'Axial tilt changes the angle of sunlight and makes the seasons.',
            'en-time': 'An unknown birth time cannot establish the exact rising sign or house.',
            'en-return': 'A return window can be described without inventing an exact birth time.',
            'da-season': 'Jordens aksehældning ændrer sollysets vinkel og danner årstider.',
            'da-time': 'Uden et kendt fødselstidspunkt kan man ikke fastslå ascendant eller hus.',
            'da-return': 'Et tidsinterval er mere ærligt end et opdigtet præcist øjeblik.',
            'distractor': 'A stationery catalog lists an axial-tilt pen and retrograde labels.',
        }
        for passage_id, content in passages.items():
            refs.add_passage(self.alice, 'parallel', passage_id, passage_id, content)
        embedder = LocalEmbedder()
        started = perf_counter()
        self.assertEqual(rebuild_vectors(self.store, self.alice, embedder,
                                         limit=10)['references_indexed'], len(passages))
        index_ms = round((perf_counter() - started) * 1000)
        vectors = self.store.db.execute('''SELECT passage_id,embedding FROM reference_vectors
            WHERE owner_id=%s AND source_id=%s''', ('alice', 'parallel')).fetchall()
        cases = (
            ('en-exact', 'axial tilt changes sunlight angle', 'en-season'),
            ('en-paraphrase', 'why do we have different seasons of the year?', 'en-season'),
            ('en-multifactor', 'can an uncertain birth hour establish the rising sign?', 'en-time'),
            ('da-exact', 'kendt fødselstidspunkt ascendant hus', 'da-time'),
            ('da-paraphrase', 'hvorfor skifter solens vinkel hen over året?', 'da-season'),
            ('da-multifactor', 'er et tidsinterval ærligere end et præcist øjeblik?', 'da-return'),
            ('mixed-language', 'if fødselstidspunkt is unknown can a house be certain?', 'da-time'),
            ('no-answer', 'what clinical trial proved a treatment for insomnia?', None),
        )
        hits = {method: {kind: 0 for kind in ('en', 'da', 'mixed-language')}
                for method in ('keyword', 'semantic', 'hybrid')}
        no_answer = {}
        started = perf_counter()
        for case_id, query, expected in cases:
            lexical = search_evidence(self.store, self.alice, query,
                                      include_history=False, limit=7)
            hybrid = search_evidence(self.store, self.alice, query, embedder,
                                     include_history=False, limit=7)
            query_vec = np.array(embedder.query(query))
            semantic = [row['passage_id'] for row in sorted(vectors,
                key=lambda row: float(np.dot(query_vec, np.array(row['embedding']))),
                reverse=True)]
            if expected is None:
                no_answer = {'keyword': lexical['evidence_status'],
                             'hybrid': hybrid['evidence_status']}
                continue
            kind = 'mixed-language' if case_id == 'mixed-language' else case_id[:2]
            for method, ranks in (
                ('keyword', [row['passage_id'] for row in lexical['results'] if row['keyword_match']]),
                ('semantic', semantic),
                ('hybrid', [row['passage_id'] for row in hybrid['results']])):
                hits[method][kind] += expected in ranks[:3]
        query_ms = round((perf_counter() - started) * 1000)
        print('RAG_SYNTHETIC_METRICS=' + json.dumps({
            'eligible_passages': len(passages), 'labelled_answer_queries': 7,
            'top3_hits': hits, 'no_answer_status': no_answer,
            'index_ms': index_ms, 'query_ms': query_ms}, sort_keys=True), flush=True)
        self.assertEqual(no_answer['keyword'], 'not_found')
        self.assertEqual(no_answer['hybrid'], 'semantic_suggestions_only')
        self.assertGreaterEqual(hits['hybrid']['en'], 2)

    def test_danish_questions_against_english_only_synthetic_sources(self):
        refs = References(self.store)
        refs.add_source(self.alice, 'english-only', 'Synthetic Author', 'English-only notes',
                        'synthetic edition', 'western', 'general', 'synthetic exercise',
                        'synthetic rights', language='en')
        passages = {
            'season': 'The tilt of Earth changes the angle of sunlight, causing seasons.',
            'birth-time': 'An unknown birth time cannot establish an exact rising sign or house.',
            'return': 'A return window can be described without inventing a precise birth time.',
            'combined': 'When birth time is unknown, a return window may be discussed '
                        'without claiming an exact rising sign.',
            'pen-catalog': 'The Axial Tilt stationery collection sells colored pens '
                           'and invoices, not astronomical observations.',
            'billing': 'Rising Sign is a bookshop billing schedule with timestamps, '
                       'not a natal chart calculation.',
        }
        for passage_id, content in passages.items():
            refs.add_passage(self.alice, 'english-only', passage_id, passage_id, content)
        cases = (
            ('exact', 'Hvad betyder ukendt fødselstid for ascendanten?', 'birth-time'),
            ('paraphrase', 'Hvorfor skifter vi mellem sommer og vinter?', 'season'),
            ('multi-factor', 'Hvis fødselstidspunktet mangler, kan man beskrive et '
                             'returvindue uden at påstå en præcis ascendant?', 'combined'),
            ('distractor', 'Hvad skaber årstiderne, snarere end navnet på farvepenne?', 'season'),
            ('no-answer', 'Hvilket klinisk forsøg beviser en kur mod søvnløshed?', None),
        )

        embedder = LocalEmbedder()
        self.assertEqual(rebuild_vectors(self.store, self.alice, embedder,
                                         limit=10)['references_indexed'], len(passages))
        vectors = self.store.db.execute('''SELECT p.id AS passage_id,v.embedding,s.language
            FROM reference_passages p JOIN reference_vectors v
              ON (v.owner_id=p.owner_id AND v.source_id=p.source_id AND v.passage_id=p.id)
            JOIN reference_sources s ON (s.owner_id=p.owner_id AND s.id=p.source_id)
            WHERE p.owner_id=%s AND p.source_id=%s''', ('alice', 'english-only')).fetchall()
        self.assertEqual(len(vectors), len(passages))
        self.assertEqual({row['language'] for row in vectors}, {'en'})
        measured = {}
        for label, question, expected in cases:
            keyword = search_evidence(self.store, self.alice, question,
                                      limit=6, include_history=False)
            hybrid = search_evidence(self.store, self.alice, question, embedder,
                                     limit=6, include_history=False)
            query_vector = np.array(embedder.query(question))
            semantic = [row['passage_id'] for row in sorted(vectors,
                key=lambda row: float(np.dot(query_vector, np.array(row['embedding']))),
                reverse=True)]
            ranks = {
                'keyword': [row['passage_id'] for row in keyword['results']
                            if row['keyword_match']],
                'semantic': semantic,
                'hybrid': [row['passage_id'] for row in hybrid['results']],
            }
            measured[label] = {
                'rank': {mode: (items.index(expected) + 1 if expected in items else None)
                         for mode, items in ranks.items()} if expected else None,
                'keyword_status': keyword['evidence_status'],
                'hybrid_status': hybrid['evidence_status'],
            }
            self.assertFalse(hybrid['reference_scan_truncated'])
            self.assertFalse(hybrid['semantic_index_incomplete'])
        print('RAG_DANISH_TO_ENGLISH_SYNTHETIC=' + json.dumps(measured, sort_keys=True),
              flush=True)
        self.assertEqual(measured['no-answer']['keyword_status'], 'not_found')
        self.assertIn(measured['no-answer']['hybrid_status'],
                      ('not_found', 'semantic_suggestions_only'))
