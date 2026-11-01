"""Isolated synthetic corpus revision, withdrawal, rights and evidence lifecycle."""

import json
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.backup import dump_owned, restore_owned
from m2.store import Store
from m2.agent_reads import execute
from m2.evidence import LocalEmbedder, rebuild_vectors, search_evidence
from m2.provenance import current_turn_usable
from m2.recall import rebuild_pending, search
from m2.references import References
from m2.test_support import DatabaseCase


class ReferenceLifecycleTests(DatabaseCase):
    fixture_requires_fresh_migration = True
    def metadata(self, source_id, edition, **options):
        return dict(source_id=source_id, author='Synthetic author',
            title='Original synthetic aspects note', edition=edition,
            tradition='invented_fixture', technique='aspects',
            provenance='locally authored fixture, not a real astrological tradition',
            rights_evidence='synthetic test-only rights record; no external work imported',
            rights_basis='synthetic_fixture', language='en',
            extraction_note='Locally authored digital text; no OCR or omitted pages', **options)

    def test_atomic_original_revision_revocation_and_derived_invalidation(self):
        refs = References(self.store)
        text = ('In this synthetic method, angular crossings represent measured sky geometry. '
                'A metaphor about rivers is interpretation, not a calculated transit.')
        refs.ingest_edition(self.alice, self.metadata('edition-v1', 'v1'), text,
            [{'id': 'a', 'section': 'page 1, angular crossings', 'content': text.split(' A metaphor')[0]}])
        row = refs.get_passage(self.alice, 'edition-v1', 'a')
        self.assertEqual(row['section'], 'page 1, angular crossings')
        original = self.store.db.execute('''
            SELECT original_text,content_sha256 FROM reference_originals
            WHERE owner_id='alice' AND source_id='edition-v1'
        ''').fetchone()
        from hashlib import sha256
        self.assertEqual(original['content_sha256'], sha256(text.encode()).hexdigest())
        self.assertEqual(row['content'], text.split(' A metaphor')[0])
        self.assertEqual(search_evidence(self.store, self.alice, 'crossings', limit=3)
                         ['results'][0]['source_id'], 'edition-v1')
        self.assertEqual(rebuild_vectors(self.store, self.alice, LocalEmbedder())
                         ['references_indexed'], 1)

        self.store.create_conversation(self.alice, 'reader')
        self.store.begin(self.alice, 'reader', 'read-v1', 'What does this crossing mean?')
        self.store.append(self.alice, 'reader', 'read-v1', 'tool_result', {'results': [
            {'kind': 'reference_passage', 'source_id': 'edition-v1', 'passage_id': 'a'}]})
        self.store.append(self.alice, 'reader', 'read-v1', 'assistant_chunk',
                          {'content': 'This old edition used the synthetic crossing metaphor.'})
        self.store.append(self.alice, 'reader', 'read-v1', 'complete', {})
        rebuild_pending(self.store, self.alice)
        self.assertTrue(search(self.store, self.alice, 'metaphor')['results'])

        revision = ('In this synthetic revision, angular crossings are geometry. '
                    'One cannot infer medical or financial outcomes from them.')
        refs.ingest_edition(self.alice, self.metadata('edition-v2', 'v2',
            supersedes_source_id='edition-v1'), revision,
            [{'id': 'a', 'section': 'page 2, revised crossing', 'content': revision}])
        refs.revoke(self.alice, 'edition-v1')
        self.assertFalse(current_turn_usable(self.store, self.alice, 'reader', 'read-v1'))
        self.assertEqual(self.store.db.execute('''
            SELECT count(*) AS value FROM reference_vectors WHERE owner_id='alice'
                AND source_id='edition-v1'
        ''').fetchone()['value'], 0)
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'get_reference_passage',
                    {'source_id': 'edition-v1', 'passage_id': 'a'}, set())
        self.assertEqual([r['source_id'] for r in search_evidence(self.store, self.alice,
                         'crossings', limit=4)['results']], ['edition-v2'])
        rebuild_pending(self.store, self.alice)
        self.assertEqual(search(self.store, self.alice, 'metaphor')['results'], [])
        with self.assertRaises(ValueError):
            self.ledger.delete_reference(self.store, self.alice, 'edition-v1')
        self.ledger.delete_conversation(self.store, self.alice, 'reader')
        self.ledger.delete_reference(self.store, self.alice, 'edition-v2')
        self.ledger.delete_reference(self.store, self.alice, 'edition-v1')
        self.assertEqual(self.store.db.execute('''
            SELECT count(*) AS value FROM reference_originals WHERE owner_id='alice'
        ''').fetchone()['value'], 0)
        self.assertEqual(search_evidence(self.store, self.alice, 'crossings')['results'], [])
        with self.assertRaises(ValueError):
            refs.ingest_edition(self.alice, self.metadata('edition-v1', 'v1'), text,
                [{'id': 'a', 'section': 'page 1', 'content': text}])

    def test_older_backup_cannot_reenable_revoked_source(self):
        refs = References(self.store)
        text = 'Synthetic remembered passage subject to a later revocation.'
        refs.ingest_edition(self.alice, self.metadata('revoked-backup', 'v1'), text,
            [{'id': 'p1', 'section': 'page 1', 'content': text}])
        refs.select(self.alice, 'revoked-backup')
        snapshot = Path(self.directory.name) / 'before-revocation.dump'
        dump_owned(self.dsn, snapshot)
        refs.revoke(self.alice, 'revoked-backup')
        self.assertEqual(search_evidence(self.store, self.alice, 'remembered')['results'], [])
        database = 'kat_m2_restored_' + uuid4().hex[:12]
        restored_dsn = make_conninfo(self.admin_dsn, dbname=database)
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        restored = None
        try:
            restore_owned(restored_dsn, snapshot)
            restored = Store(restored_dsn, Path(self.directory.name) / 'restored-files',
                             self.ledger)
            session = restored.authenticate('alice', 'synthetic-password-alice')
            row = References(restored).get_passage(session, 'revoked-backup', 'p1')
            self.assertEqual(row['approval'], 'revoked')
            self.assertEqual(search_evidence(restored, session, 'remembered')['results'], [])
            with self.assertRaises(PermissionError):
                execute(restored, session, 'get_reference_passage',
                        {'source_id': 'revoked-backup', 'passage_id': 'p1'}, set())
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))

    def test_embedding_failure_keeps_original_and_keyword_retrieval(self):
        refs = References(self.store)
        text = 'Synthetic attributed constellation phrase, not an instruction.'
        refs.ingest_edition(self.alice, self.metadata('embed-source', 'fixture'), text,
            [{'id': 'p1', 'section': 'page 1', 'content': text}])
        class FailedEmbedding:
            def document(self, text):
                raise RuntimeError('synthetic offline model failure')
        with self.assertRaisesRegex(RuntimeError, 'offline model failure'):
            rebuild_vectors(self.store, self.alice, FailedEmbedding())
        self.assertEqual(refs.get_passage(self.alice, 'embed-source', 'p1')['content'], text)
        result = search_evidence(self.store, self.alice, 'constellation', limit=3)
        self.assertEqual(result['results'][0]['source_id'], 'embed-source')
        self.assertFalse(result['semantic_available'])

    def test_invalid_chunk_rolls_back_whole_import_and_unselected_nonfixture_hidden(self):
        refs = References(self.store)
        metadata = self.metadata('candidate', 'synthetic simulated open-license edition')
        metadata['rights_basis'] = 'open_license'  # simulated grant, never a real import
        text = 'Synthetic lunar image only. This is locally authored test material.'
        with self.assertRaisesRegex(ValueError, 'occur exactly'):
            refs.ingest_edition(self.alice, metadata, text, [
                {'id': 'p1', 'section': 's1', 'content': 'Synthetic lunar image only.'},
                {'id': 'bad', 'section': 's2', 'content': 'Invented missing passage'}])
        self.assertEqual(self.store.db.execute('''
            SELECT count(*) AS value FROM reference_sources WHERE id='candidate'
        ''').fetchone()['value'], 0)
        refs.ingest_edition(self.alice, metadata, text,
            [{'id': 'p1', 'section': 's1', 'content': 'Synthetic lunar image only.'}])
        self.assertEqual(search_evidence(self.store, self.alice, 'lunar')['results'], [])
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'get_reference_passage',
                    {'source_id': 'candidate', 'passage_id': 'p1'}, set())
        with self.assertRaises(KeyError):
            refs.select(self.bob, 'candidate')
        refs.select(self.alice, 'candidate')  # simulated choice inside owned fixture only
        self.assertEqual(search_evidence(self.store, self.alice, 'lunar')
                         ['results'][0]['source_id'], 'candidate')
